import os
import sys
import unittest
from datetime import date, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_DIR = os.path.join(BASE_DIR, "server")
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from db import init_db
from services import license_manager
from services.license_manager import (
    generate_signed_license_key,
    verify_license_key,
    activate_license,
    get_license_status,
    check_seat_available,
    is_system_read_only,
    invalidate_license_cache,
)

from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization


class TestLicenseManager(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Isolate: never mutate the developer's real data/argos.db license row.
        import db as db_module
        import shutil
        import tempfile
        import threading

        cls._tmpdir = tempfile.mkdtemp(prefix="argos_license_test_")
        cls._db_path = os.path.join(cls._tmpdir, "license.sqlite")
        cls._orig_get_db_path = getattr(db_module, "get_db_path", None)

        if cls._orig_get_db_path is not None:
            db_module.get_db_path = lambda: cls._db_path
        if hasattr(db_module, "_tls"):
            db_module._tls = threading.local()

        init_db()

        # The product ships only a public key; tests generate their own throwaway
        # key pair so no signing key is ever required in the source tree.
        cls._private_key = ed25519.Ed25519PrivateKey.generate()
        cls._private_hex = cls._private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        ).hex()
        cls._public_hex = cls._private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        ).hex()

        cls._prev_env = {
            "ARGOS_LICENSE_SIGNING_KEY": os.environ.get("ARGOS_LICENSE_SIGNING_KEY"),
            "ARGOS_LICENSE_PUBLIC_KEY": os.environ.get("ARGOS_LICENSE_PUBLIC_KEY"),
        }
        os.environ["ARGOS_LICENSE_SIGNING_KEY"] = cls._private_hex
        os.environ["ARGOS_LICENSE_PUBLIC_KEY"] = cls._public_hex
        invalidate_license_cache()

    @classmethod
    def tearDownClass(cls):
        import db as db_module
        import shutil
        import threading

        for key, value in cls._prev_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        invalidate_license_cache()

        if cls._orig_get_db_path is not None:
            db_module.get_db_path = cls._orig_get_db_path
        if hasattr(db_module, "_tls"):
            db_module._tls = threading.local()
        shutil.rmtree(cls._tmpdir, ignore_errors=True)

    def setUp(self):
        invalidate_license_cache()

    def tearDown(self):
        invalidate_license_cache()

    def test_signed_license_key_generation_and_verification(self):
        exp = (date.today() + timedelta(days=365)).strftime("%Y-%m-%d")
        key = generate_signed_license_key(
            customer_name="Test Enterprise Inc.",
            max_seats=50,
            expiry_date_str=exp,
            modules=["canvas", "jira", "rag"]
        )
        self.assertTrue(key.startswith("AGY-"))
        self.assertIn(".", key)

        # Verify valid key
        ok, msg, data = verify_license_key(key)
        self.assertTrue(ok, msg)
        self.assertEqual(data["customer"], "Test Enterprise Inc.")
        self.assertEqual(data["seats"], 50)
        self.assertEqual(data["expiry"], exp)
        self.assertIn("canvas", data["modules"])

    def test_tampered_license_key_rejection(self):
        exp = (date.today() + timedelta(days=365)).strftime("%Y-%m-%d")
        key = generate_signed_license_key(
            customer_name="Test Enterprise Inc.",
            max_seats=50,
            expiry_date_str=exp,
            modules=["canvas"]
        )
        # Tamper payload
        parts = key.split(".")
        tampered = parts[0][:-2] + "AA." + parts[1]
        ok, msg, data = verify_license_key(tampered)
        self.assertFalse(ok)

    def test_expired_license_key_rejection(self):
        expired_date = "2020-01-01"
        key = generate_signed_license_key(
            customer_name="Expired Org",
            max_seats=10,
            expiry_date_str=expired_date,
            modules=["canvas"]
        )
        ok, msg, data = verify_license_key(key)
        self.assertFalse(ok)
        self.assertIn("만료", msg)

    def test_activate_license_and_status(self):
        exp = (date.today() + timedelta(days=100)).strftime("%Y-%m-%d")
        key = generate_signed_license_key(
            customer_name="Active Corp",
            max_seats=15,
            expiry_date_str=exp,
            modules=["canvas", "jira", "pim"]
        )
        ok, msg = activate_license(key)
        self.assertTrue(ok, msg)

        status = get_license_status()
        self.assertEqual(status["customer_name"], "Active Corp")
        self.assertEqual(status["max_seats"], 15)
        self.assertFalse(status["is_expired"])
        self.assertFalse(status["is_read_only"])
        self.assertFalse(is_system_read_only())

if __name__ == "__main__":
    unittest.main()
