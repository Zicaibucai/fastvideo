"""渲染预设路由：12 种系统预设 + 企业管理。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.exceptions import ForbiddenError, NotFoundError
from app.models.render_preset import RenderPreset
from app.models.user import User
from app.schemas.render import (
    RenderPresetCreate,
    RenderPresetOut,
    RenderPresetUpdate,
)

router = APIRouter(prefix="/render-presets", tags=["渲染预设"])

# 12 种系统预设
SYSTEM_PRESETS = [
    {
        "name": "工业厂房写实",
        "description": "适用于厂房、仓储类项目，突出钢结构与工业质感",
        "category": "工业建筑",
        "default_positive_prompt": "工业厂房钢结构，金属质感，大跨度屋面，通风采光良好",
        "recommended_aspect_ratio": "16:9",
        "recommended_structure_strength": 90,
    },
    {
        "name": "房建施工现场写实",
        "description": "房建项目施工现场实景，塔吊、临建、材料堆场",
        "category": "施工阶段",
        "default_positive_prompt": "房建施工现场，塔吊林立，脚手架完整，材料有序堆放",
        "recommended_aspect_ratio": "16:9",
        "recommended_structure_strength": 90,
    },
    {
        "name": "科技蓝投标风格",
        "description": "深蓝色调，科技感，适合投标汇报主视觉",
        "category": "投标风格",
        "default_positive_prompt": "深蓝色科技感色调，数据可视化元素，现代建筑",
        "recommended_aspect_ratio": "16:9",
        "recommended_structure_strength": 85,
    },
    {
        "name": "建成效果日景",
        "description": "项目建成后的日间效果，真实光照",
        "category": "建成效果",
        "default_positive_prompt": "晴朗日间，真实光照，材质细腻，绿化景观完善",
        "recommended_aspect_ratio": "16:9",
        "recommended_structure_strength": 85,
    },
    {
        "name": "建成效果夜景",
        "description": "项目建成后的夜景灯光效果",
        "category": "建成效果",
        "default_positive_prompt": "夜景灯光，暖色照明，建筑轮廓灯带，星空背景",
        "recommended_aspect_ratio": "16:9",
        "recommended_structure_strength": 85,
    },
    {
        "name": "总平面鸟瞰",
        "description": "总平面布置鸟瞰视角，道路与建筑布局",
        "category": "鸟瞰",
        "default_positive_prompt": "总平面鸟瞰，建筑体块清晰，道路系统完整，绿化分区",
        "recommended_aspect_ratio": "16:9",
        "recommended_structure_strength": 92,
    },
    {
        "name": "白模分析图",
        "description": "白模风格，用于分析图与方案推敲",
        "category": "分析图",
        "default_positive_prompt": "白色建筑模型，灰底背景，简洁分析图风格",
        "recommended_aspect_ratio": "16:9",
        "recommended_structure_strength": 92,
    },
    {
        "name": "BIM技术示意图",
        "description": "BIM 三维模型示意，管线综合展示",
        "category": "BIM",
        "default_positive_prompt": "BIM三维模型，管线颜色区分，碰撞检查视角",
        "recommended_aspect_ratio": "16:9",
        "recommended_structure_strength": 90,
    },
    {
        "name": "绿色施工展示",
        "description": "绿色施工场景，环保设施，扬尘控制",
        "category": "绿色施工",
        "default_positive_prompt": "绿色施工，喷淋降尘，垃圾分类，节能设施",
        "recommended_aspect_ratio": "16:9",
        "recommended_structure_strength": 88,
    },
    {
        "name": "安全文明施工展示",
        "description": "安全文明施工标准化现场",
        "category": "安全文明",
        "default_positive_prompt": "安全文明施工现场，标准化围挡，安全标语，防护到位",
        "recommended_aspect_ratio": "16:9",
        "recommended_structure_strength": 88,
    },
    {
        "name": "机电安装展示",
        "description": "机电管线、设备安装效果",
        "category": "机电",
        "default_positive_prompt": "机电管线安装，桥架整齐，管道保温，设备就位",
        "recommended_aspect_ratio": "16:9",
        "recommended_structure_strength": 90,
    },
    {
        "name": "钢结构吊装展示",
        "description": "钢结构吊装施工场景",
        "category": "施工阶段",
        "default_positive_prompt": "钢结构吊装，汽车吊作业，钢柱钢梁拼装",
        "recommended_aspect_ratio": "16:9",
        "recommended_structure_strength": 90,
    },
]

SYSTEM_NEGATIVE = (
    "禁止改变建筑主体数量，禁止增加或删除楼层，禁止改变建筑轮廓，"
    "禁止改变柱网，禁止移动主要门窗，禁止改变道路走向，禁止移动主要设备，"
    "禁止生成不合理施工机械，禁止修改企业Logo，禁止乱码文字，禁止低清晰度"
)


def seed_system_presets(db: Session) -> None:
    """首次启动时播种 12 种系统预设。"""
    count = db.query(RenderPreset).filter(RenderPreset.is_system.is_(True)).count()
    if count > 0:
        return
    for i, p in enumerate(SYSTEM_PRESETS):
        db.add(
            RenderPreset(
                name=p["name"],
                description=p["description"],
                category=p["category"],
                default_positive_prompt=p["default_positive_prompt"],
                default_negative_prompt=SYSTEM_NEGATIVE,
                recommended_aspect_ratio=p["recommended_aspect_ratio"],
                recommended_structure_strength=p["recommended_structure_strength"],
                is_system=True,
                is_enabled=True,
                created_by="system",
                sort_order=i,
            )
        )
    db.commit()


@router.get("", response_model=list[RenderPresetOut], summary="渲染预设列表")
def list_presets(
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> list[RenderPreset]:
    return (
        db.query(RenderPreset)
        .filter(RenderPreset.is_enabled.is_(True))
        .order_by(RenderPreset.is_system.desc(), RenderPreset.sort_order.asc())
        .all()
    )


@router.post("", response_model=RenderPresetOut, status_code=201, summary="创建企业预设")
def create_preset(
    payload: RenderPresetCreate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> RenderPreset:
    preset = RenderPreset(
        name=payload.name,
        description=payload.description,
        category=payload.category,
        default_positive_prompt=payload.default_positive_prompt,
        default_negative_prompt=payload.default_negative_prompt or SYSTEM_NEGATIVE,
        recommended_aspect_ratio=payload.recommended_aspect_ratio,
        recommended_structure_strength=payload.recommended_structure_strength,
        is_system=payload.is_system,
        is_enabled=payload.is_enabled,
        created_by=current.username,
        sort_order=100,
    )
    db.add(preset)
    db.commit()
    db.refresh(preset)
    return preset


@router.patch("/{preset_id}", response_model=RenderPresetOut, summary="更新预设")
def update_preset(
    preset_id: str,
    payload: RenderPresetUpdate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> RenderPreset:
    preset = db.get(RenderPreset, preset_id)
    if not preset:
        raise NotFoundError("预设不存在")
    if preset.is_system and not current.is_superuser:
        raise ForbiddenError("系统预设仅管理员可修改")
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(preset, field, value)
    db.commit()
    db.refresh(preset)
    return preset


@router.post("/{preset_id}/duplicate", response_model=RenderPresetOut, summary="复制为企业预设")
def duplicate_preset(
    preset_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> RenderPreset:
    src = db.get(RenderPreset, preset_id)
    if not src:
        raise NotFoundError("预设不存在")
    copy = RenderPreset(
        name=f"{src.name}(企业版)",
        description=src.description,
        category=src.category,
        default_positive_prompt=src.default_positive_prompt,
        default_negative_prompt=src.default_negative_prompt,
        recommended_aspect_ratio=src.recommended_aspect_ratio,
        recommended_structure_strength=src.recommended_structure_strength,
        is_system=False,
        is_enabled=True,
        created_by=current.username,
        source_preset_id=src.id,
        sort_order=100,
    )
    db.add(copy)
    db.commit()
    db.refresh(copy)
    return copy
