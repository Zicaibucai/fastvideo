from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AIConfigurationUpdate(BaseModel):
    providers: dict[str, dict[str, Any]] = Field(default_factory=dict)
    stages: dict[str, dict[str, Any]] = Field(default_factory=dict)
