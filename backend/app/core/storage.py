"""文件存储抽象：本地存储 与 MinIO 兼容 S3。

统一接口 save / load / delete / url，业务代码不感知后端差异。
"""

from __future__ import annotations

import io
import mimetypes
import shutil
from pathlib import Path
from urllib.parse import quote

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class StorageError(Exception):
    pass


class LocalStorage:
    """本地文件系统存储。"""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _full_path(self, key: str) -> Path:
        # 防止路径穿越
        safe = key.replace("\\", "/").lstrip("/")
        return (self.root / safe).resolve()

    def _ensure_within_root(self, full: Path) -> None:
        if not full.is_relative_to(self.root.resolve()):
            raise StorageError("非法存储路径")

    def save(self, key: str, data: bytes | io.BytesIO) -> str:
        full = self._full_path(key)
        self._ensure_within_root(full)
        full.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, io.BytesIO):
            data = data.getvalue()
        full.write_bytes(data)
        logger.debug("local_save", key=key, size=len(data))
        return key

    def load(self, key: str) -> bytes:
        full = self._full_path(key)
        self._ensure_within_root(full)
        if not full.exists():
            raise StorageError(f"文件不存在: {key}")
        return full.read_bytes()

    def save_file(self, key: str, source: str | Path) -> str:
        """从磁盘文件保存，供大文件分片合并使用，避免读入内存。"""
        full = self._full_path(key)
        self._ensure_within_root(full)
        full.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, full)
        return key

    def delete(self, key: str) -> None:
        full = self._full_path(key)
        self._ensure_within_root(full)
        if full.exists():
            full.unlink()

    def exists(self, key: str) -> bool:
        return self._full_path(key).exists()

    def local_path(self, key: str) -> str:
        """返回文件在本地磁盘上的绝对路径，供大文件流式解析使用。

        注意：调用方使用完毕后必须调用 ``release_local_path(path)`` 释放资源。
        对于 LocalStorage 这是个空操作；对于 MinioStorage 会删除临时下载文件。
        """
        full = self._full_path(key)
        self._ensure_within_root(full)
        if not full.exists():
            raise StorageError(f"文件不存在: {key}")
        return str(full)

    def release_local_path(self, path: str) -> None:
        """释放 local_path 返回的资源。LocalStorage 无需清理。"""
        return None

    def url(self, key: str) -> str:
        quoted = quote(key)
        return f"/files/{quoted}"


class MinioStorage:
    """MinIO / S3 兼容存储（懒加载客户端）。"""

    def __init__(self) -> None:
        from minio import Minio  # 延迟导入，避免本地无依赖时影响启动

        self.client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )
        self.bucket = settings.minio_bucket
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)
            logger.info("minio_bucket_created", bucket=self.bucket)

    def save(self, key: str, data: bytes | io.BytesIO) -> str:
        if isinstance(data, bytes):
            data = io.BytesIO(data)
        length = data.getbuffer().nbytes
        data.seek(0)
        content_type = mimetypes.guess_type(key)[0] or "application/octet-stream"
        self.client.put_object(
            self.bucket, key, data, length=length, content_type=content_type
        )
        return key

    def load(self, key: str) -> bytes:
        resp = self.client.get_object(self.bucket, key)
        try:
            return resp.read()
        finally:
            resp.close()
            resp.release_conn()

    def save_file(self, key: str, source: str | Path) -> str:
        content_type = mimetypes.guess_type(key)[0] or "application/octet-stream"
        self.client.fput_object(self.bucket, key, str(source), content_type=content_type)
        return key

    def delete(self, key: str) -> None:
        self.client.remove_object(self.bucket, key)

    def exists(self, key: str) -> bool:
        try:
            self.client.stat_object(self.bucket, key)
            return True
        except Exception:
            return False

    def local_path(self, key: str) -> str:
        """MinIO 非本地存储，下载到临时文件后返回路径，供大文件流式解析使用。

        调用方使用完毕后**必须**调用 ``release_local_path(path)`` 删除临时文件。
        """
        import tempfile

        suffix = Path(key).suffix
        fd, tmp_path = tempfile.mkstemp(prefix="fastvideo_parse_", suffix=suffix)
        import os

        os.close(fd)
        try:
            self.client.fget_object(self.bucket, key, tmp_path)
        except Exception:
            Path(tmp_path).unlink(missing_ok=True)
            raise
        return tmp_path

    def release_local_path(self, path: str) -> None:
        """删除 MinioStorage.local_path 下载到本地的临时文件。"""
        Path(path).unlink(missing_ok=True)

    def url(self, key: str) -> str:
        return self.client.presigned_get_object(self.bucket, key)


def get_storage() -> LocalStorage | MinioStorage:
    if settings.storage_backend == "minio":
        try:
            return MinioStorage()
        except Exception as exc:  # pragma: no cover
            logger.exception("minio_init_failed_fallback_local")
            raise StorageError(f"MinIO 初始化失败: {exc}") from exc
    return LocalStorage(settings.storage_root)


# 全局单例（懒初始化由 get_storage 处理，这里保留兼容引用）
storage = get_storage()
