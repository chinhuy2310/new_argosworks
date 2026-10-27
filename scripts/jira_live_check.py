#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""jira_live_check.py — Live Jira Cloud connectivity smoke test (real network).

tests/test_jira_client.py mocks urllib, so it can never prove that the configured
Jira account/token/project actually work. This script talks to the REAL instance
configured in .env and walks the same code paths the server uses:

  1. config resolution ............ JIRA_ENABLED / BASE_URL / EMAIL / TOKEN / PROJECT_KEY
  2. GET /rest/api/3/myself ....... credentials are valid
  3. GET /rest/api/3/project/{KEY}  the account can see the project
  4. createmeta/{KEY}/issuetypes .. which issue types we may create
  5. check_jira_connection_status()  the router's health probe
  6. jira_search_issues() ......... production JQL/search path (read-only)
  7. --create: create_jira_issue() + add_jira_comment()  (WRITES to Jira)

Usage (from the repository root):
    python scripts/jira_live_check.py              # read-only checks
    python scripts/jira_live_check.py --create     # also create a smoke-test issue

Exit code: 0 = every executed check passed, 1 = at least one failed.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_DIR = os.path.join(ROOT_DIR, "server")
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from config import load_config  # noqa: E402
from services import jira_client  # noqa: E402

TIMEOUT_SEC = 20
RESULTS = []

try:  # Korean log lines from jira_client must not kill the report
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _mask(secret):
    """Never print the API token in full."""
    if not secret:
        return "(empty)"
    if len(secret) <= 12:
        return "*" * len(secret)
    return "%s...%s (len=%d)" % (secret[:6], secret[-4:], len(secret))


def _snippet(payload):
    if isinstance(payload, (dict, list)):
        text = json.dumps(payload, ensure_ascii=False)
    else:
        text = str(payload)
    text = " ".join(text.split())
    return text[:300]


def jira_get(cfg, path):
    """GET through jira_client's own auth header + SSL policy (production path)."""
    base_url = (cfg.get("jira") or {}).get("base_url", "").rstrip("/")
    req = urllib.request.Request(
        base_url + path, method="GET", headers=jira_client._jira_auth_header(cfg["jira"])
    )
    try:
        with jira_client._urlopen(req, timeout=TIMEOUT_SEC) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def record(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    line = "  [%s] %s" % ("PASS" if ok else "FAIL", name)
    if detail:
        line += " — " + str(detail)
    print(line)
    return ok


def run_check(name, fn, cfg):
    try:
        ok, detail = fn(cfg)
    except urllib.error.HTTPError as e:
        ok, detail = False, "HTTP %s: %s" % (e.code, e.read().decode("utf-8", "replace")[:300])
    except Exception as e:  # smoke test: keep going so every step is reported
        ok, detail = False, "%s: %s" % (type(e).__name__, e)
    return record(name, ok, detail)


# ---------------------------------------------------------------------------
# checks
# ---------------------------------------------------------------------------
def check_config(cfg):
    j = cfg.get("jira") or {}
    print("       base_url        : %s" % (j.get("base_url") or "(empty)"))
    print("       email           : %s" % (j.get("email") or "(empty)"))
    print("       api_token       : %s" % _mask(j.get("api_token")))
    print("       default_project : %s" % (j.get("default_project_key") or "(empty)"))
    print("       project_map     : %s" % json.dumps(j.get("project_map") or {}, ensure_ascii=False, sort_keys=True))

    missing = [k for k in ("base_url", "email", "api_token") if not j.get(k)]
    if not j.get("enabled"):
        missing.append("enabled=false (set JIRA_ENABLED=true)")
    if missing:
        return False, ", ".join(missing)
    return True, "Jira enabled and credentials resolved from .env"


def check_myself(cfg):
    status, data = jira_get(cfg, "/rest/api/3/myself")
    if status != 200 or not isinstance(data, dict):
        return False, "HTTP %s: %s" % (status, _snippet(data))
    return True, "%s <%s> accountId=%s active=%s" % (
        data.get("displayName"),
        data.get("emailAddress") or "?",
        data.get("accountId"),
        data.get("active"),
    )


def check_project(cfg):
    key = (cfg.get("jira") or {}).get("default_project_key")
    if not key:
        return False, "JIRA_PROJECT_KEY is empty"
    status, data = jira_get(cfg, "/rest/api/3/project/%s" % urllib.parse.quote(key))
    if status != 200 or not isinstance(data, dict):
        return False, "HTTP %s: %s" % (status, _snippet(data))
    return True, "%s (%s, id=%s)" % (data.get("name"), data.get("projectTypeKey"), data.get("id"))


def check_issue_types(cfg):
    key = (cfg.get("jira") or {}).get("default_project_key")
    if not key:
        return False, "JIRA_PROJECT_KEY is empty"
    status, data = jira_get(
        cfg, "/rest/api/3/issue/createmeta/%s/issuetypes?maxResults=50" % urllib.parse.quote(key)
    )
    if status != 200 or not isinstance(data, dict):
        return False, "HTTP %s: %s" % (status, _snippet(data))
    names = [str(t.get("name")) for t in (data.get("issueTypes") or [])]
    if not names:
        return False, "no creatable issue types returned (check project permissions)"
    return True, ", ".join(names)


def check_connection_status(cfg):
    ready, message = jira_client.check_jira_connection_status(cfg)
    return ready, message


def check_search(cfg):
    records, activities = jira_client.jira_search_issues(cfg, max_results=100, page_size=50)
    if records is None:
        return False, "jira_search_issues() returned None (auth/JQL/network error — see log above)"
    if not records:
        return True, "0 issues returned (API call succeeded; project may be empty)"
    keys = [(r.get("jira") or {}).get("key") for r in records[:5]]
    return True, "%d issue(s), %d activity item(s); sample=%s" % (
        len(records),
        len(activities or []),
        ", ".join(str(k) for k in keys if k) or "-",
    )


def check_create(cfg):
    j = cfg.get("jira") or {}
    key = j.get("default_project_key")
    issue_type = j.get("default_issue_type") or "Task"
    if not key:
        return False, "JIRA_PROJECT_KEY is empty"
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    issue, note = jira_client.create_jira_issue(
        cfg,
        key,
        issue_type,
        "ARGOS WORKS live check %s" % stamp,
        "Automated ARGOS WORKS connectivity check - safe to delete.",
        ["argos-smoke-test"],
        None,
    )
    if not issue:
        return False, note or "create_jira_issue() returned no issue"
    print("       created: %s" % issue.get("url"))

    payload, comment_note = jira_client.add_jira_comment(
        cfg, issue["key"], "ARGOS WORKS live check comment at %s" % stamp
    )
    if not payload:
        return False, "%s created, but comment failed: %s" % (issue["key"], comment_note)
    return True, "%s created with comment (%s)" % (issue["key"], issue.get("url"))


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Live Jira Cloud connectivity check for ARGOS WORKS")
    parser.add_argument(
        "--create",
        action="store_true",
        help="also create a real smoke-test issue (and one comment) in the configured project",
    )
    args = parser.parse_args()

    print("ARGOS WORKS - live Jira connectivity check")
    print("=" * 68)
    cfg = load_config()

    checks = [
        ("config resolved from .env", check_config),
        ("GET /rest/api/3/myself (auth)", check_myself),
        ("GET /rest/api/3/project/{key}", check_project),
        ("creatable issue types", check_issue_types),
        ("check_jira_connection_status()", check_connection_status),
        ("jira_search_issues() (read-only)", check_search),
    ]
    if args.create:
        checks.append(("create_jira_issue() + add_jira_comment()", check_create))

    for name, fn in checks:
        run_check(name, fn, cfg)

    failed = [name for name, ok, _ in RESULTS if not ok]
    print("-" * 68)
    print("%d/%d checks passed" % (len(RESULTS) - len(failed), len(RESULTS)))
    if failed:
        print("FAILED: " + "; ".join(failed))
        return 1
    print("All live Jira checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
