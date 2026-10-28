// history.js — Work History & Daily Activity Explorer for Admin (JARVIS)
// =========================================================================

function getLocalTodayIso() {
  var d = new Date();
  var yyyy = d.getFullYear();
  var mm = String(d.getMonth() + 1).padStart(2, "0");
  var dd = String(d.getDate()).padStart(2, "0");
  return yyyy + "-" + mm + "-" + dd;
}

var historyActivities = [];
var historyRecentDates = [];
var selectedHistoryDate = getLocalTodayIso();
var historyListenersBound = false;

function formatHistoryTime(timeStr) {
  if (!timeStr) return "--:--";
  try {
    var parts = String(timeStr).trim().split(" ");
    if (parts.length >= 2 && parts[1].includes(":")) {
      var t = parts[1].split(":");
      return t[0] + ":" + t[1];
    }
    if (timeStr.includes("T")) {
      var timePart = timeStr.split("T")[1];
      if (timePart) {
        var t2 = timePart.split(":");
        if (t2.length >= 2) return t2[0] + ":" + t2[1];
      }
    }
    var d = new Date(timeStr);
    if (!isNaN(d.getTime())) {
      var hh = String(d.getHours()).padStart(2, "0");
      var mm = String(d.getMinutes()).padStart(2, "0");
      return hh + ":" + mm;
    }
  } catch (e) {}
  return timeStr;
}

function getHistStatusClass(st) {
  if (!st) return "todo";
  var s = String(st).toLowerCase();
  if (s.includes("완료") || s.includes("done") || s.includes("good")) return "done";
  if (s.includes("진행") || s.includes("progress") || s.includes("info")) return "inprog";
  return "todo";
}

function formatHistActionDetail(actionType, rawDetail) {
  if (!rawDetail && actionType !== "created" && actionType !== "status_change") return "";

  if (actionType === "created") {
    if (!rawDetail || rawDetail === "새 작업 생성" || rawDetail === "Tạo thẻ mới") return "";
    return escapeHtml(rawDetail);
  }

  if (actionType === "status_change" || actionType === "STATUS_CHANGE") {
    var parts = (rawDetail || "").split("➔").map(function(s){ return s.trim(); });
    if (parts.length === 2) {
      var oldSt = parts[0];
      var newSt = parts[1];
      var oldCls = getHistStatusClass(oldSt);
      var newCls = getHistStatusClass(newSt);
      return '<span class="act-status-flow">' +
        '<span class="hist-status-pill hist-status-' + oldCls + '">' + escapeHtml(oldSt) + '</span>' +
        '<span class="act-status-arrow">➔</span>' +
        '<span class="hist-status-pill hist-status-' + newCls + '">' + escapeHtml(newSt) + '</span>' +
        '</span>';
    }
    return '<span style="font-weight:600; margin-left:6px;">' + escapeHtml(rawDetail) + '</span>';
  }

  if (actionType === "comment" || actionType === "COMMENT_ADDED") {
    return '<span style="font-style:italic; margin-left:6px; opacity:0.9;">"' + escapeHtml(rawDetail) + '"</span>';
  }

  if (actionType === "attachment" || actionType === "attachment_deleted") {
    var isDel = actionType === "attachment_deleted";
    var lines = (rawDetail || "").split("\n").filter(Boolean);
    if (lines.length === 1) {
      return '<span style="display:inline-flex; align-items:center; gap:5px; margin-left:6px; font-weight:600;' + (isDel ? ' text-decoration:line-through; opacity:0.8;' : '') + '">' +
        '<span>' + (isDel ? '🗑️' : '📎') + '</span>' +
        '<span>' + escapeHtml(lines[0]) + '</span>' +
        '</span>';
    } else if (lines.length > 1) {
      return '<div style="display:flex; flex-direction:column; gap:3px; margin-top:4px; margin-left:4px;">' +
        lines.map(function(f){
          return '<span style="display:inline-flex; align-items:center; gap:5px; font-size:12px;' + (isDel ? ' text-decoration:line-through; opacity:0.8;' : '') + '">' +
            '<span>' + (isDel ? '🗑️' : '📎') + '</span><span>' + escapeHtml(f) + '</span></span>';
        }).join('') +
        '</div>';
    }
  }

  if (actionType === "updated") {
    return '<span style="margin-left:6px; font-weight:600;">' + escapeHtml(rawDetail) + '</span>';
  }

  return '<span style="margin-left:6px;">' + escapeHtml(rawDetail) + '</span>';
}

function renderHistActionBadge(actionType, actionDetail, act) {
  var label = "작업 수정";
  var badgeClass = actionType || "updated";

  if (actionType === "created") {
    label = "새 작업 생성";
    badgeClass = "created";
  } else if (actionType === "status_change" || actionType === "STATUS_CHANGE") {
    label = "상태 변경";
    badgeClass = "status_change";
  } else if (actionType === "comment" || actionType === "COMMENT_ADDED") {
    label = "새 댓글";
    badgeClass = "comment";
  } else if (actionType === "attachment") {
    label = "파일 첨부";
    badgeClass = "attachment";
  } else if (actionType === "attachment_deleted") {
    label = "파일 삭제";
    badgeClass = "attachment_deleted";
  } else if (actionType === "schedule_update" || actionType === "schedule") {
    label = "일정 변경";
    badgeClass = "schedule";
  }

  var isMultiFile = (actionType === "attachment" || actionType === "attachment_deleted") &&
                    ((act && act.files && act.files.length > 1) || (actionDetail && actionDetail.indexOf("\n") !== -1));

  var detailHtml = formatHistActionDetail(actionType, actionDetail);

  if (isMultiFile) {
    var fileCount = (act && act.files && act.files.length) ? act.files.length : actionDetail.split("\n").filter(Boolean).length;
    return '<div style="display:flex; flex-direction:column; align-items:flex-start; gap:2px; padding:2px 0;">' +
      '<div style="display:inline-flex; align-items:center; gap:6px;">' +
        '<span class="act-badge act-badge-' + escapeHtml(badgeClass) + '">' + escapeHtml(label) + '</span>' +
        '<span style="font-size:11px; font-weight:700; color:var(--ink-soft); background:var(--code-bg); padding:1px 7px; border-radius:10px; border:1px solid var(--line);">' +
          fileCount +
        '</span>' +
      '</div>' +
      detailHtml +
    '</div>';
  }

  return '<div style="display:inline-flex; align-items:center; flex-wrap:wrap; gap:4px;">' +
    '<span class="act-badge act-badge-' + escapeHtml(badgeClass) + '">' + escapeHtml(label) + '</span>' +
    detailHtml +
    '</div>';
}

function groupHistoryActivities(activities) {
  if (!Array.isArray(activities)) return [];
  var grouped = [];
  var attachGroupMap = {};

  activities.forEach(function(act) {
    if (act.action_type === "attachment" || act.action_type === "attachment_deleted") {
      var created = act.created_at || "";
      var minuteTime = created.length >= 16 ? created.substring(0, 16) : created;
      var groupKey = (act.issue_key || "") + "_" + act.action_type + "_" + (act.author_name || "") + "_" + minuteTime;

      if (attachGroupMap[groupKey]) {
        var groupAct = attachGroupMap[groupKey];
        if (!groupAct.files) {
          groupAct.files = (groupAct.action_detail || "").split("\n").filter(Boolean);
        }
        var currFile = act.action_detail || "";
        currFile.split("\n").forEach(function(f) {
          var trimmed = f.trim();
          if (trimmed && groupAct.files.indexOf(trimmed) === -1) {
            groupAct.files.push(trimmed);
          }
        });
        groupAct.action_detail = groupAct.files.join("\n");
      } else {
        var copy = Object.assign({}, act);
        copy.files = (act.files && act.files.length > 0)
          ? act.files.slice()
          : (copy.action_detail ? copy.action_detail.split("\n").filter(Boolean) : []);
        attachGroupMap[groupKey] = copy;
        grouped.push(copy);
      }
    } else {
      grouped.push(act);
    }
  });

  return grouped;
}

function renderHistoryTable() {
  var container = document.getElementById("historyContent");
  var subtitleEl = document.getElementById("historySubtitleCounter");
  if (!container) return;

  var filtered = historyActivities || [];

  var isEn = (window.i18n && window.i18n.getLang && window.i18n.getLang() === "en");
  if (subtitleEl) {
    subtitleEl.textContent = (window.i18n && window.i18n.t)
      ? window.i18n.t("history.subtitle", { date: selectedHistoryDate, count: filtered.length })
      : (isEn ? (selectedHistoryDate + " • Total " + filtered.length + " activities") : (selectedHistoryDate + " • 총 " + filtered.length + "건의 활동"));
  }

  if (filtered.length === 0) {
    var quickDatesHtml = "";
    var qLabel = (window.i18n && window.i18n.t) ? window.i18n.t("history.quick_label") : (isEn ? "Jump to recent activity date:" : "최근 활동이 기록된 날짜 바로가기:");
    if (historyRecentDates && historyRecentDates.length > 0) {
      quickDatesHtml = '<div style="margin-top:18px; display:flex; flex-direction:column; align-items:center; gap:10px;">' +
        '<div style="font-size:12.5px; font-weight:600; color:var(--ink-soft);">' + qLabel + '</div>' +
        '<div style="display:flex; flex-wrap:wrap; gap:8px; justify-content:center; max-width:600px;">' +
        historyRecentDates.map(function(item){
          return '<button type="button" class="history-quick-date-btn" onclick="loadHistoryActivities(\'' + item.date + '\')">' +
            '📅 ' + item.date + ' <strong style="margin-left:4px; color:var(--tab-settings, #0284c7);">' + item.count + (isEn ? " items" : "건") + '</strong>' +
            '</button>';
        }).join('') +
        '</div></div>';
    }

    var emptyTitle = (window.i18n && window.i18n.t)
      ? window.i18n.t("history.empty_title", { date: escapeHtml(selectedHistoryDate) })
      : (isEn ? ("No activity recorded for " + escapeHtml(selectedHistoryDate) + ".") : ("선택한 날짜(" + escapeHtml(selectedHistoryDate) + ")에 활동 내역이 없습니다."));
    var emptyDesc = (window.i18n && window.i18n.t)
      ? window.i18n.t("history.empty_desc")
      : (isEn ? "Use the arrows (< >) above to choose another date, or select a recent date below." : "상단 화살표(&lt; &gt;)로 다른 날짜를 선택하거나 아래 최근 기록일을 클릭해 보세요.");

    container.innerHTML = '<div class="history-empty">' +
      '<div class="history-empty-icon">📂</div>' +
      '<div class="history-empty-title">' + emptyTitle + '</div>' +
      '<div class="history-empty-desc">' + emptyDesc + '</div>' +
      quickDatesHtml +
      '</div>';
    return;
  }

  var thKey = isEn ? "Issue Key" : "이슈 키";
  var thTitle = isEn ? "Issue / Task Title" : "이슈 / 업무명";
  var thDetails = isEn ? "Activity & Changes" : "활동 및 변경 상세";
  var thAuthor = isEn ? "Author" : "작업자";
  var thTime = isEn ? "Time" : "시간";

  var html = '<div class="history-table-card">' +
    '<table class="history-table">' +
    '<thead><tr>' +
    '<th style="width:110px;">' + thKey + '</th>' +
    '<th style="width:28%;">' + thTitle + '</th>' +
    '<th>' + thDetails + '</th>' +
    '<th style="width:150px;">' + thAuthor + '</th>' +
    '<th style="width:85px; text-align:right;">' + thTime + '</th>' +
    '</tr></thead><tbody>';

  filtered.forEach(function(act) {
    var timeStr = formatHistoryTime(act.created_at);
    var author = act.author_name || "시스템";
    var authorInitial = (author.charAt(0) || "U").toUpperCase();
    var statusCls = getHistStatusClass(act.status);

    var avatarHtml = '';
    if (act.author_avatar) {
      avatarHtml = '<div class="hist-avatar"><img src="' + escapeHtml(act.author_avatar) + '" alt="' + escapeHtml(author) + '"></div>';
    } else {
      avatarHtml = '<div class="hist-avatar">' + escapeHtml(authorInitial) + '</div>';
    }

    var keyHtml = '<span class="hist-key">' + escapeHtml(act.issue_key || "-") + '</span>';

    html += '<tr class="hist-row">' +
      '<td class="hist-col-key">' + keyHtml + '</td>' +
      '<td class="hist-col-summary">' +
        '<div class="hist-summary-wrap">' +
          '<div class="hist-summary-title">' + escapeHtml(act.summary || act.issue_key || "-") + '</div>' +
          '<div class="hist-summary-meta">' +
            '<span class="hist-status-pill hist-status-' + statusCls + '">' + escapeHtml(act.status || "진행") + '</span>' +
            (act.issue_type ? '<span>• ' + escapeHtml(act.issue_type) + '</span>' : '') +
          '</div>' +
        '</div>' +
      '</td>' +
      '<td class="hist-col-action">' + renderHistActionBadge(act.action_type, act.action_detail, act) + '</td>' +
      '<td class="hist-col-author">' +
        '<div class="hist-author">' +
          avatarHtml +
          '<div>' +
            '<div class="hist-author-name">' + escapeHtml(author) + '</div>' +
            (act.assignee_dept ? '<div class="hist-author-dept">' + escapeHtml(act.assignee_dept) + '</div>' : '') +
          '</div>' +
        '</div>' +
      '</td>' +
      '<td class="hist-time hist-col-time" title="' + escapeHtml(act.created_at || "") + '">' + escapeHtml(timeStr) + '</td>' +
      '</tr>';
  });

  html += '</tbody></table></div>';
  container.innerHTML = html;
}

function loadHistoryActivities(targetDate) {
  if (targetDate) selectedHistoryDate = targetDate;
  var dateInput = document.getElementById("historyDateFilter");
  if (dateInput && dateInput.value !== selectedHistoryDate) {
    dateInput.value = selectedHistoryDate;
  }

  var subtitleEl = document.getElementById("historySubtitleCounter");
  if (subtitleEl) {
    subtitleEl.textContent = selectedHistoryDate;
  }

  var container = document.getElementById("historyContent");
  if (container) {
    container.innerHTML = '<div style="padding:40px; text-align:center; color:var(--ink-soft);"><span class="loading-spinner"></span> ' +
      selectedHistoryDate + ' 업무 활동 내역을 불러오는 중입니다...</div>';
  }

  apiGet("/api/activities?date=" + encodeURIComponent(selectedHistoryDate))
    .then(function(res) {
      if (res && res.ok) {
        historyActivities = groupHistoryActivities(res.activities || []);
        historyRecentDates = res.recentDates || [];
        renderHistoryTable();
      } else {
        if (container) {
          var errorMsg = res && res.error ? res.error : "서버 오류";
          var reLoginHtml = "";
          if (res && res.authRequired) {
            reLoginHtml = '<div style="margin-top:14px;"><button type="button" class="btn-login" style="display:inline-flex;" onclick="window.location.href=\'/login\'">🔑 다시 로그인하기</button></div>';
          }
          container.innerHTML = '<div class="history-empty" style="color:var(--stat-critical);">' +
            '<div class="history-empty-title">데이터를 불러오지 못했습니다.</div>' +
            '<div class="history-empty-desc">' + escapeHtml(errorMsg) + '</div>' +
            reLoginHtml +
            '</div>';
        }
      }
    })
    .catch(function(err) {
      if (container) {
        container.innerHTML = '<div class="history-empty" style="color:var(--stat-critical);">' +
          '<div class="history-empty-title">네트워크 오류</div>' +
          '<div class="history-empty-desc">' + escapeHtml(err.message || String(err)) + '</div></div>';
      }
    });
}

function shiftHistoryDate(daysDelta) {
  try {
    var cur = new Date(selectedHistoryDate + "T00:00:00");
    cur.setDate(cur.getDate() + daysDelta);
    var yyyy = cur.getFullYear();
    var mm = String(cur.getMonth() + 1).padStart(2, "0");
    var dd = String(cur.getDate()).padStart(2, "0");
    selectedHistoryDate = yyyy + "-" + mm + "-" + dd;
    loadHistoryActivities(selectedHistoryDate);
  } catch (e) {
    console.error("Date shift error:", e);
  }
}

function initHistoryEventListeners() {
  if (historyListenersBound) return;
  historyListenersBound = true;

  var dateInput = document.getElementById("historyDateFilter");
  var prevBtn = document.getElementById("btnHistoryPrevDate");
  var nextBtn = document.getElementById("btnHistoryNextDate");
  var todayBtn = document.getElementById("btnHistoryToday");

  if (dateInput) {
    dateInput.value = selectedHistoryDate;
    dateInput.addEventListener("change", function() {
      if (dateInput.value) {
        selectedHistoryDate = dateInput.value;
        loadHistoryActivities(selectedHistoryDate);
      }
    });
  }

  if (prevBtn) prevBtn.addEventListener("click", function() { shiftHistoryDate(-1); });
  if (nextBtn) nextBtn.addEventListener("click", function() { shiftHistoryDate(1); });
  if (todayBtn) todayBtn.addEventListener("click", function() {
    selectedHistoryDate = getLocalTodayIso();
    loadHistoryActivities(selectedHistoryDate);
  });
}

// Window global exports
window.loadHistoryActivities = loadHistoryActivities;
window.renderHistoryTable = renderHistoryTable;
window.shiftHistoryDate = shiftHistoryDate;
window.initHistoryEventListeners = initHistoryEventListeners;

window.addEventListener("langchange", function(){
  renderHistoryTable();
});
