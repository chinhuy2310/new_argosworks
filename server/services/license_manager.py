# -*- coding: utf-8 -*-
"""license_manager.py — Enterprise Asymmetric (Ed25519) License & Capacity Engine for ARGOS WORKS.
Manages seats count (max active users), contract expiration date, offline asymmetric activation,
and read-only mode enforcement upon license expiry.
Client instances contain ONLY the embedded Ed25519 Public Key. Clients CANNOT sign their own keys.
"""

import os
import json
import base64
import time
import threading
from datetime import datetime, date, timedelta
from db import query, get_one, execute
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization
from cryptography.exceptions import InvalidSignature

# ---------------------------------------------------------------------------
# Trust anchor
# ---------------------------------------------------------------------------
# Customer instances ship ONLY the vendor's Ed25519 PUBLIC key. The matching
# PRIVATE key never exists in this repository or in any released bundle; it is
# kept offline by the vendor (see tools/vendor/license_tool.py).
EMBEDDED_LICENSE_PUBLIC_KEY_HEX = "8500bd89ac956230655b758e6f965f085a2d0a02b221285384f299ce4f57ff32"

# Legacy public key(s) that may still verify during a rotation window.
# Kept empty on purpose: the previous key pair was published in the source tree
# and is therefore compromised. Add a hex key here only for a time-boxed
# migration of already-issued licenses.
LEGACY_LICENSE_PUBLIC_KEY_HEXES = []

# License status is read on almost every write request; cache it briefly.
_STATUS_CACHE_TTL_SECONDS = 30

# Upper bound accepted for a signed trial term (defensive: a corrupted or
# maliciously signed payload must never grant a multi-year evaluation).
_MAX_TRIAL_TERM_DAYS = 365

# Clock-rollback protection (offline trial tampering). The highest wall-clock
# timestamp this instance has ever observed is persisted as a high-water mark;
# trial maths is clamped to it, so winding the system clock back can never
# extend an evaluation. Tolerates small NTP corrections; writes are throttled so
# normal read traffic does not hammer the database.
_CLOCK_ROLLBACK_TOLERANCE_SECONDS = 300
_LAST_SEEN_WRITE_INTERVAL_SECONDS = 3600
_status_cache = {"ts": 0.0, "data": None}
_status_cache_lock = threading.Lock()


class LicenseSigningKeyMissing(RuntimeError):
    """Raised when a vendor-only signing operation runs without a private key."""


def invalidate_license_cache():
    """Drop the cached license status (call after activation/import)."""
    with _status_cache_lock:
        _status_cache["ts"] = 0.0
        _status_cache["data"] = None


def get_license_public_keys():
    """Return the list of Ed25519 public keys trusted by this instance."""
    raw_env = (os.environ.get("ARGOS_LICENSE_PUBLIC_KEY") or "").strip()
    hex_keys = [k.strip() for k in raw_env.split(",") if k.strip()] if raw_env else []
    if not hex_keys:
        hex_keys = [EMBEDDED_LICENSE_PUBLIC_KEY_HEX] + list(LEGACY_LICENSE_PUBLIC_KEY_HEXES)

    keys = []
    for hex_key in hex_keys:
        try:
            keys.append(ed25519.Ed25519PublicKey.from_public_bytes(bytes.fromhex(hex_key)))
        except Exception:
            continue
    return keys


def get_license_public_key() -> ed25519.Ed25519PublicKey:
    """Backward-compatible single-key accessor (first accepted public key)."""
    keys = get_license_public_keys()
    if not keys:
        raise ValueError("No valid ARGOS license public key configured.")
    return keys[0]



def _empty_license_status(reason="No valid license"):
    return {
        "customer_name": "Unlicensed Enterprise",
        "license_key": "",
        "max_seats": 0,
        "active_seats": 0,
        "expiry_date": "1970-01-01",
        "is_active": False,
        "is_expired": True,
        "is_read_only": True,
        "license_valid": False,
        "license_reason": reason,
        "days_left": 0,
        "expiry_warning": False,
        "is_trial": False,
        "term_days": 0,
        "activated_at": "",
        "hard_expiry_date": "",
        "last_seen_at": "",
        "clock_rollback_detected": False,
        "modules": []
    }


def _parse_iso_date(value):
    """'YYYY-MM-DD' (optionally followed by a time) → date, or None."""
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def resolve_license_expiry(payload, activated_at=None, now=None):
    """
    Resolve the effective expiry of a signed licence payload.

    Returns ``(effective_expiry, hard_cap, anchor)`` where both dates may be
    ``None`` when the payload carries no usable date.

    * Commercial licence (no ``trial``/``term_days``): expiry is the absolute
      date signed by the vendor — behaviour identical to previous releases.
    * Trial licence: ``term_days`` counts from the FIRST activation
      (``license_info.activated_at``), never from "today", so re-activating the
      same key cannot extend the evaluation period. The anchor is clamped into
      ``[iat, now]`` so a tampered DB row or a wound-back clock cannot push the
      window forward. A signed ``expiry`` is optional: when present it stays a
      hard cap, when absent the trial simply runs ``term_days`` from activation.
    """
    payload = payload or {}
    hard = _parse_iso_date(payload.get("expiry"))
    iat = _parse_iso_date(payload.get("iat"))

    # Payloads produced by verify_license_key() normalise the flag to ``is_trial``
    # while the signed JSON uses ``trial``; accept both.
    is_trial = bool(payload.get("trial")) or bool(payload.get("is_trial"))
    if not is_trial or not payload.get("term_days"):
        return hard, hard, None

    try:
        term = int(payload.get("term_days"))
    except (TypeError, ValueError):
        return hard, hard, None
    if term <= 0 or term > _MAX_TRIAL_TERM_DAYS:
        return hard, hard, None

    today = now or date.today()
    anchor = _parse_iso_date(activated_at) or iat or today
    if iat and anchor < iat:
        anchor = iat            # a licence can never start before its issue date
    if anchor > today:
        anchor = iat or today   # future anchor = tampered DB / rolled-back clock
    soft = anchor + timedelta(days=term)
    return (min(soft, hard) if hard else soft), hard, anchor


def _load_last_seen_ts():
    """Highest wall-clock timestamp this instance has observed (0 when unknown)."""
    try:
        row = get_one("SELECT last_seen_ts FROM license_info WHERE id = 1") or {}
        return float(row.get("last_seen_ts") or 0)
    except Exception:
        return 0.0


def _record_last_seen(now_epoch, stored):
    """Advance the clock high-water mark (throttled, never moves backwards)."""
    if now_epoch - stored < _LAST_SEEN_WRITE_INTERVAL_SECONDS:
        return
    try:
        execute(
            "UPDATE license_info SET last_seen_ts = ? WHERE id = 1 AND last_seen_ts < ?",
            (now_epoch, now_epoch),
        )
    except Exception:
        pass


def resolve_current_date():
    """
    Return ``(now_date, clock_rollback_detected, high_water_date)``.

    ``now_date`` is the LATER of the wall clock and the persisted high-water
    mark. Winding the system clock backwards therefore never moves a trial
    clock backwards: the evaluation keeps counting from the last time the
    instance was really seen.
    """
    now_epoch = time.time()
    stored = _load_last_seen_ts()
    rollback = bool(stored and now_epoch < (stored - _CLOCK_ROLLBACK_TOLERANCE_SECONDS))
    if rollback:
        high_water = datetime.fromtimestamp(stored).date()
        return high_water, True, high_water
    _record_last_seen(now_epoch, stored)
    today = date.today()
    high_water = datetime.fromtimestamp(stored).date() if stored else today
    return today, False, high_water



def get_license_status(use_cache=True):
    """
    현재 시스템 라이선스 상태 및 사용 좌석(Active Seats) 현황을 반환한다.

    The stored license key is verified against the vendor's Ed25519 public key.
    A row that was written directly into the database (seed, manual INSERT,
    restored backup of another tenant) is NOT trusted: unsigned or tampered
    keys are reported as unlicensed instead of granting unlimited seats.
    """
    now = time.time()
    if use_cache:
        with _status_cache_lock:
            if _status_cache["data"] is not None and (now - _status_cache["ts"]) < _STATUS_CACHE_TTL_SECONDS:
                return dict(_status_cache["data"])

    status = _compute_license_status()

    with _status_cache_lock:
        _status_cache["ts"] = time.time()
        _status_cache["data"] = dict(status)
    return status


def _compute_license_status():
    row = get_one("SELECT * FROM license_info WHERE id = 1")
    if not row:
        return _empty_license_status("라이선스 정보가 없습니다")

    # Count active non-disabled users
    user_cnt_row = get_one("SELECT count(*) as c FROM users WHERE disabled = 0")
    active_seats = user_cnt_row["c"] if user_cnt_row else 0

    stored_key = (row.get("license_key") or "").strip()
    verified_ok, verify_msg, verified_data = verify_license_key(stored_key)

    # Seats / expiry / modules come from the signed payload. Trial expiry is
    # anchored to the first activation. `clock_now` is the LATER of the wall
    # clock and the persisted high-water mark, so winding the system clock back
    # can never move the trial window backwards.
    clock_now, clock_rollback, high_water = resolve_current_date()

    is_trial = False
    term_days = 0
    anchor_str = ""
    hard_str = ""
    if verified_ok and verified_data:
        max_seats = int(verified_data.get("seats") or 0)
        modules = verified_data.get("modules") or []
        customer = verified_data.get("customer") or row.get("customer_name") or "Enterprise Customer"
        is_trial = bool(verified_data.get("is_trial"))
        term_days = int(verified_data.get("term_days") or 0)
        exp_date, hard_cap, anchor = resolve_license_expiry(
            verified_data, row.get("activated_at"), now=clock_now
        )
        exp_str = exp_date.strftime("%Y-%m-%d") if exp_date else "1970-01-01"
        hard_str = hard_cap.strftime("%Y-%m-%d") if hard_cap else ""
        anchor_str = anchor.strftime("%Y-%m-%d") if anchor else (row.get("activated_at") or "")[:10]
    else:
        max_seats = 0
        exp_str = "1970-01-01"
        modules = []
        customer = row.get("customer_name") or "Enterprise Customer"

    is_expired = True
    days_left = 0
    try:
        exp_date = datetime.strptime(exp_str[:10], "%Y-%m-%d").date()
        days_left = (exp_date - clock_now).days
        is_expired = days_left < 0
    except Exception:
        is_expired = True

    row_active = bool(row.get("is_active"))
    is_active = verified_ok and row_active and not is_expired
    is_read_only = not is_active

    warn_window = min(30, max(3, term_days // 2)) if (is_trial and term_days) else 30

    return {
        "customer_name": customer,
        "license_key": stored_key,
        "max_seats": max_seats,
        "active_seats": active_seats,
        "expiry_date": exp_str,
        "hard_expiry_date": hard_str,
        "is_trial": is_trial,
        "term_days": term_days,
        "activated_at": anchor_str,
        "last_seen_at": high_water.strftime("%Y-%m-%d"),
        "clock_rollback_detected": clock_rollback,
        "is_active": is_active,
        "is_expired": is_expired,
        "is_read_only": is_read_only,
        "license_valid": verified_ok,
        "license_reason": verify_msg,
        "days_left": max(0, days_left),
        "expiry_warning": bool(verified_ok and not is_expired and 0 <= days_left <= warn_window),
        "modules": modules
    }

get_license_info = get_license_status


def get_license_modules():
    """Return the set of licensed module codes (empty when unlicensed)."""
    status = get_license_status()
    if not status.get("is_active"):
        return set()
    return {str(m).strip().lower() for m in (status.get("modules") or []) if str(m).strip()}


def has_module(module_name):
    """True when the active license entitles this module ('*'/'all' = every module)."""
    if not module_name:
        return True
    modules = get_license_modules()
    if not modules:
        return False
    name = str(module_name).strip().lower()
    return name in modules or "*" in modules or "all" in modules



def check_seat_available():
    """신규 사용자 등록 시 좌석 한도 초과 여부를 검사한다."""
    status = get_license_status()
    if not status.get("license_valid"):
        return False, "유효한 라이선스가 없습니다. 관리자 라이선스 활성화 후 계정을 발급할 수 있습니다."
    if status["is_read_only"]:
        return False, f"라이선스가 만료되어 읽기 전용 상태입니다 (만료일: {status['expiry_date']}). 갱신이 필요합니다."
    if status["active_seats"] >= status["max_seats"]:
        return False, f"라이선스 사용자 좌석 한도({status['max_seats']}명)를 초과했습니다. 관리자에게 라이선스 증설을 요청하세요."
    return True, ""


def is_system_read_only():
    """시스템이 라이선스 만료 등으로 읽기 전용 상태인지 여부를 반환한다."""
    try:
        status = get_license_status()
        return bool(status.get("is_read_only", False))
    except Exception:
        return True


def generate_signed_license_key(customer_name, max_seats, expiry_date_str, modules,
                                signing_key_hex=None, is_trial=False, term_days=None):
    """
    VENDOR-ONLY: sign an offline license with the Ed25519 private key.

    ``is_trial=True`` + ``term_days=N`` issues an evaluation licence whose clock
    starts on the customer's FIRST activation: the runtime computes
    ``expiry = activated_at + N`` (capped by ``expiry_date_str`` when one is
    supplied). Pass ``expiry_date_str=None`` for a trial with no absolute cap.

    The private key must be provided explicitly (argument or
    ARGOS_LICENSE_SIGNING_KEY). There is deliberately NO default/fallback key:
    a shipped private key would let any customer mint unlimited licenses.
    Use tools/vendor/license_tool.py instead of calling this directly.
    """
    priv_hex = (signing_key_hex or os.environ.get("ARGOS_LICENSE_SIGNING_KEY") or "").strip()
    if not priv_hex:
        raise LicenseSigningKeyMissing(
            "License signing key is not configured. This is a vendor-only operation: "
            "set ARGOS_LICENSE_SIGNING_KEY or pass signing_key_hex. The private key must "
            "never be stored in the product source tree or in a customer deployment."
        )

    try:
        priv_bytes = bytes.fromhex(priv_hex)
    except ValueError:
        raise ValueError(
            "ARGOS_LICENSE_SIGNING_KEY must be a hex-encoded Ed25519 private key (64 hex chars)."
        )
    if len(priv_bytes) != 32:
        raise ValueError("ARGOS_LICENSE_SIGNING_KEY must contain exactly 32 bytes (64 hex chars).")
    private_key = ed25519.Ed25519PrivateKey.from_private_bytes(priv_bytes)

    payload = {
        "customer": customer_name,
        "seats": max_seats,
        "modules": modules,
        "iat": datetime.now().strftime("%Y-%m-%d")
    }
    # A trial may run purely for ``term_days`` from the first activation; when an
    # expiry is supplied it acts as an absolute hard cap.
    if expiry_date_str:
        payload["expiry"] = expiry_date_str
    if is_trial:
        try:
            term = int(term_days)
        except (TypeError, ValueError):
            raise ValueError("term_days must be a positive integer for a trial license.")
        if term <= 0 or term > _MAX_TRIAL_TERM_DAYS:
            raise ValueError(
                f"term_days must be between 1 and {_MAX_TRIAL_TERM_DAYS} days."
            )
        payload["trial"] = True
        payload["term_days"] = term
    raw_json = json.dumps(payload, separators=(',', ':'), sort_keys=True).encode("utf-8")
    sig = private_key.sign(raw_json)
    b64_payload = base64.urlsafe_b64encode(raw_json).decode("ascii").rstrip("=")
    b64_sig = base64.urlsafe_b64encode(sig).decode("ascii").rstrip("=")
    return f"AGY-{b64_payload}.{b64_sig}"


DEFAULT_TRIAL_LICENSE_KEY = (
    "AGY-eyJjdXN0b21lciI6IkFyZ29zIEVudGVycHJpc2UgVHJpYWwiLCJpYXQiOiIyMDI2LTEwLTI5IiwibW9kdWxlcyI6WyJjYW52YXMiLCJwaW0iLCJqaXJhIiwicmFnIiwic2NoZWR1bGUiLCJhdWRpdCJdLCJzZWF0cyI6NTAsInRlcm1fZGF5cyI6NjAsInRyaWFsIjp0cnVlfQ.ovSRoVxez65COM4zzyVnNKrZ5chxofIqcyVtCWYq-ExX5KLt6vb8JrBHDPW21ygMCTAKXm63sMLVmVWZ6jtQDQ"
)


def verify_license_key(license_key_str):
    """라이선스 키의 유효성을 Ed25519 공개키로 비대칭 검증하고 메타데이터를 반환한다."""
    key = (license_key_str or "").strip()
    if not key:
        return False, "라이선스 키를 입력해주세요.", None

    # Convenience: Automatically expand 'TRIAL' alias to the official signed trial key
    if key.upper() == "TRIAL":
        key = DEFAULT_TRIAL_LICENSE_KEY

    if "." not in key:
        return False, "잘못된 라이선스 키 형식입니다 (AGY-payload.signature 구조 필요).", None

    content = key
    if content.startswith("AGY-"):
        content = content[4:]

    parts = content.split(".")
    if len(parts) != 2:
        return False, "유효하지 않은 라이선스 서명 구조입니다.", None

    b64_payload, b64_sig = parts[0], parts[1]

    # Decode payload
    pad_p = len(b64_payload) % 4
    if pad_p:
        b64_payload += "=" * (4 - pad_p)

    pad_s = len(b64_sig) % 4
    if pad_s:
        b64_sig += "=" * (4 - pad_s)

    try:
        raw_json = base64.urlsafe_b64decode(b64_payload.encode("ascii"))
        sig_bytes = base64.urlsafe_b64decode(b64_sig.encode("ascii"))
    except Exception as e:
        return False, f"라이선스 디코딩 실패: {e}", None

    # Verify asymmetric Ed25519 digital signature against any accepted public key
    accepted_keys = get_license_public_keys()
    if not accepted_keys:
        return False, "서버에 유효한 라이선스 공개키가 설정되어 있지 않습니다.", None

    signature_ok = False
    for public_key in accepted_keys:
        try:
            public_key.verify(sig_bytes, raw_json)
            signature_ok = True
            break
        except InvalidSignature:
            continue
        except Exception as e:
            return False, f"서명 검증 중 오류: {e}", None

    if not signature_ok:
        return False, "라이선스 디지털 서명(Ed25519) 검증에 실패했습니다. (위변조 감지 또는 미승인 발급키)", None

    try:
        data = json.loads(raw_json.decode("utf-8"))
        customer = data.get("customer") or "Valued Enterprise Customer"
        seats = int(data.get("seats") or 0)
        expiry = str(data.get("expiry") or "")[:10]
        modules = data.get("modules") or []

        is_trial = bool(data.get("trial"))
        term_days = 0
        if is_trial:
            try:
                term_days = int(data.get("term_days"))
            except (TypeError, ValueError):
                return False, "체험 기간(term_days) 값이 유효하지 않습니다.", None
            if term_days <= 0 or term_days > _MAX_TRIAL_TERM_DAYS:
                return False, (
                    f"체험 기간(term_days) 값이 유효하지 않습니다 (1~{_MAX_TRIAL_TERM_DAYS}일)."
                ), None
            if not _parse_iso_date(data.get("iat")):
                return False, "체험 라이선스에 발급일(iat) 정보가 없습니다.", None

        # A trial may omit `expiry` entirely: its window is term_days counted from
        # the first activation. Every other licence must carry a signed expiry.
        if not expiry and not term_days:
            return False, "라이선스에 만료일(expiry) 정보가 없습니다.", None

        # Hard cap, when present. The effective trial window is resolved later
        # against the first activation anchor.
        if expiry:
            try:
                exp_date = datetime.strptime(expiry[:10], "%Y-%m-%d").date()
                if date.today() > exp_date:
                    return False, f"만료된 라이선스 키입니다 (만료일: {expiry}).", None
            except Exception:
                pass

        return True, "유효한 엔터프라이즈 정품 라이선스입니다.", {
            "customer": customer,
            "seats": seats,
            "expiry": expiry,
            "modules": modules,
            "iat": str(data.get("iat") or "")[:10],
            "is_trial": is_trial or ("trial" in customer.lower()),
            "term_days": term_days,
        }
    except Exception as e:
        return False, f"라이선스 페이로드 파싱 실패: {e}", None


def activate_license(license_key_str):
    """고객 인스턴스: Ed25519 서명 라이선스 키를 검증하고 시스템에 적용한다."""
    ok, msg, data = verify_license_key(license_key_str)
    if not ok:
        return False, msg

    if not data or int(data.get("seats") or 0) <= 0:
        return False, "라이선스에 유효한 사용자 좌석(Seats) 정보가 없습니다."

    try:
        customer = data.get("customer") or "Valued Enterprise"
        seats = int(data.get("seats") or 0)
        expiry = str(data.get("expiry") or "")[:10]
        modules = data.get("modules") or []
        key = (license_key_str or "").strip()
        now_dt = datetime.now()
        now_str = now_dt.strftime("%Y-%m-%dT%H:%M:%S")
        now_epoch = time.time()

        # Clock-rollback protection: never evaluate a trial against a clock that
        # is earlier than the highest time this instance has already seen.
        clock_now, _clock_rollback, _hw = resolve_current_date()

        # Trial anchor: written once per licence key. Re-activating the SAME key
        # must not restart the evaluation clock; switching to a different key
        # (e.g. trial -> commercial, or a freshly issued trial) resets it.
        row = get_one("SELECT license_key, activated_at FROM license_info WHERE id = 1") or {}
        same_key = (row.get("license_key") or "").strip() == key
        anchor_str = ((row.get("activated_at") or "").strip() if same_key else "") or now_str

        exp_date, _hard_cap, _anchor = resolve_license_expiry(data, anchor_str, now=clock_now)
        if data.get("term_days"):
            if exp_date and exp_date < clock_now:
                return False, (
                    f"체험 기간({data['term_days']}일)이 종료되었습니다 "
                    f"(만료일: {exp_date.strftime('%Y-%m-%d')}). 정품 라이선스를 활성화해주세요."
                )

        # `expiry_date` in the DB is informational only: the signed payload plus
        # `activated_at` are authoritative. A trial without a signed hard cap
        # stores its computed end date for readability.
        if not expiry and exp_date:
            expiry = exp_date.strftime("%Y-%m-%d")
        if not expiry:
            expiry = "1970-01-01"

        execute("""
            INSERT INTO license_info (id, customer_name, license_key, max_seats, expiry_date, modules_json, is_active, activated_at, last_seen_ts, updated_at)
            VALUES (1, ?, ?, ?, ?, ?, 1, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
                customer_name = EXCLUDED.customer_name,
                license_key = EXCLUDED.license_key,
                max_seats = EXCLUDED.max_seats,
                expiry_date = EXCLUDED.expiry_date,
                modules_json = EXCLUDED.modules_json,
                is_active = 1,
                activated_at = CASE
                    WHEN COALESCE(license_info.license_key, '') <> EXCLUDED.license_key
                        THEN EXCLUDED.activated_at
                    ELSE COALESCE(NULLIF(license_info.activated_at, ''), EXCLUDED.activated_at)
                END,
                last_seen_ts = CASE
                    WHEN COALESCE(license_info.last_seen_ts, 0) > EXCLUDED.last_seen_ts
                        THEN license_info.last_seen_ts
                    ELSE EXCLUDED.last_seen_ts
                END,
                updated_at = EXCLUDED.updated_at
        """, (customer, key, seats, expiry, json.dumps(modules), anchor_str, now_epoch, now_str))

        invalidate_license_cache()

        if data.get("term_days"):
            effective = exp_date.strftime("%Y-%m-%d") if exp_date else expiry
            return True, (
                f"'{customer}' 체험판 {data['term_days']}일이 활성화되었습니다 "
                f"(활성화일: {anchor_str[:10]}, 만료일: {effective})."
            )
        return True, f"'{customer}' 엔터프라이즈 라이선스(좌석: {seats}명, 만료일: {expiry})가 성공적으로 활성화되었습니다."
    except Exception as e:
        return False, f"라이선스 활성화 실패: {e}"
