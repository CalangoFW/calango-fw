from __future__ import annotations

import logging
from types import SimpleNamespace
from uuid import UUID

import pytest
from calango_identity.events import IdentityEvents, LoggingIdentityEvents
from calango_identity.manager import UserManager
from calango_identity.plugin import IdentityPlugin
from calango_identity.refresh_tokens import InMemoryRefreshTokenStore
from calango_identity.settings import IdentitySettings
from fastapi import Request, Response
from fastapi.routing import iter_route_contexts

from calango import Calango
from calango.config import CalangoSettings, SecuritySettings
from tests.conftest import TEST_PRIVATE_KEY, TEST_PUBLIC_KEY

USER_ID = UUID("22222222-2222-2222-2222-222222222222")
EMAIL = "events-user@example.com"
SECRET_TOKEN = "opaque-delivery-token-marker"


class RecordingEvents:
    def __init__(self) -> None:
        self.calls: list[tuple[str, UUID, str | None]] = []

    async def on_registered(self, user, request: Request | None) -> None:
        self.calls.append(("registered", user.id, None))

    async def on_login(self, user, request: Request | None, response: Response | None) -> None:
        self.calls.append(("login", user.id, None))

    async def send_password_reset(self, user, token: str, request: Request | None) -> None:
        self.calls.append(("password_reset", user.id, token))

    async def send_verification(self, user, token: str, request: Request | None) -> None:
        self.calls.append(("verification", user.id, token))


class FailingEvents:
    async def _fail(self, *args: object) -> None:
        raise RuntimeError(f"provider rejected {EMAIL} with {SECRET_TOKEN}")

    on_registered = _fail
    on_login = _fail
    send_password_reset = _fail
    send_verification = _fail


def _settings() -> IdentitySettings:
    return IdentitySettings(
        PRIVATE_KEY=TEST_PRIVATE_KEY,
        PUBLIC_KEY=TEST_PUBLIC_KEY,
        REDIS_URL="memory://",
    )


def _user() -> SimpleNamespace:
    return SimpleNamespace(id=USER_ID, email=EMAIL)


def _manager(events: object | None) -> UserManager:
    # The manager forwards hooks without touching the user database.
    return UserManager(None, _settings(), events)  # ty: ignore[invalid-argument-type]


def test_events_implementations_satisfy_protocol():
    assert isinstance(LoggingIdentityEvents(), IdentityEvents)
    assert isinstance(RecordingEvents(), IdentityEvents)


async def test_manager_forwards_every_account_event_to_the_provider():
    events = RecordingEvents()
    manager = _manager(events)
    user = _user()

    await manager.on_after_register(user)  # ty: ignore[invalid-argument-type]
    await manager.on_after_login(user)  # ty: ignore[invalid-argument-type]
    await manager.on_after_forgot_password(user, "reset-token")  # ty: ignore[invalid-argument-type]
    await manager.on_after_request_verify(user, "verify-token")  # ty: ignore[invalid-argument-type]

    assert events.calls == [
        ("registered", USER_ID, None),
        ("login", USER_ID, None),
        ("password_reset", USER_ID, "reset-token"),
        ("verification", USER_ID, "verify-token"),
    ]


async def test_manager_without_provider_ignores_account_events():
    manager = _manager(None)

    await manager.on_after_forgot_password(_user(), "reset-token")  # ty: ignore[invalid-argument-type]


async def test_provider_failure_never_escapes_and_logs_only_the_error_type(caplog):
    caplog.set_level(logging.DEBUG)
    manager = _manager(FailingEvents())
    user = _user()

    await manager.on_after_register(user)  # ty: ignore[invalid-argument-type]
    await manager.on_after_login(user)  # ty: ignore[invalid-argument-type]
    await manager.on_after_forgot_password(user, SECRET_TOKEN)  # ty: ignore[invalid-argument-type]
    await manager.on_after_request_verify(user, SECRET_TOKEN)  # ty: ignore[invalid-argument-type]

    failures = [record for record in caplog.records if record.name == "calango_identity.manager"]
    assert [record.error_type for record in failures] == ["RuntimeError"] * 4
    assert all(record.exc_info is None for record in failures)
    assert EMAIL not in caplog.text
    assert SECRET_TOKEN not in caplog.text


async def test_logging_events_record_event_and_user_id_only(caplog):
    caplog.set_level(logging.INFO, logger="calango_identity.events")
    events = LoggingIdentityEvents()
    user = _user()

    await events.on_registered(user, None)  # ty: ignore[invalid-argument-type]
    await events.on_login(user, None, None)  # ty: ignore[invalid-argument-type]
    await events.send_password_reset(user, SECRET_TOKEN, None)  # ty: ignore[invalid-argument-type]
    await events.send_verification(user, SECRET_TOKEN, None)  # ty: ignore[invalid-argument-type]

    messages = [record.getMessage() for record in caplog.records]
    assert len(messages) == 4
    assert all(str(USER_ID) in message for message in messages)
    assert EMAIL not in caplog.text
    assert SECRET_TOKEN not in caplog.text


def _route_paths(app: Calango) -> set[str | None]:
    return {context.path for context in iter_route_contexts(app.routes)}


def _app(env: str) -> Calango:
    settings = CalangoSettings(
        ENV=env,  # ty: ignore[invalid-argument-type]
        security=SecuritySettings(SECRET_KEY="test-secret"),
    )
    return Calango(settings=settings)


@pytest.mark.parametrize(
    ("enable_password_reset", "enable_verification"),
    [pytest.param(True, False, id="password-reset"), pytest.param(False, True, id="verification")],
)
def test_production_rejects_delivery_endpoints_without_a_provider(
    enable_password_reset: bool,
    enable_verification: bool,
):
    plugin = IdentityPlugin(
        settings=_settings(),
        refresh_store=InMemoryRefreshTokenStore(),
        enable_password_reset=enable_password_reset,
        enable_verification=enable_verification,
    )

    with pytest.raises(RuntimeError, match="IdentityEvents"):
        _app("production").include_plugin(plugin)


def test_production_rejects_development_logging_provider():
    plugin = IdentityPlugin(
        settings=_settings(),
        refresh_store=InMemoryRefreshTokenStore(),
        events=LoggingIdentityEvents(),
    )

    with pytest.raises(RuntimeError, match="development-only"):
        _app("production").include_plugin(plugin)


def test_production_accepts_delivery_endpoints_with_a_provider():
    app = _app("production")
    app.include_plugin(
        IdentityPlugin(
            settings=_settings(),
            refresh_store=InMemoryRefreshTokenStore(),
            events=RecordingEvents(),
            enable_password_reset=True,
            enable_verification=True,
        )
    )

    paths = _route_paths(app)
    assert {"/auth/forgot-password", "/auth/request-verify-token"} <= paths


def test_delivery_endpoints_are_disabled_by_default():
    app = _app("development")
    app.include_plugin(
        IdentityPlugin(settings=_settings(), refresh_store=InMemoryRefreshTokenStore())
    )

    paths = _route_paths(app)
    assert "/auth/forgot-password" not in paths
    assert "/auth/request-verify-token" not in paths
