from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import DeclarativeBase


@asynccontextmanager
async def test_db_session(
    database_url: str = "sqlite+aiosqlite:///:memory:",
    *,
    base: DeclarativeBase | None = None,
) -> AsyncGenerator[AsyncSession, None]:
    """
    Async context manager that provides an isolated database session for tests.

    Creates tables if `base` (DeclarativeBase) is provided, then yields a session.
    Session is NOT committed — callers control transaction lifecycle.

    Usage in conftest.py:
        @pytest.fixture
        async def db():
            from app.models import Base
            async with test_db_session(settings.database.URL, base=Base) as session:
                yield session

    Args:
        database_url: Database URL for the test session.
                     Defaults to sqlite in-memory database.
        base: Optional DeclarativeBase for automatic table creation.

    Yields:
        AsyncSession: An isolated async database session.

    Example:
        async with test_db_session(base=Base) as session:
            repo = MyRepository(session)
            item = await repo.create(data)
    """
    engine = create_async_engine(database_url, echo=False)

    if base is not None:
        async with engine.begin() as conn:
            await conn.run_sync(base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()
