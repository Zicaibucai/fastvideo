"""素材 Schema。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.common import TimestampedModel


class AssetCreate(BaseModel):
    project_id: str | None = None
    name: str = Field(min_length=1, max_length=255)
    asset_type: str = Field(pattern="^(image|video|audio|model|document)$")
    source: str = "upload"
    url: str | None = None
    prompt: str | None = None
    tags: list[str] | None = None
    meta: dict | None = None


class AssetUpdate(BaseModel):
    name: str | None = None
    tags: list[str] | None = None
    meta: dict | None = None


class AssetOut(TimestampedModel):
    project_id: str | None
    name: str
    asset_type: str
    source: str
    file_key: str | None
    url: str | None
    file_size: int
    mime_type: str | None
    width: int | None
    height: int | None
    duration_seconds: float | None
    generated_by: str | None
    prompt: str | None
    tags: list | None
