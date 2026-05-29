from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class IdentitySettings(BaseSettings):
    """Configuration for calango-identity plugin.

    All variables use the IDENTITY__ prefix in .env files.

    Example .env:
        IDENTITY__PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\\n..."
        IDENTITY__PUBLIC_KEY="-----BEGIN PUBLIC KEY-----\\n..."
        IDENTITY__REDIS_URL=redis://localhost:6379/0
    """

    PRIVATE_KEY: str
    PUBLIC_KEY: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    RATE_LIMIT_LOGIN_PER_MINUTE: int = 5
    RATE_LIMIT_LOGIN_PER_HOUR_PER_EMAIL: int = 10
    REDIS_URL: str = "redis://localhost:6379/0"

    model_config = SettingsConfigDict(env_prefix="IDENTITY__")
