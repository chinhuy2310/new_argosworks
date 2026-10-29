import json
from unittest.mock import MagicMock, patch
import pytest

class DummyHandler:
    def __init__(self, session=None, cfg=None):
        self.session = session or {}
        self.cfg = cfg or {}
        self.responses = []

    def _get_session_or_401(self):
        return self.session

    def _send_json(self, status, data, **kwargs):
        self.responses.append((status, data))


def test_handle_post_vector_sync_has_time_and_rate_limits():
    from router import handle_post_vector_sync, _vector_sync_rate_limits, _vector_sync_rate_lock
    
    handler = DummyHandler(session={"id": 999, "name": "mgr", "role": "manager"})
    ip = "192.168.1.50"
    user_key = f"999:{ip}"
    with _vector_sync_rate_lock:
        _vector_sync_rate_limits.pop(user_key, None)

    with patch("router.check_vector_sync_status", return_value={"ok": True, "total": 10}):
        # First call: should succeed (200), not throw NameError
        handle_post_vector_sync(handler, json.dumps({"check_only": True}).encode(), ip)
        assert len(handler.responses) == 1
        assert handler.responses[0][0] == 200

        # Second call immediately after: should be rate-limited (429)
        handle_post_vector_sync(handler, json.dumps({"check_only": True}).encode(), ip)
        assert len(handler.responses) == 2
        assert handler.responses[1][0] == 429
        assert "너무 빈번합니다" in handler.responses[1][1]["error"]


def test_delete_record_attachment_removes_file_and_protects_traversal(tmp_path, monkeypatch, tmp_db):
    import os
    from services.data_store import delete_record_attachment
    from db import execute, query
    import config

    attach_root = tmp_path / "attach"
    monkeypatch.setattr(config, "ATTACH_DIR", str(attach_root))
    rec_dir = attach_root / "101"
    rec_dir.mkdir(parents=True)

    test_file = rec_dir / "valid_file.txt"
    test_file.write_text("sample content")

    execute("INSERT OR IGNORE INTO departments(id, name) VALUES ('dev', 'Development')")
    execute("INSERT INTO records(id, dept_id, category, title, assignee_name) VALUES (101, 'dev', 'cat', 'test', 'tester')")
    execute("INSERT INTO record_attachments(id, record_id, filename) VALUES (1, 101, 'valid_file.txt')")

    # Call delete_record_attachment - should succeed, remove row from DB and file from disk
    ok, err = delete_record_attachment(101, 1)
    assert ok is True
    assert err is None
    assert not test_file.exists()
    assert len(query("SELECT * FROM record_attachments WHERE id = 1")) == 0

    # Path traversal safety test: filename with ../ should not delete outside file
    outside_file = attach_root / "outside.txt"
    outside_file.write_text("critical outside data")
    execute("INSERT INTO record_attachments(id, record_id, filename) VALUES (2, 101, '../outside.txt')")

    ok, err = delete_record_attachment(101, 2)
    assert ok is True
    assert outside_file.exists()  # MUST NOT be removed
    assert len(query("SELECT * FROM record_attachments WHERE id = 2")) == 0


def test_chat_stream_records_ai_usage_without_nameerror(tmp_db, monkeypatch):
    from handlers.chat_handler import handle_chat_stream
    from db import query

    class MockChatHandler:
        def __init__(self):
            self.session = {"id": 1, "name": "alice", "org": "dev", "role": "member", "email": "alice@test.com"}
            self.cfg = {"ai": {"provider": "gemini", "model": "gemini-1.5-flash"}}
            self.events = []
            self.wfile = MagicMock()

        def _get_session_or_401(self):
            return self.session

        def _send_sse_headers(self):
            pass

        def _start_sse(self):
            pass

        def _end_sse(self):
            pass

        def _send_sse_event(self, data):
            self.events.append(data)
            return True

    handler = MockChatHandler()
    payload = json.dumps({"message": "Tell me a joke", "sessionId": ""}).encode()

    with patch("handlers.chat_handler.run_agent_conversation", return_value="Why did the chicken cross the road?"):
        handle_chat_stream(handler, payload, "127.0.0.1")

    # In the bugged state, NameError on user_msg is swallowed by except: pass, so ai_usage table is EMPTY!
    rows = query("SELECT * FROM ai_usage")
    assert len(rows) == 1, "Expected ai_usage to record 1 row for chat completion"
    assert rows[0]["total_tokens"] > 0
    assert rows[0]["user_name"] == "alice"
