#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the startup diagnostics, the instance guard and the CA endpoint.

Covers the regression that motivated the refactor: the console banner must never
advertise a wildcard address, a port that is not bound, or HTTPS that was never
verified, and paths must be resolved at runtime instead of hard-coded.
"""

import errno
import os

import pytest

import instance_guard
import startup_report


def _bind_error(code, message="socket error"):
    exc = OSError(message)
    exc.errno = code
    return exc


# ---------------------------------------------------------------------------
# Host / address helpers
# ---------------------------------------------------------------------------

def test_is_wildcard_accepts_every_any_address():
    for value in ("0.0.0.0", "::", "[::]", "", "  any  "):
        assert startup_report.is_wildcard(value) is True
    for value in ("127.0.0.1", "192.168.1.5", "localhost", "argos.local"):
        assert startup_report.is_wildcard(value) is False


def test_is_lan_candidate_rejects_non_lan_addresses():
    assert startup_report.is_lan_candidate("192.168.1.20") is True
    assert startup_report.is_lan_candidate("10.1.2.3") is True
    for value in ("127.0.0.1", "169.254.10.10", "224.0.0.1", "0.0.0.0", "::1", "not-an-ip"):
        assert startup_report.is_lan_candidate(value) is False


def test_collect_lan_ips_orders_primary_first(monkeypatch):
    monkeypatch.setattr(startup_report, "_default_route_ip", lambda: "192.168.1.5")
    monkeypatch.setattr(
        startup_report,
        "_hostname_addresses",
        lambda: [("169.254.1.2", "host name"), ("10.0.0.7", "host name")],
    )
    monkeypatch.setattr(
        startup_report,
        "_windows_adapter_addresses",
        lambda: [
            {"ip": "172.20.10.1", "kind": "virtual", "label": "vEthernet (WSL)"},
            {"ip": "192.168.1.5", "kind": "additional", "label": "Ethernet0"},
        ],
    )

    entries = startup_report.collect_lan_ips()

    assert [entry["ip"] for entry in entries] == ["192.168.1.5", "10.0.0.7", "172.20.10.1"]
    assert entries[0]["kind"] == "primary"
    assert entries[-1]["kind"] == "virtual"


def test_collect_lan_ips_without_network_returns_empty(monkeypatch):
    monkeypatch.setattr(startup_report, "_default_route_ip", lambda: None)
    monkeypatch.setattr(startup_report, "_hostname_addresses", lambda: [])
    monkeypatch.setattr(startup_report, "_windows_adapter_addresses", lambda: [])
    assert startup_report.collect_lan_ips() == []


# ---------------------------------------------------------------------------
# Readiness probe
# ---------------------------------------------------------------------------

def test_wait_for_port_retries_until_open(monkeypatch):
    attempts = {"count": 0}

    class _Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    def fake_create_connection(_address, timeout=None):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise OSError("refused")
        return _Connection()

    monkeypatch.setattr(startup_report.socket, "create_connection", fake_create_connection)
    monkeypatch.setattr(startup_report.time, "sleep", lambda _seconds: None)

    assert startup_report.wait_for_port("127.0.0.1", 8443, timeout=2.0) is True
    assert attempts["count"] == 3


def test_wait_for_port_gives_up_after_timeout(monkeypatch):
    def always_refused(_address, timeout=None):
        raise OSError("refused")

    monkeypatch.setattr(startup_report.socket, "create_connection", always_refused)
    monkeypatch.setattr(startup_report.time, "sleep", lambda _seconds: None)

    assert startup_report.wait_for_port("127.0.0.1", 8443, timeout=0) is False


# ---------------------------------------------------------------------------
# Bind error reporting
# ---------------------------------------------------------------------------

def test_describe_bind_error_in_use_includes_pid_and_netstat(monkeypatch):
    monkeypatch.setattr(startup_report, "find_port_owner", lambda _port: (4321, r"C:\Other\other.exe"))

    text = startup_report.describe_bind_error(_bind_error(10048, "in use"), "0.0.0.0", 8080, r"C:\AW\config.json")

    assert "[CRITICAL ERROR]" in text
    assert "Port 8080 is already in use" in text
    assert "PID 4321" in text
    assert "netstat -ano | findstr :8080" in text
    assert r"C:\AW\config.json" in text


def test_describe_bind_error_host_not_assigned():
    text = startup_report.describe_bind_error(_bind_error(10049), "192.168.1.150", 8080)
    assert "is not assigned to this computer" in text
    assert "0.0.0.0" in text


def test_describe_bind_error_reserved_port_mentions_excluded_ranges():
    text = startup_report.describe_bind_error(_bind_error(10013), "0.0.0.0", 8080)
    assert "excludedportrange" in text
    assert "Hyper-V" in text


def test_describe_bind_error_falls_back_to_generic_message():
    text = startup_report.describe_bind_error(_bind_error(errno.EINVAL, "bad address"), "0.0.0.0", 8080)
    assert "Cannot bind 0.0.0.0:8080" in text
    assert "bad address" in text


# ---------------------------------------------------------------------------
# Banner rendering
# ---------------------------------------------------------------------------

def _state(**overrides):
    state = {
        "version": "1.0.0",
        "data_dir": r"C:\Program Files\ArgosWorks\data",
        "log_file": r"C:\Program Files\ArgosWorks\logs\startup.log",
        "db_label": "PostgreSQL 16 (embedded)",
        "db_endpoint": "127.0.0.1:5432",
        "engine": "Waitress WSGI, 64 worker threads",
        "urls": [
            ("https://localhost:8443", "HTTPS via embedded Caddy"),
            ("http://127.0.0.1:8080", "HTTP direct"),
            ("http://192.168.1.50:8080", "LAN"),
            ("http://ARGOS-SRV:8080", "host name, if resolvable"),
        ],
        "ports": [
            {"port": "8080", "proto": "HTTP", "detail": "Waitress WSGI, 64 worker threads", "bind": "IPv4 any", "up": True},
            {"port": "8443", "proto": "HTTPS", "detail": "Embedded Caddy reverse proxy", "bind": "IPv4+IPv6 any", "up": True},
            {"port": "5432", "proto": "DB", "detail": "Embedded PostgreSQL 16", "bind": "127.0.0.1 only", "up": True},
        ],
        "integrations": [("Jira sync", "Inactive (config.json)")],
        "https": {
            "lines": [
                "Status        : enabled (embedded Caddy on :8443)",
                r"Root CA file  : C:\Program Files\ArgosWorks\data\caddy\pki\authorities\local\root.crt",
            ]
        },
    }
    state.update(overrides)
    return state


def test_banner_never_prints_a_wildcard_address():
    banner = startup_report.build_banner(_state())
    assert "0.0.0.0" not in banner
    assert "[::]" not in banner


def test_banner_marks_ready_only_after_ports_are_listed():
    banner = startup_report.build_banner(_state())
    assert "[READY]" in banner
    assert banner.index("LISTENING PORTS") < banner.index("[READY]")


def test_banner_reports_port_state():
    state = _state()
    state["ports"][1]["up"] = False
    banner = startup_report.build_banner(state)
    assert "[down]" in banner
    assert "8443" in banner


def test_banner_shows_https_disabled_explanation():
    state = _state(
        urls=[("http://127.0.0.1:8080", "HTTP direct")],
        https={"lines": ["Status        : HTTP only (no embedded Caddy and no ssl_certfile/ssl_keyfile)"]},
    )
    banner = startup_report.build_banner(state)
    assert "HTTP only" in banner
    assert "https://localhost:8443" not in banner


def test_banner_without_urls_says_so():
    banner = startup_report.build_banner(_state(urls=[]))
    assert "(none - no usable network address was detected)" in banner


# ---------------------------------------------------------------------------
# Certificate discovery (per-install first, per-user fallback)
# ---------------------------------------------------------------------------

def test_caddy_data_dirs_prefers_install_directory(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))

    dirs = startup_report.caddy_data_dirs(str(tmp_path / "install"))

    assert dirs[0] == os.path.join(str(tmp_path / "install"), "data", "caddy")
    assert len(dirs) == len(set(dirs))


def test_find_caddy_root_ca_reads_install_directory(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))

    ca = tmp_path / "install" / "data" / "caddy" / "pki" / "authorities" / "local" / "root.crt"
    ca.parent.mkdir(parents=True)
    ca.write_text("-----BEGIN CERTIFICATE-----", encoding="utf-8")

    assert startup_report.find_caddy_root_ca(str(tmp_path / "install")) == str(ca)


def test_find_caddy_root_ca_returns_none_when_absent(monkeypatch, tmp_path):
    for name in ("APPDATA", "LOCALAPPDATA", "XDG_DATA_HOME"):
        monkeypatch.setenv(name, str(tmp_path / "empty"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    assert startup_report.find_caddy_root_ca(str(tmp_path / "install")) is None


def test_find_caddy_root_ca_ignores_foreign_user_profile_ca(monkeypatch, tmp_path):
    """An installation without Caddy must not expose another app's user-profile CA."""
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))

    foreign = tmp_path / "roaming" / "Caddy" / "pki" / "authorities" / "local" / "root.crt"
    foreign.parent.mkdir(parents=True)
    foreign.write_text("cert", encoding="utf-8")

    assert startup_report.find_caddy_root_ca(str(tmp_path / "install")) is None


def test_find_caddy_root_ca_uses_legacy_profile_when_caddy_is_bundled(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))

    install = tmp_path / "install"
    (install / "vendor" / "caddy").mkdir(parents=True)
    (install / "vendor" / "caddy" / "caddy.exe").write_text("bin", encoding="utf-8")
    legacy = tmp_path / "roaming" / "Caddy" / "pki" / "authorities" / "local" / "root.crt"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("cert", encoding="utf-8")

    assert startup_report.find_caddy_root_ca(str(install)) == str(legacy)


# ---------------------------------------------------------------------------
# Startup log
# ---------------------------------------------------------------------------

def test_write_startup_log_appends_every_start(tmp_path):
    log_dir = str(tmp_path / "logs")

    first = startup_report.write_startup_log(log_dir, "first run")
    second = startup_report.write_startup_log(log_dir, "second run")

    assert first == second
    with open(first, encoding="utf-8") as handle:
        content = handle.read()
    assert len([line for line in content.splitlines() if line.startswith("====")]) == 2
    assert "first run" in content and "second run" in content


def test_write_startup_log_never_raises_on_unwritable_path(tmp_path):
    blocked = tmp_path / "file-not-a-dir"
    blocked.write_text("x", encoding="utf-8")
    assert startup_report.write_startup_log(str(blocked), "boom") is None


# ---------------------------------------------------------------------------
# Single instance guard
# ---------------------------------------------------------------------------

def test_instance_guard_allows_only_one_owner(tmp_path):
    app_home = str(tmp_path)
    try:
        acquired, holder = instance_guard.acquire(app_home, {"pid": 1, "port": 8080})
        assert acquired is True
        assert holder is None

        acquired_again, holder_again = instance_guard.acquire(app_home, {"pid": 2, "port": 8081})
        assert acquired_again is False
        assert holder_again["pid"] == 1
        assert holder_again["port"] == 8080
    finally:
        instance_guard.release()

    acquired_after_release, _ = instance_guard.acquire(app_home, {"pid": 3, "port": 8082})
    assert acquired_after_release is True
    assert instance_guard.read_holder(app_home)["pid"] == 3
    instance_guard.release()


def test_instance_guard_read_holder_handles_missing_file(tmp_path):
    assert instance_guard.read_holder(str(tmp_path)) is None


# ---------------------------------------------------------------------------
# Root CA download endpoint
# ---------------------------------------------------------------------------

class _FakeHandler:
    def __init__(self):
        self.status = None
        self.payload = None
        self.streamed = None

    def _send_json(self, status, payload, extra_headers=None):
        self.status = status
        self.payload = payload

    def _stream_file(self, path, content_type, download_name=None, inline=False, extra_headers=None):
        self.streamed = {
            "path": path,
            "content_type": content_type,
            "download_name": download_name,
            "inline": inline,
        }


def test_root_ca_route_is_mapped():
    from router import handle_get_root_ca, match_get

    route_type, target, content_type = match_get("/argos-root-ca.crt")

    assert route_type == "handler"
    assert target is handle_get_root_ca
    assert content_type is None


def test_root_ca_endpoint_404_before_ca_exists(monkeypatch):
    from router import handle_get_root_ca

    monkeypatch.setattr(startup_report, "find_caddy_root_ca", lambda _app_home=None: None)
    handler = _FakeHandler()

    handle_get_root_ca(handler, None, "127.0.0.1")

    assert handler.status == 404
    assert handler.streamed is None


def test_root_ca_endpoint_streams_only_the_public_certificate(monkeypatch, tmp_path):
    from router import handle_get_root_ca

    ca = tmp_path / "root.crt"
    ca.write_text("-----BEGIN CERTIFICATE-----", encoding="utf-8")
    monkeypatch.setattr(startup_report, "find_caddy_root_ca", lambda _app_home=None: str(ca))
    handler = _FakeHandler()

    handle_get_root_ca(handler, None, "127.0.0.1")

    assert handler.streamed["path"] == str(ca)
    assert handler.streamed["content_type"] == "application/x-x509-ca-cert"
    assert handler.streamed["download_name"] == "argos-root-ca.crt"
    assert "root.key" not in handler.streamed["path"]
    assert handler.streamed["inline"] is False
