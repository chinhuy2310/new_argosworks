import os
import hmac
import hashlib
import threading
import pytest
import middleware_security as ms
from middleware_security import _get_csrf_secret


def test_csrf_secret_reads_existing_file(tmp_path, monkeypatch):
    """Verify _get_csrf_secret reads existing .csrf_secret file."""
    secret_dir = tmp_path / "data"
    secret_dir.mkdir()
    secret_file = secret_dir / ".csrf_secret"
    expected_secret = b"12345678901234567890123456789012"
    secret_file.write_bytes(expected_secret)

    monkeypatch.setattr("config.DATA_DIR", str(secret_dir))
    ms._CSRF_SECRET = None

    secret = _get_csrf_secret()
    assert secret == expected_secret


def test_csrf_secret_creates_new_file_atomically(tmp_path, monkeypatch):
    """Verify _get_csrf_secret atomically generates 32 bytes file if none exists."""
    secret_dir = tmp_path / "data"
    monkeypatch.setattr("config.DATA_DIR", str(secret_dir))
    ms._CSRF_SECRET = None

    secret = _get_csrf_secret()
    assert len(secret) == 32
    
    secret_file = secret_dir / ".csrf_secret"
    assert secret_file.exists()
    assert secret_file.read_bytes() == secret


def test_csrf_secret_derives_from_master_key_on_readonly_fs(tmp_path, monkeypatch):
    """Verify fallback to HMAC-SHA256 from master key when disk is read-only."""
    secret_dir = tmp_path / "data"
    monkeypatch.setattr("config.DATA_DIR", str(secret_dir))
    ms._CSRF_SECRET = None

    # Simulate read-only filesystem on os.open
    orig_open = os.open
    def mock_os_open(path, flags, *args, **kwargs):
        if ".csrf_secret" in str(path):
            raise PermissionError("Read-only file system")
        return orig_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", mock_os_open)
    
    dummy_master_key = b"dummy_enterprise_master_key_123456"
    monkeypatch.setattr("utils.crypto.get_master_key", lambda: dummy_master_key)

    secret = _get_csrf_secret()
    expected = hmac.new(dummy_master_key, b"argos-csrf-secret-v1", hashlib.sha256).digest()
    assert secret == expected


def test_csrf_secret_fails_closed(tmp_path, monkeypatch):
    """Verify RuntimeError is raised (fail closed) if storage and master key are unavailable."""
    secret_dir = tmp_path / "data"
    monkeypatch.setattr("config.DATA_DIR", str(secret_dir))
    ms._CSRF_SECRET = None

    def mock_os_open(path, flags, *args, **kwargs):
        raise PermissionError("Read-only file system")

    monkeypatch.setattr(os, "open", mock_os_open)
    monkeypatch.setattr("utils.crypto.get_master_key", lambda: b"")
    monkeypatch.delenv("ARGOS_MASTER_KEY", raising=False)
    monkeypatch.delenv("JARVIS_MASTER_KEY", raising=False)

    with pytest.raises(RuntimeError) as exc_info:
        _get_csrf_secret()
    assert "CSRF secret unavailable: fail closed" in str(exc_info.value)


def test_csrf_secret_concurrency(tmp_path, monkeypatch):
    """Verify concurrent threads receive the exact same secret."""
    secret_dir = tmp_path / "data"
    monkeypatch.setattr("config.DATA_DIR", str(secret_dir))
    ms._CSRF_SECRET = None

    results = []
    def worker():
        results.append(_get_csrf_secret())

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 8
    first = results[0]
    for r in results:
        assert r == first
