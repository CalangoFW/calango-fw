from __future__ import annotations

import pytest
from calango_identity.plugin import IdentityPlugin
from calango_identity.settings import IdentitySettings
from calango_plugin_base import PluginBase
from fastapi import FastAPI

from tests.conftest import TEST_PRIVATE_KEY, TEST_PUBLIC_KEY


@pytest.fixture
def settings() -> IdentitySettings:
    return IdentitySettings(PRIVATE_KEY=TEST_PRIVATE_KEY, PUBLIC_KEY=TEST_PUBLIC_KEY)


def test_identity_plugin_implements_plugin_base(settings):
    """IdentityPlugin satisfies the PluginBase Protocol."""
    plugin = IdentityPlugin(settings=settings)
    assert isinstance(plugin, PluginBase)


def test_identity_plugin_name(settings):
    """IdentityPlugin.name is 'identity'."""
    plugin = IdentityPlugin(settings=settings)
    assert plugin.name == "identity"


def test_identity_plugin_migrations(settings):
    """IdentityPlugin.migrations() returns a non-empty list."""
    plugin = IdentityPlugin(settings=settings)
    assert len(plugin.migrations()) > 0


def test_identity_plugin_settings_class(settings):
    """IdentityPlugin.settings() returns the IdentitySettings class."""
    plugin = IdentityPlugin(settings=settings)
    assert plugin.settings() is IdentitySettings


def test_identity_plugin_context_md_contains_identity(settings):
    """IdentityPlugin.context_md() returns a non-empty string mentioning identity."""
    plugin = IdentityPlugin(settings=settings)
    md = plugin.context_md()
    assert "identity" in md.lower()
    assert len(md) > 50


def test_identity_plugin_register_adds_auth_routes(settings):
    """IdentityPlugin.register() adds /auth routes to the app."""
    app = FastAPI()
    plugin = IdentityPlugin(settings=settings)
    plugin.register(app)

    routes = [r.path for r in app.routes]
    assert any("/auth" in r for r in routes)


def test_include_plugin_works_with_calango():
    """Calango.include_plugin(IdentityPlugin()) integrates end-to-end."""
    from calango import Calango
    from calango.config import CalangoSettings, SecuritySettings

    calango_settings = CalangoSettings(
        security=SecuritySettings(SECRET_KEY="test-secret")
    )
    app = Calango(settings=calango_settings)

    identity_settings = IdentitySettings(
        PRIVATE_KEY=TEST_PRIVATE_KEY,
        PUBLIC_KEY=TEST_PUBLIC_KEY,
    )
    plugin = IdentityPlugin(settings=identity_settings)
    app.include_plugin(plugin)

    routes = [r.path for r in app.routes]
    assert any("/auth" in r for r in routes)
