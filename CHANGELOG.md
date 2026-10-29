# Changelog

All notable changes to ARGOS WORKS are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security & Frontend Hardening — Admin Users Error HTML Escaping (9.3)

- Enforced `escapeHtml()` on asynchronous communication error messages when rendering the admin user management table in `web/js/settings.js`, preventing DOM-based XSS injection via malformed network error payloads.

### Security & Observability — Jira Insecure SSL Verification Startup Warning (7.7)

- Added `check_jira_ssl_warning()` in `server/services/jira_client.py` and connected to application initialization in `server/wsgi.py` and `server/main.py` to emit an explicit security warning whenever `insecure_skip_verify` or `JIRA_INSECURE_SKIP_VERIFY` is active.

### Reliability & Session Security — Per-Request Session Cache Invalidation (7.6)

- Explicitly cleared `self._current_session = None` at the entry of each HTTP dispatch verb (`do_GET`, `do_POST`, `do_OPTIONS`) in `server/handler.py`, preventing cross-request session leakage across keep-alive connections.

### Security & Denial of Service Defense — Public Body Size Limits (7.5)

- Enforced early `Content-Length` validation in `server/handler.py` rejecting payloads exceeding `PUBLIC_BODY_LIMIT` (16 KB) on unauthenticated public endpoints and 1 MB on `/api/setup/*` wizard endpoints with HTTP 413 before reading the input stream, eliminating unauthenticated heap exhaustion and DoS attack vectors.

### Security & Hardening — Fail-Closed Dynamic CSRF Secret Resolution (7.4)

- Removed the static hardcoded CSRF fallback key (`b"argos_works_enterprise_csrf_fallback_key_2026"`), eliminating static secret vulnerabilities.
- Implemented robust, prioritized CSRF secret resolution: atomic file creation (`0o600` via `O_CREAT | O_EXCL`) -> HMAC-SHA256 master key derivation for read-only containers -> fail-closed `RuntimeError`.
- Added eager initialization of CSRF secret at startup in `server/wsgi.py` and `server/main.py`.

### Security & Deployment — Narrow Default Trusted Proxies & Compose Network Isolation (7.3)

- **BREAKING**: Narrowed `DEFAULT_TRUSTED_PROXIES` in `server/handler.py` from `127.0.0.1,::1,172.16.0.0/12` to loopback only (`127.0.0.1,::1`). Upgrading deployments running behind an external reverse proxy on a non-loopback IP must explicitly set `TRUSTED_PROXIES` in `.env` to their reverse proxy's IP.
- Isolated all Docker Compose services (`argos-works`, `caddy`, `postgres`) into a dedicated `argos_net` network with subnet `${ARGOS_NET_SUBNET:-172.28.0.0/24}`, preventing IP spoofing from adjacent Docker containers or enterprise LAN hosts.
- Added startup validation warning if `TRUSTED_PROXIES` contains `0.0.0.0` or an overly broad CIDR range (prefix length <= 12).

### Maintenance & Dual-Engine Reliability — Clean Dead Regex and Enforce Replace PK Mapping Contract (7.2)

- Removed dead unused _RE_INSERT_OR_REPLACE regex in server/db.py, standardizing SQL translation around _RE_INSERT_OR_REPLACE_HEAD.
- Added automated regression tests verifying that every database table utilizing INSERT OR REPLACE across the backend is tracked in _REPLACE_PK_MAP, and confirmed that multi-row batch inserts correctly translate to PostgreSQL with terminal ON CONFLICT (...) DO UPDATE clauses.

### Reliability & Security — Database Engine Detection and Fail-Closed Scheme Validation (7.1)

- Added _detect_engine() in server/db.py to parse DATABASE_URL via URL scheme, correctly recognizing postgres://, postgresql://, and postgresql+psycopg2:// as PostgreSQL, and normalising legacy postgres:// URLs for database drivers.
- Enforced fail-closed behavior on unsupported database schemes (e.g. mysql://) by raising RuntimeError while strictly preventing connection strings, hosts, and database passwords from leaking into exception messages or logs.

### Security & Privacy — Failed Login Identifier Sanitization (6.3)

- Implemented utils.text.login_label() to pseudonymize unknown login identifiers using keyed HMAC-SHA256 (non:<8 hex>/len=<len>) across ccess_log and udit_logs. This guarantees that if a user accidentally types or pastes their password into the username field, the plaintext password is never recorded in logs, audit tables, or SIEM systems.
- Added strict length validation for login requests (username <= 254 chars, password <= 1024 chars), returning HTTP 400 for malformed or abusive payloads.
- Maintained rate limiting and account lockout capabilities using the keyed pseudonym identifier for non-existent accounts.

### Observability & Compliance — Audit Log Failure Metric and Safe Logging (6.2)

- Replaced silent \except Exception: pass\ in \server/router.py::_audit()\ and \server/services/audit_logger.py::log_audit()\ with thread-safe failure counting (\get_audit_failure_count()\) and sanitized \log_line\ error output (\[Audit] write failed: action=... target=... err=...\).
- Preserved zero-downtime reliability (primary requests continue without throwing 500s when audit writes fail) while guaranteeing monitoring systems detect audit storage exhaustion and zero secret/password leakage occurs.

### Security & Observability — SQL Parameter Sanitization in Logs (6.1)

- Replaced raw SQL parameter interpolation across SQLite and PostgreSQL error logging with sanitized \<N params>\ summary placeholders via \_safe_params()\, completely preventing sensitive data (passwords, salts, password hashes, session tokens) from leaking into server logs or customer SIEMs upon query failures.
- Sanitized database error messages with \_format_db_error()\ to strip PostgreSQL \DETAIL: Key ...\ clauses that expose column values on constraint violations.
- Added debug-only \ARGOS_LOG_SQL_PARAMS=1\ environment variable with mandatory startup warning for authorized technical support troubleshooting.

### Logging & Observability — Unhandled Exception Logging (5.2)

- Replaced silent `except Exception: pass` blocks across `server/services/auth.py`, `server/services/data_store.py`, `server/services/jira_client.py`, `server/handlers/auth_handlers.py`, and `server/handlers/chat_handler.py` with structured `log_line` error messages, eliminating silent failure swallowing while keeping normal control flow intact.

### Concurrency — Multi-Worker Unique Record ID Allocator (5.1)

- Added `id_allocator` table and migration v7 across SQLite and PostgreSQL schemas to ensure globally unique, monotonic 64-bit integer record IDs in multi-worker production deployments (e.g. Gunicorn / Uvicorn).
- Implemented atomic transaction allocation using `GREATEST` on PostgreSQL and `BEGIN IMMEDIATE` on SQLite, completely preventing primary key collision errors between concurrent workers.

### Security — SSRF DNS Rebinding & CGNAT Protection (Phase 4)

- Added `resolve_and_validate` and `safe_urlopen` in `server/utils/ssrf.py` to eliminate Time-of-Check to Time-of-Use (TOCTOU) DNS rebinding attacks. Outgoing requests connect directly to pre-validated IP addresses while preserving original hostname SNI and strict TLS certificate verification.
- Intercepted all HTTP redirects via custom `_SafeRedirectHandler` ensuring redirect locations undergo recursive SSRF validation before follow-through.
- Upgraded IP validation logic to use `not ip.is_global`, effectively closing gaps for Carrier-Grade NAT (CGNAT `100.64.0.0/10`) and special routing ranges.
- Applied `safe_urlopen` across user/admin-controlled URL handlers in `server/services/webhook_dispatcher.py` and `server/handlers/settings_handler.py`.

### Tests — Offline SSRF Validator Mocking (3.6)

- Mocked `socket.getaddrinfo` in `tests/test_unit_utils.py::TestSSRFValidator::test_valid_https_url` to allow the test suite to execute reliably in offline and air-gapped environments without external DNS dependencies.

### Security — Static Path Traversal Prevention via safe_join (3.5)

- Replaced `os.path.normpath` and `startswith(WEB_DIR)` static file routing check in `server/router.py` with `utils.file_ops.safe_join(WEB_DIR, clean)`, preventing sibling folder traversal attacks (e.g. `web_private`).

### Reliability — Atomic Transaction in append_record (3.4)

- Wrapped record creation, attachments insertion, and Jira linkage in `server/services/data_store.py::append_record` inside a single atomic database transaction. Any failure during attachment or Jira insertion guarantees a complete rollback without leaving orphaned partial records.

### Security — Explicit Department Validation on Registration (3.3)

- Rejected registration requests with invalid or missing department IDs with HTTP 400 (`유효하지 않은 부서입니다.`), eliminating dangerous implicit fallbacks to default or demo departments.
- Returned HTTP 400 with Korean error message when the system has no registered departments.

### Security — Case-Insensitive Unique User Identities & Username Validation (3.2)

- Added case-insensitive unique indexes on `LOWER(username)` and `LOWER(email)` for users table in SQLite and PostgreSQL schemas and migration v6.
- Added migration pre-check preventing startup crashes if duplicate case-insensitive usernames exist, logging warnings and providing `scripts/check_duplicate_identities.py` for administrator audit.
- Added strict username format validation (`^[A-Za-z0-9_.-]{3,30}$`, disallowing `@`) across registration, admin creation, and setup wizard.
- Ensured all single-row user queries specify deterministic `ORDER BY id ASC`.

### Security — Hardened Login Rate Limiting & Timing Attack Defense (3.1)

- Added dummy PBKDF2 hash computation on non-existent usernames to equalize response time, defending against user enumeration timing attacks.
- Enforced 3-tier login rate limiting with canonicalized identifier keys (`(ip, user)` = 5/15m, `user` across IPs = 20/15m, `ip` across users = 30/15m).
- Recorded login failures immediately prior to password verification to eliminate concurrency race conditions, returning standard HTTP 429 with `Retry-After` header.

### Security — Remove session token from JS client storage (2.5)

- Removed token storage in `localStorage` and `sessionStorage` in frontend JS (`web/js/auth.js`, `api.js`, `calendar.js`, `notifications.js`, `settings.js`), adhering to strict HttpOnly cookie security.
- Stopped returning raw `token` in login JSON response by default (opt-in via `ARGOS_LOGIN_RETURN_TOKEN=1` for testing/CLI).
- Ensured `argos_csrf` cookie receives `; Secure` flag when accessed over HTTPS.

### Security — Identifier-Based RBAC Tightening (2.4)

- Removed dangerous username matching against assignee display name (`u_username == rec_assignee`) in `can_view_record` and `can_modify_record`. Access is strictly bound to immutable user IDs, emails, or same-department name matching.
- Added migration/maintenance script `scripts/backfill_assignee_ids.py` to safely backfill missing `assignee_id`s in `records`.

### Security — Department-Isolated Assignee Resolution (2.3)

- Fixed cross-department assignee leakage in `server/services/data_store.py::append_record`. If an assignee does not match within the target department, global fallback requires an unambiguous single candidate (`LIMIT 2`). If multiple users share the same name across other departments, `assignee_id` is left `NULL` to prevent unauthorized cross-department access to private records.

### Security — Absolute Session Lifetime (2.2)

- Enforced absolute session expiration via `SESSION_MAX_AGE_HOURS` (default 168h / 7 days). Sessions that exceed the maximum age from `created_at` are automatically terminated even if continuously active, preventing permanent hijacking of stolen session tokens.

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
