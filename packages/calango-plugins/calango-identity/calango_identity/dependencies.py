from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.dependencies.utils import get_parameterless_sub_dependant
from fastapi.routing import APIRoute
from starlette.routing import BaseRoute

from calango.exceptions import AuthenticationError, AuthorizationError
from calango_identity.models import User


async def _optional_fastapi_users_dependency() -> User | None:
    """App-scoped override point for FastAPI Users' optional dependency."""
    return None


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


async def get_current_user(
    request: Request,
    user: User | None = Depends(_optional_fastapi_users_dependency),  # noqa: B008
) -> User | None:
    """Return the authenticated user, except on explicitly public routes."""
    endpoint = request.scope.get("endpoint")
    if getattr(endpoint, "__calango_public__", False):
        return None
    if user is None:
        raise AuthenticationError("Authentication required")
    return user


def enforce_authentication(
    app: FastAPI,
    optional_current_user: Callable[..., Any],
    existing_routes: Sequence[BaseRoute],
) -> None:
    """Require authentication for existing and subsequently registered routes."""
    app.dependency_overrides[_optional_fastapi_users_dependency] = optional_current_user
    auth_dependency = Depends(get_current_user)

    for route in existing_routes:
        if not isinstance(route, APIRoute):
            include_context = getattr(route, "include_context", None)
            included_dependencies = getattr(include_context, "dependencies", None)
            if isinstance(included_dependencies, list) and not any(
                dependency.dependency is get_current_user for dependency in included_dependencies
            ):
                included_dependencies.append(auth_dependency)
                # FastAPI 0.141+ caches effective routes for lazy router inclusion.
                # Reset only its cache versions after changing the include context.
                for attribute in (
                    "_effective_candidates_version",
                    "_effective_low_priority_routes_version",
                ):
                    if hasattr(route, attribute):
                        setattr(route, attribute, None)
            continue
        if any(dependency.call is get_current_user for dependency in route.dependant.dependencies):
            continue
        route.dependencies.insert(0, auth_dependency)
        route.dependant.dependencies.insert(
            0,
            get_parameterless_sub_dependant(
                depends=auth_dependency,
                path=route.path_format,
            ),
        )

    if not any(dependency.dependency is get_current_user for dependency in app.router.dependencies):
        app.router.dependencies.append(auth_dependency)


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
