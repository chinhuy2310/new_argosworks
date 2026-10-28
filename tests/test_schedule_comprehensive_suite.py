# -*- coding: utf-8 -*-
"""
test_schedule_comprehensive_suite.py
=============================================================================
Toàn bộ bộ test tự động (Comprehensive Test Suite) cho tất cả hành động Lịch:
1. Tạo lịch không cần duyệt (회의, 업무, 기타 -> approved)
2. Tạo lịch cần duyệt (연차, 반차, 병가, 출장 -> pending & gửi thông báo Manager/Admin)
3. Thêm nhiều người tham gia (participants)
4. Validation ngày tháng & tiêu đề
5. Chặn Viewer & License hết hạn khi ghi lịch
6. Manager phòng ban duyệt lịch (approve) & gửi thông báo cho nhân viên
7. Chặn Manager phòng ban khác duyệt trái phép (403 Forbidden)
8. Chặn Member thường duyệt (403 Forbidden)
9. Admin duyệt lịch của bất kỳ phòng ban nào
10. Manager từ chối lịch kèm lý do (reject with reason) & gửi thông báo lý do
11. Chủ sở hữu sửa / di chuyển ngày lịch (update/move)
12. Manager cùng phòng ban sửa lịch của nhân viên
13. Chặn người phòng ban khác sửa lịch (403)
14. Chủ sở hữu xóa lịch
15. Manager cùng phòng ban xóa lịch của nhân viên
16. Chặn người khác xóa lịch (403)
17. Kéo thẻ công việc (Task Card) gán vào lịch
18. Gán dải ngày dài hạn (start ~ end) cho thẻ công việc
19. Hủy gán thẻ công việc khỏi lịch (unassign)
20. Phát sự kiện SSE realtime (schedule_changed) khi có thay đổi lịch
=============================================================================
"""

import os
import sys
import json
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from db import init_db, execute, query
from services.data_store import write_schedule, read_schedule, append_record, delete_record
from router import handle_get_schedule, handle_assign_schedule_task, handle_unassign_schedule_task
from handlers.schedule_handlers import (
    handle_schedule_create,
    handle_schedule_update,
    handle_schedule_delete,
    handle_schedule_approve
)


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


class TestScheduleComprehensiveSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        self.license_patch = patch("services.license_manager.is_system_read_only", return_value=False)
        self.license_patch.start()

        # Dọn dẹp dữ liệu test cũ
        execute("DELETE FROM schedule_participants")
        execute("DELETE FROM schedule_events")
        execute("DELETE FROM notifications WHERE recipient_email LIKE '%@test.local' OR link_id LIKE '998%'")
        execute("DELETE FROM users WHERE username LIKE 'sched_full_%'")

        # Tạo cây người dùng mẫu đầy đủ các vai trò và phòng ban
        test_users = [
            (991001, "sched_full_admin", "관리자A", "mgmt", "admin@test.local", 1, "admin"),
            (991002, "sched_full_dev_mgr", "개발팀장", "dev", "dev_mgr@test.local", 0, "manager"),
            (991003, "sched_full_dev_usr1", "개발팀원1", "dev", "dev_usr1@test.local", 0, "member"),
            (991004, "sched_full_dev_usr2", "개발팀원2", "dev", "dev_usr2@test.local", 0, "member"),
            (991005, "sched_full_sales_mgr", "영업팀장", "sales", "sales_mgr@test.local", 0, "manager"),
            (991006, "sched_full_sales_usr", "영업팀원", "sales", "sales_usr@test.local", 0, "member"),
            (991007, "sched_full_viewer", "조회전용", "dev", "viewer@test.local", 0, "viewer"),
        ]
        for uid, username, name, dept, email, is_admin, role in test_users:
            execute("""INSERT INTO users (id, username, name, dept_id, email, salt, password_hash, is_admin, role, disabled, status)
                       VALUES (?, ?, ?, ?, ?, 'salt', 'hash', ?, ?, 0, 'active')""",
                    (uid, username, name, dept, email, is_admin, role))

        write_schedule([])

    def tearDown(self):
        self.license_patch.stop()
        execute("DELETE FROM schedule_participants")
        execute("DELETE FROM schedule_events")
        execute("DELETE FROM notifications WHERE recipient_email LIKE '%@test.local' OR link_id LIKE '998%'")
        execute("DELETE FROM users WHERE username LIKE 'sched_full_%'")

    # -------------------------------------------------------------------------
    # 1. Tạo lịch không cần duyệt (회의, 업무, 기타)
    # -------------------------------------------------------------------------
    def test_01_create_auto_approved_event(self):
        sess = {
            "id": 991003, "username": "sched_full_dev_usr1",
            "name": "개발팀원1", "org": "dev", "dept_id": "dev",
            "email": "dev_usr1@test.local", "role": "member", "is_admin": 0
        }
        h = MockHandler(sess)
        payload = {
            "type": "회의",
            "title": "주간 스프린트 회의",
            "startDate": "2026-11-05",
            "endDate": "2026-11-05",
            "memo": "회람 회의",
            "participants": []
        }
        handle_schedule_create(h, json.dumps(payload).encode("utf-8"), "127.0.0.1")
        self.assertEqual(h.status, 200)
        self.assertTrue(h.body["ok"])
        ev = h.body["event"]
        self.assertEqual(ev["approval_status"], "approved")
        self.assertEqual(ev["approved_by"], "개발팀원1")

        # Kiểm tra không gửi thông báo yêu cầu phê duyệt cho loại lịch này
        notifs = query("SELECT * FROM notifications WHERE link_id = ?", (str(ev["id"]),))
        self.assertEqual(len(notifs or []), 0)

    # -------------------------------------------------------------------------
    # 2. Tạo lịch cần duyệt (연차, 반차, 출장, 병가) & Gửi thông báo tới Manager/Admin
    # -------------------------------------------------------------------------
    def test_02_create_leave_event_pending_and_notifies_manager(self):
        sess = {
            "id": 991003, "username": "sched_full_dev_usr1",
            "name": "개발팀원1", "org": "dev", "dept_id": "dev",
            "email": "dev_usr1@test.local", "role": "member", "is_admin": 0
        }
        h = MockHandler(sess)
        payload = {
            "type": "연차",
            "title": "가족 행사 연차 휴가",
            "startDate": "2026-11-10",
            "endDate": "2026-11-12",
            "memo": "개인 사유",
            "participants": []
        }
        handle_schedule_create(h, json.dumps(payload).encode("utf-8"), "127.0.0.1")
        self.assertEqual(h.status, 200)
        self.assertTrue(h.body["ok"])
        ev = h.body["event"]
        self.assertEqual(ev["approval_status"], "pending")
        self.assertEqual(ev["approved_by"], "")

        # Kiểm tra tự động tạo thông báo gửi đến Manager phòng dev (개발팀장) và Admin (관리자A)
        notifs = query("SELECT recipient_name, tag, title, content FROM notifications WHERE link_id = ?", (str(ev["id"]),))
        self.assertGreaterEqual(len(notifs), 1)
        recipients = [n["recipient_name"] for n in notifs]
        self.assertIn("개발팀장", recipients)
        self.assertIn("관리자A", recipients)
        self.assertNotIn("영업팀장", recipients)

    # -------------------------------------------------------------------------
    # 3. Tạo lịch có nhiều người cùng tham gia (Multi-participants)
    # -------------------------------------------------------------------------
    def test_03_create_with_multiple_participants(self):
        sess = {
            "id": 991002, "username": "sched_full_dev_mgr",
            "name": "개발팀장", "org": "dev", "dept_id": "dev",
            "email": "dev_mgr@test.local", "role": "manager", "is_admin": 0
        }
        h = MockHandler(sess)
        payload = {
            "type": "업무",
            "title": "아키텍처 리뷰 세션",
            "startDate": "2026-11-08",
            "endDate": "2026-11-08",
            "participants": [
                {"name": "개발팀원1", "org": "dev", "email": "dev_usr1@test.local"},
                {"name": "개발팀원2", "org": "dev", "email": "dev_usr2@test.local"}
            ]
        }
        handle_schedule_create(h, json.dumps(payload).encode("utf-8"), "127.0.0.1")
        self.assertEqual(h.status, 200)
        ev = h.body["event"]
        p_names = [p["name"] for p in ev["participants"]]
        self.assertIn("개발팀장", p_names)
        self.assertIn("개발팀원1", p_names)
        self.assertIn("개발팀원2", p_names)
        owner_part = next((p for p in ev["participants"] if p["name"] == "개발팀장"), None)
        self.assertTrue(owner_part.get("isOwner"))

    # -------------------------------------------------------------------------
    # 4. Validation lỗi khi tạo lịch
    # -------------------------------------------------------------------------
    def test_04_create_validation_errors(self):
        sess = {
            "id": 991003, "username": "sched_full_dev_usr1",
            "name": "개발팀원1", "org": "dev", "dept_id": "dev",
            "role": "member", "is_admin": 0
        }
        h = MockHandler(sess)

        # Trống tiêu đề
        handle_schedule_create(h, json.dumps({"title": "", "startDate": "2026-11-01"}).encode("utf-8"), "127.0.0.1")
        self.assertEqual(h.status, 400)

        # Sai định dạng ngày
        handle_schedule_create(h, json.dumps({"title": "Test", "startDate": "invalid-date"}).encode("utf-8"), "127.0.0.1")
        self.assertEqual(h.status, 400)

    # -------------------------------------------------------------------------
    # 5. Chặn Viewer tạo lịch
    # -------------------------------------------------------------------------
    def test_05_create_blocked_for_viewer(self):
        sess = {
            "id": 991007, "username": "sched_full_viewer",
            "name": "조회전용", "org": "dev", "dept_id": "dev",
            "role": "viewer", "is_admin": 0
        }
        h = MockHandler(sess)
        handle_schedule_create(h, json.dumps({"title": "Test", "startDate": "2026-11-01"}).encode("utf-8"), "127.0.0.1")
        self.assertEqual(h.status, 403)
        self.assertIn("조회 전용", h.body.get("error", ""))

    # -------------------------------------------------------------------------
    # 6. Manager cùng phòng ban duyệt lịch (Approve) & Gửi thông báo cho nhân viên
    # -------------------------------------------------------------------------
    def test_06_approve_leave_by_dept_manager(self):
        # 1. Nhân viên dev tạo lịch xin nghỉ
        ev = {
            "id": 998001,
            "ownerKey": "개발팀원1|dev",
            "ownerName": "개발팀원1",
            "ownerOrg": "dev",
            "ownerEmail": "dev_usr1@test.local",
            "type": "연차",
            "title": "11월 개인 연차",
            "startDate": "2026-11-15",
            "endDate": "2026-11-15",
            "approval_status": "pending",
            "approved_by": "",
            "participants": []
        }
        write_schedule([ev])

        # 2. Manager phòng dev duyệt
        mgr_sess = {
            "id": 991002, "username": "sched_full_dev_mgr",
            "name": "개발팀장", "org": "dev", "dept_id": "dev",
            "role": "manager", "is_admin": 0
        }
        h = MockHandler(mgr_sess)
        handle_schedule_approve(h, json.dumps({"id": 998001, "action": "approve"}).encode("utf-8"), "127.0.0.1")
        self.assertEqual(h.status, 200)
        self.assertTrue(h.body["ok"])

        # Kiểm tra DB đã cập nhật
        events = read_schedule()
        updated = next((e for e in events if str(e["id"]) == "998001"), None)
        self.assertEqual(updated["approval_status"], "approved")
        self.assertEqual(updated["approved_by"], "개발팀장")

        # Kiểm tra thông báo được gửi lại cho nhân viên (개발팀원1)
        notifs = query("SELECT recipient_name, tag, content FROM notifications WHERE recipient_email = ?", ("dev_usr1@test.local",))
        self.assertGreaterEqual(len(notifs), 1)
        self.assertIn(notifs[0]["tag"], ("승인", "결재 승인"))
        self.assertIn("승인", notifs[0]["content"])

    # -------------------------------------------------------------------------
    # 7. Chặn Manager phòng ban khác duyệt trái phép (403)
    # -------------------------------------------------------------------------
    def test_07_approve_leave_blocked_for_other_dept_manager(self):
        ev = {
            "id": 998002,
            "ownerKey": "개발팀원1|dev",
            "ownerName": "개발팀원1",
            "ownerOrg": "dev",
            "type": "연차",
            "title": "연차 신청",
            "startDate": "2026-11-15",
            "endDate": "2026-11-15",
            "approval_status": "pending",
            "participants": []
        }
        write_schedule([ev])

        sales_mgr_sess = {
            "id": 991005, "username": "sched_full_sales_mgr",
            "name": "영업팀장", "org": "sales", "dept_id": "sales",
            "role": "manager", "is_admin": 0
        }
        h = MockHandler(sales_mgr_sess)
        handle_schedule_approve(h, json.dumps({"id": 998002, "action": "approve"}).encode("utf-8"), "127.0.0.1")
        self.assertEqual(h.status, 403)
        self.assertIn("소속 부서", h.body.get("error", ""))

    # -------------------------------------------------------------------------
    # 8. Chặn Member thường duyệt (403)
    # -------------------------------------------------------------------------
    def test_08_approve_leave_blocked_for_regular_member(self):
        ev = {
            "id": 998003, "ownerKey": "개발팀원1|dev", "ownerName": "개발팀원1", "ownerOrg": "dev",
            "type": "연차", "title": "연차", "startDate": "2026-11-15", "endDate": "2026-11-15",
            "approval_status": "pending", "participants": []
        }
        write_schedule([ev])

        member_sess = {
            "id": 991004, "username": "sched_full_dev_usr2",
            "name": "개발팀원2", "org": "dev", "dept_id": "dev",
            "role": "member", "is_admin": 0
        }
        h = MockHandler(member_sess)
        handle_schedule_approve(h, json.dumps({"id": 998003, "action": "approve"}).encode("utf-8"), "127.0.0.1")
        self.assertEqual(h.status, 403)

    # -------------------------------------------------------------------------
    # 9. Admin duyệt lịch của bất kỳ phòng ban nào
    # -------------------------------------------------------------------------
    def test_09_approve_leave_allowed_for_admin_any_dept(self):
        ev = {
            "id": 998004, "ownerKey": "개발팀원1|dev", "ownerName": "개발팀원1", "ownerOrg": "dev",
            "ownerEmail": "dev_usr1@test.local",
            "type": "출장", "title": "도쿄 고객사 출장", "startDate": "2026-11-20", "endDate": "2026-11-22",
            "approval_status": "pending", "participants": []
        }
        write_schedule([ev])

        admin_sess = {
            "id": 991001, "username": "sched_full_admin",
            "name": "관리자A", "org": "mgmt", "dept_id": "mgmt",
            "role": "admin", "is_admin": 1
        }
        h = MockHandler(admin_sess)
        handle_schedule_approve(h, json.dumps({"id": 998004, "action": "approve"}).encode("utf-8"), "127.0.0.1")
        self.assertEqual(h.status, 200)
        self.assertTrue(h.body["ok"])
        events = read_schedule()
        updated = next((e for e in events if str(e["id"]) == "998004"), None)
        self.assertEqual(updated["approval_status"], "approved")

    # -------------------------------------------------------------------------
    # 10. Manager từ chối lịch kèm lý do (Reject with reason) & gửi thông báo
    # -------------------------------------------------------------------------
    def test_10_reject_leave_with_reason_and_notifies_applicant(self):
        ev = {
            "id": 998005, "ownerKey": "개발팀원1|dev", "ownerName": "개발팀원1", "ownerOrg": "dev",
            "ownerEmail": "dev_usr1@test.local",
            "type": "연차", "title": "릴리즈 당일 연차", "startDate": "2026-11-30", "endDate": "2026-11-30",
            "approval_status": "pending", "participants": []
        }
        write_schedule([ev])

        mgr_sess = {
            "id": 991002, "username": "sched_full_dev_mgr",
            "name": "개발팀장", "org": "dev", "dept_id": "dev",
            "role": "manager", "is_admin": 0
        }
        h = MockHandler(mgr_sess)
        reject_reason = "중요 버전 배포일이므로 일정 조정 부탁드립니다."
        payload = {"id": 998005, "action": "reject", "reason": reject_reason}
        handle_schedule_approve(h, json.dumps(payload).encode("utf-8"), "127.0.0.1")
        self.assertEqual(h.status, 200)

        events = read_schedule()
        updated = next((e for e in events if str(e["id"]) == "998005"), None)
        self.assertEqual(updated["approval_status"], "rejected")
        self.assertEqual(updated["reject_reason"], reject_reason)

        # Kiểm tra thông báo có kèm lý do từ chối
        notifs = query("SELECT tag, content FROM notifications WHERE recipient_email = ?", ("dev_usr1@test.local",))
        self.assertGreaterEqual(len(notifs), 1)
        self.assertIn(notifs[0]["tag"], ("반려", "결재 반려"))
        self.assertIn(reject_reason, notifs[0]["content"])

    # -------------------------------------------------------------------------
    # 11. Chủ sở hữu sửa / di chuyển ngày lịch (Update/Move)
    # -------------------------------------------------------------------------
    def test_11_update_own_event_success(self):
        ev = {
            "id": 998010, "ownerKey": "개발팀원1|dev", "ownerName": "개발팀원1", "ownerOrg": "dev",
            "type": "업무", "title": "DB 마이그레이션", "startDate": "2026-11-01", "endDate": "2026-11-01",
            "approval_status": "approved", "participants": []
        }
        write_schedule([ev])

        sess = {
            "id": 991003, "username": "sched_full_dev_usr1",
            "name": "개발팀원1", "org": "dev", "dept_id": "dev",
            "role": "member", "is_admin": 0
        }
        h = MockHandler(sess)
        payload = {
            "id": 998010,
            "title": "DB 마이그레이션 (연기)",
            "type": "업무",
            "startDate": "2026-11-03",
            "endDate": "2026-11-04"
        }
        handle_schedule_update(h, json.dumps(payload).encode("utf-8"), "127.0.0.1")
        self.assertEqual(h.status, 200)

        events = read_schedule()
        updated = next((e for e in events if str(e["id"]) == "998010"), None)
        self.assertEqual(updated["startDate"], "2026-11-03")
        self.assertEqual(updated["endDate"], "2026-11-04")
        self.assertEqual(updated["title"], "DB 마이그레이션 (연기)")

    # -------------------------------------------------------------------------
    # 12. Manager cùng phòng ban sửa lịch của nhân viên
    # -------------------------------------------------------------------------
    def test_12_update_member_event_by_dept_manager_success(self):
        ev = {
            "id": 998011, "ownerKey": "개발팀원1|dev", "ownerName": "개발팀원1", "ownerOrg": "dev",
            "type": "업무", "title": "API 개발", "startDate": "2026-11-05", "endDate": "2026-11-05",
            "approval_status": "approved", "participants": []
        }
        write_schedule([ev])

        mgr_sess = {
            "id": 991002, "username": "sched_full_dev_mgr",
            "name": "개발팀장", "org": "dev", "dept_id": "dev",
            "role": "manager", "is_admin": 0
        }
        h = MockHandler(mgr_sess)
        payload = {"id": 998011, "title": "API 개발 (팀장 수정)", "startDate": "2026-11-06", "endDate": "2026-11-06"}
        handle_schedule_update(h, json.dumps(payload).encode("utf-8"), "127.0.0.1")
        self.assertEqual(h.status, 200)

    # -------------------------------------------------------------------------
    # 13. Chặn người phòng ban khác sửa lịch (403)
    # -------------------------------------------------------------------------
    def test_13_update_event_blocked_for_other_dept_member(self):
        ev = {
            "id": 998012, "ownerKey": "개발팀원1|dev", "ownerName": "개발팀원1", "ownerOrg": "dev",
            "type": "업무", "title": "보안 패치", "startDate": "2026-11-05", "endDate": "2026-11-05",
            "approval_status": "approved", "participants": []
        }
        write_schedule([ev])

        sales_usr_sess = {
            "id": 991006, "username": "sched_full_sales_usr",
            "name": "영업팀원", "org": "sales", "dept_id": "sales",
            "role": "member", "is_admin": 0
        }
        h = MockHandler(sales_usr_sess)
        payload = {"id": 998012, "title": "해킹 시도", "startDate": "2026-11-05", "endDate": "2026-11-05"}
        handle_schedule_update(h, json.dumps(payload).encode("utf-8"), "127.0.0.1")
        self.assertEqual(h.status, 403)

    # -------------------------------------------------------------------------
    # 14. Chủ sở hữu xóa lịch
    # -------------------------------------------------------------------------
    def test_14_delete_own_event_success(self):
        ev = {
            "id": 998020, "ownerKey": "개발팀원1|dev", "ownerName": "개발팀원1", "ownerOrg": "dev",
            "type": "업무", "title": "취소된 미팅", "startDate": "2026-11-05", "endDate": "2026-11-05",
            "approval_status": "approved", "participants": []
        }
        write_schedule([ev])

        sess = {
            "id": 991003, "username": "sched_full_dev_usr1",
            "name": "개발팀원1", "org": "dev", "dept_id": "dev",
            "role": "member", "is_admin": 0
        }
        h = MockHandler(sess)
        handle_schedule_delete(h, json.dumps({"id": 998020}).encode("utf-8"), "127.0.0.1")
        self.assertEqual(h.status, 200)

        events = read_schedule()
        self.assertIsNone(next((e for e in events if str(e["id"]) == "998020"), None))

    # -------------------------------------------------------------------------
    # 15. Manager cùng phòng ban xóa lịch của nhân viên
    # -------------------------------------------------------------------------
    def test_15_delete_member_event_by_dept_manager_success(self):
        ev = {
            "id": 998021, "ownerKey": "개발팀원1|dev", "ownerName": "개발팀원1", "ownerOrg": "dev",
            "type": "업무", "title": "중복된 일정", "startDate": "2026-11-05", "endDate": "2026-11-05",
            "approval_status": "approved", "participants": []
        }
        write_schedule([ev])

        mgr_sess = {
            "id": 991002, "username": "sched_full_dev_mgr",
            "name": "개발팀장", "org": "dev", "dept_id": "dev",
            "role": "manager", "is_admin": 0
        }
        h = MockHandler(mgr_sess)
        handle_schedule_delete(h, json.dumps({"id": 998021}).encode("utf-8"), "127.0.0.1")
        self.assertEqual(h.status, 200)

    # -------------------------------------------------------------------------
    # 16. Chặn người khác xóa lịch (403)
    # -------------------------------------------------------------------------
    def test_16_delete_event_blocked_for_unauthorized_user(self):
        ev = {
            "id": 998022, "ownerKey": "개발팀원1|dev", "ownerName": "개발팀원1", "ownerOrg": "dev",
            "type": "업무", "title": "중요 기획", "startDate": "2026-11-05", "endDate": "2026-11-05",
            "approval_status": "approved", "participants": []
        }
        write_schedule([ev])

        sales_usr_sess = {
            "id": 991006, "username": "sched_full_sales_usr",
            "name": "영업팀원", "org": "sales", "dept_id": "sales",
            "role": "member", "is_admin": 0
        }
        h = MockHandler(sales_usr_sess)
        handle_schedule_delete(h, json.dumps({"id": 998022}).encode("utf-8"), "127.0.0.1")
        self.assertEqual(h.status, 403)

    # -------------------------------------------------------------------------
    # 17. Kéo thẻ công việc (Task Card) gán vào lịch
    # -------------------------------------------------------------------------
    def test_17_assign_task_card_to_schedule(self):
        rec_id = 999101
        rec = {
            "id": rec_id,
            "title": "로그인 페이지 리팩토링",
            "author": "개발팀원1",
            "dept_id": "dev",
            "org": "dev",
            "assignee": "개발팀원1",
            "assignee_id": 991003,
            "category": "dev",
            "cardCode": "REC-999101"
        }
        append_record(rec)

        sess = {
            "id": 991003, "username": "sched_full_dev_usr1",
            "name": "개발팀원1", "org": "dev", "dept_id": "dev",
            "role": "member", "is_admin": 0
        }

        try:
            h = MockHandler(sess)
            payload = {"taskId": "REC-999101", "date": "2026-11-18"}
            handle_assign_schedule_task(h, json.dumps(payload).encode("utf-8"), "127.0.0.1")
            self.assertEqual(h.status, 200)
            self.assertTrue(h.body["ok"])

            # Thẻ xuất hiện trên lịch khi gọi handle_get_schedule
            handle_get_schedule(h, None, "127.0.0.1")
            self.assertEqual(h.status, 200)
            local_tasks = h.body.get("localTasks", [])
            target_task = next((t for t in local_tasks if t.get("code") == "REC-999101" or str(t.get("id")) == str(rec_id)), None)
            self.assertIsNotNone(target_task)
            self.assertEqual(target_task.get("work_date"), "2026-11-18")
        finally:
            delete_record(rec_id)

    # -------------------------------------------------------------------------
    # 18. Gán dải ngày dài hạn (start ~ end) cho thẻ công việc
    # -------------------------------------------------------------------------
    def test_18_assign_task_card_range_to_schedule(self):
        rec_id = 999102
        rec = {
            "id": rec_id,
            "title": "통합 결제 모듈 연동",
            "author": "개발팀원1",
            "dept_id": "dev",
            "org": "dev",
            "assignee": "개발팀원1",
            "assignee_id": 991003,
            "cardCode": "REC-999102"
        }
        append_record(rec)

        sess = {
            "id": 991003, "username": "sched_full_dev_usr1",
            "name": "개발팀원1", "org": "dev", "dept_id": "dev",
            "role": "member", "is_admin": 0
        }

        try:
            h = MockHandler(sess)
            payload = {"taskId": "REC-999102", "date": "2026-11-20", "endDate": "2026-11-23"}
            handle_assign_schedule_task(h, json.dumps(payload).encode("utf-8"), "127.0.0.1")
            self.assertEqual(h.status, 200)
            self.assertEqual(h.body.get("date"), "2026-11-20 ~ 2026-11-23")
        finally:
            delete_record(rec_id)

    # -------------------------------------------------------------------------
    # 19. Hủy gán thẻ công việc khỏi lịch (Unassign)
    # -------------------------------------------------------------------------
    def test_19_unassign_task_card_from_schedule(self):
        rec_id = 999103
        rec = {
            "id": rec_id,
            "title": "성능 최적화",
            "author": "개발팀원1",
            "dept_id": "dev",
            "org": "dev",
            "assignee": "개발팀원1",
            "assignee_id": 991003,
            "cardCode": "REC-999103",
            "work_date": "2026-11-25"
        }
        append_record(rec)

        sess = {
            "id": 991003, "username": "sched_full_dev_usr1",
            "name": "개발팀원1", "org": "dev", "dept_id": "dev",
            "role": "member", "is_admin": 0
        }

        try:
            h = MockHandler(sess)
            payload = {"taskId": "REC-999103"}
            handle_unassign_schedule_task(h, json.dumps(payload).encode("utf-8"), "127.0.0.1")
            self.assertEqual(h.status, 200)
            self.assertTrue(h.body.get("unassigned"))
        finally:
            delete_record(rec_id)

    # -------------------------------------------------------------------------
    # 20. Phát sự kiện SSE realtime (schedule_changed) khi có thay đổi lịch
    # -------------------------------------------------------------------------
    def test_20_sse_broadcast_on_schedule_changes(self):
        with patch("services.notification_service.broadcast_notification_event") as mock_broadcast:
            sess = {
                "id": 991003, "username": "sched_full_dev_usr1",
                "name": "개발팀원1", "org": "dev", "dept_id": "dev",
                "role": "member", "is_admin": 0
            }
            h = MockHandler(sess)
            payload = {"type": "기타", "title": "서버 점검", "startDate": "2026-11-01", "endDate": "2026-11-01"}
            handle_schedule_create(h, json.dumps(payload).encode("utf-8"), "127.0.0.1")
            self.assertEqual(h.status, 200)

            mock_broadcast.assert_called()
            event_types = [call[0][0] for call in mock_broadcast.call_args_list]
            self.assertIn("schedule_changed", event_types)


if __name__ == "__main__":
    unittest.main()
