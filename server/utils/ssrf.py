import http.client
import ipaddress
import socket
import ssl
from typing import Optional, List, Tuple, Union, Any
import urllib.error
import urllib.parse
import urllib.request


def resolve_and_validate(url: str, allow_private: bool = False, require_https: bool = True) -> Tuple[str, int, List[str]]:
    """
    URL을 검증하고 대상 호스트명을 DNS 해석하여 검증된 (hostname, port, [ip_str, ...])을 반환한다.
    
    보안 규칙:
    1. Scheme 검사: require_https가 True이면 https만 허용, 아니면 http/https 허용.
    2. Link-local (169.254.0.0/16, fe80::/10): 항상 차단 (allow_private 여부 무관, 클라우드 메타데이터 방어).
    3. Multicast, Reserved, Unspecified: 항상 차단.
    4. not ip.is_global (사설망 10.x, 172.16-31.x, 192.168.x, 127.x, CGNAT 100.64.0.0/10 등):
       allow_private=False인 경우 즉시 차단.
    """
    if not url or not isinstance(url, str):
        raise ValueError("URL이 입력되지 않았습니다.")

    url_clean = url.strip()
    parsed = urllib.parse.urlsplit(url_clean)
    scheme = (parsed.scheme or "").lower()

    if require_https and not allow_private:
        if scheme != "https":
            raise ValueError(f"보안 위험: HTTPS 프로토콜만 허용됩니다 ({scheme}:// 불허)")
    else:
        if scheme not in ("http", "https"):
            raise ValueError(f"보안 위험: HTTP 또는 HTTPS 프로토콜만 지원됩니다 ({scheme}:// 불허)")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("유효하지 않은 호스트명입니다.")

    port = parsed.port or (443 if scheme == "https" else 80)

    try:
        addr_info = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise ValueError(f"호스트명을 확인할 수 없습니다 ({hostname}): {e}")

    validated_ips: List[str] = []
    for _family, _, _, _, sockaddr in addr_info:
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue

        # 1. Link-local (169.254.x.x Cloud Metadata) — 무조건 차단 (allow_private 옵션과 무관)
        if ip.is_link_local:
            raise ValueError(f"SSRF 보안 위험: Link-local 및 클라우드 메타데이터 IP({ip}) 접근이 차단되었습니다.")

        # 2. Multicast, Reserved, Unspecified
        if ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            raise ValueError(f"SSRF 보안 위험: 특수 목적 IP({ip}) 접근이 차단되었습니다.")

        # 3. Global routable check: blocks 10.x, 172.16-31.x, 192.168.x, 127.x, CGNAT 100.64.0.0/10
        if not ip.is_global and not allow_private:
            raise ValueError(f"SSRF 보안 위험: 사설망/비공개 IP({ip}) 접근이 차단되었습니다.")

        validated_ips.append(ip_str)

    if not validated_ips:
        raise ValueError(f"유효한 IP 주소를 확인할 수 없습니다 ({hostname})")

    return (hostname, port, validated_ips)


def validate_external_url(url: str, allow_private: bool = False, require_https: bool = True) -> bool:
    """기존 코드 호환성을 위한 boolean 반환 검증 함수."""
    resolve_and_validate(url, allow_private=allow_private, require_https=require_https)
    return True


class _SafeHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host, port=None, target_ip=None, **kwargs):
        super().__init__(host, port, **kwargs)
        self._target_ip = target_ip

    def connect(self):
        dest_ip = self._target_ip or self.host
        self.sock = socket.create_connection(
            (dest_ip, self.port),
            self.timeout,
            self.source_address
        )


class _SafeHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, port=None, target_ip=None, **kwargs):
        super().__init__(host, port, **kwargs)
        self._target_ip = target_ip

    def connect(self):
        dest_ip = self._target_ip or self.host
        sock = socket.create_connection(
            (dest_ip, self.port),
            self.timeout,
            self.source_address
        )
        if self._tunnel_host:
            self.sock = sock
            self._tunnel()

        server_hostname = self.host
        context = getattr(self, "_context", None) or getattr(self, "context", None) or ssl.create_default_context()
        self.sock = context.wrap_socket(sock, server_hostname=server_hostname)


class _SafeHTTPHandler(urllib.request.HTTPHandler):
    def __init__(self, ip_map: dict):
        super().__init__()
        self._ip_map = ip_map

    def http_open(self, req):
        return self.do_open(self._get_conn, req)

    def _get_conn(self, host, **kwargs):
        h, _, p = host.partition(":")
        port = int(p) if p else 80
        target_ip = self._ip_map.get((h.lower(), port))
        return _SafeHTTPConnection(h, port=port, target_ip=target_ip, **kwargs)


class _SafeHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, ip_map: dict, context=None):
        super().__init__(context=context)
        self._ip_map = ip_map

    def https_open(self, req):
        return self.do_open(self._get_conn, req)

    def _get_conn(self, host, **kwargs):
        h, _, p = host.partition(":")
        port = int(p) if p else 443
        target_ip = self._ip_map.get((h.lower(), port))
        if "context" not in kwargs:
            kwargs["context"] = self._context or ssl.create_default_context()
        return _SafeHTTPSConnection(h, port=port, target_ip=target_ip, **kwargs)


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, allow_private: bool = False, require_https: bool = True, ip_map: Optional[dict] = None):
        super().__init__()
        self.allow_private = allow_private
        self.require_https = require_https
        self.ip_map = ip_map if ip_map is not None else {}

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Validate redirect target against SSRF and resolve target IP
        h, port, ips = resolve_and_validate(
            newurl,
            allow_private=self.allow_private,
            require_https=self.require_https
        )
        self.ip_map[(h.lower(), port)] = ips[0]
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def safe_urlopen(
    url_or_req: Union[str, urllib.request.Request],
    data: Optional[bytes] = None,
    timeout: float = 10.0,
    allow_private: bool = False,
    require_https: bool = True,
    **kwargs: Any
):
    """
    DNS Rebinding 방어 및 SSRF 방지 기능이 포함된 안전한 urlopen.
    - 사전 DNS 해석 및 IP 대역 검증 (Link-local, 사설망, CGNAT 차단)
    - 검증된 IP로 직접 소켓 연결하되 SNI 및 인증서 검증은 원본 호스트명으로 수행
    - HTTP 리디렉션 대상 또한 단계별로 동일한 SSRF 검증 수행
    """
    if isinstance(url_or_req, urllib.request.Request):
        req = url_or_req
        target_url = req.full_url
    else:
        target_url = str(url_or_req)
        req = urllib.request.Request(target_url, data=data, **kwargs)

    hostname, port, validated_ips = resolve_and_validate(
        target_url,
        allow_private=allow_private,
        require_https=require_https
    )

    ip_map = {(hostname.lower(), port): validated_ips[0]}
    ctx = ssl.create_default_context()
    redirect_handler = _SafeRedirectHandler(
        allow_private=allow_private,
        require_https=require_https,
        ip_map=ip_map
    )
    http_handler = _SafeHTTPHandler(ip_map)
    https_handler = _SafeHTTPSHandler(ip_map, context=ctx)

    opener = urllib.request.build_opener(http_handler, https_handler, redirect_handler)
    return opener.open(req, timeout=timeout)
