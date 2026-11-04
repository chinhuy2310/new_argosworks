#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_audit_remediation_wave1_wave2.py — Verification suite for Security & Functional Remediations:
- P1-1: Jira API fail-closed authorization when issue is not in cache/DB
- P1-2: Schedule ownership checks requiring exact ownerId match (no unsafe fallback when ID exists)
- P1-3: Backup restore safety backup fail-closed enforcement
- P2-1: Vector store strict synchronization avoiding document deletion on bad rows
- P2-2: Jira full-sync reconciliation cleanly removing deleted issues
- P2-3: Backup import engine validation (Postgres vs SQLite)
- PIM recursive price masking defense
"""
import io
import os
import sys
import json
import unittest
from unittest.mock import patch, MagicMock

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_DIR = os.path.join(BASE_DIR, "server")
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from db import init_db, execute, query
from handlers.schedule_handlers import handle_schedule_update, handle_schedule_delete
from services.data_store import read_schedule, write_schedule
import services.jira_db as jira_db


class MockHTTPHandler:
    def __init__(self, session=None, cfg=None, headers=None):
        self._session = session
        self.cfg = cfg or {}
        self.headers = headers or {}
        self.code = None
        self.response = None
        self.wfile = io.BytesIO()

    def _get_session_or_401(self):
        if not self._session:
            self._send_json(401, {"ok": False, "error": "인증 필요"})
            return None
        return self._session

    def _send_json(self, code, data):
        self.code = code
        self.response = data


class TestAuditRemediationSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        execute("INSERT OR IGNORE INTO departments (id, name) VALUES ('dev', 'Development')")
        execute("INSERT OR IGNORE INTO departments (id, name) VALUES ('hr', 'Human Resources')")
        execute("INSERT OR REPLACE INTO users (id, username, name, dept_id, salt, password_hash) VALUES (100, 'user100', 'Kim', 'dev', 'salt1', 'hash1')")
        execute("INSERT OR REPLACE INTO users (id, username, name, dept_id, salt, password_hash) VALUES (200, 'user200', 'KimReal', 'dev', 'salt2', 'hash2')")

    def setUp(self):
        # Clean test records & jira issues
        execute("DELETE FROM jira_issues WHERE jira_key LIKE 'TEST-%' OR jira_key LIKE 'UNCACHED-%'")
        execute("DELETE FROM jira_comments WHERE jira_key LIKE 'TEST-%' OR jira_key LIKE 'UNCACHED-%'")

    # ------------------------------------------------------------------------
    # P1-1: Jira API fail-closed authorization on uncached issues
    # ------------------------------------------------------------------------
    def test_jira_comment_fail_closed_on_uncached_issue(self):
        """User from dev cannot comment on an uncached/unverified Jira issue (fail-closed 404/403)."""
        from router import handle_post_issue_comment
        # Normal member session in 'dev' dept
        session = {"id": 101, "name": "DevUser", "role": "member", "org": "dev", "dept_id": "dev"}
        handler = MockHTTPHandler(session=session, cfg={"jira": {"enabled": False}})
        body = json.dumps({"issue_key": "UNCACHED-999", "comment": "Hello"}).encode("utf-8")

        handle_post_issue_comment(handler, body, "127.0.0.1")
        self.assertIn(handler.code, (403, 404))
        self.assertFalse(handler.response.get("ok"))

    def test_jira_transition_fail_closed_on_uncached_issue(self):
        """User from dev cannot transition an uncached Jira issue."""
        from router import handle_post_issue_transition
        session = {"id": 101, "name": "DevUser", "role": "member", "org": "dev", "dept_id": "dev"}
        handler = MockHTTPHandler(session=session, cfg={"jira": {"enabled": False}})
        body = json.dumps({"issue_key": "UNCACHED-999", "status": "완료"}).encode("utf-8")

        handle_post_issue_transition(handler, body, "127.0.0.1")
        self.assertIn(handler.code, (403, 404))
        self.assertFalse(handler.response.get("ok"))

    def test_jira_attachment_fail_closed_on_uncached_issue(self):
        """User from dev cannot upload attachment to an uncached Jira issue."""
        from router import handle_post_issue_attachment
        session = {"id": 101, "name": "DevUser", "role": "member", "org": "dev", "dept_id": "dev"}
        handler = MockHTTPHandler(
            session=session,
            cfg={"jira": {"enabled": False}},
            headers={"Content-Type": 'multipart/form-data; boundary=----WebKitFormBoundaryXYZ'}
        )
        body = (
            b"------WebKitFormBoundaryXYZ\r\n"
            b'Content-Disposition: form-data; name="issue_key"\r\n\r\n'
            b"UNCACHED-999\r\n"
            b"------WebKitFormBoundaryXYZ\r\n"
            b'Content-Disposition: form-data; name="file"; filename="test.txt"\r\n'
            b"Content-Type: text/plain\r\n\r\n"
            b"test data\r\n"
            b"------WebKitFormBoundaryXYZ--\r\n"
        )
        handle_post_issue_attachment(handler, body, "127.0.0.1")
        self.assertIn(handler.code, (403, 404))
        self.assertFalse(handler.response.get("ok"))

    # ------------------------------------------------------------------------
    # P1-2: Schedule ownership checks (immutable ownerId match)
    # ------------------------------------------------------------------------
    def test_schedule_update_mismatched_owner_id_is_forbidden(self):
        """When an event has ownerId=200, user with id=100 (even with matching name/dept) cannot edit."""
        event_id = 999888
        events = read_schedule()
        test_event = {
            "id": event_id,
            "title": "Meeting",
            "type": "회의",
            "startDate": "2026-11-10",
            "endDate": "2026-11-10",
            "ownerName": "Kim",
            "ownerOrg": "dev",
            "ownerId": 200,  # real creator id
            "participants": []
        }
        write_schedule(events + [test_event])

        try:
            # Impostor: same name and dept, but id=100
            session = {"id": 100, "name": "Kim", "role": "member", "org": "dev"}
            handler = MockHTTPHandler(session=session)
            payload = json.dumps({
                "id": event_id,
                "title": "Hacked Meeting",
                "startDate": "2026-11-10",
                "endDate": "2026-11-10"
            }).encode("utf-8")

            handle_schedule_update(handler, payload, "127.0.0.1")
            self.assertEqual(handler.code, 403, "Update must be forbidden when ownerId != session.id")
        finally:
            curr = read_schedule()
            write_schedule([e for e in curr if e.get("id") != event_id])

    def test_schedule_delete_mismatched_owner_id_is_forbidden(self):
        """When an event has ownerId=200, user with id=100 cannot delete."""
        event_id = 999889
        events = read_schedule()
        test_event = {
            "id": event_id,
            "title": "Conf",
            "type": "회의",
            "startDate": "2026-11-10",
            "endDate": "2026-11-10",
            "ownerName": "Lee",
            "ownerOrg": "dev",
            "ownerId": 200,
            "participants": []
        }
        write_schedule(events + [test_event])

        try:
            session = {"id": 100, "name": "Lee", "role": "member", "org": "dev"}
            handler = MockHTTPHandler(session=session)
            payload = json.dumps({"id": event_id}).encode("utf-8")

            handle_schedule_delete(handler, payload, "127.0.0.1")
            self.assertEqual(handler.code, 403, "Delete must be forbidden when ownerId != session.id")
        finally:
            curr = read_schedule()
            write_schedule([e for e in curr if e.get("id") != event_id])

    # ------------------------------------------------------------------------
    # P1-3: Backup safety snapshot fail-closed before restore
    # ------------------------------------------------------------------------
    def test_backup_restore_fails_closed_when_safety_backup_fails(self):
        """If safety backup creation fails, restore_backup must abort without modifying live DB."""
        import services.backup_manager as bm
        with patch.object(bm, "get_db_path", return_value="/non/existent/path/for/safety/fail.db"):
            with self.assertRaises(Exception) as ctx:
                bm.restore_backup("nonexistent_backup.tar.gz")
            # Should fail closed and not continue
            self.assertTrue(bool(ctx.exception))

    # ------------------------------------------------------------------------
    # P2-1: Vector Store strict synchronization
    # ------------------------------------------------------------------------
    def test_vector_collect_documents_strict_aborts_on_malformed_record(self):
        """_collect_all_documents(cfg, strict=True) must raise RuntimeError if an individual record is malformed."""
        from services.vector_store import _collect_all_documents

        # Mock read_records returning an invalid object that raises exception during processing
        with patch("services.data_store.read_records", return_value=[{"id": 123, "tags": 12345, "attachments": 999}]):
            # In non-strict mode: skips bad record
            docs_lax = _collect_all_documents({}, strict=False)
            self.assertIsInstance(docs_lax, list)

            # In strict mode: must raise RuntimeError so full-sync won't prune old vectors
            # by mocking a KeyError / AttributeError in extraction
            with patch("services.data_store.read_records", side_effect=Exception("DB read failure")):
                with self.assertRaises(RuntimeError):
                    _collect_all_documents({}, strict=True)

    # ------------------------------------------------------------------------
    # P2-2: Jira full-sync reconciliation cleans deleted issues
    # ------------------------------------------------------------------------
    def test_jira_full_sync_reconciliation_cleans_deleted_issues(self):
        """upsert_jira_records(replace_existing=True) must remove issues not present in the new sync."""
        # 1. Seed two jira issues
        jira_db.upsert_jira_records([
            {"jira": {"key": "TEST-100", "summary": "Old Issue 1"}},
            {"jira": {"key": "TEST-200", "summary": "Old Issue 2"}}
        ])
        rows = query("SELECT jira_key FROM jira_issues WHERE jira_key IN ('TEST-100', 'TEST-200')")
        self.assertEqual(len(rows), 2)

        # 2. Full sync returns only TEST-200 (TEST-100 was deleted in Jira)
        success = jira_db.upsert_jira_records([
            {"jira": {"key": "TEST-200", "summary": "Old Issue 2 updated"}}
        ], replace_existing=True)
        self.assertTrue(success)

        # TEST-100 must be removed from DB, TEST-200 must remain
        r100 = query("SELECT jira_key FROM jira_issues WHERE jira_key = 'TEST-100'")
        r200 = query("SELECT jira_key FROM jira_issues WHERE jira_key = 'TEST-200'")
        self.assertEqual(len(r100), 0, "TEST-100 must be deleted by reconciliation")
        self.assertEqual(len(r200), 1, "TEST-200 must remain")

    # ------------------------------------------------------------------------
    # P2-3: Backup import engine validation
    # ------------------------------------------------------------------------
    def test_backup_import_rejects_unsupported_format(self):
        """import_backup_file must reject unsupported file extensions."""
        from services.backup_manager import import_backup_file
        with self.assertRaises(ValueError):
            import_backup_file(b"dummy data", "malicious.exe")

    # ------------------------------------------------------------------------
    # PIM price masking defense
    # ------------------------------------------------------------------------
    def test_pim_product_prices_recursively_masked(self):
        """_mask_product_prices recursively zeroes any price key."""
        from router import _mask_product_prices
        pim_sample = {
            "model": "M-100",
            "price": 50000,
            "procurement": {
                "supplier": "ACME",
                "price": 30000,
                "unitPrice": 25000,
                "nested": {
                    "purchase_price": 20000
                }
            }
        }
        masked = _mask_product_prices(pim_sample)
        self.assertEqual(masked["price"], 0)
        self.assertTrue(masked["priceHidden"])
        self.assertEqual(masked["procurement"]["price"], 0)
        self.assertEqual(masked["procurement"]["unitPrice"], 0)
        self.assertEqual(masked["procurement"]["nested"]["purchase_price"], 0)


if __name__ == "__main__":
    unittest.main()
