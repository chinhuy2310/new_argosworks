import time
import threading
from services.jira_client import sync_jira_cache
from utils.logging import access_log
from services.auth import is_manager_or_admin

_sync_rate_limits = {}
_sync_rate_lock = threading.Lock()

# ---- /api/sync (POST) — 대시보드의 "⟳ Jira 동기화" 버튼 ----
def handle_sync(handler, raw_body, ip):
    session = handler._get_session_or_401()
    if not session:
        return

    if not is_manager_or_admin(session):
        handler._send_json(403, {"ok": False, "error": "Jira 동기화는 부서 관리자(Manager) 또는 시스템 관리자(Admin)만 실행할 수 있습니다."})
        return

    # Dedicated Rate Limit: 1 per minute per user
    user_key = f"{session.get('id') or session.get('name')}:{ip}"
    now = time.time()
    with _sync_rate_lock:
        last_time = _sync_rate_limits.get(user_key, 0)
        if now - last_time < 60:
            remaining = int(60 - (now - last_time))
            handler._send_json(429, {"ok": False, "error": f"동기화 요청이 너무 빈번합니다. {remaining}초 후 다시 시도해주세요. (1분당 1회 제한)"})
            return
        _sync_rate_limits[user_key] = now

    j = handler.cfg.get("jira", {}) if handler.cfg else {}
    if not j.get("enabled"):
        access_log(ip, "sync", 400, "jira=disabled")
        handler._send_json(400, {"ok": False, "error": "Jira 연동이 비활성화되어 있습니다."})
        return

    force_full = False
    if raw_body:
        try:
            from utils.text import parse_json_dict
            b_data, _ = parse_json_dict(raw_body)
            if b_data and (b_data.get("full") or b_data.get("force_full")):
                force_full = True
        except Exception:
            pass

    cache = sync_jira_cache(handler.cfg, force_full=force_full)
    count = len(cache["records"] or [])
    try:
        from services.vector_store import trigger_async_vector_sync
        trigger_async_vector_sync(handler.cfg)
    except Exception:
        pass
    access_log(ip, "sync", 200, "jira=%d error=%s" % (count, cache["error"] or "-"))
    handler._send_json(200, {"ok": True, "syncedAt": cache["synced_at"], "count": count,
                           "error": cache["error"]})
