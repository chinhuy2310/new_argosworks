import os
import sys
import unittest
import tempfile
import sqlite3

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_DIR = os.path.join(BASE_DIR, "server")
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

import db


@unittest.skipUnless(
    getattr(db, "ENGINE", "sqlite") == "sqlite",
    "SQLite-specific initialisation test (PostgreSQL is covered by test_postgres_smoke.py "
    "and test_engine_contract.py)",
)
class TestDatabase(unittest.TestCase):
    def setUp(self):
        # Use an in-memory or temporary sqlite database for tests
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp_dir, "test.sqlite")
        db.DB_PATH = self.db_path

    def tearDown(self):
        import shutil
        try:
            shutil.rmtree(self.tmp_dir)
        except Exception:
            pass

    def test_init_db_creates_canonical_tables(self):
        db.init_db()
        tables = db.query("SELECT name FROM sqlite_master WHERE type='table'")
        table_names = {t["name"] for t in tables}
        
        # Verify essential core tables exist
        self.assertIn("users", table_names)
        self.assertIn("records", table_names)
        self.assertIn("departments", table_names)
        self.assertIn("license_info", table_names)
        self.assertIn("audit_logs", table_names)
        self.assertIn("product_categories", table_names)

    def test_audit_logs_table_structure(self):
        db.init_db()
        cols = db.query("PRAGMA table_info(audit_logs)")
        col_names = {c["name"] for c in cols}
        self.assertIn("action", col_names)
        self.assertIn("username", col_names)
        self.assertIn("timestamp", col_names)
        self.assertIn("details_json", col_names)

if __name__ == "__main__":
    unittest.main()
