import io
import json
import pytest
from handler import ArgosHandler, PUBLIC_BODY_LIMIT, SETUP_BODY_LIMIT

class ExplodingRfile:
    """Stream that raises an assertion error if read() is called."""
    def read(self, *args, **kwargs):
        raise AssertionError("rfile.read() MUST NOT be called when Content-Length exceeds limit!")


class DummyResponseHandler(ArgosHandler):
    """Subclass for testing request dispatch without live network sockets."""
    def __init__(self, method="POST", path="/api/account/login", headers=None, rfile=None):
        self.command = method
        self.path = path
        self.headers = headers or {}
        self.rfile = rfile or io.BytesIO()
        self.client_address = ("127.0.0.1", 12345)
        self.status = None
        self.sent_headers = {}
        self.response_body = None
        self.cfg = {"max_upload_mb": 25}

    def _extract_client_ip(self):
        return "127.0.0.1"

    def _send_json(self, status, payload, extra_headers=None):
        self.status = status
        self.response_body = payload

    def send_response(self, code, message=None):
        self.status = code

    def send_header(self, keyword, value):
        self.sent_headers[keyword] = value

    def end_headers(self):
        pass


def test_public_endpoint_oversized_body_rejected_without_reading_rfile():
    """Unauthenticated endpoint rejects oversized body with 413 without reading stream."""
    h = DummyResponseHandler(
        method="POST",
        path="/api/account/login",
        headers={"Content-Length": "20000000"},  # 20 MB
        rfile=ExplodingRfile()  # will blow up if read is attempted
    )
    h.do_POST()
    assert h.status == 413
    assert "제한을 초과했습니다" in h.response_body.get("error", "")


def test_public_endpoint_normal_body_allowed():
    """Unauthenticated endpoint allows body <= 16KB."""
    body_bytes = json.dumps({"username": "testuser", "password": "pass"}).encode("utf-8")
    h = DummyResponseHandler(
        method="POST",
        path="/api/account/login",
        headers={"Content-Length": str(len(body_bytes))},
        rfile=io.BytesIO(body_bytes)
    )
    h.do_POST()
    # Should reach handler function and return 401 or similar, NOT 413
    assert h.status != 413


def test_setup_endpoint_allows_up_to_1mb():
    """Setup endpoints allow up to 1 MB."""
    # 500 KB on /api/setup/complete -> not 413
    h1 = DummyResponseHandler(
        method="POST",
        path="/api/setup/complete",
        headers={"Content-Length": str(500 * 1024)},
        rfile=io.BytesIO(b"x" * (500 * 1024))
    )
    h1.do_POST()
    assert h1.status != 413

    # 2 MB on /api/setup/complete -> 413 without reading rfile
    h2 = DummyResponseHandler(
        method="POST",
        path="/api/setup/complete",
        headers={"Content-Length": str(2 * 1024 * 1024)},
        rfile=ExplodingRfile()
    )
    h2.do_POST()
    assert h2.status == 413


def test_session_cache_reset_between_requests(monkeypatch):
    """Verify self._current_session is reset at the start of each request verb (7.6)."""
    h = DummyResponseHandler(
        method="GET",
        path="/api/account/me",
        headers={}
    )
    # Simulate lingering session from previous keep-alive request
    h._current_session = {"name": "alice", "id": 1, "role": "admin"}

    # Next request arrives with NO cookie/token
    h.do_GET()

    # Must be 401 unauthenticated because _current_session was cleared, not reused
    assert h.status == 401
    assert h._current_session is None
