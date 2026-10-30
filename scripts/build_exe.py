#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
build_exe.py — Compile ARGOS WORKS with Nuitka into a customer-shippable folder.

The server code is translated to C and compiled, so the customer receives a
native executable and DLLs instead of readable .py files. (This raises the bar
considerably; it is not an absolute guarantee against reverse engineering.)
The web UI (HTML/CSS/JS) is shipped as-is: browsers must download it anyway.

Run it on the OS you are targeting — Nuitka cannot cross-compile:
  Windows .exe  ->  build on Windows (needs a C compiler; Nuitka can download MinGW64)

Prerequisites (once):
  pip install -r requirements.txt
  pip install nuitka ordered-set zstandard

Usage:
  python scripts/build_exe.py                 # folder build (recommended)
  python scripts/build_exe.py --onefile       # single file; slower start, more AV false positives
  python scripts/build_exe.py --skip-compile  # only re-assemble the package from build/nuitka

Output:
  dist/ArgosWorks-<VERSION>-<platform>/        unpacked package
  dist/ArgosWorks-<VERSION>-<platform>.zip     what you ship
"""
import argparse
import os
import shutil
import subprocess
import sys
import zipfile

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_DIR = os.path.join(BASE_DIR, "server")
BUILD_DIR = os.path.join(BASE_DIR, "build", "nuitka")
IS_WINDOWS = os.name == "nt"
EXE_NAME = "ArgosWorks.exe" if IS_WINDOWS else "ArgosWorks"

# Modules imported by name at runtime or via top-level imports from inside packages.
TOP_LEVEL_MODULES = [
    "app_paths", "config", "db", "handler", "router", "wsgi",
    "module_gate", "middleware_security", "embedded_services", "prompts",
]
PACKAGES = ["handlers", "services", "utils"]

# Never needed by a customer instance (and gunicorn is POSIX-only).
NOFOLLOW = ["gunicorn", "pytest", "tkinter", "setuptools", "pip"]

PACKAGE_ENV_EXAMPLE = """\
# ARGOS WORKS - optional settings. Copy this file to ".env" ONLY if you need to change something.
# On first start the program creates ".env" by itself and stores a random ARGOS_MASTER_KEY in it.
#
# !!! BACK UP the ".env" file together with the "data" folder. !!!
# Without the same ARGOS_MASTER_KEY, API keys and tokens saved in the program cannot be decrypted.

# Network port (default 8080). Open http://localhost:<port>/ in a browser.
# PORT=8080

# Do not open the browser automatically at start.
# ARGOS_NO_BROWSER=1

# Allow staff to self-register (true/false). Default false: only admins create accounts.
# ALLOW_PUBLIC_REGISTER=false

# Folder for automatic database backups (default: data\\backups).
# BACKUP_DIR=

# Leave DATABASE_URL unset to use the built-in SQLite database (no extra software needed).
# DATABASE_URL=
"""

PACKAGE_README = """\
ARGOS WORKS - huong dan nhanh
=============================

1. Giai nen toan bo thu muc nay vao mot noi co quyen ghi (vi du D:\\ArgosWorks).
   Khong chay truc tiep trong file .zip.
2. Bam dup {exe}. Cua so den se hien ra va trinh duyet tu mo http://localhost:8080/
   (neu chua mo, tu vao dia chi do). Lan chay dau tien, lam theo trinh huong dan cai dat de
   nhap giay phep va tao tai khoan quan tri.
3. May khac trong mang noi bo truy cap bang http://<IP-cua-may-nay>:8080/
   (co the phai cho phep cong 8080 trong Windows Firewall).
4. De dung chuong trinh, dong cua so den hoac bam Ctrl+C.

Du lieu va bao mat
------------------
- Du lieu nam o thu muc "data", nhat ky o "logs", cau hinh o "config.json".
- Lan chay dau tien chuong trinh tao file ".env" chua ARGOS_MASTER_KEY.
  HAY SAO LUU file ".env" cung thu muc "data". Mat khoa nay thi cac API key/token da luu
  khong the giai ma lai.
- Nang cap: chep de cac file chuong trinh moi len, GIU NGUYEN ".env", "data", "config.json".

Cac thiet lap tuy chon xem trong file ".env.example".
"""


def read_version():
    try:
        with open(os.path.join(BASE_DIR, "VERSION"), "r", encoding="utf-8") as fh:
            return fh.read().strip() or "0.0.0"
    except OSError:
        return "0.0.0"


def plat_tag():
    return {"nt": "win64", "posix": "linux64"}.get(os.name, os.name) if sys.maxsize > 2**32 else os.name


def numeric_version(version):
    """Nuitka wants N.N.N.N for the Windows file version."""
    parts = []
    for chunk in version.replace("-", ".").split("."):
        if chunk.isdigit():
            parts.append(chunk)
    while len(parts) < 4:
        parts.append("0")
    return ".".join(parts[:4])


def nuitka_command(onefile, version):
    cmd = [
        sys.executable, "-m", "nuitka",
        "--standalone",
        "--assume-yes-for-downloads",
        "--low-memory",
        "--jobs=1",
        "--lto=no",
        "--output-dir=" + BUILD_DIR,
        "--output-filename=" + EXE_NAME,
        "--remove-output",
        "--include-data-dir=%s=web" % os.path.join(BASE_DIR, "web"),
        "--include-data-files=%s=schema.sql" % os.path.join(SERVER_DIR, "schema.sql"),
        "--include-data-files=%s=schema.postgres.sql" % os.path.join(SERVER_DIR, "schema.postgres.sql"),
        "--include-data-files=%s=VERSION" % os.path.join(BASE_DIR, "VERSION"),
        "--product-name=ARGOS WORKS",
        "--file-description=ARGOS WORKS",
        "--product-version=" + numeric_version(version),
        "--file-version=" + numeric_version(version),
    ]
    if onefile:
        cmd.append("--onefile")
    for mod in TOP_LEVEL_MODULES:
        cmd.append("--include-module=" + mod)
    for pkg in PACKAGES:
        cmd.append("--include-package=" + pkg)
    for name in NOFOLLOW:
        cmd.append("--nofollow-import-to=" + name)
    if IS_WINDOWS:
        cmd.append("--windows-console-mode=force")
        icon_path = os.path.join(BASE_DIR, "installer", "app.ico")
        if os.path.isfile(icon_path):
            cmd.append("--windows-icon-from-ico=" + icon_path)
    cmd.append(os.path.join(SERVER_DIR, "main.py"))
    return cmd


def compile_app(onefile, version):
    if subprocess.call([sys.executable, "-c", "import nuitka"], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL) != 0:
        sys.exit("Nuitka is not installed. Run:  pip install nuitka ordered-set zstandard")
    # Keep BUILD_DIR to allow resuming incremental C compilation
    os.makedirs(BUILD_DIR, exist_ok=True)
    cmd = nuitka_command(onefile, version)
    print("[build] " + " ".join(cmd))
    # cwd outside the source tree so nothing from the working directory is picked up by accident.
    rc = subprocess.call(cmd, cwd=BUILD_DIR)
    if rc != 0:
        sys.exit("[build] Nuitka failed with exit code %d" % rc)


def locate_output(onefile):
    """Return (kind, path): the folder produced by --standalone, or the onefile executable."""
    dist = os.path.join(BUILD_DIR, "main.dist")
    if os.path.isdir(dist):
        return "folder", dist
    single = os.path.join(BUILD_DIR, EXE_NAME)
    if os.path.isfile(single):
        return "file", single
    sys.exit("[build] Could not find Nuitka output in %s" % BUILD_DIR)


def assemble(version, tag, embed_ai=False):
    kind, out = locate_output(False)
    name = "ArgosWorks-%s-%s" % (version, tag)
    pkg_root = os.path.join(BASE_DIR, "dist", name)
    shutil.rmtree(pkg_root, ignore_errors=True)
    os.makedirs(pkg_root)

    if kind == "folder":
        for item in os.listdir(out):
            src = os.path.join(out, item)
            dst = os.path.join(pkg_root, item)
            if os.path.isdir(src):
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
    else:
        shutil.copy2(out, os.path.join(pkg_root, EXE_NAME))

    with open(os.path.join(pkg_root, ".env.example"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(PACKAGE_ENV_EXAMPLE)
    with open(os.path.join(pkg_root, "README.txt"), "w", encoding="utf-8", newline="\r\n" if IS_WINDOWS else "\n") as fh:
        fh.write(PACKAGE_README.format(exe=EXE_NAME))
    for extra in ("LICENSE", "CHANGELOG.md"):
        src = os.path.join(BASE_DIR, extra)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(pkg_root, extra))
    lic_dir = os.path.join(BASE_DIR, "licenses")
    if os.path.isdir(lic_dir):
        shutil.copytree(lic_dir, os.path.join(pkg_root, "licenses"))

    icon_path = os.path.join(BASE_DIR, "installer", "app.ico")
    if os.path.isfile(icon_path):
        shutil.copy2(icon_path, os.path.join(pkg_root, "app.ico"))

    vendor_pgsql = os.path.join(BASE_DIR, "vendor", "pgsql")
    if os.path.isdir(vendor_pgsql):
        print("[build] Packaging embedded PostgreSQL 16...")
        shutil.copytree(vendor_pgsql, os.path.join(pkg_root, "pgsql"), dirs_exist_ok=True)

    vendor_caddy = os.path.join(BASE_DIR, "vendor", "caddy")
    if os.path.isdir(vendor_caddy):
        print("[build] Packaging embedded Caddy HTTPS proxy...")
        shutil.copytree(vendor_caddy, os.path.join(pkg_root, "caddy"), dirs_exist_ok=True)

    if embed_ai:
        vendor_ollama = os.path.join(BASE_DIR, "vendor", "ollama")
        if os.path.isdir(vendor_ollama):
            print("[build] Packaging embedded Ollama and local AI models...")
            shutil.copytree(vendor_ollama, os.path.join(pkg_root, "ollama"), dirs_exist_ok=True)

    caddyfile_path = os.path.join(pkg_root, "Caddyfile")
    if not os.path.isfile(caddyfile_path):
        with open(caddyfile_path, "w", encoding="utf-8") as cf:
            cf.write("{\n    admin off\n    local_certs\n}\n\nhttps://localhost:8443 {\n    reverse_proxy 127.0.0.1:8080\n}\n")

    # Safety net: a customer package must never contain secrets, data, or Python sources.
    leaks = []
    for root, _dirs, files in os.walk(pkg_root):
        for fname in files:
            low = fname.lower()
            if (low in (".env", "config.json", "argos.db") or low.endswith((".db", ".sqlite", ".py", ".pyc"))
                    or "signing_key" in low):
                leaks.append(os.path.relpath(os.path.join(root, fname), pkg_root))
    if leaks:
        shutil.rmtree(pkg_root, ignore_errors=True)
        sys.exit("[build] Refusing to package; unexpected files found:\n  " + "\n  ".join(leaks))

    zip_path = pkg_root + ".zip"
    if os.path.exists(zip_path):
        os.remove(zip_path)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(pkg_root):
            for fname in files:
                full = os.path.join(root, fname)
                zf.write(full, os.path.join(name, os.path.relpath(full, pkg_root)))
    return pkg_root, zip_path


def main():
    ap = argparse.ArgumentParser(description="Build the ARGOS WORKS native package with Nuitka.")
    ap.add_argument("--onefile", action="store_true", help="single-file executable (default: folder build)")
    ap.add_argument("--skip-compile", action="store_true", help="reuse existing build/nuitka output")
    ap.add_argument("--embed-ai", action="store_true", help="include embedded Ollama and local AI models in package")
    args = ap.parse_args()

    version = read_version()
    if not args.skip_compile:
        compile_app(args.onefile, version)
    tag = plat_tag()
    if args.embed_ai:
        tag += "-ai"
    pkg_root, zip_path = assemble(version, tag, embed_ai=args.embed_ai)
    print("[build] Package folder: " + pkg_root)
    print("[build] Zip to ship:    " + zip_path)


if __name__ == "__main__":
    main()
