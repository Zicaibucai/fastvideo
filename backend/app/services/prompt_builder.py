"""提示词自动构建服务。

不要在 API 路由或 Celery 任务中拼接复杂提示词。
系统级结构保持提示自动加入，普通用户不能完全删除。
检测与工程事实冲突的结构修改请求并拦截。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.services.image_utils import SYSTEM_NEGATIVE_PROMPT, SYSTEM_STRUCTURE_PROMPT

# 工程事实冲突关键词：这些修改会改变工程结构
CONFLICT_PATTERNS = [
    (r"增加.*(楼层|层|建筑主体)", "增加楼层/建筑主体"),
    (r"删除.*(楼层|层|建筑主体)", "删除楼层/建筑主体"),
    (r"移动.*(主楼|建筑主体|塔吊|主要设备)", "移动主楼/设备"),
    (r"改变.*(轮廓|柱网|柱距)", "改变建筑轮廓/柱网"),
    (r"改.*(主入口|道路走向)", "改变主入口/道路走向"),
    (r"去掉.*(塔吊|安全设施|主要设备)", "移除塔吊/安全设施"),
    (r"改成.*(另一栋|不同建筑)", "改成其它建筑"),
]


@dataclass
class PromptBuildInput:
    project_type: str = "公共建筑"
    building_use: str = "办公"
    source_software: str = "Revit"
    camera_angle: str = "建筑人视"
    shot_description: str = ""
    user_requirements: str = ""
    preset_prompt: str = ""
    material_requirements: str = ""
    environment_requirements: str = ""
    weather: str = ""
    lighting: str = ""
    project_stage: str = "主体施工"
    brand_colors: str = ""
    composition: str = ""
    structure_strength: int = 85
    preserve_logo: bool = True
    preserve_text: bool = True
    preserve_roads: bool = True
    preserve_building_shape: bool = True
    preserve_equipment: bool = True
    custom_constraints: list[str] = field(default_factory=list)


@dataclass
class PromptBuildResult:
    positive_prompt: str
    negative_prompt: str
    structure_prompt: str
    conflicts: list[str] = field(default_factory=list)
    blocked: bool = False


def check_structure_conflicts(user_text: str) -> list[str]:
    """检测用户输入中的结构修改冲突请求。"""
    if not user_text:
        return []
    conflicts = []
    for pattern, desc in CONFLICT_PATTERNS:
        if re.search(pattern, user_text):
            conflicts.append(desc)
    return conflicts


def build_prompts(input_data: PromptBuildInput | dict[str, Any]) -> PromptBuildResult:
    """构建最终正向/负向提示词。

    结构保持强度低于 70 时加入风险提示（不阻断，但 UI 需显示警告）。
    检测到与工程事实冲突的修改请求时返回 blocked=True。
    """
    if isinstance(input_data, dict):
        input_data = PromptBuildInput(**input_data)

    # 冲突检测
    conflicts = []
    user_text = f"{input_data.user_requirements} {input_data.shot_description}"
    conflicts.extend(check_structure_conflicts(user_text))
    for c in input_data.custom_constraints or []:
        conflicts.extend(check_structure_conflicts(c))

    # 系统级结构保持提示（始终加入）
    structure_prompt = SYSTEM_STRUCTURE_PROMPT
    if input_data.structure_strength < 70:
        structure_prompt += "（结构保持强度较低，请特别注意保持主体结构）"

    # 组装正向提示词
    parts = [
        f"项目类型：{input_data.project_type}",
        f"建筑用途：{input_data.building_use}",
        f"来源软件：{input_data.source_software}",
        f"镜头角度：{input_data.camera_angle}",
    ]
    if input_data.shot_description:
        parts.append(f"分镜画面说明：{input_data.shot_description}")
    if input_data.user_requirements:
        parts.append(f"用户要求：{input_data.user_requirements}")
    if input_data.preset_prompt:
        parts.append(f"渲染风格：{input_data.preset_prompt}")
    if input_data.material_requirements:
        parts.append(f"材质要求：{input_data.material_requirements}")
    if input_data.environment_requirements:
        parts.append(f"环境要求：{input_data.environment_requirements}")
    if input_data.weather:
        parts.append(f"天气：{input_data.weather}")
    if input_data.lighting:
        parts.append(f"光照：{input_data.lighting}")
    parts.append(f"项目施工阶段：{input_data.project_stage}")
    if input_data.brand_colors:
        parts.append(f"企业品牌色：{input_data.brand_colors}")
    if input_data.composition:
        parts.append(f"构图与清晰度：{input_data.composition}")
    parts.append(f"结构保持：{structure_prompt}")

    positive = "，".join(parts)

    # 负向提示词：系统级 + 保留项
    negatives = [SYSTEM_NEGATIVE_PROMPT]
    if not input_data.preserve_logo:
        negatives.remove("禁止修改企业Logo")
    # 始终保留系统级核心约束，用户不能完全删除
    negative = "，".join(negatives)

    return PromptBuildResult(
        positive_prompt=positive,
        negative_prompt=negative,
        structure_prompt=structure_prompt,
        conflicts=conflicts,
        blocked=bool(conflicts),
    )
