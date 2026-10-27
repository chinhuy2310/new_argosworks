/**
 * i18n.js - Multi-language support (KO / EN)
 * 한국어 (Korean) & English (영어)
 * Supports dynamic real-time language switching without page reloads.
 */

(function(window) {
  "use strict";

  var TRANSLATIONS = {
    ko: {
      // General / Topbar
      "app.title": "ARGOS WORKS - 업무 인수인계 및 AI 협업 기록 시스템",
      "nav.home": "홈",
      "nav.dash": "대시보드",
      "nav.jira": "업무 등록",
      "nav.schedule": "일정",
      "nav.pim": "제품정보",
      "nav.chat": "업무 비서",
      "nav.history": "업무 이력",
      "nav.settings": "환경설정",
      "nav.main_section": "메인 업무",
      "nav.admin_section": "관리자 전용",
      "nav.toggle_menu": "메뉴 접기/펼치기",
      "nav.theme_toggle": "다크 / 라이트 모드 전환",
      "nav.lang_toggle": "언어 변경 (KO / EN)",
      "nav.theme": "화면 모드",
      "nav.theme_dark": "다크 모드",
      "nav.theme_light": "라이트 모드",
      "nav.lang": "언어",
      "nav.notifications": "알림",
      "auth.account_menu": "계정 및 설정",
      "auth.guest_title": "로그인이 필요합니다",
      "auth.guest_desc": "ArgosWorks 서비스 이용을 위해 로그인하세요",
      "auth.login_start": "로그인 / 시작",
      "auth.logout": "로그아웃",

      // Topbar Page Titles
      "title.home": "홈",
      "title.dash": "대시보드",
      "title.form": "업무 등록",
      "title.schedule": "사내 일정",
      "title.pim": "제품 정보 (PIM)",
      "title.chat": "AI 업무 비서",
      "title.history": "업무 이력 로그",
      "title.settings": "환경설정",

      // Submit Form Guest Notice
      "form.guest_title": "로그인이 필요한 기능입니다",
      "form.guest_desc": "새로운 업무 카드 등록 및 작업 배정은 사내 인증 계정으로 로그인한 사용자만 이용할 수 있습니다.<br>계정으로 로그인하여 업무 등록을 진행해 주세요.",
      "form.guest_login_btn": "로그인하기",
      "form.guest_home_btn": "홈으로 이동",

      // Dashboard Categories & Filter Toolbar
      "dept.all": "전체",
      "dept.waiting_count": "대기 {count}건",
      "dept.no_waiting": "대기 없음",
      "dept.add_btn": "+ 부서 추가",
      "dept.add_title": "새 부서 추가",
      "dept.edit_title": "부서 정보 수정",
      "dept.manage_btn": "⚙ 부서 관리",
      "dept.manage_done": "✓ 관리 완료",
      "dept.edit_btn": "수정",
      "dept.del_btn": "삭제",
      "dept.name_label": "부서명",
      "dept.name_ph": "예: 연구개발팀, B2B사업팀, 인사총무팀",
      "dept.name_hint": "대시보드 카드 및 필터에 표시될 부서 명칭입니다.",
      "dept.local_label": "로컬 카드 코드 (Local Prefix)",
      "dept.local_ph": "예: DEV (카드 코드: DEV-1, DEV-2...)",
      "dept.local_hint": "로컬 저장 시 자동 채번될 카드 코드 접두사입니다.",
      "dept.jira_label": "Jira 연동 코드 (Project Key)",
      "dept.jira_ph": "예: ARGOS (Jira 프로젝트 키)",
      "dept.jira_hint": "Jira 이슈와 자동 동기화할 프로젝트 키입니다.",
      "dept.modal_cancel": "취소",
      "dept.modal_submit": "추가",
      "dept.modal_update": "저장",
      "dept.toast_added": '"{name}" 부서를 추가했습니다.',
      "dept.toast_updated": '"{name}" 부서 정보가 수정되었습니다.',
      "dept.toast_exists": "이미 등록된 부서명입니다.",
      "dept.toast_failed": "부서 저장에 실패했습니다.",
      "dept.toast_deleted": '"{name}" 부서가 삭제되었습니다.',
      "dept.toast_del_confirm": '"{name}" 부서를 삭제하시겠습니까?',
      "dept.custom_types_label": "사내 고유 업무 유형 (선택, 쉼표 구분)",
      "dept.custom_types_ph": "예: 회의, 업무인수인계, 내부검토, 일일보고",
      "dept.custom_types_hint": "사내에서 자유롭게 사용할 세부 업무 유형들을 쉼표(,)로 구분해 등록합니다. (선택 사항)",

      // Toolbar filters
      "filter.all_assignees": "전체 담당자",
      "filter.all_categories": "전체 카테고리",
      "filter.view_tree": "트리 보기",
      "filter.view_assignee": "담당자별 그룹",
      "filter.view_flat": "플랫 보기",
      "filter.status_all": "모든 상태",
      "filter.status_inprog": "진행",
      "filter.status_review": "검토",
      "filter.status_todo": "예정",
      "filter.status_done": "완료",
      "filter.status_delayed": "지연",
      "filter.search_ph": "🔍 이슈 키, 요약 검색...",
      "filter.sync_jira": "↙ Jira 동기화",
      "filter.expand_all": "📂 모두 펼치기",
      "filter.collapse_all": "📁 모두 접기",
      "filter.create_task": "➕ 새 작업 등록",
      "filter.btn_excel": "엑셀",
      "filter.export_excel": "현재 업무 목록을 엑셀(.xlsx)로 다운로드",
      "filter.assignee_panel_title": "담당자별 현황",
      "filter.view_table": "상세 표",
      "filter.col_assignee": "담당자",
      "filter.col_dept": "소속",
      "filter.col_category": "카테고리",
      "filter.col_progress": "진행률",
      "filter.col_total_assigned": "담당 건수",
      "filter.col_total_assigned_title": "전체 담당 업무 (완료 포함)",
      "filter.table_collapse": "표 접기",
      "filter.table_expand": "상세 표 보기",
      "filter.table_close": "표 닫기",
      "filter.toggle_table_title": "상세 표 접기/펼치기",
      "filter.assignee_empty": "선택한 부서의 담당자 현황 데이터가 없습니다.",
      "filter.assigned_count": "담당 {count}건",
      "filter.weighted_progress": "가중 진행률",
      "filter.status_label": "상태",

      // Dashboard View Modes & Captions
      "filter.records_flat_title": "전체 기록 (플랫 보기)",
      "filter.records_assignee_title": "담당자별 그룹 보기",
      "filter.records_tree_title": "전체 기록 (트리 보기)",
      "filter.showing_items_of": "표시 중 {rendered}건 · 전체 {total}건 (스크롤하여 더 보기)",
      "filter.showing_groups_of": "표시 중 {rendered}개 그룹 · 전체 {total}건 (스크롤하여 더 보기)",
      "filter.total_items": "전체 {total}건",
      "filter.records_assignee_caption": "총 {members}명 · {total}건",
      "filter.tree_caption_summary": "총 {total}건 ({groups}개 그룹)",

      // Common counts & nouns
      "common.person_count": "{count}명",
      "common.count_tasks": "{count}건",
      "common.zero_items": "0건",
      "common.unassigned": "미배정",
      "common.select_placeholder": "선택하세요",

      // Cards & Tree
      "card.subtask_title": "하위 작업 {count}건 펼치기/접기",
      "card.subtask_hint": "하위 작업 {count}건 (클릭하여 캔버스에서 확인)",
      "card.subtask_badge": "하위 {count}건",
      "card.parent_prefix": "상위:",
      "card.parent_ref": "상위: {key}",
      "card.participants_title": "참여자: {list}",
      "card.click_to_open_canvas": "클릭하여 캔버스 열기",

      // Edit Profile Modal
      "profile.modal_title": "내 정보 수정",
      "profile.avatar_title": "프로필 사진 (Avatar)",
      "profile.change_photo": "사진 변경",
      "profile.reset_photo": "기본값으로 복원",
      "profile.avatar_hint": "JPG, PNG, WebP (권장 1:1 비율, 최대 5MB)",
      "profile.name_label": "이름 (성명)",
      "profile.name_ph": "이름 입력",
      "profile.email_label": "이메일",
      "profile.email_ph": "user@company.com",
      "profile.org_label": "소속 부서 (조직)",
      "profile.current_password_label": "현재 비밀번호",
      "profile.current_password_ph": "현재 비밀번호 입력",
      "profile.optional_change_only": "(변경 시에만 입력)",
      "profile.password_label": "새 비밀번호",
      "profile.password_ph": "최소 8자 이상 (비워두면 기존 유지)",
      "profile.confirm_password_label": "새 비밀번호 확인",
      "profile.confirm_password_ph": "새 비밀번호 재입력",
      "profile.err_current_required": "현재 비밀번호를 입력해주세요.",
      "profile.err_new_required": "새 비밀번호를 입력해주세요.",
      "profile.err_confirm_required": "새 비밀번호 확인을 입력해주세요.",
      "profile.err_too_short": "보안 강화를 위해 비밀번호는 최소 8자 이상이어야 합니다.",
      "profile.err_mismatch": "새 비밀번호가 일치하지 않습니다. 다시 확인해주세요.",
      "admin_user.id_label": "사용자 ID",
      "admin_user.new_password_label": "새 비밀번호 (재설정 시에만 입력)",
      "admin_user.new_password_ph": "변경하지 않을 경우 공란으로 둡니다 (최소 8자)",
      "admin_user.new_password_confirm_label": "새 비밀번호 확인",
      "admin_user.new_password_confirm_ph": "새 비밀번호 재입력",
      "admin_user.err_new_required": "새 비밀번호를 입력해주세요.",
      "admin_user.err_confirm_required": "새 비밀번호 확인을 입력해주세요.",
      "admin_user.err_too_short": "비밀번호는 최소 8자 이상이어야 합니다.",
      "admin_user.err_mismatch": "새 비밀번호가 일치하지 않습니다. 다시 확인해주세요.",
      "profile.btn_cancel": "취소",
      "profile.btn_submit": "저장하기",

      // Record Edit Modal
      "record_edit.modal_title": "업무 정보 수정",
      "record_edit.title_label": "제목",
      "record_edit.title_ph": "업무 제목 입력",
      "record_edit.assignee_label": "담당자",
      "record_edit.participants_label": "참여자",
      "record_edit.participants_ph": "예: 홍길동, 김철수 (쉼표 구분)",
      "record_edit.parent_label": "상위 작업",
      "record_edit.parent_optional": "(선택)",
      "record_edit.parent_none": "(상위 작업 없음 / 최상위 작업으로 설정)",
      "record_edit.parent_ph": "상위 작업 검색 (코드 또는 제목 입력)",
      "record_edit.start_date_label": "시작일",
      "record_edit.due_date_label": "마감일",
      "record_edit.memo_label": "상세 내용 / 메모",
      "record_edit.memo_ph": "업무 상세 설명 또는 진행 메모",
      "record_edit.btn_cancel": "취소",
      "record_edit.btn_submit": "저장하기",

      // Product Category Modal
      "prod_cat.modal_title": "제품 카테고리 및 규격 설정",
      "prod_cat.name_label": "제품 카테고리명",
      "prod_cat.name_ph": "예: IP 카메라, AI 서버, IoT 센서, 클라우드 SW",
      "prod_cat.spec_fields_label": "제품별 규격 입력 항목 (Custom Spec Fields)",
      "prod_cat.btn_add_field": "+ 항목 추가",
      "prod_cat.spec_fields_hint": "이 카테고리의 제품 등록 시 입력받을 규격(해상도, 전원, 라이선스, 배터리 등)을 정의합니다.",
      "prod_cat.col_group": "그룹 (Group)",
      "prod_cat.col_label": "항목명 (Label)",
      "prod_cat.col_key": "변수키 (Key)",
      "prod_cat.col_delete": "삭제",
      "prod_cat.btn_cancel": "취소",
      "prod_cat.btn_submit": "저장하기",

      // Home View Search
      "home.search_ph": "사내 업무, 제품 모델명, 일정, 담당자 검색...",
      "home.search_btn": "검색",
      "home.sub": "사내 업무 기록 · 인수인계 · 제품 정보 · 일정 통합 검색",
      "home.brand_desc": "업무 인수인계 및 AI 협업 기록 시스템",

      // Settings Tabs & Sections
      "settings.title": "시스템 및 API 설정",
      "settings.desc": "AI 어시스턴트, 벡터 임베딩, 업무 카테고리, 외부 연동 및 워크스페이스 설정을 주제별로 관리합니다.",
      "settings.pill_ai": "AI 어시스턴트",
      "settings.pill_voyage": "임베딩 AI",
      "settings.pill_jira": "Jira API",
      "settings.pill_vectors": "색인 벡터",
      "settings.tab_integrations": "API 및 외부 연동",
      "settings.tab_categories": "부서 / 조직 관리",
      "settings.tab_template": "보고서 서식",
      "settings.tab_security": "보안 & DB 백업",
      "settings.tab_users": "사용자 & 권한 (RBAC)",
      "settings.btn_save": "설정 저장",
      "settings.btn_test": "연결 테스트",

      // Chat & BYOK Model Selector
      "chat.welcome": "무엇이든 물어보세요. 업무 카드 검색, 일정 확인, 업무 관리를 도와드립니다.",
      "chat.model_header": "모델",
      "chat.model_default": "기본",
      "chat.model_edit": "수정",
      "chat.model_add": "다른 모델 / 키 추가...",
      "chat.byok_title_add": "개인 AI 모델 / 키 추가",
      "chat.byok_title_edit": "개인 AI 모델 수정",
      "chat.byok_name_label": "표시 이름 (Display Name)",
      "chat.byok_name_ph": "예: Claude Sonnet 4.6 (Thinking)",
      "chat.byok_provider_label": "제공자",
      "chat.byok_model_label": "모델 ID",
      "chat.byok_key_label": "개인 API 키",
      "chat.byok_key_ph": "API 키를 여기에 붙여넣으세요...",
      "chat.byok_key_hint": "키는 브라우저 로컬에 안전하게 저장됩니다.",
      "chat.byok_base_url_label": "커스텀 Base URL",
      "chat.byok_base_url_opt": "(선택사항)",
      "chat.byok_base_url_ph": "예: http://localhost:11434/v1 또는 비워둠",
      "chat.byok_btn_delete": "모델 삭제",
      "chat.byok_btn_cancel": "취소",
      "chat.byok_btn_save": "저장",
      "chat.byok_confirm_delete": "이 모델 설정을 삭제하시겠습니까?",
      "chat.byok_alert_required": "표시 이름과 모델 ID를 입력해주세요.",

      // Common actions
      "common.close": "닫기",
      "common.server_error": "서버에 연결할 수 없습니다.",

      // Empty states & Canvas
      "home.ask_empty": "질문 결과를 찾을 수 없습니다. 다른 검색어로 다시 시도해보세요.",
      "dash.empty_state": "조건에 맞는 기록이 없습니다.",
      "pim.web_empty": "검색 조건에 맞는 제품이 없습니다.",
      "pim.empty_state": "등록된 제품이 없습니다.",
      "canvas.conflict_title": "충돌 감지 (Optimistic Lock)",
      "canvas.conflict_desc": "이 카드가 방금 다른 사용자에 의해 업데이트되었습니다. 작업 내용을 덮어쓰지 않도록 최신 데이터를 다시 불러와주세요.",
      "canvas.btn_reload": "최신 데이터 불러오기",
      "canvas.due_date_invalid": "마감일은 시작일보다 빠를 수 없습니다."
    },

    en: {
      // General / Topbar
      "app.title": "ARGOS WORKS - Task Handover & AI Collaboration System",
      "nav.home": "Home",
      "nav.dash": "Dashboard",
      "nav.jira": "Register Task",
      "nav.schedule": "Schedule",
      "nav.pim": "Products",
      "nav.chat": "AI Assistant",
      "nav.history": "Audit Log",
      "nav.settings": "Settings",
      "nav.main_section": "Main Workspace",
      "nav.admin_section": "Admin Area",
      "nav.toggle_menu": "Toggle sidebar menu",
      "nav.theme_toggle": "Toggle light / dark mode",
      "nav.lang_toggle": "Change language (KO / EN)",
      "nav.theme": "Theme",
      "nav.theme_dark": "Dark Mode",
      "nav.theme_light": "Light Mode",
      "nav.lang": "Language",
      "nav.notifications": "Notifications",
      "auth.account_menu": "Account & Settings",
      "auth.guest_title": "Sign in required",
      "auth.guest_desc": "Sign in to access your ArgosWorks workspace",
      "auth.login_start": "Sign In / Start",
      "auth.logout": "Sign Out",

      // Topbar Page Titles
      "title.home": "Home",
      "title.dash": "Dashboard",
      "title.form": "Register Task",
      "title.schedule": "Calendar & Schedule",
      "title.pim": "Product Info (PIM)",
      "title.chat": "AI Assistant",
      "title.history": "Audit Activity Log",
      "title.settings": "System Settings",

      // Submit Form Guest Notice
      "form.guest_title": "Authentication Required",
      "form.guest_desc": "Registering new tasks and creating cards is only available for authenticated team members.<br>Please log in with your company account to proceed.",
      "form.guest_login_btn": "Log In",
      "form.guest_home_btn": "Go to Home",

      // Dashboard Categories & Filter Toolbar
      "dept.all": "All",
      "dept.waiting_count": "{count} pending",
      "dept.no_waiting": "None pending",
      "dept.add_btn": "+ Add Department",
      "dept.add_title": "Add New Department",
      "dept.edit_title": "Edit Department",
      "dept.manage_btn": "⚙ Manage Departments",
      "dept.manage_done": "✓ Done Managing",
      "dept.edit_btn": "Edit",
      "dept.del_btn": "Delete",
      "dept.name_label": "Department Name",
      "dept.name_ph": "e.g. R&D Team, Sales Team, HR Team",
      "dept.name_hint": "Display name shown on cards and filter menus.",
      "dept.local_label": "Local Card Code (Prefix)",
      "dept.local_ph": "e.g. DEV (Cards: DEV-1, DEV-2...)",
      "dept.local_hint": "Prefix used for generating sequential local card codes.",
      "dept.jira_label": "Jira Project Key",
      "dept.jira_ph": "e.g. ARGOS (Jira Project Key)",
      "dept.jira_hint": "Jira project key for automated synchronization.",
      "dept.modal_cancel": "Cancel",
      "dept.modal_submit": "Add",
      "dept.modal_update": "Save",
      "dept.toast_added": 'Department "{name}" added successfully.',
      "dept.toast_updated": 'Department "{name}" updated successfully.',
      "dept.toast_exists": "Department name already exists.",
      "dept.toast_failed": "Failed to save department.",
      "dept.toast_deleted": 'Department "{name}" deleted.',
      "dept.toast_del_confirm": 'Are you sure you want to delete department "{name}"?',
      "dept.custom_types_label": "Custom Work Types (Optional, comma-separated)",
      "dept.custom_types_ph": "e.g. Meeting, Handover, Review, Daily Report",
      "dept.custom_types_hint": "Register custom work types separated by comma. (Optional)",

      // Toolbar filters
      "filter.all_assignees": "All Assignees",
      "filter.all_categories": "All Categories",
      "filter.view_tree": "Tree View",
      "filter.view_assignee": "By Assignee",
      "filter.view_flat": "Flat View",
      "filter.status_all": "All Statuses",
      "filter.status_inprog": "In Progress",
      "filter.status_review": "In Review",
      "filter.status_todo": "To Do",
      "filter.status_done": "Done",
      "filter.status_delayed": "Delayed",
      "filter.search_ph": "🔍 Search work card, summary...",
      "filter.sync_jira": "⟳ Sync Jira",
      "filter.expand_all": "📂 Expand All",
      "filter.collapse_all": "📁 Collapse All",
      "filter.create_task": "➕ New Task",
      "filter.btn_excel": "Excel",
      "filter.export_excel": "Export current tasks to Excel (.xlsx)",
      "filter.assignee_panel_title": "Status by Assignee",
      "filter.view_table": "Detailed Table",
      "filter.col_assignee": "Assignee",
      "filter.col_dept": "Department",
      "filter.col_category": "Category",
      "filter.col_progress": "Progress",
      "filter.col_total_assigned": "Assigned Tasks",
      "filter.col_total_assigned_title": "All assigned tasks (including completed)",
      "filter.table_collapse": "Collapse Table",
      "filter.table_expand": "View Table",
      "filter.table_close": "Close Table",
      "filter.toggle_table_title": "Toggle detailed table",
      "filter.assignee_empty": "No assignee status data for the selected department.",
      "filter.assigned_count": "{count} assigned",
      "filter.weighted_progress": "Weighted Progress",
      "filter.status_label": "Status",

      // Dashboard View Modes & Captions
      "filter.records_flat_title": "All Records (Flat View)",
      "filter.records_assignee_title": "Grouped by Assignee",
      "filter.records_tree_title": "All Records (Tree View)",
      "filter.showing_items_of": "Showing {rendered} of {total} records (scroll for more)",
      "filter.showing_groups_of": "Showing {rendered} groups · {total} records (scroll for more)",
      "filter.total_items": "Total {total} records",
      "filter.records_assignee_caption": "Total {members} Members · {total} records",
      "filter.tree_caption_summary": "Total {total} records ({groups} groups)",

      // Common counts & nouns
      "common.person_count": "{count} Members",
      "common.count_tasks": "{count} tasks",
      "common.zero_items": "0 tasks",
      "common.unassigned": "Unassigned",
      "common.select_placeholder": "Select an option",

      // Cards & Tree
      "card.subtask_title": "Expand/collapse {count} subtasks",
      "card.subtask_hint": "{count} subtasks (click to view in canvas)",
      "card.subtask_badge": "{count} Subtasks",
      "card.parent_prefix": "Parent:",
      "card.parent_ref": "Parent: {key}",
      "card.participants_title": "Participants: {list}",
      "card.click_to_open_canvas": "Click to open canvas",

      // Edit Profile Modal
      "profile.modal_title": "Edit Profile",
      "profile.avatar_title": "Profile Avatar",
      "profile.change_photo": "Change Photo",
      "profile.reset_photo": "Reset to Default",
      "profile.avatar_hint": "JPG, PNG, WebP (1:1 ratio recommended, max 5MB)",
      "profile.name_label": "Full Name",
      "profile.name_ph": "Enter your name",
      "profile.email_label": "Email",
      "profile.email_ph": "user@company.com",
      "profile.org_label": "Work Category / Department",
      "profile.current_password_label": "Current Password",
      "profile.current_password_ph": "Enter current password",
      "profile.optional_change_only": "(enter only to change)",
      "profile.password_label": "New Password",
      "profile.password_ph": "8+ chars (leave blank to keep current)",
      "profile.confirm_password_label": "Confirm New Password",
      "profile.confirm_password_ph": "Re-enter new password",
      "profile.err_current_required": "Please enter your current password.",
      "profile.err_new_required": "Please enter a new password.",
      "profile.err_confirm_required": "Please confirm the new password.",
      "profile.err_too_short": "For security, the password must be at least 8 characters.",
      "profile.err_mismatch": "The new passwords do not match. Please check again.",
      "admin_user.id_label": "User ID",
      "admin_user.new_password_label": "New Password (only to reset)",
      "admin_user.new_password_ph": "Leave blank to keep current (min 8 chars)",
      "admin_user.new_password_confirm_label": "Confirm New Password",
      "admin_user.new_password_confirm_ph": "Re-enter new password",
      "admin_user.err_new_required": "Please enter a new password.",
      "admin_user.err_confirm_required": "Please confirm the new password.",
      "admin_user.err_too_short": "The password must be at least 8 characters.",
      "admin_user.err_mismatch": "The new passwords do not match. Please check again.",
      "profile.btn_cancel": "Cancel",
      "profile.btn_submit": "Save",

      // Record Edit Modal
      "record_edit.modal_title": "Edit Task Details",
      "record_edit.title_label": "Title",
      "record_edit.title_ph": "Enter task title",
      "record_edit.assignee_label": "Assignee",
      "record_edit.participants_label": "Participants",
      "record_edit.participants_ph": "e.g. John Doe, Alice (comma separated)",
      "record_edit.parent_label": "Parent Task",
      "record_edit.parent_optional": "(Optional)",
      "record_edit.parent_none": "(No Parent / Set as Root Task)",
      "record_edit.parent_ph": "Search parent task (code or title)...",
      "record_edit.start_date_label": "Start Date",
      "record_edit.due_date_label": "Due Date",
      "record_edit.memo_label": "Details / Notes",
      "record_edit.memo_ph": "Task details or progress notes",
      "record_edit.btn_cancel": "Cancel",
      "record_edit.btn_submit": "Save Changes",

      // Product Category Modal
      "prod_cat.modal_title": "Product Category & Spec Settings",
      "prod_cat.name_label": "Product Category Name",
      "prod_cat.name_ph": "e.g. IP Camera, AI Server, IoT Sensor, Cloud SW",
      "prod_cat.spec_fields_label": "Custom Spec Fields",
      "prod_cat.btn_add_field": "+ Add Field",
      "prod_cat.spec_fields_hint": "Define specification fields (resolution, power, license, etc.) for this category.",
      "prod_cat.col_group": "Group",
      "prod_cat.col_label": "Label",
      "prod_cat.col_key": "Key",
      "prod_cat.col_delete": "Delete",
      "prod_cat.btn_cancel": "Cancel",
      "prod_cat.btn_submit": "Save",

      // Home View Search
      "home.search_ph": "Ask anything (e.g., PoE splitter KC cert, OTA firmware, assigned tasks...)",
      "home.search_btn": "Search",
      "home.sub": "Unified search for work logs, handovers, product info, and calendar",
      "home.brand_desc": "Work Handover & AI Collaboration System",

      // Settings Tabs & Sections
      "settings.title": "System & API Settings",
      "settings.desc": "Configure AI Assistant, Vector Embeddings, Work Categories, Integrations, and Workspace branding.",
      "settings.pill_ai": "AI Assistant",
      "settings.pill_voyage": "Embedding AI",
      "settings.pill_jira": "Jira API",
      "settings.pill_vectors": "Indexed Vectors",
      "settings.tab_integrations": "API & Integrations",
      "settings.tab_categories": "Departments & Organizations",
      "settings.tab_template": "Report Templates",
      "settings.tab_security": "Security & Backup",
      "settings.tab_users": "Users & Access (RBAC)",
      "settings.btn_save": "Save Settings",
      "settings.btn_test": "Test Connections",

      // Chat & BYOK Model Selector
      "chat.welcome": "Ask anything. I can help you search work cards, check schedules, and manage tasks.",
      "chat.model_header": "Model",
      "chat.model_default": "Default",
      "chat.model_edit": "Edit",
      "chat.model_add": "Add other Model / Key...",
      "chat.byok_title_add": "Add Personal AI Model / Key",
      "chat.byok_title_edit": "Edit Personal AI Model",
      "chat.byok_name_label": "Display Name",
      "chat.byok_name_ph": "e.g. Claude Sonnet 4.6 (Thinking)",
      "chat.byok_provider_label": "Provider",
      "chat.byok_model_label": "Model ID",
      "chat.byok_key_label": "Personal API Key",
      "chat.byok_key_ph": "Paste your API key here...",
      "chat.byok_key_hint": "Key is stored securely on your browser.",
      "chat.byok_base_url_label": "Custom Base URL",
      "chat.byok_base_url_opt": "(Optional)",
      "chat.byok_base_url_ph": "e.g. http://localhost:11434/v1 or leave blank",
      "chat.byok_btn_delete": "Delete Model",
      "chat.byok_btn_cancel": "Cancel",
      "chat.byok_btn_save": "Save",
      "chat.byok_confirm_delete": "Are you sure you want to delete this model configuration?",
      "chat.byok_alert_required": "Please enter Display Name and Model ID.",

      // Common actions
      "common.close": "Close",
      "common.server_error": "Cannot connect to server.",

      // Empty states & Canvas
      "home.ask_empty": "No results found. Please try another search term.",
      "dash.empty_state": "No matching records found.",
      "pim.web_empty": "No matching products found.",
      "pim.empty_state": "No products registered yet.",
      "canvas.conflict_title": "Conflict Detected (Optimistic Lock)",
      "canvas.conflict_desc": "This card was just updated by another user. To prevent accidental overwriting, please reload the latest data.",
      "canvas.btn_reload": "Reload Latest Data",
      "canvas.due_date_invalid": "Due date cannot be earlier than start date."
    }
  };

  var currentLang = localStorage.getItem("argos_lang") || localStorage.getItem("jarvisLang") || "ko";
  if (!TRANSLATIONS[currentLang]) {
    currentLang = "ko";
  }

  function t(key, params) {
    var dict = TRANSLATIONS[currentLang] || TRANSLATIONS.ko;
    var str = dict[key] || TRANSLATIONS.ko[key] || key;
    if (params && typeof params === "object") {
      Object.keys(params).forEach(function(k) {
        str = str.replace(new RegExp("\\{" + k + "\\}", "g"), params[k]);
      });
    }
    return str;
  }

  function getLang() {
    return currentLang;
  }

  function setLang(lang) {
    if (!TRANSLATIONS[lang]) {
      console.warn("Unsupported language:", lang);
      return;
    }
    currentLang = lang;
    try {
      localStorage.setItem("argos_lang", lang);
      localStorage.setItem("jarvisLang", lang);
    } catch(e){}
    applyI18n();
    window.dispatchEvent(new CustomEvent("langchange", { detail: { lang: lang } }));
  }

  function applyI18n() {
    document.documentElement.setAttribute("lang", currentLang);

    // Update all elements with data-i18n attribute
    document.querySelectorAll("[data-i18n]").forEach(function(el) {
      var key = el.getAttribute("data-i18n");
      var text = t(key);
      if (el.tagName === "INPUT" || el.tagName === "TEXTAREA") {
        el.value = text;
      } else if (text.indexOf("<br") !== -1 || el.hasAttribute("data-i18n-html")) {
        el.innerHTML = text;
      } else {
        el.textContent = text;
      }
    });

    // Update elements with data-i18n-ph (placeholder)
    document.querySelectorAll("[data-i18n-ph]").forEach(function(el) {
      var key = el.getAttribute("data-i18n-ph");
      el.placeholder = t(key);
    });

    // Update elements with data-i18n-title (tooltip / title)
    document.querySelectorAll("[data-i18n-title]").forEach(function(el) {
      var key = el.getAttribute("data-i18n-title");
      el.title = t(key);
      if (el.hasAttribute("aria-label")) {
        el.setAttribute("aria-label", t(key));
      }
    });
  }

  window.i18n = {
    t: t,
    getLang: getLang,
    setLang: setLang,
    apply: applyI18n,
    translations: TRANSLATIONS
  };

  // Run on DOM loaded
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", applyI18n);
  } else {
    applyI18n();
  }

})(window);
