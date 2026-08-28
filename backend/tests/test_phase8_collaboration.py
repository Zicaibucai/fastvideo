"""Phase 8：项目成员、邀请与权限矩阵测试。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.database import SessionLocal

from collab_utils import (
    API,
    add_member,
    admin_headers,
    create_project,
    create_shot,
    create_user,
    get_member_id,
    invite_and_accept,
)


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def admin(client):
    return admin_headers(client)


@pytest.fixture()
def owner(client, admin):
    return create_user(client, admin, "owner")


@pytest.fixture()
def project_id(client, owner):
    return create_project(client, owner["headers"])


# ---------- 成员回填与创建 ----------

def test_new_project_owner_auto_member(client, owner, project_id):
    resp = client.get(f"{API}/projects/{project_id}/members", headers=owner["headers"])
    assert resp.status_code == 200
    members = resp.json()
    assert len(members) == 1
    assert members[0]["user_id"] == owner["id"]
    assert members[0]["role"] == "owner"
    assert members[0]["status"] == "active"


def test_project_detail_exposes_my_role_and_permissions(client, owner, project_id):
    resp = client.get(f"{API}/projects/{project_id}", headers=owner["headers"])
    assert resp.status_code == 200
    data = resp.json()
    assert data["my_role"] == "owner"
    assert "member.manage" in data["my_permissions"]
    assert data["review_policy"] == "recommended"
    assert data["revision"] >= 1


# ---------- 邀请流程 ----------

def test_invitation_full_flow(client, owner, admin, project_id):
    user = create_user(client, admin, "editor")
    data = invite_and_accept(client, owner["headers"], project_id, user["email"], "media_editor", user["headers"])
    assert data["invite_token"]
    assert data["invite_url"].endswith(data["invite_token"])
    # 成员已加入
    members = client.get(f"{API}/projects/{project_id}/members", headers=owner["headers"]).json()
    roles = {m["user_id"]: m["role"] for m in members}
    assert roles[user["id"]] == "media_editor"
    # 被邀请人现在可以访问项目
    resp = client.get(f"{API}/projects/{project_id}", headers=user["headers"])
    assert resp.status_code == 200
    assert resp.json()["my_role"] == "media_editor"
    # 被邀请人收到通知
    notif = client.get(f"{API}/notifications", headers=user["headers"]).json()
    assert any(n["type"] == "project_invited" for n in notif)


def test_invitation_list_does_not_leak_token(client, owner, admin, project_id):
    user = create_user(client, admin, "viewer")
    client.post(
        f"{API}/projects/{project_id}/invitations",
        json={"email": user["email"], "role": "viewer"},
        headers=owner["headers"],
    )
    resp = client.get(f"{API}/projects/{project_id}/invitations", headers=owner["headers"])
    assert resp.status_code == 200
    for inv in resp.json():
        assert "invite_token" not in inv
        assert "token_hash" not in inv


def test_accept_wrong_email_forbidden(client, owner, admin, project_id):
    user_a = create_user(client, admin, "a")
    user_b = create_user(client, admin, "b")
    data = invite_and_accept(client, owner["headers"], project_id, user_a["email"], "viewer")
    resp = client.post(
        f"{API}/invitations/accept",
        json={"token": data["invite_token"]},
        headers=user_b["headers"],
    )
    assert resp.status_code == 403


def test_accept_twice_conflict(client, owner, admin, project_id):
    user = create_user(client, admin, "twice")
    data = invite_and_accept(client, owner["headers"], project_id, user["email"], "viewer", user["headers"])
    resp = client.post(
        f"{API}/invitations/accept",
        json={"token": data["invite_token"]},
        headers=user["headers"],
    )
    assert resp.status_code == 409


def test_revoked_invitation_cannot_accept(client, owner, admin, project_id):
    user = create_user(client, admin, "revoked")
    data = invite_and_accept(client, owner["headers"], project_id, user["email"], "viewer")
    revoke = client.post(
        f"{API}/projects/{project_id}/invitations/{data['id']}/revoke",
        headers=owner["headers"],
    )
    assert revoke.status_code == 200
    resp = client.post(
        f"{API}/invitations/accept",
        json={"token": data["invite_token"]},
        headers=user["headers"],
    )
    assert resp.status_code == 409


def test_expired_invitation_cannot_accept(client, owner, admin, project_id):
    from datetime import timedelta

    from app.models.base import utc_now
    from app.models.collaboration import ProjectInvitation

    user = create_user(client, admin, "expired")
    data = invite_and_accept(client, owner["headers"], project_id, user["email"], "viewer")
    db = SessionLocal()
    try:
        inv = db.get(ProjectInvitation, data["id"])
        inv.expires_at = utc_now() - timedelta(days=1)
        db.commit()
    finally:
        db.close()
    resp = client.post(
        f"{API}/invitations/accept",
        json={"token": data["invite_token"]},
        headers=user["headers"],
    )
    assert resp.status_code == 409
    # 状态被标记为 expired
    invitations = client.get(f"{API}/projects/{project_id}/invitations", headers=owner["headers"]).json()
    assert any(i["status"] == "expired" for i in invitations)


def test_resend_invitation_invalidates_old_token(client, owner, admin, project_id):
    user = create_user(client, admin, "resend")
    data = invite_and_accept(client, owner["headers"], project_id, user["email"], "viewer")
    resend = client.post(
        f"{API}/projects/{project_id}/invitations/{data['id']}/resend",
        headers=owner["headers"],
    )
    assert resend.status_code == 200, resend.text
    new_token = resend.json()["invite_token"]
    # 旧令牌失效
    old = client.post(
        f"{API}/invitations/accept", json={"token": data["invite_token"]}, headers=user["headers"]
    )
    assert old.status_code == 409
    # 新令牌可用
    new = client.post(
        f"{API}/invitations/accept", json={"token": new_token}, headers=user["headers"]
    )
    assert new.status_code == 200, new.text


def test_invite_existing_member_conflict(client, owner, admin, project_id):
    user = create_user(client, admin, "member")
    add_member(client, owner["headers"], project_id, user, "viewer")
    resp = client.post(
        f"{API}/projects/{project_id}/invitations",
        json={"email": user["email"], "role": "viewer"},
        headers=owner["headers"],
    )
    assert resp.status_code == 409


def test_invite_owner_role_rejected(client, owner, admin, project_id):
    user = create_user(client, admin, "noowner")
    resp = client.post(
        f"{API}/projects/{project_id}/invitations",
        json={"email": user["email"], "role": "owner"},
        headers=owner["headers"],
    )
    assert resp.status_code in (409, 422)


# ---------- 最后一个 owner 保护 ----------

def test_last_owner_cannot_leave(client, owner, project_id):
    resp = client.post(f"{API}/projects/{project_id}/members/leave", headers=owner["headers"])
    assert resp.status_code == 409


def test_last_owner_cannot_be_removed(client, owner, project_id):
    member_id = get_member_id(client, owner["headers"], project_id, owner["id"])
    resp = client.delete(
        f"{API}/projects/{project_id}/members/{member_id}",
        headers=owner["headers"],
    )
    assert resp.status_code == 409


def test_last_owner_cannot_be_demoted(client, owner, project_id):
    member_id = get_member_id(client, owner["headers"], project_id, owner["id"])
    resp = client.patch(
        f"{API}/projects/{project_id}/members/{member_id}",
        json={"role": "bid_manager"},
        headers=owner["headers"],
    )
    assert resp.status_code == 409


# ---------- 所有权转移 ----------

def test_ownership_transfer(client, owner, admin, project_id):
    user = create_user(client, admin, "manager")
    add_member(client, owner["headers"], project_id, user, "bid_manager")
    resp = client.post(
        f"{API}/projects/{project_id}/transfer-ownership",
        json={"new_owner_user_id": user["id"], "reason": "工作交接"},
        headers=owner["headers"],
    )
    assert resp.status_code == 200, resp.text
    members = client.get(f"{API}/projects/{project_id}/members", headers=user["headers"]).json()
    roles = {m["user_id"]: m["role"] for m in members}
    assert roles[user["id"]] == "owner"
    assert roles[owner["id"]] == "bid_manager"
    # 新 owner 可以管理成员；原 owner 降级后不能
    assert client.get(
        f"{API}/projects/{project_id}/invitations", headers=user["headers"]
    ).status_code == 200
    assert client.get(
        f"{API}/projects/{project_id}/invitations", headers=owner["headers"]
    ).status_code == 403
    # 项目 owner_id 同步更新
    detail = client.get(f"{API}/projects/{project_id}", headers=user["headers"]).json()
    assert detail["owner_id"] == user["id"]
    # 新 owner 收到通知
    notif = client.get(f"{API}/notifications", headers=user["headers"]).json()
    assert any(n["type"] == "ownership_transferred" for n in notif)


def test_bid_manager_cannot_transfer_ownership(client, owner, admin, project_id):
    user = create_user(client, admin, "bm")
    add_member(client, owner["headers"], project_id, user, "bid_manager")
    resp = client.post(
        f"{API}/projects/{project_id}/transfer-ownership",
        json={"new_owner_user_id": user["id"]},
        headers=user["headers"],
    )
    assert resp.status_code == 403


# ---------- 成员提升限制 ----------

def test_member_cannot_escalate_self(client, owner, admin, project_id):
    user = create_user(client, admin, "esc")
    add_member(client, owner["headers"], project_id, user, "viewer")
    member_id = get_member_id(client, owner["headers"], project_id, user["id"])
    # viewer 无 member.manage
    resp = client.patch(
        f"{API}/projects/{project_id}/members/{member_id}",
        json={"role": "owner"},
        headers=user["headers"],
    )
    assert resp.status_code == 403
    # bid_manager 也无 member.manage
    bm = create_user(client, admin, "bm2")
    add_member(client, owner["headers"], project_id, bm, "bid_manager")
    resp = client.patch(
        f"{API}/projects/{project_id}/members/{member_id}",
        json={"role": "owner"},
        headers=bm["headers"],
    )
    assert resp.status_code == 403
    # owner 直接授予 owner 角色也被拒绝（必须走所有权转移）
    resp = client.patch(
        f"{API}/projects/{project_id}/members/{member_id}",
        json={"role": "owner"},
        headers=owner["headers"],
    )
    assert resp.status_code == 409


def test_remove_member(client, owner, admin, project_id):
    user = create_user(client, admin, "remove")
    add_member(client, owner["headers"], project_id, user, "viewer")
    member_id = get_member_id(client, owner["headers"], project_id, user["id"])
    resp = client.delete(
        f"{API}/projects/{project_id}/members/{member_id}",
        headers=owner["headers"],
    )
    assert resp.status_code == 200
    # 被移除后无法再访问项目（404）
    assert client.get(f"{API}/projects/{project_id}", headers=user["headers"]).status_code == 404


# ---------- 跨项目访问 ----------

def test_non_member_cannot_access_other_project(client, owner, admin, project_id):
    outsider = create_user(client, admin, "outsider")
    assert client.get(f"{API}/projects/{project_id}", headers=outsider["headers"]).status_code == 404
    assert client.get(f"{API}/projects/{project_id}/facts", headers=outsider["headers"]).status_code == 404
    assert client.get(f"{API}/projects/{project_id}/members", headers=outsider["headers"]).status_code == 404
    assert client.get(f"{API}/projects/{project_id}/comments", headers=outsider["headers"]).status_code == 404
    # 项目列表不包含他人项目
    lst = client.get(f"{API}/projects", headers=outsider["headers"]).json()
    assert all(p["id"] != project_id for p in lst["items"])


def test_project_list_includes_shared_projects(client, owner, admin, project_id):
    user = create_user(client, admin, "shared")
    add_member(client, owner["headers"], project_id, user, "viewer")
    lst = client.get(f"{API}/projects", headers=user["headers"]).json()
    assert any(p["id"] == project_id for p in lst["items"])


# ---------- 角色权限矩阵 ----------

@pytest.fixture()
def matrix_setup(client, owner, admin, project_id):
    users = {
        role: create_user(client, admin, role.replace("_", ""))
        for role in ("bid_manager", "technical_editor", "media_editor", "reviewer", "viewer")
    }
    for role, user in users.items():
        add_member(client, owner["headers"], project_id, user, role)
    shot = create_shot(client, owner["headers"], project_id)
    return {"users": users, "shot": shot}


def test_viewer_read_only(client, owner, project_id, matrix_setup):
    viewer = matrix_setup["users"]["viewer"]
    h = viewer["headers"]
    shot_id = matrix_setup["shot"]["id"]
    assert client.get(f"{API}/projects/{project_id}/storyboard", headers=h).status_code == 200
    assert client.get(f"{API}/projects/{project_id}/facts", headers=h).status_code == 200
    # 不能编辑分镜
    assert client.patch(
        f"{API}/projects/{project_id}/storyboard/{shot_id}",
        json={"title": "x"}, headers=h,
    ).status_code == 403
    # 不能评论
    assert client.post(
        f"{API}/projects/{project_id}/comments",
        json={"target_type": "storyboard", "body": "hi"}, headers=h,
    ).status_code == 403
    # 不能提交审核
    assert client.post(
        f"{API}/projects/{project_id}/reviews",
        json={"target_type": "storyboard"}, headers=h,
    ).status_code == 403
    # 不能创建待办
    assert client.post(
        f"{API}/projects/{project_id}/work-items",
        json={"title": "t"}, headers=h,
    ).status_code == 403
    # 不能邀请成员
    assert client.post(
        f"{API}/projects/{project_id}/invitations",
        json={"email": "x@fastvideo.cn", "role": "viewer"}, headers=h,
    ).status_code == 403
    # 不能正式导出（权限层面）
    assert client.post(
        f"{API}/video-projects/anything/export/formal", headers=h
    ).status_code in (403, 404)


def test_reviewer_cannot_edit_but_can_decide(client, owner, project_id, matrix_setup):
    reviewer = matrix_setup["users"]["reviewer"]
    h = reviewer["headers"]
    shot_id = matrix_setup["shot"]["id"]
    assert client.patch(
        f"{API}/projects/{project_id}/storyboard/{shot_id}",
        json={"title": "x"}, headers=h,
    ).status_code == 403
    assert client.post(
        f"{API}/projects/{project_id}/reviews",
        json={"target_type": "storyboard"}, headers=h,
    ).status_code == 403  # reviewer 不提交审核
    # reviewer 可以评论
    assert client.post(
        f"{API}/projects/{project_id}/comments",
        json={"target_type": "storyboard", "body": "请检查第二分镜"}, headers=h,
    ).status_code == 201


def test_technical_editor_scope(client, owner, project_id, matrix_setup, db_fact):
    tech = matrix_setup["users"]["technical_editor"]
    h = tech["headers"]
    shot_id = matrix_setup["shot"]["id"]
    # 可以核对工程参数
    assert client.post(
        f"{API}/projects/{project_id}/facts/{db_fact.id}/confirm",
        json={"status": "confirmed"}, headers=h,
    ).status_code == 200
    # 不能编辑分镜
    assert client.patch(
        f"{API}/projects/{project_id}/storyboard/{shot_id}",
        json={"title": "x"}, headers=h,
    ).status_code == 403
    # 不能管理成员
    assert client.get(f"{API}/projects/{project_id}/invitations", headers=h).status_code == 403
    # 不能删除项目
    assert client.delete(f"{API}/projects/{project_id}", headers=h).status_code == 403


def test_media_editor_scope(client, owner, project_id, matrix_setup, db_fact):
    media = matrix_setup["users"]["media_editor"]
    h = media["headers"]
    shot_id = matrix_setup["shot"]["id"]
    # 可以编辑分镜
    assert client.patch(
        f"{API}/projects/{project_id}/storyboard/{shot_id}",
        json={"title": "新标题"}, headers=h,
    ).status_code == 200
    # 不能核对工程参数（fact.edit）
    assert client.post(
        f"{API}/projects/{project_id}/facts/{db_fact.id}/confirm",
        json={"status": "confirmed"}, headers=h,
    ).status_code == 403
    # 不能管理成员
    assert client.post(
        f"{API}/projects/{project_id}/invitations",
        json={"email": "y@fastvideo.cn", "role": "viewer"}, headers=h,
    ).status_code == 403


def test_bid_manager_scope(client, owner, project_id, matrix_setup):
    bm = matrix_setup["users"]["bid_manager"]
    h = bm["headers"]
    shot_id = matrix_setup["shot"]["id"]
    # 可以编辑分镜、提交审核、分派待办
    assert client.patch(
        f"{API}/projects/{project_id}/storyboard/{shot_id}",
        json={"title": "负责人修改"}, headers=h,
    ).status_code == 200
    assert client.post(
        f"{API}/projects/{project_id}/reviews",
        json={"target_type": "storyboard"}, headers=h,
    ).status_code == 201
    viewer_id = matrix_setup["users"]["viewer"]["id"]
    assert client.post(
        f"{API}/projects/{project_id}/work-items",
        json={"title": "整理资料", "assignee_id": viewer_id}, headers=h,
    ).status_code == 201
    # 不能管理成员/删除项目/变更审核策略
    assert client.post(
        f"{API}/projects/{project_id}/invitations",
        json={"email": "z@fastvideo.cn", "role": "viewer"}, headers=h,
    ).status_code == 403
    assert client.delete(f"{API}/projects/{project_id}", headers=h).status_code == 403
    detail = client.get(f"{API}/projects/{project_id}", headers=h).json()
    assert client.patch(
        f"{API}/projects/{project_id}",
        json={"review_policy": "required", "base_revision": detail["revision"]},
        headers=h,
    ).status_code == 403
    # 不能查看审计记录
    assert client.get(f"{API}/projects/{project_id}/audit-logs", headers=h).status_code == 403


@pytest.fixture()
def db_fact(project_id):
    from collab_utils import create_fact

    db = SessionLocal()
    try:
        return create_fact(db, project_id)
    finally:
        db.close()


def test_audit_view_owner_only(client, owner, project_id):
    resp = client.get(f"{API}/projects/{project_id}/audit-logs", headers=owner["headers"])
    assert resp.status_code == 200


# ---------- 账号停用联动 ----------

def test_suspended_user_membership_blocked(client, owner, admin, project_id):
    user = create_user(client, admin, "suspend")
    add_member(client, owner["headers"], project_id, user, "media_editor")
    # 管理员停用账号
    resp = client.patch(
        f"{API}/admin/users/{user['id']}", json={"is_active": False}, headers=admin
    )
    assert resp.status_code == 200
    # 成员关系保留但标记 suspended
    members = client.get(f"{API}/projects/{project_id}/members", headers=owner["headers"]).json()
    status = {m["user_id"]: m["status"] for m in members}
    assert status[user["id"]] == "suspended"
    # 恢复后成员关系恢复
    resp = client.patch(
        f"{API}/admin/users/{user['id']}", json={"is_active": True}, headers=admin
    )
    assert resp.status_code == 200
    members = client.get(f"{API}/projects/{project_id}/members", headers=owner["headers"]).json()
    status = {m["user_id"]: m["status"] for m in members}
    assert status[user["id"]] == "active"
