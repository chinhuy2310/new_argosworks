import unittest
from unittest.mock import patch, MagicMock
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_DIR = os.path.join(BASE_DIR, "server")
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from services import vector_store


class TestVectorProviderIdentity(unittest.TestCase):
    def test_get_embedding_identity_cloud_providers(self):
        cfg_voyage = {"voyage": {"provider": "voyage", "model": "voyage-3-lite"}}
        self.assertEqual(vector_store.get_embedding_identity(cfg_voyage), "voyage:voyage-3-lite")

        cfg_openai = {"voyage": {"provider": "openai", "model": "text-embedding-3-small"}}
        self.assertEqual(vector_store.get_embedding_identity(cfg_openai), "openai:text-embedding-3-small")

        cfg_gemini = {"voyage": {"provider": "gemini", "model": "gemini-embedding-001"}}
        self.assertEqual(vector_store.get_embedding_identity(cfg_gemini), "gemini:gemini-embedding-001")

    def test_get_embedding_identity_custom_and_ollama_endpoints(self):
        cfg_ollama = {
            "voyage": {
                "provider": "ollama",
                "model": "nomic-embed-text",
                "base_url": "http://localhost:11434"
            }
        }
        id_ollama = vector_store.get_embedding_identity(cfg_ollama)
        self.assertTrue(id_ollama.startswith("ollama:nomic-embed-text@"))

        # Custom provider with same model name but different base_url
        cfg_custom = {
            "voyage": {
                "provider": "custom",
                "model": "nomic-embed-text",
                "base_url": "http://192.168.1.100:8000/v1"
            }
        }
        id_custom = vector_store.get_embedding_identity(cfg_custom)
        self.assertTrue(id_custom.startswith("custom:nomic-embed-text@"))
        self.assertNotEqual(id_ollama, id_custom, "Ollama and Custom must produce different embedding identities!")

        # Changing base_url on custom changes identity
        cfg_custom2 = {
            "voyage": {
                "provider": "custom",
                "model": "nomic-embed-text",
                "base_url": "http://192.168.1.200:8000/v1"
            }
        }
        self.assertNotEqual(id_custom, vector_store.get_embedding_identity(cfg_custom2))

    def test_check_sync_detects_provider_change_with_identical_model(self):
        """Audit Evidence 3: Ollama -> Custom with same nomic-embed-text must trigger re-index warning."""
        cfg_custom = {
            "voyage": {
                "provider": "custom",
                "model": "nomic-embed-text",
                "base_url": "http://192.168.1.100:8000/v1",
                "api_key": "custom_key"
            }
        }
        fake_docs = [{"doc_id": "doc_1", "content": "Hello World"}]

        # Existing DB has embeddings saved with Ollama identity
        existing_rows = [{
            "doc_id": "doc_1",
            "content_hash": "a591a6d40bf420404a011733cfb7b190d62c65bf0bcda32b57b277d9ad9f146e",
            "embedding_model": "ollama:nomic-embed-text@11434"
        }]

        with patch("services.vector_store.is_voyage_configured", return_value=True), \
             patch("services.vector_store.init_vector_db"), \
             patch("services.vector_store._collect_all_documents", return_value=fake_docs), \
             patch("services.vector_store.get_db_connection") as mock_conn:

            mock_c = MagicMock()
            mock_conn.return_value = mock_c
            mock_c.execute.return_value = existing_rows

            status = vector_store.check_vector_sync_status(cfg_custom)

            self.assertTrue(status.get("ok"))
            self.assertEqual(status.get("diff_model"), 1, "Must detect model/provider mismatch!")
            self.assertFalse(status.get("is_fully_synced"), "Must not conclude is_fully_synced=True!")
            self.assertTrue(status.get("needs_model_migration_warning"))

    def test_backward_compatibility_legacy_voyage_records(self):
        """Legacy records without prefix (e.g. 'voyage-3-lite') match when provider is voyage."""
        cfg_voyage = {"voyage": {"provider": "voyage", "model": "voyage-3-lite", "api_key": "k"}}
        fake_docs = [{"doc_id": "doc_1", "content": "Hello World"}]

        existing_rows = [{
            "doc_id": "doc_1",
            "content_hash": "a591a6d40bf420404a011733cfb7b190d62c65bf0bcda32b57b277d9ad9f146e",
            "embedding_model": "voyage-3-lite"  # Legacy format
        }]

        with patch("services.vector_store.is_voyage_configured", return_value=True), \
             patch("services.vector_store.init_vector_db"), \
             patch("services.vector_store._collect_all_documents", return_value=fake_docs), \
             patch("services.vector_store.get_db_connection") as mock_conn:

            mock_c = MagicMock()
            mock_conn.return_value = mock_c
            mock_c.execute.return_value = existing_rows

            status = vector_store.check_vector_sync_status(cfg_voyage)

            self.assertTrue(status.get("ok"))
            self.assertEqual(status.get("diff_model"), 0, "Legacy voyage-3-lite must match voyage provider!")
            self.assertTrue(status.get("is_fully_synced"))


if __name__ == "__main__":
    unittest.main()
