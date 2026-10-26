import unittest
import os
import sys

# Ensure server module is in sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from services.chat_tools import (
    _tool_search_issues,
    _tool_get_active_tasks,
    _tool_get_child_issues,
    _tool_get_issue_details,
    _tool_search_products,
    _tool_get_product_details,
    execute_tool
)
from db import execute, query


class TestAiChatDataPermissions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Create test records in database
        execute("DELETE FROM records WHERE id >= 999900")
        # 1. Dept Dev: public record
        execute("""
            INSERT INTO records (id, card_code, title, summary, dept_id, category, assignee_name, is_private, status, work_date)
            VALUES (999901, 'DEV-901', 'Dev Public Task', 'Public task for dev', 'dev', '연구개발', 'park.sj', 0, '진행', '2026-10-23')
        """)
        # 2. Dept Dev: private record
        execute("""
            INSERT INTO records (id, card_code, title, summary, dept_id, category, assignee_name, is_private, status, work_date)
            VALUES (999902, 'DEV-902', 'Dev Secret Task', 'Secret confidential task', 'dev', '연구개발', 'lee.dh', 1, '진행', '2026-10-23')
        """)
        # 3. Dept Sales: private record
        execute("""
            INSERT INTO records (id, card_code, title, summary, dept_id, category, assignee_name, is_private, status, work_date)
            VALUES (999903, 'SALES-903', 'Sales Confidential Deal', 'High value secret deal', 'sales', '영업', 'kang.dw', 1, '진행', '2026-10-23')
        """)
        # 4. Dept Sales: public record
        execute("""
            INSERT INTO records (id, card_code, title, summary, dept_id, category, assignee_name, is_private, status, work_date)
            VALUES (999904, 'SALES-904', 'Sales Public Campaign', 'Open campaign', 'sales', '영업', 'kang.dw', 0, '진행', '2026-10-23')
        """)
        # 5. Child task of SALES-903 (private parent)
        execute("""
            INSERT INTO records (id, card_code, title, summary, dept_id, category, assignee_name, is_private, parent_key, status, work_date)
            VALUES (999905, 'SALES-905', 'Sales Child Subtask', 'Subtask under secret deal', 'sales', '영업', 'kang.dw', 1, 'SALES-903', '진행', '2026-10-23')
        """)

    @classmethod
    def tearDownClass(cls):
        execute("DELETE FROM records WHERE id >= 999900")

    def setUp(self):
        self.cfg = {"jira": {"enabled": False}}

        self.user_admin = {
            "id": 1,
            "username": "admin",
            "name": "Admin User",
            "org": "mgmt",
            "dept_id": "mgmt",
            "role": "admin",
            "is_admin": 1
        }
        self.user_dev_manager = {
            "id": 9002,
            "username": "manager_dev",
            "name": "개발팀장",
            "org": "dev",
            "dept_id": "dev",
            "role": "manager",
            "is_admin": 0
        }
        self.user_dev_member = {
            "id": 3,
            "username": "park.sj",
            "name": "박승재",
            "org": "dev",
            "dept_id": "dev",
            "role": "member",
            "is_admin": 0
        }
        self.user_sales_member = {
            "id": 6,
            "username": "kang.dw",
            "name": "강동원",
            "org": "sales",
            "dept_id": "sales",
            "role": "member",
            "is_admin": 0
        }

    def test_search_issues_rbac_isolation(self):
        """AI tool search_issues must filter by role and department privacy"""
        # 1. Admin sees everything
        res_admin = _tool_search_issues({"query": "Secret"}, self.user_admin, self.cfg)
        keys_admin = [issue["key"] for issue in res_admin["issues"]]
        self.assertIn("DEV-902", keys_admin)
        self.assertIn("SALES-903", keys_admin)

        # 2. Dev member cannot see private or other dept tasks
        res_dev = _tool_search_issues({"query": "Sales Confidential"}, self.user_dev_member, self.cfg)
        keys_dev = [issue["key"] for issue in res_dev["issues"]]
        self.assertNotIn("SALES-903", keys_dev)

        # 3. Dev manager can see public tasks from sales, but NOT private tasks from sales
        res_mgr_sales_pub = _tool_search_issues({"query": "SALES-904"}, self.user_dev_manager, self.cfg)
        keys_mgr_pub = [issue["key"] for issue in res_mgr_sales_pub["issues"]]
        self.assertIn("SALES-904", keys_mgr_pub)

        res_mgr_sales_priv = _tool_search_issues({"query": "SALES-903"}, self.user_dev_manager, self.cfg)
        keys_mgr_priv = [issue["key"] for issue in res_mgr_sales_priv["issues"]]
        self.assertNotIn("SALES-903", keys_mgr_priv)

    def test_get_active_tasks_rbac_isolation(self):
        """AI tool get_active_tasks must filter tasks by permissions"""
        res_dev = _tool_get_active_tasks({}, self.user_dev_member, self.cfg)
        keys_dev = [t["key"] for t in res_dev["tasks"]]
        # Must not contain private sales deal
        self.assertNotIn("SALES-903", keys_dev)
        self.assertNotIn("SALES-905", keys_dev)

    def test_get_issue_details_rbac_isolation(self):
        """AI tool get_issue_details must block unauthorized access to private tasks"""
        # Dev member requesting private sales task details
        res = _tool_get_issue_details({"issue_key": "SALES-903"}, self.user_dev_member, self.cfg)
        self.assertFalse(res.get("found"))
        self.assertIn("권한이 없습니다", res.get("error", ""))

        # Admin requesting private sales task details succeeds
        res_admin = _tool_get_issue_details({"issue_key": "SALES-903"}, self.user_admin, self.cfg)
        self.assertTrue(res_admin.get("found"))
        self.assertEqual(res_admin.get("key"), "SALES-903")

    def test_get_child_issues_rbac_isolation(self):
        """AI tool get_child_issues must block unauthorized access to child tasks of private issues"""
        # Dev member requesting child tasks of SALES-903
        res = _tool_get_child_issues({"parent_key": "SALES-903"}, self.user_dev_member, self.cfg)
        self.assertEqual(res.get("children_count"), 0)
        self.assertIn("권한이 없습니다", res.get("error", ""))

        # Sales member requesting child tasks of SALES-903
        res_sales = _tool_get_child_issues({"parent_key": "SALES-903"}, self.user_sales_member, self.cfg)
        keys_sales = [c["key"] for c in res_sales.get("children", [])]
        self.assertIn("SALES-905", keys_sales)

    def test_search_and_get_product_price_masking(self):
        """PIM product search & details must mask prices for non-sales/non-admin members"""
        # Search products
        res_dev = _tool_search_products({}, self.user_dev_member, self.cfg)
        if res_dev["products"]:
            first_p = res_dev["products"][0]
            self.assertTrue(first_p.get("priceHidden"))
            self.assertEqual(first_p.get("price"), 0)
            if first_p.get("procurement"):
                self.assertTrue(first_p["procurement"].get("priceHidden"))
                self.assertEqual(first_p["procurement"].get("price", 0), 0)

        # Sales user should be able to view price
        res_sales = _tool_search_products({}, self.user_sales_member, self.cfg)
        if res_sales["products"]:
            first_p = res_sales["products"][0]
            self.assertFalse(first_p.get("priceHidden"))

        # Details
        if res_dev["products"]:
            prod_id = res_dev["products"][0]["id"]
            detail_dev = _tool_get_product_details({"product_id": prod_id}, self.user_dev_member, self.cfg)
            self.assertTrue(detail_dev.get("priceHidden"))
            self.assertEqual(detail_dev.get("price"), 0)

            detail_sales = _tool_get_product_details({"product_id": prod_id}, self.user_sales_member, self.cfg)
            self.assertFalse(detail_sales.get("priceHidden"))


if __name__ == "__main__":
    unittest.main()
