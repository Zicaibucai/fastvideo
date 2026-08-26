"""施工镜头配方的规范化、校验与 Seedance 文本编译。

施工视频不能只靠一段自然语言描述。这个模块把施工状态、工序依赖、
双时间轴、空间锚点和安全约束统一编译成发送给视频 Provider 的文本，
并保证创建任务时保存的快照与实际发送内容一致。
"""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any


CONSTRUCTION_MODE_PRESENTATION = "presentation"
CONSTRUCTION_MODE_EVOLUTION = "construction_evolution"
VALID_CONSTRUCTION_MODES = {
    CONSTRUCTION_MODE_PRESENTATION,
    CONSTRUCTION_MODE_EVOLUTION,
}


def _items(value: Any, *, limit: int = 12) -> list[str]:
    if isinstance(value, list):
        values = [str(item).strip() for item in value if str(item).strip()]
    elif isinstance(value, str) and value.strip():
        values = [item.strip() for item in value.replace("；", "\n").replace(";", "\n").splitlines() if item.strip()]
    else:
        values = []
    return values[:limit]


def _text(value: Any, *, max_length: int = 300) -> str:
    return str(value or "").strip()[:max_length]


def _object(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _timeline(value: Any, *, fallback: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return deepcopy(fallback)
    rows: list[dict[str, Any]] = []
    for item in value[:8]:
        if not isinstance(item, dict):
            continue
        try:
            start = max(0, min(100, float(item.get("from", item.get("start", 0)))))
            end = max(start, min(100, float(item.get("to", item.get("end", 100)))))
        except (TypeError, ValueError):
            continue
        instruction = _text(item.get("instruction") or item.get("description") or item.get("prompt"), max_length=240)
        if instruction:
            rows.append({"from": start, "to": end, "instruction": instruction})
    return rows or deepcopy(fallback)


def _default_construction_timeline() -> list[dict[str, Any]]:
    return [
        {"from": 0, "to": 20, "instruction": "确认前置条件与作业面，保持已完成构件和安全设施稳定"},
        {"from": 20, "to": 80, "instruction": "按照声明的施工顺序推进一个主工序，不跨越未声明的状态"},
        {"from": 80, "to": 100, "instruction": "完成目标状态，停止结构变化并保持画面连续定格"},
    ]


def _default_camera_timeline() -> list[dict[str, Any]]:
    return [
        {"from": 0, "to": 20, "instruction": "固定机位建立全景，交代作业区、机械和空间锚点"},
        {"from": 20, "to": 80, "instruction": "保持轴线和焦段稳定，缓慢跟随施工工作面"},
        {"from": 80, "to": 100, "instruction": "减速并定格在目标完成状态，不切镜"},
    ]


def normalize_construction_recipe(recipe: Any) -> dict[str, Any] | None:
    """返回可安全保存和编译的配方副本。

    旧模板没有施工字段时保留原始配方，仅补充 ``construction_mode``，
    以保证 V1 模板仍按建筑展示模式工作。
    """
    if not isinstance(recipe, dict):
        return None
    normalized = deepcopy(recipe)
    mode = str(normalized.get("construction_mode") or CONSTRUCTION_MODE_PRESENTATION).strip()
    if mode not in VALID_CONSTRUCTION_MODES:
        mode = CONSTRUCTION_MODE_PRESENTATION
    normalized["construction_mode"] = mode

    has_v2_fields = any(
        key in normalized
        for key in (
            "project_facts",
            "construction_unit",
            "state_transition",
            "construction_timeline",
            "camera_timeline",
            "spatial_anchors",
            "temporary_works",
            "safety_constraints",
            "quality_constraints",
            "acceptance_checks",
        )
    )
    if has_v2_fields or mode == CONSTRUCTION_MODE_EVOLUTION:
        try:
            normalized["recipe_version"] = max(2, int(normalized.get("recipe_version") or 1))
        except (TypeError, ValueError):
            normalized["recipe_version"] = 2

        project_facts = _object(normalized.get("project_facts"))
        normalized["project_facts"] = {
            "structure_type": _text(project_facts.get("structure_type"), max_length=120),
            "current_stage": _text(project_facts.get("current_stage"), max_length=120),
            "target_stage": _text(project_facts.get("target_stage"), max_length=120),
            "fact_sources": _items(project_facts.get("fact_sources"), limit=8),
        }

        unit = _object(normalized.get("construction_unit"))
        normalized["construction_unit"] = {
            "wbs_code": _text(unit.get("wbs_code"), max_length=48),
            "work_item": _text(unit.get("work_item"), max_length=160),
            "work_zone": _text(unit.get("work_zone"), max_length=120),
            "zone_mappings": _items(unit.get("zone_mappings"), limit=8),
            "objects": _items(unit.get("objects")),
            "prerequisites": _items(unit.get("prerequisites")),
            "completion_state": _items(unit.get("completion_state")),
        }

        transition = _object(normalized.get("state_transition"))
        normalized["state_transition"] = {
            "start_state": _text(transition.get("start_state"), max_length=320),
            "end_state": _text(transition.get("end_state"), max_length=320),
            "allowed_changes": _items(transition.get("allowed_changes")),
            "forbidden_jumps": _items(transition.get("forbidden_jumps")),
        }
        normalized["construction_timeline"] = _timeline(
            normalized.get("construction_timeline"),
            fallback=_default_construction_timeline(),
        )
        normalized["camera_timeline"] = _timeline(
            normalized.get("camera_timeline"),
            fallback=_default_camera_timeline(),
        )
        normalized["spatial_anchors"] = _items(normalized.get("spatial_anchors"))
        normalized["temporary_works"] = {
            "required": _items(_object(normalized.get("temporary_works")).get("required")),
            "forbidden": _items(_object(normalized.get("temporary_works")).get("forbidden")),
        }
        normalized["safety_constraints"] = _items(normalized.get("safety_constraints"))
        normalized["quality_constraints"] = _items(normalized.get("quality_constraints"))
        normalized["acceptance_checks"] = _items(normalized.get("acceptance_checks"))
        override = str(normalized.get("provider_prompt_override") or "").strip()
        if override:
            normalized["provider_prompt_override"] = override
        else:
            normalized.pop("provider_prompt_override", None)
    return normalized


def construction_transition_is_controlled(recipe: Any) -> bool:
    """施工演进模式只有声明了起止状态和允许变化时才可放行结构变化。"""
    normalized = normalize_construction_recipe(recipe)
    if not normalized or normalized.get("construction_mode") != CONSTRUCTION_MODE_EVOLUTION:
        return False
    transition = normalized.get("state_transition") or {}
    return bool(
        str(transition.get("start_state") or "").strip()
        and str(transition.get("end_state") or "").strip()
        and normalized.get("construction_timeline")
    )


def _join(label: str, values: Any, *, max_items: int = 8) -> str:
    items = _items(values, limit=max_items)
    return f"{label}：" + "；".join(items) if items else ""


def _timeline_text(label: str, value: Any) -> str:
    if not isinstance(value, list):
        return ""
    rows = []
    for item in value:
        if not isinstance(item, dict):
            continue
        instruction = _text(item.get("instruction"), max_length=220)
        if instruction:
            rows.append(f"{item.get('from', 0)}%-{item.get('to', 100)}% {instruction}")
    return f"{label}：" + "；".join(rows) if rows else ""


def _compact_timeline(value: Any, *, limit: int = 6) -> str:
    """只保留模型真正要执行的时序动作，不重复工程表单标题。"""
    if not isinstance(value, list):
        return ""
    rows: list[str] = []
    for item in value[:limit]:
        if not isinstance(item, dict):
            continue
        instruction = _provider_text(item.get("instruction"), max_length=62)
        if not instruction:
            continue
        start = item.get("from", 0)
        end = item.get("to", 100)
        rows.append(f"[{start}-{end}%]{instruction}")
    return "；".join(rows)


def _provider_text(value: Any, *, max_length: int = 320) -> str:
    """清理只供人阅读的备注，避免把占位说明和重复标点发送给模型。"""
    text = _text(value, max_length=max_length)
    text = re.sub(r"（[^）]*(?:请替换|具体[^）]*为准|以[^）]*为准)[^）]*）", "", text)
    text = re.sub(r"\([^)]*(?:请替换|具体[^)]*为准|以[^)]*为准)[^)]*\)", "", text)
    text = re.sub(r"请替换[^；。]*", "", text)
    text = re.sub(r"[。；]{2,}", lambda match: match.group(0)[0], text)
    return text.strip(" ；。,")


def _provider_items(value: Any, *, limit: int = 8) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in _items(value, limit=limit):
        cleaned = _provider_text(item, max_length=180)
        key = re.sub(r"[\s，。；、]", "", cleaned)
        if cleaned and key and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


def _compact_section(label: str, values: list[str]) -> str:
    values = [item for item in values if item]
    return f"{label}：" + "；".join(values) if values else ""


def _fit_sections(sections: list[str], max_chars: int) -> str:
    """按工程语义优先级装入字符预算，永远只在完整分句边界取舍。"""
    selected: list[str] = []
    used = 0
    for section in sections:
        section = section.strip("。； ")
        if not section:
            continue
        separator_cost = 1 if selected else 0
        if used + separator_cost + len(section) <= max_chars:
            selected.append(section)
            used += separator_cost + len(section)
            continue

        if "：" not in section:
            continue
        label, body = section.split("：", 1)
        partial = f"{label}："
        clauses: list[str] = []
        for clause in body.split("；"):
            candidate = partial + "；".join([*clauses, clause])
            if used + separator_cost + len(candidate) > max_chars:
                break
            clauses.append(clause)
        if clauses:
            selected.append(partial + "；".join(clauses))
            used += separator_cost + len(selected[-1])
    return "。".join(selected)


def compile_construction_prompt(recipe: Any, *, max_chars: int = 520) -> str:
    """把完整 V2 配方编译成短动作指令。

    WBS、事实来源、前置条件和验收清单属于审计数据，不应逐项塞给视频模型。
    Seedance 只接收能直接影响画面的状态、顺序、镜头和少量硬约束。
    """
    normalized = normalize_construction_recipe(recipe)
    if not normalized or normalized.get("recipe_version", 1) < 2:
        return ""

    facts = normalized.get("project_facts") or {}
    unit = normalized.get("construction_unit") or {}
    transition = normalized.get("state_transition") or {}
    temporary = normalized.get("temporary_works") or {}

    work_item = _provider_text(unit.get("work_item"), max_length=90)
    zone_mappings = _provider_items(unit.get("zone_mappings"), limit=6)
    if not zone_mappings and unit.get("work_zone"):
        zone_mappings = [_provider_text(unit.get("work_zone"), max_length=150)]

    construction_timeline = _compact_timeline(normalized.get("construction_timeline"))
    camera_rows = _provider_items(
        [item.get("instruction") for item in normalized.get("camera_timeline") or [] if isinstance(item, dict)],
        limit=1,
    )
    camera_text = "；".join(camera_rows)
    anchors = _provider_items(normalized.get("spatial_anchors"), limit=6)
    anchors.extend(_provider_items(temporary.get("required"), limit=3))
    anchors = list(dict.fromkeys(anchors))[:5]

    forbidden_values = _provider_items(transition.get("forbidden_jumps"), limit=4)
    forbidden_values.extend(_provider_items(normalized.get("quality_constraints"), limit=3))
    forbidden_values = list(dict.fromkeys(forbidden_values))[:3]

    sections = [
        (
            "BIM 4D施工进度动画。首帧是唯一初态，尾帧是唯一终态；"
            "只呈现两图之间已有构件的施工变化，构件以硬边BIM显隐方式出现"
        ),
        f"任务：{work_item}" if work_item else "",
        _compact_section("分区定位", zone_mappings),
        f"严格时序：{construction_timeline}" if construction_timeline else "",
        f"镜头：{camera_text}；全程固定高位斜俯视、同一焦段和透视、连续单镜头" if camera_text else "镜头：全程固定高位斜俯视，连续单镜头",
        _compact_section("锁定不动", anchors),
        _compact_section("硬性禁止", forbidden_values),
        "视觉禁用：液体融化、蓝色遮罩、发光扫描、粒子生长、科幻特效、结构扭曲和构件闪烁",
    ]
    return _fit_sections(sections, max(360, min(620, int(max_chars))))


def construction_quality_checks(recipe: Any) -> list[dict[str, str]]:
    """生成透明的人工验收清单；不伪装成已完成的视觉识别。"""
    normalized = normalize_construction_recipe(recipe)
    if not normalized or normalized.get("recipe_version", 1) < 2:
        return []
    checks = _items(normalized.get("acceptance_checks"))
    if not checks:
        checks = [
            "构件数量、位置和已完成状态前后一致",
            "施工顺序符合前置条件，不出现跨工序跳变",
            "空间锚点、临时设施和安全防护保持连续",
            "首尾状态与目标状态一致，视频可解码且时长符合要求",
        ]
    return [{"name": item, "status": "manual_required"} for item in checks]
