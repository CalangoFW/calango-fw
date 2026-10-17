from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from calango_identity.dependencies import get_current_user, public, require_permission
from calango_identity.models import Permission, Role, User
from calango_identity.plugin import IdentityPlugin
from calango_identity.refresh_tokens import InMemoryRefreshTokenStore
from calango_identity.settings import IdentitySettings
from fastapi import APIRouter, Depends, FastAPI, Request, WebSocket
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from calango import Calango
from calango.core.database import DatabaseRuntime
from calango.exceptions import AuthenticationError, AuthorizationError
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


async def test_authentication_guard_allows_explicit_identity_public_endpoint():
    from calango_identity.dependencies import make_authentication_guard

    async def identity_endpoint():
        pass

    identity_endpoint.__calango_identity_public__ = True  # ty: ignore[unresolved-attribute]
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/auth/example",
            "root_path": "",
            "headers": [],
            "query_string": b"",
            "scheme": "http",
            "endpoint": identity_endpoint,
        }
    )

    guard = make_authentication_guard()

    await guard(request, None)


async def test_authentication_guard_rejects_anonymous_private_endpoint():
    from calango_identity.dependencies import make_authentication_guard

    async def private_endpoint():
        pass

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/private",
            "root_path": "",
            "headers": [],
            "query_string": b"",
            "scheme": "http",
            "endpoint": private_endpoint,
        }
    )

    guard = make_authentication_guard()

    with pytest.raises(AuthenticationError):
        await guard(request, None)


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
async def identity_app() -> AsyncIterator[tuple[Calango, async_sessionmaker[AsyncSession]]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(User.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def get_db():
        async with session_factory() as session:
            yield session

    app = Calango()
    app.database = DatabaseRuntime(app.settings, session_dependency=get_db)

    @app.get("/private")
    async def private_endpoint():
        return {"private": True}

    @app.get("/open")
    @public
    async def open_endpoint():
        return {"open": True}

    @app.get("/feed")
    @public
    async def feed(user: User | None = Depends(get_current_user)):  # noqa: B008
        return {"email": None if user is None else user.email}

    @app.get("/open-permission")
    @public
    async def open_permission(user: User = require_permission("reports:view")):  # noqa: B008
        return {"user_id": str(user.id)}

    account_app = FastAPI()

    @account_app.get("/me")
    async def mounted_me(user: User = Depends(get_current_user)):  # noqa: B008
        return {"email": user.email}

    app.mount("/mounted-account", account_app)

    application_router = APIRouter()
    late_parent = APIRouter()

    @application_router.get("/router-private")
    async def router_private_endpoint():
        return {"private": True}

    @application_router.get("/router-open")
    @public
    async def router_open_endpoint():
        return {"open": True}

    app.include_router(application_router)
    app.include_router(late_parent, prefix="/late-parent")

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

    @app.get("/open-after-plugin")
    @public
    async def open_after_plugin():
        return {"open": "after"}

    @public
    @app.get("/open-outer-decorator")
    async def open_outer_decorator():
        return {"open": "outer"}

    async def starlette_private(_request: Request) -> JSONResponse:
        return JSONResponse({"private": "starlette"})

    app.add_route("/starlette-private", starlette_private)

    mounted_app = FastAPI()

    @mounted_app.get("/")
    async def mounted_root():
        return {"private": "mount"}

    app.mount("/mounted-private", mounted_app)

    late_child = APIRouter()
    late_mounted_app = FastAPI()

    async def late_nested_route(_request: Request) -> JSONResponse:
        return JSONResponse({"private": "late-route"})

    @late_mounted_app.get("/")
    async def late_mounted_root():
        return {"private": "late-mount"}

    @late_child.get("/public-api")
    @public
    async def late_public_api():
        return {"open": "late-api"}

    @late_child.get("/current-user")
    async def late_current_user(user: User = Depends(get_current_user)):  # noqa: B008
        return {"email": user.email}

    late_child.add_route("/route", late_nested_route)
    late_child.mount("/mount", late_mounted_app)
    late_parent.include_router(late_child, prefix="/child")

    async with app.router.lifespan_context(app):
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


async def test_late_nested_public_api_route_is_anonymous(identity_app):
    app, _ = identity_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/late-parent/child/public-api")

    assert response.status_code == 200
    assert response.json() == {"open": "late-api"}


async def test_late_nested_api_route_receives_authenticated_user(identity_app):
    app, _ = identity_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        headers = await _register_and_login(client, "late-current-user@example.com")
        response = await client.get("/late-parent/child/current-user", headers=headers)

    assert response.status_code == 200
    assert response.json() == {"email": "late-current-user@example.com"}


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/open-after-plugin", {"open": "after"}),
        ("/open-outer-decorator", {"open": "outer"}),
    ],
)
async def test_public_route_registered_after_plugin_is_anonymous(
    identity_app,
    path: str,
    expected: dict[str, str],
):
    app, _ = identity_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(path)

    assert response.status_code == 200
    assert response.json() == expected


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


@pytest.mark.parametrize(
    "path",
    [
        "/starlette-private",
        "/mounted-private/",
        "/late-parent/child/route",
        "/late-parent/child/mount/",
    ],
)
async def test_non_api_http_boundaries_require_authentication(identity_app, path: str):
    app, _ = identity_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(path)

    assert response.status_code == 401
    assert response.json()["error"] == "authentication_error"


@pytest.mark.parametrize(
    "path",
    [
        "/starlette-private",
        "/mounted-private/",
        "/late-parent/child/route",
        "/late-parent/child/mount/",
    ],
)
async def test_non_api_http_boundaries_accept_active_user(identity_app, path: str):
    app, _ = identity_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        headers = await _register_and_login(client, f"active-{path.count('/')}@example.com")
        response = await client.get(path, headers=headers)

    assert response.status_code == 200


async def test_identity_guard_survives_public_dependency_override_clear(identity_app):
    app, _ = identity_app
    app.dependency_overrides.clear()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        anonymous = await client.get("/private")
        headers = await _register_and_login(client, "override-clear@example.com")
        authenticated = await client.get("/private", headers=headers)

    assert anonymous.status_code == 401
    assert authenticated.status_code == 200


async def test_public_route_receives_none_for_anonymous_user(identity_app):
    app, _ = identity_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/feed")

    assert response.status_code == 200, response.text
    assert response.json() == {"email": None}


async def test_public_route_receives_authenticated_user(identity_app):
    app, _ = identity_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        headers = await _register_and_login(client, "feed@example.com")
        response = await client.get("/feed", headers=headers)

    assert response.status_code == 200, response.text
    assert response.json() == {"email": "feed@example.com"}


async def test_public_permission_route_rejects_anonymous_user(identity_app):
    app, _ = identity_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/open-permission")

    assert response.status_code == 401
    assert response.json()["error"] == "authentication_error"


async def test_mounted_application_receives_authenticated_user(identity_app):
    app, _ = identity_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        headers = await _register_and_login(client, "mounted-account@example.com")
        response = await client.get("/mounted-account/me", headers=headers)

    assert response.status_code == 200, response.text
    assert response.json() == {"email": "mounted-account@example.com"}


async def test_overriding_get_current_user_authenticates_private_routes(identity_app):
    app, _ = identity_app
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        email="override@example.com"
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        overridden = await client.get("/late-parent/child/current-user")
        app.dependency_overrides.clear()
        restored = await client.get("/late-parent/child/current-user")

    assert overridden.status_code == 200, overridden.text
    assert overridden.json() == {"email": "override@example.com"}
    assert restored.status_code == 401


async def test_user_resolution_uses_overridden_session_dependency():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(User.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def test_session():
        async with session_factory() as session:
            yield session

    app = Calango()
    private_child = FastAPI()

    @private_child.get("/")
    async def private_child_root():
        return {"private": "mount"}

    app.mount("/private-mount", private_child)
    settings = IdentitySettings(
        PRIVATE_KEY=TEST_PRIVATE_KEY,
        PUBLIC_KEY=TEST_PUBLIC_KEY,
        REDIS_URL="memory://",
    )
    app.include_plugin(IdentityPlugin(settings=settings, refresh_store=InMemoryRefreshTokenStore()))
    app.dependency_overrides[app.database.session] = test_session

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await _register_and_login(client, "override-session@example.com")
        mounted = await client.get("/private-mount/", headers=headers)
        api_route = await client.get("/users/me", headers=headers)
    await engine.dispose()

    assert mounted.status_code == 200, mounted.text
    assert api_route.status_code == 200, api_route.text


@pytest.mark.parametrize("path", ["/auth/refresh", "/auth/logout"])
async def test_refresh_token_auth_endpoints_use_their_public_boundary(
    identity_app,
    path: str,
):
    app, _ = identity_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(path, json={"refresh_token": "invalid"})

    assert response.status_code == 401
    assert response.json()["message"] == "Invalid refresh token"


async def test_identity_users_router_remains_private(identity_app):
    app, _ = identity_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/users/me")

    assert response.status_code == 401
    assert response.json()["message"] == "Authentication required"


async def test_identity_uses_calango_database_runtime_session(
    monkeypatch: pytest.MonkeyPatch,
):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(User.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def runtime_session():
        async with session_factory() as session:
            yield session

    async def forbidden_module_dependency():
        raise AssertionError("Identity must use app.database.session")
        yield

    monkeypatch.setattr("calango.core.database.get_db", forbidden_module_dependency)
    app = Calango()
    app.database = DatabaseRuntime(app.settings, session_dependency=runtime_session)
    settings = IdentitySettings(
        PRIVATE_KEY=TEST_PRIVATE_KEY,
        PUBLIC_KEY=TEST_PUBLIC_KEY,
        REDIS_URL="memory://",
    )
    app.include_plugin(
        IdentityPlugin(
            settings=settings,
            refresh_store=InMemoryRefreshTokenStore(),
        )
    )

    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/auth/register",
                json={
                    "email": "runtime@example.com",
                    "password": "SecurePassword123!",
                },
            )

    await engine.dispose()

    assert response.status_code == 201


@pytest.fixture
async def rbac_app() -> AsyncIterator[tuple[Calango, async_sessionmaker[AsyncSession]]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(User.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def get_db():
        async with session_factory() as session:
            yield session

    app = Calango()
    app.database = DatabaseRuntime(app.settings, session_dependency=get_db)

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

    async with app.router.lifespan_context(app):
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


def test_websocket_routes_are_outside_identity_authentication():
    """Documented exclusion: WebSocket endpoints must authenticate themselves."""
    app = Calango()

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await websocket.accept()
        await websocket.send_text("anonymous")
        await websocket.close()

    settings = IdentitySettings(
        PRIVATE_KEY=TEST_PRIVATE_KEY,
        PUBLIC_KEY=TEST_PUBLIC_KEY,
        REDIS_URL="memory://",
    )
    app.include_plugin(IdentityPlugin(settings=settings, refresh_store=InMemoryRefreshTokenStore()))

    with TestClient(app).websocket_connect("/ws") as connection:
        assert connection.receive_text() == "anonymous"
