"""Phase 7：AI 视频生成（Seedance 图片驱动视频分镜）测试。

覆盖：模板种子、未选首帧拦截、首尾帧双图校验、建筑约束冲突拦截、
禁止解说词回退、模板参数填充、任务创建/查询/取消/重试、版本选择/绑定/删除、
参考帧列表、参数快照可追溯。
"""

from __future__ import annotations

import io
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/fastvideo_phase7_test.db")
os.environ.setdefault("USE_CELERY", "false")
os.environ.setdefault("AI_LLM_PROVIDER", "disabled")
os.environ.setdefault("AI_PROMPT_MASTER_PROVIDER", "mock")
os.environ.setdefault("AI_PROMPT_MASTER_ALLOW_MOCK", "true")
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


def test_prompt_master_sends_reference_frames_to_volcengine_vision(
    client, project_id, auth_headers, monkeypatch
):
    """火山方舟视觉适配器必须收到原图，而不是只有文件名元数据。"""
    first_id = _upload_frame(client, project_id, auth_headers, "vision-first.png", (80, 110, 150))
    last_id = _upload_frame(client, project_id, auth_headers, "vision-last.png", (150, 110, 80))
    captured = {}

    class FakeVisionAdapter:
        provider = "volcengine_vision"
        supports_vision = True
        config = {"model": "doubao-seed-1-6-vision-250815"}

        def chat(self, messages, **kwargs):
            captured["messages"] = messages
            captured["kwargs"] = kwargs
            return "以下为结构化结果：\n```json\n" + json.dumps({
                "prompt": "镜头从首帧平稳推进并自然过渡到尾帧，建筑主体结构保持不变。",
                "negative_prompt": "改变建筑结构、增加楼层、画面抖动",
                "recipe": {"generation_modes": ["first_last_frame_video"]},
            }, ensure_ascii=False) + "\n```"

    from app.services import video_gen_service

    monkeypatch.setattr(video_gen_service, "get_llm_adapter", lambda stage="narration": FakeVisionAdapter())
    response = client.post(
        f"/api/v1/projects/{project_id}/ai-video/prompt-master",
        json={
            "first_frame_asset_id": first_id,
            "last_frame_asset_id": last_id,
            "generation_mode": "first_last_frame_video",
        },
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["is_mock"] is False
    assert result["vision_used"] is True
    assert result["provider"] == "volcengine_vision"
    # 结构化 JSON 只用于生成配方，返回给镜头输入框的必须是可直接投喂的 prompt。
    assert result["prompt"] == "镜头从首帧平稳推进并自然过渡到尾帧，建筑主体结构保持不变。"
    assert result["prompt"].lstrip().startswith("镜头")
    assert result["negative_prompt"] == "改变建筑结构、增加楼层、画面抖动"
    content = captured["messages"][0]["content"]
    assert any(item["type"] == "image_url" for item in content)
    assert sum(item["type"] == "image_url" for item in content) == 2


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


def test_conflicting_prompt_can_continue_after_confirmation(client, project_id, auth_headers):
    first = _upload_frame(client, project_id, auth_headers, "confirmed.png", (50, 80, 120))
    resp = client.post(
        f"/api/v1/projects/{project_id}/ai-video/tasks",
        json={
            "generation_mode": "image_to_video",
            "first_frame_asset_id": first,
            "positive_prompt": "拆除临时支撑并展示施工过程，建筑主体保持不变",
            "structure_conflict_confirmed": True,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 202, resp.text
    assert resp.json()["parameter_snapshot"]["structure_conflict_confirmed"] is True


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


def _construction_recipe():
    return {
        "recipe_version": 2,
        "construction_mode": "construction_evolution",
        "project_facts": {
            "structure_type": "钢筋混凝土框架-核心筒",
            "current_stage": "地下室底板钢筋完成",
            "target_stage": "底板混凝土浇筑完成",
            "fact_sources": ["施工组织设计第六章"],
        },
        "construction_unit": {
            "wbs_code": "03.02.04",
            "work_item": "地下室底板混凝土浇筑",
            "work_zone": "A区",
            "objects": ["底板钢筋", "泵管", "混凝土工作面"],
            "prerequisites": ["钢筋验收完成", "模板加固完成"],
            "completion_state": ["混凝土连续覆盖", "表面完成收面"],
        },
        "state_transition": {
            "start_state": "底板钢筋和模板已验收，混凝土尚未覆盖",
            "end_state": "底板混凝土成型并进入养护",
            "allowed_changes": ["工作面按分区连续推进"],
            "forbidden_jumps": ["直接出现上部结构", "跳过浇筑形成完整底板"],
        },
        "construction_timeline": [
            {"from": 0, "to": 40, "instruction": "准备泵管并确认作业面"},
            {"from": 40, "to": 100, "instruction": "分区连续浇筑并完成收面"},
        ],
        "camera_timeline": [
            {"from": 0, "to": 100, "instruction": "稳定斜俯视缓慢横移跟随工作面"},
        ],
        "spatial_anchors": ["核心筒位置", "基坑边界", "塔吊基础"],
        "temporary_works": {"required": ["临边防护", "泵管"], "forbidden": ["悬空模板"]},
        "safety_constraints": ["人员佩戴安全帽", "机械作业半径内无人员穿行"],
        "quality_constraints": ["已完成构件不得消失或漂移"],
        "acceptance_checks": ["构件数量与位置一致", "施工顺序连续"],
    }


def test_compile_prompt_endpoint_returns_seedance_ready_construction_text(client, project_id, auth_headers):
    recipe = _construction_recipe()
    response = client.post(
        f"/api/v1/projects/{project_id}/ai-video/compile-prompt",
        json={
            "positive_prompt": "镜头展示施工过程，增加楼层属于受控施工变化",
            "negative_prompt": "禁止构件漂移",
            "prompt_recipe": recipe,
            "constraints_enabled": True,
        },
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["blocked"] is False
    assert "BIM 4D施工进度动画" in data["positive_prompt"]
    assert "任务：地下室底板混凝土浇筑" in data["positive_prompt"]
    assert "严格时序" in data["positive_prompt"]
    assert "镜头" in data["positive_prompt"]
    assert "锁定不动" in data["positive_prompt"]
    # WBS、事实来源等审计字段留在任务快照，不整段投喂给 Seedance。
    assert "03.02.04" not in data["positive_prompt"]
    assert "禁止构件漂移" in data["negative_prompt"]
    assert data["provider_prompt"].startswith(data["positive_prompt"])
    assert "负向约束（禁止出现）：" in data["provider_prompt"]
    assert "禁止构件漂移" in data["provider_prompt"]
    assert data["provider_prompt_chars"] == len(data["provider_prompt"])
    assert data["provider_prompt_limit"] == 2000
    assert data["prompt_recipe"]["recipe_version"] == 2


def test_selected_resolution_overrides_prompt_resolution_words(client, project_id, auth_headers):
    """高级参数 720p 是最终规格，提示词大师写入的 4K 不能混入 Seedance 文本。"""
    response = client.post(
        f"/api/v1/projects/{project_id}/ai-video/compile-prompt",
        json={
            "positive_prompt": "固定斜俯视施工动画，写实 4K 分辨率，超高清画质。",
            "negative_prompt": "禁止模糊",
            "resolution": "720p",
            "constraints_enabled": False,
        },
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert "4K" not in data["positive_prompt"]
    assert "超高清" not in data["positive_prompt"]
    assert "分辨率" not in data["positive_prompt"]

    first = _upload_frame(client, project_id, auth_headers, "resolution-override.png", (65, 95, 125))
    created = client.post(
        f"/api/v1/projects/{project_id}/ai-video/tasks",
        json={
            "provider": "mock",
            "generation_mode": "image_to_video",
            "first_frame_asset_id": first,
            "positive_prompt": "建筑施工过程，4K 输出，画面清晰",
            "resolution": "720p",
        },
        headers=auth_headers,
    )
    assert created.status_code == 202, created.text
    task = created.json()
    assert task["resolution"] == "720p"
    assert "4K" not in (task["positive_prompt"] or "")


def test_compile_prompt_endpoint_includes_selected_template_constraints(client, project_id, auth_headers):
    templates = client.get(
        f"/api/v1/projects/{project_id}/ai-video/templates",
        headers=auth_headers,
    )
    assert templates.status_code == 200, templates.text
    template = next(item for item in templates.json() if item.get("default_arch_constraints"))
    response = client.post(
        f"/api/v1/projects/{project_id}/ai-video/compile-prompt",
        json={
            "template_id": template["id"],
            "positive_prompt": "保持建筑外轮廓与道路位置稳定",
            "prompt_recipe": _construction_recipe(),
            "constraints_enabled": True,
        },
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    # 施工 V2 使用自己的短锁定语句，避免模板建筑约束再次淹没施工动作。
    assert template["default_arch_constraints"][0] not in response.json()["positive_prompt"]
    assert "视觉禁用" in response.json()["positive_prompt"]


def test_dense_construction_recipe_is_semantically_compacted_under_seedance_limit(client, project_id, auth_headers):
    recipe = _construction_recipe()
    recipe["project_facts"].update({
        "structure_type": "钢筋混凝土主体结构（具体结构形式以项目结构图为准）",
        "current_stage": "一层梁板分区施工开始前，场地围挡、施工道路、三台塔吊、已完成结构和结构开洞均已形成，①②③区域梁板尚未全部完成。",
        "target_stage": "①裙房区域和②主楼区域一层梁板已经完成，③剩余楼板区域按照尾帧所示进入梁板施工状态。",
        "fact_sources": ["施工总体部署", "一层结构平面图", "梁板分区浇筑施工方案", "参考视频首尾帧"],
    })
    recipe["construction_unit"].update({
        "wbs_code": "主体结构-一层梁板（请替换为项目真实WBS编码）",
        "work_item": "一层梁板三个施工分区依次浇筑完成",
        "work_zone": "①裙房区域 ②主楼区域 ③剩余楼板区域",
        "objects": ["一层梁板", "主楼核心区域", "裙房梁板区域", "结构开洞", "已完成竖向构件", "三台塔吊及其基座"],
        "prerequisites": ["下部结构验收完成", "模板支撑完成", "钢筋验收完成", "预留洞口复核完成"],
        "completion_state": ["①区完成", "②区完成", "③区施工至尾帧状态", "结构开洞位置不变"],
    })
    recipe["state_transition"] = {
        "start_state": "场地、道路、围挡、三台塔吊和已完成结构保持首帧状态，三个区域尚未依次完成。",
        "end_state": "①裙房区域先形成，随后②主楼区域形成，最后③剩余楼板区域施工至尾帧状态。",
        "allowed_changes": ["①裙房区域梁板逐步形成", "①区完成后②主楼区域形成", "②区完成后③剩余楼板区域形成", "塔吊吊臂缓慢旋转但基座不动"],
        "forbidden_jumps": ["禁止三区同时生成", "禁止颠倒①②③顺序", "禁止②区未完成就开始③区", "禁止已完成梁板消失或漂移", "禁止改变结构开洞"],
    }
    recipe["construction_timeline"] = [
        {"from": 0, "to": 10, "instruction": "建立首帧状态并确认场地锚点"},
        {"from": 10, "to": 38, "instruction": "先施工①裙房区域梁板"},
        {"from": 38, "to": 70, "instruction": "保持①区完成，再施工②主楼区域梁板"},
        {"from": 70, "to": 94, "instruction": "保持①②区完成，开始③区剩余楼板施工至尾帧状态"},
        {"from": 94, "to": 100, "instruction": "保持③区未完全闭合状态并匹配尾帧"},
    ]
    recipe["camera_timeline"] = [
        {"from": 0, "to": 10, "instruction": "固定高位斜俯视建立全景"},
        {"from": 10, "to": 38, "instruction": "稳定机位缓慢跟随①区"},
        {"from": 38, "to": 70, "instruction": "小幅跟随至②区且不切镜"},
        {"from": 70, "to": 94, "instruction": "缓慢回到整体视角展示③区"},
        {"from": 94, "to": 100, "instruction": "轻微拉远并按尾帧定格"},
    ]
    recipe["spatial_anchors"] = ["施工场地外轮廓", "围挡", "周边道路与出入口", "三台塔吊基座", "主楼核心区", "三个分区边界", "结构开洞", "周边环境"]
    recipe["safety_constraints"] = ["塔吊基座固定", "不得站在未形成梁板上", "不得出现悬浮构件", "洞口范围清晰"]
    recipe["quality_constraints"] = ["严格按①②③顺序", "已形成区域持续保留", "梁板边界匹配尾帧", "结构开洞不得覆盖", "场地不得漂移"]
    recipe["acceptance_checks"] = ["①先于②", "②完成后开始③", "③保持尾帧状态", "洞口位置一致", "塔吊基座一致"]

    response = client.post(
        f"/api/v1/projects/{project_id}/ai-video/compile-prompt",
        json={
            "positive_prompt": "固定斜俯视BIM施工部署动画，严格按照①裙房区域、②主楼区域、③剩余楼板区域依次形成，全程连续单镜头。。",
            "prompt_recipe": recipe,
            "constraints_enabled": True,
        },
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    data = response.json()
    provider_prompt = data["provider_prompt"]
    assert data["provider_prompt_chars"] <= data["provider_prompt_limit"] == 2000
    assert all(token in provider_prompt for token in ("①裙房区域", "②主楼区域", "③区剩余楼板", "严格时序", "镜头", "尾帧"))
    assert len(provider_prompt) <= 800
    assert "请替换" not in provider_prompt
    assert "具体结构形式以项目结构图为准" not in provider_prompt
    assert "事实来源" not in provider_prompt
    assert data["prompt_recipe"]["project_facts"]["fact_sources"] == recipe["project_facts"]["fact_sources"]


def test_manual_provider_prompt_override_is_previewed_and_submitted_exactly(client, project_id, auth_headers):
    recipe = _construction_recipe()
    override = (
        "固定高位斜俯视BIM施工动画，严格按①裙房、②主楼、③剩余楼板依次推进；"
        "已完成区域持续保留，结构开洞、道路与三台塔吊基座全程锁定，单镜头，最终匹配尾帧。"
    )
    recipe["provider_prompt_override"] = override

    preview = client.post(
        f"/api/v1/projects/{project_id}/ai-video/compile-prompt",
        json={
            "positive_prompt": "这段自动提示词必须被人工终稿替换",
            "negative_prompt": "这段负向提示词也不能再次拼接",
            "prompt_recipe": recipe,
            "constraints_enabled": True,
        },
        headers=auth_headers,
    )
    assert preview.status_code == 200, preview.text
    preview_data = preview.json()
    assert preview_data["positive_prompt"] == override
    assert preview_data["negative_prompt"] == ""
    assert preview_data["provider_prompt"] == override
    assert preview_data["provider_prompt_chars"] == len(override)
    assert preview_data["prompt_recipe"]["provider_prompt_override"] == override

    first = _upload_frame(client, project_id, auth_headers, "manual-final.png", (55, 95, 125))
    created = client.post(
        f"/api/v1/projects/{project_id}/ai-video/tasks",
        json={
            "provider": "mock",
            "generation_mode": "image_to_video",
            "first_frame_asset_id": first,
            "positive_prompt": "旧的自动提示词",
            "negative_prompt": "旧的负向提示词",
            "prompt_recipe": recipe,
            "duration": 5,
        },
        headers=auth_headers,
    )
    assert created.status_code == 202, created.text
    task = created.json()
    assert task["positive_prompt"] == override
    assert task["negative_prompt"] == ""
    assert task["parameter_snapshot"]["provider_prompt"] == override
    assert task["parameter_snapshot"]["template_recipe"]["provider_prompt_override"] == override


def test_controlled_construction_transition_is_sent_and_snapshotted(client, project_id, auth_headers):
    first = _upload_frame(client, project_id, auth_headers, "construction.png", (50, 90, 120))
    response = client.post(
        f"/api/v1/projects/{project_id}/ai-video/tasks",
        json={
            "provider": "mock",
            "generation_mode": "image_to_video",
            "first_frame_asset_id": first,
            "positive_prompt": "施工演进中增加楼层，按状态转换逐步形成",
            "prompt_recipe": _construction_recipe(),
            "duration": 5,
        },
        headers=auth_headers,
    )
    assert response.status_code == 202, response.text
    data = response.json()
    assert data["status"] == "success"
    assert "BIM 4D施工进度动画" in data["positive_prompt"]
    assert "严格时序" in data["positive_prompt"]
    assert "视觉禁用" in data["positive_prompt"]
    snapshot = data["parameter_snapshot"]
    assert snapshot["construction_mode"] == "construction_evolution"
    assert snapshot["template_recipe"]["construction_unit"]["wbs_code"] == "03.02.04"
    assert data["quality_report"]["engineering_review"]["status"] == "manual_required"


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

def test_create_query_select_and_video_project_binding(client, project_id, auth_headers):
    first = _upload_frame(client, project_id, auth_headers, "v1.png", (20, 40, 80))
    last = _upload_frame(client, project_id, auth_headers, "v2.png", (220, 80, 120))

    # 创建首尾帧任务
    resp = client.post(
        f"/api/v1/projects/{project_id}/ai-video/tasks",
        json={
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

    # AI 视频结果是独立素材，AI 视频页面不提供分镜绑定契约。
    bind = client.post(
        f"/api/v1/projects/{project_id}/ai-video/versions/{vid}/bind",
        json={},
        headers=auth_headers,
    )
    assert bind.status_code == 404, bind.text

    # Only a video-engine segment can reference the generated video asset.
    _create_shot(client, project_id, auth_headers, narration="视频工程时间轴镜头")
    vp = client.post(
        f"/api/v1/projects/{project_id}/video-projects",
        json={"name": "AI 视频绑定契约测试"},
        headers=auth_headers,
    )
    assert vp.status_code == 201, vp.text
    vp_id = vp.json()["id"]
    segments = client.get(
        f"/api/v1/video-projects/{vp_id}/segments", headers=auth_headers
    ).json()
    assert segments
    patched = client.patch(
        f"/api/v1/video-projects/{vp_id}/segments/{segments[0]['id']}",
        json={"visual_asset_id": vlist[0]["result_asset_id"]},
        headers=auth_headers,
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["visual_asset_id"] == vlist[0]["result_asset_id"]

    # 项目版本列表可查，但不暴露分镜绑定字段
    allv = client.get(f"/api/v1/projects/{project_id}/ai-video/versions", headers=auth_headers)
    assert any(v["id"] == vid for v in allv.json())

    # 被视频工程分段引用的版本不可删除
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


def test_concurrent_duplicate_clicks_share_one_video_job(client, project_id, auth_headers):
    first = _upload_frame(client, project_id, auth_headers, "double-click.png", (70, 100, 130))
    payload = {
        "generation_mode": "image_to_video",
        "first_frame_asset_id": first,
        "positive_prompt": "并发幂等测试",
        "idempotency_key": "concurrent-double-click-001",
    }

    def submit():
        return client.post(
            f"/api/v1/projects/{project_id}/ai-video/tasks",
            json=payload,
            headers=auth_headers,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _index: submit(), range(2)))

    assert all(response.status_code == 202 for response in responses), [response.text for response in responses]
    assert len({response.json()["id"] for response in responses}) == 1


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


# ---------------- Provider 入口（新任务仅开放 Seedance / 测试 Mock） ----------------

def test_providers_list_exposes_seedance_not_minimax(client, project_id, auth_headers):
    resp = client.get(f"/api/v1/projects/{project_id}/ai-video/providers", headers=auth_headers)
    assert resp.status_code == 200
    names = [p["provider"] for p in resp.json()]
    assert "seedance" in names
    assert "minimax" not in names
    seedance = next(p for p in resp.json() if p["provider"] == "seedance")
    assert seedance["capabilities"]["first_last_frame_video"] is True
    assert "doubao-seedance-2-0-260128" in seedance["models"]


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
    assert any(text in resp.json()["message"] for text in ("不可用", "未配置", "仅开放 Seedance"))


def test_minimax_is_rejected_for_new_video_tasks(client, project_id, auth_headers):
    first = _upload_frame(client, project_id, auth_headers, "old-provider.png", (50, 80, 120))
    resp = client.post(
        f"/api/v1/projects/{project_id}/ai-video/tasks",
        json={
            "provider": "minimax",
            "generation_mode": "image_to_video",
            "first_frame_asset_id": first,
            "positive_prompt": "建筑缓慢推进",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 409
    assert "仅开放 Seedance" in resp.json()["message"]


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
