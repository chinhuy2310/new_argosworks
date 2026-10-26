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


# ---------------------------------------------------------------------------
# Database Fixture — Fresh SQLite per test session
# ---------------------------------------------------------------------------
@pytest.fixture(scope="function")
def tmp_db(tmp_path, monkeypatch):
    """Tạo database SQLite tạm cho mỗi test function."""
    import db as db_module
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

    def __init__(self, session=None, cfg=None):
        self._response_code = None
        self._response_body = None
        self._response_headers = {}
        self._session = session
        self.cfg = cfg or {}

    def _send_json(self, code, data):
        self._response_code = code
        self._response_body = data

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
    def _factory(session=None, cfg=None):
        return MockHandler(session=session, cfg=cfg)
    return _factory
