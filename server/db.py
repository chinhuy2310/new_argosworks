"""
db.py — Dual-Engine Database Layer (SQLite + PostgreSQL)

Auto-detects DATABASE_URL environment variable:
  - If set and starts with 'postgresql' → PostgreSQL mode (psycopg2 connection pool)
  - Otherwise → SQLite mode (thread-local connections, WAL mode)

All public functions maintain identical signatures and return types.
Consumer modules (14 files) require ZERO changes.
"""

import os
import re
import threading
import logging
from urllib.parse import quote

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Engine Detection
# ---------------------------------------------------------------------------
DATABASE_URL = os.environ.get("DATABASE_URL", "")
ENGINE = "postgres" if DATABASE_URL and DATABASE_URL.startswith("postgresql") else "sqlite"

logger.info(f"[db] Database engine: {ENGINE.upper()}")

# ---------------------------------------------------------------------------
# SQL Translation Layer (SQLite → PostgreSQL)
# ---------------------------------------------------------------------------
# Compiled regexes for performance (called on every query)
_RE_QMARK = re.compile(r"\?")
_RE_INSERT_OR_IGNORE = re.compile(
    r"INSERT\s+OR\s+IGNORE\s+INTO\s+(\w+)\s*\(([^)]+)\)",
    re.IGNORECASE,
)
_RE_INSERT_OR_REPLACE = re.compile(
    r"INSERT\s+OR\s+REPLACE\s+INTO\s+(\w+)\s*\(([^)]+)\)\s*VALUES\s*\(([^)]+)\)",
    re.IGNORECASE,
)
# Header-only variant: used to determine the conflict target / update columns without
# assuming a single VALUES row.
_RE_INSERT_OR_REPLACE_HEAD = re.compile(
    r"INSERT\s+OR\s+REPLACE\s+INTO\s+(\w+)\s*\(([^)]+)\)",
    re.IGNORECASE,
)
# Primary keys used as the ON CONFLICT target when rewriting INSERT OR REPLACE.
_REPLACE_PK_MAP = {
    "record_jira": "record_id",
    "card_sequences": "dept_id",
    "departments": "id",
    "users": "id",
    "records": "id",
    "products": "id",
    "license_info": "id",
    "schema_migrations": "version",
    "product_categories": "id",
    "document_embeddings": "doc_id",
}
_RE_STRFTIME_NOW = re.compile(
    r"strftime\s*\(\s*'[^']*'\s*,\s*'now'\s*\)",
    re.IGNORECASE,
)
_RE_DATETIME_NOW = re.compile(
    r"datetime\s*\(\s*'now'\s*\)",
    re.IGNORECASE,
)
_RE_PRAGMA = re.compile(r"^\s*PRAGMA\s+", re.IGNORECASE)
# SQLite exposes an implicit "rowid" pseudo-column that PostgreSQL does not have.
# All ARGOS tables use an explicit "id" primary key, so ordering by rowid (insert
# order in SQLite) has to fall back to ordering by the primary key on PostgreSQL.
_RE_ORDER_BY_ROWID = re.compile(r"\bORDER\s+BY\s+rowid\b", re.IGNORECASE)


def _translate_sql(sql):
    """
    Translates SQLite-dialect SQL to PostgreSQL-compatible SQL.
    Only called when ENGINE == 'postgres'.
    Safely replaces parameter '?' without breaking string literals containing '?'.
    """
    # 1. Skip PRAGMA statements entirely (SQLite-only)
    if _RE_PRAGMA.match(sql):
        return None  # Signal to skip

    # 2. strftime('%Y-...','now') or datetime('now') → CURRENT_TIMESTAMP
    sql = _RE_STRFTIME_NOW.sub("CURRENT_TIMESTAMP", sql)
    sql = _RE_DATETIME_NOW.sub("CURRENT_TIMESTAMP", sql)

    # 2b. ORDER BY rowid → ORDER BY id (SQLite implicit rowid is unavailable in PostgreSQL)
    sql = _RE_ORDER_BY_ROWID.sub("ORDER BY id", sql)

    # 3. INSERT OR IGNORE → INSERT ... ON CONFLICT DO NOTHING
    m = _RE_INSERT_OR_IGNORE.search(sql)
    if m:
        sql = _RE_INSERT_OR_IGNORE.sub(r"INSERT INTO \1 (\2)", sql)
        # Append ON CONFLICT DO NOTHING if not already present
        if "ON CONFLICT" not in sql.upper():
            sql = sql.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"

    # 4. INSERT OR REPLACE → INSERT ... ON CONFLICT (pk) DO UPDATE SET col = EXCLUDED.col
    #    NOTE: the ON CONFLICT clause is appended at the END of the statement. Rewriting
    #    the VALUES clause only worked for single-row inserts; a multi-row insert
    #    (`VALUES (...), (...)`) produced `ON CONFLICT ... , (...)` → syntax error.
    if re.search(r"INSERT\s+OR\s+REPLACE\s+INTO", sql, re.IGNORECASE):
        head = _RE_INSERT_OR_REPLACE_HEAD.search(sql)
        conflict_pk = None
        update_cols = []
        if head:
            table = head.group(1).lower()
            cols = [c.strip() for c in head.group(2).split(",") if c.strip()]
            conflict_pk = _REPLACE_PK_MAP.get(table, cols[0] if cols else "id")
            update_cols = [c for c in cols if c.lower() != conflict_pk.lower()]

        sql = re.sub(r"INSERT\s+OR\s+REPLACE\s+INTO", "INSERT INTO", sql, flags=re.IGNORECASE)
        if "ON CONFLICT" not in sql.upper():
            stripped = sql.rstrip()
            trailing = ""
            if stripped.endswith(";"):
                stripped = stripped[:-1].rstrip()
                trailing = ";"
            if conflict_pk and update_cols:
                conflict_clause = (
                    f" ON CONFLICT ({conflict_pk}) DO UPDATE SET "
                    + ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)
                )
            elif conflict_pk:
                conflict_clause = f" ON CONFLICT ({conflict_pk}) DO NOTHING"
            else:
                conflict_clause = " ON CONFLICT DO NOTHING"
            sql = stripped + conflict_clause + trailing

    # 4b. Escape literal percent signs.
    #     psycopg2 applies %-style interpolation whenever parameters are supplied,
    #     so a query containing a literal `%` (e.g. "... LIKE 'test_%'") raises
    #     `IndexError: tuple index out of range`. Doubling them keeps the literal
    #     intact; the ? → %s placeholders are introduced afterwards.
    sql = sql.replace("%", "%%")

    # 5. ? → %s (parameter placeholders) - ONLY outside string literals
    parts = re.split(r"('(?:''|[^'])*')", sql)
    for i in range(0, len(parts), 2):
        parts[i] = parts[i].replace("?", "%s")
    sql = "".join(parts)

    return sql


def _translate_params(params):
    """
    Ensures params is always a tuple for psycopg2.
    """
    if params is None:
        return ()
    if isinstance(params, (list, tuple)):
        return tuple(params)
    return (params,)


# ============================================================================
# SQLite Engine
# ============================================================================
if ENGINE == "sqlite":
    import sqlite3

    _tls = threading.local()

    def dict_factory(cursor, row):
        """Row factory that converts rows into dictionaries."""
        return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}

    def get_db_path():
        """Returns the absolute path to the database file."""
        from app_paths import APP_HOME
        data_dir = os.path.join(APP_HOME, 'data')
        os.makedirs(data_dir, exist_ok=True)
        return os.path.join(data_dir, 'argos.db')

    def init_db():
        """
        Initializes the database: ensures the db file exists, applies schema.sql,
        enables WAL mode, foreign keys, and sets a busy timeout.
        """
        db_path = get_db_path()
        from app_paths import RES_DIR
        schema_path = os.path.join(RES_DIR, 'schema.sql')

        logger.info(f"Initializing SQLite database at {db_path}")

        # Pre-migration safety snapshot: Protect on-premise customer data before DDL
        if os.path.exists(db_path) and os.path.getsize(db_path) > 0:
            try:
                from datetime import datetime
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                data_dir = os.path.dirname(db_path)
                snap_dir = os.path.join(data_dir, "backups")
                os.makedirs(snap_dir, exist_ok=True)
                snap_file = os.path.join(snap_dir, f"argos_safety_before_migration_{ts}.tmp.db")
                with sqlite3.connect(db_path) as s_conn, sqlite3.connect(snap_file) as d_conn:
                    s_conn.backup(d_conn)
                logger.info(f"[db] Pre-migration safety snapshot created: {snap_file}")
            except Exception as e:
                logger.warning(f"[db] Pre-migration safety snapshot notice: {e}")

        conn = sqlite3.connect(db_path, isolation_level=None)
        try:
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA synchronous = NORMAL;")
            conn.execute("PRAGMA foreign_keys = ON;")
            conn.execute("PRAGMA busy_timeout = 5000;")

            # 1. Apply Canonical Schema FIRST (ensures all tables & canonical columns exist on clean installs)
            if os.path.exists(schema_path):
                with open(schema_path, 'r', encoding='utf-8') as f:
                    schema_script = f.read()
                conn.executescript(schema_script)
                logger.info("Canonical schema applied successfully.")

                # Customer install (ARGOS_FRESH_INSTALL=1) must not inherit the
                # vendor's demo departments: the setup wizard creates the
                # customer's own organization chart.
                if (os.environ.get("ARGOS_FRESH_INSTALL", "").strip().lower() in ("1", "true", "yes", "on")):
                    try:
                        user_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
                        record_count = conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]
                        if user_count == 0 and record_count == 0:
                            conn.execute(
                                "DELETE FROM departments WHERE id IN ('mgmt','dev','sales','hr','hq')"
                            )
                            logger.info("[db] Fresh-install mode: demo departments removed.")
                    except Exception as e:
                        logger.warning(f"[db] Fresh-install cleanup skipped: {e}")

                conn.execute("""
                    INSERT OR IGNORE INTO schema_migrations (version, name)
                    VALUES (1, 'v2.0_baseline_canonical_schema');
                """)
            else:
                logger.warning(f"Schema file not found at {schema_path}")

            # 2. Versioned Migrations Check & Upgrades (for existing legacy databases)
            applied_migrations = {row[0] for row in conn.execute("SELECT version FROM schema_migrations").fetchall()}

            # Migration v2: Unique indexes on users (username, email) and session foreign key index
            if 2 not in applied_migrations:
                conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username_unique ON users(username) WHERE username != '';")
                conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_unique ON users(email) WHERE email != '';")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);")
                conn.execute("INSERT OR IGNORE INTO schema_migrations (version, name) VALUES (2, 'v2.1_users_unique_constraints');")
                logger.info("[db] Migration v2 (unique constraints & indexes) applied.")

            # Migration v3: Legacy column backfill & schema alignment
            if 3 not in applied_migrations:
                # Check tables and alter legacy columns if missing
                cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
                existing_tables = {row[0] for row in cur.fetchall()}

                if "records" in existing_tables:
                    r_cols = {row[1] for row in conn.execute("PRAGMA table_info(records)").fetchall()}
                    for col_name, col_def in [
                        ("status", "TEXT NOT NULL DEFAULT '진행'"),
                        ("card_code", "TEXT NOT NULL DEFAULT ''"),
                        ("start_date", "TEXT NOT NULL DEFAULT ''"),
                        ("due_date", "TEXT NOT NULL DEFAULT ''"),
                        ("is_scheduled", "INTEGER NOT NULL DEFAULT 1"),
                        ("is_private", "INTEGER NOT NULL DEFAULT 0"),
                        ("priority", "TEXT NOT NULL DEFAULT '보통'"),
                        ("version", "INTEGER NOT NULL DEFAULT 1"),
                        ("updated_at", "TEXT NOT NULL DEFAULT ''")
                    ]:
                        if col_name not in r_cols:
                            conn.execute(f"ALTER TABLE records ADD COLUMN {col_name} {col_def};")

                    conn.execute("UPDATE records SET updated_at = created_at WHERE updated_at = '' OR updated_at IS NULL;")

                    # Backfill work_date -> start_date / due_date
                    rows = conn.execute("SELECT id, work_date, start_date, due_date FROM records").fetchall()
                    for row in rows:
                        rec_id = row[0]
                        w_date = (row[1] or "").strip()
                        s_date = (row[2] or "").strip()
                        d_date = (row[3] or "").strip()
                        if (not s_date or not d_date) and w_date:
                            if "~" in w_date:
                                parts = [p.strip() for p in w_date.split("~")]
                                s_val = parts[0]
                                d_val = parts[1] if len(parts) > 1 and parts[1] else s_val
                            else:
                                s_val = w_date
                                d_val = w_date
                            conn.execute("UPDATE records SET start_date = ?, due_date = ? WHERE id = ?", (s_val, d_val, rec_id))

                if "departments" in existing_tables:
                    d_cols = {row[1] for row in conn.execute("PRAGMA table_info(departments)").fetchall()}
                    if "local_prefix" not in d_cols:
                        conn.execute("ALTER TABLE departments ADD COLUMN local_prefix TEXT NOT NULL DEFAULT '';")
                    if "jira_key" not in d_cols:
                        conn.execute("ALTER TABLE departments ADD COLUMN jira_key TEXT NOT NULL DEFAULT '';")

                if "products" in existing_tables:
                    p_cols = {row[1] for row in conn.execute("PRAGMA table_info(products)").fetchall()}
                    if "source" not in p_cols:
                        conn.execute("ALTER TABLE products ADD COLUMN source TEXT NOT NULL DEFAULT 'internal';")
                    if "price" not in p_cols:
                        conn.execute("ALTER TABLE products ADD COLUMN price INTEGER DEFAULT 0;")
                    if "currency" not in p_cols:
                        conn.execute("ALTER TABLE products ADD COLUMN currency TEXT NOT NULL DEFAULT 'KRW';")

                if "users" in existing_tables:
                    u_cols = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
                    if "username" not in u_cols:
                        conn.execute("ALTER TABLE users ADD COLUMN username TEXT NOT NULL DEFAULT '';")
                    if "role" not in u_cols:
                        conn.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'member';")
                        conn.execute("UPDATE users SET role = 'admin' WHERE is_admin = 1;")
                    if "disabled" not in u_cols:
                        conn.execute("ALTER TABLE users ADD COLUMN disabled INTEGER NOT NULL DEFAULT 0;")
                    if "status" not in u_cols:
                        conn.execute("ALTER TABLE users ADD COLUMN status TEXT NOT NULL DEFAULT 'active';")
                    if "hash_algo" not in u_cols:
                        conn.execute("ALTER TABLE users ADD COLUMN hash_algo TEXT NOT NULL DEFAULT 'pbkdf2_sha256';")
                    if "iterations" not in u_cols:
                        conn.execute("ALTER TABLE users ADD COLUMN iterations INTEGER NOT NULL DEFAULT 600000;")
                    if "avatar_url" not in u_cols:
                        conn.execute("ALTER TABLE users ADD COLUMN avatar_url TEXT NOT NULL DEFAULT '';")

                if "sessions" in existing_tables:
                    s_cols = {row[1] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
                    if "user_id" not in s_cols:
                        conn.execute("ALTER TABLE sessions ADD COLUMN user_id INTEGER REFERENCES users(id) ON DELETE CASCADE;")
                        conn.execute("""
                            UPDATE sessions
                            SET user_id = (
                                SELECT id FROM users
                                WHERE users.name = sessions.user_name AND users.dept_id = sessions.user_dept_id
                                LIMIT 1
                            )
                            WHERE user_id IS NULL;
                        """)
                    if "last_active_at" not in s_cols:
                        conn.execute("ALTER TABLE sessions ADD COLUMN last_active_at REAL DEFAULT 0;")
                        conn.execute("UPDATE sessions SET last_active_at = created_at WHERE last_active_at = 0;")

                conn.execute("INSERT OR IGNORE INTO schema_migrations (version, name) VALUES (3, 'v2.2_legacy_column_alignment');")
                logger.info("[db] Migration v3 (legacy alignment) applied.")

            # Migration v4: Session token security and sliding expiration column
            if 4 not in applied_migrations:
                cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sessions'")
                if cur.fetchone():
                    s_cols = {row[1] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
                    if "last_active_at" not in s_cols:
                        conn.execute("ALTER TABLE sessions ADD COLUMN last_active_at REAL DEFAULT 0;")
                        conn.execute("UPDATE sessions SET last_active_at = created_at WHERE last_active_at = 0;")
                conn.execute("INSERT OR IGNORE INTO schema_migrations (version, name) VALUES (4, 'v2.3_session_sliding_ttl');")
                logger.info("[db] Migration v4 (sessions last_active_at) applied.")
        except sqlite3.Error as e:
            logger.error(f"Database initialization failed: {e}")
            raise
        finally:
            conn.close()

    def get_connection():
        """Returns a thread-local database connection."""
        if not hasattr(_tls, 'conn') or _tls.conn is None:
            db_path = get_db_path()
            conn = sqlite3.connect(db_path, check_same_thread=False)
            conn.row_factory = dict_factory
            conn.execute("PRAGMA foreign_keys = ON;")
            conn.execute("PRAGMA busy_timeout = 5000;")
            conn.execute("PRAGMA synchronous = NORMAL;")
            # 8GB RAM Optimization: Allocate 64MB cache per thread and use RAM for temporary tables
            conn.execute("PRAGMA cache_size = -64000;")  # 64MB memory cache
            conn.execute("PRAGMA temp_store = MEMORY;")
            _tls.conn = conn
        return _tls.conn

    def close_connection(force=False):
        """
        Closes the thread-local database connection.

        `force` is accepted for cross-engine API parity: in PostgreSQL mode it is
        the only way to drop the shared pool (restore/shutdown), while SQLite
        always releases the thread-local connection.
        """
        if hasattr(_tls, 'conn') and _tls.conn is not None:
            try:
                _tls.conn.close()
            except sqlite3.Error:
                pass
            finally:
                _tls.conn = None

    def get_search_path():
        """SQLite has no schemas — provided for cross-engine code/fixtures."""
        return ""

    def set_search_path(schema):
        """No-op on SQLite (isolation is done with a temp database file)."""
        return None

    def drop_schema(schema):
        """No-op on SQLite."""
        return None

    def list_tables():
        """Table names in the current database (portable across both engines)."""
        rows = query("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
        return [r["name"] for r in rows]

    def list_indexes():
        """Index names in the current database (portable across both engines)."""
        rows = query("SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%' ORDER BY name")
        return [r["name"] for r in rows]

    def table_columns(table):
        """Column names of a table (portable across both engines)."""
        rows = query(f"PRAGMA table_info({table})")
        return [r["name"] for r in rows]

    def query(sql, params=()):
        """Executes a SELECT query and returns a list of dictionaries."""
        conn = get_connection()
        try:
            cursor = conn.execute(sql, params)
            return cursor.fetchall()
        except sqlite3.Error as e:
            logger.error(f"Error executing query: {sql}\nParams: {params}\nError: {e}")
            raise

    def get_one(sql, params=()):
        """Executes a SELECT query and returns a single row as a dictionary, or None."""
        conn = get_connection()
        try:
            cursor = conn.execute(sql, params)
            return cursor.fetchone()
        except sqlite3.Error as e:
            logger.error(f"Error executing get_one: {sql}\nParams: {params}\nError: {e}")
            raise

    def execute(sql, params=()):
        """Executes an INSERT, UPDATE, or DELETE query and returns the last inserted row id."""
        conn = get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            conn.commit()
            return cursor.lastrowid
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"Error executing statement: {sql}\nParams: {params}\nError: {e}")
            raise
        finally:
            cursor.close()

    def execute_rowcount(sql, params=()):
        """Executes an UPDATE or DELETE query and returns the number of modified rows."""
        conn = get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            conn.commit()
            return cursor.rowcount
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"Error executing statement for rowcount: {sql}\nParams: {params}\nError: {e}")
            raise
        finally:
            cursor.close()

    def executemany(sql, params_list):
        """Executes a batch INSERT/UPDATE/DELETE."""
        conn = get_connection()
        try:
            cursor = conn.cursor()
            cursor.executemany(sql, params_list)
            conn.commit()
            return cursor.rowcount
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"Error executing executemany: {sql}\nError: {e}")
            raise
        finally:
            cursor.close()

    _tls_tx = threading.local()

    def transaction(fn):
        """
        Executes a function fn(conn) within a transaction.
        Supports nested transactions safely via SAVEPOINTs and nesting depth tracking.
        """
        conn = get_connection()
        depth = getattr(_tls_tx, 'depth', 0)
        _tls_tx.depth = depth + 1

        if depth == 0:
            try:
                conn.execute("BEGIN IMMEDIATE;")
                result = fn(conn)
                conn.commit()
                return result
            except Exception as e:
                try:
                    conn.rollback()
                except Exception:
                    pass
                logger.error(f"Transaction failed, rolled back: {e}")
                raise
            finally:
                _tls_tx.depth = 0
        else:
            sp_name = f"sp_{depth}"
            conn.execute(f"SAVEPOINT {sp_name};")
            try:
                result = fn(conn)
                conn.execute(f"RELEASE SAVEPOINT {sp_name};")
                return result
            except Exception as e:
                try:
                    conn.execute(f"ROLLBACK TO SAVEPOINT {sp_name};")
                except Exception:
                    pass
                logger.error(f"Nested transaction ({sp_name}) failed, rolled back: {e}")
                raise
            finally:
                _tls_tx.depth = depth

# ============================================================================
# PostgreSQL Engine
# ============================================================================
else:
    import psycopg2
    import psycopg2.pool
    import psycopg2.extras
    import psycopg2.extensions

    # ---- Connection Pool (thread-safe) ----
    _pool = None
    _pool_lock = threading.Lock()

    # Optional search_path override. Production leaves this empty; the test suite
    # uses it to give every test its own isolated PostgreSQL schema instead of
    # sharing the CI database (SQLite gets the same isolation via a temp file).
    _search_path = ""

    # Pool sizing. Enterprise default is 10..128; the test suite lowers it through
    # ARGOS_PG_POOL_MIN/MAX because it creates a fresh pool per isolated schema
    # (10 connections per test would exhaust a 100-connection test server).
    def _env_int(name, default):
        try:
            return max(1, int(os.environ.get(name, "") or default))
        except (TypeError, ValueError):
            return default

    _POOL_MIN = _env_int("ARGOS_PG_POOL_MIN", 10)
    _POOL_MAX = max(_POOL_MIN, _env_int("ARGOS_PG_POOL_MAX", 128))

    def _connection_dsn():
        """DATABASE_URL, with the optional isolated search_path as a libpq option."""
        if not _search_path:
            return DATABASE_URL
        separator = "&" if "?" in DATABASE_URL else "?"
        options = quote(f"-c search_path={_search_path}", safe="")
        return f"{DATABASE_URL}{separator}options={options}"

    def get_search_path():
        """Current search_path override ('' when using the default schema)."""
        return _search_path

    def set_search_path(schema):
        """
        Point all pooled connections at `schema` ('' restores the default).

        Existing connections are discarded so the new search_path takes effect.
        """
        global _search_path
        _search_path = (schema or "").strip()
        close_connection(force=True)

    def _quote_identifier(name):
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name or ""):
            raise ValueError(f"Invalid SQL identifier: {name!r}")
        return '"' + name + '"'

    def _release(pool, conn):
        """
        Return a connection to the pool **without** leaving an open transaction.

        psycopg2 opens a transaction on the first execute(). Returning a connection
        that only ran a SELECT back to the pool leaves it "idle in transaction",
        which keeps ACCESS SHARE locks (blocking DDL such as CREATE/DROP SCHEMA and
        autovacuum) until the next statement. That made the PostgreSQL test suite
        hang on schema teardown and is equally wrong in production.
        """
        try:
            if conn is not None and not conn.closed:
                if conn.get_transaction_status() != psycopg2.extensions.TRANSACTION_STATUS_IDLE:
                    conn.rollback()
        except Exception:
            pass
        try:
            if conn is not None:
                pool.putconn(conn)
        except Exception:
            pass

    def drop_schema(schema):
        """Drop an isolated schema (test-fixture cleanup). Refuses unsafe names."""
        if not schema:
            return
        pool = _get_pool()
        conn = pool.getconn()
        try:
            if conn.get_transaction_status() != psycopg2.extensions.TRANSACTION_STATUS_IDLE:
                conn.rollback()
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(f"DROP SCHEMA IF EXISTS {_quote_identifier(schema)} CASCADE")
        finally:
            conn.autocommit = False
            _release(pool, conn)

    def _get_pool():
        """Lazily initializes and returns the PostgreSQL connection pool."""
        global _pool
        if _pool is None or _pool.closed:
            with _pool_lock:
                if _pool is None or _pool.closed:
                    # Sizing connection pool to match worker thread capacity (up to 128 workers)
                    _pool = psycopg2.pool.ThreadedConnectionPool(
                        minconn=_POOL_MIN,
                        maxconn=_POOL_MAX,
                        dsn=_connection_dsn(),
                    )
                    logger.info(
                        "[db/postgres] Connection pool created (min=%s, max=%s)",
                        _POOL_MIN, _POOL_MAX,
                    )
        return _pool

    def get_db_path():
        """
        Returns DATABASE_URL for PostgreSQL mode.
        Maintained for backward compatibility (backup_manager imports this).
        """
        return DATABASE_URL

    def init_db():
        """
        Initializes the PostgreSQL database with versioned migration check.
        Ensures baseline schema is applied only when needed and tracked in schema_migrations.
        """
        from app_paths import RES_DIR
        schema_path = os.path.join(RES_DIR, 'schema.postgres.sql')
        logger.info(f"[db/postgres] Initializing database with schema: {schema_path}")

        pool = _get_pool()
        conn = pool.getconn()
        try:
            conn.autocommit = True
            cur = conn.cursor()

            # 0. Ensure the isolated schema exists (test fixtures / dedicated schema)
            if _search_path:
                cur.execute(f"CREATE SCHEMA IF NOT EXISTS {_quote_identifier(_search_path)}")

            # 1. Ensure schema_migrations table exists
            cur.execute("""
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name VARCHAR(128) NOT NULL,
                    applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
            """)

            cur.execute("SELECT version FROM schema_migrations;")
            applied_versions = {row[0] for row in cur.fetchall()}

            # Migration 1: Baseline enterprise postgres schema
            if 1 not in applied_versions and os.path.exists(schema_path):
                with open(schema_path, 'r', encoding='utf-8') as f:
                    schema_script = f.read()
                cur.execute(schema_script)
                cur.execute("""
                    INSERT INTO schema_migrations (version, name)
                    VALUES (1, 'v2.0_baseline_enterprise_postgres')
                    ON CONFLICT (version) DO NOTHING;
                """)
                logger.info("[db/postgres] Migration v1 (baseline) applied.")
            else:
                logger.info("[db/postgres] Migration v1 already applied or schema missing. Skipping baseline.")

            # Migration 2: Unique indexes on users (username, email) to prevent race conditions
            if 2 not in applied_versions:
                cur.execute("""
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username_unique ON users(username) WHERE username != '';
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_unique ON users(email) WHERE email != '';
                    INSERT INTO schema_migrations (version, name)
                    VALUES (2, 'v2.1_users_unique_constraints')
                    ON CONFLICT (version) DO NOTHING;
                """)
                logger.info("[db/postgres] Migration v2 (users unique constraints) applied.")

            # Migration 3: login_attempts table for deployments created before it was
            # added to the baseline schema. Without it the brute-force lockout silently
            # falls back to per-process memory (see services/auth.py).
            if 3 not in applied_versions:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS login_attempts (
                        id BIGSERIAL PRIMARY KEY,
                        ip VARCHAR(64) NOT NULL,
                        identifier VARCHAR(255) NOT NULL,
                        failed_at DOUBLE PRECISION NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_login_attempts_ip_ident
                        ON login_attempts(ip, identifier, failed_at);
                    INSERT INTO schema_migrations (version, name)
                    VALUES (3, 'v2.4_login_attempts_persistence')
                    ON CONFLICT (version) DO NOTHING;
                """)
                logger.info("[db/postgres] Migration v3 (login_attempts) applied.")

            # Migration 4: password metadata columns for deployments created before
            # they were added to the baseline schema. Without them create_user()
            # fails (INSERT references hash_algo/iterations) and legacy PBKDF2 hashes
            # can never be auto-upgraded.
            if 4 not in applied_versions:
                cur.execute("""
                    ALTER TABLE users ADD COLUMN IF NOT EXISTS hash_algo VARCHAR(32) NOT NULL DEFAULT 'pbkdf2_sha256';
                    ALTER TABLE users ADD COLUMN IF NOT EXISTS iterations INTEGER NOT NULL DEFAULT 600000;
                    INSERT INTO schema_migrations (version, name)
                    VALUES (4, 'v2.5_users_password_metadata')
                    ON CONFLICT (version) DO NOTHING;
                """)
                logger.info("[db/postgres] Migration v4 (users password metadata) applied.")

            # Migration 5: widen free-text columns to TEXT.
            # PostgreSQL enforces VARCHAR(n) while SQLite does not, so long titles /
            # comments / filenames that are valid on SQLite raised 500 errors on
            # PostgreSQL. Widening is non-destructive (no data rewrite semantics
            # change, indexes are rebuilt automatically).
            if 5 not in applied_versions:
                cur.execute("""
                    ALTER TABLE users ALTER COLUMN name TYPE TEXT;
                    ALTER TABLE users ALTER COLUMN email TYPE TEXT;
                    ALTER TABLE records ALTER COLUMN category TYPE TEXT;
                    ALTER TABLE records ALTER COLUMN title TYPE TEXT;
                    ALTER TABLE records ALTER COLUMN project TYPE TEXT;
                    ALTER TABLE records ALTER COLUMN assignee_name TYPE TEXT;
                    ALTER TABLE records ALTER COLUMN assignee_email TYPE TEXT;
                    ALTER TABLE record_attachments ALTER COLUMN filename TYPE TEXT;
                    ALTER TABLE product_attachments ALTER COLUMN filename TYPE TEXT;
                    ALTER TABLE jira_attachments ALTER COLUMN filename TYPE TEXT;
                    ALTER TABLE record_comments ALTER COLUMN author_name TYPE TEXT;
                    ALTER TABLE schedule_events ALTER COLUMN title TYPE TEXT;
                    ALTER TABLE schedule_events ALTER COLUMN owner_name TYPE TEXT;
                    ALTER TABLE schedule_events ALTER COLUMN owner_email TYPE TEXT;
                    ALTER TABLE schedule_events ALTER COLUMN approved_by TYPE TEXT;
                    ALTER TABLE schedule_participants ALTER COLUMN user_name TYPE TEXT;
                    ALTER TABLE schedule_participants ALTER COLUMN user_email TYPE TEXT;
                    ALTER TABLE chat_messages ALTER COLUMN author_name TYPE TEXT;
                    ALTER TABLE notifications ALTER COLUMN title TYPE TEXT;
                    ALTER TABLE notifications ALTER COLUMN sender_name TYPE TEXT;
                    ALTER TABLE notifications ALTER COLUMN recipient_name TYPE TEXT;
                    ALTER TABLE jira_issues ALTER COLUMN assignee_name TYPE TEXT;
                    ALTER TABLE jira_issues ALTER COLUMN reporter_name TYPE TEXT;
                    ALTER TABLE audit_logs ALTER COLUMN username TYPE TEXT;
                    ALTER TABLE audit_logs ALTER COLUMN target_id TYPE TEXT;
                    INSERT INTO schema_migrations (version, name)
                    VALUES (5, 'v2.6_widen_free_text_columns')
                    ON CONFLICT (version) DO NOTHING;
                """)
                logger.info("[db/postgres] Migration v5 (free-text columns widened) applied.")

            cur.close()
        except psycopg2.Error as e:
            logger.error(f"[db/postgres] Database initialization failed: {e}")
            raise
        finally:
            conn.autocommit = False
            _release(pool, conn)

    def get_connection():
        """
        Returns a connection from the pool.
        NOTE: In PostgreSQL mode, callers should NOT hold connections long-term.
        This exists for backward compatibility with transaction().
        """
        return _get_pool().getconn()

    def close_connection(force=False):
        """
        Releases per-request resources.

        In PostgreSQL mode every query already borrows a pooled connection and
        returns it immediately, so the per-request cleanup performed by
        handler.py / wsgi.py must be a no-op: closing the whole pool after each
        request would drop 10-128 warm connections (and could close a connection
        another thread is still using).

        Pass force=True only when the pool must really be discarded
        (restore / shutdown); subsequent queries lazily rebuild it.
        """
        if not force:
            return
        global _pool
        if _pool is not None and not _pool.closed:
            with _pool_lock:
                if _pool is not None and not _pool.closed:
                    try:
                        _pool.closeall()
                    except Exception:
                        pass
                    _pool = None

    def _dict_cursor(conn):
        """Creates a cursor that returns dictionaries."""
        return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    def list_tables():
        """Table names visible through the current search_path."""
        rows = query(
            """SELECT table_name AS name FROM information_schema.tables
               WHERE table_schema = ANY (current_schemas(false))
               ORDER BY table_name"""
        )
        return [r["name"] for r in rows]

    def list_indexes():
        """Index names visible through the current search_path."""
        rows = query(
            """SELECT indexname AS name FROM pg_indexes
               WHERE schemaname = ANY (current_schemas(false))
               ORDER BY indexname"""
        )
        return [r["name"] for r in rows]

    def table_columns(table):
        """Column names of a table (portable across both engines)."""
        rows = query(
            """SELECT column_name AS name FROM information_schema.columns
               WHERE table_name = ? AND table_schema = ANY (current_schemas(false))
               ORDER BY ordinal_position""",
            (str(table or "").lower(),),
        )
        return [r["name"] for r in rows]

    def query(sql, params=()):
        """Executes a SELECT query and returns a list of dictionaries."""
        translated = _translate_sql(sql)
        if translated is None:
            return []  # PRAGMA → skip
        params = _translate_params(params)

        pool = _get_pool()
        conn = pool.getconn()
        try:
            cur = _dict_cursor(conn)
            cur.execute(translated, params)
            rows = cur.fetchall()
            cur.close()
            # Convert RealDictRow to plain dict for compatibility
            return [dict(r) for r in rows]
        except psycopg2.Error as e:
            conn.rollback()
            logger.error(f"[db/postgres] Error executing query: {sql}\nTranslated: {translated}\nParams: {params}\nError: {e}")
            raise
        finally:
            _release(pool, conn)

    def get_one(sql, params=()):
        """Executes a SELECT query and returns a single row as a dictionary, or None."""
        translated = _translate_sql(sql)
        if translated is None:
            return None
        params = _translate_params(params)

        pool = _get_pool()
        conn = pool.getconn()
        try:
            cur = _dict_cursor(conn)
            cur.execute(translated, params)
            row = cur.fetchone()
            cur.close()
            return dict(row) if row else None
        except psycopg2.Error as e:
            conn.rollback()
            logger.error(f"[db/postgres] Error executing get_one: {sql}\nTranslated: {translated}\nParams: {params}\nError: {e}")
            raise
        finally:
            _release(pool, conn)

    # Tables that have an "id" column, so INSERT ... RETURNING id is valid.
    # Cached per (schema, table): the schema matters because the test suite switches
    # search_path between isolated schemas.
    _insert_id_cache = {}
    _insert_id_lock = threading.Lock()
    _RE_INSERT_TABLE = re.compile(r"INSERT\s+INTO\s+([A-Za-z_][A-Za-z0-9_\.]*)", re.IGNORECASE)

    def _table_has_id_column(cur, translated_sql):
        """
        True when the INSERT target table exposes an `id` column.

        Used to decide whether `RETURNING id` can be appended. Previously it was
        appended unconditionally, so every INSERT into a table without an `id`
        column (record_jira, card_sequences) failed once, was rolled back and had
        to be retried — two round-trips plus a rollback per insert.
        """
        match = _RE_INSERT_TABLE.search(translated_sql)
        if not match:
            return False
        table = match.group(1).split(".")[-1].strip('"').lower()
        cache_key = (_search_path, table)
        cached = _insert_id_cache.get(cache_key)
        if cached is not None:
            return cached
        has_id = False
        try:
            cur.execute(
                """
                SELECT 1 FROM information_schema.columns
                 WHERE table_name = %s AND column_name = 'id'
                   AND table_schema = ANY (current_schemas(false))
                 LIMIT 1
                """,
                (table,),
            )
            has_id = cur.fetchone() is not None
        except psycopg2.Error:
            has_id = False
        with _insert_id_lock:
            _insert_id_cache[cache_key] = has_id
        return has_id

    def execute(sql, params=()):
        """Executes an INSERT, UPDATE, or DELETE query and returns the last inserted row id."""
        translated = _translate_sql(sql)
        if translated is None:
            return 0
        params = _translate_params(params)

        pool = _get_pool()
        conn = pool.getconn()
        try:
            cur = conn.cursor()
            sql_upper = translated.strip().upper()
            if sql_upper.startswith("INSERT") and "RETURNING" not in sql_upper:
                if _table_has_id_column(cur, translated):
                    exec_sql = translated.rstrip().rstrip(";") + " RETURNING id"
                    cur.execute(exec_sql, params)
                    row = cur.fetchone()
                    if row is not None:
                        # cursor asked with RealDictCursor below? use positional fallback
                        try:
                            new_id = row["id"]
                        except (TypeError, KeyError, IndexError):
                            new_id = row[0]
                    else:
                        new_id = 0
                    conn.commit()
                    cur.close()
                    return new_id
            cur.execute(translated, params)
            conn.commit()
            cur.close()
            return 0
        except psycopg2.Error as e:
            conn.rollback()
            logger.error(f"[db/postgres] Error executing statement: {sql}\nTranslated: {translated}\nParams: {params}\nError: {e}")
            raise
        finally:
            _release(pool, conn)

    def execute_rowcount(sql, params=()):
        """Executes an UPDATE or DELETE query and returns the number of modified rows."""
        translated = _translate_sql(sql)
        if translated is None:
            return 0
        params = _translate_params(params)

        pool = _get_pool()
        conn = pool.getconn()
        try:
            cur = conn.cursor()
            cur.execute(translated, params)
            rowcount = cur.rowcount
            conn.commit()
            cur.close()
            return rowcount
        except psycopg2.Error as e:
            conn.rollback()
            logger.error(f"[db/postgres] Error executing statement for rowcount: {sql}\nTranslated: {translated}\nParams: {params}\nError: {e}")
            raise
        finally:
            _release(pool, conn)

    def executemany(sql, params_list):
        """Executes a batch INSERT/UPDATE/DELETE using psycopg2's optimized execute_batch."""
        translated = _translate_sql(sql)
        if translated is None:
            return 0
        params_list = [_translate_params(p) for p in params_list]

        pool = _get_pool()
        conn = pool.getconn()
        try:
            cur = conn.cursor()
            psycopg2.extras.execute_batch(cur, translated, params_list)
            rowcount = cur.rowcount
            conn.commit()
            cur.close()
            return rowcount
        except psycopg2.Error as e:
            conn.rollback()
            logger.error(f"[db/postgres] Error executing executemany: {sql}\nTranslated: {translated}\nError: {e}")
            raise
        finally:
            _release(pool, conn)

    _tls_tx_pg = threading.local()

    def transaction(fn):
        """
        Executes a function fn(conn) within a transaction.
        The conn passed to fn is a TransactionProxy that auto-translates SQL.
        Supports nested transactions via SAVEPOINTs and thread-local connection tracking.
        """
        depth = getattr(_tls_tx_pg, 'depth', 0)
        if depth == 0:
            pool = _get_pool()
            conn = pool.getconn()
            _tls_tx_pg.conn = conn
            _tls_tx_pg.depth = 1
            try:
                proxy = _TransactionProxy(conn)
                result = fn(proxy)
                conn.commit()
                return result
            except Exception as e:
                try:
                    conn.rollback()
                except Exception:
                    pass
                logger.error(f"[db/postgres] Transaction failed, rolled back: {e}")
                raise
            finally:
                _tls_tx_pg.depth = 0
                _tls_tx_pg.conn = None
                _release(pool, conn)
        else:
            conn = _tls_tx_pg.conn
            _tls_tx_pg.depth = depth + 1
            sp_name = f"sp_{depth}"
            cur = conn.cursor()
            cur.execute(f"SAVEPOINT {sp_name};")
            cur.close()
            try:
                proxy = _TransactionProxy(conn)
                result = fn(proxy)
                cur = conn.cursor()
                cur.execute(f"RELEASE SAVEPOINT {sp_name};")
                cur.close()
                return result
            except Exception as e:
                try:
                    cur = conn.cursor()
                    cur.execute(f"ROLLBACK TO SAVEPOINT {sp_name};")
                    cur.close()
                except Exception:
                    pass
                logger.error(f"[db/postgres] Nested transaction ({sp_name}) failed, rolled back: {e}")
                raise
            finally:
                _tls_tx_pg.depth = depth

    class _TransactionProxy:
        """
        Wraps a psycopg2 connection to provide SQLite-compatible interface
        for transaction(fn) callbacks. Consumer code calls conn.execute(sql, params)
        and conn.cursor() — this proxy translates SQL transparently.
        """
        def __init__(self, real_conn):
            self._conn = real_conn

        def execute(self, sql, params=()):
            translated = _translate_sql(sql)
            if translated is None:
                return _DummyCursor()
            params = _translate_params(params)
            cur = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(translated, params)
            return cur

        def cursor(self):
            return _TransactionCursorProxy(self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor))

        def commit(self):
            pass  # Managed by outer transaction()

        def rollback(self):
            pass  # Managed by outer transaction()

    class _TransactionCursorProxy:
        """
        Wraps a psycopg2 cursor to translate SQL in transaction contexts
        where consumer code calls cur.execute(sql, params) directly.
        """
        def __init__(self, real_cursor):
            self._cur = real_cursor

        def execute(self, sql, params=()):
            translated = _translate_sql(sql)
            if translated is None:
                return self
            params = _translate_params(params)
            self._cur.execute(translated, params)
            return self

        def executemany(self, sql, params_list):
            translated = _translate_sql(sql)
            if translated is None:
                return self
            params_list = [_translate_params(p) for p in params_list]
            psycopg2.extras.execute_batch(self._cur, translated, params_list)
            return self

        def fetchall(self):
            rows = self._cur.fetchall()
            return [dict(r) for r in rows]

        def fetchone(self):
            row = self._cur.fetchone()
            return dict(row) if row else None

        def close(self):
            self._cur.close()

        @property
        def lastrowid(self):
            # psycopg2 doesn't have lastrowid; return 0 for safety
            return 0

        @property
        def rowcount(self):
            return self._cur.rowcount

        @property
        def description(self):
            return self._cur.description

    class _DummyCursor:
        """Returned when a PRAGMA or other skipped SQL is encountered."""
        def fetchall(self):
            return []
        def fetchone(self):
            return None
        def close(self):
            pass
        @property
        def lastrowid(self):
            return 0
        @property
        def rowcount(self):
            return 0
        @property
        def description(self):
            return None
