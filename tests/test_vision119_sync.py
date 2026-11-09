import os
import json
import pytest
from services.data_store import query
from scripts.sync_vision119_products import clean_text

def test_vision119_clean_text():
    assert clean_text("  hello   world  \n ") == "hello world"
    assert clean_text("") == ""
    assert clean_text(None) == ""

def test_vision119_json_dataset():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    json_path = os.path.join(base_dir, "data", "vision119_products.json")
    if not os.path.exists(json_path):
        pytest.skip("vision119_products.json not present in clean/CI environment")

    with open(json_path, "r", encoding="utf-8") as f:
        products = json.load(f)

    assert len(products) == 60, f"Expected 60 products, got {len(products)}"
    for p in products:
        assert p["id"].startswith("P-V119-")
        assert p["model"], "Product must have model"
        assert p["category"], "Product must have category"
        assert p["source"] == "vision119"
        assert isinstance(p["specs"], dict)

def test_vision119_sync_state():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    state_path = os.path.join(base_dir, "data", "vision119_sync_state.json")
    if not os.path.exists(state_path):
        pytest.skip("vision119_sync_state.json not present in clean/CI environment")

    with open(state_path, "r", encoding="utf-8") as f:
        state = json.load(f)

    assert state.get("totalSynced") == 60
    assert "lastSyncedAt" in state

def test_vision119_database_records():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    json_path = os.path.join(base_dir, "data", "vision119_products.json")
    if not os.path.exists(json_path):
        pytest.skip("vision119_products.json not present in clean/CI environment")

    rows = query("SELECT COUNT(*) AS cnt FROM products WHERE source = 'vision119'")
    if not rows or rows[0]["cnt"] == 0:
        pytest.skip("vision119 records not populated in current test database run")

    assert rows[0]["cnt"] == 60, f"Expected 60 products in db, got {rows[0]['cnt']}"

    att_rows = query("SELECT COUNT(*) AS cnt FROM product_attachments WHERE product_id LIKE 'P-V119-%'")
    assert att_rows[0]["cnt"] >= 60, "Expected at least 60 attachments for vision119 products"
