// calendar.js
// ── Cross-Tab Realtime Synchronization Channel ──
var schedSyncChannel = null;
if (typeof BroadcastChannel !== "undefined") {
  try {
    schedSyncChannel = new BroadcastChannel("argos_schedule_sync");
    schedSyncChannel.onmessage = function(msg) {
      if (msg && msg.data && msg.data.type === "schedule_updated") {
        if (typeof loadSchedule === "function") {
          loadSchedule(true);
        }
      }
    };
  } catch(e) {}
}

function notifyScheduleChanged() {
  if (schedSyncChannel) {
    try {
      schedSyncChannel.postMessage({ type: "schedule_updated", timestamp: Date.now() });
    } catch(e) {}
  }
}

var SCHED_TYPE_COLORS = {
  "업무": "#2563eb", "연차": "#3e6fa5", "반차": "#2c8f8a", "병가": "#a6383a",
  "출장": "#6e5cb6", "재택": "#3e8e5a", "회의": "#9c7a22", "기타": "#71807c"
};
function schedTypeColor(t){ return SCHED_TYPE_COLORS[t] || SCHED_TYPE_COLORS["기타"]; }
function pad2(n){ return (n < 10 ? "0" : "") + n; }
function todayStr(){
  var d = new Date();
  return d.getFullYear() + "-" + pad2(d.getMonth() + 1) + "-" + pad2(d.getDate());
}

function isValidDateStr(val){
  if(!val) return false;
  var s = String(val).trim().toLowerCase();
  return s !== "" && s !== "null" && s !== "undefined" && s !== "none" && s !== "-";
}

var MEMBER_COLORS = ["#2c6e63", "#c24a2c", "#6e5cb6", "#9c7a22", "#3e6fa5", "#8a4a73", "#2c8f8a", "#4c6b85"];
function memberColor(key){
  var str = key || "";
  var hash = 0;
  for(var i = 0; i < str.length; i++) hash = (hash * 31 + str.charCodeAt(i)) & 0xffffff;
  return MEMBER_COLORS[Math.abs(hash) % MEMBER_COLORS.length];
}

function getTaskThemeIndex(key){
  var hash = 0;
  var str = String(key || "");
  for(var i = 0; i < str.length; i++){
    hash = (hash * 37 + str.charCodeAt(i)) & 0x7fffffff;
  }
  return hash % 12;
}

// ── DOM References ──
var schedGrid = document.getElementById("schedGrid");
var schedWeekdays = document.getElementById("schedWeekdays");
var schedMonthLabel = document.getElementById("schedMonthLabel");
var schedLegend = document.getElementById("schedLegend");
var schedPrevBtn = document.getElementById("schedPrevBtn");
var schedNextBtn = document.getElementById("schedNextBtn");
var schedTodayBtn = document.getElementById("schedTodayBtn");
var schedShowWeekend = document.getElementById("schedShowWeekend");

// Modern Toolbar & View switcher
var schedViewMonthBtn = document.getElementById("schedViewMonthBtn");
var schedViewWeekBtn = document.getElementById("schedViewWeekBtn");
var schedViewAgendaBtn = document.getElementById("schedViewAgendaBtn");
var schedMonthPane = document.getElementById("schedMonthPane");
var schedWeekPane = document.getElementById("schedWeekPane");
var schedAgendaPane = document.getElementById("schedAgendaPane");
var schedWeekGrid = document.getElementById("schedWeekGrid");
var schedWeekHeaderRow = document.getElementById("schedWeekHeaderRow");
var schedAgendaList = document.getElementById("schedAgendaList");
var btnSchedOpenCreateModal = document.getElementById("btnSchedOpenCreateModal");
var btnSchedOpenCreateModalSide = document.getElementById("btnSchedOpenCreateModalSide");
var btnToggleMembersSidebar = document.getElementById("btnToggleMembersSidebar");
var schedMembersSidebar = document.getElementById("schedMembersSidebar");
var btnToggleOngoingJira = document.getElementById("btnToggleOngoingJira");
var schedOngoingCount = document.getElementById("schedOngoingCount");

// Draggable Task Panel (Right Sidebar for Local Task Cards)
var schedTaskDrawer = document.getElementById("schedTaskDrawer");
var btnToggleTaskDrawer = document.getElementById("btnToggleTaskDrawer");
var btnSchedTaskClose = document.getElementById("btnSchedTaskClose");
var schedTaskSearch = document.getElementById("schedTaskSearch");
var schedTaskCount = document.getElementById("schedTaskCount");
var schedTaskBadgeCount = document.getElementById("schedTaskBadgeCount");
var schedTaskCardsList = document.getElementById("schedTaskCardsList");
var schedCardSelectWrap = document.getElementById("schedCardSelectWrap");
var schedCardSelect = document.getElementById("schedCardSelect");
var schedLocalTasks = [];
var schedTaskFilterMode = "all";
var draggedItemData = null;

// Modal Elements
var schedEventModalBackdrop = document.getElementById("schedEventModalBackdrop");
var schedEventModalCard = document.getElementById("schedEventModalCard");
var schedModalTitle = document.getElementById("schedModalTitle");
var schedModalCloseBtn = document.getElementById("schedModalCloseBtn");

// Left Sidebar (DaouOffice-style Hierarchical Calendar Filters)
var schedMembersSide = document.querySelector(".schedule-members-side");
var schedMembersList = document.getElementById("schedMembersList");
var schedMembersSearch = document.getElementById("schedMembersSearch");
var schedMembersToggleAll = document.getElementById("schedMembersToggleAll");

// Filter Groups & Controls
var schedCompanyMasterCb = document.getElementById("schedCompanyMasterCb");
var schedCompanyTypeList = document.getElementById("schedCompanyTypeList");
var schedCompanyCount = document.getElementById("schedCompanyCount");

var schedTasksMasterCb = document.getElementById("schedTasksMasterCb");
var schedLocalCardsCb = document.getElementById("schedLocalCardsCb");
var schedJiraCardsCb = document.getElementById("schedJiraCardsCb");
var schedTasksCount = document.getElementById("schedTasksCount");
var schedLocalCardsCount = document.getElementById("schedLocalCardsCount");
var schedJiraCardsCount = document.getElementById("schedJiraCardsCount");
var schedJiraItemWrap = document.getElementById("schedJiraItemWrap");

var schedQuickOnlyMe = document.getElementById("schedQuickOnlyMe");
var schedQuickAll = document.getElementById("schedQuickAll");

var SCHED_COMPANY_TYPES = {
  "연차": { name: "연차", color: "#3e6fa5", label: "연차 휴가", i18nKey: "sched.type_annual" },
  "반차": { name: "반차", color: "#2c8f8a", label: "반차 (오전/오후)", i18nKey: "sched.type_half" },
  "병가": { name: "병가", color: "#a6383a", label: "병가", i18nKey: "sched.type_sick" },
  "출장": { name: "출장", color: "#6e5cb6", label: "출장", i18nKey: "sched.type_trip" },
  "재택": { name: "재택", color: "#3e8e5a", label: "재택근무", i18nKey: "sched.type_remote" },
  "회의": { name: "회의", color: "#9c7a22", label: "회의", i18nKey: "sched.type_meeting" },
  "기타": { name: "기타", color: "#71807c", label: "기타/행사", i18nKey: "sched.type_other" }
};

var EN_MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
var EN_MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function isCurrentLangEn(){
  return (window.i18n && window.i18n.getLang && window.i18n.getLang() === "en");
}

function normalizeCompanyType(rawType){
  var t = (rawType || "").trim();
  if(!t) return "기타";
  if(t.indexOf("연차") !== -1 || t.indexOf("휴가") !== -1 || t.indexOf("경조사") !== -1) return "연차";
  if(t.indexOf("반차") !== -1) return "반차";
  if(t.indexOf("병가") !== -1) return "병가";
  if(t.indexOf("출장") !== -1) return "출장";
  if(t.indexOf("재택") !== -1) return "재택";
  if(t.indexOf("회의") !== -1) return "회의";
  if(t.indexOf("업무") !== -1) return "업무";
  return SCHED_COMPANY_TYPES[t] ? t : "기타";
}

function getCompanyTypeName(t){
  var norm = normalizeCompanyType(t);
  var meta = SCHED_COMPANY_TYPES[norm] || SCHED_COMPANY_TYPES[t];
  if(!meta) return t;
  if(meta.i18nKey && window.i18n && window.i18n.t){
    return window.i18n.t(meta.i18nKey);
  }
  return meta.name;
}

var isCompanyGroupEnabled = localStorage.getItem("jarvis_cal_company_enabled") !== "false";
var savedCompanyTypes = null;
try { savedCompanyTypes = JSON.parse(localStorage.getItem("jarvis_cal_company_types")); } catch(e){}
var selectedCompanyTypes = new Set(
  Array.isArray(savedCompanyTypes) && savedCompanyTypes.length > 0
    ? savedCompanyTypes
    : Object.keys(SCHED_COMPANY_TYPES)
);

var isTasksGroupEnabled = localStorage.getItem("jarvis_cal_tasks_enabled") !== "false";
var isLocalCardsEnabled = localStorage.getItem("jarvis_cal_local_cards_enabled") !== "false";
var isJiraCardsEnabled = localStorage.getItem("jarvis_cal_jira_cards_enabled") !== "false";

var soloMemberKey = null;
var prevSelectedMemberKeys = null;

// Side / Modal form elements
var schedForm = document.getElementById("schedForm");
var schedEventIdInput = document.getElementById("schedEventId");
var schedDateStart = document.getElementById("schedDateStart");
var schedDateEnd = document.getElementById("schedDateEnd");
var schedType = document.getElementById("schedType");
var schedTitle = document.getElementById("schedTitle");
var schedMemo = document.getElementById("schedMemo");
var schedFormError = document.getElementById("schedFormError");
var schedSaveBtn = document.getElementById("schedSaveBtn");
var schedDeleteBtn = document.getElementById("schedDeleteBtn");
var schedCancelEditBtn = document.getElementById("schedCancelEditBtn");
var schedDayList = document.getElementById("schedDayList");
var schedLoginNotice = document.getElementById("schedLoginNotice");
var schedJiraOngoing = document.getElementById("schedJiraOngoing");
var schedJiraOngoingList = document.getElementById("schedJiraOngoingList");

// Participants Form Elements
var btnToggleAddParticipant = document.getElementById("btnToggleAddParticipant");
var schedSelectedParticipants = document.getElementById("schedSelectedParticipants");
var schedParticipantPicker = document.getElementById("schedParticipantPicker");
var schedParticipantSearch = document.getElementById("schedParticipantSearch");
var schedParticipantOptions = document.getElementById("schedParticipantOptions");
var currentFormParticipants = []; // array of { name, org, email, key, isOwner }

// ── Member Selection State ──
var allSchedMembers = [];
var selectedMemberKeys = new Set();
var myUserKey = "";

// ── View Mode: 'month' | 'week' | 'agenda' ──
var currentViewMode = localStorage.getItem("jarvis_cal_view_mode") || "month";

// ── Weekend Display Preference (DaouOffice-style: Default visible 7 days, toggleable) ──
var isWeekendVisible = localStorage.getItem("jarvis_cal_show_weekend_v2") !== "false";
if(schedShowWeekend){
  schedShowWeekend.checked = isWeekendVisible;
  schedShowWeekend.addEventListener("change", function(e){
    isWeekendVisible = e.target.checked;
    localStorage.setItem("jarvis_cal_show_weekend_v2", isWeekendVisible ? "true" : "false");
    refreshCurrentView();
  });
}

function isCalendarJiraActive(){
  return window.__JIRA_STATUS__ ? Boolean(window.__JIRA_STATUS__.enabled) : false;
}

// ── Jira Schedule Display Preference (Toggle on/off Jira issues on calendar) ──
var schedShowJira = document.getElementById("schedShowJira");
var isJiraVisible = localStorage.getItem("jarvis_cal_show_jira") !== "false";
if(schedShowJira){
  schedShowJira.checked = isJiraVisible;
  schedShowJira.addEventListener("change", function(e){
    isJiraVisible = e.target.checked;
    localStorage.setItem("jarvis_cal_show_jira", isJiraVisible ? "true" : "false");
    refreshCurrentView();
    renderMembersList();
  });
}

// ── Sidebar Collapsed Preference (Left Member Sidebar) & LNB Menu Coordination ──
function syncScheduleSidebarWithMainMenu(isSchedSidebarOpen){
  var viewSched = document.getElementById("viewSchedule");
  if(viewSched && viewSched.hidden) return; // Only apply when Schedule view is visible

  if(isSchedSidebarOpen){
    // When Schedule filter card is open, collapse main LNB to 56px icon rail to widen workspace
    if(!document.body.classList.contains("sidebar-collapsed")){
      document.body.setAttribute("data-auto-collapsed-sched", "1");
      document.body.classList.add("sidebar-collapsed");
    }
  } else {
    // When Schedule filter card is closed, restore main LNB if it was auto-collapsed
    if(document.body.getAttribute("data-auto-collapsed-sched") === "1"){
      document.body.removeAttribute("data-auto-collapsed-sched");
      document.body.classList.remove("sidebar-collapsed");
    }
  }
}
window.syncScheduleSidebarWithMainMenu = syncScheduleSidebarWithMainMenu;

var isSidebarCollapsed = localStorage.getItem("jarvis_cal_sidebar_collapsed") === "true";
if(schedMembersSidebar && isSidebarCollapsed){
  schedMembersSidebar.classList.add("is-collapsed");
}
if(btnToggleMembersSidebar){
  btnToggleMembersSidebar.addEventListener("click", function(){
    if(!schedMembersSidebar) return;
    var collapsed = schedMembersSidebar.classList.toggle("is-collapsed");
    localStorage.setItem("jarvis_cal_sidebar_collapsed", collapsed ? "true" : "false");
    // Action of opening -> collapse main menu; action of closing -> restore main menu
    syncScheduleSidebarWithMainMenu(!collapsed);
  });
}
var schedMembersCloseBtn = document.getElementById("schedMembersCloseBtn");
if(schedMembersCloseBtn){
  schedMembersCloseBtn.addEventListener("click", function(){
    if(!schedMembersSidebar) return;
    schedMembersSidebar.classList.add("is-collapsed");
    localStorage.setItem("jarvis_cal_sidebar_collapsed", "true");
    syncScheduleSidebarWithMainMenu(false);
  });
}
document.addEventListener("click", function(e){
  if(window.innerWidth <= 992 && schedMembersSidebar && !schedMembersSidebar.classList.contains("is-collapsed")){
    if(!schedMembersSidebar.contains(e.target) && (!btnToggleMembersSidebar || !btnToggleMembersSidebar.contains(e.target))){
      schedMembersSidebar.classList.add("is-collapsed");
      syncScheduleSidebarWithMainMenu(false);
    }
  }
});

// ── Right Task Panel Preference & Event Handlers ──
var isTaskPanelCollapsed = localStorage.getItem("jarvis_cal_tasks_collapsed_v2") !== "false";
if(schedTaskDrawer){
  if(isTaskPanelCollapsed){
    schedTaskDrawer.classList.add("is-collapsed");
    if(btnToggleTaskDrawer) btnToggleTaskDrawer.classList.remove("active");
  } else {
    schedTaskDrawer.classList.remove("is-collapsed");
    if(btnToggleTaskDrawer) btnToggleTaskDrawer.classList.add("active");
  }
}
if(btnToggleTaskDrawer){
  btnToggleTaskDrawer.addEventListener("click", function(){
    if(!schedTaskDrawer) return;
    var collapsed = schedTaskDrawer.classList.toggle("is-collapsed");
    btnToggleTaskDrawer.classList.toggle("active", !collapsed);
    localStorage.setItem("jarvis_cal_tasks_collapsed_v2", collapsed ? "true" : "false");
  });
}
if(btnSchedTaskClose){
  btnSchedTaskClose.addEventListener("click", function(){
    if(!schedTaskDrawer) return;
    schedTaskDrawer.classList.add("is-collapsed");
    if(btnToggleTaskDrawer) btnToggleTaskDrawer.classList.remove("active");
    localStorage.setItem("jarvis_cal_tasks_collapsed_v2", "true");
  });
}
document.addEventListener("click", function(e){
  if(window.innerWidth <= 992 && schedTaskDrawer && !schedTaskDrawer.classList.contains("is-collapsed")){
    if(!schedTaskDrawer.contains(e.target) && (!btnToggleTaskDrawer || !btnToggleTaskDrawer.contains(e.target))){
      schedTaskDrawer.classList.add("is-collapsed");
      if(btnToggleTaskDrawer) btnToggleTaskDrawer.classList.remove("active");
    }
  }
});

// ── Calendar Global State Variables ──
var schedViewYear = new Date().getFullYear();
var schedViewMonth = new Date().getMonth() + 1;
var schedSelectedDate = todayStr();
var schedEvents = [];
var schedJiraOngoingItems = [];
var schedEditingId = null;

(function initScheduleView(){
  var now = new Date();
  schedViewYear = now.getFullYear();
  schedViewMonth = now.getMonth() + 1;
  schedSelectedDate = todayStr();
})();

function authHeaders(){
  return (loggedInUser && loggedInUser.token) ? { "Authorization": "Bearer " + loggedInUser.token } : {};
}
function apiScheduleGet(){
  return fetch("/api/schedule", { headers: authHeaders(), cache: "no-store" }).then(function(r){
    if(r.status === 401){ handleAuthExpired(); return { ok: false, events: [], members: [] }; }
    return r.json();
  });
}
function apiSchedulePost(path, body){
  if (typeof apiPostJson === "function") {
    return apiPostJson(path, body).then(function(data){
      return { status: (data && data.ok) ? 200 : (data && data.error ? 400 : 200), data: data };
    });
  }
  var csrfToken = sessionStorage.getItem("argosCsrfToken") || localStorage.getItem("argosCsrfToken") || "";
  var headers = Object.assign({ "Content-Type": "application/json" }, authHeaders());
  if (csrfToken) headers["X-CSRF-Token"] = csrfToken;
  return fetch(path, {
    method: "POST",
    credentials: "same-origin",
    headers: headers,
    body: JSON.stringify(body)
  }).then(function(r){
    return r.json().then(function(data){ return { status: r.status, data: data }; });
  });
}

function loadSchedule(silent){
  if(!loggedInUser){
    schedEvents = [];
    schedJiraOngoingItems = [];
    schedLocalTasks = [];
    allSchedMembers = [];
    refreshCurrentView();
    renderMembersList();
    renderLocalTaskDrawer();
    populateCardSelectOptions();
    return Promise.resolve();
  }
  return apiScheduleGet().then(function(res){
    schedEvents = (res.ok && res.events) ? res.events : [];
    schedJiraOngoingItems = (res.ok && res.jiraOngoing) ? res.jiraOngoing : [];
    schedLocalTasks = (res.ok && res.localTasks) ? res.localTasks : [];
    myUserKey = res.myKey || (loggedInUser.name + "|" + loggedInUser.org);

    if(res.members && res.members.length){
      allSchedMembers = res.members;

      // Initialize selectedMemberKeys: load from localStorage if exists, else select all
      // Khôi phục đồng bộ toàn bộ bộ lọc đã lưu (Company, Tasks, Members)
      var savedComp = localStorage.getItem("jarvis_cal_company_enabled");
      if(savedComp !== null) isCompanyGroupEnabled = (savedComp !== "false");
      var savedCompTypes = null;
      try { savedCompTypes = JSON.parse(localStorage.getItem("jarvis_cal_company_types")); } catch(e){}
      if(Array.isArray(savedCompTypes) && savedCompTypes.length > 0){
        selectedCompanyTypes = new Set(savedCompTypes);
      }
      var savedTasks = localStorage.getItem("jarvis_cal_tasks_enabled");
      if(savedTasks !== null) isTasksGroupEnabled = (savedTasks !== "false");
      var savedLoc = localStorage.getItem("jarvis_cal_local_cards_enabled");
      if(savedLoc !== null) isLocalCardsEnabled = (savedLoc !== "false");
      var savedJira = localStorage.getItem("jarvis_cal_jira_cards_enabled");
      if(savedJira !== null) isJiraCardsEnabled = (savedJira !== "false");

      var validMemberKeys = new Set(allSchedMembers.map(function(m){ return m.key; }));
      if(silent && selectedMemberKeys && selectedMemberKeys.size > 0){
        var retained = new Set();
        selectedMemberKeys.forEach(function(k){
          if(validMemberKeys.has(k)) retained.add(k);
        });
        if(retained.size > 0) selectedMemberKeys = retained;
      } else {
        var saved = null;
        try { saved = JSON.parse(localStorage.getItem("jarvis_cal_selected_members")); } catch(e){}
        var quickMode = localStorage.getItem("jarvis_cal_quick_mode") || "all";

        if(quickMode === "only_me" && myUserKey){
          selectedMemberKeys = new Set([myUserKey]);
        } else if(quickMode === "custom" && Array.isArray(saved) && saved.length > 0){
          var validSaved = saved.filter(function(k){ return validMemberKeys.has(k); });
          selectedMemberKeys = (validSaved.length > 0) ? new Set(validSaved) : new Set(allSchedMembers.map(function(m){ return m.key; }));
        } else {
          selectedMemberKeys = new Set(allSchedMembers.map(function(m){ return m.key; }));
        }
      }
    }

    var isViewer = (typeof isViewerUser === "function") ? isViewerUser() : (loggedInUser && loggedInUser.role === "viewer");
    if (btnSchedOpenCreateModal) {
      btnSchedOpenCreateModal.style.display = isViewer ? "none" : "";
    }
    if (btnSchedOpenCreateModalSide) {
      btnSchedOpenCreateModalSide.style.display = isViewer ? "none" : "";
    }
    updateAllCalendarFilters();
    refreshCurrentView();
    renderLocalTaskDrawer();
    populateCardSelectOptions();
  });
}

function renderLocalTaskDrawer(){
  var allTasks = schedLocalTasks || [];

  // Tập hợp các cardCode đã được lên lịch trên lịch để loại trừ triệt để
  var scheduledCardCodes = new Set();
  (schedEvents || []).forEach(function(ev){
    if(ev.cardCode){
      scheduledCardCodes.add(String(ev.cardCode).trim().toUpperCase());
    }
  });

  function isValidDateStr(val){
    if(!val) return false;
    var s = String(val).trim().toLowerCase();
    return s !== "" && s !== "null" && s !== "undefined" && s !== "none" && s !== "-";
  }

  // Chỉ lấy những việc CHƯA gắn lên lịch và chưa hoàn thành
  var unscheduled = allTasks.filter(function(t){
    if(t.status === "완료" || t.status === "DONE" || t.status === "Closed") return false;
    var code = String(t.cardCode || t.id || "").trim().toUpperCase();
    if(code && scheduledCardCodes.has(code)) return false;
    if(t.is_scheduled === false || t.is_scheduled === 0) return true;
    var hasDate = isValidDateStr(t.work_date) || isValidDateStr(t.startDate) || isValidDateStr(t.endDate) || isValidDateStr(t.date);
    return !hasDate;
  });

  var totalCount = unscheduled.length;
  if(schedTaskCount) schedTaskCount.textContent = totalCount;

  var isEn = isCurrentLangEn();
  if(!schedTaskCardsList) return;
  if(!loggedInUser){
    schedTaskCardsList.innerHTML = '<div class="empty-state" style="padding:16px 8px;font-size:12px;">' +
      (isEn ? 'Log in to view task cards.' : '로그인 후 업무 카드가 표시됩니다.') + '</div>';
    if(schedTaskBadgeCount) schedTaskBadgeCount.textContent = isEn ? "0 items" : "0건";
    return;
  }
  if(!totalCount){
    schedTaskCardsList.innerHTML = '<div class="empty-state" style="padding:28px 12px;font-size:12.5px;text-align:center;color:var(--ink-faint);line-height:1.6;">' +
      '<strong style="color:var(--ink);display:block;margin-bottom:2px;">' + (isEn ? 'No unassigned tasks.' : '미배정 업무가 없습니다.') + '</strong>' +
      '<span style="font-size:11.5px;">' + (isEn ? 'All task cards are scheduled on the calendar.' : '모든 업무 카드가 달력에 배정되었습니다.') + '</span>' +
    '</div>';
    if(schedTaskBadgeCount) schedTaskBadgeCount.textContent = isEn ? "0 items" : "0건";
    return;
  }

  var filterText = (schedTaskSearch ? schedTaskSearch.value : "").trim().toLowerCase();
  var filtered = unscheduled.filter(function(t){
    if(filterText){
      var c = (t.cardCode || "").toLowerCase();
      var title = (t.title || "").toLowerCase();
      var sub = (t.assignee || t.submitter || "").toLowerCase();
      if(c.indexOf(filterText) === -1 && title.indexOf(filterText) === -1 && sub.indexOf(filterText) === -1){
        return false;
      }
    }
    return true;
  });

  if(schedTaskBadgeCount) schedTaskBadgeCount.textContent = filtered.length + (isEn ? " items" : "건");

  if(!filtered.length){
    schedTaskCardsList.innerHTML = '<div class="empty-state" style="padding:16px 8px;font-size:12px;">' +
      (isEn ? 'No unassigned tasks match your search.' : '검색 조건에 맞는 미배정 업무가 없습니다.') + '</div>';
    return;
  }

  var html = filtered.map(function(t){
    var code = escapeHtml(t.cardCode || String(t.id));
    var title = escapeHtml(t.title || "(제목 없음)");
    var status = escapeHtml(t.status || "TODO");
    var submitter = escapeHtml(t.assignee || t.submitter || "");

    var planDateText = "";
    if(isValidDateStr(t.startDate) && isValidDateStr(t.endDate) && t.startDate !== t.endDate){
      planDateText = t.startDate + " ~ " + t.endDate;
    } else if(isValidDateStr(t.startDate)){
      planDateText = t.startDate;
    } else if(isValidDateStr(t.work_date)){
      planDateText = t.work_date;
    }

    return '<div class="sched-task-card" draggable="true" data-task-id="' + code + '" data-card-code="' + code + '" title="마우스로 끌어서 왼쪽 달력 날짜에 놓으세요. 클릭 시 캔버스 열기">' +
      '<div class="stc-header">' +
        '<span class="stc-code">' + code + '</span>' +
        '<span class="stc-badge stc-status-' + status + '">' + status + '</span>' +
      '</div>' +
      '<div class="stc-title">' + title + '</div>' +
      (planDateText ? (
        '<div style="margin:4px 0 3px 0; font-size:11px; color:var(--text-muted); display:inline-flex; align-items:center; gap:4px; background:rgba(14,165,233,0.08); padding:1px 6px; border-radius:4px; border:1px solid rgba(14,165,233,0.2);">' +
          '<span>' + escapeHtml(planDateText) + '</span>' +
        '</div>'
      ) : '') +
      '<div class="stc-footer">' +
        '<span class="stc-user">' + (submitter ? '👤 ' + submitter : '') + '</span>' +
        '<button type="button" class="stc-assign-btn" data-task-id="' + code + '" data-task-title="' + title + '" data-task-date="' + escapeHtml(planDateText) + '" title="' + (planDateText ? (isEn ? 'Place or edit with planned date' : '기존 계획일정으로 달력에 배치 또는 수정') : (isEn ? 'Assign date' : '날짜 직접 지정')) + '">' + (isEn ? 'Assign' : '배정') + '</button>' +
      '</div>' +
    '</div>';
  }).join("");

  schedTaskCardsList.innerHTML = html;
}

if(schedTaskSearch){
  schedTaskSearch.addEventListener("input", function(){
    renderLocalTaskDrawer();
  });
}

function populateCardSelectOptions(){
  if(!schedCardSelect) return;
  var currentVal = schedCardSelect.value;
  var html = '<option value="">-- 직접 입력 (일반 일정 / 휴가 / 출장 / 회의) --</option>';
  (schedLocalTasks || []).forEach(function(t){
    var code = t.cardCode || String(t.id);
    var label = "[" + code + "] " + (t.title || "") + (t.submitter ? " (" + t.submitter + ")" : "");
    html += '<option value="' + escapeHtml(code) + '" data-title="' + escapeHtml(t.title || "") + '" data-date="' + escapeHtml(t.work_date || "") + '">' + escapeHtml(label) + '</option>';
  });
  schedCardSelect.innerHTML = html;
  if(currentVal) schedCardSelect.value = currentVal;
}

if(schedCardSelect){
  schedCardSelect.addEventListener("change", function(){
    var selectedOpt = schedCardSelect.options[schedCardSelect.selectedIndex];
    if(!selectedOpt || !selectedOpt.value) return;
    var taskCode = selectedOpt.value;
    var titleText = selectedOpt.getAttribute("data-title") || "";
    var dateVal = selectedOpt.getAttribute("data-date") || "";

    if(schedTitle){
      schedTitle.value = "[" + taskCode + "] " + titleText;
    }
    if(schedType){
      schedType.value = "업무";
    }
    if(dateVal && schedDateStart && !schedDateStart.value){
      schedDateStart.value = dateVal;
    }
  });
}

if(schedTaskCardsList){
  schedTaskCardsList.addEventListener("click", function(e){
    var assignBtn = e.target.closest(".stc-assign-btn");
    if(assignBtn){
      e.stopPropagation();
      var taskId = assignBtn.getAttribute("data-task-id");
      var taskTitle = assignBtn.getAttribute("data-task-title");
      var taskDate = assignBtn.getAttribute("data-task-date");
      openTaskAssignModal(taskId, taskTitle, taskDate);
      return;
    }

    var card = e.target.closest(".sched-task-card");
    if(!card) return;
    var cardCode = card.getAttribute("data-card-code");
    if(cardCode && window.showIssueInCanvas && typeof window.showIssueInCanvas === "function"){
      window.showIssueInCanvas(cardCode);
      if(typeof showToast === "function") showToast("업무 카드 [" + cardCode + "] 캔버스를 엽니다.");
    }
  });
}

function openTaskAssignModal(taskId, taskTitle, currentDate){
  var backdrop = document.getElementById("schedTaskAssignModalBackdrop");
  var idInput = document.getElementById("schedTaskAssignId");
  var titleEl = document.getElementById("schedTaskAssignTitle");
  var startInput = document.getElementById("schedTaskAssignStartDate");
  var endInput = document.getElementById("schedTaskAssignEndDate");
  if(!backdrop || !idInput || !startInput || !endInput) return;

  idInput.value = taskId;
  if(titleEl) titleEl.textContent = "[" + taskId + "] " + (taskTitle || "");

  var sDate = "";
  var eDate = "";
  if(currentDate && currentDate.indexOf("~") !== -1){
    var parts = currentDate.split("~").map(function(p){ return p.trim(); });
    sDate = parts[0] || "";
    eDate = parts[1] || sDate;
  } else if(currentDate){
    sDate = currentDate.trim();
    eDate = sDate;
  } else {
    sDate = schedSelectedDate || todayStr();
    eDate = sDate;
  }

  startInput.value = sDate;
  endInput.value = eDate;

  backdrop.hidden = false;
  setTimeout(function(){ startInput.focus(); }, 60);
}

function closeTaskAssignModal(){
  var backdrop = document.getElementById("schedTaskAssignModalBackdrop");
  if(backdrop) backdrop.hidden = true;
}

function renderJiraOngoing(){
  var count = schedJiraOngoingItems ? schedJiraOngoingItems.length : 0;
  if(schedOngoingCount) schedOngoingCount.textContent = count;

  if(!loggedInUser || !isJiraVisible || !count || !isCalendarJiraActive()){
    if(schedJiraOngoing) schedJiraOngoing.hidden = true;
    return;
  }
  if(schedJiraOngoingList) schedJiraOngoingList.innerHTML = schedJiraOngoingItems.map(function(it){
    var jiraKey = (it.jira && it.jira.key) ? it.jira.key : (it.key || "");
    var title = escapeHtml(it.title || "(제목 없음)");
    var status = escapeHtml(it.statusName || it.category || "");
    var itemHtml = '<span class="sjo-item-clickable" data-jira-key="' + escapeHtml(jiraKey) + '" style="cursor:pointer;color:var(--tab-schedule);font-weight:600;" title="클릭 시 캔버스에서 확인">' +
      (jiraKey ? ('<span class="cal-chip-key" style="margin-right:4px;">' + escapeHtml(jiraKey) + '</span>') : '') +
      title + '</span>';
    return '<div class="sjo-item">' +
      '<span class="sjo-item-main">' + itemHtml + '</span>' +
      '<span class="sjo-item-status">' + status + '</span>' +
    '</div>';
  }).join("");
}

if(schedJiraOngoingList){
  schedJiraOngoingList.addEventListener("click", function(e){
    var clickable = e.target.closest(".sjo-item-clickable");
    if(clickable){
      var key = clickable.getAttribute("data-jira-key");
      if(key && window.showIssueInCanvas && typeof window.showIssueInCanvas === "function"){
        window.showIssueInCanvas(key);
        if(typeof showToast === "function") showToast("Jira 이슈 [" + key + "] 캔버스를 엽니다.");
      }
    }
  });
}

if(btnToggleOngoingJira){
  btnToggleOngoingJira.addEventListener("click", function(){
    if(!schedJiraOngoing) return;
    schedJiraOngoing.hidden = !schedJiraOngoing.hidden;
  });
}

// ── Event Classification & Visibility Logic (DaouOffice Grouping) ──
function isTaskCardEvent(ev){
  if(!ev) return false;
  if(ev.source === "local" || ev.source === "jira") return true;
  if(ev.cardCode || ev.recordId) return true;
  if(ev.type === "업무") return true;
  return false;
}

function isCompanyEvent(ev){
  if(!ev) return false;
  if(isTaskCardEvent(ev)) return false;
  return true;
}

function isEventVisible(ev){
  if(!ev) return false;

  // 1. Task Card Events (업무 카드 및 Jira)
  if(isTaskCardEvent(ev)){
    if(!isTasksGroupEnabled) return false;

    if(ev.source === "jira"){
      if(!isJiraCardsEnabled) return false;
    } else {
      if(!isLocalCardsEnabled) return false;
    }
  }

  // 2. Company & Attendance Events (연차, 반차, 병가, 출장, 재택, 회의, 기타)
  if(isCompanyEvent(ev)){
    if(!isCompanyGroupEnabled) return false;
    var rawT = ev.type || "기타";
    var t = normalizeCompanyType(rawT);
    if(!selectedCompanyTypes.has(t)) return false;
  }

  // 3. Rejected events: Chiển thị cho chính người tạo và Manager/Admin, ẩn với đồng nghiệp khác
  if(ev.approval_status === "rejected"){
    var isOwner = (myUserKey && ev.ownerKey === myUserKey) || (loggedInUser && ev.ownerName === loggedInUser.name);
    var isMgr = loggedInUser && (loggedInUser.isAdmin || loggedInUser.is_admin || loggedInUser.role === "admin" || loggedInUser.role === "manager");
    if(!isOwner && !isMgr) return false;
  }

  // 4. Member Filter (팀원 선택 필터)
  if(allSchedMembers.length > 0){
    // Thẻ 업무 카드 chưa phân công người (미지정/미배정) luôn hiển thị nếu nhóm 업무 카드 đang bật
    var isUnassignedTask = isTaskCardEvent(ev) && (!ev.ownerName || ev.ownerName === "미지정" || ev.ownerName === "미배정");
    if(isUnassignedTask){
      return isLocalCardsEnabled && isTasksGroupEnabled;
    }

    // Nếu người dùng chọn TẤT CẢ thành viên: hiển thị toàn bộ
    if(selectedMemberKeys.size >= allSchedMembers.length){
      return true;
    }

    // Nếu người dùng bỏ chọn tất cả thành viên: ẩn các lịch có người
    if(selectedMemberKeys.size === 0){
      return false;
    }

    var ownerKey = ev.ownerKey || (ev.ownerName ? (ev.ownerName + "|" + (ev.ownerOrg || "")) : "");
    var oName = (ev.ownerName || "").trim().toLowerCase();

    var isOwnerSelected = false;
    if(ownerKey && selectedMemberKeys.has(ownerKey)){
      isOwnerSelected = true;
    } else if(oName){
      isOwnerSelected = Array.from(selectedMemberKeys).some(function(k){
        var kName = k.split("|")[0].trim().toLowerCase();
        return kName === oName;
      });
    }

    var isParticipantSelected = false;
    if(Array.isArray(ev.participants) && ev.participants.length > 0){
      isParticipantSelected = ev.participants.some(function(p){
        if(p.key && selectedMemberKeys.has(p.key)) return true;
        if(p.name){
          var pName = p.name.trim().toLowerCase();
          return Array.from(selectedMemberKeys).some(function(k){
            var kName = k.split("|")[0].trim().toLowerCase();
            return kName === pName;
          });
        }
        return false;
      });
    }

    var hasPerson = !!(ownerKey || oName || (Array.isArray(ev.participants) && ev.participants.length > 0));
    if(hasPerson && !isOwnerSelected && !isParticipantSelected){
      return false;
    }
  }

  return true;
}

// ── Filter events on specific date ──
function eventsOnDate(dateStr){
  return schedEvents.filter(function(ev){
    if(!isEventVisible(ev)) return false;
    return ev.startDate <= dateStr && dateStr <= ev.endDate;
  });
}

// ── Render 1. Company & Attendance Filter Group ──
function renderCompanyTypeList(){
  var ymPrefix = schedViewYear + "-" + pad2(schedViewMonth);
  var monthStart = ymPrefix + "-01";
  var lastDayNum = new Date(schedViewYear, schedViewMonth, 0).getDate();
  var monthEnd = ymPrefix + "-" + pad2(lastDayNum);

  var totalCompanyCount = 0;
  schedEvents.forEach(function(ev){
    if(!isCompanyEvent(ev)) return;
    var s = ev.startDate || "";
    var e = ev.endDate || s;
    if(s && e && s <= monthEnd && e >= monthStart){
      totalCompanyCount++;
    }
  });

  if(schedCompanyCount) schedCompanyCount.textContent = totalCompanyCount;
  if(schedCompanyMasterCb){
    schedCompanyMasterCb.checked = isCompanyGroupEnabled;
    schedCompanyMasterCb.indeterminate = false;
  }
}

// ── Render 2. Task Cards & Jira Filter Group ──
function renderTaskFilterGroup(){
  var ymPrefix = schedViewYear + "-" + pad2(schedViewMonth);
  var monthStart = ymPrefix + "-01";
  var lastDayNum = new Date(schedViewYear, schedViewMonth, 0).getDate();
  var monthEnd = ymPrefix + "-" + pad2(lastDayNum);

  var totalTasks = 0;
  schedEvents.forEach(function(ev){
    if(!isTaskCardEvent(ev)) return;
    var s = ev.startDate || "";
    var e = ev.endDate || s;
    if(s && e && s <= monthEnd && e >= monthStart){
      totalTasks++;
    }
  });

  if(schedTasksCount) schedTasksCount.textContent = totalTasks;
  if(schedTasksMasterCb){
    schedTasksMasterCb.checked = isTasksGroupEnabled;
    schedTasksMasterCb.indeterminate = false;
  }
}

// ── Render 3. Team Members Sidebar List (좌측 팀원 목록) ──
function renderMembersList(){
  if(!schedMembersList) return;
  if(!loggedInUser || !allSchedMembers || !allSchedMembers.length){
    schedMembersList.innerHTML = '<div class="empty-state" style="padding:16px 4px;font-size:12px;">' +
      (window.i18n && window.i18n.t ? window.i18n.t("sched.login_required") : "로그인 후 팀원 목록이 표시됩니다.") +
      '</div>';
    return;
  }

  var filterText = (schedMembersSearch ? schedMembersSearch.value : "").trim().toLowerCase();

  // Calculate monthly event count for each member
  var ymPrefix = schedViewYear + "-" + pad2(schedViewMonth);
  var monthStart = ymPrefix + "-01";
  var lastDayNum = new Date(schedViewYear, schedViewMonth, 0).getDate();
  var monthEnd = ymPrefix + "-" + pad2(lastDayNum);

  var counts = {};
  (schedEvents || []).forEach(function(ev){
    if((!isCalendarJiraActive() || !isJiraVisible) && ev.source === "jira") return;
    var s = ev.startDate || "";
    var e = ev.endDate || s;
    if(s && e && s <= monthEnd && e >= monthStart){
      var keysToCredit = new Set();
      if(ev.ownerKey) keysToCredit.add(ev.ownerKey);
      if(ev.participants && Array.isArray(ev.participants)){
        ev.participants.forEach(function(p){
          if(p.key) keysToCredit.add(p.key);
        });
      }
      keysToCredit.forEach(function(k){
        counts[k] = (counts[k] || 0) + 1;
      });
    }
  });

  var html = "";
  var renderedCount = 0;

  allSchedMembers.forEach(function(m){
    var nameMatch = m.name.toLowerCase().indexOf(filterText) !== -1;
    var orgName = (typeof orgLabel === "function") ? orgLabel(m.org) : (m.org || "");
    var orgMatch = orgName.toLowerCase().indexOf(filterText) !== -1;
    if(filterText && !nameMatch && !orgMatch) return;

    renderedCount++;
    var isChecked = selectedMemberKeys.has(m.key);
    var isMe = m.key === myUserKey;
    var isSolo = soloMemberKey === m.key;
    var initial = m.name ? m.name.charAt(0) : "?";
    var color = memberColor(m.key);
    var count = counts[m.key] || 0;

    html += '<label class="sched-member-item' + (isMe ? ' is-me' : '') + (isSolo ? ' is-solo' : '') + '" data-key="' + escapeHtml(m.key) + '">';
    html += '<input type="checkbox" class="sched-member-cb" data-key="' + escapeHtml(m.key) + '" ' + (isChecked ? 'checked' : '') + '>';
    html += '<span class="sched-member-name">' + escapeHtml(m.name);
    if(isMe){
      html += ' <span style="font-size:11px;color:var(--accent-2, #0ea5e9);font-weight:700;">(나)</span>';
    }
    if(orgName){
      html += ' <span class="sched-member-org-badge">' + escapeHtml(orgName) + '</span>';
    }
    html += '</span>';
    html += '<button type="button" class="sched-member-solo-btn" data-key="' + escapeHtml(m.key) + '" title="이 팀원 일정만 보기">단독</button>';
    if(count > 0){
      html += '<span class="sched-member-count" title="이번 달 일정 ' + count + '건">' + count + '</span>';
    }
    html += '<span class="sched-color-dot" style="background:' + color + ';" title="' + escapeHtml(m.name) + '"></span>';
    html += '</label>';
  });

  if(!renderedCount){
    html = '<div class="empty-state" style="padding:14px 4px;font-size:12px;">' +
      (window.i18n && window.i18n.t ? window.i18n.t("sched.search_no_results") : "검색 결과가 없습니다.") +
      '</div>';
  }
  schedMembersList.innerHTML = html;

  if(schedMyCalDefaultCb && myUserKey){
    schedMyCalDefaultCb.checked = selectedMemberKeys.has(myUserKey);
  }

  // Update Toggle All Button text
  if(schedMembersToggleAll){
    var allSelected = allSchedMembers.length > 0 && selectedMemberKeys.size === allSchedMembers.length;
    var isEn = (typeof isCurrentLangEn === "function") ? isCurrentLangEn() : false;
    schedMembersToggleAll.textContent = allSelected ? (isEn ? "Deselect All" : "전체 해제") : (isEn ? "Select All" : "전체 선택");
  }
}

function updateQuickFilterUi(){
  var quickMode = localStorage.getItem("jarvis_cal_quick_mode") || "all";
  if(schedQuickOnlyMe){
    schedQuickOnlyMe.classList.toggle("active", quickMode === "only_me");
  }
  if(schedQuickAll){
    schedQuickAll.classList.toggle("active", quickMode === "all");
  }
}

function updateAllCalendarFilters(){
  renderCompanyTypeList();
  renderTaskFilterGroup();
  renderMembersList();
  updateQuickFilterUi();
}

// ── Solo Member View Handler ──
function toggleSoloMember(memberKey){
  if(soloMemberKey === memberKey){
    // Restore previous selection
    if(prevSelectedMemberKeys && prevSelectedMemberKeys.size > 0){
      selectedMemberKeys = new Set(prevSelectedMemberKeys);
    } else {
      selectedMemberKeys = new Set(allSchedMembers.map(function(m){ return m.key; }));
    }
    soloMemberKey = null;
    prevSelectedMemberKeys = null;
  } else {
    // Isolate this member
    prevSelectedMemberKeys = new Set(selectedMemberKeys);
    selectedMemberKeys = new Set([memberKey]);
    soloMemberKey = memberKey;
  }
  try{
    localStorage.setItem("jarvis_cal_selected_members", JSON.stringify(Array.from(selectedMemberKeys)));
  }catch(err){}
  updateAllCalendarFilters();
  refreshCurrentView();
}

// ── Event Handlers for Sidebar Filters ──
if(schedCompanyMasterCb){
  schedCompanyMasterCb.addEventListener("change", function(e){
    isCompanyGroupEnabled = e.target.checked;
    localStorage.setItem("jarvis_cal_company_enabled", isCompanyGroupEnabled ? "true" : "false");
    if(isCompanyGroupEnabled){
      selectedCompanyTypes = new Set(Object.keys(SCHED_COMPANY_TYPES));
    } else {
      selectedCompanyTypes.clear();
    }
    try{
      localStorage.setItem("jarvis_cal_company_types", JSON.stringify(Array.from(selectedCompanyTypes)));
    }catch(err){}
    renderCompanyTypeList();
    updateQuickFilterUi();
    refreshCurrentView();
  });
}

if(schedTasksMasterCb){
  schedTasksMasterCb.addEventListener("change", function(e){
    isTasksGroupEnabled = e.target.checked;
    localStorage.setItem("jarvis_cal_tasks_enabled", isTasksGroupEnabled ? "true" : "false");
    isLocalCardsEnabled = isTasksGroupEnabled;
    isJiraCardsEnabled = isTasksGroupEnabled;
    renderTaskFilterGroup();
    updateQuickFilterUi();
    refreshCurrentView();
  });
}

if(schedQuickOnlyMe){
  schedQuickOnlyMe.addEventListener("click", function(){
    if(!myUserKey) return;
    soloMemberKey = myUserKey;
    selectedMemberKeys = new Set([myUserKey]);
    localStorage.setItem("jarvis_cal_quick_mode", "only_me");
    try{
      localStorage.setItem("jarvis_cal_selected_members", JSON.stringify(Array.from(selectedMemberKeys)));
    }catch(err){}
    updateAllCalendarFilters();
    refreshCurrentView();
  });
}

if(schedQuickAll){
  schedQuickAll.addEventListener("click", function(){
    soloMemberKey = null;
    prevSelectedMemberKeys = null;
    selectedMemberKeys = new Set(allSchedMembers.map(function(m){ return m.key; }));
    isCompanyGroupEnabled = true;
    selectedCompanyTypes = new Set(Object.keys(SCHED_COMPANY_TYPES));
    isTasksGroupEnabled = true;
    isLocalCardsEnabled = true;
    isJiraCardsEnabled = true;
    localStorage.setItem("jarvis_cal_quick_mode", "all");
    localStorage.setItem("jarvis_cal_company_enabled", "true");
    localStorage.setItem("jarvis_cal_tasks_enabled", "true");
    localStorage.setItem("jarvis_cal_local_cards_enabled", "true");
    localStorage.setItem("jarvis_cal_jira_cards_enabled", "true");
    try{
      localStorage.setItem("jarvis_cal_company_types", JSON.stringify(Array.from(selectedCompanyTypes)));
      localStorage.setItem("jarvis_cal_selected_members", JSON.stringify(Array.from(selectedMemberKeys)));
    }catch(err){}
    updateAllCalendarFilters();
    refreshCurrentView();
  });
}

if(schedMembersList){
  schedMembersList.addEventListener("click", function(e){
    var soloBtn = e.target.closest(".sched-member-solo-btn");
    if(soloBtn){
      e.preventDefault();
      e.stopPropagation();
      var key = soloBtn.getAttribute("data-key");
      if(key) toggleSoloMember(key);
      return;
    }
  });

  schedMembersList.addEventListener("change", function(e){
    var cb = e.target.closest(".sched-member-cb");
    if(!cb) return;
    var key = cb.getAttribute("data-key");
    if(cb.checked){
      selectedMemberKeys.add(key);
    } else {
      selectedMemberKeys.delete(key);
    }
    soloMemberKey = null;
    if(allSchedMembers.length > 0){
      if(selectedMemberKeys.size === allSchedMembers.length){
        localStorage.setItem("jarvis_cal_quick_mode", "all");
      } else if(selectedMemberKeys.size === 1 && myUserKey && selectedMemberKeys.has(myUserKey)){
        localStorage.setItem("jarvis_cal_quick_mode", "only_me");
      } else {
        localStorage.setItem("jarvis_cal_quick_mode", "custom");
      }
    }
    try{
      localStorage.setItem("jarvis_cal_selected_members", JSON.stringify(Array.from(selectedMemberKeys)));
    } catch(err){}
    renderMembersList();
    updateQuickFilterUi();
    refreshCurrentView();
  });
}

if(schedMembersToggleAll){
  schedMembersToggleAll.addEventListener("click", function(){
    if(!allSchedMembers.length) return;
    var allSelected = selectedMemberKeys.size === allSchedMembers.length;
    if(allSelected){
      selectedMemberKeys.clear();
      if(myUserKey) selectedMemberKeys.add(myUserKey);
    } else {
      selectedMemberKeys = new Set(allSchedMembers.map(function(m){ return m.key; }));
    }
    soloMemberKey = null;
    if(allSchedMembers.length > 0){
      if(selectedMemberKeys.size === allSchedMembers.length){
        localStorage.setItem("jarvis_cal_quick_mode", "all");
      } else if(selectedMemberKeys.size === 1 && myUserKey && selectedMemberKeys.has(myUserKey)){
        localStorage.setItem("jarvis_cal_quick_mode", "only_me");
      } else {
        localStorage.setItem("jarvis_cal_quick_mode", "custom");
      }
    }
    try{
      localStorage.setItem("jarvis_cal_selected_members", JSON.stringify(Array.from(selectedMemberKeys)));
    } catch(err){}
    renderMembersList();
    updateQuickFilterUi();
    refreshCurrentView();
  });
}

if(schedMembersSearch){
  schedMembersSearch.addEventListener("input", function(){
    renderMembersList();
  });
}

// ── Group Fold/Unfold Click Handler ──
document.addEventListener("click", function(e){
  var btn = e.target.closest(".sched-group-fold-btn");
  if(!btn) return;
  var targetId = btn.getAttribute("data-target");
  var target = document.getElementById(targetId);
  if(!target) return;
  var isFolded = target.classList.toggle("is-folded");
  btn.textContent = isFolded ? "▸" : "▾";
  try{
    localStorage.setItem("jarvis_cal_fold_" + targetId, isFolded ? "true" : "false");
  }catch(err){}
});

// Restore folded states for groups on load
setTimeout(function(){
  ["schedCompanyTypeList", "schedTasksSubList", "schedMembersBodyWrap"].forEach(function(targetId){
    var el = document.getElementById(targetId);
    var btn = document.querySelector('.sched-group-fold-btn[data-target="' + targetId + '"]');
    if(!el || !btn) return;
    var isFolded = localStorage.getItem("jarvis_cal_fold_" + targetId) === "true";
    if(isFolded){
      el.classList.add("is-folded");
      btn.textContent = "▸";
    }
  });
}, 0);

function renderSelectedParticipantsForm(isReadOnly){
  if(!schedSelectedParticipants) return;
  if(!currentFormParticipants || !currentFormParticipants.length){
    schedSelectedParticipants.innerHTML = '<span style="font-size:12px;color:var(--ink-faint);padding:2px 0;">선택된 참석자가 없습니다.</span>';
    return;
  }
  var html = currentFormParticipants.map(function(p, idx){
    var isOwner = !!p.isOwner;
    var name = escapeHtml(p.name || "");
    var org = p.org ? escapeHtml(orgLabel(p.org)) : "";
    var roleLabel = isOwner ? ' <span style="font-size:10px;opacity:0.75;">(등록자)</span>' : '';
    var removeBtn = (!isOwner && !isReadOnly)
      ? '<button type="button" class="sched-participant-remove" data-idx="' + idx + '" title="삭제">✕</button>'
      : '';
    var firstChar = (p.name || "?").charAt(0).toUpperCase();
    var color = memberColor(p.key || p.name);

    return '<div class="sched-participant-chip' + (isOwner ? ' is-owner' : '') + '">' +
      '<span class="sched-participant-chip-avatar" style="background:' + color + ';">' + escapeHtml(firstChar) + '</span>' +
      '<span>' + name + (org ? ' <small style="font-size:10px;opacity:0.8;">(' + org + ')</small>' : '') + roleLabel + '</span>' +
      removeBtn +
    '</div>';
  }).join("");
  schedSelectedParticipants.innerHTML = html;
}

function renderParticipantPickerOptions(){
  if(!schedParticipantOptions) return;
  var filter = (schedParticipantSearch ? schedParticipantSearch.value : "").trim().toLowerCase();
  var selectedKeys = new Set(currentFormParticipants.map(function(p){ return p.key; }));

  var available = allSchedMembers.filter(function(m){
    var name = (m.name || "").toLowerCase();
    var org = orgLabel(m.org || "").toLowerCase();
    var matchesFilter = !filter || name.indexOf(filter) !== -1 || org.indexOf(filter) !== -1;
    return matchesFilter;
  });

  if(!available.length){
    schedParticipantOptions.innerHTML = '<div style="padding:10px;text-align:center;font-size:11.5px;color:var(--ink-faint);">검색 결과가 없습니다.</div>';
    return;
  }

  var html = available.map(function(m){
    var isAlreadySelected = selectedKeys.has(m.key);
    var firstChar = (m.name || "?").charAt(0).toUpperCase();
    var color = memberColor(m.key || m.name);
    var checkIcon = isAlreadySelected ? '✓' : '＋';

    return '<div class="picker-option-item' + (isAlreadySelected ? ' selected' : '') + '" data-key="' + escapeHtml(m.key) + '">' +
      '<div class="picker-option-left">' +
        '<span class="sched-participant-chip-avatar" style="width:20px;height:20px;font-size:10px;background:' + color + ';">' + escapeHtml(firstChar) + '</span>' +
        '<span>' + escapeHtml(m.name) + '</span>' +
        '<span class="picker-option-dept">' + escapeHtml(orgLabel(m.org)) + '</span>' +
      '</div>' +
      '<span style="font-size:12px;color:' + (isAlreadySelected ? 'var(--tab-schedule)' : 'var(--ink-faint)') + ';">' + checkIcon + '</span>' +
    '</div>';
  }).join("");

  schedParticipantOptions.innerHTML = html;
}

// Participant Chip Remove Click
if(schedSelectedParticipants){
  schedSelectedParticipants.addEventListener("click", function(e){
    var btn = e.target.closest(".sched-participant-remove");
    if(!btn) return;
    var idx = parseInt(btn.getAttribute("data-idx"), 10);
    if(!isNaN(idx) && currentFormParticipants[idx] && !currentFormParticipants[idx].isOwner){
      currentFormParticipants.splice(idx, 1);
      renderSelectedParticipantsForm(false);
      renderParticipantPickerOptions();
    }
  });
}

// Toggle Participant Picker
if(btnToggleAddParticipant){
  btnToggleAddParticipant.addEventListener("click", function(e){
    e.stopPropagation();
    if(!schedParticipantPicker) return;
    var isHidden = schedParticipantPicker.hidden;
    schedParticipantPicker.hidden = !isHidden;
    if(!schedParticipantPicker.hidden){
      if(schedParticipantSearch){
        schedParticipantSearch.value = "";
        schedParticipantSearch.focus();
      }
      renderParticipantPickerOptions();
    }
  });
}

// Search Filter in Picker
if(schedParticipantSearch){
  schedParticipantSearch.addEventListener("input", function(){
    renderParticipantPickerOptions();
  });
}

// Click on option in picker
if(schedParticipantOptions){
  schedParticipantOptions.addEventListener("click", function(e){
    var item = e.target.closest(".picker-option-item");
    if(!item) return;
    var key = item.getAttribute("data-key");
    var member = allSchedMembers.filter(function(m){ return m.key === key; })[0];
    if(!member) return;

    var existsIdx = -1;
    for(var i = 0; i < currentFormParticipants.length; i++){
      if(currentFormParticipants[i].key === key){
        existsIdx = i;
        break;
      }
    }

    if(existsIdx !== -1){
      // If already added and not owner, toggle off
      if(!currentFormParticipants[existsIdx].isOwner){
        currentFormParticipants.splice(existsIdx, 1);
      }
    } else {
      currentFormParticipants.push({
        name: member.name,
        org: member.org,
        email: member.email || "",
        key: member.key,
        isOwner: false
      });
    }

    renderSelectedParticipantsForm(false);
    renderParticipantPickerOptions();
  });
}

// Close picker when clicking outside
document.addEventListener("click", function(e){
  if(schedParticipantPicker && !schedParticipantPicker.hidden){
    if(!schedParticipantPicker.contains(e.target) && e.target !== btnToggleAddParticipant){
      schedParticipantPicker.hidden = true;
    }
  }
});

function setScheduleFormReadonly(readonly){
  if(schedType) schedType.disabled = readonly;
  if(schedTitle) schedTitle.disabled = readonly;
  if(schedDateStart) schedDateStart.disabled = readonly;
  if(schedDateEnd) schedDateEnd.disabled = readonly;
  if(schedMemo) schedMemo.disabled = readonly;
  if(schedSaveBtn) schedSaveBtn.hidden = readonly;
  if(btnToggleAddParticipant) btnToggleAddParticipant.hidden = readonly;
  if(schedParticipantPicker && readonly) schedParticipantPicker.hidden = true;
}

function adjustMemoHeight(){
  if(!schedMemo) return;
  schedMemo.style.height = "auto";
  var scrollH = schedMemo.scrollHeight;
  schedMemo.style.height = Math.max(105, Math.min(scrollH + 4, 340)) + "px";
}
if(schedMemo){
  schedMemo.addEventListener("input", adjustMemoHeight);
}

function startNewEventForm(dateStr){
  if(loggedInUser && loggedInUser.role === "viewer"){
    if(typeof showToast === "function") showToast("조회 전용(Viewer) 권한의 사용자는 일정을 추가할 수 없습니다.", 3000, true);
    return;
  }
  schedEditingId = null;
  if(schedEventIdInput) schedEventIdInput.value = "";
  if(schedDateStart) schedDateStart.value = dateStr;
  if(schedDateEnd) schedDateEnd.value = "";
  if(schedType) schedType.value = "연차";
  if(schedCardSelect) schedCardSelect.value = "";
  if(schedTitle) schedTitle.value = "";
  if(schedMemo) {
    schedMemo.value = "";
    adjustMemoHeight();
  }
  if(schedFormError) schedFormError.textContent = "";
  if(schedSaveBtn) schedSaveBtn.textContent = isCurrentLangEn() ? "Add" : "추가";
  setScheduleFormReadonly(false);
  if(schedDeleteBtn) schedDeleteBtn.hidden = true;
  if(schedCancelEditBtn) schedCancelEditBtn.hidden = true;
  if(schedParticipantPicker) schedParticipantPicker.hidden = true;
  var schedApprovalActions = document.getElementById("schedApprovalActions");
  if(schedApprovalActions) schedApprovalActions.style.display = "none";

  // Initialize participants with current logged in user as owner
  if(loggedInUser){
    var myKey = myUserKey || (loggedInUser.name + "|" + loggedInUser.org);
    currentFormParticipants = [{
      name: loggedInUser.name,
      org: loggedInUser.org,
      email: loggedInUser.email || "",
      key: myKey,
      isOwner: true
    }];
  } else {
    currentFormParticipants = [];
  }
  renderSelectedParticipantsForm(false);
}

function startEditEventForm(ev){
  schedEditingId = ev.id;
  if(schedEventIdInput) schedEventIdInput.value = ev.id;
  if(schedDateStart) schedDateStart.value = ev.startDate;
  if(schedDateEnd) schedDateEnd.value = ev.endDate !== ev.startDate ? ev.endDate : "";
  var hasType = Object.prototype.hasOwnProperty.call(SCHED_TYPE_COLORS, ev.type);
  if(schedType) schedType.value = hasType ? ev.type : "기타";
  if(schedCardSelect) {
    var code = ev.cardCode || (ev.source === "local" ? ev.id : "");
    schedCardSelect.value = code;
  }
  if(schedTitle) schedTitle.value = ev.title;
  if(schedMemo) {
    schedMemo.value = ev.memo || "";
    adjustMemoHeight();
  }
  if(schedParticipantPicker) schedParticipantPicker.hidden = true;
  var schedApprovalActions = document.getElementById("schedApprovalActions");
  if(schedApprovalActions) schedApprovalActions.style.display = "none";

  var isJira = ev.source === "jira";
  var isLocal = ev.source === "local" || !!ev.cardCode;
  var isAdmin = loggedInUser && (loggedInUser.isAdmin || loggedInUser.is_admin || loggedInUser.role === "admin");
  var isManager = loggedInUser && (loggedInUser.isManager || loggedInUser.role === "manager");
  var isSameDept = loggedInUser && ev.ownerOrg && (String(loggedInUser.org).toLowerCase() === String(ev.ownerOrg).toLowerCase());
  var isManagerInDept = isManager && isSameDept;
  var isOwner = !ev.ownerKey || ev.ownerKey === myUserKey || (loggedInUser && ev.ownerName === loggedInUser.name);
  var isViewer = loggedInUser && loggedInUser.role === "viewer";
  var canEditOrDelete = !isViewer && !isJira && (isOwner || isAdmin || isManagerInDept);
  var isReadOnly = !canEditOrDelete;
  var isOtherUser = !isOwner;

  // Set participants from event
  if(ev.participants && Array.isArray(ev.participants) && ev.participants.length > 0){
    currentFormParticipants = ev.participants.map(function(p){
      return {
        name: p.name,
        org: p.org || "",
        email: p.email || "",
        key: p.key || (p.name + "|" + (p.org || "")),
        isOwner: p.key === ev.ownerKey || !!p.isOwner
      };
    });
  } else if(ev.ownerName) {
    currentFormParticipants = [{
      name: ev.ownerName,
      org: ev.ownerOrg || "",
      email: ev.ownerEmail || "",
      key: ev.ownerKey || (ev.ownerName + "|" + (ev.ownerOrg || "")),
      isOwner: true
    }];
  } else {
    currentFormParticipants = [];
  }
  renderSelectedParticipantsForm(isReadOnly);

  setScheduleFormReadonly(isReadOnly);
  if(schedFormError){
    if(isJira){
      var link = (ev.jira && ev.jira.url)
        ? ' <a href="' + escapeHtml(ev.jira.url) + '" target="_blank" rel="noopener">' + escapeHtml(ev.jira.key || "") + ' 열기</a>'
        : "";
      schedFormError.innerHTML = "🔗 Jira에서 자동으로 연동된 일정입니다. 수정·삭제는 Jira에서 해주세요." + link;
    } else if(isLocal){
      var cardCode = ev.cardCode || ev.id;
      schedFormError.innerHTML = '💼 로컬 업무 카드 <span style="font-weight:700;color:var(--tab-schedule);cursor:pointer;" onclick="window.showIssueInCanvas && window.showIssueInCanvas(\'' + escapeHtml(cardCode) + '\')">[' + escapeHtml(cardCode) + ']</span>와 연결된 일정입니다.';
    } else if(isOtherUser){
      schedFormError.textContent = "👤 " + (ev.ownerName || "동료") + " 님의 일정입니다. 등록자만 수정·삭제할 수 있습니다.";
    } else {
      schedFormError.textContent = "";
    }
  }
  if(schedSaveBtn) schedSaveBtn.textContent = isCurrentLangEn() ? "Save" : "저장";
  if(schedDeleteBtn) schedDeleteBtn.hidden = isReadOnly;
  if(schedCancelEditBtn) schedCancelEditBtn.hidden = false;

  // Xử lý nút Duyệt / Từ chối (Dành cho Manager hoặc Admin)
  var schedApprovalActions = document.getElementById("schedApprovalActions");
  if(schedApprovalActions){
    var isManagerOrAdmin = loggedInUser && (loggedInUser.isAdmin || loggedInUser.is_admin || loggedInUser.role === "admin" || loggedInUser.role === "manager" || loggedInUser.isManager);
    var isPending = ev.approval_status === "pending";
    if(isManagerOrAdmin && isPending){
      schedApprovalActions.style.display = "flex";
      var btnApprove = document.getElementById("btnSchedApprove");
      var btnReject = document.getElementById("btnSchedReject");
      if(btnApprove){
        btnApprove.onclick = function(){
          if(!confirm("이 휴가/일정 신청을 승인하시겠습니까?")) return;
          ev.approval_status = "approved";
          refreshCurrentView();
          closeSchedEventModal();
          apiSchedulePost("/api/schedule/approve", { id: ev.id, action: "approve" }).then(function(res){
            if(res.data && res.data.ok){
              if(typeof showToast === "function") showToast("✓ 일정이 승인되었습니다.");
              notifyScheduleChanged();
              loadSchedule(true);
            } else {
              alert((res.data && res.data.error) || "승인 처리 중 오류 발생");
              loadSchedule(true);
            }
          }).catch(function(){
            loadSchedule(true);
          });
        };
      }
      if(btnReject){
        btnReject.onclick = function(){
          var reason = prompt("반려 사유를 입력해주세요 (선택):", "");
          if(reason === null) return;
          ev.approval_status = "rejected";
          ev.reject_reason = reason;
          refreshCurrentView();
          closeSchedEventModal();
          apiSchedulePost("/api/schedule/approve", { id: ev.id, action: "reject", reason: reason }).then(function(res){
            if(res.data && res.data.ok){
              if(typeof showToast === "function") showToast("✕ 일정이 반려되었습니다.");
              notifyScheduleChanged();
              loadSchedule(true);
            } else {
              alert((res.data && res.data.error) || "반려 처리 중 오류 발생");
              loadSchedule(true);
            }
          }).catch(function(){
            loadSchedule(true);
          });
        };
      }
    } else {
      schedApprovalActions.style.display = "none";
    }
  }
}

// ── Multi-day Event Slot Allocation (Choivis / DaouOffice Style) ──
function allocateWeekSlots(weekCells, maxVisibleSlots){
  if(!maxVisibleSlots) maxVisibleSlots = 4;
  var weekDates = weekCells.map(function(c){ return c.dateStr; });

  // Collect all unique events across this week's cells
  var eventMap = new Map();
  weekCells.forEach(function(c){
    c.events.forEach(function(ev){
      var id = String(ev.id);
      if(!eventMap.has(id)) eventMap.set(id, ev);
    });
  });

  var allWeekEvents = Array.from(eventMap.values());

  // Split into multi-day spanning events and single-day events
  var multiDayEvents = [];
  var singleDayEvents = [];

  allWeekEvents.forEach(function(ev){
    var isSpan = (ev.startDate !== ev.endDate);
    if(isSpan) multiDayEvents.push(ev);
    else singleDayEvents.push(ev);
  });

  // Sort multi-day events: longer span first, then earlier start, then ID
  multiDayEvents.sort(function(a, b){
    var aSpan = Math.abs(new Date(a.endDate) - new Date(a.startDate));
    var bSpan = Math.abs(new Date(b.endDate) - new Date(b.startDate));
    if(aSpan !== bSpan) return bSpan - aSpan;
    if(a.startDate !== b.startDate) return a.startDate < b.startDate ? -1 : 1;
    return String(a.id).localeCompare(String(b.id));
  });

  // Sort single-day events: earlier start, then ID
  singleDayEvents.sort(function(a, b){
    if(a.startDate !== b.startDate) return a.startDate < b.startDate ? -1 : 1;
    return String(a.id).localeCompare(String(b.id));
  });

  // Initialize slotItems map and overflowCount for each weekCell
  weekCells.forEach(function(c){
    c.slotItems = new Map();
    c.overflowCount = 0;
  });

  // 1. Allocate Multi-day events first (horizontal continuity across columns)
  multiDayEvents.forEach(function(ev){
    var firstCol = -1;
    var lastCol = -1;
    for(var i = 0; i < weekCells.length; i++){
      var dStr = weekCells[i].dateStr;
      if(ev.startDate <= dStr && dStr <= ev.endDate){
        if(firstCol === -1) firstCol = i;
        lastCol = i;
      }
    }
    if(firstCol === -1) return;

    var spanCols = lastCol - firstCol + 1;
    var continuesFromPrev = (ev.startDate < weekCells[firstCol].dateStr);
    var continuesToNext = (ev.endDate > weekCells[lastCol].dateStr);

    var spanType = 'range';
    if(continuesFromPrev && continuesToNext) spanType = 'through';
    else if(continuesFromPrev) spanType = 'from-prev';
    else if(continuesToNext) spanType = 'to-next';

    // Find lowest slot free in ALL columns [firstCol..lastCol]
    var slotIdx = 0;
    while(true){
      var free = true;
      for(var k = firstCol; k <= lastCol; k++){
        if(weekCells[k].slotItems.has(slotIdx)){
          free = false;
          break;
        }
      }
      if(free) break;
      slotIdx++;
    }

    if(slotIdx < maxVisibleSlots){
      // First column gets the continuous event bar
      weekCells[firstCol].slotItems.set(slotIdx, {
        type: 'event',
        event: ev,
        spanCols: spanCols,
        spanType: spanType
      });
      // Subsequent columns in this span get invisible placeholders at this slot
      for(var k = firstCol + 1; k <= lastCol; k++){
        weekCells[k].slotItems.set(slotIdx, {
          type: 'spacer',
          placeholder: true
        });
      }
    } else {
      // Overflows max visible slots
      for(var k = firstCol; k <= lastCol; k++){
        weekCells[k].overflowCount++;
      }
    }
  });

  // 2. Allocate Single-day events per day cell (fill lowest available slots)
  weekCells.forEach(function(c){
    var daySingles = singleDayEvents.filter(function(ev){
      return ev.startDate === c.dateStr;
    });

    daySingles.forEach(function(ev){
      var slotIdx = 0;
      while(c.slotItems.has(slotIdx)){
        slotIdx++;
      }
      if(slotIdx < maxVisibleSlots){
        c.slotItems.set(slotIdx, {
          type: 'event',
          event: ev,
          spanCols: 1,
          spanType: 'single'
        });
      } else {
        c.overflowCount++;
      }
    });
  });

  // 3. Guarantee: If a day cell has total events <= maxVisibleSlots, it MUST NOT show false overflow!
  weekCells.forEach(function(c){
    if(c.events.length <= maxVisibleSlots && c.overflowCount > 0){
      c.overflowCount = 0;
    }
  });

  // 4. Build sequential slots array (0..maxSlot) for each cell
  weekCells.forEach(function(c){
    var maxSlot = -1;
    c.slotItems.forEach(function(val, s){
      if(s > maxSlot) maxSlot = s;
    });

    var slotsToRender = [];
    if(maxSlot >= 0){
      for(var s = 0; s <= maxSlot; s++){
        if(c.slotItems.has(s)){
          slotsToRender.push(c.slotItems.get(s));
        } else {
          slotsToRender.push({ type: 'spacer' });
        }
      }
    }
    c.slots = slotsToRender;
  });
}

function renderCellHtml(c, showOwnerPrefix){
  var cellClass = "cal-day-cell schedule-day";
  if(c.outside) cellClass += " other-month outside";
  if(c.isToday) cellClass += " is-today today";
  if(c.isSelected) cellClass += " selected";
  if(c.isSun) cellClass += " sun";
  if(c.isSat) cellClass += " sat";

  var html = '<td class="' + cellClass + '" data-date="' + c.dateStr + '">';
  html += '<div class="cal-day-header">';
  html += '<span class="cal-date-num">' + c.dateNum + '</span>';
  var isEnCell = isCurrentLangEn();
  var addEventTitle = isEnCell ? ("Add event on " + c.dateStr) : (c.dateStr + "에 새 일정 추가");
  html += '<span class="cal-day-add-btn" data-date="' + escapeHtml(c.dateStr) + '" title="' + addEventTitle + '">＋</span>';
  if(c.events.length > 0){
    html += '<span class="cal-day-count" data-date="' + escapeHtml(c.dateStr) + '" title="총 ' + c.events.length + '건 (클릭하여 전체 일정 보기)" style="cursor:pointer;">' + c.events.length + '</span>';
  }
  html += '</div>';
  html += '<div class="cal-events-list schedule-day-events">';

  (c.slots || []).forEach(function(slot){
    if(slot.type === 'spacer'){
      html += '<div class="cal-chip-spacer"></div>';
      return;
    }
    var ev = slot.event;
    var isJira = ev.source === "jira";
    var jiraKey = (ev.jira && ev.jira.key) ? ev.jira.key : (isJira ? ev.title : "");
    var spanCols = slot.spanCols || 1;
    var spanType = slot.spanType || 'single';
    var isMultiParticipant = ev.participants && ev.participants.length > 1;
    var ownerPrefix = "";
    var multiTagsHtml = "";

    if(isMultiParticipant){
      // Sắp xếp danh sách người tham gia: đưa người tạo (owner) lên đầu
      var sortedParts = (ev.participants || []).slice();
      sortedParts.sort(function(a, b){
        if(a.key === ev.ownerKey || a.isOwner) return -1;
        if(b.key === ev.ownerKey || b.isOwner) return 1;
        return 0;
      });

      var titleLen = (ev.title || "").trim().length;

      // Tính toán số lượng người/họ có thể hiển thị vừa vặn:
      // - Nếu chỉ có 2 người (1 người cùng tham gia) và tiêu đề ngắn (< 10 ký tự):
      //   + Nếu spanCols >= 2 hoặc tiêu đề rất ngắn (<= 6 ký tự): hiện đủ tên 2 người! Ví dụ: [동진위, 최성우] test
      //   + Ngược lại hiện 2 họ: [동..] [최..] test (không cần +1명 vì đã hiện đủ cả 2 người)
      // - Nếu có >= 3 người:
      //   + Tùy độ rộng: hiển thị 2 hoặc 3 họ kèm +X명 còn lại nếu thiếu chỗ
      if(sortedParts.length === 2){
        var p0 = sortedParts[0].name || "?";
        var p1 = sortedParts[1].name || "?";
        var s0 = p0.trim().charAt(0);
        var s1 = p1.trim().charAt(0);

        if(spanCols >= 2 || titleLen <= 5){
          // Rộng rãi: hiện tên ngắn gọn cả 2 người
          multiTagsHtml = '<span class="cal-multiparts-wrap"><span class="cal-surname-tag">[' + escapeHtml(p0.split(" ")[0]) + ', ' + escapeHtml(p1.split(" ")[0]) + ']</span></span> ';
        } else {
          // Ô 1 ngày bình thường: hiện 2 họ [동..] [최..] test (vừa khít và cực kỳ rõ ràng, không bị cộc lốc +1명)
          multiTagsHtml = '<span class="cal-multiparts-wrap"><span class="cal-surname-tag">[' + escapeHtml(s0) + '..]</span> <span class="cal-surname-tag">[' + escapeHtml(s1) + '..]</span></span> ';
        }
      } else {
        // >= 3 người tham gia
        // Nếu ô rộng (spanCols >= 2) hoặc tiêu đề ngắn (<= 6): ưu tiên hiện 2 họ + số người còn lại
        var maxSurnames = 1;
        if(spanCols >= 3) maxSurnames = 3;
        else if(spanCols >= 2 || titleLen <= 6) maxSurnames = 2;

        if(maxSurnames > sortedParts.length) maxSurnames = sortedParts.length;
        var shownParts = sortedParts.slice(0, maxSurnames);
        var remainCount = sortedParts.length - maxSurnames;

        var tags = shownParts.map(function(p){
          var surname = (p.name || "?").trim().charAt(0);
          return '<span class="cal-surname-tag">[' + escapeHtml(surname) + '..]</span>';
        }).join(" ");

        var remainText = remainCount > 0 ? (' <span class="cal-remain-tag">+' + remainCount + '명</span>') : "";
        multiTagsHtml = '<span class="cal-multiparts-wrap">' + tags + remainText + '</span> ';
      }
    } else if(ev.ownerName && showOwnerPrefix){
      // Lịch cá nhân 1 người: giữ nguyên [Tên]
      var baseOwner = ev.ownerName.split(" ")[0];
      ownerPrefix = "[" + escapeHtml(baseOwner) + "] ";
    }

    var participantNames = "";
    if(ev.participants && Array.isArray(ev.participants) && ev.participants.length > 0){
      participantNames = " (참석자: " + ev.participants.map(function(p){ return p.name; }).join(", ") + ")";
    }

        var chipClass = "cal-chip schedule-chip cal-span-" + spanType;
    var widthStyle = "";
    if(spanCols > 1){
      var extraPx = (spanCols - 1) * 13;
      widthStyle = "width: calc(" + (spanCols * 100) + "% + " + extraPx + "px); z-index: 5;";
    }

    var styleAttr = widthStyle ? ('style="' + widthStyle + '"') : '';

    if(ev.approval_status === "rejected"){
      chipClass += " is-rejected";
    }
    if(isJira){
      var themeIdx = getTaskThemeIndex(jiraKey || ev.title);
      chipClass += " chip-theme-" + themeIdx;
    } else {
      var eventType = normalizeCompanyType(ev.type || "기타");
      chipClass += " chip-type-" + eventType;
    }

    var rangeText = ev.startDate + (ev.endDate !== ev.startDate ? (" ~ " + ev.endDate) : "");
    var localKey = (!isJira && ev.cardCode) ? ev.cardCode : "";
    var tooltip = (jiraKey || localKey ? (jiraKey || localKey) + ": " : "") + (ev.ownerName ? ev.ownerName + " - " : "") + ev.title + participantNames + " (" + rangeText + ")";
    if(ev.approval_status === "rejected"){
      tooltip += " [반려" + (ev.reject_reason ? ": " + ev.reject_reason : "") + "]";
    }

    var keyHtml = "";
    if(jiraKey){
      keyHtml = '<span class="cal-chip-key">' + escapeHtml(jiraKey) + '</span>';
    } else if(localKey){
      keyHtml = '<span class="cal-chip-key cal-local-key">' + escapeHtml(localKey) + '</span>';
    }
    var approvalBadge = "";
    if(ev.approval_status === "pending"){
      approvalBadge = ' <span style="font-size:10px;font-weight:700;background:#fef3c7;color:#b45309;padding:1px 5px;border-radius:4px;border:1px solid #fde68a;">대기</span>';
    } else if(ev.approval_status === "rejected"){
      approvalBadge = ' <span style="font-size:10px;font-weight:700;background:#fee2e2;color:#b91c1c;padding:1px 5px;border-radius:4px;border:1px solid #fca5a5;">반려</span>';
    }

    var displayTitle = (keyHtml ? keyHtml + " " : "") + (multiTagsHtml ? multiTagsHtml + " " : "") + ownerPrefix + escapeHtml(ev.title) + approvalBadge;
    var canDrag = (ev.source === "local" || !!ev.cardCode || ev.ownerKey === myUserKey);

    html += '<div class="' + chipClass + '" draggable="' + (canDrag ? 'true' : 'false') + '" data-event-id="' + escapeHtml(String(ev.id)) + '" ' + styleAttr + ' title="' + escapeHtml(tooltip) + '">';
    if(canDrag && (spanType === 'single' || spanType === 'range' || spanType === 'to-next')){
      html += '<div class="cal-resizer cal-resizer-left" data-edge="start" title="시작일 변경 (마우스로 드래그)"></div>';
    }
    html += '<span class="cal-chip-title">' + displayTitle + '</span>';
    if(canDrag && (spanType === 'single' || spanType === 'range' || spanType === 'from-prev')){
      html += '<div class="cal-resizer cal-resizer-right" data-edge="end" title="종료일 변경 (마우스로 드래그)"></div>';
    }
    html += '</div>';
  });

  if(c.overflowCount > 0){
    var moreText = isEnCell ? ("+" + c.overflowCount + " more") : ("+" + c.overflowCount + "개 더보기");
    html += '<div class="cal-more-link" data-date="' + escapeHtml(c.dateStr) + '" title="' + moreText + '">' + moreText + '</div>';
  }
  html += '</div></td>';
  return html;
}

// ── Helper Date Functions ──
function parseDateYMD(str){
  if(!str) return new Date();
  var p = str.split("-");
  return new Date(parseInt(p[0], 10), parseInt(p[1], 10) - 1, parseInt(p[2], 10));
}
function formatYMD(d){
  return d.getFullYear() + "-" + pad2(d.getMonth() + 1) + "-" + pad2(d.getDate());
}

// ── Quick Event Modal Handling ──
function openSchedEventModal(dateStr, ev){
  if(!loggedInUser){
    if(typeof showToast === "function") showToast("먼저 우측 상단에서 로그인해주세요.");
    return;
  }
  var isViewer = (typeof isViewerUser === "function") ? isViewerUser() : (loggedInUser && loggedInUser.role === "viewer");
  if(!ev && isViewer){
    if(typeof showToast === "function") showToast("조회 전용(Viewer) 계정은 새 일정을 추가할 수 없습니다.");
    return;
  }
  var isEn = isCurrentLangEn();
  if(ev){
    startEditEventForm(ev);
    if(schedModalTitle) schedModalTitle.textContent = isEn ? "Event Details / Edit" : "일정 상세 / 수정";
  } else {
    startNewEventForm(dateStr || schedSelectedDate || todayStr());
    if(schedModalTitle) schedModalTitle.textContent = isEn ? "Add New Event" : "새 일정 추가";
  }
  if(schedEventModalBackdrop){
    schedEventModalBackdrop.hidden = false;
  }
  if(schedTitle && !schedTitle.disabled){
    setTimeout(function(){ schedTitle.focus(); }, 120);
  }
}

function closeSchedEventModal(){
  if(schedEventModalBackdrop){
    schedEventModalBackdrop.hidden = true;
  }
  if(schedFormError) schedFormError.textContent = "";
}

// ── View Switcher Handling: Month / Week / Agenda ──
function switchScheduleView(mode){
  currentViewMode = mode || "month";
  try { localStorage.setItem("jarvis_cal_view_mode", currentViewMode); } catch(e){}

  if(schedViewMonthBtn) schedViewMonthBtn.classList.toggle("active", currentViewMode === "month");
  if(schedViewWeekBtn) schedViewWeekBtn.classList.toggle("active", currentViewMode === "week");
  if(schedViewAgendaBtn) schedViewAgendaBtn.classList.toggle("active", currentViewMode === "agenda");

  if(schedMonthPane){
    schedMonthPane.hidden = currentViewMode !== "month";
    schedMonthPane.classList.toggle("active", currentViewMode === "month");
  }
  if(schedWeekPane){
    schedWeekPane.hidden = currentViewMode !== "week";
    schedWeekPane.classList.toggle("active", currentViewMode === "week");
  }
  if(schedAgendaPane){
    schedAgendaPane.hidden = currentViewMode !== "agenda";
    schedAgendaPane.classList.toggle("active", currentViewMode === "agenda");
  }

  refreshCurrentView();
}

function refreshCurrentView(){
  renderJiraOngoing();
  if(currentViewMode === "week"){
    renderWeekView();
  } else if(currentViewMode === "agenda"){
    renderAgendaView();
  } else {
    renderSchedule();
  }
}

// ── 1. Render Month View Grid (5-day or 7-day) ──
function renderSchedule(){
  if(!schedGrid) return;
  var loggedIn = !!loggedInUser;
  if(schedLoginNotice) schedLoginNotice.hidden = loggedIn;
  renderJiraOngoing();

  var isEn = isCurrentLangEn();
  if(schedMonthLabel){
    schedMonthLabel.textContent = isEn
      ? (EN_MONTH_NAMES[schedViewMonth - 1] + " " + schedViewYear)
      : (schedViewYear + "년 " + schedViewMonth + "월");
  }

  var today = todayStr();
  var html = "";
  var showOwnerPrefix = selectedMemberKeys.size > 1;

  if(isWeekendVisible){
    // 7-Day Calendar (일 ~ 토)
    if(schedWeekdays){
      schedWeekdays.innerHTML = isEn
        ? '<th class="sun">Sun</th><th>Mon</th><th>Tue</th><th>Wed</th><th>Thu</th><th>Fri</th><th class="sat">Sat</th>'
        : '<th class="sun">일</th><th>월</th><th>화</th><th>수</th><th>목</th><th>금</th><th class="sat">토</th>';
    }

    var startWeekday = new Date(schedViewYear, schedViewMonth - 1, 1).getDay();
    var gridStart = new Date(schedViewYear, schedViewMonth - 1, 1 - startWeekday);

    // Calculate actual number of weeks needed for this month (5 or 6, never unnecessary extra empty weeks)
    var daysInMonth = new Date(schedViewYear, schedViewMonth, 0).getDate();
    var numWeeks = Math.ceil((startWeekday + daysInMonth) / 7);

    for(var row = 0; row < numWeeks; row++){
      var weekCells = [];
      for(var col = 0; col < 7; col++){
        var dayIdx = row * 7 + col;
        var d = new Date(gridStart.getFullYear(), gridStart.getMonth(), gridStart.getDate() + dayIdx);
        var dateStr = d.getFullYear() + "-" + pad2(d.getMonth() + 1) + "-" + pad2(d.getDate());
        weekCells.push({
          dateStr: dateStr,
          dateNum: d.getDate(),
          outside: d.getMonth() !== (schedViewMonth - 1),
          isToday: dateStr === today,
          isSelected: dateStr === schedSelectedDate,
          isSun: col === 0,
          isSat: col === 6,
          events: eventsOnDate(dateStr)
        });
      }
      allocateWeekSlots(weekCells, 4);
      html += '<tr>';
      weekCells.forEach(function(c){ html += renderCellHtml(c, showOwnerPrefix); });
      html += '</tr>';
    }
  } else {
    // 5-Day Workweek (월 ~ 금, 주말 숨김)
    if(schedWeekdays){
      schedWeekdays.innerHTML = isEn
        ? '<th>Mon</th><th>Tue</th><th>Wed</th><th>Thu</th><th>Fri</th>'
        : '<th>월</th><th>화</th><th>수</th><th>목</th><th>금</th>';
    }

    var firstOfMonth = new Date(schedViewYear, schedViewMonth - 1, 1);
    var dow = firstOfMonth.getDay();
    var diffToMon = 0;
    if(dow === 0) diffToMon = 1;
    else if(dow === 6) diffToMon = 2;
    else diffToMon = -(dow - 1);

    var cursor = new Date(schedViewYear, schedViewMonth - 1, 1 + diffToMon);
    var lastOfMonth = new Date(schedViewYear, schedViewMonth, 0);

    var weeks = 0;
    while(cursor <= lastOfMonth || weeks < 5){
      var weekCells = [];
      for(var col = 0; col < 5; col++){
        var d = new Date(cursor.getFullYear(), cursor.getMonth(), cursor.getDate() + col);
        var dateStr = d.getFullYear() + "-" + pad2(d.getMonth() + 1) + "-" + pad2(d.getDate());
        weekCells.push({
          dateStr: dateStr,
          dateNum: d.getDate(),
          outside: d.getMonth() !== (schedViewMonth - 1),
          isToday: dateStr === today,
          isSelected: dateStr === schedSelectedDate,
          isSun: false,
          isSat: false,
          events: eventsOnDate(dateStr)
        });
      }
      allocateWeekSlots(weekCells, 4);
      html += '<tr>';
      weekCells.forEach(function(c){ html += renderCellHtml(c, showOwnerPrefix); });
      html += '</tr>';

      cursor.setDate(cursor.getDate() + 7);
      weeks++;
      if(weeks >= 6) break;
    }
  }

  schedGrid.innerHTML = html;

  var legendHtml = "";
  Object.keys(SCHED_TYPE_COLORS).forEach(function(t){
    var isCompany = Object.prototype.hasOwnProperty.call(SCHED_COMPANY_TYPES, t);
    var isChecked = isCompany ? (isCompanyGroupEnabled && selectedCompanyTypes.has(t)) : isTasksGroupEnabled;
    legendHtml += '<span class="sched-legend-pill" data-type="' + escapeHtml(t) + '" style="cursor:pointer; display:inline-flex; align-items:center; gap:5px; padding:2px 6px; border-radius:4px; transition:opacity 0.15s; opacity:' + (isChecked ? '1' : '0.4') + ';" title="' + escapeHtml(t) + ' 필터 토글">' +
      '<span class="sl-dot" style="background:' + SCHED_TYPE_COLORS[t] + '"></span>' + escapeHtml(t) +
    '</span>';
  });
  if(schedLegend) schedLegend.innerHTML = legendHtml;

  renderSchedDayList();
}

// ── 2. Render Week View (주간 달력) ──
function renderWeekView(){
  if(!schedWeekGrid) return;
  var loggedIn = !!loggedInUser;
  if(schedLoginNotice) schedLoginNotice.hidden = loggedIn;

  var sel = parseDateYMD(schedSelectedDate || todayStr());
  var dow = sel.getDay(); // 0=Sun, 1=Mon...6=Sat
  var startDate = new Date(sel);

  var numDays = isWeekendVisible ? 7 : 5;
  if(isWeekendVisible){
    startDate.setDate(sel.getDate() - dow);
  } else {
    var diff = dow === 0 ? -6 : (1 - dow);
    startDate.setDate(sel.getDate() + diff);
  }

  var weekDates = [];
  for(var i = 0; i < numDays; i++){
    var d = new Date(startDate.getFullYear(), startDate.getMonth(), startDate.getDate() + i);
    var dStr = formatYMD(d);
    weekDates.push({
      date: d,
      dateStr: dStr,
      dow: d.getDay(),
      events: eventsOnDate(dStr)
    });
  }

  // Multi-day Event Slot Allocation cho tuần
  allocateWeekSlots(weekDates, 999);

  var firstD = weekDates[0].dateStr;
  var lastD = weekDates[weekDates.length - 1].dateStr;
  var isEn = isCurrentLangEn();
  if(schedMonthLabel){
    var y1 = firstD.substring(0, 4);
    var m1 = parseInt(firstD.substring(5, 7), 10);
    var d1 = parseInt(firstD.substring(8, 10), 10);
    var m2 = parseInt(lastD.substring(5, 7), 10);
    var d2 = parseInt(lastD.substring(8, 10), 10);
    schedMonthLabel.textContent = isEn
      ? (EN_MONTH_ABBR[m1 - 1] + " " + d1 + " - " + (m1 !== m2 ? (EN_MONTH_ABBR[m2 - 1] + " ") : "") + d2 + ", " + y1)
      : (y1 + "년 " + m1 + "월 " + d1 + "일 ~ " + (m1 !== m2 ? (m2 + "월 ") : "") + d2 + "일");
  }

  var dayNames = isEn ? ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"] : ["일", "월", "화", "수", "목", "금", "토"];
  var today = todayStr();

  // Render Header
  if(schedWeekHeaderRow){
    var headerHtml = "";
    weekDates.forEach(function(w){
      var isToday = w.dateStr === today;
      var dayName = dayNames[w.dow];
      var isSun = w.dow === 0;
      var isSat = w.dow === 6;
      var colClass = "cal-week-header-col" + (isToday ? " is-today" : "") + (isSun ? " sun" : "") + (isSat ? " sat" : "");
      headerHtml += '<th class="' + (isSun ? "sun" : (isSat ? "sat" : "")) + '">';
      headerHtml += '<div class="' + colClass + '">';
      headerHtml += '<span class="day-name">' + dayName + '</span>';
      headerHtml += '<span class="day-number' + (isToday ? " is-today" : "") + '">' + w.date.getDate() + '</span>';
      headerHtml += '</div></th>';
    });
    schedWeekHeaderRow.innerHTML = headerHtml;
  }

  // Render Week Grid (1 hàng nhiều cột, nối liền lịch dài ngày qua các cột)
  var gridHtml = '<tr>';
  weekDates.forEach(function(w){
    var isToday = w.dateStr === today;
    var isSelected = w.dateStr === schedSelectedDate;
    var isSun = w.dow === 0;
    var isSat = w.dow === 6;

    var cellClass = "cal-week-cell schedule-day" + (isToday ? " is-today today" : "") + (isSelected ? " selected" : "") + (isSun ? " sun" : "") + (isSat ? " sat" : "");

    gridHtml += '<td class="' + cellClass + '" data-date="' + w.dateStr + '" style="vertical-align:top;min-height:500px;height:500px;padding:8px 6px;">';
    gridHtml += '<div class="cal-events-list cal-week-events-list">';

    var hasSlots = w.slots && w.slots.length > 0;
    var hasVisibleItem = false;
    if(hasSlots){
      for(var s = 0; s < w.slots.length; s++){
        if(w.slots[s].type === 'event' || w.slots[s].placeholder){
          hasVisibleItem = true;
          break;
        }
      }
    }

    if(!hasVisibleItem){
      gridHtml += '<div style="font-size:11.5px;color:var(--ink-faint);padding:6px 2px;opacity:0.6;">일정 없음</div>';
    } else {
      (w.slots || []).forEach(function(slot){
        if(slot.type === 'spacer'){
          gridHtml += '<div class="cal-week-card-spacer"></div>';
          return;
        }
        var ev = slot.event;
        var isJira = ev.source === "jira";
        var jiraKey = (ev.jira && ev.jira.key) ? ev.jira.key : (isJira ? ev.title : "");
        var evType = ev.type || "기타";
        var spanCols = slot.spanCols || 1;
        var spanType = slot.spanType || 'single';

        var cardClass = "cal-week-event-card schedule-chip cal-span-" + spanType;
        var themeIdx = getTaskThemeIndex(jiraKey || ev.title);

        if(isJira){
          cardClass += " chip-theme-" + themeIdx;
        } else {
          cardClass += " chip-type-" + evType;
        }

        var widthStyle = "";
        if(spanCols > 1){
          var extraPx = (spanCols - 1) * 1;
          widthStyle = "width: calc(" + (spanCols * 100) + "% + " + extraPx + "px); z-index: 5;";
        }
        var styleAttr = widthStyle ? ('style="' + widthStyle + '"') : '';

        var range = ev.startDate === ev.endDate ? ev.startDate : (ev.startDate + " ~ " + ev.endDate);
        var ownerTag = ev.ownerName ? ('<span style="font-weight:700;">' + escapeHtml(ev.ownerName) + '</span>') : "";
        var canDrag = (ev.source === "local" || !!ev.cardCode || ev.ownerKey === myUserKey);
        var localKey = (!isJira && ev.cardCode) ? ev.cardCode : "";

        gridHtml += '<div class="' + cardClass + '" draggable="' + (canDrag ? 'true' : 'false') + '" data-event-id="' + escapeHtml(String(ev.id)) + '" ' + styleAttr + ' title="' + escapeHtml(ev.title) + '">';
        if(canDrag && (spanType === 'single' || spanType === 'range' || spanType === 'to-next')){
          gridHtml += '<div class="cal-resizer cal-resizer-left" data-edge="start" title="시작일 변경 (마우스로 드래그)"></div>';
        }
        gridHtml += '<div style="display:flex;align-items:center;gap:4px;font-size:10px;margin-bottom:3px;">';
        if(jiraKey){
          gridHtml += '<span class="cal-chip-key">' + escapeHtml(jiraKey) + '</span>';
        } else if(localKey){
          gridHtml += '<span class="cal-chip-key cal-local-key">' + escapeHtml(localKey) + '</span>';
        } else {
          gridHtml += '<span style="font-weight:700;font-size:10px;opacity:0.85;">' + escapeHtml(evType) + '</span>';
        }
        if(ownerTag) gridHtml += '<span style="margin-left:auto;font-size:10px;opacity:0.8;">' + ownerTag + '</span>';
        gridHtml += '</div>';
        gridHtml += '<div class="cwe-title">' + escapeHtml(ev.title) + '</div>';
        if(ev.startDate !== ev.endDate){
          gridHtml += '<div class="cwe-meta">' + escapeHtml(range) + '</div>';
        }
        if(canDrag && (spanType === 'single' || spanType === 'range' || spanType === 'from-prev')){
          gridHtml += '<div class="cal-resizer cal-resizer-right" data-edge="end" title="종료일 변경 (마우스로 드래그)"></div>';
        }
        gridHtml += '</div>';
      });
    }

    gridHtml += '</div></td>';
  });
  gridHtml += '</tr>';

  schedWeekGrid.innerHTML = gridHtml;
}

// ── 3. Render Agenda View (일정 목록) ──
function renderAgendaView(){
  if(!schedAgendaList) return;
  var ymPrefix = schedViewYear + "-" + pad2(schedViewMonth);
  var isEn = isCurrentLangEn();
  if(schedMonthLabel){
    schedMonthLabel.textContent = isEn
      ? (EN_MONTH_NAMES[schedViewMonth - 1] + " " + schedViewYear + " Events")
      : (schedViewYear + "년 " + schedViewMonth + "월 일정 목록");
  }

  var monthStart = ymPrefix + "-01";
  var lastDayNum = new Date(schedViewYear, schedViewMonth, 0).getDate();
  var monthEnd = ymPrefix + "-" + pad2(lastDayNum);

  var matchingEvents = schedEvents.filter(function(ev){
    if(!isEventVisible(ev)) return false;
    var s = ev.startDate || "";
    var e = ev.endDate || s;
    if(!s || !e) return false;
    if(s > monthEnd || e < monthStart) return false;
    return true;
  });

  if(!matchingEvents.length){
    schedAgendaList.innerHTML = '<div class="empty-state" style="padding:48px 16px;text-align:center;background:var(--surface);border:1px solid var(--line);border-radius:12px;">' +
      '<div style="font-size:32px;margin-bottom:8px;">📅</div>' +
      '<div style="font-size:14px;font-weight:700;color:var(--ink);margin-bottom:4px;">등록된 일정이 없습니다.</div>' +
      '<div style="font-size:12.5px;color:var(--ink-faint);">우측 상단의 "+ 일정 추가" 버튼을 눌러 새 일정을 등록해보세요.</div>' +
    '</div>';
    return;
  }

  // Group by unique dates in this month
  var dateMap = new Map();
  var dayNames = ["일", "월", "화", "수", "목", "금", "토"];

  for(var day = 1; day <= lastDayNum; day++){
    var dStr = ymPrefix + "-" + pad2(day);
    var evs = matchingEvents.filter(function(ev){
      return ev.startDate <= dStr && dStr <= ev.endDate;
    });
    if(evs.length > 0){
      dateMap.set(dStr, evs);
    }
  }

  var today = todayStr();
  var html = "";

  dateMap.forEach(function(evs, dStr){
    var dObj = parseDateYMD(dStr);
    var dayNum = dObj.getDate();
    var weekdayName = dayNames[dObj.getDay()];
    var isToday = dStr === today;

    html += '<div class="agenda-day-group">';
    html += '<div class="agenda-date-badge' + (isToday ? ' is-today' : '') + '">';
    html += '<span class="adb-day">' + dayNum + '</span>';
    html += '<span class="adb-weekday">' + weekdayName + '요일</span>';
    html += '</div>';

    html += '<div class="agenda-events-col">';
    evs.forEach(function(ev){
      var isJira = ev.source === "jira";
      var jiraKey = (ev.jira && ev.jira.key) ? ev.jira.key : (isJira ? ev.title : "");
      var evType = ev.type || "기타";
      var themeIdx = getTaskThemeIndex(jiraKey || ev.title);
      var typeClass = isJira ? ("chip-theme-" + themeIdx) : ("chip-type-" + evType);
      var range = ev.startDate === ev.endDate ? ev.startDate : (ev.startDate + " ~ " + ev.endDate);

      var partsText = "";
      if(ev.participants && ev.participants.length > 1){
        partsText = ' <span style="font-size:11px;color:var(--tab-schedule);opacity:0.9;">👥 ' +
          ev.participants.map(function(p){ return escapeHtml(p.name); }).join(", ") + '</span>';
      }

      html += '<div class="agenda-item-row schedule-chip" data-event-id="' + escapeHtml(String(ev.id)) + '" title="클릭 시 ' + (isJira || ev.cardCode ? '캔버스 열기' : '상세보기') + '">';
      html += '<div class="agenda-item-main">';
      var localKey = (!isJira && ev.cardCode) ? ev.cardCode : "";
      if(jiraKey){
        html += '<span class="agenda-item-type ' + typeClass + '">' + escapeHtml(jiraKey) + '</span>';
      } else if(localKey){
        html += '<span class="agenda-item-type ' + typeClass + ' cal-local-key">' + escapeHtml(localKey) + '</span>';
      } else {
        html += '<span class="agenda-item-type ' + typeClass + '">' + escapeHtml(evType) + '</span>';
      }
      html += '<div class="agenda-item-title" style="font-size:13px;font-weight:700;color:var(--ink);">' +
        (ev.ownerName ? ('<span style="font-weight:600;color:var(--ink-soft);margin-right:6px;">[' + escapeHtml(ev.ownerName) + ']</span>') : '') +
        escapeHtml(ev.title) + partsText + '</div>';
      html += '</div>';

      html += '<div class="agenda-item-meta" style="font-size:11.5px;color:var(--ink-faint);flex-shrink:0;">' +
        (isJira ? '🔗 Jira' : range) +
      '</div>';
      html += '</div>';
    });
    html += '</div>'; // agenda-events-col
    html += '</div>'; // agenda-day-group
  });

  schedAgendaList.innerHTML = html;
}

function renderSchedDayList(){
  if(!schedDayList) return;
  var evs = eventsOnDate(schedSelectedDate).slice().sort(function(a, b){ return a.startDate < b.startDate ? -1 : 1; });
  var html = '<p class="records-eyebrow">' + schedSelectedDate + ' 일정 (' + evs.length + '건)</p>';
  if(!evs.length){
    html += '<p style="font-size:12.5px;color:var(--ink-faint);margin:0;">선택된 팀원의 등록된 일정이 없습니다.</p>';
  } else {
    evs.forEach(function(ev){
      var range = ev.startDate === ev.endDate ? ev.startDate : (ev.startDate + " ~ " + ev.endDate);
      var jiraNote = ev.source === "jira" ? '<br><span class="sd-range">🔗 Jira 자동 연동' + (ev.jira && ev.jira.key ? " · " + escapeHtml(ev.jira.key) : "") + '</span>' : "";
      var ownerTag = ev.ownerName ? ('<span style="font-size:11px;font-weight:600;color:var(--ink-soft);background:var(--code-bg);padding:1px 6px;border-radius:4px;margin-right:6px;">' + escapeHtml(ev.ownerName) + '</span>') : "";
      var isMe = ev.ownerKey === myUserKey;

      var participantsBadge = "";
      if(ev.participants && Array.isArray(ev.participants) && ev.participants.length > 1){
        var others = ev.participants.filter(function(p){ return p.key !== ev.ownerKey; });
        if(others.length > 0){
          var names = others.map(function(p){ return escapeHtml(p.name); }).join(", ");
          participantsBadge = '<br><span class="sd-range" style="color:var(--tab-schedule);">👥 동반: ' + names + '</span>';
        }
      }

      var approvalBadge = "";
      if(ev.approval_status === "pending"){
        approvalBadge = ' <span style="font-size:10px;font-weight:700;background:#fef3c7;color:#b45309;padding:1px 5px;border-radius:4px;border:1px solid #fde68a;">승인 대기</span>';
      } else if(ev.approval_status === "rejected"){
        approvalBadge = ' <span style="font-size:10px;font-weight:700;background:#fee2e2;color:#b91c1c;padding:1px 5px;border-radius:4px;border:1px solid #fca5a5;">반려됨' + (ev.reject_reason ? ' (' + escapeHtml(ev.reject_reason) + ')' : '') + '</span>';
      }

      html += '<button type="button" class="schedule-day-item" data-id="' + escapeHtml(String(ev.id)) + '" title="' + (isMe ? '클릭하여 수정' : '상세보기') + '">';
      var evType = ev.type || "기타";
      html += '<span class="sd-type sd-type-' + escapeHtml(evType) + '">' + escapeHtml(evType) + '</span>';
      html += '<span style="flex:1;">' + ownerTag + escapeHtml(ev.title) + approvalBadge + '<br><span class="sd-range">' + range + '</span>' + jiraNote + participantsBadge + '</span>';
      html += '</button>';
    });
  }
  schedDayList.innerHTML = html;
}

// ── Day All Events Modal (Hiển thị toàn bộ lịch của 1 ngày khi click "+N개 더보기" hoặc số đếm ngày) ──
function openDayEventsModal(dateStr){
  var backdrop = document.getElementById("schedDayEventsModalBackdrop");
  var titleEl = document.getElementById("schedDayEventsModalTitle");
  var countEl = document.getElementById("schedDayEventsModalCount");
  var listEl = document.getElementById("schedDayEventsModalList");
  if(!backdrop || !listEl) return;

  var evs = eventsOnDate(dateStr).slice().sort(function(a, b){
    if(a.startDate !== b.startDate) return a.startDate < b.startDate ? -1 : 1;
    return (a.title || "").localeCompare(b.title || "");
  });

  var isEn = isCurrentLangEn();
  if(titleEl) titleEl.textContent = dateStr + (isEn ? " All Events" : " 전체 일정");
  if(countEl) countEl.textContent = evs.length + (isEn ? " items" : "건");

  if(!evs.length){
    listEl.innerHTML = '<div class="empty-state" style="padding:24px 8px;font-size:13px;text-align:center;color:var(--ink-faint);">' +
      (isEn ? 'No events scheduled for this day.' : '해당 일자의 일정이 없습니다.') + '</div>';
  } else {
    var html = "";
    evs.forEach(function(ev){
      var isJira = ev.source === "jira";
      var jiraKey = (ev.jira && ev.jira.key) ? ev.jira.key : (isJira ? ev.title : "");
      var evType = ev.type || "기타";
      var themeIdx = getTaskThemeIndex(jiraKey || ev.title);
      var typeClass = isJira ? ("chip-theme-" + themeIdx) : ("chip-type-" + evType);
      var range = ev.startDate === ev.endDate ? ev.startDate : (ev.startDate + " ~ " + ev.endDate);

      var partsText = "";
      if(ev.participants && ev.participants.length > 1){
        partsText = ' <span style="font-size:11px;color:var(--tab-schedule);opacity:0.9;">👥 ' +
          ev.participants.map(function(p){ return escapeHtml(p.name); }).join(", ") + '</span>';
      }

      var localKey = (!isJira && ev.cardCode) ? ev.cardCode : "";
      var badgeHtml = "";
      if(jiraKey){
        badgeHtml = '<span class="agenda-item-type ' + typeClass + '">' + escapeHtml(jiraKey) + '</span>';
      } else if(localKey){
        badgeHtml = '<span class="agenda-item-type ' + typeClass + ' cal-local-key">' + escapeHtml(localKey) + '</span>';
      } else {
        badgeHtml = '<span class="agenda-item-type ' + typeClass + '">' + escapeHtml(evType) + '</span>';
      }

      html += '<div class="agenda-item-row sched-day-modal-item" data-event-id="' + escapeHtml(String(ev.id)) + '" style="cursor:pointer;" title="클릭 시 ' + (isJira || localKey ? '캔버스 열기' : '상세보기') + '">';
      html += '<div class="agenda-item-main">';
      html += badgeHtml;
      html += '<div class="agenda-item-title" style="font-size:13px;font-weight:700;color:var(--ink);">' +
        (ev.ownerName ? ('<span style="font-weight:600;color:var(--ink-soft);margin-right:6px;">[' + escapeHtml(ev.ownerName) + ']</span>') : '') +
        escapeHtml(ev.title) + partsText + '</div>';
      html += '</div>';

      html += '<div class="agenda-item-meta" style="font-size:11.5px;color:var(--ink-faint);flex-shrink:0;">' +
        (isJira ? '🔗 Jira' : range) +
      '</div>';
      html += '</div>';
    });
    listEl.innerHTML = html;
  }

  backdrop.hidden = false;
}

function closeDayEventsModal(){
  var backdrop = document.getElementById("schedDayEventsModalBackdrop");
  if(backdrop) backdrop.hidden = true;
}

// ── Event Chip Click Dispatcher: Local Task -> Canvas, Jira -> Canvas, Internal -> Modal ──
function handleEventChipClick(evId){
  var found = schedEvents.filter(function(ev){ return String(ev.id) === evId; })[0];
  if(!found) return;

  var cardCode = found.cardCode || (found.source === "local" ? found.id : null);
  if(cardCode && window.showIssueInCanvas && typeof window.showIssueInCanvas === "function"){
    window.showIssueInCanvas(cardCode);
    if(typeof showToast === "function") showToast("업무 카드 [" + cardCode + "] 캔버스를 엽니다.");
    return;
  }

  var isJira = found.source === "jira" || (found.jira && found.jira.key);
  var jiraKey = (found.jira && found.jira.key) ? found.jira.key : (isJira ? found.title : "");

  if(jiraKey && window.showIssueInCanvas && typeof window.showIssueInCanvas === "function"){
    window.showIssueInCanvas(jiraKey);
    if(typeof showToast === "function") showToast("Jira 이슈 [" + jiraKey + "] 캔버스를 엽니다.");
    return;
  }

  // Sự kiện cá nhân / nội bộ -> mở modal
  openSchedEventModal(found.startDate, found);
}

// ── Drag & Drop Scheduling (Thẻ Local -> Ô ngày Lịch, hoặc kéo chip đổi ngày) ──
function assignTaskToDate(taskId, targetDate, endDate){
  if(!loggedInUser){
    if(typeof showToast === "function") showToast("먼저 로그인해주세요.");
    return;
  }
  var isViewer = (typeof isViewerUser === "function") ? isViewerUser() : (loggedInUser && loggedInUser.role === "viewer");
  if(isViewer){
    if(typeof showToast === "function") showToast("조회 전용(Viewer) 계정은 일정을 배정할 수 없습니다.");
    return;
  }
  var payload = { taskId: taskId, date: targetDate };
  if(endDate){
    payload.endDate = endDate;
  }
  apiSchedulePost("/api/schedule/assign-task", payload).then(function(res){
    if(res.status === 401){ handleAuthExpired(); return; }
    if(!res.data.ok){
      if(typeof showToast === "function") showToast(res.data.error || "일정 배정에 실패했습니다.");
      return;
    }
    var code = res.data.cardCode || taskId;
    var rangeNotice = (endDate && endDate !== targetDate) ? (targetDate + " ~ " + endDate) : targetDate;
    var jiraActive = window.__JIRA_STATUS__ ? window.__JIRA_STATUS__.enabled : false;
    var jiraNotice = (jiraActive && res.data.jiraKey) ? (" (Jira: " + res.data.jiraKey + " 백그라운드 동기화)") : "";
    if(typeof showToast === "function"){
      showToast("💼 업무 카드 [" + code + "] 일정이 " + rangeNotice + "로 배정되었습니다." + jiraNotice);
    }
    notifyScheduleChanged();
    loadSchedule();
  }).catch(function(err){
    if(typeof showToast === "function") showToast("서버 통신 중 오류가 발생했습니다.");
  });
}

function showUnassignUndoToast(cardCode, taskId){
  var existingToast = document.getElementById("schedUndoToast");
  if(existingToast) existingToast.remove();

  var toast = document.createElement("div");
  toast.id = "schedUndoToast";
  toast.style.cssText = "position:fixed;bottom:24px;right:24px;z-index:1100;background:#1e293b;color:#f8fafc;padding:12px 18px;border-radius:10px;box-shadow:0 8px 24px rgba(0,0,0,0.35);display:flex;align-items:center;gap:12px;font-size:13px;border:1px solid rgba(255,255,255,0.1);animation:slideUpToast 0.25s ease;";
  
  toast.innerHTML = '<span><strong>[' + escapeHtml(cardCode) + ']</strong> 일정이 해제되었습니다.</span>' +
    '<button type="button" id="btnSchedUndoUnassign" style="background:#3b82f6;color:#fff;border:none;padding:5px 12px;border-radius:6px;font-size:12px;font-weight:600;cursor:pointer;transition:background 0.15s ease;" onmouseover="this.style.background=\'#2563eb\'" onmouseout="this.style.background=\'#3b82f6\'">실행 취소 (Undo)</button>' +
    '<button type="button" id="btnSchedCloseUndoToast" style="background:none;border:none;color:#94a3b8;font-size:14px;cursor:pointer;line-height:1;padding:0 2px;">✕</button>';
  
  document.body.appendChild(toast);

  var timer = setTimeout(function(){
    if(toast && toast.parentNode) toast.remove();
  }, 7000);

  var undoBtn = toast.querySelector("#btnSchedUndoUnassign");
  if(undoBtn){
    undoBtn.addEventListener("click", function(){
      clearTimeout(timer);
      toast.remove();
      if(taskId && window.showScheduleTask){
        window.showScheduleTask(taskId);
      }
    });
  }
  var closeBtn = toast.querySelector("#btnSchedCloseUndoToast");
  if(closeBtn){
    closeBtn.addEventListener("click", function(){
      clearTimeout(timer);
      toast.remove();
    });
  }
}

function unassignTask(taskId){
  if(!taskId) return;
  if(!loggedInUser){
    if(typeof showToast === "function") showToast("먼저 로그인해주세요.");
    return;
  }
  apiSchedulePost("/api/schedule/unassign-task", { taskId: taskId }).then(function(res){
    if(res.status === 401){ handleAuthExpired(); return; }
    if(!res.data.ok){
      if(typeof showToast === "function") showToast(res.data.error || "일정 해제에 실패했습니다.");
      return;
    }
    var code = res.data.cardCode || taskId;
    showUnassignUndoToast(code, taskId);
    notifyScheduleChanged();
    loadSchedule();
  }).catch(function(err){
    if(typeof showToast === "function") showToast("서버 통신 중 오류가 발생했습니다.");
  });
}
window.unassignTask = unassignTask;

function deleteCustomScheduleEvent(id){
  if(!id) return;
  if(!loggedInUser){
    if(typeof showToast === "function") showToast("먼저 로그인해주세요.");
    return;
  }
  var ev = schedEvents.filter(function(x){ return String(x.id) === String(id); })[0];
  if(ev && ev.ownerKey && ev.ownerKey !== myUserKey){
    if(typeof showToast === "function") showToast("본인이 등록한 일정만 삭제할 수 있습니다.");
    return;
  }
  apiSchedulePost("/api/schedule/delete", { id: id }).then(function(res){
    if(res.status === 401){ handleAuthExpired(); return; }
    if(!res.data.ok){
      if(typeof showToast === "function") showToast(res.data.error || "일정 삭제에 실패했습니다.");
      return;
    }
    var title = (ev && ev.title) ? (" [" + ev.title + "]") : "";
    if(typeof showToast === "function") showToast("🗑️ 일정" + title + "이(가) 삭제되었습니다.");
    loadSchedule();
  }).catch(function(){
    if(typeof showToast === "function") showToast("서버 통신 중 오류가 발생했습니다.");
  });
}
window.deleteCustomScheduleEvent = deleteCustomScheduleEvent;

function showScheduleTask(taskId){
  if(!taskId) return;
  if(!loggedInUser){
    if(typeof showToast === "function") showToast("먼저 로그인해주세요.");
    return;
  }
  apiSchedulePost("/api/schedule/assign-task", { taskId: taskId, action: "show" }).then(function(res){
    if(res.status === 401){ handleAuthExpired(); return; }
    if(!res.data.ok){
      if(typeof showToast === "function") showToast(res.data.error || "달력 표시에 실패했습니다.");
      return;
    }
    var code = res.data.cardCode || taskId;
    if(typeof showToast === "function"){
      showToast("📅 업무 카드 [" + code + "] 일정이 달력에 활성화되었습니다.");
    }
    notifyScheduleChanged();
    loadSchedule();
  }).catch(function(err){
    if(typeof showToast === "function") showToast("서버 통신 중 오류가 발생했습니다.");
  });
}
window.showScheduleTask = showScheduleTask;

function rescheduleCalendarEvent(eventId, targetDate){
  var ev = schedEvents.filter(function(x){ return String(x.id) === String(eventId); })[0];
  if(!ev) return;
  if(ev.source === "jira"){
    if(typeof showToast === "function") showToast("Jira 연동 일정은 Jira에서 수정해주세요.");
    return;
  }
  if(ev.ownerKey && ev.ownerKey !== myUserKey){
    if(typeof showToast === "function") showToast("본인이 등록한 일정만 이동할 수 있습니다.");
    return;
  }
  var origStart = parseDateYMD(ev.startDate);
  var origEnd = parseDateYMD(ev.endDate || ev.startDate);
  var dayDiff = Math.round((origEnd - origStart) / (1000 * 60 * 60 * 24));
  var newStart = targetDate;
  var newEnd = newStart;
  if(dayDiff > 0){
    var nD = parseDateYMD(newStart);
    nD.setDate(nD.getDate() + dayDiff);
    newEnd = formatYMD(nD);
  }

  var body = {
    id: ev.id,
    title: ev.title,
    type: ev.type,
    startDate: newStart,
    endDate: newEnd,
    memo: ev.memo || "",
    participants: ev.participants || []
  };

  var oldStart = ev.startDate;
  var oldEnd = ev.endDate;
  ev.startDate = newStart;
  ev.endDate = newEnd;
  refreshCurrentView();

  apiSchedulePost("/api/schedule/update", body).then(function(res){
    if(res.status === 401){ handleAuthExpired(); return; }
    if(!res.data.ok){
      ev.startDate = oldStart;
      ev.endDate = oldEnd;
      refreshCurrentView();
      if(typeof showToast === "function") showToast(res.data.error || "일정 변경에 실패했습니다.");
      return;
    }
    if(typeof showToast === "function") showToast("일정을 " + newStart + "로 이동했습니다.");
    notifyScheduleChanged();
    loadSchedule(true);
  }).catch(function(){
    ev.startDate = oldStart;
    ev.endDate = oldEnd;
    refreshCurrentView();
    if(typeof showToast === "function") showToast("서버 통신 중 오류가 발생했습니다.");
  });
}

function resizeCalendarEvent(eventId, newStart, newEnd){
  var ev = schedEvents.filter(function(x){ return String(x.id) === String(eventId); })[0];
  if(!ev) return;
  if(ev.source === "jira"){
    if(typeof showToast === "function") showToast("Jira 연동 일정은 Jira에서 수정해주세요.");
    return;
  }
  var targetCode = ev.cardCode || (ev.id ? String(ev.id).replace(/^rec-/, "") : null);
  if(ev.source === "local" || ev.cardCode){
    assignTaskToDate(targetCode, newStart, newEnd);
    return;
  }
  if(ev.ownerKey && ev.ownerKey !== myUserKey){
    if(typeof showToast === "function") showToast("본인이 등록한 일정만 수정할 수 있습니다.");
    return;
  }
  var body = {
    id: ev.id,
    title: ev.title,
    type: ev.type,
    startDate: newStart,
    endDate: newEnd,
    memo: ev.memo || "",
    participants: ev.participants || []
  };
  var oldStart = ev.startDate;
  var oldEnd = ev.endDate;
  ev.startDate = newStart;
  ev.endDate = newEnd;
  refreshCurrentView();

  apiSchedulePost("/api/schedule/update", body).then(function(res){
    if(res.status === 401){ handleAuthExpired(); return; }
    if(!res.data.ok){
      ev.startDate = oldStart;
      ev.endDate = oldEnd;
      refreshCurrentView();
      if(typeof showToast === "function") showToast(res.data.error || "일정 기간 변경에 실패했습니다.");
      return;
    }
    if(typeof showToast === "function"){
      var rangeStr = newStart === newEnd ? newStart : (newStart + " ~ " + newEnd);
      showToast("일정 기간을 " + rangeStr + "로 변경했습니다.");
    }
    notifyScheduleChanged();
    loadSchedule(true);
  }).catch(function(){
    ev.startDate = oldStart;
    ev.endDate = oldEnd;
    refreshCurrentView();
    if(typeof showToast === "function") showToast("서버 통신 중 오류가 발생했습니다.");
  });
}

function getDropTargetDayCell(e){
  if(!e) return null;
  var target = e.target;
  var cell = target ? target.closest(".schedule-day") : null;
  if(cell) return cell;

  // Nếu con trỏ chuột nằm trên drawer schedTaskDrawer, tạm thời ẩn để elementFromPoint tìm ra ô ngày bên dưới!
  if(schedTaskDrawer && target && schedTaskDrawer.contains(target)){
    var prevVis = schedTaskDrawer.style.visibility;
    schedTaskDrawer.style.visibility = "hidden";
    var underEl = document.elementFromPoint(e.clientX, e.clientY);
    schedTaskDrawer.style.visibility = prevVis;
    if(underEl){
      cell = underEl.closest(".schedule-day");
    }
  }
  return cell;
}

document.addEventListener("dragstart", function(e){
  if(window._isResizingEvent || e.target.closest(".cal-resizer")){
    e.preventDefault();
    return false;
  }
  var taskCard = e.target.closest(".sched-task-card");
  if(taskCard){
    var taskId = taskCard.getAttribute("data-task-id") || taskCard.getAttribute("data-card-code");
    draggedItemData = {
      type: "task_card",
      taskId: taskId,
      title: taskCard.querySelector(".stc-title") ? taskCard.querySelector(".stc-title").textContent : ""
    };
    e.dataTransfer.setData("text/plain", JSON.stringify(draggedItemData));
    e.dataTransfer.effectAllowed = "move";
    setTimeout(function(){
      taskCard.classList.add("is-dragging");
      if(schedTaskDrawer){
        schedTaskDrawer.classList.add("is-dragging-mode");
      }
    }, 10);
    return;
  }

  var schedChip = e.target.closest(".schedule-chip[data-event-id]");
  if(schedChip){
    var evId = schedChip.getAttribute("data-event-id");
    var found = schedEvents.filter(function(x){ return String(x.id) === String(evId); })[0];
    if(found){
      var cardCode = found.cardCode || (found.source === "local" ? found.id : null);
      var isLocal = found.source === "local" || !!found.cardCode;
      var canDeleteOrUnassign = (isLocal || found.source !== "jira");
      var origStart = parseDateYMD(found.startDate);
      var origEnd = parseDateYMD(found.endDate || found.startDate);
      var dayDiff = Math.round((origEnd - origStart) / (1000 * 60 * 60 * 24));
      draggedItemData = {
        type: "sched_chip",
        eventId: evId,
        recordId: found.recordId || (found.source === "local" ? found.id : null),
        cardCode: cardCode,
        isLocal: isLocal,
        source: found.source,
        title: found.title,
        dayDiff: dayDiff > 0 ? dayDiff : 0
      };
      e.dataTransfer.setData("text/plain", JSON.stringify(draggedItemData));
      e.dataTransfer.effectAllowed = "move";
      schedChip.classList.add("is-dragging");

      // Hiện Khu vực huỷ/gỡ lịch nổi ở đáy màn hình
      var unassignZone = document.getElementById("schedDropUnassignZone");
      if(unassignZone && canDeleteOrUnassign){
        unassignZone.hidden = false;
        setTimeout(function(){ unassignZone.classList.add("is-active"); }, 10);
      }
    }
  }
});

document.addEventListener("dragend", function(e){
  var taskCard = e.target.closest(".sched-task-card");
  if(taskCard) taskCard.classList.remove("is-dragging");
  var schedChip = e.target.closest(".schedule-chip");
  if(schedChip) schedChip.classList.remove("is-dragging");
  if(schedTaskDrawer){
    schedTaskDrawer.classList.remove("is-dragging-mode");
    schedTaskDrawer.classList.remove("cal-drop-unassign-target");
  }
  var unassignZone = document.getElementById("schedDropUnassignZone");
  if(unassignZone){
    unassignZone.classList.remove("is-active");
    unassignZone.classList.remove("is-over");
    setTimeout(function(){
      if(!draggedItemData){
        unassignZone.hidden = true;
      }
    }, 240);
  }
  draggedItemData = null;
  document.querySelectorAll(".cal-drop-target").forEach(function(el){
    el.classList.remove("cal-drop-target");
  });
});

document.addEventListener("dragover", function(e){
  if(!draggedItemData) return;

  var unassignZone = document.getElementById("schedDropUnassignZone");
  var inUnassignZone = unassignZone && unassignZone.contains(e.target);
  var canDropInUnassign = draggedItemData.type === "sched_chip" && (draggedItemData.isLocal || draggedItemData.cardCode || draggedItemData.source !== "jira");

  if(inUnassignZone && canDropInUnassign){
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    unassignZone.classList.add("is-over");
    document.querySelectorAll(".cal-drop-target").forEach(function(el){ el.classList.remove("cal-drop-target"); });
    if(schedTaskDrawer) schedTaskDrawer.classList.remove("cal-drop-unassign-target");
    return;
  }
  if(unassignZone){
    unassignZone.classList.remove("is-over");
  }

  var inDrawer = schedTaskDrawer && schedTaskDrawer.contains(e.target);
  if(inDrawer && canDropInUnassign){
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    schedTaskDrawer.classList.add("cal-drop-unassign-target");
    document.querySelectorAll(".cal-drop-target").forEach(function(el){ el.classList.remove("cal-drop-target"); });
    return;
  }
  if(schedTaskDrawer){
    schedTaskDrawer.classList.remove("cal-drop-unassign-target");
  }

  var cell = getDropTargetDayCell(e);
  if(cell){
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    document.querySelectorAll(".cal-drop-target").forEach(function(el){
      if(el !== cell) el.classList.remove("cal-drop-target");
    });
    cell.classList.add("cal-drop-target");
  } else {
    document.querySelectorAll(".cal-drop-target").forEach(function(el){
      el.classList.remove("cal-drop-target");
    });
  }
});

document.addEventListener("dragleave", function(e){
  var unassignZone = document.getElementById("schedDropUnassignZone");
  if(unassignZone && unassignZone.contains(e.target)){
    var rel = e.relatedTarget;
    if(!unassignZone.contains(rel)){
      unassignZone.classList.remove("is-over");
    }
  }
  var inDrawer = schedTaskDrawer && schedTaskDrawer.contains(e.target);
  if(inDrawer && schedTaskDrawer){
    var relDrawer = e.relatedTarget;
    if(!schedTaskDrawer.contains(relDrawer)){
      schedTaskDrawer.classList.remove("cal-drop-unassign-target");
    }
  }
  var cell = e.target.closest(".schedule-day");
  if(cell){
    var related = e.relatedTarget;
    if(!cell.contains(related)){
      cell.classList.remove("cal-drop-target");
    }
  }
});

document.addEventListener("drop", function(e){
  var unassignZone = document.getElementById("schedDropUnassignZone");
  var droppedInUnassign = unassignZone && unassignZone.contains(e.target);
  if(unassignZone){
    unassignZone.classList.remove("is-active");
    unassignZone.classList.remove("is-over");
    unassignZone.hidden = true;
  }

  var inDrawer = schedTaskDrawer && schedTaskDrawer.contains(e.target);
  var cell = getDropTargetDayCell(e);
  document.querySelectorAll(".cal-drop-target").forEach(function(el){
    el.classList.remove("cal-drop-target");
  });
  if(schedTaskDrawer){
    schedTaskDrawer.classList.remove("is-dragging-mode");
    schedTaskDrawer.classList.remove("cal-drop-unassign-target");
  }

  var rawData = e.dataTransfer.getData("text/plain");
  var data = null;
  try { data = JSON.parse(rawData); } catch(err){ data = draggedItemData; }
  if(!data) return;

  // Thả chip lịch vào Khu vực huỷ/gỡ lịch nổi (Drop to Unassign Zone)
  if(droppedInUnassign && data.type === "sched_chip"){
    e.preventDefault();
    if(data.isLocal || data.cardCode){
      var code = data.cardCode || data.eventId;
      unassignTask(code);
    } else if(data.source !== "jira"){
      deleteCustomScheduleEvent(data.eventId);
    }
    return;
  }

  // Thả chip lịch vào khay 보관함 -> GỠ LỊCH (UNASSIGN) HOẶC XOÁ LỊCH
  if(inDrawer && data.type === "sched_chip"){
    e.preventDefault();
    if(data.isLocal || data.cardCode){
      var code = data.cardCode || data.eventId;
      unassignTask(code);
    } else if(data.source !== "jira"){
      deleteCustomScheduleEvent(data.eventId);
    }
    return;
  }

  if(!cell) return;

  var targetDate = cell.getAttribute("data-date");
  if(!targetDate) return;

  e.preventDefault();

  if(data.type === "task_card"){
    assignTaskToDate(data.taskId, targetDate);
  } else if(data.type === "sched_chip"){
    if(data.isLocal || data.cardCode || data.recordId){
      var newEnd = targetDate;
      if(data.dayDiff && data.dayDiff > 0){
        var nD = parseDateYMD(targetDate);
        nD.setDate(nD.getDate() + data.dayDiff);
        newEnd = formatYMD(nD);
      }
      var targetId = data.recordId || data.cardCode || data.eventId;
      assignTaskToDate(targetId, targetDate, newEnd);
    } else {
      rescheduleCalendarEvent(data.eventId, targetDate);
    }
  }
});

// ── Month View Grid Click & Double Click ──
if(schedGrid){
  schedGrid.addEventListener("click", function(e){
    if(e.target.closest(".cal-resizer")) return;
    var moreLink = e.target.closest(".cal-more-link");
    if(moreLink){
      e.stopPropagation();
      var dStr = moreLink.getAttribute("data-date");
      if(dStr) openDayEventsModal(dStr);
      return;
    }

    var addBtn = e.target.closest(".cal-day-add-btn");
    if(addBtn){
      e.stopPropagation();
      var addDate = addBtn.getAttribute("data-date");
      if(addDate) openSchedEventModal(addDate);
      return;
    }

    var dayCount = e.target.closest(".cal-day-count");
    if(dayCount){
      e.stopPropagation();
      var dStr = dayCount.getAttribute("data-date");
      if(dStr) openDayEventsModal(dStr);
      return;
    }

    var chip = e.target.closest(".schedule-chip[data-event-id]");
    if(chip){
      e.stopPropagation();
      var evId = chip.getAttribute("data-event-id");
      handleEventChipClick(evId);
      return;
    }

    var cell = e.target.closest(".schedule-day");
    if(!cell) return;
    var clickedDate = cell.getAttribute("data-date");
    if(schedSelectedDate === clickedDate){
      openSchedEventModal(clickedDate);
      return;
    }
    schedSelectedDate = clickedDate;
    renderSchedule();
  });

  schedGrid.addEventListener("dblclick", function(e){
    if(e.target.closest(".cal-resizer")) return;
    var chip = e.target.closest(".schedule-chip[data-event-id]");
    if(chip){
      e.stopPropagation();
      var evId = chip.getAttribute("data-event-id");
      var found = schedEvents.filter(function(x){ return String(x.id) === evId; })[0];
      if(found){
        var cardCode = found.cardCode || (found.source === "local" ? found.id : null);
        if(cardCode){
          var range = found.startDate === found.endDate ? found.startDate : (found.startDate + " ~ " + found.endDate);
          openTaskAssignModal(cardCode, found.title, range);
          return;
        }
      }
      return;
    }
    var cell = e.target.closest(".schedule-day");
    if(!cell) return;
    schedSelectedDate = cell.getAttribute("data-date");
    openSchedEventModal(schedSelectedDate);
  });
}

// ── Week View Grid Click & Double Click ──
if(schedWeekGrid){
  schedWeekGrid.addEventListener("click", function(e){
    if(e.target.closest(".cal-resizer")) return;
    var moreLink = e.target.closest(".cal-more-link");
    if(moreLink){
      e.stopPropagation();
      var dStr = moreLink.getAttribute("data-date");
      if(dStr) openDayEventsModal(dStr);
      return;
    }

    var dayCount = e.target.closest(".cal-day-count");
    if(dayCount){
      e.stopPropagation();
      var dStr = dayCount.getAttribute("data-date");
      if(dStr) openDayEventsModal(dStr);
      return;
    }

    var chip = e.target.closest(".schedule-chip[data-event-id]");
    if(chip){
      e.stopPropagation();
      var evId = chip.getAttribute("data-event-id");
      handleEventChipClick(evId);
      return;
    }

    var cell = e.target.closest(".schedule-day");
    if(!cell) return;
    schedSelectedDate = cell.getAttribute("data-date");
    renderWeekView();
  });

  schedWeekGrid.addEventListener("dblclick", function(e){
    if(e.target.closest(".cal-resizer")) return;
    var chip = e.target.closest(".schedule-chip[data-event-id]");
    if(chip){
      e.stopPropagation();
      var evId = chip.getAttribute("data-event-id");
      var found = schedEvents.filter(function(x){ return String(x.id) === evId; })[0];
      if(found){
        var cardCode = found.cardCode || (found.source === "local" ? found.id : null);
        if(cardCode){
          var range = found.startDate === found.endDate ? found.startDate : (found.startDate + " ~ " + found.endDate);
          openTaskAssignModal(cardCode, found.title, range);
          return;
        }
      }
      return;
    }
    var cell = e.target.closest(".schedule-day");
    if(!cell) return;
    schedSelectedDate = cell.getAttribute("data-date");
    openSchedEventModal(schedSelectedDate);
  });
}

// ── Agenda View List Click ──
if(schedAgendaList){
  schedAgendaList.addEventListener("click", function(e){
    var item = e.target.closest(".schedule-chip[data-event-id]");
    if(item){
      var evId = item.getAttribute("data-event-id");
      handleEventChipClick(evId);
    }
  });
}

// ── Day All Events Modal Event Handlers ──
var btnSchedDayEventsClose = document.getElementById("btnSchedDayEventsClose");
if(btnSchedDayEventsClose){
  btnSchedDayEventsClose.addEventListener("click", closeDayEventsModal);
}
var schedDayEventsModalBackdrop = document.getElementById("schedDayEventsModalBackdrop");
if(schedDayEventsModalBackdrop){
  schedDayEventsModalBackdrop.addEventListener("click", function(e){
    if(e.target === schedDayEventsModalBackdrop){
      closeDayEventsModal();
    }
  });
}
var schedDayEventsModalList = document.getElementById("schedDayEventsModalList");
if(schedDayEventsModalList){
  schedDayEventsModalList.addEventListener("click", function(e){
    var item = e.target.closest(".sched-day-modal-item[data-event-id]");
    if(item){
      var evId = item.getAttribute("data-event-id");
      closeDayEventsModal();
      handleEventChipClick(evId);
    }
  });
}

// ── Quick Task Assign Modal Buttons ──
var btnSchedTaskAssignClose = document.getElementById("btnSchedTaskAssignClose");
if(btnSchedTaskAssignClose){
  btnSchedTaskAssignClose.addEventListener("click", closeTaskAssignModal);
}
var btnSchedTaskAssignCancel = document.getElementById("btnSchedTaskAssignCancel");
if(btnSchedTaskAssignCancel){
  btnSchedTaskAssignCancel.addEventListener("click", closeTaskAssignModal);
}
var schedTaskAssignModalBackdrop = document.getElementById("schedTaskAssignModalBackdrop");
if(schedTaskAssignModalBackdrop){
  schedTaskAssignModalBackdrop.addEventListener("click", function(e){
    if(e.target === schedTaskAssignModalBackdrop){
      closeTaskAssignModal();
    }
  });
}
var startInputEl = document.getElementById("schedTaskAssignStartDate");
var endInputEl = document.getElementById("schedTaskAssignEndDate");
if(startInputEl && endInputEl){
  startInputEl.addEventListener("change", function(){
    if(!endInputEl.value || endInputEl.value < startInputEl.value){
      endInputEl.value = startInputEl.value;
    }
  });
}

var schedTaskAssignForm = document.getElementById("schedTaskAssignForm");
if(schedTaskAssignForm){
  schedTaskAssignForm.addEventListener("submit", function(e){
    e.preventDefault();
    var idInput = document.getElementById("schedTaskAssignId");
    var startInput = document.getElementById("schedTaskAssignStartDate");
    var endInput = document.getElementById("schedTaskAssignEndDate");
    if(!idInput || !startInput || !idInput.value || !startInput.value) return;
    var taskId = idInput.value;
    var startDate = startInput.value;
    var endDate = (endInput && endInput.value) ? endInput.value : startDate;
    if(endDate < startDate) endDate = startDate;
    closeTaskAssignModal();
    assignTaskToDate(taskId, startDate, endDate);
  });
}


// ── Quick Event Modal Buttons ──
if(btnSchedOpenCreateModal){
  btnSchedOpenCreateModal.addEventListener("click", function(){
    openSchedEventModal(schedSelectedDate || todayStr());
  });
}
if(btnSchedOpenCreateModalSide){
  btnSchedOpenCreateModalSide.addEventListener("click", function(){
    openSchedEventModal(schedSelectedDate || todayStr());
  });
}

if(schedModalCloseBtn){
  schedModalCloseBtn.addEventListener("click", closeSchedEventModal);
}
if(schedCancelEditBtn){
  schedCancelEditBtn.addEventListener("click", function(){
    closeSchedEventModal();
  });
}
if(schedEventModalBackdrop){
  schedEventModalBackdrop.addEventListener("click", function(e){
    if(e.target === schedEventModalBackdrop){
      closeSchedEventModal();
    }
  });
}
document.addEventListener("keydown", function(e){
  if(e.key === "Escape"){
    if(schedTaskAssignModalBackdrop && !schedTaskAssignModalBackdrop.hidden){
      closeTaskAssignModal();
      return;
    }
    if(schedDayEventsModalBackdrop && !schedDayEventsModalBackdrop.hidden){
      closeDayEventsModal();
      return;
    }
    if(schedEventModalBackdrop && !schedEventModalBackdrop.hidden){
      closeSchedEventModal();
      return;
    }
  }
});

// ── View Switcher Buttons ──
if(schedViewMonthBtn){
  schedViewMonthBtn.addEventListener("click", function(){ switchScheduleView("month"); });
}
if(schedViewWeekBtn){
  schedViewWeekBtn.addEventListener("click", function(){ switchScheduleView("week"); });
}
if(schedViewAgendaBtn){
  schedViewAgendaBtn.addEventListener("click", function(){ switchScheduleView("agenda"); });
}

// Day list click: edit in modal
if(schedDayList){
  schedDayList.addEventListener("click", function(e){
    var item = e.target.closest(".schedule-day-item");
    if(!item || !loggedInUser) return;
    var id = item.getAttribute("data-id");
    handleEventChipClick(id);
  });
}

// ── Navigation Buttons (Prev / Next / Today) ──
if(schedPrevBtn){
  schedPrevBtn.addEventListener("click", function(){
    if(currentViewMode === "week"){
      var d = parseDateYMD(schedSelectedDate || todayStr());
      d.setDate(d.getDate() - 7);
      schedSelectedDate = formatYMD(d);
      schedViewYear = d.getFullYear();
      schedViewMonth = d.getMonth() + 1;
    } else {
      schedViewMonth -= 1;
      if(schedViewMonth < 1){ schedViewMonth = 12; schedViewYear -= 1; }
    }
    refreshCurrentView();
    updateAllCalendarFilters();
  });
}
if(schedNextBtn){
  schedNextBtn.addEventListener("click", function(){
    if(currentViewMode === "week"){
      var d = parseDateYMD(schedSelectedDate || todayStr());
      d.setDate(d.getDate() + 7);
      schedSelectedDate = formatYMD(d);
      schedViewYear = d.getFullYear();
      schedViewMonth = d.getMonth() + 1;
    } else {
      schedViewMonth += 1;
      if(schedViewMonth > 12){ schedViewMonth = 1; schedViewYear += 1; }
    }
    refreshCurrentView();
    updateAllCalendarFilters();
  });
}
if(schedTodayBtn){
  schedTodayBtn.addEventListener("click", function(){
    var now = new Date();
    schedViewYear = now.getFullYear();
    schedViewMonth = now.getMonth() + 1;
    schedSelectedDate = todayStr();
    refreshCurrentView();
    updateAllCalendarFilters();
  });
}

// ── Interactive Legend Filter Toggle ──
if(schedLegend){
  schedLegend.addEventListener("click", function(e){
    var pill = e.target.closest(".sched-legend-pill");
    if(!pill) return;
    var type = pill.getAttribute("data-type");
    if(!type) return;
    if(type === "업무"){
      isTasksGroupEnabled = !isTasksGroupEnabled;
      localStorage.setItem("jarvis_cal_tasks_enabled", isTasksGroupEnabled ? "true" : "false");
    } else if(Object.prototype.hasOwnProperty.call(SCHED_COMPANY_TYPES, type)){
      if(!isCompanyGroupEnabled){
        isCompanyGroupEnabled = true;
        localStorage.setItem("jarvis_cal_company_enabled", "true");
        selectedCompanyTypes = new Set([type]);
      } else {
        if(selectedCompanyTypes.has(type)){
          selectedCompanyTypes.delete(type);
          if(selectedCompanyTypes.size === 0){
            selectedCompanyTypes = new Set(Object.keys(SCHED_COMPANY_TYPES));
          }
        } else {
          selectedCompanyTypes.add(type);
        }
      }
      try{
        localStorage.setItem("jarvis_cal_company_types", JSON.stringify(Array.from(selectedCompanyTypes)));
      }catch(err){}
    }
    updateAllCalendarFilters();
    refreshCurrentView();
  });
}

// ── Modal Form Submit ──
if(schedForm){
  schedForm.addEventListener("submit", function(e){
    e.preventDefault();
    if(!loggedInUser){
      schedFormError.textContent = "먼저 로그인해주세요.";
      return;
    }
    var title = schedTitle.value.trim();
    var startDate = schedDateStart.value;
    var endDate = schedDateEnd.value || startDate;
    if(!title || !startDate){
      schedFormError.textContent = "날짜와 제목을 입력해주세요.";
      return;
    }
    if(endDate < startDate){
      schedFormError.textContent = "종료일이 시작일보다 빠릅니다.";
      return;
    }
    schedFormError.textContent = "";
    var body = {
      type: schedType.value,
      title: title,
      startDate: startDate,
      endDate: endDate,
      memo: schedMemo.value.trim(),
      participants: currentFormParticipants || []
    };
    var editingId = schedEditingId;
    if(editingId) body.id = editingId;
    schedSaveBtn.disabled = true;
    apiSchedulePost(editingId ? "/api/schedule/update" : "/api/schedule", body).then(function(res){
      schedSaveBtn.disabled = false;
      if(res.status === 401){ handleAuthExpired(); return; }
      if(!res.data.ok){
        schedFormError.textContent = res.data.error || "저장에 실패했습니다.";
        return;
      }
      showToast(editingId ? "일정을 수정했습니다." : "일정을 추가했습니다.");
      closeSchedEventModal();
      var sParts = (startDate || "").split("-");
      if(sParts.length >= 2){
        schedViewYear = parseInt(sParts[0], 10);
        schedViewMonth = parseInt(sParts[1], 10);
      }
      schedSelectedDate = startDate;
      notifyScheduleChanged();
      loadSchedule();
    }).catch(function(){
      schedSaveBtn.disabled = false;
      schedFormError.textContent = "서버에 연결할 수 없습니다.";
    });
  });
}

// ── Modal Delete Button ──
if(schedDeleteBtn){
  schedDeleteBtn.addEventListener("click", function(){
    if(!schedEditingId) return;
    var id = schedEditingId;
    if(!confirm("이 일정을 삭제하시겠습니까?")) return;
    apiSchedulePost("/api/schedule/delete", { id: id }).then(function(res){
      if(res.status === 401){ handleAuthExpired(); return; }
      if(!res.data.ok){
        schedFormError.textContent = res.data.error || "삭제에 실패했습니다.";
        return;
      }
      showToast("일정을 삭제했습니다.");
      closeSchedEventModal();
      notifyScheduleChanged();
      loadSchedule();
    }).catch(function(){
      schedFormError.textContent = "서버에 연결할 수 없습니다.";
    });
  });
}

// ── Initial View Setup ──
switchScheduleView(currentViewMode);

// ==========================================================================
// Calendar Event Drag-to-Resize (Kéo co giãn lịch ở 2 đầu)
// ==========================================================================
(function initCalendarEventResize(){
  var activeResize = null;
  window._isResizingEvent = false;
  window._justResizedEvent = false;

  var indicator = document.getElementById("calResizeIndicator");
  if(!indicator){
    indicator = document.createElement("div");
    indicator.id = "calResizeIndicator";
    indicator.className = "cal-resize-indicator";
    indicator.hidden = true;
    document.body.appendChild(indicator);
  }

  function highlightResizeRange(sDate, eDate){
    var s = sDate < eDate ? sDate : eDate;
    var e = sDate < eDate ? eDate : sDate;
    var days = document.querySelectorAll(".schedule-day[data-date]");
    for(var i = 0; i < days.length; i++){
      var d = days[i].getAttribute("data-date");
      if(d && d >= s && d <= e){
        days[i].classList.add("cal-resize-hover");
      } else {
        days[i].classList.remove("cal-resize-hover");
      }
    }
  }

  function clearResizeHighlights(){
    document.querySelectorAll(".cal-resize-hover").forEach(function(el){
      el.classList.remove("cal-resize-hover");
    });
  }

  function getDayCellUnderPointer(x, y){
    // Bounding Box Grid check - 100% robust against overlapping chips/spans!
    var days = document.querySelectorAll(".schedule-day[data-date]");
    for(var i = 0; i < days.length; i++){
      var r = days[i].getBoundingClientRect();
      if(x >= r.left && x <= r.right && y >= r.top && y <= r.bottom){
        return days[i];
      }
    }
    return null;
  }

  function updateResizeIndicator(x, y, sDate, eDate){
    if(!indicator) return;
    var text = sDate === eDate ? sDate : (sDate + " ~ " + eDate);
    var dayDiff = 1;
    try {
      var d1 = parseDateYMD(sDate);
      var d2 = parseDateYMD(eDate);
      dayDiff = Math.round((d2 - d1) / (1000 * 60 * 60 * 24)) + 1;
    } catch(err){}

    var badgeText = dayDiff > 1 ? (dayDiff + "일간") : "하루";
    indicator.innerHTML = '<span style="color:#38bdf8;margin-right:6px;font-weight:700;">' + badgeText + '</span> ' + escapeHtml(text);
    indicator.style.left = (x) + "px";
    indicator.style.top = (y - 32) + "px";
    indicator.hidden = false;
    indicator.style.display = "block";
  }

  function onStart(e){
    if(e.button !== 0) return; // Chỉ chuột trái
    if(activeResize) return;

    var resizer = e.target.closest && e.target.closest(".cal-resizer");
    if(!resizer) return;

    var chip = resizer.closest(".schedule-chip[data-event-id]");
    if(!chip) return;

    var evId = chip.getAttribute("data-event-id");
    var found = schedEvents.filter(function(x){ return String(x.id) === String(evId); })[0];
    var edge = resizer.getAttribute("data-edge"); // "start" or "end"
    if(!edge) return;

    e.preventDefault();
    e.stopPropagation();

    window._isResizingEvent = true;
    chip.draggable = false;
    chip.removeAttribute("draggable");

    var cardCode = (found && found.cardCode) ? found.cardCode : (found && found.source === "local" ? String(found.id || "").replace(/^rec-/, "") : String(evId || "").replace(/^rec-/, ""));
    var origStart = (found && found.startDate) ? found.startDate : (chip.closest(".schedule-day") ? chip.closest(".schedule-day").getAttribute("data-date") : todayStr());
    var origEnd = (found && found.endDate) ? found.endDate : origStart;

    activeResize = {
      eventId: evId,
      cardCode: cardCode,
      edge: edge,
      origStart: origStart,
      origEnd: origEnd,
      currentStart: origStart,
      currentEnd: origEnd,
      chipEl: chip,
      resizerEl: resizer
    };

    chip.classList.add("is-resizing");
    resizer.classList.add("is-active");
    document.body.style.userSelect = "none";
    document.body.style.cursor = "ew-resize";

    highlightResizeRange(origStart, origEnd);
    updateResizeIndicator(e.clientX, e.clientY, origStart, origEnd);
  }

  function onMove(e){
    if(!activeResize) return;
    e.preventDefault();

    var cell = getDayCellUnderPointer(e.clientX, e.clientY);
    if(cell){
      var hoveredDate = cell.getAttribute("data-date");
      if(hoveredDate && isValidDateStr(hoveredDate)){
        if(activeResize.edge === "start"){
          // Clamping: start date cannot exceed origEnd
          if(hoveredDate > activeResize.origEnd){
            activeResize.currentStart = activeResize.origEnd;
          } else {
            activeResize.currentStart = hoveredDate;
          }
          activeResize.currentEnd = activeResize.origEnd;
        } else {
          // Clamping: end date cannot precede origStart
          if(hoveredDate < activeResize.origStart){
            activeResize.currentEnd = activeResize.origStart;
          } else {
            activeResize.currentEnd = hoveredDate;
          }
          activeResize.currentStart = activeResize.origStart;
        }
        highlightResizeRange(activeResize.currentStart, activeResize.currentEnd);
      }
    }

    updateResizeIndicator(e.clientX, e.clientY, activeResize.currentStart, activeResize.currentEnd);
  }

  function onEnd(e){
    if(!activeResize) return;

    var resizeData = activeResize;
    activeResize = null;
    window._isResizingEvent = false;
    window._justResizedEvent = true;
    setTimeout(function(){ window._justResizedEvent = false; }, 250);

    document.body.style.userSelect = "";
    document.body.style.cursor = "";

    if(resizeData.chipEl){
      resizeData.chipEl.classList.remove("is-resizing");
      resizeData.chipEl.draggable = true;
      resizeData.chipEl.setAttribute("draggable", "true");
    }
    if(resizeData.resizerEl) resizeData.resizerEl.classList.remove("is-active");
    clearResizeHighlights();
    if(indicator){
      indicator.hidden = true;
      indicator.style.display = "none";
    }

    var changed = (resizeData.currentStart !== resizeData.origStart) || (resizeData.currentEnd !== resizeData.origEnd);
    if(!changed) return;

    resizeCalendarEvent(resizeData.eventId, resizeData.currentStart, resizeData.currentEnd);
  }

  document.addEventListener("pointerdown", onStart, true);
  document.addEventListener("mousedown", onStart, true);
  window.addEventListener("pointermove", onMove, true);
  window.addEventListener("mousemove", onMove, true);
  window.addEventListener("pointerup", onEnd, true);
  window.addEventListener("mouseup", onEnd, true);

  // Chặn sự kiện click sau khi vừa kéo co giãn xong để không bị kích hoạt mở modal/canvas
  window.addEventListener("click", function(e){
    if(window._justResizedEvent){
      e.preventDefault();
      e.stopPropagation();
      e.stopImmediatePropagation();
      return false;
    }
  }, true);
})();



// Re-render calendar UI dynamically whenever user toggles language (KO / EN)
window.addEventListener("langchange", function(){
  renderCompanyTypeList();
  renderTaskFilterGroup();
  renderMembersList();
  renderLocalTaskDrawer();
  refreshCurrentView();
});

// ── Keyboard Shortcut: 'C' to Quick-Create Event ──
document.addEventListener("keydown", function(e){
  if((e.key === "c" || e.key === "C") && !e.ctrlKey && !e.altKey && !e.metaKey){
    var activeEl = document.activeElement;
    if(activeEl && (activeEl.tagName === "INPUT" || activeEl.tagName === "TEXTAREA" || activeEl.tagName === "SELECT" || activeEl.isContentEditable)) return;
    var viewSched = document.getElementById("viewSchedule");
    if(viewSched && !viewSched.hidden){
      e.preventDefault();
      openSchedEventModal(schedSelectedDate || todayStr());
    }
  }
});

// ── Global Exports for Realtime Synchronization (SSE & Cross-Tab) ──
window.loadSchedule = loadSchedule;
window.notifyScheduleChanged = notifyScheduleChanged;

var btnSchedSidebarSettings = document.getElementById("btnSchedSidebarSettings");
if(btnSchedSidebarSettings){
  btnSchedSidebarSettings.addEventListener("click", function(){
    var settingsTab = document.getElementById("tabBtnSettings");
    if(settingsTab) settingsTab.click();
  });
}


var schedSubCompanyCb = document.getElementById("schedSubCompanyCb");
var schedSubLeaveCb = document.getElementById("schedSubLeaveCb");
var schedMyCalDefaultCb = document.getElementById("schedMyCalDefaultCb");

if(schedSubCompanyCb){
  schedSubCompanyCb.addEventListener("change", function(e){
    var companyTypes = ["회의", "출장", "기타"];
    if(e.target.checked){
      companyTypes.forEach(function(t){ selectedCompanyTypes.add(t); });
    } else {
      companyTypes.forEach(function(t){ selectedCompanyTypes.delete(t); });
    }
    refreshCurrentView();
  });
}

if(schedSubLeaveCb){
  schedSubLeaveCb.addEventListener("change", function(e){
    var leaveTypes = ["연차", "반차", "병가", "재택"];
    if(e.target.checked){
      leaveTypes.forEach(function(t){ selectedCompanyTypes.add(t); });
    } else {
      leaveTypes.forEach(function(t){ selectedCompanyTypes.delete(t); });
    }
    refreshCurrentView();
  });
}

if(schedMyCalDefaultCb){
  schedMyCalDefaultCb.addEventListener("change", function(e){
    if(!myUserKey) return;
    if(e.target.checked){
      selectedMemberKeys.add(myUserKey);
    } else {
      selectedMemberKeys.delete(myUserKey);
    }
    renderMembersList();
    refreshCurrentView();
  });
}
