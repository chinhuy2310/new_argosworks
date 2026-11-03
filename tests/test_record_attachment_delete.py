import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_DIR = os.path.join(BASE_DIR, "server")
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

import pytest


def _insert_attachment(db, record_id, filename):
    dept = db.query("SELECT id FROM departments LIMIT 1")
    assert dept, "test database should contain at least one department"
    db.execute(
        """INSERT INTO records(id, dept_id, category, title, assignee_name)
           VALUES (?, ?, 'Test', 'Attachment deletion test', 'Tester')""",
        (record_id, dept[0]["id"])
    )
    db.execute(
        "INSERT INTO record_attachments(record_id, filename) VALUES (?, ?)",
        (record_id, filename)
    )
    row = db.get_one(
        "SELECT id FROM record_attachments WHERE record_id = ? AND filename = ?",
        (record_id, filename)
    )
    return row["id"]


def test_delete_record_attachment_removes_metadata_and_file(tmp_db, tmp_path, monkeypatch):
    import config
    from services import data_store

    monkeypatch.setattr(config, "ATTACH_DIR", str(tmp_path))
    record_id = 991101
    filename = "proof.txt"
    attachment_id = _insert_attachment(tmp_db, record_id, filename)
    record_dir = tmp_path / str(record_id)
    record_dir.mkdir()
    file_path = record_dir / filename
    file_path.write_text("attachment", encoding="utf-8")

    ok, error = data_store.delete_record_attachment(record_id, attachment_id)

    assert ok is True
    assert error is None
    assert tmp_db.get_one(
        "SELECT id FROM record_attachments WHERE id = ?", (attachment_id,)
    ) is None
    assert not file_path.exists()
    assert list(record_dir.iterdir()) == []


def test_delete_record_attachment_restores_file_if_metadata_delete_fails(
    tmp_db, tmp_path, monkeypatch
):
    import config
    from services import data_store

    monkeypatch.setattr(config, "ATTACH_DIR", str(tmp_path))
    record_id = 991102
    filename = "keep.txt"
    attachment_id = _insert_attachment(tmp_db, record_id, filename)
    record_dir = tmp_path / str(record_id)
    record_dir.mkdir()
    file_path = record_dir / filename
    file_path.write_text("must survive", encoding="utf-8")

    def fail_delete(*args, **kwargs):
        raise RuntimeError("simulated database failure")

    monkeypatch.setattr(data_store, "execute", fail_delete)
    with pytest.raises(RuntimeError, match="simulated database failure"):
        data_store.delete_record_attachment(record_id, attachment_id)

    assert file_path.exists()
    assert file_path.read_text(encoding="utf-8") == "must survive"
    assert tmp_db.get_one(
        "SELECT id FROM record_attachments WHERE id = ?", (attachment_id,)
    ) is not None
    assert list(record_dir.iterdir()) == [file_path]
