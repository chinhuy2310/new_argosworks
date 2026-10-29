import json
import re
import time
import threading
from datetime import datetime
from utils.logging import log_line, access_log
from services.auth import get_session
from services.chat_store import (
    list_sessions, create_session, get_session as get_chat_session,
    append_message, load_history, update_session_title, update_proposal_status
)
from services.chat_agent import run_agent_conversation
from services.chat_tools import execute_tool
from services.jira_client import jira_ongoing_records_for, get_cached_jira_records


def _chat_session_owned(chat_sess, session):
    """
    대화 세션이 현재 로그인 사용자 소유인지 판정한다 (표시 이름 + 부서).

    이름만 비교하면 부서가 다른 동명이인의 대화 기록을 읽거나 삭제할 수 있다.
    """
    if not chat_sess or not session:
        return False
    if (chat_sess.get("user_name") or "") != (session.get("name") or ""):
        return False
    return (chat_sess.get("user_org") or "") == (session.get("org") or "")


CHAT_SYSTEM_PROMPT = """
당신은 아르고스웍스(ARGOS WORKS) R&D Lab의 AI 업무 비서입니다.
현재 날짜: {today}
현재 로그인 사용자: {user_name} (이 사용자가 현재 당신과 직접 대화하고 있는 화자입니다)

{jira_context_section}

## 시스템 내부 도구 정의 (Internal Tools Definition — AI 백그라운드 호출 전용, 사용자에게 함수명 노출 절대 금지)
(⚠️ 주의: 아래 도구명들은 AI가 내부적으로 실행할 함수 이름입니다. 사용자에게 기능을 소개하거나 안내할 때 아래 함수명(`get_active_tasks`, `search_issues` 등)을 본문이나 괄호 안에 절대로 노출하지 마세요!)
1. **데이터 조회 도구 (AI가 자동으로 즉시 호출)**:
- search_issues: 사내 업무 카드 검색 (키워드, 담당자, 상태) — 특정 담당자의 모든 업무를 조회하려면 assignee에 이름 입력 (예: assignee="{user_name}")
- search_internal_records: 사내 인수인계 기록, 자체 등록 업무, 캘린더 일정 검색
- search_products: 사내 제품 정보(PIM / 제품정보 탭) 검색 (모델명, 제품명, 제품군, 판매 상태, 사양 등)
- get_product_details: 특정 제품의 상세 스펙(Specs), 조달 등록 정보, 첨부 문서 등 전체 정보 조회
- search_documents: 문서/첨부파일 시맨틱 벡터 검색
- get_issue_details: 업무 카드 상세 정보 (업무코드, 댓글, 하위작업, 마감일, 설명 포함)
- get_child_issues: 하위 작업 목록
- get_active_tasks: 진행 중인 업무 카드 목록
- get_calendar_schedule: 캘린더 일정 조회
- generate_work_report: **주간 업무 보고서 생성** — 사내 업무 카드를 취합하여 회사 양식(12열) Excel 파일을 자동 생성한다. 사용자가 "업무 보고서", "주간 보고서", "엑셀로 정리해줘", "업무 취합", "보고서 뽑아줘" 등을 요청하면 이 도구를 호출한다. 결과에 download_url이 포함되면 반드시 마크다운 링크로 다운로드 버튼을 제공: `[📥 파일명 다운로드](download_url)`

2. **데이터 생성 및 변경 (사용자 승인 카드 — Action Proposal)**:
- 작업/태스크 생성(create_task), 댓글 추가(add_comment), 상태 변경(update_status), 일정 등록(schedule_issue)은 본문 하단에 `:::action-proposal` 블록을 작성하여 사용자에게 승인 카드를 제시합니다. 사용자가 화면의 [✓ 확인 및 실행] 버튼을 누르면 시스템이 사내 로컬 DB에 즉시 등록 및 반영합니다.

{active_tasks_section}

{referenced_issues_section}

## 답변 작성 핵심 원칙 (CRITICAL INFORMATION QUALITY)
0. **내부 시스템 도구명(함수명) 노출 절대 금지 & 자연스러운 사용자 호칭 (CRITICAL UX RULE)**:
   - 🚫 **[함수명 노출 절대 금지]**: 사용자와의 대화 본문이나 기능 소개 시 `get_active_tasks`, `search_issues`, `get_issue_details`, `get_child_issues`, `search_products`, `get_product_details`, `generate_work_report`, `search_internal_records`, `get_calendar_schedule` 등 시스템 내부 도구(Function/Tool) 이름을 본문에 절대로 직접 언급하거나 괄호 안에 나열하지 마세요!
     * ❌ 금지 예시: "진행 중인 업무 확인 ( get_active_tasks )", "업무 상세 조회 ( get_issue_details )"
     * ✅ 올바른 예시: "진행 중인 업무 목록 확인", "업무 카드 상세 내용 및 댓글 이력 조회", "제품 사양 및 스펙 검색", "주간 업무 보고서 엑셀 생성"
   - 🚫 **[기계적 계정 표기 금지]**: "현재 로그인하신 계정(uy)"처럼 시스템 변수를 괄호로 감싸서 기계적으로 부르지 마세요.
     * 한국어: "{user_name}님" (예: "{user_name}님의 업무 현황이나...")
     * Tiếng Việt: "bạn {user_name}" hoặc "anh/chị {user_name}" (Ví dụ: "Tôi có thể hỗ trợ gì cho anh/chị {user_name} hôm nay?")
     * English: "{user_name}"

1. **화자 식별 및 인칭 대명사 맥락 해석 규칙 (Speaker & Contextual Pronoun Resolution - CRITICAL)**:
   - **기본 화자 인식**: 현재 로그인 사용자는 **'{user_name}'**입니다.
   - **1인칭 직접 진술 ("나", "내", "저", "제", "tôi", "mình", "me", "my tasks")**:
     * 사용자가 본인의 작업을 직접 묻는 경우(예: "내 업무 보여줘", "tôi đang làm gì", "what are my tasks"), 주체는 현재 로그인한 **'{user_name}'**입니다. 절대로 다른 사람의 이름으로 임의 변경하지 마세요.
   - **인용문 및 제3자 진술(Quoted / Reported Speech - 문맥 분석)**:
     * 사용자가 다른 사람의 발언을 인용하거나 전언하는 경우, 문맥상 따옴표나 발화 속의 '내/tôi'는 현재 화자가 아니라 **발언한 제3자**를 가리키므로, 문맥을 파악하여 질문에서 언급된 해당 제3자의 작업을 검색하세요.
   - **제3자 특정 질의**:
     * 질문에 특정 동료의 이름이나 칭호가 명시적으로 언급된 경우:
       * 로그인 사용자와 무관하게 질문에서 지칭한 **그 동료의 작업**을 검색하세요.

2. **기타 사내 기록 및 일정 검색**:
   - 사용자가 "사내 업무", "캘린더 일정", "출장", "인수인계" 등을 물어보면 반드시 **`search_internal_records`** 도구를 실행하여 로컬 인수인계 기록과 캘린더 일정을 조회해 답변하세요.

3. **제품 정보(PIM) 문의 (Product Information / PIM)**:
   - 사용자가 "제품", "sản phẩm", "model", "PIM", "hàng hóa", "thông số sản phẩm", "sản phẩm hiện có", "có sản phẩm nào không" 등을 물어보면 **반드시 `search_products`** 도구를 실행하여 사내 제품 데이터베이스(PIM 탭)를 조회하여 답변하세요.
   - 특정 제품의 상세 스펙이나 조달 등록 정보를 물어보면 **`get_product_details`** 도구를 실행하여 답변하세요.

4. **주간 업무 보고서 표(Table) 형식 및 규격**:
   - 사용자가 주간 업무 보고서나 업무 목록 표(Table) 생성을 요청할 때, **관리자(팀장님) 주간 업무 보고서의 12개 표준 열 구조**를 정확히 따르세요:
     * 표준 열: `구분` | `업무명` | `담당자` | `세부 업무명` | `유형` | `일자` | `상세내용` | `진척(%)` | `상태` | `마감일` | `사유(지연시)` | `다음 계획`
   - ⚠️ **[세부 업무명 및 유형 절대 규칙 - CRITICAL]**:
     * **`세부 업무명` 열에는 `[DEV-1]` 같은 코드 번호를 절대로 붙이지 마세요.** 오직 순수한 업무 명칭(제목)만 깔끔하게 기재하세요.
     * **`유형` 열은 반드시 `일간`(당일 완료/단기 업무) 또는 `주간`(주 단위 진행 과제/개발) 중 하나로만 표기하세요.**
     * **임의로 `ID`나 `키` 열을 새로 추가하지 마세요.** 보고서 표준 열 12개 규격을 그대로 유지하세요.
   - 검색된 전체 항목을 누락 없이 충실하게 표로 정리하세요.

5. **응답 언어 원칙 (ADAPTIVE RESPONSE LANGUAGE RULE - CRITICAL)**:
   - **사용자의 질문 언어 또는 요청 언어에 맞추어 유연하고 자연스럽게 답변하세요.**
   - 클라이언트에서 요청한 언어 코드(`lang`)나 사용자가 작성한 문장의 언어에 맞추어 답변하세요:
     * 한국어로 질문하거나 `lang='ko'`인 경우: 자연스럽고 정중한 한국어로 답변하고, 액션 카드 및 `:::quick-actions`도 한국어로 작성하세요.
     * 베트남어로 질문하거나 `lang='vi'`인 경우: 자연스럽고 전문적인 베트남어(Tiếng Việt)로 답변하고, `:::quick-actions`도 베트남어로 작성하세요.
     * 영어로 질문하거나 `lang='en'`인 경우: 명확하고 전문적인 영어(English)로 답변하고, `:::quick-actions`도 영어로 작성하세요.
   - **제3국 언어 혼입 절대 금지 (NO UNRELATED THIRD LANGUAGES)**:
     * 러시아어, 키릴 문자, 아랍어 등 질문과 무관한 엉뚱한 제3국가 언어를 사용하지 마세요.
   - **자연스러운 대화체 원칙 (NATURAL CONVERSATIONAL TONE - 로봇식 메타 설명 금지)**:
     * 시스템 지침 문구(예: "사용자의 의견을 충실히 반영하여", "임의의 과장이나 왜곡 없이" 등)를 읊조리지 말고, 사내 전문 동료처럼 군더더기 없이 자연스럽고 명확하게 본론만 답변하세요.

6. **업무 세부 내용 및 댓글(Comments) 심층 분석 원칙**:
   - `get_issue_details` 도구가 반환하는 데이터에는 `description`(기본 설명)뿐만 아니라 개발자들의 실제 **`comments`(댓글 및 진행 이력)**가 포함되어 있습니다.
   - 사용자가 업무의 "구체적인 문제(vấn đề cụ thể)", "thách thức", "khó khăn", "lỗi", "giải pháp", "tiến độ" 등을 질문할 경우, **반드시 `comments`에 기록된 실제 시행착오, 버그 원인(예: HardFault, Buffer Overflow, LTE 속도와 MCU Flash 쓰기 속도 불일치, 패킷 제한), 해결 방안, 제어 패킷/명령어(CMD 등)**를 꼼꼼히 분석하여 구체적으로 답변하세요.

7. **작업 생성/수정 제안 (Action Proposal — 사전 중복 점검 및 상황별 최적 제안)**:
   - 사용자가 새로운 업무/작업/카드/태스크 생성을 요청하거나 ("tạo thẻ...", "tạo task...", "thêm việc...", "새 작업 만들어줘", "업무 카드 생성해줘"), 이미 수행한 작업의 완료 기록 ("hôm nay đã sửa...", "hôm nay đã làm...", "오늘 수리 완료했어"), 댓글 추가, 상태 변경을 요청할 때:
   - ⚠️ **[절대 주의 - CRITICAL]**: 절대로 "AI는 카드를 직접 등록할 수 없다"고 거절하지 마세요!
   - ⚠️ **[본문 중복 출력 절대 금지 - NO DUPLICATE CONTENT]**: `:::action-proposal` 카드 자체가 시각적인 Form 카드 역할을 하므로, 본문 텍스트에 제목, 담당자, 상세 내용 등을 중복해서 일일이 적지 마세요. 본문은 1~2줄의 친절하고 깔끔한 안내 인사만 작성하고 곧바로 카드를 제시하세요!

   * **[사전 중복 검색 및 문맥 기반 스마트 제안 (Smart Contextual Workflow)]**:
     1. 사용자가 새 작업 생성을 요청하면, **먼저 `search_issues` 도구를 자동 실행하여 시스템에 이미 관련된 기존 업무 카드가 있는지 검색**하세요.
     2. **기존 관련 업무 카드가 이미 존재하는 경우 (중복 방지 및 문맥 연계)**:
        - 새로운 독립 카드를 무턱대고 바로 생성하기보다는, 검색된 기존 업무 코드와 제목, 담당자를 간결하게 안내하세요.
        - 그리고 상황에 맞게 아래 대안들을 우선 제안하세요:
          * 기존 업무 카드에 진행 상황/테스트 결과 댓글 남기기 (`add_comment` 카드 제시)
          * 기존 업무 카드의 상태를 변경하기 (`update_status` 카드 제시)
          * 기존 업무 카드의 하위 작업(Subtask)으로 추가 등록하기 (`create_subtask` 카드 제시)
        - `:::quick-actions`에도 해당 선택지(댓글 추가, 하위 작업 생성, 새 카드로 강제 생성)를 배치하세요.
     3. **기존에 관련된 업무 카드가 없거나, 사용자가 독립적인 새 작업 생성을 명시적으로 원하는 경우**:
        - 지체 없이 아래 규격의 `create_task` 카드를 즉시 제시하세요.

   * **[새 작업/하위 작업 생성 (create_task / create_subtask)]**:
     - 제목 (summary): 30자 이내의 명확하고 깔끔한 업무명
     - 상세 설명 (description): 1. 작업 목적: ...\n2. 주요 내용:\n- 세부 작업 1\n- 세부 작업 2\n3. 완료 기준: ...
     - 담당자 (assignee): 별도 지정 없으면 로그인 사용자('{user_name}').
     - 상태 (status): 이미 수행/완료된 작업이면 `완료`, 진행 중이면 `진행중`, 새로 할 작업이면 `대기`.
     - 시작일 (start_date) 및 마감일 (due_date): `YYYY-MM-DD` (오늘: {today}).
:::action-proposal
action_type: create_task
summary: [모듈명] 작업 제목
description: 1. 작업 목적: ...\n2. 주요 내용:\n- 세부 작업 1\n- 세부 작업 2\n3. 완료 기준: ...
assignee: 담당자 이름
status: 대기 | 진행중 | 완료
start_date: YYYY-MM-DD
due_date: YYYY-MM-DD
:::

   * **[하위 작업(Subtask) 생성 (create_subtask)]**:
:::action-proposal
action_type: create_subtask
issue_key: 부모업무코드
summary: [하위작업명] 세부 작업 제목
description: 1. 작업 목적: ...\n2. 주요 내용: ...\n3. 완료 기준: ...
assignee: 담당자 이름
status: 대기 | 진행중 | 완료
start_date: YYYY-MM-DD
due_date: YYYY-MM-DD
:::

   * **[댓글 추가 제안 (add_comment)]**:
     - 사용자가 어떤 업무 카드에 어떤 내용을 남길지 구체적인 댓글 내용을 아직 말하지 않은 경우:
       가상의 댓글 내용을 임의로 지어내지 말고, 먼저 사용자에게 어떤 카드에 어떤 내용을 남기실지 친절히 안내하세요.
     - 사용자가 남길 댓글 내용을 지정한 경우:
       사용자의 원래 의미를 실제 사내 업무 댓글처럼 자연스럽고 간결한 한국어로 변환하여 작성하세요.
:::action-proposal
action_type: add_comment
issue_key: 대상업무코드
comment: 실제 업무 카드에 등록할 댓글 본문 내용
:::

   * **[상태 변경 제안 (update_status)]**:
:::action-proposal
action_type: update_status
issue_key: 대상업무코드
status: 대기 | 진행중 | 완료
:::

   * **[일정 등록/수정 제안 (schedule_issue)]**:
:::action-proposal
action_type: schedule_issue
issue_key: 대상업무코드
start_date: YYYY-MM-DD
due_date: YYYY-MM-DD
:::

8. 답변 끝에 사용자가 이어서 질문할 만한 유용한 후속 질문 제안을 2~3개 추가하세요 (질문과 동일한 언어로, 절대 Jira 명칭 언급 금지):

:::quick-actions
- 제안 1
- 제안 2
- 제안 3
:::

9. 업무 코드(DEV-1 등)는 반드시 대괄호 또는 원본 코드 형태 그대로 표기하세요.
10. PIM 제품을 언급할 때 제품 ID가 있다면 `[PIM:제품ID]` 형식(예: `[PIM:prod_123]`)을 병기하거나 모델명을 명확히 표기하여 사용자가 바로 확인할 수 있도록 하세요.
"""


def _build_system_prompt(user_name, cfg, current_user=None):
    """시스템 프롬프트를 조립한다.

    RBAC: 진행 중 업무 목록도 사용자 열람 권한(visible_records)으로 필터링한 뒤 주입한다.
    """
    from services.chat_tools import _resolve_assignee_name
    from datetime import timedelta
    now_dt = datetime.now()
    today_str = now_dt.strftime("%Y-%m-%d (%A)")
    yesterday_str = (now_dt - timedelta(days=1)).strftime("%Y-%m-%d")
    tomorrow_str = (now_dt + timedelta(days=1)).strftime("%Y-%m-%d")
    today_pure = now_dt.strftime("%Y-%m-%d")

    date_context = f"{today_str} [오늘: {today_pure}, 어제: {yesterday_str}, 내일: {tomorrow_str}]"
    resolved_name = _resolve_assignee_name(user_name, {"name": user_name}) or user_name
    
    # Active tasks section (Local-First: load all ongoing tasks for user)
    active_tasks_section = ""
    try:
        from services.search import merged_records
        from services.auth import visible_records
        records, _ = merged_records(cfg)
        if current_user:
            records = visible_records(current_user, records)
        closed_statuses = {"완료", "done", "closed", "해결됨", "resolved", "종료"}
        r_name_lower = resolved_name.lower()
        ongoing = [
            r for r in records
            if ((r.get("statusName") or r.get("status") or "").strip().lower() not in closed_statuses)
            and (r_name_lower in (r.get("assignee") or "").lower() or r_name_lower in (r.get("participants") or "").lower())
        ]
        if ongoing:
            lines = [f"## 현재 {resolved_name}의 진행 중인 업무 카드 목록 (총 {len(ongoing)}건)"]
            for r in ongoing[:30]:
                key = r.get("cardCode") or (r.get("jira") or {}).get("key") or (f"#{r.get('id')}" if r.get("id") else "")
                title = r.get("title", "")
                status = r.get("statusName") or r.get("status") or "진행"
                due = r.get("dueDate") or "마감일 미지정"
                summary = (r.get("summary") or r.get("memo") or "")[:200]
                lines.append(f"- [{key}] {title} | 상태: {status} | 마감일: {due} | 상세: {summary}")
            active_tasks_section = "\n".join(lines)
    except Exception as e:
        log_line("[Chat Handler] active_tasks_section 구성 오류:", e)
    
    is_jira_enabled = bool((cfg.get("jira") or {}).get("enabled"))
    if is_jira_enabled:
        jira_context_section = """## 시스템 기본 아키텍처 및 Jira 연동 안내:
- 본 시스템은 'ARGOS WORKS' 사내 업무 관리 시스템이며, Atlassian Jira Cloud와의 실시간/주기적 양방향 연동이 활성화되어 있습니다.
- 사내 업무 카드와 연동된 Jira 이슈(티켓)를 원활하게 조회, 요약, 마감일 확인 및 주간 보고할 수 있습니다.
- 사용자가 "Jira 이슈", "Jira 티켓", "내 Jira 작업" 등을 질문하면 친절하게 해당 업무 데이터를 검색하여 답변하세요.
- 작업 생성/수정 시에는 ARGOS WORKS 사내 로컬 DB 및 Jira 연동 체계를 통해 안전하게 처리됨을 자연스럽게 안내하세요."""
    else:
        jira_context_section = """## 시스템 기본 아키텍처 (Local-First 독립 모드):
- 본 시스템은 100% 사내 로컬 독립(Local-First)의 'ARGOS WORKS' 업무 관리 시스템입니다.
- 모든 업무는 사내 로컬 DB에서 '사내 업무 카드'('thẻ công việc')로 직접 안전하게 관리됩니다.
- 현재 워크스페이스는 외부 Jira 연동이 비활성화(선택 사항)되어 있습니다.
- 사용자가 Jira에 관해 문의하면, "현재 사내 워크스페이스는 외부 Jira 연동이 비활성화된 독립 로컬 모드로 운영 중이며, 모든 작업은 ARGOS WORKS 사내 업무 카드로 안전하게 관리되고 있습니다. Jira 연동이 필요하시면 관리자에게 [환경설정 > API 연동]에서 Jira 활성화를 요청하실 수 있습니다."라고 정중하고 명확하게 안내하세요. (절대로 무조건 모른다고 부인하거나 시비조로 응대하지 마세요.)"""

    return CHAT_SYSTEM_PROMPT.format(
        today=date_context,
        user_name=user_name,
        jira_context_section=jira_context_section,
        active_tasks_section=active_tasks_section,
        referenced_issues_section=""
    )


def _extract_referenced_keys(text):
    r"""메시지에서 프로젝트 이슈 키/로컬 업무 코드 패턴([A-Z]{2,10}-\d+ 또는 #\d+)을 동적으로 추출한다."""
    NON_ISSUE_KEYS = {"RS-485", "RS-232", "RS-422", "RJ-45", "RJ-11", "CAT-5", "CAT-6"}

    matches = re.findall(r'\b[A-Za-z]{2,10}-\d+\b', text or '')
    hash_matches = re.findall(r'#\d+\b', text or '')
    all_keys = [m.upper() for m in matches if m.upper() not in NON_ISSUE_KEYS] + hash_matches
    return list(set(all_keys))



def _parse_metadata(answer_text):
    """AI 답변에서 구조화된 블록(:::action-proposal, :::quick-actions)을 추출한다."""
    result = {
        "action": "none",
        "action_proposal": None,
        "quick_actions": []
    }
    
    # Extract action-proposal
    ap_match = re.search(r':::action-proposal\r?\n(.*?)\r?\n:::', answer_text, re.DOTALL)
    if ap_match:
        raw_content = ap_match.group(1).strip()
        proposal = {}
        if raw_content.startswith('{') and raw_content.endswith('}'):
            try:
                parsed_obj = json.loads(raw_content)
                params = parsed_obj.get('parameters') or {}
                proposal = {**params, **parsed_obj}
            except Exception:
                pass
        if not proposal:
            current_key = None
            for line in raw_content.splitlines():
                m = re.match(r'^([a-zA-Z_]+)\s*:\s*(.*)$', line)
                if m:
                    current_key = m.group(1).strip()
                    proposal[current_key] = m.group(2).strip()
                elif current_key and line.strip():
                    proposal[current_key] += '\n' + line.strip()
        if not proposal.get('action_type') and (proposal.get('action') or proposal.get('type')):
            act = proposal.get('action') or proposal.get('type')
            proposal['action_type'] = 'create_task' if act == 'create_issue' else act
        if not proposal.get('summary') and proposal.get('title'):
            proposal['summary'] = proposal.get('title')
        proposal['proposal_status'] = 'pending'
        result['action_proposal'] = proposal
        result['action'] = 'propose_action'
    
    # Extract quick-actions
    qa_match = re.search(r':::quick-actions\r?\n(.*?)\r?\n:::', answer_text, re.DOTALL)
    if qa_match:
        actions = []
        for line in qa_match.group(1).strip().splitlines():
            line = line.strip().lstrip('- ').strip()
            if line:
                actions.append(line)
        result["quick_actions"] = actions[:5]
    
    return result


def _build_referenced_section(keys, cfg, current_user=None):
    """참조된 업무 카드/이슈 키에 대한 상세 정보를 시스템 프롬프트에 추가한다.

    RBAC: 현재 사용자가 열람 권한을 가진 카드만 프롬프트에 포함한다 (권한 우회 방지).
    """
    if not keys:
        return ""
    
    from services.data_store import find_record_by_key_or_code
    from services.search import merged_records
    from services.auth import visible_records, can_view_record
    
    records, _ = merged_records(cfg)
    if current_user:
        records = visible_records(current_user, records)
    lines = ["## 참조된 업무 카드/이슈 상세 (Referenced Tasks)"]
    for key in keys:
        key_upper = key.upper()
        matched = find_record_by_key_or_code(key_upper)
        if matched and current_user and not can_view_record(current_user, matched):
            # 직접 DB 조회 결과가 권한 밖이면 프롬프트에 넣지 않는다 (fail-closed)
            matched = None
        if not matched:
            for r in records:
                k = (r.get("cardCode") or (r.get("jira") or {}).get("key") or "").strip().upper()
                if k == key_upper:
                    matched = r
                    break
        if matched:
            display_k = matched.get("cardCode") or (matched.get("jira") or {}).get("key") or key_upper
            due = matched.get("dueDate") or "마감일 미지정"
            summary = (matched.get("summary") or matched.get("memo") or "")[:300]
            status = matched.get("statusName") or matched.get("status") or ""
            lines.append(f"- [{display_k}] {matched.get('title', '')} | 상태: {status} | 담당: {matched.get('assignee', '')} | 마감일: {due} | 상세: {summary}")
    return "\n".join(lines) if len(lines) > 1 else ""


def _resolve_conversation_lang(message, history, client_lang=None):
    """
    사용자의 질문 언어 및 클라이언트 언어 설정에 맞춰 자연스럽게 응답 언어를 결정합니다.
    - 베트남어 질문/설정 -> vi
    - 한국어 질문/설정 -> ko
    - 영어 질문/설정 -> en
    """
    # 1. 사용자가 특정 언어로 명시적 요청한 경우 최우선 반영
    if re.search(r'(?:trả lời\s+(?:bằng\s+)?tiếng việt|nói\s+tiếng việt|giải thích\s+(?:bằng\s+)?tiếng việt|dịch\s+(?:sang\s+)?tiếng việt|bằng\s+tiếng việt|tiếng việt\s+đi|베트남어(?:로)?(?:\s*답변|\s*설명|\s*번역|\s*말해))', message, re.I):
        return "vi"
    if re.search(r'(?:reply\s+in\s+english|answer\s+in\s+english|explain\s+in\s+english|in\s+english\s+please|speak\s+in\s+english|영어로(?:\s*답변|\s*설명|\s*말해))', message, re.I):
        return "en"
    if re.search(r'(?:한국어로|한국말(?:로)?|korean|tiếng hàn)', message, re.I):
        return "ko"

    # 2. 메시지 텍스트 내 문자셋 분석
    has_hangul = bool(re.search(r'[가-힣]', message))
    has_vietnamese = bool(re.search(r'[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđĐ]', message, re.I))
    if not has_vietnamese:
        has_vietnamese = bool(re.search(r'\b(tôi|bạn|hôm nay|công việc|làm gì|dự án|báo cáo|thẻ|sản phẩm|cho tôi|giúp tôi)\b', message, re.I))

    if has_vietnamese and not has_hangul:
        return "vi"
    if has_hangul and not has_vietnamese:
        return "ko"

    # 3. 클라이언트 UI 언어 설정 반영
    if client_lang in ("vi", "ko", "en"):
        return client_lang

    # 4. 기본값
    return "ko"


def handle_chat_stream(handler, raw_body, ip):
    """SSE 스트리밍 채팅 엔드포인트 (POST /api/chat/stream)"""
    session = handler._get_session_or_401()
    if not session:
        return
    
    user_name = session["name"]
    user_org = session.get("org", "lab")
    
    try:
        body = json.loads(raw_body.decode('utf-8')) if raw_body else {}
    except Exception:
        handler._send_json(400, {"ok": False, "error": "잘못된 요청 형식"})
        return
    
    message = (body.get("message") or "").strip()
    session_id = body.get("sessionId")
    client_lang = body.get("lang", "ko")
    custom_ai = body.get("customAi")
    
    if not message:
        handler._send_json(400, {"ok": False, "error": "메시지를 입력해주세요."})
        return
    
    cfg = handler.cfg
    allow_user_keys = bool(cfg.get("ai", {}).get("allow_user_keys", False))
    if custom_ai and not allow_user_keys:
        custom_ai = None
    
    # Session resolution
    chat_session = None
    if session_id:
        chat_session = get_chat_session(session_id)
        if chat_session and not _chat_session_owned(chat_session, session):
            handler._send_json(403, {"ok": False, "error": "접근 권한이 없습니다."})
            return
    
    if not chat_session:
        # Find most recent or create new
        sessions = list_sessions(user_name, user_org)
        if sessions:
            chat_session = sessions[0]
            session_id = chat_session["id"]
        else:
            chat_session = create_session(user_name, user_org, message[:26])
            session_id = chat_session["id"]
    
    # Update title if default
    if chat_session.get("title") in ("새로운 대화", "Đoạn chat mới", ""):
        update_session_title(session_id, message[:26])
    
    # Save user message
    append_message(session_id, "user", message, user_name)
    
    # Load context (last 20 messages)
    history = load_history(session_id, limit=20)
    
    # 언어 결정: 사용자 질의 언어에 자연스럽게 동기화
    effective_lang = _resolve_conversation_lang(message, history, client_lang)
    
    # 현재 로그인 사용자 컨텍스트 (프롬프트 구성과 도구 실행에 동일한 RBAC 기준 적용)
    current_user_ctx = {
        "id": session.get("id") or session.get("user_id"),
        "name": user_name,
        "org": user_org,
        "dept_id": user_org,
        "role": session.get("role", "member"),
        "is_admin": session.get("role") == "admin",
        "email": session.get("email", "")
    }

    # Build messages for AI
    system_prompt = _build_system_prompt(user_name, cfg, current_user_ctx)
    
    if effective_lang == "vi":
        system_prompt += (
            f"\n\n=======================================================\n"
            f"⚠️ [NGÔN NGỮ PHẢN HỒI CHÍNH THỨC - TIẾNG VIỆT]:\n"
            f"- Hãy phản hồi 100% bằng tiếng Việt tự nhiên, chuyên nghiệp và lịch sự, bao gồm cả các nút :::quick-actions.\n"
            f"- Tuyệt đối KHÔNG hiển thị các tên hàm/tool kỹ thuật như (get_active_tasks), (search_issues), (get_issue_details), (generate_work_report)... trong câu trả lời! Chỉ dùng ngôn ngữ nghiệp vụ tự nhiên.\n"
            f"- Xưng hô tự nhiên: dùng 'bạn {user_name}' hoặc 'anh/chị {user_name}', tuyệt đối KHÔNG viết kiểu máy móc 'tài khoản hiện tại ({user_name})'.\n"
            f"- [CRITICAL ARCHITECTURAL MANDATE]: Hệ thống là 100% Local-First ARGOS WORKS.\n"
            f"  Tuyệt đối không nhắc tên 'Jira' trong câu trả lời hay nút bấm!\n"
            f"  Chỉ dùng 'thẻ công việc', 'công việc' (ví dụ: 'Tạo thẻ công việc mới', 'Xem danh sách công việc của tôi').\n"
            f"=======================================================\n"
        )
    elif effective_lang == "en":
        system_prompt += (
            f"\n\n=======================================================\n"
            f"⚠️ [OFFICIAL RESPONSE LANGUAGE - ENGLISH]:\n"
            f"- Please answer 100% in natural and professional English, including the :::quick-actions.\n"
            f"- Never leak function names (e.g. get_active_tasks, search_issues) in brackets or text. Use natural business terminology.\n"
            f"- Address the user naturally as '{user_name}', not 'current logged-in account ({user_name})'.\n"
            f"- Do not mention 'Jira'; refer to all tasks as 'work cards' or 'tasks'.\n"
            f"=======================================================\n"
        )
    else:
        system_prompt += (
            f"\n\n=======================================================\n"
            f"⚠️ [기본 응답 언어 지침 - 한국어]:\n"
            f"- 100% 자연스럽고 정중한 한국어로 명확하게 답변하세요.\n"
            f"- get_active_tasks, search_issues 등 시스템 내부 함수명을 절대로 본문이나 괄호 안에 노출하지 마세요.\n"
            f"- 사용자를 '현재 로그인하신 계정({user_name})' 대신 '{user_name}님'으로 정중하게 호칭하세요.\n"
            f"- 하단의 :::quick-actions 추천 버튼들도 한국어로 작성하세요.\n"
            f"=======================================================\n"
        )
    
    # Check for referenced issue keys (RBAC: 열람 권한이 있는 카드만 프롬프트에 주입)
    ref_keys = _extract_referenced_keys(message)
    if ref_keys:
        ref_section = _build_referenced_section(ref_keys, cfg, current_user_ctx)
        system_prompt = system_prompt.replace(
            'referenced_issues_section=""',
            f'referenced_issues_section="{ref_section}"'
        )
    
    ai_messages = [{"role": "system", "content": system_prompt}]
    for h in history:
        role = h.get("role", "user")
        if role in ("user", "assistant"):
            ai_messages.append({"role": role, "content": h.get("content", "")})
    
    # Start SSE
    handler._start_sse()
    
    try:
        # Run agent with status callback
        def on_status(text):
            ok = handler._send_sse_event({"status": text})
            return ok
        
        # Keep-alive ping thread while agent runs
        stop_ping = threading.Event()
        client_disconnected = threading.Event()

        def _keep_alive():
            while not stop_ping.wait(10.0):
                try:
                    handler.wfile.write(b": ping\n\n")
                    handler.wfile.flush()
                except Exception:
                    client_disconnected.set()
                    break
        ping_thread = threading.Thread(target=_keep_alive, daemon=True)
        ping_thread.start()

        # 인증 세션 기반 사용자 컨텍스트 (이미 위에서 구성됨 — RBAC 일관성 유지)
        answer = run_agent_conversation(
            messages=ai_messages,
            current_user=current_user_ctx,
            cfg=cfg,
            lang=effective_lang,
            on_status_update=on_status,
            max_turns=4,
            custom_ai_config=custom_ai
        )
        stop_ping.set()

        if client_disconnected.is_set():
            log_line(f"[Chat Stream] 클라이언트 연결 조기 종료 감지: session={session_id}")
            return
        
        # Stream answer in chunks (smooth typewriter effect)
        CHUNK_SIZE = 35
        for i in range(0, len(answer), CHUNK_SIZE):
            chunk = answer[i:i + CHUNK_SIZE]
            ok = handler._send_sse_event({"text": chunk})
            if not ok:
                log_line(f"[Chat Stream] 클라이언트 브라우저 닫힘(BrokenPipe) -> 전송 조기 중단: {session_id}")
                return
            time.sleep(0.012)  # 12ms delay for smooth streaming
        
        # Parse metadata
        metadata = _parse_metadata(answer)
        
        # Context warning
        if len(history) >= 20:
            metadata["context_warning"] = True
        
        # Save assistant message
        saved_msg = append_message(session_id, "assistant", answer, "AI", metadata=metadata)
        
        # Track AI Token Usage per user & session
        try:
            from services.ai_usage_service import record_ai_usage
            # Estimate prompt tokens from system_prompt + message
            p_tok = (len(system_prompt) + len(message)) // 3
            c_tok = len(answer) // 3
            t_tok = p_tok + c_tok
            ai_prov = (custom_ai or {}).get("provider") or cfg.get("ai", {}).get("provider", "gemini")
            ai_mod = (custom_ai or {}).get("model") or cfg.get("ai", {}).get("model", "")
            record_ai_usage(
                user_name=user_name,
                dept_id=user_org,
                provider=ai_prov,
                model=ai_mod,
                prompt_tokens=p_tok,
                completion_tokens=c_tok,
                total_tokens=t_tok,
                session_id=session_id,
                feature="chat"
            )
        except Exception as e:
            log_line("[AI Usage] record failed:", e)

        # Send completion event
        handler._send_sse_event({
            "done": True,
            "metadata": metadata,
            "sessionId": session_id,
            "messageId": saved_msg.get("id") if saved_msg else None
        })
        
    except (BrokenPipeError, ConnectionResetError):
        log_line(f"[Chat Stream] 클라이언트 연결 끊김(소켓 종료): {session_id}")
        stop_ping.set()
        return

    except Exception as e:
        log_line("[Chat Stream] 오류:", e)
        handler._send_sse_event({"error": f"채팅 처리 중 오류: {str(e)}"})
    
    handler._end_sse()
    access_log(ip, "chat_stream", 200, f"session={session_id} msg={message[:40]}")


def handle_list_sessions(handler, parsed, ip):
    """GET /api/chat/sessions — 세션 목록 조회"""
    session = handler._get_session_or_401()
    if not session:
        return
    sessions = list_sessions(session["name"], session.get("org", ""))
    handler._send_json(200, {"ok": True, "sessions": sessions})


def handle_create_session(handler, raw_body, ip):
    """POST /api/chat/sessions — 새 세션 생성"""
    session = handler._get_session_or_401()
    if not session:
        return
    body = {}
    if raw_body:
        try:
            body = json.loads(raw_body.decode('utf-8'))
        except Exception:
            pass
    title = body.get("title", "새로운 대화")
    new_sess = create_session(session["name"], session.get("org", ""), title)
    handler._send_json(200, {"ok": True, "session": new_sess})
    access_log(ip, "chat_create_session", 200, new_sess["id"])


def handle_delete_session(handler, raw_body, ip):
    """POST /api/chat/sessions/delete — 세션 삭제"""
    session = handler._get_session_or_401()
    if not session:
        return
    body = {}
    if raw_body:
        try:
            body = json.loads(raw_body.decode('utf-8'))
        except Exception:
            pass
    session_id = body.get("sessionId", "")
    if not session_id:
        handler._send_json(400, {"ok": False, "error": "sessionId가 필요합니다."})
        return
    from services.chat_store import delete_session
    ok = delete_session(session_id, session["name"], session.get("org", ""))
    handler._send_json(200, {"ok": ok})
    access_log(ip, "chat_delete_session", 200, session_id)


def handle_get_history(handler, parsed, ip):
    """GET /api/chat/history — 채팅 히스토리 조회 (커서 기반 페이지네이션)"""
    session = handler._get_session_or_401()
    if not session:
        return
    from urllib.parse import parse_qs
    qs = parse_qs(parsed.query)
    session_id = (qs.get("sessionId", [""])[0])
    before_id = qs.get("beforeId", [None])[0]
    # ?limit=abc 이전에는 ValueError(500), 음수 limit 은 LIMIT -1(전체 조회)이 되었다.
    try:
        limit = int(qs.get("limit", ["20"])[0])
    except (TypeError, ValueError):
        limit = 20
    limit = max(1, min(limit, 100))

    if not session_id:
        handler._send_json(400, {"ok": False, "error": "sessionId가 필요합니다."})
        return

    # Verify session ownership (fail-closed: unknown session id → 404)
    chat_sess = get_chat_session(session_id)
    if not chat_sess:
        handler._send_json(404, {"ok": False, "error": "대화 세션을 찾을 수 없습니다."})
        return
    if not _chat_session_owned(chat_sess, session):
        handler._send_json(403, {"ok": False, "error": "접근 권한이 없습니다."})
        return
    
    try:
        if before_id:
            before_id = int(before_id)
    except (ValueError, TypeError):
        before_id = None
    
    messages = load_history(session_id, limit=limit, before_id=before_id)
    handler._send_json(200, {"ok": True, "messages": messages, "hasMore": len(messages) >= limit})


def handle_execute_action(handler, raw_body, ip):
    """POST /api/chat/execute-action — 사용자가 확인한 액션 실행"""
    session = handler._get_session_or_401()
    if not session:
        return
    
    body = {}
    if raw_body:
        try:
            body = json.loads(raw_body.decode('utf-8'))
        except Exception:
            handler._send_json(400, {"ok": False, "error": "잘못된 요청"})
            return
    
    action_type = body.get("action_type", "")
    cfg = handler.cfg
    # Pass full authenticated session (id, role, name, org, email) for proper RBAC & license checks
    current_user = {
        "id": session.get("id") or session.get("user_id"),
        "name": session["name"],
        "org": session.get("org", "lab"),
        "dept_id": session.get("org", "lab"),
        "role": session.get("role", "member"),
        "is_admin": session.get("role") == "admin",
        "email": session.get("email", "")
    }
    
    # Map action_type to tool name
    action_tool_map = {
        "create_task": "create_issue",
        "create_subtask": "create_issue",
        "add_comment": "add_issue_comment",
        "update_status": "update_issue_status",
        "schedule_issue": "schedule_issue",
    }
    
    tool_name = action_tool_map.get(action_type)
    if not tool_name:
        handler._send_json(400, {"ok": False, "error": f"알 수 없는 액션: {action_type}"})
        return
    
    # Build tool args from body
    tool_args = {}
    if action_type in ("create_task", "create_subtask"):
        is_sub = (action_type == "create_subtask")
        tool_args = {
            "summary": body.get("summary", ""),
            "description": body.get("description", ""),
            "issue_type": body.get("issue_type") or ("하위 작업" if is_sub else "메인프로젝트"),
            "parent_key": (body.get("parent_key") or body.get("issue_key")) if is_sub else None,
            "priority": body.get("priority", "Medium"),
            "assignee": body.get("assignee"),
            "status": body.get("status"),
            "start_date": body.get("start_date"),
            "due_date": body.get("due_date"),
        }
    elif action_type == "add_comment":
        tool_args = {
            "issue_key": body.get("issue_key", ""),
            "comment": body.get("comment") or body.get("description") or body.get("summary", ""),
        }
    elif action_type == "update_status":
        tool_args = {
            "issue_key": body.get("issue_key", ""),
            "status": body.get("status", ""),
        }
    elif action_type == "schedule_issue":
        tool_args = {
            "issue_key": body.get("issue_key", ""),
            "start_date": body.get("start_date", ""),
            "due_date": body.get("due_date", ""),
        }
    
    # 사용자가 UI에서 직접 승인한 액션이므로 allow_write=True 허용
    result = execute_tool(tool_name, tool_args, current_user, cfg, allow_write=True)
    
    # Persist proposal status as executed if session_id provided
    session_id = body.get("session_id") or body.get("sessionId")
    if session_id and result and (result.get("success") or result.get("ok") or not result.get("error")):
        try:
            update_proposal_status(
                session_id=session_id,
                status="executed",
                message_id=body.get("message_id") or body.get("messageId"),
                summary=body.get("summary"),
                action_type=action_type,
                user_name=session["name"],
                user_dept_id=session.get("org", "")
            )
        except Exception as e:
            log_line("executed 상태 저장 오류:", e)
            
    handler._send_json(200, {"ok": True, "result": result})
    access_log(ip, f"chat_action_{action_type}", 200, body.get("issue_key", ""))


def handle_cancel_action(handler, raw_body, ip):
    """POST /api/chat/cancel-action — 액션 제안 취소 상태를 영구 저장한다."""
    session = handler._get_session_or_401()
    if not session:
        return
    body = {}
    if raw_body:
        try:
            body = json.loads(raw_body.decode('utf-8'))
        except Exception:
            handler._send_json(400, {"ok": False, "error": "잘못된 요청"})
            return
            
    session_id = body.get("sessionId") or body.get("session_id")
    message_id = body.get("messageId") or body.get("message_id")
    summary = body.get("summary")
    action_type = body.get("action_type") or body.get("actionType")
    
    ok = False
    if session_id:
        ok = update_proposal_status(
            session_id=session_id,
            status="cancelled",
            message_id=message_id,
            summary=summary,
            action_type=action_type,
            user_name=session["name"],
            user_dept_id=session.get("org", "")
        )
    handler._send_json(200, {"ok": True, "updated": ok})
