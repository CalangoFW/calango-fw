from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import MagicMock

import pytest
from calango_identity.dependencies import public, require_permission
from calango_identity.models import Permission, Role, User
from calango_identity.plugin import IdentityPlugin
from calango_identity.refresh_tokens import InMemoryRefreshTokenStore
from calango_identity.settings import IdentitySettings
from fastapi import APIRouter, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from calango import Calango
from calango.exceptions import AuthorizationError
from tests.conftest import TEST_PRIVATE_KEY, TEST_PUBLIC_KEY

# ── @public tests ──────────────────────────────────────────────────────────────


def test_public_decorator_sets_marker():
    """@public sets __calango_public__ = True on the function."""

    @public
    def my_handler():
        pass

    assert getattr(my_handler, "__calango_public__", False) is True


def test_public_decorator_preserves_function():
    """@public does not change function behavior."""

    @public
    def add(a, b):
        return a + b

    assert add(1, 2) == 3


async def test_public_endpoint_returns_200_without_token():
    """An endpoint decorated with @public is accessible without Bearer token."""
    app = FastAPI()

    @app.get("/open")
    @public
    async def open_endpoint():
        return {"open": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/open")
    assert response.status_code == 200


def test_non_public_function_has_no_marker():
    """A function without @public does not have the public marker."""

    async def plain_handler():
        pass

    assert getattr(plain_handler, "__calango_public__", False) is False


# ── require_permission tests ───────────────────────────────────────────────────


def _make_user_with_perm(perm_code: str) -> User:
    perm = MagicMock(spec=Permission)
    perm.code = perm_code
    role = MagicMock(spec=Role)
    role.permissions = [perm]
    user = MagicMock(spec=User)
    user.roles = [role]
    return user


def _make_user_no_perms() -> User:
    user = MagicMock(spec=User)
    user.roles = []
    return user


async def test_require_permission_grants_access_when_user_has_perm():
    """require_permission passes when user has the required permission code."""
    user = _make_user_with_perm("orders:read")
    dep = require_permission("orders:read")
    check_fn = dep.dependency
    result = await check_fn(user=user)
    assert result is user


async def test_require_permission_raises_403_when_missing():
    """require_permission raises AuthorizationError when user lacks permission."""
    user = _make_user_no_perms()
    dep = require_permission("orders:write")
    check_fn = dep.dependency
    with pytest.raises(AuthorizationError):
        await check_fn(user=user)


async def test_require_permission_passes_with_any_matching_role():
    """require_permission passes if ANY of user's roles has the permission."""
    perm1 = MagicMock(spec=Permission)
    perm1.code = "reports:view"
    role1 = MagicMock(spec=Role)
    role1.permissions = [perm1]

    perm2 = MagicMock(spec=Permission)
    perm2.code = "orders:read"
    role2 = MagicMock(spec=Role)
    role2.permissions = [perm2]

    user = MagicMock(spec=User)
    user.roles = [role1, role2]

    dep = require_permission("orders:read")
    check_fn = dep.dependency
    result = await check_fn(user=user)
    assert result is user


# ── Authentication-by-default and RBAC integration tests ──────────────────────────


async def _register_and_login(client: AsyncClient, email: str) -> dict[str, str]:
    registered = await client.post(
        "/auth/register",
        json={"email": email, "password": "SecurePassword123!"},
    )
    assert registered.status_code == 201, registered.text
    logged_in = await client.post(
        "/auth/login",
        data={"username": email, "password": "SecurePassword123!"},
    )
    assert logged_in.status_code == 200, logged_in.text
    return {"Authorization": f"Bearer {logged_in.json()['access_token']}"}


@pytest.fixture
async def identity_app(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[tuple[Calango, async_sessionmaker[AsyncSession]]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(User.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def get_db():
        async with session_factory() as session:
            yield session

    monkeypatch.setattr("calango.core.database.get_db", get_db)

    app = Calango()

    @app.get("/private")
    async def private_endpoint():
        return {"private": True}

    @app.get("/open")
    @public
    async def open_endpoint():
        return {"open": True}

    application_router = APIRouter()

    @application_router.get("/router-private")
    async def router_private_endpoint():
        return {"private": True}

    @application_router.get("/router-open")
    @public
    async def router_open_endpoint():
        return {"open": True}

    app.include_router(application_router)

    settings = IdentitySettings(
        PRIVATE_KEY=TEST_PRIVATE_KEY,
        PUBLIC_KEY=TEST_PUBLIC_KEY,
        REDIS_URL="memory://",
    )
    app.include_plugin(IdentityPlugin(settings=settings, refresh_store=InMemoryRefreshTokenStore()))

    @app.get("/registered-after-plugin")
    async def registered_after_plugin():
        return {"private": True}

    @application_router.get("/router-registered-after-plugin")
    async def router_registered_after_plugin():
        return {"private": True}

    yield app, session_factory
    await engine.dispose()


async def test_private_route_without_authentication_returns_401(identity_app):
    app, _ = identity_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/private")

    assert response.status_code == 401
    assert response.json()["error"] == "authentication_error"


async def test_public_route_without_authentication_returns_200(identity_app):
    app, _ = identity_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/open")

    assert response.status_code == 200
    assert response.json() == {"open": True}


async def test_authenticated_private_route_succeeds(identity_app):
    app, _ = identity_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        headers = await _register_and_login(client, "private@example.com")
        response = await client.get("/private", headers=headers)

    assert response.status_code == 200
    assert response.json() == {"private": True}


async def test_route_registered_after_plugin_requires_authentication(identity_app):
    app, _ = identity_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/registered-after-plugin")

    assert response.status_code == 401


async def test_router_included_before_plugin_requires_authentication(identity_app):
    app, _ = identity_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/router-private")

    assert response.status_code == 401


async def test_public_route_on_router_included_before_plugin_returns_200(identity_app):
    app, _ = identity_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/router-open")

    assert response.status_code == 200
    assert response.json() == {"open": True}


async def test_route_added_to_included_router_after_plugin_requires_authentication(
    identity_app,
):
    app, _ = identity_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/router-registered-after-plugin")

    assert response.status_code == 401


@pytest.fixture
async def rbac_app(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[tuple[Calango, async_sessionmaker[AsyncSession]]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(User.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def get_db():
        async with session_factory() as session:
            yield session

    monkeypatch.setattr("calango.core.database.get_db", get_db)

    app = Calango()

    @app.get("/reports")
    async def reports(
        user: User = require_permission("reports:view"),  # noqa: B008
    ):
        return {"user_id": str(user.id)}

    settings = IdentitySettings(
        PRIVATE_KEY=TEST_PRIVATE_KEY,
        PUBLIC_KEY=TEST_PUBLIC_KEY,
        REDIS_URL="memory://",
    )
    app.include_plugin(IdentityPlugin(settings=settings, refresh_store=InMemoryRefreshTokenStore()))

    yield app, session_factory
    await engine.dispose()


async def test_permission_route_without_authentication_returns_401(rbac_app):
    app, _ = rbac_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/reports")

    assert response.status_code == 401


async def test_permission_route_without_permission_returns_403(rbac_app):
    app, _ = rbac_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        headers = await _register_and_login(client, "viewer@example.com")
        response = await client.get("/reports", headers=headers)

    assert response.status_code == 403
    assert response.json()["error"] == "authorization_error"


async def test_permission_route_with_permission_returns_200(rbac_app):
    app, session_factory = rbac_app
    email = "reporter@example.com"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        headers = await _register_and_login(client, email)
        async with session_factory() as session:
            user = await session.scalar(select(User).filter_by(email=email))
            assert user is not None
            permission = Permission(code="reports:view")
            role = Role(name="reporter", users=[user], permissions=[permission])
            session.add(role)
            await session.commit()

        response = await client.get("/reports", headers=headers)

    assert response.status_code == 200
