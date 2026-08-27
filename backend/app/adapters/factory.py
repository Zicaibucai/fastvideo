"""AI 适配器工厂。

根据 settings 中的 provider 配置选择真实实现或 Mock 实现。
未配置 API Key 时自动返回 Mock，保证全流程可运行。
"""

from __future__ import annotations

from functools import lru_cache

from app.adapters.base import BaseAIAdapter
from app.adapters.image import (
    ImageAdapter,
    MiniMaxImageAdapter,
    MockImageAdapter,
    SeedreamImageAdapter,
)
from app.adapters.llm import (
    DeepSeekLLMAdapter,
    KimiLLMAdapter,
    LLMAdapter,
    MockLLMAdapter,
    VolcengineVisionLLMAdapter,
)
from app.adapters.ocr import BaseOCRAdapter, MockOCRAdapter, TesseractOCRAdapter
from app.adapters.tts import MockTTSAdapter, TTSAdapter, VolcengineTTSAdapter
from app.adapters.video import (
    MiniMaxH3VideoAdapter,
    MiniMaxVideoAdapter,
    MockVideoAdapter,
    SeedanceVideoAdapter,
    VideoAdapter,
)
from app.core.config import settings
from app.core.logging import get_logger
from app.services.ai_configuration import provider_config, stage_config

logger = get_logger(__name__)


def _openai_kwargs(*, api_key: str, model: str, base_url: str = "") -> dict:
    return {
        "api_key": api_key,
        "base_url": base_url or settings.openai_base_url,
        "timeout": settings.openai_timeout,
        "model": model,
    }


def _mock(mock_cls, *, requested_provider: str) -> BaseAIAdapter:
    if requested_provider not in ("disabled", "mock", ""):
        logger.info(
            "ai_mock_fallback",
            real_provider=requested_provider,
            reason="缺少对应 Provider API Key",
        )
    return mock_cls(api_key="", timeout=settings.openai_timeout)


def _unknown(mock_cls, provider: str) -> BaseAIAdapter:
    logger.warning("ai_unknown_provider_fallback_mock", provider=provider)
    return _mock(mock_cls, requested_provider=provider)


@lru_cache
def get_llm_adapter(stage: str = "narration") -> BaseAIAdapter:
    stage_value = stage_config(stage)
    provider = str(stage_value.get("provider") or settings.ai_llm_provider).strip().lower()
    provider_value = provider_config(provider)
    model = str(stage_value.get("model") or provider_value.get("model") or settings.ai_llm_model)
    if provider == "deepseek":
        if not provider_value.get("api_key"):
            return _mock(MockLLMAdapter, requested_provider=provider)
        return DeepSeekLLMAdapter(
            api_key=provider_value.get("api_key"),
            base_url=provider_value.get("base_url") or settings.deepseek_base_url,
            timeout=settings.deepseek_timeout,
            model=model or "deepseek-v4-flash",
        )
    if provider == "kimi":
        if not provider_value.get("api_key"):
            return _mock(MockLLMAdapter, requested_provider=provider)
        return KimiLLMAdapter(
            api_key=provider_value.get("api_key"),
            base_url=provider_value.get("base_url") or settings.kimi_base_url,
            timeout=settings.kimi_timeout,
            model=model or settings.kimi_model,
        )
    if provider == "volcengine_vision":
        if not provider_value.get("api_key"):
            return _mock(MockLLMAdapter, requested_provider=provider)
        return VolcengineVisionLLMAdapter(
            api_key=provider_value.get("api_key"),
            base_url=provider_value.get("base_url") or settings.volcengine_vision_base_url,
            timeout=settings.volcengine_vision_timeout,
            model=model or settings.volcengine_vision_model,
        )
    if provider in ("openai", "azure"):
        if not provider_value.get("api_key"):
            return _mock(MockLLMAdapter, requested_provider=provider)
        return LLMAdapter(api_key=provider_value.get("api_key"), base_url=provider_value.get("base_url"), timeout=settings.openai_timeout, model=model)
    if provider in ("disabled", "mock", ""):
        return _mock(MockLLMAdapter, requested_provider=provider)
    return _unknown(MockLLMAdapter, provider)


@lru_cache
def get_image_adapter(stage: str = "image") -> BaseAIAdapter:
    stage_value = stage_config(stage)
    provider = str(stage_value.get("provider") or settings.ai_image_provider).strip().lower()
    provider_value = provider_config(provider)
    model = str(stage_value.get("model") or provider_value.get("model") or settings.ai_image_model)
    if provider == "seedream":
        api_key = provider_value.get("api_key") or settings.seedream_api_key or settings.seedance_api_key
        if not api_key:
            return _mock(MockImageAdapter, requested_provider=provider)
        return SeedreamImageAdapter(
            api_key=api_key,
            base_url=provider_value.get("base_url") or settings.seedream_base_url,
            timeout=settings.seedream_timeout,
            model=model or settings.seedream_image_model,
            size=settings.seedream_image_size,
        )
    if provider == "minimax":
        if not provider_value.get("api_key"):
            return _mock(MockImageAdapter, requested_provider=provider)
        return MiniMaxImageAdapter(
            api_key=provider_value.get("api_key"),
            base_url=provider_value.get("base_url") or settings.minimax_base_url,
            timeout=settings.minimax_timeout,
            model=model or "image-01",
            size=settings.ai_image_size,
        )
    if provider == "openai":
        if not provider_value.get("api_key"):
            return _mock(MockImageAdapter, requested_provider=provider)
        return ImageAdapter(api_key=provider_value.get("api_key"), base_url=provider_value.get("base_url"), timeout=settings.openai_timeout, model=model, size=settings.ai_image_size)
    if provider in ("disabled", "mock", ""):
        return _mock(MockImageAdapter, requested_provider=provider)
    return _unknown(MockImageAdapter, provider)


@lru_cache
def get_video_adapter(stage: str = "video") -> BaseAIAdapter:
    stage_value = stage_config(stage)
    provider = str(stage_value.get("provider") or settings.ai_video_provider).strip().lower()
    provider_value = provider_config(provider)
    model = str(stage_value.get("model") or provider_value.get("model") or settings.ai_video_model)
    if provider == "seedance":
        if not provider_value.get("api_key"):
            return _mock(MockVideoAdapter, requested_provider=provider)
        return SeedanceVideoAdapter(
            api_key=provider_value.get("api_key"),
            base_url=provider_value.get("base_url") or settings.seedance_base_url,
            timeout=settings.seedance_timeout,
            model=model or settings.seedance_video_model,
            resolution=settings.seedance_video_resolution,
            poll_interval=settings.seedance_poll_interval,
            video_timeout=settings.seedance_video_timeout,
        )
    if provider == "minimax":
        if not provider_value.get("api_key"):
            return _mock(MockVideoAdapter, requested_provider=provider)
        return MiniMaxH3VideoAdapter(
            api_key=provider_value.get("api_key"),
            base_url=provider_value.get("base_url") or settings.minimax_base_url,
            timeout=settings.minimax_timeout,
            model=model or settings.minimax_video_model,
            resolution=settings.minimax_video_resolution,
            poll_interval=settings.minimax_video_poll_interval,
            video_timeout=settings.minimax_video_timeout,
        )
    if provider == "openai":
        if not provider_value.get("api_key"):
            return _mock(MockVideoAdapter, requested_provider=provider)
        return VideoAdapter(**_openai_kwargs(
            api_key=provider_value.get("api_key"),
            model=model,
            base_url=provider_value.get("base_url") or settings.ai_video_base_url,
        ))
    if provider in ("disabled", "mock", ""):
        return _mock(MockVideoAdapter, requested_provider=provider)
    return _unknown(MockVideoAdapter, provider)


@lru_cache
def get_tts_adapter(stage: str = "voice") -> BaseAIAdapter:
    stage_value = stage_config(stage)
    provider = str(stage_value.get("provider") or settings.ai_tts_provider).strip().lower()
    provider_value = provider_config(provider)
    model = str(stage_value.get("model") or provider_value.get("model") or settings.ai_tts_model)
    if provider == "volcengine":
        if not provider_value.get("api_key"):
            return _mock(MockTTSAdapter, requested_provider=provider)
        return VolcengineTTSAdapter(
            api_key=provider_value.get("api_key"),
            base_url=provider_value.get("base_url") or settings.volcengine_tts_base_url,
            resource_id=settings.volcengine_tts_resource_id,
            voice=settings.volcengine_tts_voice,
            timeout=settings.volcengine_tts_timeout,
        )
    if provider in ("openai", "azure"):
        if not provider_value.get("api_key"):
            return _mock(MockTTSAdapter, requested_provider=provider)
        return TTSAdapter(api_key=provider_value.get("api_key"), base_url=provider_value.get("base_url"), timeout=settings.openai_timeout, model=model, voice=settings.ai_tts_voice)
    if provider in ("disabled", "mock", ""):
        return _mock(MockTTSAdapter, requested_provider=provider)
    return _unknown(MockTTSAdapter, provider)


def get_ocr_adapter() -> BaseOCRAdapter:
    """OCR 适配器：优先 Tesseract，不可用则回退 Mock。

    与其它 AI 适配器不同，OCR 不依赖外部 API Key，而是依赖本机 tesseract。
    未安装 tesseract 时自动使用 Mock，保证流程可运行。
    """
    tesseract = TesseractOCRAdapter()
    if tesseract.is_available():
        return tesseract
    return MockOCRAdapter()


def ai_status() -> dict:
    """返回各 AI 服务的可用状态（供前端展示）。"""
    llm_adapter = get_llm_adapter()
    prompt_master_adapter = get_llm_adapter("prompt_master")
    img_adapter = get_image_adapter()
    video_adapter = get_video_adapter()
    tts_adapter = get_tts_adapter()
    llm_stage = stage_config("narration")
    prompt_master_stage = stage_config("prompt_master")
    image_stage = stage_config("image")
    video_stage = stage_config("video")
    voice_stage = stage_config("voice")
    return {
        "llm": {
            "provider": llm_adapter.provider,
            "configured_provider": llm_stage.get("provider"),
            "available": llm_adapter.is_available(),
            "model": llm_stage.get("model"),
        },
        "prompt_master": {
            "provider": prompt_master_adapter.provider,
            "configured_provider": prompt_master_stage.get("provider"),
            "available": prompt_master_adapter.is_available(),
            "model": prompt_master_stage.get("model"),
            "capabilities": prompt_master_adapter.capabilities(),
            "is_mock": prompt_master_adapter.provider == "mock",
        },
        "image": {
            "provider": img_adapter.provider,
            "configured_provider": image_stage.get("provider"),
            "available": img_adapter.is_available(),
            "model": image_stage.get("model"),
            "capabilities": img_adapter.capabilities(),
        },
        "video": {
            "provider": video_adapter.provider,
            "configured_provider": video_stage.get("provider"),
            "available": video_adapter.is_available(),
            "model": video_stage.get("model"),
            "capabilities": video_adapter.capabilities(),
        },
        "tts": {
            "provider": tts_adapter.provider,
            "configured_provider": voice_stage.get("provider"),
            "available": tts_adapter.is_available(),
            "model": voice_stage.get("model"),
            "voice": settings.ai_tts_voice,
            "capabilities": tts_adapter.capabilities(),
        },
        # 全局提示仅反映解说词、图片和视频这三项核心生成能力。TTS 可以
        # 独立保持 disabled/mock，用于演示或等待企业授权音色配置，不能因此
        # 把已配置的 Kimi / MiniMax 误报为“未配置 AI Key”。
        "mock_mode": any(
            adapter.provider == "mock"
            for adapter in (llm_adapter, img_adapter, video_adapter)
        ),
        "tts_mock_mode": tts_adapter.provider == "mock",
    }


def tts_provider_info() -> list[dict]:
    """返回 TTS Provider 列表及能力。"""
    adapter = get_tts_adapter()
    voice_stage = stage_config("voice")
    return [
        {
            "provider": adapter.provider,
            "available": adapter.is_available(),
            "capabilities": adapter.capabilities(),
            "model": voice_stage.get("model"),
            "is_mock": adapter.provider == "mock",
            "voices": adapter.list_voices() if hasattr(adapter, "list_voices") else [],
        }
    ]


def image_provider_info() -> list[dict]:
    """返回图片渲染 Provider 列表及能力。"""
    adapter = get_image_adapter()
    image_stage = stage_config("image")
    return [
        {
            "provider": adapter.provider,
            "available": adapter.is_available(),
            "capabilities": adapter.capabilities(),
            "model": image_stage.get("model"),
            "is_mock": adapter.provider == "mock",
        }
    ]


# 各视频 Provider 可选模型清单（供前端下拉；真实可用性以 Provider 控制台为准）
VIDEO_PROVIDER_MODELS = {
    "seedance": [
        "doubao-seedance-2-0-260128",
        "doubao-seedance-2-0-fast-260128",
        "doubao-seedance-1-5-pro-251215",
        "doubao-seedance-1-0-pro-250528",
    ],
    "minimax": [
        "MiniMax-H3",
    ],
}


def build_video_adapter(provider: str) -> BaseAIAdapter | None:
    """按名称构建视频生成适配器。

    未配置对应 API Key 时返回 None（**不回退 Mock**）——视频生成页面允许用户
    显式选择 Provider，选择了一个没配 Key 的 Provider 必须明确报错而不是静默降级。
    provider="mock" 时返回 Mock 适配器（供演示/测试）。
    """
    provider = (provider or "").strip().lower()
    configured = provider_config(provider)
    if provider == "seedance":
        if not configured.get("api_key"):
            return None
        return SeedanceVideoAdapter(
            api_key=configured.get("api_key"),
            base_url=configured.get("base_url") or settings.ai_video_base_url or settings.seedance_base_url,
            timeout=settings.seedance_timeout,
            model=configured.get("model") or settings.ai_video_model or settings.seedance_video_model,
            resolution=settings.seedance_video_resolution,
            poll_interval=settings.seedance_poll_interval,
            video_timeout=settings.seedance_video_timeout,
        )
    if provider == "minimax":
        if not configured.get("api_key"):
            return None
        return MiniMaxH3VideoAdapter(
            api_key=configured.get("api_key"),
            base_url=configured.get("base_url") or settings.minimax_base_url,
            timeout=settings.minimax_timeout,
            model=configured.get("model") or settings.minimax_video_model,
            resolution=settings.minimax_video_resolution,
            poll_interval=settings.minimax_video_poll_interval,
            video_timeout=settings.minimax_video_timeout,
        )
    if provider == "mock":
        return MockVideoAdapter(api_key="", timeout=settings.openai_timeout)
    return None


def video_providers_info() -> list[dict]:
    """返回当前产品开放的视频 Provider（Seedance；本地测试时可附带 Mock）。"""
    active = get_video_adapter()
    result = []
    # MiniMax 适配器仅为历史任务保留，不再暴露给新建视频任务。
    for provider in ("seedance",):
        models = VIDEO_PROVIDER_MODELS[provider]
        adapter = build_video_adapter(provider)
        # Provider 能力描述与本机是否已经配置 API Key 是两个独立维度。
        # 未配置 Key 时仍向前端暴露 Seedance 支持的生成模式，只通过
        # ``available`` 阻止实际提交，避免能力列表退化为空字典。
        capability_adapter = adapter or SeedanceVideoAdapter(api_key="")
        configured_model = provider_config(provider).get("model")
        available_models = list(dict.fromkeys([configured_model, *models])) if configured_model else models
        result.append(
            {
                "provider": provider,
                "available": adapter is not None,
                "capabilities": capability_adapter.capabilities(),
                "models": available_models,
                "default_model": configured_model or models[0],
                "is_active": active.provider == provider,
                "is_mock": False,
            }
        )
    # 仅在当前配置仍处于 disabled/mock 时展示本地演示入口，避免真实环境误用 Mock。
    if active.provider == "mock":
        mock = MockVideoAdapter(api_key="", timeout=settings.openai_timeout)
        result.append(
            {
                "provider": "mock",
                "available": True,
                "capabilities": mock.capabilities(),
                "models": ["local-demo"],
                "default_model": "local-demo",
                "is_active": True,
                "is_mock": True,
            }
        )
    return result
