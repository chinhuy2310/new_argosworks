"""
test_jira_client.py — Jira client robustness (no network required).

Regression: `_urlopen()` used to swallow urllib.URLError and return None, so
every `with _urlopen(...) as resp:` blew up with the meaningless
"'NoneType' object does not support the context manager protocol".
"""
import io
import json
import os
import sys
import urllib.error
from datetime import datetime, timedelta

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_DIR = os.path.join(BASE_DIR, "server")
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from services import jira_client  # noqa: E402


def _cfg():
    return {
        "jira": {
            "enabled": True,
            "base_url": "https://example.atlassian.net",
            "email": "user@example.com",
            "api_token": "dummy-token",
            "default_project_key": "TEST",
        }
    }


class TestUrlopenDoesNotSwallowErrors:
    def test_urlopen_reraises_urlerror(self, monkeypatch):
        def boom(*args, **kwargs):
            raise urllib.error.URLError("network down")

        monkeypatch.setattr(jira_client.urllib.request, "urlopen", boom)

        with pytest.raises(urllib.error.URLError):
            jira_client._urlopen(jira_client.urllib.request.Request("https://example.atlassian.net"))

    def test_ssl_failure_without_opt_in_is_blocked(self, monkeypatch):
        def boom(*args, **kwargs):
            raise urllib.error.URLError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")

        monkeypatch.delenv("JIRA_INSECURE_SKIP_VERIFY", raising=False)
        monkeypatch.setattr(jira_client.urllib.request, "urlopen", boom)

        with pytest.raises(urllib.error.URLError):
            jira_client._urlopen(jira_client.urllib.request.Request("https://example.atlassian.net"))


class TestCreateIssueFailsGracefully:
    def test_network_failure_returns_message_not_typeerror(self, monkeypatch):
        def boom(*args, **kwargs):
            raise urllib.error.URLError("connection reset")

        monkeypatch.setattr(jira_client.urllib.request, "urlopen", boom)

        result, note = jira_client.create_jira_issue(
            _cfg(), "TEST", "Task", "summary", "description", [], None
        )
        assert result is None
        assert "실패" in note
        assert "context manager" not in note

    def test_comment_failure_returns_tuple(self, monkeypatch):
        def boom(*args, **kwargs):
            raise urllib.error.URLError("connection reset")

        monkeypatch.setattr(jira_client.urllib.request, "urlopen", boom)

        payload, note = jira_client.add_jira_comment(_cfg(), "TEST-1", "hello")
        assert payload is None
        assert isinstance(note, str) and note


class TestSearchDegradesToCacheSignal:
    def test_search_returns_none_on_first_page_failure(self, monkeypatch):
        """None means 'lookup failed, keep previous cache' (vs [] = genuinely empty)."""
        def boom(*args, **kwargs):
            raise urllib.error.URLError("connection reset")

        monkeypatch.setattr(jira_client.urllib.request, "urlopen", boom)

        issues, activities = jira_client.jira_search_issues(_cfg(), max_results=10, page_size=10)
        assert issues is None
        assert activities is None


# ---------------------------------------------------------------------------
# Assignee resolution: Jira's /user/search is fuzzy, exact match must win
# ---------------------------------------------------------------------------
class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        import json as _json
        return _json.dumps(self._payload).encode("utf-8")


class TestAssigneeLookup:
    USERS = [
        {"accountId": "acc-wrong-1", "displayName": "김철수2", "emailAddress": "kim2@example.com"},
        {"accountId": "acc-right", "displayName": "김철수", "emailAddress": "kim@example.com"},
    ]

    def _patch(self, monkeypatch):
        monkeypatch.setattr(
            jira_client.urllib.request, "urlopen", lambda *a, **k: _FakeResponse(self.USERS)
        )

    def test_exact_display_name_wins_over_first_result(self, monkeypatch):
        self._patch(monkeypatch)
        assert jira_client.lookup_jira_account_id(_cfg(), "김철수") == "acc-right"

    def test_exact_email_wins(self, monkeypatch):
        self._patch(monkeypatch)
        assert jira_client.lookup_jira_account_id(_cfg(), "kim@example.com") == "acc-right"

    def test_fuzzy_query_falls_back_to_first_result(self, monkeypatch):
        self._patch(monkeypatch)
        assert jira_client.lookup_jira_account_id(_cfg(), "김") == "acc-wrong-1"

    def test_unknown_user_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            jira_client.urllib.request, "urlopen", lambda *a, **k: _FakeResponse([])
        )
        assert jira_client.lookup_jira_account_id(_cfg(), "없는사람") is None


# ---------------------------------------------------------------------------
# Bidirectional user aliases
# ---------------------------------------------------------------------------
class TestBidirectionalAliases:
    ALIASES = {"John Doe": "johnd", "김철수": "chulsoo.kim@company.com"}

    def _cfg(self):
        cfg = _cfg()
        cfg["jira"]["user_aliases"] = dict(self.ALIASES)
        return cfg

    def test_aliases_read_from_nested_config(self):
        assert jira_client.get_user_aliases(self._cfg()) == self.ALIASES

    def test_aliases_read_from_root_key(self):
        cfg = _cfg()
        cfg["jira"].pop("user_aliases", None)
        cfg["jira_user_aliases"] = dict(self.ALIASES)
        assert jira_client.get_user_aliases(cfg) == self.ALIASES

    # --- local -> Jira ---------------------------------------------------
    def test_local_to_jira_exact(self):
        assert jira_client.resolve_local_to_jira_query(self._cfg(), "John Doe") == "johnd"

    def test_local_to_jira_case_insensitive(self):
        assert jira_client.resolve_local_to_jira_query(self._cfg(), "john doe") == "johnd"

    def test_local_to_jira_base_name(self):
        # "김철수 대리" (chức danh) vẫn khớp alias của "김철수"
        assert jira_client.resolve_local_to_jira_query(self._cfg(), "김철수 대리") == "chulsoo.kim@company.com"

    def test_local_to_jira_without_alias_passthrough(self):
        assert jira_client.resolve_local_to_jira_query(self._cfg(), "Other Person") == "Other Person"

    # --- Jira -> local ---------------------------------------------------
    def test_jira_to_local_by_display_name(self):
        assert jira_client.resolve_jira_to_local_name(self._cfg(), "johnd") == "John Doe"

    def test_jira_to_local_by_email(self):
        assert jira_client.resolve_jira_to_local_name(
            self._cfg(), "Chulsoo", "chulsoo.kim@company.com"
        ) == "김철수"

    def test_jira_to_local_no_alias_passthrough(self):
        assert jira_client.resolve_jira_to_local_name(self._cfg(), "Random User") == "Random User"

    def test_normalize_cached_assignee_keeps_display_name(self):
        record = {"assignee": "johnd", "jira": {"key": "SCRUM-1"}}
        normalized = jira_client._normalize_cached_assignee(self._cfg(), record)
        assert normalized["assignee"] == "John Doe"
        assert normalized["jira"]["displayAssignee"] == "johnd"

    def test_lookup_uses_alias_query(self, monkeypatch):
        captured = {}

        def fake_urlopen(req, *args, **kwargs):
            captured["url"] = req.full_url
            return _FakeResponse([{"accountId": "acc-johnd", "displayName": "johnd"}])

        monkeypatch.setattr(jira_client.urllib.request, "urlopen", fake_urlopen)
        assert jira_client.lookup_jira_account_id(self._cfg(), "John Doe") == "acc-johnd"
        assert "johnd" in captured["url"]

    # --- "내 업무" matching ------------------------------------------------
    def test_my_jira_records_matches_by_alias_and_tolerates_empty_org(self, monkeypatch):
        cfg = self._cfg()
        records = [
            {"org": "dev", "assignee": "johnd", "assigneeEmail": "johnd@company.com", "jira": {"key": "SCRUM-1"}},
            {"org": "", "assignee": "johnd", "assigneeEmail": "", "jira": {"key": "SCRUM-2"}},
            {"org": "hr", "assignee": "johnd", "assigneeEmail": "", "jira": {"key": "SCRUM-3"}},
            {"org": "dev", "assignee": "Other Person", "assigneeEmail": "x@company.com", "jira": {"key": "SCRUM-4"}},
        ]
        monkeypatch.setattr(
            jira_client, "get_cached_jira_records", lambda _cfg: {"records": records}
        )

        mine = jira_client.my_jira_records(cfg, "John Doe", "dev", "johnd@company.com")
        keys = {r["jira"]["key"] for r in mine}
        assert keys == {"SCRUM-1", "SCRUM-2"}  # khác phòng (hr) bị loại, người khác bị loại

    def test_my_jira_records_matches_by_email_only(self, monkeypatch):
        cfg = self._cfg()
        records = [
            {"org": "dev", "assignee": "Other Jira Name", "assigneeEmail": "johnd@company.com", "jira": {"key": "SCRUM-9"}},
        ]
        monkeypatch.setattr(
            jira_client, "get_cached_jira_records", lambda _cfg: {"records": records}
        )
        mine = jira_client.my_jira_records(cfg, "John Doe", "dev", "johnd@company.com")
        assert [r["jira"]["key"] for r in mine] == ["SCRUM-9"]


# ---------------------------------------------------------------------------
# Jira Cloud quirk: /rest/api/3/search/jql answers HTTP 200 + {"issues": []}
# even when the token is expired/revoked (only /myself returns 401). Trusting
# that empty page made a dead token look like "connected, 0 issues".
# ---------------------------------------------------------------------------
class _StatusResponse(_FakeResponse):
    def __init__(self, payload, status=200):
        super().__init__(payload)
        self.status = status


def _route(search_payload, myself_status):
    """urlopen stub: /myself behaves per myself_status, /search/jql returns search_payload."""

    def fake(req, *args, **kwargs):
        url = getattr(req, "full_url", str(req))
        if "/rest/api/3/myself" in url:
            if myself_status != 200:
                body = io.BytesIO(b'{"errorMessages": ["Client must be authenticated."]}')
                raise urllib.error.HTTPError(url, myself_status, "Unauthorized", {}, body)
            return _StatusResponse({"accountId": "acc-me", "active": True})
        return _StatusResponse(search_payload)

    return fake


class TestEmptySearchIsCrossCheckedWithAuth:
    def test_expired_token_returns_none_not_empty_list(self, monkeypatch):
        monkeypatch.setattr(
            jira_client.urllib.request, "urlopen",
            _route({"issues": [], "isLast": True}, myself_status=401),
        )

        issues, activities = jira_client.jira_search_issues(_cfg(), max_results=10, page_size=10)

        assert issues is None  # "lookup failed" → caller keeps the previous cache
        assert activities is None

    def test_valid_token_with_no_issues_returns_empty_list(self, monkeypatch):
        monkeypatch.setattr(
            jira_client.urllib.request, "urlopen",
            _route({"issues": [], "isLast": True}, myself_status=200),
        )

        issues, activities = jira_client.jira_search_issues(_cfg(), max_results=10, page_size=10)

        assert issues == []
        assert activities == []

    def test_search_empty_with_myself_200_but_project_permission_revoked_returns_none(self, monkeypatch):
        """P1 Regression test: /myself returns 200, but project TEST returns 404/403.
        Search MUST return (None, None) so reconciliation does not wipe the DB cache.
        """
        def fake(req, *args, **kwargs):
            url = getattr(req, "full_url", str(req))
            if "/rest/api/3/myself" in url:
                return _StatusResponse({"accountId": "acc-me", "active": True})
            if "/rest/api/3/project/TEST" in url:
                body = io.BytesIO(b'{"errorMessages": ["No project could be found with key \'TEST\'."]}')
                raise urllib.error.HTTPError(url, 404, "Not Found", {}, body)
            return _StatusResponse({"issues": [], "isLast": True})

        monkeypatch.setattr(jira_client.urllib.request, "urlopen", fake)

        issues, activities = jira_client.jira_search_issues(_cfg(), max_results=10, page_size=10)

        assert issues is None  # Prevents cache deletion!
        assert activities is None

    def test_verify_auth_reports_http_error_text(self, monkeypatch):
        def boom(req, *a, **kw):
            body = io.BytesIO(b"Client must be authenticated to access this resource.")
            raise urllib.error.HTTPError(getattr(req, "full_url", ""), 401, "Unauthorized", {}, body)

        monkeypatch.setattr(jira_client.urllib.request, "urlopen", boom)

        ok, error = jira_client._verify_jira_auth(_cfg()["jira"])

        assert ok is False
        assert "401" in error
        assert "authenticated" in error

    def test_verify_jira_projects_access(self, monkeypatch):
        def fake(req, *a, **kw):
            url = getattr(req, "full_url", str(req))
            if "TEST" in url:
                return _StatusResponse({"id": "1000", "key": "TEST"})
            body = io.BytesIO(b'{"errorMessages": ["Forbidden"]}')
            raise urllib.error.HTTPError(url, 403, "Forbidden", {}, body)

        monkeypatch.setattr(jira_client.urllib.request, "urlopen", fake)

        all_ok, failed = jira_client.verify_jira_projects_access(_cfg()["jira"], ["TEST"])
        assert all_ok is True
        assert failed == {}

        all_ok, failed = jira_client.verify_jira_projects_access(_cfg()["jira"], ["TEST", "SECRET"])
        assert all_ok is False
        assert "SECRET" in failed


class TestUpsertJiraRecordsEmptyWipeProtection:
    def test_upsert_refuses_to_wipe_when_incoming_empty_and_existing_has_data(self):
        from services import jira_db
        # Insert a sample issue
        sample_record = {
            "id": "jira-EXIST-1",
            "jira": {"key": "EXIST-1", "summary": "Sample"},
            "title": "Sample",
            "org": "dept_test",
            "category": "Task",
            "assignee": "Tester",
            "date": "2026-11-05",
            "memo": "Test",
            "attachments": [],
            "comments": [],
        }
        jira_db.upsert_jira_records([sample_record])

        # Verify it exists
        all_recs = jira_db.load_all_jira_from_db()
        assert any(r.get("id") == "jira-EXIST-1" for r in all_recs)

        # Attempt to reconcile with empty incoming records
        jira_db.upsert_jira_records([], replace_existing=True)

        # The existing record MUST NOT be wiped!
        all_recs_after = jira_db.load_all_jira_from_db()
        assert any(r.get("id") == "jira-EXIST-1" for r in all_recs_after)


class TestUpsertFailureAbortsCursorAdvance:
    def test_upsert_failure_aborts_sync_cursor_advance(self, monkeypatch):
        """P1 Regression test: When upsert_jira_records() returns False,
        set_last_sync_time must NOT be called, and cache must NOT mark sync succeeded.
        """
        from unittest.mock import MagicMock
        from services import jira_db

        mock_set_sync = MagicMock()
        monkeypatch.setattr(jira_db, "set_last_sync_time", mock_set_sync)
        # Mock upsert_jira_records to simulate failure (e.g. record validation failure)
        monkeypatch.setattr(jira_db, "upsert_jira_records", lambda records, replace_existing=False: False)
        # Mock search to return valid items with is_complete=True
        fake_records = [{"jira": {"key": "TEST-1", "summary": "Sample"}}]
        monkeypatch.setattr(jira_client, "jira_search_issues", lambda cfg, **kw: (fake_records, [], True))
        monkeypatch.setattr(jira_client, "jira_fetch_project_categories", lambda cfg, pk: [])

        cfg = _cfg()
        cfg["jira"]["project_map"] = {}
        jira_client.invalidate_jira_cache()
        res = jira_client.sync_jira_cache(cfg, force_full=True)

        # Cursor MUST NOT be advanced!
        mock_set_sync.assert_not_called()
        # Cache error must indicate failure
        assert res.get("error") is not None
        # synced_at must not be set to a new timestamp
        assert res.get("synced_at") is None


class TestConcurrentSyncAndSafeWatermark:
    def test_concurrent_syncs_are_serialized_by_sync_lock(self, monkeypatch):
        """P1: Verify that _jira_sync_lock ensures only 1 sync executes at a time."""
        import time
        import threading
        from concurrent.futures import ThreadPoolExecutor

        active_count = 0
        max_concurrent = 0
        lock_counter = threading.Lock()

        def slow_search(cfg, **kw):
            nonlocal active_count, max_concurrent
            with lock_counter:
                active_count += 1
                if active_count > max_concurrent:
                    max_concurrent = active_count
            time.sleep(0.05)
            with lock_counter:
                active_count -= 1
            return ([], [], True)

        monkeypatch.setattr(jira_client, "jira_search_issues", slow_search)
        monkeypatch.setattr(jira_client, "jira_fetch_project_categories", lambda cfg, pk: [])

        cfg = _cfg()
        cfg["jira"]["project_map"] = {}

        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(jira_client.sync_jira_cache, cfg, False) for _ in range(5)]
            for f in futures:
                f.result()

        # max_concurrent must never exceed 1 because of _jira_sync_lock
        assert max_concurrent == 1

    def test_watermark_uses_sync_start_time_and_overlap_window(self, monkeypatch):
        """P1: Verify that incremental sync applies a 120s overlap window
        and sets last_sync_time to the sync START time, not completion time.
        """
        import time
        from unittest.mock import MagicMock
        from services import jira_db

        captured_since = []
        captured_new_cursor = []

        def mock_search(cfg, since_updated=None, **kw):
            captured_since.append(since_updated)
            time.sleep(0.05)  # Simulate fetch duration
            return ([], [], True)

        def mock_set_cursor(ts):
            captured_new_cursor.append(ts)

        monkeypatch.setattr(jira_client, "jira_search_issues", mock_search)
        monkeypatch.setattr(jira_client, "jira_fetch_project_categories", lambda cfg, pk: [])
        monkeypatch.setattr(jira_db, "get_last_sync_time", lambda: "2026-11-05T12:00:00")
        monkeypatch.setattr(jira_db, "get_last_full_sync_time", lambda: "2026-11-05T11:00:00")
        monkeypatch.setattr(jira_db, "set_last_sync_time", mock_set_cursor)

        cfg = _cfg()
        cfg["jira"]["project_map"] = {}
        jira_client.sync_jira_cache(cfg, force_full=False)

        # 1. Verify overlap: 12:00:00 - 120s = 11:58:00
        assert len(captured_since) == 1
        assert "11:58:00" in captured_since[0]

        # 2. Verify new cursor is the sync START time (before completion)
        assert len(captured_new_cursor) == 1
        new_cursor = captured_new_cursor[0]
        from datetime import datetime
        cursor_dt = datetime.fromisoformat(new_cursor)
        assert abs((datetime.now() - cursor_dt).total_seconds()) < 60


class TestSubresourceReconciliationAndPagination:
    def test_deleted_comments_and_attachments_are_reconciled(self):
        """P2: Verify that when comments or attachments are deleted on Jira,
        re-syncing the issue reconciles and removes stale comments/attachments from the DB.
        """
        from services import jira_db
        from db import query

        # 1. Initial upsert with 2 comments and 2 attachments
        record_v1 = {
            "id": "jira-SUB-1",
            "jira": {"key": "SUB-1", "summary": "Subresource Test"},
            "title": "Subresource Test",
            "org": "dev",
            "category": "Task",
            "assignee": "Dev",
            "date": "2026-11-05",
            "memo": "Memo",
            "comments": [
                {"id": "c1", "author": "Alice", "body": "First comment", "created": "2026-11-05 10:00:00", "source": "jira"},
                {"id": "c2", "author": "Bob", "body": "Second comment", "created": "2026-11-05 10:05:00", "source": "jira"}
            ],
            "attachments": [
                {"id": "a1", "name": "file1.pdf", "size": 100, "url": "/att/a1"},
                {"id": "a2", "name": "file2.pdf", "size": 200, "url": "/att/a2"}
            ]
        }
        jira_db.upsert_jira_records([record_v1])

        # Verify initial DB state
        c_rows = query("SELECT comment_id FROM jira_comments WHERE jira_key = 'SUB-1'")
        a_rows = query("SELECT attachment_id FROM jira_attachments WHERE jira_key = 'SUB-1'")
        assert len(c_rows) == 2
        assert len(a_rows) == 2

        # 2. Second upsert where c2 and a2 were deleted on Jira (only c1 and a1 remain)
        record_v2 = {
            "id": "jira-SUB-1",
            "jira": {"key": "SUB-1", "summary": "Subresource Test"},
            "title": "Subresource Test",
            "org": "dev",
            "category": "Task",
            "assignee": "Dev",
            "date": "2026-11-05",
            "memo": "Memo",
            "comments": [
                {"id": "c1", "author": "Alice", "body": "First comment", "created": "2026-11-05 10:00:00", "source": "jira"}
            ],
            "attachments": [
                {"id": "a1", "name": "file1.pdf", "size": 100, "url": "/att/a1"}
            ]
        }
        jira_db.upsert_jira_records([record_v2])

        # Verify c2 and a2 are cleaned up!
        c_after = query("SELECT comment_id FROM jira_comments WHERE jira_key = 'SUB-1'")
        a_after = query("SELECT attachment_id FROM jira_attachments WHERE jira_key = 'SUB-1'")
        assert len(c_after) == 1
        assert c_after[0]["comment_id"] == "c1"
        assert len(a_after) == 1
        assert a_after[0]["attachment_id"] == "a1"

    def test_comment_pagination_fetches_remaining_pages(self, monkeypatch):
        """P2: When initial comment object has total > len(comments), pagination fetches remaining comments."""
        def fake(req, *args, **kwargs):
            url = getattr(req, "full_url", str(req))
            if "startAt=1" in url:
                return _StatusResponse({
                    "comments": [{"id": "c2", "body": "Paged comment"}],
                    "total": 2,
                    "maxResults": 1,
                    "startAt": 1
                })
            return _StatusResponse({"comments": [], "total": 2})

        monkeypatch.setattr(jira_client.urllib.request, "urlopen", fake)

        initial = {
            "comments": [{"id": "c1", "body": "First comment"}],
            "total": 2,
            "maxResults": 1,
            "startAt": 0
        }
        all_comments = jira_client.fetch_all_jira_issue_comments(_cfg()["jira"], "PAG-1", initial)
        assert len(all_comments) == 2
        assert all_comments[0]["id"] == "c1"
        assert all_comments[1]["id"] == "c2"

    def test_changelog_pagination_fetches_remaining_pages(self, monkeypatch):
        """P2: When initial changelog object has total > len(histories), pagination fetches remaining histories."""
        def fake(req, *args, **kwargs):
            url = getattr(req, "full_url", str(req))
            if "startAt=1" in url:
                return _StatusResponse({
                    "values": [{"id": "h2", "items": [{"field": "status", "toString": "Done"}]}],
                    "total": 2,
                    "maxResults": 1,
                    "startAt": 1,
                    "isLast": True
                })
            return _StatusResponse({"values": [], "total": 2})

        monkeypatch.setattr(jira_client.urllib.request, "urlopen", fake)

        initial = {
            "histories": [{"id": "h1", "items": [{"field": "status", "toString": "In Progress"}]}],
            "total": 2,
            "maxResults": 1,
            "startAt": 0
        }
        all_histories = jira_client.fetch_all_jira_issue_changelog(_cfg()["jira"], "PAG-2", initial)
        assert len(all_histories) == 2
        assert all_histories[0]["id"] == "h1"
        assert all_histories[1]["id"] == "h2"


class TestTransitionJiraIssueSyncAndFallback:
    """Tests for transition_jira_issue: DB/cache sync and avoiding fake success on Review fallback."""

    def test_direct_transition_updates_db_and_cache(self, monkeypatch):
        mock_db = {}
        def fake_get_one(query, params):
            key = params[0].upper()
            if key in mock_db:
                return {"raw_json": json.dumps(mock_db[key])}
            return None

        def fake_execute(query, params):
            if "UPDATE jira_issues" in query:
                status, status_name, raw_json, key = params
                mock_db[key.upper()] = json.loads(raw_json)

        monkeypatch.setattr("db.get_one", fake_get_one)
        monkeypatch.setattr("db.execute", fake_execute)

        # Seed mock DB and cache
        mock_db["VS-101"] = {
            "key": "VS-101",
            "status": "예정",
            "statusName": "To Do",
            "jira": {"key": "VS-101", "status": "info", "statusName": "To Do"}
        }
        with jira_client._jira_cache_lock:
            jira_client._jira_cache["records"] = [
                {"key": "VS-101", "status": "예정", "statusName": "To Do", "jira": {"key": "VS-101", "status": "info", "statusName": "To Do"}}
            ]

        def fake_urlopen(req, *args, **kwargs):
            method = getattr(req, "method", "GET")
            url = getattr(req, "full_url", str(req))
            if "/transitions" in url and method == "GET":
                return _StatusResponse({
                    "transitions": [
                        {"id": "31", "name": "완료", "to": {"name": "완료"}}
                    ]
                })
            elif "/transitions" in url and method == "POST":
                return _StatusResponse({}, status=204)
            return _StatusResponse({})

        monkeypatch.setattr(jira_client.urllib.request, "urlopen", fake_urlopen)

        ok, msg = jira_client.transition_jira_issue(_cfg(), "VS-101", "완료")
        assert ok is True
        assert "완료" in msg
        # Check DB updated
        assert mock_db["VS-101"]["status"] == "완료"
        assert mock_db["VS-101"]["statusName"] == "완료"
        # Check cache updated
        assert jira_client._jira_cache["records"][0]["status"] == "완료"
        assert jira_client._jira_cache["records"][0]["statusName"] == "완료"

    def test_review_fallback_to_in_progress_updates_db_and_cache(self, monkeypatch):
        mock_db = {"VS-202": {"key": "VS-202", "status": "예정", "statusName": "To Do", "jira": {"key": "VS-202"}}}
        monkeypatch.setattr("db.get_one", lambda q, p: {"raw_json": json.dumps(mock_db[p[0].upper()])})
        monkeypatch.setattr("db.execute", lambda q, p: mock_db.update({p[3].upper(): json.loads(p[2])}))

        with jira_client._jira_cache_lock:
            jira_client._jira_cache["records"] = [{"key": "VS-202", "status": "예정", "statusName": "To Do", "jira": {"key": "VS-202"}}]

        def fake_urlopen(req, *args, **kwargs):
            method = getattr(req, "method", "GET")
            url = getattr(req, "full_url", str(req))
            if "/transitions" in url and method == "GET":
                # Only "진행 중" is available (no "검토")
                return _StatusResponse({
                    "transitions": [
                        {"id": "21", "name": "진행 중", "to": {"name": "진행 중"}}
                    ]
                })
            elif "/transitions" in url and method == "POST":
                return _StatusResponse({}, status=204)
            return _StatusResponse({})

        monkeypatch.setattr(jira_client.urllib.request, "urlopen", fake_urlopen)

        ok, msg = jira_client.transition_jira_issue(_cfg(), "VS-202", "검토")
        assert ok is True
        assert "진행 중" in msg
        # Verified DB updated to fallback status
        assert mock_db["VS-202"]["status"] == "진행"
        assert mock_db["VS-202"]["statusName"] == "진행 중"
        # Verified cache updated to fallback status
        assert jira_client._jira_cache["records"][0]["status"] == "진행"
        assert jira_client._jira_cache["records"][0]["statusName"] == "진행 중"

    def test_review_fallback_fails_cleanly_when_no_progress_transition_available(self, monkeypatch):
        """No fake success: if Review is unavailable and In Progress transition is also unavailable, returns False."""
        def fake_urlopen(req, *args, **kwargs):
            return _StatusResponse({
                "transitions": [
                    {"id": "99", "name": "보류", "to": {"name": "보류"}}
                ]
            })

        monkeypatch.setattr(jira_client.urllib.request, "urlopen", fake_urlopen)

        ok, msg = jira_client.transition_jira_issue(_cfg(), "VS-303", "검토")
        assert ok is False
        assert "전이 가능한 대체 경로(진행)도 존재하지 않습니다" in msg


class TestUploadJiraAttachmentSync:
    """Tests for P2: Uploading Jira attachment immediately syncs to DB, cache, and attachment lookup."""

    def test_upload_attachment_immediately_updates_db_cache_and_lookup(self, monkeypatch):
        mock_issues_db = {}
        mock_attachments_db = {}

        def fake_get_one(query, params=None):
            if "SELECT jira_key FROM jira_attachments" in query:
                aid = str(params[0])
                if aid in mock_attachments_db:
                    return {"jira_key": mock_attachments_db[aid]["jira_key"]}
                return None
            if "SELECT raw_json FROM jira_issues" in query:
                key = params[0].upper()
                if key in mock_issues_db:
                    return {"raw_json": json.dumps(mock_issues_db[key])}
                return None
            return None

        def fake_execute(query, params=None):
            if "INSERT INTO jira_attachments" in query:
                att_id, jira_key, fname, fsize, jurl = params
                mock_attachments_db[str(att_id)] = {
                    "attachment_id": str(att_id),
                    "jira_key": jira_key,
                    "filename": fname,
                    "file_size": fsize,
                    "jira_url": jurl
                }
            elif "UPDATE jira_issues" in query:
                raw_json, key = params
                mock_issues_db[key.upper()] = json.loads(raw_json)

        monkeypatch.setattr("db.get_one", fake_get_one)
        monkeypatch.setattr("db.execute", fake_execute)

        # Seed initial Jira issue in DB and cache
        issue_data = {
            "key": "VS-500",
            "title": "Attachment Test",
            "attachments": [],
            "comments": [],
            "jira": {"key": "VS-500"}
        }
        mock_issues_db["VS-500"] = issue_data
        with jira_client._jira_cache_lock:
            jira_client._jira_cache["records"] = [
                {"key": "VS-500", "title": "Attachment Test", "attachments": [], "jira": {"key": "VS-500"}}
            ]

        # Mock Jira API returning the uploaded attachment metadata
        def fake_urlopen(req, *args, **kwargs):
            return _StatusResponse([{
                "id": "att-9999",
                "filename": "report.pdf",
                "size": 1024,
                "content": "https://example.atlassian.net/attachment/att-9999"
            }])

        monkeypatch.setattr(jira_client.urllib.request, "urlopen", fake_urlopen)

        res, err = jira_client.upload_jira_attachment(_cfg(), "VS-500", "report.pdf", b"dummy PDF bytes", "application/pdf")
        assert err is None
        assert isinstance(res, list)
        assert len(res) == 1

        # 1. Verify jira_attachments DB table was updated
        assert "att-9999" in mock_attachments_db
        assert mock_attachments_db["att-9999"]["jira_key"] == "VS-500"
        assert mock_attachments_db["att-9999"]["filename"] == "report.pdf"

        # 2. Verify find_issue_key_by_attachment_id immediately resolves
        found_key = jira_client.find_issue_key_by_attachment_id(_cfg(), "att-9999")
        assert found_key == "VS-500"

        # 3. Verify jira_issues raw_json has the attachment
        assert len(mock_issues_db["VS-500"]["attachments"]) == 1
        assert mock_issues_db["VS-500"]["attachments"][0]["id"] == "att-9999"
        assert mock_issues_db["VS-500"]["attachments"][0]["url"] == "/api/jira/attachments/att-9999"

        # 4. Verify in-memory cache has the attachment
        cached_rec = jira_client._jira_cache["records"][0]
        assert len(cached_rec["attachments"]) == 1
        assert cached_rec["attachments"][0]["id"] == "att-9999"

        # 5. Verify get_jira_issue_by_key includes the attachment
        monkeypatch.setattr("services.jira_client.read_records", lambda: [])
        issue_detail = jira_client.get_jira_issue_by_key(_cfg(), "VS-500")
        assert issue_detail is not None
        assert any(a.get("id") == "att-9999" for a in issue_detail.get("attachments", []))


class TestFailClosedPaginationAndSnapshotIntegrity:
    """Kiểm thử cơ chế Fail-closed: từ chối snapshot không hoàn chỉnh khi phân trang comment hoặc changelog lỗi."""

    def test_comment_pagination_failure_raises_runtime_error(self, monkeypatch):
        def fake_urlopen(req, *args, **kwargs):
            raise urllib.error.URLError("Network timeout during comment pagination")

        monkeypatch.setattr(jira_client.urllib.request, "urlopen", fake_urlopen)

        initial_comment_obj = {
            "total": 50,
            "comments": [{"id": "1", "author": {"displayName": "User1"}, "body": "c1"}]
        }
        with pytest.raises(RuntimeError) as exc_info:
            jira_client.fetch_all_jira_issue_comments(_cfg()["jira"], "VS-101", initial_comment_obj)
        assert "Phân trang comment thất bại" in str(exc_info.value)

    def test_comment_pagination_premature_empty_batch_raises_runtime_error(self, monkeypatch):
        class _Resp:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self):
                return json.dumps({"comments": [], "total": 50}).encode("utf-8")

        monkeypatch.setattr(jira_client.urllib.request, "urlopen", lambda req, *args, **kwargs: _Resp())

        initial_comment_obj = {
            "total": 50,
            "comments": [{"id": "1", "author": {"displayName": "User1"}, "body": "c1"}]
        }
        with pytest.raises(RuntimeError) as exc_info:
            jira_client.fetch_all_jira_issue_comments(_cfg()["jira"], "VS-101", initial_comment_obj)
        assert "trang rỗng trước khi tải hết" in str(exc_info.value)

    def test_jira_search_issues_fails_closed_on_incomplete_comments(self, monkeypatch):
        # When comment pagination raises, search_issues must return (None, None, False)
        # to ensure the previous healthy cache is preserved.
        monkeypatch.setattr(jira_client, "jira_project_keys", lambda cfg: ["VS"])

        class _SearchResp:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self):
                return json.dumps({
                    "issues": [{
                        "key": "VS-101",
                        "fields": {
                            "project": {"key": "VS", "name": "Vision"},
                            "summary": "Test issue",
                            "status": {"name": "In Progress"},
                            "comment": {"total": 100, "comments": [{"id": "c1", "body": "hello"}]}
                        }
                    }]
                }).encode("utf-8")

        monkeypatch.setattr(jira_client.urllib.request, "urlopen", lambda req, *args, **kwargs: _SearchResp())
        monkeypatch.setattr(jira_client, "fetch_all_jira_issue_comments", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("Pagination failed")))

        res = jira_client.jira_search_issues(_cfg(), return_complete_flag=True)
        assert res == (None, None, False)

    def test_jira_search_issues_fails_closed_on_incomplete_changelog(self, monkeypatch):
        monkeypatch.setattr(jira_client, "jira_project_keys", lambda cfg: ["VS"])

        class _SearchResp:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self):
                return json.dumps({
                    "issues": [{
                        "key": "VS-101",
                        "fields": {
                            "project": {"key": "VS", "name": "Vision"},
                            "summary": "Test issue",
                            "status": {"name": "In Progress"},
                        },
                        "changelog": {"total": 50, "histories": [{"id": "h1"}]}
                    }]
                }).encode("utf-8")

        monkeypatch.setattr(jira_client.urllib.request, "urlopen", lambda req, *args, **kwargs: _SearchResp())
        monkeypatch.setattr(jira_client, "fetch_all_jira_issue_changelog", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("Changelog pagination failed")))

        res = jira_client.jira_search_issues(_cfg(), return_complete_flag=True)
        assert res == (None, None, False)


class TestReconciliationPreservesLocalComments:
    """Kiểm thử upsert_jira_records chỉ xóa comment stale từ nguồn Jira, giữ nguyên comment local."""

    def test_upsert_jira_records_preserves_local_comments(self, monkeypatch):
        import sqlite3
        conn = sqlite3.connect(":memory:")
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE jira_issues (
                jira_key TEXT PRIMARY KEY, project_name TEXT, issue_type TEXT, is_subtask INTEGER,
                parent_key TEXT, parent_summary TEXT, summary TEXT, description TEXT, status TEXT,
                status_name TEXT, assignee_name TEXT, assignee_avatar TEXT, reporter_name TEXT,
                dept_id TEXT, start_date TEXT, due_date TEXT, created_at TEXT, tags TEXT,
                raw_json TEXT, synced_at TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE jira_comments (
                comment_id TEXT PRIMARY KEY, jira_key TEXT, author_name TEXT, body TEXT,
                created_at TEXT, source TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE jira_attachments (
                attachment_id TEXT PRIMARY KEY, jira_key TEXT, filename TEXT, size INTEGER,
                content_url TEXT, created_at TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE jira_changelog (
                id TEXT PRIMARY KEY, issue_key TEXT, author_name TEXT, author_avatar TEXT,
                action_type TEXT, action_detail TEXT, created_at TEXT
            )
        """)

        # Insert a local comment and an old jira comment
        cur.execute("INSERT INTO jira_comments VALUES ('local_1', 'VS-101', 'Admin', 'Ghi chú nội bộ', '2026-03-01', 'local')")
        cur.execute("INSERT INTO jira_comments VALUES ('jira_old', 'VS-101', 'JiraUser', 'Cũ bị xóa trên Jira', '2026-03-01', 'jira')")
        conn.commit()

        monkeypatch.setattr("services.jira_db.transaction", lambda func: func(conn))
        monkeypatch.setattr("services.jira_db.get_one", lambda q, p=None: {"cnt": 1})

        from services.jira_db import upsert_jira_records

        # New snapshot with only jira_new comment
        new_record = {
            "id": "jira-VS-101",
            "jira": {"key": "VS-101", "summary": "VS 101"},
            "comments": [
                {"id": "jira_new", "author": "JiraUser", "body": "Mới", "created": "2026-03-02", "source": "jira"}
            ]
        }
        upsert_jira_records([new_record], replace_existing=False)

        cur.execute("SELECT comment_id, source FROM jira_comments WHERE jira_key = 'VS-101'")
        remaining = {row[0]: row[1] for row in cur.fetchall()}

        # jira_old was stale from Jira -> deleted
        assert "jira_old" not in remaining
        # local_1 was local -> PRESERVED!
        assert "local_1" in remaining
        assert remaining["local_1"] == "local"
        # jira_new was inserted
        assert "jira_new" in remaining


class TestStrictConsistencyRouterHandlers:
    """Kiểm thử tính nhất quán nghiêm ngặt trong router.py khi tương tác với Jira."""

    def test_handle_post_issue_transition_rejects_on_jira_failure(self, monkeypatch):
        from router import handle_post_issue_transition

        class DummyHandler:
            def __init__(self):
                self.cfg = {"jira": {"enabled": True}}
                self.sent_status = None
                self.sent_json = None
            def _get_session_or_401(self):
                return {"id": 1, "username": "admin", "name": "Admin", "role": "admin"}
            def _send_json(self, status, payload):
                self.sent_status = status
                self.sent_json = payload

        handler = DummyHandler()
        monkeypatch.setattr("router.get_record_by_id", lambda rec_id: {
            "id": 1,
            "status": "진행",
            "jira": {"key": "VS-200"}
        })
        monkeypatch.setattr("services.auth.can_transition_status", lambda s, r, st: (True, None))

        # Jira transition fails (e.g. Jira rejects state)
        monkeypatch.setattr("services.jira_client.transition_jira_issue", lambda cfg, key, st: (False, "Transition invalid in workflow"))

        status_updated = []
        monkeypatch.setattr("router.update_record_status", lambda rec_id, st: status_updated.append((rec_id, st)))

        raw_body = json.dumps({"issue_key": "REC-1", "status": "완료"}).encode("utf-8")
        handle_post_issue_transition(handler, raw_body, "127.0.0.1")

        # Must respond with HTTP 400 error
        assert handler.sent_status == 400
        assert handler.sent_json["ok"] is False
        assert "Transition invalid in workflow" in handler.sent_json["error"]
        # Local record must NOT have been updated!
        assert len(status_updated) == 0

    def test_handle_post_issue_comment_rejects_on_jira_failure(self, monkeypatch):
        from router import handle_post_issue_comment

        class DummyHandler:
            def __init__(self):
                self.cfg = {"jira": {"enabled": True}}
                self.sent_status = None
                self.sent_json = None
            def _get_session_or_401(self):
                return {"id": 1, "username": "admin", "name": "Admin", "role": "admin"}
            def _send_json(self, status, payload):
                self.sent_status = status
                self.sent_json = payload

        handler = DummyHandler()
        monkeypatch.setattr("router.get_record_by_id", lambda rec_id: {
            "id": 1,
            "status": "진행",
            "jira": {"key": "VS-200"}
        })
        monkeypatch.setattr("services.auth.can_view_record", lambda s, r: True)

        # Jira add comment fails
        monkeypatch.setattr("services.jira_client.add_jira_comment", lambda cfg, key, comment, author: (None, "Jira server unavailable"))

        local_comments_added = []
        monkeypatch.setattr("router.add_record_comment", lambda rec_id, author, c: local_comments_added.append((rec_id, author, c)))

        raw_body = json.dumps({"issue_key": "REC-1", "comment": "Bình luận mới"}).encode("utf-8")
        handle_post_issue_comment(handler, raw_body, "127.0.0.1")

        # Must respond with HTTP 400 error
        assert handler.sent_status == 400
        assert handler.sent_json["ok"] is False
        assert "Jira server unavailable" in handler.sent_json["error"]
        # Local comment must NOT have been saved!
        assert len(local_comments_added) == 0


class TestPersistentFullSyncWatermark:
    """Kiểm thử cơ chế Full Sync bền vững dựa trên timestamp trong DB (không reset khi restart server)."""

    def test_persistent_full_sync_triggers_when_never_synced(self, monkeypatch):
        search_calls = []
        monkeypatch.setattr(jira_client, "jira_project_keys", lambda cfg: ["VS"])
        monkeypatch.setattr(jira_client, "jira_search_issues", lambda cfg, **kwargs: (search_calls.append(kwargs), ([], [], True))[1])
        monkeypatch.setattr("services.jira_db.get_last_full_sync_time", lambda: None)
        monkeypatch.setattr("services.jira_db.get_last_sync_time", lambda: "2026-11-05T10:00:00")
        monkeypatch.setattr(jira_client, "verify_jira_projects_access", lambda j, k: (True, {}))
        monkeypatch.setattr("services.jira_db.load_all_jira_from_db", lambda: [])
        monkeypatch.setattr("services.jira_db.load_all_jira_activities_from_db", lambda: [])

        # Even with force_full=False, if get_last_full_sync_time is None, it MUST run full sync (since_updated=None)
        jira_client.sync_jira_cache(_cfg(), force_full=False)
        assert len(search_calls) == 1
        assert search_calls[0].get("since_updated") is None

    def test_persistent_full_sync_triggers_when_24h_elapsed(self, monkeypatch):
        search_calls = []
        monkeypatch.setattr(jira_client, "jira_project_keys", lambda cfg: ["VS"])
        monkeypatch.setattr(jira_client, "jira_search_issues", lambda cfg, **kwargs: (search_calls.append(kwargs), ([], [], True))[1])
        # Last full sync was 25 hours ago
        last_full = (datetime.now() - timedelta(hours=25)).isoformat()
        monkeypatch.setattr("services.jira_db.get_last_full_sync_time", lambda: last_full)
        monkeypatch.setattr("services.jira_db.get_last_sync_time", lambda: "2026-11-05T10:00:00")
        monkeypatch.setattr(jira_client, "verify_jira_projects_access", lambda j, k: (True, {}))
        monkeypatch.setattr("services.jira_db.load_all_jira_from_db", lambda: [])
        monkeypatch.setattr("services.jira_db.load_all_jira_activities_from_db", lambda: [])

        jira_client.sync_jira_cache(_cfg(), force_full=False)
        assert len(search_calls) == 1
        # Full sync triggered because 25h > 24h: since_updated should be None
        assert search_calls[0].get("since_updated") is None

    def test_persistent_full_sync_does_not_trigger_when_recent(self, monkeypatch):
        search_calls = []
        monkeypatch.setattr(jira_client, "jira_project_keys", lambda cfg: ["VS"])
        monkeypatch.setattr(jira_client, "jira_search_issues", lambda cfg, **kwargs: (search_calls.append(kwargs), ([], [], True))[1])
        # Last full sync was only 2 hours ago
        last_full = (datetime.now() - timedelta(hours=2)).isoformat()
        last_sync = (datetime.now() - timedelta(minutes=10)).isoformat()
        monkeypatch.setattr("services.jira_db.get_last_full_sync_time", lambda: last_full)
        monkeypatch.setattr("services.jira_db.get_last_sync_time", lambda: last_sync)
        monkeypatch.setattr(jira_client, "verify_jira_projects_access", lambda j, k: (True, {}))
        monkeypatch.setattr("services.jira_db.load_all_jira_from_db", lambda: [])
        monkeypatch.setattr("services.jira_db.load_all_jira_activities_from_db", lambda: [])

        jira_client.sync_jira_cache(_cfg(), force_full=False)
        assert len(search_calls) == 1
        # Incremental sync with overlap window: since_updated must NOT be None
        assert search_calls[0].get("since_updated") is not None










