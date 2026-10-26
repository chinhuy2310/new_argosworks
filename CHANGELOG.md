# Changelog

All notable changes to ARGOS WORKS are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
