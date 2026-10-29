#!/usr/bin/env python3
"""scripts/backfill_assignee_ids.py

Backfill missing `assignee_id` in `records` table:
For records where `assignee_id IS NULL` and `assignee_name != ''`, look up users in the same `dept_id`.
If exactly 1 user matches (name or username), assign their `id`.
If ambiguous (>1) or not found (0), leave NULL.

Usage:
    python scripts/backfill_assignee_ids.py          # Dry-run (default, read-only)
    python scripts/backfill_assignee_ids.py --apply  # Apply updates to database
"""

import os
import sys

# Ensure server package can be imported
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
SERVER_DIR = os.path.join(ROOT_DIR, "server")
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from db import query, execute, init_db, transaction


def backfill_assignee_ids(apply_changes: bool = False):
    init_db()
    records = query("SELECT id, dept_id, assignee_name FROM records WHERE assignee_id IS NULL AND assignee_name != ''")
    
    total = len(records)
    will_update = []
    ambiguous = []
    unmatched = []

    for r in records:
        rec_id = r["id"]
        dept_id = r["dept_id"]
        assignee_name = r["assignee_name"].strip()

        users = query(
            "SELECT id, name, username, dept_id FROM users WHERE (name = ? OR username = ?) AND dept_id = ?",
            (assignee_name, assignee_name, dept_id)
        )

        if len(users) == 1:
            will_update.append((users[0]["id"], rec_id, assignee_name, dept_id))
        elif len(users) > 1:
            ambiguous.append((rec_id, assignee_name, dept_id, len(users)))
        else:
            unmatched.append((rec_id, assignee_name, dept_id))

    print("=" * 60)
    print(f"Assignee ID Backfill Report ({'APPLY MODE' if apply_changes else 'DRY-RUN MODE'})")
    print("=" * 60)
    print(f"Total records with NULL assignee_id: {total}")
    print(f"Eligible for update (unique match in dept): {len(will_update)}")
    print(f"Ambiguous in same dept (>1 matches):        {len(ambiguous)}")
    print(f"Unmatched in same dept (0 matches):         {len(unmatched)}")

    if ambiguous:
        print("\n[!] Ambiguous records (skipped):")
        for rec_id, name, dept, count in ambiguous[:10]:
            print(f"  - Record #{rec_id} (dept: {dept}, assignee: '{name}') has {count} matching users")
        if len(ambiguous) > 10:
            print(f"  ... and {len(ambiguous) - 10} more.")

    if apply_changes and will_update:
        print(f"\nApplying updates to {len(will_update)} records...")
        def _do_update(conn):
            cur = conn.cursor()
            for user_id, rec_id, _, _ in will_update:
                cur.execute("UPDATE records SET assignee_id = ? WHERE id = ?", (user_id, rec_id))
        transaction(_do_update)
        print("Successfully applied updates.")
    elif not apply_changes and will_update:
        print("\nRun with '--apply' to commit these changes to the database.")

    return {
        "total": total,
        "eligible": len(will_update),
        "ambiguous": len(ambiguous),
        "unmatched": len(unmatched)
    }


if __name__ == "__main__":
    apply_flag = "--apply" in sys.argv
    backfill_assignee_ids(apply_changes=apply_flag)
