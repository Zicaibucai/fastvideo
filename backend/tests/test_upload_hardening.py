"""文档上传加固专项测试：覆盖 .doc 拒收、魔数校验、文件鉴权、分片失败清理、类型拒绝等。"""

from __future__ import annotations

import hashlib
import io
import os
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


def _msg(resp) -> str:
    """统一取错误消息，兼容 {message: ...} 与 {detail: ...} 两种 FastAPI 返回。"""
    j = resp.json()
    return str(j.get("message") or j.get("detail") or "")


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
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture()
def project_id(client, auth_headers):
    r = client.post(
        "/api/v1/projects",
        json={"name": "上传加固测试", "code": f"HARDEN-{os.urandom(3).hex()}"},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ---------- 普通上传 ----------

def test_rejects_doc_extension(client, auth_headers, project_id):
    """旧版 .doc 扩展名必须被前后端一致拒收。"""
    r = client.post(
        f"/api/v1/projects/{project_id}/documents",
        files={"file": ("投标文件.doc", b"dummy", "application/msword")},
        data={"doc_type": "tender"},
        headers=auth_headers,
    )
    assert r.status_code == 409
    assert "docx" in _msg(r).lower() or ".doc" in _msg(r)


def test_rejects_fake_pdf_magic(client, auth_headers, project_id):
    """扩展名 .pdf 但内容不是 %PDF- 开头，必须被拒绝。"""
    r = client.post(
        f"/api/v1/projects/{project_id}/documents",
        files={"file": ("fake.pdf", b"not a pdf content", "application/pdf")},
        data={"doc_type": "tender"},
        headers=auth_headers,
    )
    assert r.status_code == 409


def test_rejects_fake_docx_magic(client, auth_headers, project_id):
    """扩展名 .docx 但内容不是 zip 包，必须拒绝。"""
    r = client.post(
        f"/api/v1/projects/{project_id}/documents",
        files={"file": ("fake.docx", b"plain text pretending to be docx", "application/vnd.openxmlformats")},
        data={"doc_type": "tender"},
        headers=auth_headers,
    )
    assert r.status_code == 409


def test_accepts_real_pdf(client, auth_headers, project_id):
    """真实 %PDF- 开头的 PDF 能正常上传。"""
    pdf = b"%PDF-1.4\n%fake minimal pdf\n1 0 obj<<>>endobj\n"
    r = client.post(
        f"/api/v1/projects/{project_id}/documents",
        files={"file": ("ok.pdf", pdf, "application/pdf")},
        data={"doc_type": "tender"},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    assert r.json()["file_type"] == "pdf"


def test_accepts_real_docx(client, auth_headers, project_id):
    """真实 zip 格式的 .docx 能正常上传。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
    data = buf.getvalue()
    r = client.post(
        f"/api/v1/projects/{project_id}/documents",
        files={"file": ("ok.docx", data, "application/vnd.openxmlformats")},
        data={"doc_type": "tender"},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    assert r.json()["file_type"] == "docx"


def test_file_endpoint_requires_auth_and_project_ownership(client, auth_headers, project_id):
    """文件必须登录且只能由所属项目用户读取；JWT 不放入 URL。"""
    pdf = b"%PDF-1.4\n%auth test\n"
    up = client.post(
        f"/api/v1/projects/{project_id}/documents",
        files={"file": ("need_auth.pdf", pdf, "application/pdf")},
        data={"doc_type": "tender"},
        headers=auth_headers,
    )
    assert up.status_code == 201, up.text
    key = up.json()["file_key"]

    # Browser sessions authenticate through the HttpOnly cookie set by login.
    cookie_authed = client.get(f"/files/{key}")
    assert cookie_authed.status_code == 200

    # TestClient keeps login cookies, so explicitly clear the browser session
    # before asserting anonymous access.
    client.cookies.clear()
    anon = client.get(f"/files/{key}")
    assert anon.status_code == 401

    token = auth_headers["Authorization"].split(" ", 1)[1]
    authed = client.get(f"/files/{key}", headers=auth_headers)
    assert authed.status_code == 200
    assert authed.content == pdf

    # A different project owner must not be able to read the file even when
    # they are fully authenticated.
    registered = client.post(
        "/api/v1/auth/register",
        json={
            "email": "file-reader@example.com",
            "username": "file-reader",
            "password": "reader123",
        },
    )
    assert registered.status_code in (201, 409), registered.text
    other_login = client.post(
        "/api/v1/auth/login",
        json={"email": "file-reader@example.com", "password": "reader123"},
    )
    assert other_login.status_code == 200, other_login.text
    other_headers = {"Authorization": f"Bearer {other_login.json()['access_token']}"}
    denied = client.get(f"/files/{key}", headers=other_headers)
    assert denied.status_code == 404


# ---------- 分片上传 ----------

def test_resumable_rejects_doc_on_init(client, auth_headers, project_id):
    """创建分片会话时 .doc 扩展名必须被拒绝。"""
    r = client.post(
        f"/api/v1/projects/{project_id}/documents/uploads",
        json={"file_name": "old.doc", "file_size": 1024, "doc_type": "tender"},
        headers=auth_headers,
    )
    assert r.status_code == 409


def test_resumable_rejects_exceeding_max(client, auth_headers, project_id):
    """文件大小超过 resumable_upload_max_file_size 必须被拒绝。"""
    too_big = settings.resumable_upload_max_file_size + 1
    r = client.post(
        f"/api/v1/projects/{project_id}/documents/uploads",
        json={"file_name": "big.pdf", "file_size": too_big, "doc_type": "tender"},
        headers=auth_headers,
    )
    assert r.status_code == 409


def test_resumable_rejects_chunk_out_of_range(client, auth_headers, project_id, monkeypatch):
    """分片序号越界必须被拒绝。"""
    monkeypatch.setattr(settings, "resumable_upload_chunk_size", 8)
    init = client.post(
        f"/api/v1/projects/{project_id}/documents/uploads",
        json={"file_name": "rng.txt", "file_size": 16, "doc_type": "tender"},
        headers=auth_headers,
    )
    uid = init.json()["id"]
    r = client.put(
        f"/api/v1/projects/{project_id}/documents/uploads/{uid}/chunks/99",
        content=b"xxxxxxxx",
        headers=auth_headers,
    )
    assert r.status_code == 409
    client.delete(
        f"/api/v1/projects/{project_id}/documents/uploads/{uid}", headers=auth_headers
    )


def test_resumable_complete_rejects_missing_chunks(client, auth_headers, project_id, monkeypatch):
    """complete 时若分片未齐，必须返回 409。"""
    monkeypatch.setattr(settings, "resumable_upload_chunk_size", 8)
    init = client.post(
        f"/api/v1/projects/{project_id}/documents/uploads",
        json={"file_name": "partial.txt", "file_size": 16, "doc_type": "tender"},
        headers=auth_headers,
    )
    uid = init.json()["id"]
    chunk = b"aaaaaaaa"
    client.put(
        f"/api/v1/projects/{project_id}/documents/uploads/{uid}/chunks/0",
        content=chunk,
        headers={**auth_headers, "X-Chunk-SHA256": hashlib.sha256(chunk).hexdigest()},
    )
    r = client.post(
        f"/api/v1/projects/{project_id}/documents/uploads/{uid}/complete",
        headers=auth_headers,
    )
    assert r.status_code == 409
    assert "缺少" in _msg(r)
    client.delete(
        f"/api/v1/projects/{project_id}/documents/uploads/{uid}", headers=auth_headers
    )


def test_cancel_upload_cleans_temp_dir(client, auth_headers, project_id, monkeypatch):
    """cancel 后 temp_dir 必须被删除，避免磁盘堆积。"""
    monkeypatch.setattr(settings, "resumable_upload_chunk_size", 8)
    init = client.post(
        f"/api/v1/projects/{project_id}/documents/uploads",
        json={"file_name": "cancel.txt", "file_size": 8, "doc_type": "tender"},
        headers=auth_headers,
    )
    uid = init.json()["id"]
    from app.core.database import SessionLocal
    from app.models.document_upload_session import DocumentUploadSession

    db = SessionLocal()
    try:
        session = db.get(DocumentUploadSession, uid)
        temp_dir = Path(session.temp_dir)
        assert temp_dir.exists()
    finally:
        db.close()

    r = client.delete(
        f"/api/v1/projects/{project_id}/documents/uploads/{uid}", headers=auth_headers
    )
    assert r.status_code == 204
    assert not temp_dir.exists()
