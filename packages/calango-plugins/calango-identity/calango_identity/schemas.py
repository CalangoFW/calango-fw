from __future__ import annotations

import uuid

from fastapi_users import schemas
from pydantic import BaseModel, Field


class RefreshTokenInput(BaseModel):
    refresh_token: str = Field(min_length=43, max_length=512)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 - OAuth token type, not a credential
    refresh_token: str
    expires_in: int


class UserRead(schemas.BaseUser[uuid.UUID]):
    pass


class UserCreate(schemas.BaseUserCreate):
    pass


class UserUpdate(schemas.BaseUserUpdate):
    pass
