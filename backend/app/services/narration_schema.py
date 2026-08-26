"""解说词引擎的结构化输入输出模型与解析器。"""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.models.narration_run import NarrationEvidence


def _clean_one_line(text: str | None, limit: int = 220) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()[:limit]

VisualType = Literal[
    "title", "model_image", "site_photo", "generated_image",
    "generated_video", "bim_animation", "infographic",
]
FactCheckStatus = Literal["verified", "partial", "unverified", "conflict"]

_VISUAL_TYPE_ALIASES = {
    "title_card": "title",
    "titlecard": "title",
    "标题": "title",
    "model": "model_image",
    "3d": "model_image",
    "render": "model_image",
    "rendering": "model_image",
    "模型": "model_image",
    "site": "site_photo",
    "photo": "site_photo",
    "photograph": "site_photo",
    "现场照片": "site_photo",
    "image": "generated_image",
    "picture": "generated_image",
    "图片": "generated_image",
    "video": "generated_video",
    "短视频": "generated_video",
    "animation": "bim_animation",
    "bim": "bim_animation",
    "bim动画": "bim_animation",
    "map": "infographic",
    "diagram": "infographic",
    "chart": "infographic",
    "flowchart": "infographic",
    "table": "infographic",
    "信息图": "infographic",
    "信息图表": "infographic",
}


def _normalise_visual_type(value: Any) -> str:
    if not isinstance(value, str):
        return "generated_image"
    key = re.sub(r"[\s_\-]+", "", value.strip().lower())
    if key in {"title", "modelimage", "sitephoto", "generatedimage", "generatedvideo", "bimanimation", "infographic"}:
        return {
            "title": "title",
            "modelimage": "model_image",
            "sitephoto": "site_photo",
            "generatedimage": "generated_image",
            "generatedvideo": "generated_video",
            "bimanimation": "bim_animation",
            "infographic": "infographic",
        }[key]
    return _VISUAL_TYPE_ALIASES.get(key, "generated_image")


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
    evidenceIds: list[str] = []
    sourceReferences: list[SourceRef] = []
    factCheckStatus: FactCheckStatus = "unverified"

    @model_validator(mode="before")
    @classmethod
    def normalise_model_visual_fields(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        data["visualType"] = _normalise_visual_type(data.get("visualType"))
        for key in ("keywords", "scoringPointIds", "evidenceIds", "sourceReferences"):
            if data.get(key) is None:
                data[key] = []
        return data


class NarrationOutput(BaseModel):
    projectSummary: str = ""
    totalDurationSeconds: int | float = 0
    totalNarrationCharacters: int = 0
    unverifiedFacts: list[str] = []
    shots: list[ShotOut] = Field(min_length=1)


class EvidenceItem(BaseModel):
    evidenceId: str = ""
    topic: str = ""
    fact: str = ""
    parameters: list[str] = []
    constructionActions: list[str] = []
    sequenceContext: str = ""
    sourceReference: SourceRef = Field(default_factory=SourceRef)
    factCheckStatus: FactCheckStatus = "partial"


class EvidenceOutput(BaseModel):
    evidenceItems: list[EvidenceItem] = []
    rejectedFacts: list[str] = []


def _source_ref_from_row(row: NarrationEvidence) -> SourceRef:
    reference = dict(row.source_reference or {})
    page = reference.get("page")
    if isinstance(page, str):
        match = re.search(r"\d+", page)
        page = int(match.group(0)) if match else None
    return SourceRef(
        documentId=str(reference.get("documentId") or row.document_id or ""),
        documentName=str(reference.get("documentName") or (row.document.file_name if row.document else "")),
        page=page if isinstance(page, int) else None,
        locationLabel=reference.get("locationLabel"),
        quote=_clean_one_line(reference.get("quote"), 180) or None,
    )


def _evidence_output_from_rows(rows: list[NarrationEvidence]) -> EvidenceOutput:
    return EvidenceOutput(
        evidenceItems=[
            EvidenceItem(
                evidenceId=row.id,
                topic=row.topic,
                fact=row.fact,
                parameters=list(row.parameters or []),
                constructionActions=list(row.construction_actions or []),
                sequenceContext=row.sequence_context or "",
                sourceReference=_source_ref_from_row(row),
                factCheckStatus=row.fact_check_status if row.fact_check_status in {"verified", "partial", "conflict"} else "partial",
            )
            for row in rows
            if row.fact.strip()
        ],
        rejectedFacts=[],
    )


class OutlineChapter(BaseModel):
    sequence: int = Field(ge=1)
    title: str = ""
    durationSeconds: int | float = Field(ge=5, le=600)
    targetCharacters: int = Field(ge=10, le=3000)
    writingGoal: str = ""
    scoringFocus: list[str] = []
    visualPlan: str = ""
    evidenceIndexes: list[int] = []
    evidenceIds: list[str] = []


class OutlineOutput(BaseModel):
    totalDurationSeconds: int | float = 0
    targetCharacters: int = 0
    chapters: list[OutlineChapter] = Field(min_length=1)


class ChapterDraftOutput(BaseModel):
    shots: list[ShotOut] = Field(min_length=1)
    unverifiedFacts: list[str] = []


class ResegmentShot(BaseModel):
    """AI 重新分镜的最小输出，正文必须来自现有分镜。"""

    sequence: int = Field(ge=1)
    title: str = ""
    section: str = ""
    narration: str = ""
    durationSeconds: int | float = Field(ge=1, le=600)
    visualType: VisualType = "generated_image"
    visualDescription: str = ""
    sourceShotSequences: list[int] = []

    @model_validator(mode="before")
    @classmethod
    def normalise_visual_type(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        data["visualType"] = _normalise_visual_type(data.get("visualType"))
        if data.get("sourceShotSequences") is None:
            data["sourceShotSequences"] = []
        return data


class ResegmentOutput(BaseModel):
    shots: list[ResegmentShot] = Field(min_length=1)


class QAReviewPatch(BaseModel):
    sequence: int = Field(ge=1)
    narration: str | None = None
    factCheckStatus: FactCheckStatus | None = None
    reason: str = ""


class QAReviewOutput(BaseModel):
    issues: list[str] = []
    unsupportedFacts: list[str] = []
    patches: list[QAReviewPatch] = []


def _extract_json(raw: str) -> str:
    """从模型输出中提取完整 JSON，允许前后带解释文字或 Markdown。"""
    text = (raw or "").strip()
    if not text:
        raise ValueError("LLM 返回为空，无法解析 JSON")

    # 不再依赖“第一个左括号到最后一个右括号”。模型有时会在 JSON
    # 后补一句解释，或在代码块外再输出一个括号，简单截取会误选范围。
    decoder = json.JSONDecoder()
    try:
        value, end = decoder.raw_decode(text)
        if isinstance(value, (dict, list)):
            return text[:end]
    except json.JSONDecodeError:
        pass

    for start, char in enumerate(text):
        if char not in "{[":
            continue
        try:
            value, end = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, (dict, list)):
            return text[start : start + end]

    preview = re.sub(r"\s+", " ", text[:180])
    raise ValueError(f"无法从 LLM 输出中解析 JSON（返回长度{len(text)}，开头：{preview}）")


def parse_narration_output(raw: str) -> NarrationOutput:
    """严格校验 LLM 输出，异常时抛出 ValueError。"""
    json_text = _extract_json(raw)
    data = json.loads(json_text)
    # 兼容两种顶层结构：直接数组 或 {shots: [...]}
    if isinstance(data, list):
        data = {"projectSummary": "", "shots": data, "unverifiedFacts": []}
    data["unverifiedFacts"] = _normalise_unverified_facts(data.get("unverifiedFacts", []))
    return NarrationOutput.model_validate(data)


def parse_evidence_output(raw: str) -> EvidenceOutput:
    json_text = _extract_json(raw)
    return EvidenceOutput.model_validate(json.loads(json_text))


def parse_outline_output(raw: str) -> OutlineOutput:
    json_text = _extract_json(raw)
    return OutlineOutput.model_validate(json.loads(json_text))


def parse_chapter_draft_output(raw: str) -> ChapterDraftOutput:
    json_text = _extract_json(raw)
    data = json.loads(json_text)
    if isinstance(data, list):
        data = {"shots": data, "unverifiedFacts": []}
    data["unverifiedFacts"] = _normalise_unverified_facts(data.get("unverifiedFacts", []))
    return ChapterDraftOutput.model_validate(data)


def parse_resegment_output(raw: str) -> ResegmentOutput:
    json_text = _extract_json(raw)
    data = json.loads(json_text)
    if isinstance(data, list):
        data = {"shots": data}
    return ResegmentOutput.model_validate(data)


def parse_qa_review_output(raw: str) -> QAReviewOutput:
    json_text = _extract_json(raw)
    return QAReviewOutput.model_validate(json.loads(json_text))


def _normalise_unverified_facts(items: Any) -> list[str]:
    """兼容模型把未验证事实写成对象数组的情况。"""
    if not isinstance(items, list):
        return []
    normalised: list[str] = []
    for item in items:
        if isinstance(item, str):
            if item.strip():
                normalised.append(item.strip())
            continue
        if isinstance(item, dict):
            fact = item.get("fact") or item.get("text") or item.get("statement")
            if fact:
                status = item.get("status") or item.get("factCheckStatus")
                normalised.append(f"{fact}（{status}）" if status else str(fact))
    return list(dict.fromkeys(normalised))
