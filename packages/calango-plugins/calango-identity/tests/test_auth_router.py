from __future__ import annotations

import pytest
from calango_identity.models import Base
from calango_identity.router import make_auth_router
from calango_identity.settings import IdentitySettings
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

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
async def client(session: AsyncSession, settings: IdentitySettings):
    app = FastAPI()

    # Pass a dependency that yields the test session
    async def get_db():
        yield session

    router = make_auth_router(settings=settings, get_db=get_db)
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


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


async def test_login_returns_token(client):
    """POST /auth/jwt/login with valid credentials returns access_token."""
    await client.post(
        "/auth/register",
        json={
            "email": "login@example.com",
            "password": "SecurePassword123!",
        },
    )
    response = await client.post(
        "/auth/jwt/login",
        data={
            "username": "login@example.com",
            "password": "SecurePassword123!",
        },
    )
    assert response.status_code == 200
    assert "access_token" in response.json()


async def test_login_wrong_password_returns_400(client):
    """POST /auth/jwt/login with wrong password returns 400."""
    await client.post(
        "/auth/register",
        json={
            "email": "wrong@example.com",
            "password": "SecurePassword123!",
        },
    )
    response = await client.post(
        "/auth/jwt/login",
        data={
            "username": "wrong@example.com",
            "password": "WrongPassword!",
        },
    )
    assert response.status_code == 400


async def test_forgot_password_returns_202(client):
    """POST /auth/forgot-password returns 202 (always, even for nonexistent email)."""
    response = await client.post("/auth/forgot-password", json={"email": "nonexistent@example.com"})
    assert response.status_code == 202
