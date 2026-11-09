// utils.js
var records = [];
var DEPARTMENTS = [];
var RECENT_LIMIT = 50;
var viewMode = "recent"; // "recent" | "all"
var filters = { org: "all", cat: "all", q: "", assignee: "all", status: "all" };

var el = {
  home: document.getElementById("viewHome"),
  dash: document.getElementById("viewDash"),
  form: document.getElementById("viewForm"),
  schedule: document.getElementById("viewSchedule"),
  pim: document.getElementById("viewPim"),
  history: document.getElementById("viewHistory"),
  settings: document.getElementById("viewSettings"),
  chat: document.getElementById("sectionChat"),
  tabHome: document.getElementById("tabBtnHome"),
  tabDash: document.getElementById("tabBtnDash"),
  tabForm: document.getElementById("tabBtnForm"),
  tabSchedule: document.getElementById("tabBtnSchedule"),
  tabPim: document.getElementById("tabBtnPim"),
  tabHistory: document.getElementById("tabBtnHistory"),
  tabSettings: document.getElementById("tabBtnSettings"),
  tabChat: document.getElementById("tabBtnChat"),
  navTabsAdmin: document.getElementById("navTabsAdmin"),
  brand: document.getElementById("brandLogo"),
  deptCards: document.getElementById("deptCards"),
  assigneePanel: document.getElementById("assigneePanel"),
  assigneeBar: document.getElementById("assigneeBar"),
  assigneeTableWrap: document.getElementById("assigneeTableWrap"),
  btnToggleAssigneeView: document.getElementById("btnToggleAssigneeView"),
  assigneeCountBadge: document.getElementById("assigneeCountBadge"),
  assigneeBody: document.getElementById("assigneeTableBody"),
  list: document.getElementById("recordList"),
  empty: document.getElementById("emptyState"),
  orgChips: document.getElementById("orgChips"),
  assigneeFilter: document.getElementById("assigneeFilter"),
  filterRow: document.getElementById("filterRow"),
  catFilter: document.getElementById("catFilter"),
  dashViewMode: document.getElementById("dashViewMode"),
  statusFilter: document.getElementById("statusFilter"),
  btnCreateIssue: document.getElementById("btnCreateIssue"),
  search: document.getElementById("searchInput"),
  toast: document.getElementById("toast"),
  recordsWrap: document.getElementById("recordsWrap"),
  recordsHeader: document.getElementById("recordsHeader"),
  recordsLabel: document.getElementById("recordsLabel"),
  recordsCaption: document.getElementById("recordsCaption"),
  viewToggleBtn: document.getElementById("viewToggleBtn"),
  btnToggleTree: document.getElementById("btnToggleTree"),
  syncBtn: document.getElementById("syncBtn"),
  syncCaption: document.getElementById("syncCaption")
};

// ---- Role helpers (dung chung cho moi module UI) ----
function getSessionRole(){
  var u = null;
  try {
    if (typeof window.getCurrentUser === "function") u = window.getCurrentUser();
    if (!u) {
      var raw = sessionStorage.getItem("argosUser") || localStorage.getItem("argosUser");
      if (raw) u = JSON.parse(raw);
    }
  } catch(e){}
  if (!u) return "";
  if (u.role) return u.role;
  if (u.isAdmin || u.is_admin) return "admin";
  if (u.isManager) return "manager";
  return "member";
}

function isViewerUser(){
  return getSessionRole() === "viewer";
}

function canModifyPimUser(){
  var role = getSessionRole();
  if (role === "admin" || role === "manager") return true;
  if (typeof window.isCurrentUserManagerOrAdmin === "function") {
    return window.isCurrentUserManagerOrAdmin();
  }
  return false;
}

window.getSessionRole = getSessionRole;
window.isViewerUser = isViewerUser;
window.canModifyPimUser = canModifyPimUser;

var CATEGORIES_BY_DEPT = {};
var selectedFiles = [];
var deptAddOpen = false;
var toastTimer;

var loggedInUser = null;
var loginStage = "identify"; // "identify" | "password"
var pendingAccount = null;   // {name, org, email, exists}

var schedEvents = [];
var schedJiraOngoingItems = [];
var schedViewYear, schedViewMonth;
var schedSelectedDate = null;
var schedEditingId = null;

var pimProducts = [];
var pimSearchDebounce = null;
var pimCategories = ["일반"];
var pimSpecTemplates = { "일반": [] };

function escapeHtml(s){
  if(s === null || s === undefined) return "";
  return String(s).replace(/[&<>"']/g, function(c){
    return ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c];
  });
}

function trapFocus(modalEl) {
  if (!modalEl) return function(){};
  var focusableSelectors = 'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

  function handleKeyDown(e) {
    if (e.key !== "Tab" || modalEl.hidden) return;
    var focusable = Array.from(modalEl.querySelectorAll(focusableSelectors)).filter(function(el) {
      return el.offsetWidth > 0 || el.offsetHeight > 0 || el === document.activeElement;
    });
    if (focusable.length === 0) return;
    var firstEl = focusable[0];
    var lastEl = focusable[focusable.length - 1];

    if (e.shiftKey) {
      if (document.activeElement === firstEl) {
        lastEl.focus();
        e.preventDefault();
      }
    } else {
      if (document.activeElement === lastEl) {
        firstEl.focus();
        e.preventDefault();
      }
    }
  }

  document.addEventListener("keydown", handleKeyDown);
  return function releaseFocusTrap() {
    document.removeEventListener("keydown", handleKeyDown);
  };
}
window.trapFocus = trapFocus;

function colorVar(colorIndex){ return "var(--dept-color-" + (((colorIndex - 1) % 6) + 1) + ")"; }

function deptById(id){
  for(var i=0;i<DEPARTMENTS.length;i++){ if(DEPARTMENTS[i].id === id) return DEPARTMENTS[i]; }
  return { id: id, name: id, colorIndex: 1 };
}
function orgLabel(o){ return deptById(o).name; }

function showToast(msg, duration, isError){
  if(!el.toast) el.toast = document.getElementById("toast");
  if(!el.toast) return;
  el.toast.textContent = msg;
  if(isError){
    el.toast.classList.add("toast-error");
  } else {
    el.toast.classList.remove("toast-error");
  }
  el.toast.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(function(){
    if(el.toast){
      el.toast.classList.remove("show");
      el.toast.classList.remove("toast-error");
    }
  }, duration || 3200);
}

window.updatePrioritySelectColor = function(selectEl){
  if(!selectEl) return;
  var isDark = document.documentElement.getAttribute("data-theme") === "dark" ||
    (!document.documentElement.getAttribute("data-theme") && window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches);
  var colors = isDark ? {
    "낮음": "#4ade80",
    "보통": "#facc15",
    "높음": "#fb923c",
    "긴급": "#f87171"
  } : {
    "낮음": "#16a34a",
    "보통": "#ca8a04",
    "높음": "#ea580c",
    "긴급": "#dc2626"
  };
  var val = (selectEl.value || "보통").trim();
  selectEl.style.color = colors[val] || (isDark ? "#facc15" : "#ca8a04");
  selectEl.style.fontWeight = "600";
};

/**
 * Render structured, beautiful product specifications without raw ' > ' or raw '|' pipes.
 * Groups hierarchical specs into cards with icons and pill badges.
 */

/**
 * Render clean, professional HTML tables for product specifications,
 * matching official manufacturer/web catalog tables.
 * Zero emojis, no raw ' > ' signs, clean group rows with colspan="2".
 */
function renderStructuredSpecsHtml(specs, specMatrix) {
  // 1. Multi-column variant matrix table (e.g. models lineup)
  if (specMatrix && specMatrix.headers && specMatrix.rows && specMatrix.rows.length > 0) {
    var ths = specMatrix.headers.map(function(h) {
      return '<th>' + escapeHtml(h) + '</th>';
    }).join("");
    var trs = specMatrix.rows.map(function(r) {
      var tds = specMatrix.headers.map(function(h) {
        var val = r[h] || "-";
        return '<td style="text-align:center;">' + escapeHtml(val) + '</td>';
      }).join("");
      return '<tr>' + tds + '</tr>';
    }).join("");

    return '<div class="pim-modal-specs-table-wrap">' +
      '<h4 class="pim-specs-table-title">제품 세부 규격 (총 ' + specMatrix.rows.length + '개 모델)</h4>' +
      '<div class="pim-specs-table-responsive">' +
        '<table class="pim-specs-table">' +
          '<thead><tr>' + ths + '</tr></thead>' +
          '<tbody>' + trs + '</tbody>' +
        '</table>' +
      '</div>' +
    '</div>';
  }

  // 2. Standard 2-column specifications table (Key - Value) with clean group headers
  if (specs && typeof specs === "object" && Object.keys(specs).length > 0) {
    var groups = {};
    var groupOrder = [];

    Object.keys(specs).forEach(function(rawKey) {
      var val = specs[rawKey];
      if (val == null || String(val).trim() === "") return;

      var groupName = "";
      var fieldLabel = rawKey;

      if (rawKey.indexOf(" > ") !== -1) {
        var parts = rawKey.split(" > ");
        groupName = parts[0].trim();
        fieldLabel = parts.slice(1).join(" > ").trim();
      }

      if (!groups[groupName]) {
        groups[groupName] = [];
        groupOrder.push(groupName);
      }
      groups[groupName].push({
        label: fieldLabel,
        value: String(val).trim()
      });
    });

    if (groupOrder.length === 0) {
      return '<div class="pim-modal-specs-table-wrap">' +
        '<h4 class="pim-specs-table-title">제품 세부 규격</h4>' +
        '<p class="pim-spec-empty-msg">등록된 세부 규격 사양이 없습니다.</p>' +
      '</div>';
    }

    var html = '<div class="pim-modal-specs-table-wrap">' +
      '<h4 class="pim-specs-table-title">제품 세부 규격 사양</h4>' +
      '<div class="pim-specs-table-responsive">' +
        '<table class="pim-specs-table">' +
          '<tbody>';

    groupOrder.forEach(function(gName) {
      var items = groups[gName];

      // If group has a name (e.g. "전원 사양", "외형 치수"), output a clean section row spanning both columns
      if (gName) {
        html += '<tr class="pim-spec-group-row">' +
          '<th colspan="2">' + escapeHtml(gName) + '</th>' +
        '</tr>';
      }

      items.forEach(function(it) {
        var valText = it.value;
        var formattedVal = escapeHtml(valText);

        // If value has pipe-separated pairs like "출력: 30W | 규격: 100mm", format cleanly with line breaks
        if (valText.indexOf(" | ") !== -1 || valText.indexOf("|") !== -1) {
          var bits = valText.split("|").map(function(b) { return b.trim(); }).filter(Boolean);
          if (bits.length > 1) {
            formattedVal = bits.map(function(b) {
              return escapeHtml(b);
            }).join("<br>");
          }
        }

        html += '<tr>' +
          '<th class="pim-spec-key">' + escapeHtml(it.label) + '</th>' +
          '<td class="pim-spec-val">' + formattedVal + '</td>' +
        '</tr>';
      });
    });

    html += '</tbody></table></div></div>';
    return html;
  }

  // 3. Fallback when no specs
  return '<div class="pim-modal-specs-table-wrap">' +
    '<h4 class="pim-specs-table-title">제품 세부 규격</h4>' +
    '<p class="pim-spec-empty-msg">제공된 세부 규격 사양표가 없습니다. 카탈로그 PDF를 다운로드하여 확인하세요.</p>' +
  '</div>';
}
window.renderStructuredSpecsHtml = renderStructuredSpecsHtml;
