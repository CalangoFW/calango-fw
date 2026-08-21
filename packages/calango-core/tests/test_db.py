from __future__ import annotations

import pytest
from sqlalchemy.orm import Mapped, mapped_column
from starlette.requests import Request

from calango.config import CalangoSettings, SecuritySettings
from calango.core import database as database_module
from calango.core.database import DatabaseRuntime, get_db
from calango.db import Base


@pytest.fixture
def settings() -> CalangoSettings:
    return CalangoSettings(security=SecuritySettings(SECRET_KEY="test-secret"))


def test_package_exports_database_runtime() -> None:
    from calango import DatabaseRuntime as ExportedDatabaseRuntime

    assert ExportedDatabaseRuntime is DatabaseRuntime


async def test_runtime_start_and_close_are_idempotent(settings: CalangoSettings) -> None:
    runtime = DatabaseRuntime(settings)

    await runtime.start()
    first_engine = runtime.engine
    await runtime.start()

    assert runtime.engine is first_engine
    assert runtime.started

    await runtime.close()
    await runtime.close()

    assert runtime.engine is None
    assert not runtime.started


def test_runtime_construction_does_not_create_engine(
    settings: CalangoSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_if_called(*args: object, **kwargs: object) -> None:
        pytest.fail("engine construction must wait until runtime startup")

    monkeypatch.setattr(database_module, "create_async_engine", fail_if_called)

    runtime = DatabaseRuntime(settings)

    assert runtime.engine is None


async def test_runtime_session_requires_start(settings: CalangoSettings) -> None:
    runtime = DatabaseRuntime(settings)

    with pytest.raises(RuntimeError, match="Database runtime is not started"):
        await anext(runtime.session())


async def test_runtime_uses_injected_session_dependency(settings: CalangoSettings) -> None:
    session = object()

    async def session_dependency():
        yield session

    runtime = DatabaseRuntime(settings, session_dependency=session_dependency)

    assert [item async for item in runtime.session()] == [session]


async def test_get_db_delegates_to_request_application_runtime(
    settings: CalangoSettings,
) -> None:
    session = object()

    async def session_dependency():
        yield session

    runtime = DatabaseRuntime(settings, session_dependency=session_dependency)
    app = type("App", (), {"database": runtime})()
    request = Request({"type": "http", "app": app})

    assert [item async for item in get_db(request)] == [session]


def test_concrete_model_inherits_id_and_timestamps():
    class Widget(Base):
        __tablename__ = "widgets"
        name: Mapped[str] = mapped_column()

    cols = {c.name for c in Widget.__table__.columns}
    assert {"id", "created_at", "updated_at", "name"} <= cols


def test_models_share_one_metadata():
    class Gadget(Base):
        __tablename__ = "gadgets"

    assert "gadgets" in Base.metadata.tables


def test_import_models_registers_context_models(tmp_path, monkeypatch):

    # Build a fake project package: pkg/shop/models/order.py
    pkg = tmp_path / "demo_app" / "contexts" / "shop" / "models"
    pkg.mkdir(parents=True)
    for p in [
        tmp_path / "demo_app",
        tmp_path / "demo_app" / "contexts",
        tmp_path / "demo_app" / "contexts" / "shop",
        pkg,
    ]:
        (p / "__init__.py").write_text("")
    (pkg / "order.py").write_text(
        "from sqlalchemy.orm import Mapped, mapped_column\n"
        "from calango.db import Base\n"
        "class Order(Base):\n"
        "    __tablename__ = 'discovery_orders'\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    from calango.db import import_models

    import_models("demo_app.contexts")
    assert "discovery_orders" in Base.metadata.tables


def test_import_models_absent_package_is_noop():
    from calango.db import import_models

    import_models("nonexistent.package.path")  # must not raise
