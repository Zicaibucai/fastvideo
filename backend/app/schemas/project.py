"""项目 Schema。"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

from app.schemas.common import TimestampedModel


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    code: str | None = None
    description: str | None = None


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    code: str | None = None
    description: str | None = None
    status: str | None = None
    review_policy: str | None = Field(
        default=None, pattern="^(disabled|recommended|required)$"
    )
    base_revision: int | None = Field(
        default=None, description="乐观锁：客户端读取时的 revision，不一致返回 409"
    )

    # 关键投标参数（含来源页码）
    bid_area: float | None = None
    area_source_page: int | None = None
    bid_deadline: date | None = None
    deadline_source_page: int | None = None
    construction_period: str | None = None
    period_source_page: int | None = None
    bidder_name: str | None = None
    bidder_source_page: int | None = None
    tech_params: dict | None = None


class ProjectOut(TimestampedModel):
    name: str
    code: str | None
    description: str | None
    status: str
    last_entered_at: datetime | None

    bid_area: float | None
    area_source_page: int | None
    bid_deadline: date | None
    deadline_source_page: int | None
    construction_period: str | None
    period_source_page: int | None
    bidder_name: str | None
    bidder_source_page: int | None
    tech_params: dict | None

    owner_id: str
    review_policy: str = "recommended"
    revision: int = 1

    # 统计
    doc_count: int = 0
    shot_count: int = 0
    asset_count: int = 0


class ProjectDetail(ProjectOut):
    # 当前用户在项目中的角色与权限集合（前端据此控制按钮，后端仍逐接口校验）
    my_role: str | None = None
    my_permissions: list[str] = []
