"""report_handler.py — 주간 업무 보고서 생성 및 다운로드 핸들러"""

import json
import os
import mimetypes
import urllib.parse
from utils.logging import log_line, access_log
from services.auth import get_session
from config import DATA_DIR


def handle_get_weekly_report(handler, parsed, ip):
    """GET /api/reports/weekly?assignee=all&period=this_week&start=&end=
    주간 업무 보고서를 생성하고 메타데이터를 반환한다."""
    session = handler._get_session_or_401()
    if not session:
        return

    from services.auth import is_admin_user
    if not is_admin_user(session):
        handler._send_json(403, {
            "ok": False,
            "error": "주간 업무 보고서 엑셀 출력 기능은 관리자(팀장님) 전용 권한입니다."
        })
        return

    from urllib.parse import parse_qs
    qs = parse_qs(parsed.query)
    assignee = qs.get("assignee", ["all"])[0]
    period = qs.get("period", ["this_week"])[0]
    start_date = qs.get("start", [None])[0]
    end_date = qs.get("end", [None])[0]
    lang = qs.get("lang", ["ko"])[0].lower().strip()
    if lang not in ("ko", "en"):
        lang = "ko"

    try:
        from services.sheets_reporter import generate_weekly_report
        result = generate_weekly_report(
            handler.cfg,
            assignee=assignee,
            period=period,
            start_date=start_date,
            end_date=end_date,
            lang=lang
        )
        if result.get("ok"):
            access_log(ip, "report_generate", 200,
                       f"assignee={assignee} period={period} rows={result.get('row_count', 0)}")
        else:
            access_log(ip, "report_generate", 400, result.get("error", "unknown"))

        handler._send_json(200 if result.get("ok") else 400, result)

    except Exception as e:
        log_line(f"[Report] 보고서 생성 오류: {e}")
        handler._send_json(500, {"ok": False, "error": f"보고서 생성 중 오류: {str(e)}"})


def handle_get_report_download(handler, parsed, ip):
    """GET /api/reports/download?file=filename.xlsx
    생성된 보고서 파일을 다운로드한다."""
    from urllib.parse import parse_qs
    qs = parse_qs(parsed.query)

    session = handler._get_session_or_401()
    if not session:
        return

    # 보고서 파일에는 전사(전 부서) 업무 데이터가 포함되므로, 생성 권한과 동일하게
    # 부서 관리자(Manager) 이상만 다운로드할 수 있도록 제한한다.
    from services.auth import is_manager_or_admin
    if not is_manager_or_admin(session):
        handler._send_json(403, {
            "ok": False,
            "error": "보고서 다운로드는 부서 관리자(Manager) 또는 시스템 관리자(Admin)만 가능합니다."
        })
        return

    filename = qs.get("file", [""])[0]

    if not filename:
        handler._send_json(400, {"ok": False, "error": "파일명이 필요합니다."})
        return

    # Prevent directory traversal
    safe_name = os.path.basename(filename)
    reports_dir = os.path.join(DATA_DIR, "reports")
    file_path = os.path.join(reports_dir, safe_name)

    if not os.path.isfile(file_path):
        handler._send_json(404, {"ok": False, "error": "보고서 파일을 찾을 수 없습니다."})
        return

    ct, _ = mimetypes.guess_type(file_path)
    content_type = ct or "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    try:
        with open(file_path, "rb") as f:
            data = f.read()

        encoded_name = urllib.parse.quote(safe_name)
        handler.send_response(200)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Content-Length", str(len(data)))
        handler.send_header("Content-Disposition",
                            f"attachment; filename*=UTF-8''{encoded_name}")
        handler.send_header("Access-Control-Allow-Origin", "*")
        handler.end_headers()
        handler.wfile.write(data)

        access_log(ip, "report_download", 200, safe_name)
    except Exception as e:
        handler._send_json(500, {"ok": False, "error": f"파일 다운로드 실패: {str(e)}"})


def handle_get_report_template_info(handler, parsed, ip):
    """GET /api/reports/template/info — 보고서 템플릿 상태 및 태그 안내 반환"""
    session = handler._get_session_or_401()
    if not session:
        return
    from services.sheets_reporter import get_template_info
    info = get_template_info()
    handler._send_json(200, info)


def handle_post_report_template_upload(handler, raw_body, ip):
    """POST /api/reports/template — 커스텀 주간 보고서 엑셀 템플릿(.xlsx) 업로드 (관리자 전용)"""
    session = handler._get_session_or_401()
    if not session:
        return
    from services.auth import is_admin_user, is_manager_or_admin
    if not is_manager_or_admin(session):
        handler._send_json(403, {"ok": False, "error": "관리자 또는 부서장만 템플릿을 등록/변경할 수 있습니다."})
        return

    content_type = handler.headers.get("Content-Type", "")
    file_bytes = None

    if "multipart/form-data" in content_type:
        import re
        from utils.multipart import parse_multipart
        m = re.search(r'boundary=([^;]+)', content_type)
        if m:
            boundary = m.group(1).strip('"')
            _, files = parse_multipart(raw_body, boundary)
            if files:
                file_bytes = files[0].get("data")
    else:
        file_bytes = raw_body

    if not file_bytes:
        handler._send_json(400, {"ok": False, "error": "업로드된 엑셀 파일 데이터가 없습니다."})
        return

    # .xlsx is a ZIP container; reject anything else before handing it to openpyxl
    # (junk bodies otherwise burn seconds inside the parser, audit F-0003).
    if len(file_bytes) < 4 or not file_bytes.startswith(b"PK\x03\x04"):
        handler._send_json(400, {"ok": False, "error": "유효한 .xlsx 파일이 아닙니다."})
        return

    from services.sheets_reporter import save_custom_template
    res = save_custom_template(file_bytes)
    status_code = 200 if res.get("ok") else 400
    access_log(ip, "report_template_upload", status_code)
    handler._send_json(status_code, res)


def handle_delete_report_template(handler, parsed, ip):
    """DELETE /api/reports/template — 커스텀 템플릿 삭제 및 기본 서식 복원 (관리자/부서장 전용)"""
    session = handler._get_session_or_401()
    if not session:
        return
    from services.auth import is_admin_user, is_manager_or_admin
    if not is_manager_or_admin(session):
        handler._send_json(403, {"ok": False, "error": "관리자 또는 부서장만 템플릿을 삭제할 수 있습니다."})
        return

    from services.sheets_reporter import delete_custom_template
    res = delete_custom_template()
    status_code = 200 if res.get("ok") else 400
    access_log(ip, "report_template_delete", status_code)
    handler._send_json(status_code, res)


def handle_get_sample_template_download(handler, parsed, ip):
    """GET /api/reports/template/sample — 태그가 포함된 샘플 Excel 템플릿 다운로드"""
    from services.sheets_reporter import generate_sample_template_bytes
    try:
        data = generate_sample_template_bytes(handler.cfg)
        safe_name = "JARVIS_주간보고서_샘플템플릿.xlsx"
        encoded_name = urllib.parse.quote(safe_name)
        handler.send_response(200)
        handler.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        handler.send_header("Content-Length", str(len(data)))
        handler.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{encoded_name}")
        handler.send_header("Access-Control-Allow-Origin", "*")
        handler.end_headers()
        handler.wfile.write(data)
        access_log(ip, "report_template_sample", 200)
    except Exception as e:
        handler._send_json(500, {"ok": False, "error": f"샘플 템플릿 다운로드 실패: {str(e)}"})


def handle_get_export_records_excel(handler, parsed, ip):
    """GET /api/records/export/excel — 대시보드 업무 카드를 Excel(xlsx) 형식으로 즉시 다운로드"""
    from urllib.parse import parse_qs
    qs = parse_qs(parsed.query)

    session = handler._get_session_or_401()
    if not session:
        return

    import io
    from datetime import datetime
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from services.search import merged_records
    from services.auth import can_view_record

    records, _ = merged_records(handler.cfg)
    records = [r for r in records if can_view_record(session, r)]

    # Query string lọc (nếu có: org, status, assignee)
    filter_org = qs.get("org", [""])[0]
    filter_status = qs.get("status", [""])[0]
    filter_assignee = qs.get("assignee", [""])[0]

    if filter_org:
        records = [r for r in records if (r.get("dept_id") or r.get("org") or "") == filter_org]
    if filter_status:
        records = [r for r in records if (r.get("status") or "") == filter_status]
    if filter_assignee:
        records = [r for r in records if filter_assignee.lower() in (r.get("assignee_name") or r.get("assignee") or "").lower()]

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "업무_목록"
    ws.views.sheetView[0].showGridLines = True

    # Styling
    header_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid") # Dark Blue
    header_font = Font(name="Malgun Gothic", size=11, bold=True, color="FFFFFF")
    data_font = Font(name="Malgun Gothic", size=10)
    thin_border = Border(
        left=Side(style='thin', color='D1D5DB'),
        right=Side(style='thin', color='D1D5DB'),
        top=Side(style='thin', color='D1D5DB'),
        bottom=Side(style='thin', color='D1D5DB')
    )

    headers = ["업무코드", "제목", "구분/분류", "담당자", "부서/소속", "상태", "시작일", "마감일", "Jira 연동"]
    ws.append(headers)

    for col_idx in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = thin_border
    ws.row_dimensions[1].height = 26

    for r in records:
        code = r.get("cardCode") or (r.get("jira") or {}).get("key") or f"REC-{r.get('id', '')}"
        title = r.get("title") or r.get("summary") or ""
        cat = r.get("category") or ""
        assignee = r.get("assignee_name") or r.get("assignee") or ""
        dept = r.get("dept_id") or r.get("org") or ""
        status = r.get("status") or "진행"
        s_date = r.get("startDate") or r.get("start_date") or r.get("work_date") or ""
        e_date = r.get("endDate") or r.get("end_date") or r.get("dueDate") or r.get("due_date") or ""
        jira_k = (r.get("jira") or {}).get("key") or ""

        row_vals = [code, title, cat, assignee, dept, status, s_date, e_date, jira_k]
        ws.append(row_vals)
        curr_row = ws.max_row
        ws.row_dimensions[curr_row].height = 20

        for col_idx in range(1, len(row_vals) + 1):
            cell = ws.cell(row=curr_row, column=col_idx)
            cell.font = data_font
            cell.border = thin_border
            if col_idx in (1, 3, 5, 6, 7, 8, 9):
                cell.alignment = Alignment(horizontal="center", vertical="center")
            else:
                cell.alignment = Alignment(horizontal="left", vertical="center")

    # Column widths
    col_widths = [16, 40, 16, 14, 14, 12, 14, 14, 16]
    for i, w in enumerate(col_widths, start=1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w

    buf = io.BytesIO()
    wb.save(buf)
    excel_bytes = buf.getvalue()

    filename = f"ARGOS_업무목록_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    encoded_name = urllib.parse.quote(filename)

    handler.send_response(200)
    handler.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    handler.send_header("Content-Length", str(len(excel_bytes)))
    handler.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{encoded_name}")
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(excel_bytes)
    access_log(ip, "export_records_excel", 200, f"rows={len(records)}")

