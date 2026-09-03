"""自定义合成测试：自选视频 + 自输字幕/TTS 直接合成，不绑定分镜。

覆盖：静音/保留原声/TTS 三种配音模式、字幕切分与时间分配、
素材库归档、异常路径（无素材、缺模板、缺文本）。
"""

from __future__ import annotations

import io
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.services.custom_segment_service import (  # noqa: E402
    distribute_subtitles,
    split_subtitle_lines,
)
from app.services.video_composer import probe_media  # noqa: E402

FFMPEG = shutil.which("ffmpeg")


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
        json={"name": "自定义合成测试", "code": "CUSTOM-001"},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _mkclip(*, width: int = 320, height: int = 240, fps: int = 24, duration: float = 3.0, with_audio: bool) -> bytes:
    out = Path(tempfile.mkstemp(prefix="fv_custom_src_", suffix=".mp4")[1])
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


def _create_and_wait(client, project_id, auth_headers, payload: dict) -> dict:
    resp = client.post(f"/api/v1/projects/{project_id}/custom-segments", json=payload, headers=auth_headers)
    assert resp.status_code == 202, resp.text
    task_id = resp.json()["task_id"]
    for _ in range(60):
        task = client.get(f"/api/v1/tasks/{task_id}", headers=auth_headers).json()
        if task["status"] in ("success", "failed", "cancelled"):
            return task
        time.sleep(0.3)
    pytest.fail(f"任务未结束: {task['status']}")


# ============================================================
# 字幕切分（纯函数）
# ============================================================

def test_split_subtitle_lines():
    lines = split_subtitle_lines("项目区位优势明显。\n交通便利，配套完善；产业集聚效应显著！")
    assert lines == ["项目区位优势明显。", "交通便利，配套完善；", "产业集聚效应显著！"]
    assert split_subtitle_lines("") == []
    assert split_subtitle_lines("  \n  ") == []
    # 无标点超长句硬切，每行不超过上限
    long_lines = split_subtitle_lines("一" * 70)
    assert all(len(line) <= 28 for line in long_lines)
    assert "".join(long_lines) == "一" * 70


def test_distribute_subtitles_covers_duration():
    subs = distribute_subtitles(["短", "这是一条比较长的字幕句子"], 10.0)
    assert subs[0]["start_ms"] == 0
    assert subs[-1]["end_ms"] == 10000
    assert subs[1]["start_ms"] == subs[0]["end_ms"]
    # 长句分到更长时间
    assert (subs[1]["end_ms"] - subs[1]["start_ms"]) > (subs[0]["end_ms"] - subs[0]["start_ms"])


# ============================================================
# 合成任务
# ============================================================

@pytest.mark.skipif(not FFMPEG, reason="需要 ffmpeg")
def test_custom_segment_mute_with_subtitles(client, auth_headers, project_id):
    clip = _upload_video(client, project_id, auth_headers, _mkclip(duration=3, with_audio=False), "无声素材")
    task = _create_and_wait(client, project_id, auth_headers, {
        "name": "静音合成",
        "visual_asset_id": clip["id"],
        "duration": 4.0,
        "subtitle_text": "第一段字幕。第二段字幕。",
        "audio_mode": "mute",
        "width": 320,
        "height": 240,
        "fps": 24,
    })
    assert task["status"] == "success", task.get("error_message")
    result = task["result"]
    assert abs(result["duration"] - 4.0) < 0.01

    assets = client.get(
        f"/api/v1/projects/{project_id}/assets",
        params={"asset_type": "video", "source": "render"},
        headers=auth_headers,
    ).json()
    archived = [a for a in assets if a["name"].startswith("静音合成")]
    assert archived, "自定义合成成片应归档到素材库"
    info = probe_media(client.get(f"/files/{result['output_key']}", headers=auth_headers).content, ".mp4")
    assert (info["width"], info["height"], info["fps"]) == (320, 240, 24)


@pytest.mark.skipif(not FFMPEG, reason="需要 ffmpeg")
def test_custom_segment_keep_original_audio(client, auth_headers, project_id):
    clip = _upload_video(client, project_id, auth_headers, _mkclip(duration=3, with_audio=True), "有声素材")
    task = _create_and_wait(client, project_id, auth_headers, {
        "name": "原声合成",
        "visual_asset_id": clip["id"],
        "audio_mode": "keep_original",
        "width": 320,
        "height": 240,
        "fps": 24,
    })
    assert task["status"] == "success", task.get("error_message")
    # 未指定时长 → 跟随素材时长
    assert abs(task["result"]["duration"] - 3.0) < 0.2
    info = probe_media(client.get(f"/files/{task['result']['output_key']}", headers=auth_headers).content, ".mp4")
    assert info["has_audio"] is True


@pytest.mark.skipif(not FFMPEG, reason="需要 ffmpeg")
def test_custom_segment_tts(client, auth_headers, project_id):
    tpl = client.post(
        f"/api/v1/projects/{project_id}/voices",
        json={"name": "测试音色", "voice_provider": "mock"},
        headers=auth_headers,
    )
    assert tpl.status_code == 201, tpl.text
    clip = _upload_video(client, project_id, auth_headers, _mkclip(duration=3, with_audio=False), "TTS素材")
    task = _create_and_wait(client, project_id, auth_headers, {
        "name": "TTS合成",
        "visual_asset_id": clip["id"],
        "subtitle_text": "这里是自定义合成的配音文本，用于验证朗读。",
        "audio_mode": "tts",
        "voice_template_id": tpl.json()["id"],
        "width": 320,
        "height": 240,
        "fps": 24,
    })
    assert task["status"] == "success", task.get("error_message")
    assert task["result"]["is_mock_tts"] is True
    info = probe_media(client.get(f"/files/{task['result']['output_key']}", headers=auth_headers).content, ".mp4")
    assert info["has_audio"] is True


def test_custom_segment_missing_asset(client, auth_headers, project_id):
    resp = client.post(
        f"/api/v1/projects/{project_id}/custom-segments",
        json={"visual_asset_id": "nonexistent"},
        headers=auth_headers,
    )
    assert resp.status_code == 404


def test_custom_segment_tts_requires_template_and_text(client, auth_headers, project_id):
    resp = client.post(
        f"/api/v1/projects/{project_id}/custom-segments",
        json={"visual_asset_id": "whatever", "audio_mode": "tts"},
        headers=auth_headers,
    )
    assert resp.status_code == 409


@pytest.mark.skipif(not FFMPEG, reason="需要 ffmpeg")
def test_custom_segment_tts_missing_template_fails(client, auth_headers, project_id):
    clip = _upload_video(client, project_id, auth_headers, _mkclip(duration=1, with_audio=False), "校验素材")
    task = _create_and_wait(client, project_id, auth_headers, {
        "visual_asset_id": clip["id"],
        "audio_mode": "tts",
        "voice_template_id": "missing-tpl",
        "subtitle_text": "文本",
        "width": 320,
        "height": 240,
        "fps": 24,
    })
    assert task["status"] == "failed"
    assert "配音模板" in (task.get("error_message") or "")
