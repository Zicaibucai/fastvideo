"""工程参数台账路由：列表、确认、驳回、修改、冲突对比。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.services.revision import bump_revision, check_revision
from app.services.review_service import on_target_content_changed
from app.services.permissions import (
    get_project_access,
    PERM_DOCUMENT_EDIT,
    PERM_DOCUMENT_UPLOAD,
    PERM_DOCUMENT_VIEW,
    PERM_EXPORT_DEMO,
    PERM_EXPORT_FORMAL,
    PERM_EXPORT_VIEW,
    PERM_FACT_EDIT,
    PERM_FACT_VIEW,
    PERM_MEDIA_EDIT,
    PERM_MEDIA_VIEW,
    PERM_PROJECT_VIEW,
    PERM_SCORING_VIEW,
    PERM_STORYBOARD_EDIT,
    PERM_STORYBOARD_VIEW,
    PERM_VIDEO_EDIT,
    PERM_VIDEO_VIEW,
    PERM_VOICE_EDIT,
    PERM_VOICE_VIEW,
)
from app.core.exceptions import NotFoundError
from app.models.base import utc_now_iso
from app.models.extracted_fact import ExtractedFact
from app.models.project import Project
from app.models.source_document import SourceDocument
from app.models.user import User
from app.schemas.document import ExtractedFactOut, FactConfirmRequest, FactConfirmResult

router = APIRouter(prefix="/projects/{project_id}/facts", tags=["工程信息核对"])


_GENERIC_SCOPES = {"本项目", "本工程", "地上", "地下", "场地", "工程范围"}
_MATERIAL_CATEGORIES = {
    "材料与设备", "材料等级", "材料参数", "材料规格", "材料性能", "设备型号", "设备参数", "机械设备", "机电配置",
    "混凝土/材料等级",
}
_SIZE_CATEGORIES = {"几何尺寸", "尺寸", "直径", "长度", "宽度", "高度", "厚度", "距离", "间距", "角度", "深度", "基坑参数", "降水参数", "尺寸/标高/深度"}
_AREA_CATEGORIES = {"面积", "工程量", "数量", "重量", "体积", "金额", "分值", "面积/工程量"}
_TIME_CATEGORIES = {"日期", "时间", "工期", "工期参数", "进度参数", "进度计划", "工期/日期"}
_CONCRETE_CATEGORIES = {"材料等级", "材料性能", "强度", "配合比", "坍落度", "预制率"}


def _display_scope(value: object) -> str | None:
    scope = str(value or "").strip()
    if not scope or scope in _GENERIC_SCOPES:
        return None
    # AI 可能把整段工序描述写进 scope；台账只保留可筛选的工程对象，
    # 具体细节仍在“原文依据”中完整保留。
    if "主楼" in scope:
        return "主楼"
    if "塔楼" in scope:
        return "塔楼"
    if "裙房" in scope or "裙楼" in scope:
        return "裙房"
    if "地下" in scope:
        return "地下室"
    if "人防" in scope:
        return "人防区"
    if "基坑" in scope:
        return "基坑"
    # 对象尽量保留 AI 从上下文识别出的具体名称，例如“塔吊STT603”，
    # 不要一律压扁为“设备”；泛化对象仍归到可筛选的设备类别。
    if "塔吊" in scope:
        return scope[:48]
    if "钢柱" in scope:
        return "钢柱"
    if "设备" in scope:
        return "设备"
    if "场地" in scope or "生活区" in scope:
        return "场地/生活区"
    if "住宅" in scope:
        return "住宅"
    if "钢结构" in scope:
        return "钢结构"
    if "混凝土" in scope:
        return "混凝土"
    return None


def _display_category(value: object, label: str) -> str:
    category = str(value or "").strip()
    if label == "混凝土强度等级" or category in _CONCRETE_CATEGORIES or category == "混凝土/材料等级":
        return "混凝土/材料等级"
    if category in _MATERIAL_CATEGORIES or label in {"材料/型号", "材质"}:
        return "材料与设备"
    if category in _SIZE_CATEGORIES or label in {"埋深", "深度", "标高", "高度", "长度", "宽度", "厚度", "尺寸", "截面", "管径", "直径"}:
        return "尺寸/标高/深度"
    if category in _AREA_CATEGORIES:
        return "面积/工程量"
    if category in _TIME_CATEGORIES:
        return "工期/日期"
    if category in {"场地", "工程范围", "临建布置", "资源配置"}:
        return "工程范围/场地"
    if category in {"施工参数", "施工操作参数", "施工措施参数", "施工组织参数", "安全防护参数", "绿色施工参数"} or "施工" in category or "进度" in category or "运输" in category:
        return "施工参数"
    if category in {"编号", "名称", "规格", "型号"}:
        return "编号/规格"
    if category in {"工程参数", "工程概况", "结构参数", "构造参数", "设计参数", "质量目标"}:
        return "工程参数"
    return "其他参数"


def _fact_view(fact: ExtractedFact) -> tuple[str, str | None, str | None, str]:
    from app.services.fact_extractor import AUTO_USE_THRESHOLD, FACT_TYPE_LABELS, REVIEW_THRESHOLD

    metadata = fact.metadata_json or {}
    label = str(metadata.get("display_name") or FACT_TYPE_LABELS.get(fact.fact_name) or "待识别数字")
    scope = _display_scope(metadata.get("scope"))
    category = _display_category(metadata.get("category"), label)
    if fact.verification_status == "confirmed":
        usage = "confirmed"
    elif fact.verification_status == "rejected":
        usage = "rejected"
    elif fact.verification_status == "conflict":
        usage = "conflict"
    elif fact.confidence >= AUTO_USE_THRESHOLD:
        usage = "auto_usable"
    elif fact.confidence < REVIEW_THRESHOLD:
        usage = "low_confidence"
    else:
        usage = "review"
    return label, scope, category, usage


def _get_project(db: Session, project_id: str, user: User, permission: str = PERM_FACT_VIEW) -> Project:
    """统一项目访问：成员校验 + 细粒度权限（非成员 404，权限不足 403）。"""
    return get_project_access(db, project_id, user, permission).project


def _to_out(fact: ExtractedFact, doc_names: dict[str, str] | None = None) -> ExtractedFactOut:
    label, scope, category, usage = _fact_view(fact)
    doc_names = doc_names or {}
    candidates = [
        {
            **candidate,
            "document_name": candidate.get("document_name") or doc_names.get(candidate.get("document_id")),
        }
        for candidate in (fact.candidates or [])
    ] or None
    return ExtractedFactOut(
        id=fact.id,
        project_id=fact.project_id,
        document_id=fact.document_id,
        document_name=doc_names.get(fact.document_id),
        page_number=fact.page_number,
        source_order=(fact.metadata_json or {}).get("source_order"),
        location_label=fact.location_label,
        fact_type=fact.fact_type,
        fact_name=fact.fact_name,
        fact_label=label,
        fact_value=fact.fact_value,
        scope=scope,
        category=category,
        usage_status=usage,
        unit=fact.unit,
        source_quote=fact.source_quote,
        confidence=fact.confidence,
        verification_status=fact.verification_status,
        confirmed_by=fact.confirmed_by,
        confirmed_at=fact.confirmed_at,
        candidates=candidates,
        revision=fact.revision or 1,
        created_at=fact.created_at,
        updated_at=fact.updated_at,
    )


@router.get("", response_model=list[ExtractedFactOut], summary="参数列表")
def list_facts(
    project_id: str,
    status: str | None = Query(None, description="unverified/confirmed/rejected/conflict"),
    fact_type: str | None = None,
    unverified_only: bool = False,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> list[ExtractedFactOut]:
    _get_project(db, project_id, current, PERM_FACT_VIEW)
    query = db.query(ExtractedFact).filter(ExtractedFact.project_id == project_id)
    if status:
        query = query.filter(ExtractedFact.verification_status == status)
    if unverified_only:
        query = query.filter(ExtractedFact.verification_status.in_(["unverified", "conflict"]))
    if fact_type:
        query = query.filter(ExtractedFact.fact_type == fact_type)

    facts = query.all()
    usage_rank = {"confirmed": 0, "auto_usable": 0, "conflict": 1, "review": 2, "low_confidence": 3, "rejected": 4}
    facts.sort(
        key=lambda fact: (
            usage_rank.get(_fact_view(fact)[3], 2),
            fact.page_number if fact.page_number is not None else 10**9,
            (fact.metadata_json or {}).get("source_order", 10**9),
            fact.created_at,
        )
    )

    doc_names = {
        d.id: d.file_name
        for d in db.query(SourceDocument)
        .filter(SourceDocument.project_id == project_id)
        .all()
    }
    return [_to_out(f, doc_names) for f in facts]


@router.get("/conflicts", response_model=list[ExtractedFactOut], summary="冲突参数")
def list_conflicts(
    project_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> list[ExtractedFactOut]:
    _get_project(db, project_id, current, PERM_FACT_VIEW)
    facts = (
        db.query(ExtractedFact)
        .filter(
            ExtractedFact.project_id == project_id,
            ExtractedFact.verification_status == "conflict",
        )
        .all()
    )
    doc_names = {
        d.id: d.file_name
        for d in db.query(SourceDocument)
        .filter(SourceDocument.project_id == project_id)
        .all()
    }
    return [_to_out(f, doc_names) for f in facts]


@router.get("/types", response_model=dict, summary="参数类型枚举")
def fact_types() -> dict:
    from app.services.fact_extractor import FACT_TYPE_LABELS

    return FACT_TYPE_LABELS


@router.post("/{fact_id}/confirm", response_model=FactConfirmResult, summary="确认/驳回/修改参数")
def confirm_fact(
    project_id: str,
    fact_id: str,
    payload: FactConfirmRequest,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> FactConfirmResult:
    _get_project(db, project_id, current, PERM_FACT_EDIT)
    fact = db.get(ExtractedFact, fact_id)
    if not fact or fact.project_id != project_id:
        raise NotFoundError("参数不存在")
    check_revision(fact, payload.base_revision)

    # 若确认采用新值，则把同名的其它事实标记为 rejected（排除候选）
    if payload.status == "confirmed" and payload.fact_value:
        # 更新当前事实
        fact.fact_value = payload.fact_value
        if payload.unit:
            fact.unit = payload.unit
        fact.verification_status = "confirmed"
        fact.confirmed_by = current.username
        fact.confirmed_at = utc_now_iso()
        fact.candidates = None

        # 只有已有稳定语义的同名候选才互相排除。全量数字候选共享
        # numeric_candidate 类型，确认一条不能把其它数字一起驳回。
        if fact.fact_type != "numeric_candidate":
            from app.services.fact_extractor import _fact_conflict_key

            target_key = _fact_conflict_key(fact)
            others = (
                db.query(ExtractedFact)
                .filter(
                    ExtractedFact.project_id == project_id,
                    ExtractedFact.fact_name == fact.fact_name,
                    ExtractedFact.id != fact.id,
                )
                .all()
            )
            for other in others:
                if other.verification_status != "confirmed" and _fact_conflict_key(other) == target_key:
                    other.verification_status = "rejected"
                    other.candidates = None
    else:
        fact.verification_status = payload.status
        fact.confirmed_by = current.username if payload.status == "confirmed" else None
        fact.confirmed_at = (
            utc_now_iso() if payload.status == "confirmed" else None
        )
        if payload.status == "rejected":
            fact.candidates = None

    bump_revision(fact)
    db.flush()
    # 工程信息变更：挂起的审核失效，已批准的标记为“批准后已变更”
    on_target_content_changed(
        db, project_id=project_id, target_type="facts", actor=current
    )
    on_target_content_changed(
        db, project_id=project_id, target_type="fact", target_id=fact.id, actor=current
    )
    db.commit()

    # 同步到 Project 快捷字段
    from app.services.fact_extractor import sync_project_key_params

    all_facts = (
        db.query(ExtractedFact)
        .filter(ExtractedFact.project_id == project_id)
        .all()
    )
    project = _get_project(db, project_id, current)
    sync_project_key_params(db, project, all_facts)

    return FactConfirmResult(id=fact_id, status=fact.verification_status, message="已更新")
