"""解说词智能拆解引擎。

- 从已确认事实（ExtractedFact）与评分点（ScoringPoint）构建上下文
- 调用 LLMAdapter（不直接写在路由中）
- 使用 Pydantic 严格校验 LLM 输出结构
- 生成 10+ 分镜，每个分镜含来源引用、评分点覆盖、事实校验状态
- 无来源信息不得作为确定事实写入正式解说词（未验证项放入 unverifiedFacts）
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from pydantic import ValidationError

from app.adapters.factory import get_llm_adapter
from app.core.database import SessionLocal
from app.core.logging import get_logger
from app.models.base import utc_now_iso
from app.models.extracted_fact import ExtractedFact
from app.models.document_chunk import DocumentChunk
from app.models.document_page import DocumentPage
from app.models.project import Project
from app.models.scoring_point import ScoringPoint
from app.models.narration_beat import NarrationBeat
from app.models.narration_run import NarrationEvidence, NarrationRun
from app.models.render_task import RenderTask
from app.models.storyboard_shot import StoryboardShot
from app.services.narration_text import (
    allocate_shot_budgets as _allocate_shot_budgets,
    clean_one_line as _clean_one_line,
    extract_actions as _extract_actions,
    format_evidence as _format_evidence,
    format_evidence_by_indexes as _format_evidence_by_indexes,
    format_evidence_for_outline as _format_evidence_for_outline,
    format_ref as _format_ref,
    guess_topic as _guess_topic,
    infer_source_sequences as _infer_source_sequences,
    predefined_outline as _predefined_outline,
    project_field_lines as _project_field_lines,
    project_summary as _project_summary,
    resegment_identity as _resegment_identity,
    safe_extract_narration as _safe_extract_narration,
    split_narration_beats as _split_narration_beats,
    target_shot_count as _target_shot_count,
)

from app.services.narration_resegment import resegment_storyboard as _resegment_storyboard_impl

from app.services.narration_schema import (
    ChapterDraftOutput,
    EvidenceItem,
    EvidenceOutput,
    FactCheckStatus,
    NarrationOutput,
    OutlineChapter,
    OutlineOutput,
    QAReviewOutput,
    ResegmentOutput,
    ResegmentShot,
    ShotOut,
    SourceRef,
    _evidence_output_from_rows,
    _extract_json,
    _source_ref_from_row,
    parse_chapter_draft_output,
    parse_evidence_output,
    parse_narration_output,
    parse_outline_output,
    parse_qa_review_output,
    parse_resegment_output,
)

logger = get_logger(__name__)


# ============================================================
# 严格 Schema（Pydantic 校验）
# ============================================================



def _complete_structured(adapter, prompt: str, parser, *, stage: str, max_tokens: int, temperature: float = 0):
    """调用结构化阶段，失败时用更大输出预算和明确修正指令重试。"""
    retry_suffix = (
        "\n\n【输出修正】上一轮未返回可解析结果。请现在只输出一个完整、合法的 JSON 对象，"
        "不要输出分析过程、Markdown 代码块或任何 JSON 之外的文字。"
    )
    last_error: Exception | None = None
    retry_max_tokens = min(8000, max(max_tokens + 1500, max_tokens * 2))
    attempts = ((prompt, max_tokens), (prompt + retry_suffix, retry_max_tokens))
    for attempt, (current_prompt, current_max_tokens) in enumerate(attempts, start=1):
        raw = adapter.complete(
            current_prompt,
            temperature=temperature,
            max_tokens=current_max_tokens,
            response_format={"type": "json_object"},
        )
        try:
            return parser(raw)
        except Exception as exc:
            last_error = exc
            logger.warning(
                "llm_structured_output_invalid",
                stage=stage,
                attempt=attempt,
                response_length=len(raw or ""),
                response_preview=(raw or "")[:160],
                error=str(exc),
            )
    raise ValueError(f"{stage}阶段连续两次未返回可解析 JSON：{last_error}") from last_error


# ============================================================
# 上下文构建
# ============================================================

def _build_context(
    db,
    project_id: str,
    *,
    evidence_run_id: str | None = None,
    evidence_auto_approve: bool = True,
) -> dict:
    """收集已确认事实与评分点，构建 LLM 上下文。"""
    project = db.get(Project, project_id)
    facts = (
        db.query(ExtractedFact)
        .filter(ExtractedFact.project_id == project_id)
        .order_by(ExtractedFact.verification_status.asc(), ExtractedFact.created_at.asc())
        .all()
    )
    scoring_points = (
        db.query(ScoringPoint)
        .filter(ScoringPoint.project_id == project_id)
        .all()
    )

    from app.services.fact_extractor import REVIEW_THRESHOLD
    from app.services.fact_extractor import AUTO_USE_THRESHOLD

    confirmed_facts = [f for f in facts if f.verification_status == "confirmed"]
    sourced_facts = [
        f for f in facts
        if (
            f.verification_status == "unverified"
            and f.source_quote
            and f.document_id
            # 低于审核阈值的数字仍保留在台账，但不进入解说词证据上下文。
            and (
                bool((f.metadata_json or {}).get("auto_usable"))
                or float(f.confidence or 0) >= REVIEW_THRESHOLD
                or not f.metadata_json
            )
        )
    ]
    # 先把可自动使用的高置信度事实送入上下文，再按原文页码/提取顺序补充待审核项。
    # 这样全量数字证据变多后，不会因为前 30 条恰好是低价值编号而挤掉关键参数。
    sourced_facts.sort(
        key=lambda f: (
            0 if ((f.metadata_json or {}).get("auto_usable") or float(f.confidence or 0) >= AUTO_USE_THRESHOLD) else 1,
            -float(f.confidence or 0),
            f.page_number if f.page_number is not None else 10**9,
            (f.metadata_json or {}).get("source_order", 10**9),
        )
    )
    conflicts = [f for f in facts if f.verification_status == "conflict"]

    fact_lines = _project_field_lines(project)
    for f in confirmed_facts:
        metadata = f.metadata_json or {}
        fact_label = metadata.get("display_name") or f.fact_name
        scope = f" [{metadata.get('scope')}]" if metadata.get("scope") else ""
        source_location = f.location_label or (f"P{f.page_number}" if f.page_number else "位置未知")
        fact_lines.append(
            f"- {fact_label}{scope} (key={f.fact_name}): {f.fact_value}{f.unit or ''} [已确认] "
            f"(来源: {f.document.file_name if f.document else '未知'}"
            f" {source_location} 原文: {f.source_quote or ''})"
        )

    sourced_fact_lines = []
    for f in sourced_facts[:60]:
        metadata = f.metadata_json or {}
        fact_label = metadata.get("display_name") or f.fact_name
        scope = f" [{metadata.get('scope')}]" if metadata.get("scope") else ""
        usage_label = "自动识别可用" if (metadata.get("auto_usable") or float(f.confidence or 0) >= AUTO_USE_THRESHOLD) else "待审核"
        source_location = f.location_label or (f"P{f.page_number}" if f.page_number else "位置未知")
        sourced_fact_lines.append(
            f"- {fact_label}{scope} (key={f.fact_name}): {f.fact_value}{f.unit or ''} [{usage_label}且有来源] "
            f"(来源: {f.document.file_name if f.document else '未知'}"
            f" {source_location} 原文: {f.source_quote or ''})"
        )

    scoring_lines = []
    for idx, sp in enumerate(scoring_points):
        scoring_lines.append(
            f"- [{idx}] {sp.title}（分值{sp.score or '未标注'}）: {sp.description or ''}"
        )

    from app.services.narration_evidence import evidence_for_generation

    evidence_rows = evidence_for_generation(
        db,
        evidence_run_id,
        auto_approve=evidence_auto_approve,
    )
    return {
        "project": project,
        "confirmed_facts": confirmed_facts,
        "sourced_facts": sourced_facts,
        "conflicts": conflicts,
        "scoring_points": scoring_points,
        "fact_lines": fact_lines,
        "sourced_fact_lines": sourced_fact_lines,
        "scoring_lines": scoring_lines,
        "document_excerpt_lines": _document_excerpt_lines(db, project_id),
        "evidence_rows": evidence_rows,
        "evidence": _evidence_output_from_rows(evidence_rows),
    }


def _document_excerpt_lines(db, project_id: str, *, max_lines: int = 24) -> list[str]:
    """提取少量原文片段，避免事实抽取不完整时模型只能写模板话。"""
    keyword_re = re.compile(
        r"(项目名称|工程名称|建设地点|建筑面积|总建筑面积|工期|质量|安全|文明施工|"
        r"BIM|智慧工地|施工部署|总平面|进度计划|重难点|深基坑|绿色施工|创优)"
    )
    chunks = (
        db.query(DocumentChunk)
        .join(DocumentChunk.document)
        .filter(DocumentChunk.document.has(project_id=project_id))
        .order_by(DocumentChunk.created_at.asc())
        .limit(160)
        .all()
    )
    lines: list[str] = []
    for c in chunks:
        text = _clean_one_line(c.content)
        if text and (len(lines) < 6 or keyword_re.search(text)):
            doc_name = c.document.file_name if c.document else "未知文档"
            metadata = c.metadata_json or {}
            page_label = (
                metadata.get("location_label")
                if metadata.get("is_virtual_page")
                else (f"P{c.page_start}" if c.page_start else "P?")
            ) or "位置未知"
            loc = f"{page_label} {c.heading_path}" if c.heading_path else page_label
            lines.append(f"- {doc_name} {loc}: {text}")
        if len(lines) >= max_lines:
            return lines

    pages = (
        db.query(DocumentPage)
        .join(DocumentPage.document)
        .filter(DocumentPage.document.has(project_id=project_id))
        .order_by(DocumentPage.page_number.asc())
        .limit(80)
        .all()
    )
    for p in pages:
        text = _clean_one_line(p.cleaned_text or p.markdown_text or p.raw_text)
        if text and (len(lines) < 6 or keyword_re.search(text)):
            doc_name = p.document.file_name if p.document else "未知文档"
            page_label = p.location_label if (p.metadata_json or {}).get("is_virtual_page") else f"P{p.page_number}"
            lines.append(f"- {doc_name} {page_label or '位置未知'}: {text}")
        if len(lines) >= max_lines:
            break
    return lines


def _build_prompt(params: dict[str, Any], context: dict) -> str:
    """构建严格要求的提示词。"""
    target_duration = int(params.get("target_duration_seconds", 300))
    section_count = _target_shot_count(params)
    tone = params.get("tone", "专业庄重")
    video_purpose = params.get("video_purpose", "投标答辩")
    chars_per_minute = int(params.get("chars_per_minute", 260))
    focus_scoring = params.get("focus_scoring_points") or []
    include_company = params.get("include_company_intro", True)
    include_sim = params.get("include_construction_simulation", True)
    custom_requirements = _clean_one_line(params.get("custom_requirements"), 1800) or "（无）"

    fact_text = "\n".join(context["fact_lines"]) if context["fact_lines"] else "（无已确认事实）"
    sourced_fact_text = "\n".join(context["sourced_fact_lines"]) if context["sourced_fact_lines"] else "（无待确认来源事实）"
    excerpt_text = "\n".join(context["document_excerpt_lines"]) if context["document_excerpt_lines"] else "（无文档摘录）"
    scoring_text = "\n".join(context["scoring_lines"]) if context["scoring_lines"] else "（无评分点）"
    conflict_text = ""
    if context["conflicts"]:
        conflict_names = {f.fact_name for f in context["conflicts"]}
        conflict_text = (
            "\n注意：以下参数存在冲突，不得写入正式解说词："
            + ", ".join(conflict_names)
        )

    est_total_chars = target_duration / 60 * chars_per_minute
    per_shot_chars = max(30, est_total_chars // section_count)

    prompt = f"""你是资深工程投标视频总撰稿和施工组织方案解读专家。请为工程投标视频撰写解说词并拆分为分镜。

【视频参数】
- 目标时长：{target_duration} 秒
- 用途：{video_purpose}
- 解说风格：{tone}
- 分镜数量：{section_count} 个（默认结构：片头/项目概况/总体施工部署/施工总平面布置/项目特点/项目重难点/施工阶段及工序/关键技术措施/工期质量安全保障/履约承诺片尾）
- 每分钟参考字数：{chars_per_minute}，每分镜解说约 {per_shot_chars} 字
- 包含企业介绍：{include_company}；包含施工推演：{include_sim}
- 重点评分项：{', '.join(focus_scoring) if focus_scoring else '全部'}
- 本次额外要求：{custom_requirements}

【已确认工程事实（必须引用，不得编造）】
{fact_text}
{conflict_text}

【台账候选事实（待确认但有明确来源的材料）】
其中标记“自动识别可用”的高置信度事实可按原文直接引用；标记“待审核”的事实只能谨慎表达（如“根据文件显示、拟、约、计划”），并标为 partial。
{sourced_fact_text}

【文档原文摘录（用于补足施工方案语境，不得把摘录之外的数字写成确定事实）】
{excerpt_text}

【评分点（分镜应尽量覆盖）】
{scoring_text}

【硬性要求】
1. 旁白必须像正式投标汇报现场可直接朗读的成片解说，句子具体、连贯、有施工逻辑，避免“标准高、体系完善、保驾护航、共创未来”等空泛宣传语。
2. 每个包含工程事实的分镜必须在 sourceReferences 中给出来源（documentId/documentName/page/quote）。
3. 引用原文只保留验证所需短句。
4. 不得捏造日期、面积、金额、工期或企业业绩。
5. 无法从已确认事实验证的内容，放入顶层 unverifiedFacts，并在分镜 factCheckStatus 标为 partial 或 unverified。
6. 每个评分点至少被一个分镜覆盖（scoringPointIds 使用评分点序号，从 0 开始）。
7. 每段 narration 应围绕“画面正在展示什么 + 我方如何组织施工 + 对评分点的回应”展开；不要只写口号。
8. title 用 6-14 个字，narration 每段尽量接近上方字数要求，短片头/片尾可略短。
9. 仅输出 JSON，符合以下结构，不要输出任何其它内容：
{{
  "projectSummary": "一句话项目摘要",
  "totalDurationSeconds": {target_duration},
  "totalNarrationCharacters": 总字数,
  "unverifiedFacts": ["无法验证的事实1"],
  "shots": [
    {{
      "sequence": 1,
      "title": "分镜标题",
      "section": "章节",
      "narration": "解说词",
      "durationSeconds": 时长秒数,
      "visualType": "title|model_image|site_photo|generated_image|generated_video|bim_animation|infographic",
      "visualDescription": "画面描述",
      "imagePrompt": "图片生成提示词",
      "videoPrompt": "视频生成提示词",
      "keywords": ["关键词"],
      "scoringPointIds": [0],
      "sourceReferences": [{{"documentId": "", "documentName": "", "page": 1, "locationLabel": "", "quote": ""}}],
      "factCheckStatus": "verified|partial|unverified|conflict"
    }}
  ]
}}"""
    return prompt


EVIDENCE_TOPICS = [
    "项目概况", "总体部署", "工期节点", "平面及垂直运输", "基坑土方", "重点工艺",
    "钢结构", "机电", "BIM", "质量安全", "绿色施工", "总承包管理",
]


EMPTY_PHRASES = [
    "标准高", "体系完善", "保驾护航", "赋能发展", "共创未来", "大力推广",
    "较高要求", "坚实基础", "全面保障", "城市美好未来",
]


def _prompt_materials(context: dict) -> dict[str, str]:
    evidence = context.get("evidence")
    return {
        "facts": "\n".join(context["fact_lines"]) if context["fact_lines"] else "（无已确认事实）",
        "sourced_facts": "\n".join(context["sourced_fact_lines"]) if context["sourced_fact_lines"] else "（无待确认来源事实）",
        "excerpts": "\n".join(context["document_excerpt_lines"]) if context["document_excerpt_lines"] else "（无文档摘录）",
        "scoring": "\n".join(context["scoring_lines"]) if context["scoring_lines"] else "（无评分点）",
        "evidence": _format_evidence(evidence.evidenceItems, limit=160) if evidence else "（无全文证据）",
    }


def _build_evidence_prompt(params: dict[str, Any], context: dict) -> str:
    materials = _prompt_materials(context)
    return f"""你是工程投标视频的资料审查员。只做资料分析，不写解说词。

请阅读下方已上传文件抽取结果，按专题建立证据清单。只能使用材料中出现的事实，不得补写常识、经验或想象内容。

【专题】
{", ".join(EVIDENCE_TOPICS)}

【已确认工程事实】
{materials["facts"]}

【台账候选事实（均有明确来源；“自动识别可用”可直接引用，“待审核”只能谨慎表达）】
{materials["sourced_facts"]}

【文档原文摘录】
{materials["excerpts"]}

【输出要求】
1. 每条证据必须包含：原文事实、数字参数、施工动作、前后工序或空间关系、来源文件和页码。
2. 没有页码或来源的内容，只能作为 partial，不得标为 verified。
3. 无法支撑写作的空话放入 rejectedFacts。
4. 当前批次只输出本批次能直接支撑的证据；跨批次去重由系统完成，不得为了凑数量删掉独有数字和工序关系。
5. 仅输出 JSON，不要写解说词，不要解释。

JSON 结构：
{{
  "evidenceItems": [
    {{
      "topic": "项目概况",
      "fact": "原文事实的短句",
      "parameters": ["面积、工期、楼层等参数"],
      "constructionActions": ["开挖", "吊装", "穿插施工"],
      "sequenceContext": "前后工序或空间关系",
      "sourceReference": {{"documentId": "", "documentName": "", "page": 1, "locationLabel": "P1", "quote": "短引文"}},
      "factCheckStatus": "verified|partial|unverified|conflict"
    }}
  ],
  "rejectedFacts": ["无法验证或过于空泛的内容"]
}}"""


def _build_outline_prompt(params: dict[str, Any], context: dict, evidence: EvidenceOutput) -> str:
    target_duration = int(params.get("target_duration_seconds", 540))
    chars_per_minute = int(params.get("chars_per_minute", 215))
    target_chars = int(target_duration / 60 * chars_per_minute)
    target_beats = int(params.get("target_beat_count", 120))
    include_company = params.get("include_company_intro", False)
    include_sim = params.get("include_construction_simulation", True)
    custom_requirements = _clean_one_line(params.get("custom_requirements"), 1800) or "（无）"
    predefined_outline = _predefined_outline(params)
    materials = _prompt_materials(context)
    evidence_text = _format_evidence_for_outline(evidence.evidenceItems)
    return f"""你是施工组织推演型投标视频的总编导。此阶段只生成章节大纲，不写完整正文。

【视频目标】
- 目标时长：{target_duration} 秒
- 目标总字数：约 {target_chars} 字
- 目标旁白短句：约 {target_beats} 条，后续按句号和分号拆分时间轴
- 项目介绍：不超过 60 秒
- 施工方案与施工推演：不少于总时长 70%
- 结尾：不超过 30 秒
- 包含企业介绍：{include_company}
- 包含施工推演：{include_sim}
- 本次额外要求：{custom_requirements}

【用户预设的章节大纲】
{predefined_outline}

【全文证据清单（已按批次提取并保留来源）】
{evidence_text or "（无证据清单）"}

【评分点】
{materials["scoring"]}

【大纲要求】
1. 如果提供了用户预设大纲，必须保留其章节顺序和主线，不得擅自换成另一套章节；只能根据证据密度微调章节时长和拆分粒度。
2. 每章分配时长、目标字数、核心评分点和拟展示画面。
3. 如果未提供用户预设大纲，必须先根据原文标题、证据专题分布和施工先后关系自动提炼章节；章节数量不固定，不得预设为6章、8章或其他固定数量，但也不能把施工方案压缩成泛泛一章。
4. 项目介绍不超过60秒，施工组织与工艺推演不少于总时长70%，结尾不超过30秒。
5. 仅输出 JSON，不写正文。

JSON 结构：
{{
  "totalDurationSeconds": {target_duration},
  "targetCharacters": {target_chars},
  "chapters": [
    {{
      "sequence": 1,
      "title": "项目概况",
      "durationSeconds": 45,
      "targetCharacters": 160,
      "writingGoal": "本章要让评委确认项目边界和关键参数",
      "scoringFocus": ["评分点名称"],
      "visualPlan": "BIM 总览、区位、指标标注",
      "evidenceIndexes": [0, 1],
      "evidenceIds": ["证据数据库ID"]
    }}
  ]
}}"""


def _build_chapter_prompt(
    params: dict[str, Any],
    context: dict,
    chapter: OutlineChapter,
    evidence: EvidenceOutput,
    *,
    shot_start: int,
    shot_budget: int,
) -> str:
    materials = _prompt_materials(context)
    evidence_text = _format_evidence_by_indexes(evidence.evidenceItems, chapter.evidenceIndexes, chapter.evidenceIds)
    predefined_outline = _predefined_outline(params)
    banned = "、".join(EMPTY_PHRASES)
    shot_count = max(1, shot_budget)
    target_beats = max(1, round(int(params.get("target_beat_count", 120)) * float(chapter.durationSeconds) / max(1, int(params.get("target_duration_seconds", 540)))))
    per_shot = max(35, int(chapter.targetCharacters / shot_count))
    custom_requirements = _clean_one_line(params.get("custom_requirements"), 1800) or "（无）"
    return f"""你是资深施工组织方案解说词撰稿人。请只写本章，不要写其它章节。

【本章大纲】
- 章节：{chapter.title}
- 时长：{chapter.durationSeconds} 秒
- 目标字数：约 {chapter.targetCharacters} 字
- 分镜数量：{shot_count} 个
- 本章旁白短句目标：约 {target_beats} 条
- 本章写作目标：{chapter.writingGoal}
- 拟展示画面：{chapter.visualPlan}
- 每个分镜约 {per_shot} 字
- 分镜序号从 {shot_start} 开始
- 本次额外要求：{custom_requirements}

【全局预设大纲】
{predefined_outline}

【本章证据】
{evidence_text or "（本章没有明确证据，只能写组织逻辑，不得写具体数字）"}

【全局已确认事实】
{materials["facts"]}

【台账候选事实（“自动识别可用”可直接引用，“待审核”只能谨慎表达）】
{materials["sourced_facts"]}

【写作硬规则】
1. 语言专业、克制、具体，重点讲清施工对象、数量参数、作业顺序、穿插关系和控制结果。
2. 每句话 8 至 26 个汉字左右，适合配音和画面切换。
3. 每 2 至 3 句话至少出现一个具体工序、参数、设备或空间关系。
4. 禁止使用：{banned}。
5. 不得编造标书中没有的数字、日期、奖项、设备型号和施工方法。
6. 涉及标记为“待审核”的材料时，用“根据文件显示、计划、拟、约”等谨慎措辞，并标为 partial；“自动识别可用”材料可直接引用，但不得改写数值或范围。
7. 每个分镜必须返回 evidenceIds，且只能使用本章证据中的真实ID；sourceReferences必须与这些证据对应。
8. 没有证据支撑的内容不要写成确定事实，放入 unverifiedFacts。
9. 仅输出 JSON。

JSON 结构：
{{
  "shots": [
    {{
      "sequence": {shot_start},
      "title": "6-14字标题",
      "section": "{chapter.title}",
      "narration": "本分镜解说词，包含短句，可由2-5句组成。",
      "durationSeconds": 20,
      "visualType": "title|model_image|site_photo|generated_image|generated_video|bim_animation|infographic",
      "visualDescription": "画面内容",
      "imagePrompt": "图片提示词",
      "videoPrompt": "视频提示词",
      "keywords": ["关键词"],
      "scoringPointIds": [0],
      "evidenceIds": ["本分镜使用的证据数据库ID"],
      "sourceReferences": [{{"documentId": "", "documentName": "", "page": 1, "locationLabel": "P1", "quote": ""}}],
      "factCheckStatus": "verified|partial|unverified|conflict"
    }}
  ],
  "unverifiedFacts": []
}}"""


def _build_qa_prompt(
    params: dict[str, Any],
    context: dict,
    outline: OutlineOutput,
    draft: NarrationOutput,
) -> str:
    target_duration = int(params.get("target_duration_seconds", 540))
    section_count = int(params.get("section_count", 24))
    banned = "、".join(EMPTY_PHRASES)
    materials = _prompt_materials(context)
    custom_requirements = _clean_one_line(params.get("custom_requirements"), 1800) or "（无）"
    draft_json = draft.model_dump_json(exclude_none=True)
    outline_json = outline.model_dump_json(exclude_none=True)
    return f"""你是另一个独立终审 agent。请审查并修订整条投标视频解说词。

【终审依据】
已确认事实：
{materials["facts"]}

台账候选事实（“自动识别可用”可直接引用，“待审核”只能谨慎表达）：
{materials["sourced_facts"]}

大纲：
{outline_json}

待审全文 JSON：
{draft_json}

本次额外要求：{custom_requirements}

【审查任务】
1. 检查事实来源、数字一致性、工序先后、章节衔接、重复句式和口号化表达。
2. 删除或改写无法验证的确定性表述，无法验证内容放入 unverifiedFacts。
3. 禁止保留这些空泛表达：{banned}。
4. 维持总时长约 {target_duration} 秒，分镜数量不超过 {section_count} 个。
5. 输出必须仍是完整 NarrationOutput JSON，可直接入库。

JSON 结构与原文一致：
{{
  "projectSummary": "一句话项目摘要",
  "totalDurationSeconds": {target_duration},
  "totalNarrationCharacters": 总字数,
  "unverifiedFacts": ["无法验证的内容"],
  "shots": [...]
}}"""


def _build_qa_review_prompt(
    params: dict[str, Any],
    context: dict,
    outline: OutlineOutput,
    draft: NarrationOutput,
) -> str:
    materials = _prompt_materials(context)
    return f"""你是独立的工程投标文案终审 agent。只做审查，不重写整篇文案。

【审查依据】
已批准证据：
{materials["evidence"]}

章节大纲：
{outline.model_dump_json(exclude_none=True)}

待审分镜：
{draft.model_dump_json(exclude_none=True)}

请检查：数字、日期、设备型号、施工方法是否能被来源支撑；工序先后和空间关系是否矛盾；项目介绍、施工推演、结尾的时长比例；重复句式、口号化表达和无法验证的确定性内容。
不得生成整篇 JSON，只返回问题列表，以及确实需要修改的局部补丁。没有问题时 issues 和 patches 返回空数组。

JSON格式：
{{
  "issues": ["问题描述，指出分镜序号和原因"],
  "unsupportedFacts": ["无法验证的事实"],
  "patches": [
    {{"sequence": 1, "narration": "局部修订后的旁白", "factCheckStatus": "verified|partial|unverified|conflict", "reason": "修改原因"}}
  ]
}}"""


def _fallback_evidence(context: dict) -> EvidenceOutput:
    """LLM 证据抽取失败时，把现有事实和摘录转为证据，保证多阶段可继续。"""
    items: list[EvidenceItem] = []
    for f in context["confirmed_facts"][:50] + context["sourced_facts"][:30]:
        metadata = f.metadata_json or {}
        from app.services.fact_extractor import FACT_TYPE_LABELS

        fact_label = metadata.get("display_name") or FACT_TYPE_LABELS.get(f.fact_name) or "待识别数字"
        scope = f"（{metadata['scope']}）" if metadata.get("scope") else ""
        ref = SourceRef(
            documentId=f.document_id or "",
            documentName=f.document.file_name if f.document else "",
            page=f.page_number,
            locationLabel=f.location_label or (f"P{f.page_number}" if f.page_number else None),
            quote=_clean_one_line(f.source_quote, 120),
        )
        status: FactCheckStatus = "verified" if f.verification_status == "confirmed" else "partial"
        items.append(
            EvidenceItem(
                topic=_guess_topic(f"{fact_label} {f.fact_value} {f.source_quote}"),
                fact=f"{fact_label}{scope}: {f.fact_value}{f.unit or ''}",
                parameters=[f"{f.fact_value}{f.unit or ''}"] if f.fact_value else [],
                constructionActions=_extract_actions(f"{fact_label} {f.source_quote}"),
                sequenceContext="",
                sourceReference=ref,
                factCheckStatus=status,
            )
        )
    for line in context["document_excerpt_lines"][:24]:
        page_match = re.search(r"\sP(\d+)(?:\s|:)", line)
        page = int(page_match.group(1)) if page_match else None
        document_name = line[2:page_match.start()].strip() if page_match else "文档摘录"
        quote = line.split(": ", 1)[1] if ": " in line else line
        items.append(
            EvidenceItem(
                topic=_guess_topic(line),
                fact=line,
                constructionActions=_extract_actions(line),
                sourceReference=SourceRef(documentName=document_name, page=page, locationLabel=f"P{page}" if page else None, quote=_clean_one_line(quote, 120)),
                factCheckStatus="partial",
            )
        )
    return EvidenceOutput(evidenceItems=items, rejectedFacts=[])


def _merge_chapter_drafts(
    params: dict[str, Any],
    context: dict,
    outline: OutlineOutput,
    drafts: list[ChapterDraftOutput],
) -> NarrationOutput:
    shots: list[ShotOut] = []
    unverified: list[str] = []
    sequence = 1
    for draft in drafts:
        unverified.extend(draft.unverifiedFacts)
        for shot in draft.shots:
            data = shot.model_dump()
            data["sequence"] = sequence
            shots.append(ShotOut.model_validate(data))
            sequence += 1

    target_duration = int(params.get("target_duration_seconds", outline.totalDurationSeconds or 540))
    if shots:
        chars_per_minute = max(120, int(params.get("chars_per_minute", 215)))
        natural_durations = [
            max(
                1.5,
                len(re.sub(r"\s+", "", shot.narration or "")) / chars_per_minute * 60
                + len(re.findall(r"[。！？；]", shot.narration or "")) * 0.18,
            )
            for shot in shots
        ]
        current_duration = sum(natural_durations) or 1
        ratio = target_duration / current_duration
        for shot, natural_duration in zip(shots, natural_durations):
            shot.durationSeconds = max(1.5, round(natural_duration * ratio, 1))

    return NarrationOutput(
        projectSummary=_project_summary(context),
        totalDurationSeconds=target_duration,
        totalNarrationCharacters=sum(len(s.narration or "") for s in shots),
        unverifiedFacts=list(dict.fromkeys(unverified)),
        shots=shots,
    )


def _lint_narration_output(output: NarrationOutput) -> None:
    """保守清理口号化短语，避免终审漏掉显眼问题。"""
    for shot in output.shots:
        text = shot.narration or ""
        for phrase in EMPTY_PHRASES:
            text = text.replace(phrase, "")
        text = re.sub(r"[，,；;]\s*[，,；;]+", "，", text)
        cleaned = re.sub(r"\s+", "", text).strip("，；。")
        shot.narration = cleaned + ("。" if cleaned and not cleaned.endswith(("。", "！", "？")) else "")


# ============================================================
# 主流程
# ============================================================

def _get_document_name(db, document_id: str) -> str:
    if not document_id:
        return ""
    from app.models.source_document import SourceDocument

    doc = db.get(SourceDocument, document_id)
    return doc.file_name if doc else ""


def _map_refs(db, shot: ShotOut, project_id: str | None = None) -> list[dict]:
    """将 LLM 输出的引用映射为存库格式。

    若 LLM 给出的 documentId 是占位符（如 "tender"）或空，尝试映射到项目实际文档。
    """
    from app.models.source_document import SourceDocument

    # 项目文档映射（按 doc_type 优先）
    project_docs: dict[str, SourceDocument] = {}
    if project_id:
        for doc in (
            db.query(SourceDocument)
            .filter(SourceDocument.project_id == project_id)
            .order_by(SourceDocument.created_at.asc())
            .all()
        ):
            project_docs.setdefault(doc.doc_type, doc)
            project_docs.setdefault("all", doc)

    refs = []
    for ref in shot.sourceReferences:
        doc_id = ref.documentId
        if not doc_id or doc_id in ("tender", "construction", "scoring", "unknown"):
            # 占位符映射到项目实际文档
            mapped = project_docs.get(ref.documentId) or project_docs.get("all")
            if mapped:
                doc_id = mapped.id
            else:
                # 没有真实文档时，不能保留 "tender" 这类看似有效的假引用。
                continue
        elif not db.get(SourceDocument, doc_id):
            continue
        doc_name = ref.documentName or _get_document_name(db, doc_id)
        refs.append(
            {
                "documentId": doc_id,
                "documentName": doc_name,
                "page": ref.page,
                "locationLabel": ref.locationLabel or (f"P{ref.page}" if ref.page else None),
                "quote": ref.quote,
            }
        )
    return refs


def _fallback_outline(params: dict[str, Any], evidence: EvidenceOutput) -> OutlineOutput:
    target = int(params.get("target_duration_seconds", 540))
    cpm = int(params.get("chars_per_minute", 215))
    specs = [
        ("项目概况", .08, "交代项目边界与已核实参数"), ("总体部署", .11, "说明分区、资源与流水组织"),
        ("工期节点", .12, "说明关键节点及前后衔接"), ("平面与垂直运输", .12, "说明道路、堆场与运输组织"),
        ("基础与关键工艺", .20, "说明土方、基础及重点工艺的作业顺序"), ("主体与专业穿插", .16, "说明主体、机电与装饰的穿插关系"),
        ("BIM质量安全管理", .16, "说明BIM协同、质量安全和绿色施工控制"), ("履约收束", .05, "收束履约目标，不扩写未验证承诺"),
    ]
    chapters = [OutlineChapter(sequence=i, title=title, durationSeconds=max(15, round(target * weight)), targetCharacters=max(60, round(target * weight / 60 * cpm)), writingGoal=goal, visualPlan="对应施工区域、工序关系与控制要点的BIM或现场画面") for i, (title, weight, goal) in enumerate(specs, 1)]
    return OutlineOutput(totalDurationSeconds=target, targetCharacters=round(target / 60 * cpm), chapters=chapters)


def _is_fact_bearing_text(text: str) -> bool:
    return bool(re.search(r"\d|工期|面积|楼层|高度|塔吊|施工电梯|基坑|土方|钢结构|机电|BIM|混凝土|吊装|浇筑|开挖|回填", text or ""))


def _match_evidence_ids(shot: ShotOut, rows: list[NarrationEvidence]) -> list[str]:
    haystack = " ".join(
        [shot.title or "", shot.section or "", shot.narration or ""]
        + list(shot.keywords or [])
        + [ref.quote or "" for ref in shot.sourceReferences]
        + [ref.documentName or "" for ref in shot.sourceReferences]
    )
    matches: list[str] = []
    generic_terms = {
        "本工程", "项目概况", "施工内容", "主要施工内容", "施工组织", "施工方案",
        "施工安排", "施工阶段", "工程施工", "相关工程", "施工管理", "质量控制",
    }
    for row in rows:
        reference = row.source_reference or {}
        quote = str(reference.get("quote") or "").strip()
        if quote and len(quote) <= 100 and quote in haystack:
            matches.append(row.id)
            continue
        technical_terms = re.findall(
            r"清水混凝土|PC结构|钢结构|基坑|土方|吊装|机电|BIM|塔吊|施工电梯|"
            r"支护|降水|回填|网壳|核心筒|外框架|混凝土|幕墙|管综",
            row.fact or "",
        )
        numeric_terms = re.findall(r"\d+(?:\.\d+)?", row.fact or "")
        fact_terms = list(dict.fromkeys(
            term for term in technical_terms + numeric_terms if term not in generic_terms
        ))
        if fact_terms and sum(term in haystack for term in fact_terms) >= max(1, min(2, len(fact_terms))):
            matches.append(row.id)
    return matches[:8]


def _evidence_refs_for_shot(
    shot: ShotOut,
    rows: list[NarrationEvidence],
    *,
    limit: int = 3,
) -> list[SourceRef]:
    """把分章证据ID映射成真实来源，防止模型漏填 sourceReferences。"""
    explicit_ids = [evidence_id for evidence_id in shot.evidenceIds if evidence_id]
    matched_ids = _match_evidence_ids(shot, rows)
    wanted = list(dict.fromkeys(explicit_ids + matched_ids))[:limit]
    by_id = {row.id: row for row in rows}
    refs: list[SourceRef] = []
    for evidence_id in wanted:
        row = by_id.get(evidence_id)
        if not row:
            continue
        refs.append(_source_ref_from_row(row))
    return refs


def _grounded_fallback_narration(shot: ShotOut, rows: list[NarrationEvidence]) -> str:
    """仅在模型完全漏掉引用时，用匹配到的原文事实生成可追溯的短句。"""
    matched_ids = _match_evidence_ids(shot, rows)
    by_id = {row.id: row for row in rows}
    selected = [by_id[evidence_id] for evidence_id in matched_ids[:2] if evidence_id in by_id]
    if not selected:
        return f"本章围绕{shot.section or shot.title or '施工组织'}展开施工推演。"
    parts: list[str] = []
    for row in selected:
        fact = _clean_one_line(row.fact, 120)
        relation = _clean_one_line(row.sequence_context, 80)
        parts.append(fact + (f"；{relation}" if relation and relation != "无" else ""))
    return "。".join(parts).rstrip("。；") + "。"


def _create_narration_beats(db, project_id: str, shots: list[StoryboardShot], evidence_rows: list[NarrationEvidence], cpm: int) -> int:
    db.query(NarrationBeat).filter(NarrationBeat.project_id == project_id).delete(synchronize_session=False)
    sequence = 1
    timeline = 0.0
    for shot in shots:
        parts = _split_narration_beats(shot.narration or "")
        if not parts:
            continue
        weights = [max(1.0, len(re.sub(r"\s+", "", part))) for part in parts]
        total_weight = sum(weights) or 1.0
        shot_duration = max(0.1, float(shot.duration_seconds or 0))
        shot_refs = [SourceRef.model_validate(ref) for ref in (shot.source_references or [])]
        shot_evidence_ids = _match_evidence_ids(
            ShotOut(
                sequence=shot.sequence,
                title=shot.title or "",
                section=shot.section or "",
                narration=shot.narration or "",
                durationSeconds=shot.duration_seconds or 1,
                visualType=shot.visual_type or "generated_image",
                visualDescription=shot.visual_description or "",
                imagePrompt=shot.image_prompt or "",
                videoPrompt=shot.video_prompt or "",
                keywords=list(shot.keywords or []),
                scoringPointIds=[],
                sourceReferences=shot_refs,
                factCheckStatus=shot.fact_check_status or "unverified",
            ),
            evidence_rows,
        )
        current = timeline
        for index, (part, weight) in enumerate(zip(parts, weights), start=1):
            duration = shot_duration * weight / total_weight
            end = timeline + duration
            if index == len(parts):
                end = current + shot_duration
            db.add(
                NarrationBeat(
                    project_id=project_id,
                    shot_id=shot.id,
                    sequence=sequence,
                    shot_sequence=shot.sequence,
                    narration=part,
                    start_time=round(timeline, 3),
                    end_time=round(end, 3),
                    evidence_ids=shot_evidence_ids,
                    source_references=shot.source_references or [],
                    fact_check_status=shot.fact_check_status or "unverified",
                    status="ai_done",
                )
            )
            sequence += 1
            timeline = end
    return sequence - 1


def rebuild_project_narration_beats(db, project_id: str, cpm: int = 215) -> int:
    """旁白被人工修改后，按当前分镜重新计算字幕节拍。"""
    shots = (
        db.query(StoryboardShot)
        .filter(StoryboardShot.project_id == project_id, StoryboardShot.is_active.is_(True))
        .order_by(StoryboardShot.sequence.asc())
        .all()
    )
    count = _create_narration_beats(db, project_id, shots, [], cpm)
    return count


def resegment_storyboard(params: dict[str, Any]) -> dict[str, Any]:
    return _resegment_storyboard_impl(
        params,
        complete_structured=_complete_structured,
        create_narration_beats=_create_narration_beats,
        resegment_identity=_resegment_identity,
        infer_source_sequences=_infer_source_sequences,
    )


def _quality_report(parsed: NarrationOutput, params: dict[str, Any], evidence_rows: list[NarrationEvidence], beat_count: int) -> dict[str, Any]:
    fact_shots = [shot for shot in parsed.shots if _is_fact_bearing_text(shot.narration)]
    cited_shots = [shot for shot in fact_shots if shot.sourceReferences]
    banned_hits = sorted({phrase for shot in parsed.shots for phrase in EMPTY_PHRASES if phrase in (shot.narration or "")})
    target_duration = float(params.get("target_duration_seconds", 540))
    actual_duration = sum(float(shot.durationSeconds or 0) for shot in parsed.shots)
    construction_chars = sum(
        len(shot.narration or "")
        for shot in parsed.shots
        if not re.search(r"片头|项目概况|履约|片尾|结尾", shot.section or shot.title or "")
    )
    total_chars = sum(len(shot.narration or "") for shot in parsed.shots) or 1
    return {
        "evidence_count": len(evidence_rows),
        "beat_count": beat_count,
        "target_beat_count": int(params.get("target_beat_count", 120)),
        "beat_count_gap": beat_count - int(params.get("target_beat_count", 120)),
        "fact_shot_count": len(fact_shots),
        "cited_fact_shot_count": len(cited_shots),
        "fact_reference_rate": round(len(cited_shots) / len(fact_shots), 4) if fact_shots else 1.0,
        "construction_content_ratio": round(construction_chars / total_chars, 4),
        "target_duration_seconds": target_duration,
        "actual_duration_seconds": round(actual_duration, 2),
        "duration_gap_seconds": round(target_duration - actual_duration, 2),
        "banned_phrases": banned_hits,
        "unverified_facts": list(parsed.unverifiedFacts),
    }


def _persist_storyboard_output(db, params: dict[str, Any], context: dict, parsed: NarrationOutput, *, source: str) -> dict[str, Any]:
    project_id = params["project_id"]
    db.query(NarrationBeat).filter(NarrationBeat.project_id == project_id).delete(synchronize_session=False)
    # 分镜是视频工程、配音和素材的共同主键。重生成时复用同序号的活动记录，
    # 只归档多余记录，绝不再 delete/recreate，避免视频位置与素材绑定悬空。
    existing = (
        db.query(StoryboardShot)
        .filter(StoryboardShot.project_id == project_id, StoryboardShot.is_active.is_(True))
        .order_by(StoryboardShot.sequence.asc())
        .all()
    )
    next_revision = max((int(s.revision or 1) for s in existing), default=0) + 1
    created: list[StoryboardShot] = []
    scoring_points = context["scoring_points"]
    evidence_rows = list(context.get("evidence_rows", []))
    fallback_ref = None
    fallback_fact = next(iter(context["confirmed_facts"] or context["sourced_facts"]), None)
    if fallback_fact:
        fallback_ref = SourceRef(
            documentId=fallback_fact.document_id or "",
            documentName=fallback_fact.document.file_name if fallback_fact.document else "",
            page=fallback_fact.page_number,
            locationLabel=fallback_fact.location_label or (f"P{fallback_fact.page_number}" if fallback_fact.page_number else None),
            quote=_clean_one_line(fallback_fact.source_quote, 120),
        )
    max_shots = _target_shot_count(params)
    for i, shot_data in enumerate(parsed.shots[:max_shots], 1):
        scoring_ids = [scoring_points[idx].id for idx in shot_data.scoringPointIds if 0 <= idx < len(scoring_points)]
        evidence_refs = _evidence_refs_for_shot(shot_data, evidence_rows)
        if evidence_refs:
            shot_data.sourceReferences = list(shot_data.sourceReferences) + evidence_refs
        references = _map_refs(db, shot_data, project_id)
        if references and evidence_refs and shot_data.factCheckStatus == "unverified":
            shot_data.factCheckStatus = "partial"
        if _is_fact_bearing_text(shot_data.narration) and not references:
            shot_data.factCheckStatus = "unverified"
            parsed.unverifiedFacts.append(f"分镜{i}缺少可核验来源")
            if bool(params.get("strict_fact_mode", True)):
                shot_data.narration = _grounded_fallback_narration(shot_data, evidence_rows)
        if not references and i == 1 and fallback_ref:
            references = _map_refs(db, ShotOut(
                sequence=shot_data.sequence,
                title=shot_data.title,
                section=shot_data.section,
                narration=shot_data.narration,
                durationSeconds=shot_data.durationSeconds,
                visualType=shot_data.visualType,
                visualDescription=shot_data.visualDescription,
                imagePrompt=shot_data.imagePrompt,
                videoPrompt=shot_data.videoPrompt,
                keywords=shot_data.keywords,
                scoringPointIds=shot_data.scoringPointIds,
                sourceReferences=[fallback_ref],
                factCheckStatus=shot_data.factCheckStatus,
            ), project_id)
        shot = existing[i - 1] if i <= len(existing) else StoryboardShot(project_id=project_id, sequence=i)
        shot.sequence = i
        shot.title = shot_data.title
        shot.section = shot_data.section
        shot.narration = shot_data.narration
        shot.duration_seconds = float(shot_data.durationSeconds)
        shot.visual_type = shot_data.visualType
        shot.visual_description = shot_data.visualDescription
        shot.visual_prompt = shot_data.imagePrompt or shot_data.visualDescription
        shot.image_prompt = shot_data.imagePrompt
        shot.video_prompt = shot_data.videoPrompt
        shot.keywords = shot_data.keywords
        shot.scoring_point_ids = scoring_ids
        shot.source_references = references
        shot.fact_check_status = shot_data.factCheckStatus
        shot.status = "ai_done"
        shot.is_active = True
        shot.revision = next_revision
        history = list(shot.versions or [])
        history.append({"revision": next_revision, "narration": shot_data.narration, "visual_prompt": shot_data.imagePrompt or shot_data.visualDescription, "visual_type": shot_data.visualType, "created_at": utc_now_iso(), "source": "ai" if source.startswith("ai") else source})
        shot.versions = history[-20:]
        db.add(shot)
        created.append(shot)

    for old_shot in existing[len(created):]:
        old_shot.is_active = False
        old_shot.status = "archived"
        old_shot.revision = next_revision
    db.flush()
    db.commit()
    beat_count = _create_narration_beats(
        db,
        project_id,
        created,
        context.get("evidence_rows", []),
        int(params.get("chars_per_minute", 215)),
    )
    db.commit()
    from app.services.scoring_service import compute_scoring_coverage
    coverage = compute_scoring_coverage(db, project_id)
    total_duration = sum(float(s.duration_seconds or 0) for s in created)
    total_chars = sum(len(s.narration or "") for s in created)
    quality = _quality_report(parsed, params, context.get("evidence_rows", []), beat_count)
    return {"shot_count": len(created), "beat_count": beat_count, "total_duration_seconds": total_duration, "total_narration_characters": total_chars, "duration_gap_seconds": int(params.get("target_duration_seconds", 540) - total_duration), "unverified_facts": list(dict.fromkeys(parsed.unverifiedFacts)), "scoring_coverage_rate": coverage["coverage_rate"], "scoring_covered": coverage["covered"], "scoring_total": coverage["total"], "quality_report": quality}


def _single_pass(params: dict[str, Any], context: dict, adapter) -> NarrationOutput:
    return parse_narration_output(adapter.complete(_build_prompt(params, context), temperature=.2, max_tokens=8000, response_format={"type": "json_object"}))


def _update_generation_task(db, params: dict[str, Any], progress: int, message: str) -> None:
    task_id = params.get("task_id")
    task = db.get(RenderTask, task_id) if task_id else None
    if not task:
        return
    task.progress = max(int(task.progress or 0), max(0, min(99, int(progress))))
    task.message = message[:512]
    db.commit()


def _multi_stage(params: dict[str, Any], context: dict, adapter, db) -> tuple[NarrationOutput, dict[str, Any]]:
    """执行可恢复的证据→大纲→分章→局部终审流程。

    任何阶段失败都向任务层抛出异常，不能偷偷退回单轮生成；证据批次本身
    会在下次运行时跳过已成功结果，从而实现断点续跑。
    """
    from app.services.narration_evidence import (
        approve_evidence,
        create_evidence_run,
        evidence_for_generation,
        extract_evidence_run,
    )

    project_id = params["project_id"]
    evidence_run_id = params.get("evidence_run_id")
    run = db.get(NarrationRun, evidence_run_id) if evidence_run_id else None
    if run and run.project_id != project_id:
        raise RuntimeError("证据运行与当前项目不匹配")
    if not run:
        run_params = dict(params)
        adapter_model = getattr(adapter, "config", {}).get("model") if getattr(adapter, "config", None) else None
        if adapter_model:
            run_params["model"] = adapter_model
        run = create_evidence_run(db, project_id, run_params)
        params["evidence_run_id"] = run.id
        task_id = params.get("task_id")
        task = db.get(RenderTask, task_id) if task_id else None
        if task:
            task.params = {**(task.params or {}), "evidence_run_id": run.id, "task_id": task.id}
            db.commit()
        extract_evidence_run(
            db,
            run.id,
            adapter,
            progress_callback=lambda percent, message: _update_generation_task(
                db, params, round(percent * 0.68), message
            ),
        )
    elif run.status not in {"evidence_review", "outline_review", "drafting", "qa", "completed"}:
        extract_evidence_run(
            db,
            run.id,
            adapter,
            progress_callback=lambda percent, message: _update_generation_task(
                db, params, round(percent * 0.68), message
            ),
        )

    auto_approve = bool(params.get("evidence_auto_approve", True))
    if auto_approve:
        approve_evidence(db, run.id)
    rows = evidence_for_generation(db, run.id, auto_approve=auto_approve)
    if not rows:
        # 仅在项目没有可解析文档、但旧版事实台账仍有来源时兼容旧项目。
        fallback = _fallback_evidence(context)
        if fallback.evidenceItems:
            evidence = fallback
        elif not context["confirmed_facts"] and not context["sourced_facts"] and not context["document_excerpt_lines"]:
            # 空项目仍允许生成待补资料的组织框架，但不得伪造任何工程事实。
            evidence = EvidenceOutput(
                evidenceItems=[
                    EvidenceItem(
                        topic="总体部署",
                        fact="当前项目未提供可引用的工程事实",
                        sequenceContext="仅可写组织框架，不得写数字、日期、设备或具体方法",
                        factCheckStatus="unverified",
                    )
                ],
                rejectedFacts=[],
            )
        else:
            raise RuntimeError("全文证据为空，无法进入正式写作")
    else:
        evidence = _evidence_output_from_rows(rows)
    if not auto_approve and not rows:
        raise RuntimeError(f"证据运行 {run.id} 尚未完成人工审核")

    context = _build_context(
        db,
        project_id,
        evidence_run_id=run.id,
        evidence_auto_approve=auto_approve,
    )
    context["evidence_run_id"] = run.id
    outline: OutlineOutput | None = None
    saved_outline = (run.params or {}).get("outline_output")
    if run.status in {"drafting", "qa", "completed"} and isinstance(saved_outline, dict):
        try:
            outline = OutlineOutput.model_validate(saved_outline)
            _update_generation_task(db, params, 72, "已恢复章节大纲，继续分章写作…")
        except Exception as exc:
            logger.warning("saved_outline_invalid", run_id=run.id, error=str(exc))

    if outline is None:
        run.status = "outline_generating"
        run.progress = {"stage": "outline_generating", "completed": run.completed_batches, "total": run.total_batches}
        db.commit()
        _update_generation_task(db, params, 72, "全文证据已完成，正在编排章节大纲…")
        try:
            outline = _complete_structured(
                adapter,
                _build_outline_prompt(params, context, evidence),
                parse_outline_output,
                stage="outline",
                max_tokens=5000,
                temperature=.1,
            )
        except Exception as exc:
            run.status = "outline_failed"
            run.error_message = str(exc)[:2000]
            db.commit()
            raise

        run_params = dict(run.params or {})
        run_params["outline_output"] = outline.model_dump(mode="json")
        run.params = run_params
    run.status = "drafting"
    db.commit()
    total_shots = max(_target_shot_count(params), len(outline.chapters))
    budgets = _allocate_shot_budgets(outline, total_shots)
    drafts: list[ChapterDraftOutput] = []
    shot_start = 1
    chapter_total = max(1, len(outline.chapters))
    for chapter_index, (chapter, budget) in enumerate(zip(outline.chapters, budgets), start=1):
        try:
            draft = _complete_structured(
                adapter,
                _build_chapter_prompt(params, context, chapter, evidence, shot_start=shot_start, shot_budget=budget),
                parse_chapter_draft_output,
                stage=f"chapter_{chapter.sequence}",
                max_tokens=5000,
                temperature=.2,
            )
        except Exception as exc:
            run.status = "drafting_failed"
            run.error_message = str(exc)[:2000]
            db.commit()
            raise
        chapter_evidence_ids = list(chapter.evidenceIds)
        for evidence_index in chapter.evidenceIndexes:
            if 0 <= evidence_index < len(evidence.evidenceItems):
                evidence_id = evidence.evidenceItems[evidence_index].evidenceId
                if evidence_id:
                    chapter_evidence_ids.append(evidence_id)
        chapter_evidence_ids = list(dict.fromkeys(chapter_evidence_ids))
        if chapter_evidence_ids:
            for local_index, shot in enumerate(draft.shots):
                if not shot.evidenceIds:
                    start = (local_index * 2) % len(chapter_evidence_ids)
                    shot.evidenceIds = [
                        chapter_evidence_ids[start],
                        chapter_evidence_ids[(start + 1) % len(chapter_evidence_ids)],
                    ]
        drafts.append(draft)
        shot_start += len(draft.shots)
        _update_generation_task(
            db,
            params,
            72 + round(chapter_index / chapter_total * 20),
            f"已完成章节 {chapter_index}/{chapter_total}：{chapter.title}",
        )
    merged = _merge_chapter_drafts(params, context, outline, drafts)
    run.status = "qa"
    db.commit()
    _update_generation_task(db, params, 94, "分章文案已完成，正在核对事实与引用…")
    try:
        review = _complete_structured(
            adapter,
            _build_qa_review_prompt(params, context, outline, merged),
            parse_qa_review_output,
            stage="qa",
            max_tokens=4500,
        )
    except Exception as exc:
        run.status = "qa_failed"
        run.error_message = str(exc)[:2000]
        db.commit()
        raise
    by_sequence = {shot.sequence: shot for shot in merged.shots}
    for patch in review.patches:
        shot = by_sequence.get(patch.sequence)
        if not shot:
            continue
        if patch.narration:
            shot.narration = patch.narration
        if patch.factCheckStatus:
            shot.factCheckStatus = patch.factCheckStatus
    merged.unverifiedFacts = list(dict.fromkeys(merged.unverifiedFacts + review.unsupportedFacts))
    _lint_narration_output(merged)
    run.progress = {"stage": "qa", "completed": run.total_batches, "total": run.total_batches}
    db.commit()
    return merged, {
        "run_id": run.id,
        "evidence_count": len(rows),
        "rejected_fact_count": len(review.unsupportedFacts),
        "qa_issue_count": len(review.issues),
        "qa_issues": review.issues,
        "outline_chapters": [{"title": c.title, "duration_seconds": c.durationSeconds} for c in outline.chapters],
    }


def generate_storyboard(params: dict[str, Any]) -> dict[str, Any]:
    """按资料取证、篇章编排、分章写作和终审四阶段生成分镜。"""
    from app.services.ai_configuration import refresh_runtime_config_from_db

    refresh_runtime_config_from_db()
    db = SessionLocal()
    try:
        context = _build_context(db, params["project_id"])
        adapter = get_llm_adapter()
        if not adapter.is_available():
            raise RuntimeError("LLM 服务不可用，请检查配置。")
        mode = params.get("generation_mode", "multi_stage")
        summary: dict[str, Any] = {}
        if mode == "single_pass":
            parsed = _single_pass(params, context, adapter)
        else:
            parsed, summary = _multi_stage(params, context, adapter, db)
            mode = "multi_stage"
            context = _build_context(
                db,
                params["project_id"],
                evidence_run_id=summary.get("run_id"),
                evidence_auto_approve=bool(params.get("evidence_auto_approve", True)),
            )
            context["evidence_run_id"] = summary.get("run_id")
        result = _persist_storyboard_output(db, params, context, parsed, source="ai_multi_stage" if mode == "multi_stage" else "ai")
        result["generation_mode"] = mode
        if summary:
            result["stage_summary"] = summary
            run = db.get(NarrationRun, summary.get("run_id")) if summary.get("run_id") else None
            if run:
                run.status = "completed"
                run.progress = {"stage": "completed", "completed": run.total_batches, "total": run.total_batches}
                db.commit()
        return result
    finally:
        db.close()


def regenerate_single_shot(params: dict[str, Any]) -> dict[str, Any]:
    """重新生成单个分镜。"""
    from app.services.ai_configuration import refresh_runtime_config_from_db

    refresh_runtime_config_from_db()
    project_id = params["project_id"]
    shot_id = params["shot_id"]
    hint = params.get("prompt_hint", "")

    db = SessionLocal()
    try:
        shot = db.get(StoryboardShot, shot_id)
        if not shot or shot.project_id != project_id:
            raise RuntimeError("分镜不存在")

        context = _build_context(db, project_id)
        adapter = get_llm_adapter()
        if not adapter.is_available():
            raise RuntimeError("LLM 服务不可用，请检查配置。")

        fact_text = "\n".join(context["fact_lines"]) if context["fact_lines"] else "无"
        sourced_fact_text = "\n".join(context["sourced_fact_lines"]) if context["sourced_fact_lines"] else "无"
        excerpt_text = "\n".join(context["document_excerpt_lines"][:12]) if context["document_excerpt_lines"] else "无"
        target_chars = max(80, int((shot.duration_seconds or 25) / 60 * 260))
        prompt = (
            "你是工程投标视频总撰稿。请重写下面这个分镜的旁白，要求能直接用于正式投标汇报视频。\n"
            f"分镜标题：{shot.title or '未命名'}\n"
            f"章节：{shot.section or '未命名'}\n"
            f"原旁白：{shot.narration or '无'}\n"
            f"画面说明：{shot.visual_description or shot.visual_prompt or '无'}\n"
            f"目标字数：约 {target_chars} 字\n"
            f"用户补充要求：{hint or '无'}\n\n"
            f"已确认工程事实：\n{fact_text}\n\n"
            f"台账候选事实（‘自动识别可用’可直接引用，‘待审核’只能谨慎表达）：\n{sourced_fact_text}\n\n"
            f"文档摘录：\n{excerpt_text}\n\n"
            "写作要求：具体、连贯、有施工组织逻辑；不要空泛口号；不要编造未给出的数字、日期、金额、业绩；"
            "包含标记为待审核的材料时用谨慎措辞；自动识别可用材料可直接引用。仅输出一段旁白正文，不要 JSON、标题或解释。"
        )
        raw = adapter.complete(prompt, temperature=0.25, max_tokens=1200)
        # Mock 返回的是完整 JSON，需要兼容：取第一个 narration
        narration = _safe_extract_narration(raw)

        # 记录历史版本
        versions = list(shot.versions or [])
        revision = max([v.get("revision", 0) for v in versions] + [0]) + 1
        versions.append(
            {
                "revision": revision,
                "narration": narration,
                "visual_prompt": shot.visual_prompt,
                "visual_type": shot.visual_type,
                "created_at": utc_now_iso(),
                "source": "ai",
            }
        )
        shot.narration = narration
        shot.versions = versions
        shot.status = "ai_done"
        db.flush()
        rebuild_project_narration_beats(db, project_id)
        db.commit()

        return {"shot_id": shot_id, "narration": narration, "revision": revision}
    finally:
        db.close()
