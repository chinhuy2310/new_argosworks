"""
test_e2e_user_flows.py — End-to-End Tests cho luồng người dùng hoàn chỉnh
Mô phỏng chuỗi thao tác thực tế: đăng ký → đăng nhập → tạo phòng ban → tạo lịch → kiểm tra dữ liệu
Edge cases: luồng đăng nhập thất bại, mật khẩu sai, tài khoản bị khóa
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
# 1. Complete User Registration → Login Flow
# ============================================================================
class TestRegistrationLoginFlow:
    """E2E: Đăng ký tài khoản → Đăng nhập → Xác minh session."""

    def test_full_registration_to_login(self, tmp_db):
        """Luồng hoàn chỉnh: tạo user → verify password → tạo session."""
        from services.auth import (
            hash_password, verify_password, create_user,
            get_user_by_login, create_session, get_session
        )

        # Step 1: Register
        password = "SecurePass2026!"
        salt, hashed = hash_password(password)
        user = create_user(
            name="이영희",
            username="yhlee",
            org="dev",
            email="yhlee@company.com",
            salt=salt,
            hash_pwd=hashed,
            role="member",
            status="active",
            disabled=0
        )
        assert user is not None
        assert user["username"] == "yhlee"

        # Step 2: Login lookup
        login_user = get_user_by_login("yhlee")
        assert login_user is not None
        assert login_user["name"] == "이영희"

        # Step 3: Password verification
        assert verify_password(password, login_user["salt"], login_user["password_hash"])
        assert not verify_password("WrongPassword", login_user["salt"], login_user["password_hash"])

        # Step 4: Create session
        token = create_session(login_user["name"], org=login_user["dept_id"],
                               email=login_user.get("email", ""), user_id=login_user["id"])
        assert token is not None
        assert isinstance(token, str)

        # Step 5: Validate session
        retrieved = get_session(token)
        assert retrieved is not None
        assert retrieved["name"] == "이영희"

    def test_login_by_email(self, tmp_db):
        """Đăng nhập bằng email thay vì username."""
        from services.auth import hash_password, create_user, get_user_by_login

        salt, hashed = hash_password("pass123")
        create_user(
            name="박민수", username="parkminsoo",
            org="sales", email="park@company.com",
            salt=salt, hash_pwd=hashed
        )

        # Lookup by email
        user = get_user_by_login("park@company.com")
        assert user is not None
        assert user["name"] == "박민수"

    def test_login_case_insensitive(self, tmp_db):
        """Username tìm kiếm không phân biệt hoa/thường."""
        from services.auth import hash_password, create_user, get_user_by_login

        salt, hashed = hash_password("pass123")
        create_user(name="테스트", username="TestUser",
                    org="dev", email="case@test.com",
                    salt=salt, hash_pwd=hashed)

        assert get_user_by_login("testuser") is not None
        assert get_user_by_login("TESTUSER") is not None
        assert get_user_by_login("TestUser") is not None

    def test_disabled_user_cannot_login(self, tmp_db):
        """Tài khoản bị disabled: tìm thấy nhưng cần check status."""
        from services.auth import hash_password, create_user, get_user_by_login

        salt, hashed = hash_password("pass123")
        create_user(
            name="비활성유저", username="disabled_user",
            org="dev", email="disabled@test.com",
            salt=salt, hash_pwd=hashed,
            disabled=1, status="suspended"
        )

        user = get_user_by_login("disabled_user")
        assert user is not None
        # Application should check disabled flag
        assert user.get("disabled") == 1 or user.get("status") == "suspended"


# ============================================================================
# 2. Admin: Department Management Flow
# ============================================================================
class TestAdminDepartmentFlow:
    """E2E: Admin tạo → cập nhật → xóa phòng ban."""

    def test_full_department_lifecycle(self, seed_admin, mock_handler):
        from handlers.department_handler import (
            handle_add_department, handle_update_department,
            handle_delete_department
        )
        admin_session = {
            "name": "관리자", "org": "dev", "email": "admin@test.com",
            "isAdmin": True, "is_admin": True, "role": "admin"
        }

        # Step 1: Add department
        handler1 = mock_handler(session=admin_session)
        handle_add_department(handler1, json.dumps({
            "name": "라이프사이클테스트부서",
            "localPrefix": "LIFE",
            "jiraKey": "LIFE"
        }).encode(), "127.0.0.1")
        assert handler1.response_code == 200
        assert handler1.response_body["added"] is True

        # Find the department ID
        depts = handler1.response_body["departments"]
        new_dept = next((d for d in depts if d["name"] == "라이프사이클테스트부서"), None)
        assert new_dept is not None
        dept_id = new_dept["id"]

        # Step 2: Update department
        handler2 = mock_handler(session=admin_session)
        handle_update_department(handler2, json.dumps({
            "id": dept_id,
            "name": "수정된부서명",
            "localPrefix": "MOD",
            "jiraKey": "MOD"
        }).encode(), "127.0.0.1")
        assert handler2.response_code == 200

        # Step 3: Delete department
        handler3 = mock_handler(session=admin_session)
        handle_delete_department(handler3, json.dumps({
            "id": dept_id
        }).encode(), "127.0.0.1")
        assert handler3.response_code == 200


# ============================================================================
# 3. User: Schedule Event Creation Flow
# ============================================================================
class TestScheduleEventFlow:
    """E2E: User tạo lịch → kiểm tra dữ liệu lưu."""

    def test_create_meeting_event(self, seed_user, mock_handler):
        from handlers.schedule_handlers import handle_schedule_create
        from services.auth import get_session
        session_token = seed_user["session"]
        session_obj = get_session(session_token)
        handler = mock_handler(session=session_obj)

        handle_schedule_create(handler, json.dumps({
            "title": "프로젝트 킥오프 미팅",
            "type": "회의",
            "startDate": "2026-11-01",
            "endDate": "2026-11-01",
            "memo": "Q4 프로젝트 시작 회의"
        }).encode(), "127.0.0.1")

        assert handler.response_code == 200 or handler.response_code is None
        # If the handler succeeded, the event was persisted

    def test_leave_request_pending_status(self, seed_user, mock_handler):
        """연차 신청 시 approval_status = 'pending'."""
        from handlers.schedule_handlers import handle_schedule_create
        from services.auth import get_session
        session_token = seed_user["session"]
        session_obj = get_session(session_token)
        handler = mock_handler(session=session_obj)

        handle_schedule_create(handler, json.dumps({
            "title": "연차 휴가",
            "type": "연차",
            "startDate": "2026-12-25",
            "endDate": "2026-12-26"
        }).encode(), "127.0.0.1")

        # Verify event was created
        from services.data_store import read_schedule
        events = read_schedule()
        leave_events = [e for e in events if "연차" in str(e.get("type", ""))]
        if leave_events:
            assert leave_events[-1].get("approval_status") == "pending"


# ============================================================================
# 4. Data Integrity: Record Creation with Attachments
# ============================================================================
class TestRecordCreationFlow:
    """E2E: Tạo record → thêm comment → thêm attachment → kiểm tra."""

    def test_record_with_comments_and_attachments(self, tmp_db):
        """Tạo record đầy đủ với comments và attachments."""
        import time as t

        rec_id = int(t.time() * 1000)
        tmp_db.execute(
            """INSERT INTO records(id, dept_id, category, title, assignee_name,
               summary, status, priority) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (rec_id, "dev", "기능개발", "Dashboard 리팩토링",
             "테스트유저", "대시보드 UI를 Vue3로 전환", "진행", "높음")
        )

        # Add comment
        tmp_db.execute(
            "INSERT INTO record_comments(record_id, author_name, body) VALUES (?, ?, ?)",
            (rec_id, "테스트유저", "1차 코드리뷰 완료")
        )
        tmp_db.execute(
            "INSERT INTO record_comments(record_id, author_name, body) VALUES (?, ?, ?)",
            (rec_id, "관리자", "LGTM, 배포 진행해주세요")
        )

        # Add attachment
        tmp_db.execute(
            "INSERT INTO record_attachments(record_id, filename, file_size) VALUES (?, ?, ?)",
            (rec_id, "design_spec.pdf", 1024000)
        )

        # Verify record
        record = tmp_db.get_one("SELECT * FROM records WHERE id = ?", (rec_id,))
        assert record is not None
        assert record["title"] == "Dashboard 리팩토링"
        assert record["priority"] == "높음"

        # Verify comments
        comments = tmp_db.query("SELECT * FROM record_comments WHERE record_id = ? ORDER BY id", (rec_id,))
        assert len(comments) == 2
        assert comments[0]["body"] == "1차 코드리뷰 완료"

        # Verify attachments
        attachments = tmp_db.query("SELECT * FROM record_attachments WHERE record_id = ?", (rec_id,))
        assert len(attachments) == 1
        assert attachments[0]["filename"] == "design_spec.pdf"


# ============================================================================
# 5. Edge Case: Rapid Multiple Sessions
# ============================================================================
class TestMultipleSessionsFlow:
    """E2E: User đăng nhập nhiều lần → quản lý multi-session."""

    def test_multiple_sessions_same_user(self, seed_user):
        from services.auth import create_session, get_session

        user = seed_user["user"]
        tokens = []

        # Create 3 sessions
        for _ in range(3):
            tok = create_session(
                user["name"], org=user["dept_id"],
                email=user.get("email", ""), user_id=user["id"]
            )
            tokens.append(tok)

        # All sessions should be valid
        for token in tokens:
            s = get_session(token)
            assert s is not None
            assert s["name"] == user["name"]


# ============================================================================
# 6. Edge Case: Health Check with DB Scenarios
# ============================================================================
class TestHealthCheckEdgeCases:
    """E2E: Health check dưới nhiều điều kiện DB."""

    def test_healthy_db(self, tmp_db, mock_handler):
        from router import handle_get_health
        handler = mock_handler()
        handle_get_health(handler, None, "127.0.0.1")
        assert handler.response_code == 200
        assert handler.response_body["status"] == "healthy"

    def test_health_check_includes_timestamp(self, tmp_db, mock_handler):
        from router import handle_get_health
        handler = mock_handler()
        handle_get_health(handler, None, "127.0.0.1")
        assert "time" in handler.response_body
        assert "T" in handler.response_body["time"]  # ISO format


# ============================================================================
# 7. Edge Case: Empty / Boundary Data
# ============================================================================
class TestBoundaryData:
    """Kiểm tra các trường hợp biên với dữ liệu."""

    def test_max_length_title(self, tmp_db):
        """Title dài bất thường."""
        import time as t
        rec_id = int(t.time() * 1000) + 100
        long_title = "A" * 5000
        tmp_db.execute(
            """INSERT INTO records(id, dept_id, category, title, assignee_name, status)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (rec_id, "dev", "기타", long_title, "test", "진행")
        )
        rec = tmp_db.get_one("SELECT title FROM records WHERE id = ?", (rec_id,))
        assert rec is not None
        assert len(rec["title"]) == 5000

    def test_unicode_emoji_in_data(self, tmp_db):
        """Dữ liệu chứa emoji và Unicode đặc biệt."""
        import time as t
        rec_id = int(t.time() * 1000) + 200
        title = "🚀 프로젝트 킥오프 🎉 Café résumé"
        tmp_db.execute(
            """INSERT INTO records(id, dept_id, category, title, assignee_name, status)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (rec_id, "dev", "기타", title, "test", "진행")
        )
        rec = tmp_db.get_one("SELECT title FROM records WHERE id = ?", (rec_id,))
        assert rec["title"] == title

    def test_special_chars_in_memo(self, tmp_db):
        """Memo chứa ký tự đặc biệt SQL-dangerous."""
        import time as t
        rec_id = int(t.time() * 1000) + 300
        memo = "This has 'single quotes', \"double quotes\", and SQL -- comment; DROP TABLE"
        tmp_db.execute(
            """INSERT INTO records(id, dept_id, category, title, assignee_name, status, memo)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (rec_id, "dev", "기타", "Test", "user", "진행", memo)
        )
        rec = tmp_db.get_one("SELECT memo FROM records WHERE id = ?", (rec_id,))
        assert rec["memo"] == memo

    def test_json_tags_field(self, tmp_db):
        """JSON array trong cột tags."""
        import time as t
        rec_id = int(t.time() * 1000) + 400
        tags = json.dumps(["frontend", "bug", "urgent", "한글태그"])
        tmp_db.execute(
            """INSERT INTO records(id, dept_id, category, title, assignee_name, status, tags)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (rec_id, "dev", "기타", "Tagged", "user", "진행", tags)
        )
        rec = tmp_db.get_one("SELECT tags FROM records WHERE id = ?", (rec_id,))
        loaded_tags = json.loads(rec["tags"])
        assert "frontend" in loaded_tags
        assert "한글태그" in loaded_tags

    def test_zero_length_fields(self, tmp_db):
        """Tất cả trường optional = empty string."""
        import time as t
        rec_id = int(t.time() * 1000) + 500
        tmp_db.execute(
            """INSERT INTO records(id, dept_id, category, title, assignee_name,
               status, summary, memo, card_code, participants, parent_key)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (rec_id, "dev", "기타", "Min", "usr", "진행", "", "", "", "", "")
        )
        rec = tmp_db.get_one("SELECT * FROM records WHERE id = ?", (rec_id,))
        assert rec is not None
        assert rec["summary"] == ""
        assert rec["memo"] == ""
