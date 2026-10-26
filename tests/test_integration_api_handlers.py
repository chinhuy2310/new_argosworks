"""
test_integration_api_handlers.py — Integration Tests cho API Handler Layer
Kiểm tra tất cả endpoints: auth, department, schedule, records
Edge cases: unauthorized, empty payload, invalid JSON, duplicate data
"""
import os
import sys
import json
import time
import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_DIR = os.path.join(BASE_DIR, "server")
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

os.environ.setdefault("ARGOS_MASTER_KEY", "test-master-key-for-unit-tests-2026")


# ============================================================================
# 1. Auth Handlers — Account Check / Register / Login
# ============================================================================
class TestAuthHandlers:
    """Auth API endpoints: /api/account/*"""

    def test_account_check_missing_fields(self, tmp_db, mock_handler):
        from handlers.auth_handlers import handle_account_check
        handler = mock_handler()
        payload = json.dumps({}).encode("utf-8")
        handle_account_check(handler, payload, "127.0.0.1")
        assert handler.response_code == 400
        assert "이름" in handler.response_body.get("error", "")

    def test_account_check_empty_name(self, tmp_db, mock_handler):
        from handlers.auth_handlers import handle_account_check
        handler = mock_handler()
        payload = json.dumps({"name": "", "org": "dev"}).encode("utf-8")
        handle_account_check(handler, payload, "127.0.0.1")
        assert handler.response_code == 400

    def test_account_check_invalid_json(self, tmp_db, mock_handler):
        from handlers.auth_handlers import handle_account_check
        handler = mock_handler()
        handle_account_check(handler, b"not json at all", "127.0.0.1")
        assert handler.response_code == 400
        assert "잘못된" in handler.response_body.get("error", "")

    def test_account_check_existing_user(self, seed_user, mock_handler):
        from handlers.auth_handlers import handle_account_check
        handler = mock_handler()
        payload = json.dumps({"name": "테스트유저", "org": "dev"}).encode("utf-8")
        handle_account_check(handler, payload, "127.0.0.1")
        assert handler.response_code == 200
        assert handler.response_body["ok"] is True
        assert handler.response_body["exists"] is True

    def test_register_missing_username(self, tmp_db, mock_handler):
        from handlers.auth_handlers import handle_account_register
        handler = mock_handler(session={"name": "admin", "org": "dev", "email": "admin@test.com", "isAdmin": True, "is_admin": True, "role": "admin"})
        payload = json.dumps({
            "username": "",
            "name": "TestUser",
            "org": "dev",
            "password": "password123"
        }).encode("utf-8")
        handle_account_register(handler, payload, "127.0.0.1")
        assert handler.response_code == 400
        assert "아이디" in handler.response_body.get("error", "") or "ID" in handler.response_body.get("error", "")

    def test_register_missing_name(self, tmp_db, mock_handler):
        from handlers.auth_handlers import handle_account_register
        handler = mock_handler(session={"name": "admin", "org": "dev", "email": "admin@test.com", "isAdmin": True, "is_admin": True, "role": "admin"})
        payload = json.dumps({
            "username": "testuser",
            "name": "",
            "org": "dev",
            "password": "password123"
        }).encode("utf-8")
        handle_account_register(handler, payload, "127.0.0.1")
        assert handler.response_code == 400
        assert "이름" in handler.response_body.get("error", "")

    def test_register_short_password(self, tmp_db, mock_handler):
        from handlers.auth_handlers import handle_account_register
        handler = mock_handler(session={"name": "admin", "org": "dev", "email": "admin@test.com", "isAdmin": True, "is_admin": True, "role": "admin"})
        payload = json.dumps({
            "username": "testuser",
            "name": "Test",
            "org": "dev",
            "password": "123"
        }).encode("utf-8")
        handle_account_register(handler, payload, "127.0.0.1")
        assert handler.response_code == 400
        assert "8자" in handler.response_body.get("error", "")

    def test_register_invalid_json(self, tmp_db, mock_handler):
        from handlers.auth_handlers import handle_account_register
        handler = mock_handler(session={"name": "admin", "org": "dev", "email": "admin@test.com", "isAdmin": True, "is_admin": True, "role": "admin"})
        handle_account_register(handler, b"{broken json", "127.0.0.1")
        assert handler.response_code == 400


# ============================================================================
# 2. Department Handlers — CRUD
# ============================================================================
class TestDepartmentHandlers:
    """Department API endpoints: /api/departments/*"""

    def test_add_department_unauthorized(self, tmp_db, mock_handler):
        from handlers.department_handler import handle_add_department
        handler = mock_handler()  # No session → 401
        payload = json.dumps({"name": "New Dept"}).encode("utf-8")
        handle_add_department(handler, payload, "127.0.0.1")
        assert handler.response_code == 401

    def test_add_department_non_admin(self, seed_user, mock_handler):
        from handlers.department_handler import handle_add_department
        handler = mock_handler(session={
            "name": "테스트유저", "org": "dev", "email": "test@test.com",
            "isAdmin": False, "is_admin": False, "role": "member"
        })
        payload = json.dumps({"name": "New Dept"}).encode("utf-8")
        handle_add_department(handler, payload, "127.0.0.1")
        assert handler.response_code == 403
        assert handler.response_body.get("forbidden") is True

    def test_add_department_empty_name(self, seed_admin, mock_handler):
        from handlers.department_handler import handle_add_department
        handler = mock_handler(session={
            "name": "관리자", "org": "dev", "email": "admin@test.com",
            "isAdmin": True, "is_admin": True, "role": "admin"
        })
        payload = json.dumps({"name": ""}).encode("utf-8")
        handle_add_department(handler, payload, "127.0.0.1")
        assert handler.response_code == 400
        assert "이름" in handler.response_body.get("error", "")

    def test_add_department_success(self, seed_admin, mock_handler):
        from handlers.department_handler import handle_add_department
        handler = mock_handler(session={
            "name": "관리자", "org": "dev", "email": "admin@test.com",
            "isAdmin": True, "is_admin": True, "role": "admin"
        })
        payload = json.dumps({
            "name": "신규부서테스트",
            "localPrefix": "NEW",
            "jiraKey": "NEW"
        }).encode("utf-8")
        handle_add_department(handler, payload, "127.0.0.1")
        assert handler.response_code == 200
        assert handler.response_body["ok"] is True
        assert handler.response_body["added"] is True

    def test_add_duplicate_department(self, seed_admin, mock_handler):
        from handlers.department_handler import handle_add_department
        admin_session = {
            "name": "관리자", "org": "dev", "email": "admin@test.com",
            "isAdmin": True, "is_admin": True, "role": "admin"
        }
        # First add
        handler1 = mock_handler(session=admin_session)
        payload = json.dumps({"name": "중복테스트부서"}).encode("utf-8")
        handle_add_department(handler1, payload, "127.0.0.1")
        assert handler1.response_body["added"] is True

        # Second add (duplicate)
        handler2 = mock_handler(session=admin_session)
        handle_add_department(handler2, payload, "127.0.0.1")
        assert handler2.response_code == 200
        assert handler2.response_body["added"] is False

    def test_delete_department_missing_id(self, seed_admin, mock_handler):
        from handlers.department_handler import handle_delete_department
        handler = mock_handler(session={
            "name": "관리자", "org": "dev", "email": "admin@test.com",
            "isAdmin": True, "is_admin": True, "role": "admin"
        })
        payload = json.dumps({"id": ""}).encode("utf-8")
        handle_delete_department(handler, payload, "127.0.0.1")
        assert handler.response_code == 400

    def test_delete_department_nonexistent(self, seed_admin, mock_handler):
        from handlers.department_handler import handle_delete_department
        handler = mock_handler(session={
            "name": "관리자", "org": "dev", "email": "admin@test.com",
            "isAdmin": True, "is_admin": True, "role": "admin"
        })
        payload = json.dumps({"id": "nonexistent_dept_xyz"}).encode("utf-8")
        handle_delete_department(handler, payload, "127.0.0.1")
        assert handler.response_code == 404

    def test_update_department_missing_id(self, seed_admin, mock_handler):
        from handlers.department_handler import handle_update_department
        handler = mock_handler(session={
            "name": "관리자", "org": "dev", "email": "admin@test.com",
            "isAdmin": True, "is_admin": True, "role": "admin"
        })
        payload = json.dumps({"id": "", "name": "Test"}).encode("utf-8")
        handle_update_department(handler, payload, "127.0.0.1")
        assert handler.response_code == 400

    def test_update_department_missing_name(self, seed_admin, mock_handler):
        from handlers.department_handler import handle_update_department
        handler = mock_handler(session={
            "name": "관리자", "org": "dev", "email": "admin@test.com",
            "isAdmin": True, "is_admin": True, "role": "admin"
        })
        payload = json.dumps({"id": "dev", "name": ""}).encode("utf-8")
        handle_update_department(handler, payload, "127.0.0.1")
        assert handler.response_code == 400

    def test_invalid_json_body(self, seed_admin, mock_handler):
        from handlers.department_handler import handle_add_department
        handler = mock_handler(session={
            "name": "관리자", "org": "dev", "email": "admin@test.com",
            "isAdmin": True, "is_admin": True, "role": "admin"
        })
        handle_add_department(handler, b"not-json", "127.0.0.1")
        assert handler.response_code == 400


# ============================================================================
# 3. Schedule Handlers — Calendar Events
# ============================================================================
class TestScheduleHandlers:
    """Schedule API endpoints: /api/schedule/*"""

    def test_create_schedule_unauthorized(self, tmp_db, mock_handler):
        from handlers.schedule_handlers import handle_schedule_create
        handler = mock_handler()  # No session
        payload = json.dumps({
            "title": "Meeting", "type": "회의",
            "startDate": "2026-10-25", "endDate": "2026-10-25"
        }).encode("utf-8")
        handle_schedule_create(handler, payload, "127.0.0.1")
        assert handler.response_code == 401

    def test_create_schedule_empty_title(self, seed_user, mock_handler):
        from handlers.schedule_handlers import handle_schedule_create
        session = seed_user["session"]
        handler = mock_handler(session=session)
        payload = json.dumps({
            "title": "", "type": "회의",
            "startDate": "2026-10-25"
        }).encode("utf-8")
        handle_schedule_create(handler, payload, "127.0.0.1")
        assert handler.response_code == 400
        assert "제목" in handler.response_body.get("error", "")

    def test_create_schedule_invalid_date(self, seed_user, mock_handler):
        from handlers.schedule_handlers import handle_schedule_create
        session = seed_user["session"]
        handler = mock_handler(session=session)
        payload = json.dumps({
            "title": "회의", "type": "회의",
            "startDate": "not-a-date"
        }).encode("utf-8")
        handle_schedule_create(handler, payload, "127.0.0.1")
        assert handler.response_code == 400
        assert "날짜" in handler.response_body.get("error", "")

    def test_create_schedule_invalid_json(self, seed_user, mock_handler):
        from handlers.schedule_handlers import handle_schedule_create
        session = seed_user["session"]
        handler = mock_handler(session=session)
        handle_schedule_create(handler, b"broken{json", "127.0.0.1")
        assert handler.response_code == 400


# ============================================================================
# 4. Router — GET Endpoints
# ============================================================================
class TestRouterGETHandlers:
    """GET handlers from router.py."""

    def test_health_check_ok(self, tmp_db, mock_handler):
        from router import handle_get_health
        handler = mock_handler()
        handle_get_health(handler, None, "127.0.0.1")
        assert handler.response_code == 200
        body = handler.response_body
        assert body["ok"] is True
        assert body["status"] == "healthy"
        assert body["database"]["status"] == "connected"

    def test_get_departments(self, tmp_db, mock_handler):
        from router import handle_get_departments
        handler = mock_handler()
        handle_get_departments(handler, None, "127.0.0.1")
        assert handler.response_code == 200
        assert handler.response_body["ok"] is True
        assert isinstance(handler.response_body["departments"], list)
        assert len(handler.response_body["departments"]) > 0

    def test_get_members_unauthorized(self, tmp_db, mock_handler):
        from router import handle_get_members
        handler = mock_handler()  # No session
        handle_get_members(handler, None, "127.0.0.1")
        assert handler.response_code == 401


# ============================================================================
# 5. XSS / Injection via Handler Input
# ============================================================================
class TestXSSInjectionDefense:
    """Kiểm tra chống XSS qua dữ liệu nhập vào API."""

    def test_xss_in_department_name(self, seed_admin, mock_handler):
        from handlers.department_handler import handle_add_department
        handler = mock_handler(session={
            "name": "관리자", "org": "dev", "email": "admin@test.com",
            "isAdmin": True, "is_admin": True, "role": "admin"
        })
        payload = json.dumps({
            "name": "<script>alert('XSS')</script>",
            "localPrefix": "XSS"
        }).encode("utf-8")
        handle_add_department(handler, payload, "127.0.0.1")
        # Should succeed but store the literal string (escaping happens at render)
        assert handler.response_code == 200

    def test_sql_in_department_payload(self, seed_admin, mock_handler):
        from handlers.department_handler import handle_add_department
        handler = mock_handler(session={
            "name": "관리자", "org": "dev", "email": "admin@test.com",
            "isAdmin": True, "is_admin": True, "role": "admin"
        })
        payload = json.dumps({
            "name": "'; DROP TABLE departments; --"
        }).encode("utf-8")
        handle_add_department(handler, payload, "127.0.0.1")
        # DB should survive
        from db import query
        depts = query("SELECT * FROM departments")
        assert len(depts) > 0
