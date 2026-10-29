import os
import pytest
import handler
from handler import (
    is_trusted_proxy_peer, get_trusted_proxies, check_trusted_proxies_warning,
    ArgosHandler
)

def test_default_trusted_proxies_loopback_only(monkeypatch):
    """Verify default trusted proxies only trust loopback, not broad 172.16.0.0/12 subnets."""
    monkeypatch.delenv("TRUSTED_PROXIES", raising=False)
    handler._TRUSTED_PROXY_CACHE.clear()
    
    # Loopback trusted
    assert is_trusted_proxy_peer("127.0.0.1") is True
    assert is_trusted_proxy_peer("::1") is True
    
    # 172.16.0.0/12 subnets MUST NOT be trusted by default
    assert is_trusted_proxy_peer("172.20.1.5") is False
    assert is_trusted_proxy_peer("172.16.0.1") is False
    assert is_trusted_proxy_peer("172.31.255.254") is False
    assert is_trusted_proxy_peer("192.168.1.100") is False


def test_client_ip_untrusted_peer_cannot_spoof_xff(monkeypatch):
    """Untrusted peer attempting to supply X-Forwarded-For is ignored."""
    monkeypatch.delenv("TRUSTED_PROXIES", raising=False)
    handler._TRUSTED_PROXY_CACHE.clear()

    class FakeHandler:
        client_address = ("172.20.1.5", 54321)
        headers = {"X-Forwarded-For": "203.0.113.195"}

    ip = ArgosHandler._extract_client_ip(FakeHandler())
    # Header ignored because 172.20.1.5 is untrusted peer
    assert ip == "172.20.1.5"


def test_dedicated_subnet_trusted_proxies(monkeypatch):
    """Custom dedicated subnet trusts internal proxy and honors X-Forwarded-For."""
    monkeypatch.setenv("TRUSTED_PROXIES", "127.0.0.1,::1,172.28.0.0/24")
    handler._TRUSTED_PROXY_CACHE.clear()

    assert is_trusted_proxy_peer("172.28.0.3") is True
    assert is_trusted_proxy_peer("172.29.0.3") is False

    class FakeHandler:
        client_address = ("172.28.0.3", 54321)
        headers = {"X-Forwarded-For": "203.0.113.195"}

    ip = ArgosHandler._extract_client_ip(FakeHandler())
    assert ip == "203.0.113.195"


def test_broad_cidr_triggers_security_warning(monkeypatch, capsys):
    """Overly broad CIDR (prefixlen <= 12) or 0.0.0.0 triggers security warning."""
    # Test CIDR <= 12
    monkeypatch.setenv("TRUSTED_PROXIES", "10.0.0.0/8")
    handler._TRUSTED_PROXY_CACHE.clear()
    handler._WARNED_TRUSTED_PROXIES = False

    check_trusted_proxies_warning()
    captured = capsys.readouterr()
    assert "[SECURITY WARNING] TRUSTED_PROXIES is too broad" in captured.err

    # Test 0.0.0.0
    monkeypatch.setenv("TRUSTED_PROXIES", "0.0.0.0")
    handler._TRUSTED_PROXY_CACHE.clear()
    handler._WARNED_TRUSTED_PROXIES = False

    check_trusted_proxies_warning()
    captured2 = capsys.readouterr()
    assert "[SECURITY WARNING] TRUSTED_PROXIES is too broad" in captured2.err


def test_is_secure_ignores_spoofed_xfp_from_direct_client(monkeypatch):
    """Audit F-0005: a direct client must not be able to force the Secure flag."""
    monkeypatch.delenv("TRUSTED_PROXIES", raising=False)
    handler._TRUSTED_PROXY_CACHE.clear()

    class FakeHandler:
        client_address = ("172.20.1.5", 54321)
        headers = {"X-Forwarded-Proto": "https"}
        connection = object()  # no getpeercert -> not a TLS socket

    assert ArgosHandler._is_secure(FakeHandler()) is False


def test_is_secure_honours_xfp_from_trusted_proxy(monkeypatch):
    """X-Forwarded-Proto is trusted only when it comes from TRUSTED_PROXIES."""
    monkeypatch.setenv("TRUSTED_PROXIES", "127.0.0.1,::1,172.28.0.0/24")
    handler._TRUSTED_PROXY_CACHE.clear()

    class FakeHandler:
        client_address = ("172.28.0.3", 54321)
        headers = {"X-Forwarded-Proto": "https"}
        connection = object()

    assert ArgosHandler._is_secure(FakeHandler()) is True

