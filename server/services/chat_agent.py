"""chat_agent.py — ReAct 멀티턴 에이전트 대화 루프

AI가 도구를 호출하면 실행 결과를 피드백하고,
최종 텍스트 답변이 나올 때까지 반복한다 (최대 max_turns회).
"""

import json
from utils.logging import log_line
from services.ai_client import call_ai_chat_completions
from services.chat_tools import AGENT_READ_TOOLS, execute_tool
from prompts import POST_TOOL_NOTE, FORCE_FINAL, tool_status_text


def run_agent_conversation(messages, current_user, cfg,
                           lang="ko", on_status_update=None, max_turns=4, custom_ai_config=None):
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
        from services.ai_client import _PROVIDER_DEFAULTS
        user_ai = dict(cfg.get("ai", {}))
        prov = custom_ai_config.get("provider") or user_ai.get("provider", "gemini")
        system_base_url = user_ai.get("base_url") or _PROVIDER_DEFAULTS.get(prov, {}).get("base_url", "")
        user_ai.update({
            "enabled": True,
            "provider": prov,
            "model": custom_ai_config.get("model") or user_ai.get("model", ""),
            "api_key": custom_ai_config.get("apiKey") or custom_ai_config.get("api_key") or user_ai.get("api_key", ""),
            "base_url": system_base_url
        })
        effective_cfg["ai"] = user_ai

    current_messages = list(messages)
    turn = 0
    
    while turn < max_turns:
        turn += 1
        log_line(f"[Agent] Turn {turn}/{max_turns}")
        
        # 하드 블록 1단계: AI에게 오직 읽기 전용 도구(AGENT_READ_TOOLS)만 전달
        # 생성/수정/삭제 도구는 스키마 자체를 전달하지 않으므로 AI가 물리적으로 호출 불가능
        response = call_ai_chat_completions(
            cfg=effective_cfg,
            messages=current_messages,
            tools=AGENT_READ_TOOLS,
            tool_choice="auto",
            max_tokens=2048,
            timeout=90
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
                
                result = execute_tool(tool_name, tool_args, current_user, cfg)
                
                current_messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "content": json.dumps(result, ensure_ascii=False, default=str)
                })
            
            post_note = POST_TOOL_NOTE.get(lang) or POST_TOOL_NOTE["ko"]
            current_messages.append({
                "role": "system",
                "content": post_note
            })
            
            continue  # Loop back for AI to synthesize
        
        # Branch B: AI returned final text
        content = assistant_msg.get("content") or ""
        return content
    
    # Max turns exceeded — force final answer without tools
    log_line(f"[Agent] Max turns ({max_turns}) exceeded, forcing final answer")
    force_msg = FORCE_FINAL.get(lang) or FORCE_FINAL["ko"]
    current_messages.append({
        "role": "user",
        "content": force_msg
    })
    response = call_ai_chat_completions(
        cfg=cfg,
        messages=current_messages,
        tools=None,
        max_tokens=2048,
        timeout=30
    )
    if response and response.get("choices"):
        return response["choices"][0].get("message", {}).get("content", "")
    return "죄송합니다. 응답을 생성하는 데 실패했습니다."
