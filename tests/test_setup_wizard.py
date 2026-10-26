# -*- coding: utf-8 -*-
import unittest
import json
import os
import sys

# Add server directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from db import init_db, execute, get_one, query
from handlers.setup_handler import (
    check_needs_setup, handle_get_setup_status,
    handle_post_setup_verify_license, handle_post_setup_complete
)
from handlers.auth_handlers import handle_account_login
from services.license_manager import generate_signed_license_key, invalidate_license_cache


def _make_test_keypair():
    """Throw-away Ed25519 key pair: the product ships no private key."""
    from cryptography.hazmat.primitives.asymmetric import ed25519
    from cryptography.hazmat.primitives import serialization
    private_key = ed25519.Ed25519PrivateKey.generate()
    priv_hex = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    ).hex()
    pub_hex = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()
    return priv_hex, pub_hex



class MockHTTPHandler:
    def __init__(self, session=None):
        self.session = session
        self.status_code = None
        self.response_body = None
        self.headers_sent = {}
        self.extra_headers = []
        self.cfg = {}

    def _get_session_or_401(self):
        if not self.session:
            self._send_json(401, {"ok": False, "error": "Unauthorized"})
            return None
        return self.session

    def _send_json(self, status, data, extra_headers=None):
        self.status_code = status
        self.response_body = data
        self.extra_headers = extra_headers or []

    def send_response(self, code):
        self.status_code = code

    def send_header(self, k, v):
        self.headers_sent[k] = v

    def end_headers(self):
        pass

    def _make_auth_cookie_header(self, token):
        return ("Set-Cookie", f"session_token={token}; Path=/")


class TestEnterpriseSetupWizard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        cls._priv_hex, cls._pub_hex = _make_test_keypair()
        cls._prev_pub = os.environ.get("ARGOS_LICENSE_PUBLIC_KEY")
        os.environ["ARGOS_LICENSE_PUBLIC_KEY"] = cls._pub_hex
        invalidate_license_cache()

    @classmethod
    def tearDownClass(cls):
        if cls._prev_pub is None:
            os.environ.pop("ARGOS_LICENSE_PUBLIC_KEY", None)
        else:
            os.environ["ARGOS_LICENSE_PUBLIC_KEY"] = cls._prev_pub
        invalidate_license_cache()

    def _sign(self, customer, seats, expiry, modules):
        return generate_signed_license_key(
            customer, seats, expiry, modules, signing_key_hex=self._priv_hex
        )

    def setUp(self):
        from handlers.setup_handler import reset_setup_cache
        reset_setup_cache()
        # Backup and clear users table for setup test
        self.original_users = query("SELECT * FROM users")
        self.original_sessions = query("SELECT * FROM sessions")
        self.original_license = get_one("SELECT * FROM license_info WHERE id = 1")
        execute("DELETE FROM sessions")
        execute("DELETE FROM users")

    def tearDown(self):
        from handlers.setup_handler import reset_setup_cache
        reset_setup_cache()
        # Restore database
        execute("DELETE FROM sessions")
        execute("DELETE FROM users")
        for u in self.original_users:
            execute("""
                INSERT OR REPLACE INTO users (id, username, name, dept_id, email, salt, password_hash, is_admin, role, disabled, status, iterations, hash_algo, avatar_url, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (u["id"], u.get("username", u["name"]), u["name"], u["dept_id"], u["email"],
                  u["salt"], u["password_hash"], u["is_admin"], u.get("role", "member"),
                  u.get("disabled", 0), u.get("status", "active"), u.get("iterations", 100000),
                  u.get("hash_algo", "pbkdf2_sha256"), u.get("avatar_url", ""), u["created_at"]))
        # The setup flow activates a license signed with the test key pair; put the
        # original (real) license row back so later tests are not affected.
        if self.original_license:
            execute("""
                INSERT OR REPLACE INTO license_info
                    (id, customer_name, license_key, max_seats, expiry_date, modules_json, is_active, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                self.original_license.get("id", 1),
                self.original_license.get("customer_name", ""),
                self.original_license.get("license_key", ""),
                self.original_license.get("max_seats", 0),
                self.original_license.get("expiry_date", "1970-01-01"),
                self.original_license.get("modules_json", "[]"),
                self.original_license.get("is_active", 0),
                self.original_license.get("updated_at", ""),
            ))
        invalidate_license_cache()

    def test_setup_status_when_no_users(self):
        self.assertTrue(check_needs_setup())
        handler = MockHTTPHandler()
        handle_get_setup_status(handler, None, "127.0.0.1")
        self.assertEqual(handler.status_code, 200)
        self.assertTrue(handler.response_body.get("ok"))
        self.assertTrue(handler.response_body.get("needs_setup"))
        self.assertGreater(len(handler.response_body.get("default_departments", [])), 0)

    def test_verify_license_trial_and_signed(self):
        handler = MockHTTPHandler()

        # 1. Invalid key
        handle_post_setup_verify_license(handler, json.dumps({"license_key": "INVALID-KEY"}).encode(), "127.0.0.1")
        self.assertEqual(handler.status_code, 400)
        self.assertFalse(handler.response_body.get("ok"))

        # 2. Trial key (Ed25519 signed)
        trial_key = self._sign("Enterprise Trial", 25, "2099-12-31", ["canvas", "rag"])
        handle_post_setup_verify_license(handler, json.dumps({"license_key": trial_key}).encode(), "127.0.0.1")
        self.assertEqual(handler.status_code, 200)
        self.assertTrue(handler.response_body.get("ok"))
        self.assertEqual(handler.response_body["license"]["seats"], 25)

        # 3. Valid Signed Ed25519 key
        signed_key = self._sign("Acme Enterprise", 100, "2030-12-31", ["canvas", "rag"])
        handle_post_setup_verify_license(handler, json.dumps({"license_key": signed_key}).encode(), "127.0.0.1")
        self.assertEqual(handler.status_code, 200)
        self.assertTrue(handler.response_body.get("ok"))
        self.assertEqual(handler.response_body["license"]["customer"], "Acme Enterprise")
        self.assertEqual(handler.response_body["license"]["seats"], 100)

    def test_complete_setup_flow(self):
        self.assertTrue(check_needs_setup())

        # Complete setup
        handler = MockHTTPHandler()
        trial_key = self._sign("Enterprise Trial", 25, "2099-12-31", ["canvas", "rag"])
        setup_payload = {
            "license_key": trial_key,
            "company_name": "Test Acme Corp",
            "admin": {
                "username": "superadmin",
                "name": "Master Administrator",
                "email": "master@acme.com",
                "password": "SuperSecretPassword123!"
            },
            "admin_dept_id": "mgmt",
            "departments": [
                {"id": "mgmt", "name": "경영기획팀 (Management)", "prefix": "MGMT", "color_index": 4},
                {"id": "dev", "name": "연구개발팀 (R&D)", "prefix": "DEV", "color_index": 1}
            ]
        }

        handle_post_setup_complete(handler, json.dumps(setup_payload).encode(), "127.0.0.1")
        self.assertEqual(handler.status_code, 200)
        self.assertTrue(handler.response_body.get("ok"))
        self.assertIsNotNone(handler.response_body.get("token"))

        # Setup should now be marked complete
        self.assertFalse(check_needs_setup())

        # Master Admin should exist in DB with active admin role
        admin_row = get_one("SELECT * FROM users WHERE username = 'superadmin'")
        self.assertIsNotNone(admin_row)
        self.assertEqual(admin_row["role"], "admin")
        self.assertEqual(admin_row["is_admin"], 1)
        self.assertEqual(admin_row["status"], "active")
        self.assertEqual(admin_row["disabled"], 0)

        # Re-running setup must be blocked
        handler_repeat = MockHTTPHandler()
        handle_post_setup_complete(handler_repeat, json.dumps(setup_payload).encode(), "127.0.0.1")
        self.assertEqual(handler_repeat.status_code, 403)

        # Newly created Master Admin can log in successfully
        login_handler = MockHTTPHandler()
        login_payload = json.dumps({
            "username": "superadmin",
            "password": "SuperSecretPassword123!"
        }).encode()
        handle_account_login(login_handler, login_payload, "127.0.0.1")
        self.assertEqual(login_handler.status_code, 200)
        self.assertTrue(login_handler.response_body.get("ok"))


if __name__ == "__main__":
    unittest.main()
