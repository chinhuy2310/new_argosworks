import json
import re
import time
from services.data_store import read_departments, write_departments, update_department, delete_department, _save_lock
from services.auth import is_admin_user
from utils.logging import access_log
from utils.http_body import parse_json_dict, as_text

def _require_system_admin(handler, ip, action_name):
    """Quản lý cơ cấu tổ chức (phòng ban) là quyền của System Admin."""
    session = handler._get_session_or_401()
    if session is None:
        return None
    if not is_admin_user(session):
        user_desc = f"{session.get('name')}|{session.get('email')}"
        access_log(ip, f"forbidden_{action_name}", 403, user_desc)
        handler._send_json(403, {
            "ok": False,
            "error": "관리자(Admin) 권한이 필요합니다.",
            "forbidden": True
        })
        return None
    return session

# ---- /api/departments (POST) ----
def handle_add_department(handler, raw_body, ip):
    session = _require_system_admin(handler, ip, "add_department")
    if session is None:
        return
    try:
        payload, body_err = parse_json_dict(raw_body)
        if body_err:
            handler._send_json(400, {"ok": False, "error": body_err})
            return
    except Exception:
        handler._send_json(400, {"ok": False, "error": "잘못된 요청 본문"})
        return

    name = as_text(payload.get("name"))
    local_prefix = as_text(payload.get("localPrefix") or payload.get("local_prefix")).upper()
    jira_key = as_text(payload.get("jiraKey") or payload.get("jira_key")).upper()
    custom_categories = as_text(payload.get("customCategories") or payload.get("custom_categories"))

    if not name:
        handler._send_json(400, {"ok": False, "error": "이름을 입력해주세요."})
        return

    with _save_lock:
        depts = read_departments()
        if any(d["name"].lower() == name.lower() for d in depts):
            handler._send_json(200, {"ok": True, "added": False, "departments": depts})
            return

        # Generate id based on local_prefix if valid ascii, else timestamp
        clean_prefix = re.sub(r'[^a-zA-Z0-9]', '', local_prefix).lower()
        if clean_prefix and not any(d["id"] == clean_prefix for d in depts):
            dept_id = clean_prefix
        else:
            dept_id = "dept_" + format(int(time.time() * 1000), "x")

        color_index = (len(depts) % 6) + 1
        depts.append({
            "id": dept_id,
            "name": name,
            "colorIndex": color_index,
            "localPrefix": local_prefix,
            "jiraKey": jira_key,
            "customCategories": custom_categories
        })
        write_departments(depts)

        # Automatically link in cfg.jira.project_map if jira_key is provided
        if jira_key and hasattr(handler, "cfg") and handler.cfg:
            try:
                handler.cfg.setdefault("jira", {}).setdefault("project_map", {})[dept_id] = {
                    "project_key": jira_key,
                    "issue_type": "Task"
                }
            except Exception:
                pass

    access_log(ip, "add_department", 200, f"{name} (prefix={local_prefix}, jira={jira_key})")
    handler._send_json(200, {"ok": True, "added": True, "departments": read_departments()})


# ---- /api/departments/delete (POST) ----
def handle_delete_department(handler, raw_body, ip):
    session = _require_system_admin(handler, ip, "delete_department")
    if session is None:
        return
    try:
        payload, body_err = parse_json_dict(raw_body)
        if body_err:
            handler._send_json(400, {"ok": False, "error": body_err})
            return
    except Exception:
        handler._send_json(400, {"ok": False, "error": "잘못된 요청 본문"})
        return

    dept_id = as_text(payload.get("id"))
    if not dept_id:
        handler._send_json(400, {"ok": False, "error": "부서 ID가 필요합니다."})
        return

    with _save_lock:
        departments = read_departments()
        if not any(str(d.get("id")) == dept_id for d in departments):
            handler._send_json(404, {"ok": False, "error": "부서를 찾을 수 없습니다."})
            return
        ok, err = delete_department(dept_id)
        if not ok:
            handler._send_json(400, {"ok": False, "error": err})
            return

    access_log(ip, "delete_department", 200, dept_id)
    handler._send_json(200, {"ok": True, "departments": read_departments()})


# ---- /api/departments/update (POST) ----
def handle_update_department(handler, raw_body, ip):
    session = _require_system_admin(handler, ip, "update_department")
    if session is None:
        return
    try:
        payload, body_err = parse_json_dict(raw_body)
        if body_err:
            handler._send_json(400, {"ok": False, "error": body_err})
            return
    except Exception:
        handler._send_json(400, {"ok": False, "error": "잘못된 요청 본문"})
        return

    dept_id = as_text(payload.get("id"))
    name = as_text(payload.get("name"))
    local_prefix = as_text(payload.get("localPrefix") or payload.get("local_prefix")).upper()
    jira_key = as_text(payload.get("jiraKey") or payload.get("jira_key")).upper()
    custom_categories = as_text(payload.get("customCategories") or payload.get("custom_categories"))

    if not dept_id:
        handler._send_json(400, {"ok": False, "error": "카테고리 ID가 필요합니다."})
        return
    if not name:
        handler._send_json(400, {"ok": False, "error": "카테고리 이름을 입력해주세요."})
        return

    with _save_lock:
        ok, err = update_department(dept_id, name, local_prefix, jira_key, custom_categories)
        if not ok:
            handler._send_json(400, {"ok": False, "error": err})
            return

        # Update jira project_map if configured
        if jira_key and hasattr(handler, "cfg") and handler.cfg:
            try:
                handler.cfg.setdefault("jira", {}).setdefault("project_map", {})[dept_id] = {
                    "project_key": jira_key,
                    "issue_type": "Task"
                }
            except Exception:
                pass

    access_log(ip, "update_department", 200, f"{dept_id}: {name} (prefix={local_prefix}, jira={jira_key})")
    handler._send_json(200, {"ok": True, "departments": read_departments()})
