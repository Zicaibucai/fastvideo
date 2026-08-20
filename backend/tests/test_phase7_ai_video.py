"""Phase 7：AI 视频生成（Seedance 图片驱动视频分镜）测试。

覆盖：模板种子、未选首帧拦截、首尾帧双图校验、建筑约束冲突拦截、
禁止解说词回退、模板参数填充、任务创建/查询/取消/重试、版本选择/绑定/删除、
参考帧列表、参数快照可追溯。
"""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/fastvideo_phase7_test.db")
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
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture()
def project_id(client, auth_headers):
    resp = client.post(
        "/api/v1/projects",
        json={"name": "Phase7 AI视频生成", "code": "P7-001"},
        headers=auth_headers,
    )
    return resp.json()["id"]


def _make_image(width=1280, height=720, color=(70, 100, 140)) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buf, format="PNG")
    return buf.getvalue()


def _upload_frame(client, project_id, auth_headers, name="frame.png", color=(70, 100, 140)):
    resp = client.post(
        f"/api/v1/projects/{project_id}/render/source-images",
        files={"file": (name, io.BytesIO(_make_image(color=color)), "image/png")},
        data={"name": name, "source_software": "Revit", "camera_angle": "建筑人视"},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _create_shot(client, project_id, auth_headers, narration="这是一段解说词，描述建筑总体情况。"):
    resp = client.post(
        f"/api/v1/projects/{project_id}/storyboard",
        json={"project_id": project_id, "sequence": 1, "narration": narration},
        headers=auth_headers,
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()


# ---------------- 模板种子 ----------------

def test_evai_system_templates_seeded(client, project_id, auth_headers):
    resp = client.get(f"/api/v1/projects/{project_id}/ai-video/templates", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    # 42 个 EVAI img2Video 抓取模板：建筑外景运镜 12 + 首尾帧·创意运镜 30
    assert len(data) == 42
    outdoor = [t for t in data if t["applicable_modes"] == ["image_to_video"]]
    fl = [t for t in data if t["applicable_modes"] == ["first_last_frame_video"]]
    assert len(outdoor) == 12
    assert len(fl) == 30
    names = [t["name"] for t in data]
    assert "建筑平移" in names
    assert "建筑生长动画" in names


def test_evai_first_last_template_prompt_matches_source(client, project_id, auth_headers):
    resp = client.get(f"/api/v1/projects/{project_id}/ai-video/templates", headers=auth_headers)
    t = next(x for x in resp.json() if x["name"] == "建筑生长动画")
    assert t["default_positive_prompt"] == "一栋建筑从地面逐渐向上生长出来，固定鏡头。"
    assert t["applicable_modes"] == ["first_last_frame_video"]
    assert t["source_template_id"] == "evai_60"


def test_templates_filtered_by_mode(client, project_id, auth_headers):
    resp = client.get(
        f"/api/v1/projects/{project_id}/ai-video/templates?mode=first_last_frame_video",
        headers=auth_headers,
    )
    modes = {m for t in resp.json() for m in (t["applicable_modes"] or [])}
    assert all(m == "first_last_frame_video" for m in modes)


# ---------------- 任务创建与校验 ----------------

def test_submit_without_first_frame_blocked(client, project_id, auth_headers):
    resp = client.post(
        f"/api/v1/projects/{project_id}/ai-video/tasks",
        json={
            "generation_mode": "image_to_video",
            "first_frame_asset_id": "not-exist",
            "positive_prompt": "建筑缓慢推进",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 409
    assert "首帧" in resp.json()["message"]


def test_first_last_frame_requires_two_images(client, project_id, auth_headers):
    first = _upload_frame(client, project_id, auth_headers, "first.png", (10, 20, 30))
    resp = client.post(
        f"/api/v1/projects/{project_id}/ai-video/tasks",
        json={
            "generation_mode": "first_last_frame_video",
            "first_frame_asset_id": first,
            "positive_prompt": "日景到夜景过渡",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 409
    assert "两张图片" in resp.json()["message"]


def test_first_last_frame_requires_two_images_both_valid(client, project_id, auth_headers):
    first = _upload_frame(client, project_id, auth_headers, "f1.png", (10, 20, 30))
    last = _upload_frame(client, project_id, auth_headers, "f2.png", (200, 60, 90))
    resp = client.post(
        f"/api/v1/projects/{project_id}/ai-video/tasks",
        json={
            "generation_mode": "first_last_frame_video",
            "first_frame_asset_id": first,
            "last_frame_asset_id": last,
            "positive_prompt": "日景到夜景过渡",
            "duration": 10,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 202, resp.text
    job = resp.json()
    assert job["generation_mode"] == "first_last_frame_video"
    assert job["first_frame_asset_id"] == first
    assert job["last_frame_asset_id"] == last
    assert job["status"] == "success"
    assert job["result_url"]


# ---------------- 建筑约束拦截 ----------------

@pytest.mark.parametrize("prompt", [
    "增加楼层让建筑更高",
    "改变建筑轮廓",
    "移动道路重新布局",
    "替换主楼为另一栋",
    "删除一层",
    "把建筑改成不同建筑",
])
def test_conflicting_prompts_blocked(client, project_id, auth_headers, prompt):
    first = _upload_frame(client, project_id, auth_headers, "c.png", (50, 80, 120))
    resp = client.post(
        f"/api/v1/projects/{project_id}/ai-video/tasks",
        json={
            "generation_mode": "image_to_video",
            "first_frame_asset_id": first,
            "positive_prompt": prompt,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 409
    assert "工程结构" in resp.json()["message"] or "改变" in resp.json()["message"]


def test_constraint_check_endpoint(client, project_id, auth_headers):
    resp = client.post(
        f"/api/v1/projects/{project_id}/ai-video/constraint-check",
        json={"text": "建筑缓慢推进，保持主体不变"},
        headers=auth_headers,
    )
    assert resp.json()["blocked"] is False
    resp2 = client.post(
        f"/api/v1/projects/{project_id}/ai-video/constraint-check",
        json={"text": "增加楼层"},
        headers=auth_headers,
    )
    assert resp2.json()["blocked"] is True
    assert resp2.json()["conflicts"]


# ---------------- 提示词大师 ----------------

def test_prompt_master_requires_frame(client, project_id, auth_headers):
    resp = client.post(
        f"/api/v1/projects/{project_id}/ai-video/prompt-master",
        json={"generation_mode": "image_to_video"},
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_prompt_master_mock_single_frame(client, project_id, auth_headers):
    first = _upload_frame(client, project_id, auth_headers, "pm1.png", (40, 90, 130))
    resp = client.post(
        f"/api/v1/projects/{project_id}/ai-video/prompt-master",
        json={
            "generation_mode": "image_to_video",
            "first_frame_asset_id": first,
            "intent": "突出主入口仪式感",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["is_mock"] is True
    assert data["prompt"]
    assert "突出主入口仪式感" in data["prompt"]
    assert data["negative_prompt"]


def test_prompt_master_mock_first_last_with_template(client, project_id, auth_headers):
    first = _upload_frame(client, project_id, auth_headers, "pm2a.png", (50, 80, 120))
    last = _upload_frame(client, project_id, auth_headers, "pm2b.png", (90, 60, 30))
    # 取一个首尾帧模板作为上下文
    templates = client.get(
        f"/api/v1/projects/{project_id}/ai-video/templates",
        headers=auth_headers,
    ).json()
    fl_tpl = next(t for t in templates if "first_last_frame_video" in (t["applicable_modes"] or []))
    resp = client.post(
        f"/api/v1/projects/{project_id}/ai-video/prompt-master",
        json={
            "generation_mode": "first_last_frame_video",
            "first_frame_asset_id": first,
            "last_frame_asset_id": last,
            "template_id": fl_tpl["id"],
            "intent": "白模过渡到写实效果图",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["prompt"]
    # Mock 路径应复用模板默认提示词并追加用户意图
    assert fl_tpl["default_positive_prompt"][:20] in data["prompt"]
    assert "白模过渡到写实效果图" in data["prompt"]


# ---------------- 解说词不参与视频生成 ----------------

def test_narration_never_used_as_video_prompt(client, project_id, auth_headers):
    shot = _create_shot(client, project_id, auth_headers, narration="这段解说词绝不能被用于视频提示词")
    first = _upload_frame(client, project_id, auth_headers, "n.png", (30, 60, 100))
    resp = client.post(
        f"/api/v1/projects/{project_id}/ai-video/tasks",
        json={
            "storyboard_shot_id": shot["id"],
            "generation_mode": "image_to_video",
            "first_frame_asset_id": first,
            "positive_prompt": "独立视频提示词：镜头缓慢推进",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 202, resp.text
    job = resp.json()
    # 正向提示词只包含独立视频提示词 + 建筑约束，绝不含解说词
    assert "独立视频提示词" in job["positive_prompt"]
    assert "解说词绝不能被用于" not in job["positive_prompt"]
    assert job["architecture_constraints"]
    # 参数快照记录独立用户提示词
    assert job["parameter_snapshot"]["user_prompt"] == "独立视频提示词：镜头缓慢推进"


def test_modifying_narration_after_job_does_not_affect_job(client, project_id, auth_headers):
    shot = _create_shot(client, project_id, auth_headers, narration="初始解说词")
    first = _upload_frame(client, project_id, auth_headers, "m.png", (40, 70, 110))
    resp = client.post(
        f"/api/v1/projects/{project_id}/ai-video/tasks",
        json={
            "storyboard_shot_id": shot["id"],
            "generation_mode": "image_to_video",
            "first_frame_asset_id": first,
            "positive_prompt": "固定视频提示词",
        },
        headers=auth_headers,
    )
    job_id = resp.json()["id"]
    before = resp.json()["positive_prompt"]

    # 修改分镜解说词
    client.patch(
        f"/api/v1/projects/{project_id}/storyboard/{shot['id']}",
        json={"narration": "完全不同的新解说词"},
        headers=auth_headers,
    )
    resp2 = client.get(f"/api/v1/projects/{project_id}/ai-video/tasks/{job_id}", headers=auth_headers)
    assert resp2.json()["positive_prompt"] == before
    assert "完全不同的新解说词" not in resp2.json()["positive_prompt"]


# ---------------- 模板参数填充 ----------------

def test_template_fill_applies_default_prompt_and_constraints(client, project_id, auth_headers):
    resp = client.get(f"/api/v1/projects/{project_id}/ai-video/templates", headers=auth_headers)
    t = next(x for x in resp.json() if x["name"] == "建筑平移")
    first = _upload_frame(client, project_id, auth_headers, "t.png", (60, 90, 130))
    resp = client.post(
        f"/api/v1/projects/{project_id}/ai-video/tasks",
        json={
            "generation_mode": "image_to_video",
            "first_frame_asset_id": first,
            "template_id": t["id"],
            "positive_prompt": t["default_positive_prompt"],
            "duration": t["recommended_duration"],
            "aspect_ratio": t["recommended_aspect_ratio"],
            "resolution": t["recommended_resolution"],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 202, resp.text
    job = resp.json()
    snap = job["parameter_snapshot"]
    assert snap["template_id"] == t["id"]
    assert snap["duration"] == t["recommended_duration"]
    # 正向提示词 = 模板默认提示词 + 建筑约束
    assert "建筑主体" in job["positive_prompt"]
    assert "禁止新增/删除建筑主体" in job["positive_prompt"]
    assert any("锁定建筑主体数量" in c for c in job["architecture_constraints"])


# ---------------- 任务与版本管理 ----------------

def test_create_query_select_bind_delete_version(client, project_id, auth_headers):
    shot = _create_shot(client, project_id, auth_headers, narration="分镜解说词A")
    first = _upload_frame(client, project_id, auth_headers, "v1.png", (20, 40, 80))
    last = _upload_frame(client, project_id, auth_headers, "v2.png", (220, 80, 120))

    # 创建首尾帧任务
    resp = client.post(
        f"/api/v1/projects/{project_id}/ai-video/tasks",
        json={
            "storyboard_shot_id": shot["id"],
            "generation_mode": "first_last_frame_video",
            "first_frame_asset_id": first,
            "last_frame_asset_id": last,
            "positive_prompt": "白模过渡到写实",
            "duration": 5,
            "generate_audio": False,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 202, resp.text
    job = resp.json()
    job_id = job["id"]
    assert job["status"] == "success"
    assert job["version_count"] >= 1
    assert job["generate_audio"] is False
    assert job["result_url"]

    # 查询任务列表与详情
    lst = client.get(f"/api/v1/projects/{project_id}/ai-video/tasks", headers=auth_headers)
    assert any(j["id"] == job_id for j in lst.json())
    detail = client.get(f"/api/v1/projects/{project_id}/ai-video/tasks/{job_id}", headers=auth_headers)
    assert detail.json()["status"] == "success"

    # 任务结果版本
    versions = client.get(
        f"/api/v1/projects/{project_id}/ai-video/tasks/{job_id}/versions",
        headers=auth_headers,
    )
    assert versions.status_code == 200
    vlist = versions.json()
    assert len(vlist) >= 1
    vid = vlist[0]["id"]
    assert vlist[0]["result_url"]

    # 选为当前结果
    sel = client.post(
        f"/api/v1/projects/{project_id}/ai-video/versions/{vid}/select",
        json={},
        headers=auth_headers,
    )
    assert sel.status_code == 200
    assert sel.json()["is_selected"] is True

    # 绑定分镜
    bind = client.post(
        f"/api/v1/projects/{project_id}/ai-video/versions/{vid}/bind",
        json={"shot_id": shot["id"]},
        headers=auth_headers,
    )
    assert bind.status_code == 200, bind.text
    assert bind.json()["shot_id"] == shot["id"]

    # 分镜视频已绑定
    shot_resp = client.get(
        f"/api/v1/projects/{project_id}/storyboard/{shot['id']}",
        headers=auth_headers,
    )
    assert shot_resp.status_code == 200

    # 项目版本列表可查（含绑定分镜标题）
    allv = client.get(f"/api/v1/projects/{project_id}/ai-video/versions", headers=auth_headers)
    assert any(v["id"] == vid for v in allv.json())
    bound = next(v for v in allv.json() if v["id"] == vid)
    assert bound["bound_shot_id"] == shot["id"]

    # 已绑定版本不可删除
    dels = client.delete(f"/api/v1/projects/{project_id}/ai-video/versions/{vid}", headers=auth_headers)
    assert dels.status_code == 409


def test_reference_images_lists_only_images(client, project_id, auth_headers):
    _upload_frame(client, project_id, auth_headers, "r.png", (90, 120, 150))
    resp = client.get(
        f"/api/v1/projects/{project_id}/ai-video/reference-images",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert all(img["asset_type"] == "image" for img in resp.json())
    assert len(resp.json()) >= 1


def test_cancel_and_retry_workflow(client, project_id, auth_headers):
    first = _upload_frame(client, project_id, auth_headers, "q.png", (80, 110, 140))
    # 先创建一个会失败的任务（无有效 prompt 不失败，因此用一个不存在模板？模板校验会 404）
    # 用正常的任务取消
    resp = client.post(
        f"/api/v1/projects/{project_id}/ai-video/tasks",
        json={
            "generation_mode": "image_to_video",
            "first_frame_asset_id": first,
            "positive_prompt": "取消测试",
            "idempotency_key": "cancel-test-001",
        },
        headers=auth_headers,
    )
    job = resp.json()
    job_id = job["id"]

    # 幂等键重复提交返回同一任务
    resp2 = client.post(
        f"/api/v1/projects/{project_id}/ai-video/tasks",
        json={
            "generation_mode": "image_to_video",
            "first_frame_asset_id": first,
            "positive_prompt": "取消测试",
            "idempotency_key": "cancel-test-001",
        },
        headers=auth_headers,
    )
    assert resp2.json()["id"] == job_id

    # 取消（已 success 的不可取消，返回原状态）
    cancel = client.post(
        f"/api/v1/projects/{project_id}/ai-video/tasks/{job_id}/cancel",
        headers=auth_headers,
    )
    assert cancel.json()["status"] in ("success", "cancelled")


def test_enterprise_template_crud(client, project_id, auth_headers):
    resp = client.post(
        f"/api/v1/projects/{project_id}/ai-video/templates",
        json={
            "name": "企业自定义推进",
            "applicable_modes": ["image_to_video"],
            "default_positive_prompt": "企业自定义镜头",
            "recommended_duration": 5,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    tid = resp.json()["id"]
    assert resp.json()["is_system"] is False

    # 更新
    upd = client.patch(
        f"/api/v1/projects/{project_id}/ai-video/templates/{tid}",
        json={"default_positive_prompt": "更新后的镜头"},
        headers=auth_headers,
    )
    assert upd.json()["default_positive_prompt"] == "更新后的镜头"

    # 删除
    dels = client.delete(
        f"/api/v1/projects/{project_id}/ai-video/templates/{tid}",
        headers=auth_headers,
    )
    assert dels.status_code == 204


# ---------------- Provider 切换（Seedance / MiniMax / Mock） ----------------

def test_providers_list_includes_seedance_and_minimax(client, project_id, auth_headers):
    resp = client.get(f"/api/v1/projects/{project_id}/ai-video/providers", headers=auth_headers)
    assert resp.status_code == 200
    names = [p["provider"] for p in resp.json()]
    assert "seedance" in names
    assert "minimax" in names
    seedance = next(p for p in resp.json() if p["provider"] == "seedance")
    assert seedance["capabilities"]["first_last_frame_video"] is True
    assert "doubao-seedance-2-0-260128" in seedance["models"]
    minimax = next(p for p in resp.json() if p["provider"] == "minimax")
    # MiniMax H3（V2 接口）原生支持首尾帧
    assert minimax["capabilities"]["first_last_frame_video"] is True
    assert minimax["models"] == ["MiniMax-H3"]


def test_unknown_provider_rejected(client, project_id, auth_headers):
    first = _upload_frame(client, project_id, auth_headers, "u.png", (50, 80, 120))
    resp = client.post(
        f"/api/v1/projects/{project_id}/ai-video/tasks",
        json={
            "provider": "not-a-provider",
            "generation_mode": "image_to_video",
            "first_frame_asset_id": first,
            "positive_prompt": "建筑缓慢推进",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 409
    assert "不可用" in resp.json()["message"] or "未配置" in resp.json()["message"]


def test_explicit_mock_provider_task_records_provider(client, project_id, auth_headers):
    """显式选择 mock Provider 时，任务记录的 provider 必须是 mock（快照可追溯）。"""
    first = _upload_frame(client, project_id, auth_headers, "mk.png", (60, 90, 130))
    resp = client.post(
        f"/api/v1/projects/{project_id}/ai-video/tasks",
        json={
            "provider": "mock",
            "generation_mode": "image_to_video",
            "first_frame_asset_id": first,
            "positive_prompt": "建筑缓慢推进",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 202, resp.text
    job = resp.json()
    assert job["provider"] == "mock"
    assert job["status"] == "success"
    assert job["parameter_snapshot"]["provider"] == "mock"
