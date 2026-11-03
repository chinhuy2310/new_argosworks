#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""activity_store.py — Work History & Activity Explorer strictly for JARVIS (ARGOS WORKS)
Completely independent from Choivis. Sourced solely from JARVIS internal data:
- activities table (SQLite — formerly activities.jsonl)
- records table (submitted work records)
- schedule_events table (schedule & calendar events)
- Jira synchronized records cache
"""

import os
import json
import threading
from datetime import datetime

from config import DATA_DIR
from services.data_store import read_records, read_schedule
from db import query, execute
from utils.text import parse_iso_timestamp, assignee_base_name


def append_activity(act):
    """Append a single activity item to the activities table."""
    if not act:
        return
    if "created_at" not in act:
        act["created_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    act_id = act.get("id")
    if not act_id:
        import uuid
        act_id = f"act_{uuid.uuid4().hex}"
        act["id"] = act_id
    execute(
        """INSERT OR IGNORE INTO activities(id, issue_key, action_type, action_detail,
           author_name, author_email, summary, status, priority,
           issue_type, assignee_name, assignee_dept, source, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            act_id,
            act.get("issue_key", ""),
            act.get("action_type", ""),
            act.get("action_detail", ""),
            act.get("author_name", ""),
            act.get("author_email", ""),
            act.get("summary", ""),
            act.get("status", ""),
            act.get("priority", "보통"),
            act.get("issue_type", ""),
            act.get("assignee_name", ""),
            act.get("assignee_dept", ""),
            act.get("source", "jarvis"),
            act.get("created_at", ""),
        )
    )


def read_activities_log():
    """Read all logged activities from the activities table."""
    rows = query("SELECT * FROM activities ORDER BY created_at DESC")
    return [dict(r) for r in rows]


def is_custom_avatar(url):
    """Check if avatar URL is a real user-uploaded photo rather than default placeholder or gravatar."""
    if not url:
        return False
    u = str(url).lower()
    return "default-avatar" not in u and "default/" not in u and "gravatar.com/avatar" not in u


def build_member_identity_master(jira_activities=None):
    """Build unified member identity directory keyed by email and base_name.
    Integrates accounts.json, records.jsonl, schedule.json, departments.json, and Jira user cache.
    Email is the definitive canonical key.
    """
    from db import query
    from services.data_store import read_departments

    dept_name_map = {d["id"]: d["name"] for d in read_departments()}
    # Fallback / standard mappings
    dept_name_map["lab"] = "연구소"
    dept_name_map["기업부설연구소"] = "연구소"
    dept_name_map["sales"] = "기술영업팀"
    dept_name_map["dept_1a0a878496f"] = "생산팀"

    # email -> profile
    by_email = {}
    # base_name -> email
    name_to_email = {}

    def register(email, name, org, avatar=None):
        email_clean = (email or "").strip().lower()
        name_clean = (name or "").strip()
        if not name_clean or name_clean in ("Unassigned", "None", "-", "시스템", "Jira 사용자"):
            return

        base = assignee_base_name(name_clean)
        clean_org = dept_name_map.get(org, org or "연구소")

        if email_clean:
            if email_clean not in by_email:
                by_email[email_clean] = {
                    "email": email_clean,
                    "canonical_name": name_clean,
                    "base_name": base,
                    "dept": clean_org,
                    "avatar": avatar
                }
            else:
                prof = by_email[email_clean]
                # Prefer name with title e.g. "최성호 팀장" > "최성호"
                if len(name_clean) > len(prof["canonical_name"]):
                    prof["canonical_name"] = name_clean
                if avatar:
                    if is_custom_avatar(avatar) or not prof.get("avatar") or not is_custom_avatar(prof.get("avatar")):
                        prof["avatar"] = avatar
                if clean_org and clean_org != "연구소":
                    prof["dept"] = clean_org

            if base:
                name_to_email[base] = email_clean
            name_to_email[name_clean] = email_clean
        else:
            if base and base not in name_to_email:
                name_to_email[base] = None

    # 1. Accounts
    for u in query("SELECT email, name, dept_id FROM users WHERE disabled = 0"):
        register(u.get("email"), u.get("name"), u.get("dept_id"))

    # 2. Schedule
    for ev in read_schedule():
        register(ev.get("ownerEmail"), ev.get("ownerName"), ev.get("ownerOrg"))

    # 3. Records
    for rec in read_records():
        register(rec.get("assigneeEmail"), rec.get("assignee"), rec.get("org"))

    # 4. Jira Activities (to grab Jira Cloud avatars and link author names to email)
    if jira_activities:
        for ja in jira_activities:
            a_name = ja.get("author_name")
            a_avatar = ja.get("author_avatar")
            if a_name:
                base = assignee_base_name(a_name)
                # If we know the email for this base_name, enrich avatar
                if base in name_to_email and name_to_email[base]:
                    em = name_to_email[base]
                    if em in by_email and a_avatar:
                        if is_custom_avatar(a_avatar) or not by_email[em].get("avatar") or not is_custom_avatar(by_email[em].get("avatar")):
                            by_email[em]["avatar"] = a_avatar
                else:
                    register(None, a_name, ja.get("assignee_dept"), a_avatar)

    return by_email, name_to_email, dept_name_map


def normalize_activity_identity(act, by_email, name_to_email, dept_name_map):
    """Normalize activity worker info using Email-centric identity master."""
    author = (act.get("author_name") or "").strip()
    email = (act.get("author_email") or "").strip().lower()
    dept = act.get("assignee_dept") or ""

    profile = None
    # 1. Try finding by email
    if email and email in by_email:
        profile = by_email[email]
    # 2. Try finding by author name / base name
    if not profile and author:
        base = assignee_base_name(author)
        mapped_email = name_to_email.get(author) or name_to_email.get(base)
        if mapped_email and mapped_email in by_email:
            profile = by_email[mapped_email]

    if profile:
        act["author_name"] = profile["canonical_name"]
        act["author_email"] = profile["email"]
        act["assignee_dept"] = profile["dept"]
        # If profile has a real custom photo, always prioritize it over fallback gravatar/placeholders
        if profile.get("avatar"):
            if not act.get("author_avatar") or not is_custom_avatar(act.get("author_avatar")):
                act["author_avatar"] = profile["avatar"]
    else:
        # Standardize department label even if email not found
        act["assignee_dept"] = dept_name_map.get(dept, dept or "연구소")

    return act


def get_daily_activities(target_date=None):
    """Fetch JARVIS's own work activities and history for a given date (YYYY-MM-DD).
    Strictly isolated to JARVIS records, schedule events, and logged activities.
    """
    if not target_date:
        target_date = datetime.now().strftime("%Y-%m-%d")

    activities = []
    seen_ids = set()

    # 1. Activities logged explicitly in JARVIS (activities.jsonl)
    for a in read_activities_log():
        created_at = a.get("created_at", "")
        if created_at.startswith(target_date):
            act_id = a.get("id") or f"act_{len(activities)}"
            if act_id not in seen_ids:
                seen_ids.add(act_id)
                activities.append(a)

    # 2. JARVIS Work Records (records.jsonl)
    try:
        records = read_records()
        for r in records:
            rec_id = r.get("id", 0)
            created_ts = ""
            if isinstance(rec_id, (int, float)) and rec_id > 1000000000000:
                try:
                    created_ts = datetime.fromtimestamp(rec_id / 1000).strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    pass
            if not created_ts and r.get("createdAt"):
                created_ts = parse_iso_timestamp(r.get("createdAt"))
            if not created_ts:
                r_date = r.get("date", "")
                created_ts = f"{r_date} 09:00:00" if r_date else ""

            if created_ts and created_ts.startswith(target_date):
                jira_info = r.get("jira") or {}
                key = jira_info.get("key") or f"REC-{rec_id % 10000}"

                detail_text = r.get("category", "")
                if r.get("summary"):
                    detail_text += " · " + r.get("summary")[:80]
                elif r.get("memo"):
                    detail_text += " · " + r.get("memo")[:80]

                act_rec_id = f"jarvis_rec_{rec_id}"
                if act_rec_id not in seen_ids:
                    seen_ids.add(act_rec_id)
                    activities.append({
                        "id": act_rec_id,
                        "issue_key": key,
                        "action_type": "created",
                        "action_detail": detail_text,
                        "author_name": r.get("assignee") or "사용자",
                        "author_email": r.get("assigneeEmail") or "",
                        "author_id": None,
                        "author_avatar": None,
                        "created_at": created_ts,
                        "summary": r.get("title") or r.get("summary") or key,
                        "status": jira_info.get("statusName") or "완료",
                        "priority": "보통",
                        "issue_type": r.get("category") or "업무기록",
                        "assignee_name": r.get("assignee"),
                        "assignee_dept": r.get("org") or "연구소",
                        "source": "jarvis"
                    })

                # If record has attachments, record attachment action
                att_files = r.get("attachments") or []
                if att_files:
                    att_id = f"jarvis_att_{rec_id}"
                    if att_id not in seen_ids:
                        seen_ids.add(att_id)
                        activities.append({
                            "id": att_id,
                            "issue_key": key,
                            "action_type": "attachment",
                            "action_detail": "\n".join(a.get("name", "") if isinstance(a, dict) else str(a) for a in att_files),
                            "author_name": r.get("assignee") or "사용자",
                            "author_email": r.get("assigneeEmail") or "",
                            "author_id": None,
                            "author_avatar": None,
                            "created_at": created_ts,
                            "summary": r.get("title") or r.get("summary") or key,
                            "status": jira_info.get("statusName") or "완료",
                            "priority": "보통",
                            "issue_type": r.get("category") or "업무기록",
                            "assignee_name": r.get("assignee"),
                            "assignee_dept": r.get("org") or "연구소",
                            "source": "jarvis"
                        })
    except Exception:
        pass

    # 3. JARVIS Schedule Events (schedule.json)
    try:
        schedule_events = read_schedule()
        for ev in schedule_events:
            s_date = ev.get("startDate") or ev.get("date") or ""
            e_date = ev.get("endDate") or s_date
            created_ts = parse_iso_timestamp(ev.get("createdAt")) if ev.get("createdAt") else ""
            if not created_ts and s_date:
                created_ts = f"{s_date} 09:00:00"

            if (created_ts and created_ts.startswith(target_date)) or s_date == target_date:
                ev_id = f"sched_{ev.get('id')}"
                if ev_id not in seen_ids:
                    seen_ids.add(ev_id)
                    activities.append({
                        "id": ev_id,
                        "issue_key": f"SCHED-{str(ev.get('id', ''))[:6]}",
                        "action_type": "schedule",
                        "action_detail": f"schedule:{s_date} ~ {e_date}" if s_date != e_date else f"schedule:{s_date}",
                        "author_name": ev.get("ownerName") or "사용자",
                        "author_email": ev.get("ownerEmail") or "",
                        "author_id": None,
                        "author_avatar": None,
                        "created_at": created_ts,
                        "summary": ev.get("title") or ev.get("memo") or "일정",
                        "status": "진행",
                        "priority": "보통",
                        "issue_type": ev.get("type") or "일정",
                        "assignee_name": ev.get("ownerName"),
                        "assignee_dept": ev.get("ownerOrg") or "연구소",
                        "source": "jarvis_schedule"
                    })
    except Exception:
        pass

    # 4. Jira Operation History (Changelog synced from Jira Cloud)
    jira_activities = []
    try:
        from services.jira_client import get_cached_jira_activities
        from config import load_config
        cfg = load_config()
        jira_activities = get_cached_jira_activities(cfg)
        
        # Build index of local JARVIS activities for author reconciliation:
        # Lưu các hành động nội bộ cùng timestamp (giây) để đối chiếu cửa sổ thời gian trượt (Time Window)
        local_intents = []
        for la in activities:
            l_key = la.get("issue_key")
            l_type = la.get("action_type")
            l_author = la.get("author_name")
            l_source = la.get("source") or "jarvis"
            l_created = la.get("created_at") or ""
            if l_key and l_author and l_created:
                try:
                    dt = datetime.strptime(l_created[:19], "%Y-%m-%d %H:%M:%S")
                    ts = dt.timestamp()
                except Exception:
                    ts = 0
                local_intents.append({
                    "key": l_key,
                    "type": l_type,
                    "author": l_author,
                    "source": l_source,
                    "ts": ts
                })

        for ja in jira_activities:
            c_at = ja.get("created_at") or ""
            if c_at.startswith(target_date):
                ja_id = ja.get("id")
                if ja_id not in seen_ids:
                    seen_ids.add(ja_id)
                    # Check if this Jira action was initiated by a local JARVIS user
                    j_key = ja.get("issue_key")
                    j_type = ja.get("action_type")
                    j_ts = 0
                    try:
                        j_dt = datetime.strptime(c_at[:19], "%Y-%m-%d %H:%M:%S")
                        j_ts = j_dt.timestamp()
                    except Exception:
                        pass
                    
                    real_author = None
                    real_source = "jarvis"
                    if j_key and j_ts:
                        # Tìm bản ghi local khớp key trong cửa sổ lệch thời gian ±180 giây (3 phút)
                        # Ưu tiên khớp cả action_type và có khoảng cách thời gian nhỏ nhất
                        best_diff = 181
                        for li in local_intents:
                            if li["key"] == j_key and li["ts"]:
                                diff = abs(j_ts - li["ts"])
                                if diff <= 180:
                                    # Khớp chính xác cả loại hành động
                                    if li["type"] == j_type and diff < best_diff:
                                        real_author = li["author"]
                                        real_source = li.get("source") or "jarvis"
                                        best_diff = diff
                                    # Hoặc khớp theo mã thẻ gần nhất nếu chưa tìm được type
                                    elif not real_author and diff < best_diff:
                                        real_author = li["author"]
                                        real_source = li.get("source") or "jarvis"
                                        best_diff = diff
                    
                    if real_author:
                        ja["author_name"] = real_author
                        ja["source"] = real_source
                        
                    activities.append(ja)
    except Exception:
        pass

    # 5. Jira Comments from SQLite (jira_comments & jira_issues)
    try:
        comment_rows = query(
            """SELECT c.comment_id, c.jira_key, c.author_name, c.body, c.created_at,
                      i.summary, i.status_name, i.issue_type, i.assignee_name, i.dept_id
               FROM jira_comments c
               LEFT JOIN jira_issues i ON c.jira_key = i.jira_key
               WHERE c.created_at LIKE ? OR c.created_at LIKE ?""",
            (f"{target_date}%", f"{target_date.replace('-', '/')} %")
        )
        for crow in comment_rows:
            cid = crow["comment_id"]
            act_cid = f"jira_comment_{cid}"
            if act_cid not in seen_ids:
                seen_ids.add(act_cid)
                raw_created = (crow["created_at"] or "").replace("T", " ")[:19]
                activities.append({
                    "id": act_cid,
                    "issue_key": crow["jira_key"],
                    "action_type": "comment",
                    "action_detail": crow["body"] or "",
                    "author_name": crow["author_name"] or "Jira 사용자",
                    "author_email": "",
                    "author_id": None,
                    "author_avatar": None,
                    "created_at": raw_created,
                    "summary": crow["summary"] or crow["jira_key"],
                    "status": crow["status_name"] or "완료",
                    "priority": "보통",
                    "issue_type": crow["issue_type"] or "작업",
                    "assignee_name": crow["assignee_name"] or crow["author_name"],
                    "assignee_dept": crow["dept_id"] or "연구소",
                    "source": "jira"
                })
    except Exception:
        pass

    # Build Email-centric identity master & normalize all activities
    try:
        by_email, name_to_email, dept_name_map = build_member_identity_master(jira_activities)
        for a in activities:
            normalize_activity_identity(a, by_email, name_to_email, dept_name_map)
    except Exception as e:
        pass

    # Sort DESC by exact timestamp
    activities.sort(key=lambda a: a.get("created_at", ""), reverse=True)

    # Group multiple attachments uploaded/deleted in the same minute for the same issue and author into 1 row
    grouped_activities = []
    attach_group_map = {}

    for act in activities:
        # Filter out redundant Jira resolution updates
        detail = (act.get("action_detail") or "").lower()
        if "resolution:" in detail or detail.startswith("해결책:") or detail.startswith("해결:"):
            continue

        act_type = act.get("action_type")
        if act_type in ("attachment", "attachment_deleted"):
            created_at = act.get("created_at") or ""
            minute_time = created_at[:16] if len(created_at) >= 16 else created_at
            group_key = f"{act.get('issue_key')}_{act_type}_{act.get('author_name') or ''}_{minute_time}"

            if group_key in attach_group_map:
                group_act = attach_group_map[group_key]
                if "files" not in group_act:
                    group_act["files"] = [f for f in (group_act.get("action_detail") or "").split("\n") if f]
                curr_file = act.get("action_detail") or ""
                for line in curr_file.split("\n"):
                    line = line.strip()
                    if line and line not in group_act["files"]:
                        group_act["files"].append(line)
                group_act["action_detail"] = "\n".join(group_act["files"])
            else:
                copy_act = dict(act)
                lines = [f for f in (copy_act.get("action_detail") or "").split("\n") if f]
                copy_act["files"] = lines
                attach_group_map[group_key] = copy_act
                grouped_activities.append(copy_act)
        else:
            grouped_activities.append(act)

    return grouped_activities


def get_recent_activity_dates(limit=10):
    """Return dates with activity records and their counts strictly from JARVIS & Jira Changelog"""
    dates_map = {}

    # Check activities.jsonl
    for a in read_activities_log():
        d = (a.get("created_at") or "")[:10]
        if d:
            dates_map[d] = dates_map.get(d, 0) + 1

    # Check records.jsonl with real timestamps
    try:
        for r in read_records():
            rec_id = r.get("id", 0)
            created_ts = ""
            if isinstance(rec_id, (int, float)) and rec_id > 1000000000000:
                try:
                    created_ts = datetime.fromtimestamp(rec_id / 1000).strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    pass
            if not created_ts and r.get("createdAt"):
                created_ts = parse_iso_timestamp(r.get("createdAt"))
            if not created_ts:
                r_date = r.get("date", "")
                created_ts = f"{r_date} 09:00:00" if r_date else ""
            d = created_ts[:10]
            if d:
                dates_map[d] = dates_map.get(d, 0) + 1
    except Exception:
        pass

    # Check schedule.json
    try:
        for ev in read_schedule():
            d = (ev.get("startDate") or ev.get("date") or "")[:10]
            if not d and ev.get("createdAt"):
                d = parse_iso_timestamp(ev.get("createdAt"))[:10]
            if d:
                dates_map[d] = dates_map.get(d, 0) + 1
    except Exception:
        pass

    # Check Jira Changelog activities
    try:
        from services.jira_client import get_cached_jira_activities
        from config import load_config
        cfg = load_config()
        for ja in get_cached_jira_activities(cfg):
            d = (ja.get("created_at") or "")[:10]
            if d:
                dates_map[d] = dates_map.get(d, 0) + 1
    except Exception:
        pass

    # Check Jira Comments from SQLite
    try:
        c_dates = query("SELECT substr(created_at, 1, 10) as c_date, count(*) as cnt FROM jira_comments GROUP BY substr(created_at, 1, 10)")
        for crow in c_dates:
            d = crow["c_date"]
            if d:
                dates_map[d] = dates_map.get(d, 0) + crow["cnt"]
    except Exception:
        pass

    sorted_dates = sorted([{"date": d, "count": c} for d, c in dates_map.items()], key=lambda x: x["date"], reverse=True)
    return sorted_dates[:limit]
