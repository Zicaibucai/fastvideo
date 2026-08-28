"""旁白生成的纯文本规则。

这些函数不访问数据库，也不调用模型，集中管理提示词输入的清洗、证据格式化、
镜头预算分配和安全解析，让 narration_engine 只保留流程编排与持久化。
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import ValidationError

from app.models.project import Project
from app.models.storyboard_shot import StoryboardShot
from app.services.narration_schema import EvidenceItem, OutlineOutput, SourceRef, parse_narration_output


def clean_one_line(text: str | None, limit: int = 220) -> str:
    return re.sub(r'\s+', ' ', text or '').strip()[:limit]


def predefined_outline(params: dict[str, Any]) -> str:
    outline = str(params.get('predefined_outline') or '').strip()
    return outline[:6000] or '（未提供，由AI根据证据编排）'


def target_shot_count(params: dict[str, Any]) -> int:
    return int(params.get('target_shot_count') or params.get('section_count') or 56)


def project_field_lines(project: Project | None) -> list[str]:
    if not project:
        return []
    lines = [f'- project_name: {project.name} [项目档案]']
    if project.description:
        lines.append(f'- project_description: {clean_one_line(project.description, 180)} [项目档案]')
    if project.bid_area:
        suffix = f' P{project.area_source_page}' if project.area_source_page else ''
        lines.append(f'- area_building: {project.bid_area:g}㎡ [已确认]{suffix}')
    if project.construction_period:
        suffix = f' P{project.period_source_page}' if project.period_source_page else ''
        lines.append(f'- duration_total: {project.construction_period} [已确认]{suffix}')
    if project.bidder_name:
        suffix = f' P{project.bidder_source_page}' if project.bidder_source_page else ''
        lines.append(f'- bidder_name: {project.bidder_name} [已确认]{suffix}')
    if project.tech_params:
        for name, item in list(project.tech_params.items())[:12]:
            if isinstance(item, dict):
                value = item.get('value') or item.get('fact_value') or item.get('text')
                page = item.get('page') or item.get('source_page')
                if value:
                    lines.append(f'- {name}: {value} [项目台账]{f" P{page}" if page else ""}')
    return lines


def format_ref(ref: SourceRef) -> str:
    page = f'P{ref.page}' if ref.page else 'P?'
    doc = ref.documentName or ref.documentId or '未知文档'
    quote = f' 原文: {ref.quote}' if ref.quote else ''
    return f'{doc} {page}{quote}'


def format_evidence(items: list[EvidenceItem], *, limit: int = 160) -> str:
    lines: list[str] = []
    for idx, item in enumerate(items[:limit]):
        params = '；'.join(item.parameters) if item.parameters else '无参数'
        actions = '；'.join(item.constructionActions) if item.constructionActions else '无动作'
        evidence_key = f' id:{item.evidenceId}' if item.evidenceId else ''
        lines.append(
            f'[{idx}]{evidence_key} {item.topic}｜事实：{item.fact}｜参数：{params}｜动作：{actions}｜'
            f'工序/关系：{item.sequenceContext or "无"}｜来源：{format_ref(item.sourceReference)}｜'
            f'状态：{item.factCheckStatus}'
        )
    return '\n'.join(lines)


def format_evidence_for_outline(items: list[EvidenceItem], *, max_per_topic: int = 8) -> str:
    topic_counts: dict[str, int] = {}
    selected: list[tuple[int, EvidenceItem]] = []
    for index, item in enumerate(items):
        topic = item.topic or '项目概况'
        if topic_counts.get(topic, 0) >= max_per_topic:
            continue
        topic_counts[topic] = topic_counts.get(topic, 0) + 1
        selected.append((index, item))
    lines: list[str] = []
    for index, item in selected:
        params = clean_one_line('；'.join(item.parameters), 80) or '无'
        actions = clean_one_line('；'.join(item.constructionActions), 60) or '无'
        sequence = clean_one_line(item.sequenceContext, 100) or '无'
        source = clean_one_line(format_ref(item.sourceReference), 100)
        fact = clean_one_line(item.fact, 140)
        evidence_key = f' id:{item.evidenceId}' if item.evidenceId else ''
        lines.append(f'[{index}]{evidence_key} {item.topic}｜事实：{fact}｜参数：{params}｜动作：{actions}｜工序：{sequence}｜来源：{source}')
    return '\n'.join(lines)


def format_evidence_by_indexes(items: list[EvidenceItem], indexes: list[int], evidence_ids: list[str] | None = None) -> str:
    selected: list[EvidenceItem] = []
    seen: set[int] = set()
    id_set = set(evidence_ids or [])
    if id_set:
        selected.extend(item for item in items if item.evidenceId in id_set)
    selected_keys = {item.evidenceId or str(id(item)) for item in selected}
    for idx in indexes:
        if 0 <= idx < len(items) and idx not in seen:
            candidate = items[idx]
            key = candidate.evidenceId or str(id(candidate))
            if key not in selected_keys:
                selected.append(candidate)
                selected_keys.add(key)
            seen.add(idx)
    return format_evidence(selected or items[:10], limit=80)


def guess_topic(text: str) -> str:
    topic_keywords = [
        ('工期节点', '工期|节点|进度|竣工|开工'), ('平面及垂直运输', '总平面|塔吊|施工电梯|运输|堆场|道路'),
        ('基坑土方', '基坑|土方|开挖|支护|降水'), ('钢结构', '钢结构|钢梁|钢柱|吊装|焊接'),
        ('机电', '机电|管线|暖通|给排水|电气|消防'), ('BIM', 'BIM|模型|碰撞|管综'),
        ('质量安全', '质量|安全|文明施工|创优'), ('绿色施工', '绿色|节能|环保|扬尘|噪声'),
        ('总承包管理', '总承包|协调|分包|管理'), ('总体部署', '部署|流水|穿插|施工段'),
    ]
    for topic, pattern in topic_keywords:
        if re.search(pattern, text, flags=re.I):
            return topic
    return '项目概况'


def extract_actions(text: str) -> list[str]:
    actions = re.findall(r'(开挖|支护|降水|浇筑|吊装|安装|焊接|穿插|运输|堆放|验收|调试|封闭|回填)', text)
    return list(dict.fromkeys(actions))[:6]


def allocate_shot_budgets(outline: OutlineOutput, total_shots: int) -> list[int]:
    chapters = outline.chapters
    if not chapters:
        return []
    budgets = [1 for _ in chapters]
    remaining = max(0, total_shots - len(chapters))
    total_duration = sum(float(c.durationSeconds or 0) for c in chapters) or len(chapters)
    raw = [remaining * (float(c.durationSeconds or 0) / total_duration) for c in chapters]
    for idx, value in sorted(enumerate(raw), key=lambda pair: pair[1], reverse=True):
        add = int(value)
        budgets[idx] += add
        remaining -= add
    idx = 0
    while remaining > 0:
        budgets[idx % len(budgets)] += 1
        remaining -= 1
        idx += 1
    return budgets


def project_summary(context: dict) -> str:
    project = context.get('project')
    return f'{project.name}施工组织推演型投标视频。' if project and project.name else '施工组织推演型投标视频。'


def split_narration_beats(text: str) -> list[str]:
    parts = [part.strip() for part in re.split(r'(?<=[。！？；;])', text or '') if part.strip()]
    return parts or ([text.strip()] if text and text.strip() else [])


def resegment_identity(text: str) -> str:
    return re.sub(r'[\s，。！？；：、“”‘’（）()【】《》,.!?;:…\-—_]+', '', text or '')


def infer_source_sequences(text: str, shots: list[StoryboardShot], cursor: int) -> tuple[list[int], int]:
    combined = ''.join(resegment_identity(shot.narration or '') for shot in shots)
    target = resegment_identity(text)
    if not target:
        return [], cursor
    start = combined.find(target, cursor)
    if start < 0:
        raise ValueError('AI 重新分镜没有保留原正文，未应用本次调整')
    end = start + len(target)
    ranges: list[int] = []
    offset = 0
    for shot in shots:
        next_offset = offset + len(resegment_identity(shot.narration or ''))
        if start < next_offset and end > offset:
            ranges.append(shot.sequence)
        offset = next_offset
    return ranges, end


def safe_extract_narration(raw: str) -> str:
    try:
        parsed = parse_narration_output(raw)
        if parsed.shots:
            return parsed.shots[0].narration
    except (ValueError, ValidationError):
        pass
    text = raw.strip().strip('"').strip("'")[:500]
    return text or '解说词生成失败'
