"""画面渲染演示数据脚本。

为指定项目生成演示模型截图并执行 Mock 渲染，结果保存在素材库。
用法（在 backend/ 目录下）：
    python -m scripts.seed_render_demo <project_id>
    或
    python scripts/seed_render_demo.py <project_id>
"""

from __future__ import annotations

import sys
from pathlib import Path

# 确保 backend/ 在 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import SessionLocal
from app.core.storage import storage
from app.models.asset import Asset
from app.models.render_job import RenderJob
from app.services.image_utils import generate_demo_model_shot, make_thumbnail
from app.services.render_service import run_render_job

DEMO_SHOTS = [
    {"kind": "total_plan", "name": "总平面鸟瞰图（演示）", "angle": "总平面鸟瞰", "software": "Revit"},
    {"kind": "building_perspective", "name": "建筑人视效果图（演示）", "angle": "建筑人视", "software": "SketchUp"},
    {"kind": "construction_stage", "name": "施工阶段航拍图（演示）", "angle": "低空鸟瞰", "software": "Navisworks"},
]


def seed(project_id: str) -> None:
    db = SessionLocal()
    try:
        for i, demo in enumerate(DEMO_SHOTS):
            # 生成演示源图
            img_bytes = generate_demo_model_shot(demo["kind"], seed=100 + i)
            key = f"projects/{project_id}/model_shots/demo_{i}.png"
            storage.save(key, img_bytes)

            # 缩略图
            import io

            from PIL import Image

            img = Image.open(io.BytesIO(img_bytes))
            thumb = make_thumbnail(img)
            thumb_key = key.replace(".png", "_thumb.png")
            storage.save(thumb_key, thumb)

            # 创建 Asset
            asset = Asset(
                project_id=project_id,
                name=demo["name"],
                asset_type="image",
                source="model_shot",
                file_key=key,
                thumbnail_key=thumb_key,
                file_size=len(img_bytes),
                mime_type="image/png",
                width=img.width,
                height=img.height,
                is_original_model_shot=True,
                source_software=demo["software"],
                camera_angle=demo["angle"],
                is_ai_generated=False,
                meta={"is_demo": True},
            )
            db.add(asset)
            db.flush()

            # 建立 V0 版本
            from app.services.render_service import ensure_v0_version

            ensure_v0_version(db, asset.id)

            # 创建 2 个 Mock 渲染版本
            for v in range(2):
                from app.services.render_service import create_render_job, estimate_cost

                job = create_render_job(
                    db=db,
                    project_id=project_id,
                    source_asset_id=asset.id,
                    preset_id=None,
                    operation_type="render",
                    positive_prompt=f"演示渲染 {demo['name']} 风格{v + 1}",
                    negative_prompt="禁止改变建筑主体",
                    aspect_ratio="16:9",
                    output_width=None,
                    output_height=None,
                    variant_count=1,
                    structure_strength=88,
                    creativity=0.5,
                    seed=200 + i * 10 + v,
                    provider="mock",
                    model_name="mock-render",
                    preserve_logo=True,
                    preserve_text=True,
                    preserve_roads=True,
                    preserve_building_shape=True,
                    preserve_equipment=True,
                    custom_constraints=None,
                    mask_asset_id=None,
                    idempotency_key=f"demo-{project_id}-{i}-{v}",
                    is_conceptual=False,
                    concept_note=None,
                    estimated_cost=0.0,
                )
                job.estimated_cost = estimate_cost(job)
                db.commit()

            print(f"✓ 源图 {demo['name']} 已生成")

        # 执行所有排队任务（同步）
        jobs = (
            db.query(RenderJob)
            .filter(RenderJob.project_id == project_id, RenderJob.status == "queued")
            .all()
        )
        for job in jobs:
            run_render_job(job.id)
            print(f"✓ 渲染任务 {job.id} 完成")


        db.commit()
        print("=== 演示数据完成 ===")
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python scripts/seed_render_demo.py <project_id>")
        sys.exit(1)
    seed(sys.argv[1])
