from __future__ import annotations

from typing import Protocol, runtime_checkable

from fastapi import FastAPI
from pydantic_settings import BaseSettings


@runtime_checkable
class PluginBase(Protocol):
    """Contract every Calango plugin must implement.

    Usage:
        class MyPlugin:
            name = "my-plugin"
            version = "1.0.0"
            requires: list[str] = []

            def register(self, app: FastAPI) -> None:
                app.include_router(my_router)

            def migrations(self) -> list[str]:
                return ["my_plugin.migrations"]

            def settings(self) -> type[BaseSettings]:
                return MyPluginSettings

            def test_fixtures(self) -> list:
                return [my_fixture]

            def context_md(self) -> str:
                return "## Plugin: My Plugin\\n..."
    """

    name: str
    version: str
    requires: list[str]

    def register(self, app: FastAPI) -> None:
        """Register routers, middleware, exception handlers, lifecycle hooks."""
        ...

    def migrations(self) -> list[str]:
        """Return Alembic migration module paths contributed by this plugin."""
        ...

    def settings(self) -> type[BaseSettings]:
        """Return the plugin's pydantic-settings class."""
        ...

    def test_fixtures(self) -> list:
        """Return pytest fixtures injected into projects using this plugin."""
        ...

    def context_md(self) -> str:
        """Return a CLAUDE.md markdown block describing this plugin."""
        ...


__all__ = ["PluginBase"]
