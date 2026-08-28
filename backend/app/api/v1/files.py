"""受保护的文件存储服务路由（本地存储与 MinIO 均适用）。

所有文件访问均需登录：Bearer API 客户端使用 Authorization 头，浏览器使用
HttpOnly Cookie；不接受把 JWT 放入文件 URL 查询参数。
"""

from __future__ import annotations

import mimetypes
import posixpath

from fastapi import APIRouter, Depends, HTTPException
from starlette.background import BackgroundTask
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import get_optional_user
from app.core.database import get_db
from app.core.storage import StorageError, storage
from app.models.project import Project
from app.models.asset import Asset
from app.models.user import User
from app.services.permissions import get_project_access, PERM_PROJECT_VIEW

router = APIRouter(prefix="/files", tags=["文件"])


@router.get("/{key:path}", summary="读取存储文件（需登录）")
def get_file(
    key: str,
    user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
) -> FileResponse:
    if user is None:
        raise HTTPException(401, "未登录或登录已过期")

    # Project-owned files follow projects/{project_id}/... . Authentication
    # alone is not sufficient; enforce tenant ownership before reading storage.
    normalized_key = posixpath.normpath(key.replace("\\", "/")).lstrip("/")
    if normalized_key in ("", ".") or normalized_key == ".." or normalized_key.startswith("../"):
        raise HTTPException(404, "文件不存在")
    parts = normalized_key.split("/")
    if len(parts) >= 2 and parts[0] == "projects":
        try:
            get_project_access(db, parts[1], user, PERM_PROJECT_VIEW)
        except Exception:
            raise HTTPException(404, "文件不存在") from None
    elif normalized_key.startswith("voice/"):
        # Voice previews historically used a global key prefix; resolve the
        # owning Asset before serving so another tenant cannot guess the key.
        asset = db.query(Asset).filter(Asset.file_key == normalized_key).first()
        if not asset or not asset.project_id:
            raise HTTPException(404, "文件不存在")
        try:
            get_project_access(db, asset.project_id, user, PERM_PROJECT_VIEW)
        except Exception:
            raise HTTPException(404, "文件不存在") from None
    else:
        # New storage namespaces must opt in with an explicit ownership rule;
        # authentication alone is never enough to expose a future prefix.
        raise HTTPException(404, "文件不存在")

    try:
        local_path = storage.local_path(normalized_key)
    except StorageError as exc:
        raise HTTPException(404, str(exc)) from exc
    content_type = mimetypes.guess_type(key)[0] or "application/octet-stream"
    # MinIO downloads to a temporary local file; release it after Starlette
    # finishes streaming the response. LocalStorage treats this as a no-op.
    return FileResponse(
        local_path,
        media_type=content_type,
        background=BackgroundTask(storage.release_local_path, local_path),
    )
