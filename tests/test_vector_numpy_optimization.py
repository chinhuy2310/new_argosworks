# -*- coding: utf-8 -*-
"""Unit tests for NumPy C-BLAS vectorized similarity search and graceful fallback in vector_store.py."""

import json
import sqlite3
import pytest

np = pytest.importorskip("numpy")

from services import vector_store


def _dummy_cfg():
    return {
        "voyage": {
            "enabled": True,
            "provider": "voyage",
            "api_key": "dummy_key",
            "model": "voyage-3-lite"
        }
    }


def _seed_test_db(db_path, dim, num_docs=20):
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS document_embeddings (
            doc_id TEXT PRIMARY KEY,
            doc_type TEXT NOT NULL,
            title TEXT,
            content TEXT,
            content_hash TEXT NOT NULL,
            vector_blob BLOB NOT NULL,
            dim INTEGER NOT NULL,
            metadata_json TEXT,
            updated_at TEXT NOT NULL,
            embedding_model TEXT
        );
    """)

    np.random.seed(42)
    vectors = []
    for i in range(num_docs):
        # Generate random normalized float vector
        vec = np.random.randn(dim).astype(np.float32)
        vec /= np.linalg.norm(vec)
        vectors.append(vec)
        blob = vec.tobytes()

        meta = {
            "id": f"doc_{i}",
            "summary": f"Summary of document {i}",
            "is_private": 1 if i == 0 else 0,
        }
        if i == 5:
            meta["price"] = "1,000,000 VND"

        conn.execute("""
            INSERT INTO document_embeddings (
                doc_id, doc_type, title, content, content_hash, vector_blob, dim, metadata_json, updated_at, embedding_model
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '2026-11-06T00:00:00', 'voyage-3-lite')
        """, (
            f"doc_{i}",
            "product" if i == 5 else "jira",
            f"Title {i}",
            f"Full text content for document {i} with price details: 1,000,000 VND",
            f"hash_{i}",
            blob,
            dim,
            json.dumps(meta)
        ))
    conn.commit()
    conn.close()
    return vectors


class TestVectorNumPyOptimization:

    def test_numpy_similarity_matches_expected_ordering(self, tmp_path, monkeypatch):
        dim = 128
        db_file = str(tmp_path / "vec_test1.db")
        vectors = _seed_test_db(db_file, dim, num_docs=10)

        # Query vector is very close to doc_3
        target_vec = (vectors[3] + 0.01 * np.random.randn(dim)).astype(np.float32)
        target_vec /= np.linalg.norm(target_vec)

        def make_conn():
            c = sqlite3.connect(db_file)
            c.row_factory = sqlite3.Row
            return c

        monkeypatch.setattr(vector_store, "get_db_connection", make_conn)
        monkeypatch.setattr(vector_store, "init_vector_db", lambda: None)
        monkeypatch.setattr(vector_store, "is_voyage_configured", lambda cfg: True)
        monkeypatch.setattr(vector_store, "embed_query", lambda cfg, q: target_vec.tolist())
        monkeypatch.setattr("services.vector_store.can_view_vector_doc", lambda s, dt, m, ctx: True)

        session = {"id": 1, "username": "admin", "role": "admin"}
        results = vector_store.search_vector_store(_dummy_cfg(), "test query", limit=5, min_similarity=0.3, session=session)

        assert len(results) > 0
        # The top result must be doc_3 with similarity close to 1.0
        assert results[0]["doc_id"] == "doc_3"
        assert results[0]["similarity"] > 0.95
        # Results must be in strictly descending order
        for i in range(len(results) - 1):
            assert results[i]["similarity"] >= results[i+1]["similarity"]

    def test_numpy_fallback_to_python_loop_produces_identical_results(self, tmp_path, monkeypatch):
        dim = 64
        db_file = str(tmp_path / "vec_test2.db")
        vectors = _seed_test_db(db_file, dim, num_docs=15)

        query_vec = vectors[2].tolist()

        def make_conn():
            c = sqlite3.connect(db_file)
            c.row_factory = sqlite3.Row
            return c

        monkeypatch.setattr(vector_store, "get_db_connection", make_conn)
        monkeypatch.setattr(vector_store, "init_vector_db", lambda: None)
        monkeypatch.setattr(vector_store, "is_voyage_configured", lambda cfg: True)
        monkeypatch.setattr(vector_store, "embed_query", lambda cfg, q: query_vec)
        monkeypatch.setattr("services.vector_store.can_view_vector_doc", lambda s, dt, m, ctx: True)

        session = {"id": 1, "username": "admin", "role": "admin"}

        # 1. Normal NumPy run
        res_numpy = vector_store.search_vector_store(_dummy_cfg(), "query", limit=5, min_similarity=0.2, session=session)

        # 2. Force fallback by mocking np.dot to raise RuntimeError
        real_dot = np.dot
        def broken_dot(*args, **kwargs):
            raise RuntimeError("Simulated NumPy acceleration failure")
        monkeypatch.setattr(np, "dot", broken_dot)

        res_fallback = vector_store.search_vector_store(_dummy_cfg(), "query", limit=5, min_similarity=0.2, session=session)

        # Both must return identical documents in identical order
        assert len(res_numpy) == len(res_fallback)
        assert len(res_numpy) > 0
        for r_np, r_fb in zip(res_numpy, res_fallback):
            assert r_np["doc_id"] == r_fb["doc_id"]
            assert abs(r_np["similarity"] - r_fb["similarity"]) < 1e-4

    def test_numpy_privacy_isolation_and_price_masking(self, tmp_path, monkeypatch):
        dim = 64
        db_file = str(tmp_path / "vec_test3.db")
        vectors = _seed_test_db(db_file, dim, num_docs=10)

        # Make query identical to doc_0 (which is marked is_private: 1)
        query_vec = vectors[0].tolist()

        def make_conn():
            c = sqlite3.connect(db_file)
            c.row_factory = sqlite3.Row
            return c

        monkeypatch.setattr(vector_store, "get_db_connection", make_conn)
        monkeypatch.setattr(vector_store, "init_vector_db", lambda: None)
        monkeypatch.setattr(vector_store, "is_voyage_configured", lambda cfg: True)
        monkeypatch.setattr(vector_store, "embed_query", lambda cfg, q: query_vec)

        # Non-admin user without permission to view private records
        user_session = {"id": 99, "username": "regular_user", "role": "user", "dept_id": "other"}
        monkeypatch.setattr("services.vector_store.can_view_vector_doc", lambda s, dt, meta, ctx: not bool(meta.get("is_private")))
        monkeypatch.setattr("services.vector_store.can_view_vector_price", lambda s, ctx: False)

        results = vector_store.search_vector_store(_dummy_cfg(), "secret", limit=5, min_similarity=0.1, session=user_session)

        # Private doc_0 must be filtered out!
        result_ids = [r["doc_id"] for r in results]
        assert "doc_0" not in result_ids

        # Product doc_5 price must be masked!
        prod_doc = next((r for r in results if r["doc_id"] == "doc_5"), None)
        if prod_doc:
            assert "***" in prod_doc["summary"] or "비공개" in prod_doc["summary"] or "VND" not in prod_doc["summary"]
