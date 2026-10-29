import json
from unittest.mock import MagicMock, patch
import pytest
from db import execute, query
from handlers.auth_handlers import handle_account_login
from services.auth import create_user, hash_password

class MockLoginHandler:
    def __init__(self, secure=False):
        self.secure = secure
        self.status = None
        self.data = None
        self.extra_headers = []

    def _is_secure(self):
        return self.secure

    def _make_auth_cookie_header(self, token):
        return ("Set-Cookie", f"argos_token={token}; Path=/")

    def _send_json(self, status, data, extra_headers=None):
        self.status = status
        self.data = data
        self.extra_headers = extra_headers or []


def test_login_timing_defense_and_three_tier_lockout(tmp_db, monkeypatch):
    execute("INSERT OR IGNORE INTO departments(id, name) VALUES ('dev', 'Development')")
    salt, hpwd = hash_password("ValidPassword123!")
    create_user("AliceUser", "alice_test", "dev", "alice@example.com", salt, hpwd, status="active", role="member")

    # 1. Non-existent user: dummy hash MUST be computed to defend against timing attacks
    with patch("services.auth.hash_password", wraps=hash_password) as mock_hash:
        handler = MockLoginHandler()
        payload_nonexistent = json.dumps({"username": "ghost_user", "password": "AnyPassword123!"}).encode()
        handle_account_login(handler, payload_nonexistent, "192.168.1.100")
        assert handler.status == 401
        assert mock_hash.called, "Dummy hash was not computed for non-existent user!"

    # 2. Tier 1 Lockout: 5 failed attempts from same IP on same account -> 6th attempt gets 429 + Retry-After
    ip1 = "192.168.1.10"
    wrong_payload = json.dumps({"username": "alice_test", "password": "WrongPassword!"}).encode()
    for i in range(5):
        h = MockLoginHandler()
        handle_account_login(h, wrong_payload, ip1)
        assert h.status == 401

    # 6th attempt from ip1: MUST get 429 and Retry-After header
    h_locked = MockLoginHandler()
    handle_account_login(h_locked, wrong_payload, ip1)
    assert h_locked.status == 429
    retry_afters = [val for header, val in h_locked.extra_headers if header.lower() == "retry-after"]
    assert len(retry_afters) == 1, "Missing Retry-After header on 429 response"
    assert int(retry_afters[0]) > 0

    # 3. Different IP (ip2) for the same user is NOT locked by Tier 1 (5 attempts) since account total is < 20
    ip2 = "192.168.1.20"
    correct_payload = json.dumps({"username": "alice_test", "password": "ValidPassword123!"}).encode()
    h_other_ip = MockLoginHandler()
    handle_account_login(h_other_ip, correct_payload, ip2)
    assert h_other_ip.status == 200, f"Expected 200 for ip2 but got {h_other_ip.status}: {h_other_ip.data}"
