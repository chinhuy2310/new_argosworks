#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
build_release.py — Build a clean, customer-shippable ARGOS WORKS bundle.

Why this exists: the repository contains internal-only material (vendor signing
key, demo seed with Korean departments, developer docs, local data). Shipping
the repo as-is leaks internal data and the ability to mint licenses.

Output:
  dist/argos-works-<VERSION>/        (unpacked bundle)
  dist/argos-works-<VERSION>.zip     (what you upload/ship)

Usage:
  python scripts/build_release.py
  python scripts/build_release.py --out D:\\release --include-docs
"""
import argparse
import os
import shutil
import sys
import zipfile
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Everything a customer instance needs.
INCLUDE = [
    "server",
    "web",
    "deploy",
    "licenses",
    "scripts/init_deploy.py",
    "scripts/init_deploy.ps1",
    "scripts/apply_license.py",
    "requirements.txt",
    "requirements.lock",
    "VERSION",
    "CHANGELOG.md",
    "README.md",
    "LICENSE",
    "Dockerfile",
    "docker-compose.yml",
    "docker-entrypoint.sh",
    "Caddyfile",
    ".env.example",
    ".dockerignore",
    "run_server.bat",
    "deploy.sh",
    "deploy.bat",
    "run_tests.sh",
    "run_tests.bat",
]

# Never ship these, even if they appear inside an included directory.
EXCLUDE_NAMES = {
    "__pycache__", ".git", ".github", ".venv", "venv", "node_modules",
    ".pytest_cache", ".idea", ".vscode", "dist",
}
EXCLUDE_SUFFIXES = (
    ".pyc", ".pyo", ".db", ".db-wal", ".db-shm", ".sqlite", ".sqlite-wal",
    ".sqlite-shm", ".log", ".tmp", ".hex",
)
EXCLUDE_RELATIVE = {
    os.path.normpath("server/config.json"),
    os.path.normpath("server/argos.db"),
    os.path.normpath("data"),
    os.path.normpath("logs"),
    os.path.normpath("tools/vendor"),
    os.path.normpath("tests"),
    os.path.normpath("scratch"),
    os.path.normpath("docs"),
}


def _excluded(rel_path, name):
    norm = os.path.normpath(rel_path)
    if norm in EXCLUDE_RELATIVE:
        return True
    for blocked in EXCLUDE_RELATIVE:
        if norm.startswith(blocked + os.sep):
            return True
    if name in EXCLUDE_NAMES:
        return True
    if name.lower().endswith(EXCLUDE_SUFFIXES):
        return True
    # Vendor signing key must never travel with a release, whatever its name.
    if "signing_key" in name.lower():
        return True
    return False


def _copy_item(src, dest_root, include_docs=False):
    if os.path.isdir(src):
        count = 0
        for root, dirs, files in os.walk(src):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_NAMES]
            for fname in files:
                full = os.path.join(root, fname)
                rel_file = os.path.relpath(full, BASE_DIR)
                if _excluded(rel_file, fname):
                    continue
                target = os.path.join(dest_root, rel_file)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.copy2(full, target)
                count += 1
        return count

    if os.path.exists(src):
        rel_file = os.path.relpath(src, BASE_DIR)
        if _excluded(rel_file, os.path.basename(src)):
            return 0
        target = os.path.join(dest_root, rel_file)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(src, target)
        return 1
    return 0


def _read_version():
    try:
        with open(os.path.join(BASE_DIR, "VERSION"), "r", encoding="utf-8") as f:
            return f.read().strip() or "0.0.0"
    except Exception:
        return "0.0.0"


def _zip_dir(src_dir, zip_path):
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for root, _dirs, files in os.walk(src_dir):
            for fname in files:
                full = os.path.join(root, fname)
                arc = os.path.relpath(full, os.path.dirname(src_dir))
                zf.write(full, arc)


def main():
    parser = argparse.ArgumentParser(description="Build a clean ARGOS WORKS release bundle")
    parser.add_argument("--out", default=os.path.join(BASE_DIR, "dist"), help="Output directory")
    parser.add_argument("--include-docs", action="store_true", help="Include docs/*.md (admin/user guides)")
    args = parser.parse_args()

    version = _read_version()
    bundle_name = f"argos-works-{version}"
    bundle_dir = os.path.join(os.path.abspath(args.out), bundle_name)

    if os.path.exists(bundle_dir):
        shutil.rmtree(bundle_dir)
    os.makedirs(bundle_dir, exist_ok=True)

    copied = 0
    for item in INCLUDE:
        copied += _copy_item(os.path.join(BASE_DIR, item), bundle_dir)

    if args.include_docs:
        doc_dir = os.path.join(BASE_DIR, "docs")
        if os.path.isdir(doc_dir):
            os.makedirs(os.path.join(bundle_dir, "docs"), exist_ok=True)
            for fname in ("ADMIN_GUIDE.md", "USER_GUIDE.md", "SECURITY_WHITEPAPER.md",
                          "SLA.md", "DEPLOYMENT.md", "EULA.md"):
                src = os.path.join(doc_dir, fname)
                if os.path.exists(src):
                    shutil.copy2(src, os.path.join(bundle_dir, "docs", fname))
                    copied += 1

    manifest = [
        f"ARGOS WORKS release bundle {version}",
        f"built_at={datetime.now().isoformat(timespec='seconds')}",
        f"files={copied}",
        "",
        "NOT INCLUDED (by design):",
        "  data/, logs/, server/config.json, server/argos.db,",
        "  tools/vendor/ (license signing key), tests/, scratch/, docs/ (unless --include-docs)",
        "",
        "First run:",
        "  1) cp .env.example .env  -> set ARGOS_MASTER_KEY / DATABASE_URL",
        "  2) docker compose up -d   (or: python -m waitress --listen=0.0.0.0:8080 server.wsgi:application)",
        "  3) open https://<host>/setup.html and activate the license",
    ]
    with open(os.path.join(bundle_dir, "RELEASE_MANIFEST.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(manifest) + "\n")

    # Fail the build if a private key or a customer database slipped in.
    leaks = []
    for root, _dirs, files in os.walk(bundle_dir):
        for fname in files:
            if "signing_key" in fname.lower() or fname.endswith((".db", ".sqlite", ".hex")):
                leaks.append(os.path.relpath(os.path.join(root, fname), bundle_dir))
    if leaks:
        shutil.rmtree(bundle_dir, ignore_errors=True)
        sys.exit(f"[FATAL] Refusing to build: sensitive files in bundle: {leaks}")

    zip_path = bundle_dir + ".zip"
    _zip_dir(bundle_dir, zip_path)

    size_mb = os.path.getsize(zip_path) / (1024 * 1024)
    print("=" * 72)
    print(f"RELEASE BUILT: {version}")
    print("=" * 72)
    print(f"Bundle : {bundle_dir}")
    print(f"Zip    : {zip_path} ({size_mb:.1f} MB)")
    print(f"Files  : {copied}")
    print("=" * 72)


if __name__ == "__main__":
    main()
