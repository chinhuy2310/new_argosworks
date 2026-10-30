#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
import threading
from http.server import ThreadingHTTPServer

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
    threading.excepthook = lambda args: _log_unhandled_exception(args.exc_type, args.exc_value, args.exc_traceback)

# Ensure Windows console uses UTF-8 code page (65001) for clear rendering
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
    except Exception:
        pass

# Initialize embedded PostgreSQL 16 & Caddy BEFORE importing db.py
# so that os.environ["DATABASE_URL"] is set and db.py binds to the PostgreSQL engine!
from app_paths import IS_FROZEN, APP_HOME
try:
    from embedded_services import start_embedded_services
    start_embedded_services(APP_HOME)
except Exception as _exc:
    print("[Embedded Services] Notice:", _exc, file=sys.stderr, flush=True)

if IS_FROZEN:
    try:
        from utils.crypto import get_master_key
        get_master_key()
    except Exception:
        pass

from config import load_config, ensure_dirs, ensure_seed_files, DATA_DIR
from db import init_db
from handler import ArgosHandler, JarvisHandler
from services.jira_client import sync_jira_cache, jira_auto_sync_loop
from services.auth import cleanup_expired_sessions
from wsgi import init_app, application

def _db_engine_status():
    """Returns the active database engine name."""
    import db as db_module
    label = "PostgreSQL 16 (Embedded)" if db_module.ENGINE == "postgres" else "SQLite (Local File)"
    warning = ""
    return label, warning

def _session_cleanup_loop():
    import time
    while True:
        try:
            cleanup_expired_sessions()
        except Exception:
            pass
        time.sleep(3600)  # Clean up expired sessions once every hour

def main():
    init_app()
    cfg = load_config()
    ArgosHandler.cfg = cfg
    JarvisHandler.cfg = cfg

    import os
    host = os.environ.get("HOST") or cfg["server"].get("host", "0.0.0.0")
    port = int(os.environ.get("PORT") or cfg["server"].get("port", 8080))

    jira_state = "사용" if (cfg["jira"].get("enabled") and cfg["jira"].get("api_token")) else "미사용 (config.json 설정 필요)"

    from services.ai_client import get_ai_config
    ai_info = get_ai_config(cfg)
    if ai_info["enabled"] and (ai_info["api_key"] or ai_info["provider"] == "ollama"):
        ai_state = f"사용 ({ai_info['provider'].upper()} - {ai_info['model']})"
    else:
        ai_state = "미사용 (규칙 기반 분류로 대체)"

    from services.vector_store import is_voyage_configured, sync_all_vectors, get_vector_stats, get_embedding_provider_info
    if is_voyage_configured(cfg):
        v_info = get_embedding_provider_info(cfg)
        vector_state = f"사용 ({v_info['provider'].upper()} - {v_info['model']}) [vector_store.sqlite]"
    else:
        vector_state = "미사용 (키워드 검색 사용)"

    # SSL/TLS 설정 확인 (직접 TLS 바인딩 또는 리버스 프록시)
    import os
    import ssl
    ssl_cert = cfg.get("server", {}).get("ssl_certfile") or os.environ.get("ARGOS_SSL_CERT", "")
    ssl_key = cfg.get("server", {}).get("ssl_keyfile") or os.environ.get("ARGOS_SSL_KEY", "")
    is_ssl_configured = bool(ssl_cert and ssl_key and os.path.exists(ssl_cert) and os.path.exists(ssl_key))
    proto = "https" if is_ssl_configured else "http"
    ssl_state = f"활성화 (TLS Direct, {os.path.basename(ssl_cert)})" if is_ssl_configured else "HTTP (권장: Nginx/Cloudflare/Caddy 리버스 프록시 또는 config.json의 ssl_certfile/ssl_keyfile)"

    # Determine server engine: Waitress WSGI (Production) vs Fallback Threading Server
    force_legacy = os.environ.get("ARGOS_USE_LEGACY_SERVER", "0") in ("1", "true", "yes")
    use_waitress = False
    if not force_legacy and not is_ssl_configured:
        try:
            import waitress
            use_waitress = True
        except ImportError:
            use_waitress = False

    server_engine_info = "Waitress Enterprise WSGI (64 Concurrency Workers)" if use_waitress else "Standalone Multi-Threaded Engine (Native/Direct TLS)"
    db_label, db_warning = _db_engine_status()

    try:
        from embedded_services import _is_port_open
        has_caddy = _is_port_open("127.0.0.1", 8443)
    except Exception:
        has_caddy = False

    public_url = "https://localhost:8443" if has_caddy else f"{proto}://{host}:{port}"
    ssl_display = "HTTPS (Embedded Caddy Reverse Proxy on :8443)" if has_caddy else ssl_state

    print("=" * 60)
    print(" ARGOS WORKS Server")
    print(" Data Directory :", DATA_DIR)
    print(" Database Engine:", db_label)
    if db_warning:
        print(" Warning        :", db_warning)
    print(f" Internal Port  : {proto}://{host}:{port}")
    print(f" Public Web URL : {public_url}")
    print(" Server Runtime :", server_engine_info)
    print(" SSL/TLS Status :", ssl_display)
    print(" Jira Sync      :", "Active" if (cfg["jira"].get("enabled") and cfg["jira"].get("api_token")) else "Inactive (config.json)")
    print(" AI Service     :", ai_state)
    print(" Vector DB      :", vector_state)
    print(" Auto Backup    : Active (24h cycle, 14 days retention)")
    print(" Press Ctrl+C in this window to stop the server.")
    print("=" * 60)

    # Packaged build: open the browser automatically so a double-click is enough.
    from app_paths import IS_FROZEN
    if IS_FROZEN and os.environ.get("ARGOS_NO_BROWSER", "0").strip().lower() not in ("1", "true", "yes"):
        import webbrowser
        open_host = "localhost" if host in ("0.0.0.0", "::", "") else host
        try:
            from embedded_services import _is_port_open
            has_caddy = _is_port_open("127.0.0.1", 8443)
        except Exception:
            has_caddy = False
        browse_url = "https://localhost:8443/" if has_caddy else f"{proto}://{open_host}:{port}/"
        threading.Timer(2.0, lambda: webbrowser.open(browse_url)).start()

    if use_waitress:
        try:
            import waitress
            workers = int(os.environ.get("ARGOS_WORKER_THREADS", "64"))
            waitress.serve(
                application,
                host=host,
                port=port,
                threads=workers,
                channel_timeout=60,
                cleanup_interval=30,
                clear_untrusted_proxy_headers=False,
            )
        except KeyboardInterrupt:
            print("\n서버를 종료합니다.")
        except Exception as e:
            print(f"\n서버 예외 발생: {e}", flush=True)
            import traceback
            traceback.print_exc()
        return

    from concurrent.futures import ThreadPoolExecutor

    class ArgosThreadingHTTPServer(ThreadingHTTPServer):
        daemon_threads = True
        request_queue_size = 512
        allow_reuse_address = True
        
        # Enterprise High-Capacity Thread Pool: 128 dedicated workers
        _pool = ThreadPoolExecutor(max_workers=128, thread_name_prefix="ArgosWorker")

        def server_bind(self):
            import socket
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except Exception:
                pass
            super().server_bind()

        def process_request(self, request, client_address):
            self._pool.submit(self.process_request_thread, request, client_address)

        def server_close(self):
            super().server_close()
            self._pool.shutdown(wait=False)

    httpd = ArgosThreadingHTTPServer((host, port), ArgosHandler)
    if is_ssl_configured:
        try:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(certfile=ssl_cert, keyfile=ssl_key)
            httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
            print("[Security] Native SSL/TLS 소켓이 성공적으로 활성화되었습니다.")
        except Exception as e:
            print(f"[Security Warning] SSL/TLS 적용 실패: {e}")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n서버를 종료합니다.")
        httpd.shutdown()
    except Exception as e:
        print(f"\n서버 예외 발생: {e}", flush=True)
        import traceback
        traceback.print_exc()
        httpd.shutdown()

if __name__ == "__main__":
    main()
