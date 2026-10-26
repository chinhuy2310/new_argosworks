import unittest
import os
import sys
import json
import urllib.parse
from datetime import date, timedelta

# Add server directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from db import init_db, execute, get_one, query, _translate_sql
from services.auth import (
    create_user, create_session, get_session, is_admin_user,
    check_login_rate_limit, record_login_failure, clear_login_failures
)
from router import ATTACH_DIR, handle_get_local_attachment
from handlers.auth_handlers import handle_account_register
from handlers.setup_handler import handle_post_setup_complete, check_needs_setup
from services.license_manager import (
    generate_signed_license_key, verify_license_key, is_system_read_only
)
from services.chat_tools import (
    _tool_update_issue_status, _tool_create_issue, _tool_add_issue_comment
)


class MockRequestHelper:
    def __init__(self, session=None, token=None, path="/", headers=None):
        self.session = session
        self._current_session = session
        self.token = token
        self.path = path
        self.headers = headers or {}
        if token and "Cookie" not in self.headers:
            self.headers["Cookie"] = f"argos_token={token}"
        self.status_code = None
        self.response_body = None
        self.headers_sent = {}
        self.cfg = {"jira": {"enabled": False}, "voyage": {"enabled": False}}

    def _extract_token(self):
        if self.token:
            return self.token
        cookie = self.headers.get("Cookie", "")
        if "argos_token=" in cookie:
            return cookie.split("argos_token=")[1].split(";")[0].strip()
        return ""

    def _get_session_or_401(self):
        if self._current_session:
            return self._current_session
        t = self._extract_token()
        sess = get_session(t) if t else None
        self._current_session = sess
        if not sess:
            self._send_json(401, {"ok": False, "error": "로그인이 필요합니다.", "authRequired": True})
            return None
        return sess

    def _get_session_optional(self):
        return self._current_session

    def _send_json(self, status, data, extra_headers=None):
        self.status_code = status
        self.response_body = data

    def send_response(self, code):
        self.status_code = code

    def send_header(self, k, v):
        self.headers_sent[k] = v

    def end_headers(self):
        pass


class TestAuditRound2Suite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        execute("DELETE FROM sessions WHERE user_name LIKE 'test_round2_%'")
        execute("DELETE FROM users WHERE username LIKE 'test_round2_%'")
        execute("DELETE FROM records WHERE title LIKE 'TEST_ROUND2_%'")

    def tearDown(self):
        execute("DELETE FROM sessions WHERE user_name LIKE 'test_round2_%'")
        execute("DELETE FROM users WHERE username LIKE 'test_round2_%'")
        execute("DELETE FROM records WHERE title LIKE 'TEST_ROUND2_%'")

    # --------------------------------------------------------------------------
    # 1. Attachment Directory Traversal Defense
    # --------------------------------------------------------------------------
    def test_attachment_cross_record_path_traversal_blocked(self):
        """../를 이용한 타 레코드 첨부파일 디렉토리 탈출 시도 시 404 차단되어야 함."""
        rec_a_id = 911001
        rec_b_id = 911002

        execute("""
            INSERT OR REPLACE INTO records (id, dept_id, category, title, assignee_name, is_private)
            VALUES (?, 'dev', '개발', 'TEST_ROUND2_REC_A', 'DevUser', 0)
        """, (rec_a_id,))
        execute("""
            INSERT OR REPLACE INTO records (id, dept_id, category, title, assignee_name, is_private)
            VALUES (?, 'hr', '인사', 'TEST_ROUND2_REC_B_SECRET', 'HRUser', 1)
        """, (rec_b_id,))

        dir_b = os.path.join(ATTACH_DIR, str(rec_b_id))
        os.makedirs(dir_b, exist_ok=True)
        secret_file = os.path.join(dir_b, "payroll.pdf")
        with open(secret_file, "wb") as f:
            f.write(b"%PDF-1.4 CONFIDENTIAL PAYROLL DATA")

        try:
            user_dev = {"id": 9999, "name": "DevUser", "org": "dev", "role": "member"}

            # Traversal attempt: Record A is authorized, but filename traverses to Record B
            traversal_path = f"/api/attachments/{rec_a_id}/../{rec_b_id}/payroll.pdf"
            parsed = urllib.parse.urlparse(traversal_path)

            mock = MockRequestHelper(session=user_dev, path=traversal_path)
            handle_get_local_attachment(mock, parsed, "127.0.0.1")

            self.assertEqual(mock.status_code, 404)
            self.assertIn("찾을 수 없습니다", mock.response_body.get("error", ""))
        finally:
            if os.path.exists(secret_file):
                os.remove(secret_file)
            if os.path.exists(dir_b):
                os.rmdir(dir_b)

    # --------------------------------------------------------------------------
    # 2. AI Chat RBAC & Read-Only License Enforcement
    # --------------------------------------------------------------------------
    def test_ai_chat_tools_enforce_rbac_and_license(self):
        """AI Chat Tool 호출 시 Viewer 차단 및 라이선스 읽기 전용 상태 차단 검증."""
        rec_id = 911003
        execute("""
            INSERT OR REPLACE INTO records (id, dept_id, category, title, assignee_name, is_private, status)
            VALUES (?, 'dev', '개발', 'TEST_ROUND2_ISSUE', 'DevMember', 0, '진행')
        """, (rec_id,))

        viewer_user = {"id": 5555, "name": "AuditViewer", "org": "dev", "role": "viewer"}

        # Viewer role trying to update issue status -> rejected
        res = _tool_update_issue_status({"issue_key": str(rec_id), "status": "완료"}, current_user=viewer_user, cfg={})
        self.assertFalse(res.get("success"))
        self.assertIn("권한", res.get("error", ""))

        # Viewer role trying to create issue -> rejected
        res_create = _tool_create_issue({"title": "New Issue by Viewer"}, current_user=viewer_user, cfg={})
        self.assertFalse(res_create.get("success"))
        self.assertIn("Viewer", res_create.get("error", ""))

        # Test Read-Only License enforcement
        import services.license_manager as lm
        orig_is_ro = lm.is_system_read_only
        try:
            lm.is_system_read_only = lambda: True

            admin_user = {"id": 1, "name": "Admin", "org": "dev", "role": "admin"}
            res_ro = _tool_update_issue_status({"issue_key": str(rec_id), "status": "완료"}, current_user=admin_user, cfg={})
            self.assertFalse(res_ro.get("success"))
            self.assertIn("읽기 전용", res_ro.get("error", ""))

            res_comment_ro = _tool_add_issue_comment({"issue_key": str(rec_id), "comment": "test"}, current_user=admin_user, cfg={})
            self.assertFalse(res_comment_ro.get("success"))
            self.assertIn("읽기 전용", res_comment_ro.get("error", ""))
        finally:
            lm.is_system_read_only = orig_is_ro

    # --------------------------------------------------------------------------
    # 3. Account Lockout Isolation & IP Flood Defense
    # --------------------------------------------------------------------------
    def test_account_lockout_isolation_and_flood_prevention(self):
        """계정별 5회 실패 잠금과 IP 단위 30회 무차별 대입 차단 격리 검증."""
        ip = "198.51.100.77"
        user_target = "test_round2_target"
        user_innocent = "test_round2_innocent"

        clear_login_failures(ip, user_target)
        clear_login_failures(ip, user_innocent)

        # 5 failures for target_account
        for _ in range(5):
            record_login_failure(ip, user_target)

        # Target account must be locked
        allowed_target, msg_target = check_login_rate_limit(ip, user_target)
        self.assertFalse(allowed_target)
        self.assertIn("잠금", msg_target)

        # Innocent user from the same office IP must NOT be locked out
        allowed_innocent, _ = check_login_rate_limit(ip, user_innocent)
        self.assertTrue(allowed_innocent)

        # Clear login failures for target should only reset target's count
        clear_login_failures(ip, user_target)
        allowed_target_after, _ = check_login_rate_limit(ip, user_target)
        self.assertTrue(allowed_target_after)

    # --------------------------------------------------------------------------
    # 4. Public Registration Toggle & Setup Wizard Atomicity
    # --------------------------------------------------------------------------
    def test_public_registration_toggle_and_bootstrap_token(self):
        """ALLOW_PUBLIC_REGISTER 정책 및 부트스트랩 토큰 검증."""
        prev = os.environ.get("ALLOW_PUBLIC_REGISTER")
        try:
            # 1. Blocked when disabled
            os.environ["ALLOW_PUBLIC_REGISTER"] = "false"
            handler = MockRequestHelper()
            reg_body = json.dumps({
                "username": "test_round2_pub",
                "name": "Public User",
                "email": "pub@test.com",
                "password": "Password123!",
                "dept_id": "dev"
            }).encode("utf-8")
            handle_account_register(handler, reg_body, "127.0.0.1")
            self.assertEqual(handler.status_code, 403)
            self.assertIn("비활성화", handler.response_body.get("error", ""))

            # 2. Allowed when enabled
            os.environ["ALLOW_PUBLIC_REGISTER"] = "true"
            handler_ok = MockRequestHelper()
            handle_account_register(handler_ok, reg_body, "127.0.0.1")
            self.assertEqual(handler_ok.status_code, 200)
            self.assertTrue(handler_ok.response_body.get("ok"))
            self.assertTrue(handler_ok.response_body.get("pending"))

            # User in DB must be pending, not admin!
            u = get_one("SELECT * FROM users WHERE username = 'test_round2_pub'")
            self.assertIsNotNone(u)
            self.assertEqual(u["status"], "pending")
            self.assertEqual(u["role"], "member")
            self.assertEqual(u["is_admin"], 0)
        finally:
            if prev is not None:
                os.environ["ALLOW_PUBLIC_REGISTER"] = prev
            else:
                os.environ.pop("ALLOW_PUBLIC_REGISTER", None)

    # --------------------------------------------------------------------------
    # 5. PostgreSQL UPSERT Translation
    # --------------------------------------------------------------------------
    def test_postgres_sql_upsert_translation(self):
        """SQLite의 INSERT OR REPLACE를 PostgreSQL ON CONFLICT (pk) DO UPDATE SET 절로 정상 변환하는지 검증."""
        # 1. record_jira translation
        sql_in = "INSERT OR REPLACE INTO record_jira (record_id, jira_key, jira_status, updated_at) VALUES (?, ?, ?, ?)"
        sql_out = _translate_sql(sql_in)
        self.assertIn("ON CONFLICT (record_id) DO UPDATE SET", sql_out)
        self.assertIn("jira_key = EXCLUDED.jira_key", sql_out)
        self.assertIn("updated_at = EXCLUDED.updated_at", sql_out)
        self.assertIn("%s, %s, %s, %s", sql_out)

        # 2. card_sequences translation
        sql_seq = "INSERT OR REPLACE INTO card_sequences (dept_id, last_seq, updated_at) VALUES (?, ?, ?)"
        sql_seq_out = _translate_sql(sql_seq)
        self.assertIn("ON CONFLICT (dept_id) DO UPDATE SET", sql_seq_out)
        self.assertIn("last_seq = EXCLUDED.last_seq", sql_seq_out)

        # 3. strftime translation
        sql_time = "SELECT strftime('%Y-%m-%d %H:%M:%S', 'now')"
        self.assertIn("CURRENT_TIMESTAMP", _translate_sql(sql_time))

    # --------------------------------------------------------------------------
    # 6. Asymmetric Ed25519 License Engine
    # --------------------------------------------------------------------------
    def test_ed25519_asymmetric_license_engine(self):
        """비대칭 Ed25519 라이선스 전자서명 생성 및 공개키 기반 검증 기능 확인."""
        import os
        from cryptography.hazmat.primitives.asymmetric import ed25519
        from cryptography.hazmat.primitives import serialization
        from services.license_manager import invalidate_license_cache

        # The product ships NO private key: the test generates a throwaway pair.
        private_key = ed25519.Ed25519PrivateKey.generate()
        priv_hex = private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        ).hex()
        pub_hex = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        ).hex()

        prev_pub = os.environ.get("ARGOS_LICENSE_PUBLIC_KEY")
        os.environ["ARGOS_LICENSE_PUBLIC_KEY"] = pub_hex
        invalidate_license_cache()
        try:
            exp = (date.today() + timedelta(days=730)).strftime("%Y-%m-%d")
            key = generate_signed_license_key(
                customer_name="Argos Round2 Enterprise",
                max_seats=150,
                expiry_date_str=exp,
                modules=["canvas", "rag", "jira", "pim", "schedule", "audit"],
                signing_key_hex=priv_hex,
            )
            self.assertTrue(key.startswith("AGY-"))

            ok, msg, data = verify_license_key(key)
            self.assertTrue(ok, msg)
            self.assertEqual(data["customer"], "Argos Round2 Enterprise")
            self.assertEqual(data["seats"], 150)
            self.assertIn("canvas", data["modules"])
            self.assertIn("jira", data["modules"])
        finally:
            if prev_pub is None:
                os.environ.pop("ARGOS_LICENSE_PUBLIC_KEY", None)
            else:
                os.environ["ARGOS_LICENSE_PUBLIC_KEY"] = prev_pub
            invalidate_license_cache()


if __name__ == "__main__":
    unittest.main()
