// settings-analytics.js — AI Usage Metrics & Enterprise Audit Log Explorer
// Modularized from settings.js for maintainability and performance

async function loadAiUsageStats() {
  var periodSelect = document.getElementById("selectAiUsagePeriod");
  var period = periodSelect ? periodSelect.value : "month";
  try {
    var res = await apiGet("/api/admin/ai-usage?period=" + encodeURIComponent(period));
    if (!res || !res.ok) return;

    var s = res.summary || {};
    var callsEl = document.getElementById("statAiTotalCalls");
    var tokensEl = document.getElementById("statAiTotalTokens");
    var promptEl = document.getElementById("statAiPromptTokens");
    var compEl = document.getElementById("statAiCompletionTokens");

    if (callsEl) callsEl.textContent = Number(s.total_calls || 0).toLocaleString() + "회";
    if (tokensEl) tokensEl.textContent = Number(s.total_tokens || 0).toLocaleString();
    if (promptEl) promptEl.textContent = Number(s.total_prompt_tokens || 0).toLocaleString();
    if (compEl) compEl.textContent = Number(s.total_completion_tokens || 0).toLocaleString();

    // Table by User
    var userTbody = document.getElementById("tableAiUsageByUser");
    if (userTbody) {
      var users = res.by_user || [];
      if (!users.length) {
        userTbody.innerHTML = '<tr><td colspan="3" style="text-align:center;padding:16px;color:var(--text-muted);">집계된 사용 기록이 없습니다.</td></tr>';
      } else {
        var uHtml = "";
        users.forEach(function(u) {
          uHtml += '<tr style="border-bottom:1px solid var(--line);">';
          uHtml += '<td style="padding:6px 10px;font-weight:600;">' + escapeHtml(u.user_name || "시스템") + '</td>';
          uHtml += '<td style="padding:6px 10px;text-align:center;">' + Number(u.calls || 0).toLocaleString() + '</td>';
          uHtml += '<td style="padding:6px 10px;text-align:right;font-weight:700;color:#2563eb;">' + Number(u.tokens || 0).toLocaleString() + '</td>';
          uHtml += '</tr>';
        });
        userTbody.innerHTML = uHtml;
      }
    }

    // Table by Model
    var modelTbody = document.getElementById("tableAiUsageByModel");
    if (modelTbody) {
      var models = res.by_provider || [];
      if (!models.length) {
        modelTbody.innerHTML = '<tr><td colspan="3" style="text-align:center;padding:16px;color:var(--text-muted);">집계된 사용 기록이 없습니다.</td></tr>';
      } else {
        var mHtml = "";
        models.forEach(function(m) {
          mHtml += '<tr style="border-bottom:1px solid var(--line);">';
          mHtml += '<td style="padding:6px 10px;"><strong>' + escapeHtml(m.provider || "") + '</strong> <span style="color:var(--text-muted);font-size:11px;">(' + escapeHtml(m.model || "") + ')</span></td>';
          mHtml += '<td style="padding:6px 10px;text-align:center;">' + Number(m.calls || 0).toLocaleString() + '</td>';
          mHtml += '<td style="padding:6px 10px;text-align:right;font-weight:700;color:#7c3aed;">' + Number(m.tokens || 0).toLocaleString() + '</td>';
          mHtml += '</tr>';
        });
        modelTbody.innerHTML = mHtml;
      }
    }
  } catch (e) {
    console.warn("[AI Usage UI] error:", e);
  }
}

function exportAuditLogs(format) {
  var actionSelect = document.getElementById("selectAuditAction");
  var userSearchInput = document.getElementById("inputAuditUser");
  var action = actionSelect ? actionSelect.value : "";
  var user = userSearchInput ? userSearchInput.value.trim() : "";

  var url = "/api/admin/audit-logs/export?format=" + encodeURIComponent(format || "csv");
  if (action) url += "&action=" + encodeURIComponent(action);
  if (user) url += "&user=" + encodeURIComponent(user);

  // Session cookie travels with the navigation request; the endpoint enforces admin role.
  window.location.href = url;
  if (typeof showToast === "function") {
    showToast((format === "json" ? "JSON" : "CSV") + " 감사 로그를 내려받습니다...", 2500);
  }
}

async function loadAuditLogs() {
  var actionSelect = document.getElementById("selectAuditAction");
  var userSearchInput = document.getElementById("inputAuditUser");
  var action = actionSelect ? actionSelect.value : "";
  var user = userSearchInput ? userSearchInput.value.trim() : "";

  var url = "/api/admin/audit-logs?limit=150";
  if (action) url += "&action=" + encodeURIComponent(action);
  if (user) url += "&user=" + encodeURIComponent(user);

  var tbody = document.getElementById("tableAuditLogsBody");
  if (!tbody) return;
  tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:16px;color:var(--text-muted);">감사 로그 조회 중...</td></tr>';

  try {
    var res = await apiGet(url);
    if (!res || !res.ok) {
      tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:16px;color:#ef4444;">감사 로그를 불러오지 못했습니다.</td></tr>';
      return;
    }
    var logs = res.logs || [];
    if (!logs.length) {
      tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:16px;color:var(--text-muted);">일치하는 감사 로그가 없습니다.</td></tr>';
      return;
    }

    var html = "";
    logs.forEach(function(log) {
      var act = log.action || "";
      var badgeColor = "#64748b";
      if (act.includes("CREATE")) badgeColor = "#16a34a";
      else if (act.includes("UPDATE") || act.includes("APPROVE")) badgeColor = "#2563eb";
      else if (act.includes("DELETE") || act.includes("REJECT")) badgeColor = "#dc2626";
      else if (act.includes("LOGIN")) badgeColor = "#7c3aed";

      var detailsStr = "";
      if (log.details && typeof log.details === "object") {
        try {
          detailsStr = JSON.stringify(log.details);
        } catch(e){}
      } else if (log.details_json) {
        detailsStr = log.details_json;
      }

      html += '<tr style="border-bottom:1px solid var(--line);">';
      html += '<td style="padding:7px 10px;font-family:monospace;font-size:11px;color:var(--text-muted);">' + escapeHtml((log.timestamp || "").replace("T", " ")) + '</td>';
      html += '<td style="padding:7px 10px;font-weight:600;">' + escapeHtml(log.username || "anonymous") + '</td>';
      html += '<td style="padding:7px 10px;font-family:monospace;font-size:11px;color:var(--text-muted);">' + escapeHtml(log.ip || "") + '</td>';
      html += '<td style="padding:7px 10px;text-align:center;"><span style="display:inline-block;padding:2px 7px;font-size:10.5px;font-weight:700;color:#fff;background:' + badgeColor + ';border-radius:4px;">' + escapeHtml(act) + '</span></td>';
      html += '<td style="padding:7px 10px;font-weight:500;">' + escapeHtml((log.target_type || "") + (log.target_id ? " (" + log.target_id + ")" : "")) + '</td>';
      html += '<td style="padding:7px 10px;font-family:monospace;font-size:11px;color:var(--ink-soft);max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="' + escapeHtml(detailsStr) + '">' + escapeHtml(detailsStr) + '</td>';
      html += '</tr>';
    });
    tbody.innerHTML = html;
  } catch (err) {
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:16px;color:#ef4444;">조회 오류 발생: ' + escapeHtml(err.message) + '</td></tr>';
  }
}

(function initAiUsageAndAuditUI() {
  var btnRefreshAi = document.getElementById("btnRefreshAiUsage");
  var selectAiPeriod = document.getElementById("selectAiUsagePeriod");
  if (btnRefreshAi) btnRefreshAi.addEventListener("click", loadAiUsageStats);
  if (selectAiPeriod) selectAiPeriod.addEventListener("change", loadAiUsageStats);

  var btnFilterAudit = document.getElementById("btnFilterAudit");
  var selectAuditAction = document.getElementById("selectAuditAction");
  var inputAuditUser = document.getElementById("inputAuditUser");
  if (btnFilterAudit) btnFilterAudit.addEventListener("click", loadAuditLogs);
  if (selectAuditAction) selectAuditAction.addEventListener("change", loadAuditLogs);
  if (inputAuditUser) inputAuditUser.addEventListener("keydown", function(e){ if (e.key === "Enter") loadAuditLogs(); });

  var btnExportCsv = document.getElementById("btnExportAuditCsv");
  var btnExportJson = document.getElementById("btnExportAuditJson");
  if (btnExportCsv) btnExportCsv.addEventListener("click", function(){ exportAuditLogs("csv"); });
  if (btnExportJson) btnExportJson.addEventListener("click", function(){ exportAuditLogs("json"); });

  var nav = document.getElementById("settingsSubtabsNav");
  if (nav) {
    nav.addEventListener("click", function(e) {
      var btn = e.target.closest(".settings-subtab-btn");
      if (!btn) return;
      var tab = btn.getAttribute("data-settings-tab");
      if (tab === "ai_usage") {
        setTimeout(loadAiUsageStats, 50);
      } else if (tab === "audit") {
        setTimeout(loadAuditLogs, 50);
      }
    });
  }

  // If page was loaded with ai_usage or audit saved in session
  try {
    var saved = sessionStorage.getItem("argos_settings_tab");
    if (saved === "ai_usage") setTimeout(loadAiUsageStats, 100);
    else if (saved === "audit") setTimeout(loadAuditLogs, 100);
  } catch(e){}
})();

window.loadAiUsageStats = loadAiUsageStats;
window.loadAuditLogs = loadAuditLogs;
window.exportAuditLogs = exportAuditLogs;

// ---------------------------------------------------------------
// Release version label (single source of truth: /api/version)
// ---------------------------------------------------------------
(function initVersionLabel() {
  function render() {
    var el = document.getElementById("appVersionLabel");
    if (!el) return;
    fetch("/api/version", { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data && data.version) el.textContent = "ARGOS WORKS v" + data.version;
      })
      .catch(function () { /* version label is cosmetic */ });
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", render);
  } else {
    render();
  }
})();
