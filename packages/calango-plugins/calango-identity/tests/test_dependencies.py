from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from calango_identity.dependencies import public, require_permission
from calango_identity.models import Permission, Role, User
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from calango.exceptions import AuthorizationError

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
