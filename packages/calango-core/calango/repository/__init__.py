from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class BaseRepository[T]:
    """
    Generic async SQLAlchemy 2 repository.

    Usage:
        class OrderRepository(BaseRepository[Order]):
            model = Order
    """

    model: type[T]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, record_id: UUID) -> T | None:
        """Fetch a single record by primary key. Returns None if not found."""
        return await self.session.get(self.model, record_id)

    async def list(self, *, skip: int = 0, limit: int = 100) -> list[T]:
        """Fetch a paginated list of records."""
        result = await self.session.execute(
            select(self.model).offset(skip).limit(limit)
        )
        return list(result.scalars().all())

    async def create(self, data: BaseModel) -> T:
        """Create and persist a new record from a Pydantic model."""
        obj = self.model(**data.model_dump())
        self.session.add(obj)
        await self.session.flush()
        await self.session.refresh(obj)
        return obj

    async def update(self, record_id: UUID, data: BaseModel) -> T:
        """Update an existing record. Raises ValueError if not found."""
        obj = await self.get(record_id)
        if obj is None:
            raise ValueError(f"{self.model.__name__} with id={record_id} not found")
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(obj, field, value)
        await self.session.flush()
        await self.session.refresh(obj)
        return obj

    async def delete(self, record_id: UUID) -> None:
        """Delete a record by primary key. Raises ValueError if not found."""
        obj = await self.get(record_id)
        if obj is None:
            raise ValueError(f"{self.model.__name__} with id={record_id} not found")
        await self.session.delete(obj)
        await self.session.flush()

    async def get_for_update(self, record_id: UUID) -> T | None:
        """Fetch with SELECT FOR UPDATE (pessimistic lock)."""
        result = await self.session.execute(
            select(self.model)
            .where(self.model.id == record_id)  # type: ignore[attr-defined]
            .with_for_update()
        )
        return result.scalar_one_or_none()


__all__ = ["BaseRepository"]
