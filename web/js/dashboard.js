// dashboard.js
var catSelect = document.getElementById("catSelect");

var CATEGORIES_METADATA_BY_DEPT = {};

function loadCategoriesFor(deptId){
  if(!deptId) return Promise.resolve([]);
  if(CATEGORIES_BY_DEPT[deptId]) return Promise.resolve(CATEGORIES_BY_DEPT[deptId]);
  return apiGet("/api/categories?org=" + encodeURIComponent(deptId)).then(function(res){
    var cats = (res.ok && res.categories) ? res.categories : [];
    CATEGORIES_BY_DEPT[deptId] = cats;
    if(res.ok && res.items){
      CATEGORIES_METADATA_BY_DEPT[deptId] = res.items;
    }
    return cats;
  }).catch(function(){ return []; });
}

var JIRA_BLUE_ICON_SVG = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" style="vertical-align:-2px;margin-right:5px;flex-shrink:0;"><rect width="24" height="24" rx="5" fill="#0052CC"/><path d="M12.02 5.02L7.3 9.74a1.05 1.05 0 000 1.48l4.72 4.72a1.05 1.05 0 001.48 0l4.72-4.72a1.05 1.05 0 000-1.48L13.5 5.02a1.05 1.05 0 00-1.48 0z" fill="#FFF"/><path d="M16.74 9.74l-4.72 4.72a1.05 1.05 0 000 1.48l4.72 4.72a1.05 1.05 0 001.48 0l2.25-2.25a1.05 1.05 0 000-1.48l-2.25-2.25a1.05 1.05 0 00-1.48-4.94z" fill="#2684FF"/></svg>';

function populateCatSelect(deptId){
  if(!catSelect) return Promise.resolve();
  var current = catSelect.value;
  return loadCategoriesFor(deptId).then(function(cats){
    var items = CATEGORIES_METADATA_BY_DEPT[deptId] || [];
    var metaMap = {};
    items.forEach(function(it){ metaMap[it.name] = it; });

    // Separate into Jira and Local categories (no duplicates)
    var jiraItems = [];
    var localItems = [];
    var isJiraActive = isJiraIntegrationActive();

    cats.forEach(function(c){
      var meta = metaMap[c];
      if(meta && meta.origin === "jira" && isJiraActive){
        jiraItems.push({ name: c, isJira: true });
      } else {
        localItems.push({ name: c, isJira: false });
      }
    });

    if(window.TomSelect){
      if(window.catTomSelect){
        try { window.catTomSelect.destroy(); } catch(e){}
        window.catTomSelect = null;
      }
      catSelect.innerHTML = "";
      
      var optionsList = [{ value: "", text: "기타 / 자동 분류", optgroup: "" }];
      var optgroupsList = [];

      if(jiraItems.length && isJiraActive){
        optgroupsList.push({ id: "jira", name: "Jira 연동 유형" });
        jiraItems.forEach(function(j){
          optionsList.push({
            value: j.name,
            text: j.name,
            optgroup: "jira",
            isJira: true
          });
        });
      }

      if(localItems.length){
        optgroupsList.push({ id: "local", name: isJiraActive ? "사내 고유 업무 유형" : "업무 유형" });
        localItems.forEach(function(l){
          optionsList.push({
            value: l.name,
            text: l.name,
            optgroup: "local",
            isJira: false
          });
        });
      }

      try {
        window.catTomSelect = new TomSelect(catSelect, {
          allowEmptyOption: true,
          create: true,
          createOnBlur: true,
          controlInput: null, // Acts as a clean select without blinking cursor line
          optgroups: optgroupsList,
          optgroupField: "optgroup",
          options: optionsList,
          render: {
            option: function(data, escape){
              if(!data.value){
                return '<div class="cat-ts-opt auto-opt"><span>' + escape(data.text) + '</span></div>';
              }
              return '<div class="cat-ts-opt ' + (data.isJira ? 'jira-opt' : 'local-opt') + '">' +
                '<span class="cat-ts-name ' + (data.isJira ? 'jira-text' : 'local-text') + '">' + escape(data.text) + '</span>' +
              '</div>';
            },
            item: function(data, escape){
              if(!data.value){
                return '<div class="cat-ts-item auto-item"><span>' + escape(data.text) + '</span></div>';
              }
              return '<div class="cat-ts-item ' + (data.isJira ? 'jira-item' : 'local-item') + '">' +
                '<span class="cat-ts-name ' + (data.isJira ? 'jira-text' : 'local-text') + '">' + escape(data.text) + '</span>' +
              '</div>';
            }
          },
          onChange: function(){ this.blur(); }
        });
        window.catTomSelect.setValue(current || "", false);
        return;
      } catch(err){
        console.warn("[TomSelect] catSelect init error, fallback to native:", err);
      }
    }

    // Native select fallback
    var html = '<option value="">기타 / 자동 분류</option>';
    if(jiraItems.length && isJiraActive){
      html += '<optgroup label="Jira 연동 유형">';
      jiraItems.forEach(function(j){
        html += '<option value="' + escapeHtml(j.name) + '">' + escapeHtml(j.name) + '</option>';
      });
      html += '</optgroup>';
    }
    if(localItems.length){
      html += '<optgroup label="' + (isJiraActive ? '사내 고유 업무 유형' : '업무 유형') + '">';
      localItems.forEach(function(l){
        html += '<option value="' + escapeHtml(l.name) + '">' + escapeHtml(l.name) + '</option>';
      });
      html += '</optgroup>';
    }
    catSelect.innerHTML = html;
    if(cats.indexOf(current) !== -1) catSelect.value = current;
  });
}

function populateCatFilterAll(){
  var current = el.catFilter.value;
  var deptIds = DEPARTMENTS.map(function(d){ return d.id; });
  return Promise.all(deptIds.map(loadCategoriesFor)).then(function(results){
    var seen = {};
    var all = [];
    results.forEach(function(cats){
      cats.forEach(function(c){
        if(!seen[c]){ seen[c] = true; all.push(c); }
      });
    });
    all.sort(function(a, b){ return a.localeCompare(b, "ko"); });
    var allCatLabel = (window.i18n && typeof window.i18n.t === "function") ? window.i18n.t("filter.all_categories") : "전체 카테고리";
    var html = '<option value="all">' + escapeHtml(allCatLabel) + '</option>';
    all.forEach(function(c){
      html += '<option value="' + escapeHtml(c) + '">' + escapeHtml(c) + '</option>';
    });
    el.catFilter.innerHTML = html;
    if(current && (current === "all" || all.indexOf(current) !== -1)) el.catFilter.value = current;
  });
}

function populateCatFilterForDept(deptId){
  if(!deptId || deptId === "all"){
    return populateCatFilterAll();
  }
  var current = el.catFilter.value;
  return loadCategoriesFor(deptId).then(function(cats){
    var allCatLabel = (window.i18n && typeof window.i18n.t === "function") ? window.i18n.t("filter.all_categories") : "전체 카테고리";
    var html = '<option value="all">' + escapeHtml(allCatLabel) + '</option>';
    cats.forEach(function(c){
      html += '<option value="' + escapeHtml(c) + '">' + escapeHtml(c) + '</option>';
    });
    el.catFilter.innerHTML = html;
    if(current && (current === "all" || cats.indexOf(current) !== -1)){
      el.catFilter.value = current;
    } else {
      el.catFilter.value = "all";
      filters.cat = "all";
    }
  });
}

function refreshCategoriesAfterSync(){
  CATEGORIES_BY_DEPT = {};
  var tasks = [populateCatFilterAll()];
  if(loggedInUser) tasks.push(populateCatSelect(loggedInUser.org));
  return Promise.all(tasks);
}

function renderOrgChips(){
  if(el.orgChips){
    el.orgChips.style.display = "none";
    el.orgChips.hidden = true;
    el.orgChips.innerHTML = "";
  }
}

function renderOrgSelectOptions(){
  var orgSelectElem = document.getElementById("orgSelect");
  if(!orgSelectElem) return;
  var current = orgSelectElem.value;
  var html = '<option value="">선택하세요</option>';
  DEPARTMENTS.forEach(function(d){
    html += '<option value="' + d.id + '">' + escapeHtml(d.name) + '</option>';
  });
  orgSelectElem.innerHTML = html;
  if(DEPARTMENTS.some(function(d){ return d.id === current; })) orgSelectElem.value = current;
}

function isJiraIntegrationActive(){
  if(window.__JIRA_STATUS__ && typeof window.__JIRA_STATUS__.enabled === "boolean"){
    return Boolean(window.__JIRA_STATUS__.enabled);
  }
  return false;
}

function jiraPill(jira){
  // [요구사항] Jira 연동이 활성화된 경우에만 'Jira ↗' 및 'Jira 없음' 뱃지를 표시
  if(!isJiraIntegrationActive()){
    return "";
  }

  if(!jira) return '<span class="jira-pill none">Jira 없음</span>';
  var labelMap = { info: "진행중", good: "완료", critical: "지연" };
  var statusText = labelMap[jira.status] || jira.status || "";
  var tooltip = jira.key ? ("Jira에서 " + jira.key + " 열기" + (statusText ? " (" + statusText + ")" : "")) : "Jira 열기";
  var url = jira.url || "";

  if(!url){
    return '<span class="jira-pill ' + escapeHtml(jira.status || "info") + '">' +
      '<span>Jira</span>' +
    '</span>';
  }

  return (
    '<a href="' + escapeHtml(url) + '" target="_blank" rel="noopener" class="jira-pill jira-link-pill ' + escapeHtml(jira.status || "info") + '" ' +
       'onclick="event.stopPropagation();" title="' + escapeHtml(tooltip) + '">' +
      '<span>Jira</span>' +
      '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="margin-left:2px;vertical-align:-1px;">' +
        '<line x1="7" y1="17" x2="17" y2="7"></line>' +
        '<polyline points="7 7 17 7 17 17"></polyline>' +
      '</svg>' +
    '</a>'
  );
}

function recordStatusBadge(r){
  var text = "";
  var cls = "inprog";

  if(r.jira){
    var rawName = (r.jira.statusName || "").trim();
    var rawStatus = (r.jira.status || "").toLowerCase();
    var rawLower = rawName.toLowerCase();

    if(rawName.includes("완료") || rawLower === "done" || rawLower === "closed" || rawLower === "resolved" || rawStatus === "good"){
      text = "완료";
      cls = "done";
    } else if(rawName.includes("지연") || rawStatus === "critical"){
      text = "지연";
      cls = "delayed";
    } else if(rawName.includes("검토") || rawLower.includes("review") || rawLower.includes("testing")){
      text = "검토";
      cls = "review";
    } else if(rawName.includes("예정") || rawName.includes("할 일") || rawName.includes("준비") || rawName.includes("대기") || rawLower.includes("todo") || rawLower === "to do" || rawLower === "open"){
      text = "예정";
      cls = "todo";
    } else if(rawName.includes("진행") || rawLower.includes("in progress") || rawLower.includes("progress")){
      text = "진행";
      cls = "inprog";
    } else if(rawName){
      text = (rawStatus === "good") ? "완료" : "진행";
      cls = (rawStatus === "good") ? "done" : "inprog";
    } else {
      text = (rawStatus === "good") ? "완료" : (rawStatus === "critical" ? "지연" : "진행");
      cls = (rawStatus === "good") ? "done" : (rawStatus === "critical" ? "delayed" : "inprog");
    }
  } else {
    var loc = String(r.status || "").trim().toLowerCase();
    if(loc.indexOf("완료") !== -1 || loc.indexOf("done") !== -1 || loc.indexOf("hoàn thành") !== -1){
      text = "완료";
      cls = "done";
    } else if(loc.indexOf("검토") !== -1 || loc.indexOf("review") !== -1 || loc.indexOf("kiểm tra") !== -1){
      text = "검토";
      cls = "review";
    } else if(loc.indexOf("진행") !== -1 || loc.indexOf("progress") !== -1 || loc.indexOf("đang") !== -1){
      text = "진행";
      cls = "inprog";
    } else if(loc.indexOf("예정") !== -1 || loc.indexOf("대기") !== -1 || loc.indexOf("todo") !== -1 || loc.indexOf("to do") !== -1 || loc.indexOf("chờ") !== -1){
      text = "예정";
      cls = "todo";
    } else if(r.status){
      text = r.status;
      cls = "inprog";
    } else {
      text = "예정";
      cls = "todo";
    }
  }

  // Đa ngôn ngữ (i18n): Đồng bộ theo ngôn ngữ giao diện đang chọn (KO / EN)
  var localizedText = text;
  if(window.i18n && typeof window.i18n.t === "function"){
    if(cls === "done") localizedText = window.i18n.t("filter.status_done") || text;
    else if(cls === "review") localizedText = window.i18n.t("filter.status_review") || text;
    else if(cls === "inprog") localizedText = window.i18n.t("filter.status_inprog") || text;
    else if(cls === "todo") localizedText = window.i18n.t("filter.status_todo") || text;
    else if(cls === "delayed") localizedText = window.i18n.t("filter.status_delayed") || text;
  }

  var fullTitle = (r.jira && (r.jira.rawStatusName || r.jira.statusName)) ? (r.jira.rawStatusName || r.jira.statusName) : localizedText;
  return '<span class="record-status-badge ' + cls + '" title="상태: ' + escapeHtml(fullTitle) + '">' +
    '<span class="record-status-dot"></span>' +
    '<span>' + escapeHtml(localizedText) + '</span>' +
  '</span>';
}

function isWaiting(r){ return !!(r.jira && r.jira.status !== "good"); }

var selectedDeptForAssignee = null;

function populateAssigneeFilter(deptId){
  var select = el.assigneeFilter || document.getElementById("assigneeFilter");
  if(!select) return;
  var deptRecords = (deptId && deptId !== "all")
    ? records.filter(function(r){ return r.org === deptId; })
    : records;

  var map = {};
  deptRecords.forEach(function(r){
    if(!r.assignee) return;
    var base = assigneeBaseName(r.assignee);
    if(!map[base] || r.assignee.length > map[base].length){
      map[base] = r.assignee;
    }
  });

  var names = Object.keys(map).sort(function(a, b){ return a.localeCompare(b, "ko"); }).map(function(k){ return map[k]; });
  var allAssigneesLabel = (window.i18n && typeof window.i18n.t === "function") ? window.i18n.t("filter.all_assignees") : "전체 담당자";
  var html = '<option value="all">' + escapeHtml(allAssigneesLabel) + '</option>';
  names.forEach(function(name){
    html += '<option value="' + escapeHtml(name) + '">' + escapeHtml(name) + '</option>';
  });
  select.innerHTML = html;
  if(filters.assignee && (filters.assignee === "all" || names.indexOf(filters.assignee) !== -1)){
    select.value = filters.assignee;
  } else {
    filters.assignee = "all";
    select.value = "all";
  }
}

function updateFilterRowUI(){
  var row = el.filterRow || document.getElementById("filterRow");
  if(row){
    row.hidden = false;
    row.style.display = "";
  }

  var isAll = (!selectedDeptForAssignee || selectedDeptForAssignee === "all");
  var chips = el.orgChips || document.getElementById("orgChips");
  var assigneeSelect = el.assigneeFilter || document.getElementById("assigneeFilter");

  if(chips){
    chips.hidden = true;
    chips.style.display = "none";
  }

  if(assigneeSelect){
    assigneeSelect.hidden = true;
    assigneeSelect.style.display = "none";
  }
}

function renderDeptCards(){
  var totalRecs = records.length;
  var totalWaiting = records.filter(isWaiting).length;
  var isAllActive = (!selectedDeptForAssignee || selectedDeptForAssignee === "all");

  var t = (window.i18n && window.i18n.t) ? window.i18n.t : function(k){ return k; };
  var allCardHtml = (
    '<div class="dept-card' + (isAllActive ? " active" : "") + '" data-dept-id="all" style="--tag-color: #64748b">' +
      '<span class="dept-dot"></span>' +
      '<span class="dept-card-text">' +
        '<span class="dept-name">' + escapeHtml(t("dept.all")) + '</span>' +
        '<span class="dept-sub">' + (totalWaiting > 0 ? t("dept.waiting_count", {count: totalWaiting}) : t("dept.no_waiting")) + '</span>' +
      '</span>' +
      '<span class="dept-count">' + totalRecs + '</span>' +
    '</div>'
  );

  var cardsHtml = DEPARTMENTS.map(function(d){
    var recs = records.filter(function(r){ return r.org === d.id; });
    var waiting = recs.filter(isWaiting).length;
    var isActive = (selectedDeptForAssignee === d.id);
    var badgeParts = [];
    if(d.localPrefix) {
      badgeParts.push('<span class="dept-sub-pill" title="Prefix: ' + escapeHtml(d.localPrefix) + '">' + escapeHtml(d.localPrefix) + '</span>');
    }
    if(d.jiraKey && isJiraIntegrationActive()) {
      badgeParts.push('<span class="dept-sub-pill jira" title="Jira: ' + escapeHtml(d.jiraKey) + '">' + escapeHtml(d.jiraKey) + '</span>');
    }
    var badgesHtml = badgeParts.length ? ('<span class="dept-sub-badges">' + badgeParts.join("") + '</span>') : "";
    var waitText = (waiting > 0 ? t("dept.waiting_count", {count: waiting}) : t("dept.no_waiting"));

    return (
      '<div class="dept-card' + (isActive ? " active" : "") + '" data-dept-id="' + escapeHtml(d.id) + '" style="--tag-color:' + colorVar(d.colorIndex) + '">' +
        '<span class="dept-dot"></span>' +
        '<span class="dept-card-text">' +
          '<span class="dept-name">' + escapeHtml(d.name) + '</span>' +
          '<span class="dept-sub">' + badgesHtml + '<span class="dept-wait-text">' + escapeHtml(waitText) + '</span></span>' +
        '</span>' +
        '<span class="dept-count">' + recs.length + '</span>' +
      '</div>'
    );
  }).join("");

  var addHtml = "";
  if(typeof isCurrentUserAdmin === "function" && isCurrentUserAdmin()){
    addHtml = '<button type="button" class="dept-add-card" id="deptAddBtn" title="' + escapeHtml(t("dept.add_title")) + '">' + escapeHtml(t("dept.add_btn")) + '</button>';
  }

  el.deptCards.innerHTML = allCardHtml + cardsHtml + addHtml;
  updateFilterRowUI();
}

var TITLE_SUFFIXES = [
  "대표이사", "부사장", "전무이사", "상무이사", "전무", "상무", "이사",
  "실장", "소장", "본부장", "팀장", "부장", "차장", "과장", "대리", "주임", "사원",
  "선임연구원", "책임연구원", "수석연구원", "연구원", "선임", "수석"
];
function assigneeBaseName(name){
  name = (name || "").trim();
  for(var i = 0; i < TITLE_SUFFIXES.length; i++){
    var suf = TITLE_SUFFIXES[i];
    if(name.length > suf.length && name.slice(name.length - suf.length) === suf){
      var head = name.slice(0, name.length - suf.length).trim();
      if(head) return head;
    }
  }
  return name;
}

function getRecordProgressCategory(r){
  if(r.jira){
    var rawName = (r.jira.statusName || "").trim();
    var rawStatus = (r.jira.status || "").toLowerCase();

    if(rawName.includes("완료") || rawName.toLowerCase() === "done" || rawStatus === "good"){
      return "done";
    }
    if(rawName.includes("검토") || rawName.toLowerCase().includes("review") || rawName.toLowerCase().includes("testing") || rawName.includes("kiểm tra")){
      return "review";
    }
    if(rawName.includes("예정") || rawName.includes("할 일") || rawName.includes("준비") || rawName.includes("대기") || rawName.toLowerCase().includes("todo")){
      return "todo";
    }
    return "inprog";
  }
  var loc = String(r.status || "").trim().toLowerCase();
  if(loc.indexOf("완료") !== -1 || loc.indexOf("done") !== -1){
    return "done";
  }
  if(loc.indexOf("검토") !== -1 || loc.indexOf("review") !== -1 || loc.indexOf("kiểm tra") !== -1){
    return "review";
  }
  if(loc.indexOf("진행") !== -1 || loc.indexOf("progress") !== -1){
    return "inprog";
  }
  if(loc.indexOf("예정") !== -1 || loc.indexOf("대기") !== -1 || loc.indexOf("todo") !== -1){
    return "todo";
  }
  return "inprog";
}

function enableHorizontalDragScroll(container){
  if(!container || container._dragScrollAttached) return;
  container._dragScrollAttached = true;
  var isDown = false;
  var startX = 0;
  var scrollLeft = 0;
  var hasMoved = false;

  container.addEventListener("mousedown", function(e){
    if(e.button !== 0) return;
    isDown = true;
    hasMoved = false;
    startX = e.pageX - container.offsetLeft;
    scrollLeft = container.scrollLeft;
  });

  window.addEventListener("mousemove", function(e){
    if(!isDown) return;
    var x = e.pageX - container.offsetLeft;
    var walk = (x - startX);
    if(Math.abs(walk) > 4){
      hasMoved = true;
      container.classList.add("is-dragging");
      container.scrollLeft = scrollLeft - walk;
    }
  });

  window.addEventListener("mouseup", function(){
    if(!isDown) return;
    isDown = false;
    container.classList.remove("is-dragging");
    if(hasMoved){
      setTimeout(function(){ hasMoved = false; }, 50);
    }
  });

  container.addEventListener("wheel", function(e){
    if(e.deltaY !== 0){
      e.preventDefault();
      container.scrollLeft += e.deltaY;
    }
  }, { passive: false });
}

function getAssigneeColor(name){
  var str = String(name || "").trim();
  if(!str || str === "미배정" || str === "Unassigned" || str === "미할당"){
    return "#64748b"; // Neutral slate gray for unassigned
  }
  var palette = [
    "#2563eb", // Blue
    "#059669", // Emerald
    "#7c3aed", // Purple
    "#d97706", // Amber
    "#e11d48", // Rose
    "#0891b2", // Teal
    "#ea580c", // Orange
    "#4f46e5", // Indigo
    "#db2777", // Pink
    "#0d9488", // Dark Teal
    "#65a30d", // Lime
    "#9333ea"  // Violet
  ];
  var hash = 0;
  for(var i = 0; i < str.length; i++){
    hash = str.charCodeAt(i) + ((hash << 5) - hash);
  }
  return palette[Math.abs(hash) % palette.length];
}

function renderAssigneeTable(){
  var map = {};

  // Pre-seed registered company members so all team members appear in workload overview
  if(window.__companyMembers && Array.isArray(window.__companyMembers)){
    window.__companyMembers.forEach(function(m){
      if(!m || !m.name) return;
      if(selectedDeptForAssignee && m.org && m.org !== selectedDeptForAssignee) return;
      var key = assigneeBaseName(m.name);
      if(!map[key]){
        map[key] = {
          name: m.name,
          avatarUrl: m.avatarUrl || "",
          org: m.org || "",
          count: 0,
          activeCount: 0,
          cats: {},
          done: 0,
          review: 0,
          inprog: 0,
          todo: 0
        };
      }
    });
  }

  var targetRecords = selectedDeptForAssignee
    ? records.filter(function(r){ return r.org === selectedDeptForAssignee; })
    : records;

  targetRecords.forEach(function(r){
    if(!r.assignee) return;
    var key = assigneeBaseName(r.assignee);
    if(!map[key]){
      map[key] = {
        name: r.assignee,
        avatarUrl: r.assigneeAvatar || (r.jira && r.jira.assigneeAvatar) || r.avatarUrl || "",
        org: r.org,
        count: 0,
        activeCount: 0,
        cats: {},
        done: 0,
        review: 0,
        inprog: 0,
        todo: 0
      };
    }
    var a = map[key];
    if(r.assignee.length > a.name.length){ a.name = r.assignee; }
    if(!a.avatarUrl && (r.assigneeAvatar || (r.jira && r.jira.assigneeAvatar) || r.avatarUrl)){
      a.avatarUrl = r.assigneeAvatar || (r.jira && r.jira.assigneeAvatar) || r.avatarUrl;
    }
    a.count += 1;
    a.cats[r.category || "미분류"] = (a.cats[r.category || "미분류"] || 0) + 1;

    var cat = getRecordProgressCategory(r);
    if(cat === "done"){
      a.done += 1;
    } else {
      a.activeCount += 1;
      if(cat === "review") a.review += 1;
      else if(cat === "inprog") a.inprog += 1;
      else a.todo += 1;
    }
  });
  var rows = Object.keys(map).map(function(k){ return map[k]; }).sort(function(x, y){
    if(y.count !== x.count) return y.count - x.count;
    return y.activeCount - x.activeCount;
  });

  var labelEl = document.getElementById("assigneePanelLabel");
  var baseAssigneeTitle = (window.i18n && typeof window.i18n.t === "function") ? window.i18n.t("filter.assignee_panel_title") : "담당자별 현황";
  if(labelEl){
    if(selectedDeptForAssignee){
      var d = deptById(selectedDeptForAssignee);
      var deptName = d ? d.name : selectedDeptForAssignee;
      labelEl.innerHTML = escapeHtml(baseAssigneeTitle) + ' <span style="font-size:11.5px;font-weight:600;color:var(--accent-2);margin-left:6px;">(' + escapeHtml(deptName) + ')</span>';
    } else {
      labelEl.textContent = baseAssigneeTitle;
    }
  }

  var barEl = el.assigneeBar || document.getElementById("assigneeBar");
  var countBadgeEl = el.assigneeCountBadge || document.getElementById("assigneeCountBadge");
  if(countBadgeEl){
    countBadgeEl.textContent = (window.i18n && typeof window.i18n.t === "function")
      ? window.i18n.t("common.person_count", {count: rows.length})
      : (rows.length + "명");
  }

  if(rows.length === 0){
    var emptyMsg = (window.i18n && typeof window.i18n.t === "function")
      ? window.i18n.t("filter.assignee_empty")
      : "선택한 부서의 담당자 현황 데이터가 없습니다.";
    if(barEl){
      barEl.innerHTML = '<span style="font-size:12px;color:var(--ink-faint);padding:6px 0;">' + escapeHtml(emptyMsg) + '</span>';
    }
    if(el.assigneeBody){
      el.assigneeBody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--ink-faint);padding:24px 10px;">' + escapeHtml(emptyMsg) + '</td></tr>';
    }
    return;
  }

  var barHtml = "";

  var sDone = (window.i18n && typeof window.i18n.t === "function") ? window.i18n.t("filter.status_done") : "완료";
  var sReview = (window.i18n && typeof window.i18n.t === "function") ? window.i18n.t("filter.status_review") : "검토";
  var sInprog = (window.i18n && typeof window.i18n.t === "function") ? window.i18n.t("filter.status_inprog") : "진행";
  var sTodo = (window.i18n && typeof window.i18n.t === "function") ? window.i18n.t("filter.status_todo") : "대기";
  var sWeightedProgress = (window.i18n && typeof window.i18n.t === "function") ? window.i18n.t("filter.weighted_progress") : "가중 진행률";
  var sZeroTasks = (window.i18n && typeof window.i18n.t === "function") ? window.i18n.t("common.zero_items") : "0건";

  var tableRowsHtml = rows.map(function(a){
    var cats = Object.keys(a.cats).sort(function(x, y){ return a.cats[y] - a.cats[x]; });
    var shown = cats.slice(0, 3).map(function(c){ return '<span class="tag">' + escapeHtml(c) + '</span>'; }).join("");
    var overflow = cats.length > 3 ? '<span class="tag">+' + (cats.length - 3) + '</span>' : "";
    var dept = deptById(a.org);
    var isSelected = (filters.assignee && filters.assignee !== "all" && (assigneeBaseName(a.name) === assigneeBaseName(filters.assignee)));

    // Weighted progress: 완료 = 1.0 (100%), 검토 = 0.8 (80%), 진행 = 0.5 (50%), 대기 = 0.0 (0%)
    var weightedScore = (a.done * 1.0) + (a.review * 0.8) + (a.inprog * 0.5) + (a.todo * 0.0);
    var overallPct = a.count > 0 ? Math.round((weightedScore / a.count) * 100) : 0;

    var pctDone = a.count > 0 ? (a.done / a.count) * 100 : 0;
    var pctReview = a.count > 0 ? (a.review / a.count) * 100 : 0;
    var pctInprog = a.count > 0 ? (a.inprog / a.count) * 100 : 0;

    var stop1 = pctDone;
    var stop2 = pctDone + pctReview;
    var stop3 = pctDone + pctReview + pctInprog;

    var donutBg = a.count === 0
      ? "var(--line-strong, #cbd5e1)"
      : "conic-gradient(#10b981 0% " + stop1 + "%, #3b82f6 " + stop1 + "% " + stop2 + "%, #f59e0b " + stop2 + "% " + stop3 + "%, var(--line-strong, #94a3b8) " + stop3 + "% 100%)";

    var numColor = overallPct >= 80 ? "#10b981" : (overallPct >= 50 ? "#3b82f6" : (overallPct >= 25 ? "#f59e0b" : "var(--ink-faint)"));

    var assignedText = (window.i18n && typeof window.i18n.t === "function")
      ? window.i18n.t("filter.assigned_count", {count: a.count})
      : ("담당 " + a.count + "건");

    var tooltip = a.name + " (" + dept.name + ") · " + assignedText + " (" + sDone + " " + a.done + ", " + sReview + " " + a.review + ", " + sInprog + " " + a.inprog + ", " + sTodo + " " + a.todo + ") · " + sWeightedProgress + " " + overallPct + "%";

    var isUnassignedUser = (!a.name || a.name === "미배정" || a.name === "Unassigned" || a.name === "미할당");
    var initial = isUnassignedUser ? "?" : a.name.trim().charAt(0);
    // Choivis UX: chỉ khi được chọn (active) mới mở rộng hiện đủ họ tên. Khi chưa chọn thì thu gọn chỉ hiện Avatar và Số
    var nameHtml = isSelected ? '<span class="pill-name">' + escapeHtml(a.name) + '</span>' : '';
    var isAllDept = (!selectedDeptForAssignee || selectedDeptForAssignee === "all");
    var deptColor = colorVar(dept.colorIndex);
    var avatarColor = getAssigneeColor(a.name);
    var avatarUrl = a.avatarUrl || "";
    var isCustomAvatar = Boolean(!isUnassignedUser && avatarUrl && avatarUrl.indexOf("default-avatar") === -1 && avatarUrl.indexOf("default/") === -1);

    barHtml += '<div class="assignee-pill-item' + (isSelected ? ' active' : '') + (isAllDept ? ' colored-border' : '') + '" data-assignee="' + escapeHtml(a.name) + '" style="--dept-color:' + deptColor + ';--avatar-color:' + avatarColor + ';" title="' + escapeHtml(tooltip) + '">' +
      '<div class="pill-avatar" style="background:' + avatarColor + ';">' +
        (isCustomAvatar ? '<img src="' + escapeHtml(avatarUrl) + '" alt="" class="pill-avatar-img" onerror="this.remove();">' : '') +
        '<span class="pill-avatar-initial">' + escapeHtml(initial) + '</span>' +
      '</div>' +
      nameHtml +
      '<span class="pill-count" title="' + escapeHtml(assignedText) + '">' + a.count + '</span>' +
    '</div>';

    var breakdown = [];
    if(a.done > 0) breakdown.push('<span class="pg-item pg-done">' + escapeHtml(sDone) + ' ' + a.done + '</span>');
    if(a.review > 0) breakdown.push('<span class="pg-item pg-review">' + escapeHtml(sReview) + ' ' + a.review + '</span>');
    if(a.inprog > 0) breakdown.push('<span class="pg-item pg-inprog">' + escapeHtml(sInprog) + ' ' + a.inprog + '</span>');
    if(a.todo > 0) breakdown.push('<span class="pg-item pg-todo">' + escapeHtml(sTodo) + ' ' + a.todo + '</span>');
    if(breakdown.length === 0) breakdown.push('<span class="pg-item pg-todo">' + escapeHtml(sZeroTasks) + '</span>');

    return (
      '<tr class="assignee-row' + (isSelected ? " selected" : "") + '" data-assignee="' + escapeHtml(a.name) + '" style="cursor:pointer;' + (isSelected ? 'background:var(--accent-2-soft);' : '') + '">' +
        '<td class="assignee-name">' + escapeHtml(a.name) + '</td>' +
        '<td class="assignee-col-org"><span class="org-tag" style="--tag-color:' + colorVar(dept.colorIndex) + '">' + escapeHtml(dept.name) + '</span></td>' +
        '<td class="num assignee-col-count" title="' + escapeHtml(assignedText + " (" + sDone + " " + a.done + ", " + sReview + " " + a.review + ", " + sInprog + " " + a.inprog + ", " + sTodo + " " + a.todo + ")") + '">' + a.count + '</td>' +
        '<td class="assignee-col-cats"><div class="assignee-cat-tags">' + shown + overflow + '</div></td>' +
        '<td class="assignee-col-progress">' +
          '<div class="assignee-progress-cell" title="' + escapeHtml(tooltip) + '">' +
            '<div class="assignee-donut-wrap">' +
              '<div class="assignee-donut-pie" style="background:' + donutBg + ';"></div>' +
              '<div class="assignee-donut-hole">' +
                '<span class="assignee-donut-num" style="color:' + numColor + ';">' + overallPct + '%</span>' +
              '</div>' +
            '</div>' +
            '<div class="assignee-progress-breakdown">' +
              breakdown.join('<span style="color:var(--line-strong);margin:0 2px;">·</span>') +
            '</div>' +
          '</div>' +
        '</td>' +
      '</tr>'
    );
  }).join("");

  if(barEl){
    barEl.innerHTML = barHtml;
    enableHorizontalDragScroll(barEl);
  }
  if(el.assigneeBody){
    el.assigneeBody.innerHTML = tableRowsHtml;
  }
}

function recordMatchesQuery(r, query){
  if(!query) return true;
  var rawQuery = String(query).toLowerCase().trim();
  if(!rawQuery) return true;

  var key = ((r.jira && r.jira.key) || r.unlinked_jira_key || r.key || (r.id ? ("REC-" + r.id) : "")).toLowerCase();
  var title = (r.title || "").toLowerCase();
  var summary = (r.summary || r.memo || "").toLowerCase();
  var project = (r.project || "").toLowerCase();
  var assignee = (r.assignee || "").toLowerCase();
  var participants = (r.participants || "").toLowerCase();
  var idStr = (r.id ? String(r.id) : "");

  var hay = (title + " " + summary + " " + project + " " + key + " " + assignee + " " + participants + " " + (idStr ? ("#" + idStr + " " + idStr) : "")).toLowerCase();

  var cleanKey = key.replace(/[^a-z0-9가-힣\u00C0-\u024F\u1EA0-\u1EF9]/gi, '');
  var cleanTitle = title.replace(/[^a-z0-9가-힣\u00C0-\u024F\u1EA0-\u1EF9]/gi, '');

  var tokens = rawQuery.split(/\s+/).filter(Boolean);

  var allTokensMatch = tokens.every(function(token){
    // 1. Direct substring match in combined fields
    if(hay.indexOf(token) !== -1) return true;

    // 2. Normalized alphanumeric match for keys, titles, IDs (e.g. "vs52" matches "VS-52")
    var cleanToken = token.replace(/[^a-z0-9가-힣\u00C0-\u024F\u1EA0-\u1EF9]/gi, '');
    if(cleanToken){
      if(cleanKey && cleanKey.indexOf(cleanToken) !== -1) return true;
      if(cleanToken.length >= 2 && cleanTitle && cleanTitle.indexOf(cleanToken) !== -1) return true;
      if(idStr && cleanToken === idStr) return true;
    }

    // 3. Issue key with leading zero tolerance (e.g. "vs052" vs "VS-52")
    var termParts = token.match(/^([a-z]+)[-\s]*0*(\d+)$/);
    var keyParts = key.match(/^([a-z]+)[-\s]*0*(\d+)$/);
    if(termParts && keyParts && termParts[1] === keyParts[1] && parseInt(termParts[2], 10) === parseInt(keyParts[2], 10)){
      return true;
    }

    return false;
  });

  if(allTokensMatch) return true;

  // 4. Normalized full query match (e.g. user typed "vs 52", cleanRaw is "vs52" which matches "vs52")
  var cleanRaw = rawQuery.replace(/[^a-z0-9가-힣\u00C0-\u024F\u1EA0-\u1EF9]/gi, '');
  if(cleanRaw && cleanKey && cleanKey.indexOf(cleanRaw) !== -1) return true;
  if(cleanRaw && cleanRaw.length >= 2 && cleanTitle && cleanTitle.indexOf(cleanRaw) !== -1) return true;

  return false;
}

function matchesFilters(r){
  if(filters.org !== "all" && r.org !== filters.org) return false;
  if(filters.assignee && filters.assignee !== "all"){
    var targetBase = assigneeBaseName(filters.assignee);
    var recordBase = assigneeBaseName(r.assignee);
    var isAssigneeMatched = (targetBase === recordBase || r.assignee === filters.assignee);

    // Also match if user is in participants list
    var isParticipantMatched = false;
    if(r.participants){
      var parts = String(r.participants).split(/[,;/]+/).map(function(s){ return s.trim(); });
      isParticipantMatched = parts.some(function(p){
        return p === filters.assignee || assigneeBaseName(p) === targetBase;
      });
    }

    if(!isAssigneeMatched && !isParticipantMatched) return false;
  }
  if(filters.cat !== "all" && r.category !== filters.cat) return false;
  if(filters.status && filters.status !== "all"){
    var cat = getRecordProgressCategory(r); // "done", "review", "inprog", "todo"
    if(filters.status === "완료"){
      if(cat !== "done") return false;
    } else if(filters.status === "검토"){
      if(cat !== "review") return false;
    } else if(filters.status === "진행"){
      if(cat !== "inprog") return false;
    } else if(filters.status === "예정"){
      if(cat !== "todo") return false;
    }
  }
  if(filters.q){
    if(recordMatchesQuery(r, filters.q)) return true;

    // Subtask recursive search: Thẻ cha hiển thị nếu có bất kỳ thẻ con nào khớp tìm kiếm
    var key = (r.jira && r.jira.key) ? r.jira.key : (r.unlinked_jira_key ? r.unlinked_jira_key : ("rec-" + r.id));
    var allPool = (typeof records !== "undefined" && Array.isArray(records)) ? records : [];
    var hasMatchingChild = allPool.some(function(child){
      var pk = child.parentKey || (child.jira && child.jira.parentKey);
      var pId = child.parentId;
      var isDirectChild = (pk && (pk === key || pk === (r.jira && r.jira.key))) || (pId && (pId === r.id));
      return isDirectChild && recordMatchesQuery(child, filters.q);
    });
    if(hasMatchingChild) return true;

    return false;
  }
  return true;
}

window.expandedTreeKeys = window.expandedTreeKeys || new Set();
window.treeExpandedAll = false;

window.toggleTreeItem = function(key){
  if(window.expandedTreeKeys.has(key)){
    window.expandedTreeKeys.delete(key);
  } else {
    window.expandedTreeKeys.add(key);
  }
  var btn = document.getElementById("tree-btn-" + key);
  var childrenWrap = document.getElementById("tree-children-" + key);
  if(btn && childrenWrap){
    var isOpen = window.expandedTreeKeys.has(key);
    btn.classList.toggle("expanded", isOpen);
    childrenWrap.hidden = !isOpen;
  }
};

window.toggleAllTreeItems = function(){
  window.treeExpandedAll = !window.treeExpandedAll;
  var btn = el.btnToggleTree || document.getElementById("btnToggleTree");
  if(btn){
    btn.textContent = (window.i18n && typeof window.i18n.t === "function")
      ? window.i18n.t(window.treeExpandedAll ? "filter.collapse_all" : "filter.expand_all")
      : (window.treeExpandedAll ? "📁 모두 접기" : "📂 모두 펼치기");
  }
  document.querySelectorAll(".tree-children-wrap").forEach(function(wrap){
    wrap.hidden = !window.treeExpandedAll;
    var key = wrap.getAttribute("data-tree-key");
    if(key){
      if(window.treeExpandedAll) window.expandedTreeKeys.add(key);
      else window.expandedTreeKeys.delete(key);
      var toggleBtn = document.getElementById("tree-btn-" + key);
      if(toggleBtn) toggleBtn.classList.toggle("expanded", window.treeExpandedAll);
    }
  });
};

function buildRecordsTree(list){
  var byKey = {};
  var byId = {};
  list.forEach(function(r){
    var key = (r.jira && r.jira.key) ? r.jira.key : (r.cardCode || (r.unlinked_jira_key ? r.unlinked_jira_key : ("rec-" + r.id)));
    r._treeKey = key;
    r._children = [];
    byKey[key] = r;
    byKey[key.toUpperCase()] = r;
    if(r.jira && r.jira.key){
      byKey[r.jira.key.toUpperCase()] = r;
    }
    if(r.cardCode){
      byKey[r.cardCode.toUpperCase()] = r;
      byKey[r.cardCode.replace(/^#/, "").toUpperCase()] = r;
    }
    if(r.id){
      byId[r.id] = r;
      byKey[String(r.id)] = r;
      byKey["rec-" + r.id] = r;
      byKey["#" + r.id] = r;
    }
  });

  var childKeys = new Set();
  list.forEach(function(r){
    var pKey = r.parentKey || (r.jira && r.jira.parentKey);
    var parentRecord = null;
    if(pKey){
      var cleanP = String(pKey).trim().toUpperCase();
      parentRecord = byKey[pKey] || byKey[cleanP] || byKey[cleanP.replace(/^#/, "")] || byKey[cleanP.replace(/^REC-/, "")];
    }
    if(!parentRecord && r.parentId){
      parentRecord = byId[r.parentId] || byKey[String(r.parentId)];
    }

    if(parentRecord && parentRecord !== r){
      parentRecord._children.push(r);
      childKeys.add(r._treeKey);
    }
  });

  var roots = list.filter(function(r){
    return !childKeys.has(r._treeKey);
  });
  return roots;
}

window.currentCanvasIssueKey = window.currentCanvasIssueKey || null;

window.highlightActiveCanvasCard = function(activeKey){
  window.currentCanvasIssueKey = activeKey || null;
  document.querySelectorAll(".record.canvas-active-card").forEach(function(el){
    el.classList.remove("canvas-active-card");
  });
  if(!activeKey) return;

  var clean = String(activeKey).trim().toUpperCase().replace(/^#/, "").replace(/^REC-/, "").replace(/^JIRA-/, "");
  var matchedCards = [];
  document.querySelectorAll(".record").forEach(function(el){
    var k = (el.getAttribute("data-card-key") || "").trim().toUpperCase().replace(/^#/, "").replace(/^REC-/, "").replace(/^JIRA-/, "");
    var rid = (el.getAttribute("data-record-id") || "").trim().toUpperCase().replace(/^#/, "").replace(/^REC-/, "").replace(/^JIRA-/, "");
    if((k && k === clean) || (rid && rid === clean)){
      el.classList.add("canvas-active-card");
      matchedCards.push(el);
      // Auto-expand parent tree if child is selected
      var parentWrap = el.closest(".tree-children-wrap");
      if(parentWrap && parentWrap.hidden){
        parentWrap.hidden = false;
        var pKey = parentWrap.getAttribute("data-tree-key");
        if(pKey){
          window.expandedTreeKeys.add(pKey);
          var btn = document.getElementById("tree-btn-" + pKey);
          if(btn) btn.classList.add("expanded");
        }
      }
    }
  });

  if(matchedCards.length > 0){
    try {
      matchedCards[0].scrollIntoView({ behavior: "smooth", block: "nearest" });
    } catch(e){}
  }
};

window.handleRecordCardClick = function(event, rowEl){
  if(event && event.target && event.target.closest("a, button, input, select, textarea")){
    return;
  }
  if(!rowEl) return;
  var cardKey = rowEl.getAttribute("data-card-key") || "";
  var safeKey = rowEl.getAttribute("data-safe-key") || "";
  var hasChildren = rowEl.getAttribute("data-has-children") === "true";

  // 1. Luôn mở nội dung thẻ trên Canvas
  if(cardKey && typeof window.showIssueInCanvas === "function"){
    window.showIssueInCanvas(cardKey);
  }

  // 2. Nếu có thẻ con thì toggle đóng/mở (nếu đang mở thì thu, nếu đang thu thì mở)
  if(hasChildren && safeKey && typeof window.toggleTreeItem === "function"){
    window.toggleTreeItem(safeKey);
  }
};

function renderSingleRecordCard(r, isChild, highlightId){
  var flash = (r.id === highlightId) ? " flash" : "";
  var dept = deptById(r.org);
  var cardCode = (r.jira && r.jira.key) ? r.jira.key : (r.cardCode || (r.unlinked_jira_key ? r.unlinked_jira_key : (r.id ? ("#" + r.id) : (dept.name || "CARD"))));
  var hasChildren = (r._children && r._children.length > 0);
  var isOpen = window.expandedTreeKeys.has(r._treeKey) || window.treeExpandedAll || Boolean(filters.q);
  var safeKey = (r._treeKey || "").replace(/[^a-zA-Z0-9_-]/g, "");

  var toggleBtnHtml = "";
  if(hasChildren){
    var subtaskTitle = (window.i18n && typeof window.i18n.t === "function")
      ? window.i18n.t("card.subtask_title", {count: r._children.length})
      : ("하위 작업 " + r._children.length + "건 펼치기/접기");
    toggleBtnHtml = (
      '<button type="button" class="tree-toggle-btn' + (isOpen ? ' expanded' : '') + '" id="tree-btn-' + safeKey + '" onclick="event.preventDefault(); event.stopPropagation(); window.toggleTreeItem(\'' + safeKey + '\');" title="' + escapeHtml(subtaskTitle) + '">' +
        '<span class="tree-chevron">▶</span>' +
      '</button>'
    );
  } else {
    toggleBtnHtml = (
      '<span class="tree-toggle-btn tree-toggle-spacer"><span class="tree-leaf-dot">•</span></span>'
    );
  }

  var subtaskCount = (r._children && r._children.length > 0)
    ? r._children.length
    : (r._totalSubtasksCount || 0);

  var subtaskHint = (window.i18n && typeof window.i18n.t === "function")
    ? window.i18n.t("card.subtask_hint", {count: subtaskCount})
    : ("하위 작업 " + subtaskCount + "건 (클릭하여 캔버스에서 확인)");
  var subtaskBadgeText = (window.i18n && typeof window.i18n.t === "function")
    ? window.i18n.t("card.subtask_badge", {count: subtaskCount})
    : ("하위 " + subtaskCount + "건");

  var countBadgeHtml = (subtaskCount > 0)
    ? '<span class="badge-subtask-count" title="' + escapeHtml(subtaskHint) + '">' + escapeHtml(subtaskBadgeText) + '</span>'
    : '';

  // Resolve parent title/summary
  var parentTitle = (r.parentSummary || "").trim();
  if(!parentTitle && r.parentKey && typeof records !== "undefined" && Array.isArray(records)){
    var cleanPk = String(r.parentKey).trim().toUpperCase();
    for(var pi = 0; pi < records.length; pi++){
      var pCandidate = records[pi];
      var pJKey = (pCandidate.jira && pCandidate.jira.key ? String(pCandidate.jira.key).toUpperCase() : "");
      var pCode = (pCandidate.cardCode ? String(pCandidate.cardCode).toUpperCase().replace(/^#/, "") : "");
      var pId = String(pCandidate.id || "");
      if(cleanPk === pJKey || cleanPk === pCode || cleanPk === pId || cleanPk === ("REC-" + pId) || cleanPk === ("#" + pId)){
        parentTitle = (pCandidate.title || (pCandidate.jira && pCandidate.jira.summary) || "").trim();
        if(parentTitle) {
          r.parentSummary = parentTitle;
          break;
        }
      }
    }
  }

  var parentRefHtml = "";
  if(r.parentKey && !isChild){
    var maxParentTitleLen = 22;
    var parentTitleShort = parentTitle ? (parentTitle.length > maxParentTitleLen ? (parentTitle.slice(0, maxParentTitleLen).trim() + "...") : parentTitle) : "";
    var parentTitleLabel = parentTitleShort ? (" (" + escapeHtml(parentTitleShort) + ")") : "";

    var parentTooltip = (window.i18n && typeof window.i18n.t === "function")
      ? (window.i18n.t("card.parent_ref", {key: r.parentKey}) + (parentTitle ? (" (" + parentTitle + ")") : "") + " (" + window.i18n.t("card.click_to_open_canvas") + ")")
      : ("상위 작업: " + r.parentKey + (parentTitle ? (" (" + parentTitle + ")") : "") + " (클릭하여 캔버스 열기)");

    var parentPrefix = (window.i18n && typeof window.i18n.t === "function")
      ? (window.i18n.t("card.parent_prefix") || "상위:")
      : "상위:";

    parentRefHtml = '<span class="badge-parent-ref" title="' + escapeHtml(parentTooltip) + '" onclick="window.showIssueInCanvas(\'' + escapeHtml(r.parentKey).replace(/'/g, "\\'") + '\'); event.stopPropagation();" style="cursor:pointer;">' +
      '<span class="parent-ref-prefix">' + escapeHtml(parentPrefix) + '</span> ' +
      '<strong class="parent-ref-key">' + escapeHtml(r.parentKey) + '</strong>' +
      (parentTitleShort ? (' <span class="parent-ref-title">' + parentTitleLabel + '</span>') : '') +
    '</span>';
  }

  var attachHtml = (r.attachments && r.attachments.length)
    ? '<div class="field"><b>첨부</b>' + r.attachments.map(escapeHtml).join(", ") + '</div>' : "";
  var jiraLinkHtml = (r.jira && r.jira.url)
    ? '<div class="field"><b>Jira</b><a href="' + r.jira.url + '" target="_blank" rel="noopener">' + r.jira.key + '</a></div>'
    : (r.unlinked_jira_key
        ? '<div class="field"><b>Jira</b>' + escapeHtml(r.unlinked_jira_key) + ' (Jira 미연동)</div>'
        : '<div class="field"><b>Jira</b>연결 없음</div>');

  var cardKey = (r.jira && r.jira.key) ? r.jira.key : (r.cardCode || (r.unlinked_jira_key ? r.unlinked_jira_key : (r.key || (r.id ? String(r.id) : ""))));

  var cleanActiveKey = (window.currentCanvasIssueKey || "").trim().toUpperCase().replace(/^#/, "").replace(/^REC-/, "").replace(/^JIRA-/, "");
  var cleanCardKey = (cardKey || "").trim().toUpperCase().replace(/^#/, "").replace(/^REC-/, "").replace(/^JIRA-/, "");
  var cleanRecId = String(r.id || "").trim().toUpperCase().replace(/^#/, "").replace(/^REC-/, "").replace(/^JIRA-/, "");
  var isActiveCard = Boolean(cleanActiveKey && (cleanActiveKey === cleanCardKey || cleanActiveKey === cleanRecId));

  var unassignedText = (window.i18n && typeof window.i18n.t === "function") ? window.i18n.t("common.unassigned") : "미배정";
  var isUnassignedRec = (!r.assignee || r.assignee === "미배정" || r.assignee === "Unassigned" || r.assignee === "미할당");
  var assigneeLabelHtml = isUnassignedRec 
    ? '<span style="color:#64748b; font-weight:600;">❓ ' + escapeHtml(unassignedText) + '</span>' 
    : escapeHtml(r.assignee);

  var participantsBadgeHtml = "";
  if(r.participants){
    var pList = String(r.participants).split(/[,;/]+/).map(function(s){ return s.trim(); }).filter(Boolean);
    if(pList.length > 0){
      var partTitle = (window.i18n && typeof window.i18n.t === "function")
        ? window.i18n.t("card.participants_title", {list: escapeHtml(pList.join(', '))})
        : ("참여자: " + escapeHtml(pList.join(', ')));
      var partCount = (window.i18n && typeof window.i18n.t === "function")
        ? window.i18n.t("common.person_count", {count: pList.length})
        : (pList.length + '명');
      participantsBadgeHtml = ' <span class="badge-participants" style="display:inline-flex; align-items:center; gap:3px; font-size:11px; color:var(--text-cyan, #0ea5e9); background:rgba(14,165,233,0.08); padding:1px 6px; border-radius:4px; font-weight:600;" title="' + escapeHtml(partTitle) + '">👥 +' + escapeHtml(partCount) + '</span>';
    }
  }

  // Tối ưu thông tin thẻ: Loại bỏ các thông tin dư thừa
  var isAssigneeView = (dashViewMode === "assignee" || (el.dashViewMode && el.dashViewMode.value === "assignee"));
  var metaParts = [];
  if(r.category && r.category !== "분류 대기"){
    metaParts.push('<span class="cat">' + escapeHtml(r.category) + '</span>');
  }

  // Mức độ ưu tiên (chỉ đổi màu chữ theo mức độ, không icon, không nhãn)
  var rawPrio = r.priority || (r.jira && r.jira.priority) || "보통";
  var prioVal = (typeof formatPriority === "function") ? formatPriority(rawPrio) : rawPrio;
  var prioColor = (prioVal === "낮음") ? "#22c55e" : (prioVal === "높음" ? "#f97316" : (prioVal === "긴급" ? "#ef4444" : "#eab308"));
  metaParts.push('<span class="prio-text" style="color:' + prioColor + '; font-weight:600;">' + escapeHtml(prioVal) + '</span>');

  // Tên dự án: chỉ hiển thị nếu có dự án cụ thể và KHÔNG PHẢI là ARGOS WORKS / 프로젝트 미지정 (vì đây là tên hệ thống/mặc định dư thừa)
  var pName = (r.project || "").trim();
  if(pName && pName.toUpperCase() !== "ARGOS WORKS" && pName !== "프로젝트 미지정" && pName.toUpperCase() !== "ARGOS"){
    metaParts.push('<span class="prj">' + escapeHtml(pName) + '</span>');
  }

  // Người phụ trách: Ở chế độ xem theo người phụ trách (Assignee view) thì đã có tiêu đề nhóm của người đó rồi -> Ẩn đi để tránh lặp dư thừa
  if(!isAssigneeView && assigneeLabelHtml){
    metaParts.push(assigneeLabelHtml);
  }

  var metaContentHtml = "";
  if(metaParts.length > 0 || participantsBadgeHtml){
    metaContentHtml = '<span class="meta">' + (metaParts.length > 0 ? metaParts.join(' · ') : '') + participantsBadgeHtml + '</span>';
  }

  var openCanvasHint = (window.i18n && typeof window.i18n.t === "function") ? (" (" + window.i18n.t("card.click_to_open_canvas") + ")") : " (클릭하여 캔버스 열기)";

  return (
    '<div class="record' + flash + (isChild ? ' child-record' : '') + (isActiveCard ? ' canvas-active-card' : '') + '" id="rec-' + safeKey + '" data-card-key="' + escapeHtml(cardKey) + '" data-record-id="' + escapeHtml(String(r.id || '')) + '">' +
      '<div class="record-row" onclick="window.handleRecordCardClick(event, this);" data-card-key="' + escapeHtml(cardKey) + '" data-safe-key="' + escapeHtml(safeKey) + '" data-has-children="' + hasChildren + '" style="cursor:pointer;">' +
        toggleBtnHtml +
        '<span class="record-card-code org-tag" title="' + escapeHtml(dept.name) + (cardKey ? openCanvasHint : '') + '">' + escapeHtml(cardCode) + '</span>' +
        '<span class="record-main">' +
          '<span class="title">' + escapeHtml(r.title) + countBadgeHtml + parentRefHtml + '</span>' +
          metaContentHtml +
        '</span>' +
        '<div class="record-badges">' +
          recordStatusBadge(r) +
          '<span class="record-date">' + (r.date || "") + '</span>' +
          jiraPill(r.jira) +
        '</div>' +
      '</div>' +
    '</div>'
  );
}

function renderTreeNode(r, highlightId, depth){
  depth = depth || 0;
  var isChild = depth > 0;
  var cardHtml = renderSingleRecordCard(r, isChild, highlightId);
  if(!r._children || r._children.length === 0){
    return cardHtml;
  }

  var safeKey = (r._treeKey || "").replace(/[^a-zA-Z0-9_-]/g, "");
  var isOpen = window.expandedTreeKeys.has(r._treeKey) || window.treeExpandedAll || Boolean(filters.q);

  var childrenHtml = r._children.map(function(child){
    return (
      '<div class="tree-child-item">' +
        renderTreeNode(child, highlightId, depth + 1) +
      '</div>'
    );
  }).join("");

  return (
    '<div class="tree-node" data-node-key="' + safeKey + '">' +
      cardHtml +
      '<div class="tree-children-wrap" id="tree-children-' + safeKey + '" data-tree-key="' + safeKey + '"' + (isOpen ? '' : ' hidden') + '>' +
        childrenHtml +
      '</div>' +
    '</div>'
  );
}

var dashViewMode = "tree";
try {
  dashViewMode = localStorage.getItem("jarvis_dash_view_mode") || "tree";
} catch(e){}

var isAssigneeTableCollapsed = false;

function updateAssigneePanelVisibility(){
  var currentMode = (el.dashViewMode && el.dashViewMode.value) || dashViewMode || "tree";
  var panel = el.assigneePanel || document.getElementById("assigneePanel");
  var tableWrap = el.assigneeTableWrap || document.getElementById("assigneeTableWrap");
  var toggleBtn = el.btnToggleAssigneeView || document.getElementById("btnToggleAssigneeView");
  var tableHeader = document.getElementById("assigneeTableHeader");
  var panelRow = document.getElementById("assigneePanelRow") || document.querySelector(".assignee-panel-row");

  var isAllDept = (!selectedDeptForAssignee || selectedDeptForAssignee === "all");

  if(panel){
    var shouldShow = (currentMode !== "flat");
    panel.hidden = !shouldShow;
    panel.style.display = shouldShow ? "" : "none";
  }

  if(isAllDept){
    // "전체" (Tất cả phòng ban): Hiện bảng tiến độ + nút thu gọn, ẩn thanh avatar pills
    if(panelRow){
      panelRow.style.display = "none";
      panelRow.hidden = true;
    }
    if(tableHeader){
      tableHeader.style.display = "flex";
      tableHeader.hidden = false;
    }
    if(tableWrap){
      tableWrap.hidden = isAssigneeTableCollapsed;
      tableWrap.style.display = isAssigneeTableCollapsed ? "none" : "";
    }
    if(toggleBtn){
      toggleBtn.classList.toggle("active", !isAssigneeTableCollapsed);
      var textEl = toggleBtn.querySelector(".btn-toggle-text");
      var iconEl = toggleBtn.querySelector(".btn-toggle-icon");
      if(textEl) {
        textEl.textContent = isAssigneeTableCollapsed
          ? ((window.i18n && typeof window.i18n.t === "function") ? window.i18n.t("filter.table_expand") : "상세 표 보기")
          : ((window.i18n && typeof window.i18n.t === "function") ? window.i18n.t("filter.table_collapse") : "표 접기");
      }
      if(iconEl) iconEl.textContent = isAssigneeTableCollapsed ? "▼" : "▲";
    }
  } else {
    // Phòng ban cụ thể: Hiện thanh avatar pills, ẩn bảng tiến độ
    if(panelRow){
      panelRow.style.display = "flex";
      panelRow.hidden = false;
    }
    if(tableHeader){
      tableHeader.style.display = "none";
      tableHeader.hidden = true;
    }
    if(tableWrap){
      tableWrap.hidden = true;
      tableWrap.style.display = "none";
    }
  }
}

// Biến quản lý Infinite Scroll / Lazy Rendering cho Dashboard
var dashPageSize = 30;
var dashRenderedCount = 30;
var dashIsLoadingMore = false;
var dashLastVisibleList = [];

function setupDashboardInfiniteScroll(){
  window.addEventListener("scroll", function(){
    if(dashIsLoadingMore) return;
    // Kiểm tra tab hiện tại có phải Dashboard không
    var curTab = (location.hash || "").replace(/^#/, "").toLowerCase() || "home";
    if(curTab !== "dash") return;
    
    // Khi người dùng cuộn gần tới đáy trang (cách đáy 250px)
    var scrollHeight = document.documentElement.scrollHeight;
    var scrollTop = window.scrollY || document.documentElement.scrollTop;
    var clientHeight = window.innerHeight || document.documentElement.clientHeight;
    
    if(scrollTop + clientHeight >= scrollHeight - 250){
      loadMoreDashboardCards();
    }
  }, { passive: true });
}

function loadMoreDashboardCards(){
  if(!dashLastVisibleList || dashRenderedCount >= dashLastVisibleList.length){
    // If local rendered count has reached local list end, check if server has more!
    if(window.__RECORDS_HAS_MORE__ && typeof window.loadMoreRecords === "function" && !window.__RECORDS_IS_LOADING_MORE__){
      dashIsLoadingMore = true;
      window.loadMoreRecords().finally(function(){
        dashIsLoadingMore = false;
      });
    }
    return;
  }
  dashIsLoadingMore = true;
  
  var currentMode = (el.dashViewMode && el.dashViewMode.value) || dashViewMode || "tree";
  var nextCount = Math.min(dashRenderedCount + dashPageSize, dashLastVisibleList.length);
  var sliceToAppend = dashLastVisibleList.slice(dashRenderedCount, nextCount);
  dashRenderedCount = nextCount;
  
  var appendHtml = "";
  if(currentMode === "flat"){
    appendHtml = sliceToAppend.map(function(r){
      return renderSingleRecordCard(r, false);
    }).join("");
  } else {
    appendHtml = sliceToAppend.map(function(r){
      return renderTreeNode(r, null, 0);
    }).join("");
  }
  
  // Nạp thêm trực tiếp vào cuối el.list
  if(appendHtml && el.list){
    // If pagination banner exists, insert before it
    var pagBanner = el.list.querySelector(".dash-pagination-banner");
    if(pagBanner){
      pagBanner.insertAdjacentHTML("beforebegin", appendHtml);
    } else {
      el.list.insertAdjacentHTML("beforeend", appendHtml);
    }
  }
  
  // Cập nhật lại số lượng hiển thị trên caption
  if(el.recordsCaption){
    el.recordsCaption.textContent = (currentMode === "flat")
      ? ((window.i18n && typeof window.i18n.t === "function") ? window.i18n.t("filter.showing_items_of", {rendered: dashRenderedCount, total: dashLastVisibleList.length}) : ("표시 중 " + dashRenderedCount + "건 · 전체 " + dashLastVisibleList.length + "건 (스크롤하여 더 보기)"))
      : ((window.i18n && typeof window.i18n.t === "function") ? window.i18n.t("filter.showing_groups_of", {rendered: dashRenderedCount, total: (records ? records.length : dashLastVisibleList.length)}) : ("표시 중 " + dashRenderedCount + "개 그룹 · 전체 " + dashLastVisibleList.length + "개 그룹 (스크롤하여 더 보기)"));
  }
  
  setTimeout(function(){ dashIsLoadingMore = false; }, 80);
}

function renderPaginationControls(){
  var total = window.__RECORDS_TOTAL__ || (records ? records.length : 0);
  var loaded = records ? records.length : 0;
  var hasMore = Boolean(window.__RECORDS_HAS_MORE__);

  if(hasMore){
    return (
      '<div class="dash-pagination-banner" style="margin:24px 0 16px 0; padding:16px 20px; background:var(--bg-card); border:1px solid var(--border-light); border-radius:10px; text-align:center; box-shadow:0 1px 3px rgba(0,0,0,0.05);">' +
        '<div style="font-size:13.5px; font-weight:600; color:var(--text-main); margin-bottom:10px;">' +
          '<span>📊 현재 최근 <strong style="color:var(--vs-cyan);">' + loaded + '건</strong> 표시 중</span>' +
          '<span style="color:var(--text-muted); margin:0 8px;">·</span>' +
          '<span style="color:var(--text-muted);">서버에 총 <strong style="color:var(--text-main);">' + total + '건</strong>의 업무 기록이 있습니다</span>' +
        '</div>' +
        '<div style="display:flex; justify-content:center; gap:10px; flex-wrap:wrap;">' +
          '<button type="button" id="btnDashboardLoadMore" onclick="if(window.loadMoreRecords) window.loadMoreRecords();" class="choivis-btn" style="padding:7px 18px; font-size:12.5px; font-weight:600; cursor:pointer; background:var(--bg-subtle); border:1px solid var(--border-light); border-radius:6px; color:var(--text-main);">' +
            '⬇ 100건 더 불러오기' +
          '</button>' +
          '<button type="button" id="btnDashboardLoadAll" onclick="if(window.loadAllRecords) window.loadAllRecords();" class="choivis-btn" style="padding:7px 18px; font-size:12.5px; font-weight:600; cursor:pointer; background:var(--vs-cyan); border:none; border-radius:6px; color:#ffffff; box-shadow:0 1px 4px rgba(2,132,199,0.3);">' +
            '⚡ 전체 불러오기 (' + total + '건)' +
          '</button>' +
        '</div>' +
      '</div>'
    );
  } else if(loaded > 30){
    return (
      '<div style="margin:24px 0 16px 0; text-align:center; font-size:12px; color:var(--text-muted);">' +
        '✓ 전체 ' + loaded + '건의 업무 기록을 모두 불러왔습니다.' +
      '</div>'
    );
  }
  return '';
}

setupDashboardInfiniteScroll();

function renderRecords(highlightId){
  updateAssigneePanelVisibility();

  // Đếm tổng số thẻ con toàn cục trong hệ thống cho mỗi thẻ
  var subtaskCountMap = {};
  var allPool = (typeof records !== "undefined" && Array.isArray(records)) ? records : [];
  allPool.forEach(function(sub){
    var pk = sub.parentKey || (sub.jira && sub.jira.parentKey);
    if(pk){
      subtaskCountMap[pk] = (subtaskCountMap[pk] || 0) + 1;
    }
    if(sub.parentId){
      subtaskCountMap[sub.parentId] = (subtaskCountMap[sub.parentId] || 0) + 1;
    }
  });
  allPool.forEach(function(r){
    var key = (r.jira && r.jira.key) ? r.jira.key : (r.unlinked_jira_key ? r.unlinked_jira_key : ("rec-" + r.id));
    r._totalSubtasksCount = subtaskCountMap[key] || (r.id ? subtaskCountMap[r.id] : 0) || (r.subtasks ? r.subtasks.length : 0);
  });

  var visible = records.filter(matchesFilters);
  el.empty.hidden = visible.length !== 0;

  var currentMode = (el.dashViewMode && el.dashViewMode.value) || dashViewMode || "tree";

  if(el.btnToggleTree){
    el.btnToggleTree.hidden = (currentMode === "flat");
  }

  // Ẩn nút gạt cũ vì đã có Infinite Scroll mượt mà
  if(el.viewToggleBtn) el.viewToggleBtn.hidden = true;
  el.recordsWrap.classList.toggle("capped", false);

  // ===== MODE 1: FLAT VIEW (플랫 보기) =====
  if(currentMode === "flat"){
    var rHeader = el.recordsHeader || document.getElementById("recordsHeader");
    if(rHeader) rHeader.style.display = "";
    
    dashLastVisibleList = visible;
    dashRenderedCount = Math.min(dashPageSize, visible.length);
    var initialSlice = visible.slice(0, dashRenderedCount);

    el.recordsLabel.textContent = (window.i18n && typeof window.i18n.t === "function") ? window.i18n.t("filter.records_flat_title") : "전체 기록 (플랫 보기)";
    el.recordsCaption.textContent = visible.length > dashRenderedCount
      ? ((window.i18n && typeof window.i18n.t === "function") ? window.i18n.t("filter.showing_items_of", {rendered: dashRenderedCount, total: visible.length}) : ("표시 중 " + dashRenderedCount + "건 · 전체 " + visible.length + "건 (스크롤하여 더 보기)"))
      : ((window.i18n && typeof window.i18n.t === "function") ? window.i18n.t("filter.total_items", {total: visible.length}) : ("전체 " + visible.length + "건"));

    el.list.innerHTML = initialSlice.map(function(r){
      return renderSingleRecordCard(r, false, highlightId);
    }).join("") + renderPaginationControls();
    return;
  }

  // ===== MODE 2: ASSIGNEE VIEW (담당자별 그룹) =====
  if(currentMode === "assignee"){
    var rHeaderAssignee = el.recordsHeader || document.getElementById("recordsHeader");
    if(rHeaderAssignee) rHeaderAssignee.style.display = "none";
    var assigneeGroups = {};
    var unassignedLabel = (window.i18n && typeof window.i18n.t === "function") ? window.i18n.t("common.unassigned") : "미할당";

    visible.forEach(function(r){
      var name = r.assignee ? assigneeBaseName(r.assignee) : unassignedLabel;
      var rawName = r.assignee || unassignedLabel;
      if(!assigneeGroups[name]){
        assigneeGroups[name] = {
          key: name,
          displayName: rawName,
          org: r.org,
          records: []
        };
      }
      assigneeGroups[name].records.push(r);
    });

    var groups = Object.keys(assigneeGroups).map(function(k){ return assigneeGroups[k]; }).sort(function(a, b){
      if(a.key === unassignedLabel) return 1;
      if(b.key === unassignedLabel) return -1;
      return b.records.length - a.records.length;
    });

    el.recordsLabel.textContent = (window.i18n && typeof window.i18n.t === "function") ? window.i18n.t("filter.records_assignee_title") : "담당자별 그룹 보기";
    el.recordsCaption.textContent = (window.i18n && typeof window.i18n.t === "function")
      ? window.i18n.t("filter.records_assignee_caption", {members: groups.length, total: visible.length})
      : ("총 " + groups.length + "명 · " + visible.length + "건");

    var sDone = (window.i18n && typeof window.i18n.t === "function") ? window.i18n.t("filter.status_done") : "완료";
    var sReview = (window.i18n && typeof window.i18n.t === "function") ? window.i18n.t("filter.status_review") : "검토";
    var sInprog = (window.i18n && typeof window.i18n.t === "function") ? window.i18n.t("filter.status_inprog") : "진행";
    var sTodo = (window.i18n && typeof window.i18n.t === "function") ? window.i18n.t("filter.status_todo") : "대기";

    el.list.innerHTML = groups.map(function(g){
      var dept = deptById(g.org);
      var isUnassignedGroup = (g.key === unassignedLabel || !g.displayName || g.displayName === "미배정");
      var initial = isUnassignedGroup ? "?" : g.displayName.trim().charAt(0);
      var doneCount = g.records.filter(function(r){ return getRecordProgressCategory(r) === "done"; }).length;
      var reviewCount = g.records.filter(function(r){ return getRecordProgressCategory(r) === "review"; }).length;
      var inprogCount = g.records.filter(function(r){ return getRecordProgressCategory(r) === "inprog"; }).length;
      var todoCount = g.records.filter(function(r){ return getRecordProgressCategory(r) === "todo"; }).length;

      var groupTree = buildRecordsTree(g.records);
      var innerHtml = groupTree.map(function(r){
        return renderTreeNode(r, highlightId, 0);
      }).join("");

      var metaBreakdown = [];
      if(doneCount > 0) metaBreakdown.push('<span style="color:#10b981;font-weight:600;">' + escapeHtml(sDone) + ' ' + doneCount + '</span>');
      if(reviewCount > 0) metaBreakdown.push('<span style="color:#3b82f6;font-weight:600;">' + escapeHtml(sReview) + ' ' + reviewCount + '</span>');
      if(inprogCount > 0) metaBreakdown.push('<span style="color:#f59e0b;font-weight:600;">' + escapeHtml(sInprog) + ' ' + inprogCount + '</span>');
      if(todoCount > 0) metaBreakdown.push('<span style="color:var(--ink-faint);">' + escapeHtml(sTodo) + ' ' + todoCount + '</span>');

      var gAvatarRecord = g.records.find(function(r){ return r.assigneeAvatar || (r.jira && r.jira.assigneeAvatar); });
      var gAvatar = gAvatarRecord ? (gAvatarRecord.assigneeAvatar || (gAvatarRecord.jira && gAvatarRecord.jira.assigneeAvatar) || "") : "";
      var isGAvatar = Boolean(!isUnassignedGroup && gAvatar && gAvatar.indexOf("default-avatar") === -1 && gAvatar.indexOf("default/") === -1);
      var groupAvatarBg = isUnassignedGroup ? "#64748b" : (getAssigneeColor(g.displayName) || colorVar(dept ? dept.colorIndex : 0));

      var groupTotalText = (window.i18n && typeof window.i18n.t === "function")
        ? window.i18n.t("common.count_tasks", {count: g.records.length})
        : (g.records.length + "건");

      return (
        '<div class="assignee-group-block">' +
          '<div class="assignee-group-header">' +
            '<div class="assignee-group-info">' +
              '<div class="pill-avatar" style="background:' + groupAvatarBg + ';">' +
                (isGAvatar ? '<img src="' + escapeHtml(gAvatar) + '" alt="" class="pill-avatar-img" onerror="this.remove();">' : '') +
                '<span class="pill-avatar-initial">' + escapeHtml(initial) + '</span>' +
              '</div>' +
              '<span class="assignee-group-name">' + escapeHtml(g.displayName) + '</span>' +
              ((dept && (!selectedDeptForAssignee || selectedDeptForAssignee === "all")) ? ('<span class="pill-dept-tag" style="--tag-color:' + colorVar(dept.colorIndex) + ';">' + escapeHtml(dept.name) + '</span>') : '') +
            '</div>' +
            '<div class="assignee-group-meta">' +
              '<div class="assignee-group-breakdown">' + metaBreakdown.join('<span style="color:var(--line);margin:0 4px;">·</span>') + '</div>' +
              '<span class="badge-group-total">' + escapeHtml(groupTotalText) + '</span>' +
            '</div>' +
          '</div>' +
          '<div class="assignee-group-records">' +
            innerHtml +
          '</div>' +
        '</div>'
      );
    }).join("") + renderPaginationControls();
    return;
  }

  // ===== MODE 3: TREE VIEW (트리 보기 - Default) =====
  var rHeaderTree = el.recordsHeader || document.getElementById("recordsHeader");
  if(rHeaderTree) rHeaderTree.style.display = "";
  var treeRoots = buildRecordsTree(visible);
  
  dashLastVisibleList = treeRoots;
  dashRenderedCount = Math.min(dashPageSize, treeRoots.length);
  var initialTreeSlice = treeRoots.slice(0, dashRenderedCount);

  el.recordsLabel.textContent = (window.i18n && typeof window.i18n.t === "function") ? window.i18n.t("filter.records_tree_title") : "전체 기록 (트리 보기)";
  el.recordsCaption.textContent = treeRoots.length > dashRenderedCount
    ? ((window.i18n && typeof window.i18n.t === "function") ? window.i18n.t("filter.showing_groups_of", {rendered: dashRenderedCount, total: visible.length}) : ("표시 중 " + dashRenderedCount + "개 그룹 · 전체 " + visible.length + "건 (스크롤하여 더 보기)"))
    : ((window.i18n && typeof window.i18n.t === "function") ? window.i18n.t("filter.tree_caption_summary", {total: visible.length, groups: treeRoots.length}) : ("총 " + visible.length + "건 (" + treeRoots.length + "개 그룹)"));

  el.list.innerHTML = initialTreeSlice.map(function(r){
    return renderTreeNode(r, highlightId, 0);
  }).join("") + renderPaginationControls();
}

function refresh(highlightId){
  renderDeptCards();
  renderAssigneeTable();
  updateFilterRowUI();
  renderRecords(highlightId);
}

el.orgChips.addEventListener("click", function(e){
  var btn = e.target.closest(".chip");
  if(!btn) return;
  var org = btn.getAttribute("data-org");
  if(org && org !== "all"){
    selectedDeptForAssignee = org;
    filters.org = org;
    populateCatFilterForDept(org);
  } else {
    selectedDeptForAssignee = null;
    filters.org = "all";
    populateCatFilterAll();
  }
  filters.assignee = "all";
  filters.cat = "all";
  filters.q = "";
  if(el.catFilter) el.catFilter.value = "all";
  if(el.search) el.search.value = "";
  updateSearchClearBtn();
  renderDeptCards();
  renderAssigneeTable();
  updateFilterRowUI();
  renderRecords();
});
var searchClearBtn = document.getElementById("searchClearBtn");

function updateSearchClearBtn(){
  if(!searchClearBtn) searchClearBtn = document.getElementById("searchClearBtn");
  if(!searchClearBtn || !el.search) return;
  searchClearBtn.hidden = !el.search.value;
}

el.catFilter.addEventListener("change", function(){ filters.cat = el.catFilter.value; renderRecords(); });

if(el.search){
  el.search.addEventListener("input", function(){
    filters.q = el.search.value.trim();
    updateSearchClearBtn();
    renderRecords();
  });
  el.search.addEventListener("keydown", function(e){
    if(e.key === "Escape" && el.search.value){
      e.preventDefault();
      el.search.value = "";
      filters.q = "";
      updateSearchClearBtn();
      renderRecords();
    }
  });
}

if(searchClearBtn){
  searchClearBtn.addEventListener("click", function(e){
    e.preventDefault();
    e.stopPropagation();
    if(el.search){
      el.search.value = "";
      el.search.focus();
    }
    filters.q = "";
    updateSearchClearBtn();
    renderRecords();
  });
}

var viewModeElem = el.dashViewMode || document.getElementById("dashViewMode");
if(viewModeElem){
  viewModeElem.value = dashViewMode;
  updateAssigneePanelVisibility();
  viewModeElem.addEventListener("change", function(){
    dashViewMode = viewModeElem.value;
    try { localStorage.setItem("jarvis_dash_view_mode", dashViewMode); } catch(e){}
    if(dashViewMode !== "assignee"){
      filters.assignee = "all";
      if(el.assigneeFilter) el.assigneeFilter.value = "all";
    }
    updateAssigneePanelVisibility();
    renderAssigneeTable();
    renderRecords();
  });
}

var statusElem = el.statusFilter || document.getElementById("statusFilter");
if(statusElem){
  statusElem.addEventListener("change", function(){
    filters.status = statusElem.value;
    renderRecords();
  });
}

var createBtn = el.btnCreateIssue || document.getElementById("btnCreateIssue");
if(createBtn){
  createBtn.addEventListener("click", function(){
    if(typeof showTab === "function"){
      showTab("form");
      showToast("새 작업 등록 화면으로 이동했습니다.");
    }
  });
}



if(el.assigneeFilter){
  el.assigneeFilter.addEventListener("change", function(){
    filters.assignee = el.assigneeFilter.value;
    renderAssigneeTable();
    renderRecords();
  });
}

el.assigneeBody.addEventListener("click", function(e){
  var tr = e.target.closest("tr[data-assignee]");
  if(!tr) return;
  var name = tr.getAttribute("data-assignee");
  if(filters.assignee === name || (filters.assignee !== "all" && assigneeBaseName(filters.assignee) === assigneeBaseName(name))){
    filters.assignee = "all";
  } else {
    filters.assignee = name;
  }
  if(el.assigneeFilter) el.assigneeFilter.value = filters.assignee;
  renderAssigneeTable();
  renderRecords();
});

var barElem = el.assigneeBar || document.getElementById("assigneeBar");
if(barElem){
  barElem.addEventListener("click", function(e){
    if(barElem.classList.contains("is-dragging")) return;
    var pill = e.target.closest(".assignee-pill-item[data-assignee]");
    if(!pill) return;
    var name = pill.getAttribute("data-assignee");
    if(name === "all" || filters.assignee === name || (filters.assignee !== "all" && assigneeBaseName(filters.assignee) === assigneeBaseName(name))){
      filters.assignee = "all";
    } else {
      filters.assignee = name;
    }
    if(el.assigneeFilter) el.assigneeFilter.value = filters.assignee;
    renderAssigneeTable();
    renderRecords();
  });
}

var toggleBtn = el.btnToggleAssigneeView || document.getElementById("btnToggleAssigneeView");
var toggleBtnDept = document.getElementById("btnToggleAssigneeViewDept");
var tableWrap = el.assigneeTableWrap || document.getElementById("assigneeTableWrap");

if(toggleBtn && tableWrap){
  toggleBtn.addEventListener("click", function(){
    isAssigneeTableCollapsed = !isAssigneeTableCollapsed;
    updateAssigneePanelVisibility();
  });
}

if(toggleBtnDept && tableWrap){
  toggleBtnDept.addEventListener("click", function(){
    var isHidden = tableWrap.hidden;
    tableWrap.hidden = !isHidden;
    tableWrap.style.display = isHidden ? "" : "none";
    toggleBtnDept.classList.toggle("active", isHidden);
    var textEl = toggleBtnDept.querySelector(".btn-toggle-text");
    if(textEl) {
      textEl.textContent = isHidden
        ? ((window.i18n && typeof window.i18n.t === "function") ? window.i18n.t("filter.table_close") : "표 닫기")
        : ((window.i18n && typeof window.i18n.t === "function") ? window.i18n.t("filter.view_table") : "상세 표");
    }
  });
}

el.deptCards.addEventListener("click", function(e){
  var card = e.target.closest(".dept-card[data-dept-id]");
  if(card){
    var deptId = card.getAttribute("data-dept-id");
    var modeSelect = el.dashViewMode || document.getElementById("dashViewMode");

    if(deptId === "all" || selectedDeptForAssignee === deptId){
      selectedDeptForAssignee = null; // Reset to all
      filters.org = "all";
      filters.assignee = "all";

      // Choivis logic: chọn tất cả phòng ban -> tự động chuyển sang Tree view
      dashViewMode = "tree";
      if(modeSelect) modeSelect.value = "tree";
      try { localStorage.setItem("jarvis_dash_view_mode", "tree"); } catch(e){}

      if(el.orgChips){
        Array.prototype.forEach.call(el.orgChips.querySelectorAll(".chip"), function(c){
          c.classList.toggle("active", c.getAttribute("data-org") === "all");
        });
      }
      populateCatFilterAll();
    } else {
      selectedDeptForAssignee = deptId;
      filters.org = deptId;
      filters.assignee = "all";

      // Choivis logic: chọn phòng ban cụ thể -> tự động chuyển sang Assignee view (xếp theo người đảm nhận)
      dashViewMode = "assignee";
      if(modeSelect) modeSelect.value = "assignee";
      try { localStorage.setItem("jarvis_dash_view_mode", "assignee"); } catch(e){}

      populateCatFilterForDept(deptId);
    }
    filters.cat = "all";
    filters.q = "";
    if(el.catFilter) el.catFilter.value = "all";
    if(el.search) el.search.value = "";
    updateSearchClearBtn();
    renderDeptCards();
    renderAssigneeTable();
    updateFilterRowUI();
    renderRecords();
    return;
  }

  if(e.target.closest("#deptAddBtn")){
    openDeptModal(null);
    return;
  }
});

function openDeptModal(deptObj){
  if(typeof isCurrentUserAdmin === "function" && !isCurrentUserAdmin()){
    if(typeof showToast === "function") showToast("관리자(Admin) 권한이 있는 사용자만 부서를 관리할 수 있습니다.");
    return;
  }
  var backdrop = document.getElementById("deptModalBackdrop");
  var idInput = document.getElementById("deptAddId");
  var nameInput = document.getElementById("deptAddName");
  var localPrefixInput = document.getElementById("deptAddLocalPrefix");
  var jiraKeyInput = document.getElementById("deptAddJiraKey");
  var customCategoriesInput = document.getElementById("deptAddCustomCategories");
  var titleEl = document.getElementById("deptModalTitle");
  var submitBtn = document.getElementById("deptModalSubmitBtn");
  var t = (window.i18n && window.i18n.t) ? window.i18n.t : function(k){ return k; };

  if(deptObj){
    // Edit Mode
    if(idInput) idInput.value = deptObj.id;
    if(nameInput) nameInput.value = deptObj.name || "";
    if(localPrefixInput) localPrefixInput.value = deptObj.localPrefix || "";
    if(jiraKeyInput) jiraKeyInput.value = deptObj.jiraKey || "";
    if(customCategoriesInput) customCategoriesInput.value = deptObj.customCategories || "";
    if(titleEl) titleEl.textContent = t("dept.edit_title");
    if(submitBtn) submitBtn.textContent = t("dept.modal_update");
  } else {
    // Add Mode
    if(idInput) idInput.value = "";
    if(nameInput) nameInput.value = "";
    if(localPrefixInput) localPrefixInput.value = "";
    if(jiraKeyInput) jiraKeyInput.value = "";
    if(customCategoriesInput) customCategoriesInput.value = "";
    if(titleEl) titleEl.textContent = t("dept.add_title");
    if(submitBtn) submitBtn.textContent = t("dept.modal_submit");
  }

  var isJiraActive = (typeof isJiraIntegrationActive === "function")
    ? isJiraIntegrationActive()
    : Boolean(window.__JIRA_STATUS__ && window.__JIRA_STATUS__.enabled);
  var jiraKeyField = document.getElementById("deptAddJiraKeyField") || (jiraKeyInput ? jiraKeyInput.closest(".dept-modal-field") : null);
  if(jiraKeyField){
    jiraKeyField.style.display = isJiraActive ? "" : "none";
  }

  if(backdrop){
    backdrop.hidden = false;
    setTimeout(function(){ if(nameInput) nameInput.focus(); }, 50);
  }
}

function closeDeptModal(){
  var backdrop = document.getElementById("deptModalBackdrop");
  if(backdrop) backdrop.hidden = true;
}

window.openDeptModal = openDeptModal;
window.closeDeptModal = closeDeptModal;

(function initDeptModalEvents(){
  var backdrop = document.getElementById("deptModalBackdrop");
  var closeBtn = document.getElementById("deptModalCloseBtn");
  var cancelBtn = document.getElementById("deptModalCancelBtn");
  var form = document.getElementById("deptAddFormModal");

  if(closeBtn) closeBtn.addEventListener("click", closeDeptModal);
  if(cancelBtn) cancelBtn.addEventListener("click", closeDeptModal);

  if(backdrop){
    backdrop.addEventListener("click", function(e){
      if(e.target === backdrop) closeDeptModal();
    });
  }

  document.addEventListener("keydown", function(e){
    if(e.key === "Escape" && backdrop && !backdrop.hidden){
      closeDeptModal();
    }
  });

  if(form){
    form.addEventListener("submit", function(e){
      e.preventDefault();
      var idInput = document.getElementById("deptAddId");
      var nameInput = document.getElementById("deptAddName");
      var localPrefixInput = document.getElementById("deptAddLocalPrefix");
      var jiraKeyInput = document.getElementById("deptAddJiraKey");
      var customCategoriesInput = document.getElementById("deptAddCustomCategories");
      var editId = (idInput ? idInput.value : "").trim();
      var name = (nameInput ? nameInput.value : "").trim();
      var localPrefix = (localPrefixInput ? localPrefixInput.value : "").trim();
      var jiraKey = (jiraKeyInput ? jiraKeyInput.value : "").trim();
      var customCategories = (customCategoriesInput ? customCategoriesInput.value : "").trim();

      if(!name) return;

      var submitBtn = document.getElementById("deptModalSubmitBtn");
      if(submitBtn) submitBtn.disabled = true;

      var url = editId ? "/api/departments/update" : "/api/departments";
      var payload = {
        name: name,
        localPrefix: localPrefix,
        jiraKey: jiraKey,
        customCategories: customCategories
      };
      if(editId) payload.id = editId;

      apiPostJson(url, payload).then(function(res){
        if(submitBtn) submitBtn.disabled = false;
        closeDeptModal();
        var t = (window.i18n && window.i18n.t) ? window.i18n.t : function(k){ return k; };
        if(res.ok){
          DEPARTMENTS = res.departments;
          renderDeptCards();
          renderOrgChips();
          renderOrgSelectOptions();
          if(typeof renderIdOrgOptions === "function") renderIdOrgOptions();
          if(typeof renderSettingsCategoryTable === "function") renderSettingsCategoryTable();
          if(editId){
            showToast(t("dept.toast_updated", { name: name }));
          } else {
            showToast(res.added ? t("dept.toast_added", { name: name }) : t("dept.toast_exists"));
          }
        } else {
          showToast(res.error || t("dept.toast_failed"));
        }
      }).catch(function(){
        if(submitBtn) submitBtn.disabled = false;
        closeDeptModal();
        showToast(t("common.server_error"));
      });
    });
  }
})();

el.viewToggleBtn.addEventListener("click", function(){
  viewMode = viewMode === "recent" ? "all" : "recent";
  renderRecords();
  el.recordsWrap.scrollTop = 0;
  if(el.recordsWrap.scrollIntoView) el.recordsWrap.scrollIntoView({ behavior: "smooth", block: "start" });
});

if(el.btnToggleTree){
  el.btnToggleTree.addEventListener("click", window.toggleAllTreeItems);
}

el.syncBtn.addEventListener("click", function(){
  if(el.syncBtn.disabled) return;
  if(!isJiraIntegrationActive()){
    showToast("Jira 연동이 비활성화되어 있습니다.");
    return;
  }
  var original = el.syncBtn.textContent;
  el.syncBtn.disabled = true;
  el.syncBtn.textContent = "동기화 중…";
  apiPostJson("/api/sync", {}).then(function(res){
    return loadRecords().then(function(){ return refreshCategoriesAfterSync(); }).then(function(){ return res; });
  }).then(function(res){
    el.syncBtn.disabled = false;
    el.syncBtn.textContent = original;
    if(res && res.error){
      showToast("Jira 동기화 실패: " + res.error);
    } else {
      showToast("Jira와 동기화했습니다 (" + (res && typeof res.count === "number" ? res.count : "?") + "건).");
    }
  }).catch(function(){
    el.syncBtn.disabled = false;
    el.syncBtn.textContent = original;
    showToast("서버에 연결할 수 없어 동기화하지 못했습니다.");
  });
});

var btnExportExcel = document.getElementById("btnExportExcel");
if(btnExportExcel){
  btnExportExcel.addEventListener("click", function(){
    var org = (typeof filters !== "undefined" && filters.org && filters.org !== "all") ? filters.org : "";
    var status = (typeof filters !== "undefined" && filters.status && filters.status !== "all") ? filters.status : "";
    var assignee = (typeof filters !== "undefined" && filters.assignee && filters.assignee !== "all") ? filters.assignee : "";
    var url = "/api/records/export/excel?org=" + encodeURIComponent(org) + "&status=" + encodeURIComponent(status) + "&assignee=" + encodeURIComponent(assignee);
    if(typeof showToast === "function"){
      showToast("업무 목록 엑셀 파일 생성을 시작합니다...");
    }
    window.location.href = url;
  });
}

var orgSelectElem2 = document.getElementById("orgSelect");
if(orgSelectElem2){
  orgSelectElem2.addEventListener("change", function(){ populateCatSelect(orgSelectElem2.value); });
}

window.addEventListener("langchange", function(){
  try {
    populateCatFilterAll();
    populateAssigneeFilter(selectedDeptForAssignee);
    renderAssigneeTable();
    updateAssigneePanelVisibility();
    renderRecords();
  } catch(e){}
});
