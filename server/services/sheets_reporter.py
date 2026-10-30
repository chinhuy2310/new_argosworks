import os
import io
import csv
import json
import urllib.request
import urllib.parse
import re
from datetime import datetime, timedelta
import openpyxl
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
from openpyxl.cell.cell import MergedCell

from config import DATA_DIR
from utils.logging import log_line
from prompts import (
    REPORT_CLASSIFY_HEAD, REPORT_CATEGORY_GIVEN,
    REPORT_CATEGORY_FREE, REPORT_CLASSIFY_TAIL
)
from services.jira_client import get_cached_jira_records

TEMPLATES_DIR = os.path.join(DATA_DIR, "templates")
CUSTOM_TEMPLATE_PATH = os.path.join(TEMPLATES_DIR, "weekly_report_template.xlsx")

# Bilingual Columns Definition (English / Korean)
REPORT_COLUMNS_I18N = {
    "ko": [
        '구분', '업무명', '담당자', '세부 업무명', '유형', '일자', 
        '상세내용', '진척(%)', '상태', '마감일', '사유(지연시)', '다음 계획'
    ],
    "en": [
        'Category', 'Project', 'Assignee', 'Task Name', 'Type', 'Date',
        'Details', 'Progress(%)', 'Status', 'Due Date', 'Delay Reason', 'Next Plan'
    ]
}

def get_report_columns(lang="ko"):
    """Returns report column headers in Korean or English (default: Korean)"""
    return REPORT_COLUMNS_I18N.get(str(lang).lower().strip(), REPORT_COLUMNS_I18N["ko"])

# Default fallback
COLUMNS = REPORT_COLUMNS_I18N["ko"]

_TITLES = ('사원', '대리', '과장', '차장', '부장', '이사', '주임', '팀장', '연구원', '소장', '대표')

def _clean_assignees(text):
    """'장욱재 과장\\n강해찬 사원\\n' → '장욱재 과장\n강해찬 사원' (줄바꿈 구분)"""
    parts = [p.strip() for p in re.split(r'[\n,/]+', text or '') if p.strip()]
    return '\n'.join(parts)

def _person_names(text):
    """담당자 문자열에서 직함을 뗀 이름 목록을 반환 ('홍성우대리' → '홍성우')."""
    names = []
    for p in re.split(r'[\n,/]+', text or ''):
        p = p.strip()
        for t in _TITLES:
            if p.endswith(t):
                p = p[: -len(t)].strip()
                break
        if p:
            names.append(p)
    return names

def _classify_jira_records_contextually(cfg, jira_records):
    """Jira 티켓 목록을 AI LLM(또는 맥락 기반 규칙)을 활용해 심층 분석하여
    각 카드의 맥락(Context)에 따라 [구분], [업무명], [유형]을 지능적으로 판정한다.
    - 단발성 긴급 대응, 하루 만에 완료된 작업, 일일 점검 등은 독립 카드라도 '일간'으로 판정
    - 지속 개발 과제, 일주일 이상 소요되는 설계/프로젝트는 '주간'으로 판정"""
    results = {}
    if not jira_records:
        return results

    # 1. AI 활성화 시 LLM 문맥 심층 분석 시도
    ai_success = False
    try:
        from services.ai_client import call_ai_raw, get_ai_config
        ai_cfg = get_ai_config(cfg)
        if ai_cfg.get("enabled") and (ai_cfg.get("api_key") or ai_cfg.get("provider") == "ollama"):
            cards_prompt = []
            for idx, r in enumerate(jira_records):
                jk = (r.get('jira') or {}).get('key') or str(idx)
                title = str(r.get('title') or '')
                summary = str(r.get('summary') or '')[:200]
                parent = str(r.get('parentSummary') or '')
                start_d = str(r.get('startDate') or '')
                due_d = str(r.get('dueDate') or '')
                cards_prompt.append(
                    f"{idx+1}. 키: {jk}\n   제목: {title}\n   상세: {summary}\n   상위: {parent}\n   시작-마감: {start_d} ~ {due_d}"
                )

            # Categories and prompt customizations from config or tenant settings
            report_cfg = cfg.get("reports", {})
            custom_categories = report_cfg.get("categories") or [
                "연구", "인증", "시공", "A/S", "수입", "배송", "전시회", "사업", "심사", "운영", "기획"
            ]
            categories_str = "\n".join([f"- '{c}'" for c in custom_categories])

            custom_prompt_tpl = report_cfg.get("ai_classification_prompt")
            if custom_prompt_tpl and "{cards}" in custom_prompt_tpl:
                prompt = custom_prompt_tpl.replace("{cards}", chr(10).join(cards_prompt))
            else:
                cat_section = (
                    REPORT_CATEGORY_GIVEN.format(categories=categories_str)
                    if custom_categories
                    else REPORT_CATEGORY_FREE
                )
                prompt = (
                    REPORT_CLASSIFY_HEAD
                    + "\n"
                    + cat_section
                    + "\n"
                    + REPORT_CLASSIFY_TAIL.format(cards=chr(10).join(cards_prompt))
                )

            ai_resp = call_ai_raw(cfg, prompt, max_tokens=1000)
            if ai_resp:
                json_match = re.search(r'\[\s*\{.*?\}\s*\]', ai_resp, re.DOTALL)
                if json_match:
                    parsed = json.loads(json_match.group(0))
                    for item in parsed:
                        idx_val = int(item.get("id", 0)) - 1
                        if 0 <= idx_val < len(jira_records):
                            rec = jira_records[idx_val]
                            rid = id(rec)
                            results[rid] = (
                                item.get("category", "연구"),
                                item.get("task", "연구"),
                                item.get("type", "일간")
                            )
                    ai_success = True
    except Exception as e:
        log_line(f"[Report] AI 문맥 분류 중 예외 발생, 맥락 규칙으로 대체: {e}")

    # 2. AI 실패 또는 미설정 시: 스마트 맥락 규칙(Heuristic Context Analysis)
    for r in jira_records:
        rid = id(r)
        if rid in results:
            continue
        results[rid] = _context_heuristic_classify(r)

    return results

def _context_heuristic_classify(r):
    """카드의 작업 기간, 내용, 단어 맥락을 분석하여 동적으로 분류"""
    title = str(r.get('title') or '')
    summary = str(r.get('summary') or '')
    parent = str(r.get('parentSummary') or '')
    tags = " ".join(r.get('tags') or [])
    combined = f"{parent} {title} {summary} {tags}".lower()

    # --- [유형 (Type: 일간 / 주간)] 문맥 분석 ---
    # 1) 시작일과 마감일이 명시되어 있고 동일한 날짜면 -> '일간'
    start_d = str(r.get('startDate') or '')
    due_d = str(r.get('dueDate') or '')
    r_type = None

    if start_d and due_d:
        if start_d == due_d:
            r_type = '일간'
        else:
            try:
                d1 = datetime.strptime(start_d, "%Y-%m-%d")
                d2 = datetime.strptime(due_d, "%Y-%m-%d")
                if (d2 - d1).days <= 1:
                    r_type = '일간'
                else:
                    r_type = '주간'
            except Exception:
                pass

    # 2) 제목 및 본문 문맥으로 당일성/긴급성 여부 판정
    if not r_type:
        daily_indicators = [
            '긴급', '현장', '출동', '수리', '교체', '조치', '대응', '오류', '문제',
            '발송', '택배', '등기', '회의', '미팅', '인수검사', '실사', '점검'
        ]
        weekly_indicators = [
            '설계', '개발 방안', '구축', '기획', '과제', '프로젝트', '플랫폼', '모듈 개발'
        ]
        is_daily = any(k in combined for k in daily_indicators)
        is_weekly = any(k in combined for k in weekly_indicators)

        if is_daily and not is_weekly:
            r_type = '일간'
        elif r.get('isSubtask') or str(r.get('category')) == '하위 작업':
            r_type = '일간'
        else:
            r_type = '주간'

    # --- [업무명 (Project)] 문맥 분석 ---
    task_name = parent if parent else (r.get('project') or '일반업무')
    category = r.get('category') or '일반'
    return category, task_name, r_type


def fetch_sheet_rows(cfg):
    """Google Sheets dependency removed. Returns empty list so reports rely purely on local DB & Jira."""
    return []

def fetch_jira_rows(cfg, start_date, end_date):
    try:
        from services.search import merged_records
        records, _ = merged_records(cfg)
    except Exception as e:
        log_line(f"Error fetching merged records: {e}")
        try:
            cache = get_cached_jira_records(cfg)
            records = cache.get('records', [])
        except Exception:
            records = []
        
    # 1단계: 기간 내 대상 레코드 수집
    mapped_rows = []
    in_range_records = []
    record_dates = {}
    for r in records:
        record_date_str = (r.get('date') or '')[:10]
        record_in_range = bool(record_date_str) and start_date <= record_date_str <= end_date
        
        valid_comments = []
        comment_dates = []
        for c in (r.get('comments') or []):
            created_str = (c.get('created') or '')[:10]
            if created_str and start_date <= created_str <= end_date:
                author = c.get('author') or ''
                body = (c.get('body') or '').strip()
                if body:
                    valid_comments.append(f"[{created_str} {author}] {body}".replace("  ", " "))
                comment_dates.append(created_str)
                
        if not record_in_range and not comment_dates:
            continue
            
        row_date = record_date_str if record_in_range else max(comment_dates)
        record_dates[id(r)] = (row_date, valid_comments)
        in_range_records.append(r)

    # 2단계: AI LLM 문맥 심층 분석 (또는 문맥 규칙)으로 [구분, 업무명, 유형] 일괄 판정
    classified_map = _classify_jira_records_contextually(cfg, in_range_records)

    # 3단계: 최종 12열 행 구성
    for r in in_range_records:
        row_date, valid_comments = record_dates[id(r)]
            
        status_key = (r.get('jira') or {}).get('status', 'none')
        if status_key in ['완료', 'done', 'good']:
            progress = 100
            mapped_status = '완료'
        elif status_key in ['진행중', 'in progress', 'info']:
            progress = 50
            mapped_status = '진행중'
        elif status_key == 'new':
            progress = 0
            mapped_status = '대기'
        else:
            progress = 0
            mapped_status = status_key
            
        summary_text = (r.get('summary') or '').strip()
        if valid_comments:
            summary_text += ("\n" if summary_text else "") + "[진행 댓글]\n" + "\n".join(valid_comments)
            
        jira_key = (r.get('jira') or {}).get('key', '')
        mapped_cat, mapped_task, mapped_type = classified_map.get(id(r), ('연구', '연구', '일간'))
        
        row = {
            '구분': mapped_cat,
            '업무명': mapped_task,
            '담당자': r.get('assignee', ''),
            '세부 업무명': r.get('title', ''),
            '유형': mapped_type or '일간',
            '일자': row_date,
            '상세내용': summary_text,
            '진척(%)': str(progress),
            '상태': mapped_status,
            '마감일': r.get('dueDate', ''),
            '사유(지연시)': '',
            '다음 계획': '',
            '_source': 'jira',
            '_jira_key': jira_key,
        }
        mapped_rows.append(row)
        
    return mapped_rows

def _normalize_date(d_str):
    if not d_str:
        return ""
    d_str = str(d_str).strip()
    m = re.match(r'(20\d\d)[-./](\d{1,2})[-./](\d{1,2})', d_str)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return d_str


def _resolve_and_filter_sheet_rows(sheet_rows, start_date, end_date):
    """구글 시트 전체 행을 분석하여, '주간' 업무 등 일자(Date)가 비어 있는 행의 일자를
    상세내용의 표준 날짜(YYYY-MM-DD) 및 시트 내 주간 블록 맥락(같은 블록의 인접 행 일자)을
    통해 복원하고 지정 기간(start_date ~ end_date) 내 행만 필터링한다."""
    processed = []
    for idx, r in enumerate(sheet_rows):
        has_content = any(bool(str(v).strip()) for k, v in r.items())
        raw_date = _normalize_date(r.get('일자', ''))
        processed.append({
            "idx": idx,
            "row": dict(r),
            "is_blank": not has_content,
            "date": raw_date
        })

    # 1. 상세내용에 YYYY-MM-DD 표준 날짜가 명시되어 있는지 확인
    for item in processed:
        if item["is_blank"] or item["date"]:
            continue
        desc = item["row"].get("상세내용", "")
        full_matches = [_normalize_date(d) for d in re.findall(r'20\d\d[-./]\d{1,2}[-./]\d{1,2}', desc)]
        in_range = [d for d in full_matches if start_date <= d <= end_date]
        if in_range:
            item["date"] = max(in_range)
        elif full_matches:
            item["date"] = max(full_matches)

    # 2. Block Context (Kế thừa ngữ cảnh khối tuần từ các hàng lân cận trong cùng một khối)
    for i, item in enumerate(processed):
        if item["is_blank"] or item["date"]:
            continue

        prev_date = ""
        for j in range(i - 1, -1, -1):
            if processed[j]["is_blank"]:
                break
            if processed[j]["date"]:
                prev_date = processed[j]["date"]
                break

        next_date = ""
        for j in range(i + 1, len(processed)):
            if processed[j]["is_blank"]:
                break
            if processed[j]["date"]:
                next_date = processed[j]["date"]
                break

        if prev_date and start_date <= prev_date <= end_date:
            item["date"] = prev_date
        elif next_date and start_date <= next_date <= end_date:
            item["date"] = next_date
        else:
            item["date"] = prev_date or next_date or ""

    filtered = []
    for item in processed:
        if item["is_blank"]:
            continue
        d = item["date"]
        if d and start_date <= d <= end_date:
            r = item["row"]
            r['담당자'] = _clean_assignees(r.get('담당자', '') or r.get('담당', ''))
            r['일자'] = d
            filtered.append(r)

    return filtered


def generate_weekly_report(cfg, assignee='all', period='this_week', start_date=None, end_date=None, lang='ko'):
    today = datetime.now()
    if period == 'this_week':
        start_dt = today - timedelta(days=today.weekday())
        end_dt = start_dt + timedelta(days=6)
        start_date = start_dt.strftime('%Y-%m-%d')
        end_date = end_dt.strftime('%Y-%m-%d')
    elif period == 'last_week':
        start_dt = today - timedelta(days=today.weekday() + 7)
        end_dt = start_dt + timedelta(days=6)
        start_date = start_dt.strftime('%Y-%m-%d')
        end_date = end_dt.strftime('%Y-%m-%d')
    else:
        if not start_date or not end_date:
            return {'ok': False, 'error': 'custom period requires start_date and end_date'}
            
    sheet_rows = fetch_sheet_rows(cfg)
    filtered_sheet = _resolve_and_filter_sheet_rows(sheet_rows, start_date, end_date)
    jira_rows = fetch_jira_rows(cfg, start_date, end_date)
    
    final_rows = []
    used_jira = set()
    for s_row in filtered_sheet:
        s_title = s_row.get('세부 업무명', '')
        s_names = set(_person_names(s_row.get('담당자', '')))
        s_date = s_row.get('일자', '')
        
        for i, j_row in enumerate(jira_rows):
            if i in used_jira: continue
            
            j_title = j_row.get('세부 업무명', '')
            j_names = set(_person_names(j_row.get('담당자', '')))
            
            # 같은 날짜 + 담당자 겹침 + 제목 유사 → 시트 행 우선, Jira 키만 보충
            if s_date == j_row.get('일자', '') and (s_names & j_names):
                j_title_clean = re.sub(r'\[.*?\]', '', j_title).strip()
                if len(j_title_clean) > 2 and (j_title_clean in s_title or s_title in j_title_clean):
                    used_jira.add(i)
                    break
                    
        final_rows.append(s_row)
            
    for i, j_row in enumerate(jira_rows):
        if i not in used_jira:
            final_rows.append(j_row)
    
    # 담당자 필터 (직함 유무와 관계없이 이름으로 비교)
    if assignee and assignee != 'all':
        target = _person_names(assignee)
        target = target[0] if target else assignee
        final_rows = [r for r in final_rows if target in _person_names(r.get('담당자', ''))]
                
    final_rows.sort(key=lambda x: (x.get('일자', '') or '9999-99-99', x.get('담당자', '')))
    
    tag = '전체' if (not assignee or assignee == 'all') else assignee
    ws_name = (cfg.get("workspace", {}).get("name") if cfg else None) or "JARVIS"
    report_suffix = "Weekly_Report" if lang == "en" else "주간업무보고서"
    filename = f"{ws_name}_{report_suffix}_{tag}_{start_date}_{end_date}.xlsx"
    reports_dir = os.path.join(DATA_DIR, 'reports')
    os.makedirs(reports_dir, exist_ok=True)
    filepath = os.path.join(reports_dir, filename)
    
    if os.path.isfile(CUSTOM_TEMPLATE_PATH):
        try:
            _render_custom_template(CUSTOM_TEMPLATE_PATH, final_rows, filepath, start_date, end_date, cfg, assignee)
        except Exception as e:
            log_line(f"[Report] 커스텀 템플릿 렌더링 실패({e}), 기본 서식으로 대체 생성합니다.")
            _generate_xlsx(final_rows, filepath, start_date, end_date, cfg, lang=lang)
    else:
        _generate_xlsx(final_rows, filepath, start_date, end_date, cfg, lang=lang)

    summary = _generate_summary(final_rows)
    summary['date_range'] = f"{start_date} ~ {end_date}"
    
    return {
        'ok': True,
        'file_path': filepath,
        'filename': filename,
        'download_url': f"/api/reports/download?file={urllib.parse.quote(filename)}",
        'summary': summary,
        'row_count': len(final_rows),
        'date_range': f"{start_date} ~ {end_date}",
    }

def _generate_xlsx(rows, filepath, start_date, end_date, cfg=None, lang="ko"):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Weekly_Report" if lang == "en" else "주간업무보고서"
    
    ws_name = (cfg.get("workspace", {}).get("name") if cfg else None) or "JARVIS"
    ws.merge_cells('A1:L1')
    title_cell = ws['A1']
    title_text = f"{ws_name} Weekly Work Report ({start_date} ~ {end_date})" if lang == "en" else f"{ws_name} 주간 업무 보고서 ({start_date} ~ {end_date})"
    title_cell.value = title_text
    title_cell.font = Font(name='Malgun Gothic', size=14, bold=True)
    title_cell.alignment = Alignment(horizontal='center', vertical='center')
    
    header_fill = PatternFill(start_color="37567E", end_color="37567E", fill_type="solid")
    header_font = Font(name='Malgun Gothic', size=10, bold=True, color="FFFFFF")
    header_alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
    thin_border = Border(left=Side(style='thin'), right=Side(style='thin'), top=Side(style='thin'), bottom=Side(style='thin'))
    
    active_columns = get_report_columns(lang)
    for col_idx, col_name in enumerate(active_columns, 1):
        cell = ws.cell(row=3, column=col_idx)
        cell.value = col_name
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = header_alignment
        cell.border = thin_border
        
    alt_fill = PatternFill(start_color="EAF0F8", end_color="EAF0F8", fill_type="solid")
    status_done_fill = PatternFill(start_color="E2F0D9", end_color="E2F0D9", fill_type="solid")
    status_inprog_sheet_fill = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")
    status_inprog_jira_fill = PatternFill(start_color="FDE9D9", end_color="FDE9D9", fill_type="solid")
    base_font = Font(name='Malgun Gothic', size=9)
    
    center_align = Alignment(horizontal='center', vertical='center')
    left_align = Alignment(horizontal='left', vertical='center')
    wrap_align = Alignment(horizontal='left', vertical='center', wrap_text=True)
    assignee_align = Alignment(horizontal='left', vertical='center', wrap_text=True)
    
    center_cols = ['구분', '유형', '일자', '진척(%)', '상태', '마감일']
    wrap_cols = ['상세내용', '사유(지연시)', '다음 계획']
    
    # 상태 열 인덱스 (1-based)
    status_col_idx = COLUMNS.index('상태') + 1
    
    for row_idx, r in enumerate(rows, 4):
        row_source = r.get('_source', 'sheet')
        row_status = r.get('상태', '')
        
        for col_idx, col_name in enumerate(COLUMNS, 1):
            cell = ws.cell(row=row_idx, column=col_idx)
            cell.value = r.get(col_name, '')
            cell.font = base_font
            cell.border = thin_border
            
            if row_idx % 2 == 1:
                cell.fill = alt_fill
            
            # 상태 열 배경색: 완료=#e2f0d9, 진행중(sheet)=#fff2cc, 진행중(jira)=#FDE9D9
            if col_name == '상태':
                if row_status == '완료':
                    cell.fill = status_done_fill
                elif row_status == '진행중':
                    if row_source == 'jira':
                        cell.fill = status_inprog_jira_fill
                    else:
                        cell.fill = status_inprog_sheet_fill
                
            if col_name == '담당자':
                cell.alignment = assignee_align
            elif col_name in center_cols:
                cell.alignment = center_align
            elif col_name in wrap_cols:
                cell.alignment = wrap_align
            else:
                cell.alignment = left_align

        # 상세내용 열(폭 60) 기준으로 줄 수를 추정해 행 높이 지정
        detail = str(r.get('상세내용', '') or '')
        assignee_text = str(r.get('담당자', '') or '')
        est_lines_detail = sum(max(1, -(-len(line) // 55)) for line in detail.split('\n')) if detail else 1
        est_lines_assignee = len(assignee_text.split('\n')) if assignee_text else 1
        est_lines = max(est_lines_detail, est_lines_assignee)
        ws.row_dimensions[row_idx].height = max(18, min(est_lines * 13, 400))

    col_widths = {
        'A': 8,  'B': 18, 'C': 14, 'D': 28, 'E': 7,  'F': 12,
        'G': 60, 'H': 7,  'I': 8,  'J': 12, 'K': 15, 'L': 20
    }
    for col, width in col_widths.items():
        ws.column_dimensions[col].width = width
        
    wb.save(filepath)
    return filepath

def _generate_summary(rows):
    total = len(rows)
    by_assignee = {}
    by_status = {}
    highlights = []
    tasks_list = []
    
    by_source = {"google_sheets": 0, "jira": 0}
    for r in rows:
        if r.get('_source') == 'jira' or r.get('유형') == 'jira':
            by_source['jira'] += 1
        else:
            by_source['google_sheets'] += 1

        for name in _person_names(r.get('담당자', '')):
            by_assignee[name] = by_assignee.get(name, 0) + 1
            
        status = r.get('상태', '')
        if status:
            by_status[status] = by_status.get(status, 0) + 1
            
        if status == '완료' and str(r.get('진척(%)')) == '100' and len(highlights) < 5:
            highlights.append(r.get('세부 업무명', ''))

        tasks_list.append({
            'date': r.get('일자', ''),
            'assignee': r.get('담당자', ''),
            'task': r.get('세부 업무명', ''),
            'status': r.get('상태', ''),
            'type': r.get('유형', ''),
            'source': 'jira' if (r.get('_source') == 'jira' or r.get('유형') == 'jira') else 'local_records'
        })
            
    return {
        'total_tasks': total,
        'by_source': by_source,
        'by_assignee': by_assignee,
        'by_status': by_status,
        'highlights': highlights,
        'tasks': tasks_list
    }


# ---------------------------------------------------------------------------
# Report Template Engine
# ---------------------------------------------------------------------------
def get_template_info():
    """Return status and info about uploaded custom template"""
    has_custom = os.path.isfile(CUSTOM_TEMPLATE_PATH)
    info = {
        "ok": True,
        "has_custom_template": has_custom,
        "template_name": "weekly_report_template.xlsx" if has_custom else "기본 빌트인 서식",
        "supported_tags": [
            "{{workspace_name}}", "{{start_date}}", "{{end_date}}", "{{date_range}}", "{{assignee}}",
            "{{category}}", "{{task_name}}", "{{subtask}}", "{{assignee}}", "{{type}}",
            "{{date}}", "{{details}}", "{{progress}}", "{{status}}", "{{due_date}}", "{{delay_reason}}", "{{next_plan}}"
        ]
    }
    if has_custom:
        try:
            st = os.stat(CUSTOM_TEMPLATE_PATH)
            info["size_bytes"] = st.st_size
            info["modified_at"] = datetime.fromtimestamp(st.st_mtime).isoformat()
        except Exception:
            pass
    return info


def save_custom_template(file_bytes):
    """Validate and save uploaded .xlsx template"""
    try:
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes))
        ws = wb.active
        if not ws:
            return {"ok": False, "error": "엑셀 워크시트를 찾을 수 없습니다."}
    except Exception as e:
        return {"ok": False, "error": f"유효하지 않은 Excel (.xlsx) 파일입니다: {str(e)}"}
    
    os.makedirs(TEMPLATES_DIR, exist_ok=True)
    with open(CUSTOM_TEMPLATE_PATH, "wb") as f:
        f.write(file_bytes)
    return {"ok": True, "message": "보고서 템플릿이 성공적으로 등록되었습니다."}


def delete_custom_template():
    """Remove custom template and revert to built-in default"""
    if os.path.isfile(CUSTOM_TEMPLATE_PATH):
        try:
            os.remove(CUSTOM_TEMPLATE_PATH)
            return {"ok": True, "message": "커스텀 템플릿이 삭제되었으며 기본 서식으로 복원되었습니다."}
        except Exception as e:
            return {"ok": False, "error": f"삭제 실패: {str(e)}"}
    return {"ok": True, "message": "이미 기본 서식을 사용 중입니다."}


def generate_sample_template_bytes(cfg=None):
    """Generate a downloadable sample Excel template containing tagged placeholders"""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "주간업무보고서"
    
    # Title
    ws.merge_cells('A1:L1')
    t_cell = ws['A1']
    t_cell.value = "{{workspace_name}} 주간 업무 보고서 ({{start_date}} ~ {{end_date}})"
    t_cell.font = Font(name='Malgun Gothic', size=14, bold=True)
    t_cell.alignment = Alignment(horizontal='center', vertical='center')
    
    # Subtitle
    ws.merge_cells('A2:L2')
    s_cell = ws['A2']
    s_cell.value = "보고 대상: {{assignee}}  |  기간: {{date_range}}"
    s_cell.font = Font(name='Malgun Gothic', size=10, italic=True)
    s_cell.alignment = Alignment(horizontal='right', vertical='center')
    
    # Headers
    h_fill = PatternFill(start_color="37567E", end_color="37567E", fill_type="solid")
    h_font = Font(name='Malgun Gothic', size=10, bold=True, color="FFFFFF")
    h_align = Alignment(horizontal='center', vertical='center')
    thin_border = Border(left=Side(style='thin'), right=Side(style='thin'), top=Side(style='thin'), bottom=Side(style='thin'))
    
    for c_idx, col_name in enumerate(COLUMNS, 1):
        c = ws.cell(row=3, column=c_idx)
        c.value = col_name
        c.fill = h_fill
        c.font = h_font
        c.alignment = h_align
        c.border = thin_border
        
    # Tagged Row (Row 4)
    tag_map = [
        "{{category}}", "{{task_name}}", "{{assignee}}", "{{subtask}}", "{{type}}", "{{date}}",
        "{{details}}", "{{progress}}", "{{status}}", "{{due_date}}", "{{delay_reason}}", "{{next_plan}}"
    ]
    t_font = Font(name='Malgun Gothic', size=9)
    for c_idx, tag in enumerate(tag_map, 1):
        c = ws.cell(row=4, column=c_idx)
        c.value = tag
        c.font = t_font
        c.border = thin_border
        c.alignment = Alignment(horizontal='center' if c_idx in (1, 5, 6, 8, 9, 10) else 'left', vertical='center')

    col_widths = {
        'A': 8,  'B': 18, 'C': 14, 'D': 28, 'E': 7,  'F': 12,
        'G': 60, 'H': 7,  'I': 8,  'J': 12, 'K': 15, 'L': 20
    }
    for col, width in col_widths.items():
        ws.column_dimensions[col].width = width

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _render_custom_template(template_path, rows, filepath, start_date, end_date, cfg, assignee="all"):
    """Load custom Excel template, substitute tags, duplicate row templates, and save."""
    wb = openpyxl.load_workbook(template_path)
    ws = wb.active

    ws_name = (cfg.get("workspace", {}).get("name") if cfg else None) or "JARVIS"
    target_assignee = assignee if (assignee and assignee != 'all') else "전체"
    date_range = f"{start_date} ~ {end_date}"

    # Global tag substitutions for static cells
    scalar_replacements = {
        "{{workspace_name}}": ws_name,
        "{{start_date}}": start_date,
        "{{end_date}}": end_date,
        "{{date_range}}": date_range,
        "{{assignee}}": target_assignee,
        "{{generated_at}}": datetime.now().strftime("%Y-%m-%d %H:%M")
    }

    # Tag to row field mapping
    TAG_FIELD_MAP = {
        "{{category}}": "구분",
        "{{구분}}": "구분",
        "{{task_name}}": "업무명",
        "{{task}}": "업무명",
        "{{업무명}}": "업무명",
        "{{assignee}}": "담당자",
        "{{담당자}}": "담당자",
        "{{subtask}}": "세부 업무명",
        "{{title}}": "세부 업무명",
        "{{세부 업무명}}": "세부 업무명",
        "{{type}}": "유형",
        "{{유형}}": "유형",
        "{{date}}": "일자",
        "{{일자}}": "일자",
        "{{details}}": "상세내용",
        "{{summary}}": "상세내용",
        "{{상세내용}}": "상세내용",
        "{{progress}}": "진척(%)",
        "{{진척}}": "진척(%)",
        "{{status}}": "상태",
        "{{상태}}": "상태",
        "{{due_date}}": "마감일",
        "{{마감일}}": "마감일",
        "{{delay_reason}}": "사유(지연시)",
        "{{사유}}": "사유(지연시)",
        "{{next_plan}}": "다음 계획",
        "{{다음 계획}}": "다음 계획"
    }

    # 1. Scan sheet to replace static header tags and locate template row
    template_row_idx = None
    row_tag_cols = {}
    row_cell_styles = {}

    max_r = ws.max_row
    max_c = ws.max_column

    for r_idx in range(1, max_r + 1):
        is_row_template = False
        detected_tags = {}
        for c_idx in range(1, max_c + 1):
            cell = ws.cell(row=r_idx, column=c_idx)
            if isinstance(cell, MergedCell) or type(cell).__name__ == 'MergedCell':
                continue
            val = cell.value
            if isinstance(val, str):
                val_clean = val.strip()
                matched_field = None
                for tag, field in TAG_FIELD_MAP.items():
                    if tag in val_clean:
                        matched_field = field
                        break
                if matched_field:
                    is_row_template = True
                    detected_tags[c_idx] = matched_field
                else:
                    new_val = val
                    for s_tag, s_rep in scalar_replacements.items():
                        if s_tag in new_val:
                            new_val = new_val.replace(s_tag, s_rep)
                    if new_val != val:
                        cell.value = new_val

        if is_row_template and template_row_idx is None:
            template_row_idx = r_idx
            row_tag_cols = detected_tags
            for c_idx in range(1, max_c + 1):
                c = ws.cell(row=r_idx, column=c_idx)
                if isinstance(c, MergedCell) or type(c).__name__ == 'MergedCell':
                    continue
                row_cell_styles[c_idx] = {
                    "font": c.font.copy() if c.font else None,
                    "border": c.border.copy() if c.border else None,
                    "fill": c.fill.copy() if c.fill else None,
                    "alignment": c.alignment.copy() if c.alignment else None,
                    "number_format": c.number_format
                }
            break

    # 2. If no template row tag was detected, use default append
    if not template_row_idx or not row_tag_cols:
        _generate_xlsx(rows, filepath, start_date, end_date, cfg)
        return filepath

    # 3. Populate rows
    current_r = template_row_idx
    for row_data in rows:
        for c_idx in range(1, max_c + 1):
            c = ws.cell(row=current_r, column=c_idx)
            if isinstance(c, MergedCell) or type(c).__name__ == 'MergedCell':
                continue
            if c_idx in row_cell_styles:
                st = row_cell_styles[c_idx]
                if st["font"]: c.font = st["font"]
                if st["border"]: c.border = st["border"]
                if st["fill"]: c.fill = st["fill"]
                if st["alignment"]: c.alignment = st["alignment"]
                if st["number_format"]: c.number_format = st["number_format"]

            field = row_tag_cols.get(c_idx)
            if field:
                c.value = row_data.get(field, "")
            else:
                c.value = ""

        detail = str(row_data.get('상세내용', '') or '')
        lines = len(detail.split('\n')) if detail else 1
        ws.row_dimensions[current_r].height = max(18, min(lines * 14, 400))
        current_r += 1

    wb.save(filepath)
    return filepath
