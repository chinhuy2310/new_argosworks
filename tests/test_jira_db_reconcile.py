import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_DIR = os.path.join(BASE_DIR, "server")
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from db import query
from services.jira_db import upsert_jira_records


def _jira_record(key):
    return {
        "id": f"jira-{key}",
        "title": f"Issue {key}",
        "org": "dev",
        "assignee": "Test User",
        "jira": {"key": key, "summary": f"Issue {key}", "status": "Open"},
        "comments": [{"id": f"comment-{key}", "author": "Tester", "body": "comment"}],
        "attachments": [{"id": f"attachment-{key}", "name": "proof.txt", "size": 12, "url": "https://example.test/proof.txt"}],
    }


def test_complete_full_sync_removes_deleted_issues_and_dependents(tmp_db):
    assert upsert_jira_records([_jira_record("OLD-1"), _jira_record("KEEP-1")], replace_existing=True)

    assert query("SELECT jira_key FROM jira_issues WHERE jira_key = 'OLD-1'")
    assert query("SELECT comment_id FROM jira_comments WHERE jira_key = 'OLD-1'")
    assert query("SELECT attachment_id FROM jira_attachments WHERE jira_key = 'OLD-1'")

    assert upsert_jira_records([_jira_record("KEEP-1")], replace_existing=True)

    assert not query("SELECT jira_key FROM jira_issues WHERE jira_key = 'OLD-1'")
    assert not query("SELECT comment_id FROM jira_comments WHERE jira_key = 'OLD-1'")
    assert not query("SELECT attachment_id FROM jira_attachments WHERE jira_key = 'OLD-1'")
    assert query("SELECT jira_key FROM jira_issues WHERE jira_key = 'KEEP-1'")


def test_empty_successful_full_sync_clears_jira_cache(tmp_db):
    assert upsert_jira_records([_jira_record("OLD-2")], replace_existing=True)
    assert upsert_jira_records([], replace_existing=True)
    assert not query("SELECT jira_key FROM jira_issues WHERE jira_key = 'OLD-2'")


def test_malformed_full_sync_row_does_not_delete_existing_cache(tmp_db):
    assert upsert_jira_records([_jira_record("KEEP-2")], replace_existing=True)
    malformed = {"id": "", "title": "Issue without a stable Jira key"}
    assert not upsert_jira_records([malformed], replace_existing=True)
    assert query("SELECT jira_key FROM jira_issues WHERE jira_key = 'KEEP-2'")
