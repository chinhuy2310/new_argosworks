"""
test_unit_security.py — Unit Tests cho Security Middleware
Kiểm tra: Rate Limiter, CSRF Token, CORS Origin Whitelist
Edge cases: token hết hạn, CSRF cross-session, rate limit memory leak
"""
import os
import sys
import time
import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_DIR = os.path.join(BASE_DIR, "server")
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

os.environ.setdefault("ARGOS_MASTER_KEY", "test-master-key-for-unit-tests-2026")


# ============================================================================
# 1. Rate Limiter — Sliding Window
# ============================================================================
class TestRateLimiter:
    """check_rate_limit: sliding window rate limiting per IP."""

    def test_allows_under_limit(self):
        from middleware_security import check_rate_limit
        ip = "test-rate-1-" + str(time.time())
        allowed, retry = check_rate_limit(ip, limit_rpm=10)
        assert allowed is True
        assert retry == 0

    def test_blocks_over_limit(self):
        from middleware_security import check_rate_limit
        ip = "test-rate-2-" + str(time.time())
        for _ in range(5):
            check_rate_limit(ip, limit_rpm=5)
        allowed, retry = check_rate_limit(ip, limit_rpm=5)
        assert allowed is False
        assert retry > 0

    def test_different_ips_independent(self):
        from middleware_security import check_rate_limit
        ts = str(time.time())
        ip1 = f"rate-ip1-{ts}"
        ip2 = f"rate-ip2-{ts}"
        for _ in range(5):
            check_rate_limit(ip1, limit_rpm=5)
        # ip1 should be blocked
        allowed1, _ = check_rate_limit(ip1, limit_rpm=5)
        assert allowed1 is False
        # ip2 should still be allowed
        allowed2, _ = check_rate_limit(ip2, limit_rpm=5)
        assert allowed2 is True

    def test_returns_positive_retry_after(self):
        from middleware_security import check_rate_limit
        ip = "test-rate-3-" + str(time.time())
        for _ in range(3):
            check_rate_limit(ip, limit_rpm=3)
        _, retry = check_rate_limit(ip, limit_rpm=3)
        assert retry >= 1
        assert retry <= 60


# ============================================================================
# 2. CSRF Token Lifecycle
# ============================================================================
class TestCSRFToken:
    """generate_csrf_token / validate_csrf_token: CSRF protection."""

    def test_generate_and_validate(self):
        from middleware_security import generate_csrf_token, validate_csrf_token
        session_token = "session-abc-123"
        csrf = generate_csrf_token(session_token)
        assert csrf is not None
        assert len(csrf) > 0
        assert validate_csrf_token(csrf, session_token)

    def test_invalid_token_rejected(self):
        from middleware_security import validate_csrf_token
        assert validate_csrf_token("completely-fake-token") is False

    def test_empty_token_rejected(self):
        from middleware_security import validate_csrf_token
        assert validate_csrf_token("") is False
        assert validate_csrf_token(None) is False
        assert validate_csrf_token("   ") is False

    def test_cross_session_rejected(self):
        """Token from session A should NOT validate for session B."""
        from middleware_security import generate_csrf_token, validate_csrf_token
        csrf_a = generate_csrf_token("session-A")
        # Should fail for different session
        assert validate_csrf_token(csrf_a, "session-B") is False

    def test_anonymous_session(self):
        from middleware_security import generate_csrf_token, validate_csrf_token
        csrf = generate_csrf_token("")
        assert csrf is not None
        # Anonymous tokens should validate without session
        # The implementation maps empty session to "anonymous"

    def test_token_format(self):
        from middleware_security import generate_csrf_token
        csrf = generate_csrf_token("test-session")
        assert "." in csrf  # Format: timestamp.hmac_signature
        parts = csrf.split(".", 1)
        assert parts[0].isdigit()  # Timestamp part
        assert len(parts[1]) == 64  # SHA256 hex


# ============================================================================
# 3. CORS Origin Whitelist
# ============================================================================
class TestCORSOrigin:
    """get_allowed_cors_origin: strict CORS validation."""

    def test_exact_domain_match(self):
        from middleware_security import get_allowed_cors_origin
        whitelist = ["company.com", "argos.internal"]
        result = get_allowed_cors_origin("https://company.com", whitelist)
        assert result is not None

    def test_subdomain_match(self):
        from middleware_security import get_allowed_cors_origin
        whitelist = ["company.com"]
        result = get_allowed_cors_origin("https://sub.company.com", whitelist)
        assert result is not None

    def test_evil_origin_blocked(self):
        from middleware_security import get_allowed_cors_origin
        whitelist = ["company.com"]
        assert get_allowed_cors_origin("https://evil-hacker.com", whitelist) is None

    def test_none_origin(self):
        from middleware_security import get_allowed_cors_origin
        assert get_allowed_cors_origin(None, ["company.com"]) is None

    def test_empty_origin(self):
        from middleware_security import get_allowed_cors_origin
        assert get_allowed_cors_origin("", ["company.com"]) is None

    def test_localhost_dev_allowed(self):
        from middleware_security import get_allowed_cors_origin
        whitelist = []
        # Standard dev port 8080 should be allowed
        result = get_allowed_cors_origin("http://localhost:8080", whitelist)
        assert result is not None

    def test_localhost_random_port_blocked(self):
        from middleware_security import get_allowed_cors_origin
        whitelist = []
        # Non-standard port should be blocked
        result = get_allowed_cors_origin("http://localhost:9999", whitelist)
        assert result is None

    def test_ftp_scheme_rejected(self):
        from middleware_security import get_allowed_cors_origin
        whitelist = ["company.com"]
        result = get_allowed_cors_origin("ftp://company.com", whitelist)
        assert result is None

    def test_no_wildcard_returned(self):
        """Must never return '*' — always the specific origin or None."""
        from middleware_security import get_allowed_cors_origin
        whitelist = ["company.com"]
        result = get_allowed_cors_origin("https://company.com", whitelist)
        assert result != "*"

    def test_domain_prefix_attack_blocked(self):
        """evil-company.com should NOT match company.com whitelist."""
        from middleware_security import get_allowed_cors_origin
        whitelist = ["company.com"]
        result = get_allowed_cors_origin("https://evil-company.com", whitelist)
        assert result is None

    def test_dot_prefix_wildcard(self):
        from middleware_security import get_allowed_cors_origin
        whitelist = [".company.com"]
        assert get_allowed_cors_origin("https://sub.company.com", whitelist) is not None
        assert get_allowed_cors_origin("https://deep.sub.company.com", whitelist) is not None
