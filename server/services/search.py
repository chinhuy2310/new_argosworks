import re
from services.data_store import read_records
from services.jira_client import get_cached_jira_records

def _tokenize(text):
    tokens = re.findall(r"[\w]+", (text or "").lower(), re.UNICODE)
    return [t for t in tokens if len(t) > 1 or t.isdigit() or ord(t[0]) >= 0xAC00]

SEARCH_STOPWORDS = {
    "là", "gì", "có", "mã", "của", "và", "ở", "tại", "nào", "như", "thế", "cho", "được", "về", "những", "thông", "tin",
    "the", "is", "at", "which", "on", "a", "an", "what", "how", "who", "where", "tell", "me", "about"
}

def search_records(records, query, limit=6, extra_query=""):
    clean_q = (query or "").strip()
    raw_primary = [t for t in _tokenize(clean_q) if t not in SEARCH_STOPWORDS]
    raw_secondary = [t for t in _tokenize(extra_query) if t not in SEARCH_STOPWORDS]
    
    # Jira key detection (e.g. VS-19, vs 19, TS-01)
    target_jira_key = None
    jira_m = re.search(r'\b([a-zA-Z]{2,})\s*[-_ ]*\s*(\d+)\b', clean_q)
    if jira_m:
        target_jira_key = f"{jira_m.group(1).upper()}-{jira_m.group(2)}"

    if not raw_primary and not raw_secondary and not target_jira_key:
        return []

    field_weights = (
        ("title", 4.0), ("cardCode", 3.5), ("category", 2.0), ("project", 2.0),
        ("tags", 2.0), ("assignee", 1.5), ("participants", 1.5), ("summary", 1.5), ("memo", 1.0),
        ("comments", 0.6),
    )
    scored = []
    for r in records:
        score = 0.0
        title_text = str(r.get("title") or "").lower()
        jk = str((r.get("jira") or {}).get("key") or "").upper()
        cc = str(r.get("cardCode") or "").upper().lstrip("#")
        rid = str(r.get("id") or "")

        # 1. Exact Jira issue key / card code match gets highest priority
        if target_jira_key and (jk == target_jira_key or cc == target_jira_key):
            score += 100.0
        elif clean_q and clean_q.upper() in (jk, cc, f"#{rid}", rid):
            score += 100.0

        # 2. Field-level token matching with distinction between primary query and synonyms
        for field, weight in field_weights:
            if field == "tags":
                text = " ".join(r.get("tags") or [])
            elif field == "comments":
                text = " ".join(c.get("body", "") for c in (r.get("comments") or []))
            else:
                text = str(r.get(field, "") or "")
            field_tokens = [ft.lower() for ft in _tokenize(text)]
            if not field_tokens:
                continue

            # Primary user query (3.0x weight, full match or subword)
            for pt in raw_primary:
                pt_lower = pt.lower()
                match_cnt = 0
                for ft in field_tokens:
                    if pt_lower == ft:
                        match_cnt += 2  # exact word match gets double
                    elif len(pt_lower) >= 3 and (pt_lower in ft or ft in pt_lower):
                        match_cnt += 1
                if match_cnt > 0:
                    effective_cnt = min(2, match_cnt) if field == "comments" else min(4, match_cnt)
                    score += weight * effective_cnt * 3.0

            # Secondary expanded synonyms (0.35x weight, capped to avoid overtaking primary)
            for st in raw_secondary:
                st_lower = st.lower()
                match_cnt = 0
                for ft in field_tokens:
                    if st_lower == ft:
                        match_cnt += 1
                    elif len(st_lower) >= 3 and (st_lower in ft or ft in st_lower):
                        match_cnt += 1
                if match_cnt > 0:
                    effective_cnt = min(1, match_cnt)
                    score += weight * effective_cnt * 0.35

        # 3. Exact word in title bonus
        for pt in raw_primary:
            pt_lower = pt.lower()
            if pt_lower == jk.lower() or re.search(r'\b' + re.escape(pt_lower) + r'\b', title_text):
                score += 15.0

        if score > 0:
            r_with_score = dict(r)
            r_with_score["_search_score"] = round(score, 2)
            scored.append((score, r_with_score))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [r for _score, r in scored[:limit]]

def _enrich_parent_summaries(records):
    """Enriches each record with parentSummary (the title of its parent task) so the UI can clearly display parent names."""
    title_by_key = {}
    for r in records:
        t = (r.get("title") or (r.get("jira") or {}).get("summary") or "").strip()
        if not t:
            continue
        if r.get("id"):
            title_by_key[str(r["id"])] = t
            title_by_key[f"rec-{r['id']}"] = t
            title_by_key[f"#{r['id']}"] = t
        if r.get("cardCode"):
            clean_c = str(r["cardCode"]).strip().upper()
            title_by_key[clean_c] = t
            title_by_key[clean_c.lstrip("#")] = t
        if (r.get("jira") or {}).get("key"):
            title_by_key[str(r["jira"]["key"]).strip().upper()] = t
        if r.get("unlinked_jira_key"):
            title_by_key[str(r["unlinked_jira_key"]).strip().upper()] = t

    for r in records:
        pk = (r.get("parentKey") or (r.get("jira") or {}).get("parentKey") or "").strip()
        if pk and not r.get("parentSummary"):
            clean_pk = pk.upper()
            p_summary = (
                title_by_key.get(clean_pk)
                or title_by_key.get(clean_pk.lstrip("#"))
                or title_by_key.get(clean_pk.replace("REC-", ""))
                or title_by_key.get(pk)
            )
            if p_summary:
                r["parentSummary"] = p_summary
        elif not r.get("parentSummary"):
            r["parentSummary"] = ""
    return records

def merged_records(cfg):
    """Local-First Data Merge:
    Local DB (records) is the authoritative Primary Source of Truth.
    Local records ALWAYS retain their local title, memo, status, dates, and assignee.
    Jira only enriches local records with jira.url, remote comments, and remote attachments.
    External Jira issues that were not created locally are appended as secondary items.
    """
    jira_cfg = cfg.get("jira", {}) if cfg else {}
    jira_enabled = bool(jira_cfg.get("enabled", False))

    all_local = read_records()

    if not jira_enabled:
        # Jira disabled: 100% pure local records, no Jira badges
        records = [dict(r) for r in all_local]
        for r in records:
            r["jira"] = None
            r["isLocal"] = True
        _enrich_parent_summaries(records)
        records.sort(key=lambda r: (r.get("date", "") or r.get("startDate", "")), reverse=True)
        return records, {"records": [], "synced_at": None, "error": None}

    cache = get_cached_jira_records(cfg)
    raw_jira_records = cache.get("records") or []
    jira_records = [dict(r) for r in raw_jira_records]

    # Map Jira records by uppercase Jira key
    jira_by_key = {}
    for jr in jira_records:
        k = ((jr.get("jira") or {}).get("key") or "").strip().upper()
        if k:
            jira_by_key[k] = jr

    # Mapping tables for parent-child hierarchy
    code_to_jira_key = {}
    id_to_jira_key = {}
    claimed_jira_keys = set()

    for r in all_local:
        rid = r.get("id")
        code = (r.get("cardCode") or "").strip().upper()
        clean_code = code.lstrip("#")
        j_key = ((r.get("jira") or {}).get("key") or "").strip().upper()

        if rid is not None and j_key:
            id_to_jira_key[str(rid)] = j_key
        if clean_code and j_key:
            code_to_jira_key[clean_code] = j_key
            code_to_jira_key[code] = j_key

    merged_local = []
    for r in all_local:
        r_copy = dict(r)
        r_copy["isLocal"] = True
        j_key = ((r_copy.get("jira") or {}).get("key") or "").strip().upper()

        if j_key and j_key in jira_by_key:
            claimed_jira_keys.add(j_key)
            j_match = jira_by_key[j_key]
            # ENRICH (Do not overwrite local title, memo, status, dates, assignee!)
            r_copy["jira"] = {
                "key": j_key,
                "url": (j_match.get("jira") or {}).get("url") or f"{jira_cfg.get('base_url', '').rstrip('/')}/browse/{j_key}",
                "status": (j_match.get("jira") or {}).get("status") or r_copy.get("status", "진행"),
                "statusName": (j_match.get("jira") or {}).get("statusName") or r_copy.get("status", "진행")
            }
            # Enrich attachments from Jira if not present locally
            local_att_names = set()
            for a in (r_copy.get("attachments") or []):
                if isinstance(a, str):
                    local_att_names.add(a.lower())
                elif isinstance(a, dict):
                    local_att_names.add((a.get("name") or a.get("filename") or "").lower())

            for ja in (j_match.get("attachments") or []):
                ja_name = (ja.get("name") or ja.get("filename") or "").lower()
                if ja_name and ja_name not in local_att_names:
                    local_att_names.add(ja_name)
                    r_copy.setdefault("attachments", []).append(ja)

            # Enrich comments from Jira
            if j_match.get("comments"):
                r_copy["jiraComments"] = j_match["comments"]
        elif j_key:
            # Key no longer found in Jira Cloud (deleted from Jira) -> keep local safe
            r_copy["jira"] = None
            r_copy["unlinked_jira_key"] = j_key

        merged_local.append(r_copy)

    # Collect external Jira records (issues created directly in Jira, not in local)
    external_jira = []
    for jr in jira_records:
        k = ((jr.get("jira") or {}).get("key") or "").strip().upper()
        if k and k not in claimed_jira_keys:
            # External Jira task
            current_pk = (jr.get("parentKey") or (jr.get("jira") or {}).get("parentKey") or "").strip()
            if current_pk:
                clean_pk = current_pk.upper().lstrip("#")
                mapped_parent_jira = code_to_jira_key.get(clean_pk) or id_to_jira_key.get(clean_pk)
                if mapped_parent_jira:
                    jr["parentKey"] = mapped_parent_jira
            external_jira.append(jr)

    # Local records come first, followed by external Jira tasks
    records = merged_local + external_jira
    _enrich_parent_summaries(records)
    records.sort(key=lambda r: (r.get("date", "") or r.get("startDate", "")), reverse=True)
    return records, cache

def product_as_search_record(p, allow_price=True):
    """제품정보 한 건을 search_records()가 이해하는 '기록' 모양으로 변환한다.
    /api/ask(홈 자연어 검색)가 인수인계 기록/Jira 티켓뿐 아니라 제품정보(공통정보+
    조달정보)까지 검색 범위에 넣기 위해 쓴다.

    allow_price=False(가격 열람 권한 없음)이면 조달 단가를 검색 컨텍스트에 넣지 않는다.
    """
    cat = p.get("category") or "카메라"
    model = p.get("model", "")
    disp_name = p.get("displayName", "")
    summary = p.get("summary", "")
    memo = p.get("memo", "")
    proc = p.get("procurement") or {}
    specs = p.get("specs") or {}

    # Build rich text for search and AI context
    content_parts = []
    if summary:
        content_parts.append(summary)

    # Format key specifications (resolution, sensor, lens, FOV, etc.)
    if specs:
        specs_list = [f"{k}: {v}" for k, v in specs.items() if v]
        if specs_list:
            content_parts.append("규격 사양: " + " | ".join(specs_list[:25]))

    # Format procurement info
    if proc:
        proc_bits = []
        if proc.get("registeredName"):
            proc_bits.append("나라장터 등록명: " + proc["registeredName"])
        if proc.get("identificationNo"):
            proc_bits.append("물품식별번호: " + proc["identificationNo"])
        if allow_price and proc.get("price"):
            proc_bits.append(f"단가: {proc['price']:,}원" if isinstance(proc['price'], (int, float)) else f"단가: {proc['price']}원")
        if proc.get("configuration"):
            proc_bits.append("구성: " + proc["configuration"])
        if proc_bits:
            content_parts.append("조달정보: " + " | ".join(proc_bits))

    if memo:
        content_parts.append(memo)

    if p.get("attachments"):
        content_parts.append("첨부파일: " + ", ".join(a.get("name", "") for a in p["attachments"]))

    combined_body = "\n".join(content_parts)

    # Tags for multi-keyword search
    tags = ["제품", "제품정보", cat]
    if p.get("lifecycle"):
        tags.append(p.get("lifecycle"))
    if p.get("family"):
        tags.append(p.get("family"))
    if "카메라" in cat or "camera" in model.lower() or "cam" in model.lower():
        tags.extend(["camera", "카메라", "CCTV", "열화상", "thermal"])
    if "led" in cat.lower() or "안내판" in cat or "전광판" in cat:
        tags.extend(["LED", "안내판", "전광판", "display"])
    if "녹화기" in cat or "nvr" in model.lower():
        tags.extend(["녹화기", "NVR", "DVR", "recorder"])
    if "pole" in cat.lower() or "폴" in cat:
        tags.extend(["POLE", "폴", "지주"])
    if "스피커" in combined_body or "앰프" in combined_body or "음향" in combined_body or "speaker" in combined_body.lower() or "audio" in combined_body.lower():
        tags.extend(["스피커", "speaker", "오디오", "음향", "앰프", "AMP", "방송"])
    if "센서" in combined_body or "sensor" in combined_body.lower():
        tags.extend(["센서", "sensor", "환경센서"])

    title = f"[{cat}] {model}"
    if disp_name and disp_name != model:
        title += f" ({disp_name})"

    return {
        "id": "product-" + p.get("id", ""),
        "org": "공식카탈로그" if str(p.get("id", "")).startswith("P-V119-") else "사내",
        "category": cat,
        "title": title,
        "project": p.get("family", "") or cat,
        "assignee": "",
        "date": p.get("updatedAt") or p.get("createdAt") or "",
        "summary": summary[:600] if summary else combined_body[:600],
        "tags": list(set(tags)),
        "memo": combined_body,
        "attachments": [],
        "jira": None,
        "productLink": {"id": p.get("id", ""), "model": model}
    }

def schedule_event_as_search_record(e):
    """일정(캘린더) 한 건을 search_records()가 이해하는 '기록' 모양으로 변환한다.
    캘린더는 '본인 일정만' 원칙이라, 이 변환은 /api/ask에서 로그인된 본인 일정에만
    적용하고 다른 사람 일정은 절대 넣지 않는다(호출부에서 필터링됨)."""
    return {
        "id": "schedule-" + str(e.get("id", "")),
        "org": e.get("ownerOrg", ""),
        "category": "캘린더",
        "title": e.get("title", ""),
        "project": e.get("type", ""),
        "assignee": e.get("ownerName", ""),
        "date": e.get("startDate", ""),
        "summary": e.get("memo", "")[:500],
        "tags": ["캘린더", e.get("type", "")],
        "memo": e.get("memo", ""),
        "attachments": [],
        "jira": None
    }
