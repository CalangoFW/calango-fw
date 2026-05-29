from __future__ import annotations

import uuid

import pytest
from calango_identity.models import Base, Permission, Role, User
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


async def test_user_table_exists(session):
    """User table can be created and has expected columns."""
    user = User(
        id=uuid.uuid4(),
        email="test@example.com",
        hashed_password="hashed",
    )
    session.add(user)
    await session.flush()
    assert user.id is not None
    assert user.email == "test@example.com"


async def test_role_table_exists(session):
    """Role table can be created."""
    role = Role(id=uuid.uuid4(), name="admin")
    session.add(role)
    await session.flush()
    assert role.name == "admin"


async def test_permission_table_exists(session):
    """Permission table can be created."""
    perm = Permission(id=uuid.uuid4(), code="orders:read")
    session.add(perm)
    await session.flush()
    assert perm.code == "orders:read"


async def test_user_role_relationship(session):
    """User can have roles via the junction table."""
    user = User(id=uuid.uuid4(), email="u@test.com", hashed_password="x")
    role = Role(id=uuid.uuid4(), name="editor")
    user.roles.append(role)
    session.add(user)
    await session.flush()
    await session.refresh(user)
    assert len(user.roles) == 1
    assert user.roles[0].name == "editor"


async def test_role_permission_relationship(session):
    """Role can have permissions via the junction table."""
    role = Role(id=uuid.uuid4(), name="manager")
    perm = Permission(id=uuid.uuid4(), code="reports:view")
    role.permissions.append(perm)
    session.add(role)
    await session.flush()
    await session.refresh(role)
    assert len(role.permissions) == 1
    assert role.permissions[0].code == "reports:view"


async def test_all_tables_use_identity_prefix(session):
    """All model tables are prefixed with identity_ to avoid collisions."""
    assert User.__tablename__ == "identity_users"
    assert Role.__tablename__ == "identity_roles"
    assert Permission.__tablename__ == "identity_permissions"
