from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from calango_identity.manager import UserManager
from calango_identity.models import Base
from calango_identity.rate_limit import make_limiter
from calango_identity.refresh_tokens import (
    InMemoryRefreshTokenStore,
    RefreshTokenPair,
    RefreshTokenStorageError,
)
from calango_identity.router import _parse_refresh_token, make_auth_router
from calango_identity.settings import IdentitySettings
from httpx import ASGITransport, AsyncClient, Response
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.requests import Request as StarletteRequest

from calango import Calango
from calango.exceptions import AuthenticationError
from tests.conftest import TEST_PRIVATE_KEY, TEST_PUBLIC_KEY


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.fixture
def settings():
    return IdentitySettings(PRIVATE_KEY=TEST_PRIVATE_KEY, PUBLIC_KEY=TEST_PUBLIC_KEY)


@pytest.fixture
def clock():
    return [datetime(2026, 8, 20, tzinfo=UTC)]


@pytest.fixture
def refresh_store(clock: list[datetime]):
    return InMemoryRefreshTokenStore(now=lambda: clock[0])


@pytest.fixture
def limiter() -> Limiter:
    return make_limiter("memory://")


class DeliveryRecorder:
    """Identity events provider that records delivered tokens by user id."""

    def __init__(self) -> None:
        self.password_resets: list[tuple[str, str]] = []
        self.verifications: list[tuple[str, str]] = []

    async def on_registered(self, user, request) -> None:
        pass

    async def on_login(self, user, request, response) -> None:
        pass

    async def send_password_reset(self, user, token: str, request) -> None:
        self.password_resets.append((str(user.id), token))

    async def send_verification(self, user, token: str, request) -> None:
        self.verifications.append((str(user.id), token))


class FailingDelivery(DeliveryRecorder):
    async def send_password_reset(self, user, token: str, request) -> None:
        raise RuntimeError("provider outage")


@pytest.fixture
def delivered() -> DeliveryRecorder:
    return DeliveryRecorder()


@asynccontextmanager
async def _serve_auth_router(session: AsyncSession, **router_options):
    app = Calango()
    app.state.limiter = router_options["limiter"]

    # Pass a dependency that yields the test session
    async def get_db():
        yield session

    app.include_router(
        make_auth_router(
            get_db=get_db,
            enable_password_reset=True,
            enable_verification=True,
            **router_options,
        )
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def client(
    session: AsyncSession,
    settings: IdentitySettings,
    refresh_store: InMemoryRefreshTokenStore,
    limiter: Limiter,
    delivered: DeliveryRecorder,
):
    async with _serve_auth_router(
        session,
        settings=settings,
        refresh_store=refresh_store,
        limiter=limiter,
        events=delivered,
    ) as ac:
        yield ac


@pytest.fixture
async def failing_delivery_client(
    session: AsyncSession,
    settings: IdentitySettings,
    refresh_store: InMemoryRefreshTokenStore,
    limiter: Limiter,
):
    async with _serve_auth_router(
        session,
        settings=settings,
        refresh_store=refresh_store,
        limiter=limiter,
        events=FailingDelivery(),
    ) as ac:
        yield ac


class UnavailableRefreshTokenStore:
    async def issue(self, user_id: UUID) -> RefreshTokenPair:
        raise RefreshTokenStorageError("sensitive storage diagnostics")

    async def rotate(self, token: str) -> RefreshTokenPair:
        raise RefreshTokenStorageError("sensitive storage diagnostics")

    async def revoke(self, token: str) -> None:
        raise RefreshTokenStorageError("sensitive storage diagnostics")


@pytest.fixture
async def unavailable_client(
    session: AsyncSession,
    settings: IdentitySettings,
    limiter: Limiter,
):
    app = Calango()
    app.state.limiter = limiter

    async def get_db():
        yield session

    router = make_auth_router(
        settings=settings,
        get_db=get_db,
        refresh_store=UnavailableRefreshTokenStore(),
        limiter=limiter,
    )
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


DEAD_REDIS_HOST = "127.0.0.1:1"


@pytest.fixture(
    params=[
        pytest.param(({}, "ConnectionError"), id="redis-error"),
        pytest.param(({"wrap_exceptions": True}, "StorageError"), id="wrapped-storage-error"),
    ]
)
async def dead_limiter_client(
    request: pytest.FixtureRequest,
    session: AsyncSession,
    settings: IdentitySettings,
    refresh_store: InMemoryRefreshTokenStore,
):
    """Auth app whose rate-limit storage points at a port nothing listens on."""
    storage_options, error_type = request.param
    limiter = Limiter(
        key_func=get_remote_address,
        storage_uri=f"redis://{DEAD_REDIS_HOST}/0",
        storage_options=storage_options,
    )
    app = Calango()
    app.state.limiter = limiter

    async def get_db():
        yield session

    router = make_auth_router(
        settings=settings,
        get_db=get_db,
        refresh_store=refresh_store,
        limiter=limiter,
    )
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac, error_type


async def register_user(client: AsyncClient, email: str) -> None:
    response = await client.post(
        "/auth/register",
        json={"email": email, "password": "SecurePassword123!"},
    )
    assert response.status_code == 201


async def login_user(client: AsyncClient, email: str) -> dict:
    await register_user(client, email)
    response = await client.post(
        "/auth/login",
        data={"username": email, "password": "SecurePassword123!"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def assert_invalid_refresh_response(response: Response) -> None:
    assert response.status_code == 401, response.text
    assert response.json()["error"] == "authentication_error"
    assert response.json()["message"] == "Invalid refresh token"


INVALID_REFRESH_REQUESTS = [
    pytest.param({"json": {}}, id="absent"),
    pytest.param(
        {"content": b"{", "headers": {"content-type": "application/json"}},
        id="malformed-json",
    ),
    pytest.param({"json": {"refresh_token": "short"}}, id="short"),
    pytest.param({"json": {"refresh_token": "x" * 513}}, id="oversized"),
    pytest.param({"json": {"refresh_token": ["not", "a", "string"]}}, id="incompatible"),
]


async def test_register_returns_201(client):
    """POST /auth/register with valid data returns 201."""
    response = await client.post(
        "/auth/register",
        json={
            "email": "user@example.com",
            "password": "SecurePassword123!",
        },
    )
    assert response.status_code == 201
    assert response.json()["email"] == "user@example.com"


async def test_register_duplicate_email_returns_400(client):
    """POST /auth/register with existing email returns 400."""
    data = {"email": "dup@example.com", "password": "SecurePassword123!"}
    await client.post("/auth/register", json=data)
    response = await client.post("/auth/register", json=data)
    assert response.status_code == 400


async def test_login_returns_access_and_refresh_tokens(client):
    await register_user(client, "login@example.com")
    response = await client.post(
        "/auth/login",
        data={"username": "login@example.com", "password": "SecurePassword123!"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["token_type"] == "bearer"
    assert response.json()["expires_in"] == 900
    assert response.json()["access_token"]
    assert response.json()["refresh_token"]


async def test_login_wrong_password_returns_401(client):
    """POST /auth/login with wrong password returns a uniform auth error."""
    await register_user(client, "wrong@example.com")
    response = await client.post(
        "/auth/login",
        data={"username": "wrong@example.com", "password": "WrongPassword!"},
    )
    assert response.status_code == 401
    assert response.json()["error"] == "authentication_error"


async def test_login_preserves_user_manager_after_login_hook(client, monkeypatch):
    calls = []

    async def on_after_login(self, user, request=None, response=None):
        calls.append((user.email, request, response))

    monkeypatch.setattr(UserManager, "on_after_login", on_after_login)
    await register_user(client, "hook@example.com")

    response = await client.post(
        "/auth/login",
        data={"username": "hook@example.com", "password": "SecurePassword123!"},
    )

    assert response.status_code == 200
    assert len(calls) == 1
    assert calls[0][0] == "hook@example.com"
    assert calls[0][1] is not None
    assert calls[0][2] is not None


async def test_generated_jwt_login_is_not_registered(client):
    response = await client.post(
        "/auth/jwt/login",
        data={"username": "user@example.com", "password": "SecurePassword123!"},
    )
    assert response.status_code == 404


async def test_refresh_endpoints_document_refresh_token_schema(
    session: AsyncSession,
    settings: IdentitySettings,
    refresh_store: InMemoryRefreshTokenStore,
    limiter: Limiter,
):
    app = Calango()
    app.state.limiter = limiter

    async def get_db():
        yield session

    app.include_router(
        make_auth_router(
            settings=settings,
            get_db=get_db,
            refresh_store=refresh_store,
            limiter=limiter,
        )
    )
    schema = app.openapi()

    for path in ("/auth/refresh", "/auth/logout"):
        request_body = schema["paths"][path]["post"]["requestBody"]
        token_schema = request_body["content"]["application/json"]["schema"]
        assert request_body["required"] is True
        assert token_schema["properties"]["refresh_token"]["minLength"] == 43
        assert token_schema["properties"]["refresh_token"]["maxLength"] == 512


async def test_refresh_rotates_both_tokens(client):
    login = await login_user(client, "refresh@example.com")
    response = await client.post(
        "/auth/refresh",
        json={"refresh_token": login["refresh_token"]},
    )
    assert response.status_code == 200
    assert response.json()["refresh_token"] != login["refresh_token"]
    assert response.json()["access_token"]


async def test_refresh_reuse_returns_uniform_401_and_revokes_family(client):
    login = await login_user(client, "reuse@example.com")
    rotated = await client.post("/auth/refresh", json={"refresh_token": login["refresh_token"]})
    reused = await client.post("/auth/refresh", json={"refresh_token": login["refresh_token"]})
    family = await client.post(
        "/auth/refresh", json={"refresh_token": rotated.json()["refresh_token"]}
    )
    assert reused.status_code == family.status_code == 401
    assert reused.json()["error"] == family.json()["error"] == "authentication_error"
    assert reused.json()["message"] == family.json()["message"] == "Invalid refresh token"


@pytest.mark.parametrize("request_kwargs", INVALID_REFRESH_REQUESTS)
async def test_refresh_malformed_tokens_return_uniform_401(client, request_kwargs):
    response = await client.post("/auth/refresh", **request_kwargs)
    assert_invalid_refresh_response(response)


async def test_refresh_unknown_token_returns_uniform_401(client):
    response = await client.post("/auth/refresh", json={"refresh_token": "x" * 43})
    assert_invalid_refresh_response(response)


async def test_refresh_validation_does_not_retain_submitted_token_in_exception_chain():
    marker = "submitted-refresh-token-unique-marker"
    body = json.dumps({"refresh_token": {"value": marker}}).encode()

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    request = StarletteRequest(
        {
            "type": "http",
            "method": "POST",
            "path": "/auth/refresh",
            "headers": [(b"content-type", b"application/json")],
        },
        receive,
    )

    with pytest.raises(AuthenticationError) as error:
        await _parse_refresh_token(request)

    assert marker not in str(error.value)
    assert marker not in repr(error.value)
    assert error.value.__cause__ is None
    assert error.value.__context__ is None


async def test_refresh_validation_does_not_return_submitted_token(client):
    marker = "submitted-refresh-token-response-marker"

    response = await client.post(
        "/auth/refresh",
        json={"refresh_token": {"value": marker}},
    )

    assert_invalid_refresh_response(response)
    assert marker not in response.text


async def test_refresh_expired_token_returns_uniform_401(client, clock: list[datetime]):
    login = await login_user(client, "expired@example.com")
    clock[0] += timedelta(days=8)

    response = await client.post(
        "/auth/refresh",
        json={"refresh_token": login["refresh_token"]},
    )

    assert_invalid_refresh_response(response)


async def test_refresh_revoked_token_returns_uniform_401(client):
    login = await login_user(client, "revoked@example.com")
    body = {"refresh_token": login["refresh_token"]}
    assert (await client.post("/auth/logout", json=body)).status_code == 204

    response = await client.post("/auth/refresh", json=body)

    assert_invalid_refresh_response(response)


async def test_logout_is_idempotent(client):
    login = await login_user(client, "logout@example.com")
    body = {"refresh_token": login["refresh_token"]}
    assert (await client.post("/auth/logout", json=body)).status_code == 204
    assert (await client.post("/auth/logout", json=body)).status_code == 204


@pytest.mark.parametrize(
    "request_kwargs",
    [*INVALID_REFRESH_REQUESTS, pytest.param({"json": {"refresh_token": "x" * 43}}, id="unknown")],
)
async def test_logout_invalid_tokens_return_uniform_401(client, request_kwargs):
    response = await client.post("/auth/logout", **request_kwargs)
    assert_invalid_refresh_response(response)


async def test_login_returns_uniform_503_when_refresh_store_is_unavailable(unavailable_client):
    await register_user(unavailable_client, "unavailable-login@example.com")
    response = await unavailable_client.post(
        "/auth/login",
        data={
            "username": "unavailable-login@example.com",
            "password": "SecurePassword123!",
        },
    )
    assert response.status_code == 503, response.text
    assert response.json()["error"] == "service_unavailable"
    assert response.json()["message"] == "Authentication service unavailable"


async def test_refresh_returns_uniform_503_when_store_is_unavailable(unavailable_client):
    response = await unavailable_client.post(
        "/auth/refresh",
        json={"refresh_token": "x" * 43},
    )
    assert response.status_code == 503
    assert response.json()["error"] == "service_unavailable"
    assert response.json()["message"] == "Authentication service unavailable"


async def test_logout_returns_uniform_503_when_store_is_unavailable(unavailable_client):
    response = await unavailable_client.post(
        "/auth/logout",
        json={"refresh_token": "x" * 43},
    )
    assert response.status_code == 503
    assert response.json()["error"] == "service_unavailable"
    assert response.json()["message"] == "Authentication service unavailable"


async def test_rate_limit_storage_outage_returns_uniform_503_to_login(dead_limiter_client):
    client, _ = dead_limiter_client
    response = await client.post(
        "/auth/login",
        data={"username": "limiter-outage@example.com", "password": "SecurePassword123!"},
    )
    assert response.status_code == 503, response.text
    assert response.json()["error"] == "service_unavailable"
    assert response.json()["message"] == "Authentication service unavailable"
    assert DEAD_REDIS_HOST not in response.text


async def test_rate_limit_storage_outage_is_logged_without_credentials(dead_limiter_client, caplog):
    client, error_type = dead_limiter_client
    caplog.set_level(logging.ERROR, logger="calango_identity.router")
    await client.post(
        "/auth/login",
        data={"username": "logged-outage@example.com", "password": "SecretPassword123!"},
    )

    records = [record for record in caplog.records if record.name == "calango_identity.router"]
    assert len(records) == 1
    assert records[0].error_type == error_type
    assert records[0].exc_info is None
    message = records[0].getMessage()
    for secret in ("logged-outage@example.com", "SecretPassword123!", DEAD_REDIS_HOST):
        assert secret not in message


async def test_refresh_store_outage_is_logged_without_diagnostics(unavailable_client, caplog):
    caplog.set_level(logging.ERROR, logger="calango_identity.router")
    await unavailable_client.post("/auth/refresh", json={"refresh_token": "x" * 43})

    records = [record for record in caplog.records if record.name == "calango_identity.router"]
    assert len(records) == 1
    assert records[0].error_type == "RefreshTokenStorageError"
    assert "sensitive storage diagnostics" not in records[0].getMessage()


async def test_login_response_is_not_cacheable(client):
    await register_user(client, "no-store-login@example.com")
    response = await client.post(
        "/auth/login",
        data={"username": "no-store-login@example.com", "password": "SecurePassword123!"},
    )
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"


async def test_refresh_response_is_not_cacheable(client):
    login = await login_user(client, "no-store-refresh@example.com")
    response = await client.post("/auth/refresh", json={"refresh_token": login["refresh_token"]})
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"


async def test_forgot_password_delivers_reset_token_to_provider(client, delivered):
    registered = await client.post(
        "/auth/register",
        json={"email": "reset@example.com", "password": "SecurePassword123!"},
    )
    response = await client.post("/auth/forgot-password", json={"email": "reset@example.com"})

    assert response.status_code == 202
    assert [(user_id, bool(token)) for user_id, token in delivered.password_resets] == [
        (registered.json()["id"], True)
    ]


async def test_forgot_password_provider_failure_matches_unknown_email(failing_delivery_client):
    await register_user(failing_delivery_client, "known@example.com")
    known = await failing_delivery_client.post(
        "/auth/forgot-password", json={"email": "known@example.com"}
    )
    unknown = await failing_delivery_client.post(
        "/auth/forgot-password", json={"email": "missing@example.com"}
    )

    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()


async def test_request_verify_token_delivers_verification_token(client, delivered):
    registered = await client.post(
        "/auth/register",
        json={"email": "verify@example.com", "password": "SecurePassword123!"},
    )
    response = await client.post("/auth/request-verify-token", json={"email": "verify@example.com"})

    assert response.status_code == 202
    assert [(user_id, bool(token)) for user_id, token in delivered.verifications] == [
        (registered.json()["id"], True)
    ]


async def test_forgot_password_returns_202(client):
    """POST /auth/forgot-password returns 202 (always, even for nonexistent email)."""
    response = await client.post("/auth/forgot-password", json={"email": "nonexistent@example.com"})
    assert response.status_code == 202
