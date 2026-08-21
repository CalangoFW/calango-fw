from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from calango_plugin_base import PluginBase
from fastapi import APIRouter, Depends, FastAPI
from starlette.types import ASGIApp

from calango.config import CalangoSettings, SecuritySettings
from calango.core.database import DatabaseRuntime
from calango.core.guards import (
    RequestGuard,
    RequestGuardMiddleware,
    guarded_router_overlay,
    request_guard_dependency,
)
from calango.core.handlers import calango_exception_handler, unhandled_exception_handler
from calango.core.middleware import CalangoMiddleware
from calango.exceptions import CalangoException


class Calango(FastAPI):
    def __init__(self, settings: CalangoSettings | None = None, **kwargs: Any) -> None:
        self._request_guards: tuple[RequestGuard, ...] = ()
        self._public_mount_paths: tuple[str, ...] = ()
        self._startup_started = False

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

        self.router.middleware_stack = RequestGuardMiddleware(
            self.router.app,
            lambda: self._public_mount_paths,
            lambda: self.router.routes,
            self,
        )

        self.settings = settings
        self.database = DatabaseRuntime(settings)

        application_lifespan = self.router.lifespan_context

        @asynccontextmanager
        async def lifespan(app: Calango):
            app._startup_started = True
            await app.database.start()
            try:
                async with application_lifespan(app) as state:
                    yield state
            finally:
                await app.database.close()

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

    def include_router(self, router: APIRouter, **kwargs: Any) -> None:
        overlay = guarded_router_overlay(router)
        if overlay.routes:
            super().include_router(overlay, **kwargs)
        super().include_router(router, **kwargs)

    def mount(  # ty: ignore[invalid-method-override]
        self,
        path: str,
        app: ASGIApp,
        *,
        public: bool = False,
        name: str | None = None,
    ) -> None:
        mount_path = path.rstrip("/")
        if public:
            self._public_mount_paths = (*self._public_mount_paths, mount_path)

        super().mount(path, app, name=name)

    def include_plugin(self, plugin: PluginBase) -> None:
        """Register a Calango plugin. Calls plugin.register(self)."""
        if not isinstance(plugin, PluginBase):
            raise TypeError(
                f"{type(plugin).__name__} does not implement PluginBase. "
                "All 5 methods (register, migrations, settings, "
                "test_fixtures, context_md) must be defined."
            )
        plugin.register(self)
