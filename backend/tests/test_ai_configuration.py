from __future__ import annotations

from app.core.database import Base, SessionLocal, engine
from app.models.ai_configuration import AIConfiguration
from app.services.ai_configuration import (
    provider_config,
    refresh_runtime_config_from_db,
    save_configuration,
    set_runtime_config,
)


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
