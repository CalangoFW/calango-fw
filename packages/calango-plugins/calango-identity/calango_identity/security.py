from __future__ import annotations

from fastapi_users.authentication import (
    AuthenticationBackend,
    BearerTransport,
    JWTStrategy,
)

from calango_identity.settings import IdentitySettings


def make_jwt_strategy(settings: IdentitySettings) -> JWTStrategy:
    return JWTStrategy(
        secret=settings.PRIVATE_KEY,
        lifetime_seconds=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        algorithm="RS256",
        public_key=settings.PUBLIC_KEY,
    )


def make_auth_backend(settings: IdentitySettings) -> AuthenticationBackend:
    transport = BearerTransport(tokenUrl="/auth/jwt/login")
    return AuthenticationBackend(
        name="jwt",
        transport=transport,
        get_strategy=lambda: make_jwt_strategy(settings),
    )
