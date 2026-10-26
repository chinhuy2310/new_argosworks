"""
tests/test_postgres_backup_restore.py — PostgreSQL Backup & Restore Drill Test Suite.

Verifies end-to-end backup and restore mechanics for PostgreSQL mode:
  1. Correct invocation of `pg_dump -Fc` and packaging into .tar.gz archive.
  2. Extraction of .dump from .tar.gz and correct invocation of `pg_restore --clean --if-exists`.
  3. Pre-restore safety backup creation for PostgreSQL.
  4. Pool connection reset via db.close_connection() before restore.
  5. Actionable FileNotFoundError handling when postgresql-client is missing.
"""
import os
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch, MagicMock

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_DIR = os.path.join(BASE_DIR, "server")
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from services import backup_manager
import db


class TestPostgresBackupRestore(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.backup_dir = os.path.join(self.td, "backups")
        self.attach_dir = os.path.join(self.td, "attachments")
        os.makedirs(self.backup_dir, exist_ok=True)
        os.makedirs(self.attach_dir, exist_ok=True)

        self.db_url = "postgresql://argos_admin:secret123@postgres:5432/argos_works"

        # Patch environment and backup_manager attributes
        self.env_patch = patch.dict(os.environ, {
            "BACKUP_DIR": self.backup_dir,
            "DATABASE_URL": self.db_url
        })
        self.env_patch.start()

        self.bdir_patch = patch.object(backup_manager, "ATTACH_DIR", self.attach_dir)
        self.bdir_patch.start()

        self.engine_patch = patch.object(backup_manager, "ENGINE", "postgres")
        self.engine_patch.start()

        self.dburl_patch = patch.object(backup_manager, "DATABASE_URL", self.db_url)
        self.dburl_patch.start()

    def tearDown(self):
        self.dburl_patch.stop()
        self.engine_patch.stop()
        self.bdir_patch.stop()
        self.env_patch.stop()
        import shutil
        shutil.rmtree(self.td, ignore_errors=True)

    def test_pg_dump_called_with_correct_args_and_packaged(self):
        """create_backup in postgres mode must invoke pg_dump -Fc and package into tar.gz."""
        def fake_pg_dump(cmd, **kwargs):
            # cmd: ["pg_dump", "-Fc", "-d", DATABASE_URL, "-f", temp_db_path]
            out_file = cmd[cmd.index("-f") + 1]
            with open(out_file, "wb") as f:
                f.write(b"PG_CUSTOM_DUMP_FORMAT_MAGIC_HEADER_V16")
            res = MagicMock()
            res.returncode = 0
            res.stdout = ""
            res.stderr = ""
            return res

        with patch("subprocess.run", side_effect=fake_pg_dump) as mock_run:
            result = backup_manager.create_backup(note="Postgres Drill", backup_type="manual")

            self.assertTrue(result["ok"])
            filename = result["filename"]
            self.assertTrue(filename.endswith(".tar.gz"))
            archive_path = os.path.join(self.backup_dir, filename)
            self.assertTrue(os.path.exists(archive_path))

            # Verify subprocess call args
            mock_run.assert_called_once()
            called_cmd = mock_run.call_args[0][0]
            self.assertEqual(called_cmd[0], "pg_dump")
            self.assertEqual(called_cmd[1], "-Fc")
            self.assertEqual(called_cmd[2], "-d")
            self.assertEqual(called_cmd[3], self.db_url)
            self.assertEqual(called_cmd[4], "-f")

            # Verify contents of tar.gz
            with tarfile.open(archive_path, "r:gz") as tar:
                names = tar.getnames()
                self.assertIn("argos.dump", names)
                self.assertIn("backup_manifest.json", names)

    def test_pg_restore_called_with_clean_and_if_exists(self):
        """restore_backup in postgres mode must invoke pg_restore --clean --if-exists."""
        # 1. Create a dummy backup archive containing argos.dump
        archive_name = "test_pg_backup.tar.gz"
        archive_path = os.path.join(self.backup_dir, archive_name)
        dump_content = b"PG_CUSTOM_DUMP_DATA_FOR_RESTORE"

        temp_dump = os.path.join(self.td, "argos.dump")
        with open(temp_dump, "wb") as f:
            f.write(dump_content)

        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(temp_dump, arcname="argos.dump")

        # 2. Mock subprocess.run for safety pg_dump and pg_restore
        called_commands = []
        def fake_run(cmd, **kwargs):
            called_commands.append(cmd)
            res = MagicMock()
            res.returncode = 0
            res.stdout = ""
            res.stderr = ""
            return res

        with patch("subprocess.run", side_effect=fake_run), \
             patch("services.backup_manager.close_connection") as mock_close:
            res = backup_manager.restore_backup(archive_name)
            self.assertTrue(res.get("ok"), res)

            # close_connection must be called to reset pool
            mock_close.assert_called_once()

            # Must have called pg_dump for safety snapshot, then pg_restore
            self.assertGreaterEqual(len(called_commands), 2)

            restore_cmd = called_commands[-1]
            self.assertEqual(restore_cmd[0], "pg_restore")
            self.assertIn("--clean", restore_cmd)
            self.assertIn("--if-exists", restore_cmd)
            self.assertIn("-d", restore_cmd)
            self.assertIn(self.db_url, restore_cmd)

    def test_missing_pg_dump_raises_clear_error(self):
        """When pg_dump binary is missing, raise FileNotFoundError with actionable advice."""
        with patch("subprocess.run", side_effect=FileNotFoundError("pg_dump not found")):
            with self.assertRaises(FileNotFoundError) as ctx:
                backup_manager.create_backup(note="Missing Tool", backup_type="manual")
            self.assertIn("postgresql-client", str(ctx.exception))

    def test_missing_pg_restore_raises_clear_error(self):
        """When pg_restore binary is missing, raise FileNotFoundError with actionable advice."""
        archive_name = "test_pg_missing.tar.gz"
        archive_path = os.path.join(self.backup_dir, archive_name)
        temp_dump = os.path.join(self.td, "argos.dump")
        with open(temp_dump, "wb") as f:
            f.write(b"DUMP")

        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(temp_dump, arcname="argos.dump")

        def fake_run(cmd, **kwargs):
            if cmd[0] == "pg_dump":
                res = MagicMock()
                res.returncode = 0
                return res
            raise FileNotFoundError("pg_restore not found")

        with patch("subprocess.run", side_effect=fake_run):
            with self.assertRaises(FileNotFoundError) as ctx:
                backup_manager.restore_backup(archive_name)
            self.assertIn("postgresql-client", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
