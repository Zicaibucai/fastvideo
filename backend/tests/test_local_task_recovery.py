"""本地长任务恢复逻辑测试。"""

from app.services import task_runner


def test_local_task_recovery_skips_mock_provider(monkeypatch):
    monkeypatch.setattr(task_runner.settings, "use_celery", False)
    monkeypatch.setattr(task_runner.settings, "ai_llm_provider", "mock")

    assert task_runner.recover_local_narration_tasks() == 0
