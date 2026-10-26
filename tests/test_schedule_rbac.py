# -*- coding: utf-8 -*-
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from db import init_db, execute, query
from services.data_store import write_schedule
from router import handle_get_schedule


class MockHandler:
    def __init__(self, session):
        self.session = session
        self.status = None
        self.body = None
        self.cfg = {"jira": {"enabled": False}}

    def _get_session_or_401(self):
        return self.session

    def _send_json(self, status, payload, extra_headers=None):
        self.status = status
        self.body = payload


class TestScheduleRBACPartitioning(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        self.license_patch = patch("services.license_manager.is_system_read_only", return_value=False)
        self.license_patch.start()

        # Clean test users
        execute("DELETE FROM users WHERE username LIKE 'sched_test_%'")
        test_users = [
            (881001, "sched_test_admin", "관리자A", "mgmt", "adm@test.local", 1, "admin"),
            (881002, "sched_test_dev_mgr", "개발팀장", "dev", "dev_mgr@test.local", 0, "manager"),
            (881003, "sched_test_dev_usr", "개발팀원", "dev", "dev_usr@test.local", 0, "member"),
            (881004, "sched_test_sales_mgr", "영업팀장", "sales", "sales_mgr@test.local", 0, "manager"),
            (881005, "sched_test_sales_usr", "영업팀원", "sales", "sales_usr@test.local", 0, "member"),
        ]
        for uid, username, name, dept, email, is_admin, role in test_users:
            execute("""INSERT INTO users (id, username, name, dept_id, email, salt, password_hash, is_admin, role, disabled, status)
                       VALUES (?, ?, ?, ?, ?, 'salt', 'hash', ?, ?, 0, 'active')""",
                    (uid, username, name, dept, email, is_admin, role))

        # Setup test schedule events
        events = [
            {
                "id": 8801,
                "ownerKey": "개발팀장|dev",
                "ownerName": "개발팀장",
                "ownerOrg": "dev",
                "ownerEmail": "dev_mgr@test.local",
                "type": "회의",
                "title": "개발팀 스프린트 미팅",
                "startDate": "2026-11-01",
                "endDate": "2026-11-01",
                "approval_status": "approved",
                "participants": []
            },
            {
                "id": 8802,
                "ownerKey": "영업팀장|sales",
                "ownerName": "영업팀장",
                "ownerOrg": "sales",
                "ownerEmail": "sales_mgr@test.local",
                "type": "회의",
                "title": "영업팀 전략 미팅",
                "startDate": "2026-11-02",
                "endDate": "2026-11-02",
                "approval_status": "approved",
                "participants": []
            }
        ]
        write_schedule(events)

    def tearDown(self):
        self.license_patch.stop()
        execute("DELETE FROM users WHERE username LIKE 'sched_test_%'")

    def test_member_only_sees_own_department(self):
        """User thường ở dev chỉ thấy thành viên và sự kiện của dev."""
        sess = {
            "id": 881003, "user_id": 881003, "username": "sched_test_dev_usr",
            "name": "개발팀원", "org": "dev", "dept_id": "dev",
            "role": "member", "is_admin": 0
        }
        h = MockHandler(sess)
        handle_get_schedule(h, None, "127.0.0.1")
        self.assertEqual(h.status, 200)
        body = h.body
        self.assertTrue(body["ok"])

        # Members: only dev members
        member_names = [m["name"] for m in body["members"]]
        self.assertIn("개발팀원", member_names)
        self.assertIn("개발팀장", member_names)
        self.assertNotIn("영업팀장", member_names)
        self.assertNotIn("영업팀원", member_names)

        # Events: only dev events
        event_titles = [e["title"] for e in body["events"]]
        self.assertIn("개발팀 스프린트 미팅", event_titles)
        self.assertNotIn("영업팀 전략 미팅", event_titles)

    def test_manager_only_sees_own_department(self):
        """Manager ở dev chỉ thấy thành viên và sự kiện của dev."""
        sess = {
            "id": 881002, "user_id": 881002, "username": "sched_test_dev_mgr",
            "name": "개발팀장", "org": "dev", "dept_id": "dev",
            "role": "manager", "is_admin": 0
        }
        h = MockHandler(sess)
        handle_get_schedule(h, None, "127.0.0.1")
        self.assertEqual(h.status, 200)
        body = h.body

        # Members: only dev
        member_names = [m["name"] for m in body["members"]]
        self.assertIn("개발팀장", member_names)
        self.assertIn("개발팀원", member_names)
        self.assertNotIn("영업팀장", member_names)
        self.assertNotIn("영업팀원", member_names)

        # Events: only dev
        event_titles = [e["title"] for e in body["events"]]
        self.assertIn("개발팀 스프린트 미팅", event_titles)
        self.assertNotIn("영업팀 전략 미팅", event_titles)

    def test_admin_sees_all_departments(self):
        """Admin thấy tất cả phòng ban."""
        sess = {
            "id": 881001, "user_id": 881001, "username": "sched_test_admin",
            "name": "관리자A", "org": "mgmt", "dept_id": "mgmt",
            "role": "admin", "is_admin": 1
        }
        h = MockHandler(sess)
        handle_get_schedule(h, None, "127.0.0.1")
        self.assertEqual(h.status, 200)
        body = h.body

        # Members: both dev and sales
        member_names = [m["name"] for m in body["members"]]
        self.assertIn("개발팀장", member_names)
        self.assertIn("영업팀장", member_names)

        # Events: both dev and sales
        event_titles = [e["title"] for e in body["events"]]
        self.assertIn("개발팀 스프린트 미팅", event_titles)
        self.assertIn("영업팀 전략 미팅", event_titles)


if __name__ == "__main__":
    unittest.main()
