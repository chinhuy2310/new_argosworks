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
    import traceback
    print("\n[CRITICAL UNHANDLED EXCEPTION]", file=sys.stderr, flush=True)
    traceback.print_exception(exc_type, exc_value, exc_traceback, file=sys.stderr)
    sys.stderr.flush()

sys.excepthook = _log_unhandled_exception
if hasattr(threading, "excepthook"):
    threading.excepthook = lambda args: _log_unhandled_exception(args.exc_type, args.exc_value, args.exc_traceback)

from config import load_config, ensure_dirs, ensure_seed_files, DATA_DIR
from db import init_db
from handler import ArgosHandler, JarvisHandler
from services.jira_client import sync_jira_cache, jira_auto_sync_loop
from services.auth import cleanup_expired_sessions
from wsgi import init_app, application

def _db_engine_status():
    """시작 배너용 (엔진 이름, 경고문).

    server/db.py는 **import 시점**에 DATABASE_URL을 읽어 엔진을 고정하는데,
    이 파일은 db를 load_config()보다 먼저 import한다. 그래서 .env에만
    DATABASE_URL이 있으면 조용히 SQLite로 동작한다(운영에서 의도와 다른 DB 사용).
    동작을 바꾸지 않고 눈에 보이게만 만든다.
    """
    import os as _os
    import db as db_module
    label = "PostgreSQL" if db_module.ENGINE == "postgres" else "SQLite"
    warning = ""
    if db_module.ENGINE != "postgres" and (_os.environ.get("DATABASE_URL", "") or "").startswith("postgresql"):
        warning = (
            ".env의 DATABASE_URL이 무시되어 SQLite로 동작 중입니다. "
            "db.py가 load_config()보다 먼저 import되어 엔진이 이미 고정되었습니다. "
            "PostgreSQL을 쓰려면 DATABASE_URL을 프로세스 환경변수로 전달하세요."
        )
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
    from app_paths import IS_FROZEN as _FROZEN, APP_HOME as _APP_HOME
    try:
        from embedded_services import start_embedded_services
        start_embedded_services(_APP_HOME)
    except Exception as _exc:
        print("[Embedded Services] Notice:", _exc, file=sys.stderr, flush=True)

    # Packaged build: create .env with a fresh ARGOS_MASTER_KEY on the very first start
    # (before anything is encrypted), so the customer has the file to back up from day one.
    if _FROZEN:
        from utils.crypto import get_master_key
        get_master_key()
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

    print("=" * 60)
    print(" ARGOS WORKS 백엔드 서버")
    print(" 데이터 폴더 :", DATA_DIR)
    print(" DB 엔진     :", db_label)
    if db_warning:
        print(" 경고        :", db_warning)
    print(f" 주소        : {proto}://{host}:{port}  (사내망: {proto}://<이 PC의 IP>:{port})")
    print(" 서버 엔진   :", server_engine_info)
    print(" SSL/TLS     :", ssl_state)
    print(" Jira 연동   :", jira_state)
    print(" AI 서비스   :", ai_state)
    print(" 벡터 DB     :", vector_state)
    print(" CSDL 백업   : 자동 스케줄러 가동 (24시간 주기, 14일 보관)")
    print(" 종료하려면 이 창에서 Ctrl+C 를 누르세요.")
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
