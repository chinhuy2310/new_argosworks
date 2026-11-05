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
        r".{0,80}\b(?:task|công việc|thẻ|ticket|issue|trạng thái)\b",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"\b(?:task|công việc|thẻ|ticket|issue)\b"
        r".{0,80}\b(?:mới|riêng|được tạo|đăng ký|cập nhật|thay đổi|xóa)\b",
        re.IGNORECASE | re.DOTALL,
    ),
    # English
    re.compile(
        r"\b(?:please\s+)?(?:create|make|add|update|change|delete|remove|"
        r"schedule|post|leave)\s+(?:(?:a|the|new)\s+)?"
        r"(?:task|issue|ticket|comment|status|due\s+date)\b",
        re.IGNORECASE,
    ),
    # Korean imperative forms
    re.compile(
        r"(?:업무|작업|카드|태스크|티켓|이슈|댓글|상태)"
        r".{0,40}(?:등록해|만들어|생성해|추가해|수정해|변경해|삭제해|남겨|달아|잡아)",
        re.DOTALL,
    ),
    re.compile(
        r"(?:등록해|만들어|생성해|추가해|수정해|변경해|삭제해|남겨|달아|잡아)"
        r".{0,40}(?:업무|작업|카드|태스크|티켓|이슈|댓글|상태)",
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



_ACTIVE_TASK_CONTEXT = re.compile(
    r"(?:내\s*(?:진행\s*중\s*)?업무|내가\s*진행\s*중인\s*(?:업무|작업)|"
    r"진행\s*중인\s*업무|진행중\s*업무|"
    r"my\s+(?:active\s+|current\s+)?tasks?|tasks?\s+assigned\s+to\s+me|"
    r"công\s+việc\s+(?:đang\s+làm|hiện\s+tại|của\s+tôi)|"
    r"việc\s+đang\s+làm)",
    re.IGNORECASE,
)


def should_include_active_tasks(message):
    """Return true only when the user explicitly asks for their active-task list."""
    return bool(_ACTIVE_TASK_CONTEXT.search(message or ""))


def classify_chat_intent(message, history=None):
    """Return a conservative intent label; only explicit writes enable proposals."""
    text = (message or "").strip()
    if not text:
        return {
            "type": "ambiguous",
            "domain": None,
            "domains": [],
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
            "domains": ["tasks"],
            "requires_action": True,
            "confidence": 0.95,
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
    matched_domains = [
        domain for domain, pattern in domain_patterns
        if re.search(pattern, lowered, re.IGNORECASE)
    ]
    if len(matched_domains) > 1:
        return {
            "type": "analysis",
            "domain": None,
            "domains": matched_domains,
            "requires_action": False,
            "confidence": 0.8,
        }
    if matched_domains:
        return {
            "type": "enterprise_search",
            "domain": matched_domains[0],
            "domains": matched_domains,
            "requires_action": False,
            "confidence": 0.85,
        }

    # Only treat an actual acronym/token as a knowledge lookup. Do not mistake
    # ordinary short words such as "my" in "my active tasks" for an acronym.
    ascii_tokens = re.findall(r"[A-Za-z0-9_-]+", text)
    has_uppercase_acronym = any(
        token.isupper() and 2 <= len(token) <= 10 for token in ascii_tokens
    )
    has_lowercase_definition = bool(_QUESTION_OR_HOWTO.search(text)) and any(
        token.isalpha() and token.islower() and 2 <= len(token) <= 5
        for token in ascii_tokens
    )
    is_single_short_token = (
        len(ascii_tokens) == 1
        and 2 <= len(ascii_tokens[0]) <= 8
    )
    is_short_acronym = (
        has_uppercase_acronym
        or has_lowercase_definition
        or is_single_short_token
    ) and text.lower() not in _GREETING_ONLY

    if is_short_acronym:
        return {
            "type": "knowledge_search",
            "domain": "knowledge",
            "domains": ["knowledge"],
            "requires_action": False,
            "confidence": 0.75,
        }

    return {
        "type": "general_question",
        "domain": None,
        "domains": [],
        "requires_action": False,
        "confidence": 0.8,
    }
