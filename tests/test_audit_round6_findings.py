# -*- coding: utf-8 -*-
"""Regression tests for audit round 6 findings.

1. find_record_by_key_or_code() falls back to the jira_issues cache; local-only
   mutation paths must not treat a cached Jira issue as a local record.
2. Pushing a local card WITH attachments to Jira must not crash.
3. update_record_details(): a partial date update must keep the other date.
4. Local comments are writes: blocked while the system is read-only.
5. _stream_file(): RFC 7233 suffix ranges (bytes=-N) return the LAST N bytes.
6. WSGI handler: X-Forwarded-Proto is honoured only from a trusted proxy.
"""
import io
import json
import os
import sys
from unittest.mock import patch



SERVER_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server")
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)


class _Handler:
    """Minimal handler double (adds request headers to the conftest MockHandler idea)."""

    def __init__(self, session, cfg=None, headers=None):
        self._session = session
        self.cfg = cfg or {}
        self.headers = headers or {}
        self.code = None
        self.body = None

    def _send_json(self, code, data, extra_headers=None):
        self.code = code
        self.body = data

    def _get_session_or_401(self):
        if not self._session:
            self._send_json(401, {"ok": False})
            return None
        return self._session

    def _get_session_optional(self):
        return self._session

    def _extract_token(self):
        return ""


def _session_for(seed):
    from services.auth import get_session
    sess = get_session(seed["session"])
    assert sess, "seed session must be valid"
    return sess


def _seed_jira_only_issue(key="SCRUM-5", org="dev", assignee="관리자"):
    from services.jira_db import upsert_jira_records
    upsert_jira_records([{
        "id": f"jira-{key}",
        "title": "Jira only issue",
        "org": org,
        "assignee": assignee,
        "startDate": "2026-11-01",
        "dueDate": "2026-11-05",
        "jira": {"key": key, "status": "진행", "summary": "Jira only issue"},
    }])


def _seed_local_record(dept="dev", assignee="관리자", start="2026-11-01", due="2026-11-20",
                       attachments=None, card_code="DEV-900"):
    from services.data_store import append_record, next_record_id
    rec_id = next_record_id()
    append_record({
        "id": rec_id, "org": dept, "category": "기능개발", "title": "local card",
        "assignee": assignee, "startDate": start, "dueDate": due,
        "cardCode": card_code, "attachments": attachments or [],
    })
    return rec_id


# ---------------------------------------------------------------------------
# 1. Jira cache fallback must not leak into local mutations
# ---------------------------------------------------------------------------
def test_update_work_date_does_not_report_success_for_jira_only_issue(seed_admin):
    from services.data_store import update_record_work_date, clear_record_work_date, \
        set_record_schedule_visibility
    _seed_jira_only_issue()
    assert update_record_work_date("SCRUM-5", "2026-12-01") == (None, None)
    assert clear_record_work_date("SCRUM-5") == (None, None)
    assert set_record_schedule_visibility("SCRUM-5", True) == (None, None)


def test_rbac_lookup_still_resolves_jira_cache(seed_admin):
    """The fix must not change RBAC resolution (resolve_record_by_key)."""
    from services.auth import resolve_record_by_key
    _seed_jira_only_issue()
    rec = resolve_record_by_key("SCRUM-5")
    assert rec and rec.get("id") == "jira-SCRUM-5"


def test_assign_schedule_task_jira_only_issue_is_not_a_silent_success(seed_admin):
    import router
    _seed_jira_only_issue()
    h = _Handler(_session_for(seed_admin), cfg={"jira": {"enabled": False}})
    with patch("services.license_manager.is_system_read_only", return_value=False):
        router.handle_assign_schedule_task(h, json.dumps({"taskId": "SCRUM-5", "date": "2026-12-01"}).encode(), "127.0.0.1")
    assert h.code == 404, h.body


def test_delete_record_jira_only_issue_is_not_a_silent_success(seed_admin):
    import router
    _seed_jira_only_issue()
    h = _Handler(_session_for(seed_admin))
    with patch("services.license_manager.is_system_read_only", return_value=False), \
            patch.object(router, "delete_vector_document", lambda *_a, **_k: None):
        router.handle_delete_record(h, json.dumps({"key": "SCRUM-5"}).encode(), "127.0.0.1")
    assert h.code == 404, h.body


def test_attachment_upload_for_cached_jira_issue_goes_to_jira(seed_admin, tmp_path):
    import router
    _seed_jira_only_issue()
    boundary = "XBOUNDARYX"
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"issue_key\"\r\n\r\nSCRUM-5\r\n"
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"a.txt\"\r\n"
        f"Content-Type: text/plain\r\n\r\nhello\r\n--{boundary}--\r\n"
    ).encode()
    h = _Handler(_session_for(seed_admin),
                 cfg={"jira": {"enabled": True, "api_token": "x"}},
                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    uploads = []
    with patch("services.license_manager.is_system_read_only", return_value=False), \
            patch.object(router, "ATTACH_DIR", str(tmp_path)), \
            patch.object(router, "upload_jira_attachment",
                         lambda cfg, key, name, data, ctype: (uploads.append((key, name)) or {"ok": True}, None)), \
            patch("services.jira_client.resolve_jira_record_for_auth",
                  return_value={"dept_id": "dev", "assignee_name": "관리자"}):
        router.handle_post_issue_attachment(h, body, "127.0.0.1")
    assert h.code == 200, h.body
    assert uploads == [("SCRUM-5", "a.txt")]
    assert not os.path.exists(os.path.join(str(tmp_path), "jira-SCRUM-5"))


# ---------------------------------------------------------------------------
# 2. Push local card with attachments to Jira
# ---------------------------------------------------------------------------
def test_push_local_record_with_attachments_to_jira(seed_admin, tmp_path):
    import router
    from services.data_store import find_record_by_key_or_code
    rec_id = _seed_local_record(attachments=["spec.pdf"])
    os.makedirs(os.path.join(str(tmp_path), str(rec_id)))
    with open(os.path.join(str(tmp_path), str(rec_id), "spec.pdf"), "wb") as fh:
        fh.write(b"%PDF-1.4")
    rec = find_record_by_key_or_code(rec_id)
    assert rec["attachments"] and isinstance(rec["attachments"][0], dict)

    created, uploaded = {}, []

    def fake_create(cfg, project_key, issue_type, title, description, labels, **kw):
        created["description"] = description
        return {"key": "SCRUM-99", "url": "https://jira/browse/SCRUM-99"}, "ok"

    with patch.object(router, "ATTACH_DIR", str(tmp_path)), \
            patch.object(router, "jira_project_for_dept", lambda cfg, d: ("SCRUM", "Task")), \
            patch.object(router, "get_cached_categories", lambda cfg, d: ["Task"]), \
            patch.object(router, "jira_fetch_project_categories", lambda cfg, p: ["Task"]), \
            patch.object(router, "lookup_jira_account_id", lambda cfg, v: None), \
            patch.object(router, "create_jira_issue", fake_create), \
            patch.object(router, "upload_jira_attachment",
                         lambda cfg, key, name, data, ctype: uploaded.append(name) or ({}, None)), \
            patch.object(router, "add_jira_comment", lambda *a, **k: ({}, None)):
        res, err = router._push_single_local_record_to_jira({"jira": {}}, _session_for(seed_admin), rec)
    assert err is None and res["key"] == "SCRUM-99"
    assert "spec.pdf" in created["description"]
    assert uploaded == ["spec.pdf"]


# ---------------------------------------------------------------------------
# 3. Partial date update keeps the other stored date
# ---------------------------------------------------------------------------
def test_partial_due_date_update_keeps_start_date(seed_admin):
    from services.data_store import update_record_details, get_record_by_id
    rec_id = _seed_local_record(start="2026-11-01", due="2026-11-20")
    updated, err = update_record_details(rec_id, due_date="2026-11-25")
    assert not err
    rec = get_record_by_id(rec_id)
    assert rec["startDate"] == "2026-11-01"
    assert rec["dueDate"] == "2026-11-25"


def test_partial_start_date_update_keeps_due_date(seed_admin):
    from services.data_store import update_record_details, get_record_by_id
    rec_id = _seed_local_record(start="2026-11-01", due="2026-11-20")
    update_record_details(rec_id, start_date="2026-11-03")
    rec = get_record_by_id(rec_id)
    assert rec["startDate"] == "2026-11-03"
    assert rec["dueDate"] == "2026-11-20"


# ---------------------------------------------------------------------------
# 4. Local comment is blocked in read-only (expired licence) mode
# ---------------------------------------------------------------------------
def test_local_comment_blocked_when_read_only(seed_admin):
    import router
    from services.data_store import get_record_comments
    rec_id = _seed_local_record()
    h = _Handler(_session_for(seed_admin))
    with patch("services.license_manager.is_system_read_only", return_value=True):
        router.handle_post_issue_comment(h, json.dumps({"issue_key": str(rec_id), "comment": "hi"}).encode(), "127.0.0.1")
    assert h.code == 403, h.body
    assert get_record_comments(rec_id) == []


# ---------------------------------------------------------------------------
# 5. HTTP Range suffix requests
# ---------------------------------------------------------------------------
class _StreamProbe:
    """ArgosHandler._stream_file bound to a fake socket."""

    def __init__(self, range_header):
        from handler import ArgosHandler
        self.h = object.__new__(ArgosHandler)
        self.h.headers = {"Range": range_header} if range_header else {}
        self.h.wfile = io.BytesIO()
        self.status = None
        self.sent = {}
        self.h.send_response = lambda code, msg=None: setattr(self, "status", code)
        self.h.send_header = lambda k, v: self.sent.__setitem__(k, v)
        self.h.end_headers = lambda: None


def test_range_suffix_returns_last_bytes(tmp_path):
    p = tmp_path / "f.bin"
    p.write_bytes(b"0123456789")
    probe = _StreamProbe("bytes=-4")
    probe.h._stream_file(str(p), "application/octet-stream")
    assert probe.status == 206
    assert probe.sent["Content-Range"] == "bytes 6-9/10"
    assert probe.h.wfile.getvalue() == b"6789"


def test_range_regular_and_open_ended_unchanged(tmp_path):
    p = tmp_path / "f.bin"
    p.write_bytes(b"0123456789")
    probe = _StreamProbe("bytes=2-4")
    probe.h._stream_file(str(p), "application/octet-stream")
    assert probe.h.wfile.getvalue() == b"234"
    probe = _StreamProbe("bytes=7-")
    probe.h._stream_file(str(p), "application/octet-stream")
    assert probe.h.wfile.getvalue() == b"789"


# ---------------------------------------------------------------------------
# 6. WSGI: X-Forwarded-Proto only from trusted proxies
# ---------------------------------------------------------------------------
def _wsgi_handler(remote_addr, xfp):
    from wsgi import ArgosWSGIHandler
    environ = {"REQUEST_METHOD": "GET", "PATH_INFO": "/", "REMOTE_ADDR": remote_addr,
               "wsgi.url_scheme": "http", "HTTP_X_FORWARDED_PROTO": xfp, "wsgi.input": io.BytesIO()}
    return ArgosWSGIHandler(environ, lambda status, headers: (lambda data: None))


def test_wsgi_forwarded_proto_ignored_from_untrusted_peer(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXIES", "127.0.0.1,::1")
    assert _wsgi_handler("10.9.8.7", "https")._is_secure() is False


def test_wsgi_forwarded_proto_honoured_from_trusted_proxy(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXIES", "127.0.0.1,::1")
    assert _wsgi_handler("127.0.0.1", "https")._is_secure() is True


# ---------------------------------------------------------------------------
# 7. AI chat write tools: Jira cache rows are not local rows; remote writes fail closed
# ---------------------------------------------------------------------------
def test_chat_comment_on_cached_jira_issue_goes_to_jira(seed_admin):
    from services import chat_tools
    _seed_jira_only_issue()
    sent = []
    with patch("services.license_manager.is_system_read_only", return_value=False), \
            patch("services.jira_client.add_jira_comment", lambda cfg, key, body, author=None: sent.append(key) or ({"id": "1"}, None)), \
            patch("services.jira_client.sync_jira_cache", lambda *a, **k: None):
        res = chat_tools.execute_tool("add_issue_comment", {"issue_key": "SCRUM-5", "comment": "hi"},
                                      _session_for(seed_admin), {"jira": {"enabled": True}}, allow_write=True)
    assert sent == ["SCRUM-5"], res


def test_chat_status_on_unresolvable_jira_issue_fails_closed(seed_user):
    from services import chat_tools
    called = []
    with patch("services.license_manager.is_system_read_only", return_value=False), \
            patch("services.jira_client.resolve_jira_record_for_auth", return_value=None), \
            patch("services.jira_client.transition_jira_issue", lambda *a, **k: called.append(a) or (True, "ok")):
        res = chat_tools.execute_tool("update_issue_status", {"issue_key": "OTHER-1", "status": "진행"},
                                      _session_for(seed_user), {"jira": {"enabled": True}}, allow_write=True)
    assert called == [] and res.get("success") is False


def test_chat_schedule_blocked_when_read_only(seed_admin):
    from services import chat_tools
    with patch("services.license_manager.is_system_read_only", return_value=True):
        res = chat_tools.execute_tool("schedule_issue", {"issue_key": "DEV-900", "start_date": "2026-12-01"},
                                      _session_for(seed_admin), {"jira": {"enabled": False}}, allow_write=True)
    assert res.get("success") is False and "읽기 전용" in res.get("error", "")


# ---------------------------------------------------------------------------
# 8. Account / admin user management
# ---------------------------------------------------------------------------
def _make_user(name, username, org, disabled=0, email=""):
    from services.auth import hash_password, create_user, create_session
    salt, h_ = hash_password("Passw0rd!x")
    u = create_user(name=name, username=username, org=org, email=email, salt=salt, hash_pwd=h_,
                    role="member", status="active", disabled=disabled)
    return u, create_session(u["name"], org=org, email=email, user_id=u["id"])


def test_password_change_does_not_revoke_homonym_sessions(seed_user):
    from handlers.auth_handlers import handle_account_update_profile
    from services.auth import get_session
    _other, other_token = _make_user("테스트유저", "homonym_hr", "hr")
    h = _Handler(_session_for(seed_user))
    h._extract_token = lambda: seed_user["session"]
    handle_account_update_profile(h, json.dumps({
        "current_password": seed_user["password"], "password": "NewPassw0rd!", "confirm_password": "NewPassw0rd!"}).encode(), "127.0.0.1")
    assert h.code == 200, h.body
    assert get_session(other_token), "a same-name user in another department must stay logged in"


def test_csrf_endpoint_requires_live_session():
    from handlers.auth_handlers import handle_account_csrf
    h = _Handler(None)
    h._extract_token = lambda: "not-a-real-session-token"
    handle_account_csrf(h, None, "127.0.0.1")
    assert h.code == 401


def test_admin_reenable_user_respects_seat_limit(seed_admin):
    import router
    u, _ = _make_user("잠금사용자", "lockeduser", "dev", disabled=1)
    h = _Handler(_session_for(seed_admin))
    with patch("services.license_manager.check_seat_available", return_value=(False, "seat full")):
        router.handle_post_admin_user_update(h, json.dumps({"id": u["id"], "disabled": 0}).encode(), "127.0.0.1")
    assert h.code == 403


def test_admin_can_disable_and_delete_same_name_user(seed_admin):
    import router
    u, _ = _make_user("관리자", "hr_homonym", "hr")
    h = _Handler(_session_for(seed_admin))
    router.handle_post_admin_user_update(h, json.dumps({"id": u["id"], "disabled": 1}).encode(), "127.0.0.1")
    assert h.code == 200, h.body
    h = _Handler(_session_for(seed_admin))
    router.handle_post_admin_user_delete(h, json.dumps({"id": u["id"]}).encode(), "127.0.0.1")
    assert h.code == 200, h.body


# ---------------------------------------------------------------------------
# 9. Leave approval cannot be bypassed by editing an event
# ---------------------------------------------------------------------------
def _sched(handler_fn, session, payload):
    h = _Handler(session)
    with patch("services.license_manager.is_system_read_only", return_value=False):
        handler_fn(h, json.dumps(payload).encode(), "127.0.0.1")
    return h


def test_changing_meeting_into_leave_requires_approval(seed_user):
    from handlers.schedule_handlers import handle_schedule_create, handle_schedule_update
    me = _session_for(seed_user)
    ev = _sched(handle_schedule_create, me, {"title": "sync", "type": "회의", "startDate": "2026-12-01"}).body["event"]
    assert ev["approval_status"] == "approved"
    h = _sched(handle_schedule_update, me, {"id": ev["id"], "title": "sync", "type": "연차",
                                            "startDate": "2026-12-01", "endDate": "2026-12-14"})
    assert h.code == 200 and h.body["event"]["approval_status"] == "pending"


def test_extending_approved_leave_requires_reapproval(seed_user, seed_admin):
    from handlers.schedule_handlers import handle_schedule_create, handle_schedule_update, handle_schedule_approve
    me, admin = _session_for(seed_user), _session_for(seed_admin)
    ev = _sched(handle_schedule_create, me, {"title": "휴가", "type": "연차", "startDate": "2026-12-01"}).body["event"]
    assert _sched(handle_schedule_approve, admin, {"id": ev["id"], "action": "approve"}).body["event"]["approval_status"] == "approved"
    h = _sched(handle_schedule_update, me, {"id": ev["id"], "title": "휴가", "type": "연차",
                                            "startDate": "2026-12-01", "endDate": "2026-12-14"})
    assert h.body["event"]["approval_status"] == "pending"
    # title-only edits keep the approval
    ev2 = _sched(handle_schedule_approve, admin, {"id": ev["id"], "action": "approve"}).body["event"]
    h = _sched(handle_schedule_update, me, {"id": ev["id"], "title": "휴가(수정)", "type": "연차",
                                            "startDate": ev2["startDate"], "endDate": ev2["endDate"]})
    assert h.body["event"]["approval_status"] == "approved"


# ---------------------------------------------------------------------------
# 10. Submit, PIM detail masking, backup import
# ---------------------------------------------------------------------------
def test_submit_same_named_files_do_not_overwrite(seed_user, tmp_path):
    from handlers import submit_handler
    b = "SUBMITBOUNDARY"
    parts = [f'--{b}\r\nContent-Disposition: form-data; name="org"\r\n\r\ndev\r\n',
             f'--{b}\r\nContent-Disposition: form-data; name="title"\r\n\r\nt\r\n',
             f'--{b}\r\nContent-Disposition: form-data; name="category"\r\n\r\n기타업무\r\n',
             f'--{b}\r\nContent-Disposition: form-data; name="f1"; filename="a.txt"\r\nContent-Type: text/plain\r\n\r\none\r\n',
             f'--{b}\r\nContent-Disposition: form-data; name="f2"; filename="a.txt"\r\nContent-Type: text/plain\r\n\r\ntwo\r\n',
             f'--{b}--\r\n']
    h = _Handler(_session_for(seed_user), cfg={"jira": {"enabled": False}, "ai": {"enabled": False}},
                 headers={"Content-Type": f"multipart/form-data; boundary={b}"})
    att = tmp_path / "att"
    att.mkdir()
    with patch.object(submit_handler, "ATTACH_DIR", str(att)), \
            patch("services.license_manager.is_system_read_only", return_value=False):
        submit_handler.handle_submit(h, "".join(parts).encode(), "127.0.0.1")
    assert h.code == 200, h.body
    rec_dir = os.path.join(str(att), str(h.body["record"]["id"]))
    contents = sorted(open(os.path.join(rec_dir, f), "rb").read() for f in os.listdir(rec_dir))
    assert contents == [b"one", b"two"]


def test_product_detail_masks_price_like_spec_keys(seed_user):
    import router
    from urllib.parse import urlsplit
    from services.data_store import save_product_category, write_products
    save_product_category(None, "견적부품", [{"key": "unitPrice", "label": "단가"}])
    write_products([{"id": "P-t1", "model": "M1", "displayName": "M1", "category": "견적부품",
                     "specs": {"unitPrice": "123000", "color": "red"}, "createdAt": "x", "updatedAt": "x"}])
    h = _Handler(_session_for(seed_user))
    router.handle_get_product_detail(h, urlsplit("/api/products/detail?id=P-t1"), "127.0.0.1")
    specs = h.body["detail"]["specs"]
    assert specs["unitPrice"] == 0 and specs["color"] == "red"


def test_backup_import_ignores_database_like_attachments(tmp_path):
    import sqlite3
    import tarfile
    from services import backup_manager
    is_pg = (backup_manager.ENGINE == "postgres")
    top_db_name = "argos.dump" if is_pg else "argos.db"
    dbp = tmp_path / top_db_name
    if is_pg:
        dbp.write_bytes(b"PGDMP\x01\x00\x00")
    else:
        conn = sqlite3.connect(str(dbp))
        conn.execute("CREATE TABLE users(id INTEGER)")
        conn.commit()
        conn.close()
    tarp = tmp_path / "b.tar.gz"
    with tarfile.open(str(tarp), "w:gz") as t:
        t.add(str(dbp), arcname=top_db_name)
        data = b"user attachment, not a database"
        ti = tarfile.TarInfo("attachments/123/sample.dump" if not is_pg else "attachments/123/sample.db")
        ti.size = len(data)
        t.addfile(ti, io.BytesIO(data))
    bdir = tmp_path / "bk"
    bdir.mkdir()
    with patch.object(backup_manager, "get_backup_dir", lambda: str(bdir)), \
            patch("subprocess.run", lambda *a, **k: type("SubProc", (), {"returncode": 0, "stderr": ""})()):
        res = backup_manager.import_backup_file(tarp.read_bytes(), "b.tar.gz")
    assert res["ok"]


# ---------------------------------------------------------------------------
# 11. Cross-department name-only matching on PUBLIC records: allowed only when
#     the name is not shared by 2+ active accounts (view, modify, transition)
# ---------------------------------------------------------------------------
def _rec(dept, assignee, private=0, participants=""):
    return {"dept_id": dept, "assignee_name": assignee, "is_private": private, "participants": participants}


def test_cross_dept_name_match_allowed_when_name_is_unique(tmp_db):
    from services.auth import get_session, can_view_record, can_modify_record
    _u, tok = _make_user("고유이름", "unique_name_dev", "dev")
    sess = get_session(tok)
    rec = _rec("sales", "고유이름")
    assert can_view_record(sess, rec) is True
    assert can_modify_record(sess, rec) is True


def test_cross_dept_name_match_denied_when_name_is_shared(tmp_db):
    from services.auth import get_session, can_view_record, can_modify_record, can_transition_status
    _a, ta = _make_user("Minh", "minh_dev", "dev")
    _b, tb = _make_user("Minh", "minh_hr", "hr")
    sa, sb = get_session(ta), get_session(tb)
    pub = _rec("sales", "Minh")
    for sess in (sa, sb):
        assert can_view_record(sess, pub) is False
        assert can_modify_record(sess, pub) is False
        assert can_transition_status(sess, pub, "검토")[0] is False
    # participant-name matching follows the same rule
    assert can_view_record(sa, _rec("sales", "Other", participants="Minh")) is False
    # same-department name matching is unchanged
    assert can_view_record(sa, _rec("dev", "Minh")) is True
    assert can_modify_record(sa, _rec("dev", "Minh")) is True
    # private records: still same-department only (unchanged)
    assert can_view_record(sa, _rec("sales", "Minh", private=1)) is False


def test_inactive_homonyms_do_not_block_access(tmp_db):
    from db import execute
    from services.auth import get_session, can_view_record
    _a, ta = _make_user("Linh", "linh_dev", "dev")
    _make_user("Linh", "linh_hr", "hr", disabled=1)
    c, _tc = _make_user("Linh", "linh_sales", "sales")
    execute("UPDATE users SET status = 'pending', disabled = 1 WHERE id = ?", (c["id"],))
    assert can_view_record(get_session(ta), _rec("hq", "Linh")) is True


def test_shared_name_detection_is_unicode_case_insensitive(tmp_db):
    from services.auth import get_session, can_view_record
    _a, ta = _make_user("Đông", "dong_dev", "dev")
    _make_user("ĐÔNG", "dong_hr", "hr")
    assert can_view_record(get_session(ta), _rec("sales", "đông")) is False


def test_visible_records_applies_shared_name_rule(tmp_db):
    from services.auth import get_session, visible_records
    _a, ta = _make_user("Minh", "minh_dev2", "dev")
    _make_user("Minh", "minh_hr2", "hr")
    _u, tu = _make_user("Unique Kim", "unique_kim", "dev")
    records = [_rec("sales", "Minh"), _rec("sales", "Unique Kim"), _rec("dev", "Someone")]
    assert visible_records(get_session(ta), records) == [records[2]]
    assert visible_records(get_session(tu), records) == [records[1], records[2]]
