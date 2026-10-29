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
