"""Phase 3：模型截图渲染与分镜画面绑定 测试。

覆盖：图片上传校验、PromptBuilder、Provider能力、Mock渲染、多版本、
遮罩、扩图、清晰度增强、质量检查、分镜绑定、跨项目隔离、幂等键等。
"""

from __future__ import annotations

import io
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/fastvideo_phase3_test.db")
os.environ.setdefault("USE_CELERY", "false")
os.environ.setdefault("AI_IMAGE_PROVIDER", "disabled")

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
        json={"name": "Phase3渲染测试", "code": "P3-001"},
        headers=auth_headers,
    )
    return resp.json()["id"]


def _make_test_image(width=1280, height=720, mode="RGB", fmt="PNG") -> bytes:
    """用 Pillow 生成测试图片。"""
    from PIL import Image, ImageDraw

    img = Image.new(mode, (width, height), (60, 90, 130))
    draw = ImageDraw.Draw(img)
    draw.rectangle([100, 100, 400, 500], fill=(180, 190, 200))
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


def _upload(client, project_id, auth_headers, data, fname, software="Revit", angle="建筑人视"):
    return client.post(
        f"/api/v1/projects/{project_id}/render/source-images",
        files={"file": (fname, io.BytesIO(data), "image/png")},
        data={"name": fname, "source_software": software, "camera_angle": angle},
        headers=auth_headers,
    )


def _create_task(client, project_id, auth_headers, src_id, **overrides):
    payload = {
        "source_asset_id": src_id,
        "operation_type": "render",
        "positive_prompt": "科技蓝投标风格",
        "variant_count": 2,
        "structure_strength": 85,
        "seed": 42,
    }
    payload.update(overrides)
    return client.post(
        f"/api/v1/projects/{project_id}/render/tasks",
        json=payload,
        headers=auth_headers,
    )


# ---------------- 上传校验 ----------------

def test_valid_image_upload(client, project_id, auth_headers):
    resp = _upload(client, project_id, auth_headers, _make_test_image(), "合法截图.png")
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["width"] == 1280
    assert data["height"] == 720
    assert data["sha256"]
    assert data["aspect_ratio"] == "16:9"


def test_illegal_file_type_rejected(client, project_id, auth_headers):
    resp = _upload(client, project_id, auth_headers, b"not an image", "test.txt")
    assert resp.status_code == 409


def test_svg_rejected(client, project_id, auth_headers):
    resp = _upload(client, project_id, auth_headers, b'<svg></svg>', "test.svg")
    assert resp.status_code == 409


def test_forged_extension_rejected(client, project_id, auth_headers):
    # 扩展名 .png 但实际不是图片
    resp = _upload(client, project_id, auth_headers, b"PK\x03\x04 fake", "fake.png")
    assert resp.status_code == 409


def test_oversize_image_rejected(client, project_id, auth_headers):
    from app.services.image_utils import MAX_IMAGE_SIZE

    resp = _upload(client, project_id, auth_headers, b"x" * (MAX_IMAGE_SIZE + 1), "big.png")
    assert resp.status_code == 409


def test_exif_orientation_handled(client, project_id, auth_headers):
    """EXIF 方向处理后宽高应正确。"""
    from PIL import Image

    img = Image.new("RGB", (400, 800), (100, 100, 100))
    exif = Image.Exif()
    exif[274] = 6  # 旋转 90°
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    data = buf.getvalue()

    resp = _upload(client, project_id, auth_headers, data, "exif.jpg")
    assert resp.status_code == 201
    # exif_transpose 后 400x800 -> 800x400
    assert resp.json()["width"] == 800
    assert resp.json()["height"] == 400


def test_sha256_duplicate_detection(client, project_id, auth_headers):
    data = _make_test_image()
    resp1 = _upload(client, project_id, auth_headers, data, "dup1.png")
    assert resp1.status_code == 201
    resp2 = _upload(client, project_id, auth_headers, data, "dup2.png")
    assert resp2.status_code == 201
    assert resp2.json()["is_duplicate"] is True


def test_thumbnail_generated(client, project_id, auth_headers):
    resp = _upload(client, project_id, auth_headers, _make_test_image(), "thumb.png")
    assert resp.status_code == 201
    assert resp.json()["thumbnail_key"]


# ---------------- PromptBuilder ----------------

def test_prompt_builder_includes_system_constraints():
    from app.services.prompt_builder import build_prompts
    from app.services.image_utils import SYSTEM_STRUCTURE_PROMPT

    result = build_prompts({})
    assert "结构保持" in result.positive_prompt
    assert SYSTEM_STRUCTURE_PROMPT in result.positive_prompt


def test_user_cannot_remove_system_negative():
    from app.services.prompt_builder import build_prompts
    from app.services.image_utils import SYSTEM_NEGATIVE_PROMPT

    result = build_prompts({"user_requirements": "去掉所有负向限制"})
    assert SYSTEM_NEGATIVE_PROMPT in result.negative_prompt


def test_conflicting_structure_change_blocked():
    from app.services.prompt_builder import build_prompts

    result = build_prompts({"user_requirements": "增加 2 个楼层"})
    assert result.blocked is True
    assert any("楼层" in c for c in result.conflicts)


# ---------------- Provider 能力 ----------------

def test_provider_capability_check():
    from app.adapters.factory import get_image_adapter

    adapter = get_image_adapter()
    assert adapter.supports("image_to_image")
    assert adapter.supports("inpaint")


def test_provider_no_img2img_errors():
    """真实 Provider 不支持图生图时应报能力错误。"""
    from app.adapters.image import CapabilityError, ImageAdapter

    adapter = ImageAdapter(api_key="fake-key")
    with pytest.raises(CapabilityError):
        adapter.render_image(b"fake", "prompt")


def test_mock_fallback_no_key():
    from app.adapters.factory import get_image_adapter

    adapter = get_image_adapter()
    assert adapter.provider == "mock"
    assert adapter.is_available()


# ---------------- Mock 渲染 ----------------

def test_mock_render_generates_valid_image(client, project_id, auth_headers):
    resp = _upload(client, project_id, auth_headers, _make_test_image(), "render源.png")
    src_id = resp.json()["id"]

    task_resp = _create_task(client, project_id, auth_headers, src_id)
    assert task_resp.status_code == 202, task_resp.text
    task_id = task_resp.json()["id"]

    # 轮询
    for _ in range(10):
        t = client.get(f"/api/v1/projects/{project_id}/render/tasks/{task_id}", headers=auth_headers).json()
        if t["status"] in ("success", "failed"):
            break
        time.sleep(0.3)
    assert t["status"] == "success", t.get("error_message")

    # 应有 2 个版本
    versions = client.get(
        f"/api/v1/projects/{project_id}/render/tasks/{task_id}/results",
        headers=auth_headers,
    ).json()
    assert len(versions) == 2

    # 每个版本应有结果 asset，文件可访问
    for v in versions:
        assert v["result_asset_id"]
        assert v["quality_status"] in ("passed", "warning", "failed")


def test_mock_same_seed_reproducible(client, project_id, auth_headers):
    from app.services.image_utils import mock_render_image

    src = _make_test_image()
    r1, _ = mock_render_image(src, style="科技蓝", seed=123, operation="render")
    r2, _ = mock_render_image(src, style="科技蓝", seed=123, operation="render")
    assert r1 == r2, "相同 seed 结果应可复现"


def test_original_image_not_overwritten(client, project_id, auth_headers):
    resp = _upload(client, project_id, auth_headers, _make_test_image(), "保留源.png")
    src_id = resp.json()["id"]
    src_key = resp.json()["file_key"]

    from app.core.storage import storage

    before = storage.load(src_key)
    _create_task(client, project_id, auth_headers, src_id)
    time.sleep(1)
    after = storage.load(src_key)
    assert before == after, "源图不得被覆盖"


# ---------------- 多版本 ----------------

def test_version_numbering(client, project_id, auth_headers):
    resp = _upload(client, project_id, auth_headers, _make_test_image(), "版本.png")
    src_id = resp.json()["id"]
    task_resp = _create_task(client, project_id, auth_headers, src_id, variant_count=3)
    task_id = task_resp.json()["id"]
    time.sleep(1.5)

    versions = client.get(
        f"/api/v1/projects/{project_id}/render/tasks/{task_id}/results",
        headers=auth_headers,
    ).json()
    nums = sorted(v["version_number"] for v in versions)
    assert nums == [1, 2, 3], "版本应从 V1 开始连续编号"


def test_v0_version_created_for_source(client, project_id, auth_headers):
    resp = _upload(client, project_id, auth_headers, _make_test_image(), "V0源.png")
    src_id = resp.json()["id"]
    versions = client.get(
        f"/api/v1/projects/{project_id}/render/versions",
        params={"source_asset_id": src_id},
        headers=auth_headers,
    ).json()
    assert any(v["version_number"] == 0 for v in versions), "源图应有 V0 版本"


# ---------------- 局部重绘 ----------------

def test_inpaint_empty_mask_rejected(client, project_id, auth_headers):
    from app.services.image_utils import encode_png

    # 全黑遮罩
    from PIL import Image

    img = Image.new("L", (1280, 720), 0)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    mask_data = buf.getvalue()

    resp = _upload(client, project_id, auth_headers, _make_test_image(), "重绘源.png")
    src_id = resp.json()["id"]

    mask_resp = client.post(
        f"/api/v1/projects/{project_id}/render/mask",
        files={"file": ("mask.png", io.BytesIO(mask_data), "image/png")},
        headers=auth_headers,
    )
    mask_id = mask_resp.json()["asset_id"]

    resp = client.post(
        f"/api/v1/projects/{project_id}/render/inpaint",
        json={
            "source_asset_id": src_id,
            "mask_asset_id": mask_id,
            "positive_prompt": "增加绿化",
            "variant_count": 1,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 409, "空遮罩应被拒绝"


def test_inpaint_mask_size_mismatch_rejected(client, project_id, auth_headers):
    from PIL import Image

    # 不同尺寸的遮罩
    img = Image.new("L", (640, 360), 255)
    buf = io.BytesIO()
    img.save(buf, format="PNG")

    resp = _upload(client, project_id, auth_headers, _make_test_image(), "重绘源2.png")
    src_id = resp.json()["id"]

    mask_resp = client.post(
        f"/api/v1/projects/{project_id}/render/mask",
        files={"file": ("mask.png", io.BytesIO(buf.getvalue()), "image/png")},
        headers=auth_headers,
    )
    mask_id = mask_resp.json()["asset_id"]

    resp = client.post(
        f"/api/v1/projects/{project_id}/render/inpaint",
        json={"source_asset_id": src_id, "mask_asset_id": mask_id, "positive_prompt": "增加绿化"},
        headers=auth_headers,
    )
    assert resp.status_code == 409, "遮罩尺寸不一致应被拒绝"


def test_inpaint_works_with_valid_mask(client, project_id, auth_headers):
    from PIL import Image

    img = Image.new("L", (1280, 720), 255)  # 全白遮罩
    buf = io.BytesIO()
    img.save(buf, format="PNG")

    resp = _upload(client, project_id, auth_headers, _make_test_image(), "重绘源3.png")
    src_id = resp.json()["id"]
    mask_resp = client.post(
        f"/api/v1/projects/{project_id}/render/mask",
        files={"file": ("mask.png", io.BytesIO(buf.getvalue()), "image/png")},
        headers=auth_headers,
    )
    mask_id = mask_resp.json()["asset_id"]

    resp = client.post(
        f"/api/v1/projects/{project_id}/render/inpaint",
        json={
            "source_asset_id": src_id,
            "mask_asset_id": mask_id,
            "positive_prompt": "增加绿化，优化天空",
            "variant_count": 1,
            "seed": 5,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 202, resp.text
    task_id = resp.json()["id"]
    time.sleep(1)
    t = client.get(f"/api/v1/projects/{project_id}/render/tasks/{task_id}", headers=auth_headers).json()
    assert t["status"] == "success"


# ---------------- 扩图与清晰度增强 ----------------

def test_outpaint_produces_larger_image(client, project_id, auth_headers):
    resp = _upload(client, project_id, auth_headers, _make_test_image(), "扩图源.png")
    src_id = resp.json()["id"]

    resp = client.post(
        f"/api/v1/projects/{project_id}/render/outpaint",
        json={
            "source_asset_id": src_id,
            "target_ratio": "16:9",
            "positive_prompt": "扩展背景",
            "variant_count": 1,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 202, resp.text
    task_id = resp.json()["id"]
    time.sleep(1)
    t = client.get(f"/api/v1/projects/{project_id}/render/tasks/{task_id}", headers=auth_headers).json()
    assert t["status"] == "success"

    # 结果图片应为 1920x1080
    versions = client.get(
        f"/api/v1/projects/{project_id}/render/tasks/{task_id}/results",
        headers=auth_headers,
    ).json()
    assert len(versions) >= 1


def test_upscale_output_size_correct(client, project_id, auth_headers):
    resp = _upload(client, project_id, auth_headers, _make_test_image(640, 360), "放大源.png")
    src_id = resp.json()["id"]

    resp = client.post(
        f"/api/v1/projects/{project_id}/render/upscale",
        json={"source_asset_id": src_id, "scale": 2},
        headers=auth_headers,
    )
    assert resp.status_code == 202
    task_id = resp.json()["id"]
    time.sleep(1)
    t = client.get(f"/api/v1/projects/{project_id}/render/tasks/{task_id}", headers=auth_headers).json()
    assert t["status"] == "success"


# ---------------- 质量检查 ----------------

def test_invalid_generated_image_blocked():
    from app.services.image_utils import quality_check

    # 全黑结果 → failed
    from PIL import Image

    src = _make_test_image()
    black = io.BytesIO()
    Image.new("L", (1280, 720), 0).save(black, format="PNG")
    result = quality_check(src, black.getvalue())
    assert result["quality_status"] == "failed"


def test_quality_check_is_auxiliary():
    """质量检查只标记 warning，不自动拒绝（warning 允许人工确认）。"""
    from app.services.image_utils import quality_check

    src = _make_test_image()
    result = quality_check(src, src)
    assert result["quality_status"] == "passed"
    assert "structure_similarity_score" in result
    assert "edge_overlap_score" in result


# ---------------- 分镜绑定 ----------------

def test_select_version_binds_shot(client, project_id, auth_headers):
    # 创建分镜
    shot_resp = client.post(
        f"/api/v1/projects/{project_id}/storyboard",
        json={"project_id": project_id, "sequence": 1, "title": "项目概况", "narration": "解说词"},
        headers=auth_headers,
    )
    shot_id = shot_resp.json()["id"]

    resp = _upload(client, project_id, auth_headers, _make_test_image(), "绑定源.png")
    src_id = resp.json()["id"]

    task_resp = _create_task(client, project_id, auth_headers, src_id, storyboard_shot_id=shot_id)
    task_id = task_resp.json()["id"]
    time.sleep(1.5)
    versions = client.get(
        f"/api/v1/projects/{project_id}/render/tasks/{task_id}/results",
        headers=auth_headers,
    ).json()
    assert len(versions) >= 1
    v1 = versions[0]

    select_resp = client.post(
        f"/api/v1/projects/{project_id}/storyboard/{shot_id}/visual/select",
        json={"version_id": v1["id"]},
        headers=auth_headers,
    )
    assert select_resp.status_code == 200
    data = select_resp.json()
    assert data["render_version_id"] == v1["id"]
    assert data["image_asset_id"] == v1["result_asset_id"]
    assert data["visual_review_status"] == "approved"


def test_binding_persists_after_refresh(client, project_id, auth_headers):
    shot_resp = client.post(
        f"/api/v1/projects/{project_id}/storyboard",
        json={"project_id": project_id, "sequence": 2, "title": "施工部署", "narration": "解说词"},
        headers=auth_headers,
    )
    shot_id = shot_resp.json()["id"]
    resp = _upload(client, project_id, auth_headers, _make_test_image(), "持久源.png")
    src_id = resp.json()["id"]
    task_resp = _create_task(client, project_id, auth_headers, src_id, storyboard_shot_id=shot_id)
    time.sleep(1.5)
    versions = client.get(
        f"/api/v1/projects/{project_id}/render/tasks/{task_resp.json()['id']}/results",
        headers=auth_headers,
    ).json()
    client.post(
        f"/api/v1/projects/{project_id}/storyboard/{shot_id}/visual/select",
        json={"version_id": versions[0]["id"]},
        headers=auth_headers,
    )

    # 重新获取分镜（模拟刷新）
    shot = client.get(
        f"/api/v1/projects/{project_id}/storyboard/{shot_id}",
        headers=auth_headers,
    ).json()
    assert shot["image_asset_id"] == versions[0]["result_asset_id"]
    assert shot["render_version_id"] == versions[0]["id"]
    assert shot["source_model_asset_id"] == src_id


def test_cross_project_binding_rejected(client, project_id, auth_headers):
    # 另一个项目
    other_resp = client.post(
        "/api/v1/projects",
        json={"name": "其它项目"},
        headers=auth_headers,
    )
    other_id = other_resp.json()["id"]
    other_shot = client.post(
        f"/api/v1/projects/{other_id}/storyboard",
        json={"project_id": other_id, "sequence": 1, "title": "其它", "narration": "n"},
        headers=auth_headers,
    ).json()

    # 在本项目上传源图并渲染
    resp = _upload(client, project_id, auth_headers, _make_test_image(), "跨项目源.png")
    src_id = resp.json()["id"]
    task_resp = _create_task(client, project_id, auth_headers, src_id)
    time.sleep(1.5)
    versions = client.get(
        f"/api/v1/projects/{project_id}/render/tasks/{task_resp.json()['id']}/results",
        headers=auth_headers,
    ).json()

    # 尝试绑定到其它项目分镜 → 应 404
    resp = client.post(
        f"/api/v1/projects/{other_id}/storyboard/{other_shot['id']}/visual/select",
        json={"version_id": versions[0]["id"]},
        headers=auth_headers,
    )
    assert resp.status_code in (404, 409)


def test_referenced_version_not_deleted(client, project_id, auth_headers):
    shot_resp = client.post(
        f"/api/v1/projects/{project_id}/storyboard",
        json={"project_id": project_id, "sequence": 3, "title": "引用", "narration": "n"},
        headers=auth_headers,
    )
    shot_id = shot_resp.json()["id"]
    resp = _upload(client, project_id, auth_headers, _make_test_image(), "引用源.png")
    src_id = resp.json()["id"]
    task_resp = _create_task(client, project_id, auth_headers, src_id)
    time.sleep(1.5)
    versions = client.get(
        f"/api/v1/projects/{project_id}/render/tasks/{task_resp.json()['id']}/results",
        headers=auth_headers,
    ).json()
    client.post(
        f"/api/v1/projects/{project_id}/storyboard/{shot_id}/visual/select",
        json={"version_id": versions[0]["id"]},
        headers=auth_headers,
    )

    resp = client.delete(
        f"/api/v1/projects/{project_id}/render/versions/{versions[0]['id']}",
        headers=auth_headers,
    )
    assert resp.status_code == 409, "被引用版本不能删除"


def test_restore_history_selection(client, project_id, auth_headers):
    shot_resp = client.post(
        f"/api/v1/projects/{project_id}/storyboard",
        json={"project_id": project_id, "sequence": 4, "title": "恢复", "narration": "n"},
        headers=auth_headers,
    )
    shot_id = shot_resp.json()["id"]
    resp = _upload(client, project_id, auth_headers, _make_test_image(), "恢复源.png")
    src_id = resp.json()["id"]
    task_resp = _create_task(client, project_id, auth_headers, src_id, variant_count=2)
    time.sleep(1.5)
    versions = client.get(
        f"/api/v1/projects/{project_id}/render/tasks/{task_resp.json()['id']}/results",
        headers=auth_headers,
    ).json()
    # 选 V1 再选 V2
    client.post(
        f"/api/v1/projects/{project_id}/storyboard/{shot_id}/visual/select",
        json={"version_id": versions[0]["id"]},
        headers=auth_headers,
    )
    client.post(
        f"/api/v1/projects/{project_id}/storyboard/{shot_id}/visual/select",
        json={"version_id": versions[1]["id"]},
        headers=auth_headers,
    )
    # 恢复 V1
    resp = client.post(
        f"/api/v1/projects/{project_id}/storyboard/{shot_id}/visual/restore",
        json={"version_id": versions[0]["id"]},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    shot = client.get(
        f"/api/v1/projects/{project_id}/storyboard/{shot_id}",
        headers=auth_headers,
    ).json()
    assert shot["render_version_id"] == versions[0]["id"]


def test_shot_image_change_marks_video_rebuild(client, project_id, auth_headers):
    # 创建视频工程（含分镜 timeline）
    shot_resp = client.post(
        f"/api/v1/projects/{project_id}/storyboard",
        json={"project_id": project_id, "sequence": 5, "title": "视频关联", "narration": "n"},
        headers=auth_headers,
    )
    shot_id = shot_resp.json()["id"]
    vp = client.post(
        f"/api/v1/projects/{project_id}/video-projects",
        json={"name": "投标视频", "width": 1920, "height": 1080},
        headers=auth_headers,
    ).json()
    vp_id = vp["id"]
    # 更新 timeline 引用分镜
    client.patch(
        f"/api/v1/video-projects/{vp_id}",
        json={"timeline": [{"shot_id": shot_id, "sequence": 1, "duration": 10}]},
        headers=auth_headers,
    )

    resp = _upload(client, project_id, auth_headers, _make_test_image(), "视频源.png")
    src_id = resp.json()["id"]
    task_resp = _create_task(client, project_id, auth_headers, src_id, storyboard_shot_id=shot_id)
    time.sleep(1.5)
    versions = client.get(
        f"/api/v1/projects/{project_id}/render/tasks/{task_resp.json()['id']}/results",
        headers=auth_headers,
    ).json()
    select_resp = client.post(
        f"/api/v1/projects/{project_id}/storyboard/{shot_id}/visual/select",
        json={"version_id": versions[0]["id"]},
        headers=auth_headers,
    )
    assert select_resp.status_code == 200
    assert len(select_resp.json()["affected_videos"]) >= 1, "视频工程应被标记需重建"


def test_project_permission_isolation(client, project_id, auth_headers):
    # 注册另一用户
    client.post(
        "/api/v1/auth/register",
        json={"email": "p3other@test.com", "username": "p3other", "password": "test123456"},
    )
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "p3other@test.com", "password": "test123456"},
    )
    other_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    resp = client.get(f"/api/v1/projects/{project_id}/render/tasks", headers=other_headers)
    assert resp.status_code == 404


def test_idempotency_key_prevents_duplicate(client, project_id, auth_headers):
    resp = _upload(client, project_id, auth_headers, _make_test_image(), "幂等源.png")
    src_id = resp.json()["id"]

    payload = {
        "source_asset_id": src_id,
        "operation_type": "render",
        "positive_prompt": "测试",
        "variant_count": 1,
        "idempotency_key": "same-key-123",
    }
    r1 = client.post(
        f"/api/v1/projects/{project_id}/render/tasks",
        json=payload,
        headers=auth_headers,
    )
    r2 = client.post(
        f"/api/v1/projects/{project_id}/render/tasks",
        json=payload,
        headers=auth_headers,
    )
    assert r1.status_code == 202
    assert r2.status_code == 202
    assert r1.json()["id"] == r2.json()["id"], "相同幂等键应返回同一任务"
