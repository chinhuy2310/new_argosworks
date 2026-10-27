import io
import unittest
import json
from services.data_store import read_product_categories, get_used_spec_keys, execute, query
from handlers.product_handlers import handle_product_category_save, handle_get_product_categories_admin

class DummyHandler:
    def __init__(self, is_admin=True):
        self.session = {"account_key": "admin_key", "role": "admin"} if is_admin else {"account_key": "mem_key", "role": "member"}
        self.status = None
        self.response = None
        self.headers = {}
        self.sent_headers = {}
        self.wfile = io.BytesIO()

    def _get_session_or_401(self):
        return self.session
    
    def _send_json(self, status, data):
        self.status = status
        self.response = data

class TestProductSpecKeySafety(unittest.TestCase):
    def test_used_spec_keys_and_lock_deletion(self):
        # 1. Create a test category
        cat_id = "cat_test_lock_01"
        cat_name = "TestCategorySafety"
        tpl = [
            {"group": "사양", "label": "해상도", "key": "res_key"},
            {"group": "사양", "label": "배터리", "key": "bat_key"}
        ]
        
        adm_h = DummyHandler(is_admin=True)
        handle_product_category_save(adm_h, json.dumps({
            "id": cat_id,
            "name": cat_name,
            "spec_template": tpl
        }).encode("utf-8"), "127.0.0.1")
        self.assertEqual(adm_h.status, 200)

        # 2. Insert a product that uses 'res_key'
        prod_id = "prod_safety_test_01"
        execute("DELETE FROM products WHERE id = ?", (prod_id,))
        iso_now = "2026-10-27T00:00:00"
        execute(
            """INSERT INTO products(id, model, display_name, category, specs, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (prod_id, "TEST-MODEL", "Test Model", cat_name, json.dumps({"res_key": "4K Ultra HD"}), iso_now, iso_now)
        )

        # 3. get_used_spec_keys should identify 'res_key' as used, but not 'bat_key'
        used = get_used_spec_keys(cat_name)
        self.assertIn("res_key", used)
        self.assertNotIn("bat_key", used)

        # 4. handle_get_product_categories_admin should include used_keys
        get_h = DummyHandler(is_admin=True)
        handle_get_product_categories_admin(get_h, None, "127.0.0.1")
        self.assertEqual(get_h.status, 200)
        found = next((c for c in get_h.response["categories"] if c["id"] == cat_id), None)
        self.assertIsNotNone(found)
        self.assertIn("res_key", found.get("used_keys", []))

        # 5. Attempting to save without 'res_key' should be BLOCKED with 400
        bad_save_h = DummyHandler(is_admin=True)
        handle_product_category_save(bad_save_h, json.dumps({
            "id": cat_id,
            "name": cat_name,
            "spec_template": [
                {"group": "사양", "label": "배터리", "key": "bat_key"}  # res_key is deleted
            ]
        }).encode("utf-8"), "127.0.0.1")
        self.assertEqual(bad_save_h.status, 400)
        self.assertIn("res_key", bad_save_h.response["error"])

        # 6. Deleting unused 'bat_key' should be ALLOWED
        good_save_h = DummyHandler(is_admin=True)
        handle_product_category_save(good_save_h, json.dumps({
            "id": cat_id,
            "name": cat_name,
            "spec_template": [
                {"group": "사양", "label": "해상도", "key": "res_key"}  # bat_key is deleted, res_key kept
            ]
        }).encode("utf-8"), "127.0.0.1")
        self.assertEqual(good_save_h.status, 200)

        # Cleanup
        execute("DELETE FROM products WHERE id = ?", (prod_id,))
        execute("DELETE FROM product_categories WHERE id = ?", (cat_id,))

if __name__ == "__main__":
    unittest.main()
