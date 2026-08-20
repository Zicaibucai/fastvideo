"""后端 pytest 冒烟测试。

测试数据库使用独立的 SQLite（内存或临时文件），不影响开发库。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# 让 app 包可导入
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 测试环境配置：必须在导入 app 之前设置
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/fastvideo_test.db")
os.environ.setdefault("USE_CELERY", "false")
os.environ.setdefault("AI_LLM_PROVIDER", "disabled")
os.environ.setdefault("AI_IMAGE_PROVIDER", "disabled")
os.environ.setdefault("AI_VIDEO_PROVIDER", "disabled")
os.environ.setdefault("AI_TTS_PROVIDER", "disabled")

from app.main import app  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def auth_headers(client):
    # 使用 .env 默认管理员
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@fastvideo.cn", "password": "admin123456"},
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_health(client):
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"


def test_system_status(client):
    resp = client.get("/api/v1/system/status")
    assert resp.status_code == 200
    assert "ai" in resp.json()
    assert "mock_mode" in resp.json()["ai"]


def test_register_and_login(client):
    resp = client.post(
        "/api/v1/auth/register",
        json={
            "email": "user1@test.com",
            "username": "user1",
            "password": "test123456",
        },
    )
    assert resp.status_code == 201, resp.text
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "user1@test.com", "password": "test123456"},
    )
    assert resp.status_code == 200
    assert "access_token" in resp.json()


def test_me(client, auth_headers):
    resp = client.get("/api/v1/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["email"] == "admin@fastvideo.cn"


def test_project_crud(client, auth_headers):
    # 创建
    resp = client.post(
        "/api/v1/projects",
        json={"name": "测试项目-市民中心", "code": "ZB-2026-001"},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    pid = resp.json()["id"]

    # 列表
    resp = client.get("/api/v1/projects", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1

    # 详情
    resp = client.get(f"/api/v1/projects/{pid}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["name"] == "测试项目-市民中心"

    # 更新关键参数（含来源页码）
    resp = client.patch(
        f"/api/v1/projects/{pid}",
        json={"bid_area": 52800, "area_source_page": 3, "construction_period": "540日历天"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["bid_area"] == 52800
    assert resp.json()["area_source_page"] == 3

    # 删除
    resp = client.delete(f"/api/v1/projects/{pid}", headers=auth_headers)
    assert resp.status_code == 204


def test_ai_narration_generation(client, auth_headers):
    # 创建项目
    resp = client.post(
        "/api/v1/projects",
        json={"name": "AI解说词测试"},
        headers=auth_headers,
    )
    pid = resp.json()["id"]

    # 生成解说词（USE_CELERY=false -> 同步执行）
    resp = client.post(
        f"/api/v1/projects/{pid}/storyboard/generate",
        json={"project_id": pid, "section_count": 4, "tone": "专业庄重"},
        headers=auth_headers,
    )
    assert resp.status_code == 202, resp.text
    task_id = resp.json()["task_id"]

    # 查询任务状态
    resp = client.get(f"/api/v1/tasks/{task_id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"

    # 分镜应已生成
    resp = client.get(f"/api/v1/projects/{pid}/storyboard", headers=auth_headers)
    assert resp.status_code == 200
    shots = resp.json()
    assert len(shots) == 4
    assert shots[0]["narration"]


def test_shot_edit_and_versions(client, auth_headers):
    # 创建项目 + 生成分镜
    resp = client.post(
        "/api/v1/projects",
        json={"name": "版本历史测试"},
        headers=auth_headers,
    )
    pid = resp.json()["id"]
    client.post(
        f"/api/v1/projects/{pid}/storyboard/generate",
        json={"project_id": pid, "section_count": 3},
        headers=auth_headers,
    )
    shots = client.get(f"/api/v1/projects/{pid}/storyboard", headers=auth_headers).json()
    shot_id = shots[0]["id"]

    # 编辑解说词
    resp = client.patch(
        f"/api/v1/projects/{pid}/storyboard/{shot_id}",
        json={"narration": "人工修改后的解说词"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["narration"] == "人工修改后的解说词"
    assert resp.json()["status"] == "edited"

    # 历史版本应包含 2 条（AI 初始 + 人工修改）
    versions = resp.json()["versions"]
    assert len(versions) >= 2

    # 恢复 AI 版本
    ai_version = next(v for v in versions if v["source"] == "ai")
    resp = client.post(
        f"/api/v1/projects/{pid}/storyboard/{shot_id}/restore",
        json={"revision": ai_version["revision"]},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["narration"] == ai_version["narration"]


def test_image_generation_mock(client, auth_headers):
    resp = client.post(
        "/api/v1/projects",
        json={"name": "AI图片测试"},
        headers=auth_headers,
    )
    pid = resp.json()["id"]
    client.post(
        f"/api/v1/projects/{pid}/storyboard/generate",
        json={"project_id": pid, "section_count": 2},
        headers=auth_headers,
    )
    shots = client.get(f"/api/v1/projects/{pid}/storyboard", headers=auth_headers).json()
    shot_id = shots[0]["id"]

    resp = client.post(
        f"/api/v1/projects/{pid}/assets/ai-image",
        data={"shot_id": shot_id, "prompt": "现代建筑外观"},
        headers=auth_headers,
    )
    assert resp.status_code == 202, resp.text
    task_id = resp.json()["task_id"]

    resp = client.get(f"/api/v1/tasks/{task_id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"

    # 应有图片素材
    assets = client.get(f"/api/v1/projects/{pid}/assets", headers=auth_headers).json()
    images = [a for a in assets if a["asset_type"] == "image"]
    assert len(images) >= 1

    # 分镜应关联图片
    shot = client.get(f"/api/v1/projects/{pid}/storyboard/{shot_id}", headers=auth_headers).json()
    assert shot["image_asset_id"] is not None


def test_video_project_and_export(client, auth_headers):
    resp = client.post(
        "/api/v1/projects",
        json={"name": "导出测试"},
        headers=auth_headers,
    )
    pid = resp.json()["id"]
    client.post(
        f"/api/v1/projects/{pid}/storyboard/generate",
        json={"project_id": pid, "section_count": 3},
        headers=auth_headers,
    )

    resp = client.post(
        f"/api/v1/projects/{pid}/video-projects",
        json={"name": "投标视频-1080P", "width": 1920, "height": 1080},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    vp_id = resp.json()["id"]

    resp = client.post(
        f"/api/v1/video-projects/{vp_id}/export",
        json={"video_project_id": vp_id, "export_format": "mp4"},
        headers=auth_headers,
    )
    assert resp.status_code == 202, resp.text
    export_id = resp.json()["export_task_id"]

    resp = client.get(f"/api/v1/exports/{export_id}", headers=auth_headers)
    assert resp.status_code == 200
    # 同步模式下应已完成
    assert resp.json()["status"] in ("success", "failed")
