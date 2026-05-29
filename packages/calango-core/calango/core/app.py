from __future__ import annotations

from calango_plugin_base import PluginBase
from fastapi import FastAPI

from calango.config import CalangoSettings, SecuritySettings
from calango.core.handlers import calango_exception_handler, unhandled_exception_handler
from calango.core.middleware import CalangoMiddleware
from calango.exceptions import CalangoException


class Calango(FastAPI):
    def __init__(self, settings: CalangoSettings | None = None, **kwargs: object) -> None:
        if settings is None:
            settings = CalangoSettings(security=SecuritySettings(SECRET_KEY="changeme"))  # noqa: S106

        kwargs.setdefault("title", settings.APP_NAME)
        kwargs.setdefault("version", settings.VERSION)

        super().__init__(**kwargs)

        self.settings = settings

        self.add_middleware(CalangoMiddleware)

        self.add_exception_handler(CalangoException, calango_exception_handler)  # type: ignore[arg-type]
        self.add_exception_handler(Exception, unhandled_exception_handler)

    def include_plugin(self, plugin: PluginBase) -> None:
        """Register a Calango plugin. Calls plugin.register(self)."""
        if not isinstance(plugin, PluginBase):
            raise TypeError(
                f"{type(plugin).__name__} does not implement PluginBase. "
                "All 5 methods (register, migrations, settings, "
                "test_fixtures, context_md) must be defined."
            )
        plugin.register(self)
