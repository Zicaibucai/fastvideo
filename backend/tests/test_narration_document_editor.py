"""连续文稿编辑器的保存与重新分镜接口测试。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def _auth_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@fastvideo.cn", "password": "admin123456"},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_document_save_rebuilds_beats_and_resegment_preserves_text():
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project = client.post(
            "/api/v1/projects",
            json={"name": "连续文稿编辑测试"},
            headers=headers,
        )
        assert project.status_code == 201, project.text
        project_id = project.json()["id"]

        for sequence, narration in enumerate(("先完成基坑开挖。再组织支护施工。", "主体结构分区流水推进。"), start=1):
            response = client.post(
                f"/api/v1/projects/{project_id}/storyboard",
                json={
                    "project_id": project_id,
                    "sequence": sequence,
                    "title": f"镜头{sequence}",
                    "section": "施工方案",
                    "narration": narration,
                    "duration_seconds": 12,
                    "visual_type": "generated_image",
                },
                headers=headers,
            )
            assert response.status_code == 201, response.text

        shots = client.get(f"/api/v1/projects/{project_id}/storyboard", headers=headers).json()
        edited = "先完成基坑开挖。随后组织支护施工，并复核开挖面。"
        saved = client.patch(
            f"/api/v1/projects/{project_id}/storyboard/document",
            json={
                "shots": [
                    {"shot_id": shots[0]["id"], "narration": edited},
                    {"shot_id": shots[1]["id"], "narration": shots[1]["narration"]},
                ]
            },
            headers=headers,
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["beat_count"] == 3

        beats = client.get(f"/api/v1/projects/{project_id}/storyboard/beats", headers=headers).json()
        assert beats[0]["narration"] == "先完成基坑开挖。"
        assert beats[-1]["narration"] == "主体结构分区流水推进。"

        resegmented = client.post(
            f"/api/v1/projects/{project_id}/storyboard/resegment",
            json={"target_shot_count": 2},
            headers=headers,
        )
        assert resegmented.status_code == 202, resegmented.text
        task = client.get(f"/api/v1/tasks/{resegmented.json()['task_id']}", headers=headers)
        assert task.status_code == 200, task.text
        assert task.json()["status"] == "success", task.text
        refreshed = client.get(f"/api/v1/projects/{project_id}/storyboard", headers=headers).json()
        assert "基坑开挖" in "".join(shot["narration"] for shot in refreshed)
        assert "主体结构分区流水推进" in "".join(shot["narration"] for shot in refreshed)
