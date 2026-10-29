# -*- coding: utf-8 -*-
"""http_body.py — Defensive JSON body parsing for POST handlers.

``json.loads(b"null")`` returns ``None`` and ``json.loads(b"[]")`` returns a
list; the following ``body.get(...)`` then raises ``AttributeError`` and the
client receives an unhandled HTTP 500 (audit finding F-0003). Every POST
handler must therefore validate the decoded type before using it.
"""
import json


def parse_json_dict(raw_body):
    """Parse a request body that MUST be a JSON object.

    Returns ``(data, error)``:
      * ``data`` is a ``dict`` (empty for an empty body), ``error`` is ``None``;
      * on failure ``data`` is ``None`` and ``error`` is a user-facing message
        that the handler should return with HTTP 400.
    """
    if not raw_body:
        return {}, None
    try:
        data = json.loads(raw_body.decode("utf-8"))
    except Exception:
        return None, "잘못된 JSON 형식입니다."
    if not isinstance(data, dict):
        return None, "잘못된 요청 본문입니다 (JSON 객체가 필요합니다)."
    return data, None


def as_text(value):
    """Coerce a JSON scalar into a stripped string.

    Request bodies may carry numbers/bools where a string is expected; calling
    ``.strip()`` on them raises AttributeError (unhandled 500, audit F-0003).
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, dict)):
        return ""
    return str(value).strip()
