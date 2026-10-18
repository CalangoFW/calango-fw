import warnings
from pathlib import Path

import pytest
from pydantic import ValidationError

from calango.config import CalangoSettings, DatabaseSettings, RedisSettings, SecuritySettings


class TestDatabaseSettings:
    def test_defaults_saudaveis(self):
        db = DatabaseSettings()
        assert db.POOL_SIZE == 10
        assert db.MAX_OVERFLOW == 20
        assert db.POOL_TIMEOUT == 30
        assert db.POOL_RECYCLE == 1800

    def test_url_tem_valor_padrao(self):
        db = DatabaseSettings()
        assert "postgresql" in db.URL


class TestRedisSettings:
    def test_url_padrao(self):
        redis = RedisSettings()
        assert redis.URL == "redis://localhost:6379/0"


class TestSecuritySettings:
    def test_secret_key_e_obrigatorio(self):
        with pytest.raises(ValidationError):
            SecuritySettings()  # ty: ignore[missing-argument]  # intentional: SECRET_KEY omitted

    def test_algoritmo_padrao_rs256(self):
        sec = SecuritySettings(SECRET_KEY="minha-chave-secreta")
        assert sec.JWT_ALGORITHM == "RS256"

    def test_token_expira_em_15_minutos(self):
        sec = SecuritySettings(SECRET_KEY="minha-chave-secreta")
        assert sec.ACCESS_TOKEN_EXPIRE_MINUTES == 15

    def test_cors_fechado_por_padrao(self):
        sec = SecuritySettings(SECRET_KEY="minha-chave-secreta")
        assert sec.CORS_ORIGINS == []


class TestCalangoSettings:
    def test_defaults_de_aplicacao(self, monkeypatch):
        for name in ("APP_NAME", "VERSION", "ENV", "DEBUG"):
            monkeypatch.delenv(name, raising=False)
        settings = CalangoSettings(security=SecuritySettings(SECRET_KEY="test-key"))
        assert settings.APP_NAME == "Calango App"
        assert settings.VERSION == "0.1.0"
        assert settings.ENV == "development"
        assert settings.DEBUG is False

    def test_sub_settings_database_disponivel(self):
        settings = CalangoSettings(security=SecuritySettings(SECRET_KEY="test-key"))
        assert isinstance(settings.database, DatabaseSettings)

    def test_sub_settings_redis_disponivel(self):
        settings = CalangoSettings(security=SecuritySettings(SECRET_KEY="test-key"))
        assert isinstance(settings.redis, RedisSettings)

    def test_sub_settings_security_disponivel(self):
        settings = CalangoSettings(security=SecuritySettings(SECRET_KEY="test-key"))
        assert isinstance(settings.security, SecuritySettings)

    def test_override_via_construtor(self):
        settings = CalangoSettings(
            APP_NAME="Minha API",
            security=SecuritySettings(SECRET_KEY="test-key"),
        )
        assert settings.APP_NAME == "Minha API"


def test_calango_prefix_wins(monkeypatch):
    monkeypatch.setenv("DEBUG", "release")
    monkeypatch.setenv("CALANGO_DEBUG", "true")
    value = CalangoSettings(security=SecuritySettings(SECRET_KEY="test"))
    assert value.DEBUG is True


def test_legacy_name_warns_without_value(monkeypatch):
    monkeypatch.delenv("CALANGO_APP_NAME", raising=False)
    monkeypatch.setenv("APP_NAME", "legacy-secret-like-value")
    with pytest.warns(DeprecationWarning, match="APP_NAME") as records:
        value = CalangoSettings(security=SecuritySettings(SECRET_KEY="test"))
    assert value.APP_NAME == "legacy-secret-like-value"
    assert "legacy-secret-like-value" not in str(records[0].message)


def test_calango_prefix_does_not_rename_nested_process_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE__URL", "sqlite+aiosqlite:///nested.db")
    monkeypatch.setenv("REDIS__URL", "redis://nested:6379/3")
    monkeypatch.setenv("SECURITY__SECRET_KEY", "nested-secret")
    monkeypatch.setenv("CALANGO_DATABASE__URL", "sqlite+aiosqlite:///wrong.db")

    settings = CalangoSettings()  # ty: ignore[missing-argument]  # loaded from environment

    assert settings.database.URL == "sqlite+aiosqlite:///nested.db"
    assert settings.redis.URL == "redis://nested:6379/3"
    assert settings.security.SECRET_KEY == "nested-secret"


def test_nested_and_legacy_settings_load_from_dotenv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "APP_NAME",
        "CALANGO_APP_NAME",
        "DATABASE__URL",
        "REDIS__URL",
        "SECURITY__SECRET_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "APP_NAME=dotenv-legacy\n"
        "DATABASE__URL=sqlite+aiosqlite:///dotenv.db\n"
        "REDIS__URL=redis://dotenv:6379/4\n"
        "SECURITY__SECRET_KEY=dotenv-secret\n"
    )

    with pytest.warns(DeprecationWarning, match="APP_NAME") as records:
        settings = CalangoSettings(  # ty: ignore[missing-argument]
            _env_file=env_file  # ty: ignore[unknown-argument]
        )

    assert settings.APP_NAME == "dotenv-legacy"
    assert settings.database.URL == "sqlite+aiosqlite:///dotenv.db"
    assert settings.redis.URL == "redis://dotenv:6379/4"
    assert settings.security.SECRET_KEY == "dotenv-secret"
    assert "dotenv-legacy" not in str(records[0].message)


def test_namespaced_dotenv_value_wins_over_process_legacy_without_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("VERSION", "ENV", "DEBUG"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("APP_NAME", "process-legacy")
    monkeypatch.delenv("CALANGO_APP_NAME", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("CALANGO_APP_NAME=dotenv-namespaced\nSECURITY__SECRET_KEY=dotenv-secret\n")

    with warnings.catch_warnings(record=True) as records:
        warnings.simplefilter("always", DeprecationWarning)
        settings = CalangoSettings(  # ty: ignore[missing-argument]
            _env_file=env_file  # ty: ignore[unknown-argument]
        )

    assert settings.APP_NAME == "dotenv-namespaced"
    assert not [record for record in records if "APP_NAME" in str(record.message)]
