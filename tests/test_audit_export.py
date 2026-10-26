"""
test_audit_export.py — Audit trail export (ISO / internal audit requirement).
"""
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_DIR = os.path.join(BASE_DIR, "server")
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from services.audit_logger import build_audit_export  # noqa: E402

SAMPLE_LOGS = [
    {
        "timestamp": "2026-10-23T10:15:00",
        "username": "김철수",
        "dept_id": "dev",
        "ip": "10.0.0.5",
        "action": "RECORD_UPDATE",
        "target_type": "record",
        "target_id": "DEV-102",
        "details_json": '{"field":"status"}',
    },
    {
        "timestamp": "2026-10-23T10:20:00",
        "username": "=cmd|calc",          # CSV injection attempt
        "dept_id": "hr",
        "ip": "10.0.0.9",
        "action": "LOGIN_FAILED",
        "target_type": "auth",
        "target_id": "@SUM(1+1)",
        "details_json": "+1+1",
    },
]


class TestAuditCsvExport:
    def test_csv_has_bom_and_header(self):
        body, content_type, ext = build_audit_export(SAMPLE_LOGS, "csv")
        assert ext == "csv"
        assert "text/csv" in content_type
        text = body.decode("utf-8")
        assert text.startswith("\ufeff"), "Excel needs a UTF-8 BOM for Korean/Vietnamese text"
        header = text.splitlines()[0].lstrip("\ufeff")
        assert header.startswith("timestamp,username,dept_id,ip,action")

    def test_csv_contains_rows(self):
        body, _, _ = build_audit_export(SAMPLE_LOGS, "csv")
        text = body.decode("utf-8")
        assert "DEV-102" in text
        assert "RECORD_UPDATE" in text
        assert "김철수" in text

    def test_csv_formula_injection_neutralised(self):
        body, _, _ = build_audit_export(SAMPLE_LOGS, "csv")
        text = body.decode("utf-8")
        # Every dangerous cell must be prefixed with an apostrophe
        assert ",=cmd|calc," not in text
        assert ",'=cmd|calc," in text or "'=cmd|calc" in text
        assert "'@SUM(1+1)" in text
        assert "'+1+1" in text

    def test_json_export_is_valid(self):
        body, content_type, ext = build_audit_export(SAMPLE_LOGS, "json")
        assert ext == "json"
        assert "application/json" in content_type
        parsed = json.loads(body.decode("utf-8"))
        assert len(parsed) == 2
        assert parsed[1]["action"] == "LOGIN_FAILED"

    def test_empty_log_set(self):
        body, _, ext = build_audit_export([], "csv")
        assert ext == "csv"
        assert len(body.decode("utf-8").strip().splitlines()) == 1


class TestVersionEndpoint:
    def test_version_handler_reports_release(self):
        from router import handle_get_version

        captured = {}

        class FakeHandler:
            def _send_json(self, code, payload):
                captured["code"] = code
                captured["payload"] = payload

        handle_get_version(FakeHandler(), None, "127.0.0.1")
        assert captured["code"] == 200
        assert captured["payload"]["ok"] is True
        assert captured["payload"]["version"] not in ("", "0.0.0-dev")
        assert "database" not in captured["payload"]
