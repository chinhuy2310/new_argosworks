# -*- coding: utf-8 -*-
import json
from unittest.mock import patch

from handlers.chat_handler import handle_execute_action
from services.chat_store import append_message, create_session, load_history


class DummyActionHandler:
    def __init__(self, session):
        self._session = session
        self.cfg = {}
        self.responses = []

    def _get_session_or_401(self):
        return self._session

    def _send_json(self, status, data):
        self.responses.append((status, data))


def _setup_pending_proposal(tmp_db, proposal=None):
    session = {
        "id": 101,
        "name": "Alice",
        "org": "dev",
        "role": "admin",
        "email": "alice@example.test",
    }
    chat_session = create_session("Alice", "dev", "Action validation")
    stored_proposal = proposal or {
        "action_type": "create_task",
        "proposal_status": "pending",
        "summary": "Trusted task title",
        "description": "Trusted task description",
        "status": "대기",
        "priority": "보통",
    }
    message = append_message(
        chat_session["id"],
        "assistant",
        "Proposal",
        "AI",
        metadata={"action_proposal": stored_proposal},
    )
    return session, chat_session["id"], message["id"], stored_proposal


def test_execute_action_requires_a_stored_pending_proposal(tmp_db):
    session, session_id, message_id, _proposal = _setup_pending_proposal(tmp_db)
    handler = DummyActionHandler(session)
    payload = {
        "session_id": session_id,
        "message_id": message_id,
        "action_type": "create_task",
        "summary": "Client-invented task",
    }

    with patch("handlers.chat_handler.execute_tool") as execute_mock:
        handle_execute_action(handler, json.dumps(payload).encode(), "127.0.0.1")

    assert handler.responses[0][0] == 200
    assert handler.responses[0][1]["ok"] is True
    execute_mock.assert_called_once()
    args = execute_mock.call_args.args[1]
    assert args["summary"] == "Trusted task title"
    assert args["description"] == "Trusted task description"
    assert execute_mock.call_args.kwargs["allow_write"] is True

    # A second request cannot replay an already executed proposal.
    replay_handler = DummyActionHandler(session)
    with patch("handlers.chat_handler.execute_tool") as replay_mock:
        handle_execute_action(replay_handler, json.dumps(payload).encode(), "127.0.0.1")

    assert replay_handler.responses[0][0] == 409
    replay_mock.assert_not_called()
    saved = load_history(session_id, limit=10)
    assert saved[-1]["metadata"]["action_proposal"]["proposal_status"] == "executed"


def test_execute_action_rejects_wrong_owner_and_mismatched_action(tmp_db):
    session, session_id, message_id, _proposal = _setup_pending_proposal(tmp_db)
    wrong_owner = DummyActionHandler({
        "id": 202,
        "name": "Mallory",
        "org": "other",
        "role": "admin",
    })
    payload = {
        "session_id": session_id,
        "message_id": message_id,
        "action_type": "create_task",
    }

    with patch("handlers.chat_handler.execute_tool") as execute_mock:
        handle_execute_action(wrong_owner, json.dumps(payload).encode(), "127.0.0.1")
    assert wrong_owner.responses[0][0] == 403
    execute_mock.assert_not_called()

    mismatch_handler = DummyActionHandler(session)
    payload["action_type"] = "update_status"
    with patch("handlers.chat_handler.execute_tool") as execute_mock:
        handle_execute_action(mismatch_handler, json.dumps(payload).encode(), "127.0.0.1")
    assert mismatch_handler.responses[0][0] == 409
    execute_mock.assert_not_called()


def test_failed_action_returns_proposal_to_pending_without_overwriting_task_status(tmp_db):
    proposal = {
        "action_type": "create_task",
        "proposal_status": "pending",
        "summary": "Trusted task title",
        "description": "Trusted task description",
        "status": "진행중",
        "priority": "보통",
    }
    session, session_id, message_id, _proposal = _setup_pending_proposal(tmp_db, proposal)
    handler = DummyActionHandler(session)
    payload = {
        "session_id": session_id,
        "message_id": message_id,
        "action_type": "create_task",
    }

    with patch(
        "handlers.chat_handler.execute_tool",
        return_value={"success": False, "error": "validation failed"},
    ):
        handle_execute_action(handler, json.dumps(payload).encode(), "127.0.0.1")

    assert handler.responses[0][0] == 400
    saved = load_history(session_id, limit=10)
    stored = saved[-1]["metadata"]["action_proposal"]
    assert stored["proposal_status"] == "pending"
    assert stored["status"] == "진행중"
