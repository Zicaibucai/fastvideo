from __future__ import annotations

from app.api.v1 import auth


def test_login_failure_limiter_caps_attempts_and_can_reset(monkeypatch):
    monkeypatch.setattr(auth.settings, "use_celery", False)
    key = "127.0.0.1:attacker@example.com"
    now = 1000.0
    auth._clear_login_failures(key)
    for _ in range(auth._LOGIN_MAX_FAILURES):
        auth._record_login_failure(key, now)
    assert auth._login_limited(key, now)
    auth._clear_login_failures(key)
    assert not auth._login_limited(key, now)
