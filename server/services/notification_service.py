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
import sys
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
_BACKFILL_LOCK = threading.Lock()
_BACKFILL_DONE = False


def _normalize_identity(identity):
    ident = identity or {}
    return {
        "user_id": ident.get("user_id") or ident.get("id"),
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


def _name_base_is_unambiguous(name):
    """제목 접미사를 제거한 base 이름도 유일할 때만 fallback 매칭을 허용한다."""
    try:
        from services.auth import is_display_name_base_unique
        return is_display_name_base_unique(name)
    except Exception:
        return False


_SELF_NOTIFICATION_EXCLUSION_SQL = (
    "NOT ("
    "COALESCE(TRIM(n.recipient_email), '') = '' "
    "AND COALESCE(TRIM(n.sender_name), '') != '' "
    "AND COALESCE(TRIM(n.recipient_name), '') != '' "
    "AND LOWER(TRIM(n.recipient_name)) NOT IN ('관리자', 'admin') "
    "AND LOWER(TRIM(n.sender_name)) NOT IN ('시스템', 'system') "
    "AND LOWER(TRIM(n.sender_name)) = LOWER(TRIM(n.recipient_name))"
    ")"
)


def _resolve_recipient_user_id(recipient_email, recipient_name):
    """Resolve a notification recipient to a stable users.id when possible.

    Email is authoritative. Name-only resolution is allowed only when the name
    is unique and is not a role pseudo-name.
    """
    email = str(recipient_email or "").strip().lower()
    name = str(recipient_name or "").strip()
    if email and email != "all":
        row = query("SELECT id FROM users WHERE LOWER(email) = LOWER(?) LIMIT 1", (email,))
        if row:
            return row[0].get("id")
    if not name or name.lower() in ("", "all", "관리자", "admin"):
        return None
    rows = query("SELECT id FROM users WHERE LOWER(name) = LOWER(?)", (name,))
    if len(rows) == 1:
        return rows[0].get("id")
    return None


def notification_is_shared(recipient_email, recipient_name, recipient_user_id=None):
    """True for a broadcast/role row whose recipient is not a single user.

    Read state is still stored per user in notification_reads; this helper only
    keeps the legacy is_read column from being written for shared rows.
    """
    if recipient_user_id:
        return False
    r_email = (recipient_email or "").strip().lower()
    r_name = (recipient_name or "").strip().lower()
    return r_email == "all" or (not r_email and r_name in ("", "all", "관리자", "admin"))


def notification_is_for_identity(identity, recipient_email, recipient_name, recipient_user_id=None):
    """SSE 실시간 이벤트 1건이 해당 구독자(사용자)에게 속하는지 판정한다."""
    ident = _normalize_identity(identity)
    r_email = (recipient_email or "").strip().lower()
    r_name = (recipient_name or "").strip()

    # Stable user id is authoritative. If the event has one, do not fall back
    # to email/name when the subscriber has no matching id (fail closed).
    if recipient_user_id:
        return bool(ident["user_id"] and str(recipient_user_id) == str(ident["user_id"]))

    # 전체 공지 / 시스템 브로드캐스트
    if r_email == "all" or (r_email == "" and r_name in ("", "all")):
        return True
    # 이메일이 지정된 알림은 이메일로만 판정한다. (이름 fallback은 타 사용자
    # 알림 노출로 이어질 수 있음)
    if r_email:
        return bool(ident["email"] and r_email == ident["email"])
    if r_name.strip().lower() in ("관리자", "admin"):
        return bool(ident["is_admin"])
    if not ident["name"]:
        return False
    if not _name_is_unambiguous(ident["name"]):
        return False
    base = assignee_base_name(ident["name"])
    if r_name.lower() == ident["name"].lower():
        return True
    return bool(base and r_name.lower() == base.lower() and _name_base_is_unambiguous(ident["name"]))


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
            identity,
            data.get("recipient_email"),
            data.get("recipient_name"),
            data.get("recipient_user_id"),
        ):
            continue
        payload = {"type": event_type, "data": data}
        try:
            q.put_nowait(payload)
        except queue.Full:
            # A brief burst (e.g. backfill or a schedule fan-out) must not
            # permanently unsubscribe a live SSE client. Drop the oldest event;
            # the client re-fetches the authoritative list on the next event.
            try:
                q.get_nowait()
            except queue.Empty:
                pass
            try:
                q.put_nowait(payload)
            except Exception:
                dead.append(q)
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
    created_at=None,
    broadcast=False,
    notify_external=True,
    realtime=True,
    recipient_user_id=None,
):
    """Insert a new notification record into the notifications table.

    A notification with neither an email nor a name is *not* treated as a
    broadcast by default: callers must opt in with ``broadcast=True``. This
    prevents a missing assignee/recipient (e.g. an unassigned card comment)
    from leaking the content to every user.
    """
    clean_title = str(title or "").strip()
    clean_content = str(content or "").strip()
    if not clean_title or not clean_content:
        return None

    recipient_email = str(recipient_email or "").strip().lower()
    recipient_name = str(recipient_name or "").strip()
    if recipient_user_id is None:
        try:
            recipient_user_id = _resolve_recipient_user_id(recipient_email, recipient_name)
        except Exception:
            recipient_user_id = None
    else:
        try:
            recipient_user_id = int(recipient_user_id)
        except (TypeError, ValueError):
            recipient_user_id = None
    if not recipient_email and not recipient_name and not recipient_user_id and not broadcast:
        return None

    notif_id = f"notif_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
    if not created_at:
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    clean_sender = str(sender_name or "시스템").strip()
    clean_tag = str(tag or "").strip()
    clean_type = str(notif_type or "assign").strip()

    execute(
        """INSERT INTO notifications (
            id, recipient_email, recipient_name, recipient_user_id, sender_name, type,
            title, content, link_id, tag, tag_type, is_read, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)""",
        (
            notif_id,
            recipient_email,
            recipient_name,
            recipient_user_id,
            clean_sender,
            clean_type,
            clean_title,
            clean_content,
            str(link_id or ""),
            clean_tag,
            (tag_type or "info").strip(),
            created_at,
        )
    )

    # Asynchronously dispatch to Slack / Teams / Webhooks if configured
    if notify_external:
        try:
            from services.webhook_dispatcher import dispatch_notification_webhook
            dispatch_notification_webhook(
                title=clean_title,
                content=clean_content,
                sender=clean_sender,
                link_id=str(link_id or ""),
                tag=clean_tag
            )
        except Exception:
            pass

    # Realtime SSE Broadcast to all connected clients
    if realtime:
        try:
            broadcast_notification_event("new_notification", {
                "id": notif_id,
                "recipient_email": recipient_email,
                "recipient_name": recipient_name,
                "recipient_user_id": recipient_user_id,
                "title": clean_title,
                "content": clean_content,
                "type": clean_type,
                "tag": clean_tag,
                "tag_type": (tag_type or "info").strip(),
                "link_id": str(link_id or ""),
            })
        except Exception:
            pass

    return notif_id


def get_user_notifications(user_email=None, user_name=None, is_admin=False, limit=50, user_id=None, offset=0):
    """Retrieve notifications for a specific user from the database.

    Read state comes from notification_reads (per user, cross-device), with the
    legacy notifications.is_read fallback only for old direct rows.
    """
    clean_email = (user_email or "").strip().lower()
    clean_name = (user_name or "").strip()
    base_name = assignee_base_name(clean_name) if clean_name else ""
    try:
        limit = max(1, min(int(limit), 201))
    except (TypeError, ValueError):
        limit = 50
    try:
        offset = max(0, int(offset))
    except (TypeError, ValueError):
        offset = 0

    # Cheap emptiness check. COUNT(*) scanned the whole table on every fetch,
    # while all we need is "is there at least one row?".
    global _BACKFILL_DONE
    has_any = query("SELECT 1 FROM notifications LIMIT 1")

    if not has_any and not _BACKFILL_DONE:
        # Two first-page loads can both observe an empty table. Serialize the
        # check+backfill in this process so the initial rows are not inserted
        # twice. The flag also avoids re-scanning records on every poll when
        # there is nothing to backfill yet.
        with _BACKFILL_LOCK:
            if not _BACKFILL_DONE:
                _BACKFILL_DONE = True
                if not query("SELECT 1 FROM notifications LIMIT 1"):
                    backfill_initial_notifications()

    # Name-only matching is disabled when the display name is not unique.
    reserved_admin_name = clean_name.strip().lower() in ("관리자", "admin")
    name_matching = (
        bool(clean_name)
        and not reserved_admin_name
        and _name_is_unambiguous(clean_name)
    )

    # Rows created after this migration carry recipient_user_id. Legacy rows
    # (recipient_user_id IS NULL) still use email/name matching.
    legacy_prefix = "n.recipient_user_id IS NULL AND " if user_id else ""
    where_clauses = [
        "n.recipient_email = 'all'",
        "(n.recipient_email = '' AND (n.recipient_name = '' OR n.recipient_name = 'all'))",
    ]
    params = []
    if user_id:
        where_clauses.append("n.recipient_user_id = ?")
        params.append(user_id)
    if clean_email:
        where_clauses.append(f"({legacy_prefix}n.recipient_email = ?)")
        params.append(clean_email)
    if name_matching:
        where_clauses.append(
            f"({legacy_prefix}COALESCE(n.recipient_email, '') = '' AND LOWER(n.recipient_name) = LOWER(?))"
        )
        params.append(clean_name)
    if name_matching and base_name and base_name != clean_name and _name_base_is_unambiguous(clean_name):
        where_clauses.append(
            f"({legacy_prefix}COALESCE(n.recipient_email, '') = '' AND LOWER(n.recipient_name) = LOWER(?))"
        )
        params.append(base_name)
    if is_admin:
        where_clauses.append(
            "(n.recipient_user_id IS NULL AND COALESCE(n.recipient_email, '') = '' "
            "AND LOWER(n.recipient_name) IN ('관리자', 'admin'))"
        )

    join_user_id = user_id if user_id else -1
    if clean_email or name_matching or is_admin or user_id:
        sql = f"""SELECT n.*, nr.read_at AS user_read_at
                  FROM notifications n
                  LEFT JOIN notification_reads nr
                    ON nr.notification_id = n.id AND nr.user_id = ?
                  WHERE ({" OR ".join(where_clauses)})
                    AND {_SELF_NOTIFICATION_EXCLUSION_SQL}
                  ORDER BY n.created_at DESC, n.id DESC
                  LIMIT ? OFFSET ?"""
        rows = query(sql, tuple([join_user_id] + params + [limit, offset]))
    else:
        # No stable user id / email / unambiguous name: only broadcasts.
        rows = query(
            """SELECT n.*, nr.read_at AS user_read_at
               FROM notifications n
               LEFT JOIN notification_reads nr
                 ON nr.notification_id = n.id AND nr.user_id = ?
               WHERE n.recipient_email = 'all'
                  OR (n.recipient_email = '' AND (n.recipient_name = '' OR n.recipient_name = 'all'))
               ORDER BY n.created_at DESC, n.id DESC
               LIMIT ? OFFSET ?""",
            (join_user_id, limit, offset),
        )

    result = []
    for r in rows:
        # Safeguard: never surface a name-only self-notification. Do not apply
        # this to email-addressed rows: two different accounts may share the
        # same display name, and the email is authoritative for them.
        s_name = (r.get("sender_name") or "").strip()
        r_name = (r.get("recipient_name") or "").strip()
        r_email = (r.get("recipient_email") or "").strip().lower()
        if (not r_email and s_name and r_name
                and r_name.lower() not in ("관리자", "admin")
                and s_name.lower() not in ("시스템", "system")
                and _is_same_user(s_name, r_name)):
            continue

        read_at = r.get("user_read_at")
        if not read_at and user_id:
            # Legacy direct rows were backfilled into notification_reads; keep
            # this fallback for a partially migrated database.
            r_uid = r.get("recipient_user_id")
            if (r_uid is not None and str(r_uid) == str(user_id)
                    and bool(r.get("is_read"))):
                read_at = r.get("read_at") or r.get("created_at")
        if not user_id:
            read_at = r.get("read_at") if bool(r.get("is_read")) else None

        result.append({
            "id": r["id"],
            "type": r["type"],
            "category": "mention" if r["type"] == "assign" else r["type"],
            "title": r["title"],
            "desc": r["content"],
            "time": r["created_at"],
            "tag": r["tag"],
            "tag_type": r["tag_type"],
            "is_read": bool(read_at),
            "read_at": read_at,
            "record_id": r["link_id"],
            "sender_name": r["sender_name"],
            "recipient_name": r["recipient_name"],
            "recipient_email": r["recipient_email"],
            "recipient_user_id": r.get("recipient_user_id"),
        })
    return result


def count_unread_notifications(user_email=None, user_name=None, is_admin=False, user_id=None):
    """Count unread rows across the whole visible set, not just the first page."""
    clean_email = (user_email or "").strip().lower()
    clean_name = (user_name or "").strip()
    base_name = assignee_base_name(clean_name) if clean_name else ""
    reserved_admin_name = clean_name.strip().lower() in ("관리자", "admin")
    name_matching = (
        bool(clean_name)
        and not reserved_admin_name
        and _name_is_unambiguous(clean_name)
    )
    legacy_prefix = "n.recipient_user_id IS NULL AND " if user_id else ""
    where_clauses = [
        "n.recipient_email = 'all'",
        "(n.recipient_email = '' AND (n.recipient_name = '' OR n.recipient_name = 'all'))",
    ]
    params = []
    if user_id:
        where_clauses.append("n.recipient_user_id = ?")
        params.append(user_id)
    if clean_email:
        where_clauses.append(f"({legacy_prefix}n.recipient_email = ?)")
        params.append(clean_email)
    if name_matching:
        where_clauses.append(
            f"({legacy_prefix}COALESCE(n.recipient_email, '') = '' AND LOWER(n.recipient_name) = LOWER(?))"
        )
        params.append(clean_name)
    if name_matching and base_name and base_name != clean_name and _name_base_is_unambiguous(clean_name):
        where_clauses.append(
            f"({legacy_prefix}COALESCE(n.recipient_email, '') = '' AND LOWER(n.recipient_name) = LOWER(?))"
        )
        params.append(base_name)
    if is_admin:
        where_clauses.append(
            "(n.recipient_user_id IS NULL AND COALESCE(n.recipient_email, '') = '' "
            "AND LOWER(n.recipient_name) IN ('관리자', 'admin'))"
        )
    join_user_id = user_id if user_id else -1
    sql = f"""SELECT COUNT(*) AS cnt
                FROM notifications n
                LEFT JOIN notification_reads nr
                  ON nr.notification_id = n.id AND nr.user_id = ?
               WHERE ({" OR ".join(where_clauses)})
                 AND {_SELF_NOTIFICATION_EXCLUSION_SQL}
                 AND COALESCE(NULLIF(nr.read_at, ''), '') = ''"""
    rows = query(sql, tuple([join_user_id] + params))
    return int(rows[0]["cnt"]) if rows else 0


def mark_notification_as_read(notif_id, user_id=None):
    """Mark a single notification as read.

    With a user id the authoritative write goes to notification_reads, so the
    state is per-user and synchronizes across devices. The legacy is_read column
    is also updated for direct (non-shared) rows for backwards compatibility.
    """
    if not notif_id:
        return False
    row = query(
        """SELECT recipient_email, recipient_name, recipient_user_id
             FROM notifications WHERE id = ?""",
        (notif_id,)
    )
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if not row:
        return True
    row = row[0]
    shared = notification_is_shared(
        row.get("recipient_email"), row.get("recipient_name"), row.get("recipient_user_id")
    )
    if user_id:
        execute(
            """INSERT OR IGNORE INTO notification_reads
               (notification_id, user_id, read_at) VALUES (?, ?, ?)""",
            (notif_id, user_id, now_str)
        )
    if not shared:
        execute(
            "UPDATE notifications SET is_read = 1, read_at = ? WHERE id = ?",
            (now_str, notif_id)
        )
    return True


def mark_all_notifications_as_read(user_email=None, user_name=None, is_admin=False, user_id=None):
    """Mark all notifications visible to a user as read.

    Per-user rows go to notification_reads (including broadcasts/role rows), so
    one user clearing their badge cannot clear another user's. The legacy
    is_read column is updated only for direct rows.
    """
    clean_email = (user_email or "").strip().lower()
    clean_name = (user_name or "").strip()
    base_name = assignee_base_name(clean_name) if clean_name else ""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    reserved_admin_name = clean_name.strip().lower() in ("관리자", "admin")
    name_matching = (
        bool(clean_name)
        and not reserved_admin_name
        and _name_is_unambiguous(clean_name)
    )
    legacy_prefix = "n.recipient_user_id IS NULL AND " if user_id else ""

    # Rows visible to this user (same predicates as get_user_notifications).
    access_clauses = [
        "n.recipient_email = 'all'",
        "(n.recipient_email = '' AND (n.recipient_name = '' OR n.recipient_name = 'all'))",
    ]
    access_params = []
    if user_id:
        access_clauses.append("n.recipient_user_id = ?")
        access_params.append(user_id)
    if clean_email:
        access_clauses.append(f"({legacy_prefix}n.recipient_email = ?)")
        access_params.append(clean_email)
    if name_matching:
        access_clauses.append(
            f"({legacy_prefix}COALESCE(n.recipient_email, '') = '' AND LOWER(n.recipient_name) = LOWER(?))"
        )
        access_params.append(clean_name)
    if name_matching and base_name and base_name != clean_name and _name_base_is_unambiguous(clean_name):
        access_clauses.append(
            f"({legacy_prefix}COALESCE(n.recipient_email, '') = '' AND LOWER(n.recipient_name) = LOWER(?))"
        )
        access_params.append(base_name)
    if is_admin:
        access_clauses.append(
            "(n.recipient_user_id IS NULL AND COALESCE(n.recipient_email, '') = '' "
            "AND LOWER(n.recipient_name) IN ('관리자', 'admin'))"
        )

    if user_id:
        sql = f"""INSERT OR IGNORE INTO notification_reads
                  (notification_id, user_id, read_at)
                  SELECT n.id, ?, ?
                    FROM notifications n
                   WHERE ({" OR ".join(access_clauses)})
                     AND {_SELF_NOTIFICATION_EXCLUSION_SQL}"""
        execute(sql, tuple([user_id, now_str] + access_params))

    # Backwards-compatible legacy flag for direct rows only.
    direct_clauses = []
    direct_params = [now_str]
    if user_id:
        direct_clauses.append("recipient_user_id = ?")
        direct_params.append(user_id)
    if clean_email:
        direct_clauses.append("(recipient_user_id IS NULL AND recipient_email = ?)")
        direct_params.append(clean_email)
    if name_matching:
        direct_clauses.append(
            "(recipient_user_id IS NULL AND COALESCE(recipient_email, '') = '' "
            "AND LOWER(recipient_name) = LOWER(?))"
        )
        direct_params.append(clean_name)
    if name_matching and base_name and base_name != clean_name and _name_base_is_unambiguous(clean_name):
        direct_clauses.append(
            "(recipient_user_id IS NULL AND COALESCE(recipient_email, '') = '' "
            "AND LOWER(recipient_name) = LOWER(?))"
        )
        direct_params.append(base_name)

    if direct_clauses:
        sql = f"""UPDATE notifications
                  SET is_read = 1, read_at = ?
                  WHERE ({" OR ".join(direct_clauses)}) AND is_read = 0"""
        execute(sql, tuple(direct_params))
    return True


# -------------------------------------------------------------
# Trigger Helpers: Called when events occur in the application
# -------------------------------------------------------------

def _is_same_user(user_a, user_b):
    """Check if two user identifiers (name or email) point to the same user.

    Compare exact normalized identifiers. Stripping title suffixes here would
    treat two distinct accounts ("홍길동" and "홍길동 팀장") as one person and
    silently suppress a legitimate assignment notification.
    """
    if not user_a or not user_b:
        return False
    a = str(user_a).strip().lower()
    b = str(user_b).strip().lower()
    return bool(a and b and a == b)


def _same_person(author_name, author_email, recipient_name, recipient_email):
    """Whether an event author and its recipient are the same account.

    Email is authoritative when both sides have one: two accounts may share a
    display name, and comparing only names would suppress their notifications.
    """
    a_email = str(author_email or "").strip().lower()
    r_email = str(recipient_email or "").strip().lower()
    if a_email and r_email:
        return a_email == r_email
    return _is_same_user(author_name, recipient_name)


def trigger_task_assigned_notification(record_id, title, author_name, assignee_name, assignee_email="", participants="", author_email=""):
    """Trigger notifications when a card is created or assigned."""
    prefix = f"[{author_name}] " if author_name else ""

    # 1. Main Assignee - Do not notify if user assigns a task to themselves
    if assignee_name and assignee_name not in ("미배정", "Unassigned", "None", "-", "이름 미상"):
        if not _same_person(author_name, author_email, assignee_name, assignee_email):
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
                if not _same_person(author_name, author_email, p_clean, ""):
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


def trigger_participants_added_notification(record_id, title, author_name, added_names,
                                             assignee_name="", author_email=""):
    """Notify only participants newly added to an existing card."""
    prefix = f"[{author_name}] " if author_name else ""
    for p in (added_names or []):
        p_clean = str(p or "").strip()
        if not p_clean or p_clean == assignee_name or p_clean == "없음":
            continue
        if _same_person(author_name, author_email, p_clean, ""):
            continue
        add_notification(
            recipient_email="",
            recipient_name=p_clean,
            sender_name=author_name or "시스템",
            notif_type="assign",
            title="공동 작업자로 참여 요청되었습니다",
            content=f"{prefix}{title}",
            link_id=record_id,
            tag="참여",
            tag_type="info",
        )


def trigger_status_changed_notification(record_id, title, author_name, old_status, new_status, assignee_name="", assignee_email="", author_email=""):
    """Trigger notification when a card changes status."""
    # Do not notify if the person changing the status is the assignee themselves
    if _same_person(author_name, author_email, assignee_name, assignee_email):
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
        sender_email = (
            (sender_session.get("email") if isinstance(sender_session, dict) else "") or ""
        ).strip().lower()

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
        print(f"[ReviewNotification] Error sending review notification: {e}", file=sys.stderr)


def trigger_comment_notification(record_id, title, author_name, comment_body, assignee_name="", assignee_email="", author_email=""):
    """Trigger notification when someone leaves a comment."""
    # Do not notify if author of comment is the assignee themselves
    if _same_person(author_name, author_email, assignee_name, assignee_email):
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


def cleanup_old_notifications(days=None):
    """Delete notifications older than the configured retention window.

    Disabled by default (ARGOS_NOTIFICATION_RETENTION_DAYS=0). Explicit cleanup
    also removes the matching per-user read rows so no orphaned PII remains.
    """
    if days is None:
        try:
            days = int(os.environ.get("ARGOS_NOTIFICATION_RETENTION_DAYS", "0") or 0)
        except (TypeError, ValueError):
            days = 0
    try:
        days = int(days)
    except (TypeError, ValueError):
        days = 0
    if days <= 0:
        return 0
    days = min(days, 3650)
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    execute(
        """DELETE FROM notification_reads
            WHERE notification_id IN (
                SELECT id FROM notifications WHERE created_at < ?
            )""",
        (cutoff,)
    )
    execute("DELETE FROM notifications WHERE created_at < ?", (cutoff,))
    return 0


def _backfill_add(**kwargs):
    """Insert synthetic backfill rows without re-sending webhooks/SSE.

    Backfill runs on the first `/api/notifications` request and can create dozens
    of rows; dispatching each one to Slack/Teams (and broadcasting a burst of SSE
    events) would be both noisy and expensive.
    """
    kwargs.setdefault("notify_external", False)
    kwargs.setdefault("realtime", False)
    return add_notification(**kwargs)


def backfill_initial_notifications():
    """Populate targeted deadline/D-Day notifications for existing records.

    Activity backfill was deliberately removed: it created global broadcasts
    from comments/status changes of every record, leaking private card content
    to unrelated departments and users.
    """
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
                _backfill_add(
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
                _backfill_add(
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
