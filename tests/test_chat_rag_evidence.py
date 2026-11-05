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
        with patch(
            "services.search.merged_records", return_value=([], None)
        ), patch(
            "services.auth.visible_records", side_effect=lambda _session, records: records
        ), patch(
            "services.search.search_records", return_value=[]
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


    @patch("services.vector_store.is_voyage_configured", return_value=True)
    @patch(
        "services.vector_store.search_vector_store",
        return_value=[
            {
                "source_id": "DOC-OTHER",
                "title": "Unrelated guide",
                "doc_type": "document",
                "summary": "General maintenance",
                "evidence": "Routine maintenance instructions",
                "similarity": 0.82,
            },
            {
                "source_id": "DOC-GFC",
                "title": "GFC connection",
                "doc_type": "document",
                "summary": "GFC connection steps",
                "evidence": "Connect the GFC controller using the required interface",
                "similarity": 0.58,
            },
        ],
    )
    def test_keyword_candidates_are_merged_and_reranked(
        self, _search_vector_store, _is_voyage_configured
    ):
        with patch(
            "services.search.merged_records",
            return_value=([{"id": 1, "title": "GFC connection wiring", "summary": "GFC connection wiring steps"}], None),
        ), patch(
            "services.auth.visible_records",
            side_effect=lambda _session, records: records,
        ), patch(
            "services.search.search_records",
            return_value=[{
                "id": 1,
                "cardCode": "REC-1",
                "title": "GFC connection",
                "summary": "GFC connection wiring steps",
            }],
        ):
            result = _tool_search_documents(
                {"query": "GFC connection", "limit": 3},
                {"name": "test-user"},
                {},
            )

        self.assertEqual(result["found_count"], 3)
        self.assertEqual(result["documents"][0]["source_id"], "REC-1")
        self.assertEqual(result["documents"][0]["similarity"], None)
        self.assertIn("GFC connection", result["documents"][0]["evidence"])


if __name__ == "__main__":
    unittest.main()
