import sqlite3

from services import vector_store


def test_empty_complete_source_set_removes_stale_vectors_without_embedding_provider(tmp_path, monkeypatch):
    db_path = tmp_path / "vectors.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE document_embeddings (doc_id TEXT PRIMARY KEY, content_hash TEXT, embedding_model TEXT)"
    )
    conn.execute(
        "INSERT INTO document_embeddings(doc_id, content_hash, embedding_model) VALUES (?, ?, ?)",
        ("record:123", "old-hash", "voyage-3-lite"),
    )
    conn.commit()
    conn.close()

    def connect():
        db = sqlite3.connect(str(db_path))
        db.row_factory = sqlite3.Row
        return db

    monkeypatch.setattr(vector_store, "is_voyage_configured", lambda cfg: False)
    monkeypatch.setattr(vector_store, "_collect_all_documents", lambda cfg, strict=False: [])
    monkeypatch.setattr(vector_store, "init_vector_db", lambda: None)
    monkeypatch.setattr(vector_store, "get_db_connection", connect)

    result = vector_store.sync_all_vectors({})

    check = connect()
    try:
        remaining = check.execute("SELECT doc_id FROM document_embeddings").fetchall()
    finally:
        check.close()

    assert result["reason"] == "voyage_not_configured"
    assert result["cleaned"] == 1
    assert remaining == []


def test_incomplete_source_collection_aborts_before_vector_cleanup(monkeypatch):
    called = {"db": False}

    def fail_collection(cfg, strict=False):
        assert strict is True
        raise RuntimeError("source unavailable")

    def unexpected_db():
        called["db"] = True
        raise AssertionError("vector DB must not be opened after incomplete source collection")

    monkeypatch.setattr(vector_store, "is_voyage_configured", lambda cfg: True)
    monkeypatch.setattr(vector_store, "_collect_all_documents", fail_collection)
    monkeypatch.setattr(vector_store, "init_vector_db", lambda: None)
    monkeypatch.setattr(vector_store, "get_db_connection", unexpected_db)

    try:
        vector_store.sync_all_vectors({})
    except RuntimeError as exc:
        assert "source unavailable" in str(exc)
    else:
        raise AssertionError("incomplete source collection must abort")
    assert called["db"] is False
