#!/usr/bin/env python3
"""
ARGOS WORKS - first-run deployment bootstrap.

Idempotent. Safe to run on every deploy/upgrade.

  1. Creates .env from .env.example (or fills gaps in an existing .env) with
     freshly generated secrets: ARGOS_MASTER_KEY, POSTGRES_PASSWORD.
     Placeholder values shipped in the template are detected and replaced,
     never trusted.
  2. Makes sure server/config.json exists as a *file* (Docker bind-mounts it;
     when the file is missing Docker creates a directory instead, the app then
     silently falls back to defaults and can no longer persist settings).
  3. Creates the persistent data directories.

Usage:
    python scripts/init_deploy.py            # prepare a local checkout
    python scripts/init_deploy.py --check    # verify only, change nothing
"""
import argparse
import json
import os
import re
import secrets
import shutil
import string
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(ROOT, ".env")
ENV_EXAMPLE = os.path.join(ROOT, ".env.example")
CONFIG_PATH = os.path.join(ROOT, "server", "config.json")
CONFIG_EXAMPLE = os.path.join(ROOT, "server", "config.example.json")
DATA_DIRS = ["data", "data/backups", "data/attachments", "data/templates", "logs"]
DEFAULT_TRUSTED_PROXIES = "127.0.0.1,::1,172.16.0.0/12"

# Values copied verbatim from .env.example that must never reach production.
PLACEHOLDER_VALUES = {
    "YOUR_STRONG_PASSWORD_HERE",
    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
}

MIN_SECRET_LEN = 32


def _log(msg):
    print(f"[init] {msg}")


def _fail(msg):
    print(f"[init][ERROR] {msg}", file=sys.stderr)
    return False


def strong_password(length=32):
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def parse_env_text(text):
    """KEY=VALUE pairs from an env file body (comments and order ignored)."""
    values = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values[key.strip()] = value.strip()
    return values


def set_env_value(text, key, value):
    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
    if pattern.search(text):
        return pattern.sub(f"{key}={value}", text, count=1)
    if text and not text.endswith("\n"):
        text += "\n"
    return text + f"{key}={value}\n"


def _is_weak(value, minimum=MIN_SECRET_LEN):
    return (not value) or (value in PLACEHOLDER_VALUES) or (len(value) < minimum)


def prepare_env(check_only=False, rotate=False):
    """Ensure .env exists with usable secrets. Returns True on success.

    Secrets are only regenerated when .env is newly created or when --rotate is
    given: rotating ARGOS_MASTER_KEY invalidates every credential already
    encrypted with the old key, and rotating POSTGRES_PASSWORD requires a
    matching ALTER USER in PostgreSQL. Silently rotating them on an upgrade
    would look like data loss to the customer.
    """
    created = False
    if not os.path.exists(ENV_PATH):
        if not os.path.exists(ENV_EXAMPLE):
            return _fail(".env is missing and .env.example could not be found.")
        if check_only:
            return _fail(".env is missing (run without --check to create it).")
        shutil.copyfile(ENV_EXAMPLE, ENV_PATH)
        created = True
        _log(".env created from .env.example")

    with open(ENV_PATH, "r", encoding="utf-8") as handle:
        text = handle.read()
    original = text
    values = parse_env_text(text)

    secret_keys = ("ARGOS_MASTER_KEY", "POSTGRES_PASSWORD")
    generators = {
        "ARGOS_MASTER_KEY": lambda: secrets.token_hex(32),
        "POSTGRES_PASSWORD": lambda: strong_password(),
    }
    missing = [key for key in secret_keys if not values.get(key)]
    weak = [key for key in secret_keys if values.get(key) and _is_weak(values[key])]
    placeholders = [key for key in secret_keys if values.get(key) in PLACEHOLDER_VALUES]
    rotate_targets = list(dict.fromkeys(missing + placeholders + (weak if (created or rotate) else [])))

    if check_only and rotate_targets:
        return _fail(
            "secrets need to be generated for: " + ", ".join(rotate_targets)
        )

    changes = []
    for key in rotate_targets:
        text = set_env_value(text, key, generators[key]())
        changes.append(key)

    stale = [key for key in weak if key not in rotate_targets]
    if stale:
        _log(
            "WARNING: template/weak secret(s) in .env: " + ", ".join(stale) + ". "
            "Run 'python scripts/init_deploy.py --rotate' to generate strong values "
            "(rotating ARGOS_MASTER_KEY invalidates secrets already encrypted with the "
            "old key; rotating POSTGRES_PASSWORD requires ALTER USER in PostgreSQL)."
        )
        if check_only:
            return _fail("weak secrets found: " + ", ".join(stale))


    # Rebuild DATABASE_URL whenever it is absent or still carries the template
    # password, so it always matches POSTGRES_PASSWORD.
    values = parse_env_text(text)
    db_url = values.get("DATABASE_URL", "")
    if (not db_url) or ("POSTGRES_PASSWORD" in changes) or any(
        p in db_url for p in PLACEHOLDER_VALUES
    ):
        user = values.get("POSTGRES_USER") or "argos_admin"
        dbname = values.get("POSTGRES_DB") or "argos_works"
        if any(p in user for p in PLACEHOLDER_VALUES):
            user = "argos_admin"
        if any(p in dbname for p in PLACEHOLDER_VALUES):
            dbname = "argos_works"
        password = values.get("POSTGRES_PASSWORD", "")
        text = set_env_value(
            text,
            "DATABASE_URL",
            f"postgresql://{user}:{password}@localhost:5432/{dbname}",
        )
        changes.append("DATABASE_URL")

    defaults = {
        "TRUSTED_PROXIES": DEFAULT_TRUSTED_PROXIES,
        "SESSION_TTL_HOURS": "24",
        "ALLOW_PUBLIC_REGISTER": "false",
        "TZ": "Asia/Seoul",
    }
    for key, value in defaults.items():
        if key not in values:
            text = set_env_value(text, key, value)
            changes.append(key)

    if text == original:
        _log(".env unchanged (no secrets needed regeneration)")
        return True
    if check_only:
        return _fail(f".env needs regeneration for: {', '.join(changes)}")

    if created:
        backup_note = ""
    else:
        backup = f"{ENV_PATH}.bak-{time.strftime('%Y%m%d%H%M%S')}"
        shutil.copyfile(ENV_PATH, backup)
        backup_note = f"; previous copy at {os.path.basename(backup)}"
    with open(ENV_PATH, "w", encoding="utf-8") as handle:
        handle.write(text)
    _log(f".env updated ({', '.join(changes)}){backup_note}")
    _log("Keep .env secret: it holds the master key used to encrypt stored credentials.")
    return True


def prepare_config(check_only=False):
    """server/config.json must exist as a real file before `docker compose up`."""
    if os.path.isdir(CONFIG_PATH):
        return _fail(
            "server/config.json is a directory - Docker created it because the file "
            "was missing during a previous deploy. Remove that directory (it contains "
            "no data) and run this script again."
        )
    if os.path.exists(CONFIG_PATH):
        _log("server/config.json present - unchanged")
        return True
    if check_only:
        return _fail("server/config.json is missing (run without --check to create it).")

    payload = {}
    if os.path.isfile(CONFIG_EXAMPLE):
        with open(CONFIG_EXAMPLE, "r", encoding="utf-8") as handle:
            try:
                payload = json.load(handle)
            except ValueError:
                payload = {}
    if not payload:
        payload = {"server": {"host": "0.0.0.0", "port": 8080}}
    with open(CONFIG_PATH, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    _log("server/config.json created from config.example.json")
    return True


def prepare_dirs(check_only=False):
    missing = []
    for rel in DATA_DIRS:
        target = os.path.join(ROOT, rel)
        if os.path.isdir(target):
            continue
        missing.append(rel)
        if not check_only:
            os.makedirs(target, exist_ok=True)
    if not missing:
        return True
    if check_only:
        return _fail(f"missing directories: {', '.join(missing)}")
    _log(f"created directories: {', '.join(missing)}")
    return True


def main():
    parser = argparse.ArgumentParser(description="Prepare an ARGOS WORKS self-hosted deployment.")
    parser.add_argument("--check", action="store_true", help="verify without writing anything")
    parser.add_argument(
        "--rotate",
        action="store_true",
        help="regenerate ARGOS_MASTER_KEY / POSTGRES_PASSWORD",
    )
    args = parser.parse_args()

    ok = True
    steps = (
        ("directories", lambda: prepare_dirs(args.check)),
        ("environment", lambda: prepare_env(args.check, args.rotate)),
        ("config", lambda: prepare_config(args.check)),
    )
    for label, step in steps:
        try:
            ok = step() and ok
        except OSError as exc:
            ok = _fail(f"{label} step failed: {exc}") and ok

    if not ok:
        return 1
    if args.check:
        _log("Deployment prerequisites are satisfied.")
    else:
        _log("Ready. Next: docker compose up -d --build")
    return 0


if __name__ == "__main__":
    sys.exit(main())

