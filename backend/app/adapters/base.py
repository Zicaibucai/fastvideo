"""AI 适配器基类与工厂。

设计原则：
- 所有外部 AI 服务统一走 Adapter 模式，业务代码只依赖基类接口。
- 未配置 API Key 时自动使用 Mock 实现，保证全流程可运行。
- 新增 provider 只需实现对应基类并在工厂中注册。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.core.exceptions import AIProviderError
from app.core.logging import get_logger

logger = get_logger(__name__)


class BaseAIAdapter(ABC):
    """AI 适配器基类。"""

    provider: str = "disabled"

    def __init__(self, **kwargs: Any) -> None:
        self.config = kwargs

    @abstractmethod
    def is_available(self) -> bool:
        """服务是否可用（是否配置了有效 Key）。"""
        raise NotImplementedError

    def capabilities(self) -> dict[str, bool]:
        """能力矩阵。默认全部不可用，具体适配器按需覆写。"""
        return {}

    def supports(self, cap: str) -> bool:
        """是否支持某能力（基于能力矩阵）。"""
        return bool(self.capabilities().get(cap))

    def _raise_unavailable(self, action: str) -> None:
        raise AIProviderError(
            f"AI 服务不可用（provider={self.provider}, action={action}），请检查 API Key 配置。"
        )


class MockMixin:
    """Mock 实现的公共标记。"""

    provider = "mock"
