from __future__ import annotations

from sqlalchemy.orm import Mapped, mapped_column

from calango.db import Base


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
