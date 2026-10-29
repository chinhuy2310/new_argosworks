#!/usr/bin/env python3
"""scripts/check_duplicate_identities.py

Lists case-insensitive duplicate usernames and emails in the `users` table.
Used by system administrators to audit and resolve duplicate accounts before
applying unique case-insensitive indexes.

Exit codes:
    0: No duplicate identities found (safe to apply unique index)
    1: One or more case-insensitive duplicate identities found
"""

import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
SERVER_DIR = os.path.join(ROOT_DIR, "server")
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from db import query, init_db


def check_duplicate_identities():
    init_db()

    rows = query("SELECT id, username, name, dept_id, email FROM users ORDER BY id ASC")
    
    # 1. Group usernames by LOWER
    user_groups = {}
    for r in rows:
        uname = (r["username"] or "").strip()
        if uname:
            key = uname.lower()
            user_groups.setdefault(key, []).append(r)

    dup_usernames = {k: v for k, v in user_groups.items() if len(v) > 1}

    # 2. Group emails by LOWER
    email_groups = {}
    for r in rows:
        mail = (r["email"] or "").strip()
        if mail:
            key = mail.lower()
            email_groups.setdefault(key, []).append(r)

    dup_emails = {k: v for k, v in email_groups.items() if len(v) > 1}

    print("=" * 65)
    print("Case-Insensitive User Identity Audit Report")
    print("=" * 65)

    found_duplicates = False

    if dup_usernames:
        found_duplicates = True
        print(f"\n[!] Duplicate Case-Insensitive Usernames Detected ({len(dup_usernames)} groups):")
        for lower_name, users in dup_usernames.items():
            print(f"  Key: '{lower_name}' ({len(users)} conflicting accounts):")
            for u in users:
                print(f"    - ID: {u['id']}, Username: '{u['username']}', Name: '{u['name']}', Dept: '{u['dept_id']}'")
    else:
        print("\n[OK] No duplicate usernames detected.")

    if dup_emails:
        found_duplicates = True
        print(f"\n[!] Duplicate Case-Insensitive Emails Detected ({len(dup_emails)} groups):")
        for lower_email, users in dup_emails.items():
            print(f"  Key: '{lower_email}' ({len(users)} conflicting accounts):")
            for u in users:
                print(f"    - ID: {u['id']}, Email: '{u['email']}', Name: '{u['name']}', Dept: '{u['dept_id']}'")
    else:
        print("\n[OK] No duplicate emails detected.")

    print("\n" + "=" * 65)
    if found_duplicates:
        print("ACTION REQUIRED: Resolve duplicate accounts above so case-insensitive")
        print("unique indexes can be safely applied to users(LOWER(username)) and users(LOWER(email)).")
        return 1
    else:
        print("All usernames and emails are unique across cases.")
        return 0


if __name__ == "__main__":
    code = check_duplicate_identities()
    sys.exit(code)
