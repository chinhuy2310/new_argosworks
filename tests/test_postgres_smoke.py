"""
PostgreSQL compatibility gate (P0).

The shipped docker-compose stack defaults to PostgreSQL, but before this test
existed the PostgreSQL path had never been executed: the suite only ran against
SQLite, and two router queries used the SQLite-only clause ``COLLATE NOCASE``,
which makes PostgreSQL raise a syntax error.

Two layers:
  * TestSqlTranslation — pure-Python, runs everywhere (no database needed).
  * TestPostgresEngine — runs only when DATABASE_URL points at PostgreSQL
    (CI job `postgres-tests` provisions a real PostgreSQL 16 service and asserts
    that the engine really is PostgreSQL; `tests/test_engine_contract.py` covers
    the cross-engine contract and schema parity).
"""
import os
import sys
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_DIR = os.path.join(BASE_DIR, "server")
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

import db  # noqa: E402

DATABASE_URL = os.environ.get("DATABASE_URL", "")
IS_POSTGRES = DATABASE_URL.startswith(("postgresql://", "postgres://"))


class TestSqlTranslation(unittest.TestCase):
    """Dialect translation must stay correct regardless of the active engine."""

    def test_placeholders_are_translated_outside_string_literals(self):
        translated = db._translate_sql("SELECT '?' AS q, ? AS v FROM t WHERE a = ?")
        self.assertIn("'?'", translated)
        self.assertIn("%s AS v", translated)
        self.assertIn("a = %s", translated)
        self.assertNotIn("? AS v", translated)

    def test_pragma_statements_are_dropped(self):
        self.assertIsNone(db._translate_sql("PRAGMA table_info(users)"))
        self.assertIsNone(db._translate_sql("  pragma journal_mode = WAL"))

    def test_insert_or_ignore_becomes_on_conflict_do_nothing(self):
        translated = db._translate_sql(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)"
        )
        self.assertIn("INSERT INTO settings", translated)
        self.assertIn("ON CONFLICT DO NOTHING", translated)
        self.assertNotIn("OR IGNORE", translated)

    def test_insert_or_replace_becomes_upsert_on_table_primary_key(self):
        translated = db._translate_sql(
            "INSERT OR REPLACE INTO record_jira (record_id, jira_key, updated_at) "
            "VALUES (?, ?, ?)"
        )
        self.assertIn("ON CONFLICT (record_id) DO UPDATE SET", translated)
        self.assertIn("jira_key = EXCLUDED.jira_key", translated)
        self.assertNotIn("record_id = EXCLUDED.record_id", translated)

    def test_sqlite_strftime_now_becomes_current_timestamp(self):
        translated = db._translate_sql(
            "INSERT INTO audit_logs (created_at) "
            "VALUES (strftime('%Y-%m-%d %H:%M:%S','now'))"
        )
        self.assertIn("CURRENT_TIMESTAMP", translated)
        self.assertNotIn("strftime", translated)

    def test_server_code_avoids_sqlite_only_collations(self):
        """COLLATE NOCASE is a SQLite-only clause; PostgreSQL rejects it outright."""
        offenders = []
        for root, _dirs, files in os.walk(SERVER_DIR):
            for name in files:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(root, name)
                try:
                    with open(path, "r", encoding="utf-8", errors="ignore") as handle:
                        if "COLLATE NOCASE" in handle.read():
                            offenders.append(os.path.relpath(path, BASE_DIR))
                except OSError:
                    continue
        self.assertEqual(offenders, [], f"SQLite-only COLLATE NOCASE found in: {offenders}")


@unittest.skipUnless(
    IS_POSTGRES,
    "set DATABASE_URL=postgresql://... to exercise the PostgreSQL engine "
    "(CI job `postgres-tests` provides a live server)",
)
class TestPostgresEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if db.ENGINE != "postgres":
            raise unittest.SkipTest("db module did not select the postgres engine")
        db.init_db()

    def test_01_engine_selected(self):
        self.assertEqual(db.ENGINE, "postgres")

    def test_02_baseline_schema_is_present(self):
        # list_tables() follows the active search_path (the test suite runs in an
        # isolated schema; production uses the default one).
        tables = set(db.list_tables())
        for expected in (
            "users",
            "records",
            "departments",
            "audit_logs",
            "license_info",
            "schema_migrations",
        ):
            with self.subTest(table=expected):
                self.assertIn(expected, tables)

    def test_03_upsert_and_ignore_round_trip(self):
        db.execute("DROP TABLE IF EXISTS ci_smoke")
        db.execute(
            "CREATE TABLE ci_smoke (id INTEGER PRIMARY KEY, name TEXT, updated_at TEXT)"
        )
        try:
            db.execute(
                "INSERT OR REPLACE INTO ci_smoke (id, name, updated_at) "
                "VALUES (?, ?, CURRENT_TIMESTAMP)",
                (1, "first"),
            )
            db.execute(
                "INSERT OR REPLACE INTO ci_smoke (id, name, updated_at) "
                "VALUES (?, ?, CURRENT_TIMESTAMP)",
                (1, "second"),
            )
            rows = db.query("SELECT name FROM ci_smoke WHERE id = ?", (1,))
            self.assertEqual([row["name"] for row in rows], ["second"])

            db.execute(
                "INSERT OR IGNORE INTO ci_smoke (id, name) VALUES (?, ?)",
                (1, "ignored"),
            )
            rows = db.query("SELECT name FROM ci_smoke WHERE id = ?", (1,))
            self.assertEqual(rows[0]["name"], "second")
        finally:
            db.execute("DROP TABLE IF EXISTS ci_smoke")

    def test_04_question_mark_inside_literal_is_preserved(self):
        rows = db.query("SELECT 'what?' AS marker, ? AS echoed", ("ok",))
        self.assertEqual(rows[0]["marker"], "what?")
        self.assertEqual(rows[0]["echoed"], "ok")

    def test_05_get_one_returns_dict(self):
        row = db.get_one("SELECT 1 AS one")
        self.assertEqual(row["one"], 1)


if __name__ == "__main__":
    unittest.main()
