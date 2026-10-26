#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""settings_handler.py — API 및 시스템 연동(AI, Voyage AI, Jira) 설정 관리 핸들러"""

import os
import json
import time
import urllib.request
import urllib.error
import base64
import re

from config import BASE_DIR
from utils.logging import access_log, log_line
from services.ai_client import get_ai_config, get_ai_fallback_config, get_provider_api_keys, _execute_ai_raw_single, call_ai_raw
from services.vector_store import (
    is_voyage_configured,
    get_vector_stats,
    call_voyage_embeddings,
    get_voyage_api_keys,
    get_embedding_provider_info,
    _execute_embedding_http
)
from services.auth import is_admin_user
from services.jira_client import _urlopen as jira_urlopen
from utils.crypto import encrypt_secret, decrypt_secret

ENV_PATH = os.path.join(BASE_DIR, ".env")

SENSITIVE_KEYS = ["AI_API_KEY", "AI_FALLBACK_API_KEY", "VOYAGE_API_KEY", "VOYAGE_API_KEYS", "JIRA_API_TOKEN", "ANTHROPIC_API_KEY"]


def _mask_value(key, val):
    if not val:
        return ""
    if key in SENSITIVE_KEYS:
        val_str = str(val).strip()
        if len(val_str) > 8:
            return val_str[:4] + "••••••••" + val_str[-4:]
        return "••••••••"
    return str(val)


def _read_env_dict():
    """Read .env file into key-value dict, decrypting sensitive values"""
    data = {}
    if os.path.isfile(ENV_PATH):
        try:
            with open(ENV_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, _, v = line.partition("=")
                        k_clean = k.strip()
                        v_clean = v.strip()
                        if k_clean in SENSITIVE_KEYS:
                            data[k_clean] = decrypt_secret(v_clean)
                        else:
                            data[k_clean] = v_clean
        except Exception as e:
            log_line(f"Failed to read .env: {e}")
    return data


def _resolve_submitted_secret(key_name, submitted_val, current_real_val):
    """
    사용자가 입력한 시크릿 값을 복원한다.
    마스킹된 값(••••)이 포함되어 있으면 기존 실제 키를 유지하고,
    새로운 값이 입력된 경우 새 값을 반영한다.
    """
    if not submitted_val:
        return ""
    val_str = str(submitted_val).strip()
    if "••••" in val_str or "****" in val_str:
        return current_real_val or ""
    return val_str


def _write_env_updates(updates):
    """Write updates to .env file preserving existing formatting/comments"""
    existing_lines = []
    env_dict = _read_env_dict()

    if os.path.isfile(ENV_PATH):
        try:
            with open(ENV_PATH, "r", encoding="utf-8") as f:
                existing_lines = f.readlines()
        except Exception as e:
            log_line(f"Failed to read .env for write: {e}")

    updated_keys = set()
    new_lines = []

    for line in existing_lines:
        trimmed = line.strip()
        if not trimmed or trimmed.startswith("#") or "=" not in trimmed:
            new_lines.append(line)
            continue
        k, _, _ = trimmed.partition("=")
        key = k.strip()
        if key in updates:
            raw_val = str(updates[key]).strip()
            # Resolve secrets if key is sensitive and contains masked placeholder
            if key in SENSITIVE_KEYS:
                current_real = env_dict.get(key, os.environ.get(key, ""))
                val = _resolve_submitted_secret(key, raw_val, current_real)
            else:
                val = raw_val

            if val or raw_val == "":
                save_val = encrypt_secret(val) if (key in SENSITIVE_KEYS and val) else val
                new_lines.append(f"{key}={save_val}\n")
                updated_keys.add(key)
                os.environ[key] = val
            else:
                new_lines.append(line)
                updated_keys.add(key)
        else:
            new_lines.append(line)
        continue

    # Append any brand new keys
    for k, v in updates.items():
        if k not in updated_keys:
            raw_val = str(v).strip()
            if k in SENSITIVE_KEYS:
                current_real = env_dict.get(k, os.environ.get(k, ""))
                val = _resolve_submitted_secret(k, raw_val, current_real)
            else:
                val = raw_val
            save_val = encrypt_secret(val) if (k in SENSITIVE_KEYS and val) else val
            new_lines.append(f"{k}={save_val}\n")
            os.environ[k] = val

    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.writelines(new_lines)



def _require_admin(handler, ip, action_name):
    """Verify session and ensure admin privileges. Returns session or None (sends error)."""
    session = handler._get_session_or_401()
    if session is None:
        return None
    if not is_admin_user(session):
        user_desc = f"{session.get('name')}|{session.get('email')}"
        access_log(ip, f"forbidden_{action_name}", 403, user_desc)
        handler._send_json(403, {
            "ok": False,
            "error": "관리자(Admin) 권한이 있는 사용자만 접근할 수 있습니다.",
            "forbidden": True
        })
        return None
    return session


def handle_get_settings(handler, parsed, ip):
    """GET /api/settings — 현재 API 연동 설정 및 상태 반환 (관리자 전용)"""
    session = _require_admin(handler, ip, "get_settings")
    if session is None:
        return

    cfg = handler.cfg
    env_data = _read_env_dict()

    ai = get_ai_config(cfg)
    ai_fb = get_ai_fallback_config(cfg)
    voyage_cfg = cfg.get("voyage", {})
    jira_cfg = cfg.get("jira", {})
    stats = get_vector_stats()

    # Masked config values for UI form
    settings = {
        # AI Primary
        "AI_ENABLED": env_data.get("AI_ENABLED", str(ai.get("enabled", False)).lower()),
        "AI_PROVIDER": env_data.get("AI_PROVIDER", ai.get("provider", "gemini")),
        "AI_API_KEY": _mask_value("AI_API_KEY", env_data.get("AI_API_KEY") or ai.get("api_key", "")),
        "AI_MODEL": env_data.get("AI_MODEL", ai.get("model", "gemini-2.5-flash")),
        "AI_BASE_URL": env_data.get("AI_BASE_URL", ai.get("base_url", "")),
        "AI_ALLOW_USER_KEYS": env_data.get("AI_ALLOW_USER_KEYS", str(ai.get("allow_user_keys", False)).lower()),

        # AI Fallback
        "AI_FALLBACK_ENABLED": env_data.get("AI_FALLBACK_ENABLED", str(ai_fb.get("enabled", False)).lower()),
        "AI_FALLBACK_PROVIDER": env_data.get("AI_FALLBACK_PROVIDER", ai_fb.get("provider", "openai")),
        "AI_FALLBACK_API_KEY": _mask_value("AI_FALLBACK_API_KEY", env_data.get("AI_FALLBACK_API_KEY") or ai_fb.get("api_key", "")),
        "AI_FALLBACK_MODEL": env_data.get("AI_FALLBACK_MODEL", ai_fb.get("model", "gpt-4o-mini")),
        "AI_FALLBACK_BASE_URL": env_data.get("AI_FALLBACK_BASE_URL", ai_fb.get("base_url", "")),

        # Voyage / Embedding Vector AI
        "VOYAGE_ENABLED": env_data.get("VOYAGE_ENABLED", str(voyage_cfg.get("enabled", False)).lower()),
        "VOYAGE_PROVIDER": env_data.get("VOYAGE_PROVIDER", voyage_cfg.get("provider", "voyage")),
        "VOYAGE_API_KEY": _mask_value("VOYAGE_API_KEY", env_data.get("VOYAGE_API_KEY") or voyage_cfg.get("api_key", "")),
        "VOYAGE_MODEL": env_data.get("VOYAGE_MODEL", voyage_cfg.get("model", "voyage-3-lite")),
        "VOYAGE_BASE_URL": env_data.get("VOYAGE_BASE_URL", voyage_cfg.get("base_url", "")),

        # Jira
        "JIRA_ENABLED": env_data.get("JIRA_ENABLED", str(jira_cfg.get("enabled", False)).lower()),
        "JIRA_BASE_URL": env_data.get("JIRA_BASE_URL", jira_cfg.get("base_url", "")),
        "JIRA_EMAIL": env_data.get("JIRA_EMAIL", jira_cfg.get("email", "")),
        "JIRA_API_TOKEN": _mask_value("JIRA_API_TOKEN", env_data.get("JIRA_API_TOKEN") or jira_cfg.get("api_token", "")),
        "JIRA_PROJECT_KEY": env_data.get("JIRA_PROJECT_KEY", jira_cfg.get("default_project_key", "")),
        "JIRA_PROJECT_MAP": jira_cfg.get("project_map", {}),

        "JIRA_USER_ALIASES": jira_cfg.get("user_aliases", {}),

        # Workspace Branding
        "WORKSPACE_NAME": env_data.get("WORKSPACE_NAME", cfg.get("workspace", {}).get("name", "JARVIS")),
        "WORKSPACE_TITLE": env_data.get("WORKSPACE_TITLE", cfg.get("workspace", {}).get("title", "")),
        "WORKSPACE_WELCOME_GREETING": env_data.get("WORKSPACE_WELCOME_GREETING", cfg.get("workspace", {}).get("welcome_greeting", "")),
        "WORKSPACE_WELCOME_SUBTITLE": env_data.get("WORKSPACE_WELCOME_SUBTITLE", cfg.get("workspace", {}).get("welcome_subtitle", "")),
        "WORKSPACE_LOGO_URL": env_data.get("WORKSPACE_LOGO_URL", cfg.get("workspace", {}).get("logo_url", "")),
        "WORKSPACE_FOOTER_TEXT": env_data.get("WORKSPACE_FOOTER_TEXT", cfg.get("workspace", {}).get("footer_text", "")),

        # Outgoing Webhooks (Slack, Teams, Generic)
        "SLACK_WEBHOOK_URL": env_data.get("SLACK_WEBHOOK_URL") or os.environ.get("SLACK_WEBHOOK_URL", ""),
        "TEAMS_WEBHOOK_URL": env_data.get("TEAMS_WEBHOOK_URL") or os.environ.get("TEAMS_WEBHOOK_URL", ""),
        "GENERIC_WEBHOOK_URL": env_data.get("GENERIC_WEBHOOK_URL") or os.environ.get("GENERIC_WEBHOOK_URL", "")
    }

    # Connection status summary
    ai_keys = get_provider_api_keys(ai.get("api_key", ""))
    voyage_keys = get_voyage_api_keys(cfg)
    v_info = get_embedding_provider_info(cfg)
    status = {
        "ai": {
            "enabled": bool(ai.get("enabled")),
            "provider": ai.get("provider"),
            "model": ai.get("model"),
            "has_key": bool(ai.get("api_key") or ai.get("provider") == "ollama"),
            "key_count": len(ai_keys),
            "fallback": {
                "enabled": bool(ai_fb.get("enabled")),
                "provider": ai_fb.get("provider"),
                "model": ai_fb.get("model"),
                "has_key": bool(ai_fb.get("api_key") or ai_fb.get("provider") == "ollama")
            }
        },
        "voyage": {
            "enabled": bool(voyage_cfg.get("enabled", True)),
            "provider": v_info.get("provider", "voyage"),
            "model": v_info.get("model", "voyage-3-lite"),
            "has_key": is_voyage_configured(cfg),
            "key_count": len(voyage_keys),
            "vector_count": stats.get("total_vectors", 0)
        },
        "jira": {
            "enabled": bool(jira_cfg.get("enabled", False)),
            "base_url": jira_cfg.get("base_url", ""),
            "has_key": bool(jira_cfg.get("api_token") and jira_cfg.get("email"))
        }
    }

    handler._send_json(200, {
        "ok": True,
        "settings": settings,
        "status": status,
        "vectorStats": stats
    })


def handle_post_settings(handler, raw_body, ip):
    """POST /api/settings — API 설정 저장 및 런타임 실시간 적용 (관리자 전용)"""
    session = _require_admin(handler, ip, "post_settings")
    if session is None:
        return

    try:
        body = json.loads(raw_body.decode("utf-8"))
    except Exception:
        handler._send_json(400, {"ok": False, "error": "잘못된 JSON 형식입니다."})
        return

    updates = body.get("settings", body)
    if not isinstance(updates, dict):
        handler._send_json(400, {"ok": False, "error": "설정 데이터는 객체 형태여야 합니다."})
        return

    cfg = handler.cfg

    # SSRF Protection: Validate admin-supplied URLs before saving
    from utils.ssrf import validate_external_url

    def _is_local_ai_endpoint(p):
        if not p or not isinstance(p, str):
            return False
        return p.strip().lower() in ("ollama", "custom", "vllm", "lmstudio", "local", "openai_compatible", "openai-compatible")

    ai_prov = updates.get("AI_PROVIDER") or cfg.get("ai", {}).get("provider") or ""
    ai_fb_prov = updates.get("AI_FALLBACK_PROVIDER") or cfg.get("ai", {}).get("fallback", {}).get("provider") or ""
    voyage_prov = updates.get("VOYAGE_PROVIDER") or cfg.get("voyage", {}).get("provider") or ""

    url_checks = [
        ("AI_BASE_URL", updates.get("AI_BASE_URL"), _is_local_ai_endpoint(ai_prov)),
        ("AI_FALLBACK_BASE_URL", updates.get("AI_FALLBACK_BASE_URL"), _is_local_ai_endpoint(ai_fb_prov)),
        ("VOYAGE_BASE_URL", updates.get("VOYAGE_BASE_URL"), _is_local_ai_endpoint(voyage_prov)),
        ("JIRA_BASE_URL", updates.get("JIRA_BASE_URL"), False),
        ("WORKSPACE_LOGO_URL", updates.get("WORKSPACE_LOGO_URL"), False),
        ("SLACK_WEBHOOK_URL", updates.get("SLACK_WEBHOOK_URL"), False),
        ("TEAMS_WEBHOOK_URL", updates.get("TEAMS_WEBHOOK_URL"), False),
        ("GENERIC_WEBHOOK_URL", updates.get("GENERIC_WEBHOOK_URL"), False),
    ]
    for key, val, allow_priv in url_checks:
        if val and isinstance(val, str) and val.strip():
            u = val.strip()
            try:
                validate_external_url(u, allow_private=allow_priv, require_https=(not allow_priv))
            except ValueError as ve:
                handler._send_json(400, {"ok": False, "error": f"{key} 검증 실패: {str(ve)}"})
                return

    # Update .env file
    _write_env_updates(updates)

    # Immediately sync with handler.cfg so restart is not strictly required

    # Sync AI cfg
    ai_cfg = cfg.setdefault("ai", {})
    if "AI_ENABLED" in updates:
        ai_cfg["enabled"] = str(updates["AI_ENABLED"]).lower() in ("true", "1", "yes")
    if "AI_PROVIDER" in updates:
        ai_cfg["provider"] = updates["AI_PROVIDER"]
    if "AI_MODEL" in updates:
        ai_cfg["model"] = updates["AI_MODEL"]
    if "AI_BASE_URL" in updates:
        ai_cfg["base_url"] = updates["AI_BASE_URL"]
    if "AI_ALLOW_USER_KEYS" in updates:
        ai_cfg["allow_user_keys"] = str(updates["AI_ALLOW_USER_KEYS"]).lower() in ("true", "1", "yes")
    if "AI_API_KEY" in updates:
        resolved_ai_key = _resolve_submitted_secret("AI_API_KEY", updates["AI_API_KEY"], ai_cfg.get("api_key", ""))
        if resolved_ai_key:
            ai_cfg["api_key"] = resolved_ai_key

    # Sync AI Fallback cfg
    fb_cfg = ai_cfg.setdefault("fallback", {})
    if "AI_FALLBACK_ENABLED" in updates:
        fb_cfg["enabled"] = str(updates["AI_FALLBACK_ENABLED"]).lower() in ("true", "1", "yes")
    if "AI_FALLBACK_PROVIDER" in updates:
        fb_cfg["provider"] = updates["AI_FALLBACK_PROVIDER"]
    if "AI_FALLBACK_MODEL" in updates:
        fb_cfg["model"] = updates["AI_FALLBACK_MODEL"]
    if "AI_FALLBACK_BASE_URL" in updates:
        fb_cfg["base_url"] = updates["AI_FALLBACK_BASE_URL"]
    if "AI_FALLBACK_API_KEY" in updates:
        resolved_fb_key = _resolve_submitted_secret("AI_FALLBACK_API_KEY", updates["AI_FALLBACK_API_KEY"], fb_cfg.get("api_key", ""))
        if resolved_fb_key:
            fb_cfg["api_key"] = resolved_fb_key

    # Sync Voyage cfg
    if "VOYAGE_ENABLED" in updates:
        cfg.setdefault("voyage", {})["enabled"] = str(updates["VOYAGE_ENABLED"]).lower() in ("true", "1", "yes")
    if "VOYAGE_PROVIDER" in updates:
        cfg.setdefault("voyage", {})["provider"] = updates["VOYAGE_PROVIDER"]
    if "VOYAGE_MODEL" in updates:
        cfg.setdefault("voyage", {})["model"] = updates["VOYAGE_MODEL"]
    if "VOYAGE_BASE_URL" in updates:
        cfg.setdefault("voyage", {})["base_url"] = updates["VOYAGE_BASE_URL"]
    if "VOYAGE_API_KEY" in updates:
        resolved_voyage_key = _resolve_submitted_secret("VOYAGE_API_KEY", updates["VOYAGE_API_KEY"], cfg.get("voyage", {}).get("api_key", ""))
        if resolved_voyage_key:
            cfg.setdefault("voyage", {})["api_key"] = resolved_voyage_key

    # Sync Jira cfg
    if "JIRA_ENABLED" in updates:
        cfg.setdefault("jira", {})["enabled"] = str(updates["JIRA_ENABLED"]).lower() in ("true", "1", "yes")
    if "JIRA_BASE_URL" in updates:
        cfg.setdefault("jira", {})["base_url"] = updates["JIRA_BASE_URL"]
    if "JIRA_EMAIL" in updates:
        cfg.setdefault("jira", {})["email"] = updates["JIRA_EMAIL"]
    if "JIRA_API_TOKEN" in updates:
        resolved_jira_token = _resolve_submitted_secret("JIRA_API_TOKEN", updates["JIRA_API_TOKEN"], cfg.get("jira", {}).get("api_token", ""))
        if resolved_jira_token:
            cfg.setdefault("jira", {})["api_token"] = resolved_jira_token
    if "JIRA_PROJECT_KEY" in updates:
        cfg.setdefault("jira", {})["default_project_key"] = updates["JIRA_PROJECT_KEY"]
    if "JIRA_PROJECT_MAP" in updates:
        raw_map = updates["JIRA_PROJECT_MAP"]
        if isinstance(raw_map, str):
            try:
                raw_map = json.loads(raw_map)
            except Exception:
                pass
        if isinstance(raw_map, dict):
            cfg.setdefault("jira", {})["project_map"] = raw_map

    # Bidirectional user aliases: {'<tên trong ARGOS>': '<tên/username/email trong Jira>'}

    if "JIRA_USER_ALIASES" in updates:

        raw_aliases = updates["JIRA_USER_ALIASES"]

        if isinstance(raw_aliases, str):

            try:

                raw_aliases = json.loads(raw_aliases) if raw_aliases.strip() else {}

            except Exception:

                raw_aliases = {}

        if isinstance(raw_aliases, dict):

            cleaned_aliases = {}

            for local_name, jira_ref in raw_aliases.items():

                if local_name and jira_ref:

                    cleaned_aliases[str(local_name).strip()] = str(jira_ref).strip()

            cfg.setdefault("jira", {})["user_aliases"] = cleaned_aliases


    # Sync Workspace Branding
    ws_cfg = cfg.setdefault("workspace", {})
    if "WORKSPACE_NAME" in updates:
        ws_cfg["name"] = updates["WORKSPACE_NAME"]
    if "WORKSPACE_TITLE" in updates:
        ws_cfg["title"] = updates["WORKSPACE_TITLE"]
    if "WORKSPACE_WELCOME_GREETING" in updates:
        ws_cfg["welcome_greeting"] = updates["WORKSPACE_WELCOME_GREETING"]
    if "WORKSPACE_WELCOME_SUBTITLE" in updates:
        ws_cfg["welcome_subtitle"] = updates["WORKSPACE_WELCOME_SUBTITLE"]
    if "WORKSPACE_LOGO_URL" in updates:
        ws_cfg["logo_url"] = updates["WORKSPACE_LOGO_URL"]
    if "WORKSPACE_FOOTER_TEXT" in updates:
        ws_cfg["footer_text"] = updates["WORKSPACE_FOOTER_TEXT"]

    # Sync Outgoing Webhook Environment
    if "SLACK_WEBHOOK_URL" in updates:
        val = str(updates["SLACK_WEBHOOK_URL"]).strip()
        os.environ["SLACK_WEBHOOK_URL"] = val
    if "TEAMS_WEBHOOK_URL" in updates:
        val = str(updates["TEAMS_WEBHOOK_URL"]).strip()
        os.environ["TEAMS_WEBHOOK_URL"] = val
    if "GENERIC_WEBHOOK_URL" in updates:
        val = str(updates["GENERIC_WEBHOOK_URL"]).strip()
        os.environ["GENERIC_WEBHOOK_URL"] = val

    # Persist non-sensitive structural configuration to config.json
    from config import CONFIG_PATH
    try:
        # Create safe clone of cfg for config.json (strip tokens so .env remains source of truth for secrets)
        safe_cfg = json.loads(json.dumps(cfg))
        safe_cfg.get("jira", {})["api_token"] = ""
        safe_cfg.get("ai", {})["api_key"] = ""
        safe_cfg.get("voyage", {})["api_key"] = ""
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(safe_cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log_line(f"Failed to persist config.json: {e}")

    # Config (Jira URL/token/aliases) just changed: drop the in-memory Jira cache.

    try:

        from services.jira_client import invalidate_jira_cache

        invalidate_jira_cache()

    except Exception:

        pass

    # If Jira is enabled, trigger background sync & vectorization
    if cfg.get("jira", {}).get("enabled"):
        try:
            import threading
            from services.jira_client import sync_jira_cache
            threading.Thread(target=sync_jira_cache, args=(cfg,), daemon=True).start()
        except Exception:
            pass
    elif is_voyage_configured(cfg):
        try:
            from services.vector_store import trigger_async_vector_sync
            trigger_async_vector_sync(cfg)
        except Exception:
            pass

    access_log(ip, "update_settings", 200, f"Updated {len(updates)} keys")
    handler._send_json(200, {
        "ok": True,
        "message": "API 및 시스템 설정이 성공적으로 저장되었습니다."
    })



def handle_post_settings_test(handler, raw_body, ip):
    """POST /api/settings/test — 각 API 연동 상태 즉시 진단 및 테스트 (관리자 전용)"""
    session = _require_admin(handler, ip, "test_settings")
    if session is None:
        return

    cfg = handler.cfg
    results = {}

    # 1. AI Connection Test (Every Primary Key individually + Fallback)
    ai_cfg = get_ai_config(cfg)
    t0 = time.time()
    primary_keys = get_provider_api_keys(ai_cfg.get("api_key"))

    if ai_cfg["enabled"] and (primary_keys or ai_cfg["provider"] in ("ollama", "custom")):
        if ai_cfg["provider"] == "custom" and (not ai_cfg.get("base_url") or not ai_cfg.get("model")):
            results["ai"] = {
                "ok": False,
                "error": "사용자 정의(Custom) 제공자는 Base URL과 모델명이 필수입니다."
            }
        else:
            valid_ai_keys = []
            invalid_ai_keys = []
            key_details = []
            best_latency = 0

            keys_to_test = primary_keys if primary_keys else [""]
            for idx, k in enumerate(keys_to_test):
                tk0 = time.time()
                res_k, err_code, err_detail = _execute_ai_raw_single(
                    ai_cfg, k, "Hello, respond with 'OK'", max_tokens=100, timeout=10
                )
                lat_k = int((time.time() - tk0) * 1000)
                masked = (k[:4] + "..." + k[-4:]) if len(k) > 8 else (k or ai_cfg["provider"])
                if res_k is not None:
                    valid_ai_keys.append(masked)
                    best_latency = lat_k
                    key_details.append({
                        "index": idx,
                        "masked": masked,
                        "ok": True,
                        "status": "valid",
                        "latency_ms": lat_k
                    })
                elif err_code == 429:
                    # 429는 키는 유효하지만 Rate Limit 상태
                    valid_ai_keys.append(f"{masked} (429 RateLimit 대기)")
                    best_latency = lat_k
                    key_details.append({
                        "index": idx,
                        "masked": masked,
                        "ok": True,
                        "status": "rate_limited",
                        "error": "429 Rate Limit 대기",
                        "latency_ms": lat_k
                    })
                else:
                    err_str = f"HTTP {err_code}" if err_code else (err_detail[:40] or "오류")
                    invalid_ai_keys.append(f"{masked} ({err_str})")
                    key_details.append({
                        "index": idx,
                        "masked": masked,
                        "ok": False,
                        "status": "invalid",
                        "error": err_str,
                        "latency_ms": lat_k
                    })

            if valid_ai_keys:
                results["ai"] = {
                    "ok": True,
                    "provider": ai_cfg["provider"],
                    "model": ai_cfg["model"],
                    "latency_ms": best_latency,
                    "message": f"주(Primary) {ai_cfg['provider'].upper()} 연결 성공 ({best_latency}ms)"
                }
            else:
                err_details = f" ({invalid_ai_keys[0]})" if invalid_ai_keys else ""
                results["ai"] = {
                    "ok": False,
                    "error": f"주(Primary) AI 인증 실패{err_details}. URL 또는 API Key를 확인해주세요."
                }
    else:
        results["ai"] = {"ok": False, "error": "AI가 비활성화되어 있거나 API 키가 설정되지 않았습니다."}

    # 1-1. Test Fallback AI if enabled
    ai_fb = get_ai_fallback_config(cfg)
    if ai_fb.get("enabled"):
        fb_keys = get_provider_api_keys(ai_fb.get("api_key"))
        if fb_keys or ai_fb.get("provider") in ("ollama", "custom"):
            if ai_fb.get("provider") == "custom" and (not ai_fb.get("base_url") or not ai_fb.get("model")):
                results["ai_fallback"] = {
                    "ok": False,
                    "error": "사용자 정의(Custom) 보조 제공자는 Base URL과 모델명이 필수입니다."
                }
            else:
                t_fb = time.time()
                fb_key = fb_keys[0] if fb_keys else ""
                res_fb, err_code, err_detail = _execute_ai_raw_single(
                    ai_fb, fb_key, "Hello, respond with 'OK'", max_tokens=100, timeout=12
                )
                lat_fb = int((time.time() - t_fb) * 1000)
                if res_fb is not None:
                    results["ai_fallback"] = {
                        "ok": True,
                        "provider": ai_fb["provider"],
                        "model": ai_fb["model"],
                        "latency_ms": lat_fb,
                        "message": f"보조(Fallback) {ai_fb['provider'].upper()} ({ai_fb['model']}) 연결 성공 ({lat_fb}ms)"
                    }
                elif err_code == 429:
                    results["ai_fallback"] = {
                        "ok": True,
                        "provider": ai_fb["provider"],
                        "model": ai_fb["model"],
                        "latency_ms": lat_fb,
                        "message": f"보조(Fallback) {ai_fb['provider'].upper()} 키 정상 (현재 429 Rate Limit 대기 상태)"
                    }
                else:
                    results["ai_fallback"] = {
                        "ok": False,
                        "error": f"보조(Fallback) AI 연결 실패 (오류: {err_code} {err_detail[:60]})"
                    }
        else:
            results["ai_fallback"] = {
                "ok": False,
                "error": "보조 AI가 활성화되었으나 API 키가 설정되지 않았습니다."
            }

    # 2. Vector Embedding Connection Test
    t0 = time.time()
    v_info = get_embedding_provider_info(cfg)
    prov_name = v_info["provider"].upper()
    keys = get_voyage_api_keys(cfg)
    is_local_voyage = v_info["provider"] in ("ollama", "custom", "local", "vllm", "lmstudio")
    if not keys and is_local_voyage:
        keys = ["local-key"]
    if keys:
        valid_keys = []
        invalid_keys = []
        voyage_key_details = []
        dim = 512
        model = v_info["model"]

        for idx, k in enumerate(keys):
            masked = (k[:4] + "..." + k[-4:]) if len(k) > 8 else "key"
            tk0 = time.time()
            embs, err_code, err_msg = _execute_embedding_http(
                v_info, k, ["ping"], input_type="query", timeout=10
            )
            lat_k = int((time.time() - tk0) * 1000)

            if embs is not None and len(embs) > 0 and len(embs[0]) > 0:
                valid_keys.append(k)
                dim = len(embs[0])
                voyage_key_details.append({
                    "index": idx,
                    "masked": masked,
                    "ok": True,
                    "status": "valid",
                    "latency_ms": lat_k
                })
            elif err_code == 429:
                valid_keys.append(k)
                voyage_key_details.append({
                    "index": idx,
                    "masked": masked,
                    "ok": True,
                    "status": "rate_limited",
                    "error": "429 Rate Limit 대기",
                    "latency_ms": lat_k
                })
            else:
                err_str = f"HTTP {err_code}" if err_code else (err_msg[:40] if err_msg else "오류")
                invalid_keys.append(f"{masked} ({err_str})")
                voyage_key_details.append({
                    "index": idx,
                    "masked": masked,
                    "ok": False,
                    "status": "invalid",
                    "error": err_str,
                    "latency_ms": lat_k
                })

        latency = int((time.time() - t0) * 1000)
        if valid_keys:
            results["voyage"] = {
                "ok": True,
                "provider": v_info["provider"],
                "model": model,
                "dim": dim,
                "latency_ms": latency,
                "message": f"AI 벡터 임베딩 연결 성공 ({dim}차원, {latency}ms)"
            }
        else:
            err_details = f" ({invalid_keys[0]})" if invalid_keys else ""
            if is_local_voyage:
                diag_msg = f"로컬/오프라인 AI 벡터 임베딩 연결 실패{err_details}. Base URL({v_info.get('base_url')}) 및 모델({model}) 상태를 확인해주세요."
            else:
                diag_msg = f"AI 벡터 임베딩 API 키 인증 실패{err_details}. 유효한 API Key인지 확인해주세요."
            results["voyage"] = {
                "ok": False,
                "provider": v_info["provider"],
                "model": model,
                "error": diag_msg
            }
    else:
        results["voyage"] = {"ok": False, "error": "AI 벡터 임베딩 API 키가 설정되지 않았습니다."}

    # 3. Jira Connection Test
    t0 = time.time()
    j_cfg = cfg.get("jira", {})
    j_base = (j_cfg.get("base_url") or "").rstrip("/")
    j_email = j_cfg.get("email") or ""
    j_token = j_cfg.get("api_token") or ""

    if j_base and j_email and j_token:
        try:
            auth_str = base64.b64encode(f"{j_email}:{j_token}".encode("utf-8")).decode("ascii")
            url = f"{j_base}/rest/api/2/serverInfo"
            req = urllib.request.Request(url, headers={
                "Authorization": f"Basic {auth_str}",
                "Accept": "application/json"
            })
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                latency = int((time.time() - t0) * 1000)
                server_title = data.get("serverTitle", "Atlassian Jira")
                results["jira"] = {
                    "ok": True,
                    "server": server_title,
                    "version": data.get("version", ""),
                    "latency_ms": latency,
                    "message": f"Jira 연결 성공 ({server_title}, {latency}ms)"
                }
                from services.jira_client import _jira_cache, _jira_cache_lock
                with _jira_cache_lock:
                    _jira_cache["error"] = None
        except urllib.error.HTTPError as e:
            err_msg = f"HTTP {e.code} 인증 실패 (이메일/토큰 확인 필요)"
            results["jira"] = {"ok": False, "error": err_msg}
            from services.jira_client import _jira_cache, _jira_cache_lock
            with _jira_cache_lock:
                _jira_cache["error"] = err_msg
        except Exception as e:
            err_msg = f"Jira 연결 실패: {str(e)}"
            results["jira"] = {"ok": False, "error": err_msg}
            from services.jira_client import _jira_cache, _jira_cache_lock
            with _jira_cache_lock:
                _jira_cache["error"] = err_msg
    else:
        results["jira"] = {"ok": False, "error": "Jira URL, 이메일, API 토큰을 모두 설정해주세요."}

    # 4. Outgoing Webhooks Connection Test
    env_data = _read_env_dict()
    slack_url = env_data.get("SLACK_WEBHOOK_URL") or os.environ.get("SLACK_WEBHOOK_URL", "")
    teams_url = env_data.get("TEAMS_WEBHOOK_URL") or os.environ.get("TEAMS_WEBHOOK_URL", "")
    generic_url = env_data.get("GENERIC_WEBHOOK_URL") or os.environ.get("GENERIC_WEBHOOK_URL", "")

    if slack_url or teams_url or generic_url:
        from services.webhook_dispatcher import _send_http_post, format_slack_payload, format_teams_payload
        webhook_res = {}
        if slack_url:
            t_s = time.time()
            payload = format_slack_payload("🔔 [ARGOS WORKS] Webhook 연결 테스트", "Slack 실시간 알림 연동이 성공적으로 설정되었습니다.", sender="ARGOS System", tag="연결확인")
            err = _send_http_post(slack_url, payload, timeout=6)
            lat = int((time.time() - t_s) * 1000)
            if err:
                webhook_res["slack"] = {"ok": False, "error": str(err)}
            else:
                webhook_res["slack"] = {"ok": True, "latency_ms": lat, "message": f"Slack 웹훅 전송 성공 ({lat}ms)"}

        if teams_url:
            t_t = time.time()
            payload = format_teams_payload("🔔 [ARGOS WORKS] Webhook 연결 테스트", "Teams 실시간 알림 연동이 성공적으로 설정되었습니다.", sender="ARGOS System", tag="연결확인")
            err = _send_http_post(teams_url, payload, timeout=6)
            lat = int((time.time() - t_t) * 1000)
            if err:
                webhook_res["teams"] = {"ok": False, "error": str(err)}
            else:
                webhook_res["teams"] = {"ok": True, "latency_ms": lat, "message": f"Teams 웹훅 전송 성공 ({lat}ms)"}

        if generic_url:
            t_g = time.time()
            payload = {
                "event": "test.ping",
                "message": "ARGOS WORKS Generic Webhook Test",
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
            }
            err = _send_http_post(generic_url, payload, timeout=6)
            lat = int((time.time() - t_g) * 1000)
            if err:
                webhook_res["generic"] = {"ok": False, "error": str(err)}
            else:
                webhook_res["generic"] = {"ok": True, "latency_ms": lat, "message": f"Generic 웹훅 전송 성공 ({lat}ms)"}

        results["webhooks"] = webhook_res
    else:
        results["webhooks"] = {"info": "설정된 웹훅 URL이 없습니다."}

    access_log(ip, "test_settings", 200)
    handler._send_json(200, {
        "ok": True,
        "results": results
    })


def handle_get_workspace_config(handler, parsed, ip):
    """GET /api/workspace-config — 퍼블릭 워크스페이스 브랜딩 설정 및 서비스 연동 상태 반환 (비로그인 상태 지원)"""
    ws = handler.cfg.get("workspace", {
        "name": "ARGOS WORKS",
        "title": "업무 인수인계 및 AI 협업 기록 시스템",
        "welcome_greeting": "ARGOS WORKS에 오신 것을 환영합니다",
        "welcome_subtitle": "연구 및 프로젝트 인수인계, 실시간 AI 질의응답 및 Jira 연동 시스템입니다.",
        "logo_url": "",
        "footer_text": "ARGOS WORKS System © 2026"
    })
    from services.jira_client import check_jira_connection_status
    jira_ready, jira_msg = check_jira_connection_status(handler.cfg)
    j_cfg = handler.cfg.get("jira", {})
    ai_cfg = handler.cfg.get("ai", {})
    handler._send_json(200, {
        "ok": True,
        "workspace": ws,
        "ai": {
            "enabled": bool(ai_cfg.get("enabled")),
            "provider": ai_cfg.get("provider", "gemini"),
            "model": ai_cfg.get("model", "gemini-3.5-flash-lite"),
            "allow_user_keys": bool(ai_cfg.get("allow_user_keys", False))
        },
        "jira": {
            "enabled": bool(j_cfg.get("enabled")),
            "connected": bool(jira_ready),
            "message": jira_msg
        }
    })


def handle_jira_inspect(handler, raw_body, ip):
    """POST /api/jira/inspect — Jira 연동 마법사: 연결 테스트 및 프로젝트, 이슈 타입, 워크플로 상태 자동 스캔"""
    session = _require_admin(handler, ip, "jira_inspect")
    if session is None:
        return

    try:
        body = json.loads(raw_body.decode("utf-8") or "{}")
    except Exception:
        body = {}

    cfg = handler.cfg
    j_cfg = cfg.get("jira", {})

    base_url = (body.get("base_url") or body.get("JIRA_BASE_URL") or j_cfg.get("base_url") or "").strip().rstrip("/")
    email = (body.get("email") or body.get("JIRA_EMAIL") or j_cfg.get("email") or "").strip()
    api_token = (body.get("api_token") or body.get("JIRA_API_TOKEN") or j_cfg.get("api_token") or "").strip()

    if "••••" in api_token or "****" in api_token:
        api_token = j_cfg.get("api_token") or ""

    if not base_url or not email or not api_token:
        handler._send_json(400, {
            "ok": False,
            "error": "Jira Base URL, 이메일, API 토큰을 모두 입력해주세요."
        })
        return

    auth_str = base64.b64encode(f"{email}:{api_token}".encode("utf-8")).decode("ascii")
    headers = {
        "Authorization": f"Basic {auth_str}",
        "Accept": "application/json"
    }

    t0 = time.time()
    try:
        # 1. Myself
        req_user = urllib.request.Request(f"{base_url}/rest/api/2/myself", headers=headers)
        with jira_urlopen(req_user, timeout=12, cfg=cfg) as resp:
            user_data = json.loads(resp.read().decode("utf-8"))

        # 2. Projects
        req_proj = urllib.request.Request(f"{base_url}/rest/api/2/project", headers=headers)
        with jira_urlopen(req_proj, timeout=12, cfg=cfg) as resp:
            proj_data = json.loads(resp.read().decode("utf-8"))

        # 3. Issue Types
        req_types = urllib.request.Request(f"{base_url}/rest/api/2/issuetype", headers=headers)
        with jira_urlopen(req_types, timeout=12, cfg=cfg) as resp:
            types_data = json.loads(resp.read().decode("utf-8"))

        # 4. Statuses
        statuses_data = []
        try:
            req_status = urllib.request.Request(f"{base_url}/rest/api/2/status", headers=headers)
            with jira_urlopen(req_status, timeout=12, cfg=cfg) as resp:
                statuses_data = json.loads(resp.read().decode("utf-8"))
        except Exception:
            pass

        latency = int((time.time() - t0) * 1000)

        projects = [
            {
                "id": str(p.get("id")),
                "key": p.get("key"),
                "name": p.get("name"),
                "projectTypeKey": p.get("projectTypeKey", "")
            }
            for p in proj_data if isinstance(p, dict)
        ]

        issue_types = [
            {
                "id": str(it.get("id")),
                "name": it.get("name"),
                "subtask": bool(it.get("subtask", False)),
                "description": it.get("description", "")
            }
            for it in types_data if isinstance(it, dict)
        ]

        statuses = [
            {
                "id": str(st.get("id")),
                "name": st.get("name"),
                "category": (st.get("statusCategory") or {}).get("name", "")
            }
            for st in statuses_data if isinstance(st, dict)
        ]

        access_log(ip, "jira_inspect", 200, f"Found {len(projects)} projs, {len(issue_types)} types")
        handler._send_json(200, {
            "ok": True,
            "latency_ms": latency,
            "user": {
                "displayName": user_data.get("displayName", ""),
                "emailAddress": user_data.get("emailAddress", email),
                "active": user_data.get("active", True)
            },
            "projects": projects,
            "issueTypes": issue_types,
            "statuses": statuses
        })

    except urllib.error.HTTPError as e:
        if e.code == 401:
            err_msg = "인증 실패 (401 Unauthorized): Jira 계정 이메일과 API Token을 다시 확인해주세요."
        elif e.code == 403:
            err_msg = "접근 권한 없음 (403 Forbidden): 입력하신 계정에 Jira API 접근 권한이 부족합니다."
        elif e.code == 404:
            err_msg = "URL 오류 (404 Not Found): 올바른 Jira Base URL(예: https://yourdomain.atlassian.net)인지 확인해주세요."
        else:
            err_msg = f"Jira API 호출 실패 (HTTP {e.code}): {e.reason}"
        access_log(ip, "jira_inspect", e.code, err_msg)
        handler._send_json(e.code, {"ok": False, "error": err_msg})
    except Exception as e:
        access_log(ip, "jira_inspect", 500, str(e))
        handler._send_json(500, {"ok": False, "error": f"Jira 연결 중 오류 발생: {str(e)}"})

