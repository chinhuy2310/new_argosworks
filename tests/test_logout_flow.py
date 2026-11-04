"""
Regression tests for the logout endpoint (P0).

Background: `match_post()` returned `handle_account_logout` only as unreachable
code after `return handle_account_login`, so POST /api/account/logout (and
/api/auth/logout) fell through to the 404 branch. The frontend treated that as a
success, the HttpOnly session cookie could not be cleared from JavaScript, and
the session stayed valid for its full TTL (24h by default).

These tests pin both the routing contract and the handler's side effects.
"""
import os
import sys
import unittest
from unittest.mock import patch

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_DIR = os.path.join(BASE_DIR, "server")
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from router import match_get, match_post  # noqa: E402
from handlers import auth_handlers  # noqa: E402
from handler import PUBLIC_API_WHITELIST  # noqa: E402

LOGOUT_PATHS = ("/api/account/logout", "/api/auth/logout")
LOGOUT_ALL_PATHS = ("/api/account/logout-all", "/api/auth/logout-all")


class FakeHandler:
    """Minimal stand-in for ArgosHandler covering what the logout handler needs."""

    def __init__(self, session=None, token="session-token-abc"):
        self.session = session
        self.token = token
        self.status = None
        self.payload = None
        self.extra_headers = []

    def _get_session_optional(self):
        return self.session

    def _extract_token(self):
        return self.token

    def _make_logout_cookie_header(self):
        return ("Set-Cookie", "argos_token=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0")

    def _send_json(self, status, payload, extra_headers=None):
        self.status = status
        self.payload = payload
        self.extra_headers = extra_headers or []


class TestLogoutRouting(unittest.TestCase):
    def test_post_logout_is_registered_for_both_aliases(self):
        for path in LOGOUT_PATHS:
            with self.subTest(path=path):
                self.assertIs(match_post(path), auth_handlers.handle_account_logout)

    def test_post_logout_all_is_registered_for_both_aliases(self):
        for path in LOGOUT_ALL_PATHS:
            with self.subTest(path=path):
                self.assertIs(match_post(path), auth_handlers.handle_account_logout_all)

    def test_get_logout_remains_unrouted(self):
        """Logout must stay POST-only so a link/std<img> cannot end the session (CSRF)."""
        for path in LOGOUT_PATHS:
            with self.subTest(path=path):
                self.assertEqual(match_get(path)[0], "notfound")

    def test_logout_all_not_in_public_whitelist_to_enforce_csrf(self):
        """Logout-all mutates all sessions and must NOT be in PUBLIC_API_WHITELIST so it requires CSRF."""
        for path in LOGOUT_ALL_PATHS:
            with self.subTest(path=path):
                self.assertNotIn(path, PUBLIC_API_WHITELIST)

    def test_every_whitelisted_endpoint_is_routed(self):
        """A path listed in PUBLIC_API_WHITELIST that no router branch handles is a 404."""
        unrouted = [
            path
            for path in sorted(PUBLIC_API_WHITELIST)
            if match_get(path)[0] == "notfound" and match_post(path) is None
        ]
        self.assertEqual(unrouted, [], f"whitelisted but never routed: {unrouted}")


class TestLogoutHandlerBehaviour(unittest.TestCase):
    def test_logout_deletes_server_side_session_and_clears_cookie(self):
        handler = FakeHandler(session={"name": "alice", "role": "admin"})
        with patch("services.auth.delete_session") as delete_session, \
                patch("services.audit_logger.log_audit") as log_audit:
            auth_handlers.handle_account_logout(handler, b"{}", "203.0.113.7")

        delete_session.assert_called_once_with("session-token-abc")
        log_audit.assert_called_once()
        self.assertEqual(log_audit.call_args.kwargs.get("action"), "LOGOUT")
        self.assertEqual(handler.status, 200)
        self.assertEqual(handler.payload, {"ok": True})
        self.assertTrue(handler.extra_headers, "logout must send a Set-Cookie header")
        header_name, header_value = handler.extra_headers[0]
        self.assertEqual(header_name, "Set-Cookie")
        self.assertIn("argos_token=", header_value)
        self.assertIn("Max-Age=0", header_value)

    def test_logout_without_session_still_clears_cookie(self):
        """Expired/absent session must not turn logout into a 401 loop for the client."""
        handler = FakeHandler(session=None, token=None)
        with patch("services.auth.delete_session") as delete_session, \
                patch("services.audit_logger.log_audit") as log_audit:
            auth_handlers.handle_account_logout(handler, b"{}", "203.0.113.7")

        delete_session.assert_not_called()
        log_audit.assert_not_called()
        self.assertEqual(handler.status, 200)
        self.assertEqual(handler.extra_headers[0][0], "Set-Cookie")

    def test_logout_survives_session_store_failure(self):
        """A failing session store must not block cookie clearing."""
        handler = FakeHandler(session={"name": "alice"})
        with patch("services.auth.delete_session", side_effect=RuntimeError("db down")), \
                patch("services.audit_logger.log_audit"):
            auth_handlers.handle_account_logout(handler, b"{}", "203.0.113.7")

        self.assertEqual(handler.status, 200)
        self.assertIn("Max-Age=0", handler.extra_headers[0][1])


if __name__ == "__main__":
    unittest.main()
