#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""main.py - ARGOS WORKS server entrypoint.

Startup order is deliberate:

  1. console setup + global exception hooks
  2. configuration load and input validation
  3. single-instance guard (one process per data directory)
  4. embedded services (PostgreSQL / Caddy / Ollama) with readiness probes
  5. application init (database schema + background schedulers)
  6. bind the HTTP socket  -> a port conflict surfaces BEFORE any success banner
  7. banner + "[READY]" + serve

Everything printed at step 7 is derived from the state that actually exists, so
the console can never advertise a port, URL or certificate that is not there.
All console output is English; the process returns a non-zero exit code when it
cannot start (0 = running or reusing an instance, 1 = fatal, 2 = bad config).
"""

import os
import socket
import sys
import threading

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def _log_unhandled_exception(exc_type, exc_value, exc_traceback):
    try:
        from config import is_client_disconnect

        if exc_value and is_client_disconnect(exc_value):
            return
    except Exception:
        pass
    import traceback

    print("\n[CRITICAL UNHANDLED EXCEPTION]", file=sys.stderr, flush=True)
    traceback.print_exception(exc_type, exc_value, exc_traceback, file=sys.stderr)
    sys.stderr.flush()


sys.excepthook = _log_unhandled_exception
if hasattr(threading, "excepthook"):
    threading.excepthook = lambda args: _log_unhandled_exception(
        args.exc_type, args.exc_value, args.exc_traceback
    )

# Windows console: UTF-8 code page so the banner renders identically everywhere.
if sys.platform == "win32":
    try:
        import ctypes

        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
    except Exception:
        pass

from app_paths import APP_HOME, IS_FROZEN  # noqa: E402

EXIT_OK = 0
EXIT_FATAL = 1
EXIT_CONFIG = 2

_TRUTHY = ("1", "true", "yes", "on")


def _env_flag(name, default="0"):
    return os.environ.get(name, default).strip().lower() in _TRUTHY


def _pause_before_exit():
    """Keep the console open on a double-click start so the error can be read."""
    if not IS_FROZEN or _env_flag("ARGOS_NO_PAUSE"):
        return
    try:
        if sys.stdin and sys.stdin.isatty():
            input("\nPress Enter to exit...")
    except Exception:
        pass


def _fail(message, log_dir, code=EXIT_FATAL):
    """Persist an actionable error, print it, keep the window open, exit."""
    from startup_report import write_startup_log

    log_path = write_startup_log(log_dir, message)
    if log_path:
        message = "%s\n Full details are written to: %s" % (message, log_path)
    print(message, flush=True)
    _pause_before_exit()
    raise SystemExit(code)


def _resolve_host_port(cfg):
    """Validated (host, port) from environment or config.json."""
    host = str(os.environ.get("HOST") or cfg["server"].get("host", "0.0.0.0")).strip() or "0.0.0.0"
    raw_port = os.environ.get("PORT") or cfg["server"].get("port", 8080)
    try:
        port = int(raw_port)
    except (TypeError, ValueError):
        raise ValueError("server.port is not a number: %r" % (raw_port,))
    if not 1 <= port <= 65535:
        raise ValueError("server.port must be between 1 and 65535 (got %s)" % port)
    return host, port


def _probe_running_argos(port, timeout=1.5):
    """Version payload of an already-running ARGOS WORKS instance, or None."""
    import json
    import urllib.request

    try:
        url = "http://127.0.0.1:%d/api/version" % int(port)
        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload = json.loads(response.read(4096).decode("utf-8", "replace") or "{}")
    except Exception:
        return None
    if isinstance(payload, dict) and payload.get("version"):
        return payload
    return None


def _handle_second_instance(app_home, holder, data_dir, log_dir):
    """Explain who owns the data directory and reuse it when it is a live server."""
    import time

    from instance_guard import read_holder

    holder = holder or {}
    holder_port = holder.get("port")
    if not holder_port:
        # The owner may still be starting up (it writes its port after load_config).
        for _ in range(40):
            time.sleep(0.1)
            refreshed = read_holder(app_home) or {}
            if refreshed.get("port"):
                holder = refreshed
                holder_port = refreshed["port"]
                break
    holder_data_dir = holder.get("data_dir")
    same_dir = not holder_data_dir or os.path.normcase(str(holder_data_dir)) == os.path.normcase(data_dir)
    running = _probe_running_argos(holder_port) if holder_port else None

    if same_dir and running:
        url = "http://127.0.0.1:%s/" % holder_port
        print("=" * 64)
        print(" ARGOS WORKS Server is already running")
        print("=" * 64)
        print(" Data directory : %s" % data_dir)
        print(" Process        : PID %s, port %s" % (holder.get("pid", "?"), holder_port))
        print(" URL            : %s" % url)
        print("")
        print(" A data directory can only be served by one process, so this launch")
        print(" opens the existing session instead of starting a second server.")
        print(" Stop the running server (Ctrl+C in its window) to start a new one.")
        print("=" * 64)
        if not _env_flag("ARGOS_NO_BROWSER"):
            import webbrowser

            try:
                webbrowser.open(url)
            except Exception:
                pass
        return EXIT_OK

    message = (
        "[CRITICAL ERROR] The ARGOS WORKS data directory is already in use.\n"
        " Data directory : %s\n"
        " Owner          : PID %s (port %s)\n"
        " The owner did not answer http://127.0.0.1:%s/api/version, so it is still\n"
        " starting, stuck, or shutting down.\n"
        " Action required:\n"
        "   1. Close the other ARGOS WORKS window/process, then start again.\n"
        "   2. If no ARGOS WORKS window is open, terminate PID %s and retry."
        % (data_dir, holder.get("pid", "?"), holder_port or "?", holder_port or "?", holder.get("pid", "?"))
    )
    _fail(message, log_dir)
    return EXIT_FATAL


def _db_engine_status(data_dir):
    """(label, endpoint) of the active database engine; never prints credentials."""
    import db as db_module

    if getattr(db_module, "ENGINE", "sqlite") == "postgres":
        url = os.environ.get("DATABASE_URL", "")
        if "127.0.0.1" in url or "localhost" in url:
            return "PostgreSQL 16 (embedded)", "127.0.0.1:5432"
        return "PostgreSQL (external)", "configured through DATABASE_URL"
    return "SQLite (local file)", os.path.join(data_dir, "argos.db")


def _startup_state(cfg, host, port, proto, services, engine, direct_tls=False):
    """Assemble every value the banner prints, from what actually exists now."""
    from config import APP_VERSION, DATA_DIR, LOG_DIR
    from startup_report import (
        CADDY_HTTP_PORT,
        OLLAMA_PORT,
        POSTGRES_PORT,
        collect_lan_ips,
        find_caddy_root_ca,
        is_wildcard,
    )

    services = services or {}
    https_available = bool(services.get("caddy"))
    caddy_owned = bool(services.get("caddy_owned"))
    ca_path = find_caddy_root_ca(APP_HOME)
    db_label, db_endpoint = _db_engine_status(DATA_DIR)

    if host in ("127.0.0.1", "localhost", "::1"):
        mode = "loopback"
    elif is_wildcard(host):
        mode = "wildcard"
    else:
        mode = "specific"

    lan_ips = collect_lan_ips() if mode == "wildcard" else []
    urls = []
    if https_available:
        urls.append(("https://localhost:%d" % CADDY_HTTP_PORT, "HTTPS via embedded Caddy"))
        urls.append(("http://127.0.0.1:%d" % port, "HTTP direct"))
    elif proto == "https":
        urls.append(("https://localhost:%d" % port, "HTTPS, direct TLS"))
    else:
        urls.append(("http://127.0.0.1:%d" % port, "HTTP direct"))

    primary_ip = None
    if mode == "wildcard":
        if lan_ips:
            primary = next((entry for entry in lan_ips if entry["kind"] == "primary"), lan_ips[0])
            primary_ip = primary["ip"]
            urls.append(("http://%s:%d" % (primary_ip, port), "LAN"))
            if https_available:
                urls.append(("https://%s:%d" % (primary_ip, CADDY_HTTP_PORT), "LAN HTTPS, internal CA"))
            for entry in lan_ips:
                if entry is primary:
                    continue
                note = entry["label"]
                if entry["kind"] == "virtual":
                    note += " - virtual, may be unreachable"
                urls.append(("http://%s:%d" % (entry["ip"], port), note))
            urls.append(("http://%s:%d" % (socket.gethostname(), port), "host name, if resolvable"))
        else:
            urls.append(("(no LAN address detected)", "offline or no active adapter"))
    elif mode == "specific":
        primary_ip = host
        urls.append(("http://%s:%d" % (host, port), "configured host"))
        if https_available:
            urls.append(("https://%s:%d" % (host, CADDY_HTTP_PORT), "HTTPS, internal CA"))
    else:
        urls.append(("LAN URL not advertised", "server is bound to loopback only"))

    ca_url = None
    if ca_path:
        ca_host = primary_ip or "127.0.0.1"
        ca_url = "http://%s:%d/argos-root-ca.crt" % (ca_host, port)

    https_lines = []
    if https_available:
        if caddy_owned:
            https_lines.append("Status        : enabled (embedded Caddy on :%d)" % CADDY_HTTP_PORT)
        else:
            https_lines.append(
                "Status        : detected on :%d (listener started outside this process)" % CADDY_HTTP_PORT
            )
        default_ca = os.path.join(APP_HOME, "data", "caddy", "pki", "authorities", "local", "root.crt")
        https_lines.append("Root CA file  : %s" % (ca_path or default_ca))
        https_lines.append(
            "Certificate   : %s"
            % ("created" if ca_path else "not created yet - issued at the first HTTPS connection")
        )
        if ca_url:
            https_lines.append("Client setup  : open %s on the client PC and install it" % ca_url)
            https_lines.append("                as a Trusted Root CA (Administrator), then use the HTTPS LAN URL.")
        https_lines.append("Note          : trusting a root CA is a security decision - do it only on")
        https_lines.append("                company computers, otherwise use the HTTP URL above.")
    elif direct_tls:
        https_lines.append("Status        : enabled (native TLS on :%d, certificate from config.json)" % port)
    else:
        https_lines.append("Status        : HTTP only (no embedded Caddy and no ssl_certfile/ssl_keyfile)")
        https_lines.append("To enable     : install the bundled Caddy (vendor/caddy) or set")
        https_lines.append("                server.ssl_certfile + server.ssl_keyfile in config.json")

    bind = "IPv4 any" if host == "0.0.0.0" else ("IPv4+IPv6 any" if host == "::" else host)
    ports = [
        {"port": str(port), "proto": proto.upper(), "detail": engine, "bind": bind, "up": True},
        {
            "port": str(CADDY_HTTP_PORT),
            "proto": "HTTPS",
            "detail": "Embedded Caddy reverse proxy",
            "bind": "IPv4+IPv6 any",
            "up": https_available,
        },
    ]
    if db_endpoint == "127.0.0.1:5432":
        # Only advertise the embedded database port when it is the engine in use.
        ports.append(
            {
                "port": str(POSTGRES_PORT),
                "proto": "DB",
                "detail": "Embedded PostgreSQL 16",
                "bind": "127.0.0.1 only",
                "up": bool(services.get("postgres")),
            }
        )
    ollama_bundled = os.path.isfile(os.path.join(APP_HOME, "ollama", "ollama.exe")) or os.path.isfile(
        os.path.join(APP_HOME, "vendor", "ollama", "ollama.exe")
    )
    if ollama_bundled:
        ports.append(
            {
                "port": str(OLLAMA_PORT),
                "proto": "AI",
                "detail": "Embedded Ollama",
                "bind": "127.0.0.1 only",
                "up": bool(services.get("ollama")),
            }
        )

    integrations = []
    jira_active = bool(cfg.get("jira", {}).get("enabled") and cfg["jira"].get("api_token"))
    integrations.append(("Jira sync", "Active" if jira_active else "Inactive (config.json)"))
    try:
        from services.ai_client import get_ai_config

        ai_info = get_ai_config(cfg)
        if ai_info["enabled"] and (ai_info["api_key"] or ai_info["provider"] == "ollama"):
            ai_value = "Active (%s - %s)" % (ai_info["provider"].upper(), ai_info["model"])
        else:
            ai_value = "Inactive (rule-based classification fallback)"
    except Exception:
        ai_value = "Unknown (configuration error)"
    integrations.append(("AI service", ai_value))
    try:
        from services.vector_store import get_embedding_provider_info, is_voyage_configured

        if is_voyage_configured(cfg):
            vector_info = get_embedding_provider_info(cfg)
            vector_value = "Active (%s - %s) [vector_store.sqlite]" % (
                vector_info["provider"].upper(),
                vector_info["model"],
            )
        else:
            vector_value = "Inactive (keyword search fallback)"
    except Exception:
        vector_value = "Unknown (configuration error)"
    integrations.append(("Vector search", vector_value))
    integrations.append(("Auto backup", "Active (24h cycle, 14-day retention)"))

    return {
        "version": APP_VERSION,
        "data_dir": DATA_DIR,
        "log_file": os.path.join(LOG_DIR, "startup.log"),
        "db_label": db_label,
        "db_endpoint": db_endpoint,
        "engine": engine,
        "urls": urls,
        "ports": ports,
        "integrations": integrations,
        "https": {"lines": https_lines},
    }


def _run(cfg, host, port, services):
    """Bind the socket, report the real state, then serve.

    ``services`` comes from start_embedded_services(): it is collected *before*
    load_config() because config._load_env() publishes DATABASE_URL from .env,
    and start_embedded_services() only boots the embedded PostgreSQL when
    DATABASE_URL is still unset.
    """
    import ssl

    from config import CONFIG_PATH, LOG_DIR, load_config
    from startup_report import CADDY_HTTP_PORT, build_banner, describe_bind_error, write_startup_log

    services = services or {}

    if IS_FROZEN:
        try:
            from utils.crypto import get_master_key

            get_master_key()
        except Exception:
            pass

    from handler import ArgosHandler, JarvisHandler
    from wsgi import application, init_app

    init_app()
    cfg = load_config()
    ArgosHandler.cfg = cfg
    JarvisHandler.cfg = cfg

    ssl_cert = cfg.get("server", {}).get("ssl_certfile") or os.environ.get("ARGOS_SSL_CERT", "")
    ssl_key = cfg.get("server", {}).get("ssl_keyfile") or os.environ.get("ARGOS_SSL_KEY", "")
    is_ssl_configured = bool(
        ssl_cert and ssl_key and os.path.exists(ssl_cert) and os.path.exists(ssl_key)
    )
    proto = "https" if is_ssl_configured else "http"

    use_waitress = False
    if not _env_flag("ARGOS_USE_LEGACY_SERVER") and not is_ssl_configured:
        try:
            import waitress  # noqa: F401

            use_waitress = True
        except ImportError:
            use_waitress = False
    try:
        workers = int(os.environ.get("ARGOS_WORKER_THREADS", "64"))
    except ValueError:
        workers = 64

    server = None
    httpd = None

    if use_waitress:
        import waitress as waitress_module

        # Windows: waitress enables SO_REUSEADDR, which lets a second process bind
        # the same port silently and hide a real conflict. Bind the socket here with
        # SO_EXCLUSIVEADDRUSE and hand it to waitress instead.
        listen_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if sys.platform == "win32":
                listen_socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            else:
                listen_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listen_socket.bind((host, port))
        except OSError as exc:
            try:
                listen_socket.close()
            except OSError:
                pass
            _fail(describe_bind_error(exc, host, port, CONFIG_PATH), LOG_DIR)

        try:
            server = waitress_module.create_server(
                application,
                sockets=[listen_socket],
                threads=workers,
                channel_timeout=60,
                cleanup_interval=30,
                clear_untrusted_proxy_headers=False,
            )
        except OSError as exc:
            _fail(describe_bind_error(exc, host, port, CONFIG_PATH), LOG_DIR)
        except Exception as exc:
            _fail("[CRITICAL ERROR] Failed to start the WSGI server.\n Cause : %s" % exc, LOG_DIR)
        engine = "Waitress WSGI, %d worker threads" % workers
    else:
        from concurrent.futures import ThreadPoolExecutor
        from http.server import ThreadingHTTPServer

        class ArgosThreadingHTTPServer(ThreadingHTTPServer):
            daemon_threads = True
            request_queue_size = 512
            allow_reuse_address = False
            _pool = ThreadPoolExecutor(max_workers=128, thread_name_prefix="ArgosWorker")

            def server_bind(self):
                try:
                    if sys.platform == "win32":
                        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                    else:
                        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                except OSError:
                    pass
                super().server_bind()

            def process_request(self, request, client_address):
                self._pool.submit(self.process_request_thread, request, client_address)

            def server_close(self):
                super().server_close()
                self._pool.shutdown(wait=False)

        try:
            httpd = ArgosThreadingHTTPServer((host, port), ArgosHandler)
        except OSError as exc:
            _fail(describe_bind_error(exc, host, port, CONFIG_PATH), LOG_DIR)

        if is_ssl_configured:
            try:
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                context.load_cert_chain(certfile=ssl_cert, keyfile=ssl_key)
                httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
                print("[Security] Native TLS socket enabled.", flush=True)
            except Exception as exc:
                print("[Security Warning] Failed to apply native TLS: %s" % exc, flush=True)
        engine = "Standalone engine, 128 workers"

    state = _startup_state(cfg, host, port, proto, services, engine, direct_tls=is_ssl_configured)
    banner = build_banner(state)
    print(banner, flush=True)
    write_startup_log(LOG_DIR, banner)

    if IS_FROZEN and not _env_flag("ARGOS_NO_BROWSER"):
        import webbrowser

        browse_url = (
            "https://localhost:%d/" % CADDY_HTTP_PORT
            if services.get("caddy")
            else "http://127.0.0.1:%d/" % port
        )
        timer = threading.Timer(2.0, lambda: webbrowser.open(browse_url))
        timer.daemon = True
        timer.start()

    try:
        if server is not None:
            server.run()
        else:
            httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down ARGOS WORKS server...", flush=True)
    except Exception as exc:
        import traceback

        message = "[FATAL] Server error: %s" % exc
        print("\n" + message, file=sys.stderr, flush=True)
        traceback.print_exc()
        write_startup_log(LOG_DIR, message + "\n" + traceback.format_exc())
        return EXIT_FATAL
    finally:
        try:
            if server is not None:
                server.close()
            elif httpd is not None:
                httpd.server_close()
        except Exception:
            pass
    return EXIT_OK


def main():
    from config import APP_VERSION, CONFIG_PATH, DATA_DIR, LOG_DIR, ensure_dirs, load_config
    from instance_guard import acquire, release, update_meta

    ensure_dirs()

    # 1) Claim the data directory first: a second launch must not start services,
    #    touch the database or run schedulers before it is rejected.
    acquired, holder = acquire(
        APP_HOME,
        {"pid": os.getpid(), "data_dir": DATA_DIR, "version": APP_VERSION},
    )
    if not acquired:
        raise SystemExit(_handle_second_instance(APP_HOME, holder, DATA_DIR, LOG_DIR))

    try:
        # 2) Embedded PostgreSQL / Caddy must boot *before* load_config():
        #    config._load_env() publishes DATABASE_URL from .env, and
        #    start_embedded_services() only starts the embedded PostgreSQL while
        #    DATABASE_URL is still unset (same contract as the original entrypoint).
        services = {}
        try:
            from embedded_services import start_embedded_services

            services = start_embedded_services(APP_HOME) or {}
        except Exception as exc:
            print("[Embedded Services] Notice: %s" % exc, file=sys.stderr, flush=True)

        cfg = load_config()

        try:
            host, port = _resolve_host_port(cfg)
        except ValueError as exc:
            _fail('[CONFIGURATION ERROR] %s\n Fix "server" in: %s' % (exc, CONFIG_PATH), LOG_DIR, EXIT_CONFIG)

        update_meta(
            APP_HOME,
            {
                "pid": os.getpid(),
                "host": host,
                "port": port,
                "data_dir": DATA_DIR,
                "version": APP_VERSION,
            },
        )
        return _run(cfg, host, port, services)
    finally:
        release()


if __name__ == "__main__":
    sys.exit(main())
