from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from typing import Any

from calango_plugin_base import PluginBase
from fastapi import Depends, FastAPI
from starlette.routing import Mount
from starlette.types import ASGIApp

from calango.config import CalangoSettings, SecuritySettings
from calango.core.database import DatabaseRuntime
from calango.core.guards import (
    DependencyRequestGuard,
    DependencyRequestGuardRegistration,
    RequestGuard,
    RequestGuardDependency,
    RequestGuardDependencyOverrides,
    RequestGuardMiddleware,
    RequestGuardResolver,
    request_guard_dependency_boundary,
)
from calango.core.handlers import calango_exception_handler, unhandled_exception_handler
from calango.core.middleware import CalangoMiddleware
from calango.exceptions import CalangoException

PluginLifespan = Callable[["Calango"], AbstractAsyncContextManager[Any]]


class Calango(FastAPI):
    def __init__(self, settings: CalangoSettings | None = None, **kwargs: Any) -> None:
        self._request_guards: tuple[RequestGuard, ...] = ()
        self._dependency_request_guard: DependencyRequestGuardRegistration | None = None
        self._public_mounts: tuple[Mount, ...] = ()
        self._plugin_lifespans: tuple[PluginLifespan, ...] = ()
        self._startup_started = False

        request_guard_dependency, self._request_guard_context_dependency = (
            request_guard_dependency_boundary(self)
        )

        if settings is None:
            settings = CalangoSettings(security=SecuritySettings(SECRET_KEY="changeme"))  # noqa: S106

        kwargs.setdefault("title", settings.APP_NAME)
        kwargs.setdefault("version", settings.VERSION)
        application_dependencies = list(kwargs.pop("dependencies", ()) or ())
        kwargs["dependencies"] = [
            Depends(request_guard_dependency),
            *application_dependencies,
        ]

        super().__init__(**kwargs)

        request_guard_dependency_overrides = RequestGuardDependencyOverrides(
            self._request_guard_context_dependency,
            self.dependency_overrides,
        )
        self.dependency_overrides = request_guard_dependency_overrides
        self._request_guard_dependency_overrides = request_guard_dependency_overrides

        self.router.middleware_stack = RequestGuardMiddleware(
            self.router.app,
            lambda: self._public_mounts,
            lambda: self.router.routes,
            self,
            request_guard_dependency,
        )

        self.settings = settings
        self.database = DatabaseRuntime(settings)

        application_lifespan = self.router.lifespan_context

        @asynccontextmanager
        async def lifespan(app: Calango):
            app._startup_started = True
            async with AsyncExitStack() as framework_resources:
                framework_resources.push_async_callback(app.database.close)
                await app.database.start()
                for plugin_lifespan in app._plugin_lifespans:
                    await framework_resources.enter_async_context(plugin_lifespan(app))
                async with application_lifespan(app) as state:
                    yield state

        self.router.lifespan_context = lifespan

        self.add_middleware(CalangoMiddleware)

        # Starlette types handlers as (Request, Exception); ours narrow the second
        # param to CalangoException. The narrowing is safe but unexpressible here.
        self.add_exception_handler(CalangoException, calango_exception_handler)  # ty: ignore[invalid-argument-type]
        self.add_exception_handler(Exception, unhandled_exception_handler)

    def add_request_guard(self, guard: RequestGuard) -> None:
        if self._startup_started:
            raise RuntimeError("Request guards cannot be registered after startup begins")
        self._request_guards = (*self._request_guards, guard)

    def add_plugin_lifespan(self, lifespan: PluginLifespan) -> None:
        """Enter a plugin resource before user startup and close it afterward."""
        if self._startup_started:
            raise RuntimeError("Plugin lifespans cannot be registered after startup begins")
        self._plugin_lifespans = (*self._plugin_lifespans, lifespan)

    def add_dependency_request_guard(
        self,
        guard: DependencyRequestGuard,
        *,
        dependency: RequestGuardDependency,
        resolver: RequestGuardResolver,
    ) -> None:
        """Register one guard with a dependency-resolved authentication context.

        FastAPI resolves ``dependency`` (including nested ``Depends``) for every
        ``APIRoute``. For Starlette ``Route`` and ``Mount`` boundaries, Calango
        awaits ``resolver(request)``. The resulting value is passed to ``guard``
        as its second argument in both cases, so authentication parsing stays in
        the registered dependency/resolver rather than being repeated by guards.
        """
        if self._startup_started:
            raise RuntimeError(
                "Dependency request guards cannot be registered after startup begins"
            )
        if self._dependency_request_guard is not None:
            raise RuntimeError("A dependency request guard is already registered")

        self._dependency_request_guard = DependencyRequestGuardRegistration(
            guard=guard,
            dependency=dependency,
            resolver=resolver,
        )
        self._request_guard_dependency_overrides.set_context_override(dependency)

    def mount(  # ty: ignore[invalid-method-override]
        self,
        path: str,
        app: ASGIApp,
        *,
        public: bool = False,
        name: str | None = None,
    ) -> None:
        super().mount(path, app, name=name)
        mounted_route = self.router.routes[-1]
        if public and isinstance(mounted_route, Mount):
            self._public_mounts = (*self._public_mounts, mounted_route)

    def include_plugin(self, plugin: PluginBase) -> None:
        """Register a Calango plugin. Calls plugin.register(self)."""
        if not isinstance(plugin, PluginBase):
            raise TypeError(
                f"{type(plugin).__name__} does not implement PluginBase. "
                "All 6 methods (register, import_models, migrations, settings, "
                "test_fixtures, context_md) must be defined."
            )
        plugin.register(self)
