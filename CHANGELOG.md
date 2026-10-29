# Changelog

All notable changes to ARGOS WORKS are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security — Eliminate Pass-the-Hash in session tokens (2.1)

- Removed legacy plaintext fallback `OR s.token = ?` from all session queries in `server/services/auth.py`, `server/handlers/auth_handlers.py`, and `server/router.py`. All session lookups, updates, and deletions now strictly match SHA-256 token hashes, completely preventing hash-equivalence authentication bypass.

### Fixed — Undefined name in notification_service (1.5)

- Moved `import sys` to module level in `server/services/notification_service.py` to prevent `NameError` in exception handlers during notification backfill.

### Fixed — Undefined name in auth_handlers (1.4)

- Added missing `log_line` import to `server/handlers/auth_handlers.py` to ensure unhandled registration errors return a clean JSON 500 without crashing with `NameError`.

### Fixed — Undefined name in chat_handler (1.3)

- Renamed undefined `user_msg` to `message` in `server/handlers/chat_handler.py` so AI token metrics are correctly recorded into `ai_usage`. Replaced empty `except: pass` with `log_line` error reporting.

### Fixed — Undefined name in data_store (1.2)

- Added missing `import os` in `server/services/data_store.py` and wrapped `delete_record_attachment` file removal with `safe_join` to prevent path traversal, with proper `log_line` error logging instead of empty pass.

### Fixed — Undefined name in router (1.1)

- Added missing `import time` in `server/router.py` to fix `NameError` on `/api/vectors/sync` (`handle_post_vector_sync`) rate limit check.

### Added — CI linting gate (Phase 0)

- Integrated `ruff` (F821, F811) into CI and `requirements-dev.txt` with configuration in `ruff.toml` to prevent undefined variables and duplicate imports. Cleaned trivial redundant re-imports across `handler.py`, `auth_handlers.py`, and `router.py`.

### Fixed — Password change (self-service & admin reset)

- **`/api/account/update-profile` now verifies the current password** before storing a
  new one (`verify_password` with the stored salt/iterations, so legacy PBKDF2 hashes
  are still auto-upgraded). A wrong password answers
  `400 현재 비밀번호가 일치하지 않습니다.` and is counted by the login lockout
  (`login_attempts`), so the form cannot be used to brute-force the account from a
  stolen session.
- **Changing the password invalidates every other device.** The other rows in
  `sessions` are deleted inside the same transaction (the current token is kept so the
  user is not thrown out of the tab they are using); the response returns
  `passwordChanged` + `sessionsRevoked` and the success message mentions the count.
  Previously a hijacked session survived the password change.
- **The confirmation field is mandatory on the API**, not only in the browser form
  (`confirm_password` for self-service, `new_password_confirm` for admin reset);
  missing confirmation answers `400 … 확인을 입력해주세요.` instead of silently
  accepting a single, unchecked password.
- **The profile update resolves the user by session id first** and only falls back to
  name/email. After an admin renamed a user, the old lookup returned 404 and the user
  could not change their own password until they logged in again.
- `hash_algo` is refreshed to `pbkdf2_sha256` when a password is written (both flows).
- UI: `현재 비밀번호` / `새 비밀번호` / `새 비밀번호 확인` in the profile modal and
  `새 비밀번호` / `새 비밀번호 확인` in the admin user modal; browser-side checks
  (required, ≥ 8, both entries equal, focus on the offending field); all labels,
  placeholders and the `(변경 시에만 입력)` hint are translated (KO/EN); the admin modal
  shows validation/API errors inline instead of blocking `alert()` dialogs.
- Tests: `tests/test_password_change_workflows.py` (11 cases) covers both flows,
  including "other sessions revoked, current session kept" and "confirmation is
  required"; the suite is green on SQLite and PostgreSQL.

### Fixed — Security / Path traversal (audit round 5)

- **PIM attachment routes could escape their folder.** `handle_get_products_attachment`
  built the path with `os.path.join(PRODUCT_ATTACH_DIR, pid, name)` and only the
  record-attachment route had a containment check. Every attachment path now goes
  through the new `utils.file_ops.safe_join()` (realpath + `commonpath`), applied as
  **two steps** — the product folder must stay inside the products root *and* the
  attachment inside that product folder — so `…/P-1/../P-2/secret` is rejected.
  Applied to: product download, product upload folder, product delete, record
  download, record attachment upload, submit upload, avatar serving.
  `safe_join()` returns `None` on traversal and the handler answers 404 instead of
  touching the disk (`commonpath`, not `startswith`, so `…/attach_evil` cannot pass
  as `…/attach`).
- **`DANGEROUS_EXTENSIONS` missed script / Java / .NET payloads.** Uploads named
  `.py`, `.pyw`, `.pyc`, `.jar`, `.class`, `.jsp`, `.jspx`, `.war`, `.asp`, `.aspx`,
  `.ascx`, `.ashx`, `.asmx`, `.shtml`, `.htaccess`, `.msi`, `.lnk`, `.reg`, `.wasm`
  are now stored as `.bin` like `.html`/`.js`/`.exe` (they were already downloaded
  with `Content-Disposition: attachment` + `CSP: sandbox`, so this closes the
  "internal tooling could import the stored file" gap).
- **Outgoing webhooks had no dispatch-time SSRF gate.** `_send_http_post()` validated
  nothing, so a webhook URL injected through `.env` / the process environment could
  be `file://` (urllib reads local files), `ftp://`, or an internal address, and
  `urlopen()` silently followed redirects. Now every dispatch and **every redirect
  target** is validated with `services.webhook_dispatcher.validate_webhook_target()`
  → `utils.ssrf.validate_external_url()`: HTTP(S) only, loopback / private /
  link-local (`169.254.169.254`) / multicast blocked, cross-host redirects
  re-validated. `/api/settings` already validated webhook URLs at save time; this
  adds the defense-in-depth layer for values that bypass the UI.

### Fixed — Security / RBAC

- **Private cards could be read through the card-code lookup path.**
  `data_store.find_record_by_key_or_code()` returned a record dict without
  `is_private`, so `can_view_record()` treated private cards as public whenever a
  record was resolved by card code / Jira key (AI chat `get_issue_details`,
  `/api/records/hierarchy`, attachment download, subtask creation).
  The field is now always included.
- **`/api/schedule` leaked private cards of the same department** to members who
  were not the assignee (calendar events + "unassigned tasks" panel). Private
  records are now additionally filtered with `can_view_record()`.
- **Notification SSE stream broadcast every notification to every client.**
  `/api/notifications/stream` now keeps a per-subscriber identity and only
  delivers notifications addressed to that user (or system broadcasts).
- **Notification/chat identity matching hardened for duplicate display names.**
  Name-only matching is disabled when the same display name exists in several
  departments (notifications), and chat session ownership now requires the
  (name, department) pair. Prevents two employees with the same name from
  reading/marking each other's data.
- **Login no longer invents a department.** Accounts without `dept_id` used to be
  silently placed in `dev`, granting that department's records; the stored
  (empty) department is now used and non-active account statuses are rejected at
  login.
- **Self-service department change now requires admin approval.** The profile
  update endpoint keeps the current department and creates a
  "부서 변경 승인 요청" notification for admins (previously the caller could move
  themselves into another department and inherit its records/prices).
- **Report download is restricted to Manager/Admin**, matching report generation
  (generated workbooks contain company-wide data).
- Avatar uploads are validated as real raster images, the file extension is
  derived from the actual format, and `avatar_url` only accepts app-relative or
  HTTPS values.
- Admin self-protection (`cannot disable/demote yourself`, `last admin` guard) now
  also works when the JSON body sends the user id as a string.

### Fixed — PostgreSQL parity (docker-compose / enterprise default)

PostgreSQL is the default engine for the shipped `docker-compose.yml`, but the
suite only ever exercised SQLite, so several defects could only appear at a
customer. They are now fixed **and** covered by tests that run on both engines.

- **`login_attempts` table was missing from `schema.postgres.sql`.** The
  persistent brute-force lockout silently degraded to an in-memory fallback on
  PostgreSQL (failures were never stored, so a restart cleared every lockout).
  Added to the baseline schema and to a migration (`v2.4`).
- **`users.hash_algo` / `users.iterations` were missing from the PostgreSQL
  schema.** `create_user()` inserts both columns, so user creation (setup wizard,
  admin create, registration) failed on PostgreSQL, and legacy PBKDF2 hashes could
  never be auto-upgraded. Added to the baseline schema + migration (`v2.5`).
- **Free-text columns were `VARCHAR(n)` on PostgreSQL while SQLite stores TEXT.**
  A 5000-character task title (valid on SQLite) raised
  `value too long for type character varying(512)`. Titles, comments, filenames,
  notification text, names and audit fields are now `TEXT` + migration (`v2.6`).
- **`ORDER BY rowid`** (SQLite-only) is translated to `ORDER BY id`; it made
  `read_departments()` / `read_product_categories()` fail on PostgreSQL.
- **`close_connection()` no longer tears down the whole PostgreSQL pool after
  every request.** It is a no-op per request and only closes the pool with
  `close_connection(force=True)` (backup restore / shutdown).
- **Connections are returned to the pool without an open transaction.** A SELECT
  used to leave the connection "idle in transaction", holding ACCESS SHARE locks
  (DDL such as CREATE/DROP SCHEMA and autovacuum blocked — the PostgreSQL test
  suite hung on schema teardown).
- **`INSERT OR REPLACE` rewriting now appends `ON CONFLICT` at the end of the
  statement.** The old rewrite only handled a single `VALUES (...)` row; a
  multi-row insert produced `ON CONFLICT ... , (...)` → syntax error.
- **Literal `%` in SQL is escaped for psycopg2.** `... LIKE 'test_%'` raised
  `IndexError: tuple index out of range` because psycopg2 applies %-formatting
  whenever parameters are supplied.
- **`INSERT ... RETURNING id` is only used for tables that actually have an `id`
  column** (record_jira / card_sequences used to fail once, roll back and retry).
- **`/api/admin/ai-usage`** grouped by `user_name` while selecting `dept_id`
  (PostgreSQL error 42803 → HTTP 500). Now grouped by `(user_name, dept_id)`.
- **`write_schedule()` lost `schedule_events.owner_id` on PostgreSQL** (`row[0]`
  on a dict row raised `KeyError`, swallowed by `except`).
- **Audit-log user search** uses `LOWER(username) LIKE LOWER(?)` so behaviour no
  longer differs between SQLite (case-insensitive LIKE) and PostgreSQL.

### Added — cross-engine test infrastructure

- `tests/test_engine_contract.py`: schema parity (same tables **and** columns in
  `schema.sql` / `schema.postgres.sql`), engine selection guard, and identical
  DB-facade behaviour on both engines (execute/transaction/owner-link/lockout).
- `conftest.tmp_db` is engine-aware: SQLite gets a temp file, PostgreSQL gets a
  **temporary schema** (search_path) that is dropped afterwards. The whole
  PostgreSQL session also runs in its own throw-away schema, so repeated runs are
  reproducible instead of accumulating rows.
- `db` exposes `list_tables()`, `list_indexes()`, `table_columns()` and
  `set_search_path()` so tests no longer query `sqlite_master`/`PRAGMA` directly.
- CI now runs **two real jobs** (`sqlite-tests`, `postgres-tests` — same suite on a
  live PostgreSQL 16 service, with an engine assertion) plus a
  `container-smoke` job that boots the shipped `docker-compose.yml`
  (app + PostgreSQL + Caddy) and checks `/api/health`, `/api/version`,
  `/api/setup/status` and the 401 on unauthenticated `/api/records`.

### Fixed — Data & robustness

- `/api/account/update-profile` no longer wipes the email when the field is absent,
  and the current session row is updated using the hashed token (it previously
  never matched the SHA-256 `sessions.token` value).
- Expired-session cleanup honours the sliding TTL (`last_active_at`) instead of
  `created_at`, so active users are not logged out after 24h.
- `/api/attachments/avatars/<file>` now serves profile images (previously 404);
  record attachments are resolved from the record's real id even when the URL uses
  a card code.
- `/api/chat/history`: non-numeric `limit` no longer raises 500, negative limits
  are clamped, and unknown sessions return 404.
- AI chat schedule writes (create/schedule_issue) now use the global schedule lock
  (`data_store.mutate_schedule`) so concurrent saves cannot drop events.
- Setup wizard rejects a department list without ids instead of raising
  `IndexError`; `/api/schedule/assign-task` accepts non-string dates without 500.
- `product_categories` DDL runs once per database instead of on every read.
- Login responses include the stored avatar, and PBKDF2 iterations are read from
  the user row in the same query.

## [1.0.0] — 2026-10-23

First commercially sellable on-premise release (B2B, one instance per customer).

### Security (BREAKING)

- **License signing key is now vendor-only.** The Ed25519 private key that was
  previously embedded in `server/services/license_manager.py` has been removed
  and **rotated**. Any license signed with the old key is no longer accepted;
  re-issue customer licenses with `tools/vendor/license_tool.py`.
- Customer instances ship **only** the public key. `generate_signed_license_key()`
  now raises `LicenseSigningKeyMissing` when no key is supplied.
- **Stored license rows are verified, not trusted.** `get_license_status()` now
  validates the Ed25519 signature of the key stored in `license_info`. Editing
  the row (seats, expiry, modules) no longer grants a bigger contract, and an
  unsigned/forged key is reported as *unlicensed* (read-only).
- **Module entitlements are enforced server-side.** New `server/module_gate.py`
  blocks API groups (`pim`, `jira`, `rag`, `schedule`, `audit`) with HTTP 403
  when the active license does not include them. Previously `modules` was
  display-only, so a PIM-only customer also got Jira/RAG/Audit.
- License status is cached for 30s and invalidated on activation to avoid two
  extra queries per write request.
- Browser clients now surface network failures instead of silently failing.

### Added

- `tools/vendor/license_tool.py` — vendor CLI: `keygen`, `issue`, `inspect`,
  plus an issuance log (`issued_licenses.csv`) for commercial tracking.
- `licenses/trial-50.lic` — signed 50-seat evaluation license (expires 2027-12-31).
- `scripts/apply_license.py` — offline activation against an existing SQLite DB.
- `scripts/build_release.py` — produces a clean customer bundle and **refuses to
  build** if a signing key, database or `.hex` file would be included.
- `GET /api/admin/audit-logs/export?format=csv|json` — audit export for ISO /
  internal audit, with UTF-8 BOM and CSV formula-injection protection. Export
  actions are themselves audited (`AUDIT_EXPORT`).
- Audit tab: CSV / JSON download buttons wired to the current filters.
- Settings → **License** tab (admin only): customer, seats used/total with
  progress bar, expiry + 30-day warning, licensed modules, activation form.
- `GET /api/version` and `VERSION` file (`1.0.0`); the settings footer shows the
  running release.
- **Bidirectional Jira user aliases.** One `jira.user_aliases` map (local name → Jira
  name/username/email) now works in both directions: it resolves the Jira `accountId`
  when creating/pushing cards, and it maps the Jira `assignee` back to the local user
  name when syncing, so “my tasks”, the personal calendar and department permissions
  work even when the two systems spell a name differently. Matching is
  case-insensitive, ignores job-title suffixes, prefers the Jira email when visible,
  and tolerates issues from unmapped projects. Configurable in
  **Settings → Jira → 사용자 별칭** (JSON) with validation.
- `deploy/argos-works.service` (systemd, hardened) and
  `deploy/install_windows_service.ps1` (NSSM or boot-time scheduled task).
- `ARGOS_FRESH_INSTALL=1` removes vendor demo departments on a clean install so
  customers never see the vendor's org chart.
- Documentation: `docs/ADMIN_GUIDE.md`, `docs/USER_GUIDE.md`,
  `docs/SECURITY_WHITEPAPER.md`, `docs/SLA.md`.

### Fixed

- **Jira client swallowed network errors.** `services/jira_client._urlopen()` caught
  `urllib.error.URLError` and (outside the explicit insecure-SSL opt-in) fell through
  returning `None`. Every caller uses `with _urlopen(...) as resp:`, so a transient
  network/TLS failure surfaced as the meaningless
  `'NoneType' object does not support the context manager protocol` — masking the real
  cause on issue creation, comments, transitions, attachments and sync.
  `_urlopen()` now re-raises after logging; callers report the actual error.
  Verified against a live Jira Cloud site (project SCRUM): connection test, issue search
  (14 issues / 57 activities cached), status scan, create → comment → transition →
  date update → delete all succeeded.
- Setup wizard, admin user creation and password change stored a hardcoded
  `iterations = 600000` while hashing with the effective work factor, which made
  the first login fail. Password iteration counts are now always persisted.
- `POST /api/admin/license/activate` unpacked three values from a two-value
  function and therefore returned HTTP 500 on every activation attempt.
- `get_license_status()` no longer reports an active license when the signed
  payload has expired, even if the row says `is_active = 1`.
- Tests no longer mutate `data/argos.db` (license row, users) — setup/license
  suites are isolated and restore state.

### Changed

- `PBKDF2_ROUNDS` remains 600,000 in production; the new `ARGOS_PBKDF2_ROUNDS`
  environment variable (minimum 1,000) exists so the test suite runs in ~1s
  instead of ~30s. Never set it in production.
- Test suite: `pytest` is now a first-class gate (`requirements-dev.txt`), CI runs
  both `unittest` (legacy suites) and `pytest` with coverage, and `run_tests.bat`
  / `run_tests.sh` were rewritten (no interactive `pause` in CI).

## [0.9.0] — 2026-10-19

Internal MVP baseline: Jira sync, artifact canvas, PIM, calendar, AI ReAct agent
with RAG, RBAC (admin/manager/member/viewer), audit trail, backups,
PostgreSQL support and Docker/Caddy deployment.
