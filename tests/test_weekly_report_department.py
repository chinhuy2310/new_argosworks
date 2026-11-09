# -*- coding: utf-8 -*-
import os
import pytest
from unittest.mock import MagicMock
from services.sheets_reporter import (
    resolve_department,
    _matches_department,
    generate_weekly_report,
    get_report_columns,
    REPORT_COLUMNS_I18N
)
from handlers.report_handler import handle_get_weekly_report


def test_resolve_department():
    # Empty or all
    assert resolve_department(None) == (None, None)
    assert resolve_department("all") == (None, None)
    assert resolve_department("전체") == (None, None)
    assert resolve_department("tất cả") == (None, None)

    # Alias heuristics
    did, dname = resolve_department("R&D")
    assert did in ("lab", "rnd", "R&D") or "연구" in dname

    did_sales, dname_sales = resolve_department("kinh doanh")
    assert did_sales in ("sales", "kinh doanh") or "영업" in dname_sales


def test_matches_department():
    row_with_dept = {"dept_id": "lab", "담당자": "홍길동"}
    assert _matches_department(row_with_dept, "lab", "연구소") is True
    assert _matches_department(row_with_dept, "sales", "기술영업팀") is False

    row_with_org = {"org": "sales", "담당자": "김영업"}
    assert _matches_department(row_with_org, "sales", "기술영업팀") is True
    assert _matches_department(row_with_org, "lab", "연구소") is False


def test_vietnamese_column_headers():
    vi_cols = get_report_columns("vi")
    assert "Phân loại" in vi_cols
    assert "Người phụ trách" in vi_cols
    assert "Hạn chót" in vi_cols
    assert len(vi_cols) == 12


def test_generate_weekly_report_workspace_name_and_dept_filtering(tmp_path, monkeypatch):
    monkeypatch.setattr("services.sheets_reporter.DATA_DIR", str(tmp_path))
    monkeypatch.setattr("services.sheets_reporter.CUSTOM_TEMPLATE_PATH", str(tmp_path / "no_template.xlsx"))

    mock_jira_rows = [
        {
            '구분': '개발',
            '업무명': 'Vision Box',
            '담당자': '이도현',
            '세부 업무명': 'TensorRT 최적화',
            '유형': '주간',
            '일자': '2026-11-04',
            '상세내용': 'INT8 양자화 테스트',
            '진척(%)': '80',
            '상태': '진행중',
            '마감일': '2026-11-06',
            '사유(지연시)': '',
            '다음 계획': '성능 리포트 작성',
            '_source': 'jira',
            '_jira_key': 'DEV-202',
            'dept_id': 'lab',
            '_dept': 'lab',
        },
        {
            '구분': '영업',
            '업무명': '고객사 미팅',
            '담당자': '최영업',
            '세부 업무명': '제품 데모 시연',
            '유형': '일간',
            '일자': '2026-11-05',
            '상세내용': 'Vision-Box 시연',
            '진척(%)': '100',
            '상태': '완료',
            '마감일': '2026-11-05',
            '사유(지연시)': '',
            '다음 계획': '',
            '_source': 'jira',
            '_jira_key': 'SALES-55',
            'dept_id': 'sales',
            '_dept': 'sales',
        }
    ]

    monkeypatch.setattr("services.sheets_reporter.fetch_jira_rows", lambda cfg, s, e: mock_jira_rows)
    monkeypatch.setattr("services.sheets_reporter.fetch_sheet_rows", lambda cfg: [])

    cfg = {"workspace": {"name": "ARGOS WORKS"}}

    # 1. Filter by lab / R&D
    res_lab = generate_weekly_report(
        cfg,
        assignee="all",
        dept="lab",
        period="custom",
        start_date="2026-11-02",
        end_date="2026-11-08",
        lang="vi"
    )
    assert res_lab["ok"] is True
    assert res_lab["row_count"] == 1
    assert "ARGOS_WORKS" in res_lab["filename"]
    assert "Bao_cao_tuan" in res_lab["filename"]
    assert os.path.isfile(res_lab["file_path"])

    # 2. Filter by sales
    res_sales = generate_weekly_report(
        cfg,
        assignee="all",
        dept="sales",
        period="custom",
        start_date="2026-11-02",
        end_date="2026-11-08",
        lang="en"
    )
    assert res_sales["ok"] is True
    assert res_sales["row_count"] == 1
    assert "ARGOS_WORKS" in res_sales["filename"]
    assert "Weekly_Report" in res_sales["filename"]

    # 3. No dept filter (all)
    res_all = generate_weekly_report(
        cfg,
        assignee="all",
        dept=None,
        period="custom",
        start_date="2026-11-02",
        end_date="2026-11-08",
        lang="ko"
    )
    assert res_all["ok"] is True
    assert res_all["row_count"] == 2
    assert "전체" in res_all["filename"]


def test_handle_get_weekly_report_with_dept(monkeypatch):
    import urllib.parse
    handler = MagicMock()
    handler.cfg = {"workspace": {"name": "ARGOS WORKS"}}
    handler._get_session_or_401.return_value = {"role": "admin", "is_admin": 1}

    captured_args = {}
    def mock_generate(cfg, assignee='all', dept=None, period='this_week', start_date=None, end_date=None, lang='ko'):
        captured_args['assignee'] = assignee
        captured_args['dept'] = dept
        captured_args['period'] = period
        captured_args['lang'] = lang
        return {"ok": True, "filename": "test.xlsx", "download_url": "/api/reports/download?file=test.xlsx", "row_count": 0}

    monkeypatch.setattr("services.sheets_reporter.generate_weekly_report", mock_generate)

    parsed = urllib.parse.urlsplit("/api/reports/weekly?dept=lab&assignee=all&period=this_week&lang=vi")
    handle_get_weekly_report(handler, parsed, "127.0.0.1")

    assert captured_args["dept"] == "lab"
    assert captured_args["lang"] == "vi"
    handler._send_json.assert_called_with(200, {"ok": True, "filename": "test.xlsx", "download_url": "/api/reports/download?file=test.xlsx", "row_count": 0})


def test_assignee_matches_participants(tmp_path, monkeypatch):
    monkeypatch.setattr("services.sheets_reporter.DATA_DIR", str(tmp_path))
    monkeypatch.setattr("services.sheets_reporter.CUSTOM_TEMPLATE_PATH", str(tmp_path / "no_template.xlsx"))

    mock_rows = [
        {
            '구분': 'AI',
            '업무명': 'OCR Engine',
            '담당자': 'Trần Văn A',
            'participants': 'Nguyễn Văn B, Lê Thị C',
            '세부 업무명': 'Tối ưu nhận diện text',
            '유형': '주간',
            '일자': '2026-11-04',
            '상세내용': 'Huấn luyện model mới',
            '진척(%)': '90',
            '상태': '진행중',
            '마감일': '2026-11-06',
            '사유(지연시)': '',
            '다음 계획': '',
            '_source': 'jira',
            '_jira_key': 'AI-101',
        }
    ]
    monkeypatch.setattr("services.sheets_reporter.fetch_jira_rows", lambda cfg, s, e: mock_rows)
    monkeypatch.setattr("services.sheets_reporter.fetch_sheet_rows", lambda cfg: [])

    cfg = {"workspace": {"name": "ARGOS WORKS"}}

    # Search by primary assignee
    res_primary = generate_weekly_report(cfg, assignee="Trần Văn A", period="custom", start_date="2026-11-01", end_date="2026-11-07")
    assert res_primary["ok"] is True
    assert res_primary["row_count"] == 1

    # Search by participant
    res_part = generate_weekly_report(cfg, assignee="Nguyễn Văn B", period="custom", start_date="2026-11-01", end_date="2026-11-07")
    assert res_part["ok"] is True
    assert res_part["row_count"] == 1

    # Search by unrelated person
    res_none = generate_weekly_report(cfg, assignee="Phạm Văn D", period="custom", start_date="2026-11-01", end_date="2026-11-07")
    assert res_none["ok"] is True
    assert res_none["row_count"] == 0


def test_generate_custom_columns_report(tmp_path, monkeypatch):
    monkeypatch.setattr("services.sheets_reporter.DATA_DIR", str(tmp_path))

    mock_rows = [
        {
            '구분': 'Backend',
            '업무명': 'API Gateway',
            '담당자': 'Huy Hoàng',
            'participants': 'Thành Nam',
            '세부 업무명': 'Rate limiting',
            '유형': '주간',
            '일자': '2026-11-04',
            '상세내용': 'Áp dụng token bucket algorithm',
            '진척(%)': '100',
            '상태': '완료',
            '마감일': '2026-11-05',
            '사유(지연시)': '',
            '다음 계획': 'Viết unit test',
            '_source': 'jira',
            '_jira_key': 'GW-12',
        }
    ]
    monkeypatch.setattr("services.sheets_reporter.fetch_jira_rows", lambda cfg, s, e: mock_rows)
    monkeypatch.setattr("services.sheets_reporter.fetch_sheet_rows", lambda cfg: [])

    import openpyxl
    custom_cols = [
        {"header": "Mã Issue", "field": "key"},
        {"header": "Công việc chính", "field": "title"},
        {"header": "Người phụ trách", "field": "assignee"},
        {"header": "Người cùng làm", "field": "participants"},
        {"header": "Tiến độ", "field": "progress"},
    ]

    cfg = {"workspace": {"name": "ARGOS WORKS"}}
    res = generate_weekly_report(
        cfg,
        assignee="all",
        period="custom",
        start_date="2026-11-01",
        end_date="2026-11-07",
        custom_columns=custom_cols,
        lang="vi"
    )

    assert res["ok"] is True
    assert res["row_count"] == 1
    assert os.path.isfile(res["file_path"])

    wb = openpyxl.load_workbook(res["file_path"])
    ws = wb.active
    # Headers in row 3
    headers = [ws.cell(row=3, column=c).value for c in range(1, 6)]
    assert headers == ["Mã Issue", "Công việc chính", "Người phụ trách", "Người cùng làm", "Tiến độ"]
    # Data row in row 4
    data = [ws.cell(row=4, column=c).value for c in range(1, 6)]
    assert data[0] == "GW-12"
    assert data[1] == "Rate limiting"
    assert data[2] == "Huy Hoàng"
    assert data[3] == "Thành Nam"
    assert data[4] == "100%"


def test_fact_grounded_delay_and_plan_extraction():
    from services.sheets_reporter import _extract_delay_and_rework, _extract_next_plan_intelligent

    # Case 1: On-time task, no blocker comments -> Delay reason MUST be empty (zero hallucination)
    delay_1 = _extract_delay_and_rework(
        due_date="2026-11-10",
        row_date="2026-11-05",
        title="Develop module",
        summary="Coding",
        comments=["Đang triển khai code bình thường"],
        status="진행중"
    )
    assert delay_1 == ""

    # Case 2: Overdue task -> Delay reason clearly states overdue
    delay_2 = _extract_delay_and_rework(
        due_date="2026-11-01",
        row_date="2026-11-05",
        title="Develop module",
        summary="Coding",
        comments=[],
        status="진행중"
    )
    assert "2026-11-01" in delay_2 or "지연" in delay_2

    # Case 3: Blocker in comment -> Extracted as delay/blocker reason
    delay_3 = _extract_delay_and_rework(
        due_date="2026-11-10",
        row_date="2026-11-05",
        title="Integration API",
        summary="",
        comments=["Block: Đang đợi bên đối tác cấp key API"],
        status="진행중"
    )
    assert "Block" in delay_3 or "đối tác" in delay_3

    # Case 4: No next plan in comments -> MUST be empty (zero hallucination)
    empty_plan = _extract_next_plan_intelligent(
        title="Deploy app",
        summary="Deployment done",
        comments=[]
    )
    assert empty_plan == ""

    # Case 5: Explicit future plan in comments -> Extracted cleanly
    plan_found = _extract_next_plan_intelligent(
        title="Deploy app",
        summary="",
        comments=["Kế hoạch tiếp theo: Chạy performance test và deploy staging"]
    )
    assert "deploy staging" in plan_found or "performance test" in plan_found

