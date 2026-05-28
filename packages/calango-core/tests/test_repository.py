from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel
from sqlalchemy import String
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from calango.repository import BaseRepository

# ---------------------------------------------------------------------------
# In-memory test models
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    pass


class Item(Base):
    __tablename__ = "items"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(100))


class ItemCreate(BaseModel):
    id: UUID
    name: str


class ItemUpdate(BaseModel):
    name: str


class ItemRepository(BaseRepository[Item]):
    model = Item


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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBaseRepository:
    async def test_create_persists_record(self, repo: ItemRepository) -> None:
        """create() persists a new record and returns it with id."""
        data = ItemCreate(id=uuid4(), name="Widget")
        item = await repo.create(data)
        assert isinstance(item, Item)
        assert item.name == "Widget"
        assert item.id is not None

    async def test_get_returns_existing_record(self, repo: ItemRepository) -> None:
        """get() returns the record when it exists."""
        data = ItemCreate(id=uuid4(), name="Gadget")
        created = await repo.create(data)
        fetched = await repo.get(created.id)
        assert fetched is not None
        assert fetched.id == created.id
        assert fetched.name == "Gadget"

    async def test_get_returns_none_for_missing_id(self, repo: ItemRepository) -> None:
        """get() returns None when id does not exist."""
        result = await repo.get(uuid4())
        assert result is None

    async def test_list_returns_all_records(self, repo: ItemRepository) -> None:
        """list() returns all persisted records."""
        await repo.create(ItemCreate(id=uuid4(), name="Alpha"))
        await repo.create(ItemCreate(id=uuid4(), name="Beta"))
        await repo.create(ItemCreate(id=uuid4(), name="Gamma"))
        items = await repo.list()
        assert len(items) == 3

    async def test_list_respects_skip_and_limit(self, repo: ItemRepository) -> None:
        """list(skip=1, limit=1) returns the correct subset."""
        await repo.create(ItemCreate(id=uuid4(), name="First"))
        await repo.create(ItemCreate(id=uuid4(), name="Second"))
        await repo.create(ItemCreate(id=uuid4(), name="Third"))
        items = await repo.list(skip=1, limit=1)
        assert len(items) == 1
        assert items[0].name == "Second"

    async def test_update_modifies_record(self, repo: ItemRepository) -> None:
        """update() persists the new field values."""
        created = await repo.create(ItemCreate(id=uuid4(), name="Old Name"))
        updated = await repo.update(created.id, ItemUpdate(name="New Name"))
        assert updated.name == "New Name"
        assert updated.id == created.id

    async def test_update_raises_for_missing_id(self, repo: ItemRepository) -> None:
        """update() raises ValueError when record does not exist."""
        with pytest.raises(ValueError, match="not found"):
            await repo.update(uuid4(), ItemUpdate(name="Ghost"))

    async def test_delete_removes_record(self, repo: ItemRepository) -> None:
        """delete() removes the record from the database."""
        created = await repo.create(ItemCreate(id=uuid4(), name="ToDelete"))
        await repo.delete(created.id)
        result = await repo.get(created.id)
        assert result is None

    async def test_delete_raises_for_missing_id(self, repo: ItemRepository) -> None:
        """delete() raises ValueError when record does not exist."""
        with pytest.raises(ValueError, match="not found"):
            await repo.delete(uuid4())

    async def test_get_for_update_returns_record(self, repo: ItemRepository) -> None:
        """get_for_update() returns the record (SQLite skips the lock, that's fine)."""
        created = await repo.create(ItemCreate(id=uuid4(), name="Lockable"))
        result = await repo.get_for_update(created.id)
        assert result is not None
        assert result.id == created.id
        assert result.name == "Lockable"


# ---------------------------------------------------------------------------
# test_db_session tests
# ---------------------------------------------------------------------------


class TestTestDbSession:
    async def test_test_db_session_yields_async_session(self) -> None:
        """test_db_session yields an AsyncSession."""
        from calango.testing import test_db_session

        async with test_db_session() as session:
            assert isinstance(session, AsyncSession)

    async def test_test_db_session_creates_tables_when_base_provided(self) -> None:
        """test_db_session creates tables when base is provided."""
        from calango.testing import test_db_session

        async with test_db_session(base=Base) as session:
            # Verify that tables exist by attempting to query them
            from sqlalchemy import select

            # If the table doesn't exist, this will raise an error
            result = await session.execute(select(Item))
            items = result.scalars().all()
            assert isinstance(items, list)

    async def test_test_db_session_allows_crud_operations(self) -> None:
        """test_db_session yields a working session for CRUD."""
        from calango.testing import test_db_session

        async with test_db_session(base=Base) as session:
            repo = ItemRepository(session)
            # Create
            item_id = uuid4()
            created = await repo.create(ItemCreate(id=item_id, name="TestItem"))
            assert created.id == item_id
            assert created.name == "TestItem"

            # Read
            fetched = await repo.get(item_id)
            assert fetched is not None
            assert fetched.name == "TestItem"

            # Update
            updated = await repo.update(item_id, ItemUpdate(name="Updated"))
            assert updated.name == "Updated"

            # Delete
            await repo.delete(item_id)
            deleted = await repo.get(item_id)
            assert deleted is None
