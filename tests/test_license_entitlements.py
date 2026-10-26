"""
test_license_entitlements.py — Commercial license hardening & module entitlements.

Covers the commercial blockers:
  1. No signing key may be embedded in the product (vendor-only signing).
  2. A license row written directly into the DB (unsigned / tampered) is NOT trusted.
  3. Editing license_info cannot inflate seats/expiry (payload is authoritative).
  4. Module entitlement gates (PIM/Jira/RAG/Schedule/Audit) actually block APIs.
  5. Expiring licence surfaces a warning; expired licence is refused.
"""
import os
import sys
from datetime import date, timedelta

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_DIR = os.path.join(BASE_DIR, "server")
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from cryptography.hazmat.primitives.asymmetric import ed25519  # noqa: E402
from cryptography.hazmat.primitives import serialization  # noqa: E402

from services.license_manager import (  # noqa: E402
    LicenseSigningKeyMissing,
    activate_license,
    generate_signed_license_key,
    get_license_status,
    has_module,
    invalidate_license_cache,
)


def _keypair():
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


@pytest.fixture
def vendor_keys(tmp_db, monkeypatch):
    """Trust exactly one throw-away public key for the duration of a test."""
    priv_hex, pub_hex = _keypair()
    monkeypatch.setenv("ARGOS_LICENSE_SIGNING_KEY", priv_hex)
    monkeypatch.setenv("ARGOS_LICENSE_PUBLIC_KEY", pub_hex)
    invalidate_license_cache()
    yield {"private": priv_hex, "public": pub_hex}
    invalidate_license_cache()


def _issue(priv_hex, seats=10, days=365, modules=("canvas", "pim")):
    expiry = (date.today() + timedelta(days=days)).strftime("%Y-%m-%d")
    return generate_signed_license_key(
        customer_name="Entitlement Test Corp",
        max_seats=seats,
        expiry_date_str=expiry,
        modules=list(modules),
        signing_key_hex=priv_hex,
    )


# ---------------------------------------------------------------------------
# 1. Vendor-only signing key
# ---------------------------------------------------------------------------
class TestSigningKeyNeverShipped:
    def test_signing_without_key_raises(self, tmp_db, monkeypatch):
        monkeypatch.delenv("ARGOS_LICENSE_SIGNING_KEY", raising=False)
        with pytest.raises(LicenseSigningKeyMissing):
            generate_signed_license_key("No Key Corp", 5, "2030-01-01", ["canvas"])

    def test_source_has_no_private_key_constant(self):
        source_path = os.path.join(SERVER_DIR, "services", "license_manager.py")
        with open(source_path, "r", encoding="utf-8") as f:
            source = f.read()
        assert "79177ec5e385a059f4851cf8701b73f09111a25bc365046afb1d7fcfc42753a0" not in source


# ---------------------------------------------------------------------------
# 2. Database rows are not trusted unless signed
# ---------------------------------------------------------------------------
class TestUnsignedDatabaseRowRejected:
    def test_unsigned_seed_row_is_unlicensed(self, tmp_db, vendor_keys, monkeypatch):
        tmp_db.execute(
            """INSERT OR REPLACE INTO license_info (id, customer_name, license_key, max_seats, expiry_date, modules_json, is_active)
               VALUES (1, 'Free Rider Ltd', 'ARGOS-FAKE-2099', 999, '2099-12-31',
                       '["canvas","pim","jira","rag","schedule","audit"]', 1)"""
        )
        invalidate_license_cache()
        status = get_license_status()
        assert status["license_valid"] is False
        assert status["is_active"] is False
        assert status["is_read_only"] is True
        assert status["max_seats"] == 0
        assert status["modules"] == []

    def test_signed_key_activates(self, tmp_db, vendor_keys):
        ok, msg = activate_license(_issue(vendor_keys["private"], seats=12))
        assert ok, msg
        status = get_license_status()
        assert status["license_valid"] is True
        assert status["is_active"] is True
        assert status["max_seats"] == 12


# ---------------------------------------------------------------------------
# 3. Payload is authoritative (DB tampering cannot inflate the contract)
# ---------------------------------------------------------------------------
class TestDatabaseTamperingCannotInflateContract:
    def test_tampered_max_seats_ignored(self, tmp_db, vendor_keys):
        ok, msg = activate_license(_issue(vendor_keys["private"], seats=3))
        assert ok, msg

        tmp_db.execute("UPDATE license_info SET max_seats = 5000 WHERE id = 1")
        invalidate_license_cache()

        status = get_license_status()
        assert status["max_seats"] == 3, "seats must come from the signed payload"

    def test_tampered_expiry_ignored(self, tmp_db, vendor_keys):
        ok, msg = activate_license(_issue(vendor_keys["private"], days=1))
        assert ok, msg

        tmp_db.execute("UPDATE license_info SET expiry_date = '2099-12-31' WHERE id = 1")
        invalidate_license_cache()

        status = get_license_status()
        assert status["expiry_date"] != "2099-12-31"


# ---------------------------------------------------------------------------
# 4. Module entitlements
# ---------------------------------------------------------------------------
class TestModuleEntitlements:
    def test_licensed_modules_only(self, tmp_db, vendor_keys):
        ok, msg = activate_license(_issue(vendor_keys["private"], modules=("canvas", "pim")))
        assert ok, msg
        invalidate_license_cache()

        assert has_module("canvas") is True
        assert has_module("pim") is True
        assert has_module("jira") is False
        assert has_module("rag") is False
        assert has_module("audit") is False

    def test_module_gate_blocks_unlicensed_paths(self, tmp_db, vendor_keys):
        from module_gate import check_module_access, required_module

        ok, msg = activate_license(_issue(vendor_keys["private"], modules=("canvas", "pim")))
        assert ok, msg
        invalidate_license_cache()

        allowed, module = check_module_access("/api/products")
        assert (allowed, module) == (True, "pim")

        for path, expected in (
            ("/api/jira/search", "jira"),
            ("/api/issues", "jira"),
            ("/api/chat/send", "rag"),
            ("/api/vectors/stats", "rag"),
            ("/api/admin/audit-logs", "audit"),
        ):
            allowed, module = check_module_access(path)
            assert module == expected
            assert allowed is False, f"{path} must be blocked without the {expected} module"

        # Licensing / identity endpoints stay reachable so an admin can re-activate
        assert check_module_access("/api/admin/license") == (True, None)
        assert check_module_access("/api/account/me") == (True, None)
        assert required_module("/api/records") is None

    def test_wildcard_license_covers_all_modules(self, tmp_db, vendor_keys):
        ok, msg = activate_license(_issue(vendor_keys["private"], modules=("*",)))
        assert ok, msg
        invalidate_license_cache()
        assert has_module("jira") is True
        assert has_module("rag") is True


# ---------------------------------------------------------------------------
# 5. Expiry handling
# ---------------------------------------------------------------------------
class TestExpiryHandling:
    def test_expired_key_is_rejected(self, tmp_db, vendor_keys):
        ok, msg = activate_license(_issue(vendor_keys["private"], days=-1))
        assert ok is False
        assert "만료" in msg

    def test_status_flags_expiring_soon(self, tmp_db, vendor_keys):
        ok, msg = activate_license(_issue(vendor_keys["private"], days=10))
        assert ok, msg
        status = get_license_status()
        assert status["is_active"] is True
        assert status["expiry_warning"] is True
        assert 0 < status["days_left"] <= 30

