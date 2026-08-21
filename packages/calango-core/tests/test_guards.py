from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi import APIRouter, Depends, FastAPI, Request, WebSocket
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.testclient import TestClient
from starlette.routing import Mount

from calango.config import CalangoSettings, SecuritySettings
from calango.core.app import Calango
from calango.core.guards import RequestGuardMiddleware
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


def test_guard_covers_starlette_routes_and_mounts_added_after_router_inclusion(
    app: Calango,
) -> None:
    router = APIRouter()
    child = FastAPI()
    guarded_paths = []

    @child.get("/")
    async def child_root() -> dict[str, bool]:
        return {"ok": True}

    async def deny(request: Request) -> None:
        guarded_paths.append(request.url.path)
        raise AuthenticationError("Authentication required")

    app.add_request_guard(deny)
    app.include_router(router, prefix="/included")

    async def late_route(_request: Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    router.add_route("/late-route", late_route)
    router.mount("/late-mount", child)

    client = TestClient(app)

    assert client.get("/included/late-route").status_code == 401
    assert client.get("/included/late-mount/").status_code == 401
    assert guarded_paths == [
        "/included/late-route",
        "/included/late-mount/",
    ]


def test_include_router_does_not_mutate_router_reused_by_plain_fastapi(
    app: Calango,
) -> None:
    router = APIRouter()
    child = FastAPI()

    @router.get("/api-route")
    async def api_route() -> dict[str, str]:
        return {"kind": "api"}

    async def starlette_route(_request: Request) -> JSONResponse:
        return JSONResponse({"kind": "starlette"})

    @child.get("/")
    async def mounted_route() -> dict[str, str]:
        return {"kind": "mount"}

    router.add_route("/starlette-route", starlette_route)
    router.mount("/mounted", child)
    original_routes = tuple(router.routes)

    async def allow(_request: Request) -> None:
        pass

    app.add_request_guard(allow)
    app.include_router(router)

    plain_app = FastAPI()
    plain_app.include_router(router)
    plain_client = TestClient(plain_app, raise_server_exceptions=False)

    assert plain_client.get("/api-route").status_code == 200
    assert plain_client.get("/starlette-route").status_code == 200
    assert plain_client.get("/mounted/").status_code == 200
    assert len(router.routes) == len(original_routes)
    assert all(
        current is original
        for current, original in zip(router.routes, original_routes, strict=True)
    )


def test_include_router_preserves_api_route_precedence_over_later_starlette_route(
    app: Calango,
) -> None:
    router = APIRouter()

    @router.api_route("/collision", methods=["GET", "HEAD"])
    async def api_route() -> JSONResponse:
        return JSONResponse({"kind": "api"}, headers={"x-route-kind": "api"})

    async def starlette_route(_request: Request) -> JSONResponse:
        return JSONResponse({"kind": "starlette"}, headers={"x-route-kind": "starlette"})

    router.add_route("/collision", starlette_route)
    app.include_router(router)

    assert TestClient(app).head("/collision").headers["x-route-kind"] == "api"


def test_include_router_preserves_starlette_route_precedence_over_later_api_route(
    app: Calango,
) -> None:
    router = APIRouter()

    async def starlette_route(_request: Request) -> JSONResponse:
        return JSONResponse({"kind": "starlette"}, headers={"x-route-kind": "starlette"})

    router.add_route("/collision", starlette_route)

    @router.api_route("/collision", methods=["GET", "HEAD"])
    async def api_route() -> JSONResponse:
        return JSONResponse({"kind": "api"}, headers={"x-route-kind": "api"})

    app.include_router(router)

    assert TestClient(app).head("/collision").headers["x-route-kind"] == "starlette"


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


def test_public_mount_policy_is_bound_to_the_exact_mount_instance(app: Calango) -> None:
    private_child = FastAPI()
    public_child = FastAPI()

    @private_child.get("/")
    async def private_root() -> dict[str, str]:
        return {"mount": "private"}

    @public_child.get("/")
    async def public_root() -> dict[str, str]:
        return {"mount": "public"}

    async def deny(_request: Request) -> None:
        raise AuthenticationError("Authentication required")

    app.add_request_guard(deny)
    app.mount("/collision", private_child)
    app.mount("/collision", public_child, public=True)

    assert TestClient(app).get("/collision/").status_code == 401


@pytest.mark.parametrize(
    ("scope", "routes", "public_mounts"),
    [
        (
            {
                "type": "http",
                "method": "GET",
                "path": "/missing",
                "root_path": "",
                "headers": [],
                "query_string": b"",
            },
            [],
            (),
        ),
        (
            {
                "type": "websocket",
                "path": "/ws",
                "root_path": "",
                "headers": [],
                "query_string": b"",
                "scheme": "ws",
            },
            [],
            (),
        ),
    ],
    ids=["not-found", "websocket"],
)
async def test_unguarded_scopes_keep_original_receive(scope, routes, public_mounts) -> None:
    receives_seen = []
    guard_calls = []

    async def downstream(_scope, receive, _send) -> None:
        receives_seen.append(receive)

    async def original_receive():
        return {"type": "http.disconnect"}

    async def send(_message) -> None:
        pass

    async def guard(request: Request) -> None:
        guard_calls.append(request.url.path)

    owner = type(
        "GuardOwner",
        (),
        {"_request_guards": (guard,), "_dependency_request_guard": None},
    )()
    middleware = RequestGuardMiddleware(
        downstream,
        lambda: public_mounts,
        lambda: routes,
        owner,
    )

    await middleware(scope, original_receive, send)

    assert receives_seen == [original_receive]
    assert guard_calls == []


async def test_public_mount_keeps_original_receive() -> None:
    receives_seen = []
    guard_calls = []

    async def child(_scope, receive, _send) -> None:
        receives_seen.append(receive)

    async def original_receive():
        return {"type": "http.disconnect"}

    async def send(_message) -> None:
        pass

    async def guard(request: Request) -> None:
        guard_calls.append(request.url.path)

    mount = Mount("/public", app=child)
    owner = type(
        "GuardOwner",
        (),
        {"_request_guards": (guard,), "_dependency_request_guard": None},
    )()
    middleware = RequestGuardMiddleware(
        child,
        lambda: (mount,),
        lambda: [mount],
        owner,
    )
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/public/resource",
        "root_path": "",
        "headers": [],
        "query_string": b"",
        "scheme": "http",
    }

    await middleware(scope, original_receive, send)

    assert receives_seen == [original_receive]
    assert guard_calls == []


def test_dependency_request_guard_uses_fastapi_dependency_and_mount_resolver(
    app: Calango,
) -> None:
    parse_calls = []
    guard_contexts = []

    def parse_token(request: Request) -> str | None:
        parse_calls.append(request.url.path)
        return request.headers.get("authorization")

    async def token_dependency(request: Request) -> str | None:
        return parse_token(request)

    async def dependency_context(
        token: str | None = Depends(token_dependency),
    ) -> str | None:
        return token

    async def route_resolver(request: Request) -> str | None:
        return parse_token(request)

    async def require_token(request: Request, context: object) -> None:
        guard_contexts.append((request.url.path, context))
        if context != "Bearer allowed":
            raise AuthenticationError("Authentication required")

    @app.get("/api-route")
    async def api_route() -> dict[str, bool]:
        return {"ok": True}

    async def starlette_route(_request: Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    app.add_route("/starlette-route", starlette_route)

    app.add_dependency_request_guard(
        require_token,
        dependency=dependency_context,
        resolver=route_resolver,
    )

    child = FastAPI()

    @child.get("/")
    async def child_root() -> dict[str, bool]:
        return {"ok": True}

    app.mount("/mounted", child)
    client = TestClient(app)

    assert client.get("/api-route").status_code == 401
    assert client.get("/api-route", headers={"Authorization": "Bearer allowed"}).status_code == 200
    assert client.get("/starlette-route").status_code == 401
    assert (
        client.get("/starlette-route", headers={"Authorization": "Bearer allowed"}).status_code
        == 200
    )
    assert client.get("/mounted/").status_code == 401
    assert client.get("/mounted/", headers={"Authorization": "Bearer allowed"}).status_code == 200
    assert parse_calls == [
        "/api-route",
        "/api-route",
        "/starlette-route",
        "/starlette-route",
        "/mounted/",
        "/mounted/",
    ]
    assert guard_contexts == [
        ("/api-route", None),
        ("/api-route", "Bearer allowed"),
        ("/starlette-route", None),
        ("/starlette-route", "Bearer allowed"),
        ("/mounted/", None),
        ("/mounted/", "Bearer allowed"),
    ]


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


def test_dependency_request_guard_does_not_resolve_for_websocket(app: Calango) -> None:
    context_calls = []

    async def dependency(request: Request) -> object:
        context_calls.append(("dependency", request.url.path))
        return object()

    async def resolver(request: Request) -> object:
        context_calls.append(("resolver", request.url.path))
        return object()

    async def guard(request: Request, _context: object) -> None:
        context_calls.append(("guard", request.url.path))

    app.add_dependency_request_guard(
        guard,
        dependency=dependency,
        resolver=resolver,
    )

    @app.websocket("/dependency-ws")
    async def websocket(socket: WebSocket) -> None:
        await socket.accept()
        await socket.send_text("ok")
        await socket.close()

    with TestClient(app).websocket_connect("/dependency-ws") as socket:
        assert socket.receive_text() == "ok"

    assert context_calls == []


def test_guard_registration_is_rejected_after_startup_begins(app: Calango) -> None:
    async def allow(_request: Request) -> None:
        pass

    with TestClient(app):
        with pytest.raises(RuntimeError, match="startup"):
            app.add_request_guard(allow)

    with pytest.raises(RuntimeError, match="startup"):
        app.add_request_guard(allow)
