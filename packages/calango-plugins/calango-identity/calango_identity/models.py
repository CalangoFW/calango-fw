from __future__ import annotations

import uuid
from uuid import UUID

from fastapi_users.db import SQLAlchemyBaseUserTableUUID
from sqlalchemy import Column, ForeignKey, String, Table
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# Junction tables — pure many-to-many associations, no extra columns
user_roles = Table(
    "identity_user_roles",
    Base.metadata,
    Column("user_id", ForeignKey("identity_users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", ForeignKey("identity_roles.id", ondelete="CASCADE"), primary_key=True),
)

role_permissions = Table(
    "identity_role_permissions",
    Base.metadata,
    Column("role_id", ForeignKey("identity_roles.id", ondelete="CASCADE"), primary_key=True),
    Column(
        "permission_id",
        ForeignKey("identity_permissions.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class User(SQLAlchemyBaseUserTableUUID, Base):
    """Auth user. FastAPI-Users provides: id, email, hashed_password,
    is_active, is_superuser, is_verified."""

    __tablename__ = "identity_users"

    roles: Mapped[list[Role]] = relationship(
        secondary=user_roles,
        lazy="selectin",
        back_populates="users",
    )


class Role(Base):
    __tablename__ = "identity_roles"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)

    users: Mapped[list[User]] = relationship(
        secondary=user_roles,
        lazy="selectin",
        back_populates="roles",
    )
    permissions: Mapped[list[Permission]] = relationship(
        secondary=role_permissions,
        lazy="selectin",
        back_populates="roles",
    )


class Permission(Base):
    __tablename__ = "identity_permissions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)

    roles: Mapped[list[Role]] = relationship(
        secondary=role_permissions,
        lazy="selectin",
        back_populates="permissions",
    )
