from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi import APIRouter, FastAPI, Request, WebSocket
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.testclient import TestClient

from calango.config import CalangoSettings, SecuritySettings
from calango.core.app import Calango
from calango.exceptions import AuthenticationError


@pytest.fixture
def app() -> Calango:
    settings = CalangoSettings(security=SecuritySettings(SECRET_KEY="test-secret"))
    return Calango(settings=settings)


def test_request_guard_is_exported() -> None:
    from calango.core import RequestGuard

    assert RequestGuard is not None


def test_guard_covers_routes_added_before_and_after_registration(app: Calango) -> None:
    selected_endpoints = []

    @app.get("/before")
    async def before() -> dict[str, bool]:
        return {"ok": True}

    async def deny(request: Request) -> None:
        selected_endpoints.append(request.scope["endpoint"])
        raise AuthenticationError("Authentication required")

    app.add_request_guard(deny)

    @app.get("/after")
    async def after() -> dict[str, bool]:
        return {"ok": True}

    client = TestClient(app)

    assert client.get("/before").status_code == 401
    assert client.get("/after").status_code == 401
    assert selected_endpoints == [before, after]


def test_guard_covers_routes_included_from_an_api_router(app: Calango) -> None:
    router = APIRouter()
    selected_endpoints = []

    @router.get("/included")
    async def included() -> dict[str, bool]:
        return {"ok": True}

    async def deny(request: Request) -> None:
        selected_endpoints.append(request.scope["endpoint"])
        raise AuthenticationError("Authentication required")

    app.add_request_guard(deny)
    app.include_router(router)

    assert TestClient(app).get("/included").status_code == 401
    assert selected_endpoints == [included]


def test_guard_covers_routes_in_nested_api_routers(app: Calango) -> None:
    child = APIRouter()
    parent = APIRouter()
    selected_endpoints = []

    @child.get("/nested")
    async def nested() -> dict[str, bool]:
        return {"ok": True}

    parent.include_router(child)

    async def deny(request: Request) -> None:
        selected_endpoints.append(request.scope["endpoint"])
        raise AuthenticationError("Authentication required")

    app.add_request_guard(deny)
    app.include_router(parent)

    assert TestClient(app).get("/nested").status_code == 401
    assert selected_endpoints == [nested]


def test_guard_covers_starlette_route_included_from_an_api_router(
    app: Calango,
) -> None:
    router = APIRouter()
    selected_endpoints = []

    async def included(_request: Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    router.add_route("/included-starlette", included)

    async def deny(request: Request) -> None:
        selected_endpoints.append(request.scope["endpoint"])
        raise AuthenticationError("Authentication required")

    app.add_request_guard(deny)
    app.include_router(router)

    assert TestClient(app).get("/included-starlette").status_code == 401
    assert len(selected_endpoints) == 1
    assert selected_endpoints[0] is not None


def test_guard_covers_private_mount_included_from_an_api_router(
    app: Calango,
) -> None:
    router = APIRouter()
    child = FastAPI()
    selected_endpoints = []

    @child.get("/")
    async def child_root() -> dict[str, bool]:
        return {"ok": True}

    router.mount("/included-child", child)

    async def deny(request: Request) -> None:
        selected_endpoints.append(request.scope["endpoint"])
        raise AuthenticationError("Authentication required")

    app.add_request_guard(deny)
    app.include_router(router)

    assert TestClient(app).get("/included-child/").status_code == 401
    assert len(selected_endpoints) == 1
    assert selected_endpoints[0] is not None


def test_request_guards_run_in_registration_order(app: Calango) -> None:
    calls = []

    async def first(request: Request) -> None:
        calls.append(("first", request.scope["endpoint"]))

    async def second(request: Request) -> None:
        calls.append(("second", request.scope["endpoint"]))

    app.add_request_guard(first)
    app.add_request_guard(second)

    @app.get("/ordered")
    async def ordered() -> dict[str, bool]:
        return {"ok": True}

    response = TestClient(app).get("/ordered")

    assert response.status_code == 200
    assert calls == [("first", ordered), ("second", ordered)]


def test_guard_can_read_body_without_consuming_endpoint_payload(app: Calango) -> None:
    bodies_seen_by_guard = []

    async def read_body(request: Request) -> None:
        bodies_seen_by_guard.append(await request.body())

    app.add_request_guard(read_body)

    @app.post("/echo-body")
    async def echo_body(request: Request) -> JSONResponse:
        return JSONResponse({"body": (await request.body()).decode()})

    response = TestClient(app).post("/echo-body", content=b"same-payload")

    assert response.status_code == 200
    assert response.json() == {"body": "same-payload"}
    assert bodies_seen_by_guard == [b"same-payload"]


def test_mount_is_guarded_by_default(app: Calango) -> None:
    child = FastAPI()
    selected_endpoints = []

    @child.get("/")
    async def root() -> dict[str, bool]:
        return {"ok": True}

    async def deny(request: Request) -> None:
        selected_endpoints.append(request.scope["endpoint"])
        raise AuthenticationError("Authentication required")

    app.add_request_guard(deny)
    app.mount("/child", child)

    assert TestClient(app).get("/child/").status_code == 401
    assert len(selected_endpoints) == 1
    assert selected_endpoints[0] is not None


def test_public_mount_skips_guard(app: Calango) -> None:
    child = FastAPI()
    guarded_endpoints = []

    @child.get("/")
    async def root() -> dict[str, bool]:
        return {"ok": True}

    async def deny(request: Request) -> None:
        guarded_endpoints.append(request.scope["endpoint"])
        raise AuthenticationError("Authentication required")

    app.add_request_guard(deny)
    app.mount("/docs-app", child, public=True)

    assert TestClient(app).get("/docs-app/").status_code == 200
    assert guarded_endpoints == []


def test_private_mount_preserves_root_path_and_streaming(app: Calango) -> None:
    child = FastAPI()
    guard_root_paths = []

    async def allow(request: Request) -> None:
        guard_root_paths.append(request.scope["root_path"])

    async def chunks() -> AsyncIterator[bytes]:
        yield b"first"
        yield b"-second"

    @child.get("/stream")
    async def stream(request: Request) -> StreamingResponse:
        assert request.scope["root_path"] == "/proxy/child"
        return StreamingResponse(chunks(), media_type="text/plain")

    app.add_request_guard(allow)
    app.mount("/child", child)

    response = TestClient(app, root_path="/proxy").get("/proxy/child/stream")

    assert response.status_code == 200
    assert response.content == b"first-second"
    assert guard_root_paths == ["/proxy/child"]


def test_websocket_scope_is_not_guarded(app: Calango) -> None:
    guard_calls = []

    async def deny(request: Request) -> None:
        guard_calls.append(request.scope.get("endpoint"))
        raise AuthenticationError("Authentication required")

    app.add_request_guard(deny)

    @app.websocket("/ws")
    async def websocket(socket: WebSocket) -> None:
        await socket.accept()
        await socket.send_text("ok")
        await socket.close()

    with TestClient(app).websocket_connect("/ws") as socket:
        assert socket.receive_text() == "ok"

    assert guard_calls == []


def test_guard_registration_is_rejected_after_startup_begins(app: Calango) -> None:
    async def allow(_request: Request) -> None:
        pass

    with TestClient(app):
        with pytest.raises(RuntimeError, match="startup"):
            app.add_request_guard(allow)

    with pytest.raises(RuntimeError, match="startup"):
        app.add_request_guard(allow)
