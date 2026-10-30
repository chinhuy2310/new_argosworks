#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""embedded_services.py - Manages embedded PostgreSQL and Caddy HTTPS reverse proxy on Windows.

When ArgosWorks is packaged as a standalone Windows application with embedded
PostgreSQL and Caddy binaries, this module automatically boots and stops them:
  1. Boots PostgreSQL 16 Portable on localhost:5432 (auto-runs initdb on first launch).
  2. Creates the 'argos_works' database if not present.
  3. Sets DATABASE_URL="postgresql://argos_admin@127.0.0.1:5432/argos_works".
  4. Starts Caddy to serve HTTPS on https://localhost:8443.
  5. Cleanly stops both services on application exit via atexit.
"""

import atexit
import os
import socket
import subprocess
import sys
import time

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
_POSTGRES_STARTED = False
_CADDY_PROC = None
_OLLAMA_PROC = None
_PG_DATA_DIR = None
_PG_BIN_DIR = None


def _is_port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, socket.timeout):
        return False


def _stop_embedded_services():
    global _POSTGRES_STARTED, _CADDY_PROC, _OLLAMA_PROC
    if _OLLAMA_PROC and _OLLAMA_PROC.poll() is None:
        try:
            _OLLAMA_PROC.terminate()
            _OLLAMA_PROC.wait(timeout=3)
        except Exception:
            try:
                _OLLAMA_PROC.kill()
            except Exception:
                pass
        _OLLAMA_PROC = None

    if _CADDY_PROC and _CADDY_PROC.poll() is None:
        try:
            _CADDY_PROC.terminate()
            _CADDY_PROC.wait(timeout=3)
        except Exception:
            try:
                _CADDY_PROC.kill()
            except Exception:
                pass
        _CADDY_PROC = None

    if _POSTGRES_STARTED and _PG_BIN_DIR and _PG_DATA_DIR:
        pg_ctl = os.path.join(_PG_BIN_DIR, "pg_ctl.exe")
        if os.path.isfile(pg_ctl):
            try:
                subprocess.run(
                    [pg_ctl, "-D", _PG_DATA_DIR, "stop", "-m", "fast"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=CREATE_NO_WINDOW,
                    timeout=10,
                )
            except Exception:
                pass
        _POSTGRES_STARTED = False


def start_embedded_services(app_home: str):
    """Detect and launch embedded PostgreSQL and Caddy if bundled next to the app."""
    global _POSTGRES_STARTED, _CADDY_PROC, _PG_DATA_DIR, _PG_BIN_DIR

    # -------------------------------------------------------------------------
    # 1. Embedded PostgreSQL 16
    # -------------------------------------------------------------------------
    candidate_pg_bins = [
        os.path.join(app_home, "pgsql", "bin"),
        os.path.join(app_home, "vendor", "pgsql", "bin"),
    ]
    pg_bin = next((b for b in candidate_pg_bins if os.path.isfile(os.path.join(b, "postgres.exe"))), None)

    if pg_bin:
        _PG_BIN_DIR = pg_bin
        if pg_bin not in os.environ.get("PATH", ""):
            os.environ["PATH"] = pg_bin + os.pathsep + os.environ.get("PATH", "")

    if pg_bin and not os.environ.get("DATABASE_URL"):
        data_dir = os.path.join(app_home, "data", "postgres")
        log_dir = os.path.join(app_home, "logs")
        os.makedirs(data_dir, exist_ok=True)
        os.makedirs(log_dir, exist_ok=True)
        _PG_DATA_DIR = data_dir
        log_file = os.path.join(log_dir, "postgres.log")

        initdb_exe = os.path.join(pg_bin, "initdb.exe")
        pg_ctl_exe = os.path.join(pg_bin, "pg_ctl.exe")
        createdb_exe = os.path.join(pg_bin, "createdb.exe")

        # First run: initialize database cluster if PG_VERSION doesn't exist
        pg_version_file = os.path.join(data_dir, "PG_VERSION")
        if not os.path.isfile(pg_version_file):
            print("[Embedded DB] First run: initializing PostgreSQL cluster in %s..." % data_dir, flush=True)
            try:
                subprocess.run(
                    [initdb_exe, "-D", data_dir, "-U", "argos_admin", "-A", "trust", "-E", "UTF8", "--locale=C"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=CREATE_NO_WINDOW,
                    timeout=30,
                )
            except Exception as exc:
                print("[Embedded DB] initdb error: %s" % exc, file=sys.stderr, flush=True)

        # Start PostgreSQL if not already running on 5432
        if not _is_port_open("127.0.0.1", 5432):
            print("[Embedded DB] Starting embedded PostgreSQL 16 on 127.0.0.1:5432...", flush=True)
            try:
                subprocess.run(
                    [pg_ctl_exe, "-D", data_dir, "-l", log_file, "-o", "-p 5432 -h 127.0.0.1", "start"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=CREATE_NO_WINDOW,
                    timeout=15,
                )
            except Exception as exc:
                print("[Embedded DB] pg_ctl start error: %s" % exc, file=sys.stderr, flush=True)

            # Wait for PostgreSQL to be ready
            for _ in range(40):
                if _is_port_open("127.0.0.1", 5432):
                    break
                time.sleep(0.2)

        if _is_port_open("127.0.0.1", 5432):
            _POSTGRES_STARTED = True
            atexit.register(_stop_embedded_services)

            # Ensure default database 'argos_works' exists
            if os.path.isfile(createdb_exe):
                try:
                    subprocess.run(
                        [createdb_exe, "-h", "127.0.0.1", "-p", "5432", "-U", "argos_admin", "argos_works"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=CREATE_NO_WINDOW,
                        timeout=10,
                    )
                except Exception:
                    pass

            os.environ["DATABASE_URL"] = "postgresql://argos_admin@127.0.0.1:5432/argos_works"
            print("[Embedded DB] Connected: PostgreSQL is ready at %s" % os.environ["DATABASE_URL"], flush=True)

    # -------------------------------------------------------------------------
    # 2. Embedded Caddy (HTTPS Reverse Proxy)
    # -------------------------------------------------------------------------
    candidate_caddy_bins = [
        os.path.join(app_home, "caddy", "caddy.exe"),
        os.path.join(app_home, "vendor", "caddy", "caddy.exe"),
    ]
    caddy_exe = next((c for c in candidate_caddy_bins if os.path.isfile(c)), None)

    if caddy_exe:
        # Use dedicated standalone Caddyfile to avoid conflict with Docker Caddyfile (:443)
        caddyfile = os.path.join(app_home, "data", "Caddyfile.embedded")
        default_caddy_content = (
            "{\n"
            "    admin off\n"
            "    auto_https disable_redirects\n"
            "}\n\n"
            ":8443 {\n"
            "    tls internal\n"
            "    reverse_proxy 127.0.0.1:8080\n"
            "}\n"
        )
        try:
            with open(caddyfile, "w", encoding="utf-8") as f:
                f.write(default_caddy_content)
        except Exception:
            pass

        if os.path.isfile(caddyfile) and not _is_port_open("127.0.0.1", 8443):
            print("[Embedded HTTPS] Starting Caddy reverse proxy on https://localhost:8443...", flush=True)
            try:
                _CADDY_PROC = subprocess.Popen(
                    [caddy_exe, "run", "--config", caddyfile],
                    cwd=app_home,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=CREATE_NO_WINDOW,
                )
                if not _POSTGRES_STARTED:
                    atexit.register(_stop_embedded_services)
            except Exception as exc:
                print("[Embedded HTTPS] Warning: could not launch Caddy: %s" % exc, file=sys.stderr, flush=True)

    # -------------------------------------------------------------------------
    # 3. Embedded Ollama (Local AI & BGE-M3 Embeddings)
    # -------------------------------------------------------------------------
    candidate_ollama_bins = [
        os.path.join(app_home, "ollama", "ollama.exe"),
        os.path.join(app_home, "vendor", "ollama", "ollama.exe"),
    ]
    ollama_exe = next((o for o in candidate_ollama_bins if os.path.isfile(o)), None)

    if ollama_exe:
        global _OLLAMA_PROC
        candidate_model_dirs = [
            os.path.join(app_home, "ollama", "models"),
            os.path.join(app_home, "vendor", "ollama", "models"),
            os.path.join(app_home, "data", "models"),
        ]
        models_dir = next((d for d in candidate_model_dirs if os.path.isdir(d)), os.path.join(app_home, "data", "models"))
        os.makedirs(models_dir, exist_ok=True)

        if not _is_port_open("127.0.0.1", 11434):
            print("[Embedded AI] Starting embedded Ollama on http://127.0.0.1:11434...", flush=True)
            try:
                ollama_env = os.environ.copy()
                ollama_env["OLLAMA_MODELS"] = models_dir
                ollama_env["OLLAMA_HOST"] = "127.0.0.1:11434"
                _OLLAMA_PROC = subprocess.Popen(
                    [ollama_exe, "serve"],
                    cwd=app_home,
                    env=ollama_env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=CREATE_NO_WINDOW,
                )
                atexit.register(_stop_embedded_services)
            except Exception as exc:
                print("[Embedded AI] Warning: could not launch Ollama: %s" % exc, file=sys.stderr, flush=True)

        # Automatically default to Ollama + bge-m3 if not already customized
        if not os.environ.get("VOYAGE_PROVIDER"):
            os.environ["VOYAGE_PROVIDER"] = "ollama"
        if not os.environ.get("VOYAGE_MODEL"):
            os.environ["VOYAGE_MODEL"] = "bge-m3"
        if not os.environ.get("VOYAGE_BASE_URL"):
            os.environ["VOYAGE_BASE_URL"] = "http://127.0.0.1:11434/v1/embeddings"
        if os.environ.get("VOYAGE_ENABLED") is None:
            os.environ["VOYAGE_ENABLED"] = "true"
