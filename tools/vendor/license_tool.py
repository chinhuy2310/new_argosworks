#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
license_tool.py — VENDOR-ONLY license issuing tool for ARGOS WORKS.

WARNING: This tool and the private key it uses MUST NEVER be shipped to a
customer. It is excluded from release bundles by scripts/build_release.py.

Usage
-----
  # One-time: create the vendor key pair (private key stays on your machine)
  python tools/vendor/license_tool.py keygen

  # Issue a commercial license for a customer
  python tools/vendor/license_tool.py issue \
      --customer "ACME Manufacturing Co., Ltd." \
      --seats 40 --expiry 2027-12-31 \
      --modules canvas,pim,jira,rag,schedule,audit \
      --out licenses/ACME-2027.lic

  # Verify a license file / key before sending it to the customer
  python tools/vendor/license_tool.py inspect licenses/ACME-2027.lic

The private key is read from (in order):
  1. --key-file argument
  2. ARGOS_LICENSE_SIGNING_KEY environment variable (hex)
  3. tools/vendor/license_signing_key.hex (default location)

Keep the private key in a password manager / hardware token / offline vault.
If it leaks, every license it signed must be considered compromised: run
`keygen`, embed the new public key in server/services/license_manager.py,
rebuild, and re-issue all customer licenses.
"""
import argparse
import csv
import os
import sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SERVER_DIR = os.path.join(BASE_DIR, "server")
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from cryptography.hazmat.primitives.asymmetric import ed25519  # noqa: E402
from cryptography.hazmat.primitives import serialization  # noqa: E402

from services.license_manager import (  # noqa: E402
    generate_signed_license_key,
    verify_license_key,
    LicenseSigningKeyMissing,
)

DEFAULT_KEY_FILE = os.path.join(BASE_DIR, "tools", "vendor", "license_signing_key.hex")
ISSUE_LOG = os.path.join(BASE_DIR, "tools", "vendor", "issued_licenses.csv")

VALID_MODULES = ["canvas", "pim", "jira", "rag", "schedule", "audit"]


def _read_key(key_file=None):
    if key_file:
        if not os.path.exists(key_file):
            sys.exit(f"[ERROR] Key file not found: {key_file}")
        with open(key_file, "r", encoding="utf-8") as f:
            return f.read().strip()

    env_key = (os.environ.get("ARGOS_LICENSE_SIGNING_KEY") or "").strip()
    if env_key:
        return env_key

    if os.path.exists(DEFAULT_KEY_FILE):
        with open(DEFAULT_KEY_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()

    return ""


def _slug(name):
    cleaned = "".join(c if c.isalnum() or c in "-_" else "-" for c in name)
    return cleaned.strip("-").lower()[:48] or "customer"


def _sha256(value):
    import hashlib
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def cmd_keygen(args):
    private_key = ed25519.Ed25519PrivateKey.generate()
    priv_hex = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    ).hex()
    pub_hex = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()

    out_path = args.out or DEFAULT_KEY_FILE
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    if os.path.exists(out_path) and not args.force:
        sys.exit(
            f"[ERROR] {out_path} already exists. Refusing to overwrite a signing key "
            f"(use --force only if you are intentionally rotating and have re-issued licenses)."
        )

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(priv_hex + "\n")
    try:
        os.chmod(out_path, 0o600)
    except Exception:
        pass

    print("=" * 72)
    print("NEW SIGNING KEY PAIR GENERATED")
    print("=" * 72)
    print(f"Private key file : {out_path}   (KEEP OFFLINE - never commit/share)")
    print(f"Public key (hex) : {pub_hex}")
    print()
    print("Next steps:")
    print("  1) Embed the public key in server/services/license_manager.py:")
    print(f'     EMBEDDED_LICENSE_PUBLIC_KEY_HEX = "{pub_hex}"')
    print("  2) Rebuild + re-issue every existing customer license (old keys stop verifying).")
    print("  3) Back up the private key in a vault; losing it means you can never")
    print("     issue or renew a license again.")
    print("=" * 72)


def _log_issue(args, out_path):
    headers = ["issued_at", "customer", "seats", "expiry", "modules", "file", "key_sha256"]
    new_file = not os.path.exists(ISSUE_LOG)
    try:
        with open(out_path, "r", encoding="utf-8") as f:
            key_hash = _sha256(f.read().strip())
        with open(ISSUE_LOG, "a", newline="", encoding="utf-8") as log:
            writer = csv.writer(log)
            if new_file:
                writer.writerow(headers)
            writer.writerow([
                datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                args.customer,
                args.seats,
                args.expiry,
                ",".join(m.strip().lower() for m in args.modules.split(",") if m.strip()),
                os.path.relpath(out_path, BASE_DIR),
                key_hash,
            ])
    except Exception as e:
        print(f"[WARN] Could not append to issue log ({ISSUE_LOG}): {e}")


def cmd_issue(args):
    modules = [m.strip().lower() for m in (args.modules or "").split(",") if m.strip()]
    unknown = [m for m in modules if m not in VALID_MODULES]
    if unknown:
        sys.exit(f"[ERROR] Unknown module(s): {', '.join(unknown)}. Allowed: {', '.join(VALID_MODULES)}")
    if not modules:
        sys.exit("[ERROR] --modules is required (comma separated).")

    try:
        datetime.strptime(args.expiry, "%Y-%m-%d")
    except ValueError:
        sys.exit("[ERROR] --expiry must be YYYY-MM-DD")

    if args.seats <= 0:
        sys.exit("[ERROR] --seats must be a positive integer")

    key_hex = _read_key(args.key_file)
    if not key_hex:
        sys.exit(
            "[ERROR] No signing key found. Run `license_tool.py keygen` first, or pass "
            "--key-file / ARGOS_LICENSE_SIGNING_KEY."
        )

    try:
        license_key = generate_signed_license_key(
            customer_name=args.customer,
            max_seats=args.seats,
            expiry_date_str=args.expiry,
            modules=modules,
            signing_key_hex=key_hex,
        )
    except LicenseSigningKeyMissing as e:
        sys.exit(f"[ERROR] {e}")
    except ValueError as e:
        sys.exit(f"[ERROR] {e}")

    # Self-check: a license we cannot verify ourselves must never be delivered.
    ok, msg, data = verify_license_key(license_key)
    if not ok:
        sys.exit(f"[ERROR] Self-verification failed: {msg}")

    out_path = args.out or os.path.join(BASE_DIR, "licenses", f"{_slug(args.customer)}-{args.expiry}.lic")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(license_key + "\n")

    _log_issue(args, out_path)

    print("=" * 72)
    print("LICENSE ISSUED")
    print("=" * 72)
    print(f"Customer : {data['customer']}")
    print(f"Seats    : {data['seats']}")
    print(f"Expiry   : {data['expiry']}")
    print(f"Modules  : {', '.join(data['modules'])}")
    print(f"File     : {out_path}")
    print(f"SHA256   : {_sha256(license_key)}")
    print("=" * 72)


def cmd_inspect(args):
    source = args.license_file
    if os.path.exists(source):
        with open(source, "r", encoding="utf-8") as f:
            key = f.read().strip()
    else:
        key = source.strip()

    ok, msg, data = verify_license_key(key)
    print("=" * 72)
    print("LICENSE VERIFICATION")
    print("=" * 72)
    print(f"Result : {'VALID' if ok else 'INVALID'}")
    print(f"Message: {msg}")
    if data:
        print(f"Customer : {data.get('customer')}")
        print(f"Seats    : {data.get('seats')}")
        print(f"Expiry   : {data.get('expiry')}")
        print(f"Modules  : {', '.join(data.get('modules') or [])}")
        print(f"Trial    : {data.get('is_trial')}")
    print("=" * 72)
    if not ok:
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="ARGOS WORKS vendor license tool")
    sub = parser.add_subparsers(dest="command", required=True)

    p_keygen = sub.add_parser("keygen", help="Generate a new Ed25519 signing key pair")
    p_keygen.add_argument("--out", help="Private key output path")
    p_keygen.add_argument("--force", action="store_true", help="Overwrite an existing key file")
    p_keygen.set_defaults(func=cmd_keygen)

    p_issue = sub.add_parser("issue", help="Issue a signed offline license")
    p_issue.add_argument("--customer", required=True)
    p_issue.add_argument("--seats", type=int, required=True)
    p_issue.add_argument("--expiry", required=True, help="YYYY-MM-DD")
    p_issue.add_argument("--modules", required=True, help="Comma separated: " + ",".join(VALID_MODULES))
    p_issue.add_argument("--out", help="Output .lic path")
    p_issue.add_argument("--key-file", help="Path to the private key file")
    p_issue.set_defaults(func=cmd_issue)

    p_inspect = sub.add_parser("inspect", help="Verify a .lic file or raw key")
    p_inspect.add_argument("license_file")
    p_inspect.set_defaults(func=cmd_inspect)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
