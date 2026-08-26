"""任务重试请求的参数约束测试。
"""

from app.schemas.task import TaskCancelRequest, TaskRetryRequest


def test_retry_and_cancel_requests_accept_task_id():
    task_id = "task-123"
    assert TaskRetryRequest(task_id=task_id).task_id == task_id
    assert TaskCancelRequest(task_id=task_id).task_id == task_id
