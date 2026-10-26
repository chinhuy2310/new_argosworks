"""
test_backup_restore.py — Backup → data loss → restore round-trip.

Selling an on-prem product means proving that a restore really brings the
customer's data back (not just that a .tar.gz file was created).
"""
import os
import sys
import threading

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_DIR = os.path.join(BASE_DIR, "server")
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

os.environ.setdefault("ARGOS_MASTER_KEY", "test-master-key-for-unit-tests-2026")
os.environ.setdefault("ARGOS_PBKDF2_ROUNDS", "2000")


@pytest.fixture
def isolated_backup_env(tmp_path, monkeypatch):
    """Point the DB, attachment dir and backup dir to a throw-away location."""
    import db as db_module
    from services import backup_manager

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    attach_dir = data_dir / "attachments"
    attach_dir.mkdir()
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    db_path = str(data_dir / "argos.db")

    monkeypatch.setattr(db_module, "get_db_path", lambda: db_path, raising=False)
    monkeypatch.setattr(backup_manager, "get_db_path", lambda: db_path, raising=False)
    monkeypatch.setattr(backup_manager, "ATTACH_DIR", str(attach_dir), raising=False)
    monkeypatch.setenv("BACKUP_DIR", str(backup_dir))

    if hasattr(db_module, "_tls"):
        db_module._tls = threading.local()

    db_module.init_db()

    yield {"db_path": db_path, "backup_dir": str(backup_dir), "attach_dir": str(attach_dir)}


def _insert_marker(db_module, record_id):
    db_module.execute(
        """INSERT OR REPLACE INTO records (id, dept_id, category, title, assignee_name, status)
           VALUES (?, 'dev', '개발', 'BACKUP_RESTORE_MARKER', 'Tester', '진행')""",
        (record_id,)
    )


def _marker_exists(db_module, record_id):
    return db_module.get_one("SELECT id, title FROM records WHERE id = ?", (record_id,)) is not None


class TestBackupRestoreRoundTrip:
    def test_backup_then_restore_brings_data_back(self, isolated_backup_env):
        import db as db_module
        from services import backup_manager

        marker_id = 990001
        _insert_marker(db_module, marker_id)
        assert _marker_exists(db_module, marker_id)

        result = backup_manager.create_backup(note="pytest round-trip", backup_type="manual")
        assert result["ok"] is True
        assert result["filename"].endswith(".tar.gz")
        assert os.path.exists(os.path.join(isolated_backup_env["backup_dir"], result["filename"]))
        assert result["raw_size"] > 0

        # Simulate customer data loss
        db_module.execute("DELETE FROM records WHERE id = ?", (marker_id,))
        assert not _marker_exists(db_module, marker_id)

        # Restore from the archive
        restore_res = backup_manager.restore_backup(result["filename"])
        assert restore_res.get("ok") is True, restore_res
        assert restore_res.get("safety_backup")

        # A restore replaces the DB file; make sure we read through a fresh connection.
        if hasattr(db_module, "_tls"):
            db_module._tls = threading.local()

        assert _marker_exists(db_module, marker_id), "restored database must contain the row again"

    def test_restore_creates_safety_snapshot(self, isolated_backup_env):
        import db as db_module
        from services import backup_manager

        _insert_marker(db_module, 990002)
        result = backup_manager.create_backup(note="snapshot test", backup_type="manual")
        restore_res = backup_manager.restore_backup(result["filename"])
        assert restore_res.get("ok") is True, restore_res

        files = os.listdir(isolated_backup_env["backup_dir"])
        assert any(name.startswith("argos_safety_before_restore_") for name in files), \
            "restore must never run without a pre-restore safety backup"

    def test_backup_of_missing_database_fails_loudly(self, isolated_backup_env):
        from services import backup_manager

        os.remove(isolated_backup_env["db_path"])
        with pytest.raises(FileNotFoundError):
            backup_manager.create_backup(note="no db", backup_type="manual")
