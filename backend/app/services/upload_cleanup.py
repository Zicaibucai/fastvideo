"""分片上传暂存目录的垃圾回收。

场景：用户开始分片上传后关闭浏览器、complete 阶段失败，分片文件会残留在磁盘上。
按单文件最高 1GB 计算，废弃几次就能写满磁盘，因此：
- 启动时清理 failed 会话和超过 24 小时未完成的 uploading 会话；
- 同时扫描暂存根目录，删除数据库中已无对应会话的孤儿目录。
"""

from __future__ import annotations

import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.logging import get_logger
from app.models.document_upload_session import DocumentUploadSession

logger = get_logger(__name__)

# uploading 会话的最大保留时长：超过即视为用户放弃
STALE_AFTER = timedelta(hours=24)


def cleanup_resumable_uploads() -> dict[str, int]:
    """清理废弃的分片暂存目录与数据库记录。返回统计信息。"""
    root = settings.resumable_upload_root
    root.mkdir(parents=True, exist_ok=True)

    removed_dirs = 0
    removed_records = 0
    freed_bytes = 0
    stale_cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - STALE_AFTER

    db = SessionLocal()
    try:
        sessions = db.scalars(select(DocumentUploadSession)).all()
        live_session_ids = {s.id for s in sessions}

        for session in sessions:
            should_remove = session.status == "failed" or (
                session.status == "uploading"
                and session.created_at is not None
                and session.created_at < stale_cutoff
            )
            if not should_remove:
                continue

            temp_dir = Path(session.temp_dir)
            if temp_dir.exists():
                freed_bytes += sum(f.stat().st_size for f in temp_dir.rglob("*") if f.is_file())
                shutil.rmtree(temp_dir, ignore_errors=True)
                removed_dirs += 1
            db.delete(session)
            removed_records += 1

        db.commit()

        # 清理磁盘上的孤儿目录（数据库里已无对应会话，例如容器重建后残留）
        for child in root.iterdir():
            if child.is_dir() and child.name not in live_session_ids:
                freed_bytes += sum(f.stat().st_size for f in child.rglob("*") if f.is_file())
                shutil.rmtree(child, ignore_errors=True)
                removed_dirs += 1
    except Exception:
        db.rollback()
        logger.exception("resumable_upload_cleanup_failed")
    finally:
        db.close()

    if removed_dirs or removed_records:
        logger.info(
            "resumable_upload_cleanup_done",
            removed_dirs=removed_dirs,
            removed_records=removed_records,
            freed_mb=round(freed_bytes / 1024 / 1024, 1),
        )
    return {"removed_dirs": removed_dirs, "removed_records": removed_records}
