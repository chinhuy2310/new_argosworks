import os
import tempfile
import unittest
from unittest.mock import patch

from handlers import product_handlers


class DummyHandler:
    def __init__(self):
        self.status = None
        self.response = None
        self.session = {"id": 10, "role": "manager", "dept_id": "dev"}

    def _get_session_or_401(self):
        return self.session

    def _send_json(self, status, data):
        self.status = status
        self.response = data


class TestPimAttachmentDeleteSafety(unittest.TestCase):
    def _run_delete(self, root, write_side_effect=None):
        product_id = "P-test-attachment"
        filename = "manual.txt"
        product_dir = os.path.join(root, product_id)
        os.makedirs(product_dir, exist_ok=True)
        file_path = os.path.join(product_dir, filename)
        with open(file_path, "w", encoding="utf-8") as output:
            output.write("keep me if metadata save fails")

        product = {
            "id": product_id,
            "attachments": [{"name": filename, "size": 29}],
        }
        handler = DummyHandler()
        with (
            patch.object(product_handlers, "PRODUCT_ATTACH_DIR", root),
            patch.object(product_handlers, "read_products", return_value=[product]),
            patch.object(product_handlers, "write_products", side_effect=write_side_effect) as save,
            patch("services.license_manager.is_system_read_only", return_value=False),
            patch("services.auth.can_modify_pim", return_value=True),
        ):
            product_handlers.handle_product_attachment_delete(
                handler,
                b'{"id":"P-test-attachment","name":"manual.txt"}',
                "127.0.0.1",
            )
        return handler, file_path, product, save

    def test_file_is_removed_after_metadata_save(self):
        with tempfile.TemporaryDirectory() as root:
            handler, file_path, product, save = self._run_delete(root)
            self.assertEqual(handler.status, 200)
            self.assertFalse(os.path.exists(file_path))
            self.assertEqual(product["attachments"], [])
            save.assert_called_once()

    def test_file_is_restored_when_metadata_save_fails(self):
        with tempfile.TemporaryDirectory() as root:
            handler, file_path, product, save = self._run_delete(
                root, write_side_effect=RuntimeError("database unavailable")
            )
            self.assertEqual(handler.status, 500)
            self.assertTrue(os.path.isfile(file_path))
            with open(file_path, encoding="utf-8") as source:
                self.assertEqual(source.read(), "keep me if metadata save fails")
            self.assertEqual(product["attachments"], [])
            save.assert_called_once()


if __name__ == "__main__":
    unittest.main()
