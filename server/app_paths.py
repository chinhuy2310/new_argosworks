#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""app_paths.py — single source of truth for where ARGOS WORKS reads and writes files.

Two layouts are supported:

  * Source / Docker layout (default)
        <repo>/server/*.py      code            (RES_DIR)
        <repo>/web/             static UI       (WEB_ROOT/web)
        <repo>/data, logs, .env writable state  (APP_HOME)

  * Packaged layout (compiled with Nuitka / frozen)
        ArgosWorks/ArgosWorks.exe   launcher    (APP_HOME = folder of the exe)
        ArgosWorks/.env, config.json, data/, logs/    writable, owned by the customer
        <bundle>/web, schema.sql, VERSION             read-only, shipped inside the build
                                                      (RES_DIR == WEB_ROOT)

Keeping writable state next to the executable (never inside the temporary
extraction folder of a onefile build) is what makes upgrades safe: replacing the
exe does not touch the customer's data or secrets.

This module must not import anything from the rest of the server.
"""

import os
import sys

# Nuitka sets a module-level ``__compiled__``; PyInstaller sets ``sys.frozen``.
IS_FROZEN = bool(getattr(sys, "frozen", False)) or ("__compiled__" in globals())

# Directory that holds this module: ``server/`` from source, bundle root when compiled.
RES_DIR = os.path.dirname(os.path.abspath(__file__))

if IS_FROZEN:
    # sys.argv[0] is the path of the executable the customer launched, even for a
    # onefile build (where __file__ points into a temporary extraction folder).
    APP_HOME = os.environ.get("ARGOS_HOME") or os.path.dirname(os.path.abspath(sys.argv[0]))
    WEB_ROOT = RES_DIR
else:
    APP_HOME = os.environ.get("ARGOS_HOME") or os.path.dirname(RES_DIR)
    WEB_ROOT = os.path.dirname(RES_DIR)
