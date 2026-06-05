from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import BaseModel
from sqlalchemy import String
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from calango.repository import BaseRepository
from calango.service import BaseService

# ---------------------------------------------------------------------------
# In-memory test models (reuse from test_repository.py pattern)
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    pass


class Item(Base):
    __tablename__ = "items"

    id: Mapped[str] = mapped_column(primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(100))


class ItemCreate(BaseModel):
    id: str
    name: str


class ItemUpdate(BaseModel):
    name: str


class ItemRepository(BaseRepository[Item]):
    model = Item


class ItemService(BaseService[ItemRepository]):
    """Concrete service for testing BaseService."""

    pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async_session = async_sessionmaker(engine, expire_on_commit=False)
    async with async_session() as s:
        yield s
    await engine.dispose()


@pytest.fixture
def repo(session: AsyncSession) -> ItemRepository:
    return ItemRepository(session)


@pytest.fixture
def service(repo: ItemRepository) -> ItemService:
    return ItemService(repo)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBaseService:
    async def test_service_stores_repository(self, repo: ItemRepository) -> None:
        """BaseService stores the repository passed to __init__."""
        service = BaseService(repo)
        assert service._repository is repo

    async def test_service_repository_property_returns_repo(self, repo: ItemRepository) -> None:
        """repository property returns the injected repository instance."""
        service = BaseService(repo)
        assert service.repository is repo

    async def test_service_subclass_can_call_repository_methods(
        self, service: ItemService, repo: ItemRepository
    ) -> None:
        """A concrete service subclass can call repository CRUD methods."""
        data = ItemCreate(id=str(uuid4()), name="Widget")
        item = await repo.create(data)
        fetched = await service.repository.get(item.id)
        assert fetched is not None
        assert fetched.name == "Widget"

    async def test_service_accepts_any_repository_subclass(self, session: AsyncSession) -> None:
        """BaseService works with any BaseRepository subclass."""
        repo = ItemRepository(session)
        service = BaseService(repo)
        assert isinstance(service.repository, BaseRepository)
        assert service.repository.model == Item
