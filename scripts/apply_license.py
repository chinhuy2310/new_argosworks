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

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_DIR = os.path.join(BASE_DIR, "server")
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from services.license_manager import verify_license_key  # noqa: E402

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
        conn.execute(
            """UPDATE license_info
               SET customer_name = ?, license_key = ?, max_seats = ?, expiry_date = ?, modules_json = ?, is_active = 1
               WHERE id = 1""",
            (
                data.get("customer") or "Enterprise Customer",
                license_key,
                int(data.get("seats") or 0),
                data.get("expiry") or "1970-01-01",
                json.dumps(data.get("modules") or []),
            ),
        )
        if conn.total_changes == 0:
            conn.execute(
                """INSERT INTO license_info (id, customer_name, license_key, max_seats, expiry_date, modules_json, is_active)
                   VALUES (1, ?, ?, ?, ?, ?, 1)""",
                (
                    data.get("customer") or "Enterprise Customer",
                    license_key,
                    int(data.get("seats") or 0),
                    data.get("expiry") or "1970-01-01",
                    json.dumps(data.get("modules") or []),
                ),
            )
        conn.commit()
    finally:
        conn.close()

    print("[OK] License applied")
    print(f"     DB       : {args.db}")
    print(f"     Customer : {data.get('customer')}")
    print(f"     Seats    : {data.get('seats')}")
    print(f"     Expiry   : {data.get('expiry')}")
    print(f"     Modules  : {', '.join(data.get('modules') or [])}")
    print("     Restart the server (or wait 30s for the license cache to expire).")


if __name__ == "__main__":
    main()
