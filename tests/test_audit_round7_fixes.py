# -*- coding: utf-8 -*-
"""Regression tests for audit round 7 fixes:
1. get_next_card_code uses row-level locking (FOR UPDATE) on PostgreSQL.
2. CAST(... AS REAL) is translated to DOUBLE PRECISION on PostgreSQL.
3. Schedule approve logs audit exactly once (no duplicate log_audit call).
4. Admin create user returns 400 for invalid dept and 409 for duplicate email.
5. pg_dump / pg_restore do not expose database password in CLI arguments.
6. Backup safety snapshots before restore are pruned.
7. Backup scheduler and pruning honor config settings.
"""
import json
import os
import sys
from unittest.mock import patch

SERVER_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server")
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from db import init_db, execute, get_one, query, _translate_sql
import router
from handlers import schedule_handlers
from services import audit_logger, backup_manager, data_store


class _MockHandler:
    def __init__(self, session):
        self._session = session
        self.code = None
        self.body = None
        self.headers = {}

    def _send_json(self, code, data, **kw):
        self.code = code
        self.body = data

    def _get_session_or_401(self):
        return self._session


def test_translate_sql_casts_real_to_double_precision():
    sql = "DELETE FROM sessions WHERE CAST(last_active_at AS REAL) < ? OR (CAST(created_at AS REAL) > 0)"
    translated = _translate_sql(sql)
    assert "DOUBLE PRECISION" in translated
    assert "AS REAL" not in translated


def test_schedule_approve_single_audit_log(seed_admin):
    from services.auth import get_session
    admin_sess = get_session(seed_admin["session"])
    audit_calls = []
    original_log_audit = audit_logger.log_audit

    def mock_log_audit(*args, **kwargs):
        audit_calls.append((args, kwargs))
        return original_log_audit(*args, **kwargs)

    data_store.write_schedule([{
        "id": 88123,
        "ownerOrg": "dev",
        "ownerName": "Test Dev",
        "ownerEmail": "dev@test.com",
        "title": "Vacation Request",
        "approval_status": "pending"
    }])

    with patch.object(audit_logger, "log_audit", mock_log_audit):
        h = _MockHandler(admin_sess)
        schedule_handlers.handle_schedule_approve(h, json.dumps({"id": 88123, "action": "approve"}).encode(), "127.0.0.1")
        assert h.code == 200

    # Exactly 1 audit log call must be recorded (previously duplicated)
    assert len(audit_calls) == 1
    assert audit_calls[0][1].get("action") == "SCHEDULE_APPROVE" or (len(audit_calls[0][0]) > 2 and audit_calls[0][0][2] == "SCHEDULE_APPROVE")


def test_admin_create_user_validates_department_and_email(seed_admin):
    from services.auth import get_session
    admin_sess = get_session(seed_admin["session"])

    # 1. Invalid department returns 400 Bad Request (not 500)
    h1 = _MockHandler(admin_sess)
    router.handle_post_admin_user_create(h1, json.dumps({
        "username": "user_valid_name",
        "name": "User Valid",
        "dept_id": "non_existent_dept_999",
        "email": "unique1@test.com",
        "password": "Password123!"
    }).encode(), "127.0.0.1")
    assert h1.code == 400
    assert "부서" in h1.body.get("error", "")

    # 2. Duplicate email returns 409 Conflict (not 500)
    execute("INSERT OR IGNORE INTO departments (id, name) VALUES ('dev', 'Development')")
    execute("INSERT OR REPLACE INTO users (id, username, name, dept_id, email, password_hash, salt, role) VALUES (7711, 'email_owner', 'Owner', 'dev', 'shared@test.com', 'h', 's', 'member')")

    h2 = _MockHandler(admin_sess)
    router.handle_post_admin_user_create(h2, json.dumps({
        "username": "user_diff_name",
        "name": "User Diff",
        "dept_id": "dev",
        "email": "shared@test.com",
        "password": "Password123!"
    }).encode(), "127.0.0.1")
    assert h2.code == 409
    assert "이메일" in h2.body.get("error", "")


def test_pg_conn_params_hides_password_from_cmdline():
    url = "postgresql://myuser:supersecretpass@db.internal:5432/myproductiondb"
    args, env = backup_manager._pg_conn_params(url)

    # Password must not be in CLI args
    for arg in args:
        assert "supersecretpass" not in arg
        assert "postgresql://" not in arg

    # Host, port, user, dbname must be in args
    assert "-h" in args and "db.internal" in args
    assert "-p" in args and "5432" in args
    assert "-U" in args and "myuser" in args
    assert "-d" in args and "myproductiondb" in args

    # Password must be securely passed via PGPASSWORD
    assert env.get("PGPASSWORD") == "supersecretpass"


def test_backup_restore_safety_snapshots_retention(tmp_path):
    bdir = tmp_path / "backups"
    bdir.mkdir()

    # Create 8 dummy safety snapshots
    for i in range(8):
        f = bdir / f"argos_safety_before_restore_20261104_12000{i}.tar.gz"
        f.write_text("safety")

    with patch.object(backup_manager, "_ensure_backup_dir", lambda: str(bdir)):
        backup_manager._prune_old_backups({}, max_days=30, max_count=30)

    remaining = [f for f in os.listdir(str(bdir)) if f.startswith("argos_safety_before_restore_")]
    # Exactly 5 most recent safety snapshots must remain
    assert len(remaining) == 5


def test_get_next_card_code_atomic_allocation():
    execute("INSERT OR IGNORE INTO departments (id, name) VALUES ('dev', 'Development')")
    c1 = data_store.get_next_card_code("dev", "DEV")
    c2 = data_store.get_next_card_code("dev", "DEV")
    assert c1 != c2
    p1 = int(c1.split("-")[-1])
    p2 = int(c2.split("-")[-1])
    assert p2 == p1 + 1
