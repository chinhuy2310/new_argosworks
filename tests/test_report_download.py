# -*- coding: utf-8 -*-
import os
import urllib.parse
from unittest.mock import MagicMock
import pytest

from handlers.report_handler import handle_get_report_download
from config import DATA_DIR


class TestReportDownload:
    def test_report_download_resolves_special_ampersand_and_korean(self, tmp_path, monkeypatch):
        # Setup temporary reports folder
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        
        test_file = reports_dir / "R&D_주간업무보고서_전체_2026-10-26_2026-10-30.xlsx"
        test_file.write_bytes(b"PK\x03\x04test_excel_content")
        
        monkeypatch.setattr("handlers.report_handler.DATA_DIR", str(tmp_path))
        
        # 1. Test when filename has unencoded &
        handler = MagicMock()
        handler._get_session_or_401.return_value = {"role": "admin", "is_admin": 1}
        
        parsed = urllib.parse.urlsplit("/api/reports/download?file=R&D_주간업무보고서_전체_2026-10-26_2026-10-30.xlsx")
        handle_get_report_download(handler, parsed, "127.0.0.1")
        
        handler.send_response.assert_called_with(200)
        handler.wfile.write.assert_called_with(b"PK\x03\x04test_excel_content")

    def test_report_download_resolves_percent_encoded_query(self, tmp_path, monkeypatch):
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        
        test_file = reports_dir / "R&D_주간업무보고서_전체_2026-10-26_2026-10-30.xlsx"
        test_file.write_bytes(b"PK\x03\x04test_excel_content")
        
        monkeypatch.setattr("handlers.report_handler.DATA_DIR", str(tmp_path))
        
        handler = MagicMock()
        handler._get_session_or_401.return_value = {"role": "admin", "is_admin": 1}
        
        encoded_name = urllib.parse.quote("R&D_주간업무보고서_전체_2026-10-26_2026-10-30.xlsx")
        parsed = urllib.parse.urlsplit(f"/api/reports/download?file={encoded_name}")
        handle_get_report_download(handler, parsed, "127.0.0.1")
        
        handler.send_response.assert_called_with(200)
        handler.wfile.write.assert_called_with(b"PK\x03\x04test_excel_content")

    def test_report_download_404_when_file_not_found(self, tmp_path, monkeypatch):
        monkeypatch.setattr("handlers.report_handler.DATA_DIR", str(tmp_path))
        
        handler = MagicMock()
        handler._get_session_or_401.return_value = {"role": "admin", "is_admin": 1}
        
        parsed = urllib.parse.urlsplit("/api/reports/download?file=non_existent_file.xlsx")
        handle_get_report_download(handler, parsed, "127.0.0.1")
        
        handler._send_json.assert_called_with(404, {"ok": False, "error": "보고서 파일을 찾을 수 없습니다."})
