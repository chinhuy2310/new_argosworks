"""Tab Home search RBAC 회귀 테스트.

핵심 원칙: 검색 결과 목록뿐 아니라, 검색 결과를 클릭했을 때 열리는 상세 엔드포인트
(/api/issues, /api/records/hierarchy, /api/jira/attachments)도 동일한 권한 기준을 적용해야 한다.

검증 항목:
1. 타 부서 비공개 카드 상세 조회 차단 (IDOR)
2. 같은 부서 / admin 허용
3. 권한 없는 하위 작업(subtasks) 제거
4. 동명이인(타 부서 비공개) 차단
5. 계층(hierarchy) 차단 및 상위 경로 truncate
6. Jira 첨부파일 IDOR 차단 / 권한 있는 경우 통과
7. /api/ask 최종 게이트: 권한 밖 검색 결과는 sources 에서 제외
8. can_view_search_item 헬퍼 단위 검증
"""
import json
import os
import sys
import unittest
from unittest.mock import patch
from urllib.parse import urlparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from db import init_db, execute
from services.data_store import append_record
from services.auth import can_view_search_item
from router import (
    handle_get_issue_detail,
    handle_get_record_hierarchy,
    handle_get_jira_attachment,
    handle_get_ask,
)


REC_DEV = 996701
REC_SALES_PRIVATE = 996702
REC_SALES_CHILD = 996703
REC_DEV_PARENT = 996704
REC_HIDDEN_CHILD = 996705
REC_SALES_ROOT = 996706
REC_DEV_CHILD = 996707
REC_SAME_NAME = 996708

DEV_MEMBER = {
    "id": 996102, "user_id": 996102, "username": "hs_dev_member", "name": "HS Dev",
    "role": "member", "org": "dev", "dept_id": "dev", "email": "hs_dev@test.local", "is_admin": 0,
}
SALES_MEMBER = {
    "id": 996104, "user_id": 996104, "username": "hs_sales_member", "name": "HS Sales",
    "role": "member", "org": "sales", "dept_id": "sales", "email": "hs_sales@test.local", "is_admin": 0,
}
ADMIN = {
    "id": 996101, "user_id": 996101, "username": "hs_admin", "name": "HS Admin",
    "role": "admin", "org": "mgmt", "dept_id": "mgmt", "email": "hs_admin@test.local", "is_admin": 1,
}


class MockHandler:
    def __init__(self, sess, cfg=None):
        self.session = sess
        self.status = None
        self.body = None
        self.headers = {}
        self.cfg = cfg or {"jira": {"enabled": False, "api_token": ""}, "ai": {}, "voyage": {}}

    def _get_session_or_401(self):
        if not self.session:
            self._send_json(401, {"ok": False, "error": "로그인이 필요합니다."})
            return None
        return self.session

    def _send_json(self, status, payload, extra_headers=None):
        self.status = status
        self.body = payload


def _rec(rec_id, org, title, assignee, card_code, is_private=0, parent_key=""):
    return {
        "id": rec_id,
        "org": org,
        "category": "업무",
        "title": title,
        "project": "HS",
        "assignee": assignee,
        "assigneeEmail": "",
        "startDate": "2099-01-02",
        "dueDate": "2099-01-03",
        "summary": "",
        "tags": [],
        "memo": "",
        "cardCode": card_code,
        "participants": "",
        "parentKey": parent_key,
        "is_private": is_private,
        "jira": None,
    }


class TestHomeSearchRbac(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        execute("DELETE FROM records WHERE id >= 996700")
        append_record(_rec(REC_DEV, "dev", "Home Search Dev Task", "HS Dev", "HSDEV-1"))
        append_record(_rec(REC_SALES_PRIVATE, "sales", "Home Search Sales Secret", "HS Sales", "HSSALES-1", 1))
        append_record(_rec(REC_SALES_CHILD, "sales", "Home Search Sales Child", "HS Sales", "HSSALES-2", 1, "HSSALES-1"))
        append_record(_rec(REC_DEV_PARENT, "dev", "Home Search Dev Parent", "HS Dev", "HSDEV-PARENT"))
        append_record(_rec(REC_HIDDEN_CHILD, "sales", "Home Search Hidden Child", "HS Sales", "HSSALES-CHILD", 1, "HSDEV-PARENT"))
        append_record(_rec(REC_SALES_ROOT, "sales", "Home Search Sales Root", "HS Sales", "HSSALES-ROOT", 1))
        append_record(_rec(REC_DEV_CHILD, "dev", "Home Search Dev Child", "HS Dev", "HSDEV-CHILD", 0, "HSSALES-ROOT"))
        # 동명이인: dev 사용자와 같은 이름이지만 sales 부서의 비공개 카드
        append_record(_rec(REC_SAME_NAME, "sales", "Home Search Same Name Secret", "HS Dev", "HSSALES-SAMENAME", 1))

    def tearDown(self):
        execute("DELETE FROM records WHERE id >= 996700")

    # ---------------------------------------------------------- issue detail
    def test_issue_detail_blocks_cross_dept_private(self):
        handler = MockHandler(DEV_MEMBER)
        handle_get_issue_detail(handler, urlparse("/api/issues?key=HSSALES-1"), "127.0.0.1")
        self.assertEqual(handler.status, 404)
        self.assertNotIn("Home Search Sales Secret", json.dumps(handler.body, ensure_ascii=False))

    def test_issue_detail_allows_same_dept_and_admin(self):
        same_dept = MockHandler(DEV_MEMBER)
        handle_get_issue_detail(same_dept, urlparse("/api/issues?key=HSDEV-1"), "127.0.0.1")
        self.assertEqual(same_dept.status, 200)
        self.assertIn("Home Search Dev Task", str(same_dept.body.get("title", "")))

        admin = MockHandler(ADMIN)
        handle_get_issue_detail(admin, urlparse("/api/issues?key=HSSALES-1"), "127.0.0.1")
        self.assertEqual(admin.status, 200)
        self.assertIn("Home Search Sales Secret", json.dumps(admin.body, ensure_ascii=False))

    def test_issue_detail_filters_unauthorized_subtasks(self):
        handler = MockHandler(DEV_MEMBER)
        handle_get_issue_detail(handler, urlparse("/api/issues?key=HSDEV-PARENT"), "127.0.0.1")
        self.assertEqual(handler.status, 200)
        payload = json.dumps(handler.body, ensure_ascii=False)
        self.assertNotIn("HSSALES-CHILD", payload)
        self.assertNotIn("Home Search Hidden Child", payload)

    def test_issue_detail_blocks_same_name_other_dept_private(self):
        handler = MockHandler(DEV_MEMBER)
        handle_get_issue_detail(handler, urlparse("/api/issues?key=HSSALES-SAMENAME"), "127.0.0.1")
        self.assertEqual(handler.status, 404)

    # -------------------------------------------------------------- hierarchy
    def test_record_hierarchy_blocks_cross_dept(self):
        handler = MockHandler(DEV_MEMBER)
        handle_get_record_hierarchy(handler, urlparse("/api/records/hierarchy?id=996702"), "127.0.0.1")
        self.assertEqual(handler.status, 404)

    def test_record_hierarchy_truncates_hidden_parent(self):
        handler = MockHandler(DEV_MEMBER)
        handle_get_record_hierarchy(handler, urlparse("/api/records/hierarchy?id=996707"), "127.0.0.1")
        self.assertEqual(handler.status, 200)
        self.assertTrue(handler.body.get("truncated"))
        self.assertNotIn("Home Search Sales Root", json.dumps(handler.body, ensure_ascii=False))

    # ------------------------------------------------------------- attachment
    def test_jira_attachment_blocks_without_permission(self):
        with patch("services.jira_client.find_issue_key_by_attachment_id", return_value="HSSALES-1"):
            handler = MockHandler(DEV_MEMBER)
            handle_get_jira_attachment(handler, urlparse("/api/jira/attachments/att-123"), "127.0.0.1")
        self.assertEqual(handler.status, 403)

    def test_jira_attachment_allows_permitted_issue(self):
        with patch("services.jira_client.find_issue_key_by_attachment_id", return_value="HSDEV-1"):
            handler = MockHandler(DEV_MEMBER)
            handle_get_jira_attachment(handler, urlparse("/api/jira/attachments/att-456"), "127.0.0.1")
        # Jira 가 비활성인 테스트 설정이므로 RBAC 통과 후 500 (Jira disabled) 이어야 한다.
        self.assertEqual(handler.status, 500)

    # --------------------------------------------------------------- /api/ask
    def test_ask_sources_exclude_unauthorized(self):
        vector_hit = [{
            "id": REC_SALES_PRIVATE,
            "doc_id": f"record:{REC_SALES_PRIVATE}",
            "doc_type": "record",
            "title": "Home Search Sales Secret",
            "similarity": 0.95,
            "summary": "secret summary",
            "org": "sales",
            "category": "업무",
            "date": "2099-01-02",
            "assignee": "HS Sales",
            "jira": None,
        }]

        with patch("router.is_voyage_configured", return_value=True), \
             patch("router.search_vector_store", return_value=vector_hit), \
             patch("router.call_ai_answer", return_value=None):
            dev = MockHandler(DEV_MEMBER)
            handle_get_ask(dev, urlparse("/api/ask?q=Home+Search+Sales+Secret"), "127.0.0.1")
        self.assertEqual(dev.status, 200)
        dev_titles = [s.get("title") for s in dev.body.get("sources", [])]
        self.assertNotIn("Home Search Sales Secret", dev_titles)

        with patch("router.is_voyage_configured", return_value=True), \
             patch("router.search_vector_store", return_value=vector_hit), \
             patch("router.call_ai_answer", return_value=None):
            sales = MockHandler(SALES_MEMBER)
            handle_get_ask(sales, urlparse("/api/ask?q=Home+Search+Sales+Secret"), "127.0.0.1")
        self.assertEqual(sales.status, 200)
        sales_titles = [s.get("title") for s in sales.body.get("sources", [])]
        self.assertIn("Home Search Sales Secret", sales_titles)

    def test_can_view_search_item_helper(self):
        # 제품은 전사 공개 (가격은 별도 마스킹)
        self.assertTrue(can_view_search_item(DEV_MEMBER, {"id": "product-prod_1", "org": "사내"}))
        # 타 부서 비공개 레코드 차단 / 같은 부서 허용
        self.assertFalse(can_view_search_item(
            DEV_MEMBER, {"id": REC_SALES_PRIVATE, "org": "sales", "dept_id": "sales", "is_private": True}
        ))
        self.assertTrue(can_view_search_item(
            DEV_MEMBER, {"id": REC_DEV, "org": "dev", "dept_id": "dev", "is_private": False}
        ))
        # 일정은 부서/본인 기준
        self.assertTrue(can_view_search_item(
            DEV_MEMBER, {"id": "schedule-1", "ownerName": "HS Dev", "ownerOrg": "dev"}
        ))
        self.assertFalse(can_view_search_item(
            DEV_MEMBER, {"id": "schedule-2", "ownerName": "HS Sales", "ownerOrg": "sales"}
        ))


if __name__ == "__main__":
    unittest.main()
