import unittest
from unittest.mock import patch, MagicMock
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_DIR = os.path.join(BASE_DIR, "server")
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from services import vector_store


class TestVectorSyncIntegrity(unittest.TestCase):
    def setUp(self):
        # Reset locks & flags before each test
        if vector_store._sync_lock.locked():
            try:
                vector_store._sync_lock.release()
            except RuntimeError:
                pass
        with vector_store._sync_pending_lock:
            vector_store._sync_pending = False
            vector_store._worker_running = False

    def test_init_vector_db_error_does_not_leak_sync_lock(self):
        cfg = {"voyage": {"api_key": "fake_key", "model": "voyage-3-lite"}}

        with patch("services.vector_store.is_voyage_configured", return_value=True), \
             patch("services.vector_store.init_vector_db", side_effect=RuntimeError("Simulated disk error")):
            with self.assertRaises(RuntimeError):
                vector_store.sync_all_vectors(cfg)

        # Crucial check: _sync_lock MUST NOT remain locked!
        self.assertFalse(vector_store._sync_lock.locked(), "_sync_lock was leaked after init_vector_db exception!")

    def test_partial_embedding_failure_returns_ok_false(self):
        cfg = {"voyage": {"api_key": "fake_key", "model": "voyage-3-lite"}}
        fake_docs = [
            {"doc_id": "rec_1", "doc_type": "record", "title": "T1", "content": "Content 1", "metadata": {}},
            {"doc_id": "rec_2", "doc_type": "record", "title": "T2", "content": "Content 2 (Poison)", "metadata": {}}
        ]

        def fake_embed(cfg, texts, input_type="document"):
            # If batch has >1, fail to trigger single-item fallback
            if len(texts) > 1:
                return None
            # For single item: rec_1 succeeds, rec_2 fails
            if "Content 1" in texts[0]:
                return [[0.1] * 512]
            return None

        with patch("services.vector_store.is_voyage_configured", return_value=True), \
             patch("services.vector_store.init_vector_db"), \
             patch("services.vector_store._collect_all_documents", return_value=(fake_docs, set())), \
             patch("services.vector_store.call_voyage_embeddings", side_effect=fake_embed), \
             patch("services.vector_store.get_db_connection") as mock_conn:

            mock_c = MagicMock()
            mock_conn.return_value = mock_c
            mock_c.execute.return_value = []

            res = vector_store.sync_all_vectors(cfg, force=True)

            self.assertFalse(res.get("ok"), "API must return ok: False on partial embedding failure!")
            self.assertTrue(res.get("partial"))
            self.assertEqual(res.get("failed"), 1)
            self.assertIn("rec_2", res.get("failed_doc_ids", []))
            self.assertEqual(res.get("indexed"), 1)

    def test_sync_retrigger_when_pending_arrived_during_sync(self):
        cfg = {"voyage": {"api_key": "fake_key", "model": "voyage-3-lite"}}

        with patch("services.vector_store.is_voyage_configured", return_value=True), \
             patch("services.vector_store.init_vector_db"), \
             patch("services.vector_store._collect_all_documents", return_value=([], set())), \
             patch("services.vector_store.trigger_async_vector_sync") as mock_retrigger:

            # Simulate pending set during execution
            def side_effect(*args, **kwargs):
                with vector_store._sync_pending_lock:
                    vector_store._sync_pending = True
                return ([], set())

            with patch("services.vector_store._collect_all_documents", side_effect=side_effect):
                vector_store.sync_all_vectors(cfg)

            mock_retrigger.assert_called_once_with(cfg)


if __name__ == "__main__":
    unittest.main()
