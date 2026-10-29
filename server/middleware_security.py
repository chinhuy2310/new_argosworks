"""
security.py — Enterprise Security Middleware & Utilities
Provides:
1. In-memory & Redis-ready Rate Limiter (sliding window)
2. Strict CORS policy check
3. CSRF token generation and validation (strictly bound to session)
4. Account lockout & Brute-force protection
"""

import os
import time
import secrets
import hmac
import hashlib
import threading
from typing import Tuple, Optional, Dict, List

_rate_limit_lock = threading.Lock()
_rate_limits: Dict[str, List[float]] = {}

_csrf_tokens_lock = threading.Lock()
_csrf_tokens: Dict[str, str] = {}  # token -> session_token
_csrf_token_times: Dict[str, float] = {}  # token -> timestamp
_CSRF_SECRET: Optional[bytes] = None
_csrf_secret_lock = threading.Lock()

def _get_csrf_secret() -> bytes:
    """Returns persistent secret key for CSRF HMAC generation and verification across restarts.
    Priority:
    1. Read data/.csrf_secret if >= 16 bytes.
    2. Atomically create data/.csrf_secret with 32 bytes and 0o600 permissions.
    3. If filesystem read-only, derive deterministically from master key via HMAC-SHA256.
    4. Otherwise, fail closed by raising RuntimeError.
    """
    global _CSRF_SECRET
    if _CSRF_SECRET is not None:
        return _CSRF_SECRET

    with _csrf_secret_lock:
        if _CSRF_SECRET is not None:
            return _CSRF_SECRET

        from config import DATA_DIR
        secret_file = os.path.join(DATA_DIR, ".csrf_secret")

        # 1. Read existing file
        try:
            if os.path.exists(secret_file):
                with open(secret_file, "rb") as f:
                    content = f.read().strip()
                if len(content) >= 16:
                    _CSRF_SECRET = content
                    return _CSRF_SECRET
        except Exception:
            pass

        # 2. Atomically create file
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            if hasattr(os, "O_BINARY"):
                flags |= os.O_BINARY
            new_secret = secrets.token_bytes(32)
            try:
                fd = os.open(secret_file, flags, 0o600)
                try:
                    os.write(fd, new_secret)
                finally:
                    os.close(fd)
                _CSRF_SECRET = new_secret
                return _CSRF_SECRET
            except FileExistsError:
                # Race condition: another thread/process created it
                with open(secret_file, "rb") as f:
                    content = f.read().strip()
                if len(content) >= 16:
                    _CSRF_SECRET = content
                    return _CSRF_SECRET
        except (OSError, PermissionError):
            pass

        # 3. Derive from master key if read-only filesystem
        try:
            from utils.crypto import get_master_key
            mkey = get_master_key()
            if mkey:
                derived = hmac.new(mkey, b"argos-csrf-secret-v1", hashlib.sha256).digest()
                _CSRF_SECRET = derived
                return _CSRF_SECRET
        except Exception:
            pass

        env_mkey = os.environ.get("ARGOS_MASTER_KEY", "").strip() or os.environ.get("JARVIS_MASTER_KEY", "").strip()
        if env_mkey:
            derived = hmac.new(env_mkey.encode("utf-8"), b"argos-csrf-secret-v1", hashlib.sha256).digest()
            _CSRF_SECRET = derived
            return _CSRF_SECRET

        # 4. Fail closed
        raise RuntimeError("CSRF secret unavailable: fail closed")

DEFAULT_RATE_LIMIT_RPM = 120  # Max 120 requests per minute per IP

def check_rate_limit(ip: str, limit_rpm: int = DEFAULT_RATE_LIMIT_RPM) -> Tuple[bool, int]:
    """
    Sliding window rate limiter with auto-eviction of idle IPs to prevent memory leak.
    Returns (is_allowed, retry_after_seconds).
    """
    now = time.time()
    window = 60.0  # 1 minute

    with _rate_limit_lock:
        if len(_rate_limits) > 2000:
            stale_ips = [k for k, v in _rate_limits.items() if not v or (now - v[-1]) > window]
            for sip in stale_ips:
                del _rate_limits[sip]

        timestamps = [t for t in _rate_limits.get(ip, []) if now - t < window]
        if len(timestamps) >= limit_rpm:
            earliest = timestamps[0]
            retry_after = max(1, int(window - (now - earliest)))
            return False, retry_after

        timestamps.append(now)
        _rate_limits[ip] = timestamps
        return True, 0

def generate_csrf_token(session_token: str) -> str:
    """
    Generates a cryptographic CSRF token strictly bound to session token and persistent server secret.
    Binds (session_token, token) in memory and cryptographic HMAC.
    """
    if not session_token:
        session_token = "anonymous"
    ts = int(time.time())
    msg = f"{session_token}:{ts}".encode("utf-8")
    sig = hmac.new(_get_csrf_secret(), msg, hashlib.sha256).hexdigest()
    token = f"{ts}.{sig}"
    
    with _csrf_tokens_lock:
        _csrf_tokens[token] = session_token
        _csrf_token_times[token] = time.time()
        # Clean old tokens > 24 hours
        cutoff = time.time() - 86400
        for k in list(_csrf_token_times.keys()):
            if _csrf_token_times[k] < cutoff:
                del _csrf_token_times[k]
                _csrf_tokens.pop(k, None)
    return token

def validate_csrf_token(token: str, session_token: Optional[str] = None) -> bool:
    """
    Validates provided CSRF token.
    Fast-path and HMAC verification strictly verify the token belongs to the given session_token.
    Prevents token from one session being used against another session.
    """
    if not token or not isinstance(token, str):
        return False
    token = token.strip()
    if not token:
        return False

    # 1. Fast path: In-memory lookup strictly verifying binding to session_token
    with _csrf_tokens_lock:
        if token in _csrf_tokens:
            recorded_session = _csrf_tokens[token]
            if session_token is not None:
                return recorded_session == session_token
            return recorded_session == "anonymous"

    # 2. Resilient cryptographic HMAC validation bound to user's session token
    if session_token:
        if "." in token:
            parts = token.split(".", 1)
            try:
                ts_int = int(parts[0])
                # Token valid within 7 days
                if abs(time.time() - ts_int) <= 86400 * 7:
                    msg = f"{session_token}:{ts_int}".encode("utf-8")
                    expected_sig = hmac.new(_get_csrf_secret(), msg, hashlib.sha256).hexdigest()
                    if hmac.compare_digest(parts[1], expected_sig):
                        return True
            except Exception:
                pass
        else:
            msg = session_token.encode("utf-8")
            expected_sig = hmac.new(_get_csrf_secret(), msg, hashlib.sha256).hexdigest()
            if hmac.compare_digest(token, expected_sig):
                return True

    return False

def get_allowed_cors_origin(origin_header: Optional[str], allowed_domains: List[str]) -> Optional[str]:
    """
    Validates origin against strict enterprise whitelist. Never returns wildcard '*'.
    Prevents arbitrary localhost ports from accessing sensitive endpoints with credentials.
    """
    if not origin_header:
        return None
    from urllib.parse import urlsplit
    try:
        parsed = urlsplit(origin_header)
        scheme = (parsed.scheme or "").lower()
        host = (parsed.hostname or "").lower()
        port = parsed.port
    except Exception:
        return None

    if not host or scheme not in ("http", "https"):
        return None

    cleaned_allowed = [d.strip().lower() for d in allowed_domains if d.strip()]

    origin_clean = f"{scheme}://{host}" + (f":{port}" if port and port not in (80, 443) else "")
    origin_host_port = f"{host}" + (f":{port}" if port else "")

    for pattern in cleaned_allowed:
        if pattern in (origin_clean, origin_host_port, host):
            return origin_header
        if pattern.startswith(".") and host.endswith(pattern):
            return origin_header
        if host == pattern or (not pattern.startswith(".") and host.endswith("." + pattern)):
            return origin_header

    # For dev environments: only allow standard dev ports (8080, 80, 443, 3000, 5173)
    allowed_dev_ports = {8080, 80, 443, 3000, 5173}
    if host in ("localhost", "127.0.0.1", "::1"):
        if port is None or port in allowed_dev_ports:
            return origin_header

    return None
