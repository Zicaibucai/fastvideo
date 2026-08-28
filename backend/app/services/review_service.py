"""审核服务：提交、决定、快照、批准失效与正式导出门禁。

核心约定：
- 审核请求绑定提交时的内容版本（target_revision + snapshot_hash + 快照 JSON）。
- 内容再次修改后：pending 请求自动 superseded；approved 请求保留记录，
  但派生状态变为 approved_but_changed（哈希不一致），不再视为有效批准。
- 审核人默认不得审核自己提交的内容；owner/超管可带理由覆盖（is_override）。
- 驳回或要求修改必须填写原因。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.models.base import utc_now
from app.models.collaboration import (
    COMMENT_STATUS_OPEN,
    REVIEW_DECISIONS,
    REVIEW_STATUS_APPROVED,
    REVIEW_STATUS_CHANGES_REQUESTED,
    REVIEW_STATUS_PENDING,
    REVIEW_STATUS_SUPERSEDED,
    REVIEWABLE_TARGET_TYPES,
    TARGET_TYPE_FACT,
    TARGET_TYPE_FACTS,
    TARGET_TYPE_PROJECT,
    TARGET_TYPE_SHOT,
    TARGET_TYPE_STORYBOARD,
    TARGET_TYPE_VIDEO_PROJECT,
    ProjectComment,
    ReviewDecision,
    ReviewRequest,
)
from app.models.extracted_fact import ExtractedFact
from app.models.project import Project
from app.models.storyboard_shot import StoryboardShot
from app.models.user import User
from app.models.video_project import VideoProject
from app.models.video_segment import VideoSegment
from app.services.audit import log_action
from app.services.notification_service import notify
from app.services.target_resolver import resolve_target

# 派生审核状态
STATE_DRAFT = "draft"
STATE_IN_REVIEW = "in_review"
STATE_CHANGES_REQUESTED = "changes_requested"
STATE_APPROVED = "approved"
STATE_APPROVED_BUT_CHANGED = "approved_but_changed"

REVIEW_POLICY_DISABLED = "disabled"
REVIEW_POLICY_RECOMMENDED = "recommended"
REVIEW_POLICY_REQUIRED = "required"


def _canonical_hash(payload: Any) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compute_snapshot(
    db: Session, project_id: str, target_type: str, target_id: str | None
) -> tuple[int, str, dict, str]:
    """计算目标当前内容快照。返回 (revision, hash, snapshot, label)。"""
    if target_type == TARGET_TYPE_FACTS:
        facts = list(
            db.scalars(
                select(ExtractedFact)
                .where(ExtractedFact.project_id == project_id)
                .order_by(ExtractedFact.fact_type, ExtractedFact.id)
            ).all()
        )
        items = [
            {
                "id": f.id,
                "type": f.fact_type,
                "value": f.fact_value,
                "unit": f.unit,
                "status": f.verification_status,
                "revision": f.revision or 1,
            }
            for f in facts
        ]
        revision = sum(item["revision"] for item in items) or 1
        snapshot = {"kind": "facts", "count": len(items), "items": items}
        return revision, _canonical_hash(snapshot), snapshot, "工程信息（整体）"

    if target_type == TARGET_TYPE_FACT:
        fact = db.get(ExtractedFact, target_id or "")
        if not fact or fact.project_id != project_id:
            raise NotFoundError("审核目标不存在或不属于当前项目")
        meta = fact.metadata_json or {}
        snapshot = {
            "kind": "fact",
            "id": fact.id,
            "type": fact.fact_type,
            "value": fact.fact_value,
            "unit": fact.unit,
            "status": fact.verification_status,
            "revision": fact.revision or 1,
        }
        label = f"工程参数·{meta.get('label') or fact.fact_type or '参数'}"
        return fact.revision or 1, _canonical_hash(snapshot), snapshot, label

    if target_type == TARGET_TYPE_STORYBOARD:
        shots = list(
            db.scalars(
                select(StoryboardShot)
                .where(
                    StoryboardShot.project_id == project_id,
                    StoryboardShot.is_active.is_(True),
                )
                .order_by(StoryboardShot.sequence, StoryboardShot.id)
            ).all()
        )
        items = [
            {
                "id": s.id,
                "sequence": s.sequence,
                "title": s.title,
                "narration_hash": s.narration_hash,
                "narration": s.narration,
                "revision": s.revision or 1,
            }
            for s in shots
        ]
        revision = sum(item["revision"] for item in items) or 1
        snapshot = {"kind": "storyboard", "count": len(items), "items": items}
        return revision, _canonical_hash(snapshot), snapshot, "解说词与分镜（整份文稿）"

    if target_type == TARGET_TYPE_SHOT:
        shot = db.get(StoryboardShot, target_id or "")
        if not shot or shot.project_id != project_id:
            raise NotFoundError("审核目标不存在或不属于当前项目")
        snapshot = {
            "kind": "shot",
            "id": shot.id,
            "sequence": shot.sequence,
            "title": shot.title,
            "narration": shot.narration,
            "visual_prompt": shot.visual_prompt,
            "revision": shot.revision or 1,
        }
        label = f"分镜 {shot.sequence}·{shot.title or '未命名'}"
        return shot.revision or 1, _canonical_hash(snapshot), snapshot, label

    if target_type == TARGET_TYPE_VIDEO_PROJECT:
        vp = db.get(VideoProject, target_id or "")
        if not vp or vp.project_id != project_id:
            raise NotFoundError("审核目标不存在或不属于当前项目")
        segments = list(
            db.scalars(
                select(VideoSegment)
                .where(VideoSegment.video_project_id == vp.id)
                .order_by(VideoSegment.sequence, VideoSegment.id)
            ).all()
        )
        items = [
            {
                "id": s.id,
                "sequence": s.sequence,
                "duration": s.duration,
                "visual_asset_id": s.visual_asset_id,
                "audio_version_id": s.audio_version_id,
                "input_hash": s.input_hash,
                "revision": s.revision or 1,
            }
            for s in segments
        ]
        revision = (vp.revision or 1) + sum(item["revision"] for item in items)
        snapshot = {
            "kind": "video_project",
            "id": vp.id,
            "name": vp.name,
            "vp_revision": vp.revision or 1,
            "timeline": vp.timeline,
            "segments": items,
        }
        return revision, _canonical_hash(snapshot), snapshot, f"视频工程·{vp.name}"

    raise NotFoundError(f"目标类型 {target_type} 不支持提交审核")


def _latest_effective_request(
    db: Session, project_id: str, target_type: str, target_id: str | None
) -> ReviewRequest | None:
    """目标最近一次未失效的审核请求（pending/changes_requested/approved）。"""
    stmt = (
        select(ReviewRequest)
        .where(
            ReviewRequest.project_id == project_id,
            ReviewRequest.target_type == target_type,
            ReviewRequest.status.in_(
                [REVIEW_STATUS_PENDING, REVIEW_STATUS_CHANGES_REQUESTED, REVIEW_STATUS_APPROVED]
            ),
        )
        .order_by(ReviewRequest.submitted_at.desc())
        .limit(1)
    )
    if target_id is None:
        stmt = stmt.where(ReviewRequest.target_id.is_(None))
    else:
        stmt = stmt.where(ReviewRequest.target_id == target_id)
    return db.scalar(stmt)


def target_review_state(
    db: Session, project_id: str, target_type: str, target_id: str | None = None
) -> dict[str, Any]:
    """派生目标当前审核状态。"""
    request = _latest_effective_request(db, project_id, target_type, target_id)
    if request is None:
        return {"state": STATE_DRAFT, "request": None, "changed_after_approval": False}
    if request.status == REVIEW_STATUS_PENDING:
        return {"state": STATE_IN_REVIEW, "request": request, "changed_after_approval": False}
    if request.status == REVIEW_STATUS_CHANGES_REQUESTED:
        return {
            "state": STATE_CHANGES_REQUESTED,
            "request": request,
            "changed_after_approval": False,
        }
    # approved：比较当前内容哈希
    try:
        _, current_hash, _, _ = compute_snapshot(db, project_id, target_type, target_id)
    except NotFoundError:
        current_hash = None
    changed = current_hash is not None and current_hash != request.snapshot_hash
    return {
        "state": STATE_APPROVED_BUT_CHANGED if changed else STATE_APPROVED,
        "request": request,
        "changed_after_approval": changed,
    }


def submit_review(
    db: Session,
    *,
    access,
    target_type: str,
    target_id: str | None,
    note: str | None,
    assigned_reviewer_id: str | None,
) -> ReviewRequest:
    """提交审核：同一目标的旧 pending/changes_requested 请求自动 superseded。"""
    project_id = access.project.id
    if target_type not in REVIEWABLE_TARGET_TYPES:
        raise ConflictError(f"目标类型 {target_type} 不支持提交审核")
    # 目标归属校验
    resolve_target(db, project_id, target_type, target_id)

    if assigned_reviewer_id:
        from app.services.permissions import assert_active_member

        reviewer = assert_active_member(db, project_id, assigned_reviewer_id)
        from app.services.permissions import PERM_REVIEW_DECIDE, permissions_for_role

        if PERM_REVIEW_DECIDE not in permissions_for_role(reviewer.role):
            raise ConflictError("指定的审核人不具备审核权限")
        if assigned_reviewer_id == access.user.id:
            raise ConflictError("不能指定自己为审核人")

    revision, snapshot_hash, snapshot, label = compute_snapshot(
        db, project_id, target_type, target_id
    )

    now = utc_now()
    # 旧的未完成请求失效
    stmt = select(ReviewRequest).where(
        ReviewRequest.project_id == project_id,
        ReviewRequest.target_type == target_type,
        ReviewRequest.status.in_([REVIEW_STATUS_PENDING, REVIEW_STATUS_CHANGES_REQUESTED]),
    )
    stmt = stmt.where(ReviewRequest.target_id.is_(None)) if target_id is None else stmt.where(
        ReviewRequest.target_id == target_id
    )
    for old in db.scalars(stmt).all():
        old.status = REVIEW_STATUS_SUPERSEDED

    request = ReviewRequest(
        project_id=project_id,
        target_type=target_type,
        target_id=target_id,
        target_label=label,
        target_revision=revision,
        snapshot_hash=snapshot_hash,
        snapshot=snapshot,
        note=note,
        submitted_by=access.user.id,
        assigned_reviewer_id=assigned_reviewer_id,
        status=REVIEW_STATUS_PENDING,
        submitted_at=now,
    )
    db.add(request)
    db.flush()

    # 通知：指定审核人或所有具备审核权限的成员
    from app.services.permissions import PERM_REVIEW_DECIDE, active_members, permissions_for_role

    recipients = []
    if assigned_reviewer_id:
        recipients = [assigned_reviewer_id]
    else:
        recipients = [
            m.user_id
            for m in active_members(db, project_id)
            if PERM_REVIEW_DECIDE in permissions_for_role(m.role)
        ]
    for uid in recipients:
        notify(
            db,
            user_id=uid,
            type="review_requested",
            title=f"收到审核请求：{label}",
            body=note,
            project_id=project_id,
            link=f"/project/{project_id}/collaboration?tab=reviews",
            actor=access.user,
        )

    log_action(
        db,
        user=access.user,
        project_id=project_id,
        action="review_submit",
        entity_type=target_type,
        entity_id=target_id,
        detail={
            "request_id": request.id,
            "target_revision": revision,
            "snapshot_hash": snapshot_hash[:16],
            "assigned_reviewer_id": assigned_reviewer_id,
        },
        commit=False,
    )
    return request


def decide_review(
    db: Session,
    *,
    access,
    request: ReviewRequest,
    decision: str,
    comment: str | None,
    override_reason: str | None = None,
) -> ReviewDecision:
    """审核决定。审核人默认不得审核自己提交的内容；覆盖必须填写理由。"""
    if decision not in REVIEW_DECISIONS:
        raise ConflictError(f"无效的审核决定：{decision}")
    if request.status != REVIEW_STATUS_PENDING:
        raise ConflictError("该审核请求已处理或已失效")

    is_override = False
    if request.submitted_by == access.user.id:
        # 自审需要管理覆盖权限（owner/超管）且必须填写理由
        from app.services.permissions import PERM_ADMIN_OVERRIDE

        if PERM_ADMIN_OVERRIDE not in access.permissions:
            raise ForbiddenError("不能审核自己提交的内容（需要项目所有者带理由覆盖）")
        if not override_reason or not override_reason.strip():
            raise ConflictError("审核自己提交的内容属于管理覆盖，必须填写理由")
        is_override = True

    if decision in ("changes_requested", "rejected") and not (comment and comment.strip()):
        raise ConflictError("要求修改或驳回时必须填写原因")

    now = utc_now()
    record = ReviewDecision(
        review_request_id=request.id,
        reviewer_id=access.user.id,
        decision=decision,
        comment=comment,
        is_override=is_override,
        override_reason=override_reason,
    )
    db.add(record)

    if decision == "approved":
        request.status = REVIEW_STATUS_APPROVED
    elif decision == "changes_requested":
        request.status = REVIEW_STATUS_CHANGES_REQUESTED
    else:
        # rejected 视为要求修改的强形式，同样回到待修改状态
        request.status = REVIEW_STATUS_CHANGES_REQUESTED
    request.decided_at = now

    label = request.target_label or request.target_type
    if decision == "approved":
        notify(
            db,
            user_id=request.submitted_by,
            type="review_approved",
            title=f"审核通过：{label}",
            body=comment,
            project_id=request.project_id,
            link=f"/project/{request.project_id}/collaboration?tab=reviews",
            actor=access.user,
        )
    else:
        notify(
            db,
            user_id=request.submitted_by,
            type="review_changes_requested",
            title=f"审核要求修改：{label}",
            body=comment,
            project_id=request.project_id,
            link=f"/project/{request.project_id}/collaboration?tab=reviews",
            actor=access.user,
        )
        # 审核意见自动沉淀为可跟踪评论（可一键转待办）
        db.add(
            ProjectComment(
                project_id=request.project_id,
                target_type=request.target_type,
                target_id=request.target_id,
                target_label=label,
                author_id=access.user.id,
                body=comment or "",
                is_blocking=True,
                status=COMMENT_STATUS_OPEN,
            )
        )

    log_action(
        db,
        user=access.user,
        project_id=request.project_id,
        action="review_decide",
        entity_type=request.target_type,
        entity_id=request.target_id,
        detail={
            "request_id": request.id,
            "decision": decision,
            "is_override": is_override,
            "override_reason": override_reason if is_override else None,
        },
        note=override_reason if is_override else None,
        commit=False,
    )
    return record


def on_target_content_changed(
    db: Session,
    *,
    project_id: str,
    target_type: str,
    target_id: str | None = None,
    actor: User | None = None,
) -> None:
    """目标内容被修改后调用：

    - pending 审核请求 → superseded（针对旧版本的待审已无意义）
    - approved 请求保留，派生状态自动变为 approved_but_changed
    - 通知提交人/批准人“已批准内容发生变更”
    """
    stmt = select(ReviewRequest).where(
        ReviewRequest.project_id == project_id,
        ReviewRequest.target_type == target_type,
        ReviewRequest.status.in_([REVIEW_STATUS_PENDING, REVIEW_STATUS_APPROVED]),
    )
    stmt = stmt.where(ReviewRequest.target_id.is_(None)) if target_id is None else stmt.where(
        ReviewRequest.target_id == target_id
    )
    requests = list(db.scalars(stmt).all())
    if not requests:
        return
    for request in requests:
        if request.status == REVIEW_STATUS_PENDING:
            request.status = REVIEW_STATUS_SUPERSEDED
        else:
            # 已批准内容发生变更：通知提交人与批准人
            label = request.target_label or request.target_type
            approver_ids = {
                d.reviewer_id for d in request.decisions if d.decision == "approved"
            }
            for uid in {request.submitted_by, *approver_ids}:
                notify(
                    db,
                    user_id=uid,
                    type="approved_content_changed",
                    title=f"已批准内容发生变更：{label}",
                    body="批准后的内容被再次修改，原批准状态已失效，需要重新提交审核。",
                    project_id=project_id,
                    link=f"/project/{project_id}/collaboration?tab=reviews",
                    actor=actor,
                )
            log_action(
                db,
                user=actor,
                project_id=project_id,
                action="approved_content_changed",
                entity_type=target_type,
                entity_id=target_id,
                detail={"request_id": request.id},
                commit=False,
            )


def review_gate_issues(db: Session, vp: VideoProject, mode: str) -> list[dict]:
    """正式导出前的协作审核门禁。

    - review_policy=disabled：不检查
    - recommended：审核未完成时给 warning；演示导出醒目标记
    - required：关键工程信息 / 当前分镜文稿 / 当前视频工程均已批准，
      且不存在未解决的阻断级审核意见，否则 error
    """
    project = db.get(Project, vp.project_id) if vp.project_id else None
    if project is None:
        return []
    policy = project.review_policy or REVIEW_POLICY_RECOMMENDED
    if policy == REVIEW_POLICY_DISABLED:
        return []

    issues: list[dict] = []
    level = "error" if (policy == REVIEW_POLICY_REQUIRED and mode == "formal") else "warning"

    checks = [
        (TARGET_TYPE_FACTS, None, "关键工程信息"),
        (TARGET_TYPE_STORYBOARD, None, "当前分镜文稿"),
        (TARGET_TYPE_VIDEO_PROJECT, vp.id, "当前视频工程"),
    ]
    incomplete: list[str] = []
    for target_type, target_id, label in checks:
        state = target_review_state(db, project.id, target_type, target_id)
        if state["state"] != STATE_APPROVED:
            state_label = {
                STATE_DRAFT: "未提交审核",
                STATE_IN_REVIEW: "审核中",
                STATE_CHANGES_REQUESTED: "审核要求修改",
                STATE_APPROVED_BUT_CHANGED: "批准后已变更",
            }.get(state["state"], state["state"])
            incomplete.append(f"{label}（{state_label}）")

    # 未解决的阻断级审核意见
    blocking = db.scalar(
        select(ProjectComment.id)
        .where(
            ProjectComment.project_id == project.id,
            ProjectComment.is_blocking.is_(True),
            ProjectComment.status == COMMENT_STATUS_OPEN,
        )
        .limit(1)
    )

    if incomplete:
        issues.append({
            "level": level,
            "code": "review_incomplete",
            "message": "协作审核未完成：" + "、".join(incomplete),
        })
    if blocking:
        issues.append({
            "level": level,
            "code": "review_blocking_comments",
            "message": "存在未解决的阻断级审核意见，请在协作中心处理后再导出。",
        })
    return issues
