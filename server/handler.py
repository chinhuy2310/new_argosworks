import json
import os
import ipaddress
import mimetypes
import tempfile
import traceback
import urllib.parse
from urllib.parse import urlsplit, parse_qs
from http.server import BaseHTTPRequestHandler
from http.cookies import SimpleCookie
from services.auth import get_session
from router import match_get, match_post
from module_gate import check_module_access, denial_message
from utils.logging import log_line, access_log
from middleware_security import check_rate_limit, validate_csrf_token, get_allowed_cors_origin
from db import close_connection

PUBLIC_API_WHITELIST = {
    # System health, release identifier & Setup
    "/api/health",
    "/api/version",
    "/api/setup/status",
    "/api/setup/verify-license",
    "/api/setup/complete",

    # Authentication & Session Handshake
    "/api/account/check",
    "/api/auth/check",
    "/api/account/login",
    "/api/auth/login",
    "/api/account/register",
    "/api/auth/register",
    "/api/account/csrf",
    "/api/auth/csrf",
    "/api/account/logout",
    "/api/auth/logout",
    "/api/account/logout-all",
    "/api/auth/logout-all",
    "/api/account/me",

    # Public Workspace UI Branding
    "/api/workspace-config",
}

# ---------------------------------------------------------------------------
# Reverse-proxy trust
# ---------------------------------------------------------------------------
# TRUSTED_PROXIES is a comma separated list of IPs / CIDRs (hostnames are also
# accepted for backwards compatibility) whose X-Forwarded-For / X-Real-IP
# headers are honoured. Only the *immediate* TCP peer is matched against this
# list, so a workstation that talks to ARGOS directly can never spoof its IP.
#   127.0.0.1 / ::1   - reverse proxy running on the same host
#   172.16.0.0/12     - default Docker bridge / compose networks (Caddy)
# Deployments fronted by a proxy on another subnet MUST extend this value.
# "0.0.0.0" (trust every peer, therefore spoofable) exists only for isolated
# lab setups and is never enabled implicitly.
DEFAULT_TRUSTED_PROXIES = "127.0.0.1,::1,172.16.0.0/12"

_TRUSTED_PROXY_CACHE = {}


def _parse_trusted_proxies(raw):
    exact, networks, trust_any = set(), [], False
    for item in (raw or "").split(","):
        item = item.strip()
        if not item:
            continue
        if item == "0.0.0.0":
            trust_any = True
            continue
        try:
            networks.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            exact.add(item.lower())
    return frozenset(exact), tuple(networks), trust_any


def get_trusted_proxies():
    """Parsed TRUSTED_PROXIES, cached per raw configuration value."""
    raw = os.environ.get("TRUSTED_PROXIES", DEFAULT_TRUSTED_PROXIES)
    cached = _TRUSTED_PROXY_CACHE.get(raw)
    if cached is None:
        cached = _parse_trusted_proxies(raw)
        _TRUSTED_PROXY_CACHE.clear()
        _TRUSTED_PROXY_CACHE[raw] = cached
    return cached


def is_trusted_proxy_peer(peer):
    """True when *peer* (IP or host string) is an explicitly configured proxy."""
    exact, networks, trust_any = get_trusted_proxies()
    if trust_any:
        return True
    if not peer:
        return False
    if peer.lower() in exact:
        return True
    try:
        addr = ipaddress.ip_address(peer)
    except ValueError:
        return False
    return any(addr in net for net in networks)


class ArgosHandler(BaseHTTPRequestHandler):
    server_version = "ArgosServer/2.0"
    cfg = None  # class-level, set in main()
    timeout = 60  # Socket inactivity timeout (seconds) preventing thread leaks

    def log_message(self, fmt, *args):
        log_line(self.address_string(), fmt % args)

    # ---- 공통 응답 헬퍼 ----
    def _send_json(self, status, payload, extra_headers=None):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        # Enterprise Hardened Headers (Zero-Day & Injection Prevention)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("X-XSS-Protection", "1; mode=block")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("Server", "ArgosEnterprise/2.0")
        if extra_headers:
            for k, v in extra_headers:
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _is_secure(self):
        """요청이 HTTPS를 통해 전달되었는지 검사 (Direct TLS 또는 Reverse Proxy X-Forwarded-Proto)."""
        proto = (self.headers.get("X-Forwarded-Proto") or "").lower()
        if proto == "https":
            return True
        conn = getattr(self, "connection", None)
        if conn and hasattr(conn, "getpeercert"):
            return True
        return False

    def _make_auth_cookie_header(self, token, max_age_days=1):
        """Enterprise HttpOnly Cookie 헤더 생성 (SameSite=Lax, HttpOnly, HTTPS 시 Secure 플래그 적용, 기본 24h)."""
        max_age = int(max_age_days * 24 * 3600)
        cookie = f"argos_token={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={max_age}"
        if self._is_secure():
            cookie += "; Secure"
        return ("Set-Cookie", cookie)

    def _make_logout_cookie_header(self):
        """세션 만료용 Set-Cookie 헤더 생성."""
        cookie = "argos_token=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0; Expires=Thu, 01 Jan 1970 00:00:00 GMT"
        if self._is_secure():
            cookie += "; Secure"
        return ("Set-Cookie", cookie)

    def _extract_client_ip(self):
        """
        Resolve the real client IP.

        X-Forwarded-For / X-Real-IP are honoured only when the direct TCP peer is
        listed in TRUSTED_PROXIES (IP, CIDR or hostname). The header chain is then
        walked right-to-left and the first untrusted, syntactically valid address
        wins, so a client-supplied "X-Forwarded-For: 1.2.3.4" prefix cannot spoof
        the rate-limiter bucket or the IP recorded in the audit log.
        """
        try:
            peer_ip = self.client_address[0]
        except Exception:
            peer_ip = self.address_string()

        if not is_trusted_proxy_peer(peer_ip):
            return peer_ip

        candidates = []
        xff = self.headers.get("X-Forwarded-For")
        if xff:
            candidates.extend(part.strip() for part in xff.split(",") if part.strip())
        real_ip = (self.headers.get("X-Real-IP") or "").strip()
        if real_ip:
            candidates.append(real_ip)

        valid = []
        for candidate in candidates:
            try:
                valid.append(str(ipaddress.ip_address(candidate)))
            except ValueError:
                continue
        if not valid:
            return peer_ip

        for candidate in reversed(valid):
            if not is_trusted_proxy_peer(candidate):
                return candidate
        return valid[0]

    def _extract_token(self):
        """
        인증 토큰을 안전하게 추출한다.
        1. Cookie 헤더 (argos_token=<token>) - XSS / F12 방어형 HttpOnly
        2. Authorization: Bearer <token> - 하위 호환성 및 API 클라이언트 지원
        * 보안 강화: Query string (?token=...) 전송은 전면 차단 (URL 로깅 및 어깨 너머 노출 방지).
        """
        # 1. Cookie 우선 검사
        cookie_header = self.headers.get("Cookie", "") or ""
        if "argos_token=" in cookie_header:
            from http.cookies import SimpleCookie
            try:
                sc = SimpleCookie()
                sc.load(cookie_header)
                if "argos_token" in sc and sc["argos_token"].value:
                    return sc["argos_token"].value.strip()
            except Exception:
                pass

        # 2. Authorization 헤더 Fallback
        auth = self.headers.get("Authorization", "") or ""
        if auth.startswith("Bearer "):
            return auth[7:].strip()

        return ""

    def _get_session_or_401(self):
        if hasattr(self, "_current_session") and self._current_session:
            return self._current_session
        token = self._extract_token()
        session = get_session(token) if token else None
        self._current_session = session
        if not session:
            self._send_json(401, {"ok": False, "error": "로그인이 필요합니다.", "authRequired": True})
            return None
        return session

    def _get_session_optional(self):
        """로그인 여부가 필수는 아니지만, 로그인돼 있으면 그 정보를 쓰고 싶은 곳에서
        사용한다(예: /api/ask에서 본인 캘린더까지 검색 범위에 포함시킬지 여부).
        토큰이 없거나 유효하지 않아도 401을 보내지 않고 조용히 None을 돌려준다."""
        if hasattr(self, "_current_session") and self._current_session is not None:
            return self._current_session
        token = self._extract_token()
        session = get_session(token) if token else None
        self._current_session = session
        return session

    def _stream_file(self, path, content_type, download_name=None, inline=False, extra_headers=None):
        """
        Streams file in 64KB chunks directly to client socket.
        Supports HTTP Range requests (RFC 7233) for resumable downloads and media/PDF seeking.
        Prevents thread memory exhaustion (OOM) on large file downloads.
        """
        try:
            stat = os.stat(path)
            file_size = stat.st_size
            etag = f'"{int(stat.st_mtime)}-{file_size}"'

            if_none_match = self.headers.get("If-None-Match")
            if if_none_match and if_none_match.strip() == etag:
                self.send_response(304)
                self.end_headers()
                return

            range_header = self.headers.get("Range")
            start_byte = 0
            end_byte = file_size - 1
            is_range = False

            if range_header and range_header.startswith("bytes="):
                ranges = range_header[6:].split("-")
                try:
                    if ranges[0]:
                        start_byte = int(ranges[0])
                    if len(ranges) > 1 and ranges[1]:
                        end_byte = min(int(ranges[1]), file_size - 1)
                    if start_byte <= end_byte and start_byte < file_size:
                        is_range = True
                except ValueError:
                    pass

            disp_type = "inline" if inline else "attachment"
            content_length = (end_byte - start_byte + 1) if is_range else file_size

            if is_range:
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start_byte}-{end_byte}/{file_size}")
            else:
                self.send_response(200)

            self.send_header("Content-Type", content_type or "application/octet-stream")
            self.send_header("Content-Length", str(content_length))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("ETag", etag)

            if download_name:
                self.send_header("Content-Disposition", f"{disp_type}; filename*=UTF-8''{urllib.parse.quote(download_name)}")

            # Hardened Security Headers on all file responses
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "SAMEORIGIN")
            self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")

            # Static asset cache: no-cache, must-revalidate allows 304 while ensuring instant updates on deployment
            is_static_asset = any(p in path.replace("\\", "/") for p in ["/css/", "/js/", "/assets/", "/images/", "favicon.svg"])
            if is_static_asset:
                self.send_header("Cache-Control", "no-cache, must-revalidate")
            else:
                self.send_header("Cache-Control", "no-store")

            if extra_headers:
                for k, v in extra_headers:
                    self.send_header(k, v)

            self.end_headers()

            # Stream file in 64KB chunks
            chunk_size = 64 * 1024
            with open(path, "rb") as f:
                if is_range and start_byte > 0:
                    f.seek(start_byte)
                remaining = content_length
                while remaining > 0:
                    read_len = min(remaining, chunk_size)
                    buf = f.read(read_len)
                    if not buf:
                        break
                    self.wfile.write(buf)
                    remaining -= len(buf)
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except FileNotFoundError:
            self._send_json(404, {"ok": False, "error": "not found"})
        except Exception as e:
            self._send_json(500, {"ok": False, "error": str(e)})

    def _send_file(self, path, content_type):
        self._stream_file(path, content_type, inline=True)

    def _send_attachment(self, path, download_name):
        content_type, _ = mimetypes.guess_type(download_name)
        self._stream_file(path, content_type or "application/octet-stream", download_name=download_name, inline=False, extra_headers=[
            ("Content-Security-Policy", "sandbox")
        ])

    def _start_sse(self):
        """SSE(Server-Sent Events) 스트리밍 응답을 시작한다."""
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Connection', 'keep-alive')
        self.send_header('X-Accel-Buffering', 'no')
        self.end_headers()

    def _send_sse_event(self, data):
        """하나의 SSE 이벤트를 전송한다. 클라이언트 접속 종료 시 False 반환."""
        try:
            payload = json.dumps(data, ensure_ascii=False)
            self.wfile.write(f"data: {payload}\n\n".encode('utf-8'))
            self.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            return False

    def _end_sse(self):
        """SSE 스트림을 종료한다."""
        try:
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass

    # ---- OPTIONS (CORS Preflight) ----
    def do_OPTIONS(self):
        origin = self.headers.get("Origin")
        allowed_domain = self.headers.get("Host", "localhost")
        self.send_response(204)
        if origin:
            allowed = get_allowed_cors_origin(origin, [allowed_domain])
            if allowed:
                self.send_header("Access-Control-Allow-Origin", allowed)
                self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With, X-CSRF-Token")
                self.send_header("Access-Control-Allow-Credentials", "true")
                self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()

    # ---- HEAD ----
    def do_HEAD(self):
        self.do_GET()

    # ---- GET ----
    def do_GET(self):
        try:
            parsed = urlsplit(self.path)
            path = parsed.path
            ip = self._extract_client_ip()

            # Enterprise Rate Limiting Check (bypass static files for smooth UX)
            if path.startswith("/api/"):
                allowed, retry_after = check_rate_limit(ip, limit_rpm=180)
                if not allowed:
                    self._send_json(429, {"ok": False, "error": f"요청 한도(Rate limit)를 초과했습니다. {retry_after}초 후 다시 시도하세요."}, extra_headers=[("Retry-After", str(retry_after))])
                    return

                # Default Authentication Guard: all /api endpoints require login unless whitelisted
                if path not in PUBLIC_API_WHITELIST:
                    if not self._get_session_or_401():
                        return

                    # License entitlement gate (paid modules only)
                    allowed_module, module_code = check_module_access(path)
                    if not allowed_module:
                        self._send_json(403, {
                            "ok": False,
                            "code": "MODULE_NOT_LICENSED",
                            "module": module_code,
                            "error": denial_message(module_code)
                        })
                        return

            try:
                route_type, handler_or_path, content_type = match_get(path)
                
                if route_type == "file":
                    self._send_file(handler_or_path, content_type)
                elif route_type == "redirect":
                    self.send_response(302)
                    self.send_header("Location", handler_or_path)
                    self.end_headers()
                elif route_type == "nocontent":
                    self.send_response(204)
                    self.end_headers()
                elif route_type == "handler":
                    handler_or_path(self, parsed, ip)
                elif route_type == "notfound":
                    self._send_json(404, {"ok": False, "error": "not found"})
                    
            except Exception as e:
                log_line("GET 처리 중 오류:\n", traceback.format_exc())
                self._send_json(500, {"ok": False, "error": "서버 내부 오류가 발생했습니다. (Internal Server Error)"})
        finally:
            close_connection()

    # ---- POST ----
    def do_POST(self):
        try:
            parsed = urlsplit(self.path)
            path = parsed.path
            ip = self._extract_client_ip()

            # Enterprise Rate Limiting Check on API mutations
            if path.startswith("/api/"):
                allowed, retry_after = check_rate_limit(ip, limit_rpm=120)
                if not allowed:
                    self._send_json(429, {"ok": False, "error": f"요청 한도(Rate limit)를 초과했습니다. {retry_after}초 후 다시 시도하세요."}, extra_headers=[("Retry-After", str(retry_after))])
                    return

                # Default Authentication Guard: all /api endpoints require login unless whitelisted
                if path not in PUBLIC_API_WHITELIST:
                    if not self._get_session_or_401():
                        return

                    # License entitlement gate (paid modules only)
                    allowed_module, module_code = check_module_access(path)
                    if not allowed_module:
                        self._send_json(403, {
                            "ok": False,
                            "code": "MODULE_NOT_LICENSED",
                            "module": module_code,
                            "error": denial_message(module_code)
                        })
                        return

                # CSRF Protection for state-changing endpoints (exempt whitelisted public endpoints)
                if path not in PUBLIC_API_WHITELIST:
                    csrf_header = self.headers.get("X-CSRF-Token", "")
                    session_token = self._extract_token()
                    # If request has session cookie, validate CSRF token to prevent cross-site request forgery
                    cookie_header = self.headers.get("Cookie", "")
                    if "argos_token=" in cookie_header:
                        valid_csrf = validate_csrf_token(csrf_header, session_token=session_token)
                        
                        # Fallback A: Double-submit cookie (argos_csrf)
                        if not valid_csrf:
                            try:
                                sc = SimpleCookie()
                                sc.load(cookie_header)
                                if "argos_csrf" in sc and sc["argos_csrf"].value:
                                    valid_csrf = validate_csrf_token(sc["argos_csrf"].value, session_token=session_token)
                            except Exception:
                                pass

                        # Fallback B: Browser Same-Origin Verification (Sec-Fetch-Site / Origin / Referer against Host)
                        if not valid_csrf:
                            sec_fetch_site = (self.headers.get("Sec-Fetch-Site") or "").strip().lower()
                            origin = (self.headers.get("Origin") or "").strip().lower()
                            host = (self.headers.get("Host") or "").strip().lower()
                            referer = (self.headers.get("Referer") or "").strip().lower()

                            origin_match = False
                            if origin:
                                try:
                                    origin_match = (urlsplit(origin).netloc.lower() == host)
                                except Exception:
                                    pass
                            elif referer:
                                try:
                                    origin_match = (urlsplit(referer).netloc.lower() == host)
                                except Exception:
                                    pass

                            # If guaranteed same-origin by browser security boundary
                            if sec_fetch_site == "same-origin" or origin_match:
                                valid_csrf = True

                        if not valid_csrf:
                            self._send_json(403, {"ok": False, "error": "CSRF 검증 실패 (Invalid or missing CSRF token)"})
                            return

            try:
                length = int(self.headers.get("Content-Length", "0"))
                max_bytes = int((self.cfg.get("max_upload_mb", 25))) * 1024 * 1024
                if length > max_bytes:
                    self._send_json(413, {"ok": False, "error": "업로드 용량 제한(%dMB) 초과" % self.cfg.get("max_upload_mb", 25)})
                    return
                # Stream read body with memory capping (prevents thread OOM during concurrent uploads)
                # Small payloads (<1MB) stay in memory, large payloads spill safely to temporary disk
                raw_body = b""
                if length > 0:
                    if length <= 1024 * 1024:
                        raw_body = self.rfile.read(length)
                    else:
                        with tempfile.SpooledTemporaryFile(max_size=1024 * 1024) as spool:
                            remaining = length
                            chunk_size = 64 * 1024
                            while remaining > 0:
                                chunk = self.rfile.read(min(remaining, chunk_size))
                                if not chunk:
                                    break
                                spool.write(chunk)
                                remaining -= len(chunk)
                            spool.seek(0)
                            raw_body = spool.read()

                handler_func = match_post(path)
                if handler_func:
                    handler_func(self, raw_body, ip)
                else:
                    self._send_json(404, {"ok": False, "error": "not found"})
            except Exception as e:
                log_line("POST 처리 중 오류:\n", traceback.format_exc())
                access_log(ip, "error", 500, f"Exception: {type(e).__name__}")
                self._send_json(500, {"ok": False, "error": "서버 내부 오류가 발생했습니다. (Internal Server Error)"})
        finally:
            close_connection()

# Backward compatibility alias
JarvisHandler = ArgosHandler
