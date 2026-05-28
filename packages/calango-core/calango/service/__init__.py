from __future__ import annotations

from typing import TypeVar

from calango.repository import BaseRepository

R = TypeVar("R", bound=BaseRepository)  # type: ignore[type-arg]


class BaseService[R: BaseRepository]:
    """
    Generic service base class. Inject repository via __init__.

    Usage:
        class OrderService(BaseService[OrderRepository]):
            pass

        # In FastAPI:
        async def get_order_service(db=Depends(get_db)):
            return OrderService(OrderRepository(db))
    """

    def __init__(self, repository: R) -> None:
        self._repository = repository

    @property
    def repository(self) -> R:
        """Access the injected repository."""
        return self._repository


__all__ = ["BaseService"]
