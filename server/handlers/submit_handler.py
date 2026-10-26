import json
import re
import os
from datetime import date, datetime
from config import ATTACH_DIR
from utils.logging import access_log
from services.data_store import read_departments, append_record, get_next_card_code
from utils.text import dept_by_id

# ---- /api/submit (POST, multipart/form-data) ----
def handle_submit(handler, raw_body, ip):
    content_type = handler.headers.get("Content-Type", "")
    m = re.search(r'boundary="?([^";]+)"?', content_type)
    if not m:
        handler._send_json(400, {"ok": False, "error": "multipart/form-data 요청이 아닙니다."})
        return
    
    # Kiểm tra xác thực phiên đăng nhập (Ngăn chặn bypass qua F12 / curl / Postman)
    session = handler._get_session_or_401()
    if not session:
        return

    from services.license_manager import is_system_read_only
    if is_system_read_only():
        handler._send_json(403, {"ok": False, "error": "라이선스가 만료되어 시스템이 읽기 전용(Read-Only) 상태입니다. 관리자에게 문의하세요."})
        return

    from services.auth import get_user_role
    if get_user_role(session) == "viewer":
        handler._send_json(403, {"ok": False, "error": "조회 전용(Viewer) 권한의 사용자는 업무를 등록하거나 수정할 수 없습니다."})
        return

    from utils.multipart import parse_multipart
    from utils.file_ops import sanitize_filename
    from utils.text import sanitize_label, guess_category
    from services.data_store import next_record_id
    from services.ai_client import call_ai_classify as call_claude_classify
    from services.jira_client import jira_project_for_dept, get_cached_categories, lookup_jira_account_id, create_jira_issue
    
    fields, files = parse_multipart(raw_body, m.group(1))

    org = (fields.get("org") or "").strip()
    depts = read_departments()
    dept = dept_by_id(depts, org)
    if not dept:
        handler._send_json(400, {"ok": False, "error": "유효하지 않은 소속입니다."})
        return

    # RBAC: 일반 사용자(member)는 본인 소속 부서의 업무만 등록 가능
    user_role = get_user_role(session)
    user_dept = (session.get("org") or session.get("dept_id") or "").strip().lower()
    if user_role == "member" and user_dept and user_dept != org.lower():
        handler._send_json(403, {"ok": False, "error": "일반 사용자는 본인 소속 부서의 업무만 등록할 수 있습니다."})
        return

    memo = (fields.get("memo") or "").strip()
    user_title = (fields.get("title") or "").strip()
    if not user_title and not memo and not files:
        handler._send_json(400, {"ok": False, "error": "제목, 파일 또는 메모 중 하나는 입력해주세요."})
        return

    assignee_name = (fields.get("assigneeName") or "").strip() or "이름 미상"
    assignee_email = (fields.get("assigneeEmail") or "").strip()
    project = (fields.get("project") or "").strip() or "프로젝트 미지정"
    category = (fields.get("category") or "").strip()
    submitted_category = category  # 자동 분류로 덮어쓰기 전, 사용자가 실제로 고른 값
    parent_key = (fields.get("parentKey") or "").strip().upper() or None
    if parent_key:
        from services.data_store import find_record_by_key_or_code
        from services.auth import can_view_record
        parent_rec = find_record_by_key_or_code(parent_key)
        if parent_rec and not can_view_record(session, parent_rec):
            handler._send_json(403, {"ok": False, "error": "상위 작업에 대한 열람 권한이 없어 하위 작업을 생성할 수 없습니다."})
            return
    participants = (fields.get("participants") or "").strip()
    if participants and assignee_name:
        parts_list = [p.strip() for p in participants.replace(";", ",").split(",") if p.strip()]
        parts_list = [p for p in parts_list if p.lower() != assignee_name.lower()]
        participants = ", ".join(parts_list)
    followup = (fields.get("followup") or "").lower() in ("1", "true", "on", "yes")
    priority = (fields.get("priority") or "보통").strip()
    if priority not in ("낮음", "보통", "높음", "긴급"):
        priority = "보통" 
    start_date = (fields.get("startDate") or fields.get("start_date") or fields.get("date") or "").strip()
    due_date = (fields.get("dueDate") or fields.get("due_date") or fields.get("endDate") or fields.get("end_date") or "").strip()
    if not start_date and due_date:
        start_date = due_date
    elif not start_date:
        start_date = date.today().strftime("%Y-%m-%d")
    if not due_date:
        due_date = start_date

    if start_date and due_date and start_date > due_date:
        handler._send_json(400, {"ok": False, "error": "마감일은 시작일보다 빠를 수 없습니다. (마감일 >= 시작일)"})
        return

    filenames = [sanitize_filename(f["filename"]) for f in files]

    claude_result = None
    if not category:
        ai_cfg = handler.cfg.get("ai", {})
        legacy_anthropic = handler.cfg.get("anthropic", {})
        ai_active = bool((ai_cfg.get("enabled") and (ai_cfg.get("api_key") or ai_cfg.get("provider") == "ollama")) or (legacy_anthropic.get("enabled") and legacy_anthropic.get("api_key")))
        if ai_active:
            claude_result = call_claude_classify(handler.cfg, memo, filenames, dept["name"])
            
    if claude_result and claude_result.get("category"):
        category = claude_result["category"]
    elif not category:
        category = "기타업무"

    if claude_result and claude_result.get("summary"):
        summary = claude_result["summary"]
    elif memo:
        summary = memo
    elif user_title:
        summary = user_title
    elif files:
        summary = "첨부 파일 %d건에 대한 기록입니다. (분류: %s)" % (len(files), category)
    else:
        summary = ""

    record_id = next_record_id()
    if user_title:
        title = user_title
    elif memo:
        title = memo[:28] + ("…" if len(memo) > 28 else "")
    elif filenames:
        title = filenames[0]
    else:
        title = "제목 없는 기록"

    # 첨부파일 저장
    saved_attachments = []
    if files:
        from utils.image_optimizer import optimize_and_save_file
        record_attach_dir = os.path.join(ATTACH_DIR, str(record_id))
        os.makedirs(record_attach_dir, exist_ok=True)
        for f in files:
            fname = sanitize_filename(f["filename"])
            dest = os.path.join(record_attach_dir, fname)
            optimize_and_save_file(f["data"], dest)
            saved_attachments.append(fname)

    # Jira 티켓 (후속조치 체크 시에만)
    jira = None
    jira_note = None
    jira_enabled = bool(handler.cfg.get("jira", {}).get("enabled", False))
    if followup and jira_enabled:
        labels = ["ARGOS_WORKS_발행", "부서_" + sanitize_label(dept["name"]), "분류_" + sanitize_label(category)]
        description = memo or summary
        if participants:
            description += "\n\n참여자: " + participants
        if saved_attachments:
            description += "\n\n첨부파일: " + ", ".join(saved_attachments)
        description += f"\n\n[ARGOS WORKS 등록] 제출자: {assignee_name} ({dept['name']})"

        project_key, default_issue_type = jira_project_for_dept(handler.cfg, dept["id"])
        if not project_key:
            jira, jira_note = None, "'%s' 부서에는 아직 Jira 프로젝트가 연결되지 않았습니다. config.json의 jira.project_map에 추가해주세요." % dept["name"]
        else:
            # 사용자가 그 부서의 실제 Jira 카테고리(=이슈 타입) 목록에서 고른
            # 값이면 그 이슈 타입 그대로 생성한다 — 이게 이번에 매칭시킨 부분.
            # 자동 분류로 채워진 값이거나 목록에 없는 값이면(구버전 자유 텍스트 등)
            # 존재하지 않는 이슈 타입 이름을 그대로 보내 생성 자체가 깨지는 걸
            # 막기 위해 부서 기본 이슈 타입으로 안전하게 대체한다.
            # If a parent task is selected, this is a subtask
            if parent_key:
                proj_info = handler.cfg.get("jira", {}).get("project_map", {}).get(dept["id"], {})
                issue_type = proj_info.get("subtask_type") or handler.cfg.get("jira", {}).get("default_subtask_type") or "Subtask"
            else:
                real_categories = get_cached_categories(handler.cfg, dept["id"])
                if submitted_category and submitted_category in real_categories:
                    issue_type = submitted_category
                else:
                    issue_type = default_issue_type

            # 실제 제출자를 Jira의 보고자(Reporter)/담당자(assignee)로 그대로 매칭한다 —
            # 이메일로 먼저 찾고, 못 찾으면 이름으로 한 번 더 시도한다.
            submitter_account_id = lookup_jira_account_id(handler.cfg, assignee_email) or \
                lookup_jira_account_id(handler.cfg, assignee_name)
            jira, jira_note = create_jira_issue(
                handler.cfg, project_key, issue_type, title, description, labels, due_date or None,
                submitter_account_id=submitter_account_id, parent_key=parent_key
            )

    # Determine cardCode: Jira key if created, else localPrefix-sequence
    if jira and jira.get("key"):
        card_code = jira["key"]
    else:
        dept_prefix = (dept.get("localPrefix") or "").strip() or "REC"
        card_code = get_next_card_code(dept["id"], dept_prefix)

    record = {
        "id": record_id,
        "org": dept["id"],
        "category": category,
        "title": title,
        "project": project,
        "assignee": assignee_name,
        "assigneeEmail": assignee_email,
        "participants": participants,
        "startDate": start_date,
        "dueDate": due_date,
        "date": start_date,
        "work_date": f"{start_date} ~ {due_date}" if (start_date and due_date and start_date != due_date) else start_date,
        "summary": summary,
        "tags": [category],
        "memo": memo,
        "cardCode": card_code,
        "attachments": saved_attachments,
        "parentKey": parent_key,
        "priority": priority,
        "jira": jira
    }
    append_record(record)
    access_log(ip, "submit", 200, "id=%s org=%s code=%s jira=%s" % (record_id, dept["id"], card_code, jira["key"] if jira else "-"))

    # Log to JARVIS activity store
    try:
        from services.activity_store import append_activity
        append_activity({
            "id": f"jarvis_rec_{record_id}",
            "issue_key": card_code,
            "action_type": "created",
            "action_detail": f"{category} · {summary[:80]}" if summary else category,
            "author_name": assignee_name,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "summary": title or summary or card_code,
            "status": (jira.get("statusName") if jira else "진행"),
            "priority": priority,
            "issue_type": category,
            "assignee_name": assignee_name,
            "assignee_dept": dept["name"],
            "source": "jarvis"
        })
    except Exception:
        pass

    try:
        from services.notification_service import trigger_task_assigned_notification
        author_name = session.get("name") if session else assignee_name
        trigger_task_assigned_notification(
            record_id=card_code or record_id,
            title=title or summary or "새 업무",
            author_name=author_name or "사용자",
            assignee_name=assignee_name,
            assignee_email=assignee_email,
            participants=participants
        )
    except Exception:
        pass

    try:
        from services.vector_store import trigger_async_vector_sync
        trigger_async_vector_sync(handler.cfg)
    except Exception:
        pass

    try:
        from services.audit_logger import log_audit
        log_audit(
            session=session,
            ip=ip,
            action="RECORD_CREATE",
            target_type="record",
            target_id=str(record_id),
            details={"card_code": card_code, "title": title or summary, "dept_id": org, "assignee": assignee_name}
        )
    except Exception:
        pass

    handler._send_json(200, {"ok": True, "record": record, "jiraNote": jira_note})
