import os
import tempfile
from unittest.mock import patch

from router import handle_delete_record


class DummyHandler:
    def __init__(self):
        self.cfg = {}
        self.session = {"id": 99, "name": "Admin", "email": "admin@test.local", "role": "admin"}
        self.status = None
        self.response = None

    def _get_session_or_401(self):
        return self.session

    def _send_json(self, status, payload):
        self.status = status
        self.response = payload


class TestRecordDeleteReconciliation:
    def _run_delete(self, root, delete_side_effect=None, vector_side_effect=None, audit_result=True):
        record_id = 998811
        record_dir = os.path.join(root, str(record_id))
        os.makedirs(record_dir)
        attachment = os.path.join(record_dir, "evidence.txt")
        with open(attachment, "w", encoding="utf-8") as output:
            output.write("record attachment")
        handler = DummyHandler()
        record = {"id": record_id, "title": "test record", "card_code": "REC-998811"}

        with (
            patch("router.ATTACH_DIR", root),
            patch("services.license_manager.is_system_read_only", return_value=False),
            patch("router.find_record_by_key_or_code", return_value=record),
            patch("services.auth.can_delete_record", return_value=True),
            patch("router.delete_record", side_effect=delete_side_effect),
            patch("router.delete_vector_document", side_effect=vector_side_effect),
            patch("services.audit_logger.log_audit", return_value=audit_result),
            patch("services.activity_store.append_activity"),
            patch("router.access_log"),
            patch("router.log_line"),
            patch("services.vector_store.trigger_async_vector_sync") as trigger_sync,
        ):
            handle_delete_record(handler, b'{"id":"REC-998811"}', "127.0.0.1")

        return handler, record_dir, attachment, trigger_sync

    def test_database_failure_restores_quarantined_attachment_directory(self):
        with tempfile.TemporaryDirectory() as root:
            handler, record_dir, attachment, _ = self._run_delete(
                root, delete_side_effect=RuntimeError("database unavailable")
            )
            assert handler.status == 500
            assert os.path.isfile(attachment)
            with open(attachment, encoding="utf-8") as source:
                assert source.read() == "record attachment"

    def test_vector_delete_failure_requests_full_sync_and_reports_pending_cleanup(self):
        with tempfile.TemporaryDirectory() as root:
            handler, record_dir, attachment, trigger_sync = self._run_delete(
                root, vector_side_effect=RuntimeError("vector db unavailable")
            )
            assert handler.status == 200
            assert handler.response["ok"] is True
            assert handler.response["cleanupPending"] is True
            assert not os.path.exists(record_dir)
            trigger_sync.assert_called_once()

    def test_audit_persistence_failure_is_not_reported_as_fully_clean(self):
        with tempfile.TemporaryDirectory() as root:
            handler, _, _, _ = self._run_delete(root, audit_result=False)
            assert handler.status == 200
            assert handler.response["cleanupPending"] is True
