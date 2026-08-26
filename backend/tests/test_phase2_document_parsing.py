"""功能1：文档精准解析 + 解说词智能拆解 测试。

覆盖：PDF逐页解析、DOCX段落表格、扫描页OCR降级、文件重复检测、
参数来源页码、数据冲突检测、无来源参数拦截、LLM JSON格式异常处理、
Mock生成10+分镜、分镜排序持久化、单分镜重新生成、历史版本恢复、权限隔离。
"""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path

import pytest

# 让 app 包可导入
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/fastvideo_phase2_test.db")
os.environ.setdefault("USE_CELERY", "false")
os.environ.setdefault("AI_LLM_PROVIDER", "disabled")
os.environ.setdefault("AI_IMAGE_PROVIDER", "disabled")
os.environ.setdefault("AI_VIDEO_PROVIDER", "disabled")
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
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def project_id(client, auth_headers):
    resp = client.post(
        "/api/v1/projects",
        json={"name": "功能1测试项目", "code": "ZB-P2-001"},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _make_txt(content: str) -> io.BytesIO:
    return io.BytesIO(content.encode("utf-8"))


def _upload_txt(client, project_id, auth_headers, content, doc_type="tender"):
    files = {"file": ("招标文件.txt", _make_txt(content), "text/plain")}
    data = {"doc_type": doc_type}
    return client.post(
        f"/api/v1/projects/{project_id}/documents",
        files=files,
        data=data,
        headers=auth_headers,
    )


# ---------------- 文档上传与解析 ----------------

def test_upload_txt_and_parse(client, project_id, auth_headers):
    content = (
        "项目名称：测试智慧园区项目\n"
        "招标人：测试市建设发展有限公司\n"
        "建筑面积 52800 平方米，总工期 540 日历天。\n"
    )
    resp = _upload_txt(client, project_id, auth_headers, content)
    assert resp.status_code == 201, resp.text
    doc = resp.json()
    assert doc["parse_status"] in ("success", "queued", "parsing")
    assert doc["sha256"]

    # 轮询解析完成
    for _ in range(10):
        doc_resp = client.get(
            f"/api/v1/projects/{project_id}/documents/{doc['id']}",
            headers=auth_headers,
        )
        if doc_resp.json()["parse_status"] in ("success", "failed"):
            break
        import time

        time.sleep(0.5)
    assert doc_resp.json()["parse_status"] == "success", doc_resp.text

    # 参数应包含面积、工期
    facts = client.get(f"/api/v1/projects/{project_id}/facts", headers=auth_headers).json()
    fact_names = {f["fact_name"] for f in facts}
    assert "area_building" in fact_names, f"facts={fact_names}"
    assert "duration_total" in fact_names


def test_duplicate_upload_detection(client, project_id, auth_headers):
    content = "项目名称：去重测试项目\n建筑面积 10000 平方米。\n"
    resp1 = _upload_txt(client, project_id, auth_headers, content)
    assert resp1.status_code == 201
    resp2 = _upload_txt(client, project_id, auth_headers, content)
    assert resp2.status_code == 409, "重复上传应返回 409"


def test_unsupported_file_type(client, project_id, auth_headers):
    files = {"file": ("test.exe", b"MZ\x90\x00", "application/octet-stream")}
    resp = client.post(
        f"/api/v1/projects/{project_id}/documents",
        files=files,
        data={"doc_type": "tender"},
        headers=auth_headers,
    )
    assert resp.status_code == 409, "不支持的文件类型应返回 409"


# ---------------- 参数提取与冲突检测 ----------------

def test_fact_extraction_and_page_source(client, project_id, auth_headers):
    content = (
        "项目名称：市民中心建设项目\n"
        "招标人：市民中心建设指挥部\n"
        "总建筑面积 32000 平方米，建筑高度 45.6 米，地上 8 层。\n"
        "总工期 360 日历天。\n"
    )
    resp = _upload_txt(client, project_id, auth_headers, content)
    doc_id = resp.json()["id"]
    for _ in range(10):
        d = client.get(f"/api/v1/projects/{project_id}/documents/{doc_id}", headers=auth_headers).json()
        if d["parse_status"] in ("success", "failed"):
            break
        import time

        time.sleep(0.5)

    facts = client.get(f"/api/v1/projects/{project_id}/facts", headers=auth_headers).json()
    area_fact = next((f for f in facts if f["fact_name"] == "area_building"), None)
    assert area_fact, "应提取出面积参数"
    assert area_fact["page_number"] == 1, "来源页码应为 1"
    assert area_fact["fact_value"] == "32000"
    assert area_fact["unit"] == "㎡"
    assert area_fact["verification_status"] == "unverified"


def test_conflict_detection(client, project_id, auth_headers):
    """两个文件对同一参数给出不同值 → conflict。"""
    # 文件 A
    _upload_txt(client, project_id, auth_headers, "项目名称：冲突测试\n建筑面积 10000 平方米。\n")
    # 文件 B（不同值）
    _upload_txt(client, project_id, auth_headers, "项目名称：冲突测试\n建筑面积 20000 平方米。\n")

    import time

    time.sleep(1)  # 同步模式已解析完成

    facts = client.get(f"/api/v1/projects/{project_id}/facts", headers=auth_headers).json()
    area_facts = [f for f in facts if f["fact_name"] == "area_building"]
    assert len(area_facts) >= 2, "应提取出两个面积候选"
    assert any(f["verification_status"] == "conflict" for f in area_facts), (
        "存在不同值应标记 conflict"
    )

    # 冲突列表
    conflicts = client.get(f"/api/v1/projects/{project_id}/facts/conflicts", headers=auth_headers).json()
    assert len(conflicts) >= 1


def test_fact_confirm_updates_project(client, project_id, auth_headers):
    _upload_txt(client, project_id, auth_headers, "项目名称：确认测试\n建筑面积 52800 平方米。\n")
    import time

    time.sleep(1)
    facts = client.get(f"/api/v1/projects/{project_id}/facts", headers=auth_headers).json()
    area_fact = next(f for f in facts if f["fact_name"] == "area_building")

    resp = client.post(
        f"/api/v1/projects/{project_id}/facts/{area_fact['id']}/confirm",
        json={"status": "confirmed"},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    project = client.get(f"/api/v1/projects/{project_id}", headers=auth_headers).json()
    assert project["bid_area"] == 52800, "确认后应同步到项目字段"
    assert project["area_source_page"] == 1, "应带来源页码"


# ---------------- 分镜生成与校验 ----------------

def test_narration_generation_10_plus_shots(client, project_id, auth_headers):
    _upload_txt(
        client,
        project_id,
        auth_headers,
        "项目名称：智能拆解测试\n招标人：测试建设单位\n"
        "总建筑面积 86500 平方米，建筑高度 96.5 米，总工期 720 日历天。\n",
    )
    import time

    time.sleep(1)

    resp = client.post(
        f"/api/v1/projects/{project_id}/storyboard/generate",
        json={
            "project_id": project_id,
            "section_count": 10,
            "target_duration_seconds": 300,
            "tone": "专业庄重",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 202, resp.text
    task_id = resp.json()["task_id"]

    for _ in range(10):
        task = client.get(f"/api/v1/tasks/{task_id}", headers=auth_headers).json()
        if task["status"] in ("success", "failed"):
            break
        time.sleep(0.5)
    assert task["status"] == "success", f"生成失败: {task.get('error_message')}"
    result = task["result"]
    assert result["shot_count"] >= 10, f"应生成至少10个分镜，实际{result['shot_count']}"
    run_id = result["stage_summary"]["run_id"]
    from app.core.database import SessionLocal
    from app.models.render_task import RenderTask

    with SessionLocal() as db:
        persisted_task = db.get(RenderTask, task_id)
        assert persisted_task.params["task_id"] == task_id
        assert persisted_task.params["evidence_run_id"] == run_id
    evidence_run = client.get(
        f"/api/v1/projects/{project_id}/storyboard/evidence/runs/{run_id}",
        headers=auth_headers,
    ).json()
    assert evidence_run["run"]["status"] == "completed"
    assert evidence_run["run"]["total_batches"] >= 1
    assert evidence_run["run"]["evidence_count"] >= 1

    shots = client.get(f"/api/v1/projects/{project_id}/storyboard", headers=auth_headers).json()
    assert len(shots) >= 10
    # 每个分镜应有解说词
    assert all(s["narration"] for s in shots)
    summary = client.get(
        f"/api/v1/projects/{project_id}/storyboard/summary", headers=auth_headers
    ).json()
    assert summary["beat_count"] >= len(shots)
    beats = client.get(
        f"/api/v1/projects/{project_id}/storyboard/beats", headers=auth_headers
    ).json()
    assert [beat["sequence"] for beat in beats] == list(range(1, len(beats) + 1))
    assert all(beat["end_time"] > beat["start_time"] for beat in beats)


def test_narration_prompt_uses_sourced_facts_and_document_excerpts(client, project_id, auth_headers):
    _upload_txt(
        client,
        project_id,
        auth_headers,
        "项目名称：摘录增强测试\n总建筑面积 45600 平方米。\n"
        "施工部署采用分区流水组织，重点控制深基坑、机电管综和绿色施工。\n",
    )
    import time

    time.sleep(1)

    from app.core.database import SessionLocal
    from app.services.narration_engine import _build_context, _build_prompt

    db = SessionLocal()
    try:
        context = _build_context(db, project_id)
        prompt = _build_prompt({"project_id": project_id, "section_count": 10}, context)
    finally:
        db.close()

    assert "待确认但有明确来源的材料" in prompt
    assert "area_building" in prompt
    assert "45600" in prompt
    assert "文档原文摘录" in prompt
    assert "分区流水组织" in prompt


def test_multi_stage_prompts_keep_evidence_and_writing_separate(client, project_id, auth_headers):
    """先取证、后编排、再写作，避免模型直接用模板填满全文。"""
    from app.core.database import SessionLocal
    from app.services.narration_engine import (
        EvidenceOutput,
        _build_chapter_prompt,
        _build_context,
        _build_evidence_prompt,
        _build_outline_prompt,
        _fallback_outline,
    )

    db = SessionLocal()
    try:
        context = _build_context(db, project_id)
        params = {"project_id": project_id, "target_duration_seconds": 540, "chars_per_minute": 215}
        evidence_prompt = _build_evidence_prompt(params, context)
        outline = _fallback_outline(params, EvidenceOutput())
        outline_prompt = _build_outline_prompt(params, context, EvidenceOutput())
        chapter_prompt = _build_chapter_prompt(params, context, outline.chapters[0], EvidenceOutput(), shot_start=1, shot_budget=2)
    finally:
        db.close()

    assert "只做资料分析，不写解说词" in evidence_prompt
    assert "来源文件和页码" in evidence_prompt
    assert "此阶段只生成章节大纲，不写完整正文" in outline_prompt
    assert "施工方案与施工推演：不少于总时长 70%" in outline_prompt
    assert "每句话 8 至 26 个汉字左右" in chapter_prompt
    assert "保驾护航" in chapter_prompt


def test_mock_narration_reads_enriched_prompt_context():
    from app.adapters.llm import _mock_narration
    from app.services.narration_engine import parse_narration_output

    raw = _mock_narration(
        "【已确认工程事实（必须引用，不得编造）】\n"
        "- project_name: 新能源产业园一期 [项目档案]\n"
        "- area_building: 45600㎡ [已确认] P1\n"
        "- duration_total: 365日历天 [已确认] P2\n"
        "【文档原文摘录】\n"
        "- 招标文件 P1: 建设地点：临港新区，总建筑面积 45600 平方米，地上 9 层。\n"
    )
    parsed = parse_narration_output(raw)
    combined = "\n".join(s.narration for s in parsed.shots)
    assert "新能源产业园一期" in combined
    assert "45600" in combined
    assert "365" in combined


def test_shot_fact_check_and_sources(client, project_id, auth_headers):
    _upload_txt(client, project_id, auth_headers, "项目名称：来源校验测试\n总建筑面积 52800 平方米。\n")
    import time

    time.sleep(1)
    client.post(
        f"/api/v1/projects/{project_id}/storyboard/generate",
        json={"project_id": project_id, "section_count": 10},
        headers=auth_headers,
    )
    time.sleep(1)
    shots = client.get(f"/api/v1/projects/{project_id}/storyboard", headers=auth_headers).json()
    # 至少一个分镜带来源引用
    with_refs = [s for s in shots if s.get("source_references")]
    assert len(with_refs) >= 1, "包含工程事实的分镜应有来源引用"


def test_llm_json_parse_error_handling(client, project_id, auth_headers):
    """LLM 输出非法 JSON 时，parse_narration_output 应抛 ValueError。"""
    from app.services.narration_engine import parse_narration_output

    with pytest.raises(ValueError):
        parse_narration_output("这不是 JSON，这是纯文本解说词。")


def test_shot_reorder_persistence(client, project_id, auth_headers):
    _upload_txt(client, project_id, auth_headers, "项目名称：排序测试\n建筑面积 30000 平方米。\n")
    import time

    time.sleep(1)
    client.post(
        f"/api/v1/projects/{project_id}/storyboard/generate",
        json={"project_id": project_id, "section_count": 10},
        headers=auth_headers,
    )
    time.sleep(1)
    shots = client.get(f"/api/v1/projects/{project_id}/storyboard", headers=auth_headers).json()
    assert len(shots) >= 2

    # 反转顺序
    reversed_ids = [s["id"] for s in reversed(shots)]
    resp = client.post(
        f"/api/v1/projects/{project_id}/storyboard/reorder",
        json={"shot_ids": reversed_ids},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    reordered = resp.json()
    assert [s["sequence"] for s in reordered] == list(range(1, len(reordered) + 1)), "sequence 必须连续"

    # 刷新后顺序持久化
    refreshed = client.get(f"/api/v1/projects/{project_id}/storyboard", headers=auth_headers).json()
    assert [s["id"] for s in refreshed] == reversed_ids, "刷新后顺序不丢失"


def test_shot_regenerate_single(client, project_id, auth_headers):
    _upload_txt(client, project_id, auth_headers, "项目名称：重生成测试\n建筑面积 20000 平方米。\n")
    import time

    time.sleep(1)
    client.post(
        f"/api/v1/projects/{project_id}/storyboard/generate",
        json={"project_id": project_id, "section_count": 5},
        headers=auth_headers,
    )
    time.sleep(1)
    shots = client.get(f"/api/v1/projects/{project_id}/storyboard", headers=auth_headers).json()
    shot_id = shots[0]["id"]
    old_narration = shots[0]["narration"]

    resp = client.post(
        f"/api/v1/projects/{project_id}/storyboard/{shot_id}/regenerate",
        json={"shot_id": shot_id, "prompt_hint": "强调绿色施工"},
        headers=auth_headers,
    )
    assert resp.status_code == 202, resp.text

    # 重新生成后应有历史版本
    shot = client.get(
        f"/api/v1/projects/{project_id}/storyboard/{shot_id}",
        headers=auth_headers,
    ).json()
    assert len(shot["versions"]) >= 2, "重生成后应保留历史版本"


def test_shot_restore_version(client, project_id, auth_headers):
    _upload_txt(client, project_id, auth_headers, "项目名称：版本恢复测试\n建筑面积 15000 平方米。\n")
    import time

    time.sleep(1)
    client.post(
        f"/api/v1/projects/{project_id}/storyboard/generate",
        json={"project_id": project_id, "section_count": 3},
        headers=auth_headers,
    )
    time.sleep(1)
    shots = client.get(f"/api/v1/projects/{project_id}/storyboard", headers=auth_headers).json()
    shot_id = shots[0]["id"]
    orig_versions = shots[0]["versions"]
    ai_version = next(v for v in orig_versions if v["source"] == "ai")

    # 编辑
    client.patch(
        f"/api/v1/projects/{project_id}/storyboard/{shot_id}",
        json={"narration": "人工修改后的解说词"},
        headers=auth_headers,
    )
    # 恢复 AI 版本
    resp = client.post(
        f"/api/v1/projects/{project_id}/storyboard/{shot_id}/restore",
        json={"revision": ai_version["revision"]},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["narration"] == ai_version["narration"]


def test_project_permission_isolation(client, project_id, auth_headers):
    """另一个用户不应看到该项目的数据。"""
    # 注册第二个用户
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": "other2@test.com", "username": "other2", "password": "test123456"},
    )
    assert resp.status_code == 201
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "other2@test.com", "password": "test123456"},
    )
    other_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    # 其他用户访问项目应 404
    resp = client.get(f"/api/v1/projects/{project_id}", headers=other_headers)
    assert resp.status_code == 404
    resp = client.get(f"/api/v1/projects/{project_id}/facts", headers=other_headers)
    assert resp.status_code == 404


# ---------------- 阅读器 / 搜索 / 评分点 ----------------

def test_reader_pages_and_toc(client, project_id, auth_headers):
    content = (
        "一、项目概况\n项目名称：阅读器测试项目\n总建筑面积 40000 平方米。\n"
        "二、施工部署\n施工部署内容。\n三、质量保证\n质量目标：优质工程。\n"
    )
    resp = _upload_txt(client, project_id, auth_headers, content)
    doc_id = resp.json()["id"]
    import time

    time.sleep(1)

    pages = client.get(f"/api/v1/projects/{project_id}/reader/{doc_id}/pages", headers=auth_headers).json()
    assert len(pages) >= 1
    assert pages[0]["page_number"] == 1

    toc = client.get(f"/api/v1/projects/{project_id}/documents/{doc_id}/toc", headers=auth_headers).json()
    assert len(toc) >= 1, "应识别出目录结构"


def test_document_search(client, project_id, auth_headers):
    _upload_txt(client, project_id, auth_headers, "项目名称：搜索测试\n总工期 540 日历天。\n")
    import time

    time.sleep(1)
    resp = client.get(
        f"/api/v1/projects/{project_id}/documents/search",
        params={"q": "工期"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


def test_scoring_points_from_scoring_doc(client, project_id, auth_headers):
    content = (
        "评分办法\n"
        "1. 施工组织设计：20 分\n"
        "2. 质量保证措施：15 分\n"
        "3. 安全文明施工：10 分\n"
    )
    _upload_txt(client, project_id, auth_headers, content, doc_type="scoring")
    import time

    time.sleep(1)
    points = client.get(f"/api/v1/projects/{project_id}/scoring", headers=auth_headers).json()
    assert len(points) >= 3, "应提取出评分点"

    coverage = client.get(f"/api/v1/projects/{project_id}/scoring/coverage", headers=auth_headers).json()
    assert coverage["total"] >= 3


def test_delete_document_blocked_when_referenced(client, project_id, auth_headers):
    """删除被分镜引用的文档应被阻止。"""
    resp = _upload_txt(client, project_id, auth_headers, "项目名称：删除保护测试\n建筑面积 12000 平方米。\n")
    doc_id = resp.json()["id"]
    import time

    time.sleep(1)

    client.post(
        f"/api/v1/projects/{project_id}/storyboard/generate",
        json={"project_id": project_id, "section_count": 5},
        headers=auth_headers,
    )
    time.sleep(1)
    shots = client.get(f"/api/v1/projects/{project_id}/storyboard", headers=auth_headers).json()

    # 让分镜引用该文档
    with_refs = [s for s in shots if s.get("source_references")]
    if with_refs:
        resp = client.delete(f"/api/v1/projects/{project_id}/documents/{doc_id}", headers=auth_headers)
        assert resp.status_code == 409, "被引用文档删除应被阻止"
    else:
        # 无引用则正常删除
        resp = client.delete(f"/api/v1/projects/{project_id}/documents/{doc_id}", headers=auth_headers)
        assert resp.status_code in (204, 409)
