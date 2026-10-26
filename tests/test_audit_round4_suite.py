"""
test_audit_round4_suite.py — Audit round 4 회귀 테스트.

검증 범위 (server/ 코드의 실제 결함 수정):
1. PostgreSQL 호환: `ORDER BY rowid` → `ORDER BY id` SQL 변환
2. `close_connection(force=...)` 계약 (per-request pool 종료 방지)
3. `find_record_by_key_or_code` 가 `is_private` 를 반환 (card code 기반 RBAC 우회 차단)
4. AI 챗 도구가 같은 부서의 비공개 카드를 card code 로 노출하지 않음
5. `/api/attachments/<card_code>/<file>` 가 비공개 카드 첨부파일을 차단
6. `/api/schedule` 이 같은 부서 타인의 비공개 카드를 노출하지 않음
7. 알림 SSE 가 수신자별로만 이벤트를 전달 (전체 broadcast 제거)
8. 동명이인(부서 다름) 알림 이름 매칭 비활성화 (fail-closed)
9. 만료 세션 정리가 슬라이딩 TTL(last_active_at)을 존중
10. 채팅 히스토리 limit 파싱 (비정상/음수 값)
11. Admin 이 문자열 id 로 본인 계정을 잠그지 못함
12. 프로필 수정: email 미전송 시 유지 + 소속 변경은 관리자 승인 대기
13. 초기 설정 마법사: id 없는 부서 목록 거부 (IndexError 방지)
14. product_categories DDL 이 요청마다 실행되지 않음
15. `mutate_schedule` 이 일정 read-modify-write 를 락으로 보호
"""
import json
import os
import queue
import sys
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

import db as db_module
from db import init_db, execute, get_one
from config import ATTACH_DIR
from services.auth import (
    create_user, hash_password, can_view_record, user_can_access_notification,
    cleanup_expired_sessions, get_session_ttl_seconds,
)
from services.data_store import (
    append_record, find_record_by_key_or_code, read_schedule, mutate_schedule,
    next_record_id, read_product_categories,
)
from services.notification_service import (
    subscribe_notifications, unsubscribe_notifications, broadcast_notification_event,
    add_notification, get_user_notifications,
)
from services import chat_store
from router import (
    handle_get_schedule,
    handle_get_local_attachment,
    handle_get_history,
    handle_post_admin_user_update,
)
from handlers.auth_handlers import handle_account_update_profile


# ---------------------------------------------------------------------------
# Test data identifiers (isolated, cleaned up in tearDown)
# ---------------------------------------------------------------------------
PRIV_REC_ID = 996720
PUB_REC_ID = 996721
PRIV_CARD_CODE = "R4DEV-PRIV"
PUB_CARD_CODE = "R4DEV-PUB"
PRIV_ATTACH_NAME = "r4-payroll.pdf"

DEV_MEMBER = {
    "id": 996110, "user_id": 996110, "username": "r4_dev_member", "name": "R4 Dev Member",
    "role": "member", "org": "dev", "dept_id": "dev", "email": "r4_dev_member@test.local", "is_admin": 0,
}
DEV_MANAGER = {
    "id": 996111, "user_id": 996111, "username": "r4_dev_manager", "name": "R4 Dev Manager",
    "role": "manager", "org": "dev", "dept_id": "dev", "email": "r4_dev_manager@test.local", "is_admin": 0,
}
ADMIN = {
    "id": 996112, "user_id": 996112, "username": "r4_admin", "name": "R4 Admin",
    "role": "admin", "org": "mgmt", "dept_id": "mgmt", "email": "r4_admin@test.local", "is_admin": 1,
}


class MockHandler:
    """Minimal handler stub capturing the JSON response / streamed file."""

    def __init__(self, session=None, cfg=None):
        self.session = session
        self.cfg = cfg if cfg is not None else {"jira": {"enabled": False, "api_token": ""}, "ai": {}, "voyage": {}}
        self.status = None
        self.body = None
        self.streamed = None
        self.headers = {}
        self.wfile = None

    def _get_session_or_401(self):
        if not self.session:
            self._send_json(401, {"ok": False, "error": "로그인이 필요합니다."})
            return None
        return self.session

    def _get_session_optional(self):
        return self.session

    def _send_json(self, status, payload, extra_headers=None):
        self.status = status
        self.body = payload

    def _extract_token(self):
        return None

    def _stream_file(self, path, content_type, download_name=None, inline=False, extra_headers=None):
        self.streamed = path
        self.status = 200


def _make_record(rec_id, org, title, assignee, card_code, is_private=0):
    return {
        "id": rec_id,
        "org": org,
        "category": "업무",
        "title": title,
        "project": "R4",
        "assignee": assignee,
        "assigneeEmail": "",
        "startDate": "2099-03-02",
        "dueDate": "2099-03-03",
        "date": "2099-03-02",
        "summary": "",
        "tags": [],
        "memo": "",
        "cardCode": card_code,
        "participants": "",
        "parentKey": "",
        "is_private": is_private,
        "jira": None,
    }


class TestAuditRound4Suite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        execute("DELETE FROM records WHERE id IN (?, ?)", (PRIV_REC_ID, PUB_REC_ID))
        execute("DELETE FROM notifications WHERE recipient_name LIKE 'R4 %' OR title LIKE 'R4 %'")
        execute("DELETE FROM chat_sessions WHERE user_name LIKE 'R4 %'")
        execute("DELETE FROM users WHERE username LIKE 'r4_%'")
        execute("DELETE FROM sessions WHERE user_name LIKE 'R4 %'")

        append_record(_make_record(PRIV_REC_ID, "dev", "R4 Private Payroll", "R4 Owner", PRIV_CARD_CODE, 1))
        append_record(_make_record(PUB_REC_ID, "dev", "R4 Public Task", "R4 Dev Member", PUB_CARD_CODE, 0))

        # Attachments are stored per record id.
        attach_dir = os.path.join(ATTACH_DIR, str(PRIV_REC_ID))
        os.makedirs(attach_dir, exist_ok=True)
        with open(os.path.join(attach_dir, PRIV_ATTACH_NAME), "wb") as f:
            f.write(b"%PDF-1.4 r4 audit fixture")

    def tearDown(self):
        execute("DELETE FROM records WHERE id IN (?, ?)", (PRIV_REC_ID, PUB_REC_ID))
        execute("DELETE FROM notifications WHERE recipient_name LIKE 'R4 %' OR title LIKE 'R4 %'")
        execute("DELETE FROM chat_sessions WHERE user_name LIKE 'R4 %'")
        execute("DELETE FROM users WHERE username LIKE 'r4_%'")
        execute("DELETE FROM sessions WHERE user_name LIKE 'R4 %'")
        fpath = os.path.join(ATTACH_DIR, str(PRIV_REC_ID), PRIV_ATTACH_NAME)
        if os.path.isfile(fpath):
            try:
                os.remove(fpath)
            except OSError:
                pass

    # ---------------------------------------------------------------- 1. PG SQL
    def test_translate_sql_order_by_rowid_uses_primary_key(self):
        """ORDER BY rowid is SQLite-only; PostgreSQL must fall back to ORDER BY id."""
        translated = db_module._translate_sql(
            "SELECT id, name FROM departments ORDER BY rowid"
        )
        self.assertIsNotNone(translated)
        self.assertNotIn("rowid", translated.lower())
        self.assertIn("ORDER BY ID", translated.upper())

    # ------------------------------------------------- 2. close_connection contract
    def test_close_connection_accepts_force_flag(self):
        """Both engines must accept close_connection(force=True) (restore path)."""
        import inspect
        params = inspect.signature(db_module.close_connection).parameters
        self.assertIn("force", params)
        db_module.close_connection()
        db_module.close_connection(force=True)

    # ------------------------------------------- 3. is_private on record lookup
    def test_find_record_by_key_or_code_returns_is_private(self):
        """RBAC fields must survive the card-code lookup path."""
        rec = find_record_by_key_or_code(PRIV_CARD_CODE)
        self.assertIsNotNone(rec)
        self.assertEqual(int(rec.get("is_private") or 0), 1)
        self.assertFalse(can_view_record(DEV_MEMBER, rec))
        self.assertTrue(can_view_record(DEV_MANAGER, rec))
        self.assertTrue(can_view_record(ADMIN, rec))

    # --------------------------------- 4. AI chat tool must not leak private card
    def test_chat_tool_details_block_same_dept_private_by_card_code(self):
        from services.chat_tools import _tool_get_issue_details
        cfg = {"jira": {"enabled": False}}
        res = _tool_get_issue_details({"issue_key": PRIV_CARD_CODE}, current_user=DEV_MEMBER, cfg=cfg)
        self.assertFalse(res.get("found", True))
        self.assertNotIn("R4 Private Payroll", json.dumps(res, ensure_ascii=False))

        res_pub = _tool_get_issue_details({"issue_key": PUB_CARD_CODE}, current_user=DEV_MEMBER, cfg=cfg)
        self.assertTrue(res_pub.get("found"))

    # ------------------------------------- 5. attachment download by card code
    def test_local_attachment_by_card_code_blocks_private_card(self):
        path = f"/api/attachments/{PRIV_CARD_CODE}/{PRIV_ATTACH_NAME}"
        member = MockHandler(DEV_MEMBER)
        handle_get_local_attachment(member, urlparse(path), "127.0.0.1")
        self.assertIn(member.status, (403, 404))
        self.assertIsNone(member.streamed, "private attachment must not be streamed")

        admin = MockHandler(ADMIN)
        handle_get_local_attachment(admin, urlparse(path), "127.0.0.1")
        self.assertEqual(admin.status, 200)
        self.assertTrue(admin.streamed and admin.streamed.endswith(PRIV_ATTACH_NAME))

    # ------------------------------------------------ 6. calendar private leak
    def test_schedule_excludes_private_card_from_same_dept_member(self):
        member = MockHandler(DEV_MEMBER)
        handle_get_schedule(member, urlparse("/api/schedule"), "127.0.0.1")
        self.assertEqual(member.status, 200)
        payload = json.dumps(member.body, ensure_ascii=False)
        self.assertNotIn(PRIV_CARD_CODE, payload)
        self.assertNotIn("R4 Private Payroll", payload)

        manager = MockHandler(DEV_MANAGER)
        handle_get_schedule(manager, urlparse("/api/schedule"), "127.0.0.1")
        self.assertEqual(manager.status, 200)
        self.assertIn(PRIV_CARD_CODE, json.dumps(manager.body, ensure_ascii=False))


    # ----------------------------------------------------- 7. SSE notification
    def test_notification_sse_only_delivers_to_recipient(self):
        salt, pwd_hash = hash_password("R4Passw0rd!")
        self.assertTrue(create_user("R4 Alice", "r4_alice", "dev", "r4_alice@test.local",
                                    salt, pwd_hash, role="member"))
        self.assertTrue(create_user("R4 Bob", "r4_bob", "sales", "r4_bob@test.local",
                                    salt, pwd_hash, role="member"))

        q_alice, q_bob = queue.Queue(), queue.Queue()
        subscribe_notifications(q_alice, {"email": "r4_alice@test.local", "name": "R4 Alice"})
        subscribe_notifications(q_bob, {"email": "r4_bob@test.local", "name": "R4 Bob"})
        try:
            broadcast_notification_event("new_notification", {
                "recipient_email": "r4_alice@test.local",
                "recipient_name": "R4 Alice",
                "title": "R4 Secret for Alice",
                "content": "only alice",
            })
            self.assertFalse(q_alice.empty(), "recipient must receive the event")
            self.assertTrue(q_bob.empty(), "other users must NOT receive the event")

            broadcast_notification_event("new_notification", {
                "recipient_email": "all", "recipient_name": "",
                "title": "R4 Broadcast", "content": "everyone",
            })
            self.assertFalse(q_alice.empty())
            self.assertFalse(q_bob.empty(), "broadcast notifications reach everyone")
        finally:
            unsubscribe_notifications(q_alice)
            unsubscribe_notifications(q_bob)

    # ------------------------------------------ 8. duplicate display-name safety
    def test_notification_name_matching_disabled_on_duplicate_names(self):
        salt, pwd_hash = hash_password("R4Passw0rd!")
        dup_dev = create_user("R4 Dup", "r4_dup1", "dev", "r4_dup1@test.local",
                              salt, pwd_hash, role="member")
        self.assertTrue(dup_dev)
        self.assertTrue(create_user("R4 Dup", "r4_dup2", "sales", "r4_dup2@test.local",
                                    salt, pwd_hash, role="member"))

        notif_row = {"recipient_email": "", "recipient_name": "R4 Dup"}
        self.assertFalse(user_can_access_notification(
            {"id": dup_dev["id"], "name": "R4 Dup", "org": "dev", "email": "r4_dup1@test.local"},
            notif_row
        ))

        add_notification(recipient_email="", recipient_name="R4 Dup",
                         sender_name="R4 Alice", title="R4 Dup Target",
                         content="ambiguous recipient")
        rows = get_user_notifications(user_email="", user_name="R4 Dup", is_admin=False)
        self.assertNotIn("R4 Dup Target", [r.get("title") for r in rows])

    # ------------------------------------------- 9. sliding session TTL cleanup
    def test_cleanup_keeps_sessions_with_recent_activity(self):
        ttl = get_session_ttl_seconds()
        old = 1000.0
        recent = time.time() - 60
        execute(
            """INSERT INTO sessions(token, user_id, user_name, user_dept_id, user_email, is_admin, created_at, last_active_at)
               VALUES (?, NULL, ?, ?, '', 0, ?, ?)""",
            ("r4_session_hash_active", "R4 Active", "dev", old, recent)
        )
        execute(
            """INSERT INTO sessions(token, user_id, user_name, user_dept_id, user_email, is_admin, created_at, last_active_at)
               VALUES (?, NULL, ?, ?, '', 0, ?, ?)""",
            ("r4_session_hash_stale", "R4 Stale", "dev", old, old - ttl - 10)
        )
        cleanup_expired_sessions()
        self.assertIsNotNone(get_one("SELECT token FROM sessions WHERE token = ?", ("r4_session_hash_active",)))
        self.assertIsNone(get_one("SELECT token FROM sessions WHERE token = ?", ("r4_session_hash_stale",)))


    # --------------------------------------------- 10. chat history limit parse
    def test_chat_history_limit_is_safely_bounded(self):
        sess = chat_store.create_session("R4 Chatter", "dev", "R4 chat")
        for i in range(5):
            chat_store.append_message(sess["id"], "user", f"r4 message {i}", "R4 Chatter")

        session_ctx = {"id": 996199, "name": "R4 Chatter", "org": "dev", "role": "member"}

        bad = MockHandler(session_ctx)
        handle_get_history(bad, urlparse(f"/api/chat/history?sessionId={sess['id']}&limit=abc"), "127.0.0.1")
        self.assertEqual(bad.status, 200, "non-numeric limit must not 500")
        self.assertEqual(len(bad.body["messages"]), 5)

        negative = MockHandler(session_ctx)
        handle_get_history(negative, urlparse(f"/api/chat/history?sessionId={sess['id']}&limit=-5"), "127.0.0.1")
        self.assertEqual(negative.status, 200)
        self.assertEqual(len(negative.body["messages"]), 1, "negative limit is clamped to 1")

        foreign = MockHandler({"id": 996198, "name": "R4 Other", "org": "dev", "role": "member"})
        handle_get_history(foreign, urlparse(f"/api/chat/history?sessionId={sess['id']}"), "127.0.0.1")
        self.assertEqual(foreign.status, 403)

        unknown = MockHandler(session_ctx)
        handle_get_history(unknown, urlparse("/api/chat/history?sessionId=sess_does_not_exist"), "127.0.0.1")
        self.assertEqual(unknown.status, 404)

    # ------------------------------------- 11. admin cannot lock itself (string id)
    def test_admin_cannot_disable_self_via_string_id(self):
        salt, pwd_hash = hash_password("R4Passw0rd!")
        admin_user = create_user("R4 Real Admin", "r4_real_admin", "mgmt", "r4_real_admin@test.local",
                                 salt, pwd_hash, role="admin", is_admin=True)
        self.assertTrue(admin_user)

        session_ctx = {
            "id": admin_user["id"], "user_id": admin_user["id"], "username": "r4_real_admin",
            "name": "R4 Real Admin", "org": "mgmt", "role": "admin", "email": "r4_real_admin@test.local",
        }
        handler = MockHandler(session_ctx)
        body = json.dumps({"id": str(admin_user["id"]), "disabled": 1}).encode("utf-8")
        handle_post_admin_user_update(handler, body, "127.0.0.1")

        self.assertEqual(handler.status, 400)
        row = get_one("SELECT disabled FROM users WHERE id = ?", (admin_user["id"],))
        self.assertEqual(int(row["disabled"] or 0), 0, "self-lockout must be blocked")

    # ------------------------- 12. profile update: email kept + dept deferred
    def test_profile_update_keeps_email_and_defers_dept_change(self):
        salt, pwd_hash = hash_password("R4Passw0rd!")
        user = create_user("R4 Profile", "r4_profile", "dev", "r4_profile@test.local",
                           salt, pwd_hash, role="member")
        self.assertTrue(user)
        session_ctx = {
            "id": user["id"], "user_id": user["id"], "username": "r4_profile",
            "name": "R4 Profile", "org": "dev", "role": "member", "email": "r4_profile@test.local",
        }

        handler = MockHandler(session_ctx)
        payload = json.dumps({"name": "R4 Profile"}).encode("utf-8")
        handle_account_update_profile(handler, payload, "127.0.0.1")
        self.assertEqual(handler.status, 200)
        row = get_one("SELECT email, dept_id FROM users WHERE id = ?", (user["id"],))
        self.assertEqual(row["email"], "r4_profile@test.local", "omitted email must be preserved")

        # Department change by a non-admin is deferred to an admin approval.
        target_org = "sales" if (row["dept_id"] or "").lower() != "sales" else "hr"
        handler2 = MockHandler(session_ctx)
        payload2 = json.dumps({"name": "R4 Profile", "org": target_org}).encode("utf-8")
        handle_account_update_profile(handler2, payload2, "127.0.0.1")
        self.assertEqual(handler2.status, 200)
        self.assertTrue(handler2.body.get("deptChangePending"))
        self.assertEqual(handler2.body["user"]["org"], "dev", "dept must not change immediately")
        row2 = get_one("SELECT dept_id FROM users WHERE id = ?", (user["id"],))
        self.assertEqual((row2["dept_id"] or "").lower(), "dev")


    # ------------------------------------------- 13. setup wizard dept validation
    def test_setup_rejects_departments_without_ids(self):
        from handlers import setup_handler

        handler = MockHandler(None)
        body = json.dumps({
            "license_key": "r4-dummy-license",
            "admin": {"username": "r4root", "name": "R4 Root", "password": "R4Passw0rd!", "email": ""},
            "departments": [{"name": "No Id Dept"}],
            "admin_dept_id": "",
        }).encode("utf-8")

        with patch.object(setup_handler, "check_needs_setup", return_value=True), \
             patch("services.license_manager.verify_license_key",
                   return_value=(True, "ok", {"customer": "R4 Co", "seats": 5,
                                              "expiry": "2099-01-01", "modules": []})):
            setup_handler.handle_post_setup_complete(handler, body, "127.0.0.1")

        self.assertEqual(handler.status, 400)
        self.assertIn("부서", handler.body.get("error", ""))

    # --------------------------------------- 14. product_categories DDL once
    def test_product_categories_ddl_runs_once_per_database(self):
        import services.data_store as ds
        ds._PRODUCT_CATEGORIES_READY.clear()
        ddl_calls = {"count": 0}
        real_execute = ds.execute

        def _counting_execute(sql, params=()):
            if "CREATE TABLE IF NOT EXISTS product_categories" in sql:
                ddl_calls["count"] += 1
            return real_execute(sql, params)

        with patch.object(ds, "execute", side_effect=_counting_execute):
            read_product_categories()
            read_product_categories()
            read_product_categories()

        self.assertEqual(ddl_calls["count"], 1, "DDL must not run on every read")

    # ---------------------------------------------- 15. mutate_schedule locking
    def test_mutate_schedule_appends_under_lock(self):
        from services import data_store
        event_id = next_record_id()
        event = {
            "id": event_id, "ownerKey": "R4 Sched|dev", "ownerName": "R4 Sched",
            "ownerOrg": "dev", "ownerEmail": "", "type": "업무", "title": "R4 Mutate Event",
            "startDate": "2099-04-01", "endDate": "2099-04-01", "memo": "",
            "createdAt": "2099-04-01T00:00:00",
        }
        try:
            mutate_schedule(lambda events: events.append(dict(event)))
            self.assertTrue(any(str(e.get("id")) == str(event_id) for e in read_schedule()))
            self.assertFalse(data_store._save_lock.locked(), "lock must be released")
        finally:
            def _drop(events):
                events[:] = [e for e in events if str(e.get("id")) != str(event_id)]
            mutate_schedule(_drop)


if __name__ == "__main__":
    unittest.main()

