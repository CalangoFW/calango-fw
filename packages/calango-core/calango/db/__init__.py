from __future__ import annotations

import importlib
import pkgutil
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

__all__ = ["Base", "import_models"]


class Base(DeclarativeBase):
    """Canonical declarative base. Every application model inherits this so a
    single ``Base.metadata`` sees all models for Alembic autogenerate."""

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


def import_models(package: str = "app.contexts") -> None:
    """Import every ``models`` submodule under ``package`` so each model class
    registers on ``Base.metadata``. Safe to call when the package is absent."""
    try:
        root = importlib.import_module(package)
    except ModuleNotFoundError:
        return
    for ctx in pkgutil.iter_modules(root.__path__):
        models_pkg_name = f"{package}.{ctx.name}.models"
        try:
            models_pkg = importlib.import_module(models_pkg_name)
        except ModuleNotFoundError:
            continue
        for sub in pkgutil.iter_modules(models_pkg.__path__):
            importlib.import_module(f"{models_pkg_name}.{sub.name}")
