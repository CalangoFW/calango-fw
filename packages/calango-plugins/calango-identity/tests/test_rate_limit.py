from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from calango_identity.models import Base
from calango_identity.plugin import IdentityPlugin
from calango_identity.rate_limit import get_email_key, make_limiter
from calango_identity.refresh_tokens import InMemoryRefreshTokenStore
from calango_identity.settings import IdentitySettings
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from calango import Calango
from tests.conftest import TEST_PRIVATE_KEY, TEST_PUBLIC_KEY


def test_make_limiter_returns_limiter():
    """make_limiter() returns a slowapi Limiter instance."""
    limiter = make_limiter("memory://")
    assert isinstance(limiter, Limiter)


def test_get_email_key_returns_email_from_state():
    """get_email_key returns login_email from request.state when present."""
    # Simulate a request with login_email set on state
    state = type("State", (), {"login_email": " A@B.COM "})()
    request = type("Req", (), {"state": state, "client": type("C", (), {"host": "127.0.0.1"})()})()
    key = get_email_key(request)  # ty: ignore[invalid-argument-type]  # duck-typed Request stub
    assert key == "a@b.com"


def test_get_email_key_falls_back_to_ip():
    """get_email_key falls back to IP address when login_email is not on state."""
    state = type("State", (), {})()  # no login_email
    request = type(
        "Req",
        (),
        {
            "state": state,
            "client": type("C", (), {"host": "1.2.3.4"})(),
            "headers": {},
        },
    )()
    key = get_email_key(request)  # ty: ignore[invalid-argument-type]  # duck-typed Request stub
    # Should return something (IP or similar), not crash
    assert key is not None
    assert isinstance(key, str)


async def test_rate_limit_blocks_after_threshold():
    """Endpoint decorated with limiter blocks requests after the threshold."""
    from slowapi import _rate_limit_exceeded_handler

    limiter = make_limiter("memory://")
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # ty: ignore[invalid-argument-type]

    @app.get("/limited")
    @limiter.limit("2/minute")
    async def limited_endpoint(request: Request):
        return {"ok": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r1 = await client.get("/limited")
        r2 = await client.get("/limited")
        r3 = await client.get("/limited")  # should be blocked

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r3.status_code == 429


@pytest.fixture
async def limited_login_app(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[Calango]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def get_db():
        async with session_factory() as session:
            yield session

    monkeypatch.setattr("calango.core.database.get_db", get_db)
    settings = IdentitySettings(
        PRIVATE_KEY=TEST_PRIVATE_KEY,
        PUBLIC_KEY=TEST_PUBLIC_KEY,
        REDIS_URL="memory://",
        RATE_LIMIT_LOGIN_PER_MINUTE=2,
        RATE_LIMIT_LOGIN_PER_HOUR_PER_EMAIL=2,
    )
    app = Calango()
    app.include_plugin(IdentityPlugin(settings=settings, refresh_store=InMemoryRefreshTokenStore()))

    yield app
    await engine.dispose()


async def _login_attempt(
    app: Calango,
    *,
    client_ip: str,
    email: str,
    password: str = "UniquePasswordMarker!",
):
    transport = ASGITransport(app=app, client=(client_ip, 123))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(
            "/auth/login",
            data={"username": email, "password": password},
        )


async def test_login_enforces_configured_per_ip_limit(limited_login_app):
    responses = [
        await _login_attempt(
            limited_login_app,
            client_ip="192.0.2.10",
            email=f"unknown-{index}@example.com",
        )
        for index in range(3)
    ]

    assert [response.status_code for response in responses] == [401, 401, 429]
    assert all("UniquePasswordMarker!" not in response.text for response in responses)


async def test_login_enforces_configured_limit_per_normalized_email(limited_login_app):
    responses = [
        await _login_attempt(
            limited_login_app,
            client_ip=f"192.0.2.{index}",
            email=email,
        )
        for index, email in enumerate(
            ("TARGET@example.com", "target@EXAMPLE.com", "target@example.com"),
            start=20,
        )
    ]

    assert [response.status_code for response in responses] == [401, 401, 429]
