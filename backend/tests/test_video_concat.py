"""分镜拼接测试：多视频素材归一化拼接、转场、归档与异常路径。

覆盖：不同分辨率/帧率输入自动统一、无音频素材补静音轨、拼接成片归档素材库、
下载端点、少于 2 个素材 / 假视频 / 跨项目素材的校验。
"""

from __future__ import annotations

import io
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.services.video_composer import probe_media  # noqa: E402

FFMPEG = shutil.which("ffmpeg")
pytestmark = pytest.mark.skipif(not FFMPEG, reason="需要 ffmpeg")


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def auth_headers(client):
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@fastvideo.cn", "password": "admin123456"},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture()
def project_id(client, auth_headers):
    resp = client.post(
        "/api/v1/projects",
        json={"name": "分镜拼接测试", "code": "CONCAT-001"},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _mkclip(*, width: int, height: int, fps: int, duration: float, with_audio: bool) -> bytes:
    """生成一个小测试视频：testsrc 画面，可带 sine 音轨。"""
    out = Path(tempfile.mkstemp(prefix="fv_concat_src_", suffix=".mp4")[1])
    cmd = [
        FFMPEG, "-y",
        "-f", "lavfi", "-i", f"testsrc=size={width}x{height}:rate={fps}:duration={duration}",
    ]
    if with_audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
    if with_audio:
        cmd += ["-c:a", "aac", "-shortest"]
    cmd.append(str(out))
    proc = subprocess.run(cmd, capture_output=True, timeout=120)
    assert proc.returncode == 0, proc.stderr.decode()[-500:]
    data = out.read_bytes()
    out.unlink(missing_ok=True)
    return data


def _upload_video(client, project_id, auth_headers, data: bytes, name: str) -> dict:
    resp = client.post(
        f"/api/v1/projects/{project_id}/assets",
        files={"file": (f"{name}.mp4", io.BytesIO(data), "video/mp4")},
        data={"name": name},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_concat_success_normalizes_and_archives(client, auth_headers, project_id):
    a = _upload_video(client, project_id, auth_headers, _mkclip(width=640, height=360, fps=15, duration=2, with_audio=True), "剪映片段A")
    b = _upload_video(client, project_id, auth_headers, _mkclip(width=320, height=240, fps=10, duration=2, with_audio=False), "无声片段B")

    resp = client.post(
        f"/api/v1/projects/{project_id}/video-concats",
        json={
            "name": "测试拼接",
            "width": 320,
            "height": 240,
            "fps": 24,
            "items": [
                {"asset_id": a["id"], "transition_type": "crossfade", "transition_duration": 0.5},
                {"asset_id": b["id"]},
            ],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 202, resp.text
    task = resp.json()
    assert task["status"] == "success", task.get("error_message")
    assert task["output_url"]
    # 总时长 = 2 + 2 - 0.5 转场
    assert abs(task["duration_seconds"] - 3.5) < 0.3

    data = client.get(f"/api/v1/video-concats/{task['id']}/download", headers=auth_headers)
    assert data.status_code == 200
    assert data.content[4:8] == b"ftyp"
    info = probe_media(data.content, ".mp4")
    assert info["decodable"] is True
    assert (info["width"], info["height"]) == (320, 240)
    assert info["fps"] == 24
    assert info["has_audio"] is True

    # 成片归档进素材库，可再次作为拼接输入
    assets = client.get(f"/api/v1/projects/{project_id}/assets", params={"asset_type": "video", "source": "render"}, headers=auth_headers).json()
    archived = [item for item in assets if item["name"].startswith("测试拼接")]
    assert archived, "拼接成片应归档到素材库"
    assert archived[0]["duration_seconds"] == pytest.approx(task["duration_seconds"], abs=0.01)

    # 列表端点能查到该任务
    tasks = client.get(f"/api/v1/projects/{project_id}/video-concats", headers=auth_headers).json()
    assert any(t["id"] == task["id"] for t in tasks)


def test_concat_requires_two_items(client, auth_headers, project_id):
    a = _upload_video(client, project_id, auth_headers, _mkclip(width=320, height=240, fps=24, duration=1, with_audio=True), "单片段")
    resp = client.post(
        f"/api/v1/projects/{project_id}/video-concats",
        json={"items": [{"asset_id": a["id"]}]},
        headers=auth_headers,
    )
    assert resp.status_code == 422


def test_concat_rejects_duplicate_items(client, auth_headers, project_id):
    a = _upload_video(client, project_id, auth_headers, _mkclip(width=320, height=240, fps=24, duration=1, with_audio=True), "重复片段")
    resp = client.post(
        f"/api/v1/projects/{project_id}/video-concats",
        json={"items": [{"asset_id": a["id"]}, {"asset_id": a["id"]}]},
        headers=auth_headers,
    )
    assert resp.status_code == 409


def test_concat_rejects_undecodable_video(client, auth_headers, project_id):
    bad = _upload_video(client, project_id, auth_headers, b"this is not a video", "假视频")
    good = _upload_video(client, project_id, auth_headers, _mkclip(width=320, height=240, fps=24, duration=1, with_audio=True), "好片段")
    resp = client.post(
        f"/api/v1/projects/{project_id}/video-concats",
        json={"items": [{"asset_id": bad["id"]}, {"asset_id": good["id"]}]},
        headers=auth_headers,
    )
    assert resp.status_code == 409


def test_concat_rejects_foreign_project_asset(client, auth_headers):
    resp = client.post("/api/v1/projects", json={"name": "拼接外部项目", "code": "CONCAT-002"}, headers=auth_headers)
    other_project = resp.json()["id"]
    foreign = _upload_video(client, other_project, auth_headers, _mkclip(width=320, height=240, fps=24, duration=1, with_audio=True), "外部片段")

    resp = client.post("/api/v1/projects", json={"name": "拼接本项目", "code": "CONCAT-003"}, headers=auth_headers)
    my_project = resp.json()["id"]
    mine = _upload_video(client, my_project, auth_headers, _mkclip(width=320, height=240, fps=24, duration=1, with_audio=True), "本段")

    resp = client.post(
        f"/api/v1/projects/{my_project}/video-concats",
        json={"items": [{"asset_id": foreign["id"]}, {"asset_id": mine["id"]}]},
        headers=auth_headers,
    )
    assert resp.status_code == 409
