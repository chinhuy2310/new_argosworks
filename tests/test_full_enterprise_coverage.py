import io
import os
import sys
import json
import pytest
import unittest
from datetime import datetime
from urllib.parse import urlparse

# Set server path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'server')))

from db import query, get_one, execute
from services.auth import (
    create_session, can_modify_pim, is_manager_or_admin,
    can_transition_status, can_modify_record, check_record_write_access
)
from services.data_store import (
    read_products, write_products, find_record_by_key_or_code
)
from handlers.product_handlers import (
    handle_product_save, handle_product_category_save, handle_product_category_delete
)
from router import (
    handle_assign_schedule_task, handle_unassign_schedule_task,
    handle_post_issue_transition, handle_get_schedule,
    handle_get_admin_audit_logs_export
)

class DummyHandler:
    def __init__(self, session=None, headers=None):
        self.session = session
        self.headers = headers or {}
        self.status = None
        self.response = None
        self.sent_headers = {}
        self.wfile = io.BytesIO()
        self.cfg = {"jira": {"enabled": False}}

    def _get_session_or_401(self):
        if not self.session:
            self.status = 401
            self.response = {"ok": False, "error": "로그인이 필요합니다."}
            return None
        return self.session

    def _send_json(self, status, data):
        self.status = status
        self.response = data

    def send_response(self, code):
        self.status = code

    def send_header(self, keyword, value):
        self.sent_headers[keyword] = value

    def end_headers(self):
        pass


class TestFullEnterpriseCoverage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Setup mock sessions for all 4 roles across departments
        cls.admin_sess = {
            "id": 1, "name": "김민수", "role": "admin", "is_admin": 1,
            "isAdmin": True, "org": "mgmt", "dept_id": "mgmt", "email": "admin@argos.com"
        }
        cls.mgr_dev_sess = {
            "id": 2, "name": "이도현", "role": "manager", "is_admin": 0,
            "isManager": True, "org": "dev", "dept_id": "dev", "email": "dohyun@argos.com"
        }
        cls.mgr_sales_sess = {
            "id": 5, "name": "정우성", "role": "manager", "is_admin": 0,
            "isManager": True, "org": "sales", "dept_id": "sales", "email": "woosung@argos.com"
        }
        cls.mem_dev_sess = {
            "id": 3, "name": "박서준", "role": "member", "is_admin": 0,
            "org": "dev", "dept_id": "dev", "email": "seojun@argos.com"
        }
        cls.viewer_sess = {
            "id": 4, "name": "최유나", "role": "viewer", "is_admin": 0,
            "org": "dev", "dept_id": "dev", "email": "yuna@argos.com"
        }

    # =========================================================================
    # SUITE 1: PIM Full Lifecycle & Multi-Role RBAC Coverage
    # =========================================================================
    def test_pim_permissions_helper(self):
        """Verify can_modify_pim logic across all roles."""
        self.assertTrue(can_modify_pim(self.admin_sess), "Admin must have PIM edit rights")
        self.assertTrue(can_modify_pim(self.mgr_dev_sess), "Dev Manager must have PIM edit rights")
        self.assertTrue(can_modify_pim(self.mgr_sales_sess), "Sales Manager must have PIM edit rights")
        self.assertFalse(can_modify_pim(self.mem_dev_sess), "Regular Member cannot modify PIM")
        self.assertFalse(can_modify_pim(self.viewer_sess), "Viewer cannot modify PIM")
        self.assertFalse(can_modify_pim(None), "Guest cannot modify PIM")

    def test_pim_create_and_edit_lifecycle(self):
        """Test Admin creates product, Manager edits product, Member & Viewer get 403."""
        import time as _time
        from services.data_store import read_product_categories

        # Use a category that really exists in this database (SQLite dev DBs have
        # customised categories, a fresh PostgreSQL schema has the seeded defaults).
        cats = read_product_categories()
        category = cats[0]["name"] if cats else "일반"
        model_name = f"ARGOS-GW-{int(_time.time() * 1000)}"
        mem_handler = DummyHandler(self.mem_dev_sess)
        payload_create = {
            "mode": "create",
            "displayName": "Enterprise Security Gateway Pro",
            "model": model_name,
            "category": category,
            "price": 1250000,
            "summary": "Industrial AI Edge Gateway"
        }
        # 1. Member tries to create product -> 403 Forbidden
        handle_product_save(mem_handler, json.dumps(payload_create).encode('utf-8'), "127.0.0.1")
        self.assertEqual(mem_handler.status, 403)
        self.assertFalse(mem_handler.response.get("ok"))

        # 2. Viewer tries to create product -> 403 Forbidden
        view_handler = DummyHandler(self.viewer_sess)
        handle_product_save(view_handler, json.dumps(payload_create).encode('utf-8'), "127.0.0.1")
        self.assertEqual(view_handler.status, 403)

        # 3. Guest (no session) tries to create product -> 401 Unauthorized
        guest_handler = DummyHandler(None)
        handle_product_save(guest_handler, json.dumps(payload_create).encode('utf-8'), "127.0.0.1")
        self.assertEqual(guest_handler.status, 401)

        # 4. Admin creates product -> 200 OK
        adm_handler = DummyHandler(self.admin_sess)
        handle_product_save(adm_handler, json.dumps(payload_create).encode('utf-8'), "127.0.0.1")
        self.assertEqual(adm_handler.status, 200, f"Create product failed: {adm_handler.response}")
        self.assertTrue(adm_handler.response.get("ok"))
        created_prod = adm_handler.response.get("product", {})
        prod_id = created_prod.get("id")
        self.assertIsNotNone(prod_id)
        self.assertEqual(created_prod.get("displayName"), "Enterprise Security Gateway Pro")

        # 5. Manager edits product price and specifications -> 200 OK
        mgr_handler = DummyHandler(self.mgr_dev_sess)
        payload_edit = {
            "mode": "edit",
            "id": prod_id,
            "revision": created_prod.get("revision", 1),
            "displayName": "Enterprise Security Gateway Pro V2",
            "model": model_name,
            "category": category,
            "price": 1350000,
            "summary": "Industrial AI Edge Gateway V2 with Dual Gigabit LAN"
        }
        handle_product_save(mgr_handler, json.dumps(payload_edit).encode('utf-8'), "127.0.0.1")
        self.assertEqual(mgr_handler.status, 200, f"Edit product failed: {mgr_handler.response}")
        self.assertTrue(mgr_handler.response.get("ok"))
        updated_prod = mgr_handler.response.get("product", {})
        self.assertEqual(updated_prod.get("displayName"), "Enterprise Security Gateway Pro V2")
        self.assertEqual(updated_prod.get("price"), 1350000)

        # Clean up test product
        products = read_products()
        filtered = [p for p in products if p.get("id") != prod_id]
        write_products(filtered)

    def test_product_category_governance(self):
        """PIM Category Save/Delete is permitted for Admin & Manager; Member & Viewer are blocked."""
        cat_id = f"test_cat_{int(datetime.now().timestamp() * 1000)}"
        cat_name = f"테스트 카테고리 {int(datetime.now().timestamp() * 1000)}"
        cat_payload = {
            "id": cat_id,
            "name": cat_name,
            "spec_template": ["주파수", "정밀도"]
        }

        # 1. Member tries to create category -> 403 Forbidden
        mem_handler = DummyHandler(self.mem_dev_sess)
        handle_product_category_save(mem_handler, json.dumps(cat_payload).encode('utf-8'), "127.0.0.1")
        self.assertEqual(mem_handler.status, 403)

        # 2. Viewer tries to create category -> 403 Forbidden
        view_handler = DummyHandler(self.viewer_sess)
        handle_product_category_save(view_handler, json.dumps(cat_payload).encode('utf-8'), "127.0.0.1")
        self.assertEqual(view_handler.status, 403)

        # 3. Manager creates category -> 200 OK (Manager + Admin permission)
        mgr_handler = DummyHandler(self.mgr_dev_sess)
        handle_product_category_save(mgr_handler, json.dumps(cat_payload).encode('utf-8'), "127.0.0.1")
        self.assertEqual(mgr_handler.status, 200)
        self.assertTrue(mgr_handler.response.get("ok"))

        # 4. Admin deletes category -> 200 OK
        adm_del_handler = DummyHandler(self.admin_sess)
        handle_product_category_delete(adm_del_handler, json.dumps({"id": cat_id}).encode('utf-8'), "127.0.0.1")
        self.assertEqual(adm_del_handler.status, 200)

    # =========================================================================
    # SUITE 2: Schedule Drag & Drop Assign/Unassign Lifecycle & RBAC
    # =========================================================================
    def test_schedule_assign_and_unassign_workflow(self):
        """Test Drag & Drop Schedule task assignment & unassignment with RBAC boundaries."""
        task_id = 99801
        card_code = f"DEV-{task_id}"
        execute(
            "INSERT OR REPLACE INTO records (id, dept_id, category, title, assignee_name, card_code, status, is_private) "
            "VALUES (?, 'dev', '개발', 'Sprint Deployment Pipeline', '박서준', ?, 'inprogress', 0)",
            (task_id, card_code)
        )

        # 1. Viewer attempts to assign schedule -> 403 Forbidden
        view_handler = DummyHandler(self.viewer_sess)
        payload_assign = {
            "taskId": card_code,
            "date": "2026-10-28",
            "endDate": "2026-10-30"
        }
        handle_assign_schedule_task(view_handler, json.dumps(payload_assign).encode('utf-8'), "127.0.0.1")
        self.assertEqual(view_handler.status, 403, "Viewer must be blocked from assigning tasks to calendar")

        # 2. Member assigns their own task -> 200 OK
        mem_handler = DummyHandler(self.mem_dev_sess)
        handle_assign_schedule_task(mem_handler, json.dumps(payload_assign).encode('utf-8'), "127.0.0.1")
        self.assertEqual(mem_handler.status, 200, f"Member assign task failed: {mem_handler.response}")
        self.assertTrue(mem_handler.response.get("ok"))

        # Verify record was updated in database
        rec = get_one("SELECT start_date, due_date, is_scheduled FROM records WHERE id = ?", (task_id,))
        self.assertEqual(rec["start_date"], "2026-10-28")
        self.assertEqual(rec["due_date"], "2026-10-30")
        self.assertEqual(rec["is_scheduled"], 1)

        # 3. Cross-department Member (Sales) attempts to change Dev private task -> 403 Forbidden
        mem_sales_sess = {
            "id": 6, "name": "강하늘", "role": "member", "is_admin": 0,
            "org": "sales", "dept_id": "sales", "email": "haneul@argos.com"
        }
        execute("UPDATE records SET is_private = 1 WHERE id = ?", (task_id,))
        sales_handler = DummyHandler(mem_sales_sess)
        payload_cross = { "taskId": card_code, "date": "2026-11-01" }
        handle_assign_schedule_task(sales_handler, json.dumps(payload_cross).encode('utf-8'), "127.0.0.1")
        self.assertEqual(sales_handler.status, 403)

        # 4. Dev Manager unassigns task -> 200 OK
        mgr_handler = DummyHandler(self.mgr_dev_sess)
        payload_unassign = { "taskId": card_code, "unassign": True, "wipeDates": True }
        handle_assign_schedule_task(mgr_handler, json.dumps(payload_unassign).encode('utf-8'), "127.0.0.1")
        self.assertEqual(mgr_handler.status, 200)
        self.assertTrue(mgr_handler.response.get("ok"))

        # Clean up
        execute("DELETE FROM records WHERE id = ?", (task_id,))

    # =========================================================================
    # SUITE 3: Full Status Lifecycle & Manager Approval Governance
    # =========================================================================
    def test_full_governance_approval_chain(self):
        """Test complete workflow: todo -> inprogress -> review -> done (approval)."""
        task_id = 99802
        card_code = f"DEV-{task_id}"
        execute(
            "INSERT OR REPLACE INTO records (id, dept_id, category, title, assignee_name, card_code, status, is_private) "
            "VALUES (?, 'dev', '개발', 'Core Engine Refactoring', '박서준', ?, 'todo', 0)",
            (task_id, card_code)
        )

        rec = find_record_by_key_or_code(card_code)
        self.assertIsNotNone(rec)

        # Step A: Member transitions 'todo' -> 'inprogress' (Permitted)
        can_prog, _ = can_transition_status(self.mem_dev_sess, rec, "inprogress")
        self.assertTrue(can_prog)
        execute("UPDATE records SET status = 'inprogress' WHERE id = ?", (task_id,))

        # Step B: Member transitions 'inprogress' -> 'review' (Permitted for review submission)
        rec["status"] = "inprogress"
        can_rev, _ = can_transition_status(self.mem_dev_sess, rec, "review")
        self.assertTrue(can_rev)
        execute("UPDATE records SET status = 'review' WHERE id = ?", (task_id,))

        # Step C: Member attempts direct self-approval 'review' -> 'done' (BLOCKED)
        rec["status"] = "review"
        can_self_done, err = can_transition_status(self.mem_dev_sess, rec, "done")
        self.assertFalse(can_self_done, "Member cannot self-approve task to done")
        self.assertIn("관리자", err)

        # Step D: Other department Manager (Sales) attempts to approve Dev task (BLOCKED)
        can_other_mgr, other_err = can_transition_status(self.mgr_sales_sess, rec, "done")
        self.assertFalse(can_other_mgr, "Cross-department manager cannot approve tasks outside their department")

        # Step E: Proper Dev Department Manager approves task -> 'done' (PERMITTED)
        can_mgr_done, _ = can_transition_status(self.mgr_dev_sess, rec, "done")
        self.assertTrue(can_mgr_done, "Department Manager must be permitted to approve tasks")

        # Step F: Admin can also approve any task -> 'done' (PERMITTED)
        can_adm_done, _ = can_transition_status(self.admin_sess, rec, "done")
        self.assertTrue(can_adm_done, "System Admin must be permitted to approve any department task")

        # Clean up
        execute("DELETE FROM records WHERE id = ?", (task_id,))

    # =========================================================================
    # SUITE 4: Audit Log Export RBAC
    # =========================================================================
    def test_admin_audit_log_export_rbac(self):
        """Audit Log Export requires Admin credentials; Member and Viewer are blocked."""
        parsed_url = urlparse("/api/admin/audit-logs/export?format=csv")

        # 1. Member tries to export audit logs -> 403 Forbidden
        mem_handler = DummyHandler(self.mem_dev_sess)
        handle_get_admin_audit_logs_export(mem_handler, parsed_url, "127.0.0.1")
        self.assertEqual(mem_handler.status, 403)

        # 2. Viewer tries to export audit logs -> 403 Forbidden
        view_handler = DummyHandler(self.viewer_sess)
        handle_get_admin_audit_logs_export(view_handler, parsed_url, "127.0.0.1")
        self.assertEqual(view_handler.status, 403)

        # 3. Admin exports audit logs -> 200 OK with CSV Content-Type
        adm_handler = DummyHandler(self.admin_sess)
        handle_get_admin_audit_logs_export(adm_handler, parsed_url, "127.0.0.1")
        self.assertEqual(adm_handler.status, 200)
        self.assertIn("text/csv", adm_handler.sent_headers.get("Content-Type", ""))

    # =========================================================================
    # SUITE 5: Subtask Parent-Key Hierarchy Persistence
    # =========================================================================
    def test_subtask_hierarchy_linking(self):
        """Subtask created with parent_key correctly maintains database hierarchy."""
        parent_id = 99803
        child_id = 99804
        parent_code = f"DEV-{parent_id}"
        child_code = f"DEV-{child_id}"

        # Insert Parent
        execute(
            "INSERT OR REPLACE INTO records (id, dept_id, category, title, assignee_name, card_code, status) "
            "VALUES (?, 'dev', '개발', 'Parent Epic Architecture', '박서준', ?, 'inprogress')",
            (parent_id, parent_code)
        )

        # Insert Child with parent_key
        execute(
            "INSERT OR REPLACE INTO records (id, dept_id, category, title, assignee_name, card_code, status, parent_key) "
            "VALUES (?, 'dev', '개발', 'Child Module Implementation', '박서준', ?, 'todo', ?)",
            (child_id, child_code, parent_code)
        )

        child_row = get_one("SELECT parent_key FROM records WHERE id = ?", (child_id,))
        self.assertEqual(child_row["parent_key"], parent_code)

        # Query subtasks of parent
        subtasks = query("SELECT id, title FROM records WHERE parent_key = ?", (parent_code,))
        self.assertEqual(len(subtasks), 1)
        self.assertEqual(subtasks[0]["id"], child_id)

        # Clean up
        execute("DELETE FROM records WHERE id IN (?, ?)", (parent_id, child_id))

    # =========================================================================
    # SUITE 6: Role Fallback & State Consistency Verification
    # =========================================================================
    def test_role_fallback_and_manager_resolution(self):
        """Ensure session profiles without explicit 'role' string are correctly resolved."""
        # Profile without 'role' but with is_admin=1
        admin_legacy = {"name": "OldAdmin", "is_admin": 1, "org": "mgmt"}
        self.assertTrue(is_manager_or_admin(admin_legacy))

        # Profile with role='manager'
        mgr_legacy = {"name": "OldManager", "role": "manager", "org": "dev"}
        self.assertTrue(is_manager_or_admin(mgr_legacy))

        # Regular member without role
        member_legacy = {"name": "OldMember", "role": "member", "org": "dev"}
        self.assertFalse(is_manager_or_admin(member_legacy))

if __name__ == '__main__':
    unittest.main()
