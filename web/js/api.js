// Purge any leaked tokens from localStorage / sessionStorage to enforce 100% HttpOnly Cookie security
(function purgeLeakedTokens() {
  try {
    localStorage.removeItem("argos_token");
    sessionStorage.removeItem("argos_token");
    localStorage.removeItem("argosToken");
    sessionStorage.removeItem("argosToken");
    localStorage.removeItem("jarvisToken");
    sessionStorage.removeItem("jarvisToken");
    localStorage.removeItem("argosCsrfToken");
    ["jarvisUser", "batonUser", "argosUser"].forEach(function(k) {
      var item = localStorage.getItem(k) || sessionStorage.getItem(k);
      if (item) {
        try {
          var u = JSON.parse(item);
          if (u && u.token) {
            delete u.token;
            localStorage.setItem(k, JSON.stringify(u));
            sessionStorage.setItem(k, JSON.stringify(u));
          }
        } catch(e){}
      }
    });
  } catch(e){}
})();

function getAuthHeaders(){
  // Pure Enterprise HttpOnly Cookie mode: No tokens stored or read in JavaScript.
  return {};
}

function safeParseJson(response) {
  return response.text().then(function(text) {
    if (!text) {
      return response.ok ? { ok: true } : { ok: false, error: "HTTP " + response.status };
    }
    try {
      return JSON.parse(text);
    } catch(err) {
      return {
        ok: false,
        error: "서버 응답 오류 (HTTP " + response.status + "): 유효하지 않은 JSON 응답입니다."
      };
    }
  });
}

function apiGet(path){
  return fetch(path, {
    method: "GET",
    credentials: "same-origin",
    headers: { "Cache-Control": "no-store" },
    cache: "no-store"
  }).then(function(r){
    if (r.status === 401 && !path.includes("/api/account/check") && !path.includes("/api/departments") && !path.includes("/api/account/logout") && !path.includes("/api/products/categories/admin")) {
      if (typeof handleAuthExpired === "function") {
        handleAuthExpired();
      }
    }
    return safeParseJson(r);
  }).catch(function(networkErr){
    console.warn("[apiGet] Network or fetch error:", networkErr);
    if(typeof showToast === "function"){
      showToast("네트워크 연결을 확인해주세요. (서버와 통신할 수 없습니다)", 4000, true);
    }
    return { ok: false, error: "네트워크 연결 오류: " + (networkErr.message || "서버에 연결할 수 없습니다.") };
  });
}
window.apiGet = apiGet;
window.apiGetJson = apiGet;

function apiPostJson(path, body){
  var headers = {
    "Content-Type": "application/json",
    "Cache-Control": "no-store"
  };
  var csrfToken = sessionStorage.getItem("argosCsrfToken");
  if(!csrfToken){
    try {
      var match = document.cookie.match(/argos_csrf=([^;]+)/);
      if(match) csrfToken = decodeURIComponent(match[1]);
    } catch(e){}
  }
  if(!csrfToken){
    try {
      var match = document.cookie.match(/argos_csrf=([^;]+)/);
      if(match) csrfToken = decodeURIComponent(match[1]);
    } catch(e){}
  }
  if(csrfToken){
    headers["X-CSRF-Token"] = csrfToken;
  }
  return fetch(path, {
    method: "POST",
    credentials: "same-origin",
    headers: headers,
    body: JSON.stringify(body)
  }).then(async function(r){
    if (r.status === 403) {
      try {
        var clone = r.clone();
        var data = await clone.json();
        if (data && data.error && (data.error.indexOf("CSRF") !== -1 || data.error.indexOf("csrf") !== -1)) {
          // Automatic resilient CSRF token refresh & retry
          var csrfRes = await fetch("/api/account/csrf", { credentials: "same-origin", cache: "no-store" });
          var csrfData = await csrfRes.json();
          if (csrfData && csrfData.ok && csrfData.csrfToken) {
            sessionStorage.setItem("argosCsrfToken", csrfData.csrfToken);
            try { localStorage.removeItem("argosCsrfToken"); } catch(e){}
            headers["X-CSRF-Token"] = csrfData.csrfToken;
            var retryRes = await fetch(path, {
              method: "POST",
              credentials: "same-origin",
              headers: headers,
              body: JSON.stringify(body)
            });
            return safeParseJson(retryRes);
          }
        }
      } catch(e){}
    }
    if (r.status === 401 && !path.includes("/api/account/login") && !path.includes("/api/account/check") && !path.includes("/api/account/logout")) {
      if (typeof handleAuthExpired === "function") {
        handleAuthExpired();
      }
    }
    return safeParseJson(r);
  }).catch(function(networkErr){
    console.warn("[apiPostJson] Network or fetch error:", networkErr);
    if(typeof showToast === "function"){
      showToast("네트워크 연결을 확인해주세요. (서버와 통신할 수 없습니다)", 4000, true);
    }
    return { ok: false, error: "네트워크 연결 오류: " + (networkErr.message || "서버에 연결할 수 없습니다.") };
  });
}
window.apiPostJson = apiPostJson;
window.apiPost = apiPostJson;

function loadDepartments(){
  if(typeof apiGet === "function"){
    apiGet("/api/members").then(function(mRes){
      if(mRes && mRes.ok && Array.isArray(mRes.members)){
        window.__companyMembers = mRes.members;
        if(typeof renderAssigneeTable === "function") renderAssigneeTable();
      }
    }).catch(function(){});
  }
  return apiGet("/api/departments").then(function(res){
    if(res.ok){ DEPARTMENTS = res.departments; }
    renderOrgChips();
    renderOrgSelectOptions();
    if(typeof idOrgSelect !== "undefined" && idOrgSelect) renderIdOrgOptions();
    return populateCatFilterAll();
  });
}
window.__RECORDS_OFFSET__ = 0;
window.__RECORDS_TOTAL__ = 0;
window.__RECORDS_HAS_MORE__ = false;
window.__RECORDS_IS_LOADING_MORE__ = false;

function loadRecords(limit, offset){
  var isAppend = (typeof offset === "number" && offset > 0);
  var query = (typeof limit === "number")
    ? ("/api/records?limit=" + limit + "&offset=" + (offset || 0))
    : "/api/records?mode=recent&limit=100";

  return apiGet(query).then(function(res){
    if(res.ok){
      var incoming = res.records || [];
      if(isAppend){
        // Deduplicate incoming records
        var existingKeys = new Set((records || []).map(function(r){
          return String(r.id || (r.jira && r.jira.key) || r.cardCode || "");
        }));
        incoming.forEach(function(r){
          var rKey = String(r.id || (r.jira && r.jira.key) || r.cardCode || "");
          if(!existingKeys.has(rKey)){
            records.push(r);
            existingKeys.add(rKey);
          }
        });
      } else {
        records = incoming;
      }
      window.records = records;
      window.allJiraIssues = records;
      window.__RECORDS_OFFSET__ = (res.offset || 0) + incoming.length;
      window.__RECORDS_TOTAL__ = res.total || records.length;
      window.__RECORDS_HAS_MORE__ = Boolean(res.hasMore);
      window.__JIRA_STATUS__ = {
        enabled: Boolean(res.jiraEnabled),
        connected: Boolean(res.jiraConnected)
      };
      if(typeof window.updateJiraIntegrationUI === "function"){
        window.updateJiraIntegrationUI();
      }
      updateSyncCaption(res.syncedAt, res.syncError);
      try {
        var curOrg = (document.getElementById("orgSelect") && document.getElementById("orgSelect").value) || (loggedInUser && loggedInUser.org) || "";
        if(typeof window.populateParentKeySelect === "function"){
          window.populateParentKeySelect(curOrg);
        }
        if(typeof window.populateParticipantsSelect === "function"){
          window.populateParticipantsSelect(curOrg);
        }
      } catch(err){
        console.warn("[populateSelects] init failed:", err);
      }
    }
    refresh();
    if(typeof renderHomePortalSection === "function"){
      try { renderHomePortalSection(); } catch(e){}
    }
    return res;
  });
}

function loadMoreRecords(){
  if(window.__RECORDS_IS_LOADING_MORE__ || !window.__RECORDS_HAS_MORE__) return Promise.resolve();
  window.__RECORDS_IS_LOADING_MORE__ = true;
  var currentOffset = window.__RECORDS_OFFSET__ || (records ? records.length : 0);

  var loadMoreBtn = document.getElementById("btnDashboardLoadMore");
  if(loadMoreBtn){
    loadMoreBtn.disabled = true;
    loadMoreBtn.textContent = "불러오는 중...";
  }

  return loadRecords(100, currentOffset).finally(function(){
    window.__RECORDS_IS_LOADING_MORE__ = false;
  });
}
window.loadMoreRecords = loadMoreRecords;

function loadAllRecords(){
  if(window.__RECORDS_IS_LOADING_MORE__) return Promise.resolve();
  window.__RECORDS_IS_LOADING_MORE__ = true;
  var loadAllBtn = document.getElementById("btnDashboardLoadAll");
  if(loadAllBtn){
    loadAllBtn.disabled = true;
    loadAllBtn.textContent = "전체 로딩 중...";
  }

  return apiGet("/api/records?mode=all").then(function(res){
    if(res.ok){
      records = res.records || [];
      window.records = records;
      window.allJiraIssues = records;
      window.__RECORDS_OFFSET__ = records.length;
      window.__RECORDS_TOTAL__ = res.total || records.length;
      window.__RECORDS_HAS_MORE__ = false;
      refresh();
      if(typeof showToast === "function"){
        showToast("전체 " + records.length + "건의 업무 카드를 모두 불러왔습니다.");
      }
    }
  }).finally(function(){
    window.__RECORDS_IS_LOADING_MORE__ = false;
  });
}
window.loadAllRecords = loadAllRecords;

function formatSyncedAt(iso){
  if(!iso) return "";
  try{
    return new Date(iso).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  }catch(e){ return ""; }
}
function updateSyncCaption(syncedAt, syncError){
  if(!el.syncCaption) return;
  var isJiraEnabled = window.__JIRA_STATUS__ ? window.__JIRA_STATUS__.enabled : false;
  if(!isJiraEnabled){
    el.syncCaption.textContent = "";
    el.syncCaption.style.display = "none";
    el.syncCaption.classList.remove("sync-error");
    return;
  }
  el.syncCaption.style.display = "";
  if(syncError){
    el.syncCaption.textContent = "Jira 동기화 실패(이전 목록 유지) · " + formatSyncedAt(syncedAt);
    el.syncCaption.classList.add("sync-error");
  } else if(syncedAt){
    el.syncCaption.textContent = "Jira 동기화: " + formatSyncedAt(syncedAt);
    el.syncCaption.classList.remove("sync-error");
  } else {
    el.syncCaption.textContent = "";
    el.syncCaption.classList.remove("sync-error");
  }
}
