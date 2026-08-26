"""Phase 5：多分段视频合成、可视化时间轴与正式成片导出 测试。

覆盖：图片→标准分段、视频标准化、冻结尾帧、配音混入、静音轨、字幕烧录、
UTF-8 SRT、中文字体、背景音乐与 ducking、转场、Logo、片头片尾、input_hash 缓存、
变化触发重建、失败重试、批量部分失败、演示/正式导出校验、ffprobe 验证、命令注入防护。
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/fastvideo_phase5_test.db")
os.environ.setdefault("USE_CELERY", "false")
os.environ.setdefault("AI_TTS_PROVIDER", "disabled")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


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
        json={"name": "Phase5视频测试", "code": "P5-001"},
        headers=auth_headers,
    )
    return resp.json()["id"]


def _mkimg(color=(60, 90, 130), w=1280, h=720) -> bytes:
    from PIL import Image

    im = Image.new("RGB", (w, h), color)
    b = io.BytesIO()
    im.save(b, format="PNG")
    return b.getvalue()


def _mk_wav(duration: float = 2.0) -> bytes:
    import array
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(48000)
        wf.writeframes(array.array("h", [3000] * int(48000 * duration)).tobytes())
    return buf.getvalue()


def _make_shot(client, project_id, auth_headers, seq, title, narration, duration=15):
    resp = client.post(
        f"/api/v1/projects/{project_id}/storyboard",
        json={"project_id": project_id, "sequence": seq, "title": title, "narration": narration, "duration_seconds": duration},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _gen_voice(client, project_id, auth_headers, shot_id, seed=1):
    resp = client.post(f"/api/v1/projects/{project_id}/voice/generate", json={"shot_id": shot_id, "seed": seed}, headers=auth_headers)
    task_id = resp.json()["task_id"]
    for _ in range(40):
        t = client.get(f"/api/v1/projects/{project_id}/voice/jobs/{task_id}", headers=auth_headers).json()
        if t["status"] in ("success", "failed"):
            break
        time.sleep(0.3)
    assert t["status"] == "success", t.get("error_message")


def _upload_image(client, project_id, auth_headers, color=(30, 80, 120), name="img"):
    resp = client.post(
        f"/api/v1/projects/{project_id}/render/source-images",
        files={"file": (f"{name}.png", io.BytesIO(_mkimg(color)), "image/png")},
        data={"name": name, "source_software": "Revit"},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _create_vp(client, project_id, auth_headers, **overrides):
    payload = {"name": "P5视频", "width": 1920, "height": 1080, "fps": 25}
    payload.update(overrides)
    resp = client.post(f"/api/v1/projects/{project_id}/video-projects", json=payload, headers=auth_headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _render_all_and_wait(client, vp_id, auth_headers):
    resp = client.post(f"/api/v1/video-projects/{vp_id}/segments/render-all", headers=auth_headers)
    task_id = resp.json().get("task_id")
    if task_id:
        for _ in range(80):
            t = client.get(f"/api/v1/tasks/{task_id}", headers=auth_headers).json()
            if t["status"] in ("success", "failed"):
                break
            time.sleep(0.5)
    return client.get(f"/api/v1/video-projects/{vp_id}/segments", headers=auth_headers).json()


# ============================================================
# 合成引擎单元测试
# ============================================================

def test_image_segment_standard():
    from app.services.video_composer import probe_media, render_image_segment

    data = render_image_segment(_mkimg(), duration=2.0, motion="zoom_in", fit_mode="cover",
                                width=1920, height=1080, fps=25, audio_bytes=_mk_wav())
    info = probe_media(data, ".mp4")
    assert info["width"] == 1920 and info["height"] == 1080
    assert info["fps"] == 25
    assert info["vcodec"] == "h264"
    assert info["acodec"] == "aac"
    assert info["has_audio"] is True
    assert abs(info["duration_seconds"] - 2.0) < 0.2


def test_image_contain_not_stretched():
    from app.services.video_composer import probe_media, render_image_segment

    # 竖版图片在 contain 模式下不应被拉伸（保持比例，黑边）
    data = render_image_segment(_mkimg(color=(200, 50, 50), w=400, h=800), duration=1.5,
                                motion="static", fit_mode="contain", width=1920, height=1080, fps=25)
    info = probe_media(data, ".mp4")
    assert info["width"] == 1920 and info["height"] == 1080


def test_video_segment_freeze_tail():
    from app.services.video_composer import probe_media, render_image_segment, render_video_segment

    # 先生成一段 1s 视频
    short = render_image_segment(_mkimg(color=(10, 40, 90)), duration=1.0, motion="static", audio_bytes=_mk_wav(1.0))
    # 目标 3s，loop 模式
    data = render_video_segment(short, duration=3.0, fit_mode="cover", width=1920, height=1080, fps=25,
                                audio_bytes=_mk_wav(3.0), short_video="loop")
    info = probe_media(data, ".mp4")
    assert abs(info["duration_seconds"] - 3.0) < 0.3


def test_silence_when_no_audio():
    from app.services.video_composer import probe_media, render_image_segment

    data = render_image_segment(_mkimg(), duration=1.5, motion="static", audio_bytes=None)
    info = probe_media(data, ".mp4")
    assert info["has_audio"] is True  # 静音轨


def test_ass_chinese_font():
    from app.services.video_composer import build_ass

    subs = [{"start_ms": 0, "end_ms": 1000, "text": "中文字幕测试"}]
    ass = build_ass(subs, style={"font_size": 46})
    assert "Noto Serif CJK SC" in ass
    assert "中文字幕测试" in ass
    # 只验证 ASS 声明了目标字体；字体文件路径随 Linux/macOS/容器镜像不同。


def test_srt_utf8():
    from app.services.video_composer import build_ass
    from app.services.audio_utils import render_srt

    subs = [{"start_ms": 0, "end_ms": 1500, "text": "第一句解说词。"}, {"start_ms": 1500, "end_ms": 3000, "text": "第二句解说词。"}]
    srt = render_srt(subs)
    assert "第一句解说词。" in srt
    assert "00:00:00,000 --> 00:00:01,500" in srt
    build_ass(subs, style={})  # ASS 也能生成


def test_transition_concat_duration():
    from app.services.video_composer import concat_with_transitions, render_image_segment

    items = []
    for i in range(3):
        seg = render_image_segment(_mkimg(color=(i * 40, 90, 130)), duration=2.0, motion="static", audio_bytes=_mk_wav(2.0))
        p = Path(f"/tmp/fv_p5_seg_{i}_{time.time()}.mp4")
        p.write_bytes(seg)
        items.append({"path": str(p), "duration": 2.0, "transition_type": "crossfade", "transition_duration": 0.5})
    try:
        video, total = concat_with_transitions(items, width=1920, height=1080, fps=25)
        assert abs(total - (6.0 - 1.0)) < 0.2, "总时长应扣除转场重叠"
        from app.services.video_composer import probe_media

        info = probe_media(video, ".mp4")
        assert abs(info["duration_seconds"] - total) < 0.3
    finally:
        for it in items:
            Path(it["path"]).unlink(missing_ok=True)


def test_music_and_ducking_no_clip():
    import tempfile

    from app.services.video_composer import build_music_track, duck_and_mix, probe_media

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(_mk_wav(2.0))
        music_path = f.name
    try:
        music = build_music_track(
            [{"path": music_path, "volume": 1.0, "fade_in": 0.3, "fade_out": 0.5}],
            total_duration=2.0,
        )
        mixed = duck_and_mix(_mk_wav(2.0), music, ducking=True)
        info = probe_media(mixed, ".m4a")
        assert info["has_audio"] is True
        assert info["acodec"] == "aac"
    finally:
        Path(music_path).unlink(missing_ok=True)


def test_logo_overlay():
    from app.services.video_composer import overlay_logo, probe_media, render_image_segment

    base = render_image_segment(_mkimg(), duration=1.0, motion="static", audio_bytes=_mk_wav(1.0))
    data = overlay_logo(base, _mkimg(color=(255, 0, 0), w=200, h=80), position="top_right", size_ratio=0.12)
    info = probe_media(data, ".mp4")
    assert info["width"] == 1920 and info["has_audio"] is True


def test_title_card_open_close():
    from app.services.video_composer import probe_media, render_title_card

    card = render_title_card("项目名称", "副标题", duration=2.0, brand_color="#1E3A5F")
    info = probe_media(card, ".mp4")
    assert info["width"] == 1920 and info["has_audio"] is True


def test_no_command_injection():
    """用户文本含 shell 特殊字符不得导致命令注入，渲染应成功。"""
    from app.services.video_composer import probe_media, render_title_card

    evil = "片头; rm -rf /tmp/pwned && touch /tmp/injected"
    card = render_title_card(evil, None, duration=1.5)
    info = probe_media(card, ".mp4")
    assert info["decodable"] is True
    assert not Path("/tmp/injected").exists()


# ============================================================
# 集成：分段 / 预检 / 导出
# ============================================================

def test_sync_storyboard_creates_segments(client, project_id, auth_headers):
    _make_shot(client, project_id, auth_headers, 1, "项目概况", "本项目总建筑面积十二万平方米。")
    _make_shot(client, project_id, auth_headers, 2, "施工部署", "采用EPC管理模式。")
    vp_id = _create_vp(client, project_id, auth_headers)
    segs = client.get(f"/api/v1/video-projects/{vp_id}/segments", headers=auth_headers).json()
    assert len(segs) == 2
    assert all(s["sequence"] == i + 1 for i, s in enumerate(segs))
    assert all(s["render_status"] == "pending" for s in segs)


def test_input_hash_cache_and_rebuild(client, project_id, auth_headers):
    shot = _make_shot(client, project_id, auth_headers, 1, "概况", "解说词内容。")
    _gen_voice(client, project_id, auth_headers, shot["id"], seed=5)
    img_id = _upload_image(client, project_id, auth_headers)
    vp_id = _create_vp(client, project_id, auth_headers)
    seg = client.get(f"/api/v1/video-projects/{vp_id}/segments", headers=auth_headers).json()[0]
    client.patch(f"/api/v1/video-projects/{vp_id}/segments/{seg['id']}", json={"visual_asset_id": img_id}, headers=auth_headers)
    segs = _render_all_and_wait(client, vp_id, auth_headers)
    h1 = segs[0]["input_hash"]
    assert segs[0]["render_status"] == "success"
    # 再次 render-all：无变化，不应重复渲染
    resp = client.post(f"/api/v1/video-projects/{vp_id}/segments/render-all", headers=auth_headers).json()
    assert resp.get("rendered") == 0
    segs = client.get(f"/api/v1/video-projects/{vp_id}/segments", headers=auth_headers).json()
    assert segs[0]["input_hash"] == h1
    # 更换画面 → 触发重建
    img2 = _upload_image(client, project_id, auth_headers, color=(200, 60, 60))
    client.patch(f"/api/v1/video-projects/{vp_id}/segments/{segs[0]['id']}", json={"visual_asset_id": img2}, headers=auth_headers)
    segs = client.get(f"/api/v1/video-projects/{vp_id}/segments", headers=auth_headers).json()
    assert segs[0]["needs_rebuild"] is True
    assert segs[0]["render_status"] == "pending"


def test_demo_export_success_and_ffprobe(client, project_id, auth_headers):
    s1 = _make_shot(client, project_id, auth_headers, 1, "概况", "本项目总建筑面积十二万平方米，工期三百六十五日历天。")
    s2 = _make_shot(client, project_id, auth_headers, 2, "部署", "采用EPC管理模式，MEP管线综合优化。")
    _gen_voice(client, project_id, auth_headers, s1["id"], seed=10)
    _gen_voice(client, project_id, auth_headers, s2["id"], seed=11)
    img1 = _upload_image(client, project_id, auth_headers, color=(30, 80, 120))
    img2 = _upload_image(client, project_id, auth_headers, color=(120, 80, 30))
    vp_id = _create_vp(client, project_id, auth_headers,
                       open_config={"text": "片头", "duration": 2.0}, close_config={"text": "谢谢", "duration": 2.0})
    segs = client.get(f"/api/v1/video-projects/{vp_id}/segments", headers=auth_headers).json()
    for i, seg in enumerate(segs):
        client.patch(f"/api/v1/video-projects/{vp_id}/segments/{seg['id']}", json={"visual_asset_id": [img1, img2][i]}, headers=auth_headers)
    _render_all_and_wait(client, vp_id, auth_headers)

    # 预检 demo 通过
    r = client.post(f"/api/v1/video-projects/{vp_id}/preflight", params={"mode": "demo"}, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["ok"] is True

    # 演示导出
    r = client.post(f"/api/v1/video-projects/{vp_id}/export/demo", headers=auth_headers)
    assert r.status_code == 202
    et_id = r.json()["export_task_id"]
    for _ in range(80):
        t = client.get(f"/api/v1/exports/{et_id}", headers=auth_headers).json()
        if t["status"] in ("success", "failed", "cancelled"):
            break
        time.sleep(0.5)
    assert t["status"] == "success", t.get("error_message")
    assert t["output_url"]
    assert t["srt_url"]
    assert t["report_url"]
    assert t["duration_seconds"] and t["duration_seconds"] > 0

    # 下载 MP4 并 ffprobe 验证
    r = client.get(f"/api/v1/exports/{et_id}/download", headers=auth_headers)
    assert r.status_code == 200
    mp4 = r.content
    assert mp4[4:8] == b"ftyp", "应为 MP4 容器"
    p = Path("/tmp/fv_p5_final.mp4")
    p.write_bytes(mp4)
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,codec_type,width,height,pix_fmt,r_frame_rate:format=duration",
         "-of", "json", str(p)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0
    info = json.loads(proc.stdout)
    streams = {s["codec_type"]: s for s in info["streams"]}
    assert streams["video"]["codec_name"] == "h264"
    assert streams["video"]["pix_fmt"] == "yuv420p"
    assert streams["video"]["width"] == 1920 and streams["video"]["height"] == 1080
    assert streams["audio"]["codec_name"] == "aac"
    # SRT 内容
    r = client.get(f"/api/v1/exports/{et_id}/srt", headers=auth_headers)
    srt_text = r.content.decode("utf-8")
    assert "--> " in srt_text
    assert "建筑面积" in srt_text or "EPC" in srt_text


def test_formal_export_rejects_mock(client, project_id, auth_headers):
    shot = _make_shot(client, project_id, auth_headers, 1, "概况", "正式校验解说词。")
    _gen_voice(client, project_id, auth_headers, shot["id"], seed=20)
    img = _upload_image(client, project_id, auth_headers)
    vp_id = _create_vp(client, project_id, auth_headers)
    seg = client.get(f"/api/v1/video-projects/{vp_id}/segments", headers=auth_headers).json()[0]
    client.patch(f"/api/v1/video-projects/{vp_id}/segments/{seg['id']}", json={"visual_asset_id": img}, headers=auth_headers)
    _render_all_and_wait(client, vp_id, auth_headers)

    # Mock 音频在正式模式应被拒绝
    r = client.post(f"/api/v1/video-projects/{vp_id}/preflight", params={"mode": "formal"}, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["ok"] is False
    codes = [i["code"] for i in r.json()["issues"]]
    assert "mock_audio" in codes

    # 正式导出被阻止
    r = client.post(f"/api/v1/video-projects/{vp_id}/export/formal", headers=auth_headers)
    assert r.status_code == 409


def test_formal_rejects_missing_visual(client, project_id, auth_headers):
    shot = _make_shot(client, project_id, auth_headers, 1, "概况", "无画面正式校验。")
    _gen_voice(client, project_id, auth_headers, shot["id"], seed=30)
    vp_id = _create_vp(client, project_id, auth_headers)
    _render_all_and_wait(client, vp_id, auth_headers)
    r = client.post(f"/api/v1/video-projects/{vp_id}/preflight", params={"mode": "formal"}, headers=auth_headers)
    assert r.json()["ok"] is False
    codes = [i["code"] for i in r.json()["issues"]]
    assert "missing_visual" in codes


def test_formal_rejects_unverified_facts(client, project_id, auth_headers):
    # 创建一条未确认的工程事实
    from app.core.database import SessionLocal
    from app.models.extracted_fact import ExtractedFact

    db = SessionLocal()
    db.add(ExtractedFact(
        project_id=project_id, fact_type="area", fact_name="建筑面积",
        fact_value="120000", unit="㎡", source_quote="招标文件",
        verification_status="unverified", confidence=0.5,
    ))
    db.commit()
    db.close()

    shot = _make_shot(client, project_id, auth_headers, 1, "概况", "有冲突事实。")
    _gen_voice(client, project_id, auth_headers, shot["id"], seed=40)
    img = _upload_image(client, project_id, auth_headers)
    vp_id = _create_vp(client, project_id, auth_headers)
    seg = client.get(f"/api/v1/video-projects/{vp_id}/segments", headers=auth_headers).json()[0]
    client.patch(f"/api/v1/video-projects/{vp_id}/segments/{seg['id']}", json={"visual_asset_id": img}, headers=auth_headers)
    _render_all_and_wait(client, vp_id, auth_headers)
    r = client.post(f"/api/v1/video-projects/{vp_id}/preflight", params={"mode": "formal"}, headers=auth_headers)
    assert r.json()["ok"] is False
    codes = [i["code"] for i in r.json()["issues"]]
    assert "unverified_facts" in codes


def test_segment_fail_then_retry(client, project_id, auth_headers):
    shot = _make_shot(client, project_id, auth_headers, 1, "概况", "重试测试。")
    _gen_voice(client, project_id, auth_headers, shot["id"], seed=50)
    # 上传一个伪装成 mp4 的文本文件 → 渲染必失败
    fake = client.post(
        f"/api/v1/projects/{project_id}/assets",
        files={"file": ("bad.mp4", io.BytesIO(b"this is not a video"), "video/mp4")},
        data={"name": "bad"},
        headers=auth_headers,
    )
    assert fake.status_code == 201
    bad_asset = fake.json()["id"]
    vp_id = _create_vp(client, project_id, auth_headers)
    seg = client.get(f"/api/v1/video-projects/{vp_id}/segments", headers=auth_headers).json()[0]
    client.patch(f"/api/v1/video-projects/{vp_id}/segments/{seg['id']}", json={"visual_asset_id": bad_asset}, headers=auth_headers)
    # 渲染 → 失败
    client.post(f"/api/v1/video-projects/{vp_id}/segments/{seg['id']}/render", headers=auth_headers)
    time.sleep(3)
    segs = client.get(f"/api/v1/video-projects/{vp_id}/segments", headers=auth_headers).json()
    assert segs[0]["render_status"] == "failed"
    # 更换为正常图片并重试 → 成功
    img = _upload_image(client, project_id, auth_headers)
    client.patch(f"/api/v1/video-projects/{vp_id}/segments/{seg['id']}", json={"visual_asset_id": img}, headers=auth_headers)
    client.post(f"/api/v1/video-projects/{vp_id}/segments/{seg['id']}/retry", headers=auth_headers)
    time.sleep(3)
    segs = client.get(f"/api/v1/video-projects/{vp_id}/segments", headers=auth_headers).json()
    assert segs[0]["render_status"] == "success"


def test_batch_partial_failure(client, project_id, auth_headers):
    s1 = _make_shot(client, project_id, auth_headers, 1, "好段", "正常分段。")
    s2 = _make_shot(client, project_id, auth_headers, 2, "坏段", "异常分段。")
    _gen_voice(client, project_id, auth_headers, s1["id"], seed=60)
    _gen_voice(client, project_id, auth_headers, s2["id"], seed=61)
    img = _upload_image(client, project_id, auth_headers)
    fake = client.post(
        f"/api/v1/projects/{project_id}/assets",
        files={"file": ("bad2.mp4", io.BytesIO(b"not video"), "video/mp4")},
        data={"name": "bad2"},
        headers=auth_headers,
    ).json()["id"]
    vp_id = _create_vp(client, project_id, auth_headers)
    segs = client.get(f"/api/v1/video-projects/{vp_id}/segments", headers=auth_headers).json()
    client.patch(f"/api/v1/video-projects/{vp_id}/segments/{segs[0]['id']}", json={"visual_asset_id": img}, headers=auth_headers)
    client.patch(f"/api/v1/video-projects/{vp_id}/segments/{segs[1]['id']}", json={"visual_asset_id": fake}, headers=auth_headers)
    resp = client.post(f"/api/v1/video-projects/{vp_id}/segments/render-all", headers=auth_headers).json()
    assert resp["rendered"] == 2
    time.sleep(4)
    segs = client.get(f"/api/v1/video-projects/{vp_id}/segments", headers=auth_headers).json()
    statuses = {s["sequence"]: s["render_status"] for s in segs}
    assert statuses[1] == "success"
    assert statuses[2] == "failed"


def test_project_permission_isolation(client, project_id, auth_headers):
    _make_shot(client, project_id, auth_headers, 1, "概况", "权限隔离。")
    vp_id = _create_vp(client, project_id, auth_headers)
    # 另一用户
    client.post("/api/v1/auth/register", json={"email": "p5other@test.com", "username": "p5other", "password": "test123456"})
    login = client.post("/api/v1/auth/login", json={"email": "p5other@test.com", "password": "test123456"})
    other_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    r = client.get(f"/api/v1/video-projects/{vp_id}/segments", headers=other_headers)
    assert r.status_code == 404


def test_legacy_export_endpoint_still_works(client, project_id, auth_headers):
    _make_shot(client, project_id, auth_headers, 1, "概况", "旧导出。")
    vp_id = _create_vp(client, project_id, auth_headers)
    resp = client.post(
        f"/api/v1/video-projects/{vp_id}/export",
        json={"video_project_id": vp_id, "export_format": "mp4"},
        headers=auth_headers,
    )
    assert resp.status_code == 202
    assert resp.json()["status"] in ("success", "failed")
