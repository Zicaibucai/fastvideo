"""本地存储文件服务路由（仅 local 后端使用）。"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import Response

from app.core.storage import LocalStorage, storage

router = APIRouter(prefix="/files", tags=["文件"])


@router.get("/{key:path}", summary="读取存储文件")
def get_file(key: str) -> Response:
    data = storage.load(key)
    if data is None:
        from fastapi import HTTPException

        raise HTTPException(404, "文件不存在")
    # 简单 MIME 判断
    content_type = "application/octet-stream"
    if key.endswith(".png"):
        content_type = "image/png"
    elif key.endswith(".jpg") or key.endswith(".jpeg"):
        content_type = "image/jpeg"
    elif key.endswith(".mp4"):
        content_type = "video/mp4"
    elif key.endswith(".mp3"):
        content_type = "audio/mpeg"
    elif key.endswith(".pdf"):
        content_type = "application/pdf"
    elif key.endswith(".svg"):
        content_type = "image/svg+xml"
    return Response(content=data, media_type=content_type)
