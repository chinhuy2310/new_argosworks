import json
from datetime import datetime
from services.auth import get_session
from services.data_store import read_schedule, write_schedule, _save_lock, next_record_id
from utils.logging import access_log
from config import SCHEDULE_DATE_RE
from services.auth import account_key


def _audit(session, ip, action, target_id, details=None):
    """Audit trail cho thay đổi lịch; không làm hỏng request nếu lỗi."""
    try:
        from services.audit_logger import log_audit
        log_audit(session, ip, action, "schedule", target_id, details=details)
    except Exception:
        pass


def _require_schedule_write(handler, session, ip, action_name):
    """
    Chặn viewer (read-only tuyệt đối) và chặn khi license hết hạn.
    Trả True nếu được phép ghi.
    """
    from services.auth import can_write_data
    from services.license_manager import is_system_read_only

    if is_system_read_only():
        handler._send_json(403, {"ok": False, "error": "라이선스가 만료되어 시스템이 읽기 전용(Read-Only) 상태입니다. 관리자에게 문의하세요."})
        return False
    if not can_write_data(session):
        access_log(ip, "forbidden_" + action_name, 403,
                   f"{session.get('name')}|{session.get('email')}")
        handler._send_json(403, {"ok": False,
                                 "error": "조회 전용(Viewer) 권한의 사용자는 일정을 생성/수정/삭제할 수 없습니다."})
        return False
    return True


# ---- /api/schedule (POST) — 새 일정 추가 ----
def handle_schedule_create(handler, raw_body, ip):
    session = handler._get_session_or_401()
    if session is None:
        return
    if not _require_schedule_write(handler, session, ip, "schedule_create"):
        return
    try:
        payload = json.loads(raw_body.decode("utf-8") or "{}")
    except Exception:
        handler._send_json(400, {"ok": False, "error": "잘못된 요청 본문"})
        return
    title = (payload.get("title") or "").strip()
    ev_type = (payload.get("type") or "").strip() or "기타"
    start_date = (payload.get("startDate") or "").strip()
    end_date = (payload.get("endDate") or "").strip() or start_date
    memo = (payload.get("memo") or "").strip()
    if not title:
        handler._send_json(400, {"ok": False, "error": "제목을 입력해주세요."})
        return
    if not SCHEDULE_DATE_RE.match(start_date) or not SCHEDULE_DATE_RE.match(end_date):
        handler._send_json(400, {"ok": False, "error": "날짜 형식이 올바르지 않습니다."})
        return
    if end_date < start_date:
        end_date = start_date
    
    raw_participants = payload.get("participants") or []
    participants = []
    # Always ensure owner is in participants list
    owner_entry = {
        "name": session["name"],
        "org": session["org"],
        "email": session.get("email", ""),
        "key": account_key(session["name"], session["org"]),
        "isOwner": True
    }
    participants.append(owner_entry)
    seen_keys = {owner_entry["key"]}

    if isinstance(raw_participants, list):
        for p in raw_participants:
            if isinstance(p, dict):
                p_name = (p.get("name") or "").strip()
                p_org = (p.get("org") or session["org"]).strip()
                p_key = p.get("key") or account_key(p_name, p_org)
                if p_name and p_key not in seen_keys:
                    seen_keys.add(p_key)
                    participants.append({
                        "name": p_name,
                        "org": p_org,
                        "email": (p.get("email") or "").strip(),
                        "key": p_key,
                        "isOwner": False
                    })

    # Tự động xác định trạng thái duyệt: 연차/반차/휴가/출장 -> pending, còn lại approved
    leave_types = ("연차", "반차", "오전반차", "오후반차", "출장", "경조사", "휴가", "leave", "vacation")
    is_leave = any(lt in ev_type.lower() for lt in leave_types)
    initial_status = "pending" if is_leave else "approved"

    event = {
        "id": next_record_id(),
        "ownerKey": account_key(session["name"], session["org"]),
        "ownerName": session["name"], "ownerOrg": session["org"],
        "ownerEmail": session.get("email", ""),
        "participants": participants,
        "type": ev_type[:20], "title": title[:80],
        "startDate": start_date, "endDate": end_date,
        "memo": memo[:500],
        "approval_status": initial_status,
        "approved_by": session["name"] if initial_status == "approved" else "",
        "approved_at": datetime.now().isoformat() if initial_status == "approved" else "",
        "reject_reason": "",
        "createdAt": datetime.now().isoformat()
    }
    with _save_lock:
        events = read_schedule()
        events.append(event)
        write_schedule(events)
    access_log(ip, "schedule_create", 200, "%s %s~%s" % (session["name"], start_date, end_date))
    _audit(session, ip, "SCHEDULE_CREATE", event["id"],
           {"type": ev_type, "startDate": start_date, "endDate": end_date})

    # Log to JARVIS activity store
    try:
        from services.activity_store import append_activity
        append_activity({
            "id": f"sched_{event['id']}",
            "issue_key": f"SCHED-{str(event['id'])[:6]}",
            "action_type": "schedule",
            "action_detail": f"schedule:{start_date} ~ {end_date}" if start_date != end_date else f"schedule:{start_date}",
            "author_name": session["name"],
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "summary": title,
            "status": "진행",
            "priority": "보통",
            "issue_type": ev_type,
            "assignee_name": session["name"],
            "assignee_dept": session["org"],
            "source": "jarvis_schedule"
        })
    except Exception:
        pass

    handler._send_json(200, {"ok": True, "event": event})

# ---- /api/schedule/update (POST) — 본인 일정만 수정 가능 ----
def handle_schedule_update(handler, raw_body, ip):
    session = handler._get_session_or_401()
    if session is None:
        return
    if not _require_schedule_write(handler, session, ip, "schedule_update"):
        return
    try:
        payload = json.loads(raw_body.decode("utf-8") or "{}")
    except Exception:
        handler._send_json(400, {"ok": False, "error": "잘못된 요청 본문"})
        return
    owner_key = account_key(session["name"], session["org"])
    event_id = payload.get("id")
    with _save_lock:
        events = read_schedule()
        target = next((e for e in events if str(e.get("id")) == str(event_id)), None)
        if not target:
            handler._send_json(404, {"ok": False, "error": "일정을 찾을 수 없습니다."})
            return
        role = session.get("role", "member")
        is_admin = bool(role == "admin" or session.get("is_admin") == 1)
        u_dept = (session.get("org") or session.get("dept_id") or "").strip().lower()
        t_dept = (target.get("ownerOrg") or "").strip().lower()
        is_owner = (target.get("ownerKey") == owner_key or target.get("ownerName") == session.get("name"))
        is_dept_manager = (role == "manager" and bool(u_dept and t_dept and u_dept == t_dept))

        if not (is_owner or is_admin or is_dept_manager):
            handler._send_json(403, {"ok": False, "error": "본인 또는 소속 부서의 일정만 수정할 수 있습니다."})
            return
        title = (payload.get("title") or "").strip()
        start_date = (payload.get("startDate") or "").strip()
        end_date = (payload.get("endDate") or "").strip() or start_date
        if not title:
            handler._send_json(400, {"ok": False, "error": "제목을 입력해주세요."})
            return
        if not SCHEDULE_DATE_RE.match(start_date) or not SCHEDULE_DATE_RE.match(end_date):
            handler._send_json(400, {"ok": False, "error": "날짜 형식이 올바르지 않습니다."})
            return
        if end_date < start_date:
            end_date = start_date
        target["type"] = ((payload.get("type") or "").strip() or "기타")[:20]
        target["title"] = title[:80]
        target["startDate"] = start_date
        target["endDate"] = end_date
        target["memo"] = (payload.get("memo") or "").strip()[:500]

        # Update participants if provided
        if "participants" in payload:
            raw_participants = payload.get("participants") or []
            participants = []
            owner_entry = {
                "name": session["name"],
                "org": session["org"],
                "email": session.get("email", ""),
                "key": account_key(session["name"], session["org"]),
                "isOwner": True
            }
            participants.append(owner_entry)
            seen_keys = {owner_entry["key"]}
            if isinstance(raw_participants, list):
                for p in raw_participants:
                    if isinstance(p, dict):
                        p_name = (p.get("name") or "").strip()
                        p_org = (p.get("org") or session["org"]).strip()
                        p_key = p.get("key") or account_key(p_name, p_org)
                        if p_name and p_key not in seen_keys:
                            seen_keys.add(p_key)
                            participants.append({
                                "name": p_name,
                                "org": p_org,
                                "email": (p.get("email") or "").strip(),
                                "key": p_key,
                                "isOwner": False
                            })
            target["participants"] = participants

        write_schedule(events)
    access_log(ip, "schedule_update", 200, str(event_id))
    _audit(session, ip, "SCHEDULE_UPDATE", event_id)
    handler._send_json(200, {"ok": True, "event": target})

# ---- /api/schedule/delete (POST) — 본인 일정만 삭제 가능 ----
def handle_schedule_delete(handler, raw_body, ip):
    session = handler._get_session_or_401()
    if session is None:
        return
    if not _require_schedule_write(handler, session, ip, "schedule_delete"):
        return
    try:
        payload = json.loads(raw_body.decode("utf-8") or "{}")
    except Exception:
        handler._send_json(400, {"ok": False, "error": "잘못된 요청 본문"})
        return
    owner_key = account_key(session["name"], session["org"])
    event_id = payload.get("id")
    with _save_lock:
        events = read_schedule()
        target = next((e for e in events if str(e.get("id")) == str(event_id)), None)
        if not target:
            handler._send_json(404, {"ok": False, "error": "일정을 찾을 수 없습니다."})
            return
        role = session.get("role", "member")
        is_admin = bool(role == "admin" or session.get("is_admin") == 1)
        u_dept = (session.get("org") or session.get("dept_id") or "").strip().lower()
        t_dept = (target.get("ownerOrg") or "").strip().lower()
        is_owner = (target.get("ownerKey") == owner_key or target.get("ownerName") == session.get("name"))
        is_dept_manager = (role == "manager" and bool(u_dept and t_dept and u_dept == t_dept))

        if not (is_owner or is_admin or is_dept_manager):
            handler._send_json(403, {"ok": False, "error": "본인 또는 소속 부서의 일정만 삭제할 수 있습니다."})
            return
        events = [e for e in events if str(e.get("id")) != str(event_id)]
        write_schedule(events)
    access_log(ip, "schedule_delete", 200, str(event_id))
    _audit(session, ip, "SCHEDULE_DELETE", event_id)
    handler._send_json(200, {"ok": True})

# ---- /api/schedule/approve (POST) — 휴가/일정 승인 또는 반려 (Manager/Admin 전용) ----
def handle_schedule_approve(handler, raw_body, ip):
    session = handler._get_session_or_401()
    if session is None:
        return
    if not _require_schedule_write(handler, session, ip, "schedule_approve"):
        return
    from services.auth import is_manager_or_admin
    if not is_manager_or_admin(session):
        handler._send_json(403, {"ok": False, "error": "부서장(Manager) 이상의 권한이 필요합니다."})
        return

    try:
        payload = json.loads(raw_body.decode("utf-8") or "{}")
    except Exception:
        handler._send_json(400, {"ok": False, "error": "잘못된 요청 본문"})
        return

    event_id = payload.get("id") or payload.get("eventId")
    action = (payload.get("action") or "approve").strip().lower()
    reason = (payload.get("reason") or "").strip()

    if action not in ("approve", "reject"):
        handler._send_json(400, {"ok": False, "error": "action은 'approve' 또는 'reject' 여야 합니다."})
        return

    with _save_lock:
        events = read_schedule()
        target = next((e for e in events if str(e.get("id")) == str(event_id)), None)
        if not target:
            handler._send_json(404, {"ok": False, "error": "해당 일정을 찾을 수 없습니다."})
            return

        # Manager는 자기 부서 인원의 일정만 승인/반려 가능 (Admin은 전체 가능)
        role = session.get("role", "member")
        u_dept = (session.get("org") or session.get("dept_id") or "").strip().lower()
        t_dept = (target.get("ownerOrg") or "").strip().lower()

        if role != "admin" and u_dept != t_dept:
            handler._send_json(403, {"ok": False, "error": "소속 부서 직원의 일정만 승인/반려할 수 있습니다."})
            return

        new_status = "approved" if action == "approve" else "rejected"
        target["approval_status"] = new_status
        target["approved_by"] = session.get("name", "관리자")
        target["approved_at"] = datetime.now().isoformat()
        target["reject_reason"] = reason if action == "reject" else ""

        write_schedule(events)

    # Gửi thông báo đến người xin nghỉ
    try:
        from services.notification_service import add_notification
        action_kr = "승인" if action == "approve" else "반려"
        notif_msg = f"[{target.get('title')}] 일정이 {session.get('name')}님에 의해 {action_kr}되었습니다."
        if reason and action == "reject":
            notif_msg += f" (사유: {reason})"
        add_notification(
            recipient_email=target.get("ownerEmail", ""),
            recipient_name=target.get("ownerName", ""),
            sender_name=session.get("name", "관리자"),
            notif_type="schedule_approval",
            title=f"일정 {action_kr} 알림",
            content=notif_msg,
            link_id=str(target.get("id")),
            tag=action_kr,
            tag_type="success" if action == "approve" else "danger"
        )
    except Exception:
        pass

    # Ghi audit log
    try:
        from services.audit_logger import log_audit
        log_audit(
            session_or_user=session,
            action="SCHEDULE_APPROVE" if action == "approve" else "SCHEDULE_REJECT",
            target_type="schedule",
            target_id=str(event_id),
            details={"title": target.get("title"), "owner": target.get("ownerName"), "reason": reason},
            ip=ip
        )
    except Exception:
        pass

    access_log(ip, f"schedule_{action}", 200, f"id={event_id} status={new_status}")
    _audit(session, ip, "SCHEDULE_" + action.upper(), event_id,
           {"status": new_status, "reason": reason})
    handler._send_json(200, {"ok": True, "event": target})

