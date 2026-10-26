#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""notification_service.py — ARGOS WORKS DB-Backed Notification Engine
Persists all notifications in the SQLite `notifications` table:
1. Task assignment & collaboration (배정 / 참여자 추가)
2. Comments & discussions (댓글 / 멘션)
3. Approaching due dates & overdue alerts (마감일 임박 / D-Day & 지연)
4. Status changes & workflow updates (상태 변경)
5. Jira synchronization results (Jira 동기화)
"""

import os
import time
import uuid
from datetime import datetime, timedelta
from db import query, execute
from utils.text import parse_iso_timestamp, assignee_base_name
import threading
import queue

# Bộ lắng nghe SSE thời gian thực cho Thông báo (Pub/Sub SSE Listeners)
# queue.Queue -> identity dict ({"email","name","is_admin"}) — mỗi subscriber chỉ
# nhận đúng thông báo của mình, không broadcast nội dung cho toàn bộ client.
_NOTIF_SUBSCRIBERS = {}
_NOTIF_LOCK = threading.Lock()


def _normalize_identity(identity):
    ident = identity or {}
    return {
        "email": (ident.get("email") or "").strip().lower(),
        "name": (ident.get("name") or "").strip(),
        "is_admin": bool(ident.get("is_admin")),
    }


def _name_is_unambiguous(name):
    """표시 이름이 시스템 내에서 유일한지 확인 (동명이인 알림 노출 방지, fail-closed)."""
    try:
        from services.auth import is_display_name_unique
        return is_display_name_unique(name)
    except Exception:
        return False


def notification_is_for_identity(identity, recipient_email, recipient_name):
    """SSE 실시간 이벤트 1건이 해당 구독자(사용자)에게 속하는지 판정한다."""
    ident = _normalize_identity(identity)
    r_email = (recipient_email or "").strip().lower()
    r_name = (recipient_name or "").strip()

    # 전체 공지 / 시스템 브로드캐스트
    if r_email == "all" or (r_email == "" and r_name in ("", "all")):
        return True
    if ident["email"] and r_email == ident["email"]:
        return True
    if ident["is_admin"] and r_name in ("관리자", "admin"):
        return True
    if not ident["name"]:
        return False
    if not _name_is_unambiguous(ident["name"]):
        return False
    base = assignee_base_name(ident["name"])
    return r_name == ident["name"] or bool(base and r_name == base)


def subscribe_notifications(q: queue.Queue, identity=None):
    with _NOTIF_LOCK:
        _NOTIF_SUBSCRIBERS[q] = _normalize_identity(identity)


def unsubscribe_notifications(q: queue.Queue):
    with _NOTIF_LOCK:
        _NOTIF_SUBSCRIBERS.pop(q, None)


def broadcast_notification_event(event_type: str, data: dict):
    data = data or {}
    with _NOTIF_LOCK:
        subscribers = list(_NOTIF_SUBSCRIBERS.items())

    dead = []
    for q, identity in subscribers:
        if not notification_is_for_identity(
            identity, data.get("recipient_email"), data.get("recipient_name")
        ):
            continue
        try:
            q.put_nowait({"type": event_type, "data": data})
        except Exception:
            dead.append(q)
    if dead:
        with _NOTIF_LOCK:
            for d in dead:
                _NOTIF_SUBSCRIBERS.pop(d, None)


def add_notification(
    recipient_email="",
    recipient_name="",
    sender_name="시스템",
    notif_type="assign",
    title="",
    content="",
    link_id="",
    tag="",
    tag_type="info",
    created_at=None
):
    """Insert a new notification record into the notifications table."""
    if not title or not content:
        return None

    notif_id = f"notif_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
    if not created_at:
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    execute(
        """INSERT INTO notifications (
            id, recipient_email, recipient_name, sender_name, type,
            title, content, link_id, tag, tag_type, is_read, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)""",
        (
            notif_id,
            (recipient_email or "").strip().lower(),
            (recipient_name or "").strip(),
            (sender_name or "시스템").strip(),
            (notif_type or "assign").strip(),
            title.strip(),
            content.strip(),
            str(link_id or ""),
            (tag or "").strip(),
            (tag_type or "info").strip(),
            created_at,
        )
    )

    # Asynchronously dispatch to Slack / Teams / Webhooks if configured
    try:
        from services.webhook_dispatcher import dispatch_notification_webhook
        dispatch_notification_webhook(
            title=title.strip(),
            content=content.strip(),
            sender=(sender_name or "시스템").strip(),
            link_id=str(link_id or ""),
            tag=(tag or "").strip()
        )
    except Exception:
        pass

    # Realtime SSE Broadcast to all connected clients
    try:
        broadcast_notification_event("new_notification", {
            "id": notif_id,
            "recipient_email": (recipient_email or "").strip().lower(),
            "recipient_name": (recipient_name or "").strip(),
            "title": title.strip(),
            "content": content.strip(),
            "type": notif_type
        })
    except Exception:
        pass

    return notif_id


def get_user_notifications(user_email=None, user_name=None, is_admin=False, limit=50):
    """Retrieve notifications for a specific user from the database.
    If the table is empty, backfills initial events so the user has immediate context.
    """
    clean_email = (user_email or "").strip().lower()
    clean_name = (user_name or "").strip()
    base_name = assignee_base_name(clean_name) if clean_name else ""

    # Check count in DB
    count_row = query("SELECT COUNT(*) as cnt FROM notifications")
    total_in_db = count_row[0]["cnt"] if count_row else 0

    if total_in_db == 0:
        backfill_initial_notifications()

    # Query notifications
    # Name-only matching is disabled when the display name is not unique, otherwise
    # two employees with the same name in different departments would see (and could
    # mark as read) each other's notifications.
    name_matching = bool(clean_name) and _name_is_unambiguous(clean_name)
    if clean_email or name_matching:
        where_clauses = [
            "recipient_email = 'all'",
            "(recipient_email = '' AND (recipient_name = '' OR recipient_name = 'all'))"
        ]
        params = []
        if clean_email:
            where_clauses.append("recipient_email = ?")
            params.append(clean_email)
        if name_matching:
            where_clauses.append("recipient_name = ?")
            params.append(clean_name)
        if name_matching and base_name and base_name != clean_name:
            where_clauses.append("recipient_name = ?")
            params.append(base_name)
        if is_admin:
            where_clauses.append("recipient_name = '관리자'")
            where_clauses.append("recipient_name = 'admin'")

        sql = f"""SELECT * FROM notifications
                  WHERE ({" OR ".join(where_clauses)})
                  ORDER BY created_at DESC LIMIT ?"""
        params.append(limit)
        rows = query(sql, tuple(params))
    else:
        # No email and no unambiguous name: only system/broadcast notifications
        rows = query(
            """SELECT * FROM notifications
               WHERE recipient_email = 'all' OR (recipient_email = '' AND (recipient_name = '' OR recipient_name = 'all'))
               ORDER BY created_at DESC LIMIT ?""",
            (limit,)
        )

    result = []
    for r in rows:
        # Safeguard: Never surface self-notifications to the user
        s_name = (r.get("sender_name") or "").strip()
        r_name = (r.get("recipient_name") or "").strip()
        if s_name and r_name and s_name not in ("시스템", "system") and _is_same_user(s_name, r_name):
            continue

        result.append({
            "id": r["id"],
            "type": r["type"],
            "category": "mention" if r["type"] == "assign" else r["type"],
            "title": r["title"],
            "desc": r["content"],
            "time": r["created_at"],
            "tag": r["tag"],
            "tag_type": r["tag_type"],
            "is_read": bool(r["is_read"]),
            "read_at": r["read_at"],
            "record_id": r["link_id"],
            "sender_name": r["sender_name"],
            "recipient_name": r["recipient_name"],
            "recipient_email": r["recipient_email"],
        })
    return result


def mark_notification_as_read(notif_id):
    """Mark a single notification as read in the database."""
    if not notif_id:
        return False
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    execute(
        "UPDATE notifications SET is_read = 1, read_at = ? WHERE id = ?",
        (now_str, notif_id)
    )
    return True


def mark_all_notifications_as_read(user_email=None, user_name=None, is_admin=False):
    """Mark all notifications as read for a given user."""
    clean_email = (user_email or "").strip().lower()
    clean_name = (user_name or "").strip()
    base_name = assignee_base_name(clean_name) if clean_name else ""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    name_matching = bool(clean_name) and _name_is_unambiguous(clean_name)
    if clean_email or name_matching:
        where_clauses = [
            "recipient_email = 'all'",
            "(recipient_email = '' AND (recipient_name = '' OR recipient_name = 'all'))"
        ]
        params = [now_str]
        if clean_email:
            where_clauses.append("recipient_email = ?")
            params.append(clean_email)
        if name_matching:
            where_clauses.append("recipient_name = ?")
            params.append(clean_name)
        if name_matching and base_name and base_name != clean_name:
            where_clauses.append("recipient_name = ?")
            params.append(base_name)
        if is_admin:
            where_clauses.append("recipient_name = '관리자'")
            where_clauses.append("recipient_name = 'admin'")

        sql = f"""UPDATE notifications 
                  SET is_read = 1, read_at = ? 
                  WHERE ({" OR ".join(where_clauses)}) AND is_read = 0"""
        execute(sql, tuple(params))
    else:
        # Never fall back to "mark everything read" — only system/broadcast rows.
        execute(
            """UPDATE notifications SET is_read = 1, read_at = ?
               WHERE is_read = 0
                 AND (recipient_email = 'all'
                      OR (recipient_email = '' AND (recipient_name = '' OR recipient_name = 'all')))""",
            (now_str,)
        )
    return True


# -------------------------------------------------------------
# Trigger Helpers: Called when events occur in the application
# -------------------------------------------------------------

def _is_same_user(user_a, user_b):
    """Check if two user identifiers (name or email) point to the same user."""
    if not user_a or not user_b:
        return False
    a = assignee_base_name(str(user_a)).strip().lower()
    b = assignee_base_name(str(user_b)).strip().lower()
    return bool(a and b and a == b)


def trigger_task_assigned_notification(record_id, title, author_name, assignee_name, assignee_email="", participants=""):
    """Trigger notifications when a card is created or assigned."""
    prefix = f"[{author_name}] " if author_name else ""
    
    # 1. Main Assignee - Do not notify if user assigns a task to themselves
    if assignee_name and assignee_name not in ("미배정", "Unassigned", "None", "-"):
        if not _is_same_user(author_name, assignee_name) and not _is_same_user(author_name, assignee_email):
            add_notification(
                recipient_email=assignee_email,
                recipient_name=assignee_name,
                sender_name=author_name or "시스템",
                notif_type="assign",
                title=f"새 업무가 배정되었습니다",
                content=f"{prefix}{title}",
                link_id=record_id,
                tag="배정",
                tag_type="info"
            )

    # 2. Participants - Do not notify if author adds themselves
    if participants:
        for p in participants.split(","):
            p_clean = p.strip()
            if p_clean and p_clean != assignee_name and p_clean != "없음":
                if not _is_same_user(author_name, p_clean):
                    add_notification(
                        recipient_email="",
                        recipient_name=p_clean,
                        sender_name=author_name or "시스템",
                        notif_type="assign",
                        title=f"공동 작업자로 참여 요청되었습니다",
                        content=f"{prefix}{title}",
                        link_id=record_id,
                        tag="참여",
                        tag_type="info"
                    )


def trigger_status_changed_notification(record_id, title, author_name, old_status, new_status, assignee_name="", assignee_email=""):
    """Trigger notification when a card changes status."""
    # Do not notify if the person changing the status is the assignee themselves
    if _is_same_user(author_name, assignee_name) or _is_same_user(author_name, assignee_email):
        return

    add_notification(
        recipient_email=assignee_email,
        recipient_name=assignee_name,
        sender_name=author_name or "시스템",
        notif_type="status",
        title=f"업무 상태가 변경되었습니다: {new_status}",
        content=f"{title} ({old_status} ➔ {new_status})",
        link_id=record_id,
        tag="상태",
        tag_type="done" if new_status in ("완료", "Done") else "info"
    )


def trigger_review_request_notification(local_rec, sender_session):
    """
    일반 사용자가 업무 카드를 '검토' 상태로 변경했을 때 부서 관리자(Manager) 및 시스템 관리자(Admin)에게 알림 전송.
    """
    if not local_rec:
        return
    try:
        from db import query
        rec_dept = (local_rec.get("dept_id") or local_rec.get("org") or "").strip()
        rec_title = local_rec.get("title") or local_rec.get("summary") or ""
        card_code = local_rec.get("cardCode") or local_rec.get("card_code") or f"#{local_rec.get('id')}"
        sender_name = (sender_session.get("name") if isinstance(sender_session, dict) else "") or "담당자"
        sender_email = (sender_session.get("email") if isinstance(sender_session, dict) else "").strip().lower()

        # Find all active admins and managers of this department
        managers_and_admins = query(
            """SELECT id, name, email, role, is_admin FROM users
               WHERE (disabled = 0 OR disabled IS NULL)
                 AND (status = 'active' OR status IS NULL)
                 AND (role = 'admin' OR is_admin = 1 OR (role = 'manager' AND LOWER(dept_id) = LOWER(?)))""",
            (rec_dept,)
        )

        notif_title = f"[검토 요청] {card_code} {rec_title}"
        notif_content = f"{sender_name}님이 '{rec_title}' 작업을 '검토' 상태로 변경하고 완료 승인을 요청했습니다."

        notified_emails = set()
        for target_user in (managers_and_admins or []):
            t_email = (target_user.get("email") or "").strip().lower()
            t_name = target_user.get("name") or target_user.get("username") or ""
            if t_email and t_email == sender_email:
                continue
            if t_email and t_email in notified_emails:
                continue
            if t_email:
                notified_emails.add(t_email)

            add_notification(
                recipient_email=t_email,
                recipient_name=t_name,
                sender_name=sender_name,
                notif_type="mention",
                title=notif_title,
                content=notif_content,
                link_id=str(card_code),
                tag="검토요청",
                tag_type="review"
            )
    except Exception as e:
        import sys
        print(f"[ReviewNotification] Error sending review notification: {e}", file=sys.stderr)


def trigger_comment_notification(record_id, title, author_name, comment_body, assignee_name="", assignee_email=""):
    """Trigger notification when someone leaves a comment."""
    # Do not notify if author of comment is the assignee themselves
    if _is_same_user(author_name, assignee_name) or _is_same_user(author_name, assignee_email):
        return

    add_notification(
        recipient_email=assignee_email,
        recipient_name=assignee_name,
        sender_name=author_name or "시스템",
        notif_type="comment",
        title=f"{author_name}님의 새 댓글",
        content=f"{title}: {comment_body}",
        link_id=record_id,
        tag="댓글",
        tag_type="info"
    )


def backfill_initial_notifications():
    """Populate initial notifications from existing records and activities so DB has immediate data."""
    today = datetime.now()
    today_str = today.strftime("%Y-%m-%d")

    # 1. Backfill from upcoming or overdue deadlines
    try:
        recs = query(
            """SELECT id, title, project, assignee_name, assignee_email, participants, due_date, status, created_at
               FROM records
               WHERE due_date IS NOT NULL AND due_date != ''
               ORDER BY due_date ASC LIMIT 30"""
        )
        for r in recs:
            due = str(r["due_date"]).strip()
            st = str(r["status"] or "").strip()
            if st in ("완료", "Done", "완료됨", "good"):
                continue

            rec_id = r["id"]
            title = r["title"] or "제목 없음"
            proj = r["project"] or ""
            p_prefix = f"[{proj}] " if proj else ""

            if due < today_str:
                add_notification(
                    recipient_email=r["assignee_email"],
                    recipient_name=r["assignee_name"],
                    sender_name="시스템 알림",
                    notif_type="deadline",
                    title="마감일 초과 (지연 업무)",
                    content=f"{p_prefix}{title} (마감일: {due})",
                    link_id=rec_id,
                    tag="지연",
                    tag_type="urgent",
                    created_at=due + " 18:00:00"
                )
            elif due == today_str:
                add_notification(
                    recipient_email=r["assignee_email"],
                    recipient_name=r["assignee_name"],
                    sender_name="시스템 알림",
                    notif_type="deadline",
                    title="오늘 마감 예정 (D-Day)",
                    content=f"{p_prefix}{title}",
                    link_id=rec_id,
                    tag="D-Day",
                    tag_type="urgent",
                    created_at=due + " 09:00:00"
                )
    except Exception as e:
        print(f"[Notification] Warning: Backfill deadline notifications failed: {e}", file=sys.stderr)

    # 2. Backfill recent activities
    try:
        acts = query(
            """SELECT id, issue_key, action_type, action_detail, author_name, author_email, summary, created_at
               FROM activities
               ORDER BY created_at DESC LIMIT 25"""
        )
        for act in acts:
            atype = act.get("action_type", "")
            detail = act.get("action_detail", "") or ""
            author = act.get("author_name", "") or "시스템"
            summary = act.get("summary", "") or "업무"
            created_at = act.get("created_at", "")
            rec_id = act.get("issue_key", "")

            if atype == "comment":
                add_notification(
                    recipient_email="",
                    recipient_name="",
                    sender_name=author,
                    notif_type="comment",
                    title=f"{author}님의 새 댓글",
                    content=f"{summary}: {detail}",
                    link_id=rec_id,
                    tag="댓글",
                    tag_type="info",
                    created_at=created_at
                )
            elif atype == "status_change":
                add_notification(
                    recipient_email="",
                    recipient_name="",
                    sender_name=author,
                    notif_type="status",
                    title="업무 상태 변경",
                    content=f"{summary} ({detail})",
                    link_id=rec_id,
                    tag="상태",
                    tag_type="info",
                    created_at=created_at
                )
            elif atype == "created":
                add_notification(
                    recipient_email="",
                    recipient_name="",
                    sender_name=author,
                    notif_type="assign",
                    title=f"새 업무 등록 ({author})",
                    content=summary,
                    link_id=rec_id,
                    tag="신규",
                    tag_type="info",
                    created_at=created_at
                )
            elif atype in ("jira_push", "jira_sync"):
                add_notification(
                    recipient_email="",
                    recipient_name="",
                    sender_name="Jira 연동",
                    notif_type="jira",
                    title="Jira 동기화 완료",
                    content=f"{summary} ({rec_id})",
                    link_id=rec_id,
                    tag="Jira",
                    tag_type="done",
                    created_at=created_at
                )
    except Exception as e:
        print(f"[Notification] Warning: Backfill activity notifications failed: {e}", file=sys.stderr)
