from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolate_calango_settings_from_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """Host application settings must not leak into core unit tests."""
    for name in ("APP_NAME", "VERSION", "ENV", "DEBUG"):
        monkeypatch.delenv(name, raising=False)
