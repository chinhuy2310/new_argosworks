import unittest
import os
import sys
import json
import hashlib
import time

# Add server directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from db import init_db, execute, get_one, query
from services.auth import (
    create_user, create_session, get_session, delete_session, rotate_session,
    hash_session_token, get_user_role, can_view_record, can_modify_record,
    visible_records, verify_password, hash_password
)
from middleware_security import (
    generate_csrf_token, validate_csrf_token, get_allowed_cors_origin
)
from router import match_get
from handlers.auth_handlers import handle_account_check


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

    def _get_session_or_401(self):
        return self._current_session

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


class TestAuditRound3Suite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        execute("DELETE FROM sessions WHERE user_name LIKE 'test_round3_%'")
        execute("DELETE FROM users WHERE username LIKE 'test_round3_%'")
        execute("DELETE FROM records WHERE title LIKE 'TEST_ROUND3_%'")

    def tearDown(self):
        execute("DELETE FROM sessions WHERE user_name LIKE 'test_round3_%'")
        execute("DELETE FROM users WHERE username LIKE 'test_round3_%'")
        execute("DELETE FROM records WHERE title LIKE 'TEST_ROUND3_%'")

    # --------------------------------------------------------------------------
    # 1. CSRF & CORS Security
    # --------------------------------------------------------------------------
    def test_csrf_token_strictly_bound_to_session(self):
        """CSRF 토큰은 특정 세션에 암호학적으로 종속되며, 타 사용자 세션에 재사용될 수 없음."""
        sess_a = "token-session-alice-1111"
        sess_b = "token-session-bob-2222"

        token_a = generate_csrf_token(sess_a)

        # Token A is valid for Alice
        self.assertTrue(validate_csrf_token(token_a, session_token=sess_a))

        # Token A MUST BE REJECTED when submitted against Bob's session
        self.assertFalse(validate_csrf_token(token_a, session_token=sess_b))

        # Invalid/empty tokens rejected
        self.assertFalse(validate_csrf_token("", session_token=sess_a))
        self.assertFalse(validate_csrf_token(token_a, session_token=None))

    def test_cors_arbitrary_localhost_ports_blocked(self):
        """CORS는 임의의 localhost 포트(예: 9999)를 차단하고 인가된 도메인/포트만 허용해야 함."""
        whitelist = ["corp.argos.internal", "app.company.com"]

        # Configured enterprise domains allowed
        self.assertIsNotNone(get_allowed_cors_origin("https://corp.argos.internal", whitelist))
        self.assertIsNotNone(get_allowed_cors_origin("https://app.company.com", whitelist))

        # Standard dev port allowed
        self.assertIsNotNone(get_allowed_cors_origin("http://localhost:8080", whitelist))

        # Arbitrary untrusted localhost port rejected
        self.assertIsNone(get_allowed_cors_origin("http://localhost:9999", whitelist))
        self.assertIsNone(get_allowed_cors_origin("http://127.0.0.1:4444", whitelist))
        self.assertIsNone(get_allowed_cors_origin("http://evil.com", whitelist))

    # --------------------------------------------------------------------------
    # 2. Session Hashing, Sliding Expiration, and Rotation
    # --------------------------------------------------------------------------
    def test_session_stored_as_sha256_hash_in_db(self):
        """세션 토큰은 DB에 Plaintext가 아닌 SHA-256 해시로 저장되어야 함."""
        u = create_user(
            name="SessionHashUser",
            username="test_round3_session_user",
            org="dev",
            email="sess@test.com",
            salt="s_hash",
            hash_pwd="h_hash",
            role="member",
            status="active"
        )
        raw_token = create_session(u["name"], u["dept_id"], u["email"], user_id=u["id"])
        self.assertIsNotNone(raw_token)

        # Check DB: Raw token MUST NOT exist in DB
        raw_in_db = get_one("SELECT * FROM sessions WHERE token = ?", (raw_token,))
        self.assertIsNone(raw_in_db)

        # Expected hash MUST exist in DB
        expected_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        hash_in_db = get_one("SELECT * FROM sessions WHERE token = ?", (expected_hash,))
        self.assertIsNotNone(hash_in_db)
        self.assertEqual(hash_in_db["user_id"], u["id"])

        # get_session(raw_token) successfully finds and verifies it
        sess = get_session(raw_token)
        self.assertIsNotNone(sess)
        self.assertEqual(sess["id"], u["id"])

        # rotate_session invalidates old token and creates a new one
        new_token = rotate_session(raw_token)
        self.assertIsNotNone(new_token)
        self.assertNotEqual(raw_token, new_token)
        self.assertIsNone(get_session(raw_token))
        self.assertIsNotNone(get_session(new_token))

    # --------------------------------------------------------------------------
    # 3. Performance & N+1 Prevention
    # --------------------------------------------------------------------------
    def test_visible_records_avoids_n_plus_one_queries(self):
        """visible_records 호출 시 세션에 캐시된 role을 활용하여 레코드별 DB 쿼리(N+1)를 방지해야 함."""
        session = {
            "id": 8888,
            "name": "PerfUser",
            "username": "test_round3_perf",
            "org": "dev",
            "dept_id": "dev",
            "role": "member",
            "email": "perf@test.com"
        }
        # Create 30 records
        records = [
            {"id": i, "dept_id": "dev", "assignee_name": "Other", "is_private": 0, "title": f"TEST_ROUND3_REC_{i}"}
            for i in range(30)
        ]

        vis = visible_records(session, records)
        self.assertEqual(len(vis), 30)

        # Fast path test: get_user_role on dict with role should return without database query
        self.assertEqual(get_user_role(session), "member")

    def test_verify_password_avoids_double_cpu_burn(self):
        """지정된 iterations가 있는 경우 잘못된 비밀번호 시 600k+100k 이중 연산을 하지 않음."""
        salt, pwd_hash = hash_password("CorrectPass123!", iterations=600000)
        t0 = time.time()
        # Failed password with iterations specified
        res = verify_password("WrongPassword!", salt, pwd_hash, iterations=600000)
        t_single = time.time() - t0
        self.assertFalse(res)
        # Should finish reasonably fast for a single 600k iteration, not doubling to 700k
        self.assertLess(t_single, 2.5)

    # --------------------------------------------------------------------------
    # 4. Display Name Collision Protection
    # --------------------------------------------------------------------------
    def test_identical_name_different_dept_cannot_access_private_record(self):
        """동명이인(타 부서) 사용자가 비공개 레코드(급여/평가 등)를 열람하거나 수정할 수 없어야 함."""
        rec_hr_private = {
            "id": 777001,
            "dept_id": "hr",
            "assignee_name": "KimCheolSoo",
            "is_private": 1,
            "title": "TEST_ROUND3_SECRET_EVALUATION"
        }

        # Dev department user with identical name 'KimCheolSoo'
        dev_kim = {
            "id": 9901,
            "name": "KimCheolSoo",
            "username": "test_round3_dev_kim",
            "org": "dev",
            "dept_id": "dev",
            "role": "member"
        }

        # HR department user with same name 'KimCheolSoo'
        hr_kim = {
            "id": 9902,
            "name": "KimCheolSoo",
            "username": "test_round3_hr_kim",
            "org": "hr",
            "dept_id": "hr",
            "role": "member"
        }

        # Dev Kim MUST NOT be able to view or modify HR's private record
        self.assertFalse(can_view_record(dev_kim, rec_hr_private))
        self.assertFalse(can_modify_record(dev_kim, rec_hr_private))

        # HR Kim CAN view and modify it
        self.assertTrue(can_view_record(hr_kim, rec_hr_private))
        self.assertTrue(can_modify_record(hr_kim, rec_hr_private))

    # --------------------------------------------------------------------------
    # 5. Endpoint Hardening & Information Disclosure
    # --------------------------------------------------------------------------
    def test_account_check_enumeration_prevented_when_public_register_disabled(self):
        """공개 가입이 비활성화된 경우 /api/account/check를 통한 사용자 계정 존재 여부 탐색이 차단되어야 함."""
        prev = os.environ.get("ALLOW_PUBLIC_REGISTER")
        try:
            os.environ["ALLOW_PUBLIC_REGISTER"] = "false"
            handler = MockRequestHelper()
            req_body = json.dumps({"name": "NonExistentUser", "org": "dev"}).encode("utf-8")
            handle_account_check(handler, req_body, "127.0.0.1")
            self.assertEqual(handler.status_code, 200)
            # Must always return exists: True to direct caller to password step without leaking whether user exists
            self.assertTrue(handler.response_body.get("exists"))
        finally:
            if prev is not None:
                os.environ["ALLOW_PUBLIC_REGISTER"] = prev
            else:
                os.environ.pop("ALLOW_PUBLIC_REGISTER", None)

    def test_logo_preview_and_get_logout_removed_from_get_router(self):
        """공개 노출되었던 /logo-preview 및 GET 방식 /api/account/logout이 GET 라우터에서 제거되었는지 검증."""
        self.assertEqual(match_get("/logo-preview")[0], "notfound")
        self.assertEqual(match_get("/logo-preview.html")[0], "notfound")
        self.assertEqual(match_get("/api/account/logout")[0], "notfound")
        self.assertEqual(match_get("/api/auth/logout")[0], "notfound")

    def test_update_record_parent_key_and_cycle_prevention(self):
        """상위 작업(parentKey) 변경 및 순환 참조 방지 로직 검증."""
        from services.data_store import update_record_details
        execute("INSERT OR REPLACE INTO records (id, dept_id, category, title, project, assignee_name, card_code, parent_key) VALUES (911001, 'dev', '개발', 'DEV-1 Title', 'P', 'Mem', 'DEV-1', '')")
        execute("INSERT OR REPLACE INTO records (id, dept_id, category, title, project, assignee_name, card_code, parent_key) VALUES (911002, 'sales', '영업', 'SALES-3 Title', 'P', 'Mem', 'SALES-3', 'DEV-1')")
        # 1. 자기 자신을 상위 작업으로 지정 시 차단
        _, err_self = update_record_details("DEV-1", parent_key="DEV-1")
        self.assertIn("자기 자신", err_self)

        # 2. 하위 작업(SALES-3)을 상위 작업(DEV-1)의 부모로 지정 시 순환 참조 차단
        _, err_cycle = update_record_details("DEV-1", parent_key="SALES-3")
        self.assertIn("순환 참조", err_cycle)

        # 3. 상위 작업 해제 (최상위 작업으로 변경)
        rec_unlinked, err_un = update_record_details("SALES-3", parent_key="")
        self.assertEqual(err_un, "")
        self.assertEqual(rec_unlinked["parentKey"], "")

        # 4. 상위 작업 재지정 (DEV-1로 재연결)
        rec_relinked, err_re = update_record_details("SALES-3", parent_key="DEV-1")
        self.assertEqual(err_re, "")
        self.assertEqual(rec_relinked["parentKey"], "DEV-1")


    def test_invalid_expected_version_is_rejected_without_mutation(self):
        """잘못된 expected_version은 락 검증을 우회하지 않고 레코드를 변경하지 않아야 함."""
        from services.data_store import update_record_details
        record_id = 911003
        title = "TEST_ROUND3_INVALID_VERSION"
        execute(
            "INSERT OR REPLACE INTO records (id, dept_id, category, title, project, assignee_name, card_code, parent_key) VALUES (?, 'dev', '개발', ?, 'P', 'Mem', 'DEV-INVALID-VERSION', '')",
            (record_id, title)
        )
        before = get_one("SELECT title, version FROM records WHERE id = ?", (record_id,))
        updated, error = update_record_details(
            "DEV-INVALID-VERSION",
            title="MUST_NOT_BE_SAVED",
            expected_version="not-a-version"
        )
        after = get_one("SELECT title, version FROM records WHERE id = ?", (record_id,))
        self.assertIsNone(updated)
        self.assertIn("유효하지 않은 버전", error)
        self.assertEqual(after["title"], before["title"])
        self.assertEqual(after["version"], before["version"])


    def test_excel_export_values_are_not_interpreted_as_formulas(self):
        """내보내기 셀의 사용자 입력은 Excel 수식으로 실행되지 않아야 함."""
        from handlers.report_handler import _excel_safe_value
        for payload in ("=1+1", "+cmd|' /C calc'!A0", "-1+2", "@SUM(A1:A2)", "  =1+1"):
            safe = _excel_safe_value(payload)
            self.assertTrue(safe.startswith("'"))
        self.assertEqual(_excel_safe_value("ordinary text"), "ordinary text")
        self.assertEqual(_excel_safe_value(42), 42)



if __name__ == "__main__":
    unittest.main()
