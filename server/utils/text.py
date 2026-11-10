import json
import re
from datetime import datetime, timezone, timedelta

from config import CATEGORY_KEYWORDS, VALID_CATEGORIES

def parse_iso_timestamp(ts_str):
    """Parse ISO timestamp with timezone support and convert to local time (KST/JST UTC+9).
    Returns YYYY-MM-DD HH:MM:SS format string.
    """
    if not ts_str:
        return ""
    try:
        clean_ts = str(ts_str).strip()
        if clean_ts.endswith("Z"):
            clean_ts = clean_ts[:-1] + "+00:00"
        elif len(clean_ts) >= 5 and (clean_ts[-5] in ("+", "-")) and clean_ts[-3] != ":":
            clean_ts = clean_ts[:-2] + ":" + clean_ts[-2:]
        dt = datetime.fromisoformat(clean_ts)
        kst = timezone(timedelta(hours=9))
        if dt.tzinfo is not None:
            dt_kst = dt.astimezone(kst)
        else:
            dt_kst = dt
        return dt_kst.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        s = str(ts_str).replace("T", " ")
        if "." in s:
            s = s.split(".")[0]
        return s[:19]

TITLE_SUFFIXES = [
    "대표이사", "부사장", "전무이사", "상무이사", "전무", "상무", "이사",
    "실장", "소장", "본부장", "팀장", "부장", "차장", "과장", "대리", "주임", "사원",
    "선임연구원", "책임연구원", "수석연구원", "연구원", "선임", "수석"
]

def sanitize_label(text):
    text = re.sub(r"[,\s]+", "_", (text or "").strip())
    text = re.sub(r"[^0-9A-Za-z가-힣_\-\.]", "", text)
    return text[:60] or "미지정"

def guess_category(text):
    lower = (text or "").lower()
    for cat, kws in CATEGORY_KEYWORDS:
        for kw in kws:
            if kw in lower:
                return cat
    return "기타업무"

def dept_by_id(depts, dept_id):
    for d in depts:
        if d["id"] == dept_id:
            return d
    return None

def assignee_base_name(name):
    name = (name or "").strip()
    for suf in TITLE_SUFFIXES:
        if len(name) > len(suf) and name[-len(suf):] == suf:
            head = name[:-len(suf)].strip()
            if head:
                return head
    return name

def _adf_to_text(node):
    """Jira 설명(description) 필드는 ADF(JSON) 형식이라, 여기서 순수 텍스트만 뽑아낸다.
    형식이 예상과 다르면 예외를 삼키고 빈 문자열을 반환한다."""
    parts = []

    def walk(n):
        if isinstance(n, dict):
            if n.get("type") == "text":
                parts.append(n.get("text", ""))
            for child in n.get("content") or []:
                walk(child)
        elif isinstance(n, list):
            for item in n:
                walk(item)

    try:
        walk(node)
    except Exception:
        return ""
    return " ".join(p for p in parts if p).strip()

def clean_jira_rich_text(text: str) -> str:
    """Jira Changelog나 텍스트 필드에 포함된 {adf...} JSON 블록, {panel...},
    h2., [^첨부파일] 등의 Jira Wiki/ADF 마크업을 읽기 쉬운 순수 텍스트로 정제한다."""
    if not text or not isinstance(text, str):
        return text
    if "{adf" not in text and "{panel" not in text and "h2." not in text and "[^" not in text:
        return text

    def parse_adf_block(match):
        block = match.group(1).strip()
        try:
            data = json.loads(block)
            if data.get("type") == "table":
                rows = []
                for row in data.get("content", []):
                    cells = []
                    for cell in row.get("content", []):
                        parts = []
                        def walk(n):
                            if isinstance(n, dict):
                                if n.get("type") == "text":
                                    parts.append(n.get("text", ""))
                                for c in n.get("content", []):
                                    walk(c)
                            elif isinstance(n, list):
                                for item in n:
                                    walk(item)
                        walk(cell)
                        cells.append(" ".join(parts).strip())
                    if cells and any(cells):
                        rows.append(cells)
                if len(rows) > 1 and len(rows[0]) == 2:
                    pairs = []
                    for r in rows[1:]:
                        if len(r) >= 2 and r[0] and r[1]:
                            pairs.append(f"{r[0]}: {r[1]}")
                        elif len(r) == 1 and r[0]:
                            pairs.append(r[0])
                    if pairs:
                        return " 📋 [" + " | ".join(pairs) + "] "
                elif rows:
                    row_strs = [" - ".join(r) for r in rows if r]
                    return " 📋 [" + " | ".join(row_strs) + "] "
            elif data.get("type") == "doc":
                parts = []
                def walk(n):
                    if isinstance(n, dict):
                        if n.get("type") == "text":
                            parts.append(n.get("text", ""))
                        for c in n.get("content", []):
                            walk(c)
                    elif isinstance(n, list):
                        for item in n:
                            walk(item)
                walk(data)
                return " " + " ".join(parts).strip() + " "
            return " "
        except Exception:
            return " "

    cleaned = re.sub(r'\{adf[^}]*\}\s*(\{.*?\})\s*\{adf\}', parse_adf_block, text, flags=re.DOTALL)
    cleaned = re.sub(r'\{panel[^}]*\}(.*?)\{panel\}', r' [\1] ', cleaned, flags=re.DOTALL)
    cleaned = re.sub(r'(?m)^h[1-6]\.\s*', '', cleaned)
    cleaned = re.sub(r'h[1-6]\.\s*', '', cleaned)
    cleaned = re.sub(r'\[\^([^\]]+)\]', r' 📎 \1', cleaned)
    cleaned = re.sub(r'\{\{([^}]+)\}\}', r'\1', cleaned)
    cleaned = re.sub(r'[\r\n]+', ' · ', cleaned)
    cleaned = re.sub(r'\s{2,}', ' ', cleaned).strip()
    return cleaned

def login_label(acc, login_id: str) -> str:
    """Returns canonical username if user exists, or a keyed pseudonymous fingerprint if not found,
    preventing accidentally pasted passwords in login_id from leaking into logs/SIEM.
    """
    if acc and isinstance(acc, dict):
        return acc.get("username") or acc.get("name") or "known_user"
    clean_id = (login_id or "").strip()
    if not clean_id:
        return "anon:empty/len=0"
    try:
        from utils.crypto import get_master_key
        mkey = get_master_key()
    except Exception:
        import os
        mkey = os.environ.get("ARGOS_MASTER_KEY", "fallback_key_2026").encode("utf-8")
    import hmac
    import hashlib
    fp = hmac.new(mkey, clean_id.lower().encode("utf-8"), hashlib.sha256).hexdigest()[:8]
    return f"anon:{fp}/len={len(clean_id)}"

