import unittest
import os
import sys
import json

# Add server directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from db import init_db, execute, get_one, query
from services.auth import can_modify_record, can_delete_record, can_transition_status
from router import handle_delete_record, handle_post_issue_transition, handle_delete_record_attachment
from services.data_store import get_record_by_id


class MockRequestHelper:
    def __init__(self, session=None, token=None, path="/", headers=None):
        self.session = session
        self._current_session = session
        self.token = token
        self.path = path
        self.headers = headers or {}
        self.status_code = None
        self.response_body = None
        self.headers_sent = {}
        self.cfg = {"jira": {"enabled": False}}

    def _get_session_or_401(self):
        if self._current_session:
            return self._current_session
        self._send_json(401, {"ok": False, "error": "로그인이 필요합니다."})
        return None

    def _send_json(self, status, payload):
        self.status_code = status
        self.response_body = payload


class TestGovernanceRBAC(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        # Seed users with different roles for testing
        execute("""
            INSERT OR REPLACE INTO users (id, username, name, dept_id, email, is_admin, role, disabled, status, salt, password_hash)
            VALUES (9001, 'admin_gov', 'AdminGov', 'dev', 'admingov@test.com', 1, 'admin', 0, 'active', 's', 'p'),
                   (9002, 'manager_dev', 'MgrDev', 'dev', 'mgrdev@test.com', 0, 'manager', 0, 'active', 's', 'p'),
                   (9003, 'manager_sales', 'MgrSales', 'sales', 'mgrsales@test.com', 0, 'manager', 0, 'active', 's', 'p'),
                   (9004, 'member_dev', 'MemDev', 'dev', 'memdev@test.com', 0, 'member', 0, 'active', 's', 'p'),
                   (9005, 'viewer_dev', 'ViewDev', 'dev', 'viewdev@test.com', 0, 'viewer', 0, 'active', 's', 'p')
        """)

    @classmethod
    def tearDownClass(cls):
        execute("DELETE FROM users WHERE id IN (9001, 9002, 9003, 9004, 9005)")
        execute("DELETE FROM records WHERE id IN (88001, 88002, 88003)")
        execute("DELETE FROM notifications WHERE link_id = 'DEV-88003'")

    def setUp(self):
        self.admin_sess = {"id": 9001, "username": "admin_gov", "name": "AdminGov", "role": "admin", "is_admin": 1, "dept_id": "dev", "email": "admingov@test.com"}
        self.mgr_dev_sess = {"id": 9002, "username": "manager_dev", "name": "MgrDev", "role": "manager", "is_admin": 0, "dept_id": "dev", "email": "mgrdev@test.com"}
        self.mgr_sales_sess = {"id": 9003, "username": "manager_sales", "name": "MgrSales", "role": "manager", "is_admin": 0, "dept_id": "sales", "email": "mgrsales@test.com"}
        self.mem_dev_sess = {"id": 9004, "username": "member_dev", "name": "MemDev", "role": "member", "is_admin": 0, "dept_id": "dev", "email": "memdev@test.com"}
        self.viewer_sess = {"id": 9005, "username": "viewer_dev", "name": "ViewDev", "role": "viewer", "is_admin": 0, "dept_id": "dev", "email": "viewdev@test.com"}

        # Record belonging to 'dev' dept, assigned to 'MemDev'
        self.dev_rec = {
            "id": 88001,
            "dept_id": "dev",
            "org": "dev",
            "title": "DEV Task 1",
            "assignee_id": 9004,
            "assignee_name": "MemDev",
            "status": "진행",
            "card_code": "DEV-88001"
        }

    def test_delete_permissions_governance(self):
        # 1. Admin can delete
        self.assertTrue(can_delete_record(self.admin_sess, self.dev_rec))

        # 2. Manager of same department ('dev') can delete
        self.assertTrue(can_delete_record(self.mgr_dev_sess, self.dev_rec))

        # 3. Manager of different department ('sales') CANNOT delete
        self.assertFalse(can_delete_record(self.mgr_sales_sess, self.dev_rec))

        # 4. Member CANNOT delete (even if they are assignee!)
        self.assertFalse(can_delete_record(self.mem_dev_sess, self.dev_rec))

        # 5. Viewer CANNOT delete
        self.assertFalse(can_delete_record(self.viewer_sess, self.dev_rec))

    def test_status_transition_governance(self):
        # 1. Member can transition to '검토' (Review) or '진행' (In Progress)
        can_prog, _ = can_transition_status(self.mem_dev_sess, self.dev_rec, "진행")
        self.assertTrue(can_prog)

        can_rev, _ = can_transition_status(self.mem_dev_sess, self.dev_rec, "검토")
        self.assertTrue(can_rev)

        # 2. Member CANNOT transition to '완료' (Done)
        can_done, err_msg = can_transition_status(self.mem_dev_sess, self.dev_rec, "완료")
        self.assertFalse(can_done)
        self.assertIn("일반 사용자는 '완료' 상태로 직접 변경할 수 없습니다", err_msg)

        # 3. Manager of same dept CAN transition to '완료'
        can_mgr_done, _ = can_transition_status(self.mgr_dev_sess, self.dev_rec, "완료")
        self.assertTrue(can_mgr_done)

        # 4. Admin CAN transition to '완료'
        can_adm_done, _ = can_transition_status(self.admin_sess, self.dev_rec, "완료")
        self.assertTrue(can_adm_done)

        # 5. Manager of other dept CANNOT transition dev record to '완료'
        can_other_done, other_err = can_transition_status(self.mgr_sales_sess, self.dev_rec, "완료")
        self.assertFalse(can_other_done)

        # 6. Viewer CANNOT transition at all
        can_v, _ = can_transition_status(self.viewer_sess, self.dev_rec, "진행")
        self.assertFalse(can_v)

    def test_http_delete_handler_member_rejected(self):
        # Create actual record in DB
        execute("""
            INSERT OR REPLACE INTO records (id, dept_id, category, title, assignee_name, card_code, status)
            VALUES (88002, 'dev', '개발', 'Test HTTP Delete', 'MemDev', 'DEV-88002', '진행')
        """)
        rec = get_record_by_id(88002)
        self.assertIsNotNone(rec)

        # Member tries to delete -> 403 Forbidden
        req_member = MockRequestHelper(session=self.mem_dev_sess)
        handle_delete_record(req_member, json.dumps({"id": 88002}).encode('utf-8'), "127.0.0.1")
        self.assertEqual(req_member.status_code, 403)
        self.assertIn("삭제 권한이 없습니다", req_member.response_body.get("error", ""))

        # Admin tries to delete -> 200 OK
        req_admin = MockRequestHelper(session=self.admin_sess)
        handle_delete_record(req_admin, json.dumps({"id": 88002}).encode('utf-8'), "127.0.0.1")
        self.assertEqual(req_admin.status_code, 200)

    def test_viewer_cannot_transition_jira_issue(self):
        """Audit F-0001: a read-only viewer must never reach the Jira transition call."""
        from unittest.mock import patch

        called = []

        def _fake_transition(cfg, key, status):
            called.append((key, status))
            return True, "ok"

        req = MockRequestHelper(session=self.viewer_sess)
        with patch("router.transition_jira_issue", _fake_transition):
            handle_post_issue_transition(
                req,
                json.dumps({"issue_key": "JIRA-9999", "status": "완료"}).encode("utf-8"),
                "127.0.0.1",
            )

        self.assertEqual(req.status_code, 403)
        self.assertEqual(called, [], "viewer must never reach the Jira transition call")

    def test_delete_attachment_invalid_id_returns_400(self):
        """Audit F-0012: a non-numeric attachment id must be a 400, not a 500."""
        from unittest.mock import patch

        rec = {"id": 88001, "card_code": "DEV-88001", "dept_id": "dev", "assignee_name": "AdminGov"}
        req = MockRequestHelper(session=self.admin_sess)
        with patch("router.find_record_by_key_or_code", return_value=rec):
            handle_delete_record_attachment(
                req,
                json.dumps({"key": "DEV-88001", "id": "not-a-number"}).encode("utf-8"),
                "127.0.0.1",
            )

        self.assertEqual(req.status_code, 400)

    def test_http_transition_member_review_and_done(self):
        try:
            # Create record in DB
            execute("""
                INSERT OR REPLACE INTO records (id, dept_id, category, title, assignee_name, card_code, status)
                VALUES (88003, 'dev', '개발', 'Test Transition Workflow', 'MemDev', 'DEV-88003', '진행')
            """)

            # Member tries to transition to '완료' -> 403 Forbidden
            req_done = MockRequestHelper(session=self.mem_dev_sess)
            handle_post_issue_transition(req_done, json.dumps({"key": "DEV-88003", "status": "완료"}).encode('utf-8'), "127.0.0.1")
            self.assertEqual(req_done.status_code, 403)
            self.assertIn("일반 사용자는 '완료' 상태로 직접 변경할 수 없습니다", req_done.response_body.get("error", ""))

            # Member transitions to '검토' -> 200 OK and notification created
            req_rev = MockRequestHelper(session=self.mem_dev_sess)
            handle_post_issue_transition(req_rev, json.dumps({"key": "DEV-88003", "status": "검토"}).encode('utf-8'), "127.0.0.1")
            self.assertEqual(req_rev.status_code, 200)

            # Verify notification was sent to manager (mgrdev@test.com) and admin (admingov@test.com)
            notifs = query("SELECT * FROM notifications WHERE link_id = 'DEV-88003' ORDER BY id DESC")
            self.assertTrue(len(notifs) >= 1)
            recipients = [n["recipient_email"] for n in notifs]
            self.assertIn("mgrdev@test.com", recipients)
            self.assertIn("admingov@test.com", recipients)

            # Now Manager transitions to '완료' -> 200 OK
            req_mgr_done = MockRequestHelper(session=self.mgr_dev_sess)
            handle_post_issue_transition(req_mgr_done, json.dumps({"key": "DEV-88003", "status": "완료"}).encode('utf-8'), "127.0.0.1")
            self.assertEqual(req_mgr_done.status_code, 200)
        finally:
            execute("DELETE FROM records WHERE id = 88003")
            execute("DELETE FROM notifications WHERE link_id = 'DEV-88003'")


if __name__ == "__main__":
    unittest.main()
