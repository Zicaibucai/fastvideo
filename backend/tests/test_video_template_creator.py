"""从专业视频提炼 AI 视频模板的闭环回归测试。"""

from __future__ import annotations

import os
import subprocess

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("AI_PROMPT_MASTER_PROVIDER", "mock")
os.environ.setdefault("AI_PROMPT_MASTER_ALLOW_MOCK", "true")

from app.main import app
from app.services.video_gen_service import build_recipe_prompt, build_reference_timing


def test_multi_reference_timing_is_relative_to_clip_start():
    timing = build_reference_timing(
        clip_start_seconds=10,
        clip_end_seconds=15,
        reference_frame_times=[10.1, 15],
        generation_mode="multi_reference_video",
    )
    assert timing == {
        "clip_duration_seconds": 5.0,
        "reference_timing_seconds": [0.0, 0.1, 5.0],
    }
    prompt = build_recipe_prompt(prompt="平稳展示建筑", recipe=timing)
    assert "第1张=0.000s；第2张=0.100s；第3张=5.000s" in prompt
    assert "不使用原视频绝对时间" in prompt


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


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
    response = client.post(
        "/api/v1/projects",
        json={"name": "模板创建回归测试", "code": "TEMPLATE-001"},
        headers=auth_headers,
    )
    assert response.status_code in (200, 201), response.text
    return response.json()["id"]


def _make_video() -> bytes:
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=0x26415f:s=640x360:r=24:d=4",
            "-an",
            "-f",
            "mp4",
            "-movflags",
            "frag_keyframe+empty_moov",
            "pipe:1",
        ],
        check=True,
        capture_output=True,
    )
    return result.stdout


def test_template_creator_extracts_frames_and_saves_preview_to_assets(
    client, project_id, auth_headers
):
    upload = client.post(
        f"/api/v1/projects/{project_id}/assets",
        files={"file": ("sample.mp4", _make_video(), "video/mp4")},
        headers=auth_headers,
    )
    assert upload.status_code == 201, upload.text
    source_id = upload.json()["id"]

    # 素材库列表会为旧视频补齐时长和分辨率，供模板创建器直接选择。
    listed_videos = client.get(
        f"/api/v1/projects/{project_id}/assets?asset_type=video",
        headers=auth_headers,
    )
    assert listed_videos.status_code == 200, listed_videos.text
    listed_source = next(item for item in listed_videos.json() if item["id"] == source_id)
    assert listed_source["duration_seconds"] > 3
    assert listed_source["width"] == 640
    assert listed_source["height"] == 360

    draft_response = client.post(
        f"/api/v1/projects/{project_id}/ai-video/template-drafts",
        json={
            "source_video_asset_id": source_id,
            "name": "建筑外景试用模板",
        },
        headers=auth_headers,
    )
    assert draft_response.status_code == 201, draft_response.text
    draft = draft_response.json()
    draft_id = draft["id"]
    assert draft["source_video_duration_seconds"] > 3

    clip = client.post(
        f"/api/v1/projects/{project_id}/ai-video/template-drafts/{draft_id}/clip",
        json={"clip_start_seconds": 0, "clip_end_seconds": 3, "middle_seconds": 1.5},
        headers=auth_headers,
    )
    assert clip.status_code == 200, clip.text
    clipped = clip.json()
    assert clipped["status"] == "frames_ready"
    assert clipped["first_frame_file_key"]
    assert clipped["middle_frame_file_key"]
    assert clipped["last_frame_file_key"]

    analyzed = client.post(
        f"/api/v1/projects/{project_id}/ai-video/template-drafts/{draft_id}/analyze",
        json={"intent": "强调建筑体量和立面关系"},
        headers=auth_headers,
    )
    assert analyzed.status_code == 200, analyzed.text
    assert analyzed.json()["prompt_recipe"]["prompt"]
    assert analyzed.json()["prompt_recipe"]["reference_timing_seconds"] == [0.0]
    assert analyzed.json()["prompt_recipe"]["clip_duration_seconds"] == 3.0
    assert analyzed.json()["prompt_recipe"]["recommended"]["duration"] == 3

    preview = client.post(
        f"/api/v1/projects/{project_id}/ai-video/template-drafts/{draft_id}/preview",
        json={"duration": 3},
        headers=auth_headers,
    )
    assert preview.status_code == 202, preview.text
    assert preview.json()["status"] == "success"

    assets = client.get(
        f"/api/v1/projects/{project_id}/assets?source=ai_video",
        headers=auth_headers,
    )
    assert assets.status_code == 200, assets.text
    trial_assets = [a for a in assets.json() if "视频模板试生成" in (a.get("tags") or [])]
    assert trial_assets, assets.json()

    published = client.post(
        f"/api/v1/projects/{project_id}/ai-video/template-drafts/{draft_id}/publish",
        json={"scope": "organization", "category": "建筑外景运镜"},
        headers=auth_headers,
    )
    assert published.status_code == 201, published.text
    assert published.json()["preview_asset_id"] == trial_assets[0]["id"]
    assert published.json()["preview_file_key"]
    assert published.json()["first_frame_file_key"]
    assert published.json()["last_frame_file_key"]

    # 发布后模板参考帧必须是模板自有副本；草稿重新提帧不能让已发布模板变空。
    published_template_id = published.json()["id"]
    published_reference_ids = published.json()["reference_frame_asset_ids"]
    assert len(published_reference_ids) >= 2
    reclip = client.post(
        f"/api/v1/projects/{project_id}/ai-video/template-drafts/{draft_id}/clip",
        json={"clip_start_seconds": 0.2, "clip_end_seconds": 3.2, "middle_seconds": 1.7},
        headers=auth_headers,
    )
    assert reclip.status_code == 200, reclip.text
    assets_after_reclip = client.get(
        f"/api/v1/projects/{project_id}/assets?asset_type=image",
        headers=auth_headers,
    )
    assert assets_after_reclip.status_code == 200
    asset_ids_after_reclip = {item["id"] for item in assets_after_reclip.json()}
    assert set(published_reference_ids).issubset(asset_ids_after_reclip)
    templates_after_reclip = client.get(
        f"/api/v1/projects/{project_id}/ai-video/templates",
        headers=auth_headers,
    )
    published_after_reclip = next(item for item in templates_after_reclip.json() if item["id"] == published_template_id)
    assert published_after_reclip["reference_frame_asset_ids"] == published_reference_ids


def test_template_library_scope_filters_personal_templates(client, project_id, auth_headers):
    created = client.post(
        f"/api/v1/projects/{project_id}/ai-video/templates",
        json={
            "name": "我的低空环绕模板",
            "scope": "personal",
            "default_positive_prompt": "镜头缓慢环绕建筑",
            "applicable_modes": ["first_last_frame_video"],
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    personal_id = created.json()["id"]

    personal = client.get(
        f"/api/v1/projects/{project_id}/ai-video/templates?scope=personal",
        headers=auth_headers,
    )
    assert personal.status_code == 200, personal.text
    assert personal_id in {item["id"] for item in personal.json()}
    assert all(item.get("scope") == "personal" for item in personal.json())

    organization = client.get(
        f"/api/v1/projects/{project_id}/ai-video/templates?scope=organization",
        headers=auth_headers,
    )
    assert organization.status_code == 200, organization.text
    assert personal_id not in {item["id"] for item in organization.json()}
