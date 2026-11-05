"""chat_agent.py — ReAct 멀티턴 에이전트 대화 루프

AI가 도구를 호출하면 실행 결과를 피드백하고,
최종 텍스트 답변이 나올 때까지 반복한다 (최대 max_turns회).
"""

import json
import re
from utils.logging import log_line
from services.ai_client import call_ai_chat_completions
from services.chat_tools import AGENT_READ_TOOLS, execute_tool
from prompts import (
    POST_TOOL_NOTE,
    FORCE_FINAL,
    POST_TOOL_NOTE_READ_ONLY,
    FORCE_FINAL_READ_ONLY,
    POST_TOOL_NOTE_KNOWLEDGE,
    FORCE_FINAL_KNOWLEDGE,
    tool_status_text,
)



_TOOL_GROUPS = {
    "tasks": {
        "search_issues", "get_issue_details", "get_child_issues", "get_active_tasks"
    },
    "products": {"search_products", "get_product_details", "search_documents"},
    "calendar": {"get_calendar_schedule", "search_internal_records"},
    "documents": {"search_documents"},
    "records": {"search_internal_records", "search_documents"},
    "reports": {"generate_work_report", "search_issues", "get_issue_details"},
    "knowledge": {
        "search_documents", "search_internal_records", "search_issues", "search_products"
    },
}


def select_agent_tools(intent=None):
    """Select only read tools needed by the classified request."""
    if intent is None:
        return list(AGENT_READ_TOOLS)
    if intent.get("type") == "general_question":
        return []

    domains = intent.get("domains") or (
        [intent.get("domain")] if intent.get("domain") else []
    )
    if intent.get("type") == "knowledge_search":
        domains = ["knowledge"]
    elif intent.get("type") == "business_action":
        domains = ["tasks"]
    elif intent.get("type") == "ambiguous" and not domains:
        domains = ["knowledge"]

    allowed_names = set()
    for domain in domains:
        allowed_names.update(_TOOL_GROUPS.get(domain, set()))
    if "tasks" in domains and not intent.get("include_active_tasks"):
        allowed_names.discard("get_active_tasks")
    if not allowed_names:
        allowed_names = _TOOL_GROUPS["knowledge"]

    return [
        tool for tool in AGENT_READ_TOOLS
        if tool.get("function", {}).get("name") in allowed_names
    ]


def _append_document_sources(answer, messages, lang="ko"):
    """Ensure retrieved document evidence remains traceable in the final answer."""
    sources = []
    seen = set()
    for message in messages or []:
        if not isinstance(message, dict) or message.get("role") != "tool":
            continue
        try:
            payload = json.loads(message.get("content") or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        documents = payload.get("documents") if isinstance(payload, dict) else None
        if not isinstance(documents, list):
            continue
        for document in documents:
            if not isinstance(document, dict):
                continue
            source_id = str(document.get("source_id") or "").strip()
            title = re.sub(r"\s+", " ", str(document.get("title") or "")).strip()
            if not source_id or source_id in seen:
                continue
            seen.add(source_id)
            sources.append((title, source_id))
            if len(sources) >= 3:
                break
        if len(sources) >= 3:
            break

    answer = str(answer or "")
    if not answer.strip() or not sources:
        return answer
    missing_sources = [
        (title, source_id) for title, source_id in sources
        if source_id not in answer
    ]
    if not missing_sources:
        return answer

    labels = {
        "ko": "출처",
        "vi": "Nguồn tham khảo",
        "en": "Sources",
    }
    label = labels.get(lang, labels["ko"])
    refs = "; ".join(
        f"[{title} / {source_id}]" if title else f"[{source_id}]"
        for title, source_id in missing_sources
    )
    citation_line = f"{label}: {refs}"

    # Keep action-proposal and quick-action blocks at the end of the response.
    markers = [
        match.start()
        for pattern in (r":::action-proposal\s*\r?\n", r":::quick-actions\s*\r?\n")
        if (match := re.search(pattern, answer))
    ]
    if markers:
        index = min(markers)
        return answer[:index].rstrip() + "\n\n" + citation_line + "\n\n" + answer[index:].lstrip()
    return answer.rstrip() + "\n\n" + citation_line


def resolve_agent_max_turns(intent=None, requested=4):
    """Bound ReAct calls by intent while preserving enough steps for multi-tool work."""
    try:
        requested = max(1, int(requested))
    except (TypeError, ValueError):
        requested = 4
    if not isinstance(intent, dict):
        return requested

    intent_type = intent.get("type")
    limits = {
        "general_question": 1,
        "knowledge_search": 2,
        "enterprise_search": 3,
    }
    if intent_type in limits:
        return min(requested, limits[intent_type])
    # Cross-domain analysis and explicit business actions may require several
    # read/validate/synthesize steps; retain the caller's configured ceiling.
    return requested


def run_agent_conversation(messages, current_user, cfg,
                           lang="ko", on_status_update=None, max_turns=4, custom_ai_config=None,
                           intent=None, usage_context=None):
    """멀티턴 ReAct 에이전트 루프를 실행한다.
    
    Args:
        messages: 시스템 프롬프트 + 대화 히스토리 (OpenAI messages 배열)
        current_user: {"name": "...", "org": "..."}
        cfg: 서버 설정
        lang: 응답 언어 힌트
        on_status_update: 콜백 함수(status_text) — SSE로 도구 실행 상태 전송
        max_turns: 최대 반복 횟수
        custom_ai_config: (선택) 사용자가 직접 제공한 BYOK AI 설정
    
    Returns:
        str: AI의 최종 텍스트 답변
    """
    effective_cfg = dict(cfg)
    if custom_ai_config and isinstance(custom_ai_config, dict):
        # Override AI configuration with user-provided personal key (BYOK)
        # SSRF 방어: 일반 사용자가 제출한 임의의 baseUrl은 전면 차단하며, baseUrl은 시스템이 지정한 공식 엔드포인트만 사용
        from services.ai_client import PROVIDER_CONFIGS
        user_ai = dict(cfg.get("ai", {}))
        prov = custom_ai_config.get("provider") or user_ai.get("provider", "gemini")
        system_base_url = user_ai.get("base_url") or PROVIDER_CONFIGS.get(prov, {}).get("base_url", "")
        user_ai.update({
            "enabled": True,
            "provider": prov,
            "model": custom_ai_config.get("model") or user_ai.get("model", ""),
            "api_key": custom_ai_config.get("apiKey") or custom_ai_config.get("api_key") or user_ai.get("api_key", ""),
            "base_url": system_base_url
        })
        effective_cfg["ai"] = user_ai

    selected_tools = select_agent_tools(intent)
    max_turns = resolve_agent_max_turns(intent, max_turns)
    allowed_tool_names = {
        tool.get("function", {}).get("name") for tool in selected_tools
    }
    message_chars = sum(len(str(item.get("content") or "")) for item in messages if isinstance(item, dict))
    tool_schema_chars = len(json.dumps(selected_tools, ensure_ascii=False))
    log_line(
        "[Agent Prompt Metrics] "
        f"intent={(intent or {}).get('type', 'legacy')} "
        f"tool_count={len(selected_tools)} tool_schema_chars={tool_schema_chars} "
        f"message_count={len(messages)} message_chars={message_chars} max_turns={max_turns}"
    )
    if intent is not None and not selected_tools:
        max_turns = 1

    current_messages = list(messages)
    turn = 0
    
    while turn < max_turns:
        turn += 1
        turn_message_chars = sum(
            len(str(item.get("content") or ""))
            for item in current_messages
            if isinstance(item, dict)
        )
        log_line(
            "[Agent Turn Prompt Metrics] "
            f"turn={turn}/{max_turns} message_count={len(current_messages)} "
            f"message_chars={turn_message_chars} tool_schema_chars={tool_schema_chars}"
        )
        log_line(f"[Agent] Turn {turn}/{max_turns}")
        
        # 하드 블록 1단계: AI에게 오직 읽기 전용 도구(AGENT_READ_TOOLS)만 전달
        # 생성/수정/삭제 도구는 스키마 자체를 전달하지 않으므로 AI가 물리적으로 호출 불가능
        response = call_ai_chat_completions(
            cfg=effective_cfg,
            messages=current_messages,
            tools=selected_tools or None,
            tool_choice="auto" if selected_tools else None,
            max_tokens=2048,
            timeout=90,
            usage_context=usage_context
        )
        
        if not response:
            return "죄송합니다. AI 서비스에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요."
        
        choices = response.get("choices", [])
        if not choices:
            return "AI 응답을 처리할 수 없습니다."
        
        assistant_msg = choices[0].get("message", {})
        
        # Branch A: AI wants to call tools
        tool_calls = assistant_msg.get("tool_calls")
        if tool_calls:
            current_messages.append(assistant_msg)
            
            for tc in tool_calls:
                func = tc.get("function", {})
                tool_name = func.get("name", "")
                try:
                    tool_args = json.loads(func.get("arguments", "{}"))
                except (json.JSONDecodeError, TypeError):
                    tool_args = {}
                
                # Notify frontend about tool execution
                if on_status_update:
                    try:
                        on_status_update(tool_status_text(tool_name, lang))
                    except Exception:
                        pass
                
                log_line(f"[Agent] Tool call: {tool_name}({json.dumps(tool_args, ensure_ascii=False)[:100]})")
                
                if tool_name not in allowed_tool_names:
                    result = {"error": "This tool is not enabled for the current request."}
                else:
                    result = execute_tool(tool_name, tool_args, current_user, cfg)
                
                current_messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "content": json.dumps(result, ensure_ascii=False, default=str)
                })
            
            if intent is not None and intent.get("type") == "knowledge_search":
                post_note_table = POST_TOOL_NOTE_KNOWLEDGE
            elif intent is not None and not intent.get("requires_action"):
                post_note_table = POST_TOOL_NOTE_READ_ONLY
            else:
                post_note_table = POST_TOOL_NOTE
            post_note = post_note_table.get(lang) or post_note_table["ko"]
            current_messages.append({
                "role": "system",
                "content": post_note
            })
            
            continue  # Loop back for AI to synthesize
        
        # Branch B: AI returned final text
        content = assistant_msg.get("content") or ""
        return _append_document_sources(content, current_messages, lang)
    
    # Max turns exceeded — force final answer without tools
    log_line(f"[Agent] Max turns ({max_turns}) exceeded, forcing final answer")
    if intent is not None and intent.get("type") == "knowledge_search":
        force_table = FORCE_FINAL_KNOWLEDGE
    elif intent is not None and not intent.get("requires_action"):
        force_table = FORCE_FINAL_READ_ONLY
    else:
        force_table = FORCE_FINAL
    force_msg = force_table.get(lang) or force_table["ko"]
    current_messages.append({
        "role": "user",
        "content": force_msg
    })
    response = call_ai_chat_completions(
        cfg=effective_cfg,
        messages=current_messages,
        tools=None,
        max_tokens=2048,
        timeout=30,
        usage_context=usage_context
    )
    if response and response.get("choices"):
        content = response["choices"][0].get("message", {}).get("content", "")
        return _append_document_sources(content, current_messages, lang)
    return "죄송합니다. 응답을 생성하는 데 실패했습니다."
