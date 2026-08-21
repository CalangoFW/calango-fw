from contextlib import asynccontextmanager
from typing import ClassVar

import pytest
from fastapi import FastAPI, Request
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

    def test_framework_and_user_lifespan_order(self, settings):
        events = []

        @asynccontextmanager
        async def lifespan(app):
            assert app.database.started
            events.append("user-start")
            yield
            events.append("user-stop")
            assert app.database.started

        app = Calango(settings=settings, lifespan=lifespan)

        with TestClient(app):
            assert app.database.started
            events.append("request")

        assert events == ["user-start", "request", "user-stop"]
        assert not app.database.started

    def test_framework_closes_database_after_user_startup_exception(self, settings):
        @asynccontextmanager
        async def lifespan(app):
            assert app.database.started
            raise RuntimeError("user startup failed")
            yield

        app = Calango(settings=settings, lifespan=lifespan)

        with pytest.raises(RuntimeError, match="user startup failed"):
            with TestClient(app):
                pass

        assert not app.database.started

    def test_user_lifespan_state_is_preserved(self, settings):
        @asynccontextmanager
        async def lifespan(app):
            yield {"from_user_lifespan": "available"}

        app = Calango(settings=settings, lifespan=lifespan)

        @app.get("/lifespan-state")
        def lifespan_state(request: Request):
            return {"value": request.state.from_user_lifespan}

        with TestClient(app) as client:
            response = client.get("/lifespan-state")

        assert response.json() == {"value": "available"}

    def test_default_lifespan_keeps_event_handlers(self, settings):
        events = []
        app = Calango(settings=settings, on_startup=[lambda: events.append("startup")])
        app.router.add_event_handler("shutdown", lambda: events.append("shutdown"))

        with TestClient(app):
            assert events == ["startup"]

        assert events == ["startup", "shutdown"]

    def test_plugin_lifespans_wrap_user_lifespan_and_close_in_reverse_order(self, settings):
        events = []

        @asynccontextmanager
        async def first_plugin(app):
            assert app.database.started
            events.append("first-start")
            try:
                yield
            finally:
                events.append("first-stop")

        @asynccontextmanager
        async def second_plugin(app):
            assert app.database.started
            events.append("second-start")
            try:
                yield
            finally:
                events.append("second-stop")

        @asynccontextmanager
        async def lifespan(app):
            events.append("user-start")
            yield
            events.append("user-stop")

        app = Calango(settings=settings, lifespan=lifespan)
        app.add_plugin_lifespan(first_plugin)
        app.add_plugin_lifespan(second_plugin)

        with TestClient(app):
            events.append("request")

        assert events == [
            "first-start",
            "second-start",
            "user-start",
            "request",
            "user-stop",
            "second-stop",
            "first-stop",
        ]
        assert not app.database.started

    def test_plugin_lifespan_registration_is_rejected_after_startup(self, settings):
        @asynccontextmanager
        async def plugin_lifespan(_app):
            yield

        app = Calango(settings=settings)

        with TestClient(app):
            with pytest.raises(RuntimeError, match="startup"):
                app.add_plugin_lifespan(plugin_lifespan)

        with pytest.raises(RuntimeError, match="startup"):
            app.add_plugin_lifespan(plugin_lifespan)

    def test_plugin_startup_exception_closes_entered_resources_and_database(self, settings):
        events = []

        @asynccontextmanager
        async def entered_plugin(_app):
            events.append("entered-start")
            try:
                yield
            finally:
                events.append("entered-stop")

        @asynccontextmanager
        async def failing_plugin(_app):
            events.append("failing-start")
            raise RuntimeError("plugin startup failed")
            yield

        app = Calango(settings=settings)
        app.add_plugin_lifespan(entered_plugin)
        app.add_plugin_lifespan(failing_plugin)

        with pytest.raises(RuntimeError, match="plugin startup failed"):
            with TestClient(app):
                pass

        assert events == ["entered-start", "failing-start", "entered-stop"]
        assert not app.database.started

    def test_user_shutdown_exception_closes_plugin_and_database(self, settings):
        events = []

        @asynccontextmanager
        async def plugin_lifespan(_app):
            events.append("plugin-start")
            try:
                yield
            finally:
                events.append("plugin-stop")

        @asynccontextmanager
        async def lifespan(_app):
            events.append("user-start")
            yield
            events.append("user-stop")
            raise RuntimeError("user shutdown failed")

        app = Calango(settings=settings, lifespan=lifespan)
        app.add_plugin_lifespan(plugin_lifespan)

        with pytest.raises(RuntimeError, match="user shutdown failed"):
            with TestClient(app):
                events.append("request")

        assert events == [
            "plugin-start",
            "user-start",
            "request",
            "user-stop",
            "plugin-stop",
        ]
        assert not app.database.started


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
        app.include_plugin(object())  # ty: ignore[invalid-argument-type]  # intentional: non-PluginBase


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
