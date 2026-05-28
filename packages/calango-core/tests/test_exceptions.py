
from calango.exceptions import (
    AuthenticationError,
    AuthorizationError,
    CalangoException,
    ConfigurationError,
    ConflictError,
    NotFoundError,
    RateLimitError,
    ServiceUnavailableError,
    ValidationError,
)


class TestCalangoException:
    def test_base_exception_tem_status_code_message_e_error_code(self):
        exc = CalangoException(message="algo falhou", status_code=500, error_code="internal_error")
        assert exc.status_code == 500
        assert exc.message == "algo falhou"
        assert exc.error_code == "internal_error"

    def test_base_exception_e_subclasse_de_exception(self):
        exc = CalangoException(message="erro", status_code=500, error_code="err")
        assert isinstance(exc, Exception)


class TestNotFoundError:
    def test_status_code_e_404(self):
        exc = NotFoundError("Pedido não encontrado")
        assert exc.status_code == 404

    def test_error_code_padrao(self):
        exc = NotFoundError("Pedido não encontrado")
        assert exc.error_code == "not_found"

    def test_e_subclasse_de_calango_exception(self):
        exc = NotFoundError("x")
        assert isinstance(exc, CalangoException)


class TestValidationError:
    def test_status_code_e_422(self):
        assert ValidationError("campo inválido").status_code == 422

    def test_error_code_padrao(self):
        assert ValidationError("campo inválido").error_code == "validation_error"


class TestAuthenticationError:
    def test_status_code_e_401(self):
        assert AuthenticationError("token inválido").status_code == 401

    def test_error_code_padrao(self):
        assert AuthenticationError("token inválido").error_code == "authentication_error"


class TestAuthorizationError:
    def test_status_code_e_403(self):
        assert AuthorizationError("sem permissão").status_code == 403

    def test_error_code_padrao(self):
        assert AuthorizationError("sem permissão").error_code == "authorization_error"


class TestConflictError:
    def test_status_code_e_409(self):
        assert ConflictError("email já existe").status_code == 409

    def test_error_code_padrao(self):
        assert ConflictError("email já existe").error_code == "conflict"


class TestRateLimitError:
    def test_status_code_e_429(self):
        assert RateLimitError("muitas requisições").status_code == 429

    def test_error_code_padrao(self):
        assert RateLimitError("muitas requisições").error_code == "rate_limit_exceeded"

    def test_retry_after_padrao_e_60(self):
        exc = RateLimitError("muitas requisições")
        assert exc.retry_after == 60

    def test_retry_after_configuravel(self):
        exc = RateLimitError("muitas requisições", retry_after=120)
        assert exc.retry_after == 120


class TestServiceUnavailableError:
    def test_status_code_e_503(self):
        assert ServiceUnavailableError("banco indisponível").status_code == 503

    def test_error_code_padrao(self):
        assert ServiceUnavailableError("banco indisponível").error_code == "service_unavailable"


class TestConfigurationError:
    def test_status_code_e_500(self):
        assert ConfigurationError("SECRET_KEY não configurada").status_code == 500

    def test_error_code_padrao(self):
        assert ConfigurationError("SECRET_KEY não configurada").error_code == "configuration_error"
