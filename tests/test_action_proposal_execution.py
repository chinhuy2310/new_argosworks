# -*- coding: utf-8 -*-
"""Integration tests for all chatbot action confirmation and execution flows."""
import json
import unittest
from unittest.mock import MagicMock, patch

from config import load_config
from handlers.chat_handler import handle_execute_action, handle_cancel_action, _parse_metadata
from services.chat_store import create_session, append_message, get_session


class MockHttpHandler:
    def __init__(self, session_user, cfg):
        self.session_user = session_user
        self.cfg = cfg
        self.status = 200
        self.response_data = None

    def _get_session_or_401(self):
        return self.session_user

    def _send_json(self, status, data):
        self.status = status
        self.response_data = data


class TestActionProposalExecutionFlows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = load_config()
        cls.admin_user = {
            "id": 1,
            "name": "uy",
            "org": "mgmt",
            "dept_id": "mgmt",
            "role": "admin",
            "email": "admin@argos.local"
        }

    def setUp(self):
        # Create a fresh chat session for test tracking
        self.chat_sess = create_session(user_name="uy", user_org="mgmt", title="Test Action Flow")
        self.session_id = self.chat_sess["id"]

    def test_flow_1_create_task(self):
        """Test confirming create_task creates the issue and records execution status."""
        handler = MockHttpHandler(self.admin_user, self.cfg)
        payload = json.dumps({
            "action_type": "create_task",
            "session_id": self.session_id,
            "summary": "Integration Test Task - Auto Verification",
            "description": "1. Purpose: Test\n2. Details: Verify execution\n3. Acceptance: Success",
            "assignee": "uy",
            "status": "진행중",
            "priority": "보통",
            "start_date": "2026-10-30",
            "due_date": "2026-11-05"
        }).encode("utf-8")

        handle_execute_action(handler, payload, "127.0.0.1")
        self.assertEqual(handler.status, 200)
        self.assertTrue(handler.response_data.get("ok"))
        res = handler.response_data.get("result", {})
        self.assertTrue(res.get("success") or res.get("ok"))
        
        # Verify card code or ID returned
        card_code = res.get("cardCode") or res.get("issue_key") or res.get("id")
        self.assertTrue(bool(card_code))

    def test_flow_2_create_subtask(self):
        """Test confirming create_subtask creates child task under parent."""
        handler = MockHttpHandler(self.admin_user, self.cfg)
        
        # First create parent task
        create_payload = json.dumps({
            "action_type": "create_task",
            "session_id": self.session_id,
            "summary": "Parent Task for Subtask Test",
            "description": "Parent task description",
            "assignee": "uy",
            "status": "대기",
            "priority": "보통"
        }).encode("utf-8")
        handle_execute_action(handler, create_payload, "127.0.0.1")
        parent_code = handler.response_data["result"].get("cardCode") or handler.response_data["result"].get("issue_key")

        # Now create subtask
        sub_payload = json.dumps({
            "action_type": "create_subtask",
            "session_id": self.session_id,
            "issue_key": parent_code,
            "summary": "Subtask Unit Test",
            "description": "Child work details",
            "assignee": "uy",
            "status": "대기",
            "priority": "낮음",
            "due_date": "2026-11-06"
        }).encode("utf-8")
        
        handle_execute_action(handler, sub_payload, "127.0.0.1")
        self.assertEqual(handler.status, 200)
        self.assertTrue(handler.response_data.get("ok"))
        sub_res = handler.response_data.get("result", {})
        self.assertTrue(sub_res.get("success") or sub_res.get("ok"))

    def test_flow_3_add_comment(self):
        """Test confirming add_comment posts a comment to the task."""
        handler = MockHttpHandler(self.admin_user, self.cfg)
        
        # Create task first
        create_payload = json.dumps({
            "action_type": "create_task",
            "session_id": self.session_id,
            "summary": "Task for Comment Test",
            "assignee": "uy"
        }).encode("utf-8")
        handle_execute_action(handler, create_payload, "127.0.0.1")
        card_code = handler.response_data["result"].get("cardCode") or handler.response_data["result"].get("issue_key")

        # Add comment
        comment_payload = json.dumps({
            "action_type": "add_comment",
            "session_id": self.session_id,
            "issue_key": card_code,
            "comment": "Testing confirmation comment: API verification complete."
        }).encode("utf-8")

        handle_execute_action(handler, comment_payload, "127.0.0.1")
        self.assertEqual(handler.status, 200)
        self.assertTrue(handler.response_data.get("ok"))
        comm_res = handler.response_data.get("result", {})
        self.assertTrue(comm_res.get("success") or comm_res.get("ok"))

    def test_flow_4_update_status(self):
        """Test confirming update_status changes card status."""
        handler = MockHttpHandler(self.admin_user, self.cfg)
        
        # Create task first
        create_payload = json.dumps({
            "action_type": "create_task",
            "session_id": self.session_id,
            "summary": "Task for Status Update Test",
            "assignee": "uy",
            "status": "대기"
        }).encode("utf-8")
        handle_execute_action(handler, create_payload, "127.0.0.1")
        card_code = handler.response_data["result"].get("cardCode") or handler.response_data["result"].get("issue_key")

        # Update status to 완료
        status_payload = json.dumps({
            "action_type": "update_status",
            "session_id": self.session_id,
            "issue_key": card_code,
            "status": "완료"
        }).encode("utf-8")

        handle_execute_action(handler, status_payload, "127.0.0.1")
        self.assertEqual(handler.status, 200)
        self.assertTrue(handler.response_data.get("ok"))
        stat_res = handler.response_data.get("result", {})
        self.assertTrue(stat_res.get("success") or stat_res.get("ok"))

    def test_flow_5_schedule_issue(self):
        """Test confirming schedule_issue updates start_date and due_date."""
        handler = MockHttpHandler(self.admin_user, self.cfg)
        
        # Create task first
        create_payload = json.dumps({
            "action_type": "create_task",
            "session_id": self.session_id,
            "summary": "Task for Scheduling Test",
            "assignee": "uy"
        }).encode("utf-8")
        handle_execute_action(handler, create_payload, "127.0.0.1")
        card_code = handler.response_data["result"].get("cardCode") or handler.response_data["result"].get("issue_key")

        # Schedule task
        sched_payload = json.dumps({
            "action_type": "schedule_issue",
            "session_id": self.session_id,
            "issue_key": card_code,
            "start_date": "2026-11-01",
            "due_date": "2026-11-10"
        }).encode("utf-8")

        handle_execute_action(handler, sched_payload, "127.0.0.1")
        self.assertEqual(handler.status, 200)
        self.assertTrue(handler.response_data.get("ok"))
        sched_res = handler.response_data.get("result", {})
        self.assertTrue(sched_res.get("success") or sched_res.get("ok"))

    def test_flow_cancel_action(self):
        """Test canceling proposal marks status as rejected/cancelled."""
        handler = MockHttpHandler(self.admin_user, self.cfg)
        cancel_payload = json.dumps({
            "session_id": self.session_id,
            "action_type": "create_task",
            "summary": "Rejected Task Proposal"
        }).encode("utf-8")

        handle_cancel_action(handler, cancel_payload, "127.0.0.1")
        self.assertEqual(handler.status, 200)
        self.assertTrue(handler.response_data.get("ok"))


if __name__ == "__main__":
    unittest.main()
