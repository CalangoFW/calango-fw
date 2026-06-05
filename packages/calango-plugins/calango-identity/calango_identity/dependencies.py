from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Depends

from calango.exceptions import AuthorizationError
from calango_identity.models import User


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


def require_permission(permission_code: str) -> Any:
    """RBAC dependency factory — raises AuthorizationError if user lacks permission.

    Checks across all roles the user holds. Raises 403 if the permission is absent.

    Usage:
        @router.post("/admin/users")
        async def create_admin(user: User = require_permission("users:admin")):
            ...
    """

    async def _check_permission(user: User) -> User:
        user_perms = {perm.code for role in user.roles for perm in role.permissions}
        if permission_code not in user_perms:
            raise AuthorizationError(f"Permission '{permission_code}' required")
        return user

    return Depends(_check_permission)
