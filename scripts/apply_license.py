#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
apply_license.py — Apply a signed .lic file to an existing SQLite database.

Useful for:
  * offline activation on an air-gapped machine (no admin UI access),
  * refreshing the bundled evaluation license in a dev/demo database,
  * recovering a deployment whose license row was damaged.

Usage:
  python scripts/apply_license.py licenses/trial-50.lic
  python scripts/apply_license.py C:\\Customer\\acme-2027.lic --db D:\\argos\\data\\argos.db

The license is verified against the vendor public key BEFORE it is written,
so an unsigned or tampered file is refused.
"""
import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_DIR = os.path.join(BASE_DIR, "server")
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from services.license_manager import verify_license_key, resolve_license_expiry  # noqa: E402

DEFAULT_DB = os.path.join(BASE_DIR, "data", "argos.db")


def main():
    parser = argparse.ArgumentParser(description="Apply a signed ARGOS license to a SQLite database")
    parser.add_argument("license_file", help="Path to the .lic file")
    parser.add_argument("--db", default=DEFAULT_DB, help=f"SQLite database path (default: {DEFAULT_DB})")
    args = parser.parse_args()

    if not os.path.exists(args.license_file):
        sys.exit(f"[ERROR] License file not found: {args.license_file}")
    if not os.path.exists(args.db):
        sys.exit(f"[ERROR] Database not found: {args.db}")

    with open(args.license_file, "r", encoding="utf-8") as f:
        license_key = f.read().strip()

    ok, msg, data = verify_license_key(license_key)
    if not ok:
        sys.exit(f"[ERROR] License rejected: {msg}")

    conn = sqlite3.connect(args.db)
    try:
        # Legacy databases may predate the trial activation anchor column.
        cols = {row[1] for row in conn.execute("PRAGMA table_info(license_info)").fetchall()}
        if "activated_at" not in cols:
            conn.execute("ALTER TABLE license_info ADD COLUMN activated_at TEXT NOT NULL DEFAULT '';")
        if "last_seen_ts" not in cols:
            conn.execute("ALTER TABLE license_info ADD COLUMN last_seen_ts REAL NOT NULL DEFAULT 0;")

        now_str = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        now_epoch = time.time()
        existing = conn.execute(
            "SELECT license_key, activated_at FROM license_info WHERE id = 1"
        ).fetchone()
        same_key = bool(existing) and (existing[0] or "").strip() == license_key
        anchor = ((existing[1] or "").strip() if same_key else "") or now_str

        exp_date, hard_cap, _anchor = resolve_license_expiry(data, anchor)
        if data.get("term_days") and exp_date and exp_date < datetime.now().date():
            sys.exit(
                f"[ERROR] Trial term of {data['term_days']} days already ended "
                f"({exp_date.strftime('%Y-%m-%d')})."
            )

        # The DB expiry column is informational only; a trial without a signed
        # hard cap stores its computed end date for readability.
        stored_expiry = str(data.get("expiry") or "")[:10]
        if not stored_expiry and exp_date:
            stored_expiry = exp_date.strftime("%Y-%m-%d")
        if not stored_expiry:
            stored_expiry = "1970-01-01"

        values = (
            data.get("customer") or "Enterprise Customer",
            license_key,
            int(data.get("seats") or 0),
            stored_expiry,
            json.dumps(data.get("modules") or []),
        )
        conn.execute(
            """UPDATE license_info
               SET customer_name = ?, license_key = ?, max_seats = ?, expiry_date = ?,
                   modules_json = ?, is_active = 1,
                   activated_at = CASE
                       WHEN COALESCE(license_key, '') <> ? THEN ?
                       ELSE COALESCE(NULLIF(activated_at, ''), ?)
                   END,
                   last_seen_ts = CASE
                       WHEN COALESCE(last_seen_ts, 0) > ? THEN last_seen_ts
                       ELSE ?
                   END
               WHERE id = 1""",
            values + (license_key, anchor, anchor, now_epoch, now_epoch),
        )
        if conn.total_changes == 0:
            conn.execute(
                """INSERT INTO license_info (id, customer_name, license_key, max_seats, expiry_date, modules_json, is_active, activated_at, last_seen_ts)
                   VALUES (1, ?, ?, ?, ?, ?, 1, ?, ?)""",
                values + (anchor, now_epoch),
            )
        conn.commit()
    finally:
        conn.close()

    effective = exp_date.strftime("%Y-%m-%d") if exp_date else (data.get("expiry") or "")
    print("[OK] License applied")
    print(f"     DB       : {args.db}")
    print(f"     Customer : {data.get('customer')}")
    print(f"     Seats    : {data.get('seats')}")
    print(f"     Expiry   : {effective}")
    if data.get("term_days"):
        print(f"     Trial    : {data['term_days']} days from activation {anchor[:10]}")
        print(f"     Hard cap : {hard_cap.strftime('%Y-%m-%d') if hard_cap else '-'}")
    print(f"     Modules  : {', '.join(data.get('modules') or [])}")
    print("     Restart the server (or wait 30s for the license cache to expire).")


if __name__ == "__main__":
    main()
