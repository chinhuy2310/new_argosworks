#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""instance_guard.py - one ARGOS WORKS server process per data directory.

Two server processes sharing one data directory corrupt backups, vector sync
and the embedded database, so the data directory is the natural unit of
exclusivity (not the TCP port).

Design notes (Windows):

* ``data/.server.lock`` is an empty file whose first byte is locked through the
  OS (``msvcrt.locking`` / ``fcntl.flock``). It is never read or written.
  Windows LockFile is *mandatory*, so keeping the metadata in a separate file is
  what allows another process to inspect the owner.
* ``data/.server.owner`` holds the owner metadata as plain JSON (pid, port,
  data directory, version). Any process - or a human with a text editor - can
  read it while the lock is held.
* Liveness is decided by the lock only: the OS drops it when the process exits,
  including a crash, so a stale ``.server.owner`` file can never block a restart.
"""

import json
import os
import sys

LOCK_FILENAME = ".server.lock"
OWNER_FILENAME = ".server.owner"

_handle = None


def lock_path(app_home):
    """Absolute path of the lock file for *app_home*."""
    return os.path.join(app_home, "data", LOCK_FILENAME)


def owner_path(app_home):
    """Absolute path of the owner metadata file for *app_home*."""
    return os.path.join(app_home, "data", OWNER_FILENAME)


def _write_owner(app_home, meta):
    """Persist the owner metadata for inspection by other processes."""
    target = owner_path(app_home)
    tmp = target + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(meta or {}, handle, ensure_ascii=False)
        os.replace(tmp, target)
        return True
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


def _os_lock(fd):
    if sys.platform == "win32":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _os_unlock(fd):
    if sys.platform == "win32":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_UN)


def read_holder(app_home):
    """Metadata recorded by the process that owns the data directory, or None."""
    try:
        with open(owner_path(app_home), "r", encoding="utf-8") as handle:
            info = json.load(handle)
    except (OSError, ValueError):
        return None
    return info if isinstance(info, dict) else None


def acquire(app_home, meta=None):
    """Become the only server process for *app_home*.

    Returns ``(True, None)`` on success and ``(False, holder)`` when another
    live process already owns the data directory (``holder`` may be None when
    the owner could not record its metadata).
    """
    global _handle
    if _handle is not None:
        return False, read_holder(app_home)

    path = lock_path(app_home)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError:
        # Read-only or missing data directory: start without the guard rather
        # than refusing to boot; the bind() step still protects the port.
        return True, None

    try:
        _os_lock(fd)
    except OSError:
        try:
            os.close(fd)
        except OSError:
            pass
        return False, read_holder(app_home)

    _handle = fd
    _write_owner(app_home, meta)
    return True, None


def release():
    """Release the lock (also happens automatically when the process exits)."""
    global _handle
    if _handle is None:
        return
    fd, _handle = _handle, None
    try:
        _os_unlock(fd)
    except OSError:
        pass
    try:
        os.close(fd)
    except OSError:
        pass


def update_meta(app_home, meta):
    """Rewrite the owner metadata while holding the lock (after config load)."""
    if _handle is None:
        return False
    return _write_owner(app_home, meta)
