"""Phase 4：AI 配音模板、时长智能适配、音频版本管理与 SRT 字幕生成 测试。

覆盖：中文朗读规范化、Mock TTS 真实 WAV、时长估算、单条生成、
版本管理、解说词变化追踪、字幕 SRT、发音词典、批量生成、授权、跨项目隔离。
"""

from __future__ import annotations

import io
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/fastvideo_phase4_test.db")
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
        json={"name": "Phase4配音测试", "code": "P4-001"},
        headers=auth_headers,
    )
    return resp.json()["id"]


def _make_shot(client, project_id, auth_headers, sequence=1, title="分镜", narration="测试解说词。", duration=20):
    resp = client.post(
        f"/api/v1/projects/{project_id}/storyboard",
        json={
            "project_id": project_id,
            "sequence": sequence,
            "title": title,
            "narration": narration,
            "duration_seconds": duration,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _generate_and_wait(client, project_id, auth_headers, shot_id, **overrides):
    payload = {"shot_id": shot_id}
    payload.update(overrides)
    resp = client.post(f"/api/v1/projects/{project_id}/voice/generate", json=payload, headers=auth_headers)
    assert resp.status_code == 202, resp.text
    task_id = resp.json()["task_id"]
    for _ in range(30):
        t = client.get(f"/api/v1/projects/{project_id}/voice/jobs/{task_id}", headers=auth_headers).json()
        if t["status"] in ("success", "failed"):
            break
        time.sleep(0.3)
    assert t["status"] == "success", t.get("error_message")
    return task_id


# ============================================================
# 中文朗读规范化
# ============================================================

def test_normalizer_dates_numbers():
    from app.services.narration_normalizer import normalize_narration

    r = normalize_narration("2026年3月1日开工，工期365日历天，总建筑面积120000㎡。")
    assert "二千零二十六年三月一日" in r.normalized_text
    assert "三百六十五日历天" in r.normalized_text
    assert "十二万平方米" in r.normalized_text


def test_normalizer_units_and_abbr():
    from app.services.narration_normalizer import normalize_narration

    r = normalize_narration("35.6m高，C40混凝土，8.5MPa，湿度99.5%。")
    assert "三十五点六米高" in r.normalized_text
    assert "C四零混凝土" in r.normalized_text
    assert "八点五兆帕" in r.normalized_text
    assert "百分之九十九点五" in r.normalized_text


def test_normalizer_keeps_abbreviations():
    from app.services.narration_normalizer import normalize_narration

    r = normalize_narration("采用BIM技术和EPC模式，MEP管线长度1200米。")
    assert "BIM" in r.normalized_text
    assert "EPC" in r.normalized_text
    assert "MEP" in r.normalized_text
    assert "一千二百米" in r.normalized_text


def test_normalizer_ten_to_nineteen():
    from app.services.narration_normalizer import normalize_narration

    r = normalize_narration("每天14:30召开协调会，计划32层，第2标段。")
    assert "十四点三十分" in r.normalized_text
    assert "三十二层" in r.normalized_text
    assert "第二标段" in r.normalized_text


def test_normalizer_custom_dictionary():
    from app.services.narration_normalizer import normalize_narration

    class _Rule:
        id = "r1"
        source_text = "XX工程公司"
        spoken_text = "某工程公司"
        rule_type = "company"
        priority = 100
        is_regex = False
        scope = "project"

    r = normalize_narration("本项目由XX工程公司承建。", rules=[_Rule()])
    assert "某工程公司" in r.normalized_text
    assert r.pronunciation_snapshot[0]["rule_id"] == "r1"


# ============================================================
# Mock TTS
# ============================================================

def test_mock_wav_valid_and_deterministic():
    from app.adapters.tts import MockTTSAdapter

    adapter = MockTTSAdapter()
    w1 = adapter.synthesize("测试文本。第二句。", voice="mock_male", format="wav", seed=42)
    w2 = adapter.synthesize("测试文本。第二句。", voice="mock_male", format="wav", seed=42)
    w3 = adapter.synthesize("测试文本。第二句。", voice="mock_male", format="wav", seed=43)
    assert w1 == w2, "相同 seed 结果应可复现"
    assert w1 != w3, "不同 seed 结果应有差异"
    # ffprobe 可读
    import subprocess
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(w1)
        p = f.name
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,sample_rate,channels",
         "-of", "json", p],
        capture_output=True, text=True,
    )
    assert r.returncode == 0
    import json

    info = json.loads(r.stdout)
    assert info["streams"][0]["codec_name"] == "pcm_s16le"
    assert info["streams"][0]["sample_rate"] == "48000"


def test_mock_mp3_export():
    from app.adapters.tts import MockTTSAdapter

    adapter = MockTTSAdapter()
    mp3 = adapter.synthesize("测试音频。", format="mp3")
    assert mp3[:3] == b"ID3" or mp3[:2] in (b"\xff\xfb", b"\xff\xf3")


def test_mock_capability_error():
    from app.adapters.tts import CapabilityError, MockTTSAdapter

    adapter = MockTTSAdapter()
    with pytest.raises(CapabilityError):
        adapter.synthesize("测试", pitch=1.2)


def test_mock_capabilities_shape():
    from app.adapters.factory import get_tts_adapter

    caps = get_tts_adapter().capabilities()
    for key in ["synthesize", "speed_control", "voice_preview", "mp3", "wav"]:
        assert caps[key] is True
    for key in ["ssml", "pitch_control", "volume_control", "emotion", "voice_cloning", "word_timestamps"]:
        assert caps[key] is False


# ============================================================
# 时长估算
# ============================================================

def test_estimate_duration():
    from app.services.audio_utils import estimate_duration_seconds

    d1 = estimate_duration_seconds("本项目总建筑面积十二万平方米。", speed=1.0)
    d2 = estimate_duration_seconds("本项目总建筑面积十二万平方米。", speed=1.2)
    assert d1 > 0
    assert d2 < d1, "语速越快预计越短"
    assert estimate_duration_seconds("") == 0.0


# ============================================================
# 单条生成
# ============================================================

def test_generate_single_creates_version(client, project_id, auth_headers):
    shot = _make_shot(client, project_id, auth_headers,
                      narration="本项目总建筑面积十二万平方米，工期三百六十五日历天。采用BIM技术。")
    _generate_and_wait(client, project_id, auth_headers, shot["id"], seed=1)

    versions = client.get(
        f"/api/v1/projects/{project_id}/storyboard/{shot['id']}/voice/versions",
        headers=auth_headers,
    ).json()
    assert len(versions) == 1
    v = versions[0]
    assert v["version_number"] == 1
    assert v["is_selected"] is True, "首个版本应自动设为正式"
    assert v["is_mock"] is True
    assert v["quality_status"] == "passed"
    assert v["actual_duration_seconds"] > 0
    assert len(v["subtitle_data"]) > 0
    assert v["waveform_data"]["count"] > 0
    assert v["wav_asset_id"] and v["mp3_asset_id"]
    assert v["original_text_snapshot"] == shot["narration"]
    assert "十二万平方米" in v["normalized_text_snapshot"]


def test_duration_status_classification(client, project_id, auth_headers):
    # 目标 20s，实际约 5-12s → script_adjustment_required
    shot = _make_shot(client, project_id, auth_headers, narration="简短的解说词。", duration=30)
    _generate_and_wait(client, project_id, auth_headers, shot["id"], seed=2)
    versions = client.get(
        f"/api/v1/projects/{project_id}/storyboard/{shot['id']}/voice/versions",
        headers=auth_headers,
    ).json()
    assert versions[0]["duration_status"] == "script_adjustment_required"


def test_version_numbering_increment(client, project_id, auth_headers):
    shot = _make_shot(client, project_id, auth_headers)
    _generate_and_wait(client, project_id, auth_headers, shot["id"], seed=10)
    _generate_and_wait(client, project_id, auth_headers, shot["id"], seed=11)
    versions = client.get(
        f"/api/v1/projects/{project_id}/storyboard/{shot['id']}/voice/versions",
        headers=auth_headers,
    ).json()
    nums = sorted(v["version_number"] for v in versions)
    assert nums == [1, 2], "版本应从 V1 起递增，不覆盖"
    assert versions[0]["is_selected"] is True, "V1 保持正式"
    assert versions[1]["is_selected"] is False


def test_select_version_and_delete_blocked(client, project_id, auth_headers):
    shot = _make_shot(client, project_id, auth_headers)
    _generate_and_wait(client, project_id, auth_headers, shot["id"], seed=20)
    _generate_and_wait(client, project_id, auth_headers, shot["id"], seed=21)
    versions = client.get(
        f"/api/v1/projects/{project_id}/storyboard/{shot['id']}/voice/versions",
        headers=auth_headers,
    ).json()
    v1, v2 = versions[0], versions[1]

    # 选择 V2 为正式
    resp = client.post(
        f"/api/v1/projects/{project_id}/storyboard/{shot['id']}/voice/versions/{v2['id']}/select",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    versions = client.get(
        f"/api/v1/projects/{project_id}/storyboard/{shot['id']}/voice/versions",
        headers=auth_headers,
    ).json()
    assert versions[1]["is_selected"] is True

    # 被引用的正式版本不可删除
    resp = client.delete(
        f"/api/v1/projects/{project_id}/storyboard/{shot['id']}/voice/versions/{v2['id']}",
        headers=auth_headers,
    )
    assert resp.status_code == 409

    # 未引用版本可软删除
    resp = client.delete(
        f"/api/v1/projects/{project_id}/storyboard/{shot['id']}/voice/versions/{v1['id']}",
        headers=auth_headers,
    )
    assert resp.status_code == 204
    versions = client.get(
        f"/api/v1/projects/{project_id}/storyboard/{shot['id']}/voice/versions",
        headers=auth_headers,
    ).json()
    assert [v["version_number"] for v in versions] == [2]

    # 软删除 V1 后再次生成必须继续使用新版本号，不能复用已占用的 V2/V1。
    _generate_and_wait(client, project_id, auth_headers, shot["id"], seed=22)
    versions = client.get(
        f"/api/v1/projects/{project_id}/storyboard/{shot['id']}/voice/versions",
        headers=auth_headers,
    ).json()
    assert sorted(v["version_number"] for v in versions) == [2, 3]


def test_restore_voice_version(client, project_id, auth_headers):
    shot = _make_shot(client, project_id, auth_headers)
    _generate_and_wait(client, project_id, auth_headers, shot["id"], seed=30)
    _generate_and_wait(client, project_id, auth_headers, shot["id"], seed=31)
    versions = client.get(
        f"/api/v1/projects/{project_id}/storyboard/{shot['id']}/voice/versions",
        headers=auth_headers,
    ).json()
    v2 = versions[1]
    client.post(
        f"/api/v1/projects/{project_id}/storyboard/{shot['id']}/voice/versions/{v2['id']}/select",
        headers=auth_headers,
    )
    # 恢复 V1
    resp = client.post(
        f"/api/v1/projects/{project_id}/storyboard/{shot['id']}/voice/restore",
        json={"version_id": versions[0]["id"]},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    versions = client.get(
        f"/api/v1/projects/{project_id}/storyboard/{shot['id']}/voice/versions",
        headers=auth_headers,
    ).json()
    assert versions[0]["is_selected"] is True


# ============================================================
# 解说词变化追踪
# ============================================================

def test_narration_change_marks_stale(client, project_id, auth_headers):
    shot = _make_shot(client, project_id, auth_headers, narration="原始解说词内容。")
    _generate_and_wait(client, project_id, auth_headers, shot["id"], seed=40)
    # 修改解说词
    resp = client.patch(
        f"/api/v1/projects/{project_id}/storyboard/{shot['id']}",
        json={"narration": "修改后的解说词内容。"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["narration_hash"]
    versions = client.get(
        f"/api/v1/projects/{project_id}/storyboard/{shot['id']}/voice/versions",
        headers=auth_headers,
    ).json()
    assert versions[0]["is_stale"] is True
    assert "解说词已修改" in (versions[0]["stale_reason"] or "")


def test_restore_narration_detects_reusable(client, project_id, auth_headers):
    shot = _make_shot(client, project_id, auth_headers, narration="可恢复的解说词。")
    _generate_and_wait(client, project_id, auth_headers, shot["id"], seed=50)
    versions_before = client.get(
        f"/api/v1/projects/{project_id}/storyboard/{shot['id']}/voice/versions",
        headers=auth_headers,
    ).json()
    orig_hash = versions_before[0]["narration_hash"]
    # 修改
    client.patch(
        f"/api/v1/projects/{project_id}/storyboard/{shot['id']}",
        json={"narration": "改动后的文本。"},
        headers=auth_headers,
    )
    # 恢复原解说词
    resp = client.patch(
        f"/api/v1/projects/{project_id}/storyboard/{shot['id']}",
        json={"narration": "可恢复的解说词。"},
        headers=auth_headers,
    )
    assert resp.json()["narration_hash"] == orig_hash, "恢复原文本后哈希应一致"


# ============================================================
# 字幕
# ============================================================

def test_subtitle_srt_export(client, project_id, auth_headers):
    shot = _make_shot(client, project_id, auth_headers,
                      narration="第一句解说词。第二句解说词，带标点。")
    _generate_and_wait(client, project_id, auth_headers, shot["id"], seed=60)
    resp = client.get(f"/api/v1/projects/{project_id}/voice/export/srt", headers=auth_headers)
    assert resp.status_code == 200
    text = resp.content.decode("utf-8")
    assert "00:00:0" in text
    assert "-->" in text
    assert "第一句解说词。" in text


def test_subtitle_edit(client, project_id, auth_headers):
    shot = _make_shot(client, project_id, auth_headers, narration="第一句。第二句。")
    _generate_and_wait(client, project_id, auth_headers, shot["id"], seed=61)
    subs = client.get(f"/api/v1/projects/{project_id}/storyboard/{shot['id']}/subtitles", headers=auth_headers).json()
    assert len(subs["subtitle_data"]) >= 2
    seg = subs["subtitle_data"][0]
    # 修改首句结束时间为一个不与其他句重叠的值
    resp = client.patch(
        f"/api/v1/projects/{project_id}/storyboard/{shot['id']}/subtitles",
        json={"segments": [{"sequence": seg["sequence"], "start_ms": 0, "end_ms": 500}]},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["subtitle_data"][0]["end_ms"] == 500
    assert resp.json()["subtitle_data"][0]["timing_source"] == "manual"


def test_subtitle_overlap_rejected(client, project_id, auth_headers):
    shot = _make_shot(client, project_id, auth_headers, narration="第一句。第二句。第三句。")
    _generate_and_wait(client, project_id, auth_headers, shot["id"], seed=62)
    subs = client.get(f"/api/v1/projects/{project_id}/storyboard/{shot['id']}/subtitles", headers=auth_headers).json()
    segs = subs["subtitle_data"]
    resp = client.patch(
        f"/api/v1/projects/{project_id}/storyboard/{shot['id']}/subtitles",
        json={
            "segments": [
                {"sequence": segs[0]["sequence"], "start_ms": 0, "end_ms": 3000},
                {"sequence": segs[1]["sequence"], "start_ms": 2500, "end_ms": 5000},
            ]
        },
        headers=auth_headers,
    )
    assert resp.status_code == 409, "重叠字幕应被拒绝"


# ============================================================
# 发音词典
# ============================================================

def test_pronunciation_crud_and_test(client, project_id, auth_headers):
    # 创建
    resp = client.post(
        f"/api/v1/projects/{project_id}/pronunciations",
        json={"source_text": "XX建设集团", "spoken_text": "某某建设集团", "rule_type": "company"},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    rule_id = resp.json()["id"]

    # 测试朗读
    resp = client.post(
        f"/api/v1/projects/{project_id}/pronunciations/test",
        json={"text": "由XX建设集团承建。"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert "某某建设集团" in resp.json()["normalized_text"]

    # 更新
    resp = client.patch(
        f"/api/v1/projects/{project_id}/pronunciations/{rule_id}",
        json={"priority": 200},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["priority"] == 200

    # 列表 / 删除
    resp = client.get(f"/api/v1/projects/{project_id}/pronunciations", headers=auth_headers)
    assert len(resp.json()) >= 1
    resp = client.delete(f"/api/v1/projects/{project_id}/pronunciations/{rule_id}", headers=auth_headers)
    assert resp.status_code == 204


def test_pronunciation_import_export(client, project_id, auth_headers):
    data = {
        "rules": [
            {"source_text": "BIM", "spoken_text": "BIM", "rule_type": "abbreviation"},
            {"source_text": "C40", "spoken_text": "C四零", "rule_type": "literal"},
        ]
    }
    resp = client.post(
        f"/api/v1/projects/{project_id}/pronunciations/import",
        json=data,
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["created"] == 2
    resp = client.get(f"/api/v1/projects/{project_id}/pronunciations/export", headers=auth_headers)
    assert resp.status_code == 200
    assert len(resp.json()["rules"]) >= 2


def test_dangerous_regex_rejected(client, project_id, auth_headers):
    resp = client.post(
        f"/api/v1/projects/{project_id}/pronunciations",
        json={
            "source_text": "(a+)+$",
            "spoken_text": "x",
            "rule_type": "literal",
            "is_regex": True,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 409, "危险正则应被拒绝"


# ============================================================
# 批量生成
# ============================================================

def test_batch_generation(client, project_id, auth_headers):
    s1 = _make_shot(client, project_id, auth_headers, sequence=1, narration="第一个分镜解说词。")
    s2 = _make_shot(client, project_id, auth_headers, sequence=2, narration="第二个分镜解说词。")
    resp = client.post(
        f"/api/v1/projects/{project_id}/voice/batch",
        json={"shot_ids": [s1["id"], s2["id"]], "idempotency_key": "batch-key-1"},
        headers=auth_headers,
    )
    assert resp.status_code == 202, resp.text
    parent_id = resp.json()["task_id"]
    detail = client.get(f"/api/v1/projects/{project_id}/voice/jobs/{parent_id}", headers=auth_headers).json()
    assert detail["status"] == "success"
    assert detail["result"]["total"] == 2
    assert detail["result"]["success"] == 2
    assert len(detail["children"]) == 2

    # 幂等：同一 key 再次提交返回同一任务
    resp2 = client.post(
        f"/api/v1/projects/{project_id}/voice/batch",
        json={"shot_ids": [s1["id"], s2["id"]], "idempotency_key": "batch-key-1"},
        headers=auth_headers,
    )
    assert resp2.json()["task_id"] == parent_id


def test_batch_skip_existing(client, project_id, auth_headers):
    s1 = _make_shot(client, project_id, auth_headers, sequence=1, narration="已有配音的分镜。")
    # 先生成
    _generate_and_wait(client, project_id, auth_headers, s1["id"], seed=70)
    # 再批量（regenerate_stale=False，已通过审核不重生成）
    resp = client.post(
        f"/api/v1/projects/{project_id}/voice/batch",
        json={"shot_ids": [s1["id"]], "regenerate_stale": False},
        headers=auth_headers,
    )
    assert resp.status_code == 409, "没有需要生成的分镜时应 409"


# ============================================================
# 授权
# ============================================================

def test_authorization_blocks_export():
    from app.models.voice_template import VoiceTemplate
    from app.services.voice_service import VoiceError, ensure_template_authorized

    for status in ("unknown", "pending", "rejected", "expired"):
        tpl = VoiceTemplate(authorization_status=status, authorization_type="custom_authorized")
        with pytest.raises(VoiceError):
            ensure_template_authorized(tpl, for_export=True)
    # 正常授权可通过
    ok = VoiceTemplate(authorization_status="approved", authorization_type="enterprise_licensed")
    ensure_template_authorized(ok, for_export=True)
    # mock_only 演示可用，正式导出被拒
    mock = VoiceTemplate(authorization_status="mock_only", authorization_type="mock")
    ensure_template_authorized(mock, for_export=False)
    with pytest.raises(VoiceError):
        ensure_template_authorized(mock, for_export=True)


# ============================================================
# 跨项目隔离 / 汇总
# ============================================================

def test_cross_project_voice_isolation(client, project_id, auth_headers):
    shot = _make_shot(client, project_id, auth_headers)
    _generate_and_wait(client, project_id, auth_headers, shot["id"], seed=80)

    # 另一个项目
    other = client.post("/api/v1/projects", json={"name": "其它项目"}, headers=auth_headers).json()
    other_id = other["id"]
    other_shot = client.post(
        f"/api/v1/projects/{other_id}/storyboard",
        json={"project_id": other_id, "sequence": 1, "title": "其它", "narration": "n"},
        headers=auth_headers,
    ).json()

    # 尝试读取本项目分镜配音版本（用其它项目 URL）→ 404
    versions = client.get(
        f"/api/v1/projects/{other_id}/storyboard/{shot['id']}/voice/versions",
        headers=auth_headers,
    )
    assert versions.status_code == 404

    # 跨项目选择版本 → 拒绝（404 或 409 均可，重点是不得跨项目绑定）
    v = client.get(
        f"/api/v1/projects/{project_id}/storyboard/{shot['id']}/voice/versions",
        headers=auth_headers,
    ).json()[0]
    resp = client.post(
        f"/api/v1/projects/{other_id}/storyboard/{other_shot['id']}/voice/versions/{v['id']}/select",
        headers=auth_headers,
    )
    assert resp.status_code in (404, 409)


def test_voice_summary(client, project_id, auth_headers):
    shot = _make_shot(client, project_id, auth_headers, narration="汇总测试解说词。")
    _generate_and_wait(client, project_id, auth_headers, shot["id"], seed=90)
    resp = client.get(f"/api/v1/projects/{project_id}/voice/summary", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["shot_count"] == 1
    assert data["missing_voice_count"] == 0
    assert data["mock_count"] == 1


def test_template_provider_endpoints(client, project_id, auth_headers):
    resp = client.get(f"/api/v1/projects/{project_id}/voice/providers", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()[0]["is_mock"] is True

    resp = client.get(f"/api/v1/projects/{project_id}/voice/providers/mock/capabilities", headers=auth_headers)
    assert resp.json()["synthesize"] is True

    resp = client.get("/api/v1/voice/speaking-styles", headers=auth_headers)
    assert "正式稳重" in resp.json()

    resp = client.get("/api/v1/voice/templates", headers=auth_headers)
    assert len(resp.json()) >= 1
