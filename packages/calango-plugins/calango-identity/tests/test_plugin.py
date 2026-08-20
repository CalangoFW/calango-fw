from __future__ import annotations

import pytest
from calango_identity.plugin import IdentityPlugin
from calango_identity.refresh_tokens import InMemoryRefreshTokenStore, RedisRefreshTokenStore
from calango_identity.settings import IdentitySettings
from calango_plugin_base import PluginBase
from fastapi import FastAPI

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
    """IdentityPlugin.migrations() returns a non-empty list."""
    plugin = IdentityPlugin(settings=settings)
    assert len(plugin.migrations()) > 0


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
    app = FastAPI()
    plugin = IdentityPlugin(settings=settings)
    plugin.register(app)

    paths = app.openapi()["paths"]
    assert any(path.startswith("/auth") for path in paths)


def test_identity_plugin_uses_injected_refresh_store_for_session_routes(settings):
    """An injected store backs the login, refresh, and logout routes."""
    refresh_store = InMemoryRefreshTokenStore()
    app = FastAPI()

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
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


async def test_plugin_closes_plugin_owned_redis_client(monkeypatch, settings):
    client = CloseTrackingRedis()
    monkeypatch.setattr("calango_identity.plugin.redis.from_url", lambda *args, **kwargs: client)
    app = FastAPI()
    plugin = IdentityPlugin(settings=settings)
    plugin.register(app)

    async with app.router.lifespan_context(app):
        pass

    assert client.closed is True


async def test_plugin_does_not_close_injected_redis_store_client(settings):
    client = CloseTrackingRedis()
    # This test double intentionally implements only the lifecycle method under test.
    injected_store = RedisRefreshTokenStore(client)  # ty: ignore[invalid-argument-type]
    app = FastAPI()
    plugin = IdentityPlugin(settings=settings, refresh_store=injected_store)
    plugin.register(app)

    async with app.router.lifespan_context(app):
        pass

    assert client.closed is False


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
