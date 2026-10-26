"""chat_store.py — AI 채팅 세션·메시지 저장소 (SQLite 버전)
기존 chat_sessions.json + chat_history/*.jsonl 대신 SQLite DB를 사용한다.
모든 함수 시그니처와 반환 형식은 100% 유지된다.
"""
import json
import os
import threading
import time
import secrets

from db import query, get_one, execute, transaction

_msg_id_lock = threading.Lock()
_last_msg_id = 0


def list_sessions(user_name, user_org):
    """특정 사용자의 세션 목록을 최신순으로 정렬하여 반환한다."""
    rows = query(
        """SELECT id, user_name, user_dept_id, title, message_count, created_at, updated_at
           FROM chat_sessions
           WHERE user_name = ? AND user_dept_id = ?
           ORDER BY updated_at DESC""",
        (user_name, user_org)
    )
    # 기존 API 호환: user_org → user_org 키 유지
    return [
        {
            "id": r["id"],
            "user_name": r["user_name"],
            "user_org": r["user_dept_id"],
            "title": r["title"],
            "message_count": r["message_count"],
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
        }
        for r in rows
    ]


def create_session(user_name, user_org, title=None):
    """새로운 채팅 세션을 생성한다."""
    timestamp = int(time.time() * 1000)
    hex_str = secrets.token_hex(4)
    session_id = f"sess_{timestamp}_{hex_str}"
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())

    execute(
        """INSERT INTO chat_sessions(id, user_name, user_dept_id, title, message_count, created_at, updated_at)
           VALUES (?, ?, ?, ?, 0, ?, ?)""",
        (session_id, user_name, user_org, title or "새로운 대화", now_iso, now_iso)
    )

    return {
        "id": session_id,
        "user_name": user_name,
        "user_org": user_org,
        "title": title or "새로운 대화",
        "message_count": 0,
        "created_at": now_iso,
        "updated_at": now_iso,
    }


def get_session(session_id):
    """ID로 세션 정보를 조회한다."""
    r = get_one(
        "SELECT id, user_name, user_dept_id, title, message_count, created_at, updated_at FROM chat_sessions WHERE id = ?",
        (session_id,)
    )
    if not r:
        return None
    return {
        "id": r["id"],
        "user_name": r["user_name"],
        "user_org": r["user_dept_id"],
        "title": r["title"],
        "message_count": r["message_count"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
    }


def delete_session(session_id, user_name, user_dept_id=None):
    """
    세션과 관련된 모든 데이터를 삭제한다 (CASCADE로 messages도 삭제).

    user_dept_id 가 주어지면 (user_name, dept) 조합까지 일치해야 삭제한다.
    표시 이름은 부서가 다르면 중복될 수 있으므로, 이름만으로 소유권을 판정하면
    동명이인(타 부서)의 대화를 삭제할 수 있다.
    """
    if user_dept_id is None:
        r = get_one(
            "SELECT id FROM chat_sessions WHERE id = ? AND user_name = ?",
            (session_id, user_name)
        )
    else:
        r = get_one(
            "SELECT id FROM chat_sessions WHERE id = ? AND user_name = ? AND user_dept_id = ?",
            (session_id, user_name, user_dept_id)
        )
    if not r:
        return False
    execute("DELETE FROM chat_sessions WHERE id = ?", (session_id,))
    return True


def update_session_title(session_id, title):
    """세션의 제목을 업데이트한다."""
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    r = get_one("SELECT id FROM chat_sessions WHERE id = ?", (session_id,))
    if not r:
        return False
    execute(
        "UPDATE chat_sessions SET title = ?, updated_at = ? WHERE id = ?",
        (title, now_iso, session_id)
    )
    return True


def _next_msg_id():
    """순차적으로 증가하는 메시지 ID를 반환한다."""
    global _last_msg_id
    with _msg_id_lock:
        current_ms = int(time.time() * 1000)
        if current_ms <= _last_msg_id:
            _last_msg_id += 1
        else:
            _last_msg_id = current_ms
        return _last_msg_id


def append_message(session_id, role, content, author_name, metadata=None):
    """세션 기록에 새 메시지를 추가한다."""
    msg_id = _next_msg_id()
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())

    meta_json = json.dumps(metadata, ensure_ascii=False) if metadata else None

    execute(
        """INSERT INTO chat_messages(id, session_id, role, content, author_name, metadata, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (msg_id, session_id, role, content, author_name, meta_json, now_iso)
    )

    # 세션 메시지 카운트 및 업데이트 시간 갱신
    execute(
        "UPDATE chat_sessions SET message_count = message_count + 1, updated_at = ? WHERE id = ?",
        (now_iso, session_id)
    )

    return {
        "id": msg_id,
        "role": role,
        "content": content,
        "author_name": author_name,
        "metadata": metadata,
        "created_at": now_iso,
    }


def load_history(session_id, limit=20, before_id=None):
    """세션 기록을 읽어 지정된 개수만큼 반환한다."""
    if before_id is not None:
        rows = query(
            """SELECT id, role, content, author_name, metadata, created_at
               FROM chat_messages
               WHERE session_id = ? AND id < ?
               ORDER BY id DESC LIMIT ?""",
            (session_id, before_id, limit)
        )
    else:
        rows = query(
            """SELECT id, role, content, author_name, metadata, created_at
               FROM chat_messages
               WHERE session_id = ?
               ORDER BY id DESC LIMIT ?""",
            (session_id, limit)
        )

    # 역순으로 반환 (오래된 → 최신) — 기존 동작과 동일
    rows.reverse()

    result = []
    for r in rows:
        msg = {
            "id": r["id"],
            "role": r["role"],
            "content": r["content"],
            "author_name": r["author_name"],
            "metadata": json.loads(r["metadata"]) if r["metadata"] else None,
            "created_at": r["created_at"],
        }
        result.append(msg)
    return result


def update_proposal_status(session_id, status, message_id=None, summary=None, action_type=None, user_name=None, user_dept_id=None):
    """세션 기록 내 action_proposal 상태('cancelled' | 'executed')를 영구 저장한다.

    user_name이 주어지면 세션 소유자를 먼저 검증한다 (타 사용자 제안 상태 변조 방지).
    user_dept_id까지 주어지면 동명이인(타 부서) 세션은 fail-closed 로 거부한다.
    """
    if user_name:
        chat_sess = get_session(session_id)
        if not chat_sess:
            return False
        if chat_sess.get("user_name") != user_name:
            return False
        if user_dept_id is not None and (chat_sess.get("user_org") or "") != user_dept_id:
            return False
    # 메시지를 찾아서 metadata 업데이트
    if message_id:
        rows = query(
            "SELECT id, metadata FROM chat_messages WHERE session_id = ? AND id = ?",
            (session_id, int(message_id))
        )
    elif summary:
        rows = query(
            "SELECT id, metadata FROM chat_messages WHERE session_id = ? AND metadata IS NOT NULL ORDER BY id DESC",
            (session_id,)
        )
        # summary 매칭
        rows = [
            r for r in rows
            if json.loads(r["metadata"] or "{}").get("action_proposal", {}).get("summary") == summary
        ]
    else:
        rows = query(
            "SELECT id, metadata FROM chat_messages WHERE session_id = ? AND metadata IS NOT NULL ORDER BY id DESC",
            (session_id,)
        )
        rows = [
            r for r in rows
            if json.loads(r["metadata"] or "{}").get("action_proposal") is not None
        ]

    if not rows:
        return False

    updated = False
    for r in rows:
        meta = json.loads(r["metadata"] or "{}")
        prop = meta.get("action_proposal")
        if prop:
            prop["proposal_status"] = status
            prop["status"] = status
            meta["action_proposal"] = prop
            execute(
                "UPDATE chat_messages SET metadata = ? WHERE id = ?",
                (json.dumps(meta, ensure_ascii=False), r["id"])
            )
            updated = True

    return updated
