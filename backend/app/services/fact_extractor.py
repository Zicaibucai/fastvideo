"""工程信息提取服务：从解析后的文档页面提取候选事实。

- 规则层尽可能保留数字、型号、尺寸和参数上下文，不因为暂时无法命名而丢弃
- 已知参数使用规则高置信度识别，未知数字保留为低置信度候选，等待 AI 整理
- 每条候选保存完整句子或表格行，避免只留下“建筑面积”这类残缺引用
- 不同文件同一参数值冲突 → 标记 conflict，不自动选择
- 无来源的参数不得作为确定事实（提取阶段只生成候选，确认后才进入正式事实）
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

# 事实类别定义（fact_name -> 元数据）
FACT_TYPES: dict[str, dict] = {
    "project_name": {"label": "项目名称", "pattern": None},
    "bidder": {"label": "招标人/建设单位", "pattern": None},
    "location": {"label": "建设地点", "pattern": None},
    "area_building": {"label": "建筑面积", "unit": "㎡"},
    "area_building_above": {"label": "地上建筑面积", "unit": "㎡"},
    "area_building_below": {"label": "地下建筑面积", "unit": "㎡"},
    "area_building_main_above": {"label": "主楼地上建筑面积", "unit": "㎡"},
    "area_building_podium_above": {"label": "裙房地上建筑面积", "unit": "㎡"},
    "area_civil_defense": {"label": "人防建筑面积", "unit": "㎡"},
    "numeric_candidate": {"label": "待识别数字", "unit": None},
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
    r"(规划用地面积|总用地面积|用地面积|占地面积|总建筑面积|地上建筑面积|"
    r"地下室?建筑面积|人防建筑面积|民防建筑面积|建筑面积)[^0-9]{0,12}"
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

# 全量数字证据。先覆盖工程型号和带单位表达式，再覆盖裸数字，避免只保存
# 预先写死的 20 类参数。裸数字置信度较低，会排在台账末尾且默认不参与正式输出。
NUMERIC_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:"
    r"(?:20\d{2}[年./-]\d{1,2}[月./-]\d{1,2}日?)|"
    r"(?:(?:HRBF?|HPB|C|P|Q|M|Φ)\s*\d[A-Za-z0-9Φφ×xX*/.~～至\-]*|"
    r"[A-Z]{2,}[A-Za-z0-9Φφ×xX*/.~～至\-]*\d[A-Za-z0-9Φφ×xX*/.~～至\-]*)|"
    r"(?:Φ\s*\d+(?:\.\d+)?)|"
    r"(?:[-+]?\d[\d,]*(?:\.\d+)?(?:\s*[~～至\-]\s*(?:[A-Za-zΦφ])?\d[\d,]*(?:\.\d+)?)?"
    r"\s*(?:平方米|㎡|m²|m2|mm|cm|km|m|米|毫米|厘米|千米|立方米|m³|m3|万元|亿元|元|吨|kg|千克|个|台|套|根|块|层|级|度|天|日历天|日|%|％|号)?))",
    re.IGNORECASE,
)

AUTO_USE_THRESHOLD = 0.80
REVIEW_THRESHOLD = 0.60
# 让一次请求携带更多候选，减少 6000+ 数值候选时的请求次数；多个批次由
# Celery worker 内的轻量线程并行发送，避免把整个文档解析拖成几个小时。
AI_ENRICHMENT_BATCH_SIZE = 60
AI_ENRICHMENT_WORKERS = 4

_AI_NUMERIC_FACT_NAMES = {
    "numeric_candidate", "area_land", "area_building", "area_building_above", "area_building_below",
    "area_building_main_above", "area_building_podium_above", "area_civil_defense", "height_building",
    "floors", "duration_total", "contract_amount",
}
_VALID_UNITS = {
    "㎡", "平方米", "m²", "m2", "m", "米", "mm", "毫米", "cm", "厘米", "km", "千米",
    "m³", "m3", "立方米", "万元", "亿元", "元", "吨", "kg", "千克", "个", "台", "套",
    "根", "块", "层", "级", "度", "天", "日历天", "日", "%", "％", "号",
}
_WEIGHT_LABELS = {"重量", "吊重", "额定吊重", "起吊重量", "荷载", "承载力", "质量"}
_DISTANCE_LABELS = {"半径", "直径", "长度", "宽度", "厚度", "深度", "高度", "标高", "尺寸", "距离", "间距"}
_IDENTIFIER_LABELS = (
    "文件编号", "项目编号", "招标编号", "合同编号", "序号", "编号", "序列号", "条款号", "章节号",
    "页码", "行号", "图号", "表号", "清单号", "文号", "档号", "流水号", "编号码", "孔号", "线号",
    "楼号", "层号", "区号", "分区", "区段", "施工分区", "地块编号", "幢号",
)
_LOW_PRIORITY_LABELS = (
    "年龄", "出生月份", "毕业时间", "从事本专业时间", "为候选供应方工作时间", "工作年限", "联系电话",
    "门牌号", "火警电话", "报警电话", "消防报警电话", "救护电话", "软件名称", "软件版本", "软件数量",
    "月份", "年份", "建造年份", "标准年份", "规范年份", "规范版本年份", "BIM工作站建立年份", "获奖数量",
    "获奖年度", "BIM大赛一等奖数量", "世界500强排名", "排名", "东盟成员国数量", "G20成员国数量",
    "城市数量", "参与数量", "承建数量", "专业分包工程数量", "独立专项工程数量", "考察项目数量",
    "培训次数",
)
_CANONICAL_CATEGORIES = {
    "尺寸/标高/深度", "工期/日期", "工程参数", "工程范围/场地", "施工参数",
    "材料与设备", "混凝土/材料等级", "编号/规格", "面积/工程量", "其他参数",
}

_PARAMETER_LABELS = (
    "总建筑面积", "建筑面积", "占地面积", "用地面积", "建筑高度", "高度", "厚度", "长度", "宽度",
    "直径", "半径", "截面", "尺寸", "施工尺寸", "板厚", "管径", "标高", "埋深",
    "强度等级", "抗渗等级", "耐火等级", "抗震烈度", "层数", "工期", "日期",
    "数量", "规格", "型号", "编号", "材质", "材料", "等级", "面积", "金额", "分值", "温度", "压力",
    "重量", "吊重", "额定吊重", "起吊重量", "荷载", "承载力", "功率", "流量", "速度", "间距", "距离",
)
_SCOPE_LABELS = ("主楼", "塔楼", "裙房", "群房", "地下室", "地下", "基坑", "人防区", "人防工程", "本项目", "本工程")


def _normalize_value(value: str) -> str:
    return value.replace(",", "").replace("，", "").strip()


def _source_context(text: str, start: int, end: int, *, limit: int = 2000) -> str:
    """返回命中项所在的完整句子或表格行。"""
    left = start
    while left > 0 and text[left - 1] not in "\n。！？；;!?":
        left -= 1
    right = end
    while right < len(text) and text[right] not in "\n。！？；;!?":
        right += 1
    if right < len(text) and text[right] in "。！？；;!?":
        right += 1
    quote = re.sub(r"[ \t]+", " ", text[left:right].strip().strip("|").strip())
    if len(quote) <= limit:
        return quote
    relative_start = start - left
    window_start = max(0, relative_start - limit // 2)
    window_end = min(len(quote), window_start + limit)
    window_start = max(0, window_end - limit)
    return f"{'…' if window_start else ''}{quote[window_start:window_end].strip()}{'…' if window_end < len(quote) else ''}"


def _area_fact_name(label: str, context: str) -> str:
    """按面积工程含义分类，避免把总量、分项和单体面积误判为冲突。"""
    compact_label = re.sub(r"\s+", "", label)
    compact_context = re.sub(r"\s+", "", context)
    if "占地" in compact_label or "用地" in compact_label:
        return "area_land"
    if "人防" in compact_label or "民防" in compact_label:
        return "area_civil_defense"
    if "地下" in compact_label:
        return "area_building_below"
    if "地上" in compact_label:
        if "主楼" in compact_context or "塔楼" in compact_context:
            return "area_building_main_above"
        if "裙房" in compact_context or "群房" in compact_context:
            return "area_building_podium_above"
        return "area_building_above"
    if "总建筑面积" in compact_label:
        return "area_building"
    if "民防" in compact_context or "人防" in compact_context:
        return "area_civil_defense"
    if "地下室" in compact_context:
        return "area_building_below"
    if "主楼" in compact_context or "塔楼" in compact_context:
        return "area_building_main_above"
    if "裙房" in compact_context or "群房" in compact_context:
        return "area_building_podium_above"
    return "area_building"


def _nearby_label(text: str, start: int) -> tuple[str | None, str | None]:
    """从当前句子中找到与数字直接相邻的参数名和对象范围。

    参数名之间如果已经出现了另一个数字，就不能继续把更早的词
    绑定到当前数字。例如“起吊半径35m，额定吊重16.56吨”中，
    16.56 必须归到“额定吊重”，不能沿用“半径”。
    """
    boundary = max(text.rfind(mark, 0, start) for mark in "\n。！？；;!?")
    prefix = text[boundary + 1 : start]
    label_candidates: list[tuple[int, int, str]] = []
    for candidate in _PARAMETER_LABELS:
        position = prefix.rfind(candidate)
        if position < 0:
            continue
        after_label = prefix[position + len(candidate) :]
        # 另一个数字已经把前面的参数和当前数字隔开，不能跨数字继承。
        if re.search(r"\d", after_label):
            continue
        distance = len(after_label)
        if distance <= 28:
            label_candidates.append((distance, -len(candidate), candidate))
    label = min(label_candidates, default=(0, 0, None))[2]
    scope = max(
        (scope for scope in _SCOPE_LABELS if scope in prefix),
        key=lambda item: prefix.rfind(item),
        default=None,
    )
    return label, scope


def _scope_from_context(context: str) -> str | None:
    compact = re.sub(r"\s+", "", context)
    for scope in ("主楼", "塔楼", "裙房", "群房", "地下室", "人防区", "人防工程", "基坑"):
        if scope in compact:
            return scope
    # “地下建筑面积”“本项目”等是参数语境，不是单体对象范围，避免在台账中
    # 把整句里的泛化词误显示成“范围：地下”。
    return None


def _split_numeric_token(token: str) -> tuple[str, str | None]:
    unit_match = re.search(
        r"\s*(平方米|㎡|m²|m2|mm|cm|km|m|米|毫米|厘米|千米|立方米|m³|m3|万元|亿元|元|吨|kg|千克|个|台|套|根|块|层|级|度|天|日历天|日|%|％|号)\s*$",
        token,
        re.IGNORECASE,
    )
    if not unit_match:
        return token.strip(), None
    return token[: unit_match.start()].strip(), unit_match.group(1)


def _generic_numeric_metadata(page_text: str, match: re.Match[str], token: str, context: str) -> dict:
    label, scope = _nearby_label(page_text, match.start())
    value, unit = _split_numeric_token(token)
    has_unit = bool(unit)
    has_identifier = bool(re.match(r"(?:[A-Za-zΦφ]|HRBF?|HPB|C|P|Q|M)\s*\d", value, re.IGNORECASE))
    has_range = bool(re.search(r"[~～至\-]", value))
    is_concrete_code = bool(re.fullmatch(r"C\d+(?:\s*[~～至]\s*C\d+)?", value, re.IGNORECASE))
    if is_concrete_code and label in {None, "材料/型号"}:
        label = "混凝土强度等级"
    if not label and unit in {"层", "级"}:
        label = "层数" if unit == "层" else "等级"
    confidence = 0.35
    if label:
        confidence += 0.24
    if has_unit:
        confidence += 0.16
    if has_identifier or has_range:
        confidence += 0.12
    if scope:
        confidence += 0.05
    if len(context) >= 25:
        confidence += 0.05
    confidence = min(0.95, round(confidence, 2))
    if label:
        display_name = label
        if label == "混凝土强度等级":
            category = "材料等级"
        elif label in {"材料", "材质", "型号", "规格"}:
            category = "材料与设备"
        elif label in _WEIGHT_LABELS:
            category = "工程量"
        else:
            category = "工程参数"
    elif has_identifier:
        display_name = "材料/型号"
        category = "材料与设备"
    else:
        display_name = "待识别数字"
        category = "待分类"
    return {
        "fact_value": value or token,
        "unit": unit,
        "confidence": confidence,
        "display_name": display_name,
        "scope": scope,
        "category": category,
        "auto_usable": bool(label and confidence >= AUTO_USE_THRESHOLD),
        "extraction_method": "rule_numeric_scan",
        "numeric_token": token,
        "ai_status": "pending",
    }


def _extract_from_page(page_text: str) -> list[dict]:
    """从单页文本提取已知事实和全量数字候选。"""
    results: list[dict] = []
    seen: set[tuple[str, str]] = set()
    known_spans: list[tuple[int, int]] = []

    def add(
        fact_name: str,
        value: str,
        quote: str,
        unit: str | None = None,
        confidence: float = 0.7,
        *,
        span: tuple[int, int] | None = None,
        metadata: dict | None = None,
    ):
        value = _normalize_value(value)
        key = (fact_name, value)
        if key in seen or not value:
            return
        seen.add(key)
        if span:
            known_spans.append(span)
        metadata = {
            "display_name": FACT_TYPES.get(fact_name, {}).get("label", "工程信息"),
            "scope": _scope_from_context(quote),
            "category": "工程参数",
            "extraction_method": "rule_keyword",
            "auto_usable": confidence >= AUTO_USE_THRESHOLD,
            "ai_status": "not_needed",
            **(metadata or {}),
        }
        results.append(
            {
                "fact_name": fact_name,
                "fact_value": value,
                "unit": unit,
                "source_quote": quote.strip(),
                "confidence": confidence,
                "metadata_json": metadata,
                "source_start": span[0] if span else 0,
            }
        )

    for m in AREA_RE.finditer(page_text):
        raw_val = m.group(2)
        # 保留原文的小数位（例如 21008.0），只去掉千位分隔符。
        area_value = _normalize_value(raw_val)
        context = _source_context(page_text, m.start(), m.end())
        fact_name = _area_fact_name(m.group(1), context)
        # 保留原文中的具体面积名称；不能把“总建筑面积”压缩成泛化的“建筑面积”。
        area_label = re.sub(r"\s+", "", m.group(1))
        add(
            fact_name,
            area_value,
            context,
            "㎡",
            0.85,
            span=m.span(),
            metadata={"display_name": area_label or FACT_TYPES[fact_name]["label"]},
        )

    for m in HEIGHT_RE.finditer(page_text):
        add("height_building", m.group(2), _source_context(page_text, m.start(), m.end()), "m", 0.85, span=m.span())

    for m in FLOORS_RE.finditer(page_text):
        add(
            "floors",
            m.group(2),
            _source_context(page_text, m.start(), m.end()),
            "层",
            0.8,
            span=m.span(),
            metadata={"scope": m.group(1) or None},
        )

    for m in PERIOD_RE.finditer(page_text):
        add("duration_total", m.group(2), _source_context(page_text, m.start(), m.end()), "日历天", 0.85, span=m.span())

    for m in AMOUNT_RE.finditer(page_text):
        add("contract_amount", m.group(2), _source_context(page_text, m.start(), m.end()), m.group(3), 0.85, span=m.span())

    for m in BIDDER_RE.finditer(page_text):
        add("bidder", m.group(2).strip(), _source_context(page_text, m.start(), m.end()), None, 0.8, span=m.span())

    for m in LOCATION_RE.finditer(page_text):
        add("location", m.group(2).strip(), _source_context(page_text, m.start(), m.end()), None, 0.8, span=m.span())

    for m in PROJECT_NAME_RE.finditer(page_text):
        add("project_name", m.group(2).strip(), _source_context(page_text, m.start(), m.end()), None, 0.8, span=m.span())

    for m in DATE_RE.finditer(page_text):
        if "竣工" in m.group(1) or "完工" in m.group(1):
            add("date_finish", m.group(2), _source_context(page_text, m.start(), m.end()), None, 0.85, span=m.span())
        else:
            add("date_start", m.group(2), _source_context(page_text, m.start(), m.end()), None, 0.85, span=m.span())

    for m in QUALITY_RE.finditer(page_text):
        add("quality_target", m.group(2).strip(), _source_context(page_text, m.start(), m.end()), None, 0.8, span=m.span())

    for m in SAFETY_RE.finditer(page_text):
        add("safety_target", m.group(2).strip(), _source_context(page_text, m.start(), m.end()), None, 0.8, span=m.span())

    for m in STRUCTURE_RE.finditer(page_text):
        add("structure_type", m.group(2).strip(), _source_context(page_text, m.start(), m.end()), None, 0.8, span=m.span())

    for m in NUMERIC_TOKEN_RE.finditer(page_text):
        if any(m.start() < end and m.end() > start for start, end in known_spans):
            continue
        token = m.group(0).strip()
        context = _source_context(page_text, m.start(), m.end())
        metadata = _generic_numeric_metadata(page_text, m, token, context)
        add(
            "numeric_candidate",
            metadata["fact_value"],
            context,
            metadata["unit"],
            metadata["confidence"],
            span=m.span(),
            metadata=metadata,
        )

    results.sort(key=lambda item: item.get("source_start", 0))

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
    source_order = 0
    for page in pages:
        text = getattr(page, "cleaned_text", None) or ""
        if not text:
            continue
        found = _extract_from_page(text)
        for f in found:
            source_order += 1
            metadata = dict(f.get("metadata_json") or {})
            metadata["source_order"] = source_order
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
                    "metadata_json": metadata,
                    "verification_status": "unverified",
                }
            )
    return candidates


def _json_from_text(raw: str) -> list[dict]:
    """兼容模型返回 Markdown 包裹 JSON 的情况。"""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE | re.DOTALL).strip()
    try:
        value = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        match = re.search(r"\[.*\]", text, flags=re.DOTALL)
        if not match:
            return []
        try:
            value = json.loads(match.group(0))
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
    return value if isinstance(value, list) else []


def _is_ai_numeric_candidate(candidate: dict) -> bool:
    metadata = candidate.get("metadata_json") or {}
    return (
        candidate.get("fact_type") in _AI_NUMERIC_FACT_NAMES
        or candidate.get("fact_name") in _AI_NUMERIC_FACT_NAMES
        or bool(metadata.get("numeric_token"))
    )


def _clean_ai_unit(value: object, candidate: dict) -> str | None:
    """单位以原文扫描结果为准；原文无单位时只接受模型返回的标准单位。"""
    original = str(candidate.get("unit") or "").strip()
    if original:
        return original
    unit = str(value or "").strip()
    return unit if unit in _VALID_UNITS else None


def _unit_name_compatible(name: str, unit: str | None) -> bool:
    if not name or not unit:
        return True
    if any(term in name for term in _WEIGHT_LABELS):
        return unit not in {"m", "米", "mm", "毫米", "cm", "厘米", "km", "千米", "㎡", "平方米", "m²", "m2"}
    if any(term in name for term in _DISTANCE_LABELS):
        return unit not in {"吨", "kg", "千克", "元", "万元", "亿元"}
    return True


def _is_identifier_label(name: object) -> bool:
    """标记文件/条款/序号等标识，不让它们进入解说词事实池。"""
    compact = re.sub(r"\s+", "", str(name or ""))
    if not compact or compact in {"材料/型号", "型号", "规格型号"}:
        return False
    return any(label in compact for label in _IDENTIFIER_LABELS)


def _downgrade_identifier_candidate(candidate: dict) -> bool:
    metadata = candidate.setdefault("metadata_json", {})
    name = metadata.get("display_name") or candidate.get("fact_name")
    if not _is_identifier_label(name):
        return False
    confidence = min(float(candidate.get("confidence") or 0.35), REVIEW_THRESHOLD - 0.01)
    candidate["confidence"] = round(confidence, 2)
    metadata.update(
        {
            "confidence": round(confidence, 2),
            "auto_usable": False,
            "identifier_only": True,
            "ai_status": "identifier_low_confidence",
        }
    )
    return True


def _is_low_priority_label(name: object) -> bool:
    compact = re.sub(r"\s+", "", str(name or ""))
    return bool(compact) and any(label in compact for label in _LOW_PRIORITY_LABELS)


def _downgrade_low_priority_candidate(candidate: dict) -> bool:
    metadata = candidate.setdefault("metadata_json", {})
    name = metadata.get("display_name") or candidate.get("fact_name")
    if not _is_low_priority_label(name):
        return False
    confidence = min(float(candidate.get("confidence") or 0.35), REVIEW_THRESHOLD - 0.01)
    candidate["confidence"] = round(confidence, 2)
    metadata.update(
        {
            "confidence": round(confidence, 2),
            "auto_usable": False,
            "low_priority": True,
            "ai_status": "low_priority",
        }
    )
    return True


def _normalize_ai_category(name: str, unit: str | None, raw_category: object, fallback: object = None) -> str:
    """把 AI 类别收敛到台账枚举，并用参数名/单位纠正明显的语义错配。"""
    compact_name = re.sub(r"\s+", "", name or "")
    raw = str(raw_category or fallback or "").strip()
    if any(term in compact_name for term in _DISTANCE_LABELS):
        return "尺寸/标高/深度"
    if any(term in compact_name for term in _WEIGHT_LABELS) or unit in {"吨", "kg", "千克"}:
        return "面积/工程量"
    if "混凝土" in compact_name or "抗渗" in compact_name or "强度等级" in compact_name:
        return "混凝土/材料等级"
    if raw in _CANONICAL_CATEGORIES:
        return raw
    # 兼容模型偶尔返回的细分类别，统一到前端可筛选的十个大类。
    if raw in {"材料等级", "材料参数", "材料规格", "材料性能", "设备型号", "设备参数", "机械设备", "机电配置"}:
        return "材料与设备"
    if raw in {"面积", "工程量", "数量", "重量", "体积", "金额", "分值"}:
        return "面积/工程量"
    if raw in {"几何尺寸", "尺寸", "直径", "长度", "宽度", "高度", "厚度", "距离", "间距", "角度", "深度", "基坑参数"}:
        return "尺寸/标高/深度"
    if raw in {"日期", "时间", "工期", "工期参数", "进度参数", "进度计划"}:
        return "工期/日期"
    if raw in {"编号", "名称", "规格", "型号"}:
        return "编号/规格"
    return "其他参数"


def enrich_numeric_candidates_with_ai(candidates: list[dict]) -> list[dict]:
    """把每个数值候选连同目标数字、原始单位和完整上下文交给 AI 整理。"""
    from app.services.ai_configuration import refresh_runtime_config_from_db

    refresh_runtime_config_from_db()
    pending = [candidate for candidate in candidates if _is_ai_numeric_candidate(candidate)]
    if not pending:
        return candidates

    try:
        from app.adapters.factory import get_llm_adapter

        adapter = get_llm_adapter("fact_extraction")
    except Exception:
        return candidates

    # Mock 模式不伪装成 AI 已经理解过，只把规则层结果标为完成。
    if getattr(adapter, "provider", "") == "mock" or not adapter.is_available():
        for candidate in pending:
            metadata = candidate.setdefault("metadata_json", {})
            metadata["ai_status"] = "heuristic"
            _downgrade_identifier_candidate(candidate)
            _downgrade_low_priority_candidate(candidate)
        return candidates

    batches = [
        pending[start : start + AI_ENRICHMENT_BATCH_SIZE]
        for start in range(0, len(pending), AI_ENRICHMENT_BATCH_SIZE)
    ]

    def call_batch(batch: list[dict]) -> dict[int, dict]:
        payload = [
            {
                "id": index,
                "target_number": (item.get("metadata_json") or {}).get("numeric_token") or item.get("fact_value", ""),
                "original_unit": item.get("unit"),
                "context": (item.get("source_quote") or "")[:1800],
            }
            for index, item in enumerate(batch)
        ]
        prompt = (
            "你是工程资料参数整理器。每条候选都必须只根据自己的原文上下文和目标数字判断。\n"
            "请返回参数名称、适用对象、参数类别、单位和置信度；不要把同一句中另一个数字前面的参数名套给当前目标数字。\n"
            "原文没有明确对象或单位时，分别返回 null；不能补写原文不存在的含义。\n"
            "如果 original_unit 不为空，unit 必须原样返回。输出 JSON 数组，每项包含 id、parameter_name、object_scope、category、unit、confidence。\n"
            "参数类别只能从：尺寸/标高/深度、工期/日期、工程参数、工程范围/场地、"
            "施工参数、材料与设备、混凝土/材料等级、编号/规格、面积/工程量、其他参数中选择。\n"
            f"候选：{json.dumps(payload, ensure_ascii=False)}"
        )
        try:
            raw = adapter.complete(prompt, temperature=0, max_tokens=6000)
            enriched = _json_from_text(raw)
        except Exception as exc:  # pragma: no cover - 真实服务故障时走规则降级
            logger.warning("fact_ai_enrichment_failed", error=str(exc))
            enriched = []
        return {
            int(row.get("id")): row
            for row in enriched
            if isinstance(row, dict) and str(row.get("id", "")).isdigit()
        }

    def apply_batch(batch: list[dict], by_id: dict[int, dict]) -> None:
        for index, candidate in enumerate(batch):
            metadata = candidate.setdefault("metadata_json", {})
            row = by_id.get(index)
            if not row:
                # AI 未返回时不把规则猜测标成高置信度，避免“半径+吨”这类组合直接可用。
                candidate["confidence"] = min(float(candidate.get("confidence") or 0.35), REVIEW_THRESHOLD - 0.01)
                metadata.update({"auto_usable": False, "ai_status": "fallback"})
                _downgrade_identifier_candidate(candidate)
                _downgrade_low_priority_candidate(candidate)
                continue
            rule_name = str(metadata.get("display_name") or "待识别数字").strip()
            name = str(row.get("parameter_name") or rule_name or "待识别数字").strip()[:80]
            unit = _clean_ai_unit(row.get("unit"), candidate)
            if not candidate.get("unit") and unit:
                candidate["unit"] = unit
            valid_semantics = name not in {"", "待识别数字"} and _unit_name_compatible(name, unit)
            if not valid_semantics:
                name = rule_name if rule_name and rule_name != "待识别数字" and _unit_name_compatible(rule_name, unit) else "待识别数字"
            ai_confidence = row.get("confidence")
            try:
                ai_confidence = max(0.05, min(0.99, float(ai_confidence)))
            except (TypeError, ValueError):
                ai_confidence = float(candidate.get("confidence") or 0.35)
            rule_confidence = float(candidate.get("confidence") or 0.35)
            confidence = round(rule_confidence * 0.35 + ai_confidence * 0.65, 2)
            if not valid_semantics or name == "待识别数字":
                confidence = min(confidence, REVIEW_THRESHOLD - 0.01)
            is_identifier = _is_identifier_label(name)
            if is_identifier:
                confidence = min(confidence, REVIEW_THRESHOLD - 0.01)
            is_low_priority = _is_low_priority_label(name)
            if is_low_priority:
                confidence = min(confidence, REVIEW_THRESHOLD - 0.01)
            candidate["confidence"] = confidence
            object_scope = str(row.get("object_scope") or row.get("scope") or "").strip()[:80] or None
            category = _normalize_ai_category(
                name,
                unit,
                row.get("category"),
                metadata.get("category"),
            )
            metadata.update(
                {
                    "display_name": name,
                    "scope": object_scope,
                    "category": category,
                    "unit": unit,
                    "confidence": confidence,
                    "auto_usable": bool(
                        valid_semantics
                        and not is_identifier
                        and not is_low_priority
                        and name != "待识别数字"
                        and confidence >= AUTO_USE_THRESHOLD
                    ),
                    "identifier_only": is_identifier,
                    "low_priority": is_low_priority,
                    "ai_status": (
                        "identifier_low_confidence"
                        if is_identifier
                        else (
                            "low_priority"
                            if is_low_priority
                            else ("enriched" if valid_semantics else "validated_fallback")
                        )
                    ),
                }
            )

    # 每个批次互相独立，适合在单个 Celery worker 内并行请求；候选写回仍在
    # 当前线程完成，保证输入列表顺序和数据库写入顺序不变。
    workers = min(AI_ENRICHMENT_WORKERS, len(batches))
    if workers <= 1:
        for batch in batches:
            apply_batch(batch, call_batch(batch))
    else:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="fact-ai") as executor:
            futures = {executor.submit(call_batch, batch): batch for batch in batches}
            for future in as_completed(futures):
                batch = futures[future]
                try:
                    result = future.result()
                except Exception as exc:  # pragma: no cover - 防止单批次中断整篇解析
                    logger.warning("fact_ai_batch_failed", error=str(exc))
                    result = {}
                apply_batch(batch, result)
    return candidates


def _fact_conflict_key(fact: Any) -> tuple[str, str]:
    """同一参数在不同对象范围内可以并存，例如塔楼/裙房高度、地上/地下层数。"""
    metadata = getattr(fact, "metadata_json", None) or {}
    scope = str(metadata.get("scope") or "").strip()
    return str(getattr(fact, "fact_name", "")), scope


def detect_conflicts(db_facts: list[Any]) -> list[str]:
    """检测同一 fact_name 下不同值的冲突，返回冲突的 fact_id 列表。

    规则：同一 fact_name 存在多个不同 fact_value 且来源不同 → conflict。
    """
    from collections import defaultdict

    groups: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for f in db_facts:
        # 全量数字候选还没有稳定的参数身份，不能把所有裸数字互相判成冲突。
        if f.verification_status == "rejected" or f.fact_type == "numeric_candidate":
            continue
        groups[_fact_conflict_key(f)].append(f)

    conflict_ids: list[str] = []
    for _key, items in groups.items():
        values = {f.fact_value for f in items}
        if len(values) > 1:
            for f in items:
                if f.verification_status != "confirmed":
                    conflict_ids.append(f.id)
    return conflict_ids


def apply_conflicts(db, facts: list[Any]) -> None:
    """为冲突事实设置 candidates 并标记 status。"""
    from collections import defaultdict

    groups: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for f in facts:
        if f.fact_type == "numeric_candidate":
            continue
        groups[_fact_conflict_key(f)].append(f)

    for _key, items in groups.items():
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
                            "unit": other.unit,
                            "scope": (other.metadata_json or {}).get("scope"),
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
