"""用户 Schema。"""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import TimestampedModel


class UserBase(BaseModel):
    email: EmailStr
    username: str = Field(min_length=2, max_length=64)
    full_name: str | None = None
    company: str | None = None


class UserCreate(UserBase):
    password: str = Field(min_length=6, max_length=128)


class UserUpdate(BaseModel):
    username: str | None = Field(default=None, min_length=2, max_length=64)
    full_name: str | None = None
    company: str | None = None
    password: str | None = Field(default=None, min_length=6, max_length=128)


class UserOut(TimestampedModel, UserBase):
    is_active: bool
    is_superuser: bool


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
