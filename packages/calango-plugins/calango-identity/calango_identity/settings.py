from __future__ import annotations

from ipaddress import ip_address, ip_network

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey
from pydantic import Field, field_validator
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
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=15, gt=0)
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(default=7, gt=0)
    REFRESH_TOKEN_KEY_PREFIX: str = "calango:identity:refresh"  # noqa: S105 - Redis namespace
    RATE_LIMIT_LOGIN_PER_MINUTE: int = Field(default=5, gt=0)
    RATE_LIMIT_LOGIN_PER_HOUR_PER_EMAIL: int = Field(default=10, gt=0)
    REDIS_URL: str = "redis://localhost:6379/0"
    TRUSTED_PROXIES: tuple[str, ...] = ()

    model_config = SettingsConfigDict(env_prefix="IDENTITY__")

    @field_validator("PRIVATE_KEY")
    @classmethod
    def validate_private_key(cls, value: str) -> str:
        """Require an unencrypted PEM-encoded RSA private key at startup."""
        try:
            key = serialization.load_pem_private_key(value.encode(), password=None)
        except (TypeError, ValueError) as error:
            raise ValueError("PRIVATE_KEY must be a valid unencrypted PEM private key") from error
        if not isinstance(key, RSAPrivateKey):
            raise ValueError("PRIVATE_KEY must be an RSA private key")
        return value

    @field_validator("PUBLIC_KEY")
    @classmethod
    def validate_public_key(cls, value: str) -> str:
        """Require a PEM-encoded RSA public key at startup."""
        try:
            key = serialization.load_pem_public_key(value.encode())
        except ValueError as error:
            raise ValueError("PUBLIC_KEY must be a valid PEM public key") from error
        if not isinstance(key, RSAPublicKey):
            raise ValueError("PUBLIC_KEY must be an RSA public key")
        return value

    @field_validator("REFRESH_TOKEN_KEY_PREFIX")
    @classmethod
    def validate_refresh_token_key_prefix(cls, value: str) -> str:
        """Prevent refresh tokens from being written into Redis's root namespace."""
        if not value.strip():
            raise ValueError("REFRESH_TOKEN_KEY_PREFIX must not be blank")
        return value

    @field_validator("TRUSTED_PROXIES")
    @classmethod
    def validate_trusted_proxies(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """Require every trusted proxy entry to be an explicit IP address or network."""
        for value in values:
            try:
                ip_address(value)
            except ValueError:
                try:
                    ip_network(value, strict=False)
                except ValueError as error:
                    raise ValueError(
                        "TRUSTED_PROXIES entries must be IP addresses or networks"
                    ) from error
        return values
