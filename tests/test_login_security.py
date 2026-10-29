import json
from unittest.mock import MagicMock, patch
import pytest
from db import execute, query
from handlers.auth_handlers import handle_account_login
from services.auth import create_user, hash_password

class MockLoginHandler:
    def __init__(self, secure=False):
        self.secure = secure
        self.status = None
        self.data = None
        self.extra_headers = []

    def _is_secure(self):
        return self.secure

    def _make_auth_cookie_header(self, token):
        return ("Set-Cookie", f"argos_token={token}; Path=/")

    def _send_json(self, status, data, extra_headers=None):
        self.status = status
        self.data = data
        self.extra_headers = extra_headers or []


def test_login_timing_defense_and_three_tier_lockout(tmp_db, monkeypatch):
    execute("INSERT OR IGNORE INTO departments(id, name) VALUES ('dev', 'Development')")
    salt, hpwd = hash_password("ValidPassword123!")
    create_user("AliceUser", "alice_test", "dev", "alice@example.com", salt, hpwd, status="active", role="member")

    # 1. Non-existent user: dummy hash MUST be computed to defend against timing attacks
    with patch("services.auth.hash_password", wraps=hash_password) as mock_hash:
        handler = MockLoginHandler()
        payload_nonexistent = json.dumps({"username": "ghost_user", "password": "AnyPassword123!"}).encode()
        handle_account_login(handler, payload_nonexistent, "192.168.1.100")
        assert handler.status == 401
        assert mock_hash.called, "Dummy hash was not computed for non-existent user!"

    # 2. Tier 1 Lockout: 5 failed attempts from same IP on same account -> 6th attempt gets 429 + Retry-After
    ip1 = "192.168.1.10"
    wrong_payload = json.dumps({"username": "alice_test", "password": "WrongPassword!"}).encode()
    for i in range(5):
        h = MockLoginHandler()
        handle_account_login(h, wrong_payload, ip1)
        assert h.status == 401

    # 6th attempt from ip1: MUST get 429 and Retry-After header
    h_locked = MockLoginHandler()
    handle_account_login(h_locked, wrong_payload, ip1)
    assert h_locked.status == 429
    retry_afters = [val for header, val in h_locked.extra_headers if header.lower() == "retry-after"]
    assert len(retry_afters) == 1, "Missing Retry-After header on 429 response"
    assert int(retry_afters[0]) > 0

    # 3. Different IP (ip2) for the same user is NOT locked by Tier 1 (5 attempts) since account total is < 20
    ip2 = "192.168.1.20"
    correct_payload = json.dumps({"username": "alice_test", "password": "ValidPassword123!"}).encode()
    h_other_ip = MockLoginHandler()
    handle_account_login(h_other_ip, correct_payload, ip2)
    assert h_other_ip.status == 200, f"Expected 200 for ip2 but got {h_other_ip.status}: {h_other_ip.data}"


def test_case_insensitive_unique_username_and_format_validation(tmp_db, monkeypatch):
    from handlers.auth_handlers import handle_account_register
    execute("INSERT OR IGNORE INTO departments(id, name) VALUES ('dev', 'Development')")
    monkeypatch.setenv("ALLOW_PUBLIC_REGISTER", "1")

    # 1. Invalid username format containing '@'
    h_invalid = MockLoginHandler()
    payload_invalid = json.dumps({
        "username": "a@b.com",
        "name": "Invalid User",
        "org": "dev",
        "password": "ValidPassword123!"
    }).encode()
    handle_account_register(h_invalid, payload_invalid, "192.168.1.100")
    assert h_invalid.status == 400
    assert "error" in h_invalid.data

    # 2. Register 'AliceUser'
    h_alice1 = MockLoginHandler()
    payload_alice1 = json.dumps({
        "username": "Alice_Case",
        "name": "Alice First",
        "org": "dev",
        "password": "ValidPassword123!"
    }).encode()
    handle_account_register(h_alice1, payload_alice1, "192.168.1.100")
    assert h_alice1.status == 200

    # 3. Register 'alice_case' (different case) -> MUST be rejected with 409
    h_alice2 = MockLoginHandler()
    payload_alice2 = json.dumps({
        "username": "alice_case",
        "name": "Alice Second",
        "org": "dev",
        "password": "ValidPassword123!"
    }).encode()
    handle_account_register(h_alice2, payload_alice2, "192.168.1.100")
    assert h_alice2.status == 409
    assert h_alice2.data.get("exists") is True


def test_migration_graceful_on_duplicate_identities(tmp_path):
    import sqlite3
    from db import init_db
    test_db = str(tmp_path / "test_dup.db")

    # Manually create sqlite database with duplicate lower identities before migration 6
    conn = sqlite3.connect(test_db)
    conn.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, name TEXT);")
    conn.execute("INSERT INTO schema_migrations (version, name) VALUES (1, 'baseline'), (2, 'v2.1'), (3, 'v2.2'), (4, 'v2.3');")
    conn.execute("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            username TEXT,
            name TEXT,
            dept_id TEXT,
            email TEXT,
            salt TEXT,
            password_hash TEXT,
            iterations INTEGER,
            is_admin INTEGER,
            role TEXT,
            disabled INTEGER,
            status TEXT,
            created_at TEXT
        );
    """)
    conn.execute("INSERT INTO users (id, username, email) VALUES (1, 'Charlie', 'c@example.com')")
    conn.execute("INSERT INTO users (id, username, email) VALUES (2, 'charlie', 'other@example.com')")
    conn.commit()
    conn.close()

    # Reconnect and run DB init pointing to test_db
    with patch("db.get_db_path", return_value=test_db):
        init_db()  # Should NOT raise sqlite3.IntegrityError or any crash

    # Verify migration 6 was safely skipped due to duplicates
    conn = sqlite3.connect(test_db)
    mig_rows = conn.execute("SELECT version FROM schema_migrations WHERE version = 6").fetchall()
    assert len(mig_rows) == 0, "Migration 6 should have been skipped when duplicates exist"
    conn.close()


def test_registration_department_validation(tmp_db, monkeypatch):
    from handlers.auth_handlers import handle_account_register
    monkeypatch.setenv("ALLOW_PUBLIC_REGISTER", "1")

    # 1. Invalid department ID
    h_bad_dept = MockLoginHandler()
    payload_bad_dept = json.dumps({
        "username": "user_bad_dept",
        "name": "User Bad Dept",
        "org": "nonexistent_dept_xyz",
        "password": "ValidPassword123!"
    }).encode()
    handle_account_register(h_bad_dept, payload_bad_dept, "192.168.1.100")
    assert h_bad_dept.status == 400
    assert h_bad_dept.data.get("error") == "유효하지 않은 부서입니다."

    # 2. Missing department ID
    h_no_dept = MockLoginHandler()
    payload_no_dept = json.dumps({
        "username": "user_no_dept",
        "name": "User No Dept",
        "password": "ValidPassword123!"
    }).encode()
    handle_account_register(h_no_dept, payload_no_dept, "192.168.1.100")
    assert h_no_dept.status == 400
    assert h_no_dept.data.get("error") == "유효하지 않은 부서입니다."

    # 3. Empty departments in system
    with patch("handlers.auth_handlers.read_departments", return_value=[]):
        h_empty_depts = MockLoginHandler()
        handle_account_register(h_empty_depts, payload_bad_dept, "192.168.1.100")
        assert h_empty_depts.status == 400
        assert "등록 가능한 부서가 없습니다" in h_empty_depts.data.get("error", "")
