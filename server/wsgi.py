#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ARGOS WORKS - Enterprise WSGI Application Entrypoint (PEP 3333)
Production-grade WSGI interface supporting Waitress, Gunicorn, and uWSGI.
Replaces legacy http.server to deliver enterprise concurrency, security compliance,
robust HTTP header validation, and seamless SSE streaming.
"""
import sys
import os
import io
import threading
import http.client
from http.client import HTTPMessage

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Add server directory to path if needed
SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from config import load_config, ensure_dirs, ensure_seed_files, DATA_DIR, is_client_disconnect
from db import init_db, close_connection
from handler import ArgosHandler, JarvisHandler
from services.auth import cleanup_expired_sessions
from utils.logging import log_line

# Hop-by-hop headers forbidden in WSGI responses per PEP 3333
HOP_BY_HOP_HEADERS = frozenset({
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
})

_app_initialized = False
_init_lock = threading.Lock()


def _decode_wsgi_path(path):
    """
    Safely decode PEP 3333 latin-1 URI path to UTF-8.
    Supports non-ASCII paths (Korean/Japanese/Vietnamese filenames and URLs).
    """
    if not path:
        return "/"
    try:
        return path.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return path


def _session_cleanup_loop():
    import time
    while True:
        try:
            cleanup_expired_sessions()
        except Exception:
            pass
        time.sleep(3600)


def init_app():
    """Initializes configuration, database, and background daemons once."""
    global _app_initialized
    if _app_initialized:
        return
    with _init_lock:
        if _app_initialized:
            return

        ensure_dirs()
        ensure_seed_files()
        init_db()

        # Architecture Concurrency Warning for Multi-Process Deployments
        web_concurrency = os.environ.get("WEB_CONCURRENCY") or os.environ.get("GUNICORN_WORKERS")
        if web_concurrency:
            try:
                if int(web_concurrency) > 1:
                    log_line(
                        f"[ARCHITECTURE WARNING] Multi-process deployment detected (workers={web_concurrency}). "
                        "In-memory state (SSE notifications, login rate limiting, background schedulers) "
                        "requires single-process multi-threaded deployment (e.g. Waitress --threads=64 or "
                        "Gunicorn --workers=1 --threads=64) unless Redis is integrated."
                    )
            except ValueError:
                pass

        # Background session cleaner daemon
        threading.Thread(target=_session_cleanup_loop, daemon=True, name="SessionCleanup").start()

        cfg = load_config()
        ArgosHandler.cfg = cfg
        JarvisHandler.cfg = cfg
        from handler import check_trusted_proxies_warning
        check_trusted_proxies_warning()
        from middleware_security import _get_csrf_secret
        _get_csrf_secret()

        # Backup scheduler
        from services.backup_manager import start_backup_scheduler
        start_backup_scheduler(interval_hours=24)

        # Vector sync if configured
        from services.vector_store import is_voyage_configured, sync_all_vectors
        if is_voyage_configured(cfg):
            threading.Thread(target=sync_all_vectors, args=(cfg,), daemon=True).start()

        # Jira sync loops if enabled
        if cfg.get("jira", {}).get("enabled"):
            from services.jira_client import sync_jira_cache, jira_auto_sync_loop, check_jira_ssl_warning
            check_jira_ssl_warning(cfg)
            threading.Thread(target=sync_jira_cache, args=(cfg,), daemon=True).start()
            threading.Thread(target=jira_auto_sync_loop, args=(cfg,), daemon=True).start()

        _app_initialized = True


class WSGIWriter:
    """Provides a file-like .write() and .flush() interface over WSGI start_response callable."""
    def __init__(self, handler):
        self._handler = handler

    def write(self, data):
        if data:
            return self._handler._write_output(data)

    def flush(self):
        pass


class ArgosWSGIHandler(ArgosHandler):
    """
    WSGI Adapter for ArgosHandler.
    Translates PEP 3333 WSGI environment into ArgosHandler attributes and methods,
    allowing 100% of existing routes, security middleware, and handlers to execute unchanged.
    """
    def __init__(self, environ, start_response):
        self.environ = environ
        self._start_response = start_response
        self._status_code = 200
        self._status_message = "OK"
        self._headers_list = []
        self._headers_sent = False
        self._write_fn = None
        self.wfile = WSGIWriter(self)

        # Reconstruct path and command
        raw_path = environ.get("PATH_INFO", "/")
        path = _decode_wsgi_path(raw_path)
        qs = environ.get("QUERY_STRING", "")
        self.path = f"{path}?{qs}" if qs else path
        self.command = environ.get("REQUEST_METHOD", "GET").upper()

        # Reconstruct request headers (case-insensitive HTTPMessage)
        headers = HTTPMessage()
        for k, v in environ.items():
            if not v:
                continue
            if k == "CONTENT_TYPE":
                headers.add_header("Content-Type", str(v))
            elif k == "CONTENT_LENGTH":
                headers.add_header("Content-Length", str(v))
            elif k.startswith("HTTP_"):
                hdr = k[5:].replace("_", "-")
                headers.add_header(hdr, str(v))
        self.headers = headers

        # Client address
        remote_addr = environ.get("REMOTE_ADDR", "127.0.0.1")
        try:
            remote_port = int(environ.get("REMOTE_PORT", 0) or 0)
        except ValueError:
            remote_port = 0
        self.client_address = (remote_addr, remote_port)

        # Request body stream
        self.rfile = environ.get("wsgi.input") or io.BytesIO()
        self.connection = None

    def address_string(self):
        return self.client_address[0]

    def _is_secure(self):
        """Checks if request arrived via HTTPS (direct TLS, wsgi scheme, or reverse proxy header)."""
        scheme = (self.environ.get("wsgi.url_scheme") or "").lower()
        if scheme == "https":
            return True
        if self.environ.get("HTTPS") in ("on", "1"):
            return True
        proto = (self.headers.get("X-Forwarded-Proto") or "").lower()
        if proto == "https":
            return True
        return False

    def send_response(self, code, message=None):
        self._status_code = int(code)
        if message is None:
            self._status_message = http.client.responses.get(self._status_code, "OK")
        else:
            self._status_message = str(message)

    def send_header(self, keyword, value):
        self._headers_list.append((keyword, str(value)))

    def end_headers(self):
        self._send_headers_if_needed()

    def _send_headers_if_needed(self):
        if not self._headers_sent:
            status_str = f"{self._status_code} {self._status_message}".strip()
            # Strip hop-by-hop headers to strictly enforce PEP 3333 compliance
            clean_headers = [
                (k, v) for k, v in self._headers_list
                if k.lower() not in HOP_BY_HOP_HEADERS
            ]
            self._write_fn = self._start_response(status_str, clean_headers)
            self._headers_sent = True

    def _write_output(self, data):
        self._send_headers_if_needed()
        if self._write_fn and data:
            if isinstance(data, str):
                data = data.encode("utf-8")
            return self._write_fn(data)

    def dispatch(self):
        """Dispatch HTTP request according to method verb."""
        try:
            if self.command == "GET":
                self.do_GET()
            elif self.command == "POST":
                self.do_POST()
            elif self.command == "OPTIONS":
                self.do_OPTIONS()
            elif self.command == "HEAD":
                self.do_HEAD()
            else:
                self.send_response(405)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(b'{"ok": false, "error": "Method not allowed"}')
        finally:
            self._send_headers_if_needed()
            close_connection()


def application(environ, start_response):
    """
    Standard PEP 3333 WSGI Entrypoint.
    Compatible with Waitress, Gunicorn, uWSGI, and Caddy/Nginx reverse proxies.
    """
    init_app()
    handler = ArgosWSGIHandler(environ, start_response)
    try:
        handler.dispatch()
    except Exception as e:
        if is_client_disconnect(e):
            return []
        import traceback
        log_line("Unhandled WSGI exception:\n", traceback.format_exc())
        if not handler._headers_sent:
            try:
                start_response("500 Internal Server Error", [
                    ("Content-Type", "application/json; charset=utf-8"),
                    ("Cache-Control", "no-store"),
                ])
                return [b'{"ok": false, "error": "Internal server error"}']
            except Exception:
                pass
        return []
    return []


# Standard alias
app = application

if __name__ == "__main__":
    import waitress
    init_app()
    cfg = load_config()
    host = os.environ.get("HOST") or cfg.get("server", {}).get("host", "0.0.0.0")
    port = int(os.environ.get("PORT") or cfg.get("server", {}).get("port", 8080))
    print(f"Starting ARGOS WORKS production WSGI server on http://{host}:{port} via Waitress...")
    waitress.serve(application, host=host, port=port, threads=64, channel_timeout=60)
