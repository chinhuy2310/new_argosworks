# Testing ARGOS WORKS

The test suite runs on **both** database engines. PostgreSQL is the default for the
shipped `docker-compose.yml`, SQLite is used by `run_server.bat` (zero-infra
deployments), so a change must pass on both.

## Quick start

```bash
pip install -r requirements.lock

# SQLite (default when DATABASE_URL is empty)
pytest -q

# PostgreSQL (any reachable server)
export DATABASE_URL="postgresql://user:password@localhost:5432/argos_works"
pytest -q
```

Windows PowerShell uses `$env:DATABASE_URL="postgresql://..."` instead of `export`.

## How engine isolation works

| Engine | Isolation |
| --- | --- |
| SQLite | `tests/conftest.py::tmp_db` points `db.get_db_path()` at a temp file per test. |
| PostgreSQL | The whole session runs in a throw-away schema (`argos_test_run_<uuid>`); `tmp_db` additionally creates a nested schema per test. Both are dropped automatically. |

Both are implemented in `server/db.py` (`set_search_path()`, `drop_schema()`,
`list_tables()`, `list_indexes()`, `table_columns()`), so tests never touch the real
database and never query `sqlite_master`/`PRAGMA` directly.

Because a fresh connection pool is created for every isolated schema, `conftest.py`
also lowers the pool size for tests (`ARGOS_PG_POOL_MIN=1`, `ARGOS_PG_POOL_MAX=8`);
otherwise 10 connections per test would exhaust a 100-connection test server.
Production defaults (10..128) are unchanged and configurable with the same variables.

Because migration 3+ run inside the target schema, re-running the suite against a
used database is reproducible — no manual cleanup is required.

## Which tests are engine-specific?

- `tests/test_db.py`, `tests/test_backup_restore.py` — SQLite file layout / WAL /
  file backups. They are skipped when `DATABASE_URL` selects PostgreSQL.
- `tests/test_postgres_smoke.py` — SQL translation (always) + live PostgreSQL checks
  (only when PostgreSQL is selected).
- `tests/test_engine_contract.py` — runs on both engines: schema parity between
  `schema.sql` and `schema.postgres.sql` (same tables **and** columns), engine
  selection guard, `execute()`/`transaction()` semantics, `write_schedule()`
  owner linking and brute-force lockout persistence.

## PostgreSQL locally without Docker

`pgserver` bundles the PostgreSQL binaries and is enough for the suite:

```python
# keep_server.py — start once, keep it running while pytest executes
import pgserver, time
srv = pgserver.get_server("C:/tmp/argos_pg/data", cleanup_mode=None)
print(srv.get_uri())   # postgresql://postgres:@127.0.0.1:<port>/postgres
while True:
    time.sleep(30)
```

```bash
pip install pgserver psycopg2-binary
python keep_server.py            # copy the printed DSN
DATABASE_URL="<printed DSN>" pytest -q
```

With Docker, use the same PostgreSQL version as production:

```bash
docker run -d --name argos-pg -e POSTGRES_PASSWORD=pg -p 5432:5432 postgres:16-alpine
DATABASE_URL="postgresql://postgres:pg@localhost:5432/postgres" pytest -q
```

## CI

`.github/workflows/ci.yml` runs:

1. `sqlite-tests` — full suite with `DATABASE_URL=""`.
2. `postgres-tests` — full suite against a real `postgres:16-alpine` service; a
   bootstrap step fails the job if `db.ENGINE != "postgres"` (so a misconfigured
   URL can never turn the PostgreSQL job into a second SQLite run).
3. `security-scan`, `docker-build-verify` — vulnerability audit, image build.
4. `container-smoke` — boots the shipped `docker-compose.yml`
   (app + PostgreSQL + Caddy) and checks `/api/health`, `/api/version`,
   `/api/setup/status`, and that `/api/records` returns 401 without a session.

## Upgrading an existing PostgreSQL deployment

`db.init_db()` applies the PostgreSQL migrations idempotently on every start
(`schema_migrations`):

| Version | Purpose |
| --- | --- |
| 2 | unique indexes on `users(username)` / `users(email)` |
| 3 | `login_attempts` (persistent brute-force lockout) |
| 4 | `users.hash_algo` / `users.iterations` (password metadata) |
| 5 | widen free-text columns to `TEXT` (SQLite parity) |

All of them are additive/non-destructive; no manual SQL is required.
