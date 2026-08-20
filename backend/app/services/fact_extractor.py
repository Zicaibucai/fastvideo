"""工程参数提取服务：从解析后的文档页面提取 ExtractedFact。

- 覆盖 20 类关键工程参数
- 每个参数保存值/单位/来源文件/页码/原文/置信度/人工确认状态
- 不同文件同一参数值冲突 → 标记 conflict，不自动选择
- 无来源的参数不得作为确定事实（提取阶段只生成候选，确认后才进入正式事实）
"""

from __future__ import annotations

import re
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

# 事实类别定义（fact_name -> 元数据）
FACT_TYPES: dict[str, dict] = {
    "project_name": {"label": "项目名称", "pattern": None},
    "bidder": {"label": "招标人/建设单位", "pattern": None},
    "location": {"label": "建设地点", "pattern": None},
    "area_building": {"label": "建筑面积", "unit": "㎡"},
    "area_land": {"label": "占地面积", "unit": "㎡"},
    "height_building": {"label": "建筑高度", "unit": "m"},
    "floors": {"label": "层数", "unit": "层"},
    "structure_type": {"label": "结构形式", "pattern": None},
    "contract_amount": {"label": "合同金额/最高限价", "unit": "元"},
    "duration_total": {"label": "总工期", "unit": "日历天"},
    "date_start": {"label": "开工日期", "pattern": None},
    "date_finish": {"label": "竣工日期", "pattern": None},
    "quality_target": {"label": "质量目标", "pattern": None},
    "safety_target": {"label": "安全文明目标", "pattern": None},
    "green_target": {"label": "绿色施工目标", "pattern": None},
    "bim_requirement": {"label": "BIM要求", "pattern": None},
    "key_node_duration": {"label": "主要节点工期", "pattern": None},
    "project_features": {"label": "项目特点", "pattern": None},
    "project_difficulties": {"label": "项目重难点", "pattern": None},
    "scoring_items": {"label": "评分项及分值", "pattern": None},
}

# 正则模式
AREA_RE = re.compile(
    r"(建筑面积|总建筑面积|用地面积|占地面积|规划用地面积)[^0-9]{0,12}"
    r"([0-9][0-9,.]*)\s*(平方米|㎡|m2|m²)",
    re.IGNORECASE,
)
HEIGHT_RE = re.compile(r"(建筑高度|檐口高度|规划高度)[^0-9]{0,8}([0-9][0-9,.]*)\s*(米|m)\b", re.IGNORECASE)
FLOORS_RE = re.compile(r"(地上|地下)?\s*([0-9]{1,2})\s*层")
PERIOD_RE = re.compile(r"(总工期|计划工期|工期)[^0-9]{0,12}([0-9]{1,4})\s*(日历天|天|日)")
AMOUNT_RE = re.compile(r"(最高限价|合同金额|招标控制价|预算金额)[^0-9]{0,8}([0-9][0-9,.]{2,})\s*(万元|元|亿元)")
BIDDER_RE = re.compile(r"(招标人|建设单位|采购人)[：:]\s*([^\n\r，。；;]{2,40})")
LOCATION_RE = re.compile(r"(建设地点|工程地点|项目地址)[：:]\s*([^\n\r，。；;]{2,60})")
PROJECT_NAME_RE = re.compile(r"(项目名称|工程名称)[：:]\s*([^\n\r，。；;]{2,80})")
DATE_RE = re.compile(r"(开工日期|计划开工|竣工日期|计划竣工)[：:]\s*((?:202[0-9]|20[0-9][0-9])[年.\-/][0-9]{1,2}[月.\-/][0-9]{1,2}日?)")
QUALITY_RE = re.compile(r"(质量目标|质量标准)[：:]\s*([^\n\r，。；;]{2,40})")
SAFETY_RE = re.compile(r"(安全目标|安全文明|安全标准)[：:]\s*([^\n\r，。；;]{2,40})")
STRUCTURE_RE = re.compile(r"(结构形式|结构类型)[：:]\s*([^\n\r，。；;]{2,30})")


def _normalize_value(value: str) -> str:
    return value.replace(",", "").replace("，", "").strip()


def _extract_from_page(page_text: str) -> list[dict]:
    """从单页文本提取候选事实。返回 [{fact_name, fact_value, unit, source_quote, confidence}]"""
    results: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def add(fact_name: str, value: str, quote: str, unit: str | None = None, confidence: float = 0.7):
        value = _normalize_value(value)
        key = (fact_name, value)
        if key in seen or not value:
            return
        seen.add(key)
        results.append(
            {
                "fact_name": fact_name,
                "fact_value": value,
                "unit": unit,
                "source_quote": quote.strip(),
                "confidence": confidence,
            }
        )

    for m in AREA_RE.finditer(page_text):
        raw_val = m.group(2)
        area = float(raw_val.replace(",", ""))
        fact_name = "area_land" if "占地" in m.group(1) or "用地" in m.group(1) else "area_building"
        add(fact_name, f"{area:.0f}" if area.is_integer() else str(area), m.group(0), "㎡", 0.85)

    for m in HEIGHT_RE.finditer(page_text):
        add("height_building", m.group(2), m.group(0), "m", 0.85)

    for m in FLOORS_RE.finditer(page_text):
        add("floors", m.group(2), m.group(0), "层", 0.8)

    for m in PERIOD_RE.finditer(page_text):
        add("duration_total", m.group(2), m.group(0), "日历天", 0.85)

    for m in AMOUNT_RE.finditer(page_text):
        add("contract_amount", m.group(2), m.group(0), m.group(3), 0.85)

    for m in BIDDER_RE.finditer(page_text):
        add("bidder", m.group(2).strip(), m.group(0), None, 0.8)

    for m in LOCATION_RE.finditer(page_text):
        add("location", m.group(2).strip(), m.group(0), None, 0.8)

    for m in PROJECT_NAME_RE.finditer(page_text):
        add("project_name", m.group(2).strip(), m.group(0), None, 0.8)

    for m in DATE_RE.finditer(page_text):
        if "竣工" in m.group(1) or "完工" in m.group(1):
            add("date_finish", m.group(2), m.group(0), None, 0.85)
        else:
            add("date_start", m.group(2), m.group(0), None, 0.85)

    for m in QUALITY_RE.finditer(page_text):
        add("quality_target", m.group(2).strip(), m.group(0), None, 0.8)

    for m in SAFETY_RE.finditer(page_text):
        add("safety_target", m.group(2).strip(), m.group(0), None, 0.8)

    for m in STRUCTURE_RE.finditer(page_text):
        add("structure_type", m.group(2).strip(), m.group(0), None, 0.8)

    return results


def extract_facts_from_pages(
    pages: list[Any],
    document_id: str,
    project_id: str,
) -> list[dict]:
    """从解析后的页面提取事实。

    pages: 列表，每项需含 page_number / location_label / cleaned_text
    返回可写入 ExtractedFact 的候选记录（含冲突标记待后续处理）。
    """
    candidates: list[dict] = []
    for page in pages:
        text = getattr(page, "cleaned_text", None) or ""
        if not text:
            continue
        found = _extract_from_page(text)
        for f in found:
            candidates.append(
                {
                    "project_id": project_id,
                    "document_id": document_id,
                    "page_number": page.page_number,
                    "location_label": page.location_label,
                    "fact_type": f["fact_name"],
                    "fact_name": f["fact_name"],
                    "fact_value": f["fact_value"],
                    "unit": f["unit"],
                    "source_quote": f["source_quote"],
                    "confidence": f["confidence"],
                    "verification_status": "unverified",
                }
            )
    return candidates


def detect_conflicts(db_facts: list[Any]) -> list[str]:
    """检测同一 fact_name 下不同值的冲突，返回冲突的 fact_id 列表。

    规则：同一 fact_name 存在多个不同 fact_value 且来源不同 → conflict。
    """
    from collections import defaultdict

    groups: dict[str, list[Any]] = defaultdict(list)
    for f in db_facts:
        if f.verification_status == "rejected":
            continue
        groups[f.fact_name].append(f)

    conflict_ids: list[str] = []
    for name, items in groups.items():
        values = {f.fact_value for f in items}
        if len(values) > 1:
            for f in items:
                if f.verification_status != "confirmed":
                    conflict_ids.append(f.id)
    return conflict_ids


def apply_conflicts(db, facts: list[Any]) -> None:
    """为冲突事实设置 candidates 并标记 status。"""
    from collections import defaultdict

    groups: dict[str, list[Any]] = defaultdict(list)
    for f in facts:
        groups[f.fact_name].append(f)

    for name, items in groups.items():
        values = {f.fact_value for f in items}
        if len(values) > 1:
            for f in items:
                if f.verification_status not in ("confirmed", "rejected"):
                    f.verification_status = "conflict"
                    f.candidates = [
                        {
                            "id": other.id,
                            "document_id": other.document_id,
                            "page_number": other.page_number,
                            "fact_value": other.fact_value,
                            "source_quote": other.source_quote,
                            "confidence": other.confidence,
                        }
                        for other in items
                        if other.id != f.id
                    ]
    db.commit()


def sync_project_key_params(db, project, facts: list[Any]) -> None:
    """将已确认的事实同步到 Project 的快捷字段（含来源页码）。"""
    confirmed = {
        f.fact_name: f
        for f in facts
        if f.verification_status == "confirmed"
    }
    mapping = {
        "area_building": ("bid_area", "area_source_page"),
        "duration_total": ("construction_period", "period_source_page"),
        "bidder": ("bidder_name", "bidder_source_page"),
    }
    for fact_name, (proj_field, page_field) in mapping.items():
        fact = confirmed.get(fact_name)
        if fact:
            try:
                setattr(project, proj_field, float(fact.fact_value))
            except (ValueError, TypeError):
                setattr(project, proj_field, fact.fact_value)
            setattr(project, page_field, fact.page_number)

    db.commit()


FACT_TYPE_LABELS = {k: v["label"] for k, v in FACT_TYPES.items()}
