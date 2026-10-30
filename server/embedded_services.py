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

start_embedded_services() returns a state dictionary describing what actually
became available (``postgres``/``caddy``/``ollama`` plus ownership flags) so the
startup banner only advertises services that answered a socket probe.

Caddy's data directory is pinned to ``<app_home>/data/caddy`` instead of the
per-user ``%APPDATA%\\Caddy`` default. That keeps the internal root CA with the
installation, identical for every Windows account and every machine, and lets
the console print one stable certificate path for client machines.
"""

import atexit
import os
import shutil
import socket
import subprocess
import sys
import time

from startup_report import POSTGRES_PORT, wait_for_port

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
_CADDY_PORT = 8443
_OLLAMA_PORT = 11434
_CADDY_START_TIMEOUT = 15.0
_OLLAMA_START_TIMEOUT = 5.0

_POSTGRES_STARTED = False
_CADDY_PROC = None
_CADDY_LOG_HANDLE = None
_OLLAMA_PROC = None
_PG_DATA_DIR = None
_PG_BIN_DIR = None


def _is_port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, socket.timeout):
        return False


def _close_caddy_log():
    global _CADDY_LOG_HANDLE
    if _CADDY_LOG_HANDLE is not None:
        try:
            _CADDY_LOG_HANDLE.close()
        except OSError:
            pass
        _CADDY_LOG_HANDLE = None


def _stop_embedded_services():
    global _POSTGRES_STARTED, _CADDY_PROC, _OLLAMA_PROC
    _close_caddy_log()

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


def _migrate_legacy_caddy_pki(target_dir: str) -> None:
    """Copy an existing per-user Caddy PKI so already-trusted clients keep working."""
    if os.path.isfile(os.path.join(target_dir, "pki", "authorities", "local", "root.crt")):
        return
    legacy_dirs = []
    for env_name in ("APPDATA", "LOCALAPPDATA"):
        base = os.environ.get(env_name)
        if base:
            legacy_dirs.append(os.path.join(base, "Caddy"))
    for legacy in legacy_dirs:
        legacy_pki = os.path.join(legacy, "pki")
        if not os.path.isdir(legacy_pki):
            continue
        try:
            shutil.copytree(legacy_pki, os.path.join(target_dir, "pki"), dirs_exist_ok=True)
            legacy_certs = os.path.join(legacy, "certificates")
            if os.path.isdir(legacy_certs):
                shutil.copytree(legacy_certs, os.path.join(target_dir, "certificates"), dirs_exist_ok=True)
        except OSError as exc:
            print("[Embedded HTTPS] Warning: could not migrate the local CA: %s" % exc, file=sys.stderr, flush=True)
            return
        print("[Embedded HTTPS] Migrated the existing local CA from %s" % legacy, flush=True)
        return


def _caddy_storage_dir(app_home: str):
    """Writable Caddy data directory pinned inside the installation, or None."""
    target = os.path.join(app_home, "data", "caddy")
    try:
        os.makedirs(target, exist_ok=True)
        probe = os.path.join(target, ".write-test")
        with open(probe, "w", encoding="utf-8") as handle:
            handle.write("ok")
        os.remove(probe)
    except OSError:
        return None
    _migrate_legacy_caddy_pki(target)
    return target


def _render_embedded_caddyfile(storage_dir) -> str:
    """Standalone Caddyfile: HTTPS on :8443 -> 127.0.0.1:8080 with a pinned data dir."""
    global_options = ["    admin off", "    auto_https disable_redirects"]
    if storage_dir:
        global_options.append('    storage file_system "%s"' % storage_dir.replace("\\", "/"))
    return (
        "{\n"
        + "\n".join(global_options)
        + "\n}\n\n:%d {\n    tls internal\n    reverse_proxy 127.0.0.1:8080\n}\n" % _CADDY_PORT
    )


def start_embedded_services(app_home: str):
    """Detect and launch embedded PostgreSQL and Caddy if bundled next to the app.

    Returns a state dictionary:
        {"postgres": bool, "caddy": bool, "caddy_owned": bool,
         "caddy_external": bool, "caddy_port": int, "caddy_log": str|None,
         "ollama": bool}
    Callers must treat this as advisory: it reflects socket probes, not intent.
    """
    global _POSTGRES_STARTED, _CADDY_PROC, _CADDY_LOG_HANDLE, _PG_DATA_DIR, _PG_BIN_DIR

    state = {
        "postgres": False,
        "caddy": False,
        "caddy_owned": False,
        "caddy_external": False,
        "caddy_port": _CADDY_PORT,
        "caddy_log": None,
        "ollama": False,
    }

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
        started_here = False
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
                started_here = True
            except Exception as exc:
                print("[Embedded DB] pg_ctl start error: %s" % exc, file=sys.stderr, flush=True)

            # Wait for PostgreSQL to be ready
            for _ in range(40):
                if _is_port_open("127.0.0.1", 5432):
                    break
                time.sleep(0.2)

        if _is_port_open("127.0.0.1", 5432):
            # Only the process that started PostgreSQL may stop it: a second launch
            # must never shut down a database shared with the running instance.
            if started_here:
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

    if pg_bin:
        state["postgres"] = _is_port_open("127.0.0.1", POSTGRES_PORT)

    # -------------------------------------------------------------------------
    # 2. Embedded Caddy (HTTPS Reverse Proxy)
    # -------------------------------------------------------------------------
    candidate_caddy_bins = [
        os.path.join(app_home, "caddy", "caddy.exe"),
        os.path.join(app_home, "vendor", "caddy", "caddy.exe"),
    ]
    caddy_exe = next((c for c in candidate_caddy_bins if os.path.isfile(c)), None)

    if caddy_exe:
        # Dedicated standalone Caddyfile so the Docker Caddyfile (:443, argos-works
        # service name) is never reused by the desktop build. The file is generated
        # on every start; set ARGOS_KEEP_CADDYFILE=1 to keep manual edits.
        caddyfile = os.path.join(app_home, "data", "Caddyfile.embedded")
        storage_dir = _caddy_storage_dir(app_home)
        caddy_content = _render_embedded_caddyfile(storage_dir)
        try:
            keep_existing = os.environ.get("ARGOS_KEEP_CADDYFILE", "0").strip().lower() in ("1", "true", "yes")
            if not (keep_existing and os.path.isfile(caddyfile)):
                os.makedirs(os.path.dirname(caddyfile), exist_ok=True)
                with open(caddyfile, "w", encoding="utf-8") as f:
                    f.write(caddy_content)
        except OSError as exc:
            print("[Embedded HTTPS] Warning: could not write %s: %s" % (caddyfile, exc), file=sys.stderr, flush=True)

        if os.path.isfile(caddyfile):
            if _is_port_open("127.0.0.1", _CADDY_PORT):
                # Somebody already serves 8443: either an orphaned Caddy from a
                # previous run, another install, or an unrelated application.
                state["caddy"] = True
                state["caddy_external"] = True
                print(
                    "[Embedded HTTPS] Port %d is already served by another process; reusing that listener."
                    % _CADDY_PORT,
                    flush=True,
                )
            else:
                print("[Embedded HTTPS] Starting Caddy reverse proxy on https://localhost:%d..." % _CADDY_PORT, flush=True)
                log_dir = os.path.join(app_home, "logs")
                try:
                    os.makedirs(log_dir, exist_ok=True)
                    _CADDY_LOG_HANDLE = open(os.path.join(log_dir, "caddy.log"), "ab")
                    state["caddy_log"] = os.path.join(log_dir, "caddy.log")
                except OSError:
                    _CADDY_LOG_HANDLE = None
                try:
                    _CADDY_PROC = subprocess.Popen(
                        [caddy_exe, "run", "--config", caddyfile],
                        cwd=app_home,
                        stdout=_CADDY_LOG_HANDLE or subprocess.DEVNULL,
                        stderr=_CADDY_LOG_HANDLE or subprocess.DEVNULL,
                        creationflags=CREATE_NO_WINDOW,
                    )
                    if not _POSTGRES_STARTED:
                        atexit.register(_stop_embedded_services)
                except Exception as exc:
                    print("[Embedded HTTPS] Warning: could not launch Caddy: %s" % exc, file=sys.stderr, flush=True)

                if wait_for_port("127.0.0.1", _CADDY_PORT, timeout=_CADDY_START_TIMEOUT):
                    state["caddy"] = True
                    state["caddy_owned"] = True
                else:
                    print(
                        "[Embedded HTTPS] Caddy did not open port %d within %.0fs; HTTPS stays disabled."
                        % (_CADDY_PORT, _CADDY_START_TIMEOUT),
                        file=sys.stderr,
                        flush=True,
                    )
                    if state["caddy_log"]:
                        print("[Embedded HTTPS] Last lines of %s:" % state["caddy_log"], file=sys.stderr, flush=True)
                        try:
                            with open(state["caddy_log"], "r", encoding="utf-8", errors="replace") as fh:
                                for line in fh.read().splitlines()[-15:]:
                                    print("    " + line, file=sys.stderr, flush=True)
                        except OSError:
                            pass

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

        state["ollama"] = wait_for_port("127.0.0.1", _OLLAMA_PORT, timeout=_OLLAMA_START_TIMEOUT)

    return state
