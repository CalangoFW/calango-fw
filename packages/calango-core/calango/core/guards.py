from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from fastapi import Depends
from fastapi.routing import APIRoute, RouteContext, iter_route_contexts
from starlette.requests import HTTPConnection, Request
from starlette.routing import BaseRoute, Match, Mount
from starlette.types import ASGIApp, Message, Receive, Scope, Send

RequestGuard = Callable[[Request], Awaitable[None]]
DependencyRequestGuard = Callable[[Request, Any], Awaitable[None]]
RequestGuardResolver = Callable[[Request], Awaitable[Any]]
RequestGuardDependency = Callable[..., Any]
PublicMountProvider = Callable[[], tuple[Mount, ...]]
RouteProvider = Callable[[], list[BaseRoute]]

_GUARDED_OWNERS_SCOPE_KEY = "calango.request_guard_owners"
_DEPENDENCY_GUARDED_OWNERS_SCOPE_KEY = "calango.dependency_request_guard_owners"
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
        self._context_override: RequestGuardDependency | None = None

    def set_context_override(self, dependency: RequestGuardDependency) -> None:
        """Set framework-owned state outside the public override mapping."""
        self._context_override = dependency

    def __bool__(self) -> bool:
        return self._context_override is not None or super().__len__() > 0

    def get(self, key: Callable[..., Any], default: Any = None) -> Any:
        if key is self.context_dependency:
            if not _HTTP_REQUEST_SCOPE.get() or self._context_override is None:
                return default
            # A public override of the registered dependency (e.g. a test user)
            # supplies the guard context; clearing public overrides restores it.
            return super().get(self._context_override, self._context_override)
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


class RequestGuardMiddleware:
    """Run application guards for the HTTP route FastAPI will select.

    Matching walks FastAPI's effective route tree, so routes on included, nested
    and late-extended routers resolve exactly as FastAPI dispatches them. API
    routes that carry the guard dependency receive it through FastAPI DI; every
    other boundary (Starlette routes, private mounts, API routes added without
    the application dependencies) receives it here, so no route fails open.
    Scope keys a guard adds are copied to the downstream scope.
    """

    def __init__(
        self,
        app: ASGIApp,
        public_mount_provider: PublicMountProvider,
        route_provider: RouteProvider,
        owner: Any,
        guard_dependency: RequestGuardDependency,
    ) -> None:
        self.app = app
        self.public_mount_provider = public_mount_provider
        self.route_provider = route_provider
        self.owner = owner
        self.guard_dependency = guard_dependency

    def _match(self, scope: Scope) -> tuple[RouteContext | None, Scope]:
        partial: tuple[RouteContext, Scope] | None = None

        for route_context in iter_route_contexts(self.route_provider()):
            match, child_scope = route_context.matches(scope)
            if match == Match.FULL:
                return route_context, child_scope
            if match == Match.PARTIAL and partial is None:
                partial = (route_context, child_scope)

        if partial is not None:
            return partial
        return None, {}

    def _guarded_by_dependency(self, route_context: RouteContext) -> bool:
        """Return whether FastAPI DI will run the guard boundary for this route."""
        if not isinstance(route_context.original_route, APIRoute):
            return False
        return any(
            getattr(dependency, "dependency", None) is self.guard_dependency
            for dependency in route_context.dependencies
        )

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

        route_context, child_scope = self._match(scope)
        route = None if route_context is None else route_context.original_route
        is_public_mount = isinstance(route, Mount) and any(
            route is public_mount for public_mount in self.public_mount_provider()
        )
        if route_context is None or "endpoint" not in child_scope or is_public_mount:
            await self.app(scope, receive, send)
            return

        guarded_by_dependency = self._guarded_by_dependency(route_context)
        should_run = (
            has_simple_request_guards(self.owner)
            if guarded_by_dependency
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
        if guarded_by_dependency:
            await run_request_guards(request, self.owner)
        else:
            await run_external_request_guards(request, self.owner)
        scope.update(
            {
                key: value
                for key, value in routed_scope.items()
                if key not in scope and key not in child_scope
            }
        )
        replayable_receive.replay()
        await self.app(scope, replayable_receive, send)
