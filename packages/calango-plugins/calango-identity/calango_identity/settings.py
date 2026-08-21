from __future__ import annotations

from ipaddress import ip_address, ip_network
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey
from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_core import InitErrorDetails, PydanticCustomError
from pydantic_settings import BaseSettings, SettingsConfigDict


class IdentitySettings(BaseSettings):
    """Configuration for calango-identity plugin.

    All variables use the IDENTITY__ prefix in .env files.

    Example .env:
        IDENTITY__PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\\n..."
        IDENTITY__PUBLIC_KEY="-----BEGIN PUBLIC KEY-----\\n..."
        IDENTITY__REDIS_URL=redis://localhost:6379/0
    """

    PRIVATE_KEY: SecretStr
    PUBLIC_KEY: SecretStr
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=15, gt=0)
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(default=7, gt=0)
    REFRESH_TOKEN_KEY_PREFIX: str = "calango:identity:refresh"  # noqa: S105 - Redis namespace
    RATE_LIMIT_LOGIN_PER_MINUTE: int = Field(default=5, gt=0)
    RATE_LIMIT_LOGIN_PER_HOUR_PER_EMAIL: int = Field(default=10, gt=0)
    REDIS_URL: str = "redis://localhost:6379/0"
    TRUSTED_PROXIES: tuple[str, ...] = ()

    model_config = SettingsConfigDict(env_prefix="IDENTITY__", hide_input_in_errors=True)

    def __init__(self, **values: Any) -> None:
        """Accept string-backed environment values while storing keys as secrets."""
        sanitized_error: ValidationError | None = None
        try:
            super().__init__(**values)
        except ValidationError as error:
            sanitized_error = self._sanitize_validation_error(error)
        if sanitized_error is not None:
            raise sanitized_error

    @staticmethod
    def _sanitize_validation_error(error: ValidationError) -> ValidationError:
        """Replace reversible RSA key data before an error crosses this boundary."""
        sanitized_errors: list[InitErrorDetails] = []
        for line_error in error.errors():
            location = line_error["loc"]
            is_key_error = bool(location) and location[0] in {
                "PRIVATE_KEY",
                "PUBLIC_KEY",
            }
            is_key_value_error = is_key_error and line_error["type"] == "value_error"
            sanitized_error: InitErrorDetails = {
                "type": (
                    PydanticCustomError(
                        "value_error",
                        "{message}",
                        {"message": line_error["msg"]},
                    )
                    if is_key_value_error
                    else line_error["type"]
                ),
                "loc": location,
                "input": "<redacted>" if is_key_error else line_error["input"],
            }
            if not is_key_error and "ctx" in line_error:
                sanitized_error["ctx"] = line_error["ctx"]
            sanitized_errors.append(sanitized_error)
        return ValidationError.from_exception_data(
            error.title,
            sanitized_errors,
            hide_input=True,
        )

    @model_validator(mode="before")
    @classmethod
    def redact_key_inputs(cls, values: Any) -> Any:
        """Wrap supplied key values before validation so structured errors redact them."""
        if not isinstance(values, dict):
            return values

        redacted_values = values.copy()
        for field in ("PRIVATE_KEY", "PUBLIC_KEY"):
            value = values.get(field)
            if isinstance(value, str):
                redacted_values[field] = SecretStr(value)
        return redacted_values

    @field_validator("PRIVATE_KEY")
    @classmethod
    def validate_private_key(cls, value: SecretStr) -> SecretStr:
        """Require an unencrypted PEM-encoded RSA private key at startup."""
        try:
            key = serialization.load_pem_private_key(
                value.get_secret_value().encode(), password=None
            )
        except (TypeError, ValueError) as error:
            raise ValueError("PRIVATE_KEY must be a valid unencrypted PEM private key") from error
        if not isinstance(key, RSAPrivateKey):
            raise ValueError("PRIVATE_KEY must be an RSA private key")
        return value

    @field_validator("PUBLIC_KEY")
    @classmethod
    def validate_public_key(cls, value: SecretStr) -> SecretStr:
        """Require a PEM-encoded RSA public key at startup."""
        try:
            key = serialization.load_pem_public_key(value.get_secret_value().encode())
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
                    ip_network(value, strict=True)
                except ValueError as error:
                    raise ValueError(
                        "TRUSTED_PROXIES entries must be IP addresses or networks"
                    ) from error
        return values
