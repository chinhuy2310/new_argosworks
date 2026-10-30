#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""startup_report.py - runtime startup diagnostics for the ARGOS WORKS console.

Every value printed by the startup banner (installation paths, listening
addresses, port states, certificate location) is resolved at runtime from the
machine that is actually starting the server. Nothing in this module is tied to
a specific computer, user account or install directory, so the same executable
reports correct information after it is moved to another folder, another
Windows account or another machine.

The module is standard-library only and keeps every side effect inside small
helpers so each one can be unit tested in isolation.
"""

import errno
import ipaddress
import os
import socket
import sys
import time
from datetime import datetime

RULE = "=" * 64
SUBRULE = "-" * 64

WILDCARD_HOSTS = frozenset({"", "0.0.0.0", "::", "[::]", "*", "any"})

# Adapters that are usually NOT reachable from another computer on the LAN.
VIRTUAL_ADAPTER_MARKERS = (
    "hyper-v", "vethernet", "virtualbox", "vmware", "wsl", "docker",
    "tap-windows", "tap adapter", "loopback", "npcap", "vpn", "wireguard",
    "tailscale", "zerotier", "bluetooth", "teredo", "isatap",
)

CADDY_HTTP_PORT = 8443
POSTGRES_PORT = 5432
OLLAMA_PORT = 11434


def is_wildcard(host):
    """True when *host* is a bind address that means "every interface"."""
    return (host or "").strip().lower() in WILDCARD_HOSTS


def wait_for_port(host, port, timeout=5.0, interval=0.1):
    """Block until host:port accepts TCP connections, or the timeout elapses."""
    deadline = time.monotonic() + max(0.0, float(timeout))
    attempt_timeout = min(0.5, max(0.05, float(timeout)))
    while True:
        try:
            with socket.create_connection((host, int(port)), timeout=attempt_timeout):
                return True
        except OSError:
            pass
        if time.monotonic() >= deadline:
            return False
        time.sleep(interval)


def is_lan_candidate(value):
    """True for a usable IPv4 LAN address (no loopback, APIPA, multicast...)."""
    try:
        addr = ipaddress.ip_address(str(value).strip())
    except ValueError:
        return False
    return not (
        addr.version != 4
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_unspecified
        or addr.is_reserved
    )


def _default_route_ip():
    """IPv4 address of the interface used for outbound traffic (no packet sent)."""
    for probe in ("8.8.8.8", "1.1.1.1", "10.255.255.255"):
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(0.2)
            sock.connect((probe, 80))
            candidate = sock.getsockname()[0]
        except OSError:
            candidate = ""
        finally:
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
        if candidate and is_lan_candidate(candidate):
            return candidate
    return None


def _hostname_addresses():
    """IPv4 addresses registered for this host name (offline/air-gapped fallback)."""
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except OSError:
        return []
    result = []
    for info in infos:
        try:
            result.append((info[4][0], "host name"))
        except (IndexError, TypeError):
            continue
    return result


def collect_lan_ips():
    """Ordered list of IPv4 addresses this host can be reached on.

    Each entry: {"ip": str, "kind": "primary"|"additional"|"virtual", "label": str}
    The first "primary" entry is the address other computers on the LAN should
    normally use; virtual/VPN adapters are kept but clearly marked.
    """
    entries = []
    seen = set()

    def add(ip, kind, label):
        ip = (ip or "").strip()
        if not ip or ip in seen or not is_lan_candidate(ip):
            return
        seen.add(ip)
        entries.append({"ip": ip, "kind": kind, "label": label})

    primary = _default_route_ip()
    if primary:
        add(primary, "primary", "default route")

    for ip, label in _hostname_addresses():
        add(ip, "additional", label)

    for item in _windows_adapter_addresses():
        add(item["ip"], item["kind"], item["label"])

    return entries


def _adapter_kind(name, description):
    marker = ("%s %s" % (name or "", description or "")).lower()
    if any(token in marker for token in VIRTUAL_ADAPTER_MARKERS):
        return "virtual"
    return "additional"


def _windows_adapter_addresses():
    """Windows only: real adapter list (friendly name + unicast IPv4).

    Uses GetAdaptersAddresses through ctypes so that VirtualBox/Hyper-V/VPN
    adapters can be labelled instead of being advertised as the LAN address.
    Any failure simply returns an empty list - the caller still has the
    default-route and host-name fallbacks.
    """
    if sys.platform != "win32":
        return []
    try:
        import ctypes

        class _SockAddr(ctypes.Structure):
            _fields_ = [("sa_family", ctypes.c_ushort), ("sa_data", ctypes.c_ubyte * 26)]

        class _SocketAddress(ctypes.Structure):
            _fields_ = [("lpSockaddr", ctypes.POINTER(_SockAddr)), ("iSockaddrLength", ctypes.c_int)]

        class _Unicast(ctypes.Structure):
            pass

        _Unicast._fields_ = [
            ("Length", ctypes.c_ulong),
            ("Flags", ctypes.c_ulong),
            ("Next", ctypes.POINTER(_Unicast)),
            ("Address", _SocketAddress),
            ("PrefixOrigin", ctypes.c_int),
            ("SuffixOrigin", ctypes.c_int),
            ("DadState", ctypes.c_int),
            ("ValidLifetime", ctypes.c_ulong),
            ("PreferredLifetime", ctypes.c_ulong),
            ("LeaseLifetime", ctypes.c_ulong),
            ("OnLinkPrefixLength", ctypes.c_ubyte),
        ]

        class _Adapter(ctypes.Structure):
            pass

        _Adapter._fields_ = [
            ("Length", ctypes.c_ulong),
            ("IfIndex", ctypes.c_ulong),
            ("Next", ctypes.POINTER(_Adapter)),
            ("AdapterName", ctypes.c_char_p),
            ("FirstUnicastAddress", ctypes.POINTER(_Unicast)),
            ("FirstAnycastAddress", ctypes.c_void_p),
            ("FirstMulticastAddress", ctypes.c_void_p),
            ("FirstDnsServerAddress", ctypes.c_void_p),
            ("DnsSuffix", ctypes.c_wchar_p),
            ("Description", ctypes.c_wchar_p),
            ("FriendlyName", ctypes.c_wchar_p),
            ("PhysicalAddress", ctypes.c_ubyte * 8),
            ("PhysicalAddressLength", ctypes.c_ulong),
            ("Flags", ctypes.c_ulong),
            ("Mtu", ctypes.c_ulong),
            ("IfType", ctypes.c_ulong),
            ("OperStatus", ctypes.c_int),
        ]

        iphlpapi = ctypes.WinDLL("iphlpapi.dll")
        get_adapters = iphlpapi.GetAdaptersAddresses
        get_adapters.argtypes = [
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_void_p,
            ctypes.POINTER(_Adapter),
            ctypes.POINTER(ctypes.c_ulong),
        ]
        get_adapters.restype = ctypes.c_ulong

        buffer_size = ctypes.c_ulong(16 * 1024)
        flags = 0x0002 | 0x0004  # GAA_FLAG_SKIP_ANYCAST | GAA_FLAG_SKIP_MULTICAST
        family = socket.AF_INET

        def _query():
            words = (buffer_size.value + 7) // 8
            buffer = (ctypes.c_uint64 * words)()
            code = get_adapters(
                family, flags, None, ctypes.cast(buffer, ctypes.POINTER(_Adapter)), ctypes.byref(buffer_size)
            )
            return code, buffer

        code, buffer = _query()
        if code == 111:  # ERROR_BUFFER_OVERFLOW - retry with the reported size
            code, buffer = _query()
        if code != 0:
            return []

        entries = []
        node = ctypes.cast(buffer, ctypes.POINTER(_Adapter))
        while node:
            adapter = node.contents
            name = (adapter.FriendlyName or adapter.Description or "").strip()
            kind = _adapter_kind(name, adapter.Description)
            label = name or "network adapter"
            if adapter.OperStatus == 1:  # IfOperStatusUp
                unicast = adapter.FirstUnicastAddress
                while unicast:
                    address = unicast.contents.Address
                    if address.lpSockaddr and address.lpSockaddr.contents.sa_family == socket.AF_INET:
                        raw = bytes(address.lpSockaddr.contents.sa_data[2:6])
                        entries.append(
                            {"ip": ".".join(str(part) for part in raw), "kind": kind, "label": label}
                        )
                    unicast = unicast.contents.Next
            node = adapter.Next
        return entries
    except Exception:
        return []


def caddy_data_dirs(app_home=None):
    """Candidate Caddy data directories, install-local directory first."""
    candidates = []
    if app_home:
        candidates.append(os.path.join(app_home, "data", "caddy"))
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        candidates.append(os.path.join(xdg_data_home, "caddy"))
    appdata = os.environ.get("APPDATA")  # Windows roaming profile (Caddy default)
    if appdata:
        candidates.append(os.path.join(appdata, "Caddy"))
    localappdata = os.environ.get("LOCALAPPDATA")
    if localappdata:
        candidates.append(os.path.join(localappdata, "Caddy"))
    home = os.path.expanduser("~")
    candidates.append(os.path.join(home, ".local", "share", "caddy"))
    candidates.append(os.path.join(home, "Library", "Application Support", "Caddy"))

    unique = []
    for path in candidates:
        if path and path not in unique:
            unique.append(path)
    return unique


def _has_embedded_caddy(app_home):
    """True when this installation ships its own Caddy binary."""
    if not app_home:
        return False
    for parts in (("caddy", "caddy.exe"), ("caddy", "caddy"), ("vendor", "caddy", "caddy.exe"), ("vendor", "caddy", "caddy")):
        if os.path.isfile(os.path.join(app_home, *parts)):
            return True
    return False


def find_caddy_root_ca(app_home=None):
    """Readable path of the root CA that belongs to *this* installation, or None.

    The installation-local CA wins. The legacy per-user ``%APPDATA%\\Caddy`` copy
    is only consulted when the installation actually ships Caddy (upgrade from a
    build that used Caddy's default storage), so an unrelated user-profile CA is
    never reported or served by an installation without Caddy.
    """
    if app_home:
        local = os.path.join(app_home, "data", "caddy", "pki", "authorities", "local", "root.crt")
        if os.path.isfile(local):
            return local
        if not _has_embedded_caddy(app_home):
            return None
    for base in caddy_data_dirs(app_home):
        candidate = os.path.join(base, "pki", "authorities", "local", "root.crt")
        if os.path.isfile(candidate):
            return candidate
    return None


def _windows_listening_pid(port):
    """PID listening on *port* (Windows only, best effort)."""
    try:
        import ctypes

        class _TcpRow(ctypes.Structure):
            _fields_ = [
                ("dwState", ctypes.c_ulong),
                ("dwLocalAddr", ctypes.c_ulong),
                ("dwLocalPort", ctypes.c_ulong),
                ("dwRemoteAddr", ctypes.c_ulong),
                ("dwRemotePort", ctypes.c_ulong),
                ("dwOwningPid", ctypes.c_ulong),
            ]

        tcp_table_owner_pid_listener = 3
        iphlpapi = ctypes.WinDLL("iphlpapi.dll")
        get_table = iphlpapi.GetExtendedTcpTable
        get_table.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.c_int,
            ctypes.c_ulong,
            ctypes.c_int,
            ctypes.c_ulong,
        ]
        get_table.restype = ctypes.c_ulong

        size = ctypes.c_ulong(0)
        get_table(None, ctypes.byref(size), 0, socket.AF_INET, tcp_table_owner_pid_listener, 0)
        if not size.value:
            return None
        words = (size.value + 7) // 8
        buffer = (ctypes.c_uint64 * words)()
        code = get_table(
            ctypes.cast(buffer, ctypes.c_void_p),
            ctypes.byref(size),
            0,
            socket.AF_INET,
            tcp_table_owner_pid_listener,
            0,
        )
        if code != 0:
            return None

        row_count = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ulong)).contents.value
        base = ctypes.addressof(buffer) + ctypes.sizeof(ctypes.c_ulong)
        rows = ctypes.cast(base, ctypes.POINTER(_TcpRow))
        for index in range(row_count):
            row = rows[index]
            if socket.ntohs(row.dwLocalPort & 0xFFFF) == int(port) and row.dwOwningPid:
                return int(row.dwOwningPid)
    except Exception:
        return None
    return None


def _windows_process_image(pid):
    """Executable path of *pid* (Windows only, best effort)."""
    try:
        import ctypes

        process_query_limited_information = 0x1000
        kernel32 = ctypes.WinDLL("kernel32.dll")
        kernel32.OpenProcess.restype = ctypes.c_void_p
        handle = kernel32.OpenProcess(process_query_limited_information, False, int(pid))
        if not handle:
            return None
        try:
            capacity = ctypes.c_ulong(1024)
            buffer = ctypes.create_unicode_buffer(capacity.value)
            kernel32.QueryFullProcessImageNameW.argtypes = [
                ctypes.c_void_p,
                ctypes.c_ulong,
                ctypes.c_wchar_p,
                ctypes.POINTER(ctypes.c_ulong),
            ]
            if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(capacity)):
                return buffer.value or None
        finally:
            kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel32.CloseHandle(handle)
    except Exception:
        return None
    return None


def find_port_owner(port):
    """(pid, executable path) of the process listening on *port*, or None."""
    if sys.platform != "win32":
        return None
    pid = _windows_listening_pid(port)
    if not pid:
        return None
    return pid, _windows_process_image(pid)


def describe_bind_error(exc, host, port, config_path=None, log_path=None):
    """Actionable English explanation of a socket bind failure."""
    winerror = getattr(exc, "winerror", None)
    code = winerror if winerror is not None else getattr(exc, "errno", None)
    reason = (getattr(exc, "strerror", None) or str(exc) or "").strip()
    target = "%s:%s" % (host, port)

    lines = ["[CRITICAL ERROR] Failed to start ARGOS WORKS Server!"]

    if code in (10048, 98):
        owner = find_port_owner(port)
        detail = ""
        if owner:
            pid, image = owner
            detail = " (PID %s%s)" % (pid, ", %s" % image if image else "")
        lines.append(" Cause : Port %s is already in use by another process%s." % (port, detail))
        lines.append(" Action required:")
        lines.append("   1. Close the application that is using port %s, or" % port)
        lines.append("   2. Change \"server.port\" in: %s" % (config_path or "config.json"))
        lines.append(" Diagnosis:")
        lines.append("   netstat -ano | findstr :%s" % port)
        if owner:
            lines.append("   tasklist /FI \"PID eq %s\"" % owner[0])
    elif code in (10049, 99):
        lines.append(" Cause : The configured host %s is not assigned to this computer." % host)
        lines.append(" Action required:")
        lines.append("   Set \"server.host\" to \"0.0.0.0\" (all interfaces) or to an address")
        lines.append("   shown by \"ipconfig\" in: %s" % (config_path or "config.json"))
    elif code in (10013, 13):
        lines.append(" Cause : Windows rejected the bind on %s (reserved range or permissions)." % target)
        lines.append(" Action required:")
        lines.append("   1. List reserved ranges: netsh int ipv4 show excludedportrange protocol=tcp")
        lines.append("   2. Pick a port outside those ranges in: %s" % (config_path or "config.json"))
        lines.append("   Hint: Hyper-V / WSL / Docker often reserve large blocks around 8000-9000.")
    else:
        lines.append(" Cause : Cannot bind %s - %s" % (target, reason or "unknown socket error"))
        lines.append(" Action required:")
        lines.append("   Verify \"server.host\"/\"server.port\" in: %s" % (config_path or "config.json"))

    if log_path:
        lines.append(" Full details are written to: %s" % log_path)
    return "\n".join(lines)


def build_banner(state):
    """Render the startup banner from a runtime *state* dictionary."""
    lines = []
    add = lines.append

    add(RULE)
    add(" ARGOS WORKS Server   v%s" % state.get("version", "0.0.0"))
    add(RULE)
    add(" Data directory : %s" % state.get("data_dir", ""))
    add(" Log file       : %s" % state.get("log_file", ""))
    add(" Database       : %s" % state.get("db_label", ""))
    add(" DB endpoint    : %s" % state.get("db_endpoint", ""))
    add(" Server engine  : %s" % state.get("engine", ""))
    add("")

    add(" ACCESS URLS")
    urls = state.get("urls") or []
    if not urls:
        add("   (none - no usable network address was detected)")
    for url, note in urls:
        add("   %s%s" % (url, ("   (%s)" % note) if note else ""))
    add("")

    add(" LISTENING PORTS")
    for item in state.get("ports") or []:
        add(
            "   %-6s %-6s %-40s %-16s [%s]"
            % (
                item.get("port", ""),
                item.get("proto", ""),
                item.get("detail", ""),
                item.get("bind", ""),
                "up" if item.get("up") else "down",
            )
        )
    add("")

    add(" INTEGRATIONS")
    for name, value in state.get("integrations") or []:
        add("   %-16s: %s" % (name, value))
    add("")

    add(" HTTPS ON THE LOCAL NETWORK")
    for line in (state.get("https") or {}).get("lines") or []:
        add("   %s" % line)
    add(SUBRULE)
    add(" [READY] All services are initialized and ready to serve.")
    add(" Press Ctrl+C in this window to stop the server.")
    add(RULE)
    return "\n".join(lines)


def write_startup_log(log_dir, text):
    """Append *text* to <log_dir>/startup.log and return the path (or None)."""
    try:
        os.makedirs(log_dir, exist_ok=True)
        path = os.path.join(log_dir, "startup.log")
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("==== %s ====\n" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            handle.write((text or "").rstrip() + "\n")
        return path
    except OSError:
        return None
