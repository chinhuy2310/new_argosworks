#!/usr/bin/env python
"""GET 엔드포인트 RBAC 회귀 가드.

민감한 읽기 엔드포인트가 (1) 세션 검사와 (2) 권한 검사를 모두 수행하는지 정적으로 확인한다.
CI 에서 실행해, 향후 누군가 권한 검사를 삭제하면 즉시 실패하도록 만드는 것이 목적이다.

사용법:
    python scripts/audit_endpoint_rbac.py          # 민감 엔드포인트만 검사 (실패 시 exit 1)
    python scripts/audit_endpoint_rbac.py --all    # 전체 GET 라우트 리포트
"""
import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_DIR = os.path.join(ROOT, "server")
ROUTER_PATH = os.path.join(SERVER_DIR, "router.py")
HANDLERS_DIR = os.path.join(SERVER_DIR, "handlers")

# 반드시 세션 + 권한 검사를 모두 가져야 하는 읽기 엔드포인트 prefix
REQUIRED_PREFIXES = (
    "/api/records",
    "/api/ask",
    "/api/schedule",
    "/api/issues",
    "/api/jira/attachments",
    "/api/attachments",
)

SESSION_MARKERS = ("_get_session_or_401", "_get_session_optional")
PERM_MARKERS = ("can_view", "visible_", "is_admin", "check_record_write_access", "can_modify")

ROUTE_RE = re.compile(
    r"path\s*(?:==|\.startswith\(|in\s*\()([^:\n]*):\s*\n\s*"
    r"return\s*\(\s*\"handler\"\s*,\s*(\w+)"
)


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _collect_sources():
    sources = [_read(ROUTER_PATH)]
    if os.path.isdir(HANDLERS_DIR):
        for fname in sorted(os.listdir(HANDLERS_DIR)):
            if fname.endswith(".py"):
                sources.append(_read(os.path.join(HANDLERS_DIR, fname)))
    return sources


def _function_bodies(sources):
    bodies = {}
    for src in sources:
        for match in re.finditer(r"^def\s+(\w+)\s*\(", src, re.M):
            name = match.group(1)
            start = match.end()
            nxt = re.search(r"^def\s+\w+\s*\(", src[start:], re.M)
            end = start + nxt.start() if nxt else len(src)
            bodies.setdefault(name, src[start:end])
    return bodies


def _parse_get_routes(router_src):
    routes = {}
    for match in ROUTE_RE.finditer(router_src):
        cond, handler = match.group(1), match.group(2)
        for path in re.findall(r'"(/api/[^"]*)"', cond):
            routes[path] = handler
    return routes


def main(argv=None):
    parser = argparse.ArgumentParser(description="Endpoint RBAC static guard")
    parser.add_argument("--all", action="store_true", help="print a report for every GET route")
    args = parser.parse_args(argv)

    try:
        router_src = _read(ROUTER_PATH)
    except OSError as exc:
        print(f"[ERROR] cannot read router.py: {exc}")
        return 2

    bodies = _function_bodies(_collect_sources())
    routes = _parse_get_routes(router_src)
    if not routes:
        print("[ERROR] no GET routes parsed — router.py structure changed?")
        return 2

    problems = []
    for path in sorted(routes):
        handler = routes[path]
        required = any(path.startswith(prefix) for prefix in REQUIRED_PREFIXES)
        body = bodies.get(handler)
        if body is None:
            if required:
                problems.append((path, handler, "handler not found"))
            continue
        has_session = any(marker in body for marker in SESSION_MARKERS)
        has_perm = any(marker in body for marker in PERM_MARKERS)
        if args.all:
            status = "OK  " if (has_session and has_perm) else "WARN"
            print(f"{status} {path:42s} -> {handler} (session={has_session}, perm={has_perm})")
        if required:
            if not has_session:
                problems.append((path, handler, "missing session check"))
            elif not has_perm:
                problems.append((path, handler, "missing permission check"))

    if problems:
        print("\n[FAIL] sensitive read endpoints without RBAC guard:")
        for path, handler, reason in problems:
            print(f"  - {path:42s} -> {handler}: {reason}")
        return 1

    print(f"[OK] {len(REQUIRED_PREFIXES)} sensitive read endpoint prefix(es) enforce session + permission checks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
