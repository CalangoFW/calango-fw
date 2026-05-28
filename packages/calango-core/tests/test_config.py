import pytest

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
        with pytest.raises(Exception):
            SecuritySettings()

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
    def test_defaults_de_aplicacao(self):
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
