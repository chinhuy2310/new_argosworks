"""AI 챗봇 RBAC 강화 회귀 테스트.

검증 대상:
1. 일정(calendar) 조회 도구의 부서/본인/참여자 격리
2. 사내 기록 검색 도구의 일정 부분 격리
3. 벡터(의미) 검색 문서 단위 RBAC (record / jira / schedule)
4. 참조 카드가 시스템 프롬프트로 주입될 때의 RBAC (타 부서 비공개 카드 차단)
5. 시스템 프롬프트 활성 업무 목록의 RBAC (동명이인 타 부서 비공개 카드 차단)
6. 하위 작업 생성 시 상위 카드 권한 검증
7. action proposal 상태 변경의 세션 소유자 검증(IDOR)
"""
import os
import sys
import unittest
from unittest import mock

# Ensure server module is in sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from db import execute

from services.auth import visible_schedule_events
from services.vector_store import (
    _mask_price_text,
    build_doc_permission_context,
    can_view_vector_doc,
)
from services.chat_tools import (
    _tool_create_issue,
    _tool_get_calendar_schedule,
    _tool_search_internal_records,
)
from services.chat_store import (
    append_message,
    create_session,
    delete_session,
    update_proposal_status,
)
from handlers.chat_handler import _build_referenced_section, _build_system_prompt


TEST_MONTH = "2099-11"
DEV_EVENT_ID = 9999101
SALES_EVENT_ID = 9999102
SALES_EVENT_SHARED_ID = 9999103


class TestAiChatRbacHardening(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        execute("DELETE FROM schedule_participants WHERE event_id >= 9999100")
        execute("DELETE FROM schedule_events WHERE id >= 9999100")
        execute("DELETE FROM records WHERE id >= 999900")

        execute(
            "INSERT INTO records (id, card_code, title, summary, dept_id, category, assignee_name, is_private, status, work_date) "
            "VALUES (999901, 'DEV-901', 'Dev Public Task', 'Public task for dev', 'dev', '개발', 'park.sj', 0, '진행', '2099-11-02')"
        )
        execute(
            "INSERT INTO records (id, card_code, title, summary, dept_id, category, assignee_name, is_private, status, work_date) "
            "VALUES (999903, 'SALES-903', 'Sales Confidential Deal', 'High value secret deal', 'sales', '영업', '강동원', 1, '진행', '2099-11-03')"
        )
        # 동명이인(타 부서 비공개) — 시스템 프롬프트 활성 업무 RBAC 검증용
        execute(
            "INSERT INTO records (id, card_code, title, summary, dept_id, category, assignee_name, is_private, status, work_date) "
            "VALUES (999906, 'SALES-906', 'Sales Name Collision Secret', 'Cross dept private card', 'sales', '영업', '박승재', 1, '진행', '2099-11-04')"
        )

        execute(
            "INSERT INTO schedule_events (id, owner_name, owner_dept_id, owner_email, type, title, start_date, end_date, memo) "
            "VALUES (?, '박승재', 'dev', 'park@example.com', '연차', 'DEV 팀 연차 일정', '2099-11-02', '2099-11-02', 'dev only memo')",
            (DEV_EVENT_ID,)
        )
        execute(
            "INSERT INTO schedule_events (id, owner_name, owner_dept_id, owner_email, type, title, start_date, end_date, memo) "
            "VALUES (?, '강동원', 'sales', 'kang@example.com', '연차', 'SALES 비밀 휴가 일정', '2099-11-03', '2099-11-03', 'sales secret memo')",
            (SALES_EVENT_ID,)
        )
        execute(
            "INSERT INTO schedule_events (id, owner_name, owner_dept_id, owner_email, type, title, start_date, end_date, memo) "
            "VALUES (?, '강동원', 'sales', 'kang@example.com', '회의', 'SALES 협업 회의', '2099-11-05', '2099-11-05', '참석자 초대 메모')",
            (SALES_EVENT_SHARED_ID,)
        )
        # 타 부서 일정이지만 dev 사용자가 참석자로 등록된 경우는 열람 가능해야 한다
        execute(
            "INSERT INTO schedule_participants (event_id, user_name, user_dept_id, user_email, is_owner) "
            "VALUES (?, '박승재', 'dev', 'park@example.com', 0)",
            (SALES_EVENT_SHARED_ID,)
        )

    @classmethod
    def tearDownClass(cls):
        execute("DELETE FROM schedule_participants WHERE event_id >= 9999100")
        execute("DELETE FROM schedule_events WHERE id >= 9999100")
        execute("DELETE FROM records WHERE id >= 999900")

    def setUp(self):
        self.cfg = {"jira": {"enabled": False}}
        self.user_admin = {
            "id": 1,
            "username": "admin",
            "name": "Admin User",
            "org": "mgmt",
            "dept_id": "mgmt",
            "role": "admin",
            "is_admin": 1,
        }
        self.user_dev_member = {
            "id": 3,
            "username": "park.sj",
            "name": "박승재",
            "org": "dev",
            "dept_id": "dev",
            "role": "member",
            "is_admin": 0,
        }
        self.user_sales_member = {
            "id": 6,
            "username": "kang.dw",
            "name": "강동원",
            "org": "sales",
            "dept_id": "sales",
            "role": "member",
            "is_admin": 0,
        }

    # ------------------------------------------------------------------
    # 1. 일정 도구 RBAC
    # ------------------------------------------------------------------
    def test_calendar_tool_dept_isolation(self):
        """get_calendar_schedule 도구는 타 부서 일정(메모 포함)을 반환하면 안 된다."""
        res_dev = _tool_get_calendar_schedule({"month": TEST_MONTH}, self.user_dev_member, self.cfg)
        titles_dev = [e.get("title") for e in res_dev["events"]]
        self.assertIn("DEV 팀 연차 일정", titles_dev)
        self.assertNotIn("SALES 비밀 휴가 일정", titles_dev)
        # 참석자로 등록된 타 부서 일정은 열람 가능
        self.assertIn("SALES 협업 회의", titles_dev)
        memos_dev = " ".join(e.get("memo", "") for e in res_dev["events"])
        self.assertNotIn("sales secret memo", memos_dev)

        # admin은 전체 열람
        res_admin = _tool_get_calendar_schedule({"month": TEST_MONTH}, self.user_admin, self.cfg)
        titles_admin = [e.get("title") for e in res_admin["events"]]
        self.assertIn("DEV 팀 연차 일정", titles_admin)
        self.assertIn("SALES 비밀 휴가 일정", titles_admin)

    def test_search_internal_records_schedule_isolation(self):
        """search_internal_records 도구의 일정 파트도 동일한 RBAC 기준을 적용해야 한다."""
        res_dev = _tool_search_internal_records({"query": "SALES 비밀"}, self.user_dev_member, self.cfg)
        titles_dev = [e.get("title") for e in res_dev["schedule_events"]]
        self.assertNotIn("SALES 비밀 휴가 일정", titles_dev)

        res_sales = _tool_search_internal_records({"query": "SALES 비밀"}, self.user_sales_member, self.cfg)
        titles_sales = [e.get("title") for e in res_sales["schedule_events"]]
        self.assertIn("SALES 비밀 휴가 일정", titles_sales)

    def test_visible_schedule_events_helper(self):
        """auth.visible_schedule_events 단일 기준 검증 (admin/부서/본인/참여자)."""
        events = [
            {"id": DEV_EVENT_ID, "ownerName": "박승재", "ownerOrg": "dev", "title": "DEV", "participants": []},
            {"id": SALES_EVENT_ID, "ownerName": "강동원", "ownerOrg": "sales", "title": "SALES", "participants": []},
            {"id": 9999199, "ownerName": "강동원", "ownerOrg": "sales", "title": "SALES-SHARED",
             "participants": [{"name": "박승재", "org": "dev"}]},
        ]
        ids_dev = [e["id"] for e in visible_schedule_events(self.user_dev_member, events)]
        self.assertIn(DEV_EVENT_ID, ids_dev)
        self.assertNotIn(SALES_EVENT_ID, ids_dev)
        self.assertIn(9999199, ids_dev)

        ids_admin = [e["id"] for e in visible_schedule_events(self.user_admin, events)]
        self.assertEqual(sorted(ids_admin), sorted([DEV_EVENT_ID, SALES_EVENT_ID, 9999199]))

    # ------------------------------------------------------------------
    # 2. 벡터(의미) 검색 RBAC
    # ------------------------------------------------------------------
    def test_vector_doc_rbac_isolation(self):
        """벡터 검색 결과도 doc_type별로 레코드/일정과 동일한 권한 규칙을 적용해야 한다."""
        ctx_dev = build_doc_permission_context(self.user_dev_member)

        # 타 부서 비공개 레코드
        self.assertFalse(can_view_vector_doc(
            self.user_dev_member, "record",
            {"dept_id": "sales", "is_private": True, "assignee_name": "강동원"}, ctx_dev
        ))
        # 같은 부서 공개 레코드
        self.assertTrue(can_view_vector_doc(
            self.user_dev_member, "record",
            {"dept_id": "dev", "is_private": False, "assignee_name": "park.sj"}, ctx_dev
        ))
        # Jira 문서: 타 부서 차단 / 같은 부서 허용
        self.assertFalse(can_view_vector_doc(
            self.user_dev_member, "jira", {"org": "sales", "assignee": "강동원"}, ctx_dev
        ))
        self.assertTrue(can_view_vector_doc(
            self.user_dev_member, "jira", {"org": "dev", "assignee": "이도현"}, ctx_dev
        ))
        # 일정 문서: 타 부서 차단 / 같은 부서 허용
        self.assertFalse(can_view_vector_doc(
            self.user_dev_member, "schedule",
            {"id": SALES_EVENT_ID, "org": "sales", "ownerName": "강동원", "ownerOrg": "sales"}, ctx_dev
        ))
        self.assertTrue(can_view_vector_doc(
            self.user_dev_member, "schedule",
            {"id": DEV_EVENT_ID, "org": "dev", "ownerName": "박승재", "ownerOrg": "dev"}, ctx_dev
        ))
        # 레거시 메타데이터(ownerName 없음)도 원본 일정 조회로 권한 판정
        self.assertFalse(can_view_vector_doc(
            self.user_dev_member, "schedule", {"id": SALES_EVENT_ID, "org": "sales"}, ctx_dev
        ))

        # admin은 전체 허용
        ctx_admin = build_doc_permission_context(self.user_admin)
        self.assertTrue(can_view_vector_doc(
            self.user_admin, "schedule",
            {"id": SALES_EVENT_ID, "org": "sales", "ownerName": "강동원", "ownerOrg": "sales"}, ctx_admin
        ))

    def test_price_text_masking(self):
        """가격 텍스트 마스킹 헬퍼 검증 (벡터 요약문 유출 방지)."""
        self.assertIn("[가격 비공개]", _mask_price_text("기준 가격: 1,200,000 KRW"))
        self.assertIn("[가격 비공개]", _mask_price_text("단가 35000원"))
        self.assertEqual(_mask_price_text("일반 사양 설명 4K HDMI"), "일반 사양 설명 4K HDMI")

    # ------------------------------------------------------------------
    # 3. 시스템 프롬프트 주입 RBAC
    # ------------------------------------------------------------------
    def test_referenced_section_rbac(self):
        """메시지에 포함된 카드 코드의 상세 정보는 권한 내 카드만 프롬프트에 주입돼야 한다."""
        section_dev = _build_referenced_section(["SALES-903"], self.cfg, self.user_dev_member)
        self.assertEqual(section_dev, "")
        self.assertNotIn("Sales Confidential Deal", section_dev)

        section_own = _build_referenced_section(["DEV-901"], self.cfg, self.user_dev_member)
        self.assertIn("DEV-901", section_own)

        section_admin = _build_referenced_section(["SALES-903"], self.cfg, self.user_admin)
        self.assertIn("Sales Confidential Deal", section_admin)

    def test_system_prompt_active_tasks_rbac(self):
        """활성 업무 목록도 visible_records로 필터링되어야 한다 (동명이인 타 부서 비공개 카드 차단)."""
        prompt_dev = _build_system_prompt("박승재", self.cfg, self.user_dev_member)
        self.assertNotIn("Sales Name Collision Secret", prompt_dev)

        prompt_admin = _build_system_prompt("박승재", self.cfg, self.user_admin)
        self.assertIn("Sales Name Collision Secret", prompt_admin)

    # ------------------------------------------------------------------
    # 4. 쓰기/상태 변조 방지
    # ------------------------------------------------------------------
    def test_create_issue_blocks_parent_without_permission(self):
        """권한 없는 상위 카드(타 부서 비공개)에는 하위 작업을 생성할 수 없어야 한다."""
        with mock.patch("services.license_manager.is_system_read_only", return_value=False):
            res = _tool_create_issue(
                {"summary": "Unauthorized subtask", "parent_key": "SALES-903"},
                self.user_dev_member,
                self.cfg,
            )
        self.assertFalse(res.get("success"))
        self.assertIn("권한", res.get("error", ""))

    def test_ask_product_context_hides_price_without_permission(self):
        """홈 자연어 검색(/api/ask)의 제품 컨텍스트도 가격 권한이 없으면 단가를 포함하면 안 된다."""
        from services.search import product_as_search_record

        prod = {
            "id": "prod_test_rbac",
            "model": "TEST-CAM",
            "displayName": "Test Cam",
            "category": "카메라",
            "summary": "테스트 제품 요약",
            "memo": "",
            "specs": {"해상도": "4K"},
            "procurement": {"price": 1200000, "identificationNo": "123", "registeredName": "테스트 품명"},
            "attachments": [],
        }
        blocked = product_as_search_record(prod, allow_price=False)
        self.assertNotIn("단가", blocked["memo"])
        self.assertNotIn("단가", blocked["summary"])

        allowed = product_as_search_record(prod, allow_price=True)
        self.assertIn("단가", allowed["memo"])

    def test_update_proposal_status_owner_only(self):
        """타 사용자의 세션에 대한 action proposal 상태 변조는 거부되어야 한다."""
        chat_sess = create_session("RBAC Test Owner", "dev", "RBAC test")
        try:
            msg = append_message(
                chat_sess["id"], "assistant", "proposal", "AI",
                metadata={"action_proposal": {"summary": "test proposal", "proposal_status": "pending"}}
            )
            self.assertFalse(update_proposal_status(
                chat_sess["id"], "executed", message_id=msg["id"], user_name="Intruder"
            ))
            self.assertTrue(update_proposal_status(
                chat_sess["id"], "executed", message_id=msg["id"], user_name="RBAC Test Owner"
            ))
        finally:
            delete_session(chat_sess["id"], "RBAC Test Owner")


if __name__ == "__main__":
    unittest.main()
