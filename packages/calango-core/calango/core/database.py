from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

if TYPE_CHECKING:
    from calango.config import CalangoSettings

_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def configure_engine(settings: CalangoSettings) -> None:
    """Initialize the global async engine. Called once at app startup."""
    global _sessionmaker
    engine = create_async_engine(
        settings.database.URL,
        pool_size=settings.database.POOL_SIZE,
        max_overflow=settings.database.MAX_OVERFLOW,
        pool_timeout=settings.database.POOL_TIMEOUT,
        pool_recycle=settings.database.POOL_RECYCLE,
        pool_pre_ping=True,
    )
    _sessionmaker = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yields an async session per request."""
    if _sessionmaker is None:
        raise RuntimeError("Database not configured. Call configure_engine() at startup.")
    async with _sessionmaker() as session:
        yield session
