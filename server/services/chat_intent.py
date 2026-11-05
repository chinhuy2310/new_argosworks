"""Deterministic intent guard for chatbot business-action proposals.

This module deliberately recognizes only explicit write requests. Read/search
queries, definitions, and acronym lookups must never be treated as actions.
"""
import re


_ACTION_PATTERNS = (
    # Vietnamese
    re.compile(
        r"\b(?:tạo|thêm|cập nhật|sửa|xóa|đăng ký|ghi nhận|lên lịch|đặt lịch|"
        r"đổi trạng thái|thay đổi trạng thái|bình luận|comment)\b"
        r".{0,80}\b(?:task|công việc|thẻ|ticket|issue|lịch|lịch trình|trạng thái)\b",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"\b(?:task|công việc|thẻ|ticket|issue|lịch|lịch trình)\b"
        r".{0,80}\b(?:mới|riêng|được tạo|đăng ký|cập nhật|thay đổi|xóa)\b",
        re.IGNORECASE | re.DOTALL,
    ),
    # English
    re.compile(
        r"\b(?:please\s+)?(?:create|make|add|update|change|delete|remove|"
        r"schedule|post|leave)\s+(?:(?:a|the|new)\s+)?"
        r"(?:task|issue|ticket|comment|event|schedule)\b",
        re.IGNORECASE,
    ),
    # Korean imperative forms
    re.compile(
        r"(?:업무|작업|카드|태스크|티켓|이슈|댓글|상태|일정)"
        r".{0,40}(?:등록해|만들어|생성해|추가해|수정해|변경해|삭제해|남겨|달아|잡아)",
        re.DOTALL,
    ),
    re.compile(
        r"(?:등록해|만들어|생성해|추가해|수정해|변경해|삭제해|남겨|달아|잡아)"
        r".{0,40}(?:업무|작업|카드|태스크|티켓|이슈|댓글|상태|일정)",
        re.DOTALL,
    ),
)

_QUESTION_OR_HOWTO = re.compile(
    r"(?:^\s*(?:cách|làm sao|how\s+to|how\s+do\s+i|what\s+is|what\s+does|"
    r"define|meaning\s+of)\b|là\s+gì|có\s+nghĩa\s+là|"
    r"무슨\s*뜻|뜻이\s*뭐|뭐야|무엇인가요|무엇인지|어떻게\s+하나요)",
    re.IGNORECASE,
)

_NEGATED = re.compile(
    r"(?:\bkhông\b|\bđừng\b|\bnot\b|\bdon't\b|\bdo\s+not\b|"
    r"하지\s*마|만들지\s*마|등록하지\s*마|취소)",
    re.IGNORECASE,
)

_FOLLOWUP_CREATE = re.compile(
    r"(?:tạo\s*mới|tạo\s*riêng|thêm\s*mới|chọn\s*tạo|"
    r"create\s+new|new\s+(?:task|issue|card)|separate\s+task|"
    r"새\s*카드|새로\s*만들|별도\s*생성|새\s*업무)",
    re.IGNORECASE,
)

_ACRONYM_QUESTION = re.compile(
    r"(?:\b[a-z][a-z0-9_-]{1,7}\b|\b[A-Z][A-Z0-9_-]{1,9}\b)",
    re.IGNORECASE,
)

_GREETING_ONLY = {
    "hi", "hello", "hey", "안녕", "안녕하세요", "xin chào", "chào",
    "thanks", "thank you", "감사합니다", "고마워",
}


def _last_assistant_message(history):
    for item in reversed(history or []):
        if isinstance(item, dict) and item.get("role") == "assistant":
            return str(item.get("content") or "")
    return ""


def _selected_create_quick_action(message, history):
    """Allow a short selection only when the immediately preceding assistant offered it."""
    previous = _last_assistant_message(history)
    match = re.search(r":::quick-actions\s*\r?\n(.*?)\r?\n:::", previous, re.DOTALL)
    if not match:
        return False

    options = [
        line.strip().lstrip("-• ").strip()
        for line in match.group(1).splitlines()
        if line.strip()
    ]
    if not options:
        return False

    normalized = re.sub(r"\s+", " ", (message or "").strip().lower())
    selected = None
    number = re.search(r"(?:option|phương án|lựa chọn)?\s*([1-9])(?:번|번을|번으로)?$", normalized)
    if number:
        index = int(number.group(1)) - 1
        if 0 <= index < len(options):
            selected = options[index]
    if selected is None:
        selected = next(
            (option for option in options
             if re.sub(r"\s+", " ", option.lower()) in normalized
             or normalized in re.sub(r"\s+", " ", option.lower())),
            None,
        )
    if selected is None:
        return False
    return bool(_FOLLOWUP_CREATE.search(selected))


def classify_chat_intent(message, history=None):
    """Return a conservative intent label; only explicit writes enable proposals."""
    text = (message or "").strip()
    if not text:
        return {
            "type": "ambiguous",
            "domain": None,
            "requires_action": False,
            "confidence": 0.0,
        }

    if _NEGATED.search(text):
        explicit_action = False
    elif _QUESTION_OR_HOWTO.search(text):
        explicit_action = False
    else:
        explicit_action = any(pattern.search(text) for pattern in _ACTION_PATTERNS)
        if not explicit_action:
            explicit_action = _selected_create_quick_action(text, history)

    if explicit_action:
        return {
            "type": "business_action",
            "domain": "tasks",
            "requires_action": True,
            "confidence": 0.95,
        }

    # Short acronym/definition lookups are knowledge searches, never task creation.
    words = re.findall(r"[A-Za-z0-9가-힣_-]+", text)
    is_short_acronym = (
        len(words) <= 5
        and any(_ACRONYM_QUESTION.fullmatch(word) for word in words)
        and text.lower() not in _GREETING_ONLY
    )
    if is_short_acronym:
        return {
            "type": "knowledge_search",
            "domain": "knowledge",
            "requires_action": False,
            "confidence": 0.75,
        }

    lowered = text.lower()
    domain_patterns = (
        ("products", r"(제품|상품|product|model|모델|사양|specification|가격|price|조달)"),
        ("calendar", r"(일정|캘린더|calendar|schedule|lịch|ngày\s+hẹn)"),
        ("documents", r"(문서|첨부파일|파일\s*내용|document|attachment|tài liệu)"),
        ("reports", r"(보고서|업무\s*보고|엑셀|report|excel|báo cáo)"),
        ("tasks", r"(업무|작업|태스크|이슈|티켓|task|issue|ticket|jira|công việc|thẻ)"),
        ("records", r"(인수인계|사내\s*기록|내부\s*기록|internal\s+record|handover|hồ sơ nội bộ)"),
    )
    for domain, pattern in domain_patterns:
        if re.search(pattern, lowered, re.IGNORECASE):
            return {
                "type": "enterprise_search",
                "domain": domain,
                "requires_action": False,
                "confidence": 0.85,
            }

    return {
        "type": "general_question",
        "domain": None,
        "requires_action": False,
        "confidence": 0.8,
    }
