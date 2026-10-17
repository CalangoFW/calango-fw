from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from calango_identity.plugin import IdentityPlugin
from calango_identity.refresh_tokens import InMemoryRefreshTokenStore, RedisRefreshTokenStore
from calango_identity.settings import IdentitySettings
from calango_plugin_base import PluginBase, PluginMigration
from fastapi import FastAPI
from fastapi.testclient import TestClient

from calango import Calango
from tests.conftest import TEST_PRIVATE_KEY, TEST_PUBLIC_KEY


@pytest.fixture
def settings() -> IdentitySettings:
    return IdentitySettings(PRIVATE_KEY=TEST_PRIVATE_KEY, PUBLIC_KEY=TEST_PUBLIC_KEY)


def test_identity_plugin_implements_plugin_base(settings):
    """IdentityPlugin satisfies the PluginBase Protocol."""
    plugin = IdentityPlugin(settings=settings)
    assert isinstance(plugin, PluginBase)


def test_identity_plugin_name(settings):
    """IdentityPlugin.name is 'identity'."""
    plugin = IdentityPlugin(settings=settings)
    assert plugin.name == "identity"


def test_identity_plugin_migrations(settings):
    """IdentityPlugin contributes one typed, wheel-safe migration descriptor."""
    plugin = IdentityPlugin(settings=settings)

    migrations = plugin.migrations()

    assert isinstance(migrations, tuple)
    assert len(migrations) == 1
    descriptor = migrations[0]
    assert isinstance(descriptor, PluginMigration)
    assert descriptor.name == "identity"
    assert descriptor.depends_on == ()
    assert descriptor.versions.name == "versions"


def test_identity_plugin_settings_class(settings):
    """IdentityPlugin.settings() returns the IdentitySettings class."""
    plugin = IdentityPlugin(settings=settings)
    assert plugin.settings() is IdentitySettings


def test_identity_plugin_context_md_contains_identity(settings):
    """IdentityPlugin.context_md() returns a non-empty string mentioning identity."""
    plugin = IdentityPlugin(settings=settings)
    md = plugin.context_md()
    assert "identity" in md.lower()
    assert len(md) > 50


def test_identity_plugin_register_adds_auth_routes(settings):
    """IdentityPlugin.register() adds /auth routes to the app."""
    app = Calango()
    plugin = IdentityPlugin(settings=settings)
    plugin.register(app)

    paths = app.openapi()["paths"]
    assert any(path.startswith("/auth") for path in paths)


def test_identity_plugin_uses_injected_refresh_store_for_session_routes(settings):
    """An injected store backs the login, refresh, and logout routes."""
    refresh_store = InMemoryRefreshTokenStore()
    app = Calango()

    plugin = IdentityPlugin(settings=settings, refresh_store=refresh_store)
    plugin.register(app)

    assert plugin.refresh_store is refresh_store
    paths = app.openapi()["paths"]
    assert {"/auth/login", "/auth/refresh", "/auth/logout"} <= paths.keys()


def test_identity_plugin_builds_redis_store_from_settings(monkeypatch, settings):
    """The production default configures Redis refresh-token persistence."""
    sentinel = object()
    monkeypatch.setattr("calango_identity.plugin.redis.from_url", lambda *args, **kwargs: sentinel)

    plugin = IdentityPlugin(settings=settings)

    assert isinstance(plugin.refresh_store, RedisRefreshTokenStore)
    assert plugin.refresh_store.redis is sentinel


class CloseTrackingRedis:
    def __init__(self) -> None:
        self.close_calls = 0

    async def aclose(self) -> None:
        self.close_calls += 1


class CloseTrackingSyncClient:
    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


class CloseTrackingLimiter:
    def __init__(self, client: CloseTrackingSyncClient) -> None:
        storage = type("Storage", (), {"storage": client})()
        self.limiter = type("Backend", (), {"storage": storage})()

    def limit(self, *_args, **_kwargs):
        def decorator(func):
            return func

        return decorator


def test_plugin_requires_calango_application(settings):
    plugin = IdentityPlugin(settings=settings, refresh_store=InMemoryRefreshTokenStore())

    with pytest.raises(TypeError, match="Calango"):
        plugin.register(FastAPI())


def test_plugin_passes_trusted_proxies_to_limiter(monkeypatch):
    calls = []
    sync_client = CloseTrackingSyncClient()
    limiter = CloseTrackingLimiter(sync_client)

    def tracking_make_limiter(*args):
        calls.append(args)
        return limiter

    monkeypatch.setattr("calango_identity.plugin.make_limiter", tracking_make_limiter)
    settings = IdentitySettings(
        PRIVATE_KEY=TEST_PRIVATE_KEY,
        PUBLIC_KEY=TEST_PUBLIC_KEY,
        REDIS_URL="memory://",
        TRUSTED_PROXIES=("10.0.0.0/8", "192.0.2.8"),
    )

    IdentityPlugin(settings=settings, refresh_store=InMemoryRefreshTokenStore())

    assert calls == [("memory://", ("10.0.0.0/8", "192.0.2.8"))]


def test_plugin_lifespan_closes_owned_async_and_sync_resources_once(
    monkeypatch,
    settings,
):
    async_client = CloseTrackingRedis()
    sync_client = CloseTrackingSyncClient()
    limiter = CloseTrackingLimiter(sync_client)
    user_events = []
    monkeypatch.setattr(
        "calango_identity.plugin.redis.from_url",
        lambda *args, **kwargs: async_client,
    )
    monkeypatch.setattr("calango_identity.plugin.make_limiter", lambda *args: limiter)

    @asynccontextmanager
    async def user_lifespan(_app):
        user_events.append("start")
        yield
        user_events.append("stop")

    app = Calango(lifespan=user_lifespan)
    plugin = IdentityPlugin(settings=settings)
    app.include_plugin(plugin)

    with TestClient(app):
        pass

    assert user_events == ["start", "stop"]
    assert async_client.close_calls == 1
    assert sync_client.close_calls == 1


def test_plugin_does_not_close_injected_resources(settings):
    async_client = CloseTrackingRedis()
    sync_client = CloseTrackingSyncClient()
    limiter = CloseTrackingLimiter(sync_client)
    # This test double intentionally implements only the lifecycle method under test.
    injected_store = RedisRefreshTokenStore(async_client)  # ty: ignore[invalid-argument-type]
    app = Calango()
    plugin = IdentityPlugin(
        settings=settings,
        refresh_store=injected_store,
        limiter=limiter,  # ty: ignore[invalid-argument-type]
    )
    app.include_plugin(plugin)

    with TestClient(app):
        pass

    assert async_client.close_calls == 0
    assert sync_client.close_calls == 0


def test_package_exports_redis_refresh_store_interfaces():
    """Applications can import the stable production refresh-store interfaces."""
    from calango_identity import RedisRefreshTokenStore, RefreshTokenStore

    assert RefreshTokenStore.__name__ == "RefreshTokenStore"
    assert RedisRefreshTokenStore.__name__ == "RedisRefreshTokenStore"


def test_package_exports_current_user_dependency():
    from calango_identity import get_current_user

    assert callable(get_current_user)


def test_include_plugin_works_with_calango():
    """Calango.include_plugin(IdentityPlugin()) integrates end-to-end."""
    from calango import Calango
    from calango.config import CalangoSettings, SecuritySettings

    calango_settings = CalangoSettings(security=SecuritySettings(SECRET_KEY="test-secret"))
    app = Calango(settings=calango_settings)

    identity_settings = IdentitySettings(
        PRIVATE_KEY=TEST_PRIVATE_KEY,
        PUBLIC_KEY=TEST_PUBLIC_KEY,
    )
    plugin = IdentityPlugin(settings=identity_settings)
    app.include_plugin(plugin)

    paths = app.openapi()["paths"]
    assert any(path.startswith("/auth") for path in paths)
