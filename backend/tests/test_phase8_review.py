"""Phase 8：评论、待办、审核、导出门禁、并发冲突与管理覆盖测试。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.database import SessionLocal

from collab_utils import (
    API,
    add_member,
    admin_headers,
    create_fact,
    create_project,
    create_shot,
    create_user,
    create_video_project,
)


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def ctx(client):
    """owner + editor + reviewer + 项目 + 分镜 + 参数 + 视频工程。"""
    admin = admin_headers(client)
    owner = create_user(client, admin, "owner")
    editor = create_user(client, admin, "editor")
    reviewer = create_user(client, admin, "reviewer")
    pid = create_project(client, owner["headers"])
    add_member(client, owner["headers"], pid, editor, "media_editor")
    add_member(client, owner["headers"], pid, reviewer, "reviewer")
    shot = create_shot(client, owner["headers"], pid)
    db = SessionLocal()
    try:
        fact = create_fact(db, pid)
    finally:
        db.close()
    vp = create_video_project(client, owner["headers"], pid)
    return {
        "admin": admin,
        "owner": owner,
        "editor": editor,
        "reviewer": reviewer,
        "pid": pid,
        "shot": shot,
        "fact": fact,
        "vp": vp,
    }


# ---------- 评论 ----------

def test_comment_create_reply_resolve_reopen(client, ctx):
    pid = ctx["pid"]
    h = ctx["editor"]["headers"]
    shot_id = ctx["shot"]["id"]
    # 评论挂接到分镜
    resp = client.post(
        f"{API}/projects/{pid}/comments",
        json={"target_type": "shot", "target_id": shot_id, "body": "这个分镜画面不对"},
        headers=h,
    )
    assert resp.status_code == 201, resp.text
    comment = resp.json()
    assert comment["target_label"]
    assert comment["status"] == "open"
    # reviewer 回复
    reply = client.post(
        f"{API}/projects/{pid}/comments",
        json={
            "target_type": "shot",
            "target_id": shot_id,
            "parent_id": comment["id"],
            "body": "同意，需要重新渲染",
        },
        headers=ctx["reviewer"]["headers"],
    )
    assert reply.status_code == 201
    # 回复必须同一目标
    bad = client.post(
        f"{API}/projects/{pid}/comments",
        json={
            "target_type": "storyboard",
            "parent_id": comment["id"],
            "body": "跨目标回复",
        },
        headers=ctx["reviewer"]["headers"],
    )
    assert bad.status_code == 409
    # 解决（作者以外有 comment.resolve 权限的成员）
    resolved = client.post(
        f"{API}/projects/{pid}/comments/{comment['id']}/resolve",
        headers=ctx["reviewer"]["headers"],
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved"
    # 重新打开
    reopened = client.post(
        f"{API}/projects/{pid}/comments/{comment['id']}/reopen", headers=h
    )
    assert reopened.json()["status"] == "open"
    # 列表筛选
    lst = client.get(
        f"{API}/projects/{pid}/comments?target_type=shot&target_id={shot_id}", headers=h
    ).json()
    assert len(lst) == 2


def test_comment_target_must_belong_to_project(client, ctx):
    # 跨项目目标：另一个项目的分镜
    other = create_project(client, ctx["owner"]["headers"], "另一个项目")
    other_shot = create_shot(client, ctx["owner"]["headers"], other)
    resp = client.post(
        f"{API}/projects/{ctx['pid']}/comments",
        json={"target_type": "shot", "target_id": other_shot["id"], "body": "越权评论"},
        headers=ctx["editor"]["headers"],
    )
    assert resp.status_code == 404


def test_comment_edit_delete_permissions(client, ctx):
    pid = ctx["pid"]
    resp = client.post(
        f"{API}/projects/{pid}/comments",
        json={"target_type": "storyboard", "body": "原作者评论"},
        headers=ctx["editor"]["headers"],
    )
    cid = resp.json()["id"]
    # 他人不能编辑
    assert client.patch(
        f"{API}/projects/{pid}/comments/{cid}",
        json={"body": "篡改"},
        headers=ctx["reviewer"]["headers"],
    ).status_code == 403
    # 作者可以编辑
    assert client.patch(
        f"{API}/projects/{pid}/comments/{cid}",
        json={"body": "作者修改"},
        headers=ctx["editor"]["headers"],
    ).status_code == 200
    # reviewer 不能删除他人评论（无 project.edit）
    assert client.delete(
        f"{API}/projects/{pid}/comments/{cid}", headers=ctx["reviewer"]["headers"]
    ).status_code == 403
    # owner 可以删除
    assert client.delete(
        f"{API}/projects/{pid}/comments/{cid}", headers=ctx["owner"]["headers"]
    ).status_code == 204


# ---------- 待办 ----------

def test_work_item_flow(client, ctx):
    pid = ctx["pid"]
    # 评论一键转待办
    comment = client.post(
        f"{API}/projects/{pid}/comments",
        json={"target_type": "storyboard", "body": "需要修改", "is_blocking": True},
        headers=ctx["reviewer"]["headers"],
    ).json()
    resp = client.post(
        f"{API}/projects/{pid}/work-items",
        json={
            "title": "修改分镜画面",
            "target_type": "storyboard",
            "assignee_id": ctx["editor"]["id"],
            "comment_id": comment["id"],
            "priority": "high",
        },
        headers=ctx["owner"]["headers"],
    )
    assert resp.status_code == 201, resp.text
    item = resp.json()
    assert item["status"] == "todo"
    assert item["target_label"]
    # 被分派人收到通知
    notif = client.get(f"{API}/notifications", headers=ctx["editor"]["headers"]).json()
    assert any(n["type"] == "task_assigned" for n in notif)
    # 负责人更新状态
    done = client.patch(
        f"{API}/projects/{pid}/work-items/{item['id']}",
        json={"status": "in_progress"},
        headers=ctx["editor"]["headers"],
    )
    assert done.status_code == 200
    # 筛选
    mine = client.get(
        f"{API}/projects/{pid}/work-items?mine=true", headers=ctx["editor"]["headers"]
    ).json()
    assert len(mine) == 1 and mine[0]["status"] == "in_progress"
    high = client.get(
        f"{API}/projects/{pid}/work-items?priority=high", headers=ctx["owner"]["headers"]
    ).json()
    assert len(high) == 1
    # 完成
    done = client.patch(
        f"{API}/projects/{pid}/work-items/{item['id']}",
        json={"status": "done"},
        headers=ctx["editor"]["headers"],
    )
    assert done.json()["completed_at"]


def test_work_item_assignee_must_be_member(client, ctx):
    outsider = create_user(client, ctx["admin"], "outsider")
    resp = client.post(
        f"{API}/projects/{ctx['pid']}/work-items",
        json={"title": "跨项目分派", "assignee_id": outsider["id"]},
        headers=ctx["owner"]["headers"],
    )
    assert resp.status_code in (403, 409)


def test_work_item_status_permission(client, ctx):
    pid = ctx["pid"]
    item = client.post(
        f"{API}/projects/{pid}/work-items",
        json={"title": "核对参数", "assignee_id": ctx["editor"]["id"]},
        headers=ctx["owner"]["headers"],
    ).json()
    # reviewer 无 task.update，且非负责人/创建者
    resp = client.patch(
        f"{API}/projects/{pid}/work-items/{item['id']}",
        json={"status": "done"},
        headers=ctx["reviewer"]["headers"],
    )
    assert resp.status_code == 403


# ---------- 审核 ----------

def test_review_submit_approve_flow(client, ctx):
    pid = ctx["pid"]
    # editor 提交分镜审核
    resp = client.post(
        f"{API}/projects/{pid}/reviews",
        json={"target_type": "storyboard", "note": "请审核整份文稿"},
        headers=ctx["editor"]["headers"],
    )
    assert resp.status_code == 201, resp.text
    request = resp.json()
    assert request["status"] == "pending"
    assert request["snapshot_hash"]
    assert request["target_revision"] >= 1
    # 审核状态总览
    status = client.get(
        f"{API}/projects/{pid}/review-status", headers=ctx["reviewer"]["headers"]
    ).json()
    assert status["storyboard"]["state"] == "in_review"
    # reviewer 收到通知
    notif = client.get(f"{API}/notifications", headers=ctx["reviewer"]["headers"]).json()
    assert any(n["type"] == "review_requested" for n in notif)
    # reviewer 批准
    decide = client.post(
        f"{API}/projects/{pid}/reviews/{request['id']}/decide",
        json={"decision": "approved", "comment": "内容无误"},
        headers=ctx["reviewer"]["headers"],
    )
    assert decide.status_code == 200, decide.text
    assert decide.json()["status"] == "approved"
    status = client.get(
        f"{API}/projects/{pid}/review-status", headers=ctx["reviewer"]["headers"]
    ).json()
    assert status["storyboard"]["state"] == "approved"
    # 提交人收到批准通知
    notif = client.get(f"{API}/notifications", headers=ctx["editor"]["headers"]).json()
    assert any(n["type"] == "review_approved" for n in notif)


def test_review_changes_requested_requires_comment(client, ctx):
    pid = ctx["pid"]
    request = client.post(
        f"{API}/projects/{pid}/reviews",
        json={"target_type": "storyboard"},
        headers=ctx["editor"]["headers"],
    ).json()
    # 要求修改必须填写原因
    bad = client.post(
        f"{API}/projects/{pid}/reviews/{request['id']}/decide",
        json={"decision": "changes_requested"},
        headers=ctx["reviewer"]["headers"],
    )
    assert bad.status_code == 409
    ok = client.post(
        f"{API}/projects/{pid}/reviews/{request['id']}/decide",
        json={"decision": "changes_requested", "comment": "第三分镜数据有误"},
        headers=ctx["reviewer"]["headers"],
    )
    assert ok.status_code == 200
    assert ok.json()["status"] == "changes_requested"
    # 审核意见沉淀为阻断级评论
    comments = client.get(
        f"{API}/projects/{pid}/comments?target_type=storyboard&status=open",
        headers=ctx["owner"]["headers"],
    ).json()
    assert any(c["is_blocking"] for c in comments)
    # 状态总览
    status = client.get(f"{API}/projects/{pid}/review-status", headers=ctx["owner"]["headers"]).json()
    assert status["storyboard"]["state"] == "changes_requested"


def test_resubmit_supersedes_old_request(client, ctx):
    pid = ctx["pid"]
    r1 = client.post(
        f"{API}/projects/{pid}/reviews",
        json={"target_type": "storyboard"},
        headers=ctx["editor"]["headers"],
    ).json()
    client.post(
        f"{API}/projects/{pid}/reviews/{r1['id']}/decide",
        json={"decision": "changes_requested", "comment": "需要修改"},
        headers=ctx["reviewer"]["headers"],
    )
    r2 = client.post(
        f"{API}/projects/{pid}/reviews",
        json={"target_type": "storyboard", "note": "已修改，重新提交"},
        headers=ctx["editor"]["headers"],
    ).json()
    reviews = client.get(f"{API}/projects/{pid}/reviews", headers=ctx["owner"]["headers"]).json()
    by_id = {r["id"]: r["status"] for r in reviews}
    assert by_id[r1["id"]] == "superseded"
    assert by_id[r2["id"]] == "pending"


def test_self_review_forbidden(client, ctx):
    pid = ctx["pid"]
    # editor 提交后不能自己审核
    request = client.post(
        f"{API}/projects/{pid}/reviews",
        json={"target_type": "storyboard"},
        headers=ctx["editor"]["headers"],
    ).json()
    resp = client.post(
        f"{API}/projects/{pid}/reviews/{request['id']}/decide",
        json={"decision": "approved"},
        headers=ctx["editor"]["headers"],
    )
    assert resp.status_code == 403
    # reviewer 自己提交的（reviewer 无提交权限，换 owner 提交后 reviewer 不受影响）
    # owner 自审必须填写覆盖理由
    owner_request = client.post(
        f"{API}/projects/{pid}/reviews",
        json={"target_type": "facts"},
        headers=ctx["owner"]["headers"],
    ).json()
    no_reason = client.post(
        f"{API}/projects/{pid}/reviews/{owner_request['id']}/decide",
        json={"decision": "approved"},
        headers=ctx["owner"]["headers"],
    )
    assert no_reason.status_code == 409
    with_reason = client.post(
        f"{API}/projects/{pid}/reviews/{owner_request['id']}/decide",
        json={"decision": "approved", "override_reason": "紧急投标， owner 自审"},
        headers=ctx["owner"]["headers"],
    )
    assert with_reason.status_code == 200, with_reason.text
    decisions = with_reason.json()["decisions"]
    assert decisions[0]["is_override"] is True
    # 覆盖进入审计
    logs = client.get(f"{API}/projects/{pid}/audit-logs", headers=ctx["owner"]["headers"]).json()
    assert any(l["action"] == "review_decide" for l in logs)


def test_approved_invalidated_after_edit(client, ctx):
    pid = ctx["pid"]
    shot_id = ctx["shot"]["id"]
    # 提交并批准整份文稿
    request = client.post(
        f"{API}/projects/{pid}/reviews",
        json={"target_type": "storyboard"},
        headers=ctx["editor"]["headers"],
    ).json()
    client.post(
        f"{API}/projects/{pid}/reviews/{request['id']}/decide",
        json={"decision": "approved"},
        headers=ctx["reviewer"]["headers"],
    )
    status = client.get(f"{API}/projects/{pid}/review-status", headers=ctx["owner"]["headers"]).json()
    assert status["storyboard"]["state"] == "approved"
    # 编辑分镜 → 批准失效
    shot = client.get(
        f"{API}/projects/{pid}/storyboard/{shot_id}", headers=ctx["editor"]["headers"]
    ).json()
    edit = client.patch(
        f"{API}/projects/{pid}/storyboard/{shot_id}",
        json={"narration": "修改后的解说词", "base_revision": shot["revision"]},
        headers=ctx["editor"]["headers"],
    )
    assert edit.status_code == 200
    status = client.get(f"{API}/projects/{pid}/review-status", headers=ctx["owner"]["headers"]).json()
    assert status["storyboard"]["state"] == "approved_but_changed"
    # 批准人收到“已批准内容发生变更”通知（修改者本人不重复通知）
    notif = client.get(f"{API}/notifications", headers=ctx["reviewer"]["headers"]).json()
    assert any(n["type"] == "approved_content_changed" for n in notif)


def test_pending_review_superseded_after_edit(client, ctx):
    pid = ctx["pid"]
    request = client.post(
        f"{API}/projects/{pid}/reviews",
        json={"target_type": "storyboard"},
        headers=ctx["editor"]["headers"],
    ).json()
    # 提交后再修改 → 旧请求失效
    client.patch(
        f"{API}/projects/{pid}/storyboard/{ctx['shot']['id']}",
        json={"narration": "再次修改"},
        headers=ctx["editor"]["headers"],
    )
    reviews = client.get(f"{API}/projects/{pid}/reviews", headers=ctx["owner"]["headers"]).json()
    by_id = {r["id"]: r["status"] for r in reviews}
    assert by_id[request["id"]] == "superseded"
    # 已失效的请求不能再决定
    resp = client.post(
        f"{API}/projects/{pid}/reviews/{request['id']}/decide",
        json={"decision": "approved"},
        headers=ctx["reviewer"]["headers"],
    )
    assert resp.status_code == 409


def test_review_detail_snapshot_diff(client, ctx):
    pid = ctx["pid"]
    request = client.post(
        f"{API}/projects/{pid}/reviews",
        json={"target_type": "shot", "target_id": ctx["shot"]["id"]},
        headers=ctx["editor"]["headers"],
    ).json()
    client.patch(
        f"{API}/projects/{pid}/storyboard/{ctx['shot']['id']}",
        json={"narration": "提交后修改的内容"},
        headers=ctx["editor"]["headers"],
    )
    detail = client.get(
        f"{API}/projects/{pid}/reviews/{request['id']}", headers=ctx["reviewer"]["headers"]
    ).json()
    assert detail["snapshot"]["narration"] == "这里是解说词"
    assert detail["current_snapshot"]["narration"] == "提交后修改的内容"


# ---------- 正式导出审核门禁 ----------

def _approve_all(client, ctx):
    pid = ctx["pid"]
    for target_type, target_id in (("facts", None), ("storyboard", None), ("video_project", ctx["vp"]["id"])):
        payload = {"target_type": target_type}
        if target_id:
            payload["target_id"] = target_id
        request = client.post(
            f"{API}/projects/{pid}/reviews", json=payload, headers=ctx["editor"]["headers"]
        )
        assert request.status_code == 201, request.text
        rid = request.json()["id"]
        decide = client.post(
            f"{API}/projects/{pid}/reviews/{rid}/decide",
            json={"decision": "approved"},
            headers=ctx["reviewer"]["headers"],
        )
        assert decide.status_code == 200, decide.text


def test_formal_export_review_gate(client, ctx):
    pid = ctx["pid"]
    vp_id = ctx["vp"]["id"]
    # 策略设为 required
    detail = client.get(f"{API}/projects/{pid}", headers=ctx["owner"]["headers"]).json()
    resp = client.patch(
        f"{API}/projects/{pid}",
        json={"review_policy": "required", "base_revision": detail["revision"]},
        headers=ctx["owner"]["headers"],
    )
    assert resp.status_code == 200, resp.text
    # 未审核 → 正式导出预检报 review_incomplete 错误
    check = client.post(
        f"{API}/video-projects/{vp_id}/preflight?mode=formal", headers=ctx["owner"]["headers"]
    ).json()
    review_errors = [i for i in check["issues"] if i["code"] == "review_incomplete"]
    assert review_errors and review_errors[0]["level"] == "error"
    # 全部批准 + 阻断评论解决后 → 门禁通过
    _approve_all(client, ctx)
    blocking = client.get(
        f"{API}/projects/{pid}/comments?status=open", headers=ctx["owner"]["headers"]
    ).json()
    for c in blocking:
        if c["is_blocking"]:
            client.post(
                f"{API}/projects/{pid}/comments/{c['id']}/resolve",
                headers=ctx["owner"]["headers"],
            )
    check = client.post(
        f"{API}/video-projects/{vp_id}/preflight?mode=formal", headers=ctx["owner"]["headers"]
    ).json()
    assert not [i for i in check["issues"] if i["code"].startswith("review_")]


def test_recommended_policy_warns_not_blocks(client, ctx):
    pid = ctx["pid"]
    vp_id = ctx["vp"]["id"]
    # 默认 recommended：review_incomplete 是 warning
    check = client.post(
        f"{API}/video-projects/{vp_id}/preflight?mode=formal", headers=ctx["owner"]["headers"]
    ).json()
    review_issues = [i for i in check["issues"] if i["code"] == "review_incomplete"]
    assert review_issues and review_issues[0]["level"] == "warning"


def test_disabled_policy_skips_review(client, ctx):
    pid = ctx["pid"]
    vp_id = ctx["vp"]["id"]
    detail = client.get(f"{API}/projects/{pid}", headers=ctx["owner"]["headers"]).json()
    client.patch(
        f"{API}/projects/{pid}",
        json={"review_policy": "disabled", "base_revision": detail["revision"]},
        headers=ctx["owner"]["headers"],
    )
    check = client.post(
        f"{API}/video-projects/{vp_id}/preflight?mode=formal", headers=ctx["owner"]["headers"]
    ).json()
    assert not [i for i in check["issues"] if i["code"].startswith("review_")]


def test_blocking_comment_blocks_required_export(client, ctx):
    pid = ctx["pid"]
    vp_id = ctx["vp"]["id"]
    detail = client.get(f"{API}/projects/{pid}", headers=ctx["owner"]["headers"]).json()
    client.patch(
        f"{API}/projects/{pid}",
        json={"review_policy": "required", "base_revision": detail["revision"]},
        headers=ctx["owner"]["headers"],
    )
    _approve_all(client, ctx)
    # 新增阻断级评论
    client.post(
        f"{API}/projects/{pid}/comments",
        json={"target_type": "video_project", "target_id": vp_id, "body": "导出前必须处理", "is_blocking": True},
        headers=ctx["reviewer"]["headers"],
    )
    check = client.post(
        f"{API}/video-projects/{vp_id}/preflight?mode=formal", headers=ctx["owner"]["headers"]
    ).json()
    errors = [i for i in check["issues"] if i["code"] == "review_blocking_comments"]
    assert errors and errors[0]["level"] == "error"


# ---------- 并发编辑冲突 ----------

def test_revision_conflict_returns_409(client, ctx):
    pid = ctx["pid"]
    shot_id = ctx["shot"]["id"]
    shot = client.get(f"{API}/projects/{pid}/storyboard/{shot_id}", headers=ctx["owner"]["headers"]).json()
    # 第一次修改成功
    ok = client.patch(
        f"{API}/projects/{pid}/storyboard/{shot_id}",
        json={"title": "第一次修改", "base_revision": shot["revision"]},
        headers=ctx["owner"]["headers"],
    )
    assert ok.status_code == 200
    # 另一成员基于旧版本提交 → 409
    conflict = client.patch(
        f"{API}/projects/{pid}/storyboard/{shot_id}",
        json={"title": "覆盖修改", "base_revision": shot["revision"]},
        headers=ctx["editor"]["headers"],
    )
    assert conflict.status_code == 409
    detail = conflict.json()["detail"]
    assert detail["server_revision"] == shot["revision"] + 1
    assert detail["base_revision"] == shot["revision"]
    assert "已被其他成员修改" in conflict.json()["message"] or "其他成员" in conflict.json()["message"]


def test_project_revision_conflict(client, ctx):
    pid = ctx["pid"]
    detail = client.get(f"{API}/projects/{pid}", headers=ctx["owner"]["headers"]).json()
    ok = client.patch(
        f"{API}/projects/{pid}",
        json={"description": "v2", "base_revision": detail["revision"]},
        headers=ctx["owner"]["headers"],
    )
    assert ok.status_code == 200
    conflict = client.patch(
        f"{API}/projects/{pid}",
        json={"description": "v3", "base_revision": detail["revision"]},
        headers=ctx["owner"]["headers"],
    )
    assert conflict.status_code == 409


# ---------- 超级管理员覆盖与审计 ----------

def test_superuser_bypass_audited(client, ctx):
    pid = ctx["pid"]
    admin = ctx["admin"]
    # 超管不是成员，但可以读取（绕过）
    resp = client.get(f"{API}/projects/{pid}/facts", headers=admin)
    assert resp.status_code == 200
    # 超管写操作
    resp = client.post(
        f"{API}/projects/{pid}/comments",
        json={"target_type": "storyboard", "body": "管理员检查"},
        headers=admin,
    )
    assert resp.status_code == 201
    # 审计记录包含绕行记录
    logs = client.get(f"{API}/projects/{pid}/audit-logs", headers=ctx["owner"]["headers"]).json()
    actions = [l["action"] for l in logs]
    assert "admin_project_access" in actions
    assert "admin_project_write" in actions


def test_disabled_user_cannot_operate(client, ctx):
    pid = ctx["pid"]
    client.patch(
        f"{API}/admin/users/{ctx['editor']['id']}", json={"is_active": False}, headers=ctx["admin"]
    )
    # 停用账号 token 失效（get_current_user 拒绝）
    resp = client.get(f"{API}/projects/{pid}", headers=ctx["editor"]["headers"])
    assert resp.status_code == 401


# ---------- 双用户完整流程（验收场景） ----------

def test_full_collaboration_flow(client, ctx):
    """owner 邀请 reviewer → editor 提交 → 要求修改 → 重新提交 → 批准 → 修改失效。"""
    pid = ctx["pid"]
    # 1. editor 提交分镜审核
    r1 = client.post(
        f"{API}/projects/{pid}/reviews",
        json={"target_type": "storyboard", "note": "初稿完成"},
        headers=ctx["editor"]["headers"],
    ).json()
    # 2. reviewer 要求修改
    client.post(
        f"{API}/projects/{pid}/reviews/{r1['id']}/decide",
        json={"decision": "changes_requested", "comment": "第二段工期数据与招标文件不一致"},
        headers=ctx["reviewer"]["headers"],
    )
    # 3. editor 修改并重新提交
    client.patch(
        f"{API}/projects/{pid}/storyboard/{ctx['shot']['id']}",
        json={"narration": "修正后的解说词"},
        headers=ctx["editor"]["headers"],
    )
    r2 = client.post(
        f"{API}/projects/{pid}/reviews",
        json={"target_type": "storyboard", "note": "已按意见修改"},
        headers=ctx["editor"]["headers"],
    ).json()
    # 4. reviewer 批准
    decide = client.post(
        f"{API}/projects/{pid}/reviews/{r2['id']}/decide",
        json={"decision": "approved"},
        headers=ctx["reviewer"]["headers"],
    )
    assert decide.json()["status"] == "approved"
    # 5. 再次修改 → 批准失效
    client.patch(
        f"{API}/projects/{pid}/storyboard/{ctx['shot']['id']}",
        json={"narration": "批准后再次修改"},
        headers=ctx["editor"]["headers"],
    )
    status = client.get(f"{API}/projects/{pid}/review-status", headers=ctx["owner"]["headers"]).json()
    assert status["storyboard"]["state"] == "approved_but_changed"
    # 6. 全部问题可回答：审计轨迹
    logs = client.get(f"{API}/projects/{pid}/audit-logs", headers=ctx["owner"]["headers"]).json()
    actions = {l["action"] for l in logs}
    assert {"member_invite", "member_join", "review_submit", "review_decide"} <= actions
