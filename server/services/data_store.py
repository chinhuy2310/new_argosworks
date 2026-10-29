"""data_store.py — JARVIS 데이터 저장소 (SQLite 버전)
기존 JSON 파일 대신 SQLite DB를 사용하며, 기존 함수 시그니처와 반환 형식을 100% 유지한다.
"""
import os
import json
import time
import threading
from datetime import datetime

from db import query, get_one, execute, transaction
from config import DEFAULT_DEPARTMENTS
from utils.logging import log_line

_id_lock = threading.Lock()
_save_lock = threading.Lock()
_last_record_id = 0
_last_product_id = 0


# ---------------------------------------------------------------------------
# Departments
# ---------------------------------------------------------------------------
def _clean_custom_cats(val):
    if not val:
        return ""
    s = str(val).strip()
    if s.startswith("[") and s.endswith("]"):
        try:
            parsed = json.loads(s)
            if isinstance(parsed, list):
                return ", ".join(str(x).strip().strip('"\'') for x in parsed if str(x).strip())
        except Exception:
            pass
    return s


def read_departments():
    """부서 목록을 반환한다."""
    rows = query("SELECT id, name, color_index, local_prefix, jira_key, custom_categories FROM departments ORDER BY rowid")
    if not rows and DEFAULT_DEPARTMENTS:
        # Seed default departments only if DEFAULT_DEPARTMENTS is non-empty
        for d in DEFAULT_DEPARTMENTS:
            execute(
                "INSERT OR IGNORE INTO departments(id, name, color_index, local_prefix, jira_key, custom_categories) VALUES (?, ?, ?, ?, ?, ?)",
                (d["id"], d["name"], d.get("colorIndex", 1), d.get("localPrefix", ""), d.get("jiraKey", ""), d.get("customCategories", ""))
            )
        rows = query("SELECT id, name, color_index, local_prefix, jira_key, custom_categories FROM departments ORDER BY rowid")
    return [{
        "id": r["id"],
        "name": r["name"],
        "colorIndex": r["color_index"],
        "localPrefix": r.get("local_prefix") or "",
        "jiraKey": r.get("jira_key") or "",
        "customCategories": _clean_custom_cats(r.get("custom_categories"))
    } for r in rows]


def write_departments(depts):
    """부서 목록을 전체 교체한다 (기존 API 호환)."""
    def _do(conn):
        cur = conn.cursor()
        existing_ids = {r["id"] for r in cur.execute("SELECT id FROM departments").fetchall()}
        new_ids = {d["id"] for d in depts}

        # 삭제 대상: 새 목록에 없는 기존 부서 (FK 참조 없는 경우만)
        for eid in existing_ids - new_ids:
            try:
                cur.execute("DELETE FROM departments WHERE id = ?", (eid,))
            except Exception:
                pass  # FK constraint — 참조되고 있으면 유지

        # UPSERT
        for d in depts:
            cur.execute(
                """INSERT INTO departments(id, name, color_index, local_prefix, jira_key, custom_categories) VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET name=excluded.name, color_index=excluded.color_index,
                   local_prefix=excluded.local_prefix, jira_key=excluded.jira_key, custom_categories=excluded.custom_categories""",
                (d["id"], d["name"], d.get("colorIndex", 1), d.get("localPrefix", ""), d.get("jiraKey", ""), d.get("customCategories", ""))
            )
    transaction(_do)


def update_department(dept_id, name, local_prefix="", jira_key="", custom_categories=""):
    """특정 부서/카테고리의 정보를 수정한다."""
    depts = read_departments()
    target = next((d for d in depts if d["id"] == dept_id), None)
    if not target:
        return False, "존재하지 않는 카테고리입니다."

    # 중복 이름 검사 (자기 자신 제외)
    if any(d["name"].lower() == name.lower() and d["id"] != dept_id for d in depts):
        return False, "이미 등록된 카테고리명입니다."

    execute(
        """UPDATE departments
           SET name = ?, local_prefix = ?, jira_key = ?, custom_categories = ?
           WHERE id = ?""",
        (name, local_prefix, jira_key, custom_categories, dept_id)
    )
    return True, ""


def delete_department(dept_id):
    """부서를 삭제한다. 레코드나 사용자가 참조하고 있으면 삭제 불가."""
    if not dept_id:
        return False, "부서 ID가 필요합니다."
    if not get_one("SELECT id FROM departments WHERE id = ?", (dept_id,)):
        return False, "부서를 찾을 수 없습니다."
    users = query("SELECT count(*) as c FROM users WHERE dept_id = ?", (dept_id,))
    recs = query("SELECT count(*) as c FROM records WHERE dept_id = ?", (dept_id,))
    user_cnt = users[0]["c"] if users else 0
    rec_cnt = recs[0]["c"] if recs else 0
    if user_cnt > 0 or rec_cnt > 0:
        return False, "부서에 등록된 사용자나 작업 기록이 있어 삭제할 수 없습니다."
    execute("DELETE FROM departments WHERE id = ?", (dept_id,))
    return True, ""


# ---------------------------------------------------------------------------
# Records (Work)
# ---------------------------------------------------------------------------
def read_records():
    """모든 작업 기록을 반환한다 (최신순 정렬). 기존 JSON 형식과 동일한 dict 반환."""
    rows = query(
        """SELECT r.*, rj.jira_key, rj.jira_status, rj.jira_url
           FROM records r
           LEFT JOIN record_jira rj ON r.id = rj.record_id
           ORDER BY r.work_date DESC, r.id DESC"""
    )
    result = []
    for r in rows:
        rec = {
            "id": r["id"],
            "dept_id": r["dept_id"],
            "org": r["dept_id"],
            "category": r["category"],
            "title": r["title"],
            "project": r["project"],
            "assignee": r["assignee_name"],
            "assignee_id": r.get("assignee_id"),
            "assigneeEmail": r["assignee_email"],
            "date": r["work_date"],
            "startDate": r.get("start_date") or r.get("work_date") or "",
            "dueDate": r.get("due_date") or r.get("work_date") or "",
            "endDate": r.get("due_date") or r.get("work_date") or "",
            "createdAt": r.get("created_at") or "",
            "summary": r["summary"],
            "tags": json.loads(r["tags"]) if r["tags"] else [],
            "memo": r["memo"],
            "status": r.get("status") or "진행",
            "priority": r.get("priority") or "보통",
            "cardCode": r.get("card_code") or (r.get("jira_key") or f"#{r['id']}"),
            "participants": r.get("participants") or "",
            "parentKey": r.get("parent_key") or "",
            "is_private": int(r.get("is_private") or 0),
            "is_scheduled": bool(r.get("is_scheduled", 1)),
            "version": int(r.get("version") or 1),
            "updatedAt": r.get("updated_at") or r.get("created_at") or "",
            "attachments": _get_record_attachments(r["id"]),
        }
        if r.get("jira_key"):
            rec["jira"] = {
                "key": r["jira_key"],
                "status": r.get("jira_status", ""),
                "url": r.get("jira_url", ""),
            }
        else:
            rec["jira"] = None
        result.append(rec)
    return result


def get_record_by_id(record_id):
    """특정 ID의 로컬 레코드를 단건 조회한다 (댓글 포함)."""
    rows = query(
        """SELECT r.*, rj.jira_key, rj.jira_status, rj.jira_url
           FROM records r
           LEFT JOIN record_jira rj ON r.id = rj.record_id
           WHERE r.id = ?""",
        (record_id,)
    )
    if not rows:
        return None
    r = rows[0]
    rec = {
        "id": r["id"],
        "dept_id": r["dept_id"],
        "org": r["dept_id"],
        "category": r["category"],
        "title": r["title"],
        "project": r["project"],
        "assignee": r["assignee_name"],
        "assignee_id": r.get("assignee_id"),
        "assigneeEmail": r["assignee_email"],
        "date": r["work_date"],
        "startDate": r.get("start_date") or r.get("work_date") or "",
        "dueDate": r.get("due_date") or r.get("work_date") or "",
        "endDate": r.get("due_date") or r.get("work_date") or "",
        "createdAt": r.get("created_at") or "",
        "summary": r["summary"],
        "tags": json.loads(r["tags"]) if r["tags"] else [],
        "memo": r["memo"],
        "status": r.get("status") or "진행",
        "priority": r.get("priority") or "보통",
        "cardCode": r.get("card_code") or (r.get("jira_key") or f"#{r['id']}"),
        "participants": r.get("participants") or "",
        "parentKey": r.get("parent_key") or "",
        "is_private": int(r.get("is_private") or 0),
        "is_scheduled": bool(r.get("is_scheduled", 1)),
        "version": int(r.get("version") or 1),
        "updatedAt": r.get("updated_at") or r.get("created_at") or "",
        "attachments": _get_record_attachments(r["id"]),
        "comments": get_record_comments(r["id"]),
    }
    if r.get("jira_key"):
        rec["jira"] = {
            "key": r["jira_key"],
            "status": r.get("jira_status", ""),
            "url": r.get("jira_url", ""),
        }
    else:
        rec["jira"] = None
    return rec


def find_record_by_key_or_code(key_or_code):
    """card_code, jira_key 또는 id로 로컬 레코드를 단건 조회한다."""
    if not key_or_code:
        return None
    raw = str(key_or_code).strip()
    clean = raw.upper().lstrip("#").replace("REC-", "").replace("LOCAL-", "").replace("JIRA-", "")
    if clean.isdigit():
        rec = get_record_by_id(int(clean))
        if rec:
            return rec

    rows = query(
        """SELECT r.*, rj.jira_key, rj.jira_status, rj.jira_url
           FROM records r
           LEFT JOIN record_jira rj ON r.id = rj.record_id
           WHERE UPPER(r.card_code) = ? OR UPPER(rj.jira_key) = ? OR UPPER(r.card_code) = ? OR UPPER(rj.jira_key) = ?
           ORDER BY r.id DESC
           LIMIT 1""",
        (raw.upper(), raw.upper(), clean, clean)
    )
    if not rows:
        # Fallback: check cached Jira issues in jira_issues table
        try:
            jira_row = get_one(
                "SELECT raw_json FROM jira_issues WHERE UPPER(jira_key) = ? OR UPPER(jira_key) = ? LIMIT 1",
                (raw.upper().replace("JIRA-", ""), clean)
            )
            if jira_row and jira_row.get("raw_json"):
                return json.loads(jira_row["raw_json"])
        except Exception as e:
            log_line("[data_store] Error loading cached Jira issue raw_json:", e)
        return None
    r = rows[0]
    rec = {
        "id": r["id"],
        "dept_id": r["dept_id"],
        "org": r["dept_id"],
        "category": r["category"],
        "title": r["title"],
        "project": r["project"],
        "assignee": r["assignee_name"],
        "assignee_id": r.get("assignee_id"),
        "assigneeEmail": r["assignee_email"],
        "date": r["work_date"],
        "startDate": r.get("start_date") or r.get("work_date") or "",
        "dueDate": r.get("due_date") or r.get("work_date") or "",
        "endDate": r.get("due_date") or r.get("work_date") or "",
        "createdAt": r.get("created_at") or "",
        "summary": r["summary"],
        "tags": json.loads(r["tags"]) if r["tags"] else [],
        "memo": r["memo"],
        "status": r.get("status") or "진행",
        "priority": r.get("priority") or "보통",
        "cardCode": r.get("card_code") or (r.get("jira_key") or f"#{r['id']}"),
        "participants": r.get("participants") or "",
        "parentKey": r.get("parent_key") or "",
        # NOTE: is_private MUST be present here as well. Every caller resolves a
        # card by code/key and then calls can_view_record(); a missing key makes
        # can_view_record treat a private card as public (RBAC bypass).
        "is_private": int(r.get("is_private") or 0),
        "is_scheduled": bool(r.get("is_scheduled", 1)),
        "version": int(r.get("version") or 1),
        "updatedAt": r.get("updated_at") or r.get("created_at") or "",
        "attachments": _get_record_attachments(r["id"]),
        "comments": get_record_comments(r["id"]),
    }
    if r.get("jira_key"):
        rec["jira"] = {
            "key": r["jira_key"],
            "status": r.get("jira_status", ""),
            "url": r.get("jira_url", ""),
        }
    else:
        rec["jira"] = None
    return rec


def get_record_hierarchy_chain(record_or_id):
    """최상위 루트부터 현재 레코드까지의 전체 계층 경로 리스트를 반환한다: [Root, ..., Parent, Current]"""
    if isinstance(record_or_id, (int, str)):
        rec = find_record_by_key_or_code(record_or_id)
    else:
        rec = record_or_id
    if not rec:
        return []

    chain = [rec]
    visited = {str(rec.get("id")), str(rec.get("cardCode", "")).upper()}
    current = rec
    for _ in range(25):
        p_key = (current.get("parentKey") or current.get("parent_key") or "").strip()
        if not p_key:
            break
        p_rec = find_record_by_key_or_code(p_key)
        if not p_rec:
            # parent_key가 Jira 직결 키이거나 외부 키인 경우
            chain.insert(0, {
                "id": None,
                "cardCode": p_key,
                "title": f"Jira 이슈 ({p_key})",
                "jira": {"key": p_key, "status": "", "url": ""},
                "isExternalJira": True
            })
            break
        p_id_str = str(p_rec.get("id"))
        if p_id_str in visited:
            break
        visited.add(p_id_str)
        if p_rec.get("cardCode"):
            visited.add(str(p_rec["cardCode"]).upper())
        chain.insert(0, p_rec)
        current = p_rec

    return chain


def update_record_status(record_id, status):
    """로컬 레코드의 상태를 업데이트한다."""
    execute("UPDATE records SET status = ? WHERE id = ?", (status, record_id))


def add_record_comment(record_id, author_name, body):
    """로컬 레코드에 댓글을 추가한다."""
    execute(
        "INSERT INTO record_comments(record_id, author_name, body) VALUES (?, ?, ?)",
        (record_id, author_name, body)
    )


def get_record_comments(record_id):
    """로컬 레코드의 댓글 목록을 반환한다."""
    rows = query(
        "SELECT id, author_name AS author, body, created_at AS created, 'local' AS source FROM record_comments WHERE record_id = ? ORDER BY id ASC",
        (record_id,)
    )
    return rows or []


def add_record_attachment(record_id, filename, file_size=0):
    """로컬 레코드에 첨부파일을 추가한다."""
    execute(
        "INSERT INTO record_attachments(record_id, filename, file_size) VALUES (?, ?, ?)",
        (record_id, filename, file_size)
    )


def _get_record_attachments(record_id):
    """레코드의 첨부파일 목록을 상세 객체 리스트로 반환한다."""
    import urllib.parse
    rows = query(
        "SELECT id, filename, file_size, uploaded_at FROM record_attachments WHERE record_id = ? ORDER BY id",
        (record_id,)
    )
    return [
        {
            "id": r["id"],
            "filename": r["filename"],
            "name": r["filename"],
            "size": r.get("file_size") or 0,
            "url": f"/api/attachments/{record_id}/{urllib.parse.quote(r['filename'])}",
            "isLocal": True,
            "source": "local",
            "uploadedAt": r.get("uploaded_at") or ""
        }
        for r in rows
    ]


def delete_record_attachment(record_id, attachment_id):
    """레코드의 첨부파일을 DB 및 디스크에서 삭제한다."""
    rows = query(
        "SELECT filename FROM record_attachments WHERE id = ? AND record_id = ?",
        (attachment_id, record_id)
    )
    if not rows:
        return False, "첨부파일을 찾을 수 없습니다."
    fname = rows[0]["filename"]
    execute(
        "DELETE FROM record_attachments WHERE id = ? AND record_id = ?",
        (attachment_id, record_id)
    )
    from config import ATTACH_DIR
    from utils.file_ops import safe_join
    from utils.logging import log_line

    rec_dir = safe_join(ATTACH_DIR, str(record_id))
    fpath = safe_join(rec_dir, fname) if rec_dir else None
    if not fpath:
        log_line(f"[Attachment] Invalid attachment path or traversal attempt: record_id={record_id}, fname={fname}")
    elif os.path.isfile(fpath):
        try:
            os.remove(fpath)
        except OSError as e:
            log_line(f"[Attachment] Failed to remove file from disk ({fpath}): {e}")
    return True, None


def append_record(record):
    """새 작업 기록을 추가한다. record는 기존 JSON 형식의 dict."""
    rec_id = record.get("id")
    tags_json = json.dumps(record.get("tags", []), ensure_ascii=False)
    status = record.get("status") or "진행"
    card_code = record.get("cardCode") or ""
    participants = record.get("participants") or ""
    parent_key = record.get("parentKey") or ""

    start_date = (record.get("startDate") or record.get("start_date") or record.get("date") or "").strip()
    due_date = (record.get("dueDate") or record.get("due_date") or record.get("endDate") or record.get("end_date") or start_date or "").strip()
    work_date = record.get("work_date") or record.get("date") or ""
    if start_date and due_date and start_date != due_date:
        work_date = f"{start_date} ~ {due_date}"
    elif start_date:
        work_date = start_date

    is_sched = 1 if record.get("is_scheduled", True) else 0

    priority = (record.get("priority") or "보통").strip()
    if priority not in ("낮음", "보통", "높음", "긴급"):
        priority = "보통"

    is_private_val = 1 if record.get("is_private") else 0
    dept_val = str(record.get("dept_id") or record.get("org") or "").strip()
    assignee_name = str(record.get("assignee") or record.get("assignee_name") or "").strip()
    assignee_email = str(record.get("assigneeEmail") or record.get("assignee_email") or "").strip()
    assignee_id = record.get("assignee_id")
    if not assignee_id and assignee_name:
        try:
            u_row = get_one("SELECT id, email FROM users WHERE (name = ? OR username = ?) AND dept_id = ? LIMIT 1", (assignee_name, assignee_name, dept_val))
            if u_row:
                assignee_id = u_row["id"]
                if not assignee_email and u_row.get("email"):
                    assignee_email = u_row["email"]
            else:
                from utils.logging import log_line
                candidates = query("SELECT id, email FROM users WHERE name = ? OR username = ? LIMIT 2", (assignee_name, assignee_name))
                if len(candidates) == 1:
                    assignee_id = candidates[0]["id"]
                    if not assignee_email and candidates[0].get("email"):
                        assignee_email = candidates[0]["email"]
                elif len(candidates) >= 2:
                    log_line(f"[Assignee] Ambiguous assignee '{assignee_name}' across multiple departments. Assignee ID left NULL.")
        except Exception as e:
            from utils.logging import log_line
            log_line(f"[Assignee] Error resolving assignee '{assignee_name}':", e)

    def _do_append(conn):
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO records(id, dept_id, category, title, project, assignee_id,
               assignee_name, assignee_email, start_date, due_date, work_date, summary, tags, memo, status, priority, card_code, participants, parent_key, is_scheduled, is_private)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                rec_id,
                dept_val,
                record.get("category", ""),
                record.get("title", ""),
                record.get("project", "프로젝트 미지정"),
                assignee_id,
                assignee_name,
                assignee_email,
                start_date,
                due_date,
                work_date,
                record.get("summary", ""),
                tags_json,
                record.get("memo", ""),
                status,
                priority,
                card_code,
                participants,
                parent_key,
                is_sched,
                is_private_val,
            )
        )

        # 첨부파일
        attachments = record.get("attachments", [])
        for fname in attachments:
            cur.execute(
                "INSERT INTO record_attachments(record_id, filename) VALUES (?, ?)",
                (rec_id, fname)
            )

        # Jira 연결
        jira = record.get("jira")
        if jira and jira.get("key"):
            cur.execute(
                "INSERT OR REPLACE INTO record_jira(record_id, jira_key, jira_status, jira_url) VALUES (?, ?, ?, ?)",
                (rec_id, jira["key"], jira.get("status", ""), jira.get("url", ""))
            )

    transaction(_do_append)


def link_record_jira(record_id, jira_key, jira_status="", jira_url=""):
    """로컬 레코드에 Jira 티켓 정보를 연결한다."""
    execute(
        "INSERT OR REPLACE INTO record_jira(record_id, jira_key, jira_status, jira_url) VALUES (?, ?, ?, ?)",
        (record_id, jira_key, jira_status, jira_url)
    )


def unlink_record_jira(record_id):
    """로컬 레코드에서 유효하지 않은 Jira 티켓 연동 정보를 제거한다."""
    execute("DELETE FROM record_jira WHERE record_id = ?", (record_id,))


def delete_record(record_id):
    """로컬 레코드 및 관련 댓글, 첨부파일, Jira 매핑 데이터를 삭제한다."""
    def _do_delete(conn):
        cur = conn.cursor()
        # Detach sub-tasks first: a dangling parent_key would make the hierarchy
        # chain render a phantom "Jira 이슈" node for a card that no longer exists.
        cur.execute(
            "UPDATE records SET parent_key = '' WHERE parent_key = "
            "(SELECT card_code FROM records WHERE id = ?)",
            (record_id,),
        )
        cur.execute("UPDATE records SET parent_key = '' WHERE parent_key = ?", (str(record_id),))
        cur.execute("DELETE FROM record_comments WHERE record_id = ?", (record_id,))
        cur.execute("DELETE FROM record_attachments WHERE record_id = ?", (record_id,))
        cur.execute("DELETE FROM record_jira WHERE record_id = ?", (record_id,))
        cur.execute("DELETE FROM records WHERE id = ?", (record_id,))
    transaction(_do_delete)


def next_record_id():
    """유일한 레코드 ID(밀리초 타임스탬프)를 반환한다. 멀티 워커 환경에서도 DB 트랜잭션을 통해 전역 고유성을 보장한다."""
    global _last_record_id
    with _id_lock:
        now_ms = int(time.time() * 1000)

        def _allocate(conn):
            from db import ENGINE
            cur = conn.cursor()
            if ENGINE == "postgres":
                cur.execute(
                    "UPDATE id_allocator SET last_value = GREATEST(last_value + 1, ?::bigint) WHERE name = 'records' RETURNING last_value",
                    (now_ms,)
                )
                row = cur.fetchone()
                if row:
                    return row[0] if isinstance(row, (list, tuple)) else row.get("last_value")
                cur.execute("INSERT INTO id_allocator(name, last_value) VALUES ('records', ?) ON CONFLICT (name) DO NOTHING", (now_ms,))
                return now_ms
            else:
                row = cur.execute("SELECT last_value FROM id_allocator WHERE name = 'records'").fetchone()
                if row is None:
                    cur.execute("INSERT OR IGNORE INTO id_allocator (name, last_value) VALUES ('records', ?)", (now_ms,))
                    last_val = now_ms
                else:
                    last_val = row[0] if isinstance(row, (list, tuple)) else row["last_value"]
                new_id = max(last_val + 1, now_ms)
                cur.execute("UPDATE id_allocator SET last_value = ? WHERE name = 'records'", (new_id,))
                return new_id

        try:
            allocated = transaction(_allocate)
            _last_record_id = allocated
            return allocated
        except Exception:
            if now_ms <= _last_record_id:
                now_ms = _last_record_id + 1
            _last_record_id = now_ms
            return now_ms


def get_next_card_code(dept_id, dept_prefix="REC"):
    """
    부서별 업무 카드 코드(예: DEV-102)를 원자적(Atomic)으로 채번한다.
    동시 요청(Race Condition) 시 번호 중복을 100% 방지한다.
    """
    dept_id = (dept_id or "").strip()
    prefix = (dept_prefix or "REC").strip()

    def _do(conn):
        cur = conn.cursor()
        cur.execute("SELECT last_seq FROM card_sequences WHERE dept_id = ?", (dept_id,))
        row = cur.fetchone()
        last_seq = 0 if row is None else (row[0] if isinstance(row, (list, tuple)) else row["last_seq"])

        # 기존 레코드에서 실제 사용된 가장 높은 번호와 대조하여 항상 더 큰 번호로 채번
        cur.execute("SELECT card_code FROM records WHERE dept_id = ?", (dept_id,))
        max_num = last_seq
        for r in cur.fetchall():
            cc = r[0] if isinstance(r, (list, tuple)) else r["card_code"]
            if cc and "-" in cc:
                parts = cc.split("-")
                if len(parts) >= 2 and parts[-1].isdigit():
                    max_num = max(max_num, int(parts[-1]))

        next_seq = max(last_seq, max_num) + 1

        # 안전장치: 혹시라도 이미 존재하는 코드인 경우 중복이 없을 때까지 번호 자동 증가
        while True:
            candidate = f"{prefix}-{next_seq}"
            exists = cur.execute("SELECT 1 FROM records WHERE card_code = ? LIMIT 1", (candidate,)).fetchone()
            if not exists:
                break
            next_seq += 1

        cur.execute("INSERT OR REPLACE INTO card_sequences(dept_id, last_seq) VALUES (?, ?)", (dept_id, next_seq))
        return f"{prefix}-{next_seq}"

    return transaction(_do)



# ---------------------------------------------------------------------------
# Schedule
# ---------------------------------------------------------------------------
def read_schedule():
    """일정 목록을 반환한다 (기존 JSON 형식과 동일한 dict)."""
    rows = query("SELECT * FROM schedule_events ORDER BY start_date DESC, id DESC")
    result = []
    for r in rows:
        ev = {
            "id": r["id"],
            "ownerKey": f"{r['owner_name']}|{r['owner_dept_id']}",
            "ownerName": r["owner_name"],
            "ownerOrg": r["owner_dept_id"],
            "ownerEmail": r["owner_email"],
            "type": r["type"],
            "title": r["title"],
            "startDate": r["start_date"],
            "endDate": r["end_date"],
            "memo": r["memo"],
            "approval_status": r.get("approval_status") or "approved",
            "approved_by": r.get("approved_by") or "",
            "approved_at": r.get("approved_at") or "",
            "reject_reason": r.get("reject_reason") or "",
            "createdAt": r["created_at"],
        }
        # participants
        parts = query(
            "SELECT user_name, user_dept_id, user_email, is_owner FROM schedule_participants WHERE event_id = ? ORDER BY id",
            (r["id"],)
        )
        if parts:
            ev["participants"] = [
                {
                    "name": p["user_name"],
                    "org": p["user_dept_id"],
                    "email": p["user_email"],
                    "key": f"{p['user_name']}|{p['user_dept_id']}",
                    "isOwner": bool(p["is_owner"]),
                }
                for p in parts
            ]
        result.append(ev)
    return result


def write_schedule(events):
    """일정 목록을 전체 교체한다 (기존 API 호환)."""
    def _do(conn):
        cur = conn.cursor()
        cur.execute("DELETE FROM schedule_participants")
        cur.execute("DELETE FROM schedule_events")

        for ev in events:
            owner_id = None
            try:
                row = cur.execute(
                    "SELECT id FROM users WHERE name = ? AND dept_id = ?",
                    (ev.get("ownerName", ""), ev.get("ownerOrg", ""))
                ).fetchone()
                if row:
                    # PostgreSQL transactions use RealDictCursor (dict rows); SQLite
                    # uses tuples. row[0] would raise KeyError on Postgres and the
                    # except below would silently drop the owner link.
                    owner_id = row["id"] if isinstance(row, dict) else row[0]
            except Exception as e:
                log_line("[data_store] Error looking up schedule event owner_id:", e)

            cur.execute(
                """INSERT INTO schedule_events(id, owner_id, owner_name, owner_dept_id, owner_email,
                   type, title, start_date, end_date, memo, approval_status, approved_by, approved_at, reject_reason, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    ev.get("id"),
                    owner_id,
                    ev.get("ownerName", ""),
                    ev.get("ownerOrg", ""),
                    ev.get("ownerEmail", ""),
                    ev.get("type", ""),
                    ev.get("title", ""),
                    ev.get("startDate", ""),
                    ev.get("endDate", ""),
                    ev.get("memo", ""),
                    ev.get("approval_status", "approved"),
                    ev.get("approved_by", ""),
                    ev.get("approved_at", ""),
                    ev.get("reject_reason", ""),
                    ev.get("createdAt", ""),
                )
            )

            for p in ev.get("participants", []):
                cur.execute(
                    """INSERT INTO schedule_participants(event_id, user_name, user_dept_id, user_email, is_owner)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        ev.get("id"),
                        p.get("name", ""),
                        p.get("org", ""),
                        p.get("email", ""),
                        1 if p.get("isOwner") else 0,
                    )
                )
    transaction(_do)


def mutate_schedule(mutator):
    """
    일정 목록에 대한 read-modify-write 를 전역 저장 락(_save_lock)으로 보호한다.

    write_schedule() 은 테이블 전체를 DELETE 후 재삽입하므로, 락 없이
    read_schedule() → 수정 → write_schedule() 을 수행하면 동시 요청이 서로의
    변경분을 덮어써 일정이 유실될 수 있다.

    mutator(events) 는 전달받은 리스트를 직접 수정하면 되고, 반환값은 그대로
    호출자에게 전달된다.
    """
    with _save_lock:
        events = read_schedule()
        result = mutator(events)
        write_schedule(events)
        return result


# ---------------------------------------------------------------------------
# Products (PIM)
# ---------------------------------------------------------------------------
def read_products(include_external=False):
    """제품 목록을 반환한다."""
    rows = query("SELECT * FROM products ORDER BY updated_at DESC")
    result = []
    for r in rows:
        proc_data = json.loads(r["procurement"]) if r["procurement"] else None
        price_val = r["price"] if "price" in r and r["price"] is not None else 0
        if not price_val and proc_data and proc_data.get("price"):
            price_val = proc_data.get("price")
        currency_val = r["currency"] if "currency" in r and r["currency"] else "KRW"
        prod = {
            "id": r["id"],
            "model": r["model"],
            "displayName": r["display_name"],
            "family": r["family"],
            "lifecycle": r["lifecycle"],
            "category": r["category"],
            "source": r.get("source") or "internal",
            "summary": r["summary"],
            "memo": r["memo"],
            "price": price_val,
            "currency": currency_val,
            "specs": json.loads(r["specs"]) if r["specs"] else {},
            "procurement": proc_data,
            "revision": r["revision"],
            "createdAt": r["created_at"],
            "updatedAt": r["updated_at"],
        }
        # attachments
        atts = query(
            "SELECT filename, file_size, uploaded_at FROM product_attachments WHERE product_id = ? ORDER BY id",
            (r["id"],)
        )
        prod["attachments"] = [
            {"name": a["filename"], "size": a["file_size"], "uploadedAt": a["uploaded_at"]}
            for a in atts
        ]
        result.append(prod)
    return result


def write_products(products, target_source=None):
    """제품 목록을 저장한다.
    target_source가 지정되지 않은 경우 전달된 products 목록에 포함된 source 목록만 삭제 후 교체하여
    사내 제품 저장 시 라이브 제품이 지워지거나, 라이브 제품 동기화 시 사내 제품이 지워지는 문제를 원천 방지한다.
    """
    def _do(conn):
        cur = conn.cursor()
        # Delete and reinsert products based on target_source or sources of provided products
        sources_to_delete = set()
        if target_source:
            sources_to_delete.add(target_source)
        elif products:
            for p in products:
                sources_to_delete.add(p.get("source") or "internal")
        
        if sources_to_delete:
            placeholders = ",".join(["?"] * len(sources_to_delete))
            src_list = list(sources_to_delete)
            cur.execute(f"DELETE FROM product_attachments WHERE product_id IN (SELECT id FROM products WHERE source IN ({placeholders}))", src_list)
            cur.execute(f"DELETE FROM products WHERE source IN ({placeholders})", src_list)
        elif target_source is None and not products:
            # If empty list passed without target_source, do not delete anything unexpectedly
            pass

        for p in products:
            specs_json = json.dumps(p.get("specs", {}), ensure_ascii=False)
            proc = p.get("procurement")
            proc_json = json.dumps(proc, ensure_ascii=False) if proc else None
            source = p.get("source") or "internal"

            cur.execute(
                """INSERT INTO products(id, model, display_name, family, lifecycle, category,
                   summary, memo, specs, procurement, revision, created_at, updated_at, source, price, currency)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    p["id"], p.get("model", ""), p.get("displayName", ""),
                    p.get("family", ""), p.get("lifecycle", "판매 중"),
                    p.get("category", "일반"), p.get("summary", ""),
                    p.get("memo", ""), specs_json, proc_json,
                    p.get("revision", 1), p.get("createdAt", ""), p.get("updatedAt", ""),
                    source,
                    p.get("price", 0),
                    p.get("currency", "KRW")
                )
            )

            for att in p.get("attachments", []):
                cur.execute(
                    "INSERT INTO product_attachments(product_id, filename, file_size, uploaded_at) VALUES (?, ?, ?, ?)",
                    (p["id"], att.get("name", ""), att.get("size", 0), att.get("uploadedAt", ""))
                )
    transaction(_do)


def next_product_id():
    """유일한 제품 ID를 반환한다 (P-hex 형식)."""
    global _last_product_id
    with _id_lock:
        now_ms = int(time.time() * 1000)
        if now_ms <= _last_product_id:
            now_ms = _last_product_id + 1
        _last_product_id = now_ms
        return "P-" + format(now_ms, "x")


# ---------------------------------------------------------------------------
# Product Categories & Spec Templates
# ---------------------------------------------------------------------------
DEFAULT_PRODUCT_CATEGORIES_DATA = [
    {
        "id": "cat_general",
        "name": "일반",
        "spec_template": [
            {"group": "기본 사양", "key": "dimensions", "label": "크기 / 규격", "maxlen": 60},
            {"group": "기본 사양", "key": "weight", "label": "중량 / 무게", "maxlen": 40},
            {"group": "기본 사양", "key": "color", "label": "색상 / 재질", "maxlen": 40}
        ]
    },
    {
        "id": "cat_sw",
        "name": "소프트웨어",
        "spec_template": [
            {"group": "소프트웨어 사양", "key": "version", "label": "버전", "maxlen": 40},
            {"group": "소프트웨어 사양", "key": "os", "label": "지원 OS", "maxlen": 60},
            {"group": "소프트웨어 사양", "key": "license", "label": "라이선스", "maxlen": 40}
        ]
    },
    {
        "id": "cat_hw",
        "name": "하드웨어",
        "spec_template": [
            {"group": "하드웨어 사양", "key": "modelNo", "label": "상세 모델 번호", "maxlen": 40},
            {"group": "하드웨어 사양", "key": "power", "label": "정격 전원", "maxlen": 40},
            {"group": "하드웨어 사양", "key": "interface", "label": "인터페이스 / 단자", "maxlen": 60}
        ]
    },
    {
        "id": "cat_etc",
        "name": "기타",
        "spec_template": [
            {"group": "기타 사양", "key": "specNote", "label": "주요 사양", "maxlen": 100}
        ]
    }
]

_PRODUCT_CATEGORIES_READY = set()
_PRODUCT_CATEGORIES_LOCK = threading.Lock()


def _ensure_product_categories_table():
    """
    product_categories 테이블 생성을 DB(경로)당 1회로 제한한다.

    이전 구현은 read_product_categories() 가 호출될 때마다 CREATE TABLE DDL 을
    실행했는데, 이 함수는 제품 저장/검증/조회 hot path 에서 매번 호출되므로
    SQLite 에서는 매 읽기마다 스키마 write-lock 을 잡고 PostgreSQL 에서는
    불필요한 DDL 락을 유발했다. 스키마(schema.sql / schema.postgres.sql)와
    init_db() 가 이미 테이블을 생성하므로, 여기서는 최초 1회만 보장하면 된다.
    """
    try:
        from db import get_db_path
        key = str(get_db_path())
        try:
            from db import get_search_path
            key += "|" + str(get_search_path())
        except Exception:
            pass
    except Exception:
        key = "__unknown_db__"
    if key in _PRODUCT_CATEGORIES_READY:
        return
    with _PRODUCT_CATEGORIES_LOCK:
        if key in _PRODUCT_CATEGORIES_READY:
            return
        execute("""CREATE TABLE IF NOT EXISTS product_categories (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        spec_template TEXT NOT NULL DEFAULT '[]',
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
    )""")
        _PRODUCT_CATEGORIES_READY.add(key)


def read_product_categories():
    """제품 카테고리 목록과 규격 템플릿을 반환한다."""
    _ensure_product_categories_table()
    rows = query("SELECT id, name, spec_template FROM product_categories ORDER BY rowid")
    if not rows:
        for item in DEFAULT_PRODUCT_CATEGORIES_DATA:
            execute(
                "INSERT OR IGNORE INTO product_categories(id, name, spec_template) VALUES (?, ?, ?)",
                (item["id"], item["name"], json.dumps(item["spec_template"], ensure_ascii=False))
            )
        rows = query("SELECT id, name, spec_template FROM product_categories ORDER BY rowid")
    
    result = []
    defaults_by_id = {item["id"]: item["spec_template"] for item in DEFAULT_PRODUCT_CATEGORIES_DATA}
    defaults_by_name = {item["name"]: item["spec_template"] for item in DEFAULT_PRODUCT_CATEGORIES_DATA}

    for r in rows:
        try:
            tpl = json.loads(r["spec_template"]) if r["spec_template"] else []
        except Exception:
            tpl = []
        # If empty in DB, provide default template if available
        if not tpl:
            tpl = defaults_by_id.get(r["id"]) or defaults_by_name.get(r["name"]) or []
        result.append({
            "id": r["id"],
            "name": r["name"],
            "spec_template": tpl
        })
    return result

def get_product_categories_and_templates():
    """API 응답 및 검증용: categories 리스트와 templates 딕셔너리를 반환한다."""
    cats = read_product_categories()
    category_names = [c["name"] for c in cats]
    templates = {c["name"]: c["spec_template"] for c in cats}
    return category_names, templates

def save_product_category(cat_id, name, spec_template):
    """제품 카테고리를 추가 또는 수정한다."""
    name = (name or "").strip()
    if not name:
        return False, "카테고리 이름을 입력해주세요."
    
    cats = read_product_categories()
    # Check duplicate name
    if any(c["name"].lower() == name.lower() and c["id"] != cat_id for c in cats):
        return False, "이미 존재하는 제품 카테고리 이름입니다."

    if not cat_id:
        cat_id = "cat_" + format(int(time.time() * 1000), "x")

    tpl_json = json.dumps(spec_template or [], ensure_ascii=False)
    execute(
        """INSERT INTO product_categories(id, name, spec_template) VALUES (?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET name=excluded.name, spec_template=excluded.spec_template""",
        (cat_id, name, tpl_json)
    )
    return True, cat_id

def delete_product_category(cat_id):
    """제품 카테고리를 삭제한다. 해당 카테고리에 속한 제품이 있으면 삭제 불가."""
    cats = read_product_categories()
    target = next((c for c in cats if c["id"] == cat_id), None)
    if not target:
        return False, "존재하지 않는 카테고리입니다."
    
    prods = query("SELECT count(*) as c FROM products WHERE category = ?", (target["name"],))
    count = prods[0]["c"] if prods else 0
    if count > 0:
        return False, f"'{target['name']}' 카테고리를 사용하는 제품이 {count}건 있어 삭제할 수 없습니다."
    
    execute("DELETE FROM product_categories WHERE id = ?", (cat_id,))
    return True, ""


def get_used_spec_keys(category_name):
    """해당 카테고리의 제품에서 실제 값이 입력된 spec key 목록을 반환한다."""
    rows = query("SELECT specs FROM products WHERE category = ?", (category_name,))
    used = set()
    for r in rows:
        try:
            specs = json.loads(r["specs"]) if r.get("specs") else {}
            for k, v in specs.items():
                if v and str(v).strip():
                    used.add(k)
        except Exception:
            pass
    return sorted(used)


def update_record_work_date(record_id_or_code, new_date, end_date=None):
    """특정 레코드의 start_date, due_date 및 work_date를 업데이트하고 달력 표시(is_scheduled = 1)를 활성화한다."""
    if not record_id_or_code or not new_date:
        return None, None
    rec = find_record_by_key_or_code(record_id_or_code)
    if not rec:
        return None, None
    r_id = rec["id"]

    raw = str(new_date).strip()
    if end_date:
        s_val = raw
        d_val = str(end_date).strip()
    elif "~" in raw:
        parts = [p.strip() for p in raw.split("~")]
        s_val = parts[0]
        d_val = parts[1] if len(parts) > 1 and parts[1] else s_val
    else:
        s_val = raw
        d_val = raw

    if s_val and d_val and s_val > d_val:
        s_val, d_val = d_val, s_val

    w_val = f"{s_val} ~ {d_val}" if (s_val and d_val and s_val != d_val) else s_val
    execute("UPDATE records SET start_date = ?, due_date = ?, work_date = ?, is_scheduled = 1 WHERE id = ?", (s_val, d_val, w_val, r_id))
    rj = query("SELECT jira_key FROM record_jira WHERE record_id = ?", (r_id,))
    jira_key = rj[0]["jira_key"] if rj else None
    return r_id, jira_key


def clear_record_work_date(record_id_or_code, wipe_dates=False):
    """특정 레코드의 달력 배정을 해제(is_scheduled = 0)하여 보관함으로 이동시킨다. 기존 날짜(시작일/마감일)는 보존된다."""
    if not record_id_or_code:
        return None, None
    rec = find_record_by_key_or_code(record_id_or_code)
    if not rec:
        return None, None
    r_id = rec["id"]
    if wipe_dates:
        execute("UPDATE records SET start_date = '', due_date = '', work_date = '', is_scheduled = 0 WHERE id = ?", (r_id,))
    else:
        execute("UPDATE records SET is_scheduled = 0 WHERE id = ?", (r_id,))
    rj = query("SELECT jira_key FROM record_jira WHERE record_id = ?", (r_id,))
    jira_key = rj[0]["jira_key"] if rj else None
    return r_id, jira_key


def set_record_schedule_visibility(record_id_or_code, is_scheduled=True):
    """특정 레코드의 달력 표시 여부를 토글/설정한다 (1: 달력 표시, 0: 달력에서 숨김)."""
    if not record_id_or_code:
        return None, None
    rec = find_record_by_key_or_code(record_id_or_code)
    if not rec:
        return None, None
    r_id = rec["id"]
    val = 1 if is_scheduled else 0
    execute("UPDATE records SET is_scheduled = ? WHERE id = ?", (val, r_id))
    rj = query("SELECT jira_key FROM record_jira WHERE record_id = ?", (r_id,))
    jira_key = rj[0]["jira_key"] if rj else None
    return r_id, jira_key


_UNSET = object()


def update_record_details(record_id_or_code, title=None, memo=None, assignee_name=None, assignee_email=None, participants=None, due_date=None, start_date=None, expected_version=None, parent_key=_UNSET, priority=None, is_private=None):
    """업무 기록의 제목, 상세 내용(메모), 담당자, 참여자, 시작일/마감일을 포괄적으로 수정한다.
    Optimistic Locking (낙관적 락): expected_version이 지정된 경우 DB의 현재 버전과 일치하는지 검증한다."""
    if not record_id_or_code:
        return None, "기록 ID가 필요합니다."
    rec = find_record_by_key_or_code(record_id_or_code)
    if not rec:
        return None, "해당 업무 기록을 찾을 수 없습니다."

    r_id = rec["id"]
    current_version = int(rec.get("version") or 1)

    # 낙관적 락 (Optimistic Concurrency Control) 사전 검증
    if expected_version is not None:
        try:
            exp_v = int(expected_version)
            if exp_v != current_version:
                return None, f"CONFLICT: 다른 사용자가 이 카드를 이미 수정했습니다 (현재 v{current_version}, 클라이언트 v{exp_v}). 최신 정보를 다시 불러와주세요."
        except (ValueError, TypeError):
            pass

    updates = []
    params = []

    if title is not None and str(title).strip():
        new_title = str(title).strip()
        updates.append("title = ?")
        params.append(new_title)
        updates.append("summary = ?")
        params.append(new_title)

    if memo is not None:
        updates.append("memo = ?")
        params.append(str(memo).strip())

    if assignee_name is not None:
        new_assignee_str = str(assignee_name).strip()
        updates.append("assignee_name = ?")
        params.append(new_assignee_str)
        try:
            r_dept = rec.get("dept_id") or rec.get("org") or ""
            u_row = get_one("SELECT id FROM users WHERE (name = ? OR username = ?) AND dept_id = ? LIMIT 1", (new_assignee_str, new_assignee_str, r_dept))
            if not u_row:
                u_row = get_one("SELECT id FROM users WHERE name = ? OR username = ? LIMIT 1", (new_assignee_str, new_assignee_str))
            if u_row:
                updates.append("assignee_id = ?")
                params.append(u_row["id"])
        except Exception:
            pass

    if assignee_email is not None:
        updates.append("assignee_email = ?")
        params.append(str(assignee_email).strip())

    effective_assignee = str(assignee_name).strip() if assignee_name is not None else (rec.get("assignee_name") or rec.get("assignee") or "")
    if participants is not None:
        p_clean = str(participants).strip()
        if p_clean and effective_assignee:
            parts_list = [p.strip() for p in p_clean.replace(";", ",").split(",") if p.strip()]
            parts_list = [p for p in parts_list if p.lower() != effective_assignee.lower()]
            p_clean = ", ".join(parts_list)
        updates.append("participants = ?")
        params.append(p_clean)

    if due_date is not None or start_date is not None:
        s_date = str(start_date).strip() if start_date is not None else (rec.get("start_date") or "")
        d_date = str(due_date).strip() if due_date is not None else (rec.get("due_date") or "")
        if not s_date and d_date:
            s_date = d_date
        elif not d_date and s_date:
            d_date = s_date
        if s_date and d_date and s_date > d_date:
            s_date, d_date = d_date, s_date
        w_date = f"{s_date} ~ {d_date}" if (s_date and d_date and s_date != d_date) else s_date
        updates.extend(["start_date = ?", "due_date = ?", "work_date = ?"])
        params.extend([s_date, d_date, w_date])

    if priority is not None and str(priority).strip():
        p_val = str(priority).strip()
        if p_val in ("낮음", "보통", "높음", "긴급"):
            updates.append("priority = ?")
            params.append(p_val)

    if is_private is not None:
        updates.append("is_private = ?")
        params.append(1 if is_private else 0)

    if parent_key is not _UNSET:
        p_val = str(parent_key or "").strip().upper()
        if p_val:
            rec_id_str = str(rec.get("id"))
            rec_code = str(rec.get("cardCode") or "").upper().lstrip("#")
            clean_target = p_val.lstrip("#").replace("REC-", "")
            if clean_target == rec_id_str or (rec_code and clean_target == rec_code):
                return None, "카드는 자기 자신을 상위 작업으로 지정할 수 없습니다."
            curr = find_record_by_key_or_code(p_val)
            visited = set()
            while curr:
                c_id = str(curr.get("id"))
                c_code = str(curr.get("cardCode") or "").upper().lstrip("#")
                if c_id in visited:
                    break
                visited.add(c_id)
                if c_id == rec_id_str or (rec_code and c_code == rec_code):
                    return None, "순환 참조(Circular Reference) 오류: 하위 작업을 상위 작업으로 지정할 수 없습니다."
                next_pk = (curr.get("parentKey") or curr.get("parent_key") or "").strip()
                if not next_pk:
                    break
                curr = find_record_by_key_or_code(next_pk)

            updates.append("parent_key = ?")
            params.append(p_val)
        else:
            updates.append("parent_key = ''")

    # 항상 version 1 증가 및 updated_at 타임스탬프 갱신
    now_iso = datetime.now().isoformat()
    updates.append("version = version + 1")
    updates.append("updated_at = ?")
    params.append(now_iso)

    if expected_version is not None:
        from db import execute_rowcount
        params.extend([r_id, current_version])
        rows_affected = execute_rowcount(f"UPDATE records SET {', '.join(updates)} WHERE id = ? AND version = ?", tuple(params))
        if rows_affected == 0:
            return None, f"CONFLICT: 수정 중 충돌이 발생했습니다. 다른 사용자에 의해 이미 업데이트되었습니다 (v{current_version})."
    else:
        params.append(r_id)
        execute(f"UPDATE records SET {', '.join(updates)} WHERE id = ?", tuple(params))

    updated_rec = get_record_by_id(r_id)
    return updated_rec, ""



