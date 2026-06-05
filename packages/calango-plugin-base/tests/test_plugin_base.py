from __future__ import annotations

from typing import ClassVar

from calango_plugin_base import PluginBase
from fastapi import FastAPI
from pydantic_settings import BaseSettings


class ValidPlugin:
    name: ClassVar[str] = "test"
    version: ClassVar[str] = "1.0.0"
    requires: ClassVar[list[str]] = []

    def register(self, app: FastAPI) -> None: ...
    def migrations(self) -> list[str]:
        return []

    def settings(self) -> type[BaseSettings]:
        return BaseSettings

    def test_fixtures(self) -> list:
        return []

    def context_md(self) -> str:
        return ""


class MissingMethodPlugin:
    name: ClassVar[str] = "bad"
    version: ClassVar[str] = "1.0.0"
    requires: ClassVar[list[str]] = []
    # missing all 5 methods


def test_valid_plugin_satisfies_protocol():
    """A class implementing all 5 methods passes isinstance check."""
    plugin = ValidPlugin()
    assert isinstance(plugin, PluginBase)


def test_missing_method_fails_isinstance():
    """A class missing protocol methods fails isinstance check."""
    plugin = MissingMethodPlugin()
    assert not isinstance(plugin, PluginBase)


def test_plugin_base_is_runtime_checkable():
    """PluginBase can be used in isinstance() at runtime."""
    plugin = ValidPlugin()
    result = isinstance(plugin, PluginBase)
    assert isinstance(result, bool)


def test_valid_plugin_name_attribute():
    """Plugin has name attribute."""
    assert ValidPlugin().name == "test"


def test_valid_plugin_version_attribute():
    """Plugin has version attribute."""
    assert ValidPlugin().version == "1.0.0"
