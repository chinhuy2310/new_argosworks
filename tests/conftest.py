"""
conftest.py — Pytest Shared Fixtures for ARGOS WORKS Test Suite
Cung cấp cơ sở dữ liệu tạm, mock server, test client dùng chung cho toàn bộ test.
"""
import os
import sys
import json
import time
import shutil
import tempfile
import sqlite3
import threading
import uuid
import pytest
from http.server import HTTPServer
from unittest.mock import MagicMock, patch
from urllib.parse import urlencode

# Add server directory to sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_DIR = os.path.join(BASE_DIR, "server")
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

# Set ARGOS_MASTER_KEY for crypto tests before any import
os.environ.setdefault("ARGOS_MASTER_KEY", "test-master-key-for-unit-tests-2026")

# Keep the suite fast: PBKDF2 with the production 600,000 rounds makes every
# password hash/verify take ~0.3s. Production default is untouched.
os.environ.setdefault("ARGOS_PBKDF2_ROUNDS", "2000")

# Sized to tolerate concurrent tests (e.g. 20 concurrent threads in test_auth_concurrency)
# while staying well within PostgreSQL's default max_connections (100).
os.environ.setdefault("ARGOS_PG_POOL_MIN", "2")
os.environ.setdefault("ARGOS_PG_POOL_MAX", "25")


# PostgreSQL: run the whole session inside a throw-away schema.
# Without this the suite shared the CI/developer database, so a second run saw the
# rows left by the first one (unique-constraint and FK failures that never happen
# on a fresh CI database). tmp_db creates a nested per-test schema and restores
# this one afterwards.
_SESSION_PG_SCHEMA = ""


def _bootstrap_database():
    """Create the baseline schema before any unittest setUpClass() runs."""
    import db as db_module
    global _SESSION_PG_SCHEMA
    if getattr(db_module, "ENGINE", "sqlite") == "postgres":
        _SESSION_PG_SCHEMA = "argos_test_run_" + uuid.uuid4().hex[:10]
        db_module.set_search_path(_SESSION_PG_SCHEMA)
    db_module.init_db()


try:
    _bootstrap_database()
except Exception as _boot_exc:  # pragma: no cover
    print(f"[conftest] bootstrap init_db() failed: {_boot_exc}", file=sys.stderr)


@pytest.fixture(scope="session", autouse=True)
def _isolated_session_database():
    """Drop the session schema (PostgreSQL) after the last test."""
    yield
    import db as db_module
    if getattr(db_module, "ENGINE", "sqlite") == "postgres" and _SESSION_PG_SCHEMA:
        try:
            db_module.set_search_path("")
            db_module.drop_schema(_SESSION_PG_SCHEMA)
        except Exception as exc:  # pragma: no cover
            print(f"[conftest] session schema cleanup failed: {exc}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Database Fixture — Fresh SQLite per test session
# ---------------------------------------------------------------------------
@pytest.fixture(scope="function")
def tmp_db(tmp_path, monkeypatch):
    """
    Isolated database for a single test — works on both engines.

    * SQLite   → temporary database file (get_db_path is patched).
    * Postgres → temporary *schema* exposed through search_path, dropped after the
      test. The SQLite patch has no effect on the PostgreSQL pool DSN, so without
      this every Postgres test shared one database (isolation was silently lost).
    """
    import db as db_module

    if getattr(db_module, "ENGINE", "sqlite") == "postgres":
        schema = "argos_test_" + uuid.uuid4().hex[:12]
        # Point pooled connections at a fresh schema, then build the baseline there.
        db_module.set_search_path(schema)
        try:
            db_module.init_db()
            yield db_module
        finally:
            # Restore the session schema (not the default one).
            db_module.set_search_path(_SESSION_PG_SCHEMA)
            try:
                db_module.drop_schema(schema)
            except Exception:
                pass
        return

    db_path = str(tmp_path / "test.sqlite")

    # Monkey-patch get_db_path to use test db
    monkeypatch.setattr(db_module, "get_db_path", lambda: db_path)

    # Force re-creation of thread-local connections
    if hasattr(db_module, "_tls"):
        db_module._tls = threading.local()
    if hasattr(db_module, "_local"):
        db_module._local = threading.local()

    db_module.init_db()
    yield db_module

    # Cleanup thread-local connections
    if hasattr(db_module, "_tls"):
        db_module._tls = threading.local()
    if hasattr(db_module, "_local"):
        db_module._local = threading.local()


@pytest.fixture(scope="function")
def seed_departments(tmp_db):
    """Seed default departments into the test database."""
    return tmp_db


@pytest.fixture(scope="function")
def seed_user(tmp_db):
    """Create a test user and return user info + session."""
    from services.auth import hash_password, create_user, create_session

    salt, hash_pwd = hash_password("TestPass123!")
    user = create_user(
        name="테스트유저",
        username="testuser",
        org="dev",
        email="test@argos.works",
        salt=salt,
        hash_pwd=hash_pwd,
        role="member",
        is_admin=False,
        status="active",
        disabled=0
    )
    session = create_session(user["name"], org=user["dept_id"],
                             email=user.get("email", ""), user_id=user["id"])
    return {"user": user, "session": session, "password": "TestPass123!"}


@pytest.fixture(scope="function")
def seed_admin(tmp_db):
    """Create a test admin user and return user info + session."""
    from services.auth import hash_password, create_user, create_session

    salt, hash_pwd = hash_password("AdminPass456!")
    user = create_user(
        name="관리자",
        username="adminuser",
        org="dev",
        email="admin@argos.works",
        salt=salt,
        hash_pwd=hash_pwd,
        role="admin",
        is_admin=True,
        status="active",
        disabled=0
    )
    session = create_session(user["name"], org=user["dept_id"],
                             email=user.get("email", ""), user_id=user["id"])
    return {"user": user, "session": session, "password": "AdminPass456!"}


@pytest.fixture(scope="function")
def tmp_data_dir(tmp_path):
    """Tạo data directory tạm."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "attachments").mkdir()
    (data_dir / "chat_history").mkdir()
    return str(data_dir)


# ---------------------------------------------------------------------------
# Mock Handler — Simulate HTTP handler for endpoint tests
# ---------------------------------------------------------------------------
class MockHandler:
    """Mock HTTP handler that captures responses for testing API handlers."""

    def __init__(self, session=None, cfg=None, token=None):
        self._response_code = None
        self._response_body = None
        self._response_headers = {}
        self._session = session
        self._token = token
        self.cfg = cfg or {}

    def _send_json(self, code, data):
        self._response_code = code
        self._response_body = data

    def _extract_token(self):
        """Session token used by handlers that revoke/log out the current device."""
        return self._token

    def _get_session_or_401(self):
        if self._session is None:
            self._send_json(401, {"ok": False, "error": "인증이 필요합니다."})
            return None
        return self._session

    def _get_session_optional(self):
        return self._session

    @property
    def response_code(self):
        return self._response_code

    @property
    def response_body(self):
        return self._response_body


@pytest.fixture
def mock_handler():
    """Factory fixture to create MockHandler instances."""
    def _factory(session=None, cfg=None, token=None):
        return MockHandler(session=session, cfg=cfg, token=token)
    return _factory
