# -*- coding: utf-8 -*-
"""
module_gate.py — License entitlement enforcement per product module.

The license payload carries a `modules` list (canvas, pim, jira, rag, schedule,
audit). Without enforcement a customer who only paid for PIM would still get
Jira/RAG/Audit, which makes the commercial packaging meaningless.

This gate is intentionally path-prefix based so it cannot be bypassed by the UI:
every API request flows through handler.do_GET / handler.do_POST.
"""

from services.license_manager import has_module

# module code -> URL prefixes owned by that module
MODULE_PREFIXES = (
    ("pim", ("/api/products", "/api/product-categories", "/api/pim")),
    ("jira", ("/api/jira", "/api/issues", "/api/sync")),
    ("rag", ("/api/chat", "/api/ask", "/api/vectors", "/api/ai/")),
    ("schedule", ("/api/schedule",)),
    ("audit", ("/api/admin/audit-logs", "/api/admin/ai-usage")),
)

# Licensing, identity, setup and health must keep working even when a module
# is not entitled — otherwise an admin cannot even paste a new license key.
ALWAYS_ALLOWED_PREFIXES = (
    "/api/health",
    "/api/setup",
    "/api/account",
    "/api/auth",
    "/api/admin/license",
    "/api/admin/users",
    "/api/admin/backups",
    "/api/version",
)


def _matches(path, prefix):
    return path == prefix or path.startswith(prefix + "/")


def required_module(path):
    """Return the module code required by this API path, or None."""
    if not path or not path.startswith("/api/"):
        return None
    for prefix in ALWAYS_ALLOWED_PREFIXES:
        if _matches(path, prefix):
            return None
    for module, prefixes in MODULE_PREFIXES:
        for prefix in prefixes:
            if _matches(path, prefix):
                return module
    return None


def check_module_access(path):
    """
    Return (allowed, module_code).
    allowed is True when the path is module-agnostic or the license covers it.
    """
    module = required_module(path)
    if not module:
        return True, None
    try:
        return bool(has_module(module)), module
    except Exception:
        # Fail closed: an unreadable license must not unlock paid modules.
        return False, module


MODULE_LABELS = {
    "pim": "PIM (제품 정보 관리)",
    "jira": "Jira 연동",
    "rag": "AI 지식 검색 (RAG)",
    "schedule": "일정 관리",
    "audit": "감사 로그 (Audit)",
}


def denial_message(module):
    label = MODULE_LABELS.get(module, module)
    return (
        f"현재 라이선스에 '{label}' 모듈이 포함되어 있지 않습니다. "
        "관리자에게 라이선스 증설(모듈 추가)을 요청하세요."
    )
