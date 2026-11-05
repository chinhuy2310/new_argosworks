# -*- coding: utf-8 -*-
import unittest
from unittest.mock import patch

from services.chat_tools import _tool_search_documents


class TestChatDocumentEvidence(unittest.TestCase):
    @patch("services.vector_store.is_voyage_configured", return_value=True)
    @patch(
        "services.vector_store.search_vector_store",
        return_value=[{
            "doc_id": "DOC-001",
            "source_id": "DOC-001",
            "id": "DOC-001",
            "title": "GFC Technical Specification",
            "doc_type": "document",
            "summary": "Short summary",
            "evidence": "Original source paragraph with the relevant requirement.",
            "similarity": 0.93,
            "date": "2026-11-05",
        }],
    )
    def test_search_documents_preserves_source_and_evidence(
        self, _search_vector_store, _is_voyage_configured
    ):
        result = _tool_search_documents(
            {"query": "GFC connection requirement", "limit": 1},
            {"name": "test-user"},
            {},
        )
        self.assertEqual(result["found_count"], 1)
        document = result["documents"][0]
        self.assertEqual(document["source_id"], "DOC-001")
        self.assertIn("Original source paragraph", document["evidence"])
        self.assertEqual(document["summary"], "Short summary")


if __name__ == "__main__":
    unittest.main()
