from typing import ClassVar

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from calango.config import CalangoSettings, SecuritySettings
from calango.core.app import Calango
from calango.exceptions import AuthorizationError, NotFoundError


@pytest.fixture
def settings():
    return CalangoSettings(security=SecuritySettings(SECRET_KEY="test-secret"))


@pytest.fixture
def app(settings):
    return Calango(settings=settings)


@pytest.fixture
def client(app):
    return TestClient(app)


class TestCalangoFactory:
    def test_calango_e_instancia_de_fastapi(self, app):
        assert isinstance(app, FastAPI)

    def test_titulo_vem_das_settings(self, settings):
        settings.APP_NAME = "Minha API"
        app = Calango(settings=settings)
        assert app.title == "Minha API"

    def test_cria_com_settings_default(self):
        app = Calango(settings=CalangoSettings(security=SecuritySettings(SECRET_KEY="k")))
        assert isinstance(app, FastAPI)


class TestCalangoMiddleware:
    def test_toda_response_tem_request_id(self, app, client):
        @app.get("/test-mid")
        def _():
            return {"ok": True}

        response = client.get("/test-mid")
        assert "x-request-id" in response.headers

    def test_request_id_e_uuid_valido(self, app, client):
        import uuid

        @app.get("/test-uuid")
        def _():
            return {"ok": True}

        response = client.get("/test-uuid")
        request_id = response.headers["x-request-id"]
        uuid.UUID(request_id)  # levanta ValueError se inválido

    def test_headers_de_seguranca_presentes(self, app, client):
        @app.get("/test-sec")
        def _():
            return {"ok": True}

        response = client.get("/test-sec")
        assert response.headers.get("x-content-type-options") == "nosniff"
        assert response.headers.get("x-frame-options") == "DENY"

    def test_versao_do_framework_no_header(self, app, client):
        @app.get("/test-ver")
        def _():
            return {"ok": True}

        response = client.get("/test-ver")
        assert "x-calango-version" in response.headers


class TestExceptionHandlers:
    def test_not_found_retorna_404(self, app, client):
        @app.get("/test-404")
        def _():
            raise NotFoundError("Recurso não encontrado")

        response = client.get("/test-404")
        assert response.status_code == 404
        body = response.json()
        assert body["error"] == "not_found"
        assert body["message"] == "Recurso não encontrado"
        assert "request_id" in body

    def test_authorization_error_retorna_403(self, app, client):
        @app.get("/test-403")
        def _():
            raise AuthorizationError("Sem permissão")

        response = client.get("/test-403")
        assert response.status_code == 403

    def test_erro_interno_retorna_500_sem_stack_trace(self, app, client):
        @app.get("/test-500")
        def _():
            raise RuntimeError("erro interno inesperado")

        response = client.get("/test-500")
        assert response.status_code == 500
        body = response.json()
        assert "request_id" in body
        assert "traceback" not in str(body).lower()
        assert "runtimeerror" not in str(body).lower()


def test_include_plugin_calls_register():
    """include_plugin() calls plugin.register(app)."""
    from pydantic_settings import BaseSettings

    class FakePlugin:
        name = "fake"
        version = "0.1.0"
        requires: ClassVar[list[str]] = []
        registered_with: ClassVar = None

        def register(self, app) -> None:
            FakePlugin.registered_with = app

        def migrations(self) -> list[str]:
            return []

        def settings(self) -> type[BaseSettings]:
            return BaseSettings

        def test_fixtures(self) -> list:
            return []

        def context_md(self) -> str:
            return ""

    app = Calango()
    plugin = FakePlugin()
    app.include_plugin(plugin)
    assert FakePlugin.registered_with is app


def test_include_plugin_raises_for_non_plugin():
    """include_plugin() raises TypeError for objects not implementing PluginBase."""
    app = Calango()
    with pytest.raises(TypeError, match="does not implement PluginBase"):
        app.include_plugin(object())  # type: ignore[arg-type]


def test_include_plugin_accepts_valid_plugin():
    """include_plugin() does not raise for a valid PluginBase implementation."""
    from pydantic_settings import BaseSettings

    class GoodPlugin:
        name = "good"
        version = "1.0.0"
        requires: ClassVar[list[str]] = []

        def register(self, app) -> None: ...

        def migrations(self) -> list[str]:
            return []

        def settings(self) -> type[BaseSettings]:
            return BaseSettings

        def test_fixtures(self) -> list:
            return []

        def context_md(self) -> str:
            return ""

    app = Calango()
    app.include_plugin(GoodPlugin())  # must not raise
