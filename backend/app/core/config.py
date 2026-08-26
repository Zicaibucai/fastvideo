"""FastVideo 配置管理。

所有配置统一从环境变量 / .env 读取，禁止在代码中硬编码任何密钥。
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

# 项目根目录（backend/）
BASE_DIR = Path(__file__).resolve().parent.parent.parent
# 仓库根目录
PROJECT_ROOT = BASE_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---------- 应用 ----------
    app_name: str = "建筑工程AI投标视频平台"
    app_env: str = "development"
    debug: bool = True
    secret_key: str = "please-change-me"
    auth_cookie_secure: bool = False
    api_v1_prefix: str = "/api/v1"
    backend_cors_origins: list[str] = ["http://localhost:5173"]

    # ---------- 数据库 ----------
    database_url: str = "sqlite:///./app.db"
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # ---------- Redis / Celery ----------
    redis_url: str = "redis://localhost:6379/0"
    use_celery: bool = True
    celery_worker_concurrency: int = 4
    celery_task_track_started: bool = True

    # ---------- 存储 ----------
    storage_backend: str = "local"  # local | minio
    storage_local_dir: str = "./data/storage"
    # 大型招标文件：浏览器按 10MB 分片上传，避免单请求占用大量内存。
    resumable_upload_chunk_size: int = 10 * 1024 * 1024
    resumable_upload_max_file_size: int = 1024 * 1024 * 1024
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "fastvideo"
    minio_secret_key: str = "fastvideo_secret"
    minio_bucket: str = "fastvideo"
    minio_secure: bool = False

    # ---------- FFmpeg ----------
    ffmpeg_binary: str = "ffmpeg"
    ffprobe_binary: str = "ffprobe"
    # Apple Silicon 本机使用 rife-metal；选择 RIFE 时执行失败会明确报错，不静默降级。
    rife_binary: str = "rife-metal"
    rife_model: str = ""
    rife_tier: str = "hq"  # hq | balanced | fast
    rife_timeout: int = 900
    video_width: int = 1920
    video_height: int = 1080
    video_fps: int = 30

    # ---------- AI 服务（Adapter + Mock） ----------
    ai_llm_provider: str = "kimi"  # kimi | deepseek | openai | disabled(mock)
    ai_llm_base_url: str = ""
    ai_llm_model: str = "kimi-k3"
    # 解说词、工程信息提取和提示词大师统一使用 Kimi；Kimi 兼容文本与图片输入。
    ai_prompt_master_provider: str = "kimi"
    ai_prompt_master_model: str = "kimi-k3"
    # 模板制作默认必须使用真实 AI；仅测试/演示环境可显式打开 Mock。
    ai_prompt_master_allow_mock: bool = False

    ai_image_provider: str = "disabled"  # minimax | openai | disabled(mock)
    ai_image_base_url: str = ""
    ai_image_model: str = "dall-e-3"
    ai_image_size: str = "1792x1024"

    ai_video_provider: str = "seedance"  # seedance | minimax | disabled(mock)
    ai_video_base_url: str = ""
    ai_video_model: str = "doubao-seedance-2-0-260128"

    ai_tts_provider: str = "disabled"
    ai_tts_base_url: str = ""
    ai_tts_model: str = "tts-1"
    ai_tts_voice: str = "onyx"
    tts_sample_rate: int = 48000
    tts_mp3_bitrate: str = "192k"

    # 火山引擎豆包语音合成（火山语音技术，openspeech.bytedance.com）
    # 需要独立的语音合成 API Key（火山引擎控制台「语音技术 → API Key 管理」创建）。
    volcengine_tts_api_key: str = ""
    volcengine_tts_base_url: str = "https://openspeech.bytedance.com/api/v3/tts/unidirectional/sse"
    volcengine_tts_resource_id: str = "seed-tts-2.0"
    volcengine_tts_voice: str = "zh_female_xiaohe_uranus_bigtts"  # 小何 2.0
    volcengine_tts_timeout: int = 120

    # 通用 OpenAI 兼容配置
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_timeout: int = 120

    # DeepSeek（历史兼容配置，当前文本结构化环节默认不使用）
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_timeout: int = 120

    # Kimi 多模态/文本模型（OpenAI 兼容接口）
    kimi_api_key: str = ""
    kimi_base_url: str = "https://api.moonshot.ai/v1"
    kimi_model: str = "kimi-k3"
    kimi_timeout: int = 180

    # MiniMax（图片生成、参考图渲染、图生视频）
    # 国内账号默认使用 api.minimaxi.com；海外账号可在 .env 改为 api.minimax.io。
    minimax_api_key: str = ""
    minimax_base_url: str = "https://api.minimaxi.com"
    minimax_timeout: int = 180
    minimax_video_model: str = "MiniMax-H3"  # V2 接口（Hailuo-03）模型
    minimax_video_resolution: str = "1080P"
    minimax_video_poll_interval: float = 10.0
    minimax_video_timeout: int = 900

    # Seedream（图生图，火山方舟 Ark）
    # 与 Seedance 视频同属火山方舟，API Key 可复用 ARK_API_KEY / SEEDANCE_API_KEY。
    ark_api_key: str = ""
    seedream_api_key: str = ""
    seedream_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    seedream_image_model: str = "doubao-seedream-4-5-251128"
    seedream_timeout: int = 180
    seedream_image_size: str = "2K"  # Seedream 4.5 支持 2K / 4K / 像素值

    # Seedance（视频生成，火山方舟 Ark）
    # 模型名 / 基础地址必须可配置，禁止把第三方网关地址或模型 ID 写死。
    seedance_api_key: str = ""
    seedance_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    seedance_video_model: str = "doubao-seedance-2-0-260128"
    seedance_timeout: int = 180
    seedance_poll_interval: float = 10.0
    seedance_video_timeout: int = 900
    seedance_video_resolution: str = "720p"

    # 历史火山方舟视觉模型配置（兼容旧配置，当前业务环节默认不再使用）
    # 未单独填写 API Key 时复用 ARK_API_KEY / SEEDANCE_API_KEY。
    volcengine_vision_api_key: str = ""
    volcengine_vision_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    # 可填写火山方舟控制台中的模型 ID 或推理接入点 ID（ep-...）。
    volcengine_vision_model: str = "doubao-seed-2-0-lite-260215"
    volcengine_vision_timeout: int = 180

    # ---------- 管理员 ----------
    admin_email: str = "admin@fastvideo.cn"
    admin_password: str = "admin123456"
    allow_public_registration: bool = True

    @field_validator("backend_cors_origins", mode="before")
    @classmethod
    def _parse_cors(cls, v: Any) -> Any:
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("["):
                import json

                return json.loads(v)
            return [item.strip() for item in v.split(",") if item.strip()]
        return v

    @model_validator(mode="after")
    def _validate_production_security(self) -> "Settings":
        """Fail fast when a production instance still uses demo credentials."""
        if self.app_env.lower() in {"prod", "production"}:
            placeholders = {"please-change-me", "please-change-me-to-a-long-random-string", "change-me-in-production"}
            if self.debug:
                raise ValueError("生产环境必须关闭 DEBUG")
            if self.secret_key in placeholders or len(self.secret_key) < 32:
                raise ValueError("生产环境必须配置至少 32 位随机 SECRET_KEY")
            if self.admin_password in {"admin123456", "change-me", "password"} or len(self.admin_password) < 12:
                raise ValueError("生产环境必须配置非默认 ADMIN_PASSWORD")
            if not self.auth_cookie_secure:
                raise ValueError("生产环境必须启用 AUTH_COOKIE_SECURE")
            if self.allow_public_registration:
                raise ValueError("生产环境默认关闭公开注册，请使用管理员创建人员")
        return self

    @property
    def ai_keys_configured(self) -> bool:
        """是否配置了任何真实 AI Key（用于前端提示与降级判断）。"""
        return bool(
            self.openai_api_key
            or self.deepseek_api_key
            or self.kimi_api_key
            or self.minimax_api_key
            or self.ark_api_key
            or self.seedance_api_key
            or self.seedream_api_key
            or self.volcengine_vision_api_key
        )

    @property
    def storage_root(self) -> Path:
        path = Path(self.storage_local_dir)
        if not path.is_absolute():
            path = BASE_DIR / path
        return path

    @property
    def resumable_upload_root(self) -> Path:
        """API 与 Worker 共享的数据卷中的分片暂存目录。"""
        path = self.storage_root.parent / "uploads"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def sqlalchemy_url(self) -> str:
        """Return a stable database URL independent of the launch directory.

        SQLite's ``sqlite:///./app.db`` is resolved against the process cwd.
        The API is often started from the repository root while Celery is
        started from ``backend/``, which can silently create two databases.
        Relative SQLite paths therefore resolve from the backend directory.
        """
        url = make_url(self.database_url)
        if url.drivername.startswith("sqlite") and url.database not in (None, ":memory:"):
            db_path = Path(url.database)
            if not db_path.is_absolute():
                db_path = (BASE_DIR / db_path).resolve()
                url = url.set(database=str(db_path))
        return url.render_as_string(hide_password=False)

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
