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
