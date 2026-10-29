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
