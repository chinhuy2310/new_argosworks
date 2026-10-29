# ARGOS WORKS — Deployment Runbook (self-hosted)

This is the operational path that the `deploy.bat` / `deploy.sh` scripts actually
execute. Everything below was verified against the repository's own scripts.

## 1. Prerequisites

| Requirement | Notes |
| --- | --- |
| Docker Engine 24+ with Compose v2 | `docker compose version` must succeed |
| Python 3.9+ (optional) | Only used by the local bootstrap script; PowerShell/openssl fallbacks exist |
| 4 GB RAM / 2 vCPU | Minimum for the app + Caddy; PostgreSQL needs ~512 MB more |

## 2. First start

**Windows**

```bat
deploy.bat
```

**Linux / macOS**

```bash
chmod +x deploy.sh
./deploy.sh
```

Both scripts call `scripts/init_deploy.py` (or `scripts/init_deploy.ps1` when
Python is absent) before `docker compose up`. The bootstrap is idempotent and
performs three steps:

1. **`.env`** — created from `.env.example` with freshly generated
   `ARGOS_MASTER_KEY` (32 random bytes, hex) and `POSTGRES_PASSWORD`.
   Any template placeholder is replaced.
2. **`server/config.json`** — created as a *file* from `server/config.example.json`.
   This matters: `docker-compose.yml` bind-mounts that single file, and if it is
   missing Docker creates a **directory** instead, after which the application can
   no longer persist settings.
3. **`data/`, `data/backups/`, `data/attachments/`, `data/templates/`, `logs/`**.

You can also run the bootstrap on its own:

```bash
python scripts/init_deploy.py          # prepare/repair a checkout
python scripts/init_deploy.py --check  # verify only, exit 1 when something is missing
```

## 3. Secrets

`ARGOS_MASTER_KEY` encrypts secrets stored at rest (integration credentials,
SMTP passwords, etc.). `POSTGRES_PASSWORD` is consumed by both the database
container and `DATABASE_URL`.

The bootstrap **never rotates an existing secret implicitly**, because:

* a new `ARGOS_MASTER_KEY` makes every value encrypted with the old key
  unreadable — it looks exactly like data loss;
* a new `POSTGRES_PASSWORD` must also be applied inside PostgreSQL
  (`ALTER USER argos_admin WITH PASSWORD '...'`), otherwise the app stops
  connecting.

Deliberate rotation:

```bash
python scripts/init_deploy.py --rotate   # regenerates all three secrets
# PowerShell fallback:
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\init_deploy.ps1 -Rotate
```

A backup copy of the previous `.env` is written next to it
(`.env.bak-YYYYMMDDHHMMSS`). Keep `.env` out of version control — it holds the
master key.

## 4. Post-start checks

```bash
docker compose ps          # argos-works, argos-proxy, argos-postgres must be Up
docker compose exec argos-works curl -fsS http://localhost:8080/api/health
curl -k https://localhost/api/health        # through Caddy
```

Only Caddy publishes reachable host ports (80/443); PostgreSQL is bound to
`127.0.0.1:5432` and the app container is only reachable on the internal network
as `argos-works:8080`. That is why `docker-compose.yml` isolates services in an `argos_net` network
(`172.28.0.0/24`) and sets `TRUSTED_PROXIES` to this dedicated subnet — the app only honours
`X-Forwarded-For` from the proxy, preventing IP spoofing from other containers or host networks.

Then open `https://localhost` (`https://<DOMAIN>` when `DOMAIN` is set). A fresh
instance redirects to `/setup`, which needs:

* a **license key** (an `AGY-...` token signed with the vendor's **Ed25519**
  private key; the customer instance only holds the public key), and
* if `ARGOS_BOOTSTRAP_TOKEN` is set in `.env`, the same value must be supplied to
  `/api/setup/complete`. Set it before the first start on any host reachable from
  an untrusted network, otherwise the first visitor can become the admin.

## 5. Upgrades

```bash
git pull
python scripts/init_deploy.py     # repairs .env / config.json if a file is missing
docker compose up -d --build
```

`.env` and `data/` are preserved; existing secrets are left untouched. The
application applies schema migrations on start (`schema_migrations` table).

## 6. Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| `docker compose` aborts with `bắt buộc đặt ARGOS_MASTER_KEY` | `.env` is missing or the key is empty — run `python scripts/init_deploy.py` |
| `server/config.json is a directory` | A previous start ran without the file. `rmdir server/config.json`, then re-run the bootstrap |
| Login succeeds but settings do not persist | `server/config.json` is not writable by the container user (check the bind mount) |
| Every client appears as `172.x.x.x` in the audit log | The proxy is outside `TRUSTED_PROXIES`; extend that value with the proxy's IP/CIDR |
| `password authentication failed for user "argos_admin"` | `POSTGRES_PASSWORD` was changed after the volume was initialised, or `DATABASE_URL` no longer matches it |

## 7. Backups

`BACKUP_DIR` (default `./data/backups`) receives database dumps; PostgreSQL uses
`pg_dump` through `services/backup_manager.py`. Point it at a mounted volume or
NAS path and copy the directory off-box — a backup that only exists on the same
disk is not a backup.

---

## 8. Running as a service (no Docker / survives reboot)

Docker Compose already restarts containers (`restart: unless-stopped`). For bare
metal installs:

**Linux (systemd)**

```bash
sudo useradd --system --home /opt/argos-works --shell /usr/sbin/nologin argos
sudo mkdir -p /opt/argos-works && sudo chown -R argos:argos /opt/argos-works
# copy the release bundle into /opt/argos-works, create .env and the venv
sudo cp deploy/argos-works.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now argos-works
journalctl -u argos-works -f
```

**Windows**

```powershell
powershell -ExecutionPolicy Bypass -File deploy\install_windows_service.ps1 `
    -Mode task -InstallDir C:\ArgosWorks -Port 8080
```

`-Mode nssm` gives a real Windows service if NSSM is installed; the default
`task` mode registers a boot-time scheduled task with restart-on-failure.

---

## 9. Build a customer release bundle

Never ship the repository as-is (it contains the vendor signing key, demo seed
data and internal docs). Build a clean bundle:

```bash
python scripts/build_release.py --include-docs
# -> dist/argos-works-1.0.0.zip
```

The script aborts if a signing key, database file or `.hex` file would be
included, and writes `RELEASE_MANIFEST.txt` listing what was excluded.

Fresh customer installs should set `ARGOS_FRESH_INSTALL=1` so the vendor demo
departments are removed before the setup wizard runs.

---

## 10. License operations (vendor side)

```bash
# one-time: create the vendor key pair (private key stays offline)
python tools/vendor/license_tool.py keygen

# issue / renew a customer license
python tools/vendor/license_tool.py issue \
    --customer "ACME Manufacturing" --seats 40 --expiry 2027-12-31 \
    --modules canvas,pim,jira,rag,schedule,audit \
    --out licenses/ACME-2027.lic

# verify before sending
python tools/vendor/license_tool.py inspect licenses/ACME-2027.lic
```

Issuance is appended to `tools/vendor/issued_licenses.csv` (never committed).
On the customer side the license is activated either through
**Settings -> License** or offline with:

```bash
python scripts/apply_license.py /path/to/ACME-2027.lic --db data/argos.db
```

If the private key ever leaks: run `keygen` again, replace
`EMBEDDED_LICENSE_PUBLIC_KEY_HEX` in `server/services/license_manager.py`,
rebuild, and re-issue every customer license (old keys stop verifying).

