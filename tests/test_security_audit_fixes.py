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
