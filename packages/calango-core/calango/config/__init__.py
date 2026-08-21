from __future__ import annotations

import os
import warnings
from typing import Any, Literal

from pydantic import Field, TypeAdapter, ValidationError
from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

_LEGACY_TOP_LEVEL_NAMES = ("APP_NAME", "VERSION", "ENV", "DEBUG")


class _LegacyTopLevelEnvironmentSource(PydanticBaseSettingsSource):
    """Load legacy top-level environment variables after namespaced sources."""

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        return None, field_name, False

    def __call__(self) -> dict[str, str]:
        values: dict[str, str] = {}
        for name in _LEGACY_TOP_LEVEL_NAMES:
            if name not in self.current_state and name in os.environ:
                value = os.environ[name]
                try:
                    TypeAdapter(self.settings_cls.model_fields[name].annotation).validate_python(
                        value
                    )
                except ValidationError:
                    continue
                warnings.warn(
                    f"{name} is deprecated; use CALANGO_{name}",
                    DeprecationWarning,
                    stacklevel=2,
                )
                values[name] = value
        return values


class DatabaseSettings(BaseSettings):
    URL: str = "postgresql+asyncpg://calango:calango@localhost:5432/calango"
    POOL_SIZE: int = 10
    MAX_OVERFLOW: int = 20
    POOL_TIMEOUT: int = 30
    POOL_RECYCLE: int = 1800

    model_config = SettingsConfigDict(env_prefix="DATABASE_")


class RedisSettings(BaseSettings):
    URL: str = "redis://localhost:6379/0"

    model_config = SettingsConfigDict(env_prefix="REDIS_")


class SecuritySettings(BaseSettings):
    SECRET_KEY: str
    JWT_ALGORITHM: str = "RS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    CORS_ORIGINS: list[str] = Field(default_factory=list)

    model_config = SettingsConfigDict(env_prefix="SECURITY_")


class CalangoSettings(BaseSettings):
    APP_NAME: str = "Calango App"
    VERSION: str = "0.1.0"
    ENV: Literal["development", "production", "test"] = "development"
    DEBUG: bool = False

    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    security: SecuritySettings

    model_config = SettingsConfigDict(
        env_prefix="CALANGO_",
        env_file=".env",
        env_nested_delimiter="__",
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            _LegacyTopLevelEnvironmentSource(settings_cls),
            file_secret_settings,
        )
