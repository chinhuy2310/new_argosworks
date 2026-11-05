# -*- coding: utf-8 -*-
"""Tests for the persisted chatbot action-proposal confirmation lifecycle."""
import json
import unittest
from unittest.mock import patch

from config import load_config
from handlers.chat_handler import handle_execute_action, handle_cancel_action
from services.chat_store import create_session, append_message, load_history


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
            "email": "admin@argos.local",
        }

    def setUp(self):
        self.chat_sess = create_session(user_name="uy", user_org="mgmt", title="Test Action Flow")
        self.session_id = self.chat_sess["id"]

    def _store_proposal(self, action_type, **fields):
        """Persist the same server-owned proposal metadata the UI confirmation flow uses."""
        message = append_message(
            self.session_id,
            "assistant",
            "아래 제안을 확인해 주세요.",
            "ARGOS",
            metadata={
                "action_proposal": {
                    "action_type": action_type,
                    "proposal_status": "pending",
                    **fields,
                }
            },
        )
        return message["id"]

    def _execute(self, action_type, fields, result=None):
        message_id = self._store_proposal(action_type, **fields)
        handler = MockHttpHandler(self.admin_user, self.cfg)
        payload = json.dumps({
            "action_type": action_type,
            "session_id": self.session_id,
            "message_id": message_id,
        }).encode("utf-8")
        tool_result = result or {"success": True, "issue_key": "TEST-100"}
        with patch("handlers.chat_handler.execute_tool", return_value=tool_result) as execute_tool:
            handle_execute_action(handler, payload, "127.0.0.1")
        self.assertEqual(handler.status, 200, handler.response_data)
        self.assertTrue(handler.response_data.get("ok"), handler.response_data)
        self.assertTrue(handler.response_data.get("result", {}).get("success"))
        stored = next(m for m in load_history(self.session_id, limit=100) if m["id"] == message_id)
        self.assertEqual(stored["metadata"]["action_proposal"]["proposal_status"], "executed")
        return handler.response_data["result"], execute_tool

    def test_flow_1_create_task(self):
        result, tool = self._execute(
            "create_task",
            {
                "summary": "Integration Test Task",
                "description": "Purpose, details and acceptance criteria",
                "assignee": "uy",
                "status": "진행중",
                "priority": "보통",
                "start_date": "2026-10-30",
                "due_date": "2026-11-05",
            },
        )
        self.assertEqual(tool.call_args.args[0], "create_issue")
        self.assertEqual(tool.call_args.args[1]["summary"], "Integration Test Task")
        self.assertTrue(result.get("issue_key"))

    def test_flow_2_create_subtask(self):
        self._execute(
            "create_task",
            {"summary": "Parent task", "description": "Parent description"},
            {"success": True, "issue_key": "TEST-200"},
        )
        result, tool = self._execute(
            "create_subtask",
            {
                "summary": "Subtask Unit Test",
                "description": "Child work details",
                "parent_key": "TEST-200",
                "assignee": "uy",
                "status": "대기",
                "priority": "낮음",
                "due_date": "2026-11-06",
            },
            {"success": True, "issue_key": "TEST-201"},
        )
        self.assertEqual(tool.call_args.args[0], "create_issue")
        self.assertEqual(tool.call_args.args[1]["parent_key"], "TEST-200")
        self.assertEqual(result["issue_key"], "TEST-201")

    def test_flow_3_add_comment(self):
        _, tool = self._execute(
            "add_comment",
            {
                "issue_key": "TEST-300",
                "comment": "Testing confirmation comment: API verification complete.",
            },
        )
        self.assertEqual(tool.call_args.args[0], "add_issue_comment")
        self.assertEqual(tool.call_args.args[1]["issue_key"], "TEST-300")

    def test_flow_4_update_status(self):
        _, tool = self._execute(
            "update_status",
            {"issue_key": "TEST-400", "status": "완료"},
        )
        self.assertEqual(tool.call_args.args[0], "update_issue_status")
        self.assertEqual(tool.call_args.args[1]["status"], "완료")

    def test_flow_5_schedule_issue(self):
        _, tool = self._execute(
            "schedule_issue",
            {
                "issue_key": "TEST-500",
                "start_date": "2026-11-01",
                "due_date": "2026-11-10",
            },
        )
        self.assertEqual(tool.call_args.args[0], "schedule_issue")
        self.assertEqual(tool.call_args.args[1]["due_date"], "2026-11-10")

    def test_flow_cancel_action(self):
        message_id = self._store_proposal(
            "create_task",
            summary="Rejected Task Proposal",
            description="Should never be executed",
        )
        handler = MockHttpHandler(self.admin_user, self.cfg)
        payload = json.dumps({
            "session_id": self.session_id,
            "message_id": message_id,
            "action_type": "create_task",
        }).encode("utf-8")

        handle_cancel_action(handler, payload, "127.0.0.1")

        self.assertEqual(handler.status, 200, handler.response_data)
        self.assertTrue(handler.response_data.get("ok"))
        stored = next(m for m in load_history(self.session_id, limit=100) if m["id"] == message_id)
        self.assertEqual(stored["metadata"]["action_proposal"]["proposal_status"], "cancelled")


if __name__ == "__main__":
    unittest.main()
