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
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from app.adapters.factory import get_llm_adapter
from app.core.database import SessionLocal
from app.core.logging import get_logger
from app.models.extracted_fact import ExtractedFact
from app.models.document_chunk import DocumentChunk
from app.models.document_page import DocumentPage
from app.models.project import Project
from app.models.scoring_point import ScoringPoint
from app.models.storyboard_shot import StoryboardShot

logger = get_logger(__name__)


# ============================================================
# 严格 Schema（Pydantic 校验）
# ============================================================

VisualType = Literal[
    "title", "model_image", "site_photo", "generated_image",
    "generated_video", "bim_animation", "infographic",
]
FactCheckStatus = Literal["verified", "partial", "unverified", "conflict"]


class SourceRef(BaseModel):
    documentId: str = ""
    documentName: str = ""
    page: int | None = None
    locationLabel: str | None = None
    quote: str | None = None


class ShotOut(BaseModel):
    sequence: int = Field(ge=1)
    title: str = ""
    section: str = ""
    narration: str = ""
    durationSeconds: int | float = Field(ge=1, le=600)
    visualType: VisualType = "generated_image"
    visualDescription: str = ""
    imagePrompt: str = ""
    videoPrompt: str = ""
    keywords: list[str] = []
    scoringPointIds: list[int] = []
    sourceReferences: list[SourceRef] = []
    factCheckStatus: FactCheckStatus = "unverified"


class NarrationOutput(BaseModel):
    projectSummary: str = ""
    totalDurationSeconds: int | float = 0
    totalNarrationCharacters: int = 0
    unverifiedFacts: list[str] = []
    shots: list[ShotOut] = Field(min_length=1)


def _extract_json(raw: str) -> str:
    """从 LLM 输出中稳健提取 JSON。"""
    raw = raw.strip()
    # 去掉 markdown 代码块
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    # 查找最外层 { ... } 或 [ ... ]
    try:
        json.loads(raw)
        return raw
    except json.JSONDecodeError:
        pass
    # 尝试截取第一个 { 到最后一个 }
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = raw[start : end + 1]
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            pass
    raise ValueError("无法从 LLM 输出中解析 JSON")


def parse_narration_output(raw: str) -> NarrationOutput:
    """严格校验 LLM 输出，异常时抛出 ValueError。"""
    json_text = _extract_json(raw)
    data = json.loads(json_text)
    # 兼容两种顶层结构：直接数组 或 {shots: [...]}
    if isinstance(data, list):
        data = {"projectSummary": "", "shots": data, "unverifiedFacts": []}
    return NarrationOutput.model_validate(data)


# ============================================================
# 上下文构建
# ============================================================

def _build_context(db, project_id: str) -> dict:
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

    confirmed_facts = [f for f in facts if f.verification_status == "confirmed"]
    sourced_facts = [
        f for f in facts
        if f.verification_status == "unverified" and f.source_quote and f.document_id
    ]
    conflicts = [f for f in facts if f.verification_status == "conflict"]

    fact_lines = _project_field_lines(project)
    for f in confirmed_facts:
        fact_lines.append(
            f"- {f.fact_name}: {f.fact_value}{f.unit or ''} [已确认] "
            f"(来源: {f.document.file_name if f.document else '未知'}"
            f" P{f.page_number or '?'} 原文: {f.source_quote or ''})"
        )

    sourced_fact_lines = []
    for f in sourced_facts[:30]:
        sourced_fact_lines.append(
            f"- {f.fact_name}: {f.fact_value}{f.unit or ''} [待确认但有来源] "
            f"(来源: {f.document.file_name if f.document else '未知'}"
            f" P{f.page_number or '?'} 原文: {f.source_quote or ''})"
        )

    scoring_lines = []
    for idx, sp in enumerate(scoring_points):
        scoring_lines.append(
            f"- [{idx}] {sp.title}（分值{sp.score or '未标注'}）: {sp.description or ''}"
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
    }


def _clean_one_line(text: str | None, limit: int = 220) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text[:limit]


def _project_field_lines(project: Project | None) -> list[str]:
    if not project:
        return []
    lines = [f"- project_name: {project.name} [项目档案]"]
    if project.description:
        lines.append(f"- project_description: {_clean_one_line(project.description, 180)} [项目档案]")
    if project.bid_area:
        suffix = f" P{project.area_source_page}" if project.area_source_page else ""
        lines.append(f"- area_building: {project.bid_area:g}㎡ [已确认]{suffix}")
    if project.construction_period:
        suffix = f" P{project.period_source_page}" if project.period_source_page else ""
        lines.append(f"- duration_total: {project.construction_period} [已确认]{suffix}")
    if project.bidder_name:
        suffix = f" P{project.bidder_source_page}" if project.bidder_source_page else ""
        lines.append(f"- bidder_name: {project.bidder_name} [已确认]{suffix}")
    if project.tech_params:
        for name, item in list(project.tech_params.items())[:12]:
            if isinstance(item, dict):
                value = item.get("value") or item.get("fact_value") or item.get("text")
                page = item.get("page") or item.get("source_page")
                if value:
                    lines.append(f"- {name}: {value} [项目台账]{f' P{page}' if page else ''}")
    return lines


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
            loc = c.heading_path or f"P{c.page_start or '?'}"
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
            lines.append(f"- {doc_name} P{p.page_number}: {text}")
        if len(lines) >= max_lines:
            break
    return lines


def _build_prompt(params: dict[str, Any], context: dict) -> str:
    """构建严格要求的提示词。"""
    target_duration = int(params.get("target_duration_seconds", 300))
    section_count = int(params.get("section_count", 10))
    tone = params.get("tone", "专业庄重")
    video_purpose = params.get("video_purpose", "投标答辩")
    chars_per_minute = int(params.get("chars_per_minute", 260))
    focus_scoring = params.get("focus_scoring_points") or []
    include_company = params.get("include_company_intro", True)
    include_sim = params.get("include_construction_simulation", True)

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

【已确认工程事实（必须引用，不得编造）】
{fact_text}
{conflict_text}

【待确认但有明确来源的材料（可用于表达，但必须谨慎措辞，如“拟、约、计划、根据文件显示”，并标为 partial）】
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


def generate_storyboard(params: dict[str, Any]) -> dict[str, Any]:
    """生成完整分镜并写入数据库。"""
    project_id = params["project_id"]
    section_count = int(params.get("section_count", 10))

    db = SessionLocal()
    try:
        context = _build_context(db, project_id)
        prompt = _build_prompt(params, context)

        adapter = get_llm_adapter()
        if not adapter.is_available():
            raise RuntimeError("LLM 服务不可用，请检查配置。")

        # 投标解说词包含 10+ 个结构化分镜，2000 token 容易截断 JSON。
        # DeepSeek V4 Flash 与 OpenAI 兼容接口均支持 json_object 输出。
        raw = adapter.complete(
            prompt,
            temperature=0.2,
            max_tokens=8000,
            response_format={"type": "json_object"},
        )
        parsed = parse_narration_output(raw)

        # 删除旧分镜（重新生成）
        db.query(StoryboardShot).filter(StoryboardShot.project_id == project_id).delete()
        db.flush()

        created: list[StoryboardShot] = []
        scoring_points = context["scoring_points"]
        for i, shot_data in enumerate(parsed.shots[:section_count], start=1):
            # 映射评分点 id
            scoring_ids = []
            for idx in shot_data.scoringPointIds:
                if 0 <= idx < len(scoring_points):
                    scoring_ids.append(scoring_points[idx].id)

            refs = _map_refs(db, shot_data, project_id)
            shot = StoryboardShot(
                project_id=project_id,
                sequence=i,
                title=shot_data.title,
                section=shot_data.section,
                narration=shot_data.narration,
                duration_seconds=float(shot_data.durationSeconds),
                visual_type=shot_data.visualType,
                visual_description=shot_data.visualDescription,
                visual_prompt=shot_data.imagePrompt or shot_data.visualDescription,
                image_prompt=shot_data.imagePrompt,
                video_prompt=shot_data.videoPrompt,
                keywords=shot_data.keywords,
                scoring_point_ids=scoring_ids,
                source_references=refs,
                fact_check_status=shot_data.factCheckStatus,
                status="ai_done",
                versions=[
                    {
                        "revision": 1,
                        "narration": shot_data.narration,
                        "visual_prompt": shot_data.imagePrompt or shot_data.visualDescription,
                        "visual_type": shot_data.visualType,
                        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "source": "ai",
                    }
                ],
            )
            db.add(shot)
            created.append(shot)

        db.commit()

        # 刷新评分点覆盖
        from app.services.scoring_service import compute_scoring_coverage

        coverage = compute_scoring_coverage(db, project_id)

        total_duration = sum(float(s.duration_seconds or 0) for s in created)
        total_chars = sum(len(s.narration or "") for s in created)
        target = int(params.get("target_duration_seconds", 300))

        return {
            "shot_count": len(created),
            "total_duration_seconds": total_duration,
            "total_narration_characters": total_chars,
            "duration_gap_seconds": int(target - total_duration),
            "unverified_facts": parsed.unverifiedFacts,
            "scoring_coverage_rate": coverage["coverage_rate"],
            "scoring_covered": coverage["covered"],
            "scoring_total": coverage["total"],
        }
    finally:
        db.close()


def regenerate_single_shot(params: dict[str, Any]) -> dict[str, Any]:
    """重新生成单个分镜。"""
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
            f"待确认但有来源材料：\n{sourced_fact_text}\n\n"
            f"文档摘录：\n{excerpt_text}\n\n"
            "写作要求：具体、连贯、有施工组织逻辑；不要空泛口号；不要编造未给出的数字、日期、金额、业绩；"
            "包含待确认材料时用谨慎措辞。仅输出一段旁白正文，不要 JSON、标题或解释。"
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
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "source": "ai",
            }
        )
        shot.narration = narration
        shot.versions = versions
        shot.status = "ai_done"
        db.commit()

        return {"shot_id": shot_id, "narration": narration, "revision": revision}
    finally:
        db.close()


def _safe_extract_narration(raw: str) -> str:
    """兼容 Mock 返回完整 JSON 的情况。"""
    try:
        parsed = parse_narration_output(raw)
        if parsed.shots:
            return parsed.shots[0].narration
    except (ValueError, ValidationError):
        pass
    text = raw.strip().strip('"').strip("'")
    if len(text) > 500:
        text = text[:500]
    return text or "解说词生成失败"
