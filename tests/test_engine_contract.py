"""
test_engine_contract.py — Hợp đồng (contract) giữa hai engine DB.

Mục tiêu: lỗi "chỉ chạy được trên SQLite" phải bị bắt ngay trong CI, không lòi ra
ở khách hàng (docker-compose mặc định dùng PostgreSQL).

Bao gồm:
1. Schema parity: `schema.sql` (SQLite) và `schema.postgres.sql` phải có **cùng tập
   bảng và cùng tập cột** (khác biệt kiểu dữ liệu là có chủ đích). Test này bắt được
   các lỗi thực tế: thiếu bảng `login_attempts`, thiếu cột `hash_algo`/`iterations`.
2. Engine contract: DATABASE_URL phải khớp engine đang chọn; baseline schema phải
   tạo đủ bảng trên engine đang chạy (SQLite hoặc PostgreSQL thật).
3. Hành vi DB facade phải giống nhau: `execute()` trả id cho bảng có cột `id` và
   KHÔNG lỗi với bảng không có `id`; `transaction()` rollback; `write_schedule()`
   giữ được `owner_id`.
4. Lockout brute-force phải được lưu bền (bảng `login_attempts`) — trước đây trên
   PostgreSQL bảng này không tồn tại nên cơ chế lockout âm thầm rơi về in-memory.
"""
import os
import re
import sys

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_DIR = os.path.join(BASE_DIR, "server")
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

import db  # noqa: E402
from db import init_db, execute, get_one, query, transaction  # noqa: E402

DATABASE_URL = os.environ.get("DATABASE_URL", "")
EXPECTED_ENGINE = "postgres" if DATABASE_URL.startswith(("postgresql://", "postgres://")) else "sqlite"

CANONICAL_TABLES = {
    "departments", "users", "records", "record_attachments", "record_comments",
    "record_jira", "schedule_events", "schedule_participants", "products",
    "product_attachments", "product_categories", "chat_sessions", "chat_messages",
    "activities", "lounge_messages", "sessions", "notifications", "jira_issues",
    "jira_comments", "jira_attachments", "jira_changelog", "audit_logs",
    "license_info", "ai_usage", "login_attempts", "schema_migrations",
    "card_sequences",
}


def _parse_schema(rel_path):
    """{table: [column, ...]} parsed from a CREATE TABLE ... ); block."""
    path = os.path.join(BASE_DIR, rel_path)
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    tables = {}
    pattern = re.compile(r"CREATE TABLE IF NOT EXISTS\s+(\w+)\s*\((.*?)\n\);", re.S | re.I)
    for match in pattern.finditer(text):
        name = match.group(1).lower()
        cols = []
        for line in match.group(2).splitlines():
            line = line.strip()
            if not line or line.startswith("--"):
                continue
            if re.match(r"(?i)^(primary key|unique|constraint|foreign key|check)\b", line):
                continue
            col = re.match(r"([A-Za-z_][A-Za-z0-9_]*)", line)
            if col:
                cols.append(col.group(1).lower())
        tables[name] = cols
    return tables


class TestSchemaParity:
    """The two schema files must describe the same logical database."""

    def test_same_tables(self):
        sqlite_tables = set(_parse_schema("server/schema.sql"))
        pg_tables = set(_parse_schema("server/schema.postgres.sql"))
        assert sqlite_tables == pg_tables, (
            f"schema mismatch — SQLite only: {sorted(sqlite_tables - pg_tables)}, "
            f"PostgreSQL only: {sorted(pg_tables - sqlite_tables)}"
        )

    def test_same_columns(self):
        sqlite_schema = _parse_schema("server/schema.sql")
        pg_schema = _parse_schema("server/schema.postgres.sql")
        problems = []
        for table in sorted(set(sqlite_schema) & set(pg_schema)):
            a, b = set(sqlite_schema[table]), set(pg_schema[table])
            if a != b:
                problems.append(
                    f"{table}: SQLite only={sorted(a - b)} PostgreSQL only={sorted(b - a)}"
                )
        assert not problems, "column mismatch — " + " | ".join(problems)

    def test_canonical_tables_are_documented(self):
        """Every core table must be present in BOTH schema files."""
        for path in ("server/schema.sql", "server/schema.postgres.sql"):
            names = set(_parse_schema(path))
            missing = CANONICAL_TABLES - names
            assert not missing, f"{path} is missing: {sorted(missing)}"


class TestSqlTranslationPortability:
    """Placeholder translation must be safe for psycopg2's %-formatting."""

    def test_literal_percent_is_escaped(self):
        translated = db._translate_sql(
            "DELETE FROM sessions WHERE user_name LIKE 'test_%'"
        )
        assert "'test_%%'" in translated, translated

    def test_placeholders_are_not_doubled(self):
        translated = db._translate_sql("SELECT * FROM users WHERE id = ? AND name = ?")
        assert translated.count("%s") == 2, translated
        assert "%%s" not in translated, translated

    def test_rowid_order_by(self):
        translated = db._translate_sql("SELECT id FROM departments ORDER BY rowid")
        assert "order by id" in translated.lower(), translated
        assert "rowid" not in translated.lower(), translated


class TestEngineSelection:
    def test_engine_matches_database_url(self):
        """A 'PostgreSQL CI run' must not silently fall back to SQLite."""
        assert db.ENGINE == EXPECTED_ENGINE, (
            f"DATABASE_URL selects {EXPECTED_ENGINE!r} but db.ENGINE={db.ENGINE!r}"
        )

    def test_baseline_creates_every_table(self, tmp_db):
        names = set(tmp_db.list_tables())
        missing = CANONICAL_TABLES - names
        assert not missing, f"[{db.ENGINE}] baseline schema missing tables: {sorted(missing)}"

    def test_baseline_seeds_departments_and_license(self, tmp_db):
        ids = {d["id"] for d in tmp_db.query("SELECT id FROM departments")}
        assert {"dev", "sales", "hr", "mgmt"} <= ids, f"[{db.ENGINE}] missing seeded departments"
        assert tmp_db.get_one("SELECT id FROM license_info WHERE id = 1") is not None


class TestDbFacadeBehaviour:
    """Same observable behaviour on SQLite and PostgreSQL."""

    def test_execute_returns_id_for_tables_with_id(self, tmp_db):
        rec_id = 996501
        try:
            new_id = tmp_db.execute(
                """INSERT INTO records(id, dept_id, category, title, assignee_name, status)
                   VALUES (?, 'dev', '개발', 'CONTRACT_ID_TABLE', 'ContractUser', '진행')""",
                (rec_id,),
            )
            row = tmp_db.get_one("SELECT id FROM records WHERE id = ?", (rec_id,))
            assert row is not None
            # The row id must be usable as the "last inserted id" on both engines.
            assert int(new_id or 0) == rec_id, f"[{db.ENGINE}] execute() returned {new_id!r}"
        finally:
            tmp_db.execute("DELETE FROM records WHERE id = ?", (rec_id,))

    def test_execute_works_for_tables_without_id(self, tmp_db):
        """record_jira has no `id` column — INSERT must not raise/try RETURNING id."""
        rec_id = 996502
        try:
            tmp_db.execute(
                """INSERT INTO records(id, dept_id, category, title, assignee_name, status)
                   VALUES (?, 'dev', '개발', 'CONTRACT_NO_ID', 'ContractUser', '진행')""",
                (rec_id,),
            )
            tmp_db.execute(
                "INSERT OR REPLACE INTO record_jira(record_id, jira_key, jira_status, jira_url) VALUES (?, ?, ?, ?)",
                (rec_id, "CONTRACT-1", "진행", "https://example.invalid/browse/CONTRACT-1"),
            )
            row = tmp_db.get_one("SELECT jira_key FROM record_jira WHERE record_id = ?", (rec_id,))
            assert row is not None and row["jira_key"] == "CONTRACT-1"
        finally:
            tmp_db.execute("DELETE FROM record_jira WHERE record_id = ?", (rec_id,))
            tmp_db.execute("DELETE FROM records WHERE id = ?", (rec_id,))

    def test_transaction_rolls_back(self, tmp_db):
        def _boom(conn):
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO departments(id, name, color_index) VALUES (?, ?, ?)",
                ("contract_rollback", "Contract Rollback", 9),
            )
            raise ValueError("intentional")

        with pytest.raises(ValueError):
            tmp_db.transaction(_boom)
        assert tmp_db.get_one("SELECT id FROM departments WHERE id = ?", ("contract_rollback",)) is None

    def test_write_schedule_keeps_owner_link(self, tmp_db):
        """owner_id must be resolved from ownerName/ownerOrg on both engines."""
        from services.auth import create_user, hash_password
        from services.data_store import write_schedule

        salt, pwd = hash_password("ContractPass1!")
        user = create_user("Contract Owner", "contract_owner", "dev", "contract_owner@test.local",
                           salt, pwd, role="member")
        assert user, "user creation failed (schema must expose hash_algo/iterations)"
        event_id = 996503
        try:
            write_schedule([{
                "id": event_id, "ownerKey": "Contract Owner|dev", "ownerName": "Contract Owner",
                "ownerOrg": "dev", "ownerEmail": "contract_owner@test.local", "type": "업무",
                "title": "CONTRACT_SCHEDULE", "startDate": "2099-05-01", "endDate": "2099-05-02",
                "memo": "", "createdAt": "2099-05-01T00:00:00",
            }])
            row = tmp_db.get_one("SELECT owner_id FROM schedule_events WHERE id = ?", (event_id,))
            assert row is not None
            assert row["owner_id"] == user["id"], f"[{db.ENGINE}] owner_id was not linked: {row}"
        finally:
            tmp_db.execute("DELETE FROM schedule_participants WHERE event_id = ?", (event_id,))
            tmp_db.execute("DELETE FROM schedule_events WHERE id = ?", (event_id,))
            tmp_db.execute("DELETE FROM users WHERE id = ?", (user["id"],))

    def test_login_attempts_persist_in_database(self, tmp_db):
        """Brute-force lockout must be stored in the DB on both engines."""
        from services.auth import (
            check_login_rate_limit, clear_login_failures, record_login_failure,
        )

        ip, ident = "198.51.100.77", "contract_lockout_user"
        clear_login_failures(ip, ident)
        try:
            for _ in range(5):
                record_login_failure(ip, ident)
            row = tmp_db.get_one(
                "SELECT COUNT(*) AS c FROM login_attempts WHERE identifier = ?", (ident,)
            )
            assert row and int(row["c"]) >= 5, (
                f"[{db.ENGINE}] login failures were not persisted: {row}"
            )
            allowed, msg = check_login_rate_limit(ip, ident)
            assert allowed is False, f"[{db.ENGINE}] lockout did not trigger"
            assert "잠금" in msg or "차단" in msg
        finally:
            clear_login_failures(ip, ident)

