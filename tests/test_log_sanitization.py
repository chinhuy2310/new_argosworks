import os
import pytest
import logging
import db as db_module

def test_sql_params_not_logged_on_error(tmp_db, caplog):
    """Verify duplicate insert error does not log sensitive parameters (hash, salt) into logs."""
    sensitive_salt = "super_secret_salt_xyz123"
    sensitive_hash = "super_secret_hash_abc789"
    
    # Insert department first
    tmp_db.execute("INSERT OR IGNORE INTO departments (id, name) VALUES (?, ?)", ("dev", "Dev"))
    
    # Insert first user
    tmp_db.execute(
        "INSERT INTO users (username, name, email, password_hash, salt, role, dept_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("test_sanitization_user", "Test User", "test_sanitization@example.com", sensitive_hash, sensitive_salt, "member", "dev")
    )
    
    caplog.clear()
    with caplog.at_level(logging.ERROR):
        with pytest.raises(Exception):
            # Attempt duplicate insert with another sensitive salt/hash
            tmp_db.execute(
                "INSERT INTO users (username, name, email, password_hash, salt, role, dept_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("test_sanitization_user", "Duplicate User", "test_dup@example.com", "second_secret_hash_456", "second_secret_salt_456", "member", "dev")
            )
            
    # Sensitive params should NOT be present in log text
    assert "second_secret_hash_456" not in caplog.text
    assert "second_secret_salt_456" not in caplog.text
    assert "Params: <" in caplog.text


def test_sql_params_debug_env(monkeypatch, caplog):
    """Verify ARGOS_LOG_SQL_PARAMS=1 enables parameter logging and warns at startup."""
    from db import _safe_params, _check_sql_params_debug
    
    # When disabled
    monkeypatch.delenv("ARGOS_LOG_SQL_PARAMS", raising=False)
    assert _safe_params(["secret"]) == "<1 params>"
    assert _safe_params([]) == "<none>"
    assert _safe_params(None) == "<none>"
    
    # When enabled
    monkeypatch.setenv("ARGOS_LOG_SQL_PARAMS", "1")
    assert _safe_params(["secret"]) == "['secret']"
    
    # Warning log
    db_module._WARNED_SQL_PARAMS = False
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        _check_sql_params_debug()
    assert "[SECURITY WARNING] ARGOS_LOG_SQL_PARAMS=1 is active" in caplog.text


def test_audit_failure_metric_and_logging(monkeypatch, capsys):
    """Verify audit logger failure increments metric and logs structured warning without swallowing."""
    from services.audit_logger import log_audit, get_audit_failure_count
    import services.audit_logger as al
    import sqlite3

    initial_count = get_audit_failure_count()

    def mock_execute(*args, **kwargs):
        raise sqlite3.OperationalError("disk full simulated")

    monkeypatch.setattr(al, "execute", mock_execute)

    # Should not raise exception
    log_audit(session={"name": "testuser"}, ip="1.2.3.4", action="LOGIN_ATTEMPT", target_type="auth", target_id="testuser")

    captured = capsys.readouterr()
    assert get_audit_failure_count() == initial_count + 1
    assert "write failed: action=LOGIN_ATTEMPT target=auth/testuser err=OperationalError" in captured.err


def test_router_audit_swallow_and_metric(monkeypatch, capsys):
    """Verify router._audit catches exceptions, increments failure metric, and does not leak secrets."""
    import router
    from services.audit_logger import get_audit_failure_count

    initial_count = get_audit_failure_count()

    def mock_log_audit(*args, **kwargs):
        raise RuntimeError("simulated audit failure in router")

    monkeypatch.setattr("services.audit_logger.log_audit", mock_log_audit)

    # Must not raise to callers
    router._audit(
        session={"name": "admin"},
        ip="10.0.0.1",
        action="CHANGE_PASSWORD",
        target_type="user",
        target_id="admin",
        details={"old_password": "super_secret_pw_123"}
    )

    captured = capsys.readouterr()
    assert get_audit_failure_count() == initial_count + 1
    assert "write failed: action=CHANGE_PASSWORD target=user/admin err=RuntimeError" in captured.err
    assert "super_secret_pw_123" not in captured.err
    assert "super_secret_pw_123" not in captured.out


def test_login_label_sanitization():
    """Verify login_label sanitizes unknown usernames into pseudonymous fingerprints."""
    from utils.text import login_label

    # Known account returns canonical username
    assert login_label({"username": "alice", "id": 1}, "anything") == "alice"
    assert login_label({"name": "Bob", "id": 2}, "anything") == "Bob"

    # Unknown account returns keyed anon fingerprint with length
    pasted_pwd = "MySecretP@ssword123!"
    lbl = login_label(None, pasted_pwd)
    assert lbl.startswith("anon:")
    assert f"/len={len(pasted_pwd)}" in lbl
    assert pasted_pwd not in lbl

    # Empty string
    assert login_label(None, "") == "anon:empty/len=0"


def test_failed_login_does_not_leak_pasted_password(tmp_db):
    """Verify entering a password in the login identifier does not leak into audit logs."""
    import json
    from handlers.auth_handlers import handle_account_login

    class DummyHandler:
        def __init__(self):
            self.status = None
            self.body = None
        def _send_json(self, status, body, extra_headers=None):
            self.status = status
            self.body = body

    handler = DummyHandler()
    pasted_pwd = "AccidentallyPastedPassword987!"
    raw_body = json.dumps({"username": pasted_pwd, "password": "some_password"}).encode("utf-8")

    handle_account_login(handler, raw_body, "192.168.10.55")

    assert handler.status == 401
    
    # Check audit_logs table
    logs = tmp_db.query("SELECT * FROM audit_logs WHERE ip = ?", ("192.168.10.55",))
    assert len(logs) > 0
    for row in logs:
        # The raw password string must NOT appear in username, target_id, or details_json
        assert pasted_pwd not in (row.get("username") or "")
        assert pasted_pwd not in (row.get("target_id") or "")
        assert pasted_pwd not in (row.get("details_json") or "")
        # Should be sanitized to anon:...
        assert (row.get("target_id") or "").startswith("anon:")


def test_login_parameter_length_limits():
    """Verify oversized username or password returns HTTP 400."""
    import json
    from handlers.auth_handlers import handle_account_login

    class DummyHandler:
        def __init__(self):
            self.status = None
            self.body = None
        def _send_json(self, status, body, extra_headers=None):
            self.status = status
            self.body = body

    handler = DummyHandler()
    
    # Username > 254
    raw_body = json.dumps({"username": "a" * 255, "password": "normal_password"}).encode("utf-8")
    handle_account_login(handler, raw_body, "127.0.0.1")
    assert handler.status == 400
    assert "잘못된 요청 파라미터입니다." in handler.body.get("error", "")

    # Password > 1024
    raw_body = json.dumps({"username": "normal_user", "password": "p" * 1025}).encode("utf-8")
    handle_account_login(handler, raw_body, "127.0.0.1")
    assert handler.status == 400
    assert "잘못된 요청 파라미터입니다." in handler.body.get("error", "")


