from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterator, Callable
from contextlib import aclosing
from typing import TYPE_CHECKING

from fastapi import Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

if TYPE_CHECKING:
    from calango.config import CalangoSettings

SessionDependency = Callable[[], AsyncIterator[AsyncSession]]


class DatabaseRuntime:
    """Own an application's async engine and session factory."""

    def __init__(
        self,
        settings: CalangoSettings,
        session_dependency: SessionDependency | None = None,
    ) -> None:
        self.settings = settings
        self._session_dependency = session_dependency
        self.engine: AsyncEngine | None = None
        self._maker: async_sessionmaker[AsyncSession] | None = None

    @property
    def started(self) -> bool:
        return self.engine is not None

    async def start(self) -> None:
        """Create the lazy engine and session factory once."""
        if self.engine is not None:
            return

        self.engine = create_async_engine(
            self.settings.database.URL,
            pool_size=self.settings.database.POOL_SIZE,
            max_overflow=self.settings.database.MAX_OVERFLOW,
            pool_timeout=self.settings.database.POOL_TIMEOUT,
            pool_recycle=self.settings.database.POOL_RECYCLE,
            pool_pre_ping=True,
        )
        self._maker = async_sessionmaker(self.engine, expire_on_commit=False)

    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """Yield a session from the injected dependency or owned factory."""
        if self._session_dependency is not None:
            sessions = self._session_dependency()
            try:
                async for session in sessions:
                    yield session
            finally:
                close = getattr(sessions, "aclose", None)
                if close is not None:
                    await close()
            return

        if self._maker is None:
            raise RuntimeError("Database runtime is not started")

        async with self._maker() as session:
            yield session

    async def close(self) -> None:
        """Dispose the owned engine, if started."""
        if self.engine is not None:
            await self.engine.dispose()
        self.engine = None
        self._maker = None


async def get_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """Yield a session from the database runtime owned by the request's app."""
    async with aclosing(request.app.database.session()) as sessions:
        async for session in sessions:
            yield session
