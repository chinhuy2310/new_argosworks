import os
import tempfile

import openpyxl

from services.sheets_reporter import (
    _excel_safe_value,
    _generate_xlsx,
    _render_custom_template,
    generate_sample_template_bytes,
)


def test_excel_safe_value_neutralizes_formula_prefixes_and_controls():
    for value in ("=1+1", "  +1+1", "\t-1+1", "\r@SUM(1,1)"):
        assert _excel_safe_value(value).lstrip() .startswith("'")
    assert _excel_safe_value("ordinary text") == "ordinary text"
    assert _excel_safe_value(42) == 42
    assert _excel_safe_value(-42) == -42


def test_builtin_report_export_stores_untrusted_values_as_text():
    row = {
        "구분": "=1+1",
        "업무명": "+cmd",
        "담당자": "-1+1",
        "세부 업무명": "@SUM(1,1)",
        "유형": "주간",
        "일자": "2026-11-04",
        "상세내용": "  =HYPERLINK(\"https://example.invalid\")",
        "진척(%)": 50,
        "상태": "진행중",
        "마감일": "",
        "사유(지연시)": "",
        "다음 계획": "",
    }
    with tempfile.TemporaryDirectory() as root:
        path = os.path.join(root, "report.xlsx")
        _generate_xlsx([row], path, "2026-11-01", "2026-11-07")
        ws = openpyxl.load_workbook(path, data_only=False).active
        for cell in ("A4", "B4", "C4", "D4", "G4"):
            assert ws[cell].data_type != "f"
            assert str(ws[cell].value).lstrip().startswith("'")


def test_custom_template_export_neutralizes_inserted_values():
    with tempfile.TemporaryDirectory() as root:
        template_path = os.path.join(root, "template.xlsx")
        output_path = os.path.join(root, "custom.xlsx")
        with open(template_path, "wb") as output:
            output.write(generate_sample_template_bytes({"workspace": {"name": "=workspace"}}))
        row = {
            "구분": "=category",
            "업무명": "+project",
            "담당자": "-assignee",
            "세부 업무명": "@task",
            "유형": "주간",
            "일자": "2026-11-04",
            "상세내용": "=details",
            "진척(%)": 10,
            "상태": "진행중",
            "마감일": "",
            "사유(지연시)": "",
            "다음 계획": "",
        }
        _render_custom_template(
            template_path, [row], output_path, "2026-11-02", "2026-11-08",
            {"workspace": {"name": "=workspace"}}, assignee="@all"
        )
        ws = openpyxl.load_workbook(output_path, data_only=False).active
        assert ws["A1"].data_type != "f"
        assert ws["A1"].value.startswith("'")
        for cell in ("A4", "B4", "C4", "D4", "G4"):
            assert ws[cell].data_type != "f"
            assert str(ws[cell].value).startswith("'")
