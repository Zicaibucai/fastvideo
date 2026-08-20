"""Phase 6：大文件分片上传与断点续传测试。"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/fastvideo_phase6_test.db")
os.environ.setdefault("USE_CELERY", "false")
os.environ.setdefault("STORAGE_BACKEND", "local")

from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def auth_headers(client):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@fastvideo.cn", "password": "admin123456"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture()
def project_id(client, auth_headers):
    response = client.post(
        "/api/v1/projects",
        json={"name": "分片上传测试", "code": f"P6-{os.urandom(3).hex()}"},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_resumable_upload_resume_and_complete(client, auth_headers, project_id, monkeypatch):
    monkeypatch.setattr(settings, "resumable_upload_chunk_size", 8)
    content = "项目名称：大文件分片测试\n建筑面积 52800 平方米。\n".encode("utf-8")
    init = client.post(
        f"/api/v1/projects/{project_id}/documents/uploads",
        json={"file_name": "大文件.txt", "file_size": len(content), "doc_type": "tender"},
        headers=auth_headers,
    )
    assert init.status_code == 201, init.text
    upload = init.json()
    assert upload["chunk_size"] == 8
    assert upload["total_chunks"] > 1

    first = content[:8]
    response = client.put(
        f"/api/v1/projects/{project_id}/documents/uploads/{upload['id']}/chunks/0",
        content=first,
        headers={**auth_headers, "X-Chunk-SHA256": hashlib.sha256(first).hexdigest()},
    )
    assert response.status_code == 200, response.text

    resumed = client.get(
        f"/api/v1/projects/{project_id}/documents/uploads/{upload['id']}", headers=auth_headers
    )
    assert resumed.status_code == 200
    assert resumed.json()["uploaded_chunks"] == [0]

    for index in range(1, upload["total_chunks"]):
        chunk = content[index * 8 : (index + 1) * 8]
        response = client.put(
            f"/api/v1/projects/{project_id}/documents/uploads/{upload['id']}/chunks/{index}",
            content=chunk,
            headers={**auth_headers, "X-Chunk-SHA256": hashlib.sha256(chunk).hexdigest()},
        )
        assert response.status_code == 200, response.text

    complete = client.post(
        f"/api/v1/projects/{project_id}/documents/uploads/{upload['id']}/complete",
        headers=auth_headers,
    )
    assert complete.status_code == 200, complete.text
    assert complete.json()["file_size"] == len(content)


def test_resumable_upload_rejects_oversized_chunk(client, auth_headers, project_id, monkeypatch):
    monkeypatch.setattr(settings, "resumable_upload_chunk_size", 4)
    init = client.post(
        f"/api/v1/projects/{project_id}/documents/uploads",
        json={"file_name": "校验.txt", "file_size": 6, "doc_type": "tender"},
        headers=auth_headers,
    )
    upload_id = init.json()["id"]
    response = client.put(
        f"/api/v1/projects/{project_id}/documents/uploads/{upload_id}/chunks/0",
        content=b"12345",
        headers=auth_headers,
    )
    assert response.status_code == 409
