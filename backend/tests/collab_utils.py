"""Phase 8 协作测试的共享工具。"""

from __future__ import annotations

import uuid

API = "/api/v1"


def admin_headers(client) -> dict:
    resp = client.post(
        f"{API}/auth/login",
        json={"email": "admin@fastvideo.cn", "password": "admin123456"},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def create_user(client, admin: dict, prefix: str, password: str = "pass123456") -> dict:
    """通过管理员创建用户并登录，返回 {"id":..., "headers":..., "email":...}"""
    suffix = uuid.uuid4().hex[:8]
    email = f"{prefix}-{suffix}@fastvideo.cn"
    resp = client.post(
        f"{API}/admin/users",
        json={"email": email, "username": f"{prefix}{suffix}", "password": password},
        headers=admin,
    )
    assert resp.status_code == 201, resp.text
    user_id = resp.json()["id"]
    login = client.post(f"{API}/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return {
        "id": user_id,
        "email": email,
        "headers": {"Authorization": f"Bearer {login.json()['access_token']}"},
    }


def create_project(client, headers: dict, name: str = "协作测试项目") -> str:
    resp = client.post(f"{API}/projects", json={"name": name}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def invite_and_accept(client, owner_headers: dict, project_id: str, email: str, role: str,
                      invitee_headers: dict | None = None) -> dict:
    """owner 邀请 + 被邀请人接受，返回邀请创建响应。"""
    resp = client.post(
        f"{API}/projects/{project_id}/invitations",
        json={"email": email, "role": role},
        headers=owner_headers,
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    if invitee_headers is not None:
        acc = client.post(
            f"{API}/invitations/accept",
            json={"token": data["invite_token"]},
            headers=invitee_headers,
        )
        assert acc.status_code == 200, acc.text
    return data


def add_member(client, owner_headers: dict, project_id: str, user: dict, role: str) -> None:
    invite_and_accept(client, owner_headers, project_id, user["email"], role, user["headers"])


def get_member_id(client, headers: dict, project_id: str, user_id: str) -> str:
    resp = client.get(f"{API}/projects/{project_id}/members", headers=headers)
    assert resp.status_code == 200, resp.text
    for m in resp.json():
        if m["user_id"] == user_id:
            return m["id"]
    raise AssertionError(f"member {user_id} not found")


def create_fact(db, project_id: str, fact_type: str = "建筑面积"):
    """直接插入一条工程参数（绕过文档解析）。"""
    from app.models.extracted_fact import ExtractedFact

    fact = ExtractedFact(
        project_id=project_id,
        fact_type=fact_type,
        fact_name=fact_type,
        fact_value="50000",
        unit="m²",
        verification_status="confirmed",
        confidence=0.9,
    )
    db.add(fact)
    db.commit()
    db.refresh(fact)
    return fact


def create_shot(client, headers: dict, project_id: str, title: str = "分镜一") -> dict:
    resp = client.post(
        f"{API}/projects/{project_id}/storyboard",
        json={"project_id": project_id, "title": title, "narration": "这里是解说词"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def create_video_project(client, headers: dict, project_id: str, name: str = "投标视频") -> dict:
    resp = client.post(
        f"{API}/projects/{project_id}/video-projects",
        json={"name": name},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()
