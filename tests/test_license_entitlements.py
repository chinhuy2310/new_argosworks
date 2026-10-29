"""
test_license_entitlements.py — Commercial license hardening & module entitlements.

Covers the commercial blockers:
  1. No signing key may be embedded in the product (vendor-only signing).
  2. A license row written directly into the DB (unsigned / tampered) is NOT trusted.
  3. Editing license_info cannot inflate seats/expiry (payload is authoritative).
  4. Module entitlement gates (PIM/Jira/RAG/Schedule/Audit) actually block APIs.
  5. Expiring licence surfaces a warning; expired licence is refused.
"""
import base64
import json
import os
import sys
import time
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
    verify_license_key,
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


def _trial_payload(term_days=60, iat_days_ago=0, hard_days=365, seats=50,
                   modules=("canvas",), customer="Argos Trial Corp"):
    today = date.today()
    payload = {
        "customer": customer,
        "seats": seats,
        "modules": list(modules),
        "iat": (today - timedelta(days=iat_days_ago)).strftime("%Y-%m-%d"),
        "trial": True,
        "term_days": term_days,
    }
    # hard_days=None issues a pure term trial with no absolute cap.
    if hard_days is not None:
        payload["expiry"] = (today + timedelta(days=hard_days)).strftime("%Y-%m-%d")
    return payload


def _sign_payload(priv_hex, payload):
    private_key = ed25519.Ed25519PrivateKey.from_private_bytes(bytes.fromhex(priv_hex))
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    sig = private_key.sign(raw)
    b64_payload = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    b64_sig = base64.urlsafe_b64encode(sig).decode("ascii").rstrip("=")
    return f"AGY-{b64_payload}.{b64_sig}"


class TestTrialTermAnchoredToActivation:
    """A trial licence lasts ``term_days`` from the FIRST activation, never longer."""

    def test_expiry_is_activation_plus_term(self, tmp_db, vendor_keys):
        key = _sign_payload(vendor_keys["private"], _trial_payload(term_days=60))
        ok, msg = activate_license(key)
        assert ok, msg

        status = get_license_status()
        expected = (date.today() + timedelta(days=60)).strftime("%Y-%m-%d")
        assert status["is_trial"] is True
        assert status["term_days"] == 60
        assert status["expiry_date"] == expected
        assert status["activated_at"] == date.today().strftime("%Y-%m-%d")
        assert status["days_left"] == 60
        assert status["is_read_only"] is False

    def test_reactivation_does_not_extend_the_term(self, tmp_db, vendor_keys):
        key = _sign_payload(vendor_keys["private"], _trial_payload(term_days=60, iat_days_ago=30))
        ok, msg = activate_license(key)
        assert ok, msg

        # Simulate that the customer activated 10 days ago (already anchored).
        ten_days_ago = (date.today() - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%S")
        tmp_db.execute("UPDATE license_info SET activated_at = ? WHERE id = 1", (ten_days_ago,))
        invalidate_license_cache()

        ok, msg = activate_license(key)
        assert ok, msg

        status = get_license_status()
        expected = (date.today() - timedelta(days=10) + timedelta(days=60)).strftime("%Y-%m-%d")
        assert status["expiry_date"] == expected
        assert status["days_left"] == 50, "re-activating the same key must not restart the clock"

    def test_future_anchor_is_clamped_to_issue_date(self, tmp_db, vendor_keys):
        key = _sign_payload(vendor_keys["private"], _trial_payload(iat_days_ago=30))
        ok, msg = activate_license(key)
        assert ok, msg

        future = (date.today() + timedelta(days=1000)).strftime("%Y-%m-%dT%H:%M:%S")
        tmp_db.execute("UPDATE license_info SET activated_at = ? WHERE id = 1", (future,))
        invalidate_license_cache()

        status = get_license_status()
        # Anchor falls back to the signed issue date (iat = 30 days ago) + 60 days.
        assert status["activated_at"] == (date.today() - timedelta(days=30)).strftime("%Y-%m-%d")
        assert status["expiry_date"] == (date.today() + timedelta(days=30)).strftime("%Y-%m-%d")


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


# ---------------------------------------------------------------------------
# 6. Trial-term guards (anchor tampering, hard cap, backward compatibility)
# ---------------------------------------------------------------------------
class TestTrialTermGuards:
    def test_anchor_cannot_precede_the_issue_date(self, tmp_db, vendor_keys):
        key = _sign_payload(vendor_keys["private"], _trial_payload(iat_days_ago=30))
        ok, msg = activate_license(key)
        assert ok, msg

        ancient = (date.today() - timedelta(days=3000)).strftime("%Y-%m-%dT%H:%M:%S")
        tmp_db.execute("UPDATE license_info SET activated_at = ? WHERE id = 1", (ancient,))
        invalidate_license_cache()

        status = get_license_status()
        assert status["expiry_date"] == (date.today() + timedelta(days=30)).strftime("%Y-%m-%d")

    def test_signed_hard_expiry_caps_the_trial(self, tmp_db, vendor_keys):
        key = _sign_payload(vendor_keys["private"], _trial_payload(term_days=60, hard_days=10))
        ok, msg = activate_license(key)
        assert ok, msg

        status = get_license_status()
        assert status["expiry_date"] == (date.today() + timedelta(days=10)).strftime("%Y-%m-%d")
        assert status["hard_expiry_date"] == status["expiry_date"]
        assert status["days_left"] == 10

    def test_expired_trial_is_read_only_and_cannot_be_reactivated(self, tmp_db, vendor_keys):
        key = _sign_payload(vendor_keys["private"], _trial_payload(term_days=60, iat_days_ago=90))
        ok, msg = activate_license(key)
        assert ok, msg

        expired_anchor = (date.today() - timedelta(days=61)).strftime("%Y-%m-%dT%H:%M:%S")
        tmp_db.execute("UPDATE license_info SET activated_at = ? WHERE id = 1", (expired_anchor,))
        invalidate_license_cache()

        status = get_license_status()
        assert status["is_expired"] is True
        assert status["is_read_only"] is True
        assert status["days_left"] == 0

        ok, msg = activate_license(key)
        assert ok is False
        assert "체험" in msg

    def test_commercial_licence_ignores_the_anchor(self, tmp_db, vendor_keys):
        ok, msg = activate_license(_issue(vendor_keys["private"], days=100))
        assert ok, msg

        tmp_db.execute("UPDATE license_info SET activated_at = '2000-01-01T00:00:00' WHERE id = 1")
        invalidate_license_cache()

        status = get_license_status()
        assert status["is_trial"] is False
        assert status["term_days"] == 0
        assert status["expiry_date"] == (date.today() + timedelta(days=100)).strftime("%Y-%m-%d")

    def test_legacy_trial_key_without_term_keeps_absolute_expiry(self, tmp_db, vendor_keys):
        expiry = (date.today() + timedelta(days=200)).strftime("%Y-%m-%d")
        key = generate_signed_license_key(
            customer_name="Legacy Trial Corp",
            max_seats=5,
            expiry_date_str=expiry,
            modules=["canvas"],
            signing_key_hex=vendor_keys["private"],
        )
        ok, msg = activate_license(key)
        assert ok, msg

        status = get_license_status()
        assert status["term_days"] == 0
        assert status["expiry_date"] == expiry

    def test_invalid_term_days_is_rejected_at_issuance(self, tmp_db, vendor_keys):
        with pytest.raises(ValueError):
            generate_signed_license_key(
                "Bad Term Corp", 5, "2030-01-01", ["canvas"],
                signing_key_hex=vendor_keys["private"],
                is_trial=True, term_days=0,
            )

    def test_signed_trial_without_term_is_rejected(self, tmp_db, vendor_keys):
        payload = _trial_payload()
        payload.pop("term_days")
        ok, msg, data = verify_license_key(_sign_payload(vendor_keys["private"], payload))
        assert ok is False
        assert "term_days" in msg


# ---------------------------------------------------------------------------
# 7. Term-only trials (no absolute hard cap) + clock-rollback protection
# ---------------------------------------------------------------------------
class TestTermOnlyTrialAndClockRollback:
    def test_trial_without_expiry_runs_term_from_activation(self, tmp_db, vendor_keys):
        key = _sign_payload(vendor_keys["private"], _trial_payload(term_days=60, hard_days=None))

        ok, msg, data = verify_license_key(key)
        assert ok, msg
        assert data["expiry"] == ""
        assert data["term_days"] == 60

        ok, msg = activate_license(key)
        assert ok, msg

        status = get_license_status()
        assert status["term_days"] == 60
        assert status["hard_expiry_date"] == ""
        assert status["expiry_date"] == (date.today() + timedelta(days=60)).strftime("%Y-%m-%d")
        assert status["days_left"] == 60

    def test_commercial_key_without_expiry_is_rejected(self, tmp_db, vendor_keys):
        payload = {
            "customer": "No Expiry Corp",
            "seats": 5,
            "modules": ["canvas"],
            "iat": date.today().strftime("%Y-%m-%d"),
        }
        ok, msg, data = verify_license_key(_sign_payload(vendor_keys["private"], payload))
        assert ok is False
        assert "만료일" in msg

    def test_clock_rollback_is_detected_and_clamped(self, tmp_db, vendor_keys):
        ok, msg = activate_license(
            _sign_payload(vendor_keys["private"], _trial_payload(term_days=60))
        )
        assert ok, msg

        # Simulate that this instance already observed "5 days from now" and the
        # system clock was then wound back.
        future = time.time() + 5 * 86400
        tmp_db.execute("UPDATE license_info SET last_seen_ts = ? WHERE id = 1", (future,))
        invalidate_license_cache()

        status = get_license_status()
        assert status["clock_rollback_detected"] is True
        assert status["last_seen_at"] == (date.today() + timedelta(days=5)).strftime("%Y-%m-%d")
        assert status["days_left"] == 55
        assert status["is_expired"] is False

    def test_high_water_mark_never_moves_backwards(self, tmp_db, vendor_keys):
        ok, msg = activate_license(
            _sign_payload(vendor_keys["private"], _trial_payload(term_days=60))
        )
        assert ok, msg

        future = time.time() + 3 * 86400
        tmp_db.execute("UPDATE license_info SET last_seen_ts = ? WHERE id = 1", (future,))
        invalidate_license_cache()

        get_license_status()  # must not lower the stored high-water mark

        row = tmp_db.get_one("SELECT last_seen_ts FROM license_info WHERE id = 1")
        assert float(row["last_seen_ts"]) >= future - 1

    def test_rollback_does_not_resurrect_an_expired_trial(self, tmp_db, vendor_keys):
        key = _sign_payload(
            vendor_keys["private"], _trial_payload(term_days=60, iat_days_ago=90)
        )
        ok, msg = activate_license(key)
        assert ok, msg

        tmp_db.execute(
            "UPDATE license_info SET activated_at = ? WHERE id = 1",
            ((date.today() - timedelta(days=61)).strftime("%Y-%m-%dT%H:%M:%S"),),
        )
        invalidate_license_cache()
        assert get_license_status()["is_expired"] is True

        # Winding the clock back cannot revive it: the high-water mark wins.
        tmp_db.execute(
            "UPDATE license_info SET last_seen_ts = ? WHERE id = 1",
            (time.time() + 30 * 86400,),
        )
        invalidate_license_cache()

        status = get_license_status()
        assert status["is_expired"] is True
        assert status["clock_rollback_detected"] is True

        ok, _msg = activate_license(key)
        assert ok is False

