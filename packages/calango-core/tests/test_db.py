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
