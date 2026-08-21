from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import update_wrapper
from typing import Any

from fastapi.routing import APIRoute
from starlette.requests import HTTPConnection, Request
from starlette.routing import BaseRoute, Match, Mount, Route, WebSocketRoute
from starlette.types import ASGIApp, Message, Receive, Scope, Send

RequestGuard = Callable[[Request], Awaitable[None]]
PublicMountProvider = Callable[[], tuple[str, ...]]
RouteProvider = Callable[[], list[BaseRoute]]
_GUARDED_OWNERS_SCOPE_KEY = "calango.request_guard_owners"


async def run_request_guards(request: Request, owner: Any) -> None:
    guarded_owners = request.scope.setdefault(_GUARDED_OWNERS_SCOPE_KEY, set())
    owner_id = id(owner)
    if owner_id in guarded_owners:
        return

    guarded_owners.add(owner_id)
    for guard in owner._request_guards:
        await guard(request)


async def request_guard_dependency(connection: HTTPConnection) -> None:
    """Dispatch guards for FastAPI routes, including nested APIRouters."""

    if isinstance(connection, Request):
        await run_request_guards(connection, connection.scope["app"])


class ReplayableReceive:
    """Replay messages consumed by a guard before continuing the ASGI stream."""

    def __init__(self, receive: Receive) -> None:
        self.receive = receive
        self.messages: list[Message] = []
        self.replay_index: int | None = None

    async def __call__(self) -> Message:
        if self.replay_index is not None and self.replay_index < len(self.messages):
            message = self.messages[self.replay_index]
            self.replay_index += 1
            return message

        message = await self.receive()
        if self.replay_index is None:
            self.messages.append(message)
        return message

    def replay(self) -> None:
        self.replay_index = 0


class GuardedASGIApp:
    """Run guards with a routed request, then delegate without consuming its body."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        endpoint: Any | None = None,
        routes: list[BaseRoute] | None = None,
    ) -> None:
        self.app = app
        self.routes = routes
        if endpoint is not None:
            update_wrapper(self, endpoint)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        replayable_receive = ReplayableReceive(receive)
        request = Request(scope, receive=replayable_receive)
        await run_request_guards(request, scope["app"])
        replayable_receive.replay()
        await self.app(scope, replayable_receive, send)


def guard_included_router_routes(routes: list[BaseRoute]) -> None:
    """Guard Starlette Route and Mount entries in an included APIRouter."""

    for index, route in enumerate(routes):
        if isinstance(route, (APIRoute, WebSocketRoute)):
            continue

        if isinstance(route, Route):
            if isinstance(route.endpoint, GuardedASGIApp):
                continue
            endpoint = GuardedASGIApp(route.app, endpoint=route.endpoint)
            routes[index] = Route(
                route.path,
                endpoint=endpoint,
                methods=route.methods,
                name=route.name,
                include_in_schema=route.include_in_schema,
            )
            continue

        if isinstance(route, Mount) and not isinstance(route.app, GuardedASGIApp):
            guarded_app = GuardedASGIApp(route.app, routes=route.routes)
            routes[index] = Mount(route.path, app=guarded_app, name=route.name)


class RequestGuardMiddleware:
    """Run application guards after Starlette has selected an HTTP route."""

    def __init__(
        self,
        app: ASGIApp,
        public_mount_provider: PublicMountProvider,
        route_provider: RouteProvider,
        owner: Any,
    ) -> None:
        self.app = app
        self.public_mount_provider = public_mount_provider
        self.route_provider = route_provider
        self.owner = owner

    def _match(self, scope: Scope) -> tuple[BaseRoute | None, Scope]:
        partial: tuple[BaseRoute, Scope] | None = None

        for route in self.route_provider():
            match, child_scope = route.matches(scope)
            if match == Match.FULL:
                return route, child_scope
            if match == Match.PARTIAL and partial is None:
                partial = (route, child_scope)

        if partial is not None:
            return partial
        return None, {}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        replayable_receive = ReplayableReceive(receive)
        if scope["type"] == "http":
            route, child_scope = self._match(scope)
            is_public_mount = (
                isinstance(route, Mount) and route.path in self.public_mount_provider()
            )
            if route is not None and "endpoint" in child_scope and not is_public_mount:
                scope.setdefault(_GUARDED_OWNERS_SCOPE_KEY, set())
                routed_scope = dict(scope)
                routed_scope.update(child_scope)
                request = Request(routed_scope, receive=replayable_receive)
                await run_request_guards(request, self.owner)
                replayable_receive.replay()

        await self.app(scope, replayable_receive, send)
