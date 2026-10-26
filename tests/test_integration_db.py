"""
test_integration_db.py — Integration Tests cho Database Layer
Kiểm tra: init_db, schema integrity, CRUD operations, transactions, migrations
Edge cases: concurrent access, WAL mode, foreign key constraints
"""
import os
import sys
import json
import threading
import tempfile
import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_DIR = os.path.join(BASE_DIR, "server")
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

os.environ.setdefault("ARGOS_MASTER_KEY", "test-master-key-for-unit-tests-2026")


# ============================================================================
# 1. Schema Initialization
# ============================================================================
class TestSchemaInitialization:
    """init_db: verify all required tables are created."""

    def test_core_tables_exist(self, tmp_db):
        tables = tmp_db.query("SELECT name FROM sqlite_master WHERE type='table'")
        names = {t["name"] for t in tables}
        required = {
            "departments", "users", "records", "record_attachments",
            "record_comments", "record_jira", "schedule_events",
            "schedule_participants", "products", "product_attachments",
            "chat_sessions", "chat_messages", "activities", "sessions",
            "notifications", "audit_logs", "license_info", "ai_usage",
            "jira_issues", "jira_comments", "jira_attachments",
            "login_attempts", "schema_migrations"
        }
        missing = required - names
        assert not missing, f"Missing tables: {missing}"

    def test_seed_departments_exist(self, tmp_db):
        depts = tmp_db.query("SELECT id, name FROM departments")
        ids = {d["id"] for d in depts}
        assert "dev" in ids
        assert "sales" in ids
        assert "hr" in ids
        assert "mgmt" in ids

    def test_license_seed_exists(self, tmp_db):
        lic = tmp_db.get_one("SELECT * FROM license_info WHERE id = 1")
        assert lic is not None
        assert lic["is_active"] == 1
        assert lic["max_seats"] == 50

    def test_indexes_created(self, tmp_db):
        indexes = tmp_db.query("SELECT name FROM sqlite_master WHERE type='index'")
        idx_names = {i["name"] for i in indexes}
        assert "idx_records_dept" in idx_names
        assert "idx_sessions_user_id" in idx_names
        assert "idx_audit_time" in idx_names

    def test_users_table_structure(self, tmp_db):
        cols = tmp_db.query("PRAGMA table_info(users)")
        col_names = {c["name"] for c in cols}
        required_cols = {
            "id", "username", "name", "dept_id", "email", "salt",
            "password_hash", "is_admin", "role", "disabled", "status"
        }
        missing = required_cols - col_names
        assert not missing, f"Missing columns in users: {missing}"


# ============================================================================
# 2. Basic CRUD Operations
# ============================================================================
class TestDatabaseCRUD:
    """query, get_one, execute, transaction: basic database operations."""

    def test_insert_and_query(self, tmp_db):
        tmp_db.execute(
            "INSERT INTO departments(id, name, color_index) VALUES (?, ?, ?)",
            ("test_dept", "Test Department", 7)
        )
        row = tmp_db.get_one("SELECT * FROM departments WHERE id = ?", ("test_dept",))
        assert row is not None
        assert row["name"] == "Test Department"

    def test_query_no_results(self, tmp_db):
        rows = tmp_db.query("SELECT * FROM users WHERE name = ?", ("nonexistent",))
        assert rows == []

    def test_get_one_no_results(self, tmp_db):
        row = tmp_db.get_one("SELECT * FROM users WHERE id = ?", (99999,))
        assert row is None

    def test_transaction_commit(self, tmp_db):
        def _insert(conn):
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO departments(id, name, color_index) VALUES (?, ?, ?)",
                ("tx_dept", "TX Dept", 1)
            )
        tmp_db.transaction(_insert)
        row = tmp_db.get_one("SELECT * FROM departments WHERE id = ?", ("tx_dept",))
        assert row is not None

    def test_transaction_rollback_on_error(self, tmp_db):
        def _bad_insert(conn):
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO departments(id, name, color_index) VALUES (?, ?, ?)",
                ("rollback_dept", "Rollback Dept", 1)
            )
            raise ValueError("Intentional error")

        with pytest.raises(ValueError):
            tmp_db.transaction(_bad_insert)
        row = tmp_db.get_one("SELECT * FROM departments WHERE id = ?", ("rollback_dept",))
        assert row is None  # Should be rolled back


# ============================================================================
# 3. Foreign Key Constraints
# ============================================================================
class TestForeignKeys:
    """Foreign key constraints verification."""

    def test_user_dept_fk(self, tmp_db):
        """User must reference existing department."""
        with pytest.raises(Exception):
            tmp_db.execute(
                """INSERT INTO users(name, username, dept_id, salt, password_hash)
                   VALUES (?, ?, ?, ?, ?)""",
                ("Test", "test", "nonexistent_dept_xyz", "salt", "hash")
            )

    def test_cascade_delete_record_attachments(self, tmp_db):
        """Deleting record should cascade-delete its attachments."""
        import time as t
        rec_id = int(t.time() * 1000)
        tmp_db.execute(
            """INSERT INTO records(id, dept_id, category, title, assignee_name, status)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (rec_id, "dev", "기능개발", "Test Record", "홍길동", "진행")
        )
        tmp_db.execute(
            "INSERT INTO record_attachments(record_id, filename) VALUES (?, ?)",
            (rec_id, "test.pdf")
        )
        # Verify attachment exists
        att = tmp_db.get_one("SELECT * FROM record_attachments WHERE record_id = ?", (rec_id,))
        assert att is not None

        # Delete record
        tmp_db.execute("DELETE FROM records WHERE id = ?", (rec_id,))
        # Attachment should be cascade-deleted
        att2 = tmp_db.get_one("SELECT * FROM record_attachments WHERE record_id = ?", (rec_id,))
        assert att2 is None

    def test_cascade_delete_record_comments(self, tmp_db):
        """Deleting record should cascade-delete its comments."""
        import time as t
        rec_id = int(t.time() * 1000) + 1
        tmp_db.execute(
            """INSERT INTO records(id, dept_id, category, title, assignee_name, status)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (rec_id, "dev", "기능개발", "Test Record", "홍길동", "진행")
        )
        tmp_db.execute(
            "INSERT INTO record_comments(record_id, author_name, body) VALUES (?, ?, ?)",
            (rec_id, "테스트유저", "Hello comment")
        )
        tmp_db.execute("DELETE FROM records WHERE id = ?", (rec_id,))
        cmt = tmp_db.get_one("SELECT * FROM record_comments WHERE record_id = ?", (rec_id,))
        assert cmt is None


# ============================================================================
# 4. Concurrent Access
# ============================================================================
class TestConcurrentAccess:
    """Multi-threaded database access (WAL mode)."""

    def test_concurrent_reads(self, tmp_db):
        results = []
        errors = []

        def read_depts():
            try:
                depts = tmp_db.query("SELECT * FROM departments")
                results.append(len(depts))
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=read_depts) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(errors) == 0, f"Errors: {errors}"
        assert len(results) == 10

    def test_concurrent_writes(self, tmp_db):
        errors = []

        def insert_user(i):
            try:
                from services.auth import hash_password, create_user
                salt, hashed = hash_password(f"pass{i}")
                create_user(
                    name=f"ConcUser{i}", username=f"concuser{i}",
                    org="dev", email=f"conc{i}@test.com",
                    salt=salt, hash_pwd=hashed
                )
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=insert_user, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert len(errors) == 0, f"Errors: {errors}"
        users = tmp_db.query("SELECT * FROM users WHERE username LIKE 'concuser%'")
        assert len(users) == 5


# ============================================================================
# 5. SQL Translation (SQLite → PostgreSQL compatibility checks)
# ============================================================================
class TestSQLTranslation:
    """db._translate_sql: verify SQLite → PostgreSQL SQL translation."""

    def test_pragma_skipped(self):
        import db as db_module
        result = db_module._translate_sql("PRAGMA foreign_keys = ON")
        assert result is None

    def test_question_mark_to_percent_s(self):
        import db as db_module
        result = db_module._translate_sql("SELECT * FROM users WHERE id = ? AND name = ?")
        assert "%s" in result
        assert "?" not in result

    def test_strftime_now_to_current_timestamp(self):
        import db as db_module
        sql = "SELECT strftime('%Y-%m-%dT%H:%M:%S','now') as ts"
        result = db_module._translate_sql(sql)
        assert "CURRENT_TIMESTAMP" in result

    def test_insert_or_ignore(self):
        import db as db_module
        sql = "INSERT OR IGNORE INTO departments(id, name) VALUES (?, ?)"
        result = db_module._translate_sql(sql)
        assert "ON CONFLICT DO NOTHING" in result
        assert "OR IGNORE" not in result

    def test_question_mark_in_string_literal_preserved(self):
        import db as db_module
        sql = "SELECT * FROM users WHERE name = '?' AND id = ?"
        result = db_module._translate_sql(sql)
        # '?' in string literal should be preserved, only bare ? replaced
        assert "'?'" in result
        assert result.count("%s") == 1
