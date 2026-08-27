"""统一 AI 配置的运行时覆盖层。

环境变量仍是初始默认值，管理员在设置页保存后写入数据库并立即覆盖当前进程。
API 返回时只暴露密钥是否已配置和末四位，避免把密钥回显到浏览器。
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import base64
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.ai_configuration import AIConfiguration

STAGES = {
    "narration": "解说词生成",
    "fact_extraction": "工程信息提取",
    "prompt_master": "提示词大师",
    "image": "图片生成与渲染",
    "video": "视频生成",
    "voice": "配音生成",
}

# 这三个环节都需要文本结构化能力；提示词大师还需要图片理解能力，统一走 Kimi 系。
KIMI_TEXT_STAGES = {"narration", "fact_extraction", "prompt_master"}
# Kimi 系允许的两个通道：Moonshot 开放平台（kimi）与 Kimi Code 编程版（kimi_code）。
KIMI_STAGE_PROVIDERS = {"kimi", "kimi_code"}

PROVIDER_META = {
    "openai": {"label": "OpenAI", "kind": "llm", "base_url": "https://api.openai.com/v1"},
    "deepseek": {"label": "DeepSeek", "kind": "llm", "base_url": "https://api.deepseek.com"},
    "kimi": {"label": "Kimi（文本+多模态）", "kind": "multimodal_llm", "base_url": "https://api.moonshot.ai/v1"},
    "kimi_code": {"label": "Kimi Code（K3 编程版）", "kind": "multimodal_llm", "base_url": "https://api.kimi.com/coding/v1"},
    "volcengine_vision": {"label": "火山方舟视觉模型（Doubao-Seed）", "kind": "vision_llm", "base_url": "https://ark.cn-beijing.volces.com/api/v3"},
    "seedream": {"label": "Seedream", "kind": "image", "base_url": "https://ark.cn-beijing.volces.com/api/v3"},
    "seedance": {"label": "Seedance", "kind": "video", "base_url": "https://ark.cn-beijing.volces.com/api/v3"},
    "minimax": {"label": "MiniMax", "kind": "multi", "base_url": "https://api.minimaxi.com"},
    "volcengine": {"label": "火山引擎语音", "kind": "voice", "base_url": "https://openspeech.bytedance.com"},
    "mock": {"label": "Mock 演示", "kind": "all", "base_url": ""},
}

_runtime: dict[str, Any] = {"providers": {}, "stages": {}}
_runtime_signature: str | None = None


def _secret_cipher() -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.secret_key.encode("utf-8")).digest())
    return Fernet(key)


def _encrypt_api_key(value: str) -> str:
    return "enc:v1:" + _secret_cipher().encrypt(value.encode("utf-8")).decode("ascii")


def _decrypt_api_key(value: Any) -> str:
    raw = str(value or "")
    if not raw.startswith("enc:v1:"):
        # Backward compatibility for rows written before encrypted storage
        # was introduced. They are re-encrypted on the next configuration load.
        return raw
    try:
        return _secret_cipher().decrypt(raw[7:].encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeError):
        return ""


def _decrypted_providers(providers: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(providers or {})
    for value in result.values():
        if isinstance(value, dict) and "api_key" in value:
            value["api_key"] = _decrypt_api_key(value.get("api_key"))
    return result


def _encrypted_providers(providers: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(providers or {})
    for value in result.values():
        if isinstance(value, dict) and value.get("api_key"):
            raw = str(value["api_key"])
            if not raw.startswith("enc:v1:"):
                value["api_key"] = _encrypt_api_key(raw)
    return result


def _configuration_signature(row: AIConfiguration | None) -> str:
    """Return a stable, secret-safe change marker for cross-process refreshes."""
    if row is None:
        payload = {"providers": {}, "stages": {}, "is_enabled": False}
    else:
        payload = {
            "providers": row.providers or {},
            "stages": row.stages or {},
            "is_enabled": bool(row.is_enabled),
        }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _default_provider_config() -> dict[str, dict[str, Any]]:
    return {
        "openai": {"api_key": settings.openai_api_key, "base_url": settings.ai_llm_base_url or settings.openai_base_url, "model": settings.ai_llm_model},
        "deepseek": {"api_key": settings.deepseek_api_key, "base_url": settings.deepseek_base_url, "model": "deepseek-v4-flash"},
        "kimi": {"api_key": settings.kimi_api_key, "base_url": settings.kimi_base_url, "model": settings.kimi_model},
        "kimi_code": {"api_key": settings.kimi_code_api_key, "base_url": settings.kimi_code_base_url, "model": settings.kimi_code_model},
        "volcengine_vision": {
            "api_key": settings.volcengine_vision_api_key or settings.ark_api_key or settings.seedance_api_key,
            "base_url": settings.volcengine_vision_base_url or settings.seedance_base_url,
            "model": settings.volcengine_vision_model,
        },
        "seedream": {"api_key": settings.seedream_api_key or settings.ark_api_key or settings.seedance_api_key, "base_url": settings.ai_image_base_url or settings.seedream_base_url, "model": settings.seedream_image_model},
        "seedance": {"api_key": settings.seedance_api_key or settings.ark_api_key, "base_url": settings.ai_video_base_url or settings.seedance_base_url, "model": settings.seedance_video_model},
        "minimax": {"api_key": settings.minimax_api_key, "base_url": settings.minimax_base_url, "model": settings.minimax_video_model},
        "volcengine": {"api_key": settings.volcengine_tts_api_key, "base_url": settings.ai_tts_base_url or settings.volcengine_tts_base_url, "model": settings.ai_tts_model},
        "mock": {"api_key": "", "base_url": "", "model": "mock"},
    }


def provider_config(provider: str) -> dict[str, Any]:
    value = _default_provider_config().get(provider, {}).copy()
    value.update((_runtime.get("providers") or {}).get(provider) or {})
    return value


def stage_config(stage: str) -> dict[str, Any]:
    configured = dict((_runtime.get("stages") or {}).get(stage) or {})
    if stage == "prompt_master":
        configured.setdefault("provider", settings.ai_prompt_master_provider)
        configured.setdefault(
            "model",
            provider_config(str(configured.get("provider") or "")).get("model")
            or settings.ai_prompt_master_model,
        )
    elif stage in {"narration", "fact_extraction"}:
        configured.setdefault("provider", settings.ai_llm_provider)
        configured.setdefault("model", provider_config(str(configured.get("provider") or "")).get("model") or settings.ai_llm_model)
    elif stage == "image":
        configured.setdefault("provider", settings.ai_image_provider)
        # 阶段模型是图片/视频页面的默认选择；Provider 默认模型只作为兜底，
        # 避免视频模型名（例如 MiniMax-H3）串入图片生成阶段。
        configured.setdefault("model", settings.ai_image_model or provider_config(str(configured.get("provider") or "")).get("model"))
    elif stage == "video":
        configured.setdefault("provider", settings.ai_video_provider)
        provider_name = str(configured.get("provider") or "").lower()
        stage_model = settings.ai_video_model
        # 默认 Seedance 模型不能串到 MiniMax；如果用户明确在 AI_VIDEO_MODEL
        # 里选择了其它模型，仍然尊重该显式选择。
        if provider_name == "minimax" and str(stage_model or "").lower().startswith("doubao-seedance"):
            stage_model = ""
        configured.setdefault("model", stage_model or provider_config(provider_name).get("model"))
    elif stage == "voice":
        configured.setdefault("provider", settings.ai_tts_provider)
        configured.setdefault("model", provider_config(str(configured.get("provider") or "")).get("model") or settings.ai_tts_model)
    return configured


def set_runtime_config(providers: dict[str, Any], stages: dict[str, Any]) -> None:
    global _runtime_signature
    _runtime["providers"] = deepcopy(providers or {})
    _runtime["stages"] = deepcopy(stages or {})
    _runtime_signature = None
    # 工厂使用 lru_cache；配置保存后必须让下一次请求重新构建适配器。
    from app.adapters import factory
    for fn in (factory.get_llm_adapter, factory.get_image_adapter, factory.get_video_adapter, factory.get_tts_adapter):
        fn.cache_clear()


def load_runtime_config(db: Session) -> None:
    global _runtime_signature
    row = db.query(AIConfiguration).filter(AIConfiguration.scope == "global").first()
    if row and row.is_enabled:
        stages = deepcopy(row.stages or {})
        changed = False
        # 将历史保存的 DeepSeek / 火山视觉绑定迁移到 Kimi 系，避免升级后仍沿用旧通道。
        for stage in KIMI_TEXT_STAGES:
            current = dict(stages.get(stage) or {})
            provider = current.get("provider")
            if provider not in KIMI_STAGE_PROVIDERS:
                stages[stage] = {**current, "provider": "kimi", "model": settings.kimi_model}
                changed = True
            elif not current.get("model"):
                default_model = settings.kimi_code_model if provider == "kimi_code" else settings.kimi_model
                stages[stage] = {**current, "model": default_model}
                changed = True
        if changed:
            row.stages = stages
            db.commit()
        # Keep only ciphertext in the database while adapters receive plaintext
        # in process memory. Also upgrade legacy plaintext rows in place.
        encrypted = _encrypted_providers(row.providers or {})
        if encrypted != (row.providers or {}):
            row.providers = encrypted
            db.commit()
        set_runtime_config(_decrypted_providers(encrypted), stages)
        _runtime_signature = _configuration_signature(row)
    else:
        # A deleted/disabled row must not leave stale provider credentials in
        # a long-lived API or Celery process.
        set_runtime_config({}, {})
        _runtime_signature = _configuration_signature(row)


def refresh_runtime_config_from_db() -> None:
    """Refresh provider settings when another process changed the DB row.

    API and Celery are separate processes.  A worker therefore cannot rely on
    the API process's in-memory runtime cache.  This lightweight signature
    check runs before each task and only clears adapter caches when the
    persisted configuration actually changed.
    """
    global _runtime_signature
    db = SessionLocal()
    try:
        row = db.query(AIConfiguration).filter(AIConfiguration.scope == "global").first()
        signature = _configuration_signature(row)
        if signature == _runtime_signature:
            return
        load_runtime_config(db)
    except Exception:
        # A temporary database outage must not erase a known-good in-memory
        # configuration or make every task fail before it starts.
        return
    finally:
        db.close()


def read_configuration(db: Session) -> dict[str, Any]:
    row = db.query(AIConfiguration).filter(AIConfiguration.scope == "global").first()
    providers = _default_provider_config()
    stages = {key: {"provider": stage_config(key).get("provider"), "model": stage_config(key).get("model")} for key in STAGES}
    if row:
        for key, value in (row.providers or {}).items():
            providers.setdefault(key, {}).update(value or {})
        stages.update(row.stages or {})
    output: dict[str, Any] = {"providers": [], "stages": stages, "stage_options": STAGES}
    for key, value in providers.items():
        secret = _decrypt_api_key(value.get("api_key"))
        output["providers"].append({
            "provider": key,
            "label": (PROVIDER_META.get(key) or {}).get("label", key),
            "kind": (PROVIDER_META.get(key) or {}).get("kind", "other"),
            "base_url": value.get("base_url") or (PROVIDER_META.get(key) or {}).get("base_url", ""),
            "model": value.get("model") or "",
            "api_key_set": bool(secret),
            "api_key_hint": f"••••{secret[-4:]}" if secret else "未配置",
        })
    return output


def save_configuration(db: Session, payload: dict[str, Any], username: str) -> dict[str, Any]:
    row = db.query(AIConfiguration).filter(AIConfiguration.scope == "global").first()
    current = row.providers if row else {}
    providers: dict[str, Any] = deepcopy(current or {})
    for key, incoming in (payload.get("providers") or {}).items():
        next_value = dict(incoming or {})
        if "api_key" in next_value:
            # 处理从密码管理器/剪贴板粘贴时附带的首尾空格或换行，避免服务端返回 401。
            next_value["api_key"] = str(next_value.get("api_key") or "").strip()
        if not next_value.get("api_key"):
            next_value.pop("api_key", None)
        if "base_url" in next_value:
            next_value["base_url"] = str(next_value.get("base_url") or "").strip().rstrip("/")
        if "model" in next_value:
            next_value["model"] = str(next_value.get("model") or "").strip()
        merged = providers.setdefault(key, {})
        if "api_key" in next_value and next_value["api_key"]:
            next_value["api_key"] = _encrypt_api_key(next_value["api_key"])
        merged.update(next_value)
        if key == "kimi":
            # Kimi Code Key 的 OpenAI 兼容入口固定为 /coding/v1；把设置页里
            # 常见的 /coding 写法保存时补全，后续任务与页面显示保持一致。
            effective_key = _decrypt_api_key(merged.get("api_key"))
            if effective_key.startswith("sk-kimi-"):
                configured_base = str(merged.get("base_url") or "").strip().rstrip("/")
                if "api.kimi.com/coding" not in configured_base:
                    merged["base_url"] = "https://api.kimi.com/coding/v1"
                elif not configured_base.endswith("/v1"):
                    merged["base_url"] = f"{configured_base}/v1"
        if key == "kimi_code":
            # kimi_code 是 Kimi Code 编程版的独立存放位置，通道固定为 /coding/v1，
            # 防止误填成 Moonshot 平台地址后跨域调用失败。
            configured_base = str(merged.get("base_url") or "").strip().rstrip("/")
            if "api.kimi.com/coding" not in configured_base:
                merged["base_url"] = settings.kimi_code_base_url
            elif not configured_base.endswith("/v1"):
                merged["base_url"] = f"{configured_base}/v1"
    stages = deepcopy(payload.get("stages") or {})
    # 文本结构化与多模态环节统一使用 Kimi 系，避免设置页或旧客户端再次切回旧通道。
    for stage in KIMI_TEXT_STAGES:
        if stage in stages:
            current = dict(stages.get(stage) or {})
            provider = current.get("provider")
            if provider not in KIMI_STAGE_PROVIDERS:
                provider = "kimi"
            default_model = settings.kimi_code_model if provider == "kimi_code" else settings.kimi_model
            stages[stage] = {
                **current,
                "provider": provider,
                "model": current.get("model") or default_model,
            }
    persisted_providers = _encrypted_providers(providers)
    if row is None:
        row = AIConfiguration(scope="global", providers=persisted_providers, stages=stages, updated_by=username)
        db.add(row)
    else:
        row.providers = persisted_providers
        row.stages = stages
        row.updated_by = username
    db.commit()
    set_runtime_config(_decrypted_providers(persisted_providers), stages)
    global _runtime_signature
    _runtime_signature = _configuration_signature(row)
    return read_configuration(db)
