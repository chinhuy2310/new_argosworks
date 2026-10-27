"""
test_password_change_workflows.py
Validates password changing rules:
1. User profile edit:
   - Updating profile without password changes succeeds without old password.
   - Changing password requires current password, new password, and matching confirm password.
   - Wrong current password fails with 400.
   - Mismatched confirm password fails with 400.
   - Missing confirm password fails with 400 (API-level rule, not only the browser form).
   - Password < 8 characters fails with 400.
   - Correct workflow successfully changes password and revokes the *other* sessions
     (the current device stays logged in, `sessionsRevoked` is reported).
2. Admin user edit:
   - Admin does NOT need old password to reset a user's password.
   - Admin enters new password and confirm password (both mandatory).
   - Mismatched confirm password fails with 400.
   - Missing confirm password fails with 400.
   - New password < 8 chars fails with 400.
   - Correct admin password reset succeeds (and refreshes `hash_algo`).
"""
import os
import sys
import json
import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_DIR = os.path.join(BASE_DIR, "server")
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from services.auth import create_user, verify_password, hash_password
from handlers.auth_handlers import handle_account_update_profile
from router import handle_post_admin_user_update
from db import get_one


def make_user(name, org, email, password, role="member", is_admin=False):
    salt, pwd_hash = hash_password(password)
    u = create_user(name, name.lower(), org, email, salt, pwd_hash, role=role, is_admin=is_admin)
    return u["id"] if isinstance(u, dict) else u


class TestPasswordChangeWorkflows:

    def test_user_update_profile_without_password(self, tmp_db, mock_handler):
        uid = make_user("Alice", "mgmt", "alice@test.com", "OldPassword123!", role="member")
        user = get_one("SELECT * FROM users WHERE id = ?", (uid,))
        assert user is not None

        handler = mock_handler(session={
            "id": uid,
            "name": "Alice",
            "org": "mgmt",
            "email": "alice@test.com",
            "role": "member",
            "isAdmin": False,
            "is_admin": False
        })

        # Update name and email without touching password
        payload = json.dumps({
            "name": "Alice Updated",
            "email": "alice_new@test.com",
            "org": "mgmt"
        }).encode("utf-8")

        handle_account_update_profile(handler, payload, "127.0.0.1")
        assert handler.response_code == 200
        assert handler.response_body["ok"] is True

        # Check DB that password hash is untouched
        user_after = get_one("SELECT * FROM users WHERE id = ?", (uid,))
        assert user_after["name"] == "Alice Updated"
        assert user_after["password_hash"] == user["password_hash"]

    def test_user_update_profile_password_requires_current_password(self, tmp_db, mock_handler):
        uid = make_user("Bob", "mgmt", "bob@test.com", "OldPassword123!", role="member")
        handler = mock_handler(session={
            "id": uid,
            "name": "Bob",
            "org": "mgmt",
            "email": "bob@test.com",
            "role": "member",
            "isAdmin": False,
            "is_admin": False
        })

        # Provide new password but NO current password
        payload = json.dumps({
            "name": "Bob",
            "email": "bob@test.com",
            "org": "mgmt",
            "password": "NewPassword123!",
            "confirm_password": "NewPassword123!"
        }).encode("utf-8")

        handle_account_update_profile(handler, payload, "127.0.0.1")
        assert handler.response_code == 400
        assert "현재 비밀번호" in handler.response_body.get("error", "")

    def test_user_update_profile_password_wrong_current_password(self, tmp_db, mock_handler):
        uid = make_user("Charlie", "mgmt", "charlie@test.com", "OldPassword123!", role="member")
        handler = mock_handler(session={
            "id": uid,
            "name": "Charlie",
            "org": "mgmt",
            "email": "charlie@test.com",
            "role": "member",
            "isAdmin": False,
            "is_admin": False
        })

        payload = json.dumps({
            "name": "Charlie",
            "email": "charlie@test.com",
            "org": "mgmt",
            "current_password": "WrongPassword123!",
            "password": "NewPassword123!",
            "confirm_password": "NewPassword123!"
        }).encode("utf-8")

        handle_account_update_profile(handler, payload, "127.0.0.1")
        assert handler.response_code == 400
        assert "현재 비밀번호가 일치하지 않습니다" in handler.response_body.get("error", "")

    def test_user_update_profile_password_mismatched_confirm(self, tmp_db, mock_handler):
        uid = make_user("David", "mgmt", "david@test.com", "OldPassword123!", role="member")
        handler = mock_handler(session={
            "id": uid,
            "name": "David",
            "org": "mgmt",
            "email": "david@test.com",
            "role": "member",
            "isAdmin": False,
            "is_admin": False
        })

        payload = json.dumps({
            "name": "David",
            "email": "david@test.com",
            "org": "mgmt",
            "current_password": "OldPassword123!",
            "password": "NewPassword123!",
            "confirm_password": "DifferentPassword123!"
        }).encode("utf-8")

        handle_account_update_profile(handler, payload, "127.0.0.1")
        assert handler.response_code == 400
        assert "새 비밀번호가 일치하지 않습니다" in handler.response_body.get("error", "")

    def test_user_update_profile_password_success(self, tmp_db, mock_handler):
        uid = make_user("Eve", "mgmt", "eve@test.com", "OldPassword123!", role="member")
        handler = mock_handler(session={
            "id": uid,
            "name": "Eve",
            "org": "mgmt",
            "email": "eve@test.com",
            "role": "member",
            "isAdmin": False,
            "is_admin": False
        })

        payload = json.dumps({
            "name": "Eve",
            "email": "eve@test.com",
            "org": "mgmt",
            "current_password": "OldPassword123!",
            "password": "BrandNewPassword123!",
            "confirm_password": "BrandNewPassword123!"
        }).encode("utf-8")

        handle_account_update_profile(handler, payload, "127.0.0.1")
        assert handler.response_code == 200
        assert handler.response_body["ok"] is True

        # Verify old password is no longer valid, and new password is valid
        user = get_one("SELECT * FROM users WHERE id = ?", (uid,))
        assert not verify_password("OldPassword123!", user["salt"], user["password_hash"], iterations=user["iterations"])
        assert verify_password("BrandNewPassword123!", user["salt"], user["password_hash"], iterations=user["iterations"])

    def test_admin_update_user_password_does_not_need_old_password(self, tmp_db, mock_handler):
        admin_id = make_user("AdminUser", "mgmt", "admin@test.com", "AdminPassword123!", role="admin", is_admin=True)
        target_id = make_user("Frank", "mgmt", "frank@test.com", "FrankOldPassword123!", role="member")

        handler = mock_handler(session={
            "id": admin_id,
            "name": "AdminUser",
            "org": "mgmt",
            "email": "admin@test.com",
            "role": "admin",
            "isAdmin": True,
            "is_admin": True
        })

        # Admin resets Frank's password without needing Frank's old password
        payload = json.dumps({
            "id": target_id,
            "name": "Frank",
            "dept_id": "mgmt",
            "email": "frank@test.com",
            "role": "member",
            "new_password": "FrankNewPassword123!",
            "new_password_confirm": "FrankNewPassword123!"
        }).encode("utf-8")

        handle_post_admin_user_update(handler, payload, "127.0.0.1")
        assert handler.response_code == 200
        assert handler.response_body["ok"] is True

        user = get_one("SELECT * FROM users WHERE id = ?", (target_id,))
        assert not verify_password("FrankOldPassword123!", user["salt"], user["password_hash"], iterations=user["iterations"])
        assert verify_password("FrankNewPassword123!", user["salt"], user["password_hash"], iterations=user["iterations"])
        assert user["hash_algo"] == "pbkdf2_sha256"

    def test_admin_update_user_password_mismatch(self, tmp_db, mock_handler):
        admin_id = make_user("AdminUser2", "mgmt", "admin2@test.com", "AdminPassword123!", role="admin", is_admin=True)
        target_id = make_user("Grace", "mgmt", "grace@test.com", "GraceOldPassword123!", role="member")

        handler = mock_handler(session={
            "id": admin_id,
            "name": "AdminUser2",
            "org": "mgmt",
            "email": "admin2@test.com",
            "role": "admin",
            "isAdmin": True,
            "is_admin": True
        })

        payload = json.dumps({
            "id": target_id,
            "name": "Grace",
            "dept_id": "mgmt",
            "email": "grace@test.com",
            "role": "member",
            "new_password": "GraceNewPassword123!",
            "new_password_confirm": "MismatchedPassword123!"
        }).encode("utf-8")

        handle_post_admin_user_update(handler, payload, "127.0.0.1")
        assert handler.response_code == 400
        assert "새 비밀번호가 일치하지 않습니다" in handler.response_body.get("error", "")

    def test_admin_update_user_password_too_short(self, tmp_db, mock_handler):
        admin_id = make_user("AdminUser3", "mgmt", "admin3@test.com", "AdminPassword123!", role="admin", is_admin=True)
        target_id = make_user("Henry", "mgmt", "henry@test.com", "HenryOldPassword123!", role="member")

        handler = mock_handler(session={
            "id": admin_id,
            "name": "AdminUser3",
            "org": "mgmt",
            "email": "admin3@test.com",
            "role": "admin",
            "isAdmin": True,
            "is_admin": True
        })

        payload = json.dumps({
            "id": target_id,
            "name": "Henry",
            "dept_id": "mgmt",
            "email": "henry@test.com",
            "role": "member",
            "new_password": "short",
            "new_password_confirm": "short"
        }).encode("utf-8")

        handle_post_admin_user_update(handler, payload, "127.0.0.1")
        assert handler.response_code == 400

    def test_user_update_profile_requires_confirm_password(self, tmp_db, mock_handler):
        """Confirm field is mandatory on the API too (not only in the browser form)."""
        uid = make_user("Jack", "mgmt", "jack@test.com", "OldPassword123!", role="member")
        handler = mock_handler(session={
            "id": uid, "name": "Jack", "org": "mgmt", "email": "jack@test.com",
            "role": "member", "isAdmin": False, "is_admin": False
        })

        payload = json.dumps({
            "name": "Jack",
            "email": "jack@test.com",
            "org": "mgmt",
            "current_password": "OldPassword123!",
            "password": "NewJackPassword123!"
        }).encode("utf-8")

        handle_account_update_profile(handler, payload, "127.0.0.1")
        assert handler.response_code == 400
        assert "새 비밀번호 확인" in handler.response_body.get("error", "")

        # Password must be untouched
        user = get_one("SELECT * FROM users WHERE id = ?", (uid,))
        assert verify_password("OldPassword123!", user["salt"], user["password_hash"], iterations=user["iterations"])

    def test_user_update_profile_revokes_other_sessions(self, tmp_db, mock_handler):
        """
        Changing the password must invalidate every other device (a stolen session
        must not survive the password change) while keeping the current one usable.
        """
        from services.auth import create_session, hash_session_token

        uid = make_user("Ivy", "mgmt", "ivy@test.com", "OldPassword123!", role="member")
        current_token = create_session(uid)
        other_token = create_session(uid)

        handler = mock_handler(session={
            "id": uid, "name": "Ivy", "org": "mgmt", "email": "ivy@test.com",
            "role": "member", "isAdmin": False, "is_admin": False
        }, token=current_token)

        payload = json.dumps({
            "name": "Ivy",
            "email": "ivy@test.com",
            "org": "mgmt",
            "current_password": "OldPassword123!",
            "password": "IvyNewPassword123!",
            "confirm_password": "IvyNewPassword123!"
        }).encode("utf-8")

        handle_account_update_profile(handler, payload, "127.0.0.1")

        assert handler.response_code == 200, handler.response_body
        assert handler.response_body.get("passwordChanged") is True
        assert handler.response_body.get("sessionsRevoked") == 1

        assert get_one(
            "SELECT token FROM sessions WHERE token = ?", (hash_session_token(other_token),)
        ) is None, "other devices must be logged out"
        assert get_one(
            "SELECT token FROM sessions WHERE token = ?", (hash_session_token(current_token),)
        ) is not None, "the current device must stay logged in"

        user = get_one("SELECT hash_algo, iterations FROM users WHERE id = ?", (uid,))
        assert user["hash_algo"] == "pbkdf2_sha256"

    def test_admin_update_user_password_requires_confirm(self, tmp_db, mock_handler):
        """Admin reset must also submit the confirmation field."""
        admin_id = make_user("AdminUser4", "mgmt", "admin4@test.com", "AdminPassword123!", role="admin", is_admin=True)
        target_id = make_user("Ken", "mgmt", "ken@test.com", "KenOldPassword123!", role="member")

        handler = mock_handler(session={
            "id": admin_id, "name": "AdminUser4", "org": "mgmt", "email": "admin4@test.com",
            "role": "admin", "isAdmin": True, "is_admin": True
        })

        payload = json.dumps({
            "id": target_id,
            "new_password": "KenNewPassword123!"
        }).encode("utf-8")

        handle_post_admin_user_update(handler, payload, "127.0.0.1")
        assert handler.response_code == 400
        assert "새 비밀번호 확인" in handler.response_body.get("error", "")

        user = get_one("SELECT * FROM users WHERE id = ?", (target_id,))
        assert verify_password("KenOldPassword123!", user["salt"], user["password_hash"], iterations=user["iterations"])
