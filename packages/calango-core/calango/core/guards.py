from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass
from functools import update_wrapper
from typing import Any

from fastapi import Depends
from fastapi.routing import APIRoute, APIRouter
from starlette.datastructures import URLPath
from starlette.requests import HTTPConnection, Request
from starlette.routing import BaseRoute, Match, Mount, NoMatchFound, Route, WebSocketRoute
from starlette.types import ASGIApp, Message, Receive, Scope, Send

RequestGuard = Callable[[Request], Awaitable[None]]
DependencyRequestGuard = Callable[[Request, Any], Awaitable[None]]
RequestGuardResolver = Callable[[Request], Awaitable[Any]]
RequestGuardDependency = Callable[..., Any]
PublicMountProvider = Callable[[], tuple[Mount, ...]]
RouteProvider = Callable[[], list[BaseRoute]]

_GUARDED_OWNERS_SCOPE_KEY = "calango.request_guard_owners"
_DEPENDENCY_GUARDED_OWNERS_SCOPE_KEY = "calango.dependency_request_guard_owners"
_DYNAMIC_ROUTE_SCOPE_KEY = "calango.dynamic_guarded_route"
_UNRESOLVED_CONTEXT = object()
_HTTP_REQUEST_SCOPE = ContextVar("calango_http_request_scope", default=False)


@dataclass(frozen=True, slots=True)
class DependencyRequestGuardRegistration:
    """One FastAPI dependency plus its non-FastAPI resolver and guard."""

    guard: DependencyRequestGuard
    dependency: RequestGuardDependency
    resolver: RequestGuardResolver


class RequestGuardDependencyOverrides(dict[Callable[..., Any], Callable[..., Any]]):
    """Apply the guard context override only while handling an HTTP scope."""

    def __init__(
        self,
        context_dependency: RequestGuardDependency,
        initial: dict[Callable[..., Any], Callable[..., Any]],
    ) -> None:
        super().__init__(initial)
        self.context_dependency = context_dependency

    def get(self, key: Callable[..., Any], default: Any = None) -> Any:
        if key is self.context_dependency and not _HTTP_REQUEST_SCOPE.get():
            return default
        return super().get(key, default)


async def run_request_guards(request: Request, owner: Any) -> None:
    """Run simple request-only guards at most once for an application owner."""
    guarded_owners = request.scope.setdefault(_GUARDED_OWNERS_SCOPE_KEY, set())
    owner_id = id(owner)
    if owner_id in guarded_owners:
        return

    guarded_owners.add(owner_id)
    for guard in owner._request_guards:
        await guard(request)


async def run_dependency_request_guard(
    request: Request,
    owner: Any,
    context: Any,
) -> None:
    """Run the dependency-aware guard once with an already-resolved context."""
    registration = owner._dependency_request_guard
    if registration is None:
        return

    guarded_owners = request.scope.setdefault(_DEPENDENCY_GUARDED_OWNERS_SCOPE_KEY, set())
    owner_id = id(owner)
    if owner_id in guarded_owners:
        return

    guarded_owners.add(owner_id)
    await registration.guard(request, context)


async def run_external_request_guards(request: Request, owner: Any) -> None:
    """Resolve and run guards for Starlette routes and mounted applications."""
    await run_request_guards(request, owner)
    registration = owner._dependency_request_guard
    if registration is not None:
        context = await registration.resolver(request)
        await run_dependency_request_guard(request, owner, context)


def has_simple_request_guards(owner: Any) -> bool:
    return bool(owner._request_guards)


def has_external_request_guards(owner: Any) -> bool:
    return has_simple_request_guards(owner) or owner._dependency_request_guard is not None


def request_guard_dependency_boundary(
    owner: Any,
) -> tuple[Callable[..., Awaitable[None]], RequestGuardDependency]:
    """Build the fixed FastAPI DI boundary and its app-local override point."""

    async def unresolved_context() -> Any:
        return _UNRESOLVED_CONTEXT

    async def request_guard_dependency(
        connection: HTTPConnection,
        context: Any = Depends(unresolved_context),  # noqa: B008
    ) -> None:
        if not isinstance(connection, Request):
            return

        await run_request_guards(connection, owner)
        if owner._dependency_request_guard is not None:
            if context is _UNRESOLVED_CONTEXT:
                raise RuntimeError("Dependency request guard context was not resolved")
            await run_dependency_request_guard(connection, owner, context)

    return request_guard_dependency, unresolved_context


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
        owner: Any,
        *,
        endpoint: Any | None = None,
    ) -> None:
        self.app = app
        self.owner = owner
        if endpoint is not None:
            update_wrapper(self, endpoint)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not has_external_request_guards(self.owner):
            await self.app(scope, receive, send)
            return

        replayable_receive = ReplayableReceive(receive)
        request = Request(scope, receive=replayable_receive)
        await run_external_request_guards(request, self.owner)
        replayable_receive.replay()
        await self.app(scope, replayable_receive, send)


class RoutedASGIApp:
    """Delegate to an existing Route app while retaining endpoint metadata."""

    def __init__(self, app: ASGIApp, endpoint: Any) -> None:
        self.app = app
        update_wrapper(self, endpoint)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self.app(scope, receive, send)


def guarded_router_overlay(router: APIRouter, owner: Any) -> APIRouter:
    """Snapshot routes in order, guarding included Starlette Route and Mount entries."""

    guarded_routes: list[BaseRoute] = []
    for route in router.routes:
        if isinstance(route, (APIRoute, WebSocketRoute)):
            guarded_routes.append(route)
            continue

        if isinstance(route, Route):
            endpoint = GuardedASGIApp(route.app, owner, endpoint=route.endpoint)
            guarded_routes.append(
                Route(
                    route.path,
                    endpoint=endpoint,
                    methods=route.methods,
                    name=route.name,
                    include_in_schema=route.include_in_schema,
                )
            )
            continue

        if isinstance(route, Mount):
            guarded_app = GuardedASGIApp(route.app, owner)
            guarded_routes.append(Mount(route.path, app=guarded_app, name=route.name))
            continue

        guarded_routes.append(route)

    return APIRouter(routes=guarded_routes)


class GuardedRouterUpdates(BaseRoute):
    """Route Starlette entries appended after an APIRouter was included.

    The overlay observes only the router's public ``routes`` list and never mutates
    the caller-owned router. API routes are matched only to preserve source order;
    FastAPI's included-router boundary remains responsible for handling them.
    """

    def __init__(
        self,
        router: APIRouter,
        owner: Any,
        *,
        prefix: str,
        existing_route_ids: frozenset[int],
    ) -> None:
        self.router = router
        self.owner = owner
        self.prefix = prefix
        self.existing_route_ids = existing_route_ids

    def _candidate(self, route: BaseRoute) -> tuple[BaseRoute, bool] | None:
        path = getattr(route, "path", None)
        if path is None:
            return None
        prefixed_path = f"{self.prefix}{path}"

        if isinstance(route, APIRoute):
            return (
                Route(
                    prefixed_path,
                    endpoint=route.endpoint,
                    methods=route.methods,
                    name=route.name,
                ),
                False,
            )
        if isinstance(route, WebSocketRoute):
            return None
        if isinstance(route, Route):
            return (
                Route(
                    prefixed_path,
                    endpoint=RoutedASGIApp(route.app, route.endpoint),
                    methods=route.methods,
                    name=route.name,
                    include_in_schema=route.include_in_schema,
                ),
                True,
            )
        if isinstance(route, Mount):
            return Mount(prefixed_path, app=route.app, name=route.name), True
        return None

    def _late_candidates(self) -> list[tuple[BaseRoute, bool]]:
        candidates: list[tuple[BaseRoute, bool]] = []
        for route in self.router.routes:
            if id(route) in self.existing_route_ids:
                continue
            candidate = self._candidate(route)
            if candidate is not None:
                candidates.append(candidate)
        return candidates

    def matches(self, scope: Scope) -> tuple[Match, Scope]:
        partial: tuple[BaseRoute, bool, Scope] | None = None

        for candidate, handles_route in self._late_candidates():
            match, child_scope = candidate.matches(scope)
            if match == Match.FULL:
                if not handles_route:
                    return Match.NONE, {}
                child_scope[_DYNAMIC_ROUTE_SCOPE_KEY] = candidate
                return match, child_scope
            if match == Match.PARTIAL and partial is None:
                partial = candidate, handles_route, child_scope

        if partial is None:
            return Match.NONE, {}
        candidate, handles_route, child_scope = partial
        if not handles_route:
            return Match.NONE, {}
        child_scope[_DYNAMIC_ROUTE_SCOPE_KEY] = candidate
        return Match.PARTIAL, child_scope

    def url_path_for(self, name: str, /, **path_params: Any) -> URLPath:
        for candidate, handles_route in self._late_candidates():
            try:
                path = candidate.url_path_for(name, **path_params)
            except NoMatchFound:
                continue
            if handles_route:
                return path
            break
        raise NoMatchFound(name, path_params)

    async def handle(self, scope: Scope, receive: Receive, send: Send) -> None:
        candidate = scope.pop(_DYNAMIC_ROUTE_SCOPE_KEY)
        await candidate.handle(scope, receive, send)


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
        token = _HTTP_REQUEST_SCOPE.set(scope["type"] == "http")
        try:
            await self._dispatch(scope, receive, send)
        finally:
            _HTTP_REQUEST_SCOPE.reset(token)

    async def _dispatch(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        route, child_scope = self._match(scope)
        is_public_mount = isinstance(route, Mount) and any(
            route is public_mount for public_mount in self.public_mount_provider()
        )
        if route is None or "endpoint" not in child_scope or is_public_mount:
            await self.app(scope, receive, send)
            return

        is_api_route = isinstance(route, APIRoute)
        should_run = (
            has_simple_request_guards(self.owner)
            if is_api_route
            else has_external_request_guards(self.owner)
        )
        if not should_run:
            await self.app(scope, receive, send)
            return

        scope.setdefault(_GUARDED_OWNERS_SCOPE_KEY, set())
        routed_scope = dict(scope)
        routed_scope.update(child_scope)
        replayable_receive = ReplayableReceive(receive)
        request = Request(routed_scope, receive=replayable_receive)
        if is_api_route:
            await run_request_guards(request, self.owner)
        else:
            await run_external_request_guards(request, self.owner)
        replayable_receive.replay()
        await self.app(scope, replayable_receive, send)
