// jira-form.js
var dropzone = document.getElementById("dropzone");
var fileInput = document.getElementById("fileInput");
var fileListEl = document.getElementById("fileList");

var form = document.getElementById("submitForm");
var formError = document.getElementById("formError");
var projectInput = document.getElementById("projectInput");
var titleInput = document.getElementById("titleInput");
var memoInput = document.getElementById("memoInput");
var startDateInput = document.getElementById("startDateInput");
var dueDateInput = document.getElementById("dueDateInput");
var followupCheck = document.getElementById("followupCheck");
var followupCheckWrap = document.getElementById("followupCheckWrap");
var startDateField = document.getElementById("startDateField");
var dueDateField = document.getElementById("dueDateField");
var startDateDisplay = document.getElementById("startDateDisplay");
var dueDateDisplay = document.getElementById("dueDateDisplay");
var parentKeySelect = document.getElementById("parentKeySelect");
var participantsSelect = document.getElementById("participantsSelect");
var prioritySelect = document.getElementById("prioritySelect");

function updatePrioritySelectColor(selectEl){
  if(window.updatePrioritySelectColor && window.updatePrioritySelectColor !== updatePrioritySelectColor){
    return window.updatePrioritySelectColor(selectEl);
  }
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
}

if(prioritySelect){
  updatePrioritySelectColor(prioritySelect);
  prioritySelect.addEventListener("change", function(){
    updatePrioritySelectColor(this);
  });
  prioritySelect.addEventListener("input", function(){
    updatePrioritySelectColor(this);
  });
}

function updateJiraIntegrationUI(){
  var isJiraEnabled = false;
  if(window.__JIRA_STATUS__ && typeof window.__JIRA_STATUS__.enabled === "boolean"){
    isJiraEnabled = Boolean(window.__JIRA_STATUS__.enabled);
  }

  // 1. Task registration form Jira sync checkbox
  if(followupCheckWrap){
    followupCheckWrap.hidden = !isJiraEnabled;
  }
  if(!isJiraEnabled && followupCheck){
    followupCheck.checked = false;
  }

  // 2. Dashboard toolbar: "⟳ Jira 동기화" button & sync status caption
  var syncBtn = document.getElementById("syncBtn");
  if(syncBtn){
    syncBtn.hidden = !isJiraEnabled;
    syncBtn.style.display = isJiraEnabled ? "" : "none";
  }
  var syncCaption = document.getElementById("syncCaption");
  if(syncCaption && !isJiraEnabled){
    syncCaption.style.display = "none";
  }

  // 3. Calendar: Jira filter checkbox & ongoing section
  var schedShowJira = document.getElementById("schedShowJira");
  var schedShowJiraWrap = schedShowJira ? schedShowJira.closest("label, .cal-opt-item, div") : null;
  if(schedShowJiraWrap){
    schedShowJiraWrap.style.display = isJiraEnabled ? "" : "none";
  }
  var schedJiraOngoing = document.getElementById("schedJiraOngoing");
  if(schedJiraOngoing && !isJiraEnabled){
    schedJiraOngoing.hidden = true;
  }
  var btnToggleOngoingJira = document.getElementById("btnToggleOngoingJira");
  if(btnToggleOngoingJira && !isJiraEnabled){
    btnToggleOngoingJira.style.display = "none";
  }

  // 4. Settings Status Pill (topbar pill)
  var pillJira = document.getElementById("pillJira");
  if(pillJira){
    pillJira.style.display = isJiraEnabled ? "" : "none";
  }

  // 5. Department Modal Jira Project Key input field
  var deptAddJiraKeyField = document.getElementById("deptAddJiraKeyField");
  if(deptAddJiraKeyField){
    deptAddJiraKeyField.style.display = isJiraEnabled ? "" : "none";
  }

  // 6. Settings Category Table Jira header & rows
  var thJira = document.getElementById("thSettingsCategoryJiraKey");
  if(thJira){
    thJira.style.display = isJiraEnabled ? "" : "none";
  }
  if(typeof window.renderSettingsCategoryTable === "function"){
    window.renderSettingsCategoryTable();
  }

  // 7. Department cards on dashboard (hide Jira project key badges if disabled)
  if(typeof window.renderDeptCards === "function"){
    window.renderDeptCards();
  }

  // 8. Settings Jira Config body collapse
  var jiraConfigBody = document.getElementById("jiraConfigBody");
  var setJiraEnabled = document.getElementById("setJiraEnabled");
  if(jiraConfigBody && setJiraEnabled){
    jiraConfigBody.style.display = (isJiraEnabled && setJiraEnabled.checked) ? "block" : "none";
  }
}
window.updateJiraIntegrationUI = updateJiraIntegrationUI;
updateJiraIntegrationUI();

function populateParentKeySelect(deptId, targetKeyToSelect){
  if(!parentKeySelect) return;
  var cleanTargetKey = targetKeyToSelect ? String(targetKeyToSelect).trim().toUpperCase().replace(/^JIRA-/, "").replace(/^#/, "") : "";
  var currentSelected = (window.parentTomSelect ? window.parentTomSelect.getValue() : "") || (parentKeySelect ? parentKeySelect.value : "");
  var preserveKey = cleanTargetKey || currentSelected || "";
  var current = preserveKey;
  var allPool = (typeof records !== "undefined" && Array.isArray(records) && records.length) ? records : ((typeof window.allJiraIssues !== "undefined" && Array.isArray(window.allJiraIssues)) ? window.allJiraIssues : []);

  // Find targetRecord if targetKey or preserveKey was specified
  var targetRecord = null;
  if(preserveKey){
    targetRecord = allPool.find(function(r){
      if(!r) return false;
      var k = (r.jira && r.jira.key) ? r.jira.key : (r.key || r.cardCode || r.id || "");
      return String(k).trim().toUpperCase().replace(/^JIRA-/, "").replace(/^#/, "") === preserveKey.toUpperCase();
    });
  }

  // Filter candidate parents (ARGOS WORKS supports N-tier hierarchy):
  var candidates = allPool.filter(function(r){
    if(!r) return false;
    var k = (r.jira && r.jira.key) || r.cardCode || (r.id ? String(r.id) : "");
    if(!k) return false;
    var cleanK = String(k).trim().toUpperCase().replace(/^JIRA-/, "").replace(/^#/, "");
    // Always include targetRecord even if org differs slightly (cross-dept collaboration)
    if(preserveKey && cleanK === preserveKey.toUpperCase()) return true;
    if(deptId && r.org && r.org !== deptId) return false;
    return true;
  });

  // Sort by Jira key descending or date descending
  candidates.sort(function(a, b){
    var ka = (a.jira && a.jira.key) || a.cardCode || "";
    var kb = (b.jira && b.jira.key) || b.cardCode || "";
    var numA = parseInt(ka.replace(/^[A-Za-z]+-/, ""), 10) || 0;
    var numB = parseInt(kb.replace(/^[A-Za-z]+-/, ""), 10) || 0;
    return numB - numA;
  });

  var optionsForSelect = candidates.map(function(r){
    var key = (r.jira && r.jira.key) || r.cardCode || String(r.id);
    var title = r.title || (r.jira && r.jira.summary) || "";
    var shortTitle = title.length > 40 ? (title.substring(0, 40) + "…") : title;
    var assignee = r.assignee ? (" (" + r.assignee + ")") : "";
    var displayText = "[" + key + "] " + shortTitle + assignee;
    var rawSearch = (key + " " + title + " " + (r.assignee || "")).replace(/[^a-zA-Z0-9가-힣\u00C0-\u024F\u1EA0-\u1EF9]/g, "").toLowerCase();
    return {
      value: key,
      text: displayText,
      search: rawSearch
    };
  });

  // Ensure preserveKey exists in options even if it belongs to a different department (cross-dept)
  if(preserveKey && !optionsForSelect.some(function(o){ return String(o.value).toUpperCase() === preserveKey.toUpperCase(); })){
    var synTitle = targetRecord ? (targetRecord.title || (targetRecord.jira && targetRecord.jira.summary) || preserveKey) : preserveKey;
    var synShortTitle = synTitle.length > 40 ? (synTitle.substring(0, 40) + "…") : synTitle;
    var synAssignee = (targetRecord && targetRecord.assignee) ? (" (" + targetRecord.assignee + ")") : "";
    var synDept = (targetRecord && targetRecord.org) ? (" [" + (typeof orgLabel === "function" ? orgLabel(targetRecord.org) : targetRecord.org) + "]") : "";
    optionsForSelect.unshift({
      value: preserveKey,
      text: "[" + preserveKey + "] " + synShortTitle + synAssignee + synDept,
      search: (preserveKey + " " + synTitle).toLowerCase()
    });
  }

  optionsForSelect.unshift({
    value: "",
    text: "없음 / 선택 안 함 (독립 상위 작업)",
    search: "없음 none 선택 안 함 독립 상위 작업"
  });

  if(window.parentTomSelect){
    try { window.parentTomSelect.destroy(); } catch(e){}
    window.parentTomSelect = null;
  }

  var tomSelectSuccess = false;
  if(window.TomSelect && parentKeySelect){
    try {
      parentKeySelect.innerHTML = "";
      window.parentTomSelect = new TomSelect(parentKeySelect, {
        allowEmptyOption: true,
        create: false,
        sortField: null,
        searchField: ["text", "value", "search"],
        options: optionsForSelect,
        maxOptions: 100,
        placeholder: "상위 작업 검색 (예: VS-53, 신장동, 장욱재...)",
        render: {
          option: function(data, escape){
            if(!data.value){
              return '<div style="color:var(--ink-faint); padding: 8px 12px; font-weight:500;">' + escape(data.text) + '</div>';
            }
            return '<div style="padding: 8px 12px; color:var(--ink); font-weight:500;">' + escape(data.text) + '</div>';
          },
          item: function(data, escape){
            if(!data.value){
              return '<div style="color:var(--ink-faint); font-weight:500;">' + escape(data.text) + '</div>';
            }
            return '<div style="color:var(--ink); font-weight:600;">' + escape(data.text) + '</div>';
          }
        },
        onChange: function(){ this.blur(); }
      });
      var valueToSet = preserveKey || "";
      window.parentTomSelect.setValue(valueToSet, false);
      tomSelectSuccess = true;
    } catch(err){
      console.warn("[TomSelect] init error, fallback to native select:", err);
    }
  }

  if(!tomSelectSuccess && parentKeySelect){
    var html = optionsForSelect.map(function(o){
      return '<option value="' + escapeHtml(o.value) + '">' + escapeHtml(o.text) + '</option>';
    }).join("");
    parentKeySelect.innerHTML = html;
    var toSelect = preserveKey || "";
    if(toSelect){
      parentKeySelect.value = toSelect;
    }
  }
}

// Expose to window so other scripts can call it when records refresh
window.populateParentKeySelect = populateParentKeySelect;

/**
 * Populate participants multi-select dropdown with all available team members
 */
function populateParticipantsSelect(currentDeptId){
  if(!participantsSelect) return;

  var curUser = (typeof loggedInUser !== "undefined" && loggedInUser) ? loggedInUser : (typeof getCurrentUser === "function" ? getCurrentUser() : null);
  var curName = (curUser && curUser.name) ? curUser.name.trim().toLowerCase() : "";
  var curUsername = (curUser && curUser.username) ? curUser.username.trim().toLowerCase() : "";
  var curEmail = (curUser && curUser.email) ? curUser.email.trim().toLowerCase() : "";

  var currentSelected = [];
  if(window.participantsTomSelect){
    try {
      var val = window.participantsTomSelect.getValue();
      if(Array.isArray(val)) currentSelected = val;
      else if(typeof val === "string" && val.trim()) currentSelected = val.split(",").map(function(s){ return s.trim(); }).filter(Boolean);
    } catch(e){}
  } else if(participantsSelect.selectedOptions){
    currentSelected = Array.from(participantsSelect.selectedOptions).map(function(o){ return o.value; });
  }
  currentSelected = currentSelected.filter(function(v){
    if(!v || v === "없음" || v === "none") return false;
    var vLow = v.trim().toLowerCase();
    if(curName && vLow === curName) return false;
    if(curUsername && vLow === curUsername) return false;
    return true;
  });

  function renderSelectOptions(memberList){
    if(!participantsSelect) return;

    var selectedDept = currentDeptId || (orgSelect && orgSelect.value) || (typeof loggedInUser !== "undefined" && loggedInUser && loggedInUser.org) || "";

    // Exclude the currently logged in user (creator/assignee) from collaborators
    var filteredMembers = (memberList || []).filter(function(m){
      if(!m) return false;
      var mName = (m.name || "").trim().toLowerCase();
      var mUser = (m.username || "").trim().toLowerCase();
      var mEmail = (m.email || "").trim().toLowerCase();

      if(curName && mName === curName) return false;
      if(curUsername && (mUser === curUsername || mName === curUsername)) return false;
      if(curEmail && mEmail === curEmail) return false;
      return true;
    });

    var optionsForSelect = filteredMembers.map(function(m){
      var deptLabel = m.dept || (typeof orgLabel === "function" ? orgLabel(m.org) : (m.org || ""));
      var displayText = m.name + (deptLabel ? " (" + deptLabel + ")" : "");
      var searchTerms = [m.name, deptLabel, m.org, m.email].filter(Boolean).join(" ").toLowerCase();
      var isCurrentDept = (selectedDept && m.org === selectedDept) ? 1 : 0;
      return {
        value: m.name,
        name: m.name,
        dept: deptLabel,
        email: m.email || "",
        text: displayText,
        search: searchTerms,
        isCurrentDept: isCurrentDept
      };
    });

    // Add "없음" (None / Clear) option at the very top
    optionsForSelect.unshift({
      value: "없음",
      name: "없음",
      dept: "초기화",
      email: "",
      text: "없음 (선택 해제 / 참여자 없음)",
      search: "없음 none empty 단독 선택안함 초기화 해제",
      isCurrentDept: 2
    });

    // Filter currentSelected so only valid options that exist in optionsForSelect remain selected
    currentSelected = currentSelected.filter(function(val){
      var vLow = (val || "").trim().toLowerCase();
      return optionsForSelect.some(function(o){ return o.value.toLowerCase() === vLow; });
    });

    if(window.participantsTomSelect){
      try {
        window.participantsTomSelect.clearOptions();
        optionsForSelect.forEach(function(opt){
          window.participantsTomSelect.addOption(opt);
        });
        if(currentSelected.length){
          window.participantsTomSelect.setValue(currentSelected, false);
        }
        window.participantsTomSelect.refreshOptions(false);
        if(window.participantsTomSelect.wrapper){
          window.participantsTomSelect.wrapper.classList.add('dropdown-up');
        }
        return;
      } catch(err){
        try { window.participantsTomSelect.destroy(); } catch(e){}
        window.participantsTomSelect = null;
      }
    }

    if(window.TomSelect && participantsSelect){
      try {
        participantsSelect.innerHTML = "";
        window.participantsTomSelect = new TomSelect(participantsSelect, {
          plugins: ['remove_button'],
          persist: false,
          create: false,
          createOnBlur: false,
          openOnFocus: true,
          maxOptions: 100,
          sortField: [
            { field: "isCurrentDept", direction: "desc" },
            { field: "name", direction: "asc" }
          ],
          searchField: ["name", "dept", "text", "value", "email", "search"],
          options: optionsForSelect,
          placeholder: "사내 등록된 팀원을 검색하여 선택하세요...",
          onInitialize: function(){
            if(this.wrapper) this.wrapper.classList.add('dropdown-up');
          },
          onItemAdd: function(value){
            var val = (value || "").trim().toLowerCase();
            if(val === "없음" || val === "none"){
              var self = this;
              setTimeout(function(){
                self.clear(true);
                self.close();
                self.blur();
                if(self.control_input) self.control_input.blur();
              }, 10);
            } else if((curName && val === curName) || (curUsername && val === curUsername)){
              var self = this;
              setTimeout(function(){
                self.removeItem(value, true);
              }, 10);
            }
          },
          onChange: function(values){
            if(!values) return;
            var arr = Array.isArray(values) ? values : [values];
            var self = this;
            if(arr.includes("없음") || arr.includes("none")){
              setTimeout(function(){
                self.clear(true);
                self.close();
                self.blur();
                if(self.control_input) self.control_input.blur();
              }, 10);
            } else if(arr.some(function(v){ var vl = (v||"").trim().toLowerCase(); return (curName && vl === curName) || (curUsername && vl === curUsername); })){
              setTimeout(function(){
                var cleaned = arr.filter(function(v){ var vl = (v||"").trim().toLowerCase(); return !(curName && vl === curName) && !(curUsername && vl === curUsername); });
                self.setValue(cleaned, true);
              }, 10);
            }
          },
          render: {
            no_results: function(data, escape) {
              return '<div class="no-results" style="padding: 9px 12px; color: var(--ink-faint); font-size: 12px; font-style: italic;">' +
                       '🔍 일치하는 사내 직원이 없습니다 (사내 등록된 계정만 선택 가능)' +
                     '</div>';
            },
            option: function(data, escape) {
              if(data.value === "없음"){
                return '<div class="part-ts-option" style="color:var(--ink-faint);">' +
                         '<span class="part-option-name" style="color:var(--ink-faint); font-weight:600;">없음 (선택 해제 / 참여자 없음)</span>' +
                         '<div class="part-option-meta"><span class="part-option-dept" style="background:var(--code-bg); color:var(--ink-faint);">초기화</span></div>' +
                       '</div>';
              }
              var deptTag = data.dept ? '<span class="part-option-dept">' + escape(data.dept) + '</span>' : '';
              var emailTag = data.email ? '<span class="part-option-email">' + escape(data.email) + '</span>' : '';
              return '<div class="part-ts-option">' +
                       '<span class="part-option-name">' + escape(data.name || data.value) + '</span>' +
                       '<div class="part-option-meta">' + deptTag + emailTag + '</div>' +
                     '</div>';
            },
            item: function(data, escape) {
              if(data.value === "없음"){
                return '<div class="item participant-tag tag-none" style="background:var(--code-bg); color:var(--ink-faint); font-weight:500;">없음</div>';
              }
              return '<div class="item participant-tag">' + escape(data.name || data.value) + '</div>';
            }
          }
        });
        if(currentSelected.length){
          window.participantsTomSelect.setValue(currentSelected, false);
        }
      } catch(err){
        console.warn("[TomSelect] participantsSelect init error:", err);
      }
    }

    if(!window.participantsTomSelect && participantsSelect){
      var html = optionsForSelect.map(function(o){
        var isSel = currentSelected.includes(o.value) ? " selected" : "";
        return '<option value="' + escapeHtml(o.value) + '"' + isSel + '>' + escapeHtml(o.text) + '</option>';
      }).join("");
      participantsSelect.innerHTML = html;
    }
  }

  // 1. If cached in window.__companyMembers, render immediately
  if(window.__companyMembers && Array.isArray(window.__companyMembers) && window.__companyMembers.length > 0){
    renderSelectOptions(window.__companyMembers);
  }

  // 2. Fetch fresh members from /api/members
  if(typeof apiGet === "function"){
    apiGet("/api/members").then(function(res){
      if(res && res.ok && Array.isArray(res.members) && res.members.length > 0){
        window.__companyMembers = res.members;
        renderSelectOptions(res.members);
      }
    }).catch(function(err){
      console.warn("[populateParticipantsSelect] /api/members failed, falling back to local pool:", err);
      fallbackFromPool();
    });
  } else {
    fallbackFromPool();
  }

  function fallbackFromPool(){
    var memberMap = {};
    function addFallback(name, org){
      var n = (name || "").trim();
      if(!n || n === "미배정" || n === "Unassigned" || n === "None" || n === "-" || n === "미할당") return;
      var k = n.toLowerCase();
      if(!memberMap[k]){
        memberMap[k] = { name: n, org: org || "", dept: (typeof orgLabel === "function" ? orgLabel(org) : org) };
      }
    }
    if(typeof allSchedMembers !== "undefined" && Array.isArray(allSchedMembers)){
      allSchedMembers.forEach(function(m){ addFallback(m.name, m.org); });
    }
    var allPool = (typeof records !== "undefined" && Array.isArray(records) && records.length) ? records : ((typeof window.allJiraIssues !== "undefined" && Array.isArray(window.allJiraIssues)) ? window.allJiraIssues : []);
    allPool.forEach(function(r){
      addFallback(r.assignee, r.org);
    });
    var fallbackList = Object.values(memberMap);
    if(fallbackList.length > 0){
      renderSelectOptions(fallbackList);
    }
  }
}
window.populateParticipantsSelect = populateParticipantsSelect;

// Auto-initialize when DOM is ready or when schedule/records load
setTimeout(function(){ populateParticipantsSelect(); }, 200);

/**
 * Switch to Jira Tab (#viewForm) and automatically preselect the given parent issue key
 */
window.selectParentInJiraForm = function(parentKey){
  var cleanKey = String(parentKey || "").trim().toUpperCase().replace(/^JIRA-/, "").replace(/^#/, "");
  if(!cleanKey) return;

  if(typeof window.closeCanvas === "function"){
    window.closeCanvas();
  }
  if(typeof showTab === "function"){
    showTab("form");
  }

  // Find the record to get its department/org if available
  var allPool = (typeof records !== "undefined" && Array.isArray(records) && records.length) ? records : ((typeof window.allJiraIssues !== "undefined" && Array.isArray(window.allJiraIssues)) ? window.allJiraIssues : []);
  var targetRecord = allPool.find(function(r){
    if(!r) return false;
    var jk = (r.jira && r.jira.key) ? String(r.jira.key).trim().toUpperCase().replace(/^JIRA-/, "").replace(/^#/, "") : "";
    var cc = r.cardCode ? String(r.cardCode).trim().toUpperCase().replace(/^#/, "") : "";
    var rid = r.id ? String(r.id).trim().toUpperCase().replace(/^#/, "") : "";
    var rk = r.key ? String(r.key).trim().toUpperCase().replace(/^JIRA-/, "").replace(/^#/, "") : "";
    return jk === cleanKey || cc === cleanKey || rid === cleanKey || rk === cleanKey;
  });

  // Determine actual parent key to store (prefer cardCode or Jira key)
  var parentKeyToStore = cleanKey;
  if(targetRecord){
    parentKeyToStore = (targetRecord.jira && targetRecord.jira.key) || targetRecord.cardCode || (targetRecord.id ? String(targetRecord.id) : cleanKey);
  }

  var targetOrg = targetRecord ? targetRecord.org : (orgSelect ? orgSelect.value : "lab");
  if(orgSelect && targetOrg && orgSelect.value !== targetOrg){
    orgSelect.value = targetOrg;
    if(typeof populateCatSelect === "function"){
      populateCatSelect(targetOrg);
    }
  }

  // Local-First: do NOT force Jira followup to true. Jira is secondary.

  // Populate and select the parentKey
  populateParentKeySelect(targetOrg, parentKeyToStore);

  // Sync TomSelect / native select and focus input
  setTimeout(function(){
    if(window.parentTomSelect){
      // Ensure option exists in TomSelect instance
      if(!window.parentTomSelect.options[parentKeyToStore]){
        var synTitle = targetRecord ? (targetRecord.title || (targetRecord.jira && targetRecord.jira.summary) || parentKeyToStore) : parentKeyToStore;
        var synShortTitle = synTitle.length > 40 ? (synTitle.substring(0, 40) + "…") : synTitle;
        var synAssignee = (targetRecord && targetRecord.assignee) ? (" (" + targetRecord.assignee + ")") : "";
        window.parentTomSelect.addOption({
          value: parentKeyToStore,
          text: "[" + parentKeyToStore + "] " + synShortTitle + synAssignee,
          search: (parentKeyToStore + " " + synTitle).toLowerCase()
        });
      }
      window.parentTomSelect.setValue(parentKeyToStore, false);
      window.parentTomSelect.refreshOptions(false);
    } else if(parentKeySelect){
      parentKeySelect.value = parentKeyToStore;
    }

    var titleEl = document.getElementById("titleInput");
    if(titleEl){
      titleEl.focus();
    }
    if(typeof showToast === "function"){
      showToast("[" + parentKeyToStore + "]의 하위 작업 작성 화면으로 이동했습니다.");
    }
  }, 60);
};

if(orgSelect){
  orgSelect.addEventListener("change", function(){
    populateParentKeySelect(orgSelect.value);
    populateParticipantsSelect(orgSelect.value);
  });
}

if(dropzone){
  dropzone.addEventListener("click", function(){ fileInput.click(); });
  dropzone.addEventListener("dragover", function(e){ e.preventDefault(); dropzone.style.borderColor = "var(--accent)"; });
  dropzone.addEventListener("dragleave", function(){ dropzone.style.borderColor = ""; });
  dropzone.addEventListener("drop", function(e){
    e.preventDefault();
    dropzone.style.borderColor = "";
    addFiles(e.dataTransfer.files);
  });
}
if(fileInput){
  fileInput.addEventListener("change", function(){ addFiles(fileInput.files); });
}

function addFiles(fileListObj){
  Array.prototype.forEach.call(fileListObj, function(f){ selectedFiles.push(f); });
  renderFileList();
}
function renderFileList(){
  if(!fileListEl) return;
  fileListEl.innerHTML = selectedFiles.map(function(f, i){
    return '<div class="file-chip"><span>' + escapeHtml(f.name) + '</span><button type="button" data-i="' + i + '" aria-label="제거" style="background:none;border:none;cursor:pointer;color:var(--ink-faint);">✕</button></div>';
  }).join("");
}
if(fileListEl){
  fileListEl.addEventListener("click", function(e){
    var btn = e.target.closest("button[data-i]");
    if(!btn) return;
    selectedFiles.splice(Number(btn.getAttribute("data-i")), 1);
    renderFileList();
  });
}

function formatCustomDateDisplay(inputEl, displayEl, defaultPlaceholder){
  if(!displayEl || !inputEl) return;
  var textEl = displayEl.querySelector(".custom-date-text");
  if(!textEl) return;
  var val = (inputEl.value || "").trim();
  if(!val){
    textEl.textContent = defaultPlaceholder || "연도-월-일 선택 (YYYY-MM-DD)";
    textEl.classList.add("placeholder");
  } else {
    var parts = val.split("-");
    if(parts.length === 3){
      textEl.textContent = parts[0] + "년 " + parseInt(parts[1], 10) + "월 " + parseInt(parts[2], 10) + "일 (" + val + ")";
    } else {
      textEl.textContent = val;
    }
    textEl.classList.remove("placeholder");
  }
}

function updateStartDateDisplay(){
  formatCustomDateDisplay(startDateInput, startDateDisplay, "시작일 선택 (YYYY-MM-DD)");
}

function updateDueDateDisplay(){
  formatCustomDateDisplay(dueDateInput, dueDateDisplay, "마감일 선택 (YYYY-MM-DD)");
}

if(startDateInput){
  startDateInput.addEventListener("input", updateStartDateDisplay);
  startDateInput.addEventListener("change", updateStartDateDisplay);
  startDateInput.addEventListener("click", function(){
    if(typeof this.showPicker === "function"){
      try { this.showPicker(); } catch(e){}
    }
  });
}

if(dueDateInput){
  dueDateInput.addEventListener("input", updateDueDateDisplay);
  dueDateInput.addEventListener("change", updateDueDateDisplay);
  dueDateInput.addEventListener("click", function(){
    if(typeof this.showPicker === "function"){
      try { this.showPicker(); } catch(e){}
    }
  });
}

if(form){
  form.addEventListener("submit", async function(e){
    e.preventDefault();
    var org = orgSelect.value;
    var title = titleInput ? titleInput.value.trim() : "";
    var memo = memoInput.value.trim();

    if(!loggedInUser){
      formError.textContent = "먼저 우측 상단에서 이름/소속을 입력해주세요.";
      formError.classList.add("show");
      return;
    }
    if(!org){
      formError.textContent = "소속 / 프로젝트를 선택해주세요.";
      formError.classList.add("show");
      return;
    }
    if(!selectedFiles.length && !memo && !title){
      formError.textContent = "제목, 파일 또는 메모 중 하나는 입력해주세요.";
      formError.classList.add("show");
      return;
    }

    var sDateVal = startDateInput ? (startDateInput.value || "") : "";
    var dDateVal = dueDateInput ? (dueDateInput.value || "") : "";
    if(sDateVal && dDateVal && dDateVal < sDateVal){
      formError.textContent = "마감일은 시작일보다 빠를 수 없습니다. (마감일 >= 시작일)";
      formError.classList.add("show");
      return;
    }
    formError.classList.remove("show");

    submitBtn.disabled = true;
    processingStatus.classList.add("show");

    var fd = new FormData();
    fd.append("org", org);
    fd.append("title", title);
    fd.append("category", catSelect.value || "");
    var prioVal = prioritySelect ? (prioritySelect.value || "보통") : "보통";
    fd.append("priority", prioVal);
    var parentKeyVal = "";
    if(window.parentTomSelect){
      parentKeyVal = window.parentTomSelect.getValue() || "";
    } else if(parentKeySelect){
      parentKeyVal = parentKeySelect.value || "";
    }
    if(parentKeyVal){
      fd.append("parentKey", parentKeyVal);
    }
    fd.append("project", projectInput.value.trim());
    fd.append("memo", memo);
    fd.append("assigneeName", loggedInUser.name);
    fd.append("assigneeEmail", loggedInUser.email || "");
    fd.append("followup", followupCheck && followupCheck.checked ? "1" : "0");
    fd.append("startDate", startDateInput ? (startDateInput.value || "") : "");
    fd.append("dueDate", dueDateInput ? (dueDateInput.value || "") : "");
    selectedFiles.forEach(function(f){ fd.append("files", f, f.name); });

    var participantsVal = "";
    var currentCreatorLower = (loggedInUser.name || "").trim().toLowerCase();
    var currentCreatorUser = (loggedInUser.username || "").trim().toLowerCase();
    function isNotSelf(name) {
      var n = (name || "").trim().toLowerCase();
      if(!n || n === "없음" || n === "none") return false;
      if(currentCreatorLower && n === currentCreatorLower) return false;
      if(currentCreatorUser && n === currentCreatorUser) return false;
      return true;
    }

    if(window.participantsTomSelect){
      var pVals = window.participantsTomSelect.getValue();
      if(Array.isArray(pVals)){
        var filtered = pVals.filter(isNotSelf);
        participantsVal = filtered.join(", ");
      } else if(pVals && isNotSelf(pVals)){
        participantsVal = String(pVals).trim();
      }
    } else if(participantsSelect){
      var filtered = Array.from(participantsSelect.selectedOptions).map(function(o){ return o.value; }).filter(isNotSelf);
      participantsVal = filtered.join(", ");
    }
    fd.append("participants", participantsVal);

    var headers = (typeof getAuthHeaders === "function") ? getAuthHeaders() : {};
    var csrfToken = sessionStorage.getItem("argosCsrfToken") || localStorage.getItem("argosCsrfToken");
    if(!csrfToken){
      try {
        var match = document.cookie.match(/argos_csrf=([^;]+)/);
        if(match) csrfToken = decodeURIComponent(match[1]);
      } catch(e){}
    }
    if(!csrfToken){
      try {
        var cResp = await fetch("/api/account/csrf", { credentials: "same-origin" });
        var cData = await cResp.json();
        if(cData && cData.csrfToken){
          csrfToken = cData.csrfToken;
          sessionStorage.setItem("argosCsrfToken", csrfToken);
          localStorage.setItem("argosCsrfToken", csrfToken);
        }
      } catch(e){}
    }
    if(csrfToken) headers["X-CSRF-Token"] = csrfToken;

    var fetchRes;
    try {
      fetchRes = await fetch("/api/submit", { method: "POST", headers: headers, credentials: "same-origin", body: fd });
    } catch(netErr){
      processingStatus.classList.remove("show");
      formError.textContent = "네트워크 연결 오류가 발생했습니다.";
      formError.classList.add("show");
      updateSubmitAvailability();
      return;
    }

    var res;
    try {
      res = await fetchRes.json();
    } catch(e){
      res = { ok: false, error: "서버 응답 처리 실패" };
    }

    // Auto-retry once if CSRF error occurred
    if(fetchRes.status === 403 && res && res.error && res.error.indexOf("CSRF") !== -1){
      try {
        var refreshResp = await fetch("/api/account/csrf", { credentials: "same-origin" });
        var refreshData = await refreshResp.json();
        if(refreshData && refreshData.csrfToken){
          headers["X-CSRF-Token"] = refreshData.csrfToken;
          sessionStorage.setItem("argosCsrfToken", refreshData.csrfToken);
          localStorage.setItem("argosCsrfToken", refreshData.csrfToken);
          var retryFetch = await fetch("/api/submit", { method: "POST", headers: headers, credentials: "same-origin", body: fd });
          res = await retryFetch.json();
        }
      } catch(e){}
    }

    processingStatus.classList.remove("show");
    if(!res || !res.ok){
      formError.textContent = (res && res.error) || "제출 중 오류가 발생했습니다.";
      formError.classList.add("show");
      updateSubmitAvailability();
      return;
    }

    form.reset();
    if(window.parentTomSelect){
      window.parentTomSelect.setValue("");
    }
    if(window.catTomSelect){
      window.catTomSelect.setValue("");
    }
    if(window.participantsTomSelect){
      window.participantsTomSelect.setValue([]);
    }
    if(prioritySelect){
      prioritySelect.value = "보통";
      updatePrioritySelectColor(prioritySelect);
    }
    updateStartDateDisplay();
    updateDueDateDisplay();
    selectedFiles = [];
    renderFileList();
    fillSubmitterFromLogin();
    updateSubmitAvailability();

    showTab("dash");
    filters.org = "all";
    filters.cat = "all";
    filters.q = "";
    filters.assignee = "all";
    viewMode = "recent";
    if(el.search) el.search.value = "";
    if(el.catFilter) el.catFilter.value = "all";
    if(typeof renderOrgChips === "function") renderOrgChips();

    if(typeof loadRecords === "function"){
      loadRecords().then(function(){
        if(el.list){
          var newEl = el.list.querySelector("details.record");
          if(newEl){
            newEl.classList.add("flash");
            if(newEl.scrollIntoView) newEl.scrollIntoView({ behavior: "smooth", block: "center" });
          }
        }
        var msg = (res.record && res.record.jira) ? ("기록이 추가되고 Jira 티켓 " + res.record.jira.key + "가 생성되었습니다.") : "기록이 대시보드에 추가되었습니다.";
        if(res.jiraNote) msg += " (" + res.jiraNote + ")";
        showToast(msg);
      });
    }
  });
}
