#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import unittest
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_DIR = os.path.join(BASE_DIR, "server")
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from db import init_db, execute, query
from services.activity_store import append_activity
import services.jira_db as jira_db

class TestJiraActivitySecurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def test_append_activity_generates_uuid_when_id_missing(self):
        execute("DELETE FROM activities WHERE author_name = 'TestUUIDUser'")
        act1 = {
            "issue_key": "TEST-1",
            "action_type": "comment",
            "action_detail": "First comment",
            "author_name": "TestUUIDUser",
        }
        act2 = {
            "issue_key": "TEST-1",
            "action_type": "comment",
            "action_detail": "Second comment",
            "author_name": "TestUUIDUser",
        }
        append_activity(act1)
        append_activity(act2)

        rows = query("SELECT * FROM activities WHERE author_name = 'TestUUIDUser' ORDER BY id")
        self.assertEqual(len(rows), 2, "Both activities must be inserted even when id was missing")
        self.assertNotEqual(rows[0]["id"], "")
        self.assertNotEqual(rows[1]["id"], "")
        self.assertNotEqual(rows[0]["id"], rows[1]["id"])

    def test_upsert_jira_records_reraises_on_db_error(self):
        # Passing an invalid record structure that violates DB type or constraints raises
        with self.assertRaises(Exception):
            jira_db.upsert_jira_records([{"jira": {"key": None}, "id": None}])

    def test_update_record_details_validates_expected_version(self):
        from services.data_store import update_record_details
        from db import execute
        execute("INSERT OR REPLACE INTO records (id, dept_id, category, title, assignee_name) VALUES (999123, 'dev', '개발', 'Test', 'Tester')")
        rec, err = update_record_details(999123, expected_version="invalid_ver")
        self.assertIn("expected_version must be an integer", err)

    def test_update_record_details_unassign_sets_assignee_id_null(self):
        from services.data_store import update_record_details
        from db import execute, get_one
        u = get_one("SELECT id FROM users LIMIT 1")
        uid = u["id"] if u else 1
        execute("INSERT OR REPLACE INTO records (id, dept_id, category, title, assignee_name, assignee_id) VALUES (999123, 'dev', '개발', 'Test', 'Tester', ?)", (uid,))
        rec, err = update_record_details(999123, assignee_name="")
        row = get_one("SELECT assignee_name, assignee_id FROM records WHERE id = 999123")
        self.assertEqual(row["assignee_name"], "")
        self.assertIsNone(row["assignee_id"])

    def test_safe_delete_user_cleans_legacy_notifications_when_name_unique(self):
        from services.auth import create_user, safe_delete_user, hash_password
        from db import execute, get_one
        salt, h_pwd = hash_password("password123")
        user = create_user("UniqueDelUser", "unique_del_user", "dev", "unique_del@test.com", salt, h_pwd)
        self.assertIsNotNone(user)
        uid = user["id"]
        execute(
            "INSERT INTO notifications (id, recipient_user_id, recipient_name, recipient_email, title, content, created_at) "
            "VALUES ('notif_legacy_test_1', NULL, 'UniqueDelUser', '', 'Legacy Title', 'Content', '2026-11-03 10:00:00')"
        )
        ok = safe_delete_user(uid)
        self.assertTrue(ok)
        notif = get_one("SELECT id FROM notifications WHERE id = 'notif_legacy_test_1'")
        self.assertIsNone(notif, "Legacy notification should be deleted when user name was unique")

    def test_safe_delete_user_preserves_other_dept_participant_with_same_name(self):
        from services.auth import create_user, safe_delete_user, hash_password
        from db import execute, get_one
        execute("DELETE FROM users WHERE username IN ('same_dev_user', 'same_sales_user')")
        salt, h_pwd = hash_password("password123")
        user_dev = create_user("SameNameGuy", "same_dev_user", "dev", "same_dev@test.com", salt, h_pwd)
        user_sales = create_user("SameNameGuy", "same_sales_user", "sales", "same_sales@test.com", salt, h_pwd)
        self.assertIsNotNone(user_dev)
        self.assertIsNotNone(user_sales)

        execute("INSERT OR REPLACE INTO schedule_events (id, owner_name, owner_dept_id, title, type, start_date, end_date) VALUES (888101, 'OwnerGuy', 'sales', 'Event', 'meeting', '2026-11-03', '2026-11-03')")
        execute("INSERT INTO schedule_participants (id, event_id, user_name, user_dept_id, user_email, is_owner) VALUES (888991, 888101, 'SameNameGuy', 'sales', 'same_sales@test.com', 0)")
        ok = safe_delete_user(user_dev["id"])
        self.assertTrue(ok)

        part = get_one("SELECT id FROM schedule_participants WHERE id = 888991")
        self.assertIsNotNone(part, "Schedule participant from sales must be preserved when dev user deleted")
        safe_delete_user(user_sales["id"])
        execute("DELETE FROM schedule_events WHERE id = 888101")

    def test_logout_all_deletes_by_user_id(self):
        from services.auth import create_user, create_session, delete_all_user_sessions, safe_delete_user, hash_password
        from db import query
        salt, h_pwd = hash_password("password123")
        u1 = create_user("UserOne", "u1_sess", "dev", "u1@test.com", salt, h_pwd)
        u2 = create_user("UserTwo", "u2_sess", "dev", "u2@test.com", salt, h_pwd)
        t1 = create_session(u1["name"], u1["dept_id"], u1["email"], user_id=u1["id"])
        t2 = create_session(u2["name"], u2["dept_id"], u2["email"], user_id=u2["id"])

        delete_all_user_sessions(u1["id"])
        s1 = query("SELECT token FROM sessions WHERE user_id = ?", (u1["id"],))
        s2 = query("SELECT token FROM sessions WHERE user_id = ?", (u2["id"],))
        self.assertEqual(len(s1), 0, "User 1 sessions must be deleted")
        self.assertEqual(len(s2), 1, "User 2 sessions must be intact")
        safe_delete_user(u1["id"])
        safe_delete_user(u2["id"])

    def test_excel_export_sanitizes_formula_injection(self):
        import io
        import openpyxl
        from urllib.parse import urlparse
        from handlers.report_handler import handle_get_export_records_excel
        from services.data_store import append_record, delete_record, next_record_id

        # 1. Insert record with formula injection payloads
        execute("INSERT OR IGNORE INTO departments (id, name) VALUES ('test_dept', 'Test Department')")
        rec_id = next_record_id()
        rec_data = {
            "id": rec_id,
            "cardCode": "=1+1",
            "title": "@SUM(A1:A10)",
            "category": "-5+2",
            "assignee": "+cmd|' /C calc'!A0",
            "dept_id": "test_dept",
            "org": "test_dept",
            "status": "진행"
        }
        append_record(rec_data)

        class MockExcelHandler:
            def __init__(self):
                self.cfg = {}
                self.headers = {}
                self.wfile = io.BytesIO()
                self.code = None

            def _get_session_or_401(self):
                return {"id": 1, "name": "Admin", "role": "admin", "org": "lab"}

            def send_response(self, code):
                self.code = code

            def send_header(self, key, value):
                self.headers[key] = value

            def end_headers(self):
                pass

        try:
            handler = MockExcelHandler()
            parsed = urlparse("/api/records/export/excel")
            handle_get_export_records_excel(handler, parsed, "127.0.0.1")

            self.assertEqual(handler.code, 200)
            excel_bytes = handler.wfile.getvalue()
            self.assertGreater(len(excel_bytes), 0)

            # 2. Open workbook with openpyxl and verify cells
            wb = openpyxl.load_workbook(io.BytesIO(excel_bytes))
            ws = wb.active
            found_test_row = False
            for row in ws.iter_rows(values_only=True):
                # row columns: [code, title, cat, assignee, dept, status, s_date, e_date, jira_k]
                if row[0] == "'=1+1":
                    found_test_row = True
                    self.assertEqual(row[0], "'=1+1")
                    self.assertEqual(row[1], "'@SUM(A1:A10)")
                    self.assertEqual(row[2], "'-5+2")
                    self.assertTrue(row[3].startswith("'+cmd"))
            self.assertTrue(found_test_row, "Exported Excel must contain the sanitized test row starting with '")
        finally:
            if rec_id:
                delete_record(rec_id)

if __name__ == "__main__":
    unittest.main()
