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
