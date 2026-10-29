import json
import re
import base64
import ssl
import threading
import time
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime

import os
from utils.logging import log_line
from utils.text import assignee_base_name, _adf_to_text, parse_iso_timestamp
from config import JIRA_AUTO_SYNC_INTERVAL_SEC, BASE_DIR
from services.data_store import read_records

def _urlopen(req, timeout=15, cfg=None):
    """
    안전한 Jira API HTTP 요청 호출기.
    기본적으로 엄격한 SSL/TLS 인증서 검증을 수행하며,
    환경 변수 JIRA_INSECURE_SKIP_VERIFY=true 또는 config의 jira.insecure_skip_verify=true가 
    명시적으로 활성화된 내부 프록시/특수 사내망 환경에서만 예외적으로 unverified context 폴백을 허용한다.
    """
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.URLError as e:
        allow_insecure = False
        if os.environ.get("JIRA_INSECURE_SKIP_VERIFY", "").lower() in ("1", "true", "yes"):
            allow_insecure = True
        elif cfg and cfg.get("jira", {}).get("insecure_skip_verify"):
            allow_insecure = True

        if "CERTIFICATE_VERIFY_FAILED" in str(e):
            if allow_insecure:
                log_line("[SECURITY WARNING] Jira SSL 인증서 검증 실패 (JIRA_INSECURE_SKIP_VERIFY=true 로 인해 우회 허용됨)")
                ctx = ssl._create_unverified_context()
                return urllib.request.urlopen(req, timeout=timeout, context=ctx)
            log_line(f"[SECURITY ALERT] Jira SSL 인증서 검증 실패: {e}. MITM 방어를 위해 연결을 차단했습니다.")

        # Never return None here: callers use `with _urlopen(...) as resp`, and a
        # swallowed error surfaces as the useless
        # "'NoneType' object does not support the context manager protocol".
        raise
# Configurable ongoing exclude categories (overrideable via env or config)
JIRA_ONGOING_EXCLUDE_CATEGORIES = [c.strip() for c in os.environ.get("JIRA_ONGOING_EXCLUDE_CATEGORIES", "메인,메인프로젝트").split(",") if c.strip()]

_jira_cache_lock = threading.Lock()
_jira_cache = {"records": None, "activities": [], "categories": {}, "synced_at": None, "error": None}


def invalidate_jira_cache():
    """Xoá cache Jira trong RAM (dùng khi admin đổi config/alias) để lần đọc sau nạp lại/đồng bộ lại."""
    with _jira_cache_lock:
        _jira_cache["records"] = None
        _jira_cache["activities"] = []
        _jira_cache["categories"] = {}
        _jira_cache["synced_at"] = None
        _jira_cache["error"] = None

def _jira_auth_header(j):
    auth = base64.b64encode((j["email"] + ":" + j["api_token"]).encode("utf-8")).decode("ascii")
    return {
        "Authorization": "Basic " + auth,
        "Content-Type": "application/json",
        "Accept": "application/json"
    }


def _verify_jira_auth(j, timeout=10):
    """자격 증명이 실제로 유효한지 /myself 로 확인한다.

    Jira Cloud의 /rest/api/3/search/jql 은 인증 실패(만료/폐기된 토큰, 권한 없음)
    에도 HTTP 200 + {"issues": []} 를 돌려준다. 반면 /rest/api/3/myself 는 401 을
    돌려주므로, 빈 검색 결과를 '정말 0건'으로 믿기 전에 이 엔드포인트로 확인해야
    '만료된 토큰인데 화면에는 연결 정상/0건'으로 보이는 상황을 막을 수 있다.

    반환: (ok: bool, error: str|None)
    """
    base_url = (j.get("base_url") or "").rstrip("/")
    if not base_url:
        return False, "base_url is not configured"
    req = urllib.request.Request(base_url + "/rest/api/3/myself", method="GET", headers=_jira_auth_header(j))
    try:
        with _urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                return True, None
            return False, "HTTP %s" % resp.status
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        return False, "HTTP %s: %s" % (e.code, body[:300])
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# User aliases (bidirectional)
# ---------------------------------------------------------------------------
# config.json:
#   "jira": { "user_aliases": { "<tên trong ARGOS>": "<tên/username/email trong Jira>" } }
# hoặc key cấp root "jira_user_aliases" (tương thích cũ).
# Cùng một map được dùng cho CẢ HAI chiều:
#   local -> Jira : khi tìm accountId để gán assignee/reporter
#   Jira -> local : khi đồng bộ issue về (assignee hiển thị/nhận diện là tên local)


def get_user_aliases(cfg):
    """Trả về {tên local: tham chiếu Jira} (giữ nguyên chữ hoa/thường để hiển thị)."""
    if not cfg:
        return {}
    j = cfg.get("jira") or {}
    raw = cfg.get("jira_user_aliases") or j.get("user_aliases") or {}
    aliases = {}
    if isinstance(raw, dict):
        for local_name, jira_ref in raw.items():
            if local_name and jira_ref:
                aliases[str(local_name).strip()] = str(jira_ref).strip()
    return aliases


def resolve_local_to_jira_query(cfg, name):
    """Tên local -> giá trị dùng để search bên Jira (không phân biệt hoa/thường, bỏ chức danh)."""
    clean = (name or "").strip()
    if not clean:
        return clean
    aliases = get_user_aliases(cfg)
    if not aliases:
        return clean
    lowered = clean.lower()
    base = assignee_base_name(clean).lower()
    for local_name, jira_ref in aliases.items():
        if lowered == local_name.lower() or base == assignee_base_name(local_name).lower():
            return jira_ref
    return clean


def resolve_jira_to_local_name(cfg, jira_name, jira_email=None):
    """Tên (hoặc email) bên Jira -> tên local tương ứng nếu có alias. Không có thì giữ nguyên."""
    original = (jira_name or "").strip()
    aliases = get_user_aliases(cfg)
    if not aliases:
        return original

    targets = set()
    for value in (original, (jira_email or "").strip()):
        if value:
            targets.add(value.lower())
            targets.add(assignee_base_name(value).lower())
    if not targets:
        return original

    for local_name, jira_ref in aliases.items():
        refs = {jira_ref.lower(), assignee_base_name(jira_ref).lower()}
        if refs & targets:
            return local_name
    return original


def _normalize_cached_assignee(cfg, record):
    """Chuẩn hoá assignee của một record Jira (đã cache) sang tên local nếu có alias."""
    if not isinstance(record, dict):
        return record
    raw_name = record.get("assignee") or ""
    if not raw_name or raw_name == "미배정":
        return record
    jira_meta = record.get("jira") or {}
    if "displayAssignee" not in jira_meta:
        jira_meta["displayAssignee"] = raw_name
        record["jira"] = jira_meta
    record["assignee"] = resolve_jira_to_local_name(cfg, raw_name, record.get("assigneeEmail"))
    return record


def check_jira_connection_status(cfg):
    """
    Jira 연동 상태 확인:
    1. 관리자가 Jira 연동을 활성화했는지 (enabled == True)
    2. 필수 접속 정보(base_url, email, api_token)가 구성되어 있는지
    3. 실제 Jira Cloud API 연결에 오류가 없는지 (최근 동기화 오류 여부)
    반환: (is_ready: bool, message: str)
    """
    j = cfg.get("jira", {}) if cfg else {}
    if not j.get("enabled"):
        return False, "Jira 연동이 비활성화되어 있습니다."
    if not j.get("base_url") or not j.get("email") or not j.get("api_token"):
        return False, "Jira 연동 접속 정보(URL, 이메일, API 토큰)가 누락되었습니다."
    
    with _jira_cache_lock:
        err = _jira_cache.get("error")
        synced_at = _jira_cache.get("synced_at")
        records = _jira_cache.get("records")
    
    if err:
        return False, f"Jira 연결 오류: {err}"
    
    # 캐시가 아직 동기화되지 않은 경우 myself 호출로 실시간 검증
    if synced_at is None or records is None:
        try:
            base_url = j["base_url"].rstrip("/")
            req = urllib.request.Request(f"{base_url}/rest/api/2/myself", headers=_jira_auth_header(j))
            with _urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    return True, "Jira 정상 연결됨"
                else:
                    return False, f"Jira 응답 오류 (HTTP {resp.status})"
        except Exception as e:
            return False, f"Jira 연결 실패: {str(e)}"

    return True, "Jira 정상 연결됨"

def jira_project_for_dept(cfg, dept_id):
    """부서 id에 매핑된 Jira 프로젝트키/이슈유형을 반환한다. 매핑이 없거나 비어있으면
    부서의 jiraKey 또는 default_project_key/default_issue_type으로 대체한다."""
    j = cfg.get("jira", {})
    mapping = j.get("project_map", {}).get(dept_id) or {}
    project_key = mapping.get("project_key") or ""
    issue_type = mapping.get("issue_type") or ""

    if not project_key:
        try:
            from services.data_store import read_departments
            for d in read_departments():
                if d["id"] == dept_id and d.get("jiraKey"):
                    project_key = d["jiraKey"]
                    break
        except Exception as e:
            log_line("[jira_client] Error reading departments for project key resolution:", e)

    if not project_key:
        project_key = j.get("default_project_key") or ""
    if not issue_type:
        issue_type = j.get("default_issue_type") or "Task"

    if not project_key or not issue_type:
        return None, None
    return project_key, issue_type

def jira_project_keys(cfg):
    """project_map 및 부서 설정에 실제로 연결된 모든 Jira 프로젝트 키 목록 (중복 제거)."""
    j = cfg.get("jira", {})
    keys = set()
    for mapping in j.get("project_map", {}).values():
        pk = mapping.get("project_key")
        if pk:
            keys.add(pk)
    try:
        from services.data_store import read_departments
        for d in read_departments():
            if d.get("jiraKey"):
                keys.add(d["jiraKey"])
    except Exception:
        pass
    if j.get("default_project_key"):
        keys.add(j["default_project_key"])
    return sorted(keys)

def jira_dept_for_project_key(cfg, project_key):
    """project_key로 부서 id를 찾는다. 못 찾으면 빈 문자열."""
    for dept_id, mapping in cfg.get("jira", {}).get("project_map", {}).items():
        if mapping.get("project_key") == project_key:
            return dept_id
    try:
        from services.data_store import read_departments
        for d in read_departments():
            if d.get("jiraKey") and d["jiraKey"].upper() == (project_key or "").upper():
                return d["id"]
    except Exception:
        pass
    return ""

def my_jira_records(cfg, name, org, email=None):
    """로그인한 사람이 담당자로 찍혀 있는 Jira 캐시 레코드만 추려서 돌려준다.

    매칭 우선순위:
      1) email (Jira 공개 프로필에 email이 노출된 경우) — chính xác nhất
      2) tên đã chuẩn hoá (bỏ chức danh) + alias 2 chiều (`jira.user_aliases`)
    org: nếu record có phòng và khác phòng user thì bỏ; record chưa map phòng (org rỗng)
    vẫn được xét để thẻ Jira không bị "mồ côi".
    """
    if not (cfg.get("jira", {}) if cfg else {}).get("enabled"):
        return []
    cache = get_cached_jira_records(cfg)
    records = cache.get("records") or []

    my_email = (email or "").strip().lower()
    my_org = (org or "").strip().lower()

    # Tên local hiện tại + giá trị alias (Jira) tương ứng, đều đã bỏ chức danh
    candidate_names = set()
    for candidate in (name, resolve_local_to_jira_query(cfg, name)):
        if candidate:
            candidate_names.add(assignee_base_name(candidate).strip().lower())
    candidate_names.discard("")

    matched = []
    for r in records:
        rec_org = (r.get("org") or "").strip().lower()
        if rec_org and my_org and rec_org != my_org:
            continue  # 명확히 다른 부서 → 동명이인 오매칭 방지
        rec_email = (r.get("assigneeEmail") or "").strip().lower()
        if rec_email and my_email and rec_email == my_email:
            matched.append(r)
            continue
        rec_assignee = assignee_base_name(r.get("assignee") or "").strip().lower()
        if rec_assignee and rec_assignee in candidate_names:
            matched.append(r)
    return matched


def jira_due_date_events_for(cfg, name, org, email=None):
    """캘린더가 로그인한 사람 몫으로 자동 표시할 Jira 마감일(dueDate) 기반 일정을 만든다."""
    if not (cfg.get("jira", {}) if cfg else {}).get("enabled"):
        return []
    out = []
    # account_key 함수를 복사하거나 수정해서 임시로 쓰기 위해 inline 구현
    def account_key(n, o):
        return (n or "").strip() + "|" + (o or "").strip()
    
    for r in my_jira_records(cfg, name, org, email):
        start_date = r.get("startDate")
        due_date = r.get("dueDate")
        if not start_date and not due_date:
            continue
        if r.get("category") in JIRA_ONGOING_EXCLUDE_CATEGORIES:
            continue  # "메인" 등 컨테이너성 이슈는 혹시 마감일이 찍혀 있어도 개인 일정처럼 보여주지 않음
        jira = r.get("jira") or {}
        s_date = start_date or due_date
        e_date = due_date or start_date
        out.append({
            "id": "jira-cal-" + jira.get("key", r.get("id", "")),
            "ownerKey": account_key(name, org),
            "ownerName": name, "ownerOrg": org, "ownerEmail": "",
            "type": r.get("category", "") or "Jira",
            "title": r.get("title", ""),
            "startDate": s_date,
            "endDate": e_date,
            "memo": r.get("summary", ""),
            "createdAt": "",
            "source": "jira",
            "jira": jira
        })
    return out

def all_jira_due_date_events(cfg, records=None):
    """모든 팀원의 일정(시작일 또는 마감일 기반) Jira 일정을 반환한다."""
    if not (cfg.get("jira", {}) if cfg else {}).get("enabled"):
        return []
    out = []
    def account_key(n, o):
        return (n or "").strip() + "|" + (o or "").strip()

    if records is None:
        cache = get_cached_jira_records(cfg)
        records = cache.get("records") or []
    for r in records:
        start_date = r.get("startDate")
        due_date = r.get("dueDate")
        if not start_date and not due_date:
            continue
        if r.get("category") in JIRA_ONGOING_EXCLUDE_CATEGORIES:
            continue
        assignee = r.get("assignee") or "미지정"
        org = r.get("org") or ""
        jira = r.get("jira") or {}

        s_date = start_date or due_date
        e_date = due_date or start_date

        out.append({
            "id": "jira-cal-" + jira.get("key", r.get("id", "")),
            "ownerKey": account_key(assignee, org),
            "ownerName": assignee,
            "ownerOrg": org,
            "ownerEmail": "",
            "type": r.get("category", "") or "Jira",
            "title": r.get("title", ""),
            "startDate": s_date,
            "endDate": e_date,
            "memo": r.get("summary", ""),
            "createdAt": "",
            "source": "jira",
            "jira": jira,
            "cardCode": jira.get("key") or ""
        })
    return out

def jira_ongoing_records_for(cfg, name, org, email=None):
    """마감일이 없어서 캘린더 날짜 칸에는 표시할 수 없는, 로그인한 사람 담당의 '진행 중' Jira 이슈 목록."""
    if not (cfg.get("jira", {}) if cfg else {}).get("enabled"):
        return []
    out = []
    for r in my_jira_records(cfg, name, org, email):
        if r.get("dueDate"):
            continue  # 마감일이 있으면 캘린더 쪽(jira_due_date_events_for)에서 이미 보여줌
        if r.get("category") in JIRA_ONGOING_EXCLUDE_CATEGORIES:
            continue  # "메인" 등 컨테이너성 이슈는 원래 마감일 개념이 없으므로 제외
        jira = r.get("jira") or {}
        if jira.get("status") == "good":  # 완료된 건 "진행중" 목록에 안 보여줌
            continue
        out.append({
            "title": r.get("title", ""),
            "category": r.get("category", "") or "Jira",
            "statusName": jira.get("statusName", ""),
            "jira": jira
        })
    return out

def jira_search_issues(cfg, max_results=2000, page_size=200, since_updated=None):
    """config.json의 project_map에 연결된 모든 Jira 프로젝트에서 실제로 등록되어 있는
    이슈를 그대로 가져와, JARVIS 대시보드가 쓰는 '기록' 형태로 변환해 돌려준다.

    주의: 예전에는 한 페이지(최대 200건)만 조회해서, 매핑된 프로젝트들의 이슈가 총
    200건을 넘으면 뒤쪽 이슈가 조용히 누락되고(= 담당자별 업무 갯 처가 실제보다 적게
    집계됨) 있었다. 지금은 Jira Cloud의 새 검색 API가 주는 nextPageToken을 따라
    끝까지(또는 안전 상한 max_results까지) 페이지를 이어서 가져온다.

    반환값 규칙(캐시 쪽에서 '진짜 0건'과 '조회 자체가 실패함'을 구분해야 하므로 중요):
      - Jira 연동이 꺼져 있거나 연결된 프로젝트가 하나도 없으면: 빈 리스트 [] (정상, 0건)
      - 네트워크/인증/API 오류 등으로 조회 자체가 실패하면: None (실패 — 캐시에서 이전
        목록을 그대로 유지시키기 위한 신호). 단, 이미 몇 페이지를 받아온 뒤 그 다음
        페이지에서 실패한 경우에는 그때까지 받아온 이슈만이라도 돌려준다(완전 실패보다
        부분 결과가 낫다)."""
    j = cfg.get("jira", {})
    if not j.get("enabled") or not j.get("api_token") or not j.get("email"):
        return [], []
    keys = jira_project_keys(cfg)
    if not keys:
        return [], []

    base_url = j["base_url"].rstrip("/")
    if since_updated:
        clean_since = since_updated.replace("T", " ")[:16]
        jql = 'project in (%s) AND updated >= "%s" ORDER BY updated DESC' % (", ".join(keys), clean_since)
    else:
        jql = "project in (%s) ORDER BY updated DESC" % ", ".join(keys)
    fields = ["summary", "description", "status", "issuetype", "assignee",
              "reporter", "created", "labels", "project", "duedate", "customfield_10015", "parent", "subtasks", "comment", "attachment"]

    all_issues = []
    next_token = None
    first_page = True
    while len(all_issues) < max_results:
        # Use GET /rest/api/3/search/jql with expand=changelog to fetch real operation history
        url = f"{base_url}/rest/api/3/search/jql?jql={urllib.parse.quote(jql)}&maxResults={min(page_size, max_results - len(all_issues))}&fields={','.join(fields)}&expand=changelog"
        if next_token:
            url += f"&nextPageToken={urllib.parse.quote(next_token)}"
        req = urllib.request.Request(url, method="GET", headers=_jira_auth_header(j))
        try:
            with _urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            # Fallback to POST if GET fails
            try:
                post_body = json.dumps({
                    "jql": jql,
                    "maxResults": min(page_size, max_results - len(all_issues)),
                    "fields": fields
                }).encode("utf-8")
                req_post = urllib.request.Request(base_url + "/rest/api/3/search/jql", data=post_body, method="POST", headers=_jira_auth_header(j))
                with _urlopen(req_post, timeout=15) as resp_post:
                    data = json.loads(resp_post.read().decode("utf-8"))
            except Exception as e2:
                if first_page:
                    log_line("Jira 이슈 목록 조회 실패(이전 캐시 유지):", e, e2)
                    return None, None
                log_line("Jira 이슈 목록 추가 페이지 조회 실패(그때까지 받은 %d건만 사용):" % len(all_issues), e)
                break
        first_page = False
        issues = data.get("issues", []) or []
        all_issues.extend(issues)
        next_token = data.get("nextPageToken")
        if not next_token or not issues:
            break

    if not all_issues:
        # Jira Cloud는 미인증/권한없음 검색에도 200 + 빈 결과를 주기 때문에,
        # 빈 결과를 그대로 '0건'으로 처리하면 만료된 토큰이 '연결 정상·0건'으로 보인다.
        auth_ok, auth_err = _verify_jira_auth(j)
        if not auth_ok:
            log_line("Jira 인증 확인 실패 — 이전 캐시를 유지합니다:", auth_err)
            return None, None

    out = []
    activities = []
    seen_act_keys = set()

    for issue in all_issues:
        f = issue.get("fields", {}) or {}
        project = f.get("project") or {}
        project_key = project.get("key", "")
        dept_id = jira_dept_for_project_key(cfg, project_key)
        dept_name = project.get("name") or "연구소"
        labels = f.get("labels") or []
        category = ""
        for lb in labels:
            if lb.startswith("분류_"):
                category = lb[len("분류_"):]
                break
        if not category:
            category = (f.get("issuetype") or {}).get("name") or "미분류"
        status = f.get("status") or {}
        raw_status_name = (status.get("name") or "").strip()
        status_cat = (status.get("statusCategory") or {}).get("key", "")
        # Normalize status names: chỉ 완료된 업무/완료/Done -> 완료 và 진행 중/진행중/In Progress -> 진행
        if "완료" in raw_status_name or raw_status_name.lower() == "done" or status_cat == "done":
            status_name = "완료"
        elif "진행" in raw_status_name or "progress" in raw_status_name.lower():
            status_name = "진행"
        else:
            status_name = raw_status_name
        assignee_obj = f.get("assignee") or {}
        raw_assignee_name = assignee_obj.get("displayName") or "미배정"
        assignee_email = (assignee_obj.get("emailAddress") or "").strip()
        # Jira -> local 방향 alias: nhận diện thẻ bằng tên local để "Việc của tôi",
        # lịch cá nhân và phân quyền hoạt động đúng dù tên 2 bên khác nhau.
        assignee_name = raw_assignee_name
        if raw_assignee_name != "미배정":
            assignee_name = resolve_jira_to_local_name(cfg, raw_assignee_name, assignee_email)
        raw_avatar = (assignee_obj.get("avatarUrls") or {}).get("48x48") or (assignee_obj.get("avatarUrls") or {}).get("32x32") or ""
        assignee_avatar = raw_avatar if ("default-avatar" not in raw_avatar and "default/" not in raw_avatar) else ""
        reporter_name = (f.get("reporter") or {}).get("displayName") or ""
        summary_text = f.get("summary") or "(제목 없음)"
        desc_text = _adf_to_text(f.get("description")) or summary_text
        created = (f.get("created") or "")[:10]
        due_date = (f.get("duedate") or "")[:10]
        start_date = (f.get("customfield_10015") or "")[:10]
        key = issue.get("key", "")
        parent_obj = f.get("parent") or {}
        parent_key = parent_obj.get("key") or ""
        parent_summary = (parent_obj.get("fields") or {}).get("summary") or ""
        subtasks_list = [s.get("key") for s in (f.get("subtasks") or []) if s.get("key")]
        # Jira Cloud issuetype: subtask is True ONLY for actual leaf subtasks (e.g. '하위 작업', hierarchyLevel = -1).
        # Standard issues (e.g. '현장', '메인프로젝트', hierarchyLevel = 0) can have parents (Epic/메인) AND can have subtasks!
        raw_is_subtask = bool((f.get("issuetype") or {}).get("subtask"))
        type_name = ((f.get("issuetype") or {}).get("name") or "").strip()
        is_subtask = raw_is_subtask or (type_name == "하위 작업" or "sub" in type_name.lower())
        can_create_subtask = not is_subtask

        # 1. Extract comments from Jira API
        comments_list = []
        raw_comments = (f.get("comment") or {}).get("comments") or []
        for c in raw_comments:
            c_author = (c.get("author") or {}).get("displayName") or "사용자"
            c_body = _adf_to_text(c.get("body")) if isinstance(c.get("body"), dict) else str(c.get("body") or "")
            c_created = (c.get("created") or "")[:19]
            if c_body.strip():
                # Extract actual author if comment was posted with signature (e.g. (최성호-Argos works))
                m_auth = re.search(r'\((?:작성자:\s*)?([^\s\)-]+?)(?:-|\s*-\s*)(?:Argos\s*works|Agros\s*works|JARVIS|Choivis)\)', c_body, re.IGNORECASE)
                if m_auth:
                    c_author = m_auth.group(1).strip()
                comments_list.append({
                    "id": str(c.get("id") or ""),
                    "author": c_author,
                    "body": c_body.strip(),
                    "created": c_created,
                    "source": "jira"
                })

        # Check local comments from external legacy DB only if explicitly configured in environment
        try:
            choivis_db_path = os.environ.get("EXTERNAL_COMMENTS_DB_PATH")
            if choivis_db_path and os.path.isfile(choivis_db_path):
                import sqlite3
                conn_c = sqlite3.connect(choivis_db_path)
                cur_c = conn_c.cursor()
                cur_c.execute("SELECT author_name, body, created_at FROM local_comments WHERE issue_key = ? ORDER BY created_at ASC", (key,))
                for row in cur_c.fetchall():
                    c_auth = row[0] or "사용자"
                    c_text = row[1] or ""
                    c_time = (row[2] or "")[:19]
                    if c_text.strip() and not any(c_text[:30] in jc["body"] for jc in comments_list):
                        comments_list.append({
                            "id": "local",
                            "author": c_auth,
                            "body": c_text.strip(),
                            "created": c_time,
                            "source": "local"
                        })
                conn_c.close()
        except Exception as e:
            log_line("[jira_client] Error reading departments for project key resolution:", e)

        # Extract attachments from Jira
        attachments_list = []
        for a in (f.get("attachment") or []):
            if a.get("filename"):
                a_id = str(a.get("id") or "")
                attachments_list.append({
                    "id": a_id,
                    "name": a.get("filename"),
                    "size": a.get("size", 0),
                    "url": f"/api/jira/attachments/{a_id}" if a_id else (a.get("content", "") or "#"),
                    "isLocal": False,
                    "source": "jira"
                })

        out.append({
            "id": "jira-" + key,
            "org": dept_id,
            "category": category,
            "title": summary_text[:40] + ("…" if len(summary_text) > 40 else ""),
            "project": project.get("name", ""),
            "assignee": assignee_name,
            "assigneeEmail": assignee_email,
            "assigneeAvatar": assignee_avatar,
            "avatarUrl": assignee_avatar,
            "date": created,
            "startDate": start_date,
            "dueDate": due_date,
            "summary": desc_text[:500],
            "tags": [t for t in [category, status_name] if t],
            "memo": desc_text,
            "attachments": attachments_list,
            "comments": comments_list,
            "parentKey": parent_key,
            "parentSummary": parent_summary,
            "subtasks": subtasks_list,
            "isSubtask": is_subtask,
            "canCreateSubtask": can_create_subtask,
            "jira": {
                "key": key,
                "summary": summary_text,
                "url": base_url + "/browse/" + key,
                "status": "good" if status_cat == "done" else "info",
                "statusName": status_name,
                "rawStatusName": raw_status_name,
                "reporter": reporter_name,
                "displayAssignee": raw_assignee_name,
                "parentKey": parent_key,
                "isSubtask": is_subtask,
                "canCreateSubtask": can_create_subtask,
                "assigneeAvatar": assignee_avatar
            }
        })

        # 2. Extract detailed changelog activities
        cl = issue.get("changelog") or {}
        for h in (cl.get("histories") or []):
            h_id = h.get("id") or str(len(activities))
            author_name = (h.get("author") or {}).get("displayName") or "Jira 사용자"
            author_avatar = (h.get("author") or {}).get("avatarUrls", {}).get("48x48")
            created_at = parse_iso_timestamp(h.get("created"))
            for it in (h.get("items") or []):
                field = (it.get("field") or "").lower()
                from_str = it.get("fromString") or ""
                to_str = it.get("toString") or ""

                # Ignore redundant resolution field (e.g. resolution: Done accompanying status change)
                if field == "resolution":
                    continue

                act_id = f"jira_chg_{h_id}_{field}"
                if act_id in seen_act_keys:
                    continue
                seen_act_keys.add(act_id)

                action_type = "updated"
                action_detail = f"{it.get('field')}: {to_str}"

                if field == "status":
                    action_type = "status_change"
                    action_detail = f"{from_str} ➔ {to_str}"
                elif field == "attachment":
                    action_type = "attachment"
                    action_detail = to_str or from_str
                elif field == "comment":
                    action_type = "comment"
                    action_detail = to_str or from_str
                elif field == "assignee":
                    action_type = "updated"
                    action_detail = f"담당자 변경: {from_str} ➔ {to_str}"
                elif field in ("duedate", "마감일"):
                    d_from = (it.get("from") or from_str or "")[:10]
                    d_to = (it.get("to") or to_str or "")[:10]
                    action_detail = f"마감일 변경: {d_from} ➔ {d_to}" if d_from else f"마감일 설정: {d_to}"
                elif field in ("start date", "시작일"):
                    d_from = (it.get("from") or from_str or "")[:10]
                    d_to = (it.get("to") or to_str or "")[:10]
                    action_detail = f"시작일 변경: {d_from} ➔ {d_to}" if d_from else f"시작일 설정: {d_to}"
                elif field == "summary":
                    action_detail = f"제목 수정: {to_str}"
                elif field in ("description", "설명"):
                    action_detail = "설명 내용 수정"
                elif field == "reporter":
                    action_detail = f"보고자 변경: {from_str} ➔ {to_str}"
                elif field == "issueparentassociation":
                    action_detail = f"상위 작업 연결: {to_str}"

                activities.append({
                    "id": act_id,
                    "issue_key": key,
                    "action_type": action_type,
                    "action_detail": action_detail,
                    "author_name": author_name,
                    "author_avatar": author_avatar,
                    "created_at": created_at,
                    "summary": summary_text,
                    "status": status_name,
                    "priority": "보통",
                    "issue_type": category,
                    "assignee_name": assignee_name,
                    "assignee_dept": dept_name,
                    "source": "jira"
                })

        # 3. Issue Creation Event
        iss_created = parse_iso_timestamp(f.get("created"))
        act_create_id = f"jira_create_{key}"
        if act_create_id not in seen_act_keys:
            seen_act_keys.add(act_create_id)
            activities.append({
                "id": act_create_id,
                "issue_key": key,
                "action_type": "created",
                "action_detail": "새 작업 생성",
                "author_name": reporter_name or assignee_name or "Jira 사용자",
                "author_avatar": None,
                "created_at": iss_created,
                "summary": summary_text,
                "status": status_name,
                "priority": "보통",
                "issue_type": category,
                "assignee_name": assignee_name,
                "assignee_dept": dept_name,
                "source": "jira"
            })

    activities.sort(key=lambda a: a.get("created_at", ""), reverse=True)
    return out, activities

def jira_fetch_project_categories(cfg, project_key):
    """해당 Jira 프로젝트("스페이스")에 실제로 설정되어 있는 이슈 타입 목록을 그대로
    가져온다 — 이게 곧 그 스페이스에서 이미 나눠놓은 '업무 카테고리'다. 하위 작업
    (Subtask)은 부모 이슈가 있어야만 만들 수 있어서 제출 폼에는 노출하지 않는다.
    실패하면 빈 리스트를 반환한다(이 함수의 실패가 폼 전체를 막지 않도록)."""
    j = cfg.get("jira", {})
    if not j.get("enabled") or not j.get("api_token") or not j.get("email") or not project_key:
        return []
    base_url = j["base_url"].rstrip("/")
    req = urllib.request.Request(base_url + "/rest/api/3/project/" + urllib.parse.quote(project_key),
                                  method="GET", headers=_jira_auth_header(j))
    try:
        with _urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        log_line("Jira 프로젝트 이슈 타입(카테고리) 조회 실패:", project_key, e)
        return []
    out = []
    for it in data.get("issueTypes", []) or []:
        if it.get("subtask"):
            continue
        # 주의: 이름 앞뒤 공백을 트림하지 않고 그대로 둔다 — Jira는 이슈 타입을
        # 이름으로 정확히 매칭하기 때문에(예: 실제 이름이 " Mas"처럼 앞에 공백이
        # 있는 경우), 트림해서 돌려주면 나중에 그 이름으로 생성 요청을 보낼 때
        # "이슈 타입 없음" 오류가 난다. 완전히 빈 이름만 걸러낸다.
        name = it.get("name") or ""
        if name.strip():
            out.append(name)
    return out

def jira_fetch_project_subtask_type(cfg, project_key):
    """해당 Jira 프로젝트의 하위 작업(Sub-task) 이슈 타입 이름을 가져온다.
    못 찾으면 '하위 작업' 또는 'Sub-task'를 기본값으로 반환한다."""
    j = cfg.get("jira", {})
    if not j.get("enabled") or not j.get("api_token") or not j.get("email") or not project_key:
        return "하위 작업"
    base_url = j["base_url"].rstrip("/")
    req = urllib.request.Request(base_url + "/rest/api/3/project/" + urllib.parse.quote(project_key),
                                  method="GET", headers=_jira_auth_header(j))
    try:
        with _urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        for it in data.get("issueTypes", []) or []:
            if it.get("subtask"):
                name = it.get("name") or ""
                if name.strip():
                    return name
    except Exception as e:
        log_line("Jira 하위 작업 이슈 타입 조회 실패:", project_key, e)
    return "하위 작업"

def jira_auto_sync_loop(cfg):
    """Jira 연동이 켜져 있는 동안, 별도 데몬 스레드에서 주기적으로 캐시를 다시 채운다.
    한 번의 동기화 실패가 루프 자체를 죽이지 않도록 매 회차를 개별적으로 감싼다."""
    while True:
        time.sleep(JIRA_AUTO_SYNC_INTERVAL_SEC)
        try:
            sync_jira_cache(cfg)
        except Exception as e:
            log_line("Jira 자동 동기화 중 오류(다음 주기에 재시도):", e)

def sync_jira_cache(cfg, force_full=False):
    """Jira를 실제로 조회해서 DB(SQLite)와 캐시를 갱신한다. Jira 연동이 비활성화되어 있으면 빈 캐시를 반환한다."""
    j = cfg.get("jira", {}) if cfg else {}
    if not j.get("enabled"):
        with _jira_cache_lock:
            _jira_cache["records"] = []
            _jira_cache["activities"] = []
            _jira_cache["categories"] = {}
            _jira_cache["error"] = None
            _jira_cache["synced_at"] = None
        return dict(_jira_cache)

    from services.jira_db import (
        get_last_sync_time, set_last_sync_time, upsert_jira_records, load_all_jira_from_db,
        upsert_jira_activities, load_all_jira_activities_from_db
    )

    last_sync = None if force_full else get_last_sync_time()
    res = jira_search_issues(cfg, since_updated=last_sync)
    if isinstance(res, tuple) and len(res) == 2:
        records, activities = res
    else:
        records, activities = res, []
    now = datetime.now().isoformat()

    # DB에 UPSERT 저장
    if records is not None:
        if records:
            upsert_jira_records(records)
            try:
                from services.vector_store import trigger_async_vector_sync
                trigger_async_vector_sync(cfg)
            except Exception:
                pass
        if activities:
            upsert_jira_activities(activities)
        set_last_sync_time(now)
        all_records = load_all_jira_from_db()
        all_activities = load_all_jira_activities_from_db()
    else:
        all_records = None
        all_activities = None

    categories = {}
    for dept_id, mapping in cfg.get("jira", {}).get("project_map", {}).items():
        project_key = mapping.get("project_key")
        if not project_key:
            continue
        cats = jira_fetch_project_categories(cfg, project_key)
        categories[dept_id] = cats  # 실패 시 빈 리스트 — 아래에서 이전 값과 병합

    with _jira_cache_lock:
        if all_records is None:
            _jira_cache["error"] = "Jira 조회 실패로 이전 목록을 그대로 보여줍니다 (서버 콘솔 로그 참고)."
            if _jira_cache["records"] is None:
                # DB에서 기존 저장된 데이터 복원
                db_recs = load_all_jira_from_db()
                _jira_cache["records"] = db_recs or []
                _jira_cache["activities"] = load_all_jira_activities_from_db() or []
        else:
            _jira_cache["records"] = all_records
            _jira_cache["activities"] = all_activities if all_activities is not None else (activities or [])
            _jira_cache["error"] = None
        for dept_id, cats in categories.items():
            if cats or dept_id not in _jira_cache["categories"]:
                _jira_cache["categories"][dept_id] = cats
        _jira_cache["synced_at"] = now
        return dict(_jira_cache)

def get_cached_jira_records(cfg):
    """Jira가 비활성화된 경우 빈 레코드 반환. 캐시가 비어있으면 DB에서 로드."""
    if not (cfg.get("jira", {}) if cfg else {}).get("enabled"):
        return {"records": [], "activities": [], "categories": {}, "error": None, "synced_at": None}
    with _jira_cache_lock:
        primed = _jira_cache["records"] is not None
    if not primed:
        from services.jira_db import load_all_jira_from_db, load_all_jira_activities_from_db
        db_recs = load_all_jira_from_db()
        if db_recs:
            # Áp alias Jira -> local cho cache cũ (đã lưu từ phiên bản trước).
            db_recs = [_normalize_cached_assignee(cfg, dict(r)) for r in db_recs]
            db_acts = load_all_jira_activities_from_db()
            with _jira_cache_lock:
                _jira_cache["records"] = db_recs
                _jira_cache["activities"] = db_acts or []
                _jira_cache["synced_at"] = datetime.now().isoformat()
            return dict(_jira_cache)
        return sync_jira_cache(cfg)
    with _jira_cache_lock:
        return dict(_jira_cache)


def find_issue_key_by_attachment_id(cfg, attachment_id):
    """첨부파일 ID로 소속 Jira 이슈 키를 찾는다 (DB → 캐시 순). 찾지 못하면 빈 문자열."""
    aid = str(attachment_id or "").strip()
    if not aid:
        return ""

    try:
        from db import get_one
        row = get_one(
            "SELECT jira_key FROM jira_attachments WHERE attachment_id = ? LIMIT 1",
            (aid,)
        )
        if row and row.get("jira_key"):
            return str(row["jira_key"]).strip().upper()
    except Exception:
        pass

    try:
        for r in (get_cached_jira_records(cfg).get("records") or []):
            for a in (r.get("attachments") or []):
                if str(a.get("id") or "").strip() == aid:
                    return ((r.get("jira") or {}).get("key") or "").strip().upper()
    except Exception:
        pass
    return ""


def get_cached_jira_activities(cfg):
    """캐시된 Jira 변경 이력(Changelog) 활동 목록을 반환한다."""
    if not (cfg.get("jira", {}) if cfg else {}).get("enabled"):
        return []
    with _jira_cache_lock:
        has_acts = bool(_jira_cache.get("activities"))
    if not has_acts:
        from services.jira_db import load_all_jira_activities_from_db
        db_acts = load_all_jira_activities_from_db()
        if db_acts:
            with _jira_cache_lock:
                _jira_cache["activities"] = db_acts
            return db_acts
        sync_jira_cache(cfg)
    with _jira_cache_lock:
        return list(_jira_cache.get("activities") or [])

def get_cached_categories(cfg, dept_id):
    """부서 id에 연결된 Jira 프로젝트의 실제 이슈 타입(=업무 카테고리) 목록을 캐시에서 돌려준다."""
    if not (cfg.get("jira", {}) if cfg else {}).get("enabled"):
        return []
    with _jira_cache_lock:
        primed = _jira_cache["records"] is not None
    if not primed:
        sync_jira_cache(cfg)
    with _jira_cache_lock:
        return list(_jira_cache["categories"].get(dept_id, []))

def lookup_jira_account_id(cfg, query):
    """이메일 또는 이름으로 Jira 계정을 찾아 accountId를 반환한다. 못 찾으면 None.
    이 accountId는 Jira 티켓의 '보고자(Reporter)'와 '담당자(assignee)' 양쪽에 그대로
    넣는다 — 두 필드 모두 이 Jira 사이트에서 API로 편집 가능한 것을 실제로 확인했다.
    즉 실제로 포털에 제출한 그 사람이 Jira에도 본인 이름으로 찍힌다."""
    j = cfg.get("jira", {})
    if not query or not j.get("enabled") or not j.get("api_token") or not j.get("email"):
        return None
    base_url = j["base_url"].rstrip("/")

    # 사용자 별칭 및 직급 접미사 처리 (config.json 또는 환경 설정에서 동적으로 로드)
    clean_query = (query or "").strip()
    # local -> Jira 방향 alias (대소문자/직급 접미사 무시)
    search_query = resolve_local_to_jira_query(cfg, clean_query)

    url = base_url + "/rest/api/3/user/search?query=" + urllib.parse.quote(search_query)
    req = urllib.request.Request(url, method="GET", headers=_jira_auth_header(j))
    try:
        with _urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if isinstance(data, list) and data:
            # Jira's user/search is fuzzy: "김철수" can also return "김철수2" or a
            # same-surname colleague. Prefer an exact match (email / username /
            # display name / base name) before falling back to the first result,
            # otherwise a card can be assigned to the wrong person.
            query_norm = (search_query or "").strip().lower()
            query_base = assignee_base_name(search_query).strip().lower()

            def _is_exact(user):
                if not isinstance(user, dict):
                    return False
                email = (user.get("emailAddress") or "").strip().lower()
                name = (user.get("displayName") or "").strip().lower()
                nick = (user.get("nickname") or user.get("name") or "").strip().lower()
                if query_norm and query_norm in (email, name, nick):
                    return True
                return bool(query_base and assignee_base_name(user.get("displayName") or "").strip().lower() == query_base)

            for user in data:
                if _is_exact(user):
                    return user.get("accountId")
            return data[0].get("accountId")
    except Exception as e:
        log_line("Jira 사용자 검색 실패(무시하고 담당자 미지정으로 진행):", query, e)
    return None

def create_jira_issue(cfg, project_key, issue_type, summary, description_text, labels, due_date,
                       submitter_account_id=None, parent_key=None, start_date=None, assignee_account_id=None):
    """실제 제출자를 Jira의 보고자(Reporter), 지정된 사람 또는 제출자를 담당자(assignee)에 지정해서 티켓을 만든다.
    시작 날짜(start_date, customfield_10015)와 마감일(due_date)을 모두 지원한다."""
    j = cfg.get("jira", {})
    if not j.get("enabled") or not j.get("api_token") or not j.get("email"):
        return None, "Jira 연동이 config.json에 설정되어 있지 않습니다."

    base_url = j["base_url"].rstrip("/")

    # Assignee priority: specific assignee_account_id if given, else submitter_account_id
    effective_assignee_id = assignee_account_id or submitter_account_id

    def build_fields(include_reporter, include_assignee, include_start_date=True):
        f = {
            "project": {"key": project_key},
            "summary": summary[:250],
            "issuetype": {"name": issue_type},
            "labels": labels,
            "description": {
                "type": "doc", "version": 1,
                "content": [{"type": "paragraph", "content": [
                    {"type": "text", "text": description_text or "(내용 없음)"}
                ]}]
            }
        }
        if parent_key:
            f["parent"] = {"key": parent_key}
        if due_date:
            f["duedate"] = due_date
        if start_date and include_start_date:
            f["customfield_10015"] = start_date
        if submitter_account_id and include_reporter:
            f["reporter"] = {"accountId": submitter_account_id}
        if effective_assignee_id and include_assignee:
            f["assignee"] = {"accountId": effective_assignee_id}
        return f

    include_reporter, include_assignee, include_start = True, True, True
    dropped = []
    label_map = {"reporter": "보고자", "assignee": "담당자", "customfield_10015": "시작 날짜"}

    for attempt in range(3):
        fields = build_fields(include_reporter, include_assignee, include_start)
        body = json.dumps({"fields": fields}).encode("utf-8")
        req = urllib.request.Request(
            base_url + "/rest/api/3/issue",
            data=body, method="POST",
            headers=_jira_auth_header(j)
        )
        try:
            with _urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            key = data.get("key")
            if not effective_assignee_id:
                note = "담당자 계정을 Jira에서 찾지 못해 담당자 미지정(서비스 계정)으로 생성했습니다. Jira에서 직접 지정해주세요."
            elif dropped:
                note = "이 프로젝트에서는 %s 필드를 API로 지정할 수 없어 제외되었습니다." % "·".join(dropped)
            else:
                note = None
            return {"key": key, "status": "info", "url": base_url + "/browse/" + key}, note
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", "replace")
            log_line("Jira 티켓 생성 실패:", e.code, err_body)
            if attempt < 2:
                retry = False
                for field_key, field_label in label_map.items():
                    if field_key in err_body:
                        if field_key == "reporter" and include_reporter:
                            include_reporter = False
                            dropped.append(field_label)
                            retry = True
                        if field_key == "assignee" and include_assignee:
                            include_assignee = False
                            dropped.append(field_label)
                            retry = True
                        if field_key == "customfield_10015" and include_start:
                            include_start = False
                            dropped.append(field_label)
                            retry = True
                if "issuetype" in err_body:
                    try:
                        valid_types = jira_fetch_project_categories(cfg, project_key)
                        if parent_key:
                            sub_t = jira_fetch_project_subtask_type(cfg, project_key)
                            if sub_t and sub_t != issue_type:
                                issue_type = sub_t
                                retry = True
                        elif valid_types:
                            matched_t = None
                            for cand in ["작업", "Task", "기능", "개선", "이슈"]:
                                if cand in valid_types and cand != issue_type:
                                    matched_t = cand
                                    break
                            if not matched_t:
                                non_epics = [t for t in valid_types if "에픽" not in t and "epic" not in t.lower() and t != issue_type]
                                if non_epics:
                                    matched_t = non_epics[0]
                            if matched_t:
                                log_line("Jira 이슈 타입을", issue_type, "에서", matched_t, "(으)로 자동 전환하여 재시도합니다.")
                                issue_type = matched_t
                                retry = True
                    except Exception as fe:
                        log_line("Jira 이슈 타입 복구 시도 실패:", fe)
                if retry:
                    log_line("문제된 필드/타입 조정 후 재시도합니다.")
                    continue
            return None, "Jira 티켓 생성 실패 (" + str(e.code) + "): " + err_body[:300]
        except Exception as e:
            log_line("Jira 티켓 생성 실패:", e)
            return None, "Jira 티켓 생성 실패: " + str(e)
    return None, "Jira 티켓 생성 실패: 재시도 초과"


def create_jira_issue_link(cfg, inward_key, outward_key, link_type_name="Relates"):
    """Jira 이슈 간 링크(Relates to / Blocked by 등)를 생성한다."""
    j = cfg.get("jira", {})
    if not j.get("enabled") or not j.get("api_token") or not j.get("email"):
        return False, "Jira 연동이 설정되지 않았습니다."
    if not inward_key or not outward_key or inward_key == outward_key:
        return False, "유효한 Jira 키가 필요합니다."
    base_url = j["base_url"].rstrip("/")
    url = base_url + "/rest/api/3/issueLink"
    body = json.dumps({
        "type": {"name": link_type_name},
        "inwardIssue": {"key": inward_key},
        "outwardIssue": {"key": outward_key}
    }).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers=_jira_auth_header(j))
    try:
        with _urlopen(req, timeout=10) as resp:
            return True, None
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", "replace")
        log_line(f"Jira 이슈 링크({inward_key} <-> {outward_key}) 생성 실패:", e.code, err)
        return False, err
    except Exception as e:
        log_line(f"Jira 이슈 링크({inward_key} <-> {outward_key}) 생성 예외:", e)
        return False, str(e)


def transition_jira_issue(cfg, issue_key, target_status_name):
    """Jira 이슈의 상태를 대상 상태(예: '진행', '완료', '예정', '검토')로 전이시킨다.
    Jira 워크플로 특성상 다단계 전이(예: 예정 -> 진행 -> 검토 -> 완료)가 필요할 수 있으므로
    BFS 또는 순차 경로 탐색을 통해 목표 상태로 안전하게 이동한다.
    
    Returns:
        (bool success, str note_or_error)
    """
    j = cfg.get("jira", {})
    if not j.get("enabled") or not j.get("api_token") or not j.get("email"):
        return False, "Jira 연동이 설정되어 있지 않습니다."

    base_url = j["base_url"].rstrip("/")
    clean_target = (target_status_name or "").strip()
    
    # Normalize target status keywords
    is_done_target = any(kw in clean_target for kw in ("완료", "Done", "Closed", "해결"))
    is_review_target = any(kw in clean_target for kw in ("검토", "Review", "review", "Testing", "검수"))
    is_progress_target = any(kw in clean_target for kw in ("진행", "Progress"))
    is_todo_target = any(kw in clean_target for kw in ("대기", "예정", "To Do", "Open"))

    def get_available_transitions():
        url = f"{base_url}/rest/api/3/issue/{issue_key}/transitions"
        req = urllib.request.Request(url, headers=_jira_auth_header(j))
        try:
            with _urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("transitions", [])
        except Exception as e:
            log_line(f"Jira 이슈 {issue_key} transitions 조회 실패:", e)
            return []

    def post_transition(t_id):
        url = f"{base_url}/rest/api/3/issue/{issue_key}/transitions"
        body = json.dumps({"transition": {"id": str(t_id)}}).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST", headers=_jira_auth_header(j))
        try:
            with _urlopen(req, timeout=10) as resp:
                return resp.status in (200, 204), None
        except urllib.error.HTTPError as e:
            err = e.read().decode("utf-8", "replace")
            log_line(f"Jira 전이(ID {t_id}) 실행 실패:", e.code, err)
            return False, f"HTTP {e.code}: {err[:200]}"
        except Exception as e:
            return False, str(e)

    # Multi-hop transition loop (max 4 steps)
    for step in range(4):
        transitions = get_available_transitions()
        if not transitions:
            return False, f"{issue_key}에 가능한 상태 전이가 없습니다."

        # Check if direct match to target exists
        direct_match = None
        for t in transitions:
            to_name = (t.get("to", {}).get("name") or "").strip()
            t_name = (t.get("name") or "").strip()
            
            if is_done_target and ("완료" in to_name or "done" in to_name.lower()):
                direct_match = t
                break
            elif is_review_target and ("검토" in to_name or "review" in to_name.lower() or "test" in to_name.lower()):
                direct_match = t
                break
            elif is_progress_target and ("진행" in to_name or "progress" in to_name.lower()):
                direct_match = t
                break
            elif is_todo_target and ("예정" in to_name or "대기" in to_name or "to do" in to_name.lower()):
                direct_match = t
                break
            elif clean_target and (clean_target in to_name or clean_target in t_name):
                direct_match = t
                break

        if direct_match:
            ok, err = post_transition(direct_match["id"])
            if ok:
                new_status_name = direct_match.get("to", {}).get("name") or clean_target
                with _jira_cache_lock:
                    if _jira_cache.get("records"):
                        for r in _jira_cache["records"]:
                            jk = ((r.get("jira") or {}).get("key") or "").upper()
                            if jk == issue_key.upper():
                                if r.get("jira"):
                                    r["jira"]["statusName"] = new_status_name
                                    r["jira"]["rawStatusName"] = new_status_name
                                    r["jira"]["status"] = "good" if ("완료" in new_status_name or "done" in new_status_name.lower()) else "info"
                                r["statusName"] = new_status_name
                                if "완료" in new_status_name or "done" in new_status_name.lower():
                                    r["status"] = "완료"
                                elif "검토" in new_status_name or "review" in new_status_name.lower():
                                    r["status"] = "검토"
                                elif "진행" in new_status_name:
                                    r["status"] = "진행"
                                else:
                                    r["status"] = "예정"
                                break
                return True, f"상태가 '{new_status_name}'(으)로 변경되었습니다."
            return False, f"전이 실패: {err}"

        # If targeting '완료', Jira workflow may require stepping through '진행' -> '검토' -> '완료'
        if is_done_target:
            hop_match = None
            # Look for '검토' first if in '진행'
            for t in transitions:
                to_name = (t.get("to", {}).get("name") or "").strip()
                if "검토" in to_name:
                    hop_match = t
                    break
            # Look for '진행' if currently in '예정'
            if not hop_match:
                for t in transitions:
                    to_name = (t.get("to", {}).get("name") or "").strip()
                    if "진행" in to_name:
                        hop_match = t
                        break

            if hop_match:
                ok, err = post_transition(hop_match["id"])
                if ok:
                    time.sleep(0.3)
                    continue  # Next iteration will look for target
                return False, f"중간 전이 실패: {err}"

        # If targeting '진행' and can step through
        if is_progress_target:
            for t in transitions:
                to_name = (t.get("to", {}).get("name") or "").strip()
                if "진행" in to_name:
                    ok, err = post_transition(t["id"])
                    if ok:
                        with _jira_cache_lock:
                            if _jira_cache.get("records"):
                                for r in _jira_cache["records"]:
                                    jk = ((r.get("jira") or {}).get("key") or "").upper()
                                    if jk == issue_key.upper():
                                        if r.get("jira"):
                                            r["jira"]["statusName"] = to_name
                                            r["jira"]["rawStatusName"] = to_name
                                            r["jira"]["status"] = "info"
                                        r["statusName"] = to_name
                                        r["status"] = "진행"
                                        break
                        return True, f"상태가 '{to_name}'(으)로 변경되었습니다."

    if is_review_target:
        # Jira 프로젝트에 '검토' 상태가 없는 표준 워크플로(To Do -> In Progress -> Done)의 경우 '진행'으로 유연하게 폴백
        log_line(f"Jira 이슈 {issue_key}: 워크플로에 '검토' 상태가 없어 '진행'(In Progress)으로 폴백을 시도합니다.")
        for t in get_available_transitions():
            to_n = (t.get("to", {}).get("name") or "").strip()
            if "진행" in to_n or "progress" in to_n.lower():
                succ, err = post_transition(t["id"])
                if succ:
                    return True, "Jira 워크플로에 '검토' 상태가 없어 '진행'(In Progress)으로 설정되었습니다."
        return True, "Jira 워크플로에 '검토' 상태가 없어 현재 상태가 유지됩니다."

    return False, f"'{clean_target}' 상태로 전이할 수 있는 워크플로 경로를 찾지 못했습니다."


def add_jira_comment(cfg, issue_key, comment_text, author_name=None):
    """Jira REST API를 통해 이슈에 댓글을 추가한다.
    POST /rest/api/3/issue/{issue_key}/comment
    """
    j = cfg.get("jira", {})
    if not j.get("enabled") or not j.get("api_token") or not j.get("email"):
        return None, "Jira 연동이 설정되어 있지 않습니다."
    
    base_url = j["base_url"].rstrip("/")
    url = f"{base_url}/rest/api/3/issue/{issue_key}/comment"
    
    full_text = (comment_text or "").strip()
    if author_name:
        full_text += f"\n\n({author_name}-Argos works)"

    payload = {
        "body": {
            "type": "doc",
            "version": 1,
            "content": [{
                "type": "paragraph",
                "content": [{
                    "type": "text",
                    "text": full_text
                }]
            }]
        }
    }

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers=_jira_auth_header(j))
    try:
        with _urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        # 캐시 및 DB에 새 댓글 즉시 반영하여 캔버스 등에 실시간 표출
        try:
            from datetime import datetime
            new_comment_obj = {
                "id": str(data.get("id") or ""),
                "author": author_name or (data.get("author") or {}).get("displayName") or "사용자",
                "body": full_text,
                "created": (data.get("created") or datetime.now().isoformat())[:19],
                "source": "jira"
            }
            from db import get_one, execute
            row = get_one("SELECT raw_json FROM jira_issues WHERE UPPER(jira_key) = ?", (issue_key.upper(),))
            if row and row.get("raw_json"):
                d = json.loads(row["raw_json"])
                cur_comments = d.get("comments") or []
                cur_comments.append(new_comment_obj)
                d["comments"] = cur_comments
                execute("UPDATE jira_issues SET raw_json = ? WHERE UPPER(jira_key) = ?", (json.dumps(d, ensure_ascii=False), issue_key.upper()))

            with _jira_cache_lock:
                if _jira_cache and _jira_cache.get("records"):
                    for r in _jira_cache["records"]:
                        jk = ((r.get("jira") or {}).get("key") or r.get("key") or "").upper()
                        if jk == issue_key.upper():
                            c_list = list(r.get("comments") or [])
                            c_list.append(new_comment_obj)
                            r["comments"] = c_list
                            break
        except Exception as ce:
            log_line("Jira 새 댓글 캐시 갱신 예외:", ce)

        return data, None
    except urllib.error.HTTPError as e:
        err_msg = ""
        try:
            err_msg = e.read().decode("utf-8", errors="ignore")
        except Exception as e:
            log_line("[jira_client] Error reading departments for project key resolution:", e)
        log_line(f"Jira 댓글 추가 실패: HTTP {e.code}", err_msg[:200])
        return None, f"Jira 댓글 등록 실패 (HTTP {e.code}): {err_msg[:200]}"
    except Exception as e:
        log_line("Jira 댓글 추가 오류:", e)
        return None, str(e)


def upload_jira_attachment(cfg, issue_key, filename, file_bytes, content_type=None):
    """Jira Cloud REST API를 통해 이슈에 첨부파일을 업로드한다.
    POST /rest/api/3/issue/{issue_key}/attachments
    """
    j = cfg.get("jira", {})
    if not j.get("enabled") or not j.get("api_token") or not j.get("email"):
        return None, "Jira 연동이 설정되어 있지 않습니다."

    import secrets
    base_url = j["base_url"].rstrip("/")
    url = f"{base_url}/rest/api/3/issue/{issue_key}/attachments"

    boundary = f"----WebKitFormBoundary{secrets.token_hex(16)}"
    c_type = content_type or "application/octet-stream"

    # RFC 2046 multipart/form-data with UTF-8 filename encoding
    safe_fname = os.path.basename(filename).replace('"', '')
    part_head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{safe_fname}"\r\n'
        f"Content-Type: {c_type}\r\n\r\n"
    ).encode("utf-8")
    part_tail = f"\r\n--{boundary}--\r\n".encode("utf-8")
    body = part_head + file_bytes + part_tail

    headers = _jira_auth_header(j)
    headers["X-Atlassian-Token"] = "no-check"
    headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    headers["Content-Length"] = str(len(body))

    req = urllib.request.Request(url, data=body, method="POST", headers=headers)
    try:
        with _urlopen(req, timeout=35) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data, None
    except urllib.error.HTTPError as e:
        err_msg = ""
        try:
            err_msg = e.read().decode("utf-8", errors="ignore")
        except Exception as e:
            log_line("[jira_client] Error reading departments for project key resolution:", e)
        try:
            err_json = json.loads(err_msg)
            if isinstance(err_json, dict) and err_json.get("errorMessages"):
                err_msg = "; ".join(err_json["errorMessages"])
        except Exception as e:
            log_line("[jira_client] Error reading departments for project key resolution:", e)
        if e.code == 413:
            err_msg = "파일 용량 제한 초과 (Jira 파일 크기 제한)"
        elif e.code == 403:
            err_msg = "Jira 저장소 용량 초과 또는 권한 부족 (403 Forbidden)"
        elif e.code == 404:
            err_msg = f"Jira 이슈 '{issue_key}'를 찾을 수 없습니다."
        log_line(f"Jira 첨부파일 업로드 실패: HTTP {e.code}", err_msg[:200])
        return None, err_msg or f"HTTP {e.code} 업로드 거부"
    except Exception as e:
        log_line("Jira 첨부파일 업로드 오류:", e)
        return None, str(e)


def update_jira_issue_dates(cfg, issue_key, start_date=None, due_date=None):
    """Jira Cloud REST API를 통해 특정 이슈의 시작일(start_date, customfield_10015)과
    마감일(due_date, duedate)을 업데이트한다.
    PUT /rest/api/3/issue/{issue_key}
    
    Returns:
        (bool success, str note_or_error)
    """
    clean_key = (issue_key or "").strip().upper()
    if not clean_key:
        return False, "이슈 키가 필요합니다."

    j = cfg.get("jira", {})
    if not j.get("enabled") or not j.get("api_token") or not j.get("email"):
        return False, "Jira 연동이 설정되어 있지 않습니다."

    base_url = j["base_url"].rstrip("/")
    url = f"{base_url}/rest/api/3/issue/{clean_key}"

    # Ensure dates order if both provided
    if start_date and due_date and start_date > due_date:
        start_date, due_date = due_date, start_date

    # Build fields to update
    def build_payload(include_start_date=True):
        fields = {}
        if due_date:
            fields["duedate"] = due_date
        if start_date and include_start_date:
            fields["customfield_10015"] = start_date
        return {"fields": fields}

    include_start = bool(start_date)
    for attempt in range(2):
        payload = build_payload(include_start_date=include_start)
        if not payload["fields"]:
            return True, "변경할 날짜 정보가 없습니다."

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="PUT", headers=_jira_auth_header(j))

        try:
            with _urlopen(req, timeout=12) as resp:
                # 204 No Content indicates success
                pass
            
            # Cache update in memory if present
            with _jira_cache_lock:
                if _jira_cache.get("records"):
                    for r in _jira_cache["records"]:
                        jk = ((r.get("jira") or {}).get("key") or "").upper()
                        if jk == clean_key:
                            if due_date:
                                r["duedate"] = due_date
                                if r.get("jira"):
                                    r["jira"]["duedate"] = due_date
                            if start_date:
                                r["startDate"] = start_date
                                if r.get("jira"):
                                    r["jira"]["startDate"] = start_date
                            break
            
            # Trigger background cache sync so other views immediately get updated
            try:
                threading.Thread(target=sync_jira_cache, args=(cfg,), daemon=True).start()
            except Exception:
                pass

            msg_parts = []
            if start_date:
                msg_parts.append(f"시작일: {start_date}")
            if due_date:
                msg_parts.append(f"마감일: {due_date}")
            return True, f"Jira 이슈 {clean_key}의 일정이 갱신되었습니다 ({', '.join(msg_parts)})."

        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8", "replace")
            except Exception:
                pass
            log_line(f"Jira 이슈 {clean_key} 날짜 갱신 실패 (HTTP {e.code}):", err_body[:200])

            # If customfield_10015 (start date) is not in edit screen, retry with duedate only
            if attempt == 0 and include_start and ("customfield_10015" in err_body or e.code == 400):
                include_start = False
                log_line(f"customfield_10015 필드 제외 후 duedate만 재시도: {clean_key}")
                continue

            return False, f"Jira 일정 갱신 실패 (HTTP {e.code}): {err_body[:200]}"
        except Exception as e:
            log_line(f"Jira 이슈 {clean_key} 날짜 갱신 오류:", e)
            return False, str(e)

    return False, "Jira 일정 갱신 실패 (재시도 초과)"


def get_jira_issue_by_key(cfg, issue_key):
    """캐시된 기록 또는 Jira REST API를 통해 특정 이슈의 전체 상세 정보를 반환한다.
    하위 작업(subtasks), 상위 작업(parent), 댓글(comments), 첨부파일(attachments) 등을 포함한다.
    """
    clean_key = (issue_key or "").strip().upper()
    if not clean_key:
        return None
    clean_id = clean_key.lstrip("#").replace("REC-", "").replace("LOCAL-", "").replace("JIRA-", "")

    local_recs = read_records()
    records = list(local_recs)
    matched = None
    is_from_local_db = False

    # 1. Local-First: Search local records (SQLite) first!
    for lr in local_recs:
        jk = ((lr.get("jira") or {}).get("key") or "").upper()
        cc = (lr.get("cardCode") or "").upper()
        rid = str(lr.get("id") or "").replace("jira-", "").upper()
        if cc == clean_key or rid == clean_key or rid == clean_id or (jk and jk == clean_key):
            matched = dict(lr)
            is_from_local_db = True
            break

    jira_enabled = bool((cfg.get("jira", {}) if cfg else {}).get("enabled", False))

    if not jira_enabled:
        if not matched:
            return None
        matched["jira"] = None
        matched["isLocal"] = True
    else:
        # 2. If not found in local records, check cached Jira records (external tasks)
        cache = get_cached_jira_records(cfg)
        cached_jira = list(cache.get("records") or [])
        records = list(local_recs) + cached_jira
        if not matched:
            for r in cached_jira:
                jk = ((r.get("jira") or {}).get("key") or "").upper()
                cc = (r.get("cardCode") or "").upper()
                rid = str(r.get("id") or "").replace("jira-", "").upper()
                if jk == clean_key or cc == clean_key or rid == clean_key or rid == clean_id:
                    matched = dict(r)
                    break
        else:
            # If matched from local, enrich with Jira attachments if linked
            jk = ((matched.get("jira") or {}).get("key") or "").upper()
            if jk:
                j_match = next((r for r in cached_jira if ((r.get("jira") or {}).get("key") or "").upper() == jk), None)
                if j_match:
                    local_names = {a if isinstance(a, str) else (a.get("name") or a.get("filename") or "") for a in (matched.get("attachments") or [])}
                    for ja in (j_match.get("attachments") or []):
                        janame = ja.get("name") or ja.get("filename") or ""
                        if janame and janame not in local_names:
                            matched.setdefault("attachments", []).append(ja)

        if not matched:
            return None

        # Jira 이슈인 경우 DB의 최신 댓글 목록을 즉시 반영
        if matched.get("jira") and matched["jira"].get("key"):
            try:
                from db import get_one
                j_row = get_one("SELECT raw_json FROM jira_issues WHERE UPPER(jira_key) = ?", (matched["jira"]["key"].upper(),))
                if j_row and j_row.get("raw_json"):
                    db_item = json.loads(j_row["raw_json"])
                    if db_item.get("comments") is not None:
                        matched["comments"] = db_item["comments"]
            except Exception:
                pass

    # 로컬 키 표준화 (cardCode 우선)
    if not (matched.get("jira") and matched["jira"].get("key")):
        matched["key"] = matched.get("cardCode") or f"#{matched.get('id')}"

    # 부모 식별자 별칭 집합 (cardCode, id, jira_key 등)
    parent_aliases = {
        clean_key,
        clean_id,
        (matched.get("cardCode") or "").strip().upper(),
        str(matched.get("id") or "").strip().upper()
    }
    if (matched.get("jira") or {}).get("key"):
        parent_aliases.add(matched["jira"]["key"].strip().upper())
    parent_aliases.discard("")

    # 2. 하위 작업들(subtasks) 상세 정보 및 전체 하위 트리(자식, 손자 등) 재귀 수집
    by_parent = {}
    for r in records:
        pk = ((r.get("parentKey") or (r.get("jira") or {}).get("parentKey") or "")).strip().upper()
        if pk:
            by_parent.setdefault(pk, []).append(r)

    subtasks_detail = []
    subtask_keys = set(matched.get("subtasks") or [])
    for r in records:
        jk = ((r.get("jira") or {}).get("key") or "").strip().upper()
        pk = ((r.get("parentKey") or (r.get("jira") or {}).get("parentKey") or "")).strip().upper()
        if (pk and pk in parent_aliases) or (jk and jk in subtask_keys):
            st_key = (r.get("jira") or {}).get("key") or r.get("cardCode") or str(r.get("id", "")).replace("jira-", "")
            if not any(s["key"] == st_key for s in subtasks_detail):
                subtasks_detail.append({
                    "key": st_key,
                    "summary": r.get("title", ""),
                    "status": (r.get("jira") or {}).get("statusName") or r.get("status", ""),
                    "assignee": r.get("assignee", "미배정"),
                    "priority": (r.get("jira") or {}).get("priority") or "보통"
                })
    matched["subtasksDetail"] = subtasks_detail

    # 재귀적으로 모든 하위 작업(후손) 수집
    all_descendants = []
    visited_desc = set()

    def collect_descendants(p_keys):
        for pk in p_keys:
            for child in by_parent.get(pk.upper(), []):
                c_key = ((child.get("jira") or {}).get("key") or child.get("cardCode") or str(child.get("id", ""))).strip().upper()
                if c_key and c_key not in visited_desc and c_key not in parent_aliases:
                    visited_desc.add(c_key)
                    all_descendants.append(child)
                    child_aliases = {c_key, str(child.get("id", "")).strip().upper(), (child.get("cardCode") or "").strip().upper()}
                    child_aliases.discard("")
                    collect_descendants(child_aliases)

    collect_descendants(parent_aliases)
    for st in subtasks_detail:
        stk = (st.get("key") or "").strip().upper()
        if stk and stk not in visited_desc and stk not in parent_aliases:
            visited_desc.add(stk)
            for r in records:
                jk = ((r.get("jira") or {}).get("key") or "").strip().upper()
                cc = (r.get("cardCode") or "").strip().upper()
                if jk == stk or cc == stk:
                    all_descendants.append(r)
                    break
            collect_descendants({stk})
        if stk and stk not in visited_desc and stk != clean_key:
            visited_desc.add(stk)
            for r in records:
                jk = ((r.get("jira") or {}).get("key") or "").strip().upper()
                if jk == stk:
                    all_descendants.append(r)
                    break
            collect_descendants(stk)

    # 참여 인원(Contributors) 산출: 메인 담당자 + 직속 참여자 + 모든 하위 작업 담당자 포함 (중복 제거)
    contributor_map = {}
    direct_participants = []
    raw_p = matched.get("participants") or ""
    if isinstance(raw_p, str) and raw_p.strip():
        import re
        direct_participants = [p.strip() for p in re.split(r'[,;/]+', raw_p) if p.strip()]
    elif isinstance(raw_p, list):
        for p in raw_p:
            name = p.strip() if isinstance(p, str) else (p.get("name", "").strip() if isinstance(p, dict) else "")
            if name:
                direct_participants.append(name)

    if all_descendants or direct_participants:
        main_assignee = (matched.get("assignee") or "").strip()
        if main_assignee and main_assignee not in ("미배정", "Unassigned", "None", ""):
            contributor_map[main_assignee] = 0

        # 직속 참여자 반영 (하위 작업이 없는 경우 기본 1)
        for dp in direct_participants:
            if dp and dp not in ("미배정", "Unassigned", "None", ""):
                contributor_map[dp] = 0

        # 하위 작업 담당자 반영 (건수 누적)
        for desc in all_descendants:
            a = (desc.get("assignee") or "").strip()
            if a and a not in ("미배정", "Unassigned", "None", ""):
                contributor_map[a] = contributor_map.get(a, 0) + 1
            desc_p = desc.get("participants") or ""
            if isinstance(desc_p, str) and desc_p.strip():
                import re
                for dp_sub in re.split(r'[,;/]+', desc_p):
                    dp_sub = dp_sub.strip()
                    if dp_sub and dp_sub not in ("미배정", "Unassigned", "None", ""):
                        contributor_map[dp_sub] = contributor_map.get(dp_sub, 0) + 1

        if all_descendants and main_assignee and main_assignee in contributor_map and contributor_map[main_assignee] == 0:
            contributor_map[main_assignee] = 1

    sorted_contributors = sorted(contributor_map.items(), key=lambda x: x[1], reverse=True)
    matched["contributorMap"] = dict(sorted_contributors)
    matched["contributorNames"] = [k for k, _ in sorted_contributors]
    matched["allDescendantsCount"] = len(all_descendants)
    matched["hasSubtasks"] = len(all_descendants) > 0 or len(subtasks_detail) > 0

    # 3. 상위 작업 요약 정보 보강 (Parent Link)
    parent_key = matched.get("parentKey") or (matched.get("jira") or {}).get("parentKey")
    if parent_key and not matched.get("parentSummary"):
        for r in records:
            jk = ((r.get("jira") or {}).get("key") or "").upper()
            if jk == parent_key.upper():
                matched["parentSummary"] = r.get("title", "")
                break

    # 4. 부가적인 Choivis 규격 메타데이터 보강
    if not matched.get("key"):
        matched["key"] = (matched.get("jira") or {}).get("key") or str(matched.get("id") or clean_id)
    if not matched.get("issueType"):
        matched["issueType"] = matched.get("category") or "Task"
    if not matched.get("priority"):
        matched["priority"] = (matched.get("jira") or {}).get("priority") or "보통"
    if not matched.get("status"):
        matched["status"] = (matched.get("jira") or {}).get("statusName") or "진행"

    # Subtask eligibility: only leaf subtasks ('하위 작업' / 'Subtask') cannot create subtasks
    cur_type = str(matched.get("issueType") or matched.get("category") or "").strip()
    is_leaf_subtask = (cur_type == "하위 작업" or "sub" in cur_type.lower() or matched.get("isSubtask") is True)
    if cur_type in ("메인", "메인프로젝트", "현장", "인증", "아이디어", "테스트", "Task"):
        is_leaf_subtask = False
    matched["canCreateSubtask"] = not is_leaf_subtask
    matched["isSubtask"] = is_leaf_subtask
    if matched.get("jira"):
        matched["jira"]["canCreateSubtask"] = not is_leaf_subtask
        matched["jira"]["isSubtask"] = is_leaf_subtask

    # 5. Local-First: do NOT overwrite local title or description with Jira!
    if not is_from_local_db:
        if matched.get("jira") and matched["jira"].get("summary"):
            matched["title"] = matched["jira"]["summary"]
        if matched.get("memo"):
            matched["description"] = matched["memo"]
    else:
        matched["title"] = matched.get("title") or (matched.get("jira") or {}).get("summary") or ""
        matched["description"] = matched.get("memo") or matched.get("summary") or ""
    if (matched.get("assigneeAvatar") or (matched.get("jira") or {}).get("assigneeAvatar")) and not matched.get("avatarUrl"):
        matched["avatarUrl"] = matched.get("assigneeAvatar") or (matched.get("jira") or {}).get("assigneeAvatar")

    # 6. 로컬 이슈인 경우 메타데이터, 댓글, 첨부파일 URL 정규화
    if jira_enabled:
        jira_info = matched.get("jira") or {}
        jira_key_in_matched = (jira_info.get("key") or "").strip().upper()
        all_known_jira_keys = {((r.get("jira") or {}).get("key") or "").strip().upper() for r in records}
        
        if jira_key_in_matched and jira_key_in_matched not in all_known_jira_keys and matched.get("id"):
            # Jira Cloud에 없는 가짜/삭제된 키 -> 로컬 이슈로 복원
            matched["jira"] = None
            matched["unlinked_jira_key"] = jira_key_in_matched
            try:
                from services.data_store import unlink_record_jira
                unlink_record_jira(matched["id"])
            except Exception:
                pass

    is_local_record = is_from_local_db or not (matched.get("jira") and matched["jira"].get("key"))
    if is_local_record:
        matched["isLocal"] = True
        matched["key"] = matched.get("cardCode") or (f"#{matched.get('id')}" if matched.get("id") else str(clean_id))
        matched["status"] = matched.get("status") or "진행"
        matched["statusName"] = matched.get("status") or "진행"

        # 날짜 정규화 (work_date / date -> startDate, dueDate)
        d_val = (matched.get("date") or matched.get("work_date") or "").strip()
        if "~" in d_val:
            parts = [x.strip() for x in d_val.split("~")]
            matched["startDate"] = parts[0]
            matched["dueDate"] = parts[1] if len(parts) > 1 and parts[1] else parts[0]
        elif d_val:
            matched["startDate"] = d_val
            matched["dueDate"] = matched.get("dueDate") or d_val

        try:
            from services.data_store import get_record_comments
            matched["comments"] = get_record_comments(matched["id"])
        except Exception:
            matched["comments"] = matched.get("comments") or []

        # 첨부파일을 캔버스 미리보기/다운로드 가능한 전체 객체로 정규화
        import urllib.parse
        norm_attachments = []
        for a in (matched.get("attachments") or []):
            if isinstance(a, str):
                fname = a
                norm_attachments.append({
                    "name": fname,
                    "filename": fname,
                    "url": f"/api/attachments/{matched['id']}/{urllib.parse.quote(fname)}",
                    "isLocal": True,
                    "source": "local"
                })
            elif isinstance(a, dict):
                a_copy = dict(a)
                fname = a_copy.get("filename") or a_copy.get("name") or "file"
                if not a_copy.get("url"):
                    a_copy["url"] = f"/api/attachments/{matched['id']}/{urllib.parse.quote(fname)}"
                a_copy["isLocal"] = True
                a_copy["source"] = "local"
                norm_attachments.append(a_copy)
        matched["attachments"] = norm_attachments

    # 7. Jira 연동 활성화 및 정상 연결 여부 플래그 (어드민 설정 및 무오류 연결 시에만 True)
    is_jira_ready, _ = check_jira_connection_status(cfg)
    matched["jiraConnected"] = is_jira_ready
    has_jira_ticket = bool(matched.get("jira") and matched["jira"].get("key"))
    matched["canPushToJira"] = is_jira_ready and is_local_record and not has_jira_ticket

    return matched



