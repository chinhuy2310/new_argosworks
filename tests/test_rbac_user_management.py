import unittest
import os
import sys
from unittest.mock import patch

# Add server directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from services.auth import get_user_role, can_view_record, can_modify_record
from db import init_db, execute, get_one, query

class TestRBAC(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def test_get_user_role(self):
        admin_session = {"name": "AdminUser", "org": "dev", "role": "admin", "isAdmin": True}
        manager_session = {"name": "ManagerUser", "org": "dev", "role": "manager"}
        member_session = {"name": "MemberUser", "org": "dev", "role": "member"}
        viewer_session = {"name": "ViewerUser", "org": "dev", "role": "viewer"}

        self.assertEqual(get_user_role(admin_session), "admin")
        self.assertEqual(get_user_role(manager_session), "manager")
        self.assertEqual(get_user_role(member_session), "member")
        self.assertEqual(get_user_role(viewer_session), "viewer")

        from services.auth import is_manager_or_admin
        self.assertTrue(is_manager_or_admin(admin_session))
        self.assertTrue(is_manager_or_admin(manager_session))
        self.assertFalse(is_manager_or_admin(member_session))
        self.assertFalse(is_manager_or_admin(viewer_session))

    def test_can_view_record_rules(self):
        # Admin can view anything
        admin = {"name": "Root", "org": "it", "role": "admin"}
        rec_private_other_dept = {"dept_id": "hr", "assignee_name": "Bob", "is_private": 1}
        self.assertTrue(can_view_record(admin, rec_private_other_dept))

        # Manager can view private records of their own dept, but not other dept
        mgr_hr = {"name": "HRBoss", "org": "hr", "role": "manager"}
        mgr_dev = {"name": "DevBoss", "org": "dev", "role": "manager"}
        self.assertTrue(can_view_record(mgr_hr, rec_private_other_dept))
        self.assertFalse(can_view_record(mgr_dev, rec_private_other_dept))

        # Manager can view public records of other depts
        rec_public_dev = {"dept_id": "dev", "assignee_name": "Alice", "is_private": 0}
        self.assertTrue(can_view_record(mgr_hr, rec_public_dev))

        # Member can view their own dept public records, but not other dept (unless assigned)
        member_dev = {"name": "DevJohn", "org": "dev", "role": "member"}
        rec_hr_public = {"dept_id": "hr", "assignee_name": "Bob", "participants": "", "is_private": 0}
        rec_hr_assigned_to_dev = {"dept_id": "hr", "assignee_name": "DevJohn", "participants": "", "is_private": 0}
        self.assertFalse(can_view_record(member_dev, rec_hr_public))
        self.assertTrue(can_view_record(member_dev, rec_hr_assigned_to_dev))

    def test_can_modify_record_rules(self):
        admin = {"name": "Root", "org": "it", "role": "admin"}
        rec = {"dept_id": "dev", "assignee_name": "Alice"}
        self.assertTrue(can_modify_record(admin, rec))

        # Viewer cannot modify anything
        viewer = {"name": "Auditor", "org": "dev", "role": "viewer"}
        self.assertFalse(can_modify_record(viewer, rec))

        # Member can modify only if assigned
        member_alice = {"name": "Alice", "org": "dev", "role": "member"}
        member_charlie = {"name": "Charlie", "org": "dev", "role": "member"}
        self.assertTrue(can_modify_record(member_alice, rec))
        self.assertFalse(can_modify_record(member_charlie, rec))

        # Manager can modify records in their dept
        mgr_dev = {"name": "DevBoss", "org": "dev", "role": "manager"}
        self.assertTrue(can_modify_record(mgr_dev, rec))


class MockHTTPHandler:
    def __init__(self, session=None):
        self.session = session
        self.status_code = None
        self.response_body = None
        self.headers_sent = {}
        self.cfg = {}

    def _get_session_or_401(self):
        if not self.session:
            self._send_json(401, {"ok": False, "error": "Unauthorized"})
            return None
        return self.session

    def _get_session_optional(self):
        return self.session

    def _send_json(self, status, data, extra_headers=None):
        self.status_code = status
        self.response_body = data
        self.extra_headers = extra_headers or []

    def send_response(self, code):
        self.status_code = code

    def send_header(self, k, v):
        self.headers_sent[k] = v

    def end_headers(self):
        pass

    def _make_auth_cookie_header(self, token):
        return ("Set-Cookie", f"session_token={token}; Path=/")


class TestDirection2ApprovalWorkflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        self._prev_allow_pub = os.environ.get("ALLOW_PUBLIC_REGISTER")
        os.environ["ALLOW_PUBLIC_REGISTER"] = "true"
        # Licensing (seat limits) is out of scope for the approval workflow tests,
        # and the local data DB may legitimately be at its seat limit.
        seat_patcher = patch("services.license_manager.check_seat_available", return_value=(True, ""))
        seat_patcher.start()
        self.addCleanup(seat_patcher.stop)
        # Clean test users if left over
        execute("DELETE FROM users WHERE username IN ('test_applicant1', 'test_applicant2')")
        execute("DELETE FROM notifications WHERE content LIKE '%test_applicant%' OR content LIKE '%Applicant%'")

    def tearDown(self):
        if self._prev_allow_pub is not None:
            os.environ["ALLOW_PUBLIC_REGISTER"] = self._prev_allow_pub
        else:
            os.environ.pop("ALLOW_PUBLIC_REGISTER", None)
        execute("DELETE FROM users WHERE username IN ('test_applicant1', 'test_applicant2')")
        execute("DELETE FROM notifications WHERE content LIKE '%test_applicant%' OR content LIKE '%Applicant%'")

    def test_signup_enters_pending_and_blocks_login_until_approved(self):
        import json
        from handlers.auth_handlers import handle_account_register, handle_account_login
        from router import handle_post_admin_user_approve, handle_post_admin_user_reject, handle_get_admin_users

        # 1. Register new account
        handler = MockHTTPHandler()
        reg_payload = json.dumps({
            "username": "test_applicant1",
            "name": "Applicant One",
            "org": "dev",
            "password": "Password1234!",
            "email": "applicant1@company.com"
        }).encode("utf-8")

        with patch("services.license_manager.check_seat_available", return_value=(True, "")):
            handle_account_register(handler, reg_payload, "127.0.0.1")
        self.assertEqual(handler.status_code, 200)
        self.assertTrue(handler.response_body.get("ok"))
        self.assertTrue(handler.response_body.get("pending"))

        # Verify database state
        user_row = get_one("SELECT * FROM users WHERE username = 'test_applicant1'")
        self.assertIsNotNone(user_row)
        self.assertEqual(user_row.get("status"), "pending")
        self.assertEqual(user_row.get("disabled"), 1)
        user_id = user_row["id"]

        # 2. Try logging in before approval -> Should be rejected with 403
        login_handler = MockHTTPHandler()
        login_payload = json.dumps({
            "username": "test_applicant1",
            "password": "Password1234!"
        }).encode("utf-8")
        handle_account_login(login_handler, login_payload, "127.0.0.1")
        self.assertEqual(login_handler.status_code, 403)
        self.assertIn("승인 대기", login_handler.response_body.get("error", ""))

        # 3. Non-admin cannot approve
        member_handler = MockHTTPHandler(session={"name": "RegularMember", "org": "dev", "role": "member", "isAdmin": False})
        approve_payload = json.dumps({"id": user_id, "role": "manager"}).encode("utf-8")
        handle_post_admin_user_approve(member_handler, approve_payload, "127.0.0.1")
        self.assertEqual(member_handler.status_code, 403)

        # 4. Admin approves request
        admin_handler = MockHTTPHandler(session={"name": "AdminBoss", "org": "dev", "role": "admin", "isAdmin": True})
        handle_post_admin_user_approve(admin_handler, approve_payload, "127.0.0.1")
        self.assertEqual(admin_handler.status_code, 200)
        self.assertTrue(admin_handler.response_body.get("ok"))

        # Check DB state after approval
        updated_row = get_one("SELECT * FROM users WHERE id = ?", (user_id,))
        self.assertEqual(updated_row.get("status"), "active")
        self.assertEqual(updated_row.get("disabled"), 0)
        self.assertEqual(updated_row.get("role"), "manager")

        # 5. Approved user can now log in
        login_handler2 = MockHTTPHandler()
        handle_account_login(login_handler2, login_payload, "127.0.0.1")
        self.assertEqual(login_handler2.status_code, 200)
        self.assertTrue(login_handler2.response_body.get("ok"))

    def test_signup_rejection_workflow(self):
        import json
        from handlers.auth_handlers import handle_account_register, handle_account_login
        from router import handle_post_admin_user_reject

        # 1. Register user 2
        handler = MockHTTPHandler()
        reg_payload = json.dumps({
            "username": "test_applicant2",
            "name": "Applicant Two",
            "org": "dev",
            "password": "Password1234!",
            "email": "applicant2@company.com"
        }).encode("utf-8")
        with patch("services.license_manager.check_seat_available", return_value=(True, "")):
            handle_account_register(handler, reg_payload, "127.0.0.1")
        user_row = get_one("SELECT * FROM users WHERE username = 'test_applicant2'")
        user_id = user_row["id"]

        # 2. Admin rejects user 2
        admin_handler = MockHTTPHandler(session={"name": "AdminBoss", "org": "dev", "role": "admin", "isAdmin": True})
        reject_payload = json.dumps({"id": user_id}).encode("utf-8")
        handle_post_admin_user_reject(admin_handler, reject_payload, "127.0.0.1")
        self.assertEqual(admin_handler.status_code, 200)

        # Check DB state
        rejected_row = get_one("SELECT * FROM users WHERE id = ?", (user_id,))
        self.assertEqual(rejected_row.get("status"), "rejected")
        self.assertEqual(rejected_row.get("disabled"), 1)

        # 3. User 2 login blocked with rejection notice
        login_handler = MockHTTPHandler()
        login_payload = json.dumps({
            "username": "test_applicant2",
            "password": "Password1234!"
        }).encode("utf-8")
        handle_account_login(login_handler, login_payload, "127.0.0.1")
        self.assertEqual(login_handler.status_code, 403)
        self.assertIn("반려", login_handler.response_body.get("error", ""))

    def test_get_admin_users_api_access(self):
        from router import handle_get_admin_users
        import urllib.parse

        # 1. Non-admin forbidden
        non_admin_handler = MockHTTPHandler(session={"name": "RegularUser", "org": "dev", "role": "member"})
        parsed = urllib.parse.urlparse("/api/admin/users")
        handle_get_admin_users(non_admin_handler, parsed, "127.0.0.1")
        self.assertEqual(non_admin_handler.status_code, 403)

        # 2. Admin allowed and returns user list with stats
        admin_handler = MockHTTPHandler(session={"name": "AdminBoss", "org": "dev", "role": "admin", "isAdmin": True})
        handle_get_admin_users(admin_handler, parsed, "127.0.0.1")
        self.assertEqual(admin_handler.status_code, 200)
        self.assertTrue(admin_handler.response_body.get("ok"))
        self.assertIn("users", admin_handler.response_body)
        self.assertIn("stats", admin_handler.response_body)


if __name__ == "__main__":
    unittest.main()
