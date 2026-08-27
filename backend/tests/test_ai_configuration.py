from __future__ import annotations

from app.core.database import Base, SessionLocal, engine
from app.models.ai_configuration import AIConfiguration
from app.services.ai_configuration import (
    provider_config,
    refresh_runtime_config_from_db,
    save_configuration,
    set_runtime_config,
)


def _cleanup(db) -> None:
    row = db.query(AIConfiguration).filter(AIConfiguration.scope == "global").first()
    if row:
        db.delete(row)
        db.commit()
    set_runtime_config({}, {})


def test_kimi_code_provider_is_stored_independently_and_pins_coding_channel():
    """kimi_code 是 Kimi Code 编程版 Key 的独立存放位置：通道固定 /coding/v1，环节绑定保留。"""
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        result = save_configuration(
            db,
            {
                "providers": {
                    "kimi_code": {
                        "api_key": "sk-kimi-code-test-key",
                        # 故意填错地址，保存时应被纠正回 /coding/v1
                        "base_url": "https://api.moonshot.cn/v1",
                        "model": "kimi-k3",
                    }
                },
                "stages": {"prompt_master": {"provider": "kimi_code", "model": "kimi-k3"}},
            },
            "admin",
        )
        row = db.query(AIConfiguration).filter(AIConfiguration.scope == "global").first()
        assert row is not None
        assert row.providers["kimi_code"]["api_key"].startswith("enc:v1:")
        assert row.providers["kimi_code"]["base_url"] == "https://api.kimi.com/coding/v1"
        assert provider_config("kimi_code")["api_key"] == "sk-kimi-code-test-key"
        # kimi_code 属于 Kimi 系，绑定不会被强制回 kimi
        assert result["stages"]["prompt_master"]["provider"] == "kimi_code"
        labels = {item["provider"]: item["label"] for item in result["providers"]}
        assert "kimi_code" in labels
        assert labels["kimi_code"] == "Kimi Code（K3 编程版）"
    finally:
        _cleanup(db)
        db.close()


def test_text_stages_still_reject_legacy_providers():
    """文本结构化环节仍只允许 Kimi 系通道，旧通道（deepseek 等）会被纠正。"""
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        result = save_configuration(
            db,
            {"providers": {}, "stages": {"narration": {"provider": "deepseek", "model": "deepseek-v4-flash"}}},
            "admin",
        )
        assert result["stages"]["narration"]["provider"] == "kimi"
    finally:
        _cleanup(db)
        db.close()


def test_ai_keys_are_encrypted_and_worker_refreshes_runtime_config():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        save_configuration(
            db,
            {
                "providers": {"kimi": {"api_key": "sk-kimi-test-key", "model": "kimi-k3"}},
                "stages": {"narration": {"provider": "kimi", "model": "kimi-k3"}},
            },
            "admin",
        )
        row = db.query(AIConfiguration).filter(AIConfiguration.scope == "global").first()
        assert row is not None
        assert row.providers["kimi"]["api_key"].startswith("enc:v1:")
        assert provider_config("kimi")["api_key"] == "sk-kimi-test-key"

        # Simulate a separate worker process with an empty in-memory cache.
        set_runtime_config({}, {})
        refresh_runtime_config_from_db()
        assert provider_config("kimi")["api_key"] == "sk-kimi-test-key"
    finally:
        row = db.query(AIConfiguration).filter(AIConfiguration.scope == "global").first()
        if row:
            db.delete(row)
            db.commit()
        set_runtime_config({}, {})
        db.close()
