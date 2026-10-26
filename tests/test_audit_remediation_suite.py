import unittest
import os
import sys
import json
import urllib.parse

# Add server directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from db import init_db, execute, get_one, query
from services.auth import (
    create_user, create_session, get_session, is_admin_user,
    get_user_role, can_view_record, can_modify_record, visible_records,
    delete_all_user_sessions
)
from handlers.auth_handlers import handle_account_login
from router import (
    handle_post_admin_user_update, handle_post_record_update,
    handle_get_local_attachment, match_get, match_post
)
from handler import PUBLIC_API_WHITELIST, ArgosHandler


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

    def _send_json(self, status, data, extra_headers=None):
        self.status_code = status
        self.response_body = data

    def send_response(self, code):
        self.status_code = code

    def send_header(self, k, v):
        self.headers_sent[k] = v

    def end_headers(self):
        pass


class TestAuditRemediationSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        execute("DELETE FROM sessions WHERE user_name LIKE 'test_audit_%'")
        execute("DELETE FROM users WHERE username LIKE 'test_audit_%'")
        execute("DELETE FROM records WHERE title LIKE 'TEST_AUDIT_%'")

    def tearDown(self):
        execute("DELETE FROM sessions WHERE user_name LIKE 'test_audit_%'")
        execute("DELETE FROM users WHERE username LIKE 'test_audit_%'")
        execute("DELETE FROM records WHERE title LIKE 'TEST_AUDIT_%'")

    # --------------------------------------------------------------------------
    # 1.1: Session theo user_id, role đọc từ DB
    # --------------------------------------------------------------------------
    def test_duplicate_name_does_not_get_admin(self):
        """동명이인(이름 동일, 부서 다름) 발생 시 일반 사용자가 관리자 권한을 승격받지 못해야 함."""
        # Admin User with display name 'AuditKim' in 'hq'
        admin_u = create_user(
            name="AuditKim",
            username="test_audit_kim_admin",
            org="hq",
            email="kim_admin@test.com",
            salt="s1",
            hash_pwd="h1",
            role="admin",
            is_admin=True,
            status="active"
        )

        # Member User with same display name 'AuditKim' in 'dev'
        member_u = create_user(
            name="AuditKim",
            username="test_audit_kim_member",
            org="dev",
            email="kim_member@test.com",
            salt="s2",
            hash_pwd="h2",
            role="member",
            is_admin=False,
            status="active"
        )

        self.assertNotEqual(admin_u["id"], member_u["id"])

        # is_admin_user checks
        self.assertTrue(is_admin_user(admin_u["id"]))
        self.assertFalse(is_admin_user(member_u["id"]))
        self.assertFalse(is_admin_user({"id": member_u["id"], "name": "AuditKim", "username": "test_audit_kim_member"}))

        # Create session for member
        token = create_session(member_u["name"], member_u["dept_id"], member_u["email"], user_id=member_u["id"])
        sess = get_session(token)

        self.assertIsNotNone(sess)
        self.assertEqual(sess["user_id"], member_u["id"])
        self.assertEqual(sess["role"], "member")
        self.assertFalse(sess["isAdmin"])
        self.assertFalse(is_admin_user(sess))

    def test_viewer_role_cannot_modify_record_gets_403(self):
        """Viewer 역할은 DB에서 실시간 로드되며 레코드 수정 시 403 차단되어야 함."""
        viewer_u = create_user(
            name="AuditViewer",
            username="test_audit_viewer",
            org="dev",
            email="viewer@test.com",
            salt="sv",
            hash_pwd="hv",
            role="viewer",
            status="active"
        )
        token = create_session(viewer_u["name"], viewer_u["dept_id"], viewer_u["email"], user_id=viewer_u["id"])
        sess = get_session(token)
        self.assertEqual(sess["role"], "viewer")

        execute("""
            INSERT OR REPLACE INTO records (id, dept_id, category, title, assignee_name)
            VALUES (112233, 'dev', '개발', 'TEST_AUDIT_REC', 'AuditViewer')
        """)
        rec = {"id": 112233, "dept_id": "dev", "assignee_name": "AuditViewer", "title": "TEST_AUDIT_REC"}
        self.assertFalse(can_modify_record(sess, rec))

        # Test HTTP handler enforcement
        mock = MockRequestHelper(session=sess)
        handle_post_record_update(mock, json.dumps({
            "id": 112233,
            "title": "Modified Title"
        }).encode("utf-8"), "127.0.0.1")
        self.assertEqual(mock.status_code, 403)
        self.assertIn("권한", mock.response_body.get("error", ""))

    def test_locking_user_invalidates_session_next_request_returns_401(self):
        """Admin이 사용자를 비활성화(잠금)하면 즉시 세션이 만료되고 다음 요청에 401 반환해야 함."""
        u = create_user(
            name="AuditLockTarget",
            username="test_audit_lock_user",
            org="dev",
            email="lock@test.com",
            salt="sl",
            hash_pwd="hl",
            role="member",
            status="active"
        )
        token = create_session(u["name"], u["dept_id"], u["email"], user_id=u["id"])
        sess_before = get_session(token)
        self.assertIsNotNone(sess_before)

        # Admin locks the user
        admin_sess = {"name": "AuditAdmin", "org": "hq", "role": "admin", "isAdmin": True}
        mock_admin = MockRequestHelper(session=admin_sess)
        update_body = json.dumps({"id": u["id"], "disabled": True}).encode("utf-8")
        handle_post_admin_user_update(mock_admin, update_body, "127.0.0.1")
        self.assertEqual(mock_admin.status_code, 200)

        # Next request with the previous token
        sess_after = get_session(token)
        self.assertIsNone(sess_after, "Session must return None for locked/disabled user")

        mock_user = MockRequestHelper(token=token)
        mock_user._get_session_or_401()
        self.assertEqual(mock_user.status_code, 401)

    # --------------------------------------------------------------------------
    # 1.2: Thêm xác thực cho 4 endpoint đang hở & Router Default Protection
    # --------------------------------------------------------------------------
    def test_unauthenticated_api_endpoints_return_401_except_whitelist(self):
        """화이트리스트에 없는 모든 /api 엔드포인트는 비로그인 시 401을 반환해야 함."""
        from handlers.product_handlers import handle_product_attachment_upload, handle_product_attachment_delete
        from handlers.sync_handler import handle_sync
        from router import handle_post_vector_sync

        unauth_handler = MockRequestHelper(session=None, token=None)

        # 1. Attachment upload without login -> 401
        handle_product_attachment_upload(unauth_handler, b"fake", "127.0.0.1")
        self.assertEqual(unauth_handler.status_code, 401)

        # 2. Attachment delete without login -> 401
        unauth_handler = MockRequestHelper(session=None, token=None)
        handle_product_attachment_delete(unauth_handler, b"{}", "127.0.0.1")
        self.assertEqual(unauth_handler.status_code, 401)

        # 3. Jira Sync without login -> 401
        unauth_handler = MockRequestHelper(session=None, token=None)
        handle_sync(unauth_handler, b"{}", "127.0.0.1")
        self.assertEqual(unauth_handler.status_code, 401)

        # 4. Vector Sync without login -> 401
        unauth_handler = MockRequestHelper(session=None, token=None)
        handle_post_vector_sync(unauth_handler, b"{}", "127.0.0.1")
        self.assertEqual(unauth_handler.status_code, 401)

        # 5. Whitelist integrity: Verify that auth endpoints, health, setup are in PUBLIC_API_WHITELIST
        self.assertIn("/api/health", PUBLIC_API_WHITELIST)
        self.assertIn("/api/setup/status", PUBLIC_API_WHITELIST)
        self.assertIn("/api/account/login", PUBLIC_API_WHITELIST)
        self.assertIn("/api/auth/login", PUBLIC_API_WHITELIST)
        self.assertIn("/api/account/register", PUBLIC_API_WHITELIST)
        self.assertIn("/api/account/me", PUBLIC_API_WHITELIST)

        # Ensure sensitive endpoints are NEVER in whitelist
        self.assertNotIn("/api/records", PUBLIC_API_WHITELIST)
        self.assertNotIn("/api/sync", PUBLIC_API_WHITELIST)
        self.assertNotIn("/api/vectors/sync", PUBLIC_API_WHITELIST)
        self.assertNotIn("/api/products/attachments/upload", PUBLIC_API_WHITELIST)
        self.assertNotIn("/api/products/attachments/delete", PUBLIC_API_WHITELIST)
        self.assertNotIn("/api/admin/users", PUBLIC_API_WHITELIST)

    # --------------------------------------------------------------------------
    # 1.3: Chặn rò rỉ bản ghi riêng tư
    # --------------------------------------------------------------------------
    def test_user_dept_a_cannot_see_private_record_of_dept_b(self):
        """A 부서 사용자가 B 부서의 비공개(is_private=1) 레코드 및 첨부파일을 열람할 수 없어야 함."""
        # Create private record in Dept 'hr'
        rec_id = 99887766
        execute("""
            INSERT OR REPLACE INTO records (id, dept_id, category, title, assignee_name, is_private, summary)
            VALUES (?, 'hr', '인사', 'TEST_AUDIT_CONFIDENTIAL_SALARY', 'HROfficer', 1, 'Secret payroll 2026')
        """, (rec_id,))

        rec = get_one("SELECT * FROM records WHERE id = ?", (rec_id,))
        self.assertIsNotNone(rec)

        user_dev = {
            "id": 8801,
            "name": "DevBob",
            "username": "test_audit_devbob",
            "org": "dev",
            "role": "member"
        }

        # 1. can_view_record must be False
        self.assertFalse(can_view_record(user_dev, rec))

        # 2. visible_records must exclude it
        vis = visible_records(user_dev, [rec])
        self.assertEqual(len(vis), 0)

        # 3. Attachment download handler must reject with 403
        mock = MockRequestHelper(session=user_dev, path=f"/api/attachments/{rec_id}/secret.pdf")
        parsed = urllib.parse.urlparse(f"/api/attachments/{rec_id}/secret.pdf")
        handle_get_local_attachment(mock, parsed, "127.0.0.1")
        self.assertEqual(mock.status_code, 403)
        self.assertIn("권한", mock.response_body.get("error", ""))

        # 4. Chat Tools (AI RAG) must exclude private record
        from services.chat_tools import _tool_search_internal_records, _tool_get_issue_details
        ai_res = _tool_search_internal_records({"query": "Secret payroll"}, current_user=user_dev, cfg={})
        internal_recs = ai_res.get("internal_records", [])
        self.assertEqual(len([r for r in internal_recs if r["id"] == rec_id]), 0)

        detail_res = _tool_get_issue_details({"issue_key": str(rec_id)}, current_user=user_dev, cfg={})
        self.assertFalse(detail_res.get("found", True))


    def test_remediation_2_1_stored_xss_prevention(self):
        """2.1: 위험 확장자(.html, .svg, .js 등)는 .bin으로 변환되고 다운로드 시 nosniff 및 CSP sandbox 적용"""
        from utils.file_ops import sanitize_filename
        self.assertEqual(sanitize_filename("exploit.html"), "exploit.bin")
        self.assertEqual(sanitize_filename("vector.SVG"), "vector.bin")
        self.assertEqual(sanitize_filename("payload.js"), "payload.bin")
        self.assertEqual(sanitize_filename("normal.png"), "normal.png")
        self.assertEqual(sanitize_filename("document.pdf"), "document.pdf")

    def test_remediation_2_2_safe_tar_extraction(self):
        """2.2: Tar Traversal 공격(상대 경로, 절대 경로, 심볼릭 링크) 차단"""
        import tarfile
        import io
        import shutil
        from services.backup_manager import _safe_extract_tar

        temp_dir = os.path.join(os.path.dirname(__file__), "test_extract_safe")
        os.makedirs(temp_dir, exist_ok=True)

        # Create malicious in-memory tar archive with ../ traversal
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            ti = tarfile.TarInfo(name="../escape.txt")
            ti.size = 5
            tar.addfile(ti, io.BytesIO(b"hello"))
        buf.seek(0)

        with tarfile.open(fileobj=buf, mode="r:gz") as tar:
            with self.assertRaises(RuntimeError) as ctx:
                _safe_extract_tar(tar, temp_dir)
            self.assertIn("비정상적인 파일 경로", str(ctx.exception))

        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_remediation_2_3_ssrf_validation(self):
        """2.3: Link-local (169.254.169.254), 루프백 및 비HTTPS 외부 URL 차단"""
        from utils.ssrf import validate_external_url

        # 169.254.169.254 must always fail
        with self.assertRaises(ValueError):
            validate_external_url("http://169.254.169.254/latest/meta-data")
        with self.assertRaises(ValueError):
            validate_external_url("http://169.254.169.254/latest/meta-data", allow_private=True)

        # 127.0.0.1 loopback blocked by default
        with self.assertRaises(ValueError):
            validate_external_url("http://127.0.0.1:11434")

        # 127.0.0.1 allowed only when explicitly allow_private=True
        self.assertTrue(validate_external_url("http://127.0.0.1:11434", allow_private=True, require_https=False))

        # LAN IPs (192.168.x.x, 10.x.x.x) allowed for offline AI (allow_private=True)
        self.assertTrue(validate_external_url("http://192.168.1.100:8000/v1", allow_private=True, require_https=False))
        self.assertTrue(validate_external_url("http://10.0.0.5:1234/v1", allow_private=True, require_https=False))

        # LAN IPs blocked by default for public webhooks / external services
        with self.assertRaises(ValueError):
            validate_external_url("http://192.168.1.100:8000/v1")
        with self.assertRaises(ValueError):
            validate_external_url("https://192.168.1.100:8000/v1")

    def test_offline_ai_and_vector_configuration(self):
        """오프라인 AI (Custom LAN vLLM / LM Studio) 및 로컬 임베딩 설정 검증"""
        from services.vector_store import is_voyage_configured, get_embedding_provider_info

        # Ollama / Custom local embedding is configured even without API key
        cfg_offline_ollama = {
            "voyage": {
                "enabled": True,
                "provider": "ollama",
                "base_url": "http://localhost:11434/v1/embeddings",
                "model": "nomic-embed-text"
            }
        }
        self.assertTrue(is_voyage_configured(cfg_offline_ollama))

        cfg_offline_custom = {
            "voyage": {
                "enabled": True,
                "provider": "custom",
                "base_url": "http://192.168.1.50:8000/v1/embeddings",
                "model": "bge-m3"
            }
        }
        self.assertTrue(is_voyage_configured(cfg_offline_custom))

        # Cloud provider without key must NOT be configured
        # (clear env fallbacks so a developer .env cannot leak a real key into this assertion)
        cfg_cloud_voyage = {
            "voyage": {
                "enabled": True,
                "provider": "voyage",
                "api_key": ""
            }
        }
        import os as _os
        from unittest.mock import patch as _patch
        with _patch.dict(_os.environ, {"VOYAGE_API_KEY": "", "VOYAGE_API_KEYS": ""}):
            self.assertFalse(is_voyage_configured(cfg_cloud_voyage))

    def test_remediation_2_4_trusted_proxy_and_log_masking(self):
        """2.4: 신뢰할 수 없는 프록시의 X-Forwarded-For 위조 방어 및 로그 쿼리스트링 마스킹"""
        from utils.logging import mask_query_string
        log_sample = "GET /api/sse?token=my_secret_token_123&key=secret_api_key HTTP/1.1"
        masked = mask_query_string(log_sample)
        self.assertNotIn("my_secret_token_123", masked)
        self.assertNotIn("secret_api_key", masked)
        self.assertIn("token=***", masked)
        self.assertIn("key=***", masked)

    def test_remediation_2_4b_pbkdf2_upgrade_and_lockout(self):
        """2.4b: 600,000 PBKDF2 반복 및 로그인 성공 시 해시 자동 업그레이드, DB 영속 잠금"""
        from services.auth import hash_password, verify_password, check_login_rate_limit, record_login_failure, clear_login_failures, PBKDF2_ROUNDS
        self.assertEqual(PBKDF2_ROUNDS, 600000)

        # Generate legacy 100k hash
        test_pwd = "UpgradePassword123!"
        salt, legacy_hash = hash_password(test_pwd, iterations=100000)

        # Insert user with legacy hash
        user_name = "test_upgrade_user"
        execute("DELETE FROM users WHERE username = ?", (user_name,))
        execute("""
            INSERT INTO users (username, name, dept_id, email, salt, password_hash, is_admin, role, disabled, status, iterations, hash_algo)
            VALUES (?, ?, 'dev', 'upgrade@test.com', ?, ?, 0, 'member', 0, 'active', 100000, 'pbkdf2_sha256')
        """, (user_name, user_name, salt, legacy_hash))
        u = get_one("SELECT id, iterations FROM users WHERE username = ?", (user_name,))
        self.assertEqual(u["iterations"], 100000)

        # Verify password triggers auto-upgrade to 600k
        res = verify_password(test_pwd, salt, legacy_hash, user_id=u["id"])
        self.assertTrue(res)

        u_upgraded = get_one("SELECT iterations, password_hash FROM users WHERE username = ?", (user_name,))
        self.assertEqual(u_upgraded["iterations"], 600000)
        self.assertNotEqual(u_upgraded["password_hash"], legacy_hash)

        # Test DB persistent lockout (5 failures)
        ip = "192.0.2.100"
        clear_login_failures(ip, user_name)
        for _ in range(5):
            record_login_failure(ip, user_name)

        allowed, lock_msg = check_login_rate_limit(ip, user_name)
        self.assertFalse(allowed)
        self.assertIn("잠금", lock_msg)

        clear_login_failures(ip, user_name)
        allowed, _ = check_login_rate_limit(ip, user_name)
        self.assertTrue(allowed)


if __name__ == "__main__":
    unittest.main()
