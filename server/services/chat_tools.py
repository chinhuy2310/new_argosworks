"""chat_tools.py — AI 에이전트를 위한 도구 정의 및 실행기"""



from utils.logging import log_line



AGENT_TOOLS = [

    {

        "type": "function",

        "function": {

            "name": "search_issues",

            "description": "사내 업무 카드를 검색한다. 특정 담당자의 전체 업무를 조회하려면 query를 비워두거나 담당자 이름을 지정한다.",

            "parameters": {

                "type": "object",

                "properties": {

                    "query": {"type": "string", "description": "검색 키워드 (제목, 설명, 업무코드 등)"},

                    "status": {"type": "string", "description": "상태 필터: 대기, 진행, 완료 등"},

                    "assignee": {"type": "string", "description": "담당자 또는 참여자 이름 필터"},

                    "limit": {"type": "number", "description": "최대 결과 수 (기본 35, 최대 60)"}

                }

            }

        }

    },

    {

        "type": "function",

        "function": {

            "name": "search_internal_records",

            "description": "사내 기록(로컬 인수인계 기록, 자체 등록 업무, 캘린더 일정)을 검색한다.",

            "parameters": {

                "type": "object",

                "properties": {

                    "query": {"type": "string", "description": "검색 키워드 (제목, 내용 등)"},

                    "assignee": {"type": "string", "description": "담당자 이름 필터"}

                }

            }

        }

    },

    {

        "type": "function",

        "function": {

            "name": "search_documents",

            "description": "벡터 저장소를 사용하여 전체 사내 업무 카드, 제품, 캘린더 문서 및 첨부 파일에서 의미론적 검색을 수행한다.",

            "parameters": {

                "type": "object",

                "properties": {

                    "query": {"type": "string", "description": "검색어"},

                    "limit": {"type": "number", "description": "최대 결과 수 (기본 5)"}

                },

                "required": ["query"]

            }

        }

    },

    {

        "type": "function",

        "function": {

            "name": "get_issue_details",

            "description": "업무 코드(예: DEV-1, #12)를 사용하여 단일 업무 카드의 전체 세부 정보를 가져온다.",

            "parameters": {

                "type": "object",

                "properties": {

                    "issue_key": {"type": "string", "description": "업무 코드 (예: DEV-1, #12)"}

                },

                "required": ["issue_key"]

            }

        }

    },

    {

        "type": "function",

        "function": {

            "name": "get_child_issues",

            "description": "부모 업무 카드의 하위 작업 목록을 가져온다.",

            "parameters": {

                "type": "object",

                "properties": {

                    "parent_key": {"type": "string", "description": "부모 업무 코드 (예: DEV-1)"}

                },

                "required": ["parent_key"]

            }

        }

    },

    {

        "type": "function",

        "function": {

            "name": "get_active_tasks",

            "description": "현재 사용자 또는 특정 담당자의 진행 중인 업무 카드를 가져온다.",

            "parameters": {

                "type": "object",

                "properties": {

                    "assignee": {"type": "string", "description": "담당자 이름 (비워두면 모든 진행 중 작업)"}

                }

            }

        }

    },

    {

        "type": "function",

        "function": {

            "name": "update_issue_status",

            "description": "업무 카드의 상태를 변경한다 (대기, 진행, 완료 등).",

            "parameters": {

                "type": "object",

                "properties": {

                    "issue_key": {"type": "string", "description": "업무 코드 (예: DEV-1)"},

                    "status": {"type": "string", "description": "새로운 상태 (대기, 진행, 완료 등)"}

                },

                "required": ["issue_key", "status"]

            }

        }

    },

    {

        "type": "function",

        "function": {

            "name": "add_issue_comment",

            "description": "업무 카드에 댓글을 추가한다.",

            "parameters": {

                "type": "object",

                "properties": {

                    "issue_key": {"type": "string", "description": "업무 코드 (예: DEV-1)"},

                    "comment": {"type": "string", "description": "댓글 내용"}

                },

                "required": ["issue_key", "comment"]

            }

        }

    },

    {

        "type": "function",

        "function": {

            "name": "create_issue",

            "description": "새로운 업무 카드를 생성한다.",

            "parameters": {

                "type": "object",

                "properties": {

                    "summary": {"type": "string", "description": "업무 제목"},

                    "description": {"type": "string", "description": "업무 상세 설명 (글머리 기호 구조화)"},

                    "issue_type": {"type": "string", "description": "업무 유형/카테고리 (기본: 메인프로젝트 또는 하위 작업)"},

                    "priority": {"type": "string", "description": "우선순위 (기본: 보통)"},

                    "parent_key": {"type": "string", "description": "부모 업무 코드 (선택 사항)"},

                    "assignee": {"type": "string", "description": "담당자 이름"},

                    "status": {"type": "string", "description": "목표 상태 (대기, 진행, 완료)"},

                    "start_date": {"type": "string", "description": "시작 날짜 (YYYY-MM-DD)"},

                    "due_date": {"type": "string", "description": "마감 날짜 (YYYY-MM-DD)"}

                },

                "required": ["summary"]

            }

        }

    },

    {

        "type": "function",

        "function": {

            "name": "get_calendar_schedule",

            "description": "월, 날짜 범위, 담당자로 캘린더 일정을 조회한다.",

            "parameters": {

                "type": "object",

                "properties": {

                    "month": {"type": "string", "description": "월 (YYYY-MM)"},

                    "start_date": {"type": "string", "description": "시작일 (YYYY-MM-DD)"},

                    "end_date": {"type": "string", "description": "종료일 (YYYY-MM-DD)"},

                    "assignee": {"type": "string", "description": "담당자 이름"}

                }

            }

        }

    },

    {

        "type": "function",

        "function": {

            "name": "schedule_issue",

            "description": "업무 카드의 시작일과 종료일(마감일)을 설정하거나 업데이트한다 (로컬 업무 및 캘린더 반영).",

            "parameters": {

                "type": "object",

                "properties": {

                    "issue_key": {"type": "string", "description": "업무 코드 또는 이슈 키 (예: DEV-1, VS-11)"},

                    "start_date": {"type": "string", "description": "시작일 (YYYY-MM-DD)"},

                    "due_date": {"type": "string", "description": "종료일 (YYYY-MM-DD)"}

                },

                "required": ["issue_key", "start_date"]

            }

        }

    },

    {

        "type": "function",

        "function": {

            "name": "search_products",

            "description": "사내 제품 정보(PIM / 제품정보 탭)를 검색한다. 모델명, 제품명, 제품군, 카테고리, 판매 상태(판매 중/단종 등), 사양으로 조회한다.",

            "parameters": {

                "type": "object",

                "properties": {

                    "query": {"type": "string", "description": "검색 키워드 (모델명, 제품명, 사양, 조달번호 등)"},

                    "lifecycle": {"type": "string", "description": "판매 상태 필터: 판매 중, 단종 예정, 단종"},

                    "category": {"type": "string", "description": "카테고리 필터 (예: 일반, 스마트보안등, 영상감시장치 등)"}

                }

            }

        }

    },

    {

        "type": "function",

        "function": {

            "name": "get_product_details",

            "description": "특정 제품의 상세 사양(Specs), 조달 등록 정보, 첨부 문서 등 전체 정보를 조회한다.",

            "parameters": {

                "type": "object",

                "properties": {

                    "product_id": {"type": "string", "description": "제품 ID (예: P-1a0efa27dc9)"},

                    "model": {"type": "string", "description": "제조 모델명 (예: test, VSC-MD5000ND-S)"}

                }

            }

        }

    },

    {

        "type": "function",

        "function": {

            "name": "generate_work_report",

            "description": "사내 업무 카드를 바탕으로 주간/기간별 업무 보고서를 회사 양식(12열) Excel 파일로 생성한다. 전체 R&D팀 또는 특정 담당자의 업무를 일자순으로 정리한다.",

            "parameters": {

                "type": "object",

                "properties": {

                    "assignee": {"type": "string", "description": "담당자 이름 또는 'all' (전체, 기본값)"},

                    "period": {"type": "string", "description": "기간: 'this_week'(이번주, 기본값), 'last_week'(지난주), 'custom'(직접 지정)"},

                    "start_date": {"type": "string", "description": "시작일 (YYYY-MM-DD, period=custom일 때만 필수)"},

                    "end_date": {"type": "string", "description": "종료일 (YYYY-MM-DD, period=custom일 때만 필수)"}

                }

            }

        }

    }

]



# 쓰기 작업 도구 목록 (AI의 직접 실행이 원천 차단됨)

WRITE_TOOL_NAMES = {

    "create_issue",

    "update_issue_status",

    "add_issue_comment",

    "schedule_issue",

}



# AI 에이전트 대화 루프에만 노출할 읽기 전용 도구 목록 (하드 블록 1단계: 스키마 차단)

AGENT_READ_TOOLS = [

    t for t in AGENT_TOOLS

    if t.get("function", {}).get("name") not in WRITE_TOOL_NAMES

]



def _resolve_assignee_name(name, current_user):

    """이름 별칭 및 대명사를 실제 Jira/로컬 등록 이름으로 매핑한다."""

    if not name:

        return ""

    n = name.strip().lower()

    curr_name = (current_user.get("name") if current_user else "") or ""

    

    # 1. 1인칭 대명사 (First-person pronouns): 현재 로그인 사용자로 명확히 해석

    first_person_pronouns = ("me", "my", "tôi", "toi", "mình", "minh", "bản thân", "ban than", "본인", "나", "내", "저", "제")

    if n in first_person_pronouns:

        return curr_name



    # 로그인 사용자의 아이디/이름과 일치하는 경우 우선 반환

    if curr_name and n == curr_name.lower():

        return curr_name



    # 2. 동적 인물/직원 별칭 매핑 (DB users 및 config 매핑 활용)

    try:

        from db import query

        # DB의 사용자 목록에서 username, name, email 일치 여부 확인

        users = query("SELECT name, username FROM users WHERE disabled = 0")

        for u in users:

            u_name = (u.get("name") or "").strip()

            u_username = (u.get("username") or "").strip()

            if u_name and n == u_name.lower():

                return u_name

            if u_username and n == u_username.lower():

                return u_name or u_username

    except Exception:

        pass



    return name.strip()





def _tool_search_issues(args, current_user, cfg):

    from services.search import merged_records, search_records

    query = (args.get("query") or "").strip()

    status_filter = args.get("status")

    assignee_input = args.get("assignee")

    limit = int(args.get("limit", 40))

    limit = max(1, min(limit, 60))

    

    # Resolve assignee alias (e.g. Uy -> 동진위)

    resolved_assignee = _resolve_assignee_name(assignee_input, current_user)

    

    # If query itself is an alias for a person (e.g. "Uy"), also resolve it

    query_as_person = _resolve_assignee_name(query, current_user)

    if query and query_as_person != query and not resolved_assignee:

        resolved_assignee = query_as_person

        query = ""  # Clean query so it doesn't fail keyword match on Korean name

    

    # Local-First: merged_records loads local DB records as primary truth + Jira cache if active

    records, _cache = merged_records(cfg)

    # RBAC: Filter records strictly by user view permissions before searching & feeding to AI
    from services.auth import visible_records
    records = visible_records(current_user, records)

    

    # If assignee filter is present, filter by assignee or participants

    if resolved_assignee:

        ra_lower = resolved_assignee.lower()

        records = [

            r for r in records 

            if ra_lower in (r.get("assignee") or "").lower() or ra_lower in (r.get("participants") or "").lower()

        ]

        

    if query:

        results = search_records(records, query, limit=limit)

    else:

        results = records

    

    # Apply status filter

    if status_filter:

        sf_lower = status_filter.lower()

        results = [

            r for r in results 

            if sf_lower in (r.get("statusName") or "").lower() or sf_lower in (r.get("status") or "").lower()

        ]

    

    results = results[:limit]

    

    formatted_issues = []

    for r in results:

        key = r.get("cardCode") or (r.get("jira") or {}).get("key") or (f"#{r.get('id')}" if r.get("id") else "")

        status = r.get("statusName") or r.get("status") or "대기"

        priority = (r.get("jira") or {}).get("priority") or "보통"

        formatted_issues.append({

            "key": key,

            "title": r.get("title", ""),

            "status": status,

            "assignee": r.get("assignee", ""),

            "participants": r.get("participants", ""),

            "category": r.get("category", ""),

            "start_date": r.get("startDate") or r.get("date") or "",

            "due_date": r.get("dueDate") or "",

            "summary": (r.get("summary") or r.get("memo") or "")[:400],

            "parent_key": r.get("parentKey") or (r.get("jira") or {}).get("parentKey") or "",

            "parent_summary": r.get("parentSummary") or "",

            "subtasks": r.get("subtasks") or [],

            "priority": priority,

            "source": "jira" if (r.get("jira") and r["jira"].get("key")) else "local"

        })



    return {

        "found_count": len(formatted_issues),

        "issues": formatted_issues

    }



def _tool_search_documents(args, current_user, cfg):

    from services.vector_store import search_vector_store, is_voyage_configured

    from services.search import merged_records, search_records

    query = args.get("query", "")

    limit = min(int(args.get("limit", 5)), 10)

    

    results = []

    # Try vector search first (with session privacy isolation)

    if is_voyage_configured(cfg):

        try:

            v_results = search_vector_store(cfg, query, limit=limit, min_similarity=0.38, session=current_user)

            results = [{

                "title": r.get("title", ""),

                "doc_type": r.get("doc_type", ""),

                "summary": r.get("summary", "")[:500],

                "similarity": r.get("similarity", 0),

                "date": r.get("date", ""),

            } for r in v_results]

        except Exception as e:

            log_line("[Chat Tool] 벡터 검색 오류:", e)

    

    # Fallback/supplement with keyword search (strictly scoped to visible_records)

    if len(results) < limit:

        from services.auth import visible_records

        records, _ = merged_records(cfg)

        records = visible_records(current_user, records)

        k_results = search_records(records, query, limit=limit)

        existing_titles = {r["title"] for r in results}

        for r in k_results:

            if r.get("title") not in existing_titles:

                results.append({

                    "title": r.get("title", ""),

                    "doc_type": "record",

                    "summary": (r.get("summary") or r.get("memo") or "")[:500],

                    "similarity": None,

                    "date": r.get("date", ""),

                })

    

    return {"found_count": len(results[:limit]), "documents": results[:limit]}



def _tool_get_issue_details(args, current_user, cfg):

    from services.data_store import find_record_by_key_or_code, read_records, get_record_comments

    from services.search import merged_records

    from services.jira_client import get_cached_jira_records, get_jira_issue_by_key



    raw_key = (args.get("issue_key") or "").strip()

    if not raw_key:

        return {"found": False, "error": "issue_key가 지정되지 않았습니다."}

    

    issue_key = raw_key.upper()

    

    # 1. Local SQLite record search first (Local-First!)

    local_rec = find_record_by_key_or_code(issue_key)

    all_merged, _ = merged_records(cfg)
    from services.auth import visible_records, can_view_record
    all_merged = visible_records(current_user, all_merged)



    if local_rec and local_rec.get("id"):

        from services.auth import can_view_record

        if not can_view_record(current_user, local_rec):

            return {"found": False, "error": "해당 업무 카드를 열람할 권한이 없습니다."}

        card_code = local_rec.get("cardCode") or (local_rec.get("jira") or {}).get("key") or f"#{local_rec.get('id')}"

        comments = get_record_comments(local_rec["id"])

        

        # Merge remote Jira comments if linked

        if local_rec.get("jira") and local_rec["jira"].get("key"):

            jira_key = local_rec["jira"]["key"]

            jira_info = get_jira_issue_by_key(cfg, jira_key) or {}

            remote_comments = jira_info.get("comments") or []

            existing_bodies = {c.get("body", "").strip() for c in comments}

            for rc in remote_comments:

                if rc.get("body", "").strip() not in existing_bodies:

                    comments.append(rc)



        formatted_comments = []

        for c in comments:

            formatted_comments.append({

                "author": c.get("author") or c.get("author_name") or "사용자",

                "date": str(c.get("created") or c.get("created_at") or "")[:10],

                "body": c.get("body", "")

            })



        # Find subtasks / children in all_merged

        children = []

        for r in all_merged:

            p_k = (r.get("parentKey") or (r.get("jira") or {}).get("parentKey") or "").strip().upper()

            if p_k in (issue_key, card_code.upper(), str(local_rec["id"])):

                children.append({

                    "key": r.get("cardCode") or (r.get("jira") or {}).get("key") or f"#{r.get('id')}",

                    "summary": r.get("title", ""),

                    "status": r.get("statusName") or r.get("status") or "",

                    "assignee": r.get("assignee", "")

                })



        parent_info = None

        p_key = local_rec.get("parentKey") or (local_rec.get("jira") or {}).get("parentKey")

        if p_key:

            p_rec = find_record_by_key_or_code(p_key)

            if p_rec:

                parent_info = {

                    "key": p_rec.get("cardCode") or (p_rec.get("jira") or {}).get("key") or f"#{p_rec.get('id')}",

                    "summary": p_rec.get("title", "")

                }

            else:

                parent_info = {"key": p_key, "summary": ""}



        attachments = [a.get("name") if isinstance(a, dict) else str(a) for a in (local_rec.get("attachments") or []) if a]

        priority = (local_rec.get("jira") or {}).get("priority") or "보통"



        return {

            "found": True,

            "key": card_code,

            "title": local_rec.get("title", ""),

            "description": (local_rec.get("summary") or local_rec.get("memo") or "")[:2000],

            "status": local_rec.get("status") or local_rec.get("statusName") or "대기",

            "assignee": local_rec.get("assignee", ""),

            "participants": local_rec.get("participants", ""),

            "category": local_rec.get("category", ""),

            "start_date": local_rec.get("startDate") or local_rec.get("date") or "",

            "due_date": local_rec.get("dueDate") or "",

            "date": local_rec.get("date") or "",

            "priority": priority,

            "parent": parent_info,

            "children": children,

            "children_count": len(children),

            "attachments": attachments,

            "comments_count": len(formatted_comments),

            "comments": formatted_comments,

            "source": "local" if not (local_rec.get("jira") and local_rec["jira"].get("key")) else "jira_linked"

        }



    # 2. If not found in local DB, check cached Jira records or remote Jira

    target_record = None

    for r in all_merged:

        k = (r.get("cardCode") or (r.get("jira") or {}).get("key") or "").strip().upper()

        if k == issue_key:

            target_record = r

            break



    if not target_record:

        target_record = get_jira_issue_by_key(cfg, issue_key)



    if not target_record:

        return {"found": False, "error": f"'{raw_key}' 업무 카드를 찾을 수 없습니다."}

    if not can_view_record(current_user, target_record):
        return {"found": False, "error": "해당 업무 카드를 열람할 권한이 없습니다."}



    jira = target_record.get("jira") or {}

    children = []

    for r in all_merged:

        p_k = (r.get("parentKey") or (r.get("jira") or {}).get("parentKey") or "").strip().upper()

        if p_k == issue_key:

            children.append({

                "key": r.get("cardCode") or (r.get("jira") or {}).get("key") or f"#{r.get('id')}",

                "summary": r.get("title", ""),

                "status": r.get("statusName") or r.get("status") or "",

                "assignee": r.get("assignee", ""),

            })



    parent_info = None

    parent_key = jira.get("parentKey") or target_record.get("parentKey")

    if parent_key:

        for r in all_merged:

            rk = (r.get("cardCode") or (r.get("jira") or {}).get("key") or "").strip().upper()

            if rk == parent_key.upper():

                parent_info = {"key": parent_key, "summary": r.get("title", "")}

                break



    comments = target_record.get("comments") or []

    formatted_comments = []

    for c in comments:

        formatted_comments.append({

            "author": c.get("author", "사용자"),

            "date": str(c.get("created") or "")[:10],

            "body": c.get("body", "")

        })



    attachments = [a.get("name") if isinstance(a, dict) else str(a) for a in (target_record.get("attachments") or []) if a]



    return {

        "found": True,

        "key": target_record.get("cardCode") or jira.get("key") or issue_key,

        "title": target_record.get("title", ""),

        "description": (target_record.get("summary") or target_record.get("memo") or "")[:2000],

        "status": target_record.get("statusName") or target_record.get("status") or "",

        "assignee": target_record.get("assignee", ""),

        "participants": target_record.get("participants", ""),

        "category": target_record.get("category", ""),

        "start_date": target_record.get("startDate", ""),

        "due_date": target_record.get("dueDate", ""),

        "date": target_record.get("date", ""),

        "priority": jira.get("priority", "보통"),

        "parent": parent_info,

        "children": children,

        "children_count": len(children),

        "attachments": attachments,

        "comments_count": len(formatted_comments),

        "comments": formatted_comments,

        "source": "jira"

    }



def _tool_get_child_issues(args, current_user, cfg):

    from services.search import merged_records

    parent_key = (args.get("parent_key") or "").upper().strip()

    if not parent_key:

        return {"parent_key": "", "children": [], "children_count": 0}

    

    records, _ = merged_records(cfg)

    # RBAC: Verify parent issue permission and filter child issues
    from services.auth import visible_records, can_view_record
    from services.data_store import find_record_by_key_or_code

    parent_rec = find_record_by_key_or_code(parent_key)
    if not parent_rec:
        for r in records:
            k = (r.get("cardCode") or (r.get("jira") or {}).get("key") or "").strip().upper()
            if k == parent_key:
                parent_rec = r
                break
    if parent_rec and not can_view_record(current_user, parent_rec):
        return {"parent_key": parent_key, "children": [], "children_count": 0, "error": "해당 상위 업무 카드를 열람할 권한이 없습니다."}

    records = visible_records(current_user, records)

    children = []

    for r in records:

        p_k = (r.get("parentKey") or (r.get("jira") or {}).get("parentKey") or "").strip().upper()

        if p_k == parent_key:

            children.append({

                "key": r.get("cardCode") or (r.get("jira") or {}).get("key") or (f"#{r.get('id')}" if r.get("id") else ""),

                "summary": r.get("title", ""),

                "status": r.get("statusName") or r.get("status") or "",

                "assignee": r.get("assignee", ""),

                "due_date": r.get("dueDate") or "",

            })

            

    return {

        "parent_key": parent_key,

        "children": children,

        "children_count": len(children)

    }



def _tool_search_internal_records(args, current_user, cfg):

    """Jira 시스템 외부의 사내 기록(로컬 인수인계 기록, 자체 등록 업무, 캘린더 일정)을 검색한다."""

    from services.data_store import read_records, read_schedule

    from services.search import search_records

    query = (args.get("query") or "").strip()

    assignee_input = args.get("assignee")

    

    resolved_assignee = _resolve_assignee_name(assignee_input, current_user)

    if query:

        query_as_person = _resolve_assignee_name(query, current_user)

        if query_as_person != query and not resolved_assignee:

            resolved_assignee = query_as_person

            query = ""



    from services.auth import visible_records, visible_schedule_events

    all_records = visible_records(current_user)

    # Non-jira records only

    internal_records = [r for r in all_records if not (r.get("jira") and r["jira"].get("key"))]

    

    if resolved_assignee:

        internal_records = [r for r in internal_records if resolved_assignee.lower() in (r.get("assignee") or "").lower()]

    

    if query:

        matched_records = search_records(internal_records, query, limit=30)

    else:

        matched_records = internal_records



    # Also search local schedule events (RBAC: 부서/본인/참여 일정만 — REST API와 동일 기준)

    schedule_events = visible_schedule_events(current_user, read_schedule())

    if resolved_assignee:

        schedule_events = [e for e in schedule_events if resolved_assignee.lower() in (e.get("ownerName") or "").lower()]

    if query:

        q_lower = query.lower()

        schedule_events = [e for e in schedule_events if q_lower in (e.get("title") or "").lower() or q_lower in (e.get("memo") or "").lower()]



    return {

        "internal_records_count": len(matched_records),

        "internal_records": [{

            "id": r.get("id"),

            "title": r.get("title", ""),

            "assignee": r.get("assignee", ""),

            "category": r.get("category", ""),

            "date": r.get("date", ""),

            "summary": (r.get("summary") or r.get("memo") or "")[:400],

            "tags": r.get("tags") or [],

            "source": "JARVIS 로컬 인수인계/업무 기록 (Jira 미연동)"

        } for r in matched_records],

        "schedule_events_count": len(schedule_events),

        "schedule_events": [{

            "id": e.get("id"),

            "title": e.get("title", ""),

            "type": e.get("type", ""),

            "owner": e.get("ownerName", ""),

            "start_date": e.get("startDate", ""),

            "end_date": e.get("endDate", ""),

            "memo": e.get("memo", ""),

            "source": "JARVIS 사내 캘린더 일정"

        } for e in schedule_events]

    }



def _tool_get_active_tasks(args, current_user, cfg):

    from services.search import merged_records

    assignee_input = args.get("assignee")

    assignee = _resolve_assignee_name(assignee_input, current_user) or (current_user.get("name") if current_user else "")

    

    records, _ = merged_records(cfg)

    # RBAC: Filter records strictly by user view permissions before filtering active tasks
    from services.auth import visible_records
    records = visible_records(current_user, records)

    

    # Filter active (not completed)

    closed_statuses = {"완료", "done", "closed", "해결됨", "resolved", "종료"}

    active = [

        r for r in records

        if ((r.get("statusName") or r.get("status") or "").strip().lower() not in closed_statuses)

    ]

    

    if assignee:

        a_lower = assignee.lower()

        active = [

            r for r in active

            if a_lower in (r.get("assignee") or "").lower() or a_lower in (r.get("participants") or "").lower()

        ]

    

    return {

        "count": len(active),

        "assignee": assignee,

        "tasks": [{

            "key": r.get("cardCode") or (r.get("jira") or {}).get("key") or (f"#{r.get('id')}" if r.get("id") else ""),

            "title": r.get("title", ""),

            "status": r.get("statusName") or r.get("status") or "대기",

            "assignee": r.get("assignee", ""),

            "participants": r.get("participants", ""),

            "category": r.get("category", ""),

            "start_date": r.get("startDate") or r.get("date") or "",

            "due_date": r.get("dueDate") or "",

            "summary": (r.get("summary") or r.get("memo") or "")[:400],

            "parent_key": r.get("parentKey") or (r.get("jira") or {}).get("parentKey") or "",

            "parent_summary": r.get("parentSummary") or "",

            "source": "jira" if (r.get("jira") and r["jira"].get("key")) else "local"

        } for r in active[:40]]

    }



def _tool_update_issue_status(args, current_user, cfg):

    import threading

    from datetime import datetime

    from services.data_store import find_record_by_key_or_code, update_record_status

    from services.activity_store import append_activity

    from services.vector_store import trigger_async_vector_sync

    

    issue_key = args.get("issue_key", "").upper().strip()

    new_status = args.get("status", "").strip()

    if not issue_key or not new_status:

        return {"success": False, "error": "issue_key와 status가 필요합니다."}

        

    author_name = current_user.get("name") or "사용자"

    log_line(f"[Chat Tool] 상태 변경 실행: {issue_key} → {new_status} (by {author_name})")



    from services.license_manager import is_system_read_only

    if is_system_read_only():

        return {"success": False, "error": "라이선스가 만료되어 시스템이 읽기 전용 상태입니다. 업무 상태를 변경할 수 없습니다."}



    from services.auth import can_transition_status
    local_rec = find_record_by_key_or_code(issue_key)
    if local_rec:
        can_trans, trans_err = can_transition_status(current_user, local_rec, new_status)
        if not can_trans:
            return {"success": False, "error": trans_err or "해당 업무 카드의 상태를 변경할 권한이 없습니다."}

    

    jira_ok = False

    jira_note = ""

    jira_key = None

    

    jira_enabled = bool(cfg.get("jira", {}).get("enabled", False))

    

    if local_rec and local_rec.get("id"):

        # 1. Update local SQLite DB first (Local-First!)

        update_record_status(local_rec["id"], new_status)
        if new_status in ("검토", "Review", "검토중"):
            try:
                from services.notification_service import trigger_review_request_notification
                trigger_review_request_notification(local_rec, current_user)
            except Exception:
                pass

        display_key = local_rec.get("cardCode") or issue_key

        

        # If linked to Jira and Jira is active, sync status to Jira

        if jira_enabled and local_rec.get("jira") and local_rec["jira"].get("key"):

            jira_key = local_rec["jira"]["key"]

            from services.jira_client import transition_jira_issue, sync_jira_cache

            jira_ok, jira_note = transition_jira_issue(cfg, jira_key, new_status)

            try:

                threading.Thread(target=sync_jira_cache, args=(cfg,), daemon=True).start()

            except Exception:

                pass

        

        # Log activity

        try:

            append_activity({

                "id": f"jarvis_chat_status_{display_key}_{int(datetime.now().timestamp()*1000)}",

                "issue_key": display_key,

                "action_type": "status_change",

                "action_detail": f"상태 변경 ➔ {new_status}" + (f" (Jira {jira_key} 동기화)" if jira_ok else ""),

                "author_name": author_name,

                "author_email": current_user.get("email", ""),

                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),

                "summary": local_rec.get("title") or display_key,

                "status": new_status,

                "priority": "보통",

                "issue_type": "로컬 업무 카드" if not jira_key else "Jira 연동",

                "assignee_name": local_rec.get("assignee") or author_name,

                "assignee_dept": current_user.get("org", "연구소"),

                "source": "jarvis_chat"

            })

        except Exception as act_err:

            log_line("[Activity] append_activity 오류 (무시):", act_err)

            

        # Trigger vector sync

        trigger_async_vector_sync(cfg)

        

        note = f"'{display_key}' 상태가 '{new_status}'(으)로 변경되었습니다."

        if jira_key and jira_note:

            note += f" (Jira: {jira_note})"

        return {"success": True, "issue_key": display_key, "new_status": new_status, "note": note}



    # If not local record, try remote Jira if enabled

    if jira_enabled:

        from services.jira_client import transition_jira_issue, sync_jira_cache

        ok, note = transition_jira_issue(cfg, issue_key, new_status)

        if ok:

            try:

                append_activity({

                    "id": f"jarvis_chat_status_{issue_key}_{int(datetime.now().timestamp()*1000)}",

                    "issue_key": issue_key,

                    "action_type": "status_change",

                    "action_detail": f"상태 변경 ➔ {new_status}",

                    "author_name": author_name,

                    "author_email": current_user.get("email", ""),

                    "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),

                    "summary": issue_key,

                    "status": new_status,

                    "priority": "보통",

                    "issue_type": "Jira",

                    "assignee_name": author_name,

                    "assignee_dept": current_user.get("org", "연구소"),

                    "source": "jarvis_chat"

                })

            except Exception:

                pass

            try:

                threading.Thread(target=sync_jira_cache, args=(cfg,), daemon=True).start()

            except Exception:

                pass

            trigger_async_vector_sync(cfg)

            return {"success": True, "issue_key": issue_key, "new_status": new_status, "note": note}

        else:

            return {"success": False, "issue_key": issue_key, "error": note}



    return {"success": False, "issue_key": issue_key, "error": f"'{issue_key}' 업무 카드를 찾을 수 없습니다."}



def _tool_add_issue_comment(args, current_user, cfg):

    import threading

    from datetime import datetime

    from services.data_store import find_record_by_key_or_code, add_record_comment

    from services.activity_store import append_activity

    from services.vector_store import trigger_async_vector_sync



    issue_key = (args.get("issue_key") or "").strip().upper()

    if not issue_key:

        return {"success": False, "error": "댓글을 추가할 대상 업무 코드/이슈 키(issue_key)가 필요합니다."}

    

    comment = (args.get("comment") or args.get("description") or args.get("summary") or "").strip()

    if not comment:

        return {"success": False, "error": "댓글 내용(comment)이 필요합니다."}

    

    author_name = current_user.get("name") or "사용자"

    log_line(f"[Chat Tool] 댓글 추가 실행: {issue_key} (작성자: {author_name})")



    from services.license_manager import is_system_read_only

    if is_system_read_only():

        return {"success": False, "error": "라이선스가 만료되어 시스템이 읽기 전용 상태입니다. 댓글을 작성할 수 없습니다."}



    from services.auth import can_modify_record

    local_rec = find_record_by_key_or_code(issue_key)

    if local_rec and not can_modify_record(current_user, local_rec):

        return {"success": False, "error": "해당 업무 카드에 댓글을 작성할 권한이 없습니다."}

    

    jira_enabled = bool(cfg.get("jira", {}).get("enabled", False))

    

    if local_rec and local_rec.get("id"):

        # 1. Local SQLite record comment first (Local-First!)

        add_record_comment(local_rec["id"], author_name, comment)

        display_key = local_rec.get("cardCode") or issue_key

        

        # 2. Sync to Jira if linked and Jira is active

        jira_note = ""

        if jira_enabled and local_rec.get("jira") and local_rec["jira"].get("key"):

            from services.jira_client import add_jira_comment, sync_jira_cache

            j_res, j_err = add_jira_comment(cfg, local_rec["jira"]["key"], comment, author_name)

            if j_res:

                jira_note = " (Jira 동기화 완료)"

                try:

                    threading.Thread(target=sync_jira_cache, args=(cfg,), daemon=True).start()

                except Exception:

                    pass



        try:

            append_activity({

                "id": f"jarvis_chat_comment_{display_key}_{int(datetime.now().timestamp()*1000)}",

                "issue_key": display_key,

                "action_type": "comment",

                "action_detail": comment[:120],

                "author_name": author_name,

                "author_email": current_user.get("email", ""),

                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),

                "summary": local_rec.get("title") or display_key,

                "status": local_rec.get("status") or "진행",

                "priority": "보통",

                "issue_type": "로컬 업무 카드",

                "assignee_name": author_name,

                "assignee_dept": current_user.get("org", "연구소"),

                "source": "jarvis_chat"

            })

        except Exception as act_err:

            log_line("[Activity] append_activity 오류 (무시):", act_err)



        trigger_async_vector_sync(cfg)

        return {

            "success": True,

            "issue_key": display_key,

            "note": f"{display_key} 업무 카드에 댓글이 등록되었습니다.{jira_note}"

        }



    # If not local record, fallback to Jira direct comment if Jira enabled

    if jira_enabled:

        from services.jira_client import add_jira_comment, sync_jira_cache

        res, err = add_jira_comment(cfg, issue_key, comment, author_name)

        if res and not err:

            try:

                append_activity({

                    "id": f"jarvis_chat_comment_{issue_key}_{int(datetime.now().timestamp()*1000)}",

                    "issue_key": issue_key,

                    "action_type": "comment",

                    "action_detail": comment[:120],

                    "author_name": author_name,

                    "author_email": current_user.get("email", ""),

                    "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),

                    "summary": issue_key,

                    "status": "진행",

                    "priority": "보통",

                    "issue_type": "Jira",

                    "assignee_name": author_name,

                    "assignee_dept": current_user.get("org", "연구소"),

                    "source": "jarvis_chat"

                })

            except Exception:

                pass

            try:

                threading.Thread(target=sync_jira_cache, args=(cfg,), daemon=True).start()

            except Exception:

                pass

            trigger_async_vector_sync(cfg)

            return {

                "success": True,

                "issue_key": issue_key,

                "comment_id": res.get("id"),

                "note": f"{issue_key} 이슈에 댓글이 등록되었습니다."

            }

        else:

            return {"success": False, "error": err or "댓글 등록 실패"}



    return {"success": False, "error": f"'{issue_key}' 업무 카드를 찾을 수 없습니다."}



def _tool_create_issue(args, current_user, cfg):

    import threading

    from datetime import datetime, date

    from services.data_store import (

        read_departments, append_record, next_record_id, get_next_card_code,

        read_schedule, write_schedule, mutate_schedule

    )

    from services.activity_store import append_activity

    from services.vector_store import trigger_async_vector_sync

    from db import query



    from services.license_manager import is_system_read_only

    if is_system_read_only():

        return {"success": False, "error": "라이선스가 만료되어 시스템이 읽기 전용 상태입니다. 신규 업무를 생성할 수 없습니다."}



    from services.auth import get_user_role

    if get_user_role(current_user) == "viewer":

        return {"success": False, "error": "조회 전용(Viewer) 권한으로는 신규 업무를 생성할 수 없습니다."}



    summary = (args.get("summary") or "").strip()

    if not summary:

        return {"success": False, "error": "업무 제목(summary)이 필요합니다."}

        

    description = (args.get("description") or "").strip()

    raw_type = (args.get("issue_type") or "").strip()

    parent_key = (args.get("parent_key") or "").strip().upper() or None

    # RBAC: 상위 업무 카드에 대한 열람/작업 권한 검증 (타 부서·비공개 카드에 하위 작업 생성 차단)
    if parent_key:
        from services.auth import can_view_record
        from services.data_store import find_record_by_key_or_code as _find_parent

        parent_rec = _find_parent(parent_key)
        if parent_rec and not can_view_record(current_user, parent_rec):
            log_line(f"[Security Guard] 권한 없는 상위 카드({parent_key})에 하위 작업 생성 시도 차단: {current_user.get('name')}")
            return {
                "success": False,
                "error": "상위 업무 카드에 접근할 권한이 없어 하위 작업을 생성할 수 없습니다."
            }

    target_status = (args.get("status") or "").strip() or "대기"

    start_date = (args.get("start_date") or "").strip() or None

    due_date = (args.get("due_date") or "").strip() or None

    if start_date and not due_date:

        due_date = start_date

    elif due_date and not start_date:

        start_date = due_date

    elif not start_date and not due_date:

        start_date = date.today().strftime("%Y-%m-%d")

        due_date = start_date



    submitter_name = current_user.get("name") if current_user else "사용자"

    assignee_name = (args.get("assignee") or "").strip()

    if assignee_name:

        resolved_assignee = _resolve_assignee_name(assignee_name, current_user) or assignee_name

    else:

        resolved_assignee = submitter_name

    

    org = current_user.get("org", "lab") if current_user else "lab"

    depts = read_departments()

    dept = next((d for d in depts if d["id"] == org), None) or (depts[0] if depts else {"id": "lab", "name": "연구소", "localPrefix": "REC"})

    dept_id = dept["id"]

    dept_prefix = (dept.get("localPrefix") or "REC").strip()



    jira_cfg = cfg.get("jira", {})

    jira_enabled = bool(jira_cfg.get("enabled", False))

    

    created_key = None

    created_record_id = None

    jira_data = None

    note_msg = ""

    issue_type = raw_type or dept.get("name") or "업무"



    # Try Jira if enabled

    if jira_enabled:

        from services.jira_client import (

            create_jira_issue, lookup_jira_account_id, 

            transition_jira_issue, sync_jira_cache

        )

        project_map = jira_cfg.get("project_map", {})

        default_proj = jira_cfg.get("default_project_key", "")

        

        if parent_key:

            project_key = parent_key.split("-")[0]

        elif org in project_map and project_map[org].get("project_key"):

            project_key = project_map[org].get("project_key")

        else:

            project_key = default_proj or (list(project_map.values())[0].get("project_key") if project_map else "PROJ")



        proj_info = project_map.get(org, {})

        configured_issue_type = proj_info.get("issue_type") or jira_cfg.get("default_issue_type")

        configured_subtask_type = proj_info.get("subtask_type")



        is_subtask = bool(parent_key or raw_type.lower() in ("subtask", "하위작업", "하위 작업"))

        if is_subtask:

            issue_type = configured_subtask_type or jira_cfg.get("default_subtask_type") or "Subtask"

        else:

            issue_type = raw_type or configured_issue_type or "작업"



        submitter_account_id = lookup_jira_account_id(cfg, submitter_name)

        assignee_account_id = lookup_jira_account_id(cfg, resolved_assignee) if resolved_assignee else submitter_account_id



        res_data, err_or_note = create_jira_issue(

            cfg=cfg,

            project_key=project_key,

            issue_type=issue_type,

            summary=summary,

            description_text=description,

            labels=["ARGOS_WORKS_CHAT"],

            due_date=due_date,

            submitter_account_id=submitter_account_id,

            parent_key=parent_key,

            start_date=start_date,

            assignee_account_id=assignee_account_id

        )



        if res_data and res_data.get("key"):

            created_key = res_data.get("key")

            jira_data = res_data

            if target_status and not any(kw in target_status for kw in ("대기", "예정", "To Do", "Open")):

                transition_jira_issue(cfg, created_key, target_status)

            note_msg = f"Jira 이슈 '{created_key}' 생성 완료"

        else:

            log_line(f"[Chat Tool] Jira 생성 실패, 로컬 레코드로 자동 전환 생성: {err_or_note}")

            note_msg = f"로컬 업무 카드로 생성되었습니다 (Jira 연동 보류: {err_or_note})"



    # If Jira was not enabled or Jira creation failed -> Local-First Card Creation!

    if not created_key:

        created_record_id = next_record_id()

        created_key = get_next_card_code(dept_id, dept_prefix)

        note_msg = f"로컬 업무 카드 '{created_key}' 생성이 완료되었습니다."



    # Save to local records table

    if not created_record_id:

        created_record_id = next_record_id()

        

    local_rec_dict = {

        "id": created_record_id,

        "org": dept_id,

        "category": issue_type,

        "title": summary,

        "project": "프로젝트 미지정",

        "assignee": resolved_assignee,

        "assigneeEmail": current_user.get("email", "") if current_user else "",

        "participants": "",

        "startDate": start_date,

        "dueDate": due_date,

        "date": start_date,

        "work_date": f"{start_date} ~ {due_date}" if (start_date and due_date and start_date != due_date) else start_date,

        "summary": description or summary,

        "tags": [issue_type] if issue_type else [],

        "memo": description,

        "status": target_status,

        "cardCode": created_key,

        "parentKey": parent_key or "",

        "attachments": [],

        "is_scheduled": bool(start_date or due_date)

    }

    if jira_data and jira_data.get("key"):

        local_rec_dict["jira"] = {

            "key": jira_data["key"],

            "status": target_status,

            "url": jira_data.get("url", "")

        }



    append_record(local_rec_dict)



    # Register in local schedule.json for calendar

    if start_date or due_date:

        try:

            s_start = start_date or due_date

            s_end = due_date or start_date

            cal_event = {

                "id": next_record_id(),

                "ownerKey": f"{resolved_assignee}|{org}",

                "ownerName": resolved_assignee,

                "ownerOrg": org,

                "ownerEmail": current_user.get("email", "") if current_user else "",

                "type": "업무",

                "title": f"[{created_key}] {summary}",

                "startDate": s_start,

                "endDate": s_end,

                "memo": description[:200] if description else "",

                "createdAt": datetime.now().isoformat()

            }

            # 전역 저장 락으로 보호된 read-modify-write (동시 저장 시 일정 유실 방지)

            mutate_schedule(lambda evs: evs.append(cal_event))

        except Exception as sch_err:

            log_line("[Chat Tool] schedule.json 등록 오류 (무시):", sch_err)



    # Log activity

    try:

        append_activity({

            "id": f"jarvis_chat_create_{created_key}_{int(datetime.now().timestamp()*1000)}",

            "issue_key": created_key,

            "action_type": "created",

            "action_detail": "새 업무 카드 생성 (via JARVIS Chat)",

            "author_name": submitter_name,

            "author_email": current_user.get("email", "") if current_user else "",

            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),

            "summary": summary,

            "status": target_status,

            "priority": "보통",

            "issue_type": issue_type,

            "assignee_name": resolved_assignee,

            "assignee_dept": dept.get("name") if dept else "연구소",

            "source": "jarvis_chat"

        })

    except Exception as act_err:

        log_line("[Activity] append_activity creation 오류 (무시):", act_err)



    if jira_enabled and jira_data:

        try:

            threading.Thread(target=sync_jira_cache, args=(cfg,), daemon=True).start()

        except Exception:

            pass



    trigger_async_vector_sync(cfg)



    return {

        "success": True,

        "issue_key": created_key,

        "card_code": created_key,

        "url": jira_data.get("url", "") if jira_data else "",

        "summary": summary,

        "assignee": resolved_assignee,

        "start_date": start_date,

        "due_date": due_date,

        "status": target_status,

        "note": note_msg

    }



def _tool_get_calendar_schedule(args, current_user, cfg):

    from services.data_store import read_schedule

    from services.jira_client import all_jira_due_date_events

    

    month = args.get("month")  # "YYYY-MM"

    start_date = args.get("start_date")  # "YYYY-MM-DD"

    end_date = args.get("end_date")  # "YYYY-MM-DD"

    assignee = args.get("assignee")

    

    from services.auth import visible_records, visible_schedule_events
    from services.jira_client import get_cached_jira_records
    jira_cache = get_cached_jira_records(cfg)
    vis_jira_records = visible_records(current_user, jira_cache.get("records") or [])
    # RBAC: 로컬 일정은 부서/본인/참여 기준으로 필터 (REST /api/schedule 과 동일)
    local_events = visible_schedule_events(current_user, read_schedule())
    events = local_events + all_jira_due_date_events(cfg, records=vis_jira_records)

    

    # Date filtering

    if month:

        events = [e for e in events if (e.get("startDate") or "").startswith(month) or (e.get("endDate") or "").startswith(month)]

    elif start_date and end_date:

        events = [e for e in events if (e.get("startDate", "") <= end_date and (e.get("endDate") or e.get("startDate", "")) >= start_date)]

    elif start_date:

        events = [e for e in events if (e.get("endDate") or e.get("startDate", "")) >= start_date]

    

    # Assignee filtering

    if assignee:

        events = [e for e in events if assignee in (e.get("ownerName") or "")]

    

    return {

        "count": len(events),

        "events": [{

            "title": e.get("title", ""),

            "type": e.get("type", ""),

            "start_date": e.get("startDate", ""),

            "end_date": e.get("endDate", ""),

            "owner": e.get("ownerName", ""),

            "memo": (e.get("memo") or "")[:200],

        } for e in events[:15]]

    }



def _tool_schedule_issue(args, current_user, cfg):

    from services.data_store import (

        find_record_by_key_or_code, update_record_work_date,

        read_schedule, write_schedule, next_record_id, mutate_schedule

    )

    from services.vector_store import trigger_async_vector_sync

    from datetime import datetime



    issue_key = (args.get("issue_key") or "").strip().upper()

    start_date = (args.get("start_date") or "").strip()

    due_date = (args.get("due_date") or "").strip() or start_date



    if not issue_key:

        return {"success": False, "error": "일정을 등록할 대상 업무 카드/이슈 키(예: DEV-1, VS-11)가 필요합니다."}



    if not start_date and not due_date:

        return {"success": False, "error": "시작 날짜 또는 마감 날짜가 지정되지 않았습니다."}



    if start_date and due_date and start_date > due_date:

        start_date, due_date = due_date, start_date



    log_line(f"[Chat Tool] 일정 등록 요청: {issue_key} ({start_date} ~ {due_date}) (by {current_user.get('name')})")



    local_rec = find_record_by_key_or_code(issue_key)
    from services.auth import can_modify_record
    if local_rec and not can_modify_record(current_user, local_rec):
        return {"success": False, "error": "해당 업무 카드의 일정을 변경할 권한이 없습니다."}

    jira_enabled = bool(cfg.get("jira", {}).get("enabled", False))

    jira_ok = False

    jira_note = ""



    # 1. Local SQLite records update first (Local-First!)

    summary = issue_key

    assignee_name = current_user.get("name", "담당자")

    org_name = current_user.get("org", "lab")

    display_key = issue_key



    if local_rec and local_rec.get("id"):

        update_record_work_date(local_rec["id"], start_date, due_date)

        display_key = local_rec.get("cardCode") or issue_key

        summary = local_rec.get("title") or display_key

        assignee_name = local_rec.get("assignee") or assignee_name

        org_name = local_rec.get("org") or org_name

        

        # If linked to Jira and Jira is active

        if jira_enabled and local_rec.get("jira") and local_rec["jira"].get("key"):

            from services.jira_client import update_jira_issue_dates

            jira_ok, jira_note = update_jira_issue_dates(cfg, local_rec["jira"]["key"], start_date=start_date, due_date=due_date)

    elif jira_enabled:

        from services.jira_client import update_jira_issue_dates, get_jira_issue_by_key

        jira_ok, jira_note = update_jira_issue_dates(cfg, issue_key, start_date=start_date, due_date=due_date)

        issue_info = get_jira_issue_by_key(cfg, issue_key) or {}

        summary = issue_info.get("title") or issue_info.get("summary") or f"이슈 {issue_key}"

        assignee_name = issue_info.get("assignee") or assignee_name



    # 2. Update schedule_events in local calendar

    try:

        s_start = start_date or due_date

        s_end = due_date or start_date

        new_event = {

            "id": next_record_id(),

            "ownerKey": f"{assignee_name}|{org_name}",

            "ownerName": assignee_name,

            "ownerOrg": org_name,

            "ownerEmail": current_user.get("email", ""),

            "type": "업무",

            "title": f"[{display_key}] {summary}",

            "startDate": s_start,

            "endDate": s_end,

            "memo": f"JARVIS AI Chatbot에 의해 등록된 일정 ({datetime.now().strftime('%Y-%m-%d %H:%M')})",

            "createdAt": datetime.now().isoformat()

        }

        def _apply_schedule_event(evs):

            for ev in evs:

                ev_title = ev.get("title", "")

                if f"[{display_key}]" in ev_title or f"[{issue_key}]" in ev_title or ev_title.startswith(f"{display_key} ") or ev_title == display_key:

                    ev["startDate"] = s_start

                    ev["endDate"] = s_end

                    ev["updatedAt"] = datetime.now().isoformat()

                    return

            evs.append(new_event)



        # 전역 저장 락으로 보호된 read-modify-write (동시 저장 시 일정 유실 방지)

        mutate_schedule(_apply_schedule_event)

    except Exception as sch_err:

        log_line("[Chat Tool] schedule_events 갱신 오류 (무시):", sch_err)



    # 3. Log activity

    try:

        from services.activity_store import append_activity

        append_activity({

            "id": f"jarvis_chat_sched_{display_key}_{int(datetime.now().timestamp()*1000)}",

            "issue_key": display_key,

            "action_type": "scheduled",

            "action_detail": f"일정 등록: {start_date} ~ {due_date}",

            "author_name": current_user.get("name", "사용자"),

            "author_email": current_user.get("email", ""),

            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),

            "summary": summary,

            "status": local_rec.get("status") if local_rec else "진행",

            "priority": "보통",

            "issue_type": "로컬 업무 카드" if not jira_ok else "Jira 연동",

            "assignee_name": assignee_name,

            "assignee_dept": org_name,

            "source": "jarvis_chat"

        })

    except Exception:

        pass



    trigger_async_vector_sync(cfg)



    note = f"'{display_key}' 일정이 {start_date} ~ {due_date}로 반영되었습니다."

    if jira_ok:

        note += f" (Jira 반영: {jira_note})"

    elif jira_note:

        note += f" (Jira: {jira_note})"



    return {

        "success": True,

        "issue_key": display_key,

        "start_date": start_date,

        "due_date": due_date,

        "jira_updated": jira_ok,

        "note": note

    }



def _tool_search_products(args, current_user, cfg):

    """PIM 제품 목록을 검색한다."""

    from services.data_store import read_products

    from services.product_manager import search_products

    query = (args.get("query") or "").strip()

    lifecycle_filter = args.get("lifecycle")

    category_filter = args.get("category")

    

    products = read_products(include_external=True)

    if query:

        matched = search_products(products, query)

    else:

        matched = products

        

    if lifecycle_filter:

        matched = [p for p in matched if lifecycle_filter in (p.get("lifecycle") or "")]

    if category_filter:

        matched = [p for p in matched if category_filter in (p.get("category") or "")]
    from services.auth import can_view_pim_price
    allow_price = can_view_pim_price(current_user)

    formatted_products = []
    for p in matched[:20]:
        proc = dict(p.get("procurement") or {}) if isinstance(p.get("procurement"), dict) else {}
        if not allow_price:
            for pk in ("price", "unitPrice", "cost", "supplierPrice", "targetPrice"):
                if pk in proc:
                    proc[pk] = 0
            proc["priceHidden"] = True

        formatted_products.append({
            "id": p.get("id"),
            "model": p.get("model", ""),
            "displayName": p.get("displayName", ""),
            "family": p.get("family", ""),
            "lifecycle": p.get("lifecycle", "판매 중"),
            "category": p.get("category", "일반"),
            "summary": p.get("summary", ""),
            "price": p.get("price") if allow_price else 0,
            "priceHidden": not allow_price,
            "procurement": proc if proc else None,
            "updatedAt": (p.get("updatedAt") or "")[:10]
        })

    return {
        "count": len(matched),
        "products": formatted_products
    }



def _tool_get_product_details(args, current_user, cfg):

    """특정 제품의 상세 스펙과 조달 정보를 가져온다."""

    from services.data_store import read_products

    product_id = (args.get("product_id") or "").strip()

    model = (args.get("model") or "").strip().lower()

    

    products = read_products(include_external=True)

    target = None

    for p in products:

        if product_id and p.get("id") == product_id:

            target = p

            break

        if model and (p.get("model") or "").lower() == model:

            target = p

            break

        if model and (p.get("displayName") or "").lower() == model:

            target = p

            break

            

    if not target:

        return {"found": False, "error": f"제품(ID: {product_id}, 모델명: {model})을 찾을 수 없습니다."}
    from services.auth import can_view_pim_price
    allow_price = can_view_pim_price(current_user)

    proc = dict(target.get("procurement") or {}) if isinstance(target.get("procurement"), dict) else {}
    if not allow_price:
        for pk in ("price", "unitPrice", "cost", "supplierPrice", "targetPrice"):
            if pk in proc:
                proc[pk] = 0
        proc["priceHidden"] = True

    return {
        "found": True,
        "id": target.get("id"),
        "model": target.get("model", ""),
        "displayName": target.get("displayName", ""),
        "family": target.get("family", ""),
        "lifecycle": target.get("lifecycle", "판매 중"),
        "category": target.get("category", "일반"),
        "summary": target.get("summary", ""),
        "memo": target.get("memo", ""),
        "specs": target.get("specs", {}),
        "price": target.get("price") if allow_price else 0,
        "priceHidden": not allow_price,
        "procurement": proc if proc else None,
        "attachments": [a.get("name") for a in (target.get("attachments") or []) if a.get("name")],
        "updatedAt": target.get("updatedAt", "")
    }



def _tool_generate_work_report(args, current_user, cfg):

    """주간 업무 보고서 생성 도구 (Google Sheets + Jira 통합, 관리자 전용)"""

    from services.auth import is_admin_user



    # 관리자(Admin) 권한 확인 — 팀장/관리자만 보고서 엑셀 출력 가능

    if not is_admin_user(current_user):

        user_name = current_user.get("name") if current_user else "사용자"

        log_line(f"[Security Guard] 일반 사용자 '{user_name}'의 주간 보고서 생성 시도 차단 (관리자 전용)")

        return {

            "error": "주간 업무 보고서 엑셀 출력 기능은 관리자(팀장님) 전용 권한입니다. 일반 사용자는 이용할 수 없습니다."

        }



    from services.sheets_reporter import generate_weekly_report



    assignee_input = args.get("assignee", "all")

    period = args.get("period", "this_week")

    start_date = args.get("start_date")

    end_date = args.get("end_date")



    # Resolve assignee alias

    resolved = _resolve_assignee_name(assignee_input, current_user)

    if resolved and resolved != assignee_input:

        assignee_input = resolved



    result = generate_weekly_report(

        cfg,

        assignee=assignee_input,

        period=period,

        start_date=start_date,

        end_date=end_date,

    )



    if result.get("ok"):

        summary = result.get("summary", {})

        by_src = summary.get("by_source", {})

        sheet_cnt = by_src.get("google_sheets", 0)

        jira_cnt = by_src.get("jira", 0)

        total_cnt = result.get("row_count", 0)

        return {

            "status": "success",

            "message": f"주간 업무 보고서가 성공적으로 생성되었습니다. (총 {total_cnt}건: Google Sheets {sheet_cnt}건 + Jira {jira_cnt}건 통합)",

            "filename": result.get("filename", ""),

            "download_url": result.get("download_url", ""),

            "row_count": total_cnt,

            "date_range": result.get("date_range", ""),

            "summary": summary,

        }

    else:

        return {"error": result.get("error", "보고서 생성 실패")}





def execute_tool(name, args, current_user, cfg, allow_write=False):

    """에이전트 도구를 실행하고 결과를 dict로 반환한다.

    

    Args:

        name: 도구 이름 (AGENT_TOOLS에 정의된 function name)

        args: 도구 인자 dict (AI가 생성한 arguments)

        current_user: 현재 사용자 정보 dict {"name": "...", "org": "..."}

        cfg: 서버 설정 dict

        allow_write: 쓰기 작업(생성/수정/삭제) 허용 여부 (사용자가 UI에서 확인 및 실행 버튼을 누른 경우만 True)

    

    Returns:

        dict: 도구 실행 결과 (AI에게 전달됨)

    """

    # 하드 블록 2단계: 런타임 차단 (사용자 명시 승인 없이 쓰기 도구 호출 시 즉시 거부)

    if name in WRITE_TOOL_NAMES and not allow_write:

        log_line(f"[Security Guard] AI의 쓰기 도구 직접 실행 시도 차단: {name} (사용자: {current_user.get('name')})")

        return {

            "error": f"'{name}' 직접 실행이 시스템 정책에 의해 원천 차단되었습니다. 쓰기 작업은 반드시 :::action-proposal 형식으로 작성하여 사용자 확인을 받아야 합니다."

        }



    handlers = {

        "search_issues": _tool_search_issues,

        "search_internal_records": _tool_search_internal_records,

        "search_documents": _tool_search_documents,

        "get_issue_details": _tool_get_issue_details,

        "get_child_issues": _tool_get_child_issues,

        "get_active_tasks": _tool_get_active_tasks,

        "update_issue_status": _tool_update_issue_status,

        "add_issue_comment": _tool_add_issue_comment,

        "create_issue": _tool_create_issue,

        "get_calendar_schedule": _tool_get_calendar_schedule,

        "schedule_issue": _tool_schedule_issue,

        "search_products": _tool_search_products,

        "get_product_details": _tool_get_product_details,

        "generate_work_report": _tool_generate_work_report,

    }

    handler = handlers.get(name)

    if not handler:

        return {"error": f"알 수 없는 도구: {name}"}

    try:

        return handler(args, current_user, cfg)

    except Exception as e:

        log_line(f"[Chat Tool] {name} 실행 오류:", e)

        return {"error": f"{name} 실행 중 오류: {str(e)}"}



