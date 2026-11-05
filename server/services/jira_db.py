#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""jira_db.py — Persistent Storage and Retrieval for Jira Issues, Comments, Attachments (SQLite)"""

import json
from datetime import datetime
from db import query, get_one, execute, transaction
from utils.logging import log_line


def get_last_sync_time():
    """Returns the last successful sync timestamp (ISO format) from sync_meta, or None."""
    try:
        row = get_one("SELECT value FROM sync_meta WHERE key = 'jira_last_sync'")
        return row["value"] if row else None
    except Exception as e:
        log_line("Error reading jira_last_sync from sync_meta:", e)
        return None


def set_last_sync_time(iso_ts=None):
    """Sets the last successful sync timestamp in sync_meta."""
    ts = iso_ts or datetime.now().isoformat()
    try:
        execute(
            """INSERT INTO sync_meta (key, value, updated_at)
               VALUES ('jira_last_sync', ?, (strftime('%Y-%m-%dT%H:%M:%S','now')))
               ON CONFLICT(key) DO UPDATE SET
                   value = excluded.value,
                   updated_at = excluded.updated_at""",
            (ts,)
        )
    except Exception as e:
        log_line("Error saving jira_last_sync to sync_meta:", e)

def get_last_full_sync_time():
    """Returns the last complete Jira snapshot reconciliation timestamp."""
    try:
        row = get_one("SELECT value FROM sync_meta WHERE key = 'jira_last_full_sync'")
        return row["value"] if row else None
    except Exception as e:
        log_line("Error reading jira_last_full_sync from sync_meta:", e)
        return None


def set_last_full_sync_time(iso_ts=None):
    """Persists the last complete full-snapshot reconciliation timestamp."""
    ts = iso_ts or datetime.now().isoformat()
    try:
        execute(
            """INSERT INTO sync_meta (key, value, updated_at)
               VALUES ('jira_last_full_sync', ?, (strftime('%Y-%m-%dT%H:%M:%S','now')))
               ON CONFLICT(key) DO UPDATE SET
                   value = excluded.value,
                   updated_at = excluded.updated_at""",
            (ts,)
        )
    except Exception as e:
        log_line("Error saving jira_last_full_sync to sync_meta:", e)


def upsert_jira_record(record):
    """Upsert a single parsed Jira record dict into jira_issues, jira_comments, jira_attachments."""
    upsert_jira_records([record])


def upsert_jira_records(records, replace_existing=False):
    """Upsert multiple parsed Jira record dicts in a single atomic transaction.
    Optionally reconcile deletions after a complete full sync when replace_existing=True.
    """
    if not records and not replace_existing:
        return True

    incoming_keys = set()
    has_missing_key = False
    for record in records or []:
        jira_info = record.get("jira") or {}
        key = jira_info.get("key") or str(record.get("id") or "").replace("jira-", "")
        if key:
            incoming_keys.add(str(key).upper())
        else:
            has_missing_key = True
    if replace_existing and has_missing_key:
        log_line("Refusing Jira full-sync reconciliation because a returned issue has no stable key.")
        return False

    def _do_upsert(conn):
        cur = conn.cursor()
        if replace_existing:
            cur.execute("SELECT jira_key FROM jira_issues")
            existing_rows = cur.fetchall()
            existing_keys = {
                str(row[0] if isinstance(row, (tuple, list)) else row.get("jira_key")).upper()
                for row in existing_rows
            }
            stale_keys = sorted(existing_keys - incoming_keys)
            for offset in range(0, len(stale_keys), 500):
                batch = stale_keys[offset:offset + 500]
                placeholders = ", ".join("?" for _ in batch)
                params = tuple(batch)
                cur.execute(f"DELETE FROM jira_comments WHERE UPPER(jira_key) IN ({placeholders})", params)
                cur.execute(f"DELETE FROM jira_attachments WHERE UPPER(jira_key) IN ({placeholders})", params)
                cur.execute(f"DELETE FROM jira_changelog WHERE UPPER(issue_key) IN ({placeholders})", params)
                cur.execute(f"DELETE FROM jira_issues WHERE UPPER(jira_key) IN ({placeholders})", params)

        for r in records or []:
            jira_info = r.get("jira") or {}
            raw_key = jira_info.get("key")
            raw_id = r.get("id")
            if raw_key is None and raw_id is None:
                raise ValueError("Jira record must have a valid key or id")
            key = raw_key or str(raw_id).replace("jira-", "")
            if not key:
                continue

            summary = jira_info.get("summary") or r.get("title", "")
            desc = r.get("memo") or r.get("summary", "")
            status = jira_info.get("status") or ""
            status_name = jira_info.get("statusName") or status
            assignee = r.get("assignee") or ""
            reporter = jira_info.get("reporter") or ""
            category = r.get("category") or ""
            org = r.get("org") or ""
            project_name = r.get("project") or ""
            start_date = r.get("startDate") or ""
            due_date = r.get("dueDate") or ""
            created_at = r.get("date") or ""
            parent_key = r.get("parentKey") or ""
            parent_summary = r.get("parentSummary") or ""
            is_subtask = 1 if r.get("isSubtask") else 0
            avatar_url = r.get("assigneeAvatar") or r.get("avatarUrl") or ""
            tags_json = json.dumps(r.get("tags") or [], ensure_ascii=False)
            raw_json = json.dumps(r, ensure_ascii=False)

            # 1. UPSERT into jira_issues
            cur.execute(
                """INSERT INTO jira_issues (
                    jira_key, project_name, issue_type, is_subtask, parent_key, parent_summary,
                    summary, description, status, status_name, assignee_name, assignee_avatar,
                    reporter_name, dept_id, start_date, due_date, created_at, tags, raw_json, synced_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, (strftime('%Y-%m-%dT%H:%M:%S','now')))
                ON CONFLICT(jira_key) DO UPDATE SET
                    project_name = excluded.project_name,
                    issue_type = excluded.issue_type,
                    is_subtask = excluded.is_subtask,
                    parent_key = excluded.parent_key,
                    parent_summary = excluded.parent_summary,
                    summary = excluded.summary,
                    description = excluded.description,
                    status = excluded.status,
                    status_name = excluded.status_name,
                    assignee_name = excluded.assignee_name,
                    assignee_avatar = excluded.assignee_avatar,
                    reporter_name = excluded.reporter_name,
                    dept_id = excluded.dept_id,
                    start_date = excluded.start_date,
                    due_date = excluded.due_date,
                    created_at = excluded.created_at,
                    tags = excluded.tags,
                    raw_json = excluded.raw_json,
                    synced_at = excluded.synced_at""",
                (
                    key, project_name, category, is_subtask, parent_key, parent_summary,
                    summary, desc, status, status_name, assignee, avatar_url,
                    reporter, org, start_date, due_date, created_at, tags_json, raw_json
                )
            )

            # Reconcile remote comments only after the caller fetched every page.
            # Preserve locally-created comments stored with source='local'.
            if r.get("_jira_comments_complete") is True:
                cur.execute(
                    "DELETE FROM jira_comments WHERE UPPER(jira_key) = UPPER(?) AND source = 'jira'",
                    (key,)
                )

            # 2. UPSERT comments for this issue
            comments = r.get("comments") or []
            for c in comments:
                c_id = str(c.get("id") or "")
                if not c_id:
                    continue
                # If local or duplicate comment id, prefix with jira key
                unique_cid = f"{key}_{c_id}" if c_id == "local" else c_id
                c_author = c.get("author") or "사용자"
                c_body = c.get("body") or ""
                c_created = c.get("created") or ""
                c_source = c.get("source") or "jira"

                cur.execute(
                    """INSERT INTO jira_comments (
                        comment_id, jira_key, author_name, body, created_at, source
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(comment_id) DO UPDATE SET
                        author_name = excluded.author_name,
                        body = excluded.body,
                        created_at = excluded.created_at,
                        source = excluded.source""",
                    (unique_cid, key, c_author, c_body, c_created, c_source)
                )

            # Attachment metadata is a complete Jira issue field snapshot.
            # Replace stale rows only when the caller marks the snapshot complete.
            if r.get("_jira_attachments_complete") is True:
                cur.execute("DELETE FROM jira_attachments WHERE UPPER(jira_key) = UPPER(?)", (key,))

            # 3. UPSERT attachments for this issue
            attachments = r.get("attachments") or []
            for a in attachments:
                a_id = str(a.get("id") or "")
                if not a_id:
                    continue
                a_name = a.get("name") or "file"
                a_size = int(a.get("size") or 0)
                a_url = a.get("url") or ""

                cur.execute(
                    """INSERT INTO jira_attachments (
                        attachment_id, jira_key, filename, file_size, jira_url
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(attachment_id) DO UPDATE SET
                        filename = excluded.filename,
                        file_size = excluded.file_size,
                        jira_url = excluded.jira_url""",
                    (a_id, key, a_name, a_size, a_url)
                )

    try:
        transaction(_do_upsert)
        return True
    except Exception as e:
        log_line("Error upserting Jira records to SQLite:", e)
        raise


def load_all_jira_from_db():
    """Load all Jira records from SQLite database with full structure preservation."""
    try:
        rows = query("SELECT raw_json FROM jira_issues ORDER BY created_at DESC, jira_key DESC")
        records = []
        for r in rows:
            raw = r.get("raw_json")
            if raw:
                try:
                    records.append(json.loads(raw))
                except Exception:
                    pass
        return records
    except Exception as e:
        log_line("Error loading Jira records from database:", e)
        return []


def upsert_jira_activities(activities):
    """Upsert list of Jira changelog activity dicts into jira_changelog table."""
    if not activities:
        return

    def _do_upsert_act(conn):
        cur = conn.cursor()
        for a in activities:
            aid = a.get("id")
            if not aid:
                continue
            cur.execute(
                """INSERT INTO jira_changelog (
                    id, issue_key, action_type, action_detail, author_name,
                    author_avatar, created_at, summary, status, priority,
                    issue_type, assignee_name, assignee_dept, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    action_detail = excluded.action_detail,
                    author_name = excluded.author_name,
                    author_avatar = excluded.author_avatar,
                    status = excluded.status,
                    summary = excluded.summary""",
                (
                    aid,
                    a.get("issue_key", ""),
                    a.get("action_type", ""),
                    a.get("action_detail", ""),
                    a.get("author_name", ""),
                    a.get("author_avatar", "") or "",
                    a.get("created_at", ""),
                    a.get("summary", ""),
                    a.get("status", ""),
                    a.get("priority", "보통"),
                    a.get("issue_type", ""),
                    a.get("assignee_name", ""),
                    a.get("assignee_dept", ""),
                    a.get("source", "jira")
                )
            )

    try:
        transaction(_do_upsert_act)
    except Exception as e:
        log_line("Error upserting Jira activities to SQLite:", e)
        raise


def load_all_jira_activities_from_db():
    """Load all Jira changelog activities from SQLite database."""
    try:
        rows = query("SELECT * FROM jira_changelog ORDER BY created_at DESC")
        return [dict(r) for r in rows]
    except Exception as e:
        log_line("Error loading Jira activities from database:", e)
        return []


def get_jira_db_stats():
    """Returns total count of stored issues, comments, and attachments in SQLite."""
    try:
        issues_cnt = get_one("SELECT COUNT(*) as cnt FROM jira_issues")
        comments_cnt = get_one("SELECT COUNT(*) as cnt FROM jira_comments")
        attachments_cnt = get_one("SELECT COUNT(*) as cnt FROM jira_attachments")
        last_sync = get_last_sync_time()
        return {
            "issues": issues_cnt["cnt"] if issues_cnt else 0,
            "comments": comments_cnt["cnt"] if comments_cnt else 0,
            "attachments": attachments_cnt["cnt"] if attachments_cnt else 0,
            "last_sync": last_sync
        }
    except Exception as e:
        return {"error": str(e)}
