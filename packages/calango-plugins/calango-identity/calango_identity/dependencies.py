from __future__ import annotations

from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import aclosing
from typing import Any

from fastapi import Depends, Request
from fastapi.security import HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from calango.exceptions import AuthenticationError, AuthorizationError
from calango_identity.manager import make_get_user_manager
from calango_identity.models import User
from calango_identity.security import make_jwt_strategy
from calango_identity.settings import IdentitySettings

AuthenticationGuard = Callable[[Request, User | None], Awaitable[None]]
SessionDependency = Callable[[], AsyncGenerator[AsyncSession, None]]
UserResolver = Callable[[Request], Awaitable[User | None]]

_CURRENT_USER_SCOPE_KEY = "calango.identity.current_user"
_bearer = HTTPBearer(auto_error=False)


def public(func: Callable) -> Callable:
    """Mark a FastAPI route as public (no authentication required).

    Usage:
        @router.get("/health")
        @public
        async def health_check():
            return {"status": "ok"}
    """
    func.__calango_public__ = True  # ty: ignore[unresolved-attribute]
    return func


def identity_public(func: Callable) -> Callable:
    """Mark an Identity-owned authentication endpoint as anonymous."""
    func.__calango_identity_public__ = True  # ty: ignore[unresolved-attribute]
    return func


def make_authentication_guard(
    optional_current_user: Callable[..., Any],
) -> AuthenticationGuard:
    """Build Identity's endpoint-aware private-by-default request guard."""
    if not callable(optional_current_user):
        raise TypeError("optional_current_user must be callable")

    async def authentication_guard(request: Request, user: User | None) -> None:
        request.scope[_CURRENT_USER_SCOPE_KEY] = user
        endpoint = request.scope.get("endpoint")
        if getattr(endpoint, "__calango_public__", False) or getattr(
            endpoint,
            "__calango_identity_public__",
            False,
        ):
            return
        if user is None:
            raise AuthenticationError("Authentication required")

    return authentication_guard


def make_optional_current_user_resolver(
    settings: IdentitySettings,
    session_dependency: SessionDependency,
) -> UserResolver:
    """Resolve the same optional active user for Starlette routes and mounts."""
    get_user_manager = make_get_user_manager(settings)
    strategy = make_jwt_strategy(settings)

    async def resolve(request: Request) -> User | None:
        credentials = await _bearer(request)
        if credentials is None:
            return None

        async with aclosing(session_dependency()) as sessions:
            async for session in sessions:
                async with aclosing(get_user_manager(session)) as managers:
                    manager = await anext(managers)
                    user = await strategy.read_token(credentials.credentials, manager)
                if user is not None and user.is_active:
                    return user
                return None
        return None

    return resolve


async def get_current_user(request: Request) -> User:
    """Return the user resolved once by Identity's application guard."""
    user = request.scope.get(_CURRENT_USER_SCOPE_KEY)
    if user is None:
        raise AuthenticationError("Authentication required")
    return user


def require_permission(permission_code: str) -> Any:
    """RBAC dependency factory — raises AuthorizationError if user lacks permission.

    Checks across all roles the user holds. Raises 403 if the permission is absent.

    Usage:
        @router.post("/admin/users")
        async def create_admin(user: User = require_permission("users:admin")):
            ...
    """

    async def _check_permission(
        user: User = Depends(get_current_user),  # noqa: B008
    ) -> User:
        user_perms = {perm.code for role in user.roles for perm in role.permissions}
        if permission_code not in user_perms:
            raise AuthorizationError(f"Permission '{permission_code}' required")
        return user

    return Depends(_check_permission)
