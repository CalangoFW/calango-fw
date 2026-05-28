from __future__ import annotations

import math
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, computed_field


class CalangoModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class PaginatedResponse[T](BaseModel):
    items: list[T]
    total: int
    page: int
    page_size: int

    @computed_field
    @property
    def pages(self) -> int:
        if self.total == 0:
            return 0
        return math.ceil(self.total / self.page_size)


class OrderDirection(StrEnum):
    ASC = "asc"
    DESC = "desc"
