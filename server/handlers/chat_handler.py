from config import is_client_disconnect
import json
import re
import time
import threading
from datetime import datetime
from utils.logging import log_line, access_log
from services.auth import get_session
from services.chat_store import (
    list_sessions, create_session, get_session as get_chat_session,
    append_message, load_history, update_session_title, update_proposal_status
)
from services.chat_agent import run_agent_conversation
from services.chat_tools import execute_tool
from services.jira_client import jira_ongoing_records_for, get_cached_jira_records
from utils.http_body import parse_json_dict


def _chat_session_owned(chat_sess, session):
    """
    대화 세션이 현재 로그인 사용자 소유인지 판정한다 (표시 이름 + 부서).

    이름만 비교하면 부서가 다른 동명이인의 대화 기록을 읽거나 삭제할 수 있다.
    """
    if not chat_sess or not session:
        return False
    if (chat_sess.get("user_name") or "") != (session.get("name") or ""):
        return False
    return (chat_sess.get("user_org") or "") == (session.get("org") or "")


from prompts import (
    CHAT_SYSTEM_PROMPT,
    JIRA_ON,
    JIRA_OFF,
    LANG_DIRECTIVE,
)


def _build_system_prompt(user_name, cfg, current_user=None, referenced_section="", lang="ko"):
    """시스템 프롬프트를 조립한다.

    RBAC: 진행 중 업무 목록도 사용자 열람 권한(visible_records)으로 필터링한 뒤 주입한다.
    """
    from services.chat_tools import _resolve_assignee_name
    from datetime import timedelta
    now_dt = datetime.now()
    today_str = now_dt.strftime("%Y-%m-%d (%A)")
    yesterday_str = (now_dt - timedelta(days=1)).strftime("%Y-%m-%d")
    tomorrow_str = (now_dt + timedelta(days=1)).strftime("%Y-%m-%d")
    today_pure = now_dt.strftime("%Y-%m-%d")

    date_context = f"{today_str} [오늘: {today_pure}, 어제: {yesterday_str}, 내일: {tomorrow_str}]"
    resolved_name = _resolve_assignee_name(user_name, {"name": user_name}) or user_name
    
    # Active tasks section (Local-First: load all ongoing tasks for user)
    active_tasks_section = ""
    try:
        from services.search import merged_records
        from services.auth import visible_records
        records, _ = merged_records(cfg)
        if current_user:
            records = visible_records(current_user, records)
        closed_statuses = {"완료", "done", "closed", "해결됨", "resolved", "종료"}
        r_name_lower = resolved_name.lower()
        ongoing = [
            r for r in records
            if ((r.get("statusName") or r.get("status") or "").strip().lower() not in closed_statuses)
            and (r_name_lower in (r.get("assignee") or "").lower() or r_name_lower in (r.get("participants") or "").lower())
        ]
        if ongoing:
            lines = [f"Danh sách thẻ đang thực hiện của {resolved_name} (tổng {len(ongoing)} thẻ):"]
            for r in ongoing[:20]:
                key = r.get("cardCode") or (r.get("jira") or {}).get("key") or (f"#{r.get('id')}" if r.get("id") else "")
                title = r.get("title", "")
                status = r.get("statusName") or r.get("status") or "진행"
                due = r.get("dueDate") or "마감일 미지정"
                summary = (r.get("summary") or r.get("memo") or "")[:150]
                lines.append(f"- [{key}] {title} | Trạng thái: {status} | Hạn: {due} | Chi tiết: {summary}")
            active_tasks_section = "\n".join(lines)
    except Exception as e:
        log_line("[Chat Handler] active_tasks_section 구성 오류:", e)
    
    is_jira_enabled = bool((cfg.get("jira") or {}).get("enabled"))
    jira_context_section = JIRA_ON if is_jira_enabled else JIRA_OFF
    company_name = (cfg.get("company") or {}).get("name") or "ARGOS WORKS"
    lang_dir = (LANG_DIRECTIVE.get(lang) or LANG_DIRECTIVE["ko"]).format(user_name=user_name)

    return CHAT_SYSTEM_PROMPT.format(
        company=company_name,
        today=date_context,
        user_name=user_name,
        jira_context_section=jira_context_section,
        company_context=jira_context_section,
        active_tasks_section=active_tasks_section,
        referenced_issues_section=referenced_section,
        lang_directive=lang_dir,
    )


def _extract_referenced_keys(text):
    r"""메시지에서 프로젝트 이슈 키/로컬 업무 코드 패턴([A-Z]{2,10}-\d+ 또는 #\d+)을 동적으로 추출한다."""
    NON_ISSUE_KEYS = {"RS-485", "RS-232", "RS-422", "RJ-45", "RJ-11", "CAT-5", "CAT-6"}

    matches = re.findall(r'\b[A-Za-z]{2,10}-\d+\b', text or '')
    hash_matches = re.findall(r'#\d+\b', text or '')
    all_keys = [m.upper() for m in matches if m.upper() not in NON_ISSUE_KEYS] + hash_matches
    return list(set(all_keys))



def _parse_metadata(answer_text):
    """AI 답변에서 구조화된 블록(:::action-proposal, :::quick-actions)을 추출한다."""
    result = {
        "action": "none",
        "action_proposal": None,
        "quick_actions": []
    }
    
    # Extract action-proposal
    ap_match = re.search(r':::action-proposal\r?\n(.*?)\r?\n:::', answer_text, re.DOTALL)
    if ap_match:
        raw_content = ap_match.group(1).strip()
        proposal = {}
        if raw_content.startswith('{') and raw_content.endswith('}'):
            try:
                parsed_obj = json.loads(raw_content)
                params = parsed_obj.get('parameters') or {}
                proposal = {**params, **parsed_obj}
            except Exception:
                pass
        if not proposal:
            current_key = None
            for line in raw_content.splitlines():
                m = re.match(r'^([a-zA-Z_]+)\s*:\s*(.*)$', line)
                if m:
                    current_key = m.group(1).strip()
                    proposal[current_key] = m.group(2).strip()
                elif current_key and line.strip():
                    proposal[current_key] += '\n' + line.strip()
        if not proposal.get('action_type') and (proposal.get('action') or proposal.get('type')):
            act = proposal.get('action') or proposal.get('type')
            proposal['action_type'] = 'create_task' if act == 'create_issue' else act
        if not proposal.get('summary') and proposal.get('title'):
            proposal['summary'] = proposal.get('title')
        proposal['proposal_status'] = 'pending'
        result['action_proposal'] = proposal
        result['action'] = 'propose_action'
    
    # Extract quick-actions
    qa_match = re.search(r':::quick-actions\r?\n(.*?)\r?\n:::', answer_text, re.DOTALL)
    if qa_match:
        actions = []
        for line in qa_match.group(1).strip().splitlines():
            line = line.strip().lstrip('- ').strip()
            if line:
                actions.append(line)
        result["quick_actions"] = actions[:5]
    
    return result


def _build_referenced_section(keys, cfg, current_user=None):
    """참조된 업무 카드/이슈 키에 대한 상세 정보를 시스템 프롬프트에 추가한다.

    RBAC: 현재 사용자가 열람 권한을 가진 카드만 프롬프트에 포함한다 (권한 우회 방지).
    """
    if not keys:
        return ""
    
    from services.data_store import find_record_by_key_or_code
    from services.search import merged_records
    from services.auth import visible_records, can_view_record
    
    records, _ = merged_records(cfg)
    if current_user:
        records = visible_records(current_user, records)
    lines = ["## 참조된 업무 카드/이슈 상세 (Referenced Tasks)"]
    for key in keys:
        key_upper = key.upper()
        matched = find_record_by_key_or_code(key_upper)
        if matched and current_user and not can_view_record(current_user, matched):
            # 직접 DB 조회 결과가 권한 밖이면 프롬프트에 넣지 않는다 (fail-closed)
            matched = None
        if not matched:
            for r in records:
                k = (r.get("cardCode") or (r.get("jira") or {}).get("key") or "").strip().upper()
                if k == key_upper:
                    matched = r
                    break
        if matched:
            display_k = matched.get("cardCode") or (matched.get("jira") or {}).get("key") or key_upper
            due = matched.get("dueDate") or "마감일 미지정"
            summary = (matched.get("summary") or matched.get("memo") or "")[:300]
            status = matched.get("statusName") or matched.get("status") or ""
            lines.append(f"- [{display_k}] {matched.get('title', '')} | 상태: {status} | 담당: {matched.get('assignee', '')} | 마감일: {due} | 상세: {summary}")
    return "\n".join(lines) if len(lines) > 1 else ""


def _resolve_conversation_lang(message, history, client_lang=None):
    """
    사용자의 질문 언어 및 클라이언트 언어 설정에 맞춰 자연스럽게 응답 언어를 결정합니다.
    - 베트남어 질문/설정 -> vi
    - 한국어 질문/설정 -> ko
    - 영어 질문/설정 -> en
    """
    # 1. 사용자가 특정 언어로 명시적 요청한 경우 최우선 반영
    if re.search(r'(?:trả lời\s+(?:bằng\s+)?tiếng việt|nói\s+tiếng việt|giải thích\s+(?:bằng\s+)?tiếng việt|dịch\s+(?:sang\s+)?tiếng việt|bằng\s+tiếng việt|tiếng việt\s+đi|베트남어(?:로)?(?:\s*답변|\s*설명|\s*번역|\s*말해))', message, re.I):
        return "vi"
    if re.search(r'(?:reply\s+in\s+english|answer\s+in\s+english|explain\s+in\s+english|in\s+english\s+please|speak\s+in\s+english|영어로(?:\s*답변|\s*설명|\s*말해))', message, re.I):
        return "en"
    if re.search(r'(?:한국어로|한국말(?:로)?|korean|tiếng hàn)', message, re.I):
        return "ko"

    # 2. 메시지 텍스트 내 문자셋 분석
    has_hangul = bool(re.search(r'[가-힣]', message))
    has_vietnamese = bool(re.search(r'[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđĐ]', message, re.I))
    if not has_vietnamese:
        has_vietnamese = bool(re.search(r'\b(tôi|bạn|hôm nay|công việc|làm gì|dự án|báo cáo|thẻ|sản phẩm|cho tôi|giúp tôi)\b', message, re.I))

    if has_vietnamese and not has_hangul:
        return "vi"
    if has_hangul and not has_vietnamese:
        return "ko"

    # 3. 클라이언트 UI 언어 설정 반영
    if client_lang in ("vi", "ko", "en"):
        return client_lang

    # 4. 기본값
    return "ko"


def handle_chat_stream(handler, raw_body, ip):
    """SSE 스트리밍 채팅 엔드포인트 (POST /api/chat/stream)"""
    session = handler._get_session_or_401()
    if not session:
        return
    
    user_name = session["name"]
    user_org = session.get("org", "lab")
    
    try:
        body, body_err = parse_json_dict(raw_body)
        if body_err:
            handler._send_json(400, {"ok": False, "error": body_err})
            return
    except Exception:
        handler._send_json(400, {"ok": False, "error": "잘못된 요청 형식"})
        return
    
    message = (body.get("message") or "").strip()
    session_id = body.get("sessionId")
    client_lang = body.get("lang", "ko")
    custom_ai = body.get("customAi")
    
    if not message:
        handler._send_json(400, {"ok": False, "error": "메시지를 입력해주세요."})
        return
    
    cfg = handler.cfg
    allow_user_keys = bool(cfg.get("ai", {}).get("allow_user_keys", False))
    if custom_ai and not allow_user_keys:
        custom_ai = None
    
    # Session resolution
    chat_session = None
    if session_id:
        chat_session = get_chat_session(session_id)
        if chat_session and not _chat_session_owned(chat_session, session):
            handler._send_json(403, {"ok": False, "error": "접근 권한이 없습니다."})
            return
    
    if not chat_session:
        # Find most recent or create new
        sessions = list_sessions(user_name, user_org)
        if sessions:
            chat_session = sessions[0]
            session_id = chat_session["id"]
        else:
            chat_session = create_session(user_name, user_org, message[:26])
            session_id = chat_session["id"]
    
    # Update title if default
    if chat_session.get("title") in ("새로운 대화", "Đoạn chat mới", ""):
        update_session_title(session_id, message[:26])
    
    # Save user message
    append_message(session_id, "user", message, user_name)
    
    # Load context (last 20 messages)
    history = load_history(session_id, limit=20)
    
    # 언어 결정: 사용자 질의 언어에 자연스럽게 동기화
    effective_lang = _resolve_conversation_lang(message, history, client_lang)
    
    # 현재 로그인 사용자 컨텍스트 (프롬프트 구성과 도구 실행에 동일한 RBAC 기준 적용)
    current_user_ctx = {
        "id": session.get("id") or session.get("user_id"),
        "name": user_name,
        "org": user_org,
        "dept_id": user_org,
        "role": session.get("role", "member"),
        "is_admin": session.get("role") == "admin",
        "email": session.get("email", "")
    }

    # Build messages for AI
    # Check for referenced issue keys (RBAC: 열람 권한이 있는 카드만 프롬프트에 주입)
    ref_keys = _extract_referenced_keys(message)
    ref_section = ""
    if ref_keys:
        ref_section = _build_referenced_section(ref_keys, cfg, current_user_ctx)

    system_prompt = _build_system_prompt(
        user_name, cfg, current_user_ctx, referenced_section=ref_section, lang=effective_lang
    )
    
    ai_messages = [{"role": "system", "content": system_prompt}]
    for h in history:
        role = h.get("role", "user")
        if role in ("user", "assistant"):
            ai_messages.append({"role": role, "content": h.get("content", "")})
    
    # Start SSE
    handler._start_sse()
    
    try:
        # Run agent with status callback
        def on_status(text):
            ok = handler._send_sse_event({"status": text})
            return ok
        
        # Keep-alive ping thread while agent runs
        stop_ping = threading.Event()
        client_disconnected = threading.Event()

        def _keep_alive():
            while not stop_ping.wait(10.0):
                try:
                    handler.wfile.write(b": ping\n\n")
                    handler.wfile.flush()
                except Exception:
                    client_disconnected.set()
                    break
        ping_thread = threading.Thread(target=_keep_alive, daemon=True)
        ping_thread.start()

        # 인증 세션 기반 사용자 컨텍스트 (이미 위에서 구성됨 — RBAC 일관성 유지)
        answer = run_agent_conversation(
            messages=ai_messages,
            current_user=current_user_ctx,
            cfg=cfg,
            lang=effective_lang,
            on_status_update=on_status,
            max_turns=4,
            custom_ai_config=custom_ai
        )
        stop_ping.set()

        if client_disconnected.is_set():
            log_line(f"[Chat Stream] 클라이언트 연결 조기 종료 감지: session={session_id}")
            return
        
        # Stream answer in chunks (smooth typewriter effect)
        CHUNK_SIZE = 35
        for i in range(0, len(answer), CHUNK_SIZE):
            chunk = answer[i:i + CHUNK_SIZE]
            ok = handler._send_sse_event({"text": chunk})
            if not ok:
                log_line(f"[Chat Stream] 클라이언트 브라우저 닫힘(BrokenPipe) -> 전송 조기 중단: {session_id}")
                return
            time.sleep(0.012)  # 12ms delay for smooth streaming
        
        # Parse metadata
        metadata = _parse_metadata(answer)
        
        # Context warning
        if len(history) >= 20:
            metadata["context_warning"] = True
        
        # Save assistant message
        saved_msg = append_message(session_id, "assistant", answer, "AI", metadata=metadata)
        
        # Track AI Token Usage per user & session
        try:
            from services.ai_usage_service import record_ai_usage
            # Estimate prompt tokens from system_prompt + message
            p_tok = (len(system_prompt) + len(message)) // 3
            c_tok = len(answer) // 3
            t_tok = p_tok + c_tok
            ai_prov = (custom_ai or {}).get("provider") or cfg.get("ai", {}).get("provider", "gemini")
            ai_mod = (custom_ai or {}).get("model") or cfg.get("ai", {}).get("model", "")
            record_ai_usage(
                user_name=user_name,
                dept_id=user_org,
                provider=ai_prov,
                model=ai_mod,
                prompt_tokens=p_tok,
                completion_tokens=c_tok,
                total_tokens=t_tok,
                session_id=session_id,
                feature="chat"
            )
        except Exception as e:
            log_line("[AI Usage] record failed:", e)

        # Send completion event
        handler._send_sse_event({
            "done": True,
            "metadata": metadata,
            "sessionId": session_id,
            "messageId": saved_msg.get("id") if saved_msg else None
        })
        
    except Exception as e:
        if is_client_disconnect(e):
            log_line(f"[Chat Stream] 클라이언트 연결 끊김(소켓 종료): {session_id}")
            stop_ping.set()
            return
        log_line("[Chat Stream] 오류:", e)
        try:
            handler._send_sse_event({"error": f"채팅 처리 중 오류: {str(e)}"})
        except Exception:
            pass
    
    handler._end_sse()
    access_log(ip, "chat_stream", 200, f"session={session_id} msg={message[:40]}")


def handle_list_sessions(handler, parsed, ip):
    """GET /api/chat/sessions — 세션 목록 조회"""
    session = handler._get_session_or_401()
    if not session:
        return
    sessions = list_sessions(session["name"], session.get("org", ""))
    handler._send_json(200, {"ok": True, "sessions": sessions})


def handle_create_session(handler, raw_body, ip):
    """POST /api/chat/sessions — 새 세션 생성"""
    session = handler._get_session_or_401()
    if not session:
        return
    body = {}
    if raw_body:
        try:
            body, body_err = parse_json_dict(raw_body)
            if body_err:
                handler._send_json(400, {"ok": False, "error": body_err})
                return
        except Exception as e:
            log_line("[Chat] Failed to parse request body in create_session:", e)
    title = body.get("title", "새로운 대화")
    new_sess = create_session(session["name"], session.get("org", ""), title)
    handler._send_json(200, {"ok": True, "session": new_sess})
    access_log(ip, "chat_create_session", 200, new_sess["id"])


def handle_delete_session(handler, raw_body, ip):
    """POST /api/chat/sessions/delete — 세션 삭제"""
    session = handler._get_session_or_401()
    if not session:
        return
    body = {}
    if raw_body:
        try:
            body, body_err = parse_json_dict(raw_body)
            if body_err:
                handler._send_json(400, {"ok": False, "error": body_err})
                return
        except Exception as e:
            log_line("[Chat] Failed to parse request body in create_session:", e)
    session_id = body.get("sessionId", "")
    if not session_id:
        handler._send_json(400, {"ok": False, "error": "sessionId가 필요합니다."})
        return
    from services.chat_store import delete_session
    ok = delete_session(session_id, session["name"], session.get("org", ""))
    handler._send_json(200, {"ok": ok})
    access_log(ip, "chat_delete_session", 200, session_id)


def handle_get_history(handler, parsed, ip):
    """GET /api/chat/history — 채팅 히스토리 조회 (커서 기반 페이지네이션)"""
    session = handler._get_session_or_401()
    if not session:
        return
    from urllib.parse import parse_qs
    qs = parse_qs(parsed.query)
    session_id = (qs.get("sessionId", [""])[0])
    before_id = qs.get("beforeId", [None])[0]
    # ?limit=abc 이전에는 ValueError(500), 음수 limit 은 LIMIT -1(전체 조회)이 되었다.
    try:
        limit = int(qs.get("limit", ["20"])[0])
    except (TypeError, ValueError):
        limit = 20
    limit = max(1, min(limit, 100))

    if not session_id:
        handler._send_json(400, {"ok": False, "error": "sessionId가 필요합니다."})
        return

    # Verify session ownership (fail-closed: unknown session id → 404)
    chat_sess = get_chat_session(session_id)
    if not chat_sess:
        handler._send_json(404, {"ok": False, "error": "대화 세션을 찾을 수 없습니다."})
        return
    if not _chat_session_owned(chat_sess, session):
        handler._send_json(403, {"ok": False, "error": "접근 권한이 없습니다."})
        return
    
    try:
        if before_id:
            before_id = int(before_id)
    except (ValueError, TypeError):
        before_id = None
    
    messages = load_history(session_id, limit=limit, before_id=before_id)
    handler._send_json(200, {"ok": True, "messages": messages, "hasMore": len(messages) >= limit})


def handle_execute_action(handler, raw_body, ip):
    """POST /api/chat/execute-action — 사용자가 확인한 액션 실행"""
    session = handler._get_session_or_401()
    if not session:
        return
    
    body = {}
    if raw_body:
        try:
            body, body_err = parse_json_dict(raw_body)
            if body_err:
                handler._send_json(400, {"ok": False, "error": body_err})
                return
        except Exception:
            handler._send_json(400, {"ok": False, "error": "잘못된 요청"})
            return
    
    action_type = body.get("action_type", "")
    cfg = handler.cfg
    # Pass full authenticated session (id, role, name, org, email) for proper RBAC & license checks
    current_user = {
        "id": session.get("id") or session.get("user_id"),
        "name": session["name"],
        "org": session.get("org", "lab"),
        "dept_id": session.get("org", "lab"),
        "role": session.get("role", "member"),
        "is_admin": session.get("role") == "admin",
        "email": session.get("email", "")
    }
    
    # Map action_type to tool name
    action_tool_map = {
        "create_task": "create_issue",
        "create_subtask": "create_issue",
        "add_comment": "add_issue_comment",
        "update_status": "update_issue_status",
        "schedule_issue": "schedule_issue",
    }
    
    tool_name = action_tool_map.get(action_type)
    if not tool_name:
        handler._send_json(400, {"ok": False, "error": f"알 수 없는 액션: {action_type}"})
        return
    
    # Build tool args from body
    tool_args = {}
    if action_type in ("create_task", "create_subtask"):
        is_sub = (action_type == "create_subtask")
        tool_args = {
            "summary": body.get("summary", ""),
            "description": body.get("description", ""),
            "issue_type": body.get("issue_type") or ("하위 작업" if is_sub else "메인프로젝트"),
            "parent_key": (body.get("parent_key") or body.get("issue_key")) if is_sub else None,
            "priority": body.get("priority", "Medium"),
            "assignee": body.get("assignee"),
            "status": body.get("status"),
            "start_date": body.get("start_date"),
            "due_date": body.get("due_date"),
        }
    elif action_type == "add_comment":
        tool_args = {
            "issue_key": body.get("issue_key", ""),
            "comment": body.get("comment") or body.get("description") or body.get("summary", ""),
        }
    elif action_type == "update_status":
        tool_args = {
            "issue_key": body.get("issue_key", ""),
            "status": body.get("status", ""),
        }
    elif action_type == "schedule_issue":
        tool_args = {
            "issue_key": body.get("issue_key", ""),
            "start_date": body.get("start_date", ""),
            "due_date": body.get("due_date", ""),
        }
    
    # 사용자가 UI에서 직접 승인한 액션이므로 allow_write=True 허용
    result = execute_tool(tool_name, tool_args, current_user, cfg, allow_write=True)
    
    # Persist proposal status as executed if session_id provided
    session_id = body.get("session_id") or body.get("sessionId")
    if session_id and result and (result.get("success") or result.get("ok") or not result.get("error")):
        try:
            update_proposal_status(
                session_id=session_id,
                status="executed",
                message_id=body.get("message_id") or body.get("messageId"),
                summary=body.get("summary"),
                action_type=action_type,
                user_name=session["name"],
                user_dept_id=session.get("org", "")
            )
        except Exception as e:
            log_line("executed 상태 저장 오류:", e)
            
    handler._send_json(200, {"ok": True, "result": result})
    access_log(ip, f"chat_action_{action_type}", 200, body.get("issue_key", ""))


def handle_cancel_action(handler, raw_body, ip):
    """POST /api/chat/cancel-action — 액션 제안 취소 상태를 영구 저장한다."""
    session = handler._get_session_or_401()
    if not session:
        return
    body = {}
    if raw_body:
        try:
            body, body_err = parse_json_dict(raw_body)
            if body_err:
                handler._send_json(400, {"ok": False, "error": body_err})
                return
        except Exception:
            handler._send_json(400, {"ok": False, "error": "잘못된 요청"})
            return
            
    session_id = body.get("sessionId") or body.get("session_id")
    message_id = body.get("messageId") or body.get("message_id")
    summary = body.get("summary")
    action_type = body.get("action_type") or body.get("actionType")
    
    ok = False
    if session_id:
        ok = update_proposal_status(
            session_id=session_id,
            status="cancelled",
            message_id=message_id,
            summary=summary,
            action_type=action_type,
            user_name=session["name"],
            user_dept_id=session.get("org", "")
        )
    handler._send_json(200, {"ok": True, "updated": ok})
