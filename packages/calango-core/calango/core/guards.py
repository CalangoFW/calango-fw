from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from starlette.requests import HTTPConnection, Request
from starlette.routing import BaseRoute, Match, Mount
from starlette.types import ASGIApp, Receive, Scope, Send

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
        if scope["type"] == "http":
            route, child_scope = self._match(scope)
            is_public_mount = (
                isinstance(route, Mount) and route.path in self.public_mount_provider()
            )
            if route is not None and "endpoint" in child_scope and not is_public_mount:
                scope.setdefault(_GUARDED_OWNERS_SCOPE_KEY, set())
                routed_scope = dict(scope)
                routed_scope.update(child_scope)
                request = Request(routed_scope, receive=receive)
                await run_request_guards(request, self.owner)

        await self.app(scope, receive, send)
