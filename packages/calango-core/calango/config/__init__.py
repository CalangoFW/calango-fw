from __future__ import annotations

import warnings
from typing import Any, Literal

from pydantic import Field, TypeAdapter, ValidationError
from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    DotEnvSettingsSource,
    EnvSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

_LEGACY_TOP_LEVEL_NAMES = ("APP_NAME", "VERSION", "ENV", "DEBUG")
_NESTED_NAMES = ("database", "redis", "security")


class _FilteredSettingsSource(PydanticBaseSettingsSource):
    """Expose only selected model fields from another public settings source."""

    def __init__(
        self,
        settings_cls: type[BaseSettings],
        source: PydanticBaseSettingsSource,
        names: tuple[str, ...],
    ) -> None:
        super().__init__(settings_cls)
        self.source = source
        self.names = names

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        values = self.source()
        return {name: values[name] for name in self.names if name in values}


class _LegacyTopLevelEnvironmentSource(PydanticBaseSettingsSource):
    """Load valid legacy top-level values after all namespaced sources."""

    def __init__(
        self,
        settings_cls: type[BaseSettings],
        source: PydanticBaseSettingsSource,
    ) -> None:
        super().__init__(settings_cls)
        self.source = source

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        return None, field_name, False

    def __call__(self) -> dict[str, str]:
        source_values = self.source()
        values: dict[str, str] = {}
        for name in _LEGACY_TOP_LEVEL_NAMES:
            if name not in self.current_state and name in source_values:
                value = source_values[name]
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
        if not isinstance(env_settings, EnvSettingsSource) or not isinstance(
            dotenv_settings, DotEnvSettingsSource
        ):
            raise TypeError("Calango settings require environment and dotenv sources")
        unprefixed_env_settings = EnvSettingsSource(
            settings_cls,
            case_sensitive=env_settings.case_sensitive,
            env_prefix="",
            env_prefix_target=env_settings.env_prefix_target,
            env_nested_delimiter=env_settings.env_nested_delimiter,
            env_nested_max_split=env_settings.env_nested_max_split,
            env_ignore_empty=env_settings.env_ignore_empty,
            env_parse_none_str=env_settings.env_parse_none_str,
            env_parse_enums=env_settings.env_parse_enums,
        )
        unprefixed_dotenv_settings = DotEnvSettingsSource(
            settings_cls,
            env_file=dotenv_settings.env_file,
            env_file_encoding=dotenv_settings.env_file_encoding,
            dotenv_filtering=dotenv_settings.dotenv_filtering,
            case_sensitive=dotenv_settings.case_sensitive,
            env_prefix="",
            env_prefix_target=dotenv_settings.env_prefix_target,
            env_nested_delimiter=dotenv_settings.env_nested_delimiter,
            env_nested_max_split=dotenv_settings.env_nested_max_split,
            env_ignore_empty=dotenv_settings.env_ignore_empty,
            env_parse_none_str=dotenv_settings.env_parse_none_str,
            env_parse_enums=dotenv_settings.env_parse_enums,
        )
        return (
            init_settings,
            _FilteredSettingsSource(settings_cls, env_settings, _LEGACY_TOP_LEVEL_NAMES),
            _FilteredSettingsSource(settings_cls, dotenv_settings, _LEGACY_TOP_LEVEL_NAMES),
            _FilteredSettingsSource(settings_cls, unprefixed_env_settings, _NESTED_NAMES),
            _FilteredSettingsSource(settings_cls, unprefixed_dotenv_settings, _NESTED_NAMES),
            _LegacyTopLevelEnvironmentSource(settings_cls, unprefixed_env_settings),
            _LegacyTopLevelEnvironmentSource(settings_cls, unprefixed_dotenv_settings),
            file_secret_settings,
        )
