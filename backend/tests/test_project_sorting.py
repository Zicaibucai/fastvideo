"""投标项目列表排序测试。"""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from app.main import app


def _auth_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@fastvideo.cn", "password": "admin123456"},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_projects_default_to_last_entered_sort() -> None:
    with TestClient(app) as client:
        headers = _auth_headers(client)
        first = client.post(
            "/api/v1/projects", json={"name": "排序测试 A"}, headers=headers
        )
        second = client.post(
            "/api/v1/projects", json={"name": "排序测试 B"}, headers=headers
        )
        assert first.status_code == 201, first.text
        assert second.status_code == 201, second.text
        first_id = first.json()["id"]
        second_id = second.json()["id"]

        entered_first = client.post(f"/api/v1/projects/{first_id}/enter", headers=headers)
        assert entered_first.status_code == 200, entered_first.text
        time.sleep(0.01)
        entered_second = client.post(f"/api/v1/projects/{second_id}/enter", headers=headers)
        assert entered_second.status_code == 200, entered_second.text

        response = client.get("/api/v1/projects", headers=headers)
        assert response.status_code == 200, response.text
        ids = [item["id"] for item in response.json()["items"]]
        assert ids.index(second_id) < ids.index(first_id)

        named = client.get(
            "/api/v1/projects",
            params={"sort_by": "name", "sort_order": "asc"},
            headers=headers,
        )
        assert named.status_code == 200, named.text
        names = [item["name"] for item in named.json()["items"]]
        assert names == sorted(names)
