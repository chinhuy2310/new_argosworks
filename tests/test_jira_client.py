"""
test_jira_client.py — Jira client robustness (no network required).

Regression: `_urlopen()` used to swallow urllib.URLError and return None, so
every `with _urlopen(...) as resp:` blew up with the meaningless
"'NoneType' object does not support the context manager protocol".
"""
import os
import sys
import urllib.error

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


