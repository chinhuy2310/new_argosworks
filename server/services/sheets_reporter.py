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

# Multilingual Columns Definition (Korean / English / Vietnamese)
REPORT_COLUMNS_I18N = {
    "ko": [
        '구분', '업무명', '담당자', '세부 업무명', '유형', '일자', 
        '상세내용', '진척(%)', '상태', '마감일', '사유(지연시)', '다음 계획'
    ],
    "en": [
        'Category', 'Project', 'Assignee', 'Task Name', 'Type', 'Date',
        'Details', 'Progress(%)', 'Status', 'Due Date', 'Delay Reason', 'Next Plan'
    ],
    "vi": [
        'Phân loại', 'Dự án', 'Người phụ trách', 'Nhiệm vụ chi tiết', 'Loại', 'Ngày',
        'Nội dung chi tiết', 'Tiến độ(%)', 'Trạng thái', 'Hạn chót', 'Lý do trễ hạn', 'Kế hoạch tiếp theo'
    ]
}

def get_report_columns(lang="ko"):
    """Returns report column headers in Korean, English, or Vietnamese (default: Korean)"""
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

def resolve_department(dept_input):
    """부서 ID, 이름, 약칭(alias)을 정규화하여 (canonical_id, display_name) 튜플을 반환한다."""
    if not dept_input or str(dept_input).strip().lower() in ('all', '전체', 'tất cả', 'tat_ca', ''):
        return None, None
    raw = str(dept_input).strip()
    low = raw.lower()

    try:
        from services.data_store import read_departments
        depts = read_departments()
    except Exception:
        depts = []

    # 1. Exact ID / Name / Prefix / JiraKey match
    for d in depts:
        did = str(d.get("id") or "").strip()
        dname = str(d.get("name") or "").strip()
        dprefix = str(d.get("localPrefix") or "").strip()
        djira = str(d.get("jiraKey") or "").strip()
        if low in (did.lower(), dname.lower(), dprefix.lower(), djira.lower()):
            return did, dname

    # 2. Common domain alias heuristics
    alias_map = {
        ("r&d", "rd", "rnd", "연구", "연구소", "개발", "개발팀", "nghiên cứu", "nghiencuu", "lab"): "lab",
        ("영업", "기술영업", "기술영업팀", "sales", "kinh doanh", "kinhdoanh"): "sales",
        ("생산", "생산팀", "production", "sản xuất", "sanxuat"): "dept_1a0a878496f",
    }
    for aliases, matched_id in alias_map.items():
        if any(a == low or low.startswith(a) or low.endswith(a) for a in aliases):
            for d in depts:
                if str(d.get("id") or "").strip().lower() == matched_id.lower():
                    return d["id"], d["name"]
            return matched_id, raw

    # 3. Substring match against department names
    for d in depts:
        dname = str(d.get("name") or "").strip()
        if low in dname.lower() or dname.lower() in low:
            return d["id"], dname

    return raw, raw

def _matches_department(row, target_dept_id, target_dept_name=None):
    """행(card/record)이 지정된 부서에 속하는지 판정한다."""
    if not target_dept_id:
        return True
    
    row_dept = str(row.get('dept_id') or row.get('_dept') or row.get('org') or '').strip().lower()
    tgt_id = str(target_dept_id).strip().lower()
    tgt_name = str(target_dept_name or '').strip().lower()

    if row_dept and (row_dept == tgt_id or (tgt_name and row_dept == tgt_name)):
        return True

    # 부서 정보가 누락된 경우 담당자의 소속 부서를 조회하여 매칭
    assignee = str(row.get('담당자') or '').strip()
    if assignee:
        try:
            from db import query
            names = _person_names(assignee)
            name_to_check = names[0] if names else assignee
            u_rows = query("SELECT dept_id FROM users WHERE name = ? OR username = ?", (name_to_check, name_to_check))
            for u in u_rows:
                u_dept = str(u.get("dept_id") or "").strip().lower()
                if u_dept == tgt_id or (tgt_name and u_dept == tgt_name):
                    return True
        except Exception:
            pass

    return False

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
                            cat = item.get("category", "연구")
                            task = item.get("task", "연구")
                            r_type = item.get("type", "일간")

                            # B2B Hierarchy Preservation:
                            # If ticket has an authoritative parent project/contract/epic (e.g. MAS, KC, IP, TEL),
                            # keep parentSummary as the task_name (업무명) instead of letting a generic
                            # subtask title or hardware model name overwrite it.
                            parent_s = str(rec.get("parentSummary") or rec.get("project") or "").strip()
                            rec_title = str(rec.get("title") or "").strip()
                            if parent_s and (not task or task == rec_title or task == "일반업무" or rec.get("isSubtask")):
                                task = parent_s

                            results[rid] = (cat, task, r_type)
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


def _extract_delay_and_rework(due_date, row_date, title, summary, comments, status):
    """'사유(지연시)'는 실제 일정이 지연(마감일 경과)되었거나 외부 요인으로 중단된 경우에만 기재.
    마감일이 지나지 않았고 정상 진행 중인 작업은 빈 문자열("") 유지 (사실 기반 0% 날조 원칙)."""
    if status in ['완료', 'done']:
        return ""

    ref_date = (row_date or datetime.now().strftime('%Y-%m-%d'))[:10]
    is_overdue = bool(due_date and str(due_date)[:10] < ref_date)

    combined = f"{title}\n{summary}\n" + "\n".join(comments or [])

    # 외부 요인으로 인한 명백한 작업 중단/지연 감지
    m_external = re.search(r'(?:규격 지속적인 변동|주무관 미 숙지|인허가 지연|외부 승인 대기|공급 차질|선적 지연|통관 지연|chờ duyệt|chờ linh kiện|tạm hoãn|block)[^.\n]*', combined, re.I)
    external_block = m_external.group(0).strip().lstrip('-*•0123456789. ') if m_external else ""

    if not is_overdue and not external_block:
        return ""

    reasons = []
    issue_patterns = [
        r'(?:오류|이상 발생|이상|불량|수리불가|연결 끊김|접속불가|lỗi|hỏng|không kết nối)[^.\n]*',
        r'(?:개선요청|시료 회수|교체로 대응|yêu cầu sửa|thu hồi)[^.\n]*',
        r'(?:감지하지 못함|실패|호환되지 않|thất bại|không tương thích)[^.\n]*',
        r'(?:서버 설치가 정상적으로 되지않아|지원요청|cần hỗ trợ)[^.\n]*',
    ]
    for pat in issue_patterns:
        m = re.search(pat, combined, re.I)
        if m:
            clean_r = m.group(0).strip().lstrip('-*•0123456789. ')
            if len(clean_r) > 4 and clean_r not in reasons:
                reasons.append(clean_r)

    reason_str = " / ".join(reasons[:2]) if reasons else external_block

    if is_overdue:
        prefix = f"[마감경과: {str(due_date)[:10]}]"
        return f"{prefix} {reason_str}".strip() if reason_str else prefix
    elif external_block:
        return external_block

    return ""


def _extract_next_plan_intelligent(title, summary, comments):
    """댓글의 '향후 계획'이나 문맥 상의 차주 예정 작업을 추출하고, 없을 시 빈 문자열("") 유지 (사실 기반 0% 날조 원칙)"""
    combined = f"{title}\n{summary}\n" + "\n".join(comments or [])

    m = re.search(r'(?:\[?향후\s*계획\]?|\[?다음\s*계획\]?|\[?차주\s*계획\]?|\[?kế hoạch tiếp theo\]?|\[?dự kiến tuần tới\]?)[:\s]*\n?([\s\S]+?)(?:\n\n|\n\[|\Z)', combined, re.I)
    if m:
        lines = [l.strip().lstrip('-*•0123456789. ') for l in m.group(1).split('\n') if l.strip()]
        if lines:
            return " / ".join(lines[:2])

    candidate = []
    for line in combined.split('\n'):
        line_clean = line.strip().lstrip('-*•0123456789. ')
        if re.match(r'^\[20\d\d[-./]\d\d[-./]\d\d.*?\]', line_clean):
            continue
        if any(kw in line_clean.lower() for kw in ['예정', '계획', '차주', 'dự kiến', 'kế hoạch', 'tuần tới', 'sẽ tiến hành', 'next week', 'upcoming', 'planned']):
            if len(line_clean) > 4 and line_clean not in candidate:
                candidate.append(line_clean)
    if candidate:
        return " / ".join(candidate[:2])

    return ""


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
        
        delay_val = _extract_delay_and_rework(r.get('dueDate'), row_date, r.get('title'), r.get('summary'), valid_comments, mapped_status)
        plan_val = _extract_next_plan_intelligent(r.get('title'), r.get('summary'), valid_comments)

        row = {
            '구분': mapped_cat,
            '업무명': mapped_task,
            '담당자': r.get('assignee', ''),
            'participants': r.get('participants') or '',
            '세부 업무명': r.get('title', ''),
            '유형': mapped_type or '일간',
            '일자': row_date,
            '상세내용': summary_text,
            '진척(%)': str(progress),
            '상태': mapped_status,
            '마감일': r.get('dueDate', ''),
            '사유(지연시)': delay_val,
            '다음 계획': plan_val,
            '_source': 'jira',
            '_jira_key': jira_key,
            'dept_id': r.get('dept_id') or r.get('org') or '',
            '_dept': r.get('dept_id') or r.get('org') or '',
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


def _deduplicate_and_merge_report_rows(rows):
    """B2B Weekly Report Row Deduplication & Aggregation:
    1. Deduplicates multiple tickets/records for the same task in the weekly period
       (same assignee, same project/task name, and same subtask title).
    2. Merges progressive daily updates (comments, status, progress) into a unified weekly record.
    3. Preserves distinct subtasks under different parent projects (e.g. MAS vs KC vs IP).
    """
    if not rows:
        return []

    merged = []
    seen_indices = {}

    for r in rows:
        r_copy = dict(r)
        assignee = _clean_assignees(r_copy.get('담당자', '') or '')
        assignee_names = _person_names(assignee)
        assignee_key = assignee_names[0] if assignee_names else assignee.strip()
        task_name = (r_copy.get('업무명', '') or '').strip()
        subtask_title = (r_copy.get('세부 업무명', '') or '').strip()
        jira_key = (r_copy.get('_jira_key', '') or '').strip().upper()

        group_key = (assignee_key, task_name.lower(), subtask_title.lower())

        if group_key in seen_indices:
            idx = seen_indices[group_key]
            target = merged[idx]

            # 1. Update date to latest date in the period
            curr_date = str(target.get('일자', '') or '')
            new_date = str(r_copy.get('일자', '') or '')
            if new_date and (not curr_date or new_date > curr_date):
                target['일자'] = new_date

            # 2. Update progress to highest progress
            try:
                curr_prog = int(target.get('진척(%)', 0))
            except Exception:
                curr_prog = 0
            try:
                new_prog = int(r_copy.get('진척(%)', 0))
            except Exception:
                new_prog = 0
            target['진척(%)'] = str(max(curr_prog, new_prog))

            # 3. Status: '완료' takes precedence, otherwise preserve latest
            curr_status = target.get('상태', '')
            new_status = r_copy.get('상태', '')
            if curr_status in ['완료', 'done'] or new_status in ['완료', 'done']:
                target['상태'] = '완료'
            elif new_status and not curr_status:
                target['상태'] = new_status

            # 4. Merge details and comments cleanly without duplicating text lines
            target_desc = (target.get('상세내용', '') or '').strip()
            new_desc = (r_copy.get('상세내용', '') or '').strip()

            if new_desc and new_desc != target_desc:
                if not target_desc:
                    target['상세내용'] = new_desc
                elif target_desc == subtask_title and new_desc != subtask_title:
                    target['상세내용'] = new_desc
                elif new_desc != subtask_title:
                    existing_lines = [ln.strip() for ln in target_desc.split('\n') if ln.strip()]
                    to_add = [ln for ln in new_desc.split('\n') if ln.strip() and ln.strip() not in existing_lines]
                    if to_add:
                        target['상세내용'] = target_desc + "\n" + "\n".join(to_add)

            # 5. Metadata fields
            if not target.get('마감일') and r_copy.get('마감일'):
                target['마감일'] = r_copy['마감일']
            if not target.get('사유(지연시)') and r_copy.get('사유(지연시)'):
                target['사유(지연시)'] = r_copy['사유(지연시)']
            if not target.get('다음 계획') and r_copy.get('다음 계획'):
                target['다음 계획'] = r_copy['다음 계획']

            # 6. Combined Jira key references
            if jira_key and jira_key not in (target.get('_jira_key', '') or ''):
                curr_jk = target.get('_jira_key', '')
                target['_jira_key'] = f"{curr_jk}, {jira_key}" if curr_jk else jira_key

            if not target.get('dept_id') and r_copy.get('dept_id'):
                target['dept_id'] = r_copy.get('dept_id')
                target['_dept'] = r_copy.get('dept_id')

            p_target = target.get('participants') or ''
            p_new = r_copy.get('participants') or ''
            if p_new and p_new not in p_target:
                target['participants'] = f"{p_target}, {p_new}" if p_target else p_new

        else:
            seen_indices[group_key] = len(merged)
            merged.append(r_copy)

    return merged

def generate_weekly_report(cfg, assignee='all', period='this_week', start_date=None, end_date=None, lang='ko', dept=None, custom_columns=None):
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
    
    # B2B Deduplication & Aggregation
    final_rows = _deduplicate_and_merge_report_rows(final_rows)

    # 1. 부서 필터
    canonical_dept_id, dept_display = resolve_department(dept)
    if canonical_dept_id:
        final_rows = [r for r in final_rows if _matches_department(r, canonical_dept_id, dept_display)]
    
    # 2. 담당자 필터 (직함 유무와 관계없이 이름으로 비교, 참여자 participants 포함하여 누락 방지)
    if assignee and assignee != 'all':
        target = _person_names(assignee)
        target = target[0] if target else assignee
        target_lower = target.lower()
        final_rows = [
            r for r in final_rows
            if target in _person_names(r.get('담당자', '')) or target_lower in str(r.get('participants', '')).lower()
        ]
                
    final_rows.sort(key=lambda x: (x.get('일자', '') or '9999-99-99', x.get('담당자', '')))
    
    ws_name = (cfg.get("workspace", {}).get("name") if cfg else None) or "ARGOS WORKS"
    ws_clean = re.sub(r'[^\w\.-]', '_', ws_name)

    parts = []
    if dept_display:
        parts.append(re.sub(r'[^\w\.-]', '_', dept_display))
    if assignee and assignee != 'all':
        parts.append(re.sub(r'[^\w\.-]', '_', assignee))

    if parts:
        tag = "_".join(parts)
    else:
        tag = "ALL" if lang == "en" else ("Tat_ca" if lang == "vi" else "전체")

    if lang == "en":
        report_suffix = "Weekly_Report"
    elif lang == "vi":
        report_suffix = "Bao_cao_tuan"
    else:
        report_suffix = "주간업무보고서"

    filename = f"{ws_clean}_{report_suffix}_{tag}_{start_date}_{end_date}.xlsx"
    reports_dir = os.path.join(DATA_DIR, 'reports')
    os.makedirs(reports_dir, exist_ok=True)
    filepath = os.path.join(reports_dir, filename)
    
    if custom_columns and isinstance(custom_columns, list) and len(custom_columns) > 0:
        _generate_custom_columns_xlsx(
            final_rows, filepath, start_date, end_date, custom_columns,
            cfg=cfg, lang=lang, dept_name=dept_display, assignee=assignee
        )
    elif os.path.isfile(CUSTOM_TEMPLATE_PATH):
        try:
            _render_custom_template(CUSTOM_TEMPLATE_PATH, final_rows, filepath, start_date, end_date, cfg, assignee=assignee, dept_name=dept_display, lang=lang)
        except Exception as e:
            log_line(f"[Report] 커스텀 템플릿 렌더링 실패({e}), 기본 서식으로 대체 생성합니다.")
            _generate_xlsx(final_rows, filepath, start_date, end_date, cfg, lang=lang, dept_name=dept_display, assignee=assignee)
    else:
        _generate_xlsx(final_rows, filepath, start_date, end_date, cfg, lang=lang, dept_name=dept_display, assignee=assignee)

    summary = _generate_summary(final_rows)
    summary['date_range'] = f"{start_date} ~ {end_date}"
    if dept_display:
        summary['department'] = dept_display
    
    return {
        'ok': True,
        'file_path': filepath,
        'filename': filename,
        'download_url': f"/api/reports/download?file={urllib.parse.quote(filename)}",
        'summary': summary,
        'row_count': len(final_rows),
        'date_range': f"{start_date} ~ {end_date}",
        'department': dept_display,
    }

def _generate_xlsx(rows, filepath, start_date, end_date, cfg=None, lang="ko", dept_name=None, assignee=None):
    wb = openpyxl.Workbook()
    ws = wb.active
    if lang == "en":
        ws.title = "Weekly_Report"
    elif lang == "vi":
        ws.title = "Bao_cao_tuan"
    else:
        ws.title = "주간업무보고서"
    
    ws_name = (cfg.get("workspace", {}).get("name") if cfg else None) or "ARGOS WORKS"
    ws.merge_cells('A1:L1')
    title_cell = ws['A1']
    dept_prefix = f" [{dept_name}]" if dept_name else ""
    if lang == "en":
        title_text = f"{ws_name}{dept_prefix} Weekly Work Report ({start_date} ~ {end_date})"
    elif lang == "vi":
        title_text = f"{ws_name}{dept_prefix} Báo Cáo Công Việc Tuần ({start_date} ~ {end_date})"
    else:
        title_text = f"{ws_name}{dept_prefix} 주간 업무 보고서 ({start_date} ~ {end_date})"
    title_cell.value = title_text
    title_cell.font = Font(name='Malgun Gothic', size=14, bold=True)
    title_cell.alignment = Alignment(horizontal='center', vertical='center')

    # Subtitle with Department & Assignee & Date Range
    ws.merge_cells('A2:L2')
    s_cell = ws['A2']
    dept_val = dept_name or ("ALL" if lang == "en" else ("Tất cả" if lang == "vi" else "전체"))
    assignee_val = assignee if (assignee and assignee != 'all') else ("ALL" if lang == "en" else ("Tất cả" if lang == "vi" else "전체"))
    if lang == "en":
        s_cell.value = f"Department: {dept_val}  |  Assignee: {assignee_val}  |  Period: {start_date} ~ {end_date}"
    elif lang == "vi":
        s_cell.value = f"Phòng ban: {dept_val}  |  Phụ trách: {assignee_val}  |  Kỳ báo cáo: {start_date} ~ {end_date}"
    else:
        s_cell.value = f"부서: {dept_val}  |  보고 대상: {assignee_val}  |  기간: {start_date} ~ {end_date}"
    s_cell.font = Font(name='Malgun Gothic', size=10, italic=True)
    s_cell.alignment = Alignment(horizontal='right', vertical='center')
    
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

def _generate_custom_columns_xlsx(rows, filepath, start_date, end_date, custom_columns, cfg=None, lang="ko", dept_name=None, assignee=None):
    wb = openpyxl.Workbook()
    ws = wb.active
    if lang == "en":
        ws.title = "Weekly_Report"
    elif lang == "vi":
        ws.title = "Bao_cao_tuan"
    else:
        ws.title = "주간업무보고서"

    num_cols = max(len(custom_columns), 1)
    end_col_letter = openpyxl.utils.get_column_letter(num_cols)

    ws_name = (cfg.get("workspace", {}).get("name") if cfg else None) or "ARGOS WORKS"
    ws.merge_cells(f'A1:{end_col_letter}1')
    title_cell = ws['A1']
    dept_prefix = f" [{dept_name}]" if dept_name else ""
    if lang == "en":
        title_text = f"{ws_name}{dept_prefix} Custom Work Report ({start_date} ~ {end_date})"
    elif lang == "vi":
        title_text = f"{ws_name}{dept_prefix} Báo Cáo Công Việc Tùy Biến ({start_date} ~ {end_date})"
    else:
        title_text = f"{ws_name}{dept_prefix} 맞춤형 업무 보고서 ({start_date} ~ {end_date})"
    title_cell.value = title_text
    title_cell.font = Font(name='Malgun Gothic', size=14, bold=True)
    title_cell.alignment = Alignment(horizontal='center', vertical='center')

    # Subtitle with Department & Assignee & Date Range
    ws.merge_cells(f'A2:{end_col_letter}2')
    s_cell = ws['A2']
    dept_val = dept_name or ("ALL" if lang == "en" else ("Tất cả" if lang == "vi" else "전체"))
    assignee_val = assignee if (assignee and assignee != 'all') else ("ALL" if lang == "en" else ("Tất cả" if lang == "vi" else "전체"))
    if lang == "en":
        s_cell.value = f"Department: {dept_val}  |  Assignee: {assignee_val}  |  Period: {start_date} ~ {end_date}"
    elif lang == "vi":
        s_cell.value = f"Phòng ban: {dept_val}  |  Phụ trách: {assignee_val}  |  Kỳ báo cáo: {start_date} ~ {end_date}"
    else:
        s_cell.value = f"부서: {dept_val}  |  보고 대상: {assignee_val}  |  기간: {start_date} ~ {end_date}"
    s_cell.font = Font(name='Malgun Gothic', size=10, italic=True)
    s_cell.alignment = Alignment(horizontal='right', vertical='center')

    # Headers
    header_fill = PatternFill(start_color="37567E", end_color="37567E", fill_type="solid")
    header_font = Font(name='Malgun Gothic', size=10, bold=True, color="FFFFFF")
    header_alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
    thin_border = Border(left=Side(style='thin'), right=Side(style='thin'), top=Side(style='thin'), bottom=Side(style='thin'))

    def _get_col_header(col):
        if isinstance(col, dict):
            return str(col.get("header") or col.get("name") or col.get("title") or col.get("field") or "")
        return str(col)

    for col_idx, col_item in enumerate(custom_columns, 1):
        cell = ws.cell(row=3, column=col_idx)
        cell.value = _get_col_header(col_item)
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

    def _resolve_col_value(col, r):
        c_field = ""
        c_header = ""
        if isinstance(col, dict):
            c_field = str(col.get("field") or col.get("key") or "").lower().strip()
            c_header = str(col.get("header") or col.get("name") or col.get("title") or "").lower().strip()
        else:
            c_header = str(col).lower().strip()

        combined_k = f"{c_field} {c_header}".strip()

        if c_field in ['key', 'jira_key', 'code', 'id', 'issue_key'] or any(k in combined_k for k in ['mã', 'key', 'code', 'id', '코드']):
            return r.get('_jira_key') or r.get('jira_key') or str(r.get('id', ''))
        if c_field in ['project', 'epic', 'parent'] or any(k in combined_k for k in ['dự án', 'project', '과제', '업무명']):
            return r.get('업무명') or r.get('project') or ''
        if c_field in ['title', 'summary', 'name', 'task'] or any(k in combined_k for k in ['nhiệm vụ', 'tiêu đề', 'task', 'title', '세부']):
            return r.get('세부 업무명') or r.get('title') or ''
        if c_field in ['assignee', 'owner'] or any(k in combined_k for k in ['chính', 'phụ trách', 'assignee', '담당자']):
            return r.get('담당자') or r.get('assignee') or ''
        if c_field in ['participants', 'collaborators', 'members'] or any(k in combined_k for k in ['tham gia', 'phối hợp', 'participant', '참여']):
            return r.get('participants') or ''
        if c_field in ['type', 'category'] or any(k in combined_k for k in ['loại', 'phân loại', 'category', 'type', '구분', '유형']):
            return r.get('구분') or r.get('유형') or r.get('category') or ''
        if c_field in ['date'] or any(k in combined_k for k in ['ngày', 'date', '일자']):
            return r.get('일자') or r.get('date') or ''
        if c_field in ['due_date', 'deadline', 'due'] or any(k in combined_k for k in ['hạn', 'deadline', 'due', '마감']):
            return r.get('마감일') or r.get('dueDate') or ''
        if c_field in ['status', 'state'] or any(k in combined_k for k in ['trạng thái', 'status', '상태']):
            return r.get('상태') or r.get('status') or ''
        if c_field in ['progress', 'percent', 'percentage'] or any(k in combined_k for k in ['tiến độ', 'progress', '%', '진척']):
            p = r.get('진척(%)', '')
            if str(p).strip() != '':
                return str(p) if '%' in str(p) else f"{p}%"
            return ''
        if c_field in ['detail', 'description', 'content'] or any(k in combined_k for k in ['chi tiết', 'nội dung', 'detail', 'summary', '상세']):
            return r.get('상세내용') or r.get('summary') or ''
        if c_field in ['delay', 'blocker', 'delay_reason', 'issue'] or any(k in combined_k for k in ['nghẽn', 'khó khăn', 'chậm', 'trễ', 'delay', 'blocker', '사유', '이슈']):
            return r.get('사유(지연시)') or ''
        if c_field in ['plan', 'next_plan', 'future_plan'] or any(k in combined_k for k in ['kế hoạch', 'tiếp theo', 'tuần tới', 'next', 'plan', '계획']):
            return r.get('다음 계획') or ''
        if c_field in ['dept', 'department', 'org'] or any(k in combined_k for k in ['phòng', 'bộ phận', 'dept', '부서']):
            return r.get('dept_id') or r.get('_dept') or ''
        return r.get(c_field, '') if c_field else r.get(c_header, '')

    for row_idx, r in enumerate(rows, 4):
        row_source = r.get('_source', 'sheet')
        row_status = r.get('상태', '')

        for col_idx, col_item in enumerate(custom_columns, 1):
            cell = ws.cell(row=row_idx, column=col_idx)
            val = _resolve_col_value(col_item, r)
            cell.value = val
            cell.font = base_font
            cell.border = thin_border

            if row_idx % 2 == 1:
                cell.fill = alt_fill

            c_text = _get_col_header(col_item).lower()
            if any(k in c_text for k in ['trạng thái', 'status', '상태']):
                if row_status in ['완료', 'done']:
                    cell.fill = status_done_fill
                elif row_status in ['진행중', 'in progress']:
                    cell.fill = status_inprog_jira_fill if row_source == 'jira' else status_inprog_sheet_fill

            if any(k in c_text for k in ['ngày', 'hạn', 'trạng thái', 'tiến độ', 'mã', 'loại', 'date', 'status', '%', 'code']):
                cell.alignment = center_align
            elif any(k in c_text for k in ['chi tiết', 'nội dung', 'nghẽn', 'khó khăn', 'kế hoạch', 'detail', 'summary']):
                cell.alignment = wrap_align
            else:
                cell.alignment = left_align

        max_len = max(len(str(_resolve_col_value(col_item, r) or '')) for col_item in custom_columns) if custom_columns else 1
        est_lines = max(1, max_len // 40)
        ws.row_dimensions[row_idx].height = max(18, min(est_lines * 14, 400))

    # Auto column widths
    for col_idx, col_item in enumerate(custom_columns, 1):
        col_letter = openpyxl.utils.get_column_letter(col_idx)
        c_low = _get_col_header(col_item).lower()
        if any(k in c_low for k in ['chi tiết', 'nội dung', 'detail', 'summary']):
            ws.column_dimensions[col_letter].width = 45
        elif any(k in c_low for k in ['nghẽn', 'khó khăn', 'kế hoạch', 'next', 'delay']):
            ws.column_dimensions[col_letter].width = 30
        elif any(k in c_low for k in ['dự án', 'nhiệm vụ', 'tiêu đề', 'task', 'project']):
            ws.column_dimensions[col_letter].width = 25
        elif any(k in c_low for k in ['mã', 'ngày', 'hạn', 'trạng thái', 'người', 'phụ trách', 'tham gia']):
            ws.column_dimensions[col_letter].width = 16
        else:
            ws.column_dimensions[col_letter].width = 14

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
            "{{workspace_name}}", "{{start_date}}", "{{end_date}}", "{{date_range}}",
            "{{dept}}", "{{department}}", "{{phong_ban}}", "{{부서}}",
            "{{assignee}}", "{{category}}", "{{task_name}}", "{{subtask}}", "{{type}}",
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
    s_cell.value = "부서: {{dept}}  |  보고 대상: {{assignee}}  |  기간: {{date_range}}"
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


def _render_custom_template(template_path, rows, filepath, start_date, end_date, cfg, assignee="all", dept_name=None, lang="ko"):
    """Load custom Excel template, substitute tags, duplicate row templates, and save."""
    wb = openpyxl.load_workbook(template_path)
    ws = wb.active

    ws_name = (cfg.get("workspace", {}).get("name") if cfg else None) or "ARGOS WORKS"
    target_assignee = assignee if (assignee and assignee != 'all') else ("ALL" if lang == "en" else ("Tất cả" if lang == "vi" else "전체"))
    target_dept = dept_name if dept_name else ("ALL" if lang == "en" else ("Tất cả" if lang == "vi" else "전체"))
    date_range = f"{start_date} ~ {end_date}"

    # Global tag substitutions for static cells
    scalar_replacements = {
        "{{workspace_name}}": ws_name,
        "{{start_date}}": start_date,
        "{{end_date}}": end_date,
        "{{date_range}}": date_range,
        "{{assignee}}": target_assignee,
        "{{dept}}": target_dept,
        "{{department}}": target_dept,
        "{{phong_ban}}": target_dept,
        "{{부서}}": target_dept,
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
        "{{다음 계획}}": "다음 계획",
        "{{participants}}": "participants",
        "{{참여자}}": "participants",
        "{{nguoi_tham_gia}}": "participants",
        "{{key}}": "_jira_key",
        "{{jira_key}}": "_jira_key",
        "{{code}}": "_jira_key",
        "{{card_code}}": "_jira_key" 
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
        _generate_xlsx(rows, filepath, start_date, end_date, cfg, lang=lang, dept_name=dept_name, assignee=assignee)
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
                orig_val = ws.cell(row=template_row_idx, column=c_idx).value
                if orig_val and isinstance(orig_val, str) and orig_val.startswith("="):
                    c.value = orig_val
                elif orig_val and not str(orig_val).startswith("{{"):
                    c.value = orig_val
                else:
                    c.value = ""

        detail = str(row_data.get('상세내용', '') or '')
        lines = len(detail.split('\n')) if detail else 1
        ws.row_dimensions[current_r].height = max(18, min(lines * 14, 400))
        current_r += 1

    wb.save(filepath)
    return filepath
