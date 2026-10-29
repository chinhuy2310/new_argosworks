import pytest
from db import get_one, execute, query
from services.auth import create_session, get_session, hash_session_token

def test_pass_the_hash_prevented(tmp_db):
    execute("INSERT OR IGNORE INTO departments(id, name) VALUES ('dev', 'Development')")
    execute("INSERT OR IGNORE INTO users(id, name, username, dept_id, email, password_hash, salt, role, is_admin, disabled, status) "
            "VALUES (100, 'Alice', 'alice', 'dev', 'alice@test.com', 'h', 's', 'member', 0, 0, 'active')")

    raw_token = create_session(user_id=100, name_or_user_id="Alice", org="dev", email="alice@test.com")
    assert raw_token is not None

    # Retrieve the stored hash from the database directly
    row = get_one("SELECT token FROM sessions WHERE user_id = 100")
    assert row is not None
    stored_hash = row["token"]

    # 1. The original plaintext token must successfully validate
    sess = get_session(raw_token)
    assert sess is not None
    assert sess["id"] == 100

    # 2. In vulnerable pass-the-hash state, passing the stored_hash itself as token returns a valid session!
    # In secure state, passing stored_hash MUST return None because get_session hashes it again.
    sess_by_hash = get_session(stored_hash)
    assert sess_by_hash is None, "Pass-the-hash vulnerability: database token hash was accepted as a valid session token!"


def test_session_absolute_timeout_enforced(tmp_db, monkeypatch):
    import time
    from services.auth import create_session, get_session, get_session_max_age_seconds
    from db import get_one, execute

    execute("INSERT OR IGNORE INTO departments(id, name) VALUES ('dev', 'Development')")
    execute("INSERT OR IGNORE INTO users(id, name, username, dept_id, email, password_hash, salt, role, is_admin, disabled, status) "
            "VALUES (101, 'Bob', 'bob', 'dev', 'bob@test.com', 'h', 's', 'member', 0, 0, 'active')")

    current_time = 1700000000.0
    monkeypatch.setattr(time, "time", lambda: current_time)

    token = create_session(user_id=101, name_or_user_id="Bob", org="dev", email="bob@test.com")
    assert token is not None

    # Step 1: 1 day later (active session within sliding TTL and within max age)
    current_time += 86400.0
    sess = get_session(token)
    assert sess is not None
    assert sess["id"] == 101

    # Step 2: 8 days from creation (exceeds default 7 days max age = 168 hours = 604800s)
    # Even though last_active was just updated to 1 day ago (less than sliding TTL 24h if we set it recent):
    current_time = 1700000000.0 + (8 * 86400.0)  # 8 days after created_at
    # Fake last_active to be 5 minutes ago so sliding expiration does NOT trigger
    execute("UPDATE sessions SET last_active_at = ? WHERE user_id = 101", (current_time - 300,))

    # In fixed state, absolute max age MUST expire the session
    sess_expired = get_session(token)
    assert sess_expired is None, "Session exceeded max age (absolute TTL) but was not expired!"


def test_assignee_department_isolation_and_ambiguity(tmp_db):
    from services.data_store import append_record, get_record_by_id
    from services.auth import can_view_record
    from db import execute

    # Create 3 departments: dept1, dept2, dept3
    execute("INSERT OR IGNORE INTO departments(id, name) VALUES ('dept1', 'Dept 1')")
    execute("INSERT OR IGNORE INTO departments(id, name) VALUES ('dept2', 'Dept 2')")
    execute("INSERT OR IGNORE INTO departments(id, name) VALUES ('dept3', 'Dept 3')")

    # Case 1: Two users with identical name 'Minh' in dept1 (id=201) and dept2 (id=202)
    execute("INSERT INTO users(id, name, username, dept_id, email, password_hash, salt, role) "
            "VALUES (201, 'Minh', 'minh1', 'dept1', 'minh1@test.com', 'h', 's', 'member')")
    execute("INSERT INTO users(id, name, username, dept_id, email, password_hash, salt, role) "
            "VALUES (202, 'Minh', 'minh2', 'dept2', 'minh2@test.com', 'h', 's', 'member')")

    # Create a private record in dept3 with assignee 'Minh'
    rec_ambiguous = {
        "id": 9001,
        "dept_id": "dept3",
        "title": "Confidential Dept3 Task",
        "category": "Security",
        "assignee": "Minh",
        "is_private": 1
    }
    append_record(rec_ambiguous)
    saved_ambiguous = get_record_by_id(9001)

    # In vulnerable state: LIMIT 1 greedily assigns id=201, allowing user 201 from dept1 to view dept3's private record!
    # In secure state: ambiguous candidates across depts -> assignee_id MUST be None
    assert saved_ambiguous["assignee_id"] is None, f"Expected assignee_id to be None due to ambiguity, got {saved_ambiguous['assignee_id']}"

    # Verify RBAC: Neither user 201 nor user 202 should have access to this private record in dept3
    u1_session = {"id": 201, "name": "Minh", "username": "minh1", "org": "dept1", "role": "member"}
    u2_session = {"id": 202, "name": "Minh", "username": "minh2", "org": "dept2", "role": "member"}
    assert can_view_record(u1_session, saved_ambiguous) is False
    assert can_view_record(u2_session, saved_ambiguous) is False

    # Case 2: Only 1 user globally named 'UniqueUser' in dept1 (id=203)
    execute("INSERT INTO users(id, name, username, dept_id, email, password_hash, salt, role) "
            "VALUES (203, 'UniqueUser', 'unique_u', 'dept1', 'unique@test.com', 'h', 's', 'member')")
    rec_unique = {
        "id": 9002,
        "dept_id": "dept3",
        "title": "Cross dept single candidate task",
        "category": "General",
        "assignee": "UniqueUser",
        "is_private": 0
    }
    append_record(rec_unique)
    saved_unique = get_record_by_id(9002)
    assert saved_unique["assignee_id"] == 203


def test_username_cannot_impersonate_display_name_in_rbac(tmp_db):
    from services.auth import can_view_record, can_modify_record

    # Target record owned by User A whose display name is 'Kim' (id=301) in dept1
    rec_private = {
        "id": 8888,
        "dept_id": "dept1",
        "title": "Private record for display name Kim",
        "assignee_name": "Kim",
        "assignee_id": 301,
        "is_private": 1
    }

    # Impersonator user B in dept2 whose USERNAME is 'kim' (display name 'Attacker', id=302)
    attacker_session = {
        "id": 302,
        "name": "Attacker",
        "username": "kim",
        "org": "dept2",
        "role": "member"
    }

    # Legitimate user A in dept1
    legit_session = {
        "id": 301,
        "name": "Kim",
        "username": "kim_user",
        "org": "dept1",
        "role": "member"
    }

    assert can_view_record(legit_session, rec_private) is True
    assert can_modify_record(legit_session, rec_private) is True

    # Attacker with username == 'kim' MUST NOT be allowed to view or modify
    assert can_view_record(attacker_session, rec_private) is False
    assert can_modify_record(attacker_session, rec_private) is False


def test_login_does_not_leak_token_in_json_by_default(tmp_db, monkeypatch):
    import json
    import os
    from handlers.auth_handlers import handle_account_login
    from services.auth import create_user, hash_password

    class LoginMockHandler:
        def __init__(self, secure=False):
            self.secure = secure
            self.status = None
            self.data = None
            self.extra_headers = []

        def _is_secure(self):
            return self.secure

        def _make_auth_cookie_header(self, token):
            return ("Set-Cookie", f"argos_token={token}; Path=/; HttpOnly; SameSite=Lax")

        def _send_json(self, status, data, extra_headers=None):
            self.status = status
            self.data = data
            self.extra_headers = extra_headers or []

    salt, hpwd = hash_password("Password123!")
    create_user("UserSecure", "usersec", "dev", "usersec@test.com", salt, hpwd, status="active", role="member")

    payload = json.dumps({"username": "usersec", "password": "Password123!"}).encode()

    # 1. Default mode: NO token returned in JSON body
    monkeypatch.delenv("ARGOS_LOGIN_RETURN_TOKEN", raising=False)
    handler = LoginMockHandler(secure=True)
    handle_account_login(handler, payload, "127.0.0.1")

    assert handler.status == 200
    assert handler.data["ok"] is True
    assert "token" not in handler.data, "Security violation: plaintext token leaked in JSON body by default!"

    # Verify HttpOnly auth cookie and Secure flag on csrf cookie
    headers_dict = dict(handler.extra_headers)
    cookie_str = headers_dict.get("Set-Cookie", "")
    csrf_cookies = [h[1] for h in handler.extra_headers if h[0] == "Set-Cookie" and "argos_csrf=" in h[1]]
    assert len(csrf_cookies) == 1
    assert "; Secure" in csrf_cookies[0]

    # 2. Opt-in compatibility mode via ARGOS_LOGIN_RETURN_TOKEN=1
    monkeypatch.setenv("ARGOS_LOGIN_RETURN_TOKEN", "1")
    handler_compat = LoginMockHandler()
    handle_account_login(handler_compat, payload, "127.0.0.1")
    assert handler_compat.status == 200
    assert "token" in handler_compat.data
