import os
import re
import json
import mimetypes
import urllib.parse
import urllib.request
from urllib.parse import urlsplit, parse_qs
from datetime import datetime
from config import WEB_DIR, PRODUCT_ATTACH_DIR, ATTACH_DIR
from utils.logging import access_log
from services.ai_client import call_ai_answer, get_ai_config
from services.product_manager import search_products
from services.data_store import (
    read_departments, read_schedule, read_products, read_records,
    get_record_by_id, update_record_status, add_record_comment, add_record_attachment,
    delete_record, link_record_jira, find_record_by_key_or_code, get_record_hierarchy_chain,
    read_product_categories, get_product_categories_and_templates,
    save_product_category, delete_product_category, update_record_details, _UNSET
)
from services.search import merged_records, search_records, product_as_search_record, schedule_event_as_search_record
from services.jira_client import (
    get_cached_categories, jira_ongoing_records_for,
    all_jira_due_date_events, get_cached_jira_records, get_jira_issue_by_key,
    transition_jira_issue, add_jira_comment, upload_jira_attachment,
    jira_project_for_dept, lookup_jira_account_id, create_jira_issue, sync_jira_cache,
    jira_fetch_project_subtask_type, jira_fetch_project_categories, create_jira_issue_link
)
import threading
from config import SPEC_TEMPLATES, PRODUCT_CATEGORIES, ATTACH_DIR
from services.auth import account_key, read_accounts, is_admin_user
from services.activity_store import get_daily_activities, get_recent_activity_dates
from services.notification_service import (
    get_user_notifications, mark_notification_as_read, mark_all_notifications_as_read,
    trigger_comment_notification, trigger_status_changed_notification
)
from utils.text import assignee_base_name, sanitize_label
from services.vector_store import (
    is_voyage_configured, search_vector_store, sync_all_vectors,
    get_vector_stats, check_vector_sync_status, delete_vector_document
)
from utils.logging import log_line


def _audit(session, ip, action, target_type, target_id, details=None):
    """Ghi audit trail cho thao tác nhạy cảm; không bao giờ làm hỏng request."""
    try:
        from services.audit_logger import log_audit
        log_audit(session, ip, action, target_type, target_id, details=details)
    except Exception:
        pass


# --- GET Handlers ---

def handle_get_health(handler, parsed, ip):
    """
    Comprehensive Enterprise Health Check.
    Checks DB connectivity (SELECT 1) without leaking internal database error messages.
    Returns HTTP 200 if healthy, HTTP 503 if DB is unreachable.
    """
    db_ok = False
    try:
        from db import query
        res = query("SELECT 1 as ping")
        if res and res[0].get("ping") == 1:
            db_ok = True
    except Exception as e:
        from utils.logging import log_line
        log_line(f"[HealthCheck] Database ping failed from {ip}: {e}")

    health_status = {
        "ok": db_ok,
        "status": "healthy" if db_ok else "unhealthy",
        "time": datetime.now().isoformat(),
        "database": {
            "status": "connected" if db_ok else "unavailable"
        }
    }

    status_code = 200 if db_ok else 503
    handler._send_json(status_code, health_status)

def handle_get_departments(handler, parsed, ip):
    handler._send_json(200, {"ok": True, "departments": read_departments()})

def handle_get_members(handler, parsed, ip):
    session = handler._get_session_or_401()
    if not session:
        return
    depts = {d["id"]: (d.get("name") or d["id"]) for d in read_departments()}
    members_map = {}

    def add_m(name, org, email=""):
        if not name:
            return
        n = str(name).strip()
        if not n or len(n) < 2 or n in ("미배정", "Unassigned", "None", "-", "미할당") or "기업부설연구소" in n:
            return
        o = (org or "").strip()
        k = n.lower()
        if k not in members_map or (not members_map[k]["org"] and o):
            members_map[k] = {
                "name": n,
                "org": o,
                "dept": depts.get(o, o),
                "email": email or (members_map.get(k, {}).get("email") or "")
            }

    try:
        from db import query
        for u in query("SELECT name, dept_id, email FROM users WHERE disabled = 0 AND (status IS NULL OR status = 'active')"):
            add_m(u.get("name"), u.get("dept_id"), u.get("email"))
        for r in query("SELECT DISTINCT assignee_name, dept_id FROM jira_issues WHERE assignee_name IS NOT NULL"):
            add_m(r.get("assignee_name"), r.get("dept_id"))
    except Exception as e:
        log_line(f"[handle_get_members] query error: {e}")

    members = list(members_map.values())
    members.sort(key=lambda m: (m["org"] or "zz", m["name"].lower()))
    handler._send_json(200, {"ok": True, "members": members})

def handle_get_categories(handler, parsed, ip):
    session = handler._get_session_or_401()
    if not session:
        return
    qs = parse_qs(parsed.query)
    dept_id = (qs.get("org", [""])[0])
    jira_enabled = bool(handler.cfg.get("jira", {}).get("enabled", False))
    jira_cats = get_cached_categories(handler.cfg, dept_id) if (dept_id and jira_enabled) else []
    
    # Retrieve configured local/custom categories for this department
    depts = read_departments()
    target_dept = next((d for d in depts if d["id"] == dept_id), None)
    custom_raw = (target_dept.get("customCategories") or "") if target_dept else ""
    local_cats = []
    if isinstance(custom_raw, list):
        local_cats = [str(c).strip().strip('"\'[]') for c in custom_raw if str(c).strip().strip('"\'[]')]
    elif isinstance(custom_raw, str):
        c_str = custom_raw.strip()
        if c_str.startswith("[") and c_str.endswith("]"):
            try:
                parsed = json.loads(c_str)
                if isinstance(parsed, list):
                    local_cats = [str(c).strip().strip('"\'[]') for c in parsed if str(c).strip().strip('"\'[]')]
            except Exception:
                pass
        if not local_cats:
            local_cats = [c.strip().strip('"\'[]') for c in re.split(r'[,;\n]+', c_str) if c.strip().strip('"\'[]')]
    
    # Merge and deduplicate while preserving origins
    # Items in jira_cats get origin="jira". Local-only items get origin="local".
    seen = set()
    items = []
    
    # Add Jira categories first
    for jc in jira_cats:
        c_clean = jc.strip()
        if c_clean and c_clean.lower() not in seen:
            seen.add(c_clean.lower())
            items.append({"name": c_clean, "origin": "jira", "isJira": True})
            
    # Add Local categories
    for lc in local_cats:
        c_clean = lc.strip()
        if c_clean:
            if c_clean.lower() in seen:
                # Exists in both Jira and Local -> mark as Jira since it can sync
                for item in items:
                    if item["name"].lower() == c_clean.lower():
                        item["isLocal"] = True
            else:
                seen.add(c_clean.lower())
                items.append({"name": c_clean, "origin": "local", "isJira": False, "isLocal": True})
                
    simple_names = [it["name"] for it in items]
    handler._send_json(200, {
        "ok": True,
        "org": dept_id,
        "categories": simple_names,
        "items": items
    })

def handle_get_records(handler, parsed, ip):
    session = handler._get_session_or_401()
    if not session:
        return
    qs = parse_qs(parsed.query)
    mode = (qs.get("mode", ["all"])[0])
    records, cache = merged_records(handler.cfg)
    from services.auth import visible_records, can_view_record
    records = visible_records(session, records)
    jira_records = [r for r in (cache["records"] or []) if can_view_record(session, r)]
    total = len(records)

    # Hỗ trợ phân trang: offset & limit
    has_more = False
    offset = 0
    raw_offset = qs.get("offset", [None])[0]
    raw_limit = qs.get("limit", [None])[0]

    if raw_offset is not None or raw_limit is not None or mode == "recent":
        try:
            offset = max(0, int(raw_offset or 0))
        except (ValueError, TypeError):
            offset = 0
        try:
            limit = max(1, int(raw_limit or (50 if mode == "recent" else 50)))
        except (ValueError, TypeError):
            limit = 50

        sliced = records[offset : offset + limit]
        has_more = (offset + limit) < total
        records = sliced

    from services.jira_client import check_jira_connection_status
    jira_ready, jira_err = check_jira_connection_status(handler.cfg)
    j_cfg = handler.cfg.get("jira", {})
    handler._send_json(200, {
        "ok": True,
        "records": records,
        "total": total,
        "offset": offset,
        "limit": len(records),
        "hasMore": has_more,
        "jiraSynced": len(jira_records),
        "syncedAt": cache["synced_at"],
        "syncError": cache["error"],
        "jiraEnabled": bool(j_cfg.get("enabled")),
        "jiraConnected": bool(jira_ready)
    })

def handle_get_ask(handler, parsed, ip):
    session = handler._get_session_or_401()
    if not session:
        return

    qs = parse_qs(parsed.query)
    question = (qs.get("q", [""])[0]).strip()
    if not question:
        handler._send_json(400, {"ok": False, "error": "질문을 입력해주세요."})
        return

    candidates = []
    search_method = "keyword"
    logged_in_name = session.get("name")

    matched_name = None
    alias_used = None

    # 1. 1인칭 대명사 감지 ("tôi", "của tôi", "mình", "my", "내", "나", "저") -> 현재 로그인 사용자로 매핑
    first_p = r"\b(tôi|của tôi|mình|của mình|bản thân|my|me|i|na|nae|내|나|저|제|본인)\b"
    if re.search(first_p, question, re.IGNORECASE) and logged_in_name:
        matched_name = logged_in_name
        alias_used = "tôi (본인)"
    else:
        # 2. 동적 인명 감지: 시스템에 등록된 계정(사원명/아이디)과 자동 매칭 (하드코딩 제거)
        try:
            from db import query
            for u in query("SELECT name, username FROM users WHERE disabled = 0"):
                m_name = (u.get("name") or "").strip()
                m_user = (u.get("username") or "").strip()
                if m_name and len(m_name) >= 2:
                    if re.search(rf"\b{re.escape(m_name)}\b", question, re.IGNORECASE):
                        matched_name = m_name
                        alias_used = m_name
                        break
                if m_user and len(m_user) >= 2:
                    if re.search(rf"\b{re.escape(m_user)}\b", question, re.IGNORECASE):
                        matched_name = m_name or m_user
                        alias_used = m_user
                        break
        except Exception:
            pass

    # 공공조달 및 기술 약어 동의어 확장 사전
    DOMAIN_TERMS = {
        r"\bmas\b": "다수공급자계약 조달 나라장터",
        r"\bota\b": "무선 펌웨어 업데이트",
        r"\bgis\b": "지도 지리정보시스템",
        r"\bpcba\b": "회로기판 하드웨어",
        r"\blte\b": "cat.m1 무선 통신",
        r"\bpim\b": "제품정보 조달 물품식별번호",
    }
    expanded_parts = []
    for pat, exp in DOMAIN_TERMS.items():
        if re.search(pat, question, re.IGNORECASE):
            expanded_parts.append(exp)

    # 검색 쿼리 보강 (별칭이 감지된 경우 정규 한국어 이름을, 전문 용어는 동의어를 함께 검색어에 포함)
    extra_terms = " ".join(filter(None, [matched_name, " ".join(expanded_parts)]))
    search_q = f"{question} {extra_terms}".strip() if extra_terms else question

    # 1. 키워드 기반 기본 검색 (고유명사, Jira 키, 이름 정확 매칭에 강함)
    from services.auth import visible_records, can_view_record, can_view_pim_price
    records, _cache = merged_records(handler.cfg)
    records = visible_records(session, records)
    allow_price = can_view_pim_price(session)
    records = list(records) + [
        product_as_search_record(p, allow_price=allow_price)
        for p in read_products(include_external=True)
    ]
    if session is not None:
        owner_key = account_key(session["name"], session["org"])
        my_events = [e for e in read_schedule() if e.get("ownerKey") == owner_key]
        records += [schedule_event_as_search_record(e) for e in my_events]

    k_candidates = search_records(records, question, limit=30, extra_query=extra_terms)

    # 2. Voyage AI 벡터 의미 기반 검색 (문맥 및 동의어 이해에 강함)
    v_candidates = []
    if is_voyage_configured(handler.cfg):
        try:
            v_candidates = search_vector_store(handler.cfg, search_q, limit=30, min_similarity=0.15, session=session)
        except Exception as e:
            log_line(f"[Ask] 벡터 검색 오류: {str(e)}")
            v_candidates = []

    # 3. 하이브리드 결합 (Hybrid Fusion & Entity Boosting)
    if v_candidates:
        search_method = "voyage_vector"
        merged = {}

        # 1. AI 벡터 검색 결과 (의미/문맥 기반 기본 뼈대, sim * 2.5 가중치 부여)
        for r in v_candidates:
            rid = str(r.get("id") or r.get("doc_id") or r.get("title"))
            if rid.startswith("jira:"):
                rid = "jira-" + rid[5:]
            elif rid.startswith("product:"):
                rid = "product-" + rid[8:]
            elif rid.startswith("record:"):
                rid = rid[7:]

            sim = r.get("similarity", 0)
            score = sim * 2.5
            assignee = str(r.get("assignee") or r.get("ownerName") or "")
            if matched_name and (matched_name in assignee or matched_name in str(r.get("title", ""))):
                score += 2.5
            merged[rid] = {"item": r, "score": score}

        # 2. 키워드 검색 결과 (보조 가중치, 상위 랭크별 0.05 ~ 0.4점)
        for idx, r in enumerate(k_candidates):
            rid = str(r.get("id") or (r.get("jira") or {}).get("key") or r.get("title"))
            if rid.startswith("jira:"):
                rid = "jira-" + rid[5:]
            elif rid.startswith("product:"):
                rid = "product-" + rid[8:]

            k_score = max(0.05, (10 - idx) * 0.04)
            assignee = str(r.get("assignee") or r.get("ownerName") or "")
            if matched_name and (matched_name in assignee or matched_name in str(r.get("title", ""))):
                k_score += 2.5

            if rid in merged:
                merged[rid]["score"] += k_score
                for k, v in r.items():
                    if v and not merged[rid]["item"].get(k):
                        merged[rid]["item"][k] = v
            else:
                merged[rid] = {"item": r, "score": k_score}

        # 3. 사용자 원본 질의어 제목 일치 대폭 우대 (Exact Title / Key Match Boost)
        q_tokens_clean = [t.lower() for t in re.findall(r"[\w]+", question) if len(t) >= 2 or ord(t[0]) >= 0xAC00]
        for rid, entry in merged.items():
            item = entry["item"]
            title_text = str(item.get("title") or "").lower()
            jk = str((item.get("jira") or {}).get("key") or "").lower()
            cc = str(item.get("cardCode") or "").lower().lstrip("#")
            for qt in q_tokens_clean:
                if qt in (jk, cc) or (len(qt) >= 2 and re.search(r'\b' + re.escape(qt) + r'\b', title_text)):
                    entry["score"] += 1.8
                    break

        # 상위 연관 티켓의 상위 업무(parentKey) 및 하위 작업(subtasks) 자동 포함
        related_keys = set()
        for x in sorted(merged.values(), key=lambda item: item["score"], reverse=True)[:6]:
            item = x["item"]
            pk = item.get("parentKey")
            if pk:
                related_keys.add(pk)
            for stk in (item.get("subtasks") or []):
                related_keys.add(stk)

        if related_keys:
            rel_upper = {str(k).strip().upper() for k in related_keys}
            for r in records:
                jk = str((r.get("jira") or {}).get("key") or "").strip().upper()
                cc = str(r.get("cardCode") or "").strip().upper()
                rid_str = str(r.get("id") or "")
                if (jk and jk in rel_upper) or (cc and cc in rel_upper) or rid_str in rel_upper:
                    target_id = "jira-" + jk if jk else ("record-" + rid_str if rid_str else cc)
                    if target_id not in merged:
                        merged[target_id] = {"item": r, "score": 0.75}

        sorted_items = sorted(merged.values(), key=lambda x: (x["item"].get("similarity") or 0, x["score"]), reverse=True)

        # 특정 인물(matched_name) 질의 시 해당 인물과 관련된 항목(score >= 2.0) 우선
        if matched_name:
            matched_items = [x for x in sorted_items if x["score"] >= 2.0]
            candidates = [x["item"] for x in (matched_items or sorted_items)[:20]]
        else:
            candidates = [x["item"] for x in sorted_items[:20]]
    else:
        # 키워드 검색의 경우 점수를 0.0 ~ 1.0 범위 유사도로 정규화하여 높은 순으로 정렬
        max_k_score = max([r.get("_search_score", 1.0) for r in k_candidates], default=1.0)
        for r in k_candidates:
            raw_s = r.get("_search_score", 0.0)
            if "similarity" not in r or r["similarity"] is None:
                r["similarity"] = round(min(0.99, max(0.40, raw_s / max(max_k_score, 10.0))), 2)

        if matched_name:
            matched_k = [r for r in k_candidates if matched_name in str(r.get("assignee") or r.get("ownerName") or "") or matched_name in str(r.get("title", ""))]
            candidates = (matched_k or k_candidates)[:20]
        else:
            candidates = k_candidates[:20]
        
        candidates.sort(key=lambda r: (r.get("similarity") or 0, r.get("_search_score") or 0), reverse=True)
        search_method = "keyword"

    # RBAC 최종 게이트: 융합/키워드/상·하위 자동 확장 등 모든 경로의 결과는
    # 사용자 열람 권한을 통과한 항목만 AI 컨텍스트와 출처 목록에 포함한다.
    from services.auth import can_view_search_item
    candidates = [c for c in candidates if can_view_search_item(session, c)]

    # AI 질문 컨텍스트 (프롬프트에 임의의 안내문이나 특정 인명을 주입하지 않고 질문 원문 유지)
    ai_question = question

    # AI에게는 상위 6건의 가장 관련도 높은 컨텍스트 제공
    ai_context_candidates = candidates[:6]
    answer = call_ai_answer(handler.cfg, ai_question, ai_context_candidates)
    ai_info = get_ai_config(handler.cfg)
    handler._send_json(200, {
        "ok": True,
        "question": question,
        "answer": answer,
        "searchMethod": search_method,
        "aiEnabled": bool(ai_info.get("enabled") and (ai_info.get("api_key") or ai_info.get("provider") == "ollama")),
        "aiProvider": ai_info.get("provider"),
        "sources": [{
            "id": r.get("id"), "title": r.get("title"), "org": r.get("org"),
            "category": r.get("category"), "date": r.get("date"),
            "summary": (r.get("summary") or "")[:200],
            "similarity": r.get("similarity"),
            "jira": r.get("jira"),
            "cardCode": r.get("cardCode") or (r.get("jira") or {}).get("key") or (f"#{r.get('id')}" if r.get("id") else ""),
            "isProduct": bool(str(r.get("id", "")).startswith(("product-", "pim-")) or r.get("productLink")),
            "productId": (
                (r.get("productLink") or {}).get("id") or 
                (re.sub(r"^(product-|pim-)", "", str(r.get("id", ""))) if str(r.get("id", "")).startswith(("product-", "pim-")) else None)
            )
        } for r in candidates]
    })
    access_log(ip, "ask", 200, question[:80])

def handle_get_vector_stats(handler, parsed, ip):
    session = handler._get_session_or_401()
    if not session:
        return
    stats = get_vector_stats()
    stats["voyageConfigured"] = is_voyage_configured(handler.cfg)
    stats["model"] = handler.cfg.get("voyage", {}).get("model", "voyage-3-lite")
    handler._send_json(200, {"ok": True, "stats": stats})

def handle_get_activities(handler, parsed, ip):
    session = handler._get_session_optional()
    from services.auth import is_manager_or_admin
    if not session or not is_manager_or_admin(session):
        handler._send_json(403, {"ok": False, "error": "부서장(Manager) 이상의 권한이 필요합니다.", "authRequired": True})
        return

    qs = parse_qs(parsed.query)
    target_date = qs.get("date", [""])[0] or datetime.now().strftime("%Y-%m-%d")

    activities = get_daily_activities(target_date)
    recent_dates = get_recent_activity_dates(7)
    handler._send_json(200, {
        "ok": True,
        "date": target_date,
        "activities": activities,
        "total": len(activities),
        "recentDates": recent_dates
    })
    access_log(ip, "activities", 200, f"date={target_date} total={len(activities)}")

def handle_get_notifications(handler, parsed, ip):
    session = handler._get_session_or_401()
    if not session:
        return
    user_name = session.get("name")
    user_email = session.get("email")
    from services.auth import is_admin_user
    is_adm = is_admin_user(session)

    notifs = get_user_notifications(user_email=user_email, user_name=user_name, is_admin=is_adm, limit=50)
    unread_count = sum(1 for n in notifs if not n.get("is_read"))
    handler._send_json(200, {
        "ok": True,
        "notifications": notifs,
        "total": len(notifs),
        "unread": unread_count
    })
    access_log(ip, "notifications", 200, f"user={user_name} total={len(notifs)} unread={unread_count}")

def handle_get_notifications_stream(handler, parsed, ip):
    """GET /api/notifications/stream - Realtime Server-Sent Events (SSE) notification stream"""
    session = handler._get_session_or_401()
    if not session:
        return
    user_name = session.get("name", "")
    user_email = session.get("email", "")

    handler._start_sse()
    import queue
    from services.notification_service import subscribe_notifications, unsubscribe_notifications

    q = queue.Queue(maxsize=32)
    # Each subscriber only receives its own notifications (no cross-user fan-out).
    try:
        is_notif_admin = is_admin_user(session)
    except Exception:
        is_notif_admin = False
    subscribe_notifications(q, {
        "email": user_email,
        "name": user_name,
        "is_admin": is_notif_admin,
    })

    # Initial ping
    handler._send_sse_event({"event": "connected", "user": user_name, "time": datetime.now().isoformat()})

    try:
        cycles = 0
        max_cycles = 45  # 15 minutes max per SSE connection to cycle HTTP threads
        while cycles < max_cycles:
            cycles += 1
            try:
                event = q.get(timeout=20)
                handler._send_sse_event({"event": event["type"], "data": event["data"]})
            except queue.Empty:
                # Keep-alive heartbeat comment every 20 seconds
                handler.wfile.write(b": ping\n\n")
                handler.wfile.flush()
    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
        pass
    finally:
        unsubscribe_notifications(q)

def handle_post_notification_read(handler, raw_body, ip):
    session = handler._get_session_or_401()
    if not session:
        return
    try:
        body = json.loads(raw_body.decode('utf-8')) if raw_body else {}
    except Exception:
        body = {}
    notif_id = body.get("id", "")
    if not notif_id:
        handler._send_json(400, {"ok": False, "error": "알림 ID가 필요합니다."})
        return
    # Chống IDOR: chỉ chủ sở hữu notification (hoặc broadcast) mới được đánh dấu đã đọc
    from db import get_one
    from services.auth import user_can_access_notification
    notif_row = get_one("SELECT * FROM notifications WHERE id = ?", (notif_id,))
    if not notif_row or not user_can_access_notification(session, notif_row):
        handler._send_json(404, {"ok": False, "error": "알림을 찾을 수 없습니다."})
        return

    ok = mark_notification_as_read(notif_id)
    handler._send_json(200, {"ok": ok})
    access_log(ip, "notif_read", 200, f"id={notif_id} by {session.get('name')}")

def handle_post_notification_read_all(handler, raw_body, ip):
    session = handler._get_session_or_401()
    if not session:
        return
    user_name = session.get("name")
    user_email = session.get("email")
    from services.auth import is_admin_user
    is_adm = is_admin_user(session)

    ok = mark_all_notifications_as_read(user_email=user_email, user_name=user_name, is_admin=is_adm)
    handler._send_json(200, {"ok": ok})
    access_log(ip, "notif_read_all", 200, f"user={user_name}")

_vector_sync_rate_limits = {}
_vector_sync_rate_lock = threading.Lock()

def handle_post_vector_sync(handler, raw_body, ip):
    session = handler._get_session_or_401()
    if not session:
        return

    from services.auth import is_manager_or_admin
    if not is_manager_or_admin(session):
        handler._send_json(403, {"ok": False, "error": "벡터 색인 동기화는 부서 관리자(Manager) 또는 시스템 관리자(Admin)만 실행할 수 있습니다."})
        return

    # Dedicated Rate Limit: 1 per minute per user
    user_key = f"{session.get('id') or session.get('name')}:{ip}"
    now = time.time()
    with _vector_sync_rate_lock:
        last_time = _vector_sync_rate_limits.get(user_key, 0)
        if now - last_time < 60:
            remaining = int(60 - (now - last_time))
            handler._send_json(429, {"ok": False, "error": f"벡터 동기화 요청이 너무 빈번합니다. {remaining}초 후 다시 시도해주세요. (1분당 1회 제한)"})
            return
        _vector_sync_rate_limits[user_key] = now

    body = {}
    if raw_body:
        try:
            body = json.loads(raw_body.decode('utf-8'))
        except Exception:
            body = {}

    check_only = bool(body.get("check_only"))
    force = bool(body.get("force") or body.get("force_reindex"))

    if check_only:
        status = check_vector_sync_status(handler.cfg)
        handler._send_json(200, status)
        return

    # Check if already fully synced with current model
    if not force:
        status = check_vector_sync_status(handler.cfg)
        if status.get("is_fully_synced"):
            handler._send_json(200, {
                "ok": True,
                "already_synced": True,
                "total": status.get("total", 0),
                "indexed": 0,
                "current_model": status.get("current_model"),
                "message": f"모든 {status.get('total', 0)}건 데이터가 [{status.get('current_model')}] 모델로 이미 완벽히 색인되어 있습니다. (소모 토큰: 0)"
            })
            return

    # Execute sync with model tracking
    res = sync_all_vectors(handler.cfg, force=force)
    handler._send_json(200, res)

def norm_member_key(name, org):
    base = assignee_base_name(name) or (name or "").strip()
    return base + "|" + (org or "").strip()

def handle_get_schedule(handler, parsed, ip):
    session = handler._get_session_or_401()
    if session is None:
        return
    owner_key = norm_member_key(session["name"], session["org"])

    role = session.get("role", "member")
    is_admin = bool(role == "admin" or session.get("is_admin") == 1)
    user_dept = (session.get("org") or session.get("dept_id") or "").strip().lower()
    user_name = (session.get("name") or "").strip()

    # 0. 사원-부서 맵 구성 (권한 필터링 및 이름 정규화 기준) — auth 헬퍼와 공유
    from services.auth import build_user_dept_map, visible_schedule_events
    user_dept_map = build_user_dept_map()

    # 1. 로컬 수동 등록 일정 (RBAC: admin 전체, 그 외 본인 부서/본인/참여 일정만 — 챗봇 도구와 동일 기준)
    all_events = visible_schedule_events(session, read_schedule(), user_dept_map=user_dept_map)

    seen_card_codes = set()
    for ev in all_events:
        if ev.get("cardCode"):
            seen_card_codes.add(str(ev["cardCode"]).upper())

    # 2. 로컬 업무 카드 (records)의 일정을 달력 이벤트로 자동 반영 & 미완료 목록 수집
    # RBAC: user와 manager는 본인 소속 부서 카드(또는 본인 담당 카드)만 달력 및 우측 미배정 패널에 표시
    local_records = read_records()
    if not is_admin:
        # 비공개(private) 카드는 can_view_record 로 한 번 더 검증한다.
        # (부서/담당자 조건만으로는 같은 부서의 타인 비공개 카드가 캘린더에 노출된다)
        from services.auth import can_view_record
        filtered_records = []
        for r in local_records:
            if bool(r.get("is_private")) and not can_view_record(session, r):
                continue
            r_assignee = (r.get("assignee") or r.get("assignee_name") or "").strip()
            r_org = (r.get("org") or r.get("dept_id") or user_dept_map.get(assignee_base_name(r_assignee).lower(), {}).get("org", "")).strip().lower()
            if (user_dept and r_org == user_dept) or (r_assignee and r_assignee == user_name):
                filtered_records.append(r)
        local_records = filtered_records

    local_tasks = []
    for r in local_records:
        raw_start = (r.get("startDate") or r.get("start_date") or r.get("work_date") or "").strip()
        raw_end = (r.get("endDate") or r.get("end_date") or r.get("dueDate") or r.get("due_date") or "").strip()

        # range 형태 파싱: "2026-10-14 ~ 2026-10-18"
        s_date = ""
        e_date = ""
        if "~" in raw_start:
            parts = [x.strip() for x in raw_start.split("~")]
            s_date = parts[0]
            e_date = parts[1] if len(parts) > 1 and parts[1] else s_date
        elif raw_start:
            s_date = raw_start
            e_date = raw_end or s_date
        elif raw_end:
            s_date = raw_end
            e_date = raw_end

        if s_date and e_date and s_date > e_date:
            s_date, e_date = e_date, s_date

        code = r.get("cardCode") or f"REC-{r.get('id')}"
        status = r.get("status") or "진행"
        assignee = r.get("assignee") or r.get("assignee_name") or "미지정"
        org = r.get("org") or r.get("dept_id") or ""
        is_sched = bool(r.get("is_scheduled", 1))

        # 기간 텍스트
        display_work_date = ""
        if s_date and e_date and s_date != e_date:
            display_work_date = f"{s_date} ~ {e_date}"
        elif s_date:
            display_work_date = s_date
        elif e_date:
            display_work_date = e_date

        # 미배정/진행중 업무 목록 (우측 패널용)
        if status != "완료":
            local_tasks.append({
                "id": r.get("id"),
                "cardCode": code,
                "title": r.get("title") or "(제목 없음)",
                "assignee": assignee,
                "org": org,
                "status": status,
                "startDate": s_date,
                "endDate": e_date,
                "date": s_date,
                "work_date": display_work_date,
                "is_scheduled": is_sched,
                "jira": r.get("jira")
            })

        # 날짜(시작일 또는 마감일)가 지정되고 is_scheduled가 True인 카드만 달력 이벤트로 표시
        rec_ident = f"rec-{r.get('id')}"
        if s_date and is_sched and rec_ident not in seen_card_codes:
            seen_card_codes.add(rec_ident)
            all_events.append({
                "id": rec_ident,
                "recordId": r.get("id"),
                "ownerKey": norm_member_key(assignee, org),
                "ownerName": assignee,
                "ownerOrg": org,
                "ownerEmail": r.get("assigneeEmail", ""),
                "type": "업무",
                "title": r.get("title") or "(제목 없음)",
                "startDate": s_date,
                "endDate": e_date or s_date,
                "memo": r.get("summary") or r.get("memo") or "",
                "createdAt": r.get("created_at") or "",
                "source": "local",
                "cardCode": code,
                "status": status,
                "jira": (r.get("jira") if bool(handler.cfg.get("jira", {}).get("enabled", False)) else None)
            })

    # 3. 모든 팀원의 Jira 마감일 일정 병합 (Jira 연동이 활성화된 경우에만)
    jira_cfg = handler.cfg.get("jira", {}) if handler.cfg else {}
    jira_active = bool(jira_cfg.get("enabled", False))
    if jira_active:
        try:
            jira_events = all_jira_due_date_events(handler.cfg)
            if not is_admin:
                jira_events = [
                    ev for ev in jira_events
                    if (bool(user_dept and (ev.get("ownerOrg") or user_dept_map.get(assignee_base_name(ev.get("ownerName", "")).lower(), {}).get("org", "")).strip().lower() == user_dept))
                    or ev.get("ownerName") == user_name
                ]
            all_events += jira_events
        except Exception:
            pass
    all_events.sort(key=lambda e: (e.get("startDate", ""), str(e.get("id", 0))))

    # 4. 팀원(멤버) 목록 종합 (계정 + 등록일정 + 업무기록 + Jira 이슈 종합, 사원 기준 고유 정규화)
    # RBAC: user와 manager는 본인 부서 팀원만 표시, admin은 전체 표시
    members_map = {}

    def add_member(name, org="", email=""):
        if not name or "기업부설연구소" in name or name in ("Unassigned", "None", "-", ""):
            return
        bn = assignee_base_name(name).strip().lower()
        if not bn:
            return

        official = user_dept_map.get(bn)
        actual_name = (official["name"] if official else name).strip()
        actual_org = (official["org"] if official else (org or "lab")).strip()
        actual_email = ((official["email"] if official else email) or "").strip()

        # RBAC: user와 manager는 본인 부서 소속 팀원만 추가 (본인은 항상 포함)
        if not is_admin:
            if user_dept and actual_org.lower() != user_dept and actual_name != user_name:
                return

        nk = norm_member_key(actual_name, actual_org)
        if bn not in members_map:
            members_map[bn] = {
                "key": nk,
                "name": actual_name,
                "org": actual_org,
                "email": actual_email
            }
        else:
            if actual_email and not members_map[bn]["email"]:
                members_map[bn]["email"] = actual_email

    # 현재 로그인 사용자 보장 추가
    add_member(session.get("name"), session.get("org") or "lab", session.get("email", ""))

    # DB에 등록된 사용자 등록 (Admin: 전체 부서 사용자, User/Manager: 자기 부서 사용자만)
    for bn, uinfo in user_dept_map.items():
        if is_admin or not user_dept or (uinfo["org"] or "").strip().lower() == user_dept:
            add_member(uinfo["name"], uinfo["org"], uinfo["email"])

    for ev in all_events:
        name = ev.get("ownerName")
        org = ev.get("ownerOrg") or ""
        add_member(name, org, ev.get("ownerEmail", ""))

    for r in local_records:
        add_member(r.get("assignee"), r.get("org") or "", r.get("assigneeEmail", ""))

    if jira_active:
        try:
            for r in get_cached_jira_records(handler.cfg).get("records", []):
                add_member(r.get("assignee"), r.get("org") or "")
        except Exception:
            pass

    org_order = {"lab": 1, "sales": 2, "dept_1a0a878496f": 3}
    members = list(members_map.values())
    members.sort(key=lambda m: (org_order.get(m["org"], 99), m["org"], m["name"]))

    # 모든 이벤트의 ownerKey를 members_map의 key와 100% 일치하도록 보정
    name_to_canonical = {}
    for m in members:
        bn = assignee_base_name(m["name"]).lower()
        if bn and bn not in name_to_canonical:
            name_to_canonical[bn] = m["key"]

    for ev in all_events:
        bn = assignee_base_name(ev.get("ownerName", "")).lower()
        if bn in name_to_canonical:
            ev["ownerKey"] = name_to_canonical[bn]
        else:
            ev["ownerKey"] = norm_member_key(ev.get("ownerName"), ev.get("ownerOrg", ""))

    jira_ongoing = jira_ongoing_records_for(handler.cfg, session["name"], session["org"], session.get("email")) if jira_active else []
    handler._send_json(200, {
        "ok": True,
        "events": all_events,
        "members": members,
        "myKey": owner_key,
        "localTasks": local_tasks,
        "jiraOngoing": jira_ongoing
    })


def _broadcast_schedule_task_changed(task_id):
    try:
        from services.notification_service import broadcast_notification_event
        broadcast_notification_event("schedule_changed", {
            "recipient_email": "",
            "recipient_name": "",
            "action": "task_changed",
            "id": str(task_id)
        })
    except Exception:
        pass


def handle_assign_schedule_task(handler, raw_body, ip):
    """POST /api/schedule/assign-task — 카드를 특정 날짜로 드래그 앤 드롭하여 일정 배정"""
    session = handler._get_session_or_401()
    if session is None:
        return
    try:
        payload = json.loads(raw_body.decode("utf-8") or "{}")
    except Exception:
        handler._send_json(400, {"ok": False, "error": "잘못된 요청"})
        return
    task_id = payload.get("taskId") or payload.get("cardCode")
    new_date = str(payload.get("date") or "").strip()
    end_date = str(payload.get("endDate") or "").strip()
    is_unassign = bool(payload.get("unassign")) or new_date.lower() == "unassign"

    if not task_id:
        handler._send_json(400, {"ok": False, "error": "taskId가 필요합니다."})
        return

    # RBAC: chỉ người được phép sửa card mới được đổi lịch (viewer bị chặn)
    from services.data_store import find_record_by_key_or_code
    from services.auth import check_record_write_access
    from services.license_manager import is_system_read_only
    target_rec = find_record_by_key_or_code(task_id)
    if target_rec:
        if is_system_read_only():
            handler._send_json(403, {"ok": False, "error": "라이선스가 만료되어 시스템이 읽기 전용(Read-Only) 상태입니다. 관리자에게 문의하세요."})
            return
        allowed, deny_err = check_record_write_access(session, target_rec)
        if not allowed:
            access_log(ip, "forbidden_assign_schedule_task", 403,
                       f"{task_id} by {session.get('name')}")
            handler._send_json(403, {"ok": False, "error": deny_err})
            return

    action = payload.get("action")
    if action == "show" or payload.get("restore"):
        from services.data_store import set_record_schedule_visibility
        rec_id, jira_key = set_record_schedule_visibility(task_id, True)
        if not rec_id:
            handler._send_json(404, {"ok": False, "error": f"해당 업무 카드 [{task_id}]를 찾을 수 없습니다."})
            return
        access_log(ip, "show_schedule_task", 200, f"{task_id}")
        _broadcast_schedule_task_changed(task_id)
        handler._send_json(200, {
            "ok": True,
            "taskId": task_id,
            "cardCode": task_id,
            "is_scheduled": True
        })
        return

    if is_unassign or not new_date:
        from services.data_store import clear_record_work_date
        rec_id, jira_key = clear_record_work_date(task_id, wipe_dates=bool(payload.get("wipeDates")))
        if not rec_id:
            handler._send_json(404, {"ok": False, "error": f"해당 업무 카드 [{task_id}]를 찾을 수 없습니다."})
            return
        access_log(ip, "unassign_schedule_task", 200, f"{task_id}")
        _broadcast_schedule_task_changed(task_id)
        _audit(session, ip, "RECORD_SCHEDULE_UNASSIGN", "record", task_id,
               {"wipeDates": bool(payload.get("wipeDates"))})
        handler._send_json(200, {
            "ok": True,
            "taskId": task_id,
            "cardCode": task_id,
            "unassigned": True
        })
        return

    if end_date and end_date != new_date:
        saved_date = f"{new_date} ~ {end_date}"
    else:
        saved_date = new_date

    from services.data_store import update_record_work_date
    rec_id, jira_key = update_record_work_date(task_id, saved_date)
    if not rec_id:
        handler._send_json(404, {"ok": False, "error": f"해당 업무 카드 [{task_id}]를 찾을 수 없습니다."})
        return

    jira_enabled = bool(handler.cfg.get("jira", {}).get("enabled", True))

    # Thẻ có Jira: chỉ chạy ngầm đồng bộ lên Jira REST API khi Jira đang BẬT
    if jira_enabled and jira_key and handler.cfg:
        try:
            import threading
            from services.jira_client import update_jira_issue_dates
            threading.Thread(
                target=update_jira_issue_dates,
                args=(handler.cfg, jira_key, new_date, end_date or new_date),
                daemon=True
            ).start()
        except Exception:
            pass

    access_log(ip, "assign_schedule_task", 200, f"{task_id} -> {saved_date}")
    _broadcast_schedule_task_changed(task_id)
    _audit(session, ip, "RECORD_SCHEDULE_ASSIGN", "record", task_id,
           {"date": saved_date, "endDate": end_date or saved_date})
    handler._send_json(200, {
        "ok": True,
        "taskId": task_id,
        "cardCode": task_id,
        "date": saved_date,
        "jiraKey": (jira_key if jira_enabled else None)
    })

def handle_unassign_schedule_task(handler, raw_body, ip):
    """POST /api/schedule/unassign-task — 카드의 일정을 제거(미배정 상태로 환원)"""
    session = handler._get_session_or_401()
    if session is None:
        return
    try:
        payload = json.loads(raw_body.decode("utf-8") or "{}")
    except Exception:
        handler._send_json(400, {"ok": False, "error": "잘못된 요청"})
        return
    task_id = payload.get("taskId") or payload.get("cardCode")
    if not task_id:
        handler._send_json(400, {"ok": False, "error": "taskId가 필요합니다."})
        return

    from services.data_store import find_record_by_key_or_code
    from services.auth import check_record_write_access
    from services.license_manager import is_system_read_only
    target_rec = find_record_by_key_or_code(task_id)
    if target_rec:
        if is_system_read_only():
            handler._send_json(403, {"ok": False, "error": "라이선스가 만료되어 시스템이 읽기 전용(Read-Only) 상태입니다. 관리자에게 문의하세요."})
            return
        allowed, deny_err = check_record_write_access(session, target_rec)
        if not allowed:
            access_log(ip, "forbidden_unassign_schedule_task", 403,
                       f"{task_id} by {session.get('name')}")
            handler._send_json(403, {"ok": False, "error": deny_err})
            return

    wipe_dates = bool(payload.get("wipeDates"))
    from services.data_store import clear_record_work_date
    rec_id, jira_key = clear_record_work_date(task_id, wipe_dates=wipe_dates)
    if not rec_id:
        handler._send_json(404, {"ok": False, "error": f"해당 업무 카드 [{task_id}]를 찾을 수 없습니다."})
        return

    access_log(ip, "unassign_schedule_task", 200, f"{task_id}")
    _broadcast_schedule_task_changed(task_id)
    _audit(session, ip, "RECORD_SCHEDULE_UNASSIGN", "record", task_id,
           {"wipeDates": wipe_dates})
    handler._send_json(200, {
        "ok": True,
        "taskId": task_id,
        "cardCode": task_id,
        "unassigned": True
    })

def handle_get_products_categories(handler, parsed, ip):
    session = handler._get_session_or_401()
    if not session:
        return
    categories, templates = get_product_categories_and_templates()
    handler._send_json(200, {"ok": True, "categories": categories, "templates": templates})

def handle_get_products(handler, parsed, ip):
    session = handler._get_session_or_401()
    if not session:
        return
    qs = parse_qs(parsed.query)
    q = (qs.get("q", [""])[0])
    # 사내 관리 제품만 반환 (공식 라이브 제품은 벡터 DB/검색용으로만 사용되며 사내 목록에는 미노출)
    products = read_products(include_external=False)
    products.sort(key=lambda p: p.get("model", ""))
    filtered = search_products(products, q)
    from services.auth import can_view_pim_price
    if not can_view_pim_price(session):
        filtered = [dict(p, price=0, priceHidden=True) for p in filtered]
    handler._send_json(200, {"ok": True, "products": filtered, "total": len(filtered)})

def handle_get_products_attachment(handler, parsed, ip):
    session = handler._get_session_or_401()
    if not session:
        return
    qs = parse_qs(parsed.query)
    pid = (qs.get("id", [""])[0])
    fname = (qs.get("file", [""])[0])
    product = next((p for p in read_products(include_external=True) if p.get("id") == pid), None)
    attachments = (product or {}).get("attachments") or []
    match = next((a for a in attachments if a.get("name") == fname), None)
    if not product or not match:
        handler._send_json(404, {"ok": False, "error": "첨부파일을 찾을 수 없습니다."})
        return
    # Strict Directory Traversal Defense (same rule as record attachments):
    # two-step containment — the product folder must stay inside the products root AND
    # the attachment must stay inside that product folder. A single commonpath check
    # against PRODUCT_ATTACH_DIR would still allow "…/P-1/../P-2/secret".
    from utils.file_ops import safe_join
    product_dir = safe_join(PRODUCT_ATTACH_DIR, pid)
    file_path = safe_join(product_dir, match["name"]) if product_dir else None
    if not file_path or not os.path.isfile(file_path):
        handler._send_json(404, {"ok": False, "error": "첨부파일을 찾을 수 없습니다."})
        return
    handler._send_attachment(file_path, match["name"])
    access_log(ip, "product_attachment_download", 200, "%s %s" % (pid, fname))

def handle_get_product_detail(handler, parsed, ip):
    session = handler._get_session_or_401()
    if not session:
        return
    qs = parse_qs(parsed.query)
    raw_pid = (qs.get("id", [""])[0]).strip()
    if not raw_pid:
        handler._send_json(400, {"ok": False, "error": "id가 필요합니다."})
        return
    pid = re.sub(r"^(product-|pim-)", "", raw_pid)

    product = next((p for p in read_products(include_external=True) if p.get("id") == pid or p.get("model") == raw_pid), None)
    if not product:
        handler._send_json(404, {"ok": False, "error": "제품 정보를 찾을 수 없습니다."})
        return

    from services.auth import can_view_pim_price
    allow_price = can_view_pim_price(session)

    model = product.get("model", "")
    category = product.get("category", "")
    summary = product.get("summary", "")
    memo = product.get("memo", "")
    specs = product.get("specs") or {}
    proc = dict(product.get("procurement") or {})
    if not allow_price:
        if "price" in proc:
            proc["price"] = 0
        if "unitPrice" in proc:
            proc["unitPrice"] = 0
        proc["priceHidden"] = True
    source = product.get("source") or "internal"
    is_live = False

    attachments = product.get("attachments") or []
    image_attach = next((a for a in attachments if re.search(r"\.(png|jpg|jpeg|webp|gif)$", a.get("name", ""), re.I)), None)
    pdf_attach = next((a for a in attachments if re.search(r"\.pdf$", a.get("name", ""), re.I)), None)

    image_url = f"/api/products/attachment?id={product['id']}&file={image_attach['name']}" if image_attach else ""
    pdf_url = f"/api/products/attachment?id={product['id']}&file={pdf_attach['name']}" if pdf_attach else ""
    source_url = ""

    bullets = []
    if summary:
        bullets = [b.strip().lstrip("- ").lstrip("• ") for b in summary.split("\n") if b.strip() and not b.strip().startswith("---")]

    handler._send_json(200, {
        "ok": True,
        "detail": {
            "id": product.get("id"),
            "model": model,
            "category": category,
            "displayName": product.get("displayName") or model,
            "lifecycle": product.get("lifecycle") or "판매 중",
            "family": product.get("family") or "",
            "procurementNo": proc.get("identificationNo", ""),
            "procurement": proc,
            "price": product.get("price") if allow_price else 0,
            "priceHidden": not allow_price,
            "currency": product.get("currency") or "KRW",
            "sourceUrl": source_url,
            "catalogPdf": pdf_url,
            "image": image_url,
            "bullets": bullets,
            "specs": specs,
            "summary": summary,
            "memo": memo if not is_live else "",
            "source": source,
            "isOfficial": is_live
        }
    })

def handle_get_issue_detail(handler, parsed, ip):
    session = handler._get_session_or_401()
    if not session:
        return
    qs = parse_qs(parsed.query)
    key = qs.get("key", [""])[0]
    if not key and parsed.path.startswith("/api/issues/"):
        key = parsed.path.split("/api/issues/")[1].split("/")[0].split("?")[0]
    if not key:
        handler._send_json(400, {"ok": False, "error": "이슈 키(key)가 필요합니다."})
        return
    issue = get_jira_issue_by_key(handler.cfg, key)
    if not issue:
        handler._send_json(404, {"ok": False, "error": f"{key} 이슈를 찾을 수 없습니다."})
        return

    # RBAC: 목록/검색에서 숨겨진 카드라도 상세 URL로 직접 열람할 수 없도록 서버에서 강제 검증.
    # (존재 여부 자체를 노출하지 않기 위해 403 대신 404 로 응답한다)
    from services.auth import can_view_record, filter_issue_payload_by_permission
    if not can_view_record(session, issue):
        try:
            from services.audit_logger import log_audit
            log_audit(session=session, ip=ip, action="RBAC_DENIED_READ",
                      target_type="issue", target_id=key,
                      details={"endpoint": "/api/issues"})
        except Exception:
            pass
        handler._send_json(404, {"ok": False, "error": f"{key} 이슈를 찾을 수 없습니다."})
        return

    # 하위 작업/상위 작업/참여자 중 권한 밖 항목 제거
    issue = filter_issue_payload_by_permission(session, issue, cfg=handler.cfg)
    handler._send_json(200, issue)

def handle_get_jira_attachment(handler, parsed, ip):
    """Proxy Jira Cloud attachment download with server authentication."""
    session = handler._get_session_or_401()
    if not session:
        return
    path = parsed.path
    # /api/jira/attachments/{attachment_id}
    parts = [p for p in path.split("/") if p]
    if len(parts) < 4:
        handler._send_json(400, {"ok": False, "error": "첨부파일 ID가 필요합니다."})
        return
    attach_id = parts[3]

    # RBAC: 첨부파일이 속한 이슈/카드의 열람 권한을 검증한다 (IDOR 차단).
    # 매핑이 불가능한 첨부파일은 fail-closed 로 거부한다.
    from services.auth import can_view_record, resolve_record_by_key
    from services.jira_client import find_issue_key_by_attachment_id
    attach_issue_key = find_issue_key_by_attachment_id(handler.cfg, attach_id)
    attach_rec = resolve_record_by_key(attach_issue_key, cfg=handler.cfg) if attach_issue_key else None
    if not attach_rec or not can_view_record(session, attach_rec):
        try:
            from services.audit_logger import log_audit
            log_audit(session=session, ip=ip, action="RBAC_DENIED_READ",
                      target_type="jira_attachment", target_id=attach_id,
                      details={"endpoint": "/api/jira/attachments", "issueKey": attach_issue_key})
        except Exception:
            pass
        handler._send_json(403, {"ok": False, "error": "해당 첨부파일에 접근할 권한이 없습니다."})
        return

    j = handler.cfg.get("jira", {})
    if not j.get("enabled") or not j.get("api_token"):
        handler._send_json(500, {"ok": False, "error": "Jira 연동이 비활성화되어 있습니다."})
        return

    from services.jira_client import _jira_auth_header
    base_url = j.get("base_url", "").rstrip("/")
    url = f"{base_url}/rest/api/3/attachment/content/{attach_id}"
    req = urllib.request.Request(url, headers=_jira_auth_header(j))
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            content_type = resp.headers.get("Content-Type") or "application/octet-stream"
            content_disposition = resp.headers.get("Content-Disposition") or ""
            data = resp.read()

        qs = parse_qs(parsed.query)
        preview = qs.get("preview", ["0"])[0] == "1"

        if preview or content_type.startswith(("image/", "text/", "application/pdf")):
            fname_match = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', content_disposition)
            fname = fname_match.group(1) if fname_match else f"attachment_{attach_id}"
            content_disposition = f"inline; filename*=UTF-8''{urllib.parse.quote(fname)}"

        handler.send_response(200)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Content-Length", str(len(data)))
        if content_disposition:
            handler.send_header("Content-Disposition", content_disposition)
        handler.send_header("Access-Control-Allow-Origin", "*")
        handler.end_headers()
        handler.wfile.write(data)
    except Exception as e:
        handler._send_json(500, {"ok": False, "error": f"첨부파일 다운로드 실패: {e}"})

_AVATAR_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def _serve_avatar_file(handler, filename):
    """
    Serve an uploaded profile avatar: /api/attachments/avatars/<file>

    Avatars are stored under data/attachments/avatars (not per-record folders), so
    they cannot be resolved by the record-attachment path. The path is restricted
    to that directory and to image extensions (no traversal, no inline HTML/SVG).
    """
    fname = os.path.basename(filename or "")
    ext = os.path.splitext(fname)[1].lower()
    avatars_dir = os.path.join(ATTACH_DIR, "avatars")
    from utils.file_ops import safe_join
    file_path = safe_join(avatars_dir, fname)

    if not file_path or not fname or ext not in _AVATAR_EXTENSIONS or not os.path.isfile(file_path):
        handler._send_json(404, {"ok": False, "error": "프로필 이미지를 찾을 수 없습니다."})
        return

    content_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
    if hasattr(handler, "_stream_file"):
        handler._stream_file(file_path, content_type, download_name=fname, inline=True)
        return
    try:
        with open(file_path, "rb") as f:
            data = f.read()
        handler.send_response(200)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Content-Length", str(len(data)))
        handler.send_header("Content-Disposition", f"inline; filename*=UTF-8''{urllib.parse.quote(fname)}")
        handler.send_header("Cache-Control", "private, max-age=86400")
        handler.end_headers()
        handler.wfile.write(data)
    except Exception as e:
        handler._send_json(500, {"ok": False, "error": str(e)})


def handle_get_local_attachment(handler, parsed, ip):
    """Serve attachment file for a local record: /api/attachments/{record_id}/{filename}"""
    session = handler._get_session_or_401()
    if not session:
        return
    path = parsed.path
    parts = [urllib.parse.unquote(p) for p in path.split("/") if p]
    # ['api', 'attachments', record_id, filename...]
    if len(parts) < 4:
        handler._send_json(400, {"ok": False, "error": "잘못된 첨부파일 경로입니다."})
        return
    record_id = parts[2]
    filename = "/".join(parts[3:])

    # Profile avatars: /api/attachments/avatars/<file> (not a record attachment)
    if record_id == "avatars":
        _serve_avatar_file(handler, filename)
        return

    # 1. Tra cứu bản ghi và xác minh quyền can_view_record
    from services.data_store import find_record_by_key_or_code
    from services.auth import can_view_record
    from db import get_one
    
    rec = None
    try:
        rid_int = int(record_id)
        rec = get_one("SELECT * FROM records WHERE id = ? LIMIT 1", (rid_int,))
    except Exception:
        rec = find_record_by_key_or_code(record_id)

    if not rec:
        handler._send_json(404, {"ok": False, "error": "해당 업무 카드를 찾을 수 없습니다."})
        return

    if not can_view_record(session, rec):
        handler._send_json(403, {"ok": False, "error": "해당 업무 카드의 첨부파일을 열람할 권한이 없습니다."})
        return
    
    # 파일이 저장된 디렉터리는 항상 레코드의 실제 ID 기준이다.
    # (URL 세그먼트가 카드 코드일 수 있으므로 record_id 문자열을 그대로 쓰면 404/혼동 발생)
    rec_attach_dir = os.path.join(ATTACH_DIR, str(rec["id"]))

    # Strict Directory Traversal Defense: the resolved path must stay inside the
    # record's attachment directory (safe_join applies realpath + commonpath).
    from utils.file_ops import safe_join
    file_path = safe_join(rec_attach_dir, filename)

    if not file_path or not os.path.isfile(file_path):
        handler._send_json(404, {"ok": False, "error": "첨부파일을 찾을 수 없습니다."})
        return

    qs = parse_qs(parsed.query)
    preview = qs.get("preview", ["0"])[0] == "1"
    
    ct, _ = mimetypes.guess_type(file_path)
    content_type = ct or "application/octet-stream"
    ext = os.path.splitext(file_path)[1].lower()
    safe_inline_exts = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".pdf"}
    disp_type = "inline" if (preview and ext in safe_inline_exts) else "attachment"
    
    if hasattr(handler, "_stream_file"):
        handler._stream_file(file_path, content_type, download_name=os.path.basename(file_path), inline=(disp_type == "inline"), extra_headers=[("Content-Security-Policy", "sandbox")])
    else:
        try:
            with open(file_path, "rb") as f:
                data = f.read()
            handler.send_response(200)
            handler.send_header("Content-Type", content_type)
            handler.send_header("Content-Length", str(len(data)))
            handler.send_header("Content-Disposition", f"{disp_type}; filename*=UTF-8''{urllib.parse.quote(os.path.basename(file_path))}")
            handler.send_header("X-Content-Type-Options", "nosniff")
            handler.send_header("Content-Security-Policy", "sandbox")
            handler.send_header("Cache-Control", "no-cache")
            handler.end_headers()
            handler.wfile.write(data)
        except Exception as e:
            handler._send_json(500, {"ok": False, "error": str(e)})

def handle_post_issue_comment(handler, raw_body, ip):
    session = handler._get_session_or_401()
    if not session:
        return
    from services.auth import can_write_data
    if not can_write_data(session):
        handler._send_json(403, {"ok": False, "error": "읽기 전용(Viewer) 권한 사용자는 댓글을 작성할 수 없습니다."})
        return
    try:
        body = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except Exception:
        body = {}
    issue_key = (body.get("issue_key") or body.get("key") or "").strip()
    comment = (body.get("comment") or body.get("body") or "").strip()
    if not issue_key or not comment:
        handler._send_json(400, {"ok": False, "error": "이슈 키와 댓글 내용이 필요합니다."})
        return

    clean_id = issue_key.strip().upper().lstrip("#").replace("REC-", "").replace("LOCAL-", "").replace("JIRA-", "")
    local_rec = None
    if clean_id.isdigit():
        local_rec = get_record_by_id(int(clean_id))
    if not local_rec:
        from db import query
        found = query("SELECT id FROM records WHERE LOWER(card_code) = LOWER(?)", (issue_key.strip(),))
        if found:
            local_rec = get_record_by_id(found[0]["id"])

    if local_rec:
        from services.auth import can_view_record
        if not can_view_record(session, local_rec):
            handler._send_json(403, {"ok": False, "error": "해당 업무 카드를 열람하거나 댓글을 작성할 권한이 없습니다."})
            return
        add_record_comment(local_rec["id"], session.get("name") or "사용자", comment)
        try:
            from services.audit_logger import log_audit
            log_audit(session, ip, "RECORD_COMMENT", "record", str(local_rec["id"]), details={"comment_preview": comment[:80], "card_code": issue_key})
        except Exception:
            pass
        try:
            from services.activity_store import append_activity
            append_activity({
                "issue_key": issue_key,
                "action_type": "comment",
                "action_detail": comment,
                "author_name": session.get("name") or "사용자",
                "author_email": session.get("email") or "",
                "summary": local_rec.get("title") or issue_key,
                "status": local_rec.get("status") or "진행",
                "assignee_name": local_rec.get("assignee"),
                "assignee_dept": local_rec.get("org") or "연구소",
                "source": "jarvis"
            })
            trigger_comment_notification(
                record_id=issue_key,
                title=local_rec.get("title") or issue_key,
                author_name=session.get("name") or "사용자",
                comment_body=comment,
                assignee_name=local_rec.get("assignee") or "",
                assignee_email=local_rec.get("assignee_email") or ""
            )
        except Exception:
            pass
        access_log(ip, "issue_comment_local", 200, f"{issue_key} by {session.get('name')}")
        try:
            from services.vector_store import trigger_async_vector_sync
            trigger_async_vector_sync(handler.cfg)
        except Exception:
            pass
        handler._send_json(200, {"ok": True, "issue_key": issue_key, "comment": comment})
        return

    res, err = add_jira_comment(handler.cfg, issue_key, comment, author_name=session.get("name"))
    if err:
        handler._send_json(500, {"ok": False, "error": err})
        return
    try:
        from services.activity_store import append_activity
        from db import query
        iss_info = query("SELECT summary, status_name, issue_type, assignee_name, dept_id FROM jira_issues WHERE jira_key = ?", (issue_key,))
        iss_row = iss_info[0] if iss_info else {}
        append_activity({
            "issue_key": issue_key,
            "action_type": "comment",
            "action_detail": comment,
            "author_name": session.get("name") or "사용자",
            "author_email": session.get("email") or "",
            "summary": iss_row.get("summary") or issue_key,
            "status": iss_row.get("status_name") or "완료",
            "issue_type": iss_row.get("issue_type") or "작업",
            "assignee_name": iss_row.get("assignee_name") or session.get("name"),
            "assignee_dept": iss_row.get("dept_id") or "연구소",
            "source": "jarvis"
        })
    except Exception:
        pass
    access_log(ip, "issue_comment", 200, f"{issue_key} by {session.get('name')}")
    try:
        from services.vector_store import trigger_async_vector_sync
        trigger_async_vector_sync(handler.cfg)
    except Exception:
        pass
    handler._send_json(200, {"ok": True, "issue_key": issue_key, "comment": comment})

def handle_post_issue_transition(handler, raw_body, ip):
    session = handler._get_session_or_401()
    if not session:
        return
    try:
        body = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except Exception:
        body = {}
    issue_key = (body.get("issue_key") or body.get("key") or "").strip()
    status = (body.get("status") or "").strip()
    if not issue_key or not status:
        handler._send_json(400, {"ok": False, "error": "이슈 키와 변경할 상태가 필요합니다."})
        return

    clean_id = issue_key.strip().upper().lstrip("#").replace("REC-", "").replace("LOCAL-", "").replace("JIRA-", "")
    local_rec = None
    if clean_id.isdigit():
        local_rec = get_record_by_id(int(clean_id))
    if not local_rec:
        from db import query
        found = query("SELECT id FROM records WHERE LOWER(card_code) = LOWER(?)", (issue_key.strip(),))
        if found:
            local_rec = get_record_by_id(found[0]["id"])

    if local_rec:
        from services.license_manager import is_system_read_only
        if is_system_read_only():
            handler._send_json(403, {"ok": False, "error": "라이선스가 만료되어 시스템이 읽기 전용(Read-Only) 상태입니다. 관리자에게 문의하세요."})
            return
        from services.auth import can_transition_status
        can_trans, trans_err = can_transition_status(session, local_rec, status)
        if not can_trans:
            handler._send_json(403, {"ok": False, "error": trans_err or "해당 작업 카드의 상태를 변경할 권한이 없습니다."})
            return
        old_status = local_rec.get("status")
        update_record_status(local_rec["id"], status)
        if status in ("검토", "Review", "검토중"):
            try:
                from services.notification_service import trigger_review_request_notification
                trigger_review_request_notification(local_rec, session)
            except Exception:
                pass
        try:
            from services.audit_logger import log_audit
            log_audit(session, ip, "RECORD_STATUS_UPDATE", "record", str(local_rec["id"]), details={"old_status": old_status, "new_status": status, "card_code": issue_key})
        except Exception:
            pass
        access_log(ip, "issue_transition_local", 200, f"{issue_key} -> {status} by {session.get('name')}")
        try:
            from services.vector_store import trigger_async_vector_sync
            trigger_async_vector_sync(handler.cfg)
        except Exception:
            pass
        handler._send_json(200, {"ok": True, "issue_key": issue_key, "status": status, "note": "로컬 이슈 상태가 변경되었습니다."})
        return

    ok, note = transition_jira_issue(handler.cfg, issue_key, status)
    if not ok:
        handler._send_json(400, {"ok": False, "error": note})
        return

    # Log status transition activity to JARVIS activity store under current logged-in user
    try:
        from services.activity_store import append_activity
        from db import query
        iss_info = query("SELECT summary, issue_type, assignee_name, dept_id FROM jira_issues WHERE jira_key = ?", (issue_key,))
        iss_row = iss_info[0] if iss_info else {}
        append_activity({
            "id": f"jarvis_canvas_status_{issue_key}_{int(datetime.now().timestamp()*1000)}",
            "issue_key": issue_key,
            "action_type": "status_change",
            "action_detail": f"상태 변경 ➔ {status}",
            "author_name": session.get("name") or "사용자",
            "author_email": session.get("email") or "",
            "summary": iss_row.get("summary") or issue_key,
            "status": status,
            "priority": "보통",
            "issue_type": iss_row.get("issue_type") or "Jira",
            "assignee_name": iss_row.get("assignee_name") or session.get("name"),
            "assignee_dept": iss_row.get("dept_id") or session.get("org") or "연구소",
            "source": "jarvis"
        })
    except Exception as e:
        log_line("Canvas 상태 변경 activity 로깅 오류 (무시):", e)

    access_log(ip, "issue_transition", 200, f"{issue_key} -> {status} by {session.get('name')}")
    handler._send_json(200, {"ok": True, "issue_key": issue_key, "status": status, "note": note})

def handle_post_issue_attachment(handler, raw_body, ip):
    session = handler._get_session_or_401()
    if not session:
        return
    content_type = handler.headers.get("Content-Type", "")
    m = re.search(r'boundary="?([^";]+)"?', content_type)
    if not m:
        handler._send_json(400, {"ok": False, "error": "multipart/form-data 요청이 아닙니다."})
        return

    from utils.multipart import parse_multipart
    fields, files = parse_multipart(raw_body, m.group(1))
    issue_key = (fields.get("issue_key") or fields.get("key") or "").strip().upper()
    if not issue_key:
        handler._send_json(400, {"ok": False, "error": "이슈 키(issue_key)가 필요합니다."})
        return
    if not files:
        handler._send_json(400, {"ok": False, "error": "업로드할 파일이 없습니다."})
        return

    local_rec = find_record_by_key_or_code(issue_key)
    if not local_rec:
        clean_id = issue_key.strip().upper().lstrip("#").replace("REC-", "").replace("LOCAL-", "").replace("JIRA-", "")
        if clean_id.isdigit():
            local_rec = get_record_by_id(int(clean_id))

    if local_rec:
        # RBAC: viewer bị chặn; chỉ người có quyền sửa card mới được đính kèm file
        from services.auth import check_record_write_access
        from services.license_manager import is_system_read_only
        if is_system_read_only():
            handler._send_json(403, {"ok": False, "error": "라이선스가 만료되어 시스템이 읽기 전용(Read-Only) 상태입니다. 관리자에게 문의하세요."})
            return
        allowed, deny_err = check_record_write_access(session, local_rec)
        if not allowed:
            access_log(ip, "forbidden_issue_attachment", 403,
                       f"{issue_key} by {session.get('name')}")
            handler._send_json(403, {"ok": False, "error": deny_err})
            return

        from utils.file_ops import sanitize_filename, safe_join
        from utils.image_optimizer import optimize_and_save_file
        record_attach_dir = os.path.join(ATTACH_DIR, str(local_rec["id"]))
        os.makedirs(record_attach_dir, exist_ok=True)
        uploaded_files = []
        for f in files:
            fname = sanitize_filename(f.get("filename") or "file")
            fdata = f.get("data") or b""
            fpath = safe_join(record_attach_dir, fname)
            if not fpath:
                # Defense in depth: sanitize_filename already strips separators.
                continue
            fsize = optimize_and_save_file(fdata, fpath)
            add_record_attachment(local_rec["id"], fname, fsize)
            uploaded_files.append(fname)

        try:
            from services.activity_store import append_activity
            append_activity({
                "id": f"jarvis_canvas_att_{local_rec['id']}_{int(datetime.now().timestamp()*1000)}",
                "issue_key": issue_key,
                "action_type": "attachment",
                "action_detail": "\n".join(uploaded_files),
                "author_name": session.get("name") or "사용자",
                "author_email": session.get("email") or "",
                "summary": local_rec.get("title") or issue_key,
                "status": local_rec.get("status") or "진행",
                "priority": "보통",
                "issue_type": local_rec.get("category") or "업무기록",
                "assignee_name": local_rec.get("assignee") or session.get("name"),
                "assignee_dept": local_rec.get("org") or session.get("org") or "연구소",
                "source": "jarvis"
            })
        except Exception as e:
            log_line("Local 첨부파일 activity 로깅 오류 (무시):", e)

        access_log(ip, "issue_attachment_upload_local", 200, f"{issue_key} files: {len(uploaded_files)} by {session.get('name')}")
        _audit(session, ip, "RECORD_ATTACHMENT_UPLOAD", "record", issue_key,
               {"files": uploaded_files})
        handler._send_json(200, {
            "ok": True,
            "issue_key": issue_key,
            "files": uploaded_files,
            "count": len(uploaded_files)
        })
        return

    from services.auth import can_write_data
    from services.license_manager import is_system_read_only
    if is_system_read_only():
        handler._send_json(403, {"ok": False, "error": "라이선스가 만료되어 시스템이 읽기 전용(Read-Only) 상태입니다. 관리자에게 문의하세요."})
        return
    if not can_write_data(session):
        access_log(ip, "forbidden_issue_attachment_jira", 403,
                   f"{issue_key} by {session.get('name')}")
        handler._send_json(403, {"ok": False, "error": "조회 전용(Viewer) 권한의 사용자는 첨부파일을 업로드할 수 없습니다."})
        return

    uploaded_files = []
    errors = []
    for f in files:
        fname = f.get("filename") or "file"
        fdata = f.get("data") or b""
        ctype = f.get("content_type") or "application/octet-stream"
        res, err = upload_jira_attachment(handler.cfg, issue_key, fname, fdata, ctype)
        if err:
            errors.append(f"{fname}: {err}")
        else:
            uploaded_files.append(fname)

    if errors:
        access_log(ip, "issue_attachment_error", 400, f"{issue_key} err: {'; '.join(errors)}")
        handler._send_json(400, {
            "ok": False,
            "error": "; ".join(errors),
            "uploaded": uploaded_files
        })
        return

    # Log Jira attachment upload activity to JARVIS activity store under current logged-in user
    if uploaded_files:
        try:
            from services.activity_store import append_activity
            from db import query
            iss_info = query("SELECT summary, status_name, issue_type, assignee_name, dept_id FROM jira_issues WHERE jira_key = ?", (issue_key,))
            iss_row = iss_info[0] if iss_info else {}
            append_activity({
                "id": f"jarvis_canvas_att_{issue_key}_{int(datetime.now().timestamp()*1000)}",
                "issue_key": issue_key,
                "action_type": "attachment",
                "action_detail": "\n".join(uploaded_files),
                "author_name": session.get("name") or "사용자",
                "author_email": session.get("email") or "",
                "summary": iss_row.get("summary") or issue_key,
                "status": iss_row.get("status_name") or "진행",
                "priority": "보통",
                "issue_type": iss_row.get("issue_type") or "Jira",
                "assignee_name": iss_row.get("assignee_name") or session.get("name"),
                "assignee_dept": iss_row.get("dept_id") or session.get("org") or "연구소",
                "source": "jarvis"
            })
        except Exception as e:
            log_line("Jira 첨부파일 activity 로깅 오류 (무시):", e)

    access_log(ip, "issue_attachment_upload", 200, f"{issue_key} files: {len(uploaded_files)} by {session.get('name')}")
    _audit(session, ip, "ISSUE_ATTACHMENT_UPLOAD", "jira_issue", issue_key,
           {"files": uploaded_files})
    handler._send_json(200, {
        "ok": True,
        "issue_key": issue_key,
        "files": uploaded_files,
        "count": len(uploaded_files)
    })


def handle_delete_record_attachment(handler, raw_body, ip):
    """로컬 카드의 첨부파일을 삭제한다."""
    session = handler._get_session_or_401()
    if not session:
        return
    try:
        body = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except Exception:
        body = {}
    key = (body.get("key") or body.get("issue_key") or body.get("card_code") or "").strip()
    attach_id = body.get("attachment_id") or body.get("id")
    if not key or not attach_id:
        handler._send_json(400, {"ok": False, "error": "업무 키와 첨부파일 ID가 필요합니다."})
        return
    rec = find_record_by_key_or_code(key)
    if not rec:
        handler._send_json(404, {"ok": False, "error": f"기록 '{key}'을 찾을 수 없습니다."})
        return
    from services.auth import can_delete_record
    if not can_delete_record(session, rec):
        handler._send_json(403, {"ok": False, "error": "작업 카드 삭제 권한이 없습니다. 관리자(Admin) 또는 소속 부서 관리자(Manager)만 삭제할 수 있습니다."})
        return
    from services.data_store import delete_record_attachment
    ok, err = delete_record_attachment(rec["id"], int(attach_id))
    if not ok:
        handler._send_json(400, {"ok": False, "error": err or "첨부파일 삭제 실패"})
        return
    handler._send_json(200, {"ok": True, "message": "첨부파일이 삭제되었습니다."})


def handle_post_record_update(handler, raw_body, ip):
    """업무 카드 정보를 포괄적으로 수정한다 (담당자, 참여자, 제목, 내용, 마감일 등)."""
    session = handler._get_session_or_401()
    if not session:
        return

    from services.license_manager import is_system_read_only
    if is_system_read_only():
        handler._send_json(403, {"ok": False, "error": "라이선스가 만료되어 시스템이 읽기 전용(Read-Only) 상태입니다. 관리자에게 문의하세요."})
        return

    try:
        body = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except Exception:
        body = {}

    key = body.get("key") or body.get("id") or body.get("cardCode") or ""
    if not key:
        handler._send_json(400, {"ok": False, "error": "수정할 업무 키(key)가 필요합니다."})
        return

    old_rec = find_record_by_key_or_code(key)
    if not old_rec:
        handler._send_json(404, {"ok": False, "error": f"기록 '{key}'을 찾을 수 없습니다."})
        return

    from services.auth import can_modify_record
    if not can_modify_record(session, old_rec):
        handler._send_json(403, {"ok": False, "error": "해당 업무 카드를 수정할 권한이 없습니다. (담당자, 부서 관리자 또는 시스템 관리자만 가능)"})
        return

    title = body.get("title")
    memo = body.get("memo") or body.get("description")
    assignee = body.get("assignee") if "assignee" in body else body.get("assignee_name")
    assignee_email = body.get("assigneeEmail") or body.get("assignee_email") or ""
    participants = body.get("participants")
    start_date = body.get("startDate") or body.get("start_date")
    due_date = body.get("dueDate") or body.get("due_date")
    priority = body.get("priority")
    expected_version = body.get("expected_version") if "expected_version" in body else body.get("version")

    updated_rec, err = update_record_details(
        record_id_or_code=key,
        title=title,
        memo=memo,
        assignee_name=assignee,
        assignee_email=assignee_email,
        participants=participants,
        due_date=due_date,
        start_date=start_date,
        expected_version=expected_version,
        parent_key=(body.get("parentKey") if "parentKey" in body else _UNSET),
        priority=priority
    )

    if err or not updated_rec:
        if err and "CONFLICT:" in err:
            cur_rec = find_record_by_key_or_code(key)
            handler._send_json(409, {
                "ok": False,
                "conflict": True,
                "error": err.replace("CONFLICT:", "").strip(),
                "current_version": cur_rec.get("version", 1) if cur_rec else None
            })
            return
        handler._send_json(400, {"ok": False, "error": err or "수정에 실패했습니다."})
        return

    session_name = session.get("name") if session else "사용자"
    session_email = session.get("email") if session else ""

    # 1. Activity log
    try:
        from services.activity_store import append_activity
        append_activity({
            "id": f"jarvis_update_{key}_{int(datetime.now().timestamp()*1000)}",
            "issue_key": str(key),
            "action_type": "updated",
            "action_detail": f"업무 수정 (담당자: {assignee or '-'})",
            "author_name": session_name,
            "author_email": session_email,
            "summary": updated_rec.get("title") or str(key),
            "status": updated_rec.get("status") or "진행",
            "assignee_name": updated_rec.get("assignee_name") or "",
            "assignee_dept": updated_rec.get("dept_id") or "연구소",
            "source": "jarvis"
        })
    except Exception:
        pass

    # 2. Trigger notification to new assignee if changed
    try:
        from services.notification_service import trigger_task_assigned_notification
        old_assignee = old_rec.get("assignee_name") or ""
        new_assignee = updated_rec.get("assignee_name") or ""
        if new_assignee and new_assignee != old_assignee:
            trigger_task_assigned_notification(
                record_id=key,
                title=updated_rec.get("title") or "업무",
                author_name=session_name,
                assignee_name=new_assignee,
                assignee_email=updated_rec.get("assignee_email") or "",
                participants=updated_rec.get("participants") or ""
            )
    except Exception:
        pass

    # 3. Async vector sync
    try:
        from services.vector_store import trigger_async_vector_sync
        trigger_async_vector_sync(handler.cfg)
    except Exception:
        pass

    access_log(ip, "record_update", 200, f"key={key} by {session_name}")
    try:
        from services.audit_logger import log_audit
        log_audit(
            session=session,
            ip=ip,
            action="RECORD_UPDATE",
            target_type="record",
            target_id=str(key),
            details={"title": updated_rec.get("title"), "assignee": assignee, "due_date": due_date}
        )
    except Exception:
        pass
    handler._send_json(200, {"ok": True, "record": updated_rec})


def handle_delete_record(handler, raw_body, ip):
    """로컬 이슈(기록)를 삭제한다 (DB, 첨부파일 폴더, 벡터 임베딩 정리)."""
    session = handler._get_session_or_401()
    if not session:
        return

    from services.license_manager import is_system_read_only
    if is_system_read_only():
        handler._send_json(403, {"ok": False, "error": "라이선스가 만료되어 시스템이 읽기 전용(Read-Only) 상태입니다. 관리자에게 문의하세요."})
        return

    try:
        body = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except Exception:
        body = {}
    record_id_raw = body.get("id") or body.get("record_id") or body.get("key") or ""
    rec = find_record_by_key_or_code(record_id_raw)
    if not rec:
        handler._send_json(404, {"ok": False, "error": f"레코드 '{record_id_raw}'를 찾을 수 없습니다."})
        return

    from services.auth import can_delete_record
    if not can_delete_record(session, rec):
        handler._send_json(403, {"ok": False, "error": "작업 카드 삭제 권한이 없습니다. 관리자(Admin) 또는 소속 부서 관리자(Manager)만 삭제할 수 있습니다."})
        return

    rec_id = rec["id"]

    # 1. DB에서 레코드 및 관련 댓글, 첨부파일, Jira 매핑 삭제
    delete_record(rec_id)
    try:
        from services.audit_logger import log_audit
        log_audit(
            session=session,
            ip=ip,
            action="RECORD_DELETE",
            target_type="record",
            target_id=str(rec_id),
            details={"title": rec.get("title"), "card_code": rec.get("card_code")}
        )
    except Exception:
        pass

    # 2. 로컬 디스크 첨부파일 디렉토리 정리
    import shutil
    rec_attach_dir = os.path.join(ATTACH_DIR, str(rec_id))
    if os.path.exists(rec_attach_dir):
        try:
            shutil.rmtree(rec_attach_dir)
        except Exception as e:
            log_line("로컬 첨부파일 삭제 중 경고:", e)

    # 3. 벡터 DB에서 해당 임베딩 제거
    try:
        delete_vector_document(f"record:{rec_id}")
    except Exception as e:
        log_line("벡터 문서 삭제 중 경고:", e)

    # 4. 활동 로그 기록
    try:
        from services.activity_store import append_activity
        append_activity({
            "issue_key": f"REC-{rec_id % 10000}",
            "action_type": "deleted",
            "action_detail": f"로컬 기록 삭제: {rec.get('title', '')[:80]}",
            "author_name": session.get("name") or "사용자",
            "author_email": session.get("email") or "",
            "summary": rec.get("title") or f"REC-{rec_id}",
            "status": "삭제됨",
            "source": "jarvis"
        })
    except Exception:
        pass

    access_log(ip, "record_delete", 200, f"id={rec_id} by {session.get('name')}")
    handler._send_json(200, {"ok": True, "message": f"레코드 #{rec_id}가 삭제되었습니다.", "id": rec_id})


def _push_single_local_record_to_jira(cfg, session, rec, parent_jira_key=None, custom_breadcrumb=None):
    """단일 로컬 레코드를 Jira 이슈로 발행하고 연동한다."""
    rec_id = rec["id"]
    dept_id = rec.get("org") or ""
    j_cfg = cfg.get("jira", {})
    project_key, default_issue_type = jira_project_for_dept(cfg, dept_id)
    if not project_key:
        project_key = j_cfg.get("default_project_key") or ""
        default_issue_type = j_cfg.get("default_issue_type") or "Task"
    if not project_key:
        return None, "Jira 프로젝트 키가 설정되지 않았습니다. 관리자 설정에서 프로젝트 매핑을 확인해주세요."

    cat = rec.get("category") or ""
    real_categories = get_cached_categories(cfg, dept_id)
    if not real_categories:
        real_categories = jira_fetch_project_categories(cfg, project_key)

    # 상위 Jira 이슈가 있으면 Sub-task 이슈 타입 우선 적용
    if parent_jira_key:
        sub_type = jira_fetch_project_subtask_type(cfg, project_key)
        issue_type = sub_type or "하위 작업"
    elif cat and cat in real_categories:
        issue_type = cat
    elif default_issue_type and default_issue_type in real_categories:
        issue_type = default_issue_type
    elif real_categories:
        # Jira 프로젝트에 실제 존재하는 일반 이슈 타입 우선 매칭 ('작업' > 'Task' > 기타 비에픽 타입)
        preferred = ["작업", "Task", "기능", "개선", "이슈"]
        matched = None
        for p in preferred:
            if p in real_categories:
                matched = p
                break
        if not matched:
            non_epics = [c for c in real_categories if "에픽" not in c and "epic" not in c.lower()]
            matched = non_epics[0] if non_epics else real_categories[0]
        issue_type = matched
    else:
        issue_type = default_issue_type or "작업"

    title = rec.get("title") or "제목 없는 로컬 기록"
    summary_text = rec.get("summary") or ""
    memo_text = rec.get("memo") or ""
    description = memo_text or summary_text or "(내용 없음)"
    if summary_text and memo_text and summary_text != memo_text:
        description = f"요약: {summary_text}\n\n상세 메모: {memo_text}"

    attach_files = rec.get("attachments") or []
    if attach_files:
        description += "\n\n첨부파일: " + ", ".join(attach_files)
    description += f"\n\n[ARGOS WORKS 로컬 발행] 제출자: {rec.get('assignee', '')} ({dept_id})"

    if custom_breadcrumb:
        description += f"\n\n{custom_breadcrumb}"

    labels = ["ARGOS_WORKS_발행"]
    if dept_id:
        labels.append("부서_" + sanitize_label(dept_id))
    if cat:
        labels.append("분류_" + sanitize_label(cat))

    due_date = rec.get("date") or None

    assignee_name = rec.get("assignee") or (session.get("name") if session else "") or ""
    assignee_email = rec.get("assigneeEmail") or (session.get("email") if session else "") or ""
    account_id = lookup_jira_account_id(cfg, assignee_email) or lookup_jira_account_id(cfg, assignee_name)

    # Jira 이슈 생성 API 호출 (상위 이슈 키 전달)
    jira_res, note = create_jira_issue(
        cfg, project_key, issue_type, title, description, labels,
        due_date=due_date, submitter_account_id=account_id, assignee_account_id=account_id,
        parent_key=parent_jira_key
    )

    # 만약 상위 이슈 키를 전달했으나 Jira 정책상 거절된 경우(예: 상위 이슈가 이미 Sub-task이거나 parent 필드 제한),
    # 독립 표준 작업(Standard Task)으로 자동 fallback 생성
    if (not jira_res or not jira_res.get("key")) and parent_jira_key:
        log_line(f"Sub-task 발행 실패, 표준 작업으로 자동 fallback 재시도 (ID={rec_id}, parent={parent_jira_key}):", note)
        fallback_issue_type = (cat if (cat and cat in real_categories) else (default_issue_type or "작업"))
        desc_fallback = description + f"\n\n[주의] 상위 Jira 이슈 ({parent_jira_key})와 연결을 시도했으나 Jira 정책에 의해 독립 작업으로 발행되었습니다."
        jira_res, note = create_jira_issue(
            cfg, project_key, fallback_issue_type, title, desc_fallback, labels,
            due_date=due_date, submitter_account_id=account_id, assignee_account_id=account_id,
            parent_key=None
        )

    if not jira_res or not jira_res.get("key"):
        err_msg = note or "Jira 이슈 생성에 실패했습니다."
        return None, err_msg

    new_jira_key = jira_res["key"]
    new_jira_url = jira_res.get("url") or (j_cfg.get("base_url", "").rstrip("/") + "/browse/" + new_jira_key)
    new_jira_status = "진행"

    # 로컬 DB에 Jira 매핑 정보 저장
    link_record_jira(rec_id, new_jira_key, new_jira_status, new_jira_url)

    # 상위 Jira 이슈가 있는 경우 Jira Issue Link(Relates to)를 생성하여 지라 웹에서도 계층 관계 시각화
    if parent_jira_key:
        try:
            create_jira_issue_link(cfg, new_jira_key, parent_jira_key, "Relates")
        except Exception as le:
            log_line("Jira 이슈 링크 생성 중 경고:", le)

    # 로컬 첨부파일이 있으면 Jira 이슈에도 자동 업로드 시도
    rec_attach_dir = os.path.join(ATTACH_DIR, str(rec_id))
    if os.path.exists(rec_attach_dir) and attach_files:
        for fname in attach_files:
            fpath = os.path.join(rec_attach_dir, fname)
            if os.path.exists(fpath):
                try:
                    with open(fpath, "rb") as f:
                        upload_jira_attachment(cfg, new_jira_key, fname, f.read(), "application/octet-stream")
                except Exception as e:
                    log_line(f"Jira 첨부파일 연동 중 경고 ({fname}):", e)

    # 로컬 댓글 자동 동기화
    local_comments = rec.get("comments") or []
    if local_comments:
        for c in local_comments:
            c_body = c.get("body") or ""
            c_author = c.get("author") or (session.get("name") if session else "작성자") or "작성자"
            c_time = c.get("created") or ""
            if c_body:
                jira_comment_text = f"[ARGOS WORKS 로컬 댓글 이관 - {c_author} ({c_time})]\n{c_body}"
                try:
                    add_jira_comment(cfg, new_jira_key, jira_comment_text, author_name=c_author)
                except Exception as ce:
                    log_line(f"Jira 댓글 연동 중 경고 (ID={c.get('id')}):", ce)

    # 활동 로그 기록
    try:
        from services.activity_store import append_activity
        append_activity({
            "issue_key": new_jira_key,
            "action_type": "created",
            "action_detail": f"로컬 레코드 #{rec_id} Jira 발행 ({new_jira_key})",
            "author_name": (session.get("name") if session else "") or assignee_name,
            "author_email": (session.get("email") if session else "") or assignee_email,
            "summary": title,
            "status": "진행",
            "issue_type": issue_type,
            "assignee_name": assignee_name,
            "assignee_dept": dept_id,
            "source": "jarvis"
        })
    except Exception:
        pass

    return {
        "key": new_jira_key,
        "url": new_jira_url,
        "note": note,
        "issue_type": issue_type
    }, None


def handle_get_record_hierarchy(handler, parsed, ip):
    """GET /api/records/hierarchy?id=... - 레코드의 전체 계층 경로 및 상위 Jira 연동 상태 조회"""
    session = handler._get_session_or_401()
    if not session:
        return
    qs = parse_qs(parsed.query)
    record_id_raw = (qs.get("id", [""])[0] or qs.get("key", [""])[0] or "").strip()
    rec = find_record_by_key_or_code(record_id_raw)
    if not rec:
        handler._send_json(404, {"ok": False, "error": f"레코드 '{record_id_raw}'를 찾을 수 없습니다."})
        return

    # RBAC: 상세/계층 정보도 열람 권한이 있는 카드만 반환 (목록에서 숨긴 카드의 IDOR 차단)
    from services.auth import can_view_record
    if not can_view_record(session, rec):
        try:
            from services.audit_logger import log_audit
            log_audit(session=session, ip=ip, action="RBAC_DENIED_READ",
                      target_type="record", target_id=record_id_raw,
                      details={"endpoint": "/api/records/hierarchy"})
        except Exception:
            pass
        handler._send_json(404, {"ok": False, "error": f"레코드 '{record_id_raw}'를 찾을 수 없습니다."})
        return

    jira_enabled = bool(handler.cfg.get("jira", {}).get("enabled", False))
    chain = get_record_hierarchy_chain(rec)

    # 상위 경로(chain) 중 열람 권한이 없는 단계에서 잘라낸다 (타 부서 카드 제목 노출 방지).
    # chain 은 [root, ..., current] 순서이므로 current 에서 위로 올라가며 권한을 확인한다.
    visible_chain = [rec]
    truncated = False
    for node in reversed(chain[:-1]):
        if not can_view_record(session, node):
            truncated = True
            break
        visible_chain.insert(0, node)
    chain = visible_chain

    unpushed_parents = []
    closest_jira_parent = None
    if jira_enabled:
        for ancestor in chain[:-1]:
            j_key = (ancestor.get("jira") or {}).get("key") if ancestor.get("jira") else None
            if j_key:
                closest_jira_parent = j_key
            else:
                unpushed_parents.append({
                    "id": ancestor.get("id"),
                    "cardCode": ancestor.get("cardCode") or f"#{ancestor.get('id')}",
                    "title": ancestor.get("title") or "제목 없음"
                })

    handler._send_json(200, {
        "ok": True,
        "record": {
            "id": rec.get("id"),
            "cardCode": rec.get("cardCode"),
            "title": rec.get("title"),
            "parentKey": rec.get("parentKey")
        },
        "chain": [
            {
                "id": n.get("id"),
                "cardCode": n.get("cardCode") or ((n.get("jira") or {}).get("key") if jira_enabled else "") or f"#{n.get('id')}",
                "title": n.get("title") or "",
                "hasJira": bool(jira_enabled and n.get("jira") and n["jira"].get("key")),
                "jiraKey": (n.get("jira") or {}).get("key") if (jira_enabled and n.get("jira")) else None,
                "isCurrent": (n.get("id") == rec.get("id"))
            } for n in chain
        ],
        "depth": len(chain),
        "truncated": truncated,
        "hasUnpushedParents": (len(unpushed_parents) > 0) if jira_enabled else False,
        "unpushedParents": unpushed_parents if jira_enabled else [],
        "closestJiraParent": closest_jira_parent if jira_enabled else None
    })


def handle_push_record_jira(handler, raw_body, ip):
    """Jira에 없는 로컬 이슈를 Jira Cloud 실제 이슈로 발행하고 연동한다."""
    session = handler._get_session_or_401()
    if not session:
        return
    try:
        body = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except Exception:
        body = {}
    record_id_raw = body.get("id") or body.get("record_id") or body.get("key") or ""
    rec = find_record_by_key_or_code(record_id_raw)
    if not rec:
        handler._send_json(404, {"ok": False, "error": f"레코드 '{record_id_raw}'를 찾을 수 없습니다."})
        return
    rec_id = rec["id"]

    # RBAC: viewer bị chặn; chỉ người có quyền sửa card mới được đẩy lên Jira
    from services.auth import check_record_write_access
    from services.license_manager import is_system_read_only
    if is_system_read_only():
        handler._send_json(403, {"ok": False, "error": "라이선스가 만료되어 시스템이 읽기 전용(Read-Only) 상태입니다. 관리자에게 문의하세요."})
        return
    allowed, deny_err = check_record_write_access(session, rec)
    if not allowed:
        access_log(ip, "forbidden_push_record_jira", 403, f"{rec_id} by {session.get('name')}")
        handler._send_json(403, {"ok": False, "error": deny_err})
        return

    if rec.get("jira") and rec["jira"].get("key"):
        handler._send_json(400, {"ok": False, "error": f"이미 Jira({rec['jira']['key']})에 연동된 레코드입니다.", "jira": rec["jira"]})
        return

    from services.jira_client import check_jira_connection_status
    jira_ready, jira_err = check_jira_connection_status(handler.cfg)
    if not jira_ready:
        handler._send_json(400, {"ok": False, "error": f"Jira 연동을 사용할 수 없습니다: {jira_err}"})
        return

    push_parent_first = bool(body.get("push_parent_first"))
    chain = get_record_hierarchy_chain(rec)

    # 1. 사용자가 상위 작업 함께 발행을 선택한 경우: 최상위부터 순차 발행
    pushed_parents_keys = []
    if push_parent_first and len(chain) > 1:
        for ancestor in chain[:-1]:
            a_id = ancestor.get("id")
            if a_id and not (ancestor.get("jira") and ancestor["jira"].get("key")):
                a_chain = get_record_hierarchy_chain(ancestor)
                a_parent_jira = None
                for a_anc in reversed(a_chain[:-1]):
                    if a_anc.get("jira") and a_anc["jira"].get("key"):
                        a_parent_jira = a_anc["jira"]["key"]
                        break
                p_res, p_err = _push_single_local_record_to_jira(
                    handler.cfg, session, ancestor, parent_jira_key=a_parent_jira
                )
                if p_res and p_res.get("key"):
                    ancestor["jira"] = {"key": p_res["key"]}
                    pushed_parents_keys.append(p_res["key"])

    # 상위 발행 후 최신 계층 경로 다시 로드
    chain = get_record_hierarchy_chain(rec)

    # 2. 계층 경로 Breadcrumb 텍스트 구성 (Description에 삽입)
    breadcrumb_text = ""
    if len(chain) > 1:
        steps = []
        for idx, node in enumerate(chain):
            code = node.get("cardCode") or ((node.get("jira") or {}).get("key")) or f"#{node.get('id')}"
            t = node.get("title") or ((node.get("jira") or {}).get("summary")) or ""
            is_cur = " 📍 [현재 발행 작업]" if node.get("id") == rec.get("id") else ""
            indent = "  " * idx
            prefix = "└── " if idx > 0 else "■ "
            steps.append(f"{indent}{prefix}[{code}] {t}{is_cur}")
        breadcrumb_text = "[업무 계층 경로 (ARGOS WORK Hierarchy)]\n" + "\n".join(steps)

    # 3. 최인접 상위 Jira 키 찾기
    closest_jira_parent = None
    for ancestor in reversed(chain[:-1]):
        if ancestor.get("jira") and ancestor["jira"].get("key"):
            closest_jira_parent = ancestor["jira"]["key"]
            break

    # 4. 현재 레코드 Jira 발행
    res_obj, err_msg = _push_single_local_record_to_jira(
        handler.cfg, session, rec,
        parent_jira_key=closest_jira_parent,
        custom_breadcrumb=breadcrumb_text
    )
    if not res_obj or err_msg:
        handler._send_json(500, {"ok": False, "error": err_msg or "Jira 이슈 생성에 실패했습니다."})
        return

    new_jira_key = res_obj["key"]
    new_jira_url = res_obj["url"]
    note = res_obj.get("note")

    threading.Thread(target=sync_jira_cache, args=(handler.cfg, False), daemon=True).start()

    access_log(ip, "record_push_jira", 200, f"id={rec_id} -> {new_jira_key} by {session.get('name')}")
    _audit(session, ip, "RECORD_PUSH_JIRA", "record", rec_id,
           {"jira_key": new_jira_key})
    handler._send_json(200, {
        "ok": True,
        "message": f"Jira 이슈 '{new_jira_key}'로 성공적으로 발행되었습니다.",
        "record_id": rec_id,
        "jira_key": new_jira_key,
        "jira_url": new_jira_url,
        "parent_jira_key": closest_jira_parent,
        "pushed_parents": pushed_parents_keys,
        "hierarchy_depth": len(chain),
        "note": note
    })


# --- Admin Backup & Disaster Recovery Handlers ---
def handle_get_admin_backups(handler, parsed, ip):
    session = handler._get_session_or_401()
    if not session:
        return
    if not is_admin_user(session):
        handler._send_json(403, {"ok": False, "error": "관리자(Admin) 권한이 필요합니다."})
        return
    try:
        from services.backup_manager import list_backups, get_backup_dir
        from config import DATA_DIR
        from db import get_db_path
        backups = list_backups()
        db_path = get_db_path()
        db_size = os.path.getsize(db_path) if os.path.exists(db_path) else 0
        current_bdir = get_backup_dir()
        default_bdir = os.path.normpath(os.path.join(DATA_DIR, "backups"))
        security_info = {
            "https_active": handler._is_secure(),
            "http_only_cookie": True,
            "optimistic_locking": True,
            "db_path": db_path,
            "db_size": db_size,
            "backup_count": len(backups),
            "backup_dir": current_bdir,
            "default_backup_dir": default_bdir,
            "is_custom_backup_dir": (current_bdir != default_bdir)
        }
        handler._send_json(200, {"ok": True, "backups": backups, "security": security_info})
    except Exception as e:
        handler._send_json(500, {"ok": False, "error": str(e)})


def handle_post_admin_backup_config(handler, raw_body, ip):
    session = handler._get_session_or_401()
    if not session:
        return
    if not is_admin_user(session):
        handler._send_json(403, {"ok": False, "error": "관리자(Admin) 권한이 필요합니다."})
        return
    try:
        body = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except Exception:
        body = {}
    new_dir = (body.get("backup_dir") or "").strip()
    try:
        from services.backup_manager import update_backup_config
        res = update_backup_config(new_dir)
        access_log(ip, "backup_config_update", 200, f"backup_dir={res['backup_dir']} by {session.get('name')}")
        handler._send_json(200, res)
    except Exception as e:
        log_line(f"백업 경로 변경 실패: {e}")
        handler._send_json(400, {"ok": False, "error": str(e)})


def handle_post_admin_backup_upload(handler, raw_body, ip):
    session = handler._get_session_or_401()
    if not session:
        return
    if not is_admin_user(session):
        handler._send_json(403, {"ok": False, "error": "관리자(Admin) 권한이 필요합니다."})
        return
    content_type = handler.headers.get("Content-Type", "")
    m = re.search(r'boundary="?([^";]+)"?', content_type)
    if not m:
        handler._send_json(400, {"ok": False, "error": "multipart/form-data 요청이 아닙니다."})
        return
    try:
        from utils.multipart import parse_multipart
        from services.backup_manager import import_backup_file
        fields, files = parse_multipart(raw_body, m.group(1))
        if not files:
            handler._send_json(400, {"ok": False, "error": "업로드할 백업 파일이 없습니다."})
            return
        uploaded = files[0]
        note = (fields.get("note") or f"{session.get('name', '관리자')} 업로드 백업").strip()
        res = import_backup_file(uploaded["data"], uploaded["filename"], note=note)
        access_log(ip, "backup_upload", 200, f"uploaded={res['filename']} by {session.get('name')}")
        handler._send_json(200, res)
    except Exception as e:
        log_line(f"백업 파일 업로드 실패: {e}")
        handler._send_json(400, {"ok": False, "error": str(e)})


def handle_post_admin_backup_create(handler, raw_body, ip):
    session = handler._get_session_or_401()
    if not session:
        return
    if not is_admin_user(session):
        handler._send_json(403, {"ok": False, "error": "관리자(Admin) 권한이 필요합니다."})
        return
    try:
        body = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except Exception:
        body = {}
    note = (body.get("note") or f"{session.get('name', '관리자')} 수동 백업").strip()
    try:
        from services.backup_manager import create_backup
        res = create_backup(note=note, backup_type="manual")
        access_log(ip, "backup_create", 200, f"created={res['filename']} by {session.get('name')}")
        handler._send_json(200, res)
    except Exception as e:
        log_line(f"백업 생성 실패: {e}")
        handler._send_json(500, {"ok": False, "error": str(e)})


def handle_post_admin_backup_restore(handler, raw_body, ip):
    session = handler._get_session_or_401()
    if not session:
        return
    if not is_admin_user(session):
        handler._send_json(403, {"ok": False, "error": "관리자(Admin) 권한이 필요합니다."})
        return
    try:
        body = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except Exception:
        body = {}
    filename = (body.get("filename") or "").strip()
    if not filename:
        handler._send_json(400, {"ok": False, "error": "복원할 백업 파일명이 필요합니다."})
        return
    try:
        from services.backup_manager import restore_backup
        res = restore_backup(filename)
        access_log(ip, "backup_restore", 200, f"restored={filename} by {session.get('name')}")
        handler._send_json(200, res)
    except Exception as e:
        log_line(f"백업 복원 실패: {e}")
        handler._send_json(500, {"ok": False, "error": str(e)})


def handle_get_admin_backup_download(handler, parsed, ip):
    session = handler._get_session_or_401()
    if not session:
        return
    if not is_admin_user(session):
        handler._send_json(403, {"ok": False, "error": "관리자(Admin) 권한이 필요합니다."})
        return
    qs = parse_qs(parsed.query)
    filename = (qs.get("filename", [""])[0] or "").strip()
    if not filename:
        handler._send_json(400, {"ok": False, "error": "다운로드할 파일명이 필요합니다."})
        return
    from services.backup_manager import get_backup_file_path
    fpath = get_backup_file_path(filename)
    if not fpath:
        handler._send_json(404, {"ok": False, "error": "해당 백업 파일을 찾을 수 없습니다."})
        return
    handler._send_attachment(fpath, filename)


def handle_get_admin_audit_logs(handler, parsed, ip):
    session = handler._get_session_or_401()
    if not session:
        return
    if not is_admin_user(session):
        handler._send_json(403, {"ok": False, "error": "관리자(Admin) 권한이 필요합니다."})
        return
    qs = parse_qs(parsed.query)
    action = (qs.get("action", [""])[0]).strip()
    user_name = (qs.get("user", [""])[0]).strip()
    target_type = (qs.get("target_type", [""])[0]).strip()
    from_date = (qs.get("from", [""])[0]).strip()
    to_date = (qs.get("to", [""])[0]).strip()
    try:
        limit = max(1, min(1000, int(qs.get("limit", ["100"])[0])))
    except Exception:
        limit = 100
    from services.audit_logger import get_audit_logs
    logs = get_audit_logs(
        action=action or None,
        username=user_name or None,
        target_type=target_type or None,
        from_date=from_date or None,
        to_date=to_date or None,
        limit=limit
    )
    handler._send_json(200, {"ok": True, "logs": logs, "total": len(logs)})


def handle_get_admin_audit_logs_export(handler, parsed, ip):
    """GET /api/admin/audit-logs/export — CSV/JSON download for ISO/audit reviews."""
    session = handler._get_session_or_401()
    if not session:
        return
    if not is_admin_user(session):
        handler._send_json(403, {"ok": False, "error": "관리자(Admin) 권한이 필요합니다."})
        return

    qs = parse_qs(parsed.query)
    action = (qs.get("action", [""])[0]).strip()
    user_name = (qs.get("user", [""])[0]).strip()
    target_type = (qs.get("target_type", [""])[0]).strip()
    from_date = (qs.get("from", [""])[0]).strip()
    to_date = (qs.get("to", [""])[0]).strip()
    export_format = (qs.get("format", ["csv"])[0]).strip().lower()
    try:
        limit = max(1, min(10000, int(qs.get("limit", ["5000"])[0])))
    except Exception:
        limit = 5000

    from services.audit_logger import get_audit_logs, build_audit_export, log_audit
    logs = get_audit_logs(
        action=action or None,
        username=user_name or None,
        target_type=target_type or None,
        from_date=from_date or None,
        to_date=to_date or None,
        limit=limit
    )

    body, content_type, ext = build_audit_export(logs, export_format)
    filename = f"argos_audit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{ext}"

    # Exporting the audit trail is itself an auditable action.
    try:
        log_audit(session, ip, "AUDIT_EXPORT", "audit", filename,
                  details={"format": ext, "rows": len(logs), "from": from_date, "to": to_date})
    except Exception:
        pass

    handler.send_response(200)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{urllib.parse.quote(filename)}")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.end_headers()
    handler.wfile.write(body)


def handle_get_version(handler, parsed, ip):
    """GET /api/version — minimal release identifier (no config/secrets)."""
    from config import APP_VERSION
    handler._send_json(200, {"ok": True, "product": "ARGOS WORKS", "version": APP_VERSION})



def handle_get_admin_ai_usage(handler, parsed, ip):
    """GET /api/admin/ai-usage — AI Token & Cost analytics (Admin only)"""
    session = handler._get_session_or_401()
    if not session:
        return
    if not is_admin_user(session):
        handler._send_json(403, {"ok": False, "error": "관리자(Admin) 권한이 필요합니다."})
        return
    qs = parse_qs(parsed.query)
    period = (qs.get("period", ["month"])[0]).strip()
    from_date = (qs.get("from", [""])[0]).strip()
    to_date = (qs.get("to", [""])[0]).strip()

    from services.ai_usage_service import get_ai_usage_stats
    stats = get_ai_usage_stats(period=period, from_date=from_date or None, to_date=to_date or None)
    handler._send_json(200, stats)


def handle_get_admin_license(handler, parsed, ip):
    session = handler._get_session_or_401()
    if not session:
        return
    if not is_admin_user(session):
        handler._send_json(403, {"ok": False, "error": "관리자(Admin) 권한이 필요합니다."})
        return
    from services.license_manager import get_license_status
    status = get_license_status()
    handler._send_json(200, {"ok": True, "license": status})


def handle_post_admin_license_activate(handler, raw_body, ip):
    session = handler._get_session_or_401()
    if not session:
        return
    if not is_admin_user(session):
        handler._send_json(403, {"ok": False, "error": "관리자(Admin) 권한이 필요합니다."})
        return
    try:
        body = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except Exception:
        body = {}
    key = (body.get("license_key") or body.get("key") or "").strip()
    from services.license_manager import activate_license, get_license_status
    ok, msg = activate_license(key)
    if not ok:
        handler._send_json(400, {"ok": False, "error": msg})
        return
    lic = get_license_status(use_cache=False)
    try:
        from services.audit_logger import log_audit
        log_audit(session, ip, "LICENSE_ACTIVATE", "license", lic.get("customer_name"),
                  details={"seats": lic.get("max_seats"), "expiry": lic.get("expiry_date"),
                           "modules": lic.get("modules")})
    except Exception:
        pass
    handler._send_json(200, {"ok": True, "message": msg, "license": lic})


def handle_get_admin_users(handler, parsed, ip):
    session = handler._get_session_or_401()
    if not session:
        return
    if not is_admin_user(session):
        handler._send_json(403, {"ok": False, "error": "관리자(Admin) 권한이 필요합니다."})
        return
    from db import query
    rows = query("""
        SELECT u.id, u.username, u.name, u.dept_id, COALESCE(d.name, u.dept_id) AS dept_name,
               u.email, u.role, u.is_admin, u.disabled, COALESCE(u.status, 'active') AS status, u.created_at
        FROM users u
        LEFT JOIN departments d ON u.dept_id = d.id
        ORDER BY u.id ASC
    """)
    from services.license_manager import get_license_info
    lic = get_license_info()
    max_seats = lic.get("max_seats", 25)

    stats = {
        "total": len(rows),
        "admins": sum(1 for r in rows if r.get("role") == "admin" or r.get("is_admin")),
        "managers": sum(1 for r in rows if r.get("role") == "manager"),
        "members": sum(1 for r in rows if r.get("role") == "member" and not r.get("is_admin")),
        "viewers": sum(1 for r in rows if r.get("role") == "viewer"),
        "disabled": sum(1 for r in rows if r.get("disabled") == 1),
        "pending": sum(1 for r in rows if r.get("status") == "pending"),
        "active": sum(1 for r in rows if r.get("status") == "active" and r.get("disabled") == 0),
        "rejected": sum(1 for r in rows if r.get("status") == "rejected"),
        "max_seats": max_seats
    }

    handler._send_json(200, {
        "ok": True,
        "users": rows,
        "total": len(rows),
        "max_seats": max_seats,
        "stats": stats
    })


def handle_post_admin_user_create(handler, raw_body, ip):
    session = handler._get_session_or_401()
    if not session:
        return
    if not is_admin_user(session):
        handler._send_json(403, {"ok": False, "error": "관리자(Admin) 권한이 필요합니다."})
        return

    from services.license_manager import check_seat_available
    avail, seat_err = check_seat_available()
    if not avail:
        handler._send_json(403, {"ok": False, "error": seat_err or "라이선스 허용 사용자 수(Seat) 제한에 도달했습니다."})
        return

    try:
        body = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except Exception:
        body = {}

    username = (body.get("username") or "").strip()
    name = (body.get("name") or "").strip()
    dept_id = (body.get("dept_id") or "").strip()
    email = (body.get("email") or "").strip()
    role = (body.get("role") or "member").strip()
    password = body.get("password") or ""

    if not username or not name or not dept_id or not password:
        handler._send_json(400, {"ok": False, "error": "아이디, 성명, 소속 부서, 비밀번호는 필수 입력 항목입니다."})
        return
    if len(password) < 8:
        handler._send_json(400, {"ok": False, "error": "비밀번호는 최소 8자 이상이어야 합니다."})
        return
    if role not in ("admin", "manager", "member", "viewer"):
        role = "member"

    from db import get_one, execute
    if get_one("SELECT id FROM users WHERE LOWER(username) = LOWER(?) LIMIT 1", (username,)):
        handler._send_json(409, {"ok": False, "error": "이미 사용 중인 아이디(ID)입니다."})
        return
    if get_one("SELECT id FROM users WHERE name = ? AND dept_id = ? LIMIT 1", (name, dept_id)):
        handler._send_json(409, {"ok": False, "error": "해당 부서에 이미 동일한 이름의 사용자가 존재합니다."})
        return

    from services.auth import hash_password, _effective_pbkdf2_rounds
    salt, pwd_hash = hash_password(password)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    is_adm = 1 if role == "admin" else 0

    execute("""
        INSERT INTO users (username, name, dept_id, email, salt, password_hash, iterations, role, is_admin, disabled, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
    """, (username, name, dept_id, email, salt, pwd_hash, _effective_pbkdf2_rounds(), role, is_adm, now_str))

    from services.audit_logger import log_audit
    log_audit(session, ip, "USER_ADMIN_CREATE", "user", username, details={"name": name, "dept": dept_id, "role": role})

    handler._send_json(200, {"ok": True, "message": f"사용자 '{name}'({username}) 계정이 성공적으로 등록되었습니다."})


def handle_post_admin_user_update(handler, raw_body, ip):
    session = handler._get_session_or_401()
    if not session:
        return
    if not is_admin_user(session):
        handler._send_json(403, {"ok": False, "error": "관리자(Admin) 권한이 필요합니다."})
        return
    try:
        body = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except Exception:
        body = {}
    user_id = body.get("id")
    name = (body.get("name") or "").strip()
    dept_id = (body.get("dept_id") or "").strip()
    email = (body.get("email") or "").strip()
    role = body.get("role")
    disabled = body.get("disabled")
    new_password = body.get("new_password") or ""
    new_password_confirm = body.get("new_password_confirm") or ""

    from db import execute, get_one, query
    target_user = get_one("SELECT * FROM users WHERE id = ? LIMIT 1", (user_id,))
    if not target_user:
        handler._send_json(404, {"ok": False, "error": "사용자를 찾을 수 없습니다."})
        return

    cur_user_id = session.get("id") or session.get("user_id")
    cur_user_name = session.get("name", "")
    cur_username = session.get("username", "")
    # JSON body can carry the id as a string ("5" vs 5). Comparing normalized values
    # prevents bypassing the self-lockout / last-admin safeguards via a type mismatch.
    is_self = bool(cur_user_id is not None and str(cur_user_id) == str(user_id))
    if not is_self:
        is_self = bool(
            (cur_username and target_user.get("username") == cur_username)
            or (cur_user_name and target_user.get("name") == cur_user_name)
        )

    # Normalize the disabled flag once: the client may send 1/0, true/false or "true".
    disabled_flag = None
    if disabled is not None:
        disabled_flag = 1 if str(disabled).strip().lower() in ("1", "true", "yes", "on") else 0

    # Safeguard against locking oneself
    if is_self and disabled_flag == 1:
        handler._send_json(400, {"ok": False, "error": "현재 로그인 중인 본인 계정은 비활성화(잠금)할 수 없습니다."})
        return

    # Safeguard against removing last admin
    if is_self and role and role != "admin":
        other_admins = query("SELECT id FROM users WHERE is_admin = 1 AND id != ? AND disabled = 0", (user_id,))
        if not other_admins:
            handler._send_json(400, {"ok": False, "error": "시스템에 활성화된 다른 관리자가 없으므로 본인의 관리자 권한을 해제할 수 없습니다."})
            return

    updates = []
    params = []
    if name:
        updates.append("name = ?")
        params.append(name)
    if dept_id:
        updates.append("dept_id = ?")
        params.append(dept_id)
    if "email" in body:
        updates.append("email = ?")
        params.append(email)
    if role in ("admin", "manager", "member", "viewer"):
        updates.append("role = ?, is_admin = ?")
        params.extend([role, 1 if role == "admin" else 0])
    if disabled_flag is not None:
        updates.append("disabled = ?")
        params.append(disabled_flag)
    if new_password or new_password_confirm:
        if not new_password:
            handler._send_json(400, {"ok": False, "error": "새 비밀번호를 입력해주세요."})
            return
        # Admin resets do not need the old password, but the double entry is mandatory
        # so a typo cannot lock the user out of their account.
        if not new_password_confirm:
            handler._send_json(400, {"ok": False, "error": "새 비밀번호 확인을 입력해주세요."})
            return
        if new_password != new_password_confirm:
            handler._send_json(400, {"ok": False, "error": "새 비밀번호가 일치하지 않습니다."})
            return
        if len(new_password) < 8:
            handler._send_json(400, {"ok": False, "error": "비밀번호는 최소 8자 이상이어야 합니다."})
            return
        from services.auth import hash_password, _effective_pbkdf2_rounds
        salt, pwd_hash = hash_password(new_password)
        updates.append("salt = ?, password_hash = ?, iterations = ?, hash_algo = 'pbkdf2_sha256'")
        params.extend([salt, pwd_hash, _effective_pbkdf2_rounds()])

    if updates:
        params.append(user_id)
        execute(f"UPDATE users SET {', '.join(updates)} WHERE id = ?", tuple(params))
        from services.auth import delete_all_user_sessions
        role_changed = (role is not None and role != target_user.get("role"))
        disabled_changed = (disabled_flag is not None and disabled_flag != int(target_user.get("disabled") or 0))
        pwd_changed = bool(new_password)
        if role_changed or disabled_changed or pwd_changed:
            if is_self:
                cur_token = handler._extract_token() if hasattr(handler, "_extract_token") else None
                if cur_token:
                    from services.auth import hash_session_token
                    token_hash = hash_session_token(cur_token)
                    execute("DELETE FROM sessions WHERE (user_id = ? OR user_name = ?) AND token != ? AND token != ?", (user_id, target_user.get("username"), cur_token, token_hash))
                else:
                    delete_all_user_sessions(user_id)
            else:
                delete_all_user_sessions(user_id)
        from services.audit_logger import log_audit
        log_audit(session, ip, "USER_ROLE_UPDATE", "user", target_user.get("username"), details={"role": role, "disabled": disabled, "dept": dept_id})
    handler._send_json(200, {"ok": True, "message": "사용자 정보 및 권한이 변경되었습니다."})


def handle_post_admin_user_delete(handler, raw_body, ip):
    session = handler._get_session_or_401()
    if not session:
        return
    if not is_admin_user(session):
        handler._send_json(403, {"ok": False, "error": "관리자(Admin) 권한이 필요합니다."})
        return
    try:
        body = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except Exception:
        body = {}
    user_id = body.get("id")
    from db import get_one, execute
    target_user = get_one("SELECT * FROM users WHERE id = ? LIMIT 1", (user_id,))
    if not target_user:
        handler._send_json(404, {"ok": False, "error": "사용자를 찾을 수 없습니다."})
        return

    cur_name = session.get("name", "")
    if target_user.get("username") == cur_name or target_user.get("name") == cur_name:
        handler._send_json(400, {"ok": False, "error": "현재 로그인된 본인 계정은 삭제할 수 없습니다."})
        return

    from services.auth import safe_delete_user, delete_all_user_sessions
    delete_all_user_sessions(user_id)
    ok = safe_delete_user(user_id)
    if not ok:
        handler._send_json(500, {"ok": False, "error": "사용자 삭제 처리에 실패했습니다."})
        return

    from services.audit_logger import log_audit
    log_audit(session, ip, "USER_ADMIN_DELETE", "user", target_user.get("username"), details={"name": target_user.get("name"), "dept": target_user.get("dept_id")})

    handler._send_json(200, {"ok": True, "message": f"사용자 '{target_user.get('name')}' 계정이 삭제되었습니다."})


def handle_post_admin_user_approve(handler, raw_body, ip):
    session = handler._get_session_or_401()
    if not session:
        return
    if not is_admin_user(session):
        handler._send_json(403, {"ok": False, "error": "관리자(Admin) 권한이 필요합니다."})
        return

    from services.license_manager import check_seat_available
    avail, seat_err = check_seat_available()
    if not avail:
        handler._send_json(403, {"ok": False, "error": seat_err or "라이선스 허용 사용자 수(Seat) 제한에 도달했습니다. 더 이상 승인할 수 없습니다."})
        return

    try:
        body = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except Exception:
        body = {}

    user_id = body.get("id")
    role = (body.get("role") or "member").strip()
    if role not in ("admin", "manager", "member", "viewer"):
        role = "member"

    from db import get_one, execute
    target_user = get_one("SELECT * FROM users WHERE id = ? LIMIT 1", (user_id,))
    if not target_user:
        handler._send_json(404, {"ok": False, "error": "사용자를 찾을 수 없습니다."})
        return

    is_adm = 1 if role == "admin" else 0
    execute("UPDATE users SET status = 'active', disabled = 0, role = ?, is_admin = ? WHERE id = ?", (role, is_adm, user_id))

    from services.audit_logger import log_audit
    log_audit(session, ip, "USER_APPROVE", "user", target_user.get("username"), details={"name": target_user.get("name"), "dept": target_user.get("dept_id"), "role": role})

    try:
        from services.notification_service import create_notification
        create_notification("user", f"계정 '{target_user.get('name')}'({target_user.get('username')})의 가입 요청이 승인되었습니다.", "success")
    except Exception:
        pass

    handler._send_json(200, {"ok": True, "message": f"'{target_user.get('name')}' 사용자의 계정 발급이 승인되었습니다."})


def handle_post_admin_user_reject(handler, raw_body, ip):
    session = handler._get_session_or_401()
    if not session:
        return
    if not is_admin_user(session):
        handler._send_json(403, {"ok": False, "error": "관리자(Admin) 권한이 필요합니다."})
        return

    try:
        body = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except Exception:
        body = {}

    user_id = body.get("id")
    from db import get_one, execute
    target_user = get_one("SELECT * FROM users WHERE id = ? LIMIT 1", (user_id,))
    if not target_user:
        handler._send_json(404, {"ok": False, "error": "사용자를 찾을 수 없습니다."})
        return

    execute("UPDATE users SET status = 'rejected', disabled = 1 WHERE id = ?", (user_id,))
    from services.auth import delete_all_user_sessions
    delete_all_user_sessions(user_id)

    from services.audit_logger import log_audit
    log_audit(session, ip, "USER_REJECT", "user", target_user.get("username"), details={"name": target_user.get("name"), "dept": target_user.get("dept_id")})

    handler._send_json(200, {"ok": True, "message": f"'{target_user.get('name')}' 사용자의 계정 발급 요청이 반려되었습니다."})


from handlers.auth_handlers import (
    handle_account_check, handle_account_register, handle_account_login,
    handle_account_logout, handle_account_logout_all, handle_account_update_profile,
    handle_account_me, handle_account_csrf
)
from handlers.schedule_handlers import handle_schedule_create, handle_schedule_update, handle_schedule_delete
from handlers.product_handlers import (
    handle_product_save, handle_product_attachment_upload, handle_product_attachment_delete,
    handle_get_product_categories_admin, handle_product_category_save, handle_product_category_delete
)
from handlers.department_handler import handle_add_department, handle_delete_department, handle_update_department
from handlers.sync_handler import handle_sync
from handlers.submit_handler import handle_submit
from handlers.settings_handler import (
    handle_get_settings, handle_post_settings, handle_post_settings_test,
    handle_jira_inspect, handle_get_workspace_config
)
from handlers.chat_handler import (
    handle_chat_stream, handle_list_sessions, handle_create_session,
    handle_delete_session, handle_get_history, handle_execute_action, handle_cancel_action
)
from handlers.report_handler import (
    handle_get_weekly_report, handle_get_report_download,
    handle_get_report_template_info, handle_post_report_template_upload,
    handle_delete_report_template, handle_get_sample_template_download
)
from handlers.setup_handler import (
    check_needs_setup, handle_get_setup_status,
    handle_post_setup_verify_license, handle_post_setup_complete
)


def match_get(path):
    """Dispatch GET request to appropriate handler. Returns (type, handler_or_path, content_type)"""
    # Only evaluate setup check on entry/auth pages to avoid N+1 COUNT(*) queries on static assets and API requests
    needs_setup = False
    if path in ("/", "/index.html", "/login", "/login.html", "/setup", "/setup.html", "/api/setup/status"):
        needs_setup = check_needs_setup()

    if path == "/" or path == "/index.html":
        if needs_setup:
            return ("redirect", "/setup", None)
        return ("file", os.path.join(WEB_DIR, "index.html"), "text/html; charset=utf-8")
    elif path == "/login" or path == "/login.html":
        if needs_setup:
            return ("redirect", "/setup", None)
        return ("file", os.path.join(WEB_DIR, "login.html"), "text/html; charset=utf-8")
    elif path == "/setup" or path == "/setup.html":
        if not needs_setup:
            return ("redirect", "/login", None)
        return ("file", os.path.join(WEB_DIR, "setup.html"), "text/html; charset=utf-8")
    elif path == "/prototype.html":
        return ("file", os.path.join(WEB_DIR, "prototype.html"), "text/html; charset=utf-8")
    elif path == "/api/setup/status":
        return ("handler", handle_get_setup_status, None)


    elif path == "/favicon.svg":
        return ("file", os.path.join(WEB_DIR, "favicon.svg"), "image/svg+xml")
    elif path == "/favicon.ico":
        return ("nocontent", None, None)
    elif path == "/api/health":
        return ("handler", handle_get_health, None)
    elif path == "/api/departments":
        return ("handler", handle_get_departments, None)
    elif path == "/api/account/me":
        return ("handler", handle_account_me, None)
    elif path in ("/api/account/csrf", "/api/auth/csrf"):
        return ("handler", handle_account_csrf, None)


    elif path == "/api/members":
        return ("handler", handle_get_members, None)
    elif path == "/api/categories":
        return ("handler", handle_get_categories, None)
    elif path == "/api/records":
        return ("handler", handle_get_records, None)
    elif path == "/api/ask":
        return ("handler", handle_get_ask, None)
    elif path == "/api/schedule":
        return ("handler", handle_get_schedule, None)
    elif path == "/api/products/categories":
        return ("handler", handle_get_products_categories, None)
    elif path == "/api/products/categories/admin":
        return ("handler", handle_get_product_categories_admin, None)
    elif path == "/api/products":
        return ("handler", handle_get_products, None)
    elif path == "/api/products/detail":
        return ("handler", handle_get_product_detail, None)
    elif path == "/api/products/attachment":
        return ("handler", handle_get_products_attachment, None)
    elif path == "/api/vectors/stats":
        return ("handler", handle_get_vector_stats, None)
    elif path == "/api/activities":
        return ("handler", handle_get_activities, None)
    elif path == "/api/notifications":
        return ("handler", handle_get_notifications, None)
    elif path == "/api/notifications/stream":
        return ("handler", handle_get_notifications_stream, None)
    elif path == "/api/settings":
        return ("handler", handle_get_settings, None)
    elif path == "/api/chat/sessions":
        return ("handler", handle_list_sessions, None)
    elif path == "/api/chat/history":
        return ("handler", handle_get_history, None)
    elif path == "/api/workspace-config":
        return ("handler", handle_get_workspace_config, None)
    elif path == "/api/reports/template/info":
        return ("handler", handle_get_report_template_info, None)
    elif path == "/api/reports/template/sample":
        return ("handler", handle_get_sample_template_download, None)
    elif path == "/api/reports/weekly":
        return ("handler", handle_get_weekly_report, None)
    elif path == "/api/reports/download":
        return ("handler", handle_get_report_download, None)
    elif path == "/api/records/hierarchy":
        return ("handler", handle_get_record_hierarchy, None)
    elif path == "/api/admin/backups":
        return ("handler", handle_get_admin_backups, None)
    elif path == "/api/admin/backups/download":
        return ("handler", handle_get_admin_backup_download, None)
    elif path == "/api/admin/audit-logs":
        return ("handler", handle_get_admin_audit_logs, None)
    elif path == "/api/admin/audit-logs/export":
        return ("handler", handle_get_admin_audit_logs_export, None)
    elif path == "/api/version":
        return ("handler", handle_get_version, None)
    elif path == "/api/admin/ai-usage":
        return ("handler", handle_get_admin_ai_usage, None)
    elif path == "/api/records/export/excel":
        from handlers.report_handler import handle_get_export_records_excel
        return ("handler", handle_get_export_records_excel, None)
    elif path == "/api/admin/license":
        return ("handler", handle_get_admin_license, None)
    elif path == "/api/admin/users":
        return ("handler", handle_get_admin_users, None)

    elif path.startswith("/api/jira/attachments/"):
        return ("handler", handle_get_jira_attachment, None)
    elif path.startswith("/api/attachments/"):
        return ("handler", handle_get_local_attachment, None)
    elif path == "/api/issues" or path.startswith("/api/issues/"):
        return ("handler", handle_get_issue_detail, None)
    else:
        # Static files: /css/*, /js/*, /assets/*, /images/*
        # Security: prevent directory traversal
        clean = urllib.parse.unquote(path).lstrip("/")
        if clean.startswith(("css/", "js/", "assets/", "images/")):
            safe_path = os.path.normpath(os.path.join(WEB_DIR, clean))
            if safe_path.startswith(os.path.normpath(WEB_DIR)) and os.path.isfile(safe_path):
                ct, _ = mimetypes.guess_type(safe_path)
                return ("file", safe_path, ct or "application/octet-stream")
        return ("notfound", None, None)


def match_post(path):
    """Return POST handler function for given path"""
    if path == "/api/departments":
        return handle_add_department
    elif path == "/api/departments/update":
        return handle_update_department
    elif path == "/api/departments/delete":
        return handle_delete_department
    elif path == "/api/submit":
        return handle_submit
    elif path == "/api/sync":
        return handle_sync
    elif path in ("/api/account/check", "/api/auth/check"):
        return handle_account_check
    elif path in ("/api/account/register", "/api/auth/register"):
        return handle_account_register
    elif path in ("/api/account/login", "/api/auth/login"):
        return handle_account_login
    elif path in ("/api/account/logout", "/api/auth/logout"):
        return handle_account_logout
    elif path in ("/api/account/logout-all", "/api/auth/logout-all"):
        return handle_account_logout_all
    elif path in ("/api/account/update-profile", "/api/auth/update-profile"):
        return handle_account_update_profile
    elif path == "/api/schedule":
        return handle_schedule_create
    elif path == "/api/schedule/update":
        return handle_schedule_update
    elif path == "/api/schedule/delete":
        return handle_schedule_delete
    elif path == "/api/schedule/approve":
        from handlers.schedule_handlers import handle_schedule_approve
        return handle_schedule_approve
    elif path == "/api/schedule/assign-task":
        return handle_assign_schedule_task
    elif path == "/api/schedule/unassign-task":
        return handle_unassign_schedule_task
    elif path == "/api/products/save":
        return handle_product_save
    elif path == "/api/products/categories/save":
        return handle_product_category_save
    elif path == "/api/products/categories/delete":
        return handle_product_category_delete
    elif path == "/api/products/attachments/upload":
        return handle_product_attachment_upload
    elif path == "/api/products/attachments/delete":
        return handle_product_attachment_delete
    elif path == "/api/vectors/sync":
        return handle_post_vector_sync
    elif path == "/api/settings":
        return handle_post_settings
    elif path == "/api/settings/test":
        return handle_post_settings_test
    elif path == "/api/jira/inspect" or path == "/api/jira/test-connection":
        return handle_jira_inspect
    elif path == "/api/reports/template":
        return handle_post_report_template_upload
    elif path == "/api/reports/template/delete":
        return handle_delete_report_template
    elif path == "/api/chat/stream":
        return handle_chat_stream
    elif path == "/api/chat/sessions":
        return handle_create_session
    elif path == "/api/chat/sessions/delete":
        return handle_delete_session
    elif path == "/api/chat/execute-action":
        return handle_execute_action
    elif path == "/api/chat/cancel-action":
        return handle_cancel_action
    elif path == "/api/issues/comment":
        return handle_post_issue_comment
    elif path == "/api/issues/transition":
        return handle_post_issue_transition
    elif path == "/api/issues/attachments":
        return handle_post_issue_attachment
    elif path == "/api/records/attachments/delete":
        return handle_delete_record_attachment
    elif path == "/api/records/delete":
        return handle_delete_record
    elif path == "/api/records/update":
        return handle_post_record_update
    elif path == "/api/records/push-jira":
        return handle_push_record_jira
    elif path == "/api/notifications/read":
        return handle_post_notification_read
    elif path == "/api/notifications/read-all":
        return handle_post_notification_read_all
    elif path == "/api/admin/backups/create":
        return handle_post_admin_backup_create
    elif path == "/api/admin/backups/restore":
        return handle_post_admin_backup_restore
    elif path == "/api/admin/backups/config":
        return handle_post_admin_backup_config
    elif path == "/api/admin/backups/upload":
        return handle_post_admin_backup_upload
    elif path == "/api/admin/license/activate":
        return handle_post_admin_license_activate
    elif path == "/api/admin/users/create":
        return handle_post_admin_user_create
    elif path == "/api/admin/users/update":
        return handle_post_admin_user_update
    elif path == "/api/admin/users/delete":
        return handle_post_admin_user_delete
    elif path == "/api/admin/users/approve":
        return handle_post_admin_user_approve
    elif path == "/api/admin/users/reject":
        return handle_post_admin_user_reject
    elif path == "/api/setup/verify-license":
        return handle_post_setup_verify_license
    elif path == "/api/setup/complete":
        return handle_post_setup_complete
    else:
        return None
