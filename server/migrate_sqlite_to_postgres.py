"""
migrate_sqlite_to_postgres.py — Production Data Migration Utility
Migrates all tables and rows from existing SQLite database to PostgreSQL instance.
Usage:
    python server/migrate_sqlite_to_postgres.py --sqlite data/argos.db --pg postgresql://user:pass@localhost:5432/argos_works
"""

import os
import sys
import sqlite3
import argparse
import json

TABLES = [
    "departments",
    "card_sequences",
    "users",
    "records",
    "record_attachments",
    "record_comments",
    "record_jira",
    "schedule_events",
    "schedule_participants",
    "products",
    "product_attachments",
    "product_categories",
    "chat_sessions",
    "chat_messages",
    "activities",
    "lounge_messages",
    "sessions",
    "notifications",
    "notification_reads",
    "sync_meta",
    "jira_issues",
    "jira_comments",
    "jira_attachments",
    "jira_changelog",
    "schema_migrations",
    "audit_logs",
    "license_info"
]

def migrate_data(sqlite_path: str, pg_dsn: str):
    try:
        import psycopg2
        import psycopg2.extras
    except ImportError:
        print("[Error] 'psycopg2' is required for migration. Run: pip install psycopg2-binary", file=sys.stderr)
        sys.exit(1)

    if not os.path.isfile(sqlite_path):
        print(f"[Error] SQLite file not found: {sqlite_path}", file=sys.stderr)
        sys.exit(1)

    print(f"[*] Connecting to SQLite: {sqlite_path}")
    sq_conn = sqlite3.connect(sqlite_path)
    sq_conn.row_factory = sqlite3.Row

    print(f"[*] Connecting to PostgreSQL: {pg_dsn}")
    pg_conn = psycopg2.connect(pg_dsn)
    pg_cur = pg_conn.cursor()

    # Apply schema first if schema.postgres.sql exists
    schema_pg = os.path.join(os.path.dirname(__file__), "schema.postgres.sql")
    if os.path.isfile(schema_pg):
        print("[*] Applying PostgreSQL schema...")
        with open(schema_pg, "r", encoding="utf-8") as f:
            pg_cur.execute(f.read())
        pg_conn.commit()

    total_rows = 0
    for tbl in TABLES:
        # Check if table exists in SQLite
        sq_cur = sq_conn.cursor()
        sq_cur.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{tbl}'")
        if not sq_cur.fetchone():
            continue

        sq_cur.execute(f"SELECT * FROM {tbl}")
        rows = sq_cur.fetchall()
        if not rows:
            continue

        col_names = [col[0] for col in sq_cur.description]
        placeholders = ",".join(["%s"] * len(col_names))
        cols_str = ",".join(col_names)

        insert_sql = f"INSERT INTO {tbl} ({cols_str}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"

        batch_data = []
        for r in rows:
            batch_data.append([r[col] for col in col_names])

        psycopg2.extras.execute_batch(pg_cur, insert_sql, batch_data)
        pg_conn.commit()
        print(f"  [+] Migrated {len(batch_data)} rows for table '{tbl}'")
        total_rows += len(batch_data)

    print(f"[SUCCESS] Migration completed! Total {total_rows} rows transferred.")
    sq_conn.close()
    pg_conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate SQLite to PostgreSQL")
    parser.add_argument("--sqlite", default=os.path.join(os.path.dirname(__file__), "..", "data", "argos.db"), help="Path to SQLite database")
    parser.add_argument("--pg", default=os.environ.get("DATABASE_URL", "postgresql://argos:argos123@localhost:5432/argos_works"), help="PostgreSQL DSN")
    args = parser.parse_args()

    migrate_data(args.sqlite, args.pg)
