"""
test_unit_auth.py — Unit Tests cho Authentication & Session Management
Kiểm tra: password hashing, verify, user CRUD, session lifecycle
Edge cases: rỗng, trùng lặp, SQL injection, concurrent, disabled users
"""
import os
import sys
import time
import threading
import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_DIR = os.path.join(BASE_DIR, "server")
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

os.environ.setdefault("ARGOS_MASTER_KEY", "test-master-key-for-unit-tests-2026")


# ============================================================================
# 1. Password Hashing — PBKDF2-HMAC-SHA256
# ============================================================================
class TestPasswordHashing:
    """hash_password / verify_password: mã hóa & xác minh mật khẩu."""

    def test_hash_roundtrip(self, tmp_db):
        from services.auth import hash_password, verify_password
        salt, hashed = hash_password("MyPassword123!")
        assert verify_password("MyPassword123!", salt, hashed)

    def test_wrong_password_fails(self, tmp_db):
        from services.auth import hash_password, verify_password
        salt, hashed = hash_password("CorrectPassword")
        assert not verify_password("WrongPassword", salt, hashed)

    def test_empty_password(self, tmp_db):
        from services.auth import hash_password, verify_password
        salt, hashed = hash_password("")
        assert verify_password("", salt, hashed)
        assert not verify_password("notempty", salt, hashed)

    def test_unicode_password(self, tmp_db):
        from services.auth import hash_password, verify_password
        salt, hashed = hash_password("한글비밀번호🔐")
        assert verify_password("한글비밀번호🔐", salt, hashed)

    def test_long_password(self, tmp_db):
        from services.auth import hash_password, verify_password
        long_pwd = "A" * 1000
        salt, hashed = hash_password(long_pwd)
        assert verify_password(long_pwd, salt, hashed)

    def test_different_salts(self, tmp_db):
        from services.auth import hash_password
        salt1, hash1 = hash_password("same-password")
        salt2, hash2 = hash_password("same-password")
        assert salt1 != salt2  # Random salts
        assert hash1 != hash2  # Different hashes


# ============================================================================
# 2. User CRUD — create / get / delete
# ============================================================================
class TestUserCRUD:
    """User creation, lookup, and deletion."""

    def test_create_user_success(self, tmp_db):
        from services.auth import hash_password, create_user
        salt, hashed = hash_password("pass123")
        user = create_user(
            name="홍길동", username="hong", org="dev",
            email="hong@test.com", salt=salt, hash_pwd=hashed
        )
        assert user is not None
        assert user["name"] == "홍길동"
        assert user["username"] == "hong"

    def test_create_user_empty_username_defaults_to_name(self, tmp_db):
        """Empty username falls back to name (username = username or name)."""
        from services.auth import hash_password, create_user
        salt, hashed = hash_password("pass")
        user = create_user(name="테스트", username="", org="dev",
                           email="fallback@test.com", salt=salt, hash_pwd=hashed)
        assert user is not None
        assert user["username"] == "테스트"  # Fallback to name

    def test_create_user_both_empty_fails(self, tmp_db):
        """Both name and username empty should raise ValueError."""
        from services.auth import hash_password, create_user
        salt, hashed = hash_password("pass")
        with pytest.raises(ValueError):
            create_user(name="", username="", org="dev",
                        email="", salt=salt, hash_pwd=hashed)

    def test_create_user_empty_name_fails(self, tmp_db):
        from services.auth import hash_password, create_user
        salt, hashed = hash_password("pass")
        with pytest.raises(ValueError, match="이름"):
            create_user(name="", username="user1", org="dev",
                        email="", salt=salt, hash_pwd=hashed)

    def test_duplicate_username_fails(self, tmp_db):
        from services.auth import hash_password, create_user
        salt, hashed = hash_password("pass")
        create_user(name="유저A", username="sameuser", org="dev",
                    email="a@test.com", salt=salt, hash_pwd=hashed)
        with pytest.raises(ValueError, match="이미 사용"):
            create_user(name="유저B", username="sameuser", org="dev",
                        email="b@test.com", salt=salt, hash_pwd=hashed)

    def test_duplicate_email_fails(self, tmp_db):
        from services.auth import hash_password, create_user
        salt, hashed = hash_password("pass")
        create_user(name="유저1", username="user1", org="dev",
                    email="same@email.com", salt=salt, hash_pwd=hashed)
        with pytest.raises(ValueError, match="이메일"):
            create_user(name="유저2", username="user2", org="dev",
                        email="same@email.com", salt=salt, hash_pwd=hashed)

    def test_duplicate_name_dept_fails(self, tmp_db):
        from services.auth import hash_password, create_user
        salt, hashed = hash_password("pass")
        create_user(name="김철수", username="kim1", org="dev",
                    email="kim1@test.com", salt=salt, hash_pwd=hashed)
        with pytest.raises(ValueError, match="동일한 이름"):
            create_user(name="김철수", username="kim2", org="dev",
                        email="kim2@test.com", salt=salt, hash_pwd=hashed)

    def test_same_name_different_dept_ok(self, tmp_db):
        from services.auth import hash_password, create_user
        salt, hashed = hash_password("pass")
        u1 = create_user(name="김철수", username="kim_dev", org="dev",
                         email="kim_dev@test.com", salt=salt, hash_pwd=hashed)
        u2 = create_user(name="김철수", username="kim_hr", org="hr",
                         email="kim_hr@test.com", salt=salt, hash_pwd=hashed)
        assert u1 is not None
        assert u2 is not None

    def test_get_user_by_login_username(self, seed_user):
        from services.auth import get_user_by_login
        user = get_user_by_login("testuser")
        assert user is not None
        assert user["name"] == "테스트유저"

    def test_get_user_by_login_email(self, seed_user):
        from services.auth import get_user_by_login
        user = get_user_by_login("test@argos.works")
        assert user is not None

    def test_get_user_by_login_case_insensitive(self, seed_user):
        from services.auth import get_user_by_login
        user = get_user_by_login("TESTUSER")
        assert user is not None

    def test_get_user_by_login_nonexistent(self, tmp_db):
        from services.auth import get_user_by_login
        user = get_user_by_login("nonexistent_user")
        assert user is None

    def test_get_user_by_login_empty(self, tmp_db):
        from services.auth import get_user_by_login
        assert get_user_by_login("") is None
        assert get_user_by_login(None) is None

    def test_get_user_by_id(self, seed_user):
        from services.auth import get_user_by_id
        user_id = seed_user["user"]["id"]
        user = get_user_by_id(user_id)
        assert user is not None
        assert user["name"] == "테스트유저"

    def test_get_user_by_id_nonexistent(self, tmp_db):
        from services.auth import get_user_by_id
        assert get_user_by_id(99999) is None
        assert get_user_by_id(None) is None

    def test_safe_delete_user(self, seed_user):
        from services.auth import safe_delete_user, get_user_by_id
        user_id = seed_user["user"]["id"]
        result = safe_delete_user(user_id)
        assert result is True
        assert get_user_by_id(user_id) is None

    def test_safe_delete_nonexistent_user(self, tmp_db):
        from services.auth import safe_delete_user
        result = safe_delete_user(99999)
        assert result is False


# ============================================================================
# 3. Session Management
# ============================================================================
class TestSessionManagement:
    """Session creation, retrieval, deletion."""

    def test_create_session(self, seed_user):
        from services.auth import get_session
        token = seed_user["session"]
        assert token is not None
        assert isinstance(token, str)
        session = get_session(token)
        assert session is not None
        assert session["name"] == "테스트유저"

    def test_get_session_valid_token(self, seed_user):
        from services.auth import get_session
        token = seed_user["session"]
        session = get_session(token)
        assert session is not None
        assert session["name"] == "테스트유저"

    def test_get_session_invalid_token(self, tmp_db):
        from services.auth import get_session
        session = get_session("invalid-token-123")
        assert session is None

    def test_get_session_empty_token(self, tmp_db):
        from services.auth import get_session
        assert get_session("") is None
        assert get_session(None) is None

    def test_admin_session_flag(self, seed_admin):
        from services.auth import is_admin_user, get_session
        token = seed_admin["session"]
        session = get_session(token)
        assert is_admin_user(session) is True

    def test_non_admin_flag(self, seed_user):
        from services.auth import is_admin_user, get_session
        token = seed_user["session"]
        session = get_session(token)
        assert is_admin_user(session) is False


# ============================================================================
# 4. Account Key
# ============================================================================
class TestAccountKey:
    """account_key: tạo composite key name|org."""

    def test_normal(self):
        from services.auth import account_key
        assert account_key("홍길동", "dev") == "홍길동|dev"

    def test_strips_whitespace(self):
        from services.auth import account_key
        assert account_key("  홍길동  ", "  dev  ") == "홍길동|dev"

    def test_empty_values(self):
        from services.auth import account_key
        assert account_key("", "") == "|"
        assert account_key(None, None) == "|"


# ============================================================================
# 5. SQL Injection Defense
# ============================================================================
class TestSQLInjectionDefense:
    """Kiểm tra hệ thống chống SQL injection."""

    def test_malicious_username(self, tmp_db):
        from services.auth import get_user_by_login
        # Should not crash or return unexpected results
        result = get_user_by_login("'; DROP TABLE users; --")
        assert result is None

    def test_malicious_name_in_create(self, tmp_db):
        from services.auth import hash_password, create_user
        salt, hashed = hash_password("pass")
        # Name with SQL injection attempt
        user = create_user(
            name="Robert'); DROP TABLE users;--",
            username="bobby_tables",
            org="dev",
            email="bobby@test.com",
            salt=salt,
            hash_pwd=hashed
        )
        # User should be created with the literal string
        assert user is not None
        # DB should still be intact
        from db import query
        tables = query("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
        assert len(tables) > 0
