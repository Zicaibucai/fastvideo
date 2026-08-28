"""Phase 8：Alembic 迁移 0021 回填测试。

在 0020 版本的库中插入用户与项目，升级到 head 后，
原项目 owner 必须自动成为 active owner 成员。
"""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

from alembic import command
from alembic.config import Config


def _alembic_config(db_path: Path) -> Config:
    backend = Path(__file__).resolve().parent.parent
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return config


def test_migration_backfills_owner_members(tmp_path, monkeypatch):
    from app.core.config import settings

    db_path = tmp_path / "mig.db"
    # env.py 从应用 settings 读取数据库 URL，指向独立临时库
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{db_path}")
    config = _alembic_config(db_path)
    command.upgrade(config, "0020")

    user_id = str(uuid.uuid4())
    project_id = str(uuid.uuid4())
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO users (id, email, username, hashed_password, is_active, is_superuser, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, 1, 0, datetime('now'), datetime('now'))",
        (user_id, "legacy@fastvideo.cn", "legacy", "x"),
    )
    conn.execute(
        "INSERT INTO projects (id, owner_id, name, status, created_at, updated_at)"
        " VALUES (?, ?, ?, 'draft', datetime('now'), datetime('now'))",
        (project_id, user_id, "历史项目"),
    )
    conn.commit()
    conn.close()

    command.upgrade(config, "head")

    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT role, status FROM project_members WHERE project_id = ? AND user_id = ?",
        (project_id, user_id),
    ).fetchall()
    assert rows == [("owner", "active")]
    # 新列存在且有默认值
    cols = {r[1]: r for r in conn.execute("PRAGMA table_info(projects)").fetchall()}
    assert "review_policy" in cols and "revision" in cols
    policy = conn.execute("SELECT review_policy, revision FROM projects WHERE id = ?", (project_id,)).fetchone()
    assert policy == ("recommended", 1)
    # owner_id 保留
    assert conn.execute("SELECT owner_id FROM projects WHERE id = ?", (project_id,)).fetchone()[0] == user_id
    # 幂等：重复执行回填不会产生重复成员
    conn.close()
    command.upgrade(config, "head")
    conn = sqlite3.connect(db_path)
    count = conn.execute(
        "SELECT COUNT(*) FROM project_members WHERE project_id = ?", (project_id,)
    ).fetchone()[0]
    assert count == 1
    conn.close()
