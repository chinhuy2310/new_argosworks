// js/canvas.js — Artifact Canvas Panel for Issue Details (Choivis Style UI/UX)

(function(){
  'use strict';

  var currentIssueKey = null;
  window.userAdjustedCanvasWidth = null;

  // --- Helper Formatters (Choivis Standard) ---
  function formatStatus(status){
    if(!status) return '대기';
    var s = String(status).trim();
    var low = s.toLowerCase();
    if(low.indexOf('완료') !== -1 || low.indexOf('done') !== -1 || low.indexOf('closed') !== -1 || low.indexOf('resolved') !== -1 || low.indexOf('hoàn thành') !== -1){
      return '완료';
    }
    if(low.indexOf('검토') !== -1 || low.indexOf('review') !== -1 || low.indexOf('kiểm tra') !== -1 || low.indexOf('xét duyệt') !== -1 || low.indexOf('testing') !== -1){
      return '검토';
    }
    if(low.indexOf('진행') !== -1 || low.indexOf('progress') !== -1 || low.indexOf('đang') !== -1){
      return '진행';
    }
    if(low.indexOf('예정') !== -1 || low.indexOf('to do') !== -1 || low.indexOf('todo') !== -1 || low.indexOf('open') !== -1 || low.indexOf('대기') !== -1 || low.indexOf('chờ') !== -1){
      return '예정';
    }
    return s.replace(/\s*\([^)]*\)/g, '').trim();
  }

  function getStatusColor(statusStr){
    var s = formatStatus(statusStr);
    if(s === '완료') return '#22c55e'; // Green
    if(s === '검토') return '#3b82f6'; // Blue / Review
    if(s === '진행') return '#f59e0b'; // Amber / In Progress
    return '#94a3b8'; // Slate Gray / Todo
  }

  function formatIssueType(type){
    if(!type) return 'Task';
    var low = String(type).toLowerCase();
    if(low.indexOf('subtask') !== -1 || low.indexOf('하위') !== -1 || low.indexOf('con') !== -1) return '하위 작업';
    if(low.indexOf('epic') !== -1 || low.indexOf('에픽') !== -1) return '에픽';
    if(low.indexOf('bug') !== -1 || low.indexOf('버그') !== -1 || low.indexOf('lỗi') !== -1) return '버그';
    return type;
  }

  function formatPriority(prio){
    if(!prio) return '보통';
    var low = String(prio).toLowerCase();
    if(low.indexOf('low') !== -1 || low.indexOf('낮') !== -1 || low.indexOf('thấp') !== -1) return '낮음';
    if(low.indexOf('crit') !== -1 || low.indexOf('긴급') !== -1 || low.indexOf('khẩn') !== -1 || low.indexOf('urg') !== -1 || low.indexOf('highest') !== -1) return '긴급';
    if(low.indexOf('high') !== -1 || low.indexOf('높') !== -1 || low.indexOf('cao') !== -1) return '높음';
    return '보통';
  }

  function getPriorityColor(prio){
    var p = formatPriority(prio);
    if(p === '낮음') return '#22c55e'; // Green
    if(p === '보통') return '#eab308'; // Yellow
    if(p === '높음') return '#f97316'; // Orange
    if(p === '긴급') return '#ef4444'; // Red
    return '#eab308';
  }

  function formatAssignee(assignee){
    if(!assignee || assignee === 'Unassigned' || assignee === 'Chưa giao' || assignee === 'Chưa phân công' || assignee === '미할당'){
      return '미배정';
    }
    return assignee;
  }

  function isUnassigned(name){
    return !name || name === '미배정' || name === 'Unassigned' || name === 'Chưa giao' || name === 'Chưa phân công' || name === '미할당';
  }

  function cleanDate(val){
    if(!val) return null;
    var s = String(val).trim();
    var match = s.match(/^\d{4}-\d{2}-\d{2}/);
    return match ? match[0] : (s.length >= 10 ? s.substring(0, 10) : s);
  }

  function parseCommentTime(dateVal){
    if(!dateVal) return 0;
    var str = String(dateVal).trim();
    if(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}/.test(str)){
      str = str.replace(' ', 'T') + 'Z';
    }
    var t = new Date(str).getTime();
    return isNaN(t) ? 0 : t;
  }

  function formatCommentDate(dateVal){
    if(!dateVal) return '-';
    var str = String(dateVal).trim();
    if(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}/.test(str)){
      str = str.replace(' ', 'T') + 'Z';
    }
    var dt = new Date(str);
    return isNaN(dt.getTime()) ? String(dateVal) : dt.toLocaleString('ko-KR');
  }

  function formatCommentContent(text){
    if(!text) return '';
    var clean = String(text).replace(/\n*\((?:작성자:\s*)?[^\)]+-(?:Argos|Agros)\s*works\)\s*$/i, '').replace(/\n*\(작성자:\s*[^\)]+\)\s*$/i, '');
    var lines = clean.split('\n');
    return lines.map(function(line, idx){
      var safe = escapeHtml(line);
      if(!line.trim()){
        return '<div style="height:8px;"></div>';
      }
      var mb = (idx === lines.length - 1) ? '0' : '8px';
      return '<div style="margin-bottom:' + mb + '; line-height:1.5; word-break:break-word;">' + safe + '</div>';
    }).join('');
  }

  // --- Layout & Canvas Window Management ---
  function updateTopbarHeight(){
    var topbar = document.querySelector('.topbar');
    if(topbar){
      var h = topbar.offsetHeight || 52;
      document.documentElement.style.setProperty('--topbar-height', h + 'px');
    }
  }

  window.applyCanvasWidthPreference = function(){
    var canvas = document.getElementById("canvasPanel");
    if(!canvas) return;
    if(canvas.classList.contains("canvas-mode-modal")){
      canvas.style.removeProperty('--canvas-width');
      canvas.style.width = "";
      return;
    }
    if(window.userAdjustedCanvasWidth){
      canvas.style.setProperty('--canvas-width', window.userAdjustedCanvasWidth + 'px');
      canvas.style.width = window.userAdjustedCanvasWidth + 'px';
    } else {
      canvas.style.removeProperty('--canvas-width');
      canvas.style.width = "";
    }
  };

  window.initCanvasResizer = function(){
    var resizer = document.getElementById("canvasResizer");
    var handle = document.getElementById("canvasResizeHandle");
    var canvas = document.getElementById("canvasPanel");
    if(!canvas) return;

    var isDragging = false;
    var startX = 0;
    var startWidth = 0;

    function startDrag(e){
      if(canvas.classList.contains("canvas-mode-modal")) return;
      isDragging = true;
      startX = e.clientX;
      startWidth = canvas.offsetWidth;
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
      if(resizer) resizer.classList.add('is-dragging');
      if(handle) handle.classList.add('is-dragging');
      e.preventDefault();
    }

    if(resizer) resizer.addEventListener('mousedown', startDrag);
    if(handle) handle.addEventListener('mousedown', startDrag);

    document.addEventListener('mousemove', function(e){
      if(!isDragging) return;
      var diff = startX - e.clientX;
      var minW = 340;
      var maxW = Math.round(window.innerWidth * 0.75);
      var newWidth = Math.max(minW, Math.min(startWidth + diff, maxW));
      canvas.style.setProperty('--canvas-width', newWidth + 'px');
      canvas.style.width = newWidth + 'px';
      window.userAdjustedCanvasWidth = newWidth;
    });

    document.addEventListener('mouseup', function(){
      if(!isDragging) return;
      isDragging = false;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      if(resizer) resizer.classList.remove('is-dragging');
      if(handle) handle.classList.remove('is-dragging');
    });

    function resetWidth(){
      window.userAdjustedCanvasWidth = null;
      canvas.style.removeProperty('--canvas-width');
      canvas.style.width = '';
    }

    if(resizer) resizer.addEventListener('dblclick', resetWidth);
    if(handle) handle.addEventListener('dblclick', resetWidth);
  };

  window.isHomeTabActive = function(){
    var vHome = document.getElementById("viewHome");
    return vHome && !vHome.hidden;
  };

  window.isDashTabActive = function(){
    var vDash = document.getElementById("viewDash");
    return vDash && !vDash.hidden;
  };

  window.isChatTabActive = function(){
    var vChat = document.getElementById("sectionChat") || document.getElementById("viewChat");
    return vChat && !vChat.hidden;
  };

  window.getCanvasDisplayMode = function(){
    if(window.isHomeTabActive()) return "modal";
    var isDash = window.isDashTabActive();
    var isChat = window.isChatTabActive();
    if(!isDash && !isChat) return "overlay";
    var saved = null;
    try { saved = localStorage.getItem("jarvis_canvas_mode"); } catch(e){}
    if(saved && ["docked", "overlay", "modal"].indexOf(saved) !== -1){
      if(saved === "docked" && window.innerWidth < 1100) return "overlay";
      return saved;
    }
    return window.innerWidth >= 1200 ? "docked" : "overlay";
  };

  window.setCanvasDisplayMode = function(mode){
    var canvas = document.getElementById("canvasPanel");
    var resizer = document.getElementById("canvasResizer");
    var backdrop = document.getElementById("canvasBackdrop");
    if(!canvas) return;

    var isHome = window.isHomeTabActive();
    var isDash = window.isDashTabActive();
    var isChat = window.isChatTabActive();
    if(isHome){
      mode = "modal";
    } else if(!isDash && !isChat && mode === "docked"){
      mode = "overlay";
    }

    updateTopbarHeight();

    if(mode === "docked" && window.innerWidth < 1100){
      mode = "overlay";
    }

    if(!isHome && (isDash || isChat)){
      try { localStorage.setItem("jarvis_canvas_mode", mode); } catch(e){}
    }

    canvas.classList.remove("canvas-mode-docked", "canvas-mode-overlay", "canvas-mode-modal");
    canvas.classList.add("canvas-mode-" + mode);

    ["docked", "overlay", "modal"].forEach(function(m){
      var btn = document.getElementById("btnCanvasMode" + m.charAt(0).toUpperCase() + m.slice(1));
      if(btn){
        btn.classList.toggle("active", m === mode);
        // Hide mode buttons if on Home tab; hide docked button if neither Dashboard nor Chat
        if(isHome || (!isDash && !isChat && m === "docked")){
          btn.style.display = "none";
        } else {
          btn.style.display = "";
        }
      }
    });

    var isVisible = !canvas.hidden;
    var dashLayout = document.querySelector(".dash-layout");

    if(mode === "docked" && isDash){
      // Must be inside .dash-layout for position: sticky to sit side-by-side with dash-main-content
      if(dashLayout && canvas.parentElement !== dashLayout){
        dashLayout.appendChild(canvas);
      }
      if(backdrop){
        backdrop.hidden = true;
        backdrop.classList.remove("modal-backdrop");
      }
      document.body.classList.remove("canvas-in-chat");
      if(resizer && isVisible) resizer.hidden = false;
      if(isVisible) document.body.classList.add("canvas-docked-open");
      else document.body.classList.remove("canvas-docked-open");
      window.applyCanvasWidthPreference();
    } else if(mode === "docked" && isChat){
      // In Chat: keep canvas in body with fixed right positioning, no backdrop, shrink chat container
      if(canvas.parentElement !== document.body){
        document.body.appendChild(canvas);
      }
      if(backdrop){
        backdrop.hidden = true;
        backdrop.classList.remove("modal-backdrop");
      }
      if(resizer) resizer.hidden = true;
      if(isVisible){
        document.body.classList.add("canvas-docked-open");
        document.body.classList.add("canvas-in-chat");
      } else {
        document.body.classList.remove("canvas-docked-open");
        document.body.classList.remove("canvas-in-chat");
      }
      window.applyCanvasWidthPreference();
    } else if(mode === "overlay"){
      // Move to body for slide-over drawer
      if(canvas.parentElement !== document.body){
        document.body.appendChild(canvas);
      }
      document.body.classList.remove("canvas-docked-open");
      if(isChat) document.body.classList.remove("canvas-in-chat");
      if(backdrop){
        if(backdrop.parentElement !== document.body) document.body.appendChild(backdrop);
        backdrop.classList.remove("modal-backdrop");
        if(isVisible) backdrop.hidden = false;
      }
      if(resizer) resizer.hidden = true;
      window.applyCanvasWidthPreference();
    } else {
      // Center modal: move to body
      if(canvas.parentElement !== document.body){
        document.body.appendChild(canvas);
      }
      document.body.classList.remove("canvas-docked-open");
      if(isChat) document.body.classList.remove("canvas-in-chat");
      if(backdrop){
        if(backdrop.parentElement !== document.body) document.body.appendChild(backdrop);
        backdrop.classList.add("modal-backdrop");
        if(isVisible) backdrop.hidden = false;
      }
      if(resizer) resizer.hidden = true;
      canvas.style.removeProperty('--canvas-width');
      canvas.style.width = "";
    }
  };

  window.closeCanvas = function(){
    var canvas = document.getElementById("canvasPanel");
    var resizer = document.getElementById("canvasResizer");
    var backdrop = document.getElementById("canvasBackdrop");
    if(canvas) canvas.hidden = true;
    if(resizer) resizer.hidden = true;
    if(backdrop) backdrop.hidden = true;
    document.body.classList.remove("canvas-open");
    document.body.classList.remove("canvas-docked-open");
    document.body.classList.remove("canvas-in-chat");
    currentIssueKey = null;
    window.currentCanvasIssueKey = null;
    if(typeof window.highlightActiveCanvasCard === "function"){
      window.highlightActiveCanvasCard(null);
    }
  };

  // --- Show Issue In Canvas ---
  window.showIssueInCanvas = function(issueKey){
    if(!issueKey) return;
    currentIssueKey = issueKey;
    window.currentCanvasIssueKey = issueKey;
    if(typeof window.highlightActiveCanvasCard === "function"){
      window.highlightActiveCanvasCard(issueKey);
    }

    var canvas = document.getElementById("canvasPanel");
    var resizer = document.getElementById("canvasResizer");
    var backdrop = document.getElementById("canvasBackdrop");
    var titleEl = document.getElementById("canvasTitleText");
    var contentEl = document.getElementById("canvasContent");

    if(!canvas || !contentEl) return;

    canvas.hidden = false;
    var mode = window.getCanvasDisplayMode();
    window.setCanvasDisplayMode(mode);
    document.body.classList.add("canvas-open");

    if(titleEl) titleEl.textContent = "🎫 " + issueKey;
    contentEl.innerHTML = '<div style="padding:24px; color:var(--vs-cyan, #33aad3); font-weight:600; text-align:center;">🔄 ' + escapeHtml(issueKey) + ' 세부 정보를 불러오는 중...</div>';

    apiGet("/api/issues?key=" + encodeURIComponent(issueKey)).then(function(res){
      if(!res || res.error){
        contentEl.innerHTML = '<div style="padding:24px; color:#ef4444; text-align:center;">이슈를 찾을 수 없거나 불러오지 못했습니다.<br><small style="color:var(--text-muted);">' + escapeHtml((res && res.error) || "") + '</small></div>';
        return;
      }
      renderCanvasIssue(res);
    }).catch(function(err){
      contentEl.innerHTML = '<div style="padding:24px; color:#ef4444; text-align:center;">서버 통신 오류: ' + escapeHtml(err.message || String(err)) + '</div>';
    });
  };

  // --- Render Issue Detail (EXACT CHOIVIS UI/UX & DOM TEMPLATE) ---
  function renderCanvasIssue(d){
    var contentEl = document.getElementById("canvasContent");
    if(!contentEl) return;

    // 1. Data Normalization
    var key = (d.jira && d.jira.key) ? d.jira.key : (d.cardCode || d.key || (d.id ? String(d.id).replace("jira-", "") : ""));
    d.key = key;
    window.currentCanvasIssueDetail = d;
    // Title vs Description disambiguation (Fixes title duplicated as description):
    var summary = (d.jira && d.jira.summary) ? d.jira.summary : (d.title || d.summary || d.memo || "(제목 없음)");
    var description = d.description || d.memo || "";
    if(!description && d.summary && d.summary !== summary){
      description = d.summary;
    }
    if(description && description.indexOf("첨부 파일 0건") !== -1){
      description = "";
    }
    var rawStatus = (d.jira && d.jira.statusName) ? d.jira.statusName : (d.status || "진행");
    var displayStatus = formatStatus(rawStatus);
    var statusColor = getStatusColor(displayStatus);

    var displayType = formatIssueType(d.issueType || d.category || "Task");
    var displayPriority = formatPriority(d.priority || ((d.jira && d.jira.priority) ? d.jira.priority : "보통"));
    var displayAssignee = formatAssignee(d.assignee);
    var isJiraGloballyEnabled = Boolean(window.__JIRA_STATUS__ && window.__JIRA_STATUS__.enabled);
    var isLocal = (d.isLocal !== undefined) ? d.isLocal : (!d.jira || !d.jira.key);

    var titleEl = document.getElementById("canvasTitleText");
    if(titleEl){
      var displayBadge = "";
      if(!isJiraGloballyEnabled){
        displayBadge = "📁 " + (d.cardCode || key);
      } else {
        displayBadge = isLocal ? ("📁 [Local] " + (d.cardCode || key)) : ("🎫 " + key);
      }
      titleEl.textContent = displayBadge;
    }

    // RBAC: Quyen sua the (Chi Admin, Manager cung phong ban, hoac Assignee truc tiep)
    var curUser = (typeof getCurrentUser === "function") ? getCurrentUser() : null;
    var canEditRecord = false;
    if(curUser){
      var curRole = (typeof getSessionRole === "function") ? getSessionRole() : (curUser.role || ((curUser.isAdmin || curUser.is_admin) ? "admin" : (curUser.isManager ? "manager" : "member")));
      if(curRole === "admin" || curUser.isAdmin || curUser.is_admin){
        canEditRecord = true;
      } else if(curRole !== "viewer"){
        var uId = String(curUser.id || curUser.user_id || "");
        var uName = String(curUser.name || "").trim().toLowerCase();
        var uUsername = String(curUser.username || "").trim().toLowerCase();
        var uDept = String(curUser.dept_id || curUser.org || "").trim().toLowerCase();

        var rDept = String(d.dept_id || d.org || "").trim().toLowerCase();
        var rAssigneeId = String(d.assignee_id || "");
        var rAssignee = String(d.assignee_name || d.assignee || "").trim().toLowerCase();

        if((curRole === "manager" || curUser.isManager) && uDept && rDept && uDept === rDept){
          canEditRecord = true;
        } else if(uId && rAssigneeId && uId === rAssigneeId){
          canEditRecord = true;
        } else if(uUsername && rAssignee && uUsername === rAssignee){
          canEditRecord = true;
        } else if(uName && rAssignee && uName === rAssignee){
          canEditRecord = true;
        }
      }
    }

    var headerEditBtn = document.getElementById("btnCanvasEditTask");
    if(headerEditBtn){
      headerEditBtn.style.display = canEditRecord ? "inline-flex" : "none";
    }

    var rawStart = d.startDate || d.start_date || null;
    var rawDue = d.dueDate || d.due_date || null;
    var sDate = cleanDate(rawStart);
    var dDate = cleanDate(rawDue);
    var scheduleRangeText = "";
    if(sDate && dDate){
      scheduleRangeText = sDate + " ~ " + dDate;
    } else if(sDate){
      scheduleRangeText = sDate + " ~ " + sDate;
    } else if(dDate){
      scheduleRangeText = dDate + " ~ " + dDate;
    }

    // 2. Subtasks & Contributors Calculation (Comprehensive: main assignee + all recursive descendants)
    var subtasks = d.subtasksDetail || d.subtasks || [];
    var contributorMap = (d.contributorMap && Object.keys(d.contributorMap).length > 0) ? d.contributorMap : null;
    var contributorNames = (d.contributorNames && d.contributorNames.length > 0) ? d.contributorNames : null;

    // Direct participants list (always parsed in outer scope so pills and boxes can safely read it)
    var directPartsList = [];
    if(d.participants){
      if(typeof d.participants === "string" && d.participants.trim()){
        directPartsList = d.participants.split(/[,;/]+/).map(function(s){ return s.trim(); }).filter(Boolean);
      } else if(Array.isArray(d.participants)){
        directPartsList = d.participants.map(function(p){
          return typeof p === "string" ? p.trim() : (p && p.name ? p.name.trim() : "");
        }).filter(Boolean);
      }
    }
    var hasParts = directPartsList.length > 0;

    if(!contributorMap){
      var allRecs = window.records || window.allJiraIssues || [];
      var allDescendants = [];
      var visitedKeys = {};
      var cleanKeyUpper = (key || "").toUpperCase();

      function walkDescendants(pKey){
        allRecs.forEach(function(item){
          var itemKey = ((item.jira && item.jira.key) ? item.jira.key : (item.key || (item.id ? String(item.id).replace("jira-", "") : ""))).toUpperCase();
          var itemParent = ((item.jira && item.jira.parentKey) ? item.jira.parentKey : (item.parentKey || "")).toUpperCase();
          if(itemParent === pKey && itemKey && !visitedKeys[itemKey] && itemKey !== cleanKeyUpper){
            visitedKeys[itemKey] = true;
            allDescendants.push(item);
            walkDescendants(itemKey);
          }
        });
      }
      walkDescendants(cleanKeyUpper);

      subtasks.forEach(function(s){
        var sk = (s.key || "").toUpperCase();
        if(sk && !visitedKeys[sk] && sk !== cleanKeyUpper){
          visitedKeys[sk] = true;
          allDescendants.push(s);
          walkDescendants(sk);
        }
      });

      contributorMap = {};

      // 1. Những người tham gia thẻ đó (direct participants of this card)
      directPartsList.forEach(function(dp){
        if(dp && !isUnassigned(dp)){
          if(contributorMap[dp] === undefined) contributorMap[dp] = 0;
        }
      });

      // 2. Những người đảm nhận thẻ con trong thẻ đó (assignees of child subtasks)
      allDescendants.forEach(function(s){
        var subAssignee = (s.assignee || "").trim();
        if(subAssignee && !isUnassigned(subAssignee)){
          contributorMap[subAssignee] = (contributorMap[subAssignee] || 0) + 1;
        }
      });

      contributorNames = Object.keys(contributorMap).sort(function(a, b){
        var countA = contributorMap[a] || 0;
        var countB = contributorMap[b] || 0;
        if(countB !== countA) return countB - countA;
        return a.localeCompare(b);
      });
    } else if(!contributorNames){
      contributorNames = Object.keys(contributorMap);
    }

    // 3. Comments Sorting
    var comments = (d.comments || []).slice().sort(function(a, b){
      return parseCommentTime(b.created) - parseCommentTime(a.created);
    });

    var attachments = d.attachments || [];
    var parentKey = d.parentKey || (d.jira && d.jira.parentKey) || null;
    var parentSummary = (d.parentSummary || "").trim();
    if(!parentSummary && parentKey && typeof records !== "undefined" && Array.isArray(records)){
      var cleanPk = String(parentKey).trim().toUpperCase();
      for(var pi = 0; pi < records.length; pi++){
        var pCand = records[pi];
        var pJKey = (pCand.jira && pCand.jira.key ? String(pCand.jira.key).toUpperCase() : "");
        var pCode = (pCand.cardCode ? String(pCand.cardCode).toUpperCase().replace(/^#/, "") : "");
        var pId = String(pCand.id || "");
        if(cleanPk === pJKey || cleanPk === pCode || cleanPk === pId || cleanPk === ("REC-" + pId) || cleanPk === ("#" + pId)){
          parentSummary = (pCand.title || (pCand.jira && pCand.jira.summary) || "").trim();
          if(parentSummary) break;
        }
      }
    }

    // 4. Action Buttons Template (Choivis Style)
    // ARGOS WORKS hỗ trợ phả hệ đa tầng (N-levels hierarchy): mọi thẻ đều có thể tạo công việc con
    var canCreateSubtask = false;
    if(curUser && curRole !== "viewer"){
      if(curRole === "admin"){
        canCreateSubtask = true;
      } else {
        var uDept = String(curUser.dept_id || curUser.org || "").trim().toLowerCase();
        var rDept = String(d.dept_id || d.org || "").trim().toLowerCase();
        if(uDept && rDept && uDept === rDept){
          canCreateSubtask = true;
        }
      }
    }

    var actionButtons = "";
    var actionBtnList = [];

    // Comprehensive Edit Button (Title, Assignee, Participants, Dates, Memo)
    if(canEditRecord){
    actionBtnList.push(
      '<button type="button" onclick="window.openEditRecordModal(\'' + escapeHtml(key) + '\')" class="canvas-action-btn canvas-btn-edit" title="업무 수정 (담당자, 참여자, 제목, 내용, 마감일)" style="display:inline-flex; align-items:center; gap:5px; background:var(--accent-2, #0284c7); color:#ffffff; border:none; padding:6px 13px; border-radius:6px; font-size:12px; font-weight:600; cursor:pointer; box-shadow:0 1px 4px rgba(2, 132, 199, 0.25);"><span style="font-size:12.5px;">✏️</span> 수정</button>'
    );
    }

    // Local Record (Not on Jira): Provide "Push to Jira" and "Delete" buttons
    // [요구사항] 'Jira로 내보내기' 버튼은 관리자가 Jira 연동을 활성화하고 연결 오류가 없을 때에만 표시
    var isJiraConnectedAndEnabled = (d.canPushToJira !== undefined)
      ? Boolean(d.canPushToJira)
      : (d.jiraConnected !== undefined
          ? Boolean(d.jiraConnected)
          : (window.__JIRA_STATUS__ ? (window.__JIRA_STATUS__.enabled && window.__JIRA_STATUS__.connected) : false));

    // Phương án A: Chỉ Admin và Manager cùng phòng ban mới có quyền xóa thẻ (Member và Viewer không có nút xóa)
    var canDeleteRecord = false;
    var curUser = (typeof getCurrentUser === "function") ? getCurrentUser() : null;
    if(curUser){
      var curRole = (typeof getSessionRole === "function") ? getSessionRole() : (curUser.role || ((curUser.isAdmin || curUser.is_admin) ? "admin" : (curUser.isManager ? "manager" : "member")));
      if(curRole === "admin" || curUser.isAdmin || curUser.is_admin){
        canDeleteRecord = true;
      } else if(curRole === "manager" || curUser.isManager){
        var uDept = String(curUser.dept_id || curUser.org || "").trim().toLowerCase();
        var rDept = String(d.dept_id || d.org || "").trim().toLowerCase();
        if(uDept && rDept && uDept === rDept){
          canDeleteRecord = true;
        }
      }
    }

    if(isLocal){
      if(isJiraConnectedAndEnabled){
        actionBtnList.push(
          '<button onclick="window.confirmPushLocalRecordToJira(\'' + escapeHtml(key) + '\', \'' + escapeHtml(summary).replace(/'/g, "\\'") + '\')" class="canvas-action-btn canvas-btn-push-jira" title="이 로컬 업무를 Jira Cloud 티켓으로 발행합니다">🚀 Jira로 내보내기</button>'
        );
      }
      if(canDeleteRecord){
        actionBtnList.push(
          '<button onclick="window.confirmDeleteLocalRecord(\'' + escapeHtml(key) + '\', \'' + escapeHtml(summary).replace(/'/g, "\\'") + '\')" class="canvas-action-btn canvas-btn-delete-local" title="이 로컬 업무 기록을 완전히 삭제합니다">🗑️ 삭제</button>'
        );
      }
    }

    if(canCreateSubtask){
      actionBtnList.push(
        '<button onclick="if(window.selectParentInJiraForm) window.selectParentInJiraForm(\'' + escapeHtml(key) + '\'); else if(window.openLocalIssueModal) window.openLocalIssueModal(\'' + escapeHtml(key) + '\');" class="canvas-action-btn canvas-btn-sub">➕ 하위 작업 추가</button>'
      );
    }

    if(actionBtnList.length > 0){
      actionButtons = (
        '<div style="display:flex; flex-wrap:wrap; gap:8px; margin-bottom:16px;">' +
          actionBtnList.join('') +
        '</div>'
      );
    }

    // 5. Contributors Box HTML (Khung người tham gia: người tham gia thẻ đó + người đảm nhận thẻ con)
    var contributorsHtml = "";
    if(contributorNames && contributorNames.length > 0){
      contributorsHtml = (
        '<div class="canvas-card-box" style="margin-bottom:16px; padding:10px 14px; background:var(--bg-subtle); border-radius:10px; border:1px solid var(--border-light);">' +
          '<div style="font-size:11.5px; font-weight:700; color:var(--text-muted); text-transform:uppercase; letter-spacing:0.5px; margin-bottom:8px; display:flex; align-items:center; justify-content:space-between;">' +
            '<span style="font-weight:700;">참여 인원</span>' +
            '<span style="font-size:11px; font-weight:600; color:var(--text-cyan);">' + contributorNames.length + ' 명</span>' +
          '</div>' +
          '<div style="display:flex; flex-wrap:wrap; gap:8px;">' +
            contributorNames.map(function(name){
              var count = contributorMap[name];
              var countBadge = (typeof count === "number" && count > 0)
                ? '<span style="font-size:10.5px; font-weight:700; color:var(--text-cyan); background:var(--vs-cyan-ghost); padding:1px 6px; border-radius:10px;">' + count + '</span>'
                : '';
              var tooltipTitle = (typeof count === "number" && count > 0)
                ? (escapeHtml(name) + ' (' + count + ' 건 작업)')
                : escapeHtml(name);

              return (
                '<div style="display:inline-flex; align-items:center; gap:6px; padding:4px 10px; border-radius:14px; background:var(--bg-card); border:1px solid var(--border-light); font-size:12px; font-weight:600; color:var(--text-main); box-shadow:0 1px 2px rgba(0,0,0,0.03);" title="' + tooltipTitle + '">' +
                  '<span>' + escapeHtml(name) + '</span>' +
                  countBadge +
                '</div>'
              );
            }).join('') +
          '</div>' +
        '</div>'
      );
    }

    // 6. Labels HTML
    var labelsHtml = "";
    if(d.labels && d.labels.length > 0){
      labelsHtml = (
        '<div style="margin-bottom:14px; display:flex; flex-wrap:wrap; gap:4px;">' +
          d.labels.map(function(l){
            return '<span style="padding:2px 8px; border-radius:4px; font-size:11px; background:var(--vs-cyan-bg); color:var(--vs-cyan); border:1px solid var(--vs-cyan-light);">' + escapeHtml(l) + '</span>';
          }).join('') +
        '</div>'
      );
    }

    // 7. Attachments List HTML
    var attachmentsHtml = (
      '<div style="margin-bottom:16px;">' +
        '<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">' +
          '<span style="font-size:12px; font-weight:700; color:var(--text-muted); text-transform:uppercase; letter-spacing:0.5px;">첨부 파일 (' + attachments.length + ')</span>' +
          '<label style="cursor:pointer; color:var(--vs-cyan); font-size:12px; font-weight:600;">' +
            '+ 파일 추가' +
            '<input type="file" multiple style="display:none;" data-key="' + escapeHtml(key) + '" onchange="if(window.uploadLocalAttachment) window.uploadLocalAttachment(event, this.dataset.key);">' +
          '</label>' +
        '</div>' +
        (attachments.length > 0 ? (
          '<div style="display:flex; flex-direction:column; gap:6px;">' +
            attachments.map(function(a){
              var fname = (typeof a === "string") ? a : (a.filename || a.name || "file");
              var furl = (typeof a === "object" && a.url) ? a.url : "#";
              var fsize = (typeof a === "object" && a.size) ? Number(a.size) : 0;
              var fmimetype = (typeof a === "object" && a.mimetype) ? a.mimetype : "";
              var ext = (fname.split('.').pop() || '').toLowerCase();
              var isImg = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'bmp'].indexOf(ext) !== -1 || (fmimetype && fmimetype.indexOf('image/') === 0);
              var isPdf = ext === 'pdf' || fmimetype === 'application/pdf';
              var isText = ['txt', 'csv', 'log', 'md', 'json', 'xml', 'sql', 'html', 'js', 'py'].indexOf(ext) !== -1;
              var canPreview = isImg || isPdf || isText;
              var previewUrl = furl + (furl.indexOf('?') !== -1 ? '&preview=1' : '?preview=1');
              var safeName = escapeHtml(fname);
              var isFileLocal = false;
              if(a.isLocal === true || a.source === "local" || (furl && furl.indexOf("/data/attachments/") !== -1)){
                isFileLocal = true;
              } else if(a.isLocal === false || a.source === "jira" || (furl && (furl.indexOf("/api/jira/") !== -1 || furl.indexOf("atlassian.net") !== -1))){
                isFileLocal = false;
              } else if(isLocal){
                isFileLocal = true;
              }

              return (
                '<div class="canvas-card-box" style="padding:6px 10px; display:flex; justify-content:space-between; align-items:center; gap:8px;">' +
                  '<div style="display:flex; align-items:center; gap:10px; min-width:0; flex:1; cursor:pointer;" ' +
                       'data-url="' + escapeHtml(furl) + '" data-filename="' + safeName + '" data-size="' + fsize + '" data-mimetype="' + escapeHtml(fmimetype) + '" ' +
                       'onclick="' + (canPreview ? "window.previewAttachment(this.dataset.url, this.dataset.filename, Number(this.dataset.size), this.dataset.mimetype)" : "window.open('" + escapeHtml(furl) + "')") + '" ' +
                       'title="클릭하여 미리보기">' +
                    (isImg ? (
                      '<img src="' + escapeHtml(previewUrl) + '" alt="" style="width:34px; height:34px; object-fit:cover; border-radius:4px; border:1px solid var(--border-light); flex-shrink:0; background:var(--bg-subtle);">'
                    ) : (
                      '<div style="width:34px; height:34px; border-radius:4px; background:var(--bg-subtle); display:flex; align-items:center; justify-content:center; font-size:16px; flex-shrink:0;">' +
                        (isPdf ? '📄' : isText ? '📝' : '📎') +
                      '</div>'
                    )) +
                    '<div style="min-width:0; flex:1;">' +
                      '<div style="display:flex; align-items:center; gap:6px;">' +
                        '<span style="color:var(--text-main); font-size:13px; font-weight:600; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">' + safeName + '</span>' +
                        (isJiraGloballyEnabled ? (
                          !isFileLocal ? (
                            '<span style="font-size:10px; padding:1px 5px; background:rgba(0,82,204,0.12); color:#0052cc; border-radius:3px; font-weight:700; flex-shrink:0;">Jira</span>'
                          ) : (
                            '<span style="font-size:10px; padding:1px 5px; background:#ecfdf5; color:#059669; border-radius:3px; font-weight:700; flex-shrink:0;">Local</span>'
                          )
                        ) : '') +
                      '</div>' +
                      '<div style="font-size:11px; color:var(--text-muted); display:flex; gap:6px; align-items:center; margin-top:2px;">' +
                        '<span>' + (fsize > 0 ? (Math.round(fsize/1024) + ' KB') : '') + '</span>' +
                        (canPreview ? '<span style="color:var(--vs-cyan); font-weight:600;">• 미리보기</span>' : '') +
                      '</div>' +
                    '</div>' +
                  '</div>' +
                  '<div style="display:flex; align-items:center; gap:6px; flex-shrink:0;">' +
                    (canPreview ? (
                      '<button data-url="' + escapeHtml(furl) + '" data-filename="' + safeName + '" data-size="' + fsize + '" data-mimetype="' + escapeHtml(fmimetype) + '" ' +
                              'onclick="window.previewAttachment(this.dataset.url, this.dataset.filename, Number(this.dataset.size), this.dataset.mimetype)" ' +
                              'class="canvas-file-action-btn" ' +
                              'title="미리보기" aria-label="미리보기">' +
                        '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
                          '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>' +
                          '<circle cx="12" cy="12" r="3"></circle>' +
                        '</svg>' +
                      '</button>'
                    ) : '') +
                    '<a href="' + escapeHtml(furl) + '" download="' + safeName + '" class="canvas-file-action-btn" title="다운로드" aria-label="다운로드">' +
                      '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">' +
                        '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>' +
                        '<polyline points="7 10 12 15 17 10"></polyline>' +
                        '<line x1="12" y1="15" x2="12" y2="3"></line>' +
                      '</svg>' +
                    '</a>' +
                    (isFileLocal && a.id ? (
                      '<button data-key="' + escapeHtml(key) + '" data-id="' + Number(a.id) + '" onclick="if(window.deleteLocalAttachment) window.deleteLocalAttachment(this.dataset.key, Number(this.dataset.id));" class="canvas-file-action-btn btn-delete" title="삭제" aria-label="삭제">' +
                        '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
                          '<polyline points="3 6 5 6 21 6"></polyline>' +
                          '<path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>' +
                        '</svg>' +
                      '</button>'
                    ) : '') +
                  '</div>' +
                '</div>'
              );
            }).join('') +
          '</div>'
        ) : '') +
      '</div>'
    );

    // 8. Subtasks List HTML
    var subtasksHtml = "";
    if(subtasks.length > 0){
      subtasksHtml = (
        '<div style="margin-bottom:16px;">' +
          '<div style="font-size:12px; font-weight:700; color:var(--text-muted); margin-bottom:6px; text-transform:uppercase; letter-spacing:0.5px;">하위 작업 (' + subtasks.length + ')</div>' +
          '<div class="canvas-card-box" style="overflow:hidden;">' +
            subtasks.map(function(sub){
              var subDisplayStatus = formatStatus(sub.status);
              var sc = getStatusColor(subDisplayStatus);
              var hasAssignee = sub.assignee && !isUnassigned(sub.assignee);

              return (
                '<div class="canvas-subtask-item" style="padding:9px 12px; border-bottom:1px solid var(--border-light); display:flex; justify-content:space-between; align-items:center; cursor:pointer;" ' +
                     'onclick="window.showIssueInCanvas(\'' + escapeHtml(sub.key) + '\')">' +
                  '<div style="display:flex; align-items:center; gap:8px; flex:1; min-width:0;">' +
                    '<span style="color:var(--vs-cyan); font-weight:bold; font-size:12px; min-width:55px;">' + escapeHtml(sub.key) + '</span>' +
                    '<span style="color:var(--text-main); font-size:13px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">' + escapeHtml(sub.summary) + '</span>' +
                  '</div>' +
                  '<div style="display:flex; align-items:center; gap:8px; flex-shrink:0; margin-left:10px;">' +
                    (hasAssignee ? (
                      '<span style="display:inline-flex; align-items:center; gap:4px; font-size:11.5px; color:var(--text-body); background:var(--bg-subtle); padding:2px 8px; border-radius:10px; border:1px solid var(--border-light); font-weight:500;" title="' + escapeHtml(sub.assignee) + '">' +
                        '<span style="font-size:11px;">👤</span> <span>' + escapeHtml(sub.assignee) + '</span>' +
                      '</span>'
                    ) : '') +
                    '<span style="padding:2px 8px; border-radius:10px; font-size:11px; background:' + sc + '18; color:' + sc + '; border:1px solid ' + sc + '40; font-weight:600;">' + subDisplayStatus + '</span>' +
                  '</div>' +
                '</div>'
              );
            }).join('') +
          '</div>' +
        '</div>'
      );
    }

    // 9. Comments HTML
    var commentPlaceholder = isJiraGloballyEnabled ? "댓글을 입력하세요... (Jira와 실시간 동기화)" : "댓글을 입력하세요...";
    var commentsHtml = (
      '<div style="margin-bottom:16px;">' +
        '<div style="font-size:12px; font-weight:700; color:var(--text-muted); margin-bottom:6px; text-transform:uppercase; letter-spacing:0.5px;">댓글 (' + comments.length + ')</div>' +
        '<div style="margin-bottom:14px; position:relative;">' +
          '<div id="local-comment-input" class="custom-textarea" contenteditable="true" spellcheck="false" placeholder="' + commentPlaceholder + '" style="padding:10px 48px 10px 12px; background:var(--bg-input); color:var(--text-main); border:1px solid var(--border-input); border-radius:8px; font-size:13px; min-height:55px; max-height:180px; overflow-y:auto; line-height:1.5; outline:none; white-space:pre-wrap; word-break:break-word; transition:border-color 0.15s;"></div>' +
          '<button type="button" onclick="window.submitCanvasComment(\'' + escapeHtml(key) + '\')" class="btn-comment-send-plane" title="댓글 전송" aria-label="댓글 전송">' +
            '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" style="margin-left:-1px; margin-top:1px;">' +
              '<line x1="22" y1="2" x2="11" y2="13"></line>' +
              '<polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>' +
            '</svg>' +
          '</button>' +
        '</div>' +

        '<div style="display:flex; flex-direction:column; gap:8px;">' +
          (comments.length > 0 ? (
            comments.map(function(c){
              var isJiraComment = c.source === 'jira';
              return (
                '<div class="canvas-card-box" id="comment-card-' + (c.id || '') + '" style="padding:10px 12px;">' +
                  '<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">' +
                    '<div style="display:flex; align-items:center; gap:6px;">' +
                      '<span style="color:var(--vs-cyan); font-weight:600; font-size:12px;">👤 ' + escapeHtml(c.author || "사용자") + '</span>' +
                      (isJiraGloballyEnabled ? (
                        isJiraComment ? (
                          '<span style="font-size:10px; padding:1px 5px; background:rgba(59,130,246,0.1); color:#3b82f6; border-radius:3px; font-weight:600;">Jira</span>'
                        ) : (
                          '<span style="font-size:10px; padding:1px 5px; background:#ecfdf5; color:#059669; border-radius:3px; font-weight:600;">Local</span>'
                        )
                      ) : '') +
                      '<span style="color:var(--text-muted); font-size:11px;">' + formatCommentDate(c.created) + '</span>' +
                    '</div>' +
                  '</div>' +
                  '<div>' +
                    formatCommentContent(c.body) +
                  '</div>' +
                '</div>'
              );
            }).join('')
          ) : (
            '<span style="color:var(--text-muted); font-size:13px; font-style:italic;">댓글이 없습니다.</span>'
          )) +
        '</div>' +
      '</div>'
    );

    // 10. Dates Footer
    function formatFooterDate(val){
      if(!val) return '-';
      try {
        var dt = new Date(val);
        if(!isNaN(dt.getTime())){
          var isEn = (window.i18n && typeof window.i18n.getLang === "function") 
            ? (window.i18n.getLang() === "en") 
            : (localStorage.getItem("argos_lang") === "en" || localStorage.getItem("jarvisLang") === "en");
          return dt.toLocaleString(isEn ? 'en-US' : 'ko-KR');
        }
      } catch(e){}
      return String(val);
    }

    var rawCreated = d.created || d.createdAt || d.created_at || null;
    var rawUpdated = d.updated || d.updatedAt || d.updated_at || null;

    var datesHtml = (
      '<div style="display:flex; gap:16px; color:var(--text-muted); font-size:12px; border-top:1px solid var(--border-light); padding-top:12px; margin-top:8px;">' +
        '<span>생성일: ' + formatFooterDate(rawCreated) + '</span>' +
        '<span>수정일: ' + formatFooterDate(rawUpdated) + '</span>' +
      '</div>'
    );

    // 11. Open In Jira Button
    var openJiraHtml = "";
    var jiraUrl = (d.jira && d.jira.url) ? d.jira.url : (d.url && d.url !== '#' ? d.url : null);
    if(jiraUrl && isJiraGloballyEnabled){
      openJiraHtml = (
        '<div style="margin-top:14px;">' +
          '<a href="' + escapeHtml(jiraUrl) + '" target="_blank" rel="noopener" style="display:inline-block; padding:8px 16px; background:var(--vs-cyan); color:white; border-radius:6px; text-decoration:none; font-size:13px; font-weight:600; box-shadow:0 2px 6px rgba(51, 170, 211, 0.3);">' +
            'Jira에서 보기 ↗' +
          '</a>' +
        '</div>'
      );
    }

    // --- ASSEMBLE FULL CANVAS DOM (CHOIVIS HIGH CONTRAST STRUCTURE) ---
    contentEl.innerHTML = (
      '<div style="padding:16px; font-family:sans-serif;">' +
        // Header
        '<div style="display:flex; align-items:center; gap:12px; margin-bottom:16px;">' +
          (d.avatarUrl && displayAssignee !== '미배정' ? (
            '<img src="' + escapeHtml(d.avatarUrl) + '" style="width:40px; height:40px; border-radius:50%; border:2px solid var(--border-light); flex-shrink:0;">'
          ) : (
            '<div style="width:40px; height:40px; border-radius:50%; background:' + (displayAssignee === '미배정' ? '#64748b' : 'var(--bg-card)') + '; border:2px solid var(--border-light); display:flex; align-items:center; justify-content:center; font-size:18px; font-weight:700; color:' + (displayAssignee === '미배정' ? '#ffffff' : 'var(--text-cyan)') + '; flex-shrink:0;">' +
              (displayAssignee && displayAssignee !== '미배정' ? escapeHtml(displayAssignee.charAt(0)) : '?') +
            '</div>'
          )) +
          '<div style="flex:1; min-width:0;">' +
            '<div style="font-size:17px; font-weight:700; color:var(--text-main); word-break:break-word; line-height:1.4;">' + escapeHtml(summary) + '</div>' +
            '<div style="font-size:12px; color:var(--text-muted); margin-top:4px; display:flex; align-items:center; gap:6px; flex-wrap:wrap;">' +
              '<span>' + escapeHtml(displayType) + ' • <span style="color:' + getPriorityColor(displayPriority) + '; font-weight:600;">' + escapeHtml(displayPriority) + '</span></span>' +
              (scheduleRangeText ? (
                '<span style="color:var(--text-muted); opacity:0.6;">•</span>' +
                '<span style="display:inline-flex; align-items:center; gap:5px; padding:2px 8px; border-radius:4px; background:' + (d.is_scheduled === false ? 'rgba(100,116,139,0.12)' : 'rgba(51, 170, 211, 0.12)') + '; color:' + (d.is_scheduled === false ? 'var(--text-muted)' : 'var(--vs-cyan, #33aad3)') + '; font-weight:600; font-size:11.5px; border:1px solid ' + (d.is_scheduled === false ? 'rgba(100,116,139,0.3)' : 'rgba(51, 170, 211, 0.28)') + ';" title="' + (d.is_scheduled === false ? '달력 미표시 상태 (보관함에 보관 중)' : '배정된 일정') + '">' +
                  '<span>' + escapeHtml(scheduleRangeText) + (d.is_scheduled === false ? ' (달력 미표시)' : '') + '</span>' +
                '</span>'
              ) : '') +
            '</div>' +
          '</div>' +
        '</div>' +

        // Action Buttons
        actionButtons +

        // Status & Assignee Pills (Bên trên chỉ có nhãn tên người đảm nhận thẻ đó)
        '<div style="display:flex; gap:8px; flex-wrap:wrap; margin-bottom:16px;">' +
          (canEditRecord ? (
            '<span style="padding:4px 12px; border-radius:12px; font-size:12px; font-weight:600; background:' + statusColor + '18; color:' + statusColor + '; border:1px solid ' + statusColor + '40; cursor:pointer;" title="상태 변경 (클릭)" onclick="window.toggleStatusDropdown(\'' + escapeHtml(key) + '\', this)">' +
              escapeHtml(displayStatus) + ' ▾' +
            '</span>'
          ) : (
            '<span style="padding:4px 12px; border-radius:12px; font-size:12px; font-weight:600; background:' + statusColor + '18; color:' + statusColor + '; border:1px solid ' + statusColor + '40;">' +
              escapeHtml(displayStatus) +
            '</span>'
          )) +
          '<span style="padding:4px 12px; border-radius:12px; font-size:12px; background:var(--bg-card); color:var(--text-main); border:1px solid var(--border-light);">' +
            '👤 ' + escapeHtml(displayAssignee) +
          '</span>' +
          (parentKey ? (
            '<span style="padding:4px 12px; border-radius:12px; font-size:12px; background:rgba(124, 58, 237, 0.12); color:#a78bfa; border:1px solid rgba(167, 139, 250, 0.3); cursor:pointer;" onclick="window.showIssueInCanvas(\'' + escapeHtml(parentKey) + '\')" title="' + escapeHtml('상위 작업: ' + parentKey + (parentSummary ? ' (' + parentSummary + ')' : '') + ' (클릭하여 캔버스 열기)') + '">' +
              '⬆ ' + escapeHtml(parentKey) + (parentSummary ? (' (' + escapeHtml(parentSummary.length > 25 ? (parentSummary.slice(0, 24).trim() + '...') : parentSummary) + ')') : '') +
            '</span>'
          ) : '') +
        '</div>' +

        // Contributors Box
        contributorsHtml +

        // Labels
        labelsHtml +


        // Description Box
        '<div style="margin-bottom:16px;">' +
          '<div style="font-size:12px; font-weight:700; color:var(--text-muted); margin-bottom:6px; text-transform:uppercase; letter-spacing:0.5px;">상세 설명 (DESCRIPTION)</div>' +
          '<div class="canvas-card-box" style="padding:12px; color:var(--text-main); font-size:13px; line-height:1.6; white-space:pre-wrap;">' +
            (description ? escapeHtml(description) : '<span style="color:var(--text-muted); font-style:italic;">상세 설명 없음</span>') +
          '</div>' +
        '</div>' +

        // Attachments Box
        attachmentsHtml +

        // Subtasks Box
        subtasksHtml +

        // Comments Box
        commentsHtml +

        // Dates
        datesHtml +

        // Open in Jira
        openJiraHtml +
      '</div>'
    );

    // Bind Ctrl+Enter or Enter to submit comment
    var commentInput = document.getElementById("local-comment-input");
    if(commentInput){
      commentInput.addEventListener("keydown", function(e){
        if(e.key === "Enter" && !e.shiftKey){
          e.preventDefault();
          window.submitCanvasComment(key);
        }
      });
    }
  }

  // --- Inline Status Change Popup (Choivis Style) ---
  window.toggleStatusDropdown = function(issueKey, badgeEl){
    document.querySelectorAll('.status-dropdown-popup').forEach(function(el){ el.remove(); });
    if(!badgeEl) return;

    var curUser = (typeof getCurrentUser === "function") ? getCurrentUser() : null;
    var isAdm = false;
    var isMgr = false;
    if(curUser){
      var curRole = (typeof getSessionRole === "function") ? getSessionRole() : (curUser.role || ((curUser.isAdmin || curUser.is_admin) ? "admin" : (curUser.isManager ? "manager" : "member")));
      if(curRole === "admin" || curUser.isAdmin || curUser.is_admin){
        isAdm = true;
      } else if(curRole === "manager" || curUser.isManager){
        isMgr = true;
      }
    }
    var record = (window.records || []).find(function(r){ return String(r.id) === String(issueKey) || (r.cardCode && r.cardCode === issueKey) || (r.jira && r.jira.key === issueKey); });
    var isSameDept = false;
    if(curUser && record){
      var uDept = String(curUser.dept_id || curUser.org || "").trim().toLowerCase();
      var rDept = String(record.dept_id || record.org || "").trim().toLowerCase();
      if(uDept && rDept && uDept === rDept) isSameDept = true;
    }
    var canComplete = isAdm || (isMgr && isSameDept);

    var rect = badgeEl.getBoundingClientRect();
    var statuses = [
      { value: '예정', label: '예정', bg: 'rgba(100, 116, 139, 0.15)', color: '#94a3b8' },
      { value: '진행', label: '진행', bg: 'rgba(245, 158, 11, 0.15)', color: '#f59e0b' },
      { value: '검토', label: '검토', bg: 'rgba(59, 130, 246, 0.15)', color: '#3b82f6' }
    ];

    if(canComplete){
      statuses.push({ value: '완료', label: '완료', bg: 'rgba(34, 197, 94, 0.15)', color: '#22c55e' });
    }

    var dropdown = document.createElement('div');
    dropdown.className = 'status-dropdown-popup';
    dropdown.style.cssText = 'position:fixed; top:' + (rect.bottom + 4) + 'px; left:' + rect.left + 'px; z-index:9999; background:#1e293b; border:1px solid #334155; border-radius:8px; padding:4px; box-shadow:0 6px 20px rgba(0,0,0,0.5); min-width:130px;';

    statuses.forEach(function(s){
      var item = document.createElement('div');
      item.style.cssText = 'padding:6px 12px; cursor:pointer; border-radius:6px; font-size:12px; font-weight:600; color:' + s.color + '; display:flex; align-items:center; gap:6px; transition:background 0.15s;';
      item.innerHTML = '<span style="width:8px; height:8px; border-radius:50%; background:' + s.color + '; display:inline-block;"></span> ' + s.label;
      item.addEventListener('mouseenter', function(){ item.style.background = s.bg; });
      item.addEventListener('mouseleave', function(){ item.style.background = 'transparent'; });
      item.addEventListener('click', function(e){
        e.stopPropagation();
        dropdown.remove();

        apiPostJson("/api/issues/transition", { issue_key: issueKey, status: s.value }).then(function(res){
          if(res && res.ok){
            var isEn = (window.i18n && typeof window.i18n.getLang === "function") 
              ? (window.i18n.getLang() === "en") 
              : (localStorage.getItem("argos_lang") === "en" || localStorage.getItem("jarvisLang") === "en");
            var successMsg = s.value === '검토'
              ? (isEn ? "Status changed to 'Review'. Approval notification sent to manager & admin." : "상태를 '검토'로 변경했습니다. 부서 관리자 및 시스템 관리자에게 승인 요청 알림이 전송되었습니다.")
              : (isEn ? "Status updated to '" + s.value + "'." : "상태를 '" + s.value + "'(으)로 변경했습니다.");
            if(typeof showToast === "function") showToast(successMsg, 3500);
            window.showIssueInCanvas(issueKey);
            if(typeof loadRecords === "function") loadRecords();
          } else {
            if(typeof showToast === "function") showToast((res && res.error) || "상태 변경 실패", 3500, true);
          }
        }).catch(function(err){
          if(typeof showToast === "function") showToast("서버 오류: " + err.message, 3500, true);
        });
      });
      dropdown.appendChild(item);
    });

    document.body.appendChild(dropdown);

    var closeHandler = function(e){
      if(!dropdown.contains(e.target) && !badgeEl.contains(e.target)){
        dropdown.remove();
        document.removeEventListener('click', closeHandler);
      }
    };
    setTimeout(function(){ document.addEventListener('click', closeHandler); }, 10);
  };

  // --- Submit Comment ---
  window.submitCanvasComment = function(issueKey){
    var input = document.getElementById("local-comment-input");
    if(!input) return;
    var comment = (input.innerText || input.textContent || input.value || "").trim();
    if(!comment){
      if(typeof showToast === "function") showToast("댓글 내용을 입력해주세요.");
      return;
    }
    apiPostJson("/api/issues/comment", { issue_key: issueKey, comment: comment }).then(function(res){
      if(res && res.ok){
        if(typeof showToast === "function") showToast("댓글이 등록되었습니다.");
        if(input.innerText !== undefined) input.innerText = "";
        if(input.value !== undefined) input.value = "";
        window.showIssueInCanvas(issueKey);
      } else {
        if(typeof showToast === "function") showToast((res && res.error) || "댓글 등록 실패");
      }
    }).catch(function(err){
      if(typeof showToast === "function") showToast("서버 오류: " + err.message);
    });
  };

  // --- Canvas Custom Confirmation Dialog ---
  function showCanvasConfirmDialog(options){
    var existing = document.getElementById("canvas-confirm-modal");
    if(existing) existing.remove();

    var backdrop = document.createElement("div");
    backdrop.id = "canvas-confirm-modal";
    backdrop.className = "canvas-confirm-modal-backdrop";

    var card = document.createElement("div");
    card.className = "canvas-confirm-modal-card";

    var header = document.createElement("div");
    header.className = "canvas-confirm-modal-header";
    var iconHtml = (options.icon && options.icon !== "")
      ? ('<span class="canvas-confirm-modal-icon">' + options.icon + '</span>')
      : (options.icon === "" ? "" : '<span class="canvas-confirm-modal-icon">⚠️</span>');
    header.innerHTML = (
      iconHtml +
      '<h3 class="canvas-confirm-modal-title">' + escapeHtml(options.title || '확인') + '</h3>'
    );

    var body = document.createElement("div");
    body.className = "canvas-confirm-modal-body";
    body.innerHTML = options.bodyHtml || ('<p>' + escapeHtml(options.message || '') + '</p>');

    var footer = document.createElement("div");
    footer.className = "canvas-confirm-modal-footer";

    function cleanup(){
      if(backdrop && backdrop.parentNode) backdrop.remove();
      document.removeEventListener("keydown", onKeyDown);
    }

    function onKeyDown(e){
      if(e.key === "Escape"){
        cleanup();
        if(typeof options.onCancel === "function") options.onCancel();
      }
    }
    document.addEventListener("keydown", onKeyDown);

    backdrop.addEventListener("click", function(e){
      if(e.target === backdrop){
        cleanup();
        if(typeof options.onCancel === "function") options.onCancel();
      }
    });

    if(Array.isArray(options.buttons) && options.buttons.length > 0){
      options.buttons.forEach(function(b){
        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "canvas-confirm-btn " + (b.className || "canvas-confirm-btn-primary");
        btn.textContent = b.text || "확인";
        btn.addEventListener("click", function(){
          if(typeof b.onClick === "function"){
            btn.disabled = true;
            var origText = btn.textContent;
            btn.textContent = "처리 중...";
            Promise.resolve(b.onClick(cleanup)).catch(function(){
              btn.disabled = false;
              btn.textContent = origText;
            });
          } else {
            cleanup();
          }
        });
        footer.appendChild(btn);
      });
    } else {
      var btnCancel = document.createElement("button");
      btnCancel.type = "button";
      btnCancel.className = "canvas-confirm-btn canvas-confirm-btn-cancel";
      btnCancel.textContent = options.cancelText || "취소";

      var btnConfirm = document.createElement("button");
      btnConfirm.type = "button";
      btnConfirm.className = "canvas-confirm-btn " + (options.isDanger ? "canvas-confirm-btn-danger" : "canvas-confirm-btn-primary");
      btnConfirm.textContent = options.confirmText || "확인";

      footer.appendChild(btnCancel);
      footer.appendChild(btnConfirm);

      btnCancel.addEventListener("click", function(){
        cleanup();
        if(typeof options.onCancel === "function") options.onCancel();
      });

      btnConfirm.addEventListener("click", function(){
        btnConfirm.disabled = true;
        btnConfirm.textContent = "처리 중...";
        if(typeof options.onConfirm === "function"){
          Promise.resolve(options.onConfirm()).then(function(){
            cleanup();
          }).catch(function(){
            btnConfirm.disabled = false;
            btnConfirm.textContent = options.confirmText || "확인";
          });
        } else {
          cleanup();
        }
      });
    }

    card.appendChild(header);
    card.appendChild(body);
    card.appendChild(footer);
    backdrop.appendChild(card);
    document.body.appendChild(backdrop);
  }

  // --- Confirm Delete Local Record ---
  window.confirmDeleteLocalRecord = function(recordId, recordTitle){
    var displayTitle = recordTitle || ("#" + recordId);
    showCanvasConfirmDialog({
      icon: "🗑️",
      title: "로컬 업무 기록 삭제",
      bodyHtml: (
        '<div style="display:flex; flex-direction:column; gap:8px;">' +
          '<div style="font-weight:600; color:var(--text-main); font-size:14px;">정말 이 로컬 업무를 삭제하시겠습니까?</div>' +
          '<div style="padding:10px 12px; background:var(--bg-subtle, #f8fafc); border-radius:8px; border:1px solid var(--border-light, #e2e8f0); color:var(--text-muted); font-size:12.5px; word-break:break-all;">' +
            '<strong>항목:</strong> #' + escapeHtml(recordId) + ' ' + escapeHtml(displayTitle) +
          '</div>' +
          '<div style="font-size:12px; color:#ef4444; margin-top:2px;">⚠️ 삭제된 로컬 기록과 첨부파일은 복구할 수 없습니다.</div>' +
        '</div>'
      ),
      confirmText: "삭제하기",
      cancelText: "취소",
      isDanger: true,
      onConfirm: function(){
        var postFn = window.apiPostJson || (typeof apiPostJson !== "undefined" ? apiPostJson : null);
        if(!postFn){
          if(typeof showToast === "function") showToast("API 클라이언트를 찾을 수 없습니다.", 3000, true);
          return Promise.reject(new Error("API 클라이언트 부재"));
        }
        return postFn("/api/records/delete", { id: recordId }).then(function(res){
          if(res && res.ok){
            if(typeof showToast === "function") showToast("로컬 업무 기록이 삭제되었습니다.");
            window.closeCanvas();
            if(typeof loadRecords === "function") loadRecords();
          } else {
            if(typeof showToast === "function") showToast((res && res.error) || "기록 삭제 실패", 3000, true);
            throw new Error((res && res.error) || "기록 삭제 실패");
          }
        }).catch(function(err){
          if(typeof showToast === "function") showToast("오류: " + err.message, 3000, true);
          throw err;
        });
      }
    });
  };

  // --- Confirm Push Local Record to Jira ---
  window.confirmPushLocalRecordToJira = function(recordId, recordTitle){
    var displayTitle = recordTitle || ("#" + recordId);

    function doPush(pushParentFirst, cleanupCb){
      var postFn = window.apiPostJson || (typeof apiPostJson !== "undefined" ? apiPostJson : null);
      if(!postFn){
        if(typeof showToast === "function") showToast("API 클라이언트를 찾을 수 없습니다.", 3000, true);
        return Promise.reject(new Error("API 클라이언트 부재"));
      }
      return postFn("/api/records/push-jira", {
        id: recordId,
        push_parent_first: Boolean(pushParentFirst)
      }).then(function(res){
        if(res && res.ok){
          var jKey = res.jira_key || "Jira 이슈";
          var extraMsg = "";
          if(res.pushed_parents && res.pushed_parents.length > 0){
            extraMsg = " (상위 " + res.pushed_parents.length + "개 작업도 함께 발행됨)";
          }
          if(typeof showToast === "function") showToast("🚀 " + jKey + " 티켓으로 성공적으로 발행되었습니다!" + extraMsg);
          // 담당자/필드가 Jira 정책상 빠졌을 수 있으므로 서버가 준 안내를 함께 표시한다.
          if(res.note && typeof showToast === "function"){
            setTimeout(function(){ showToast("ℹ️ " + res.note, 4500); }, 400);
          }
          if(typeof loadRecords === "function") loadRecords();
          if(typeof cleanupCb === "function") cleanupCb();
          if(res.jira_key){
            window.showIssueInCanvas(res.jira_key);
          } else {
            window.closeCanvas();
          }
        } else {
          if(typeof showToast === "function") showToast((res && res.error) || "Jira 발행 실패", 3000, true);
          throw new Error((res && res.error) || "Jira 발행 실패");
        }
      }).catch(function(err){
        if(typeof showToast === "function") showToast("오류: " + err.message, 3000, true);
        throw err;
      });
    }

    // 1. Fetch Hierarchy Info
    var getFn = window.apiGetJson || window.apiGet || (typeof apiGetJson !== "undefined" ? apiGetJson : null);
    if(!getFn){
      return doPush(false);
    }
    getFn("/api/records/hierarchy?id=" + encodeURIComponent(recordId)).then(function(hData){
      var chain = (hData && hData.chain) || [];
      var hasUnpushedParents = Boolean(hData && hData.hasUnpushedParents);
      var closestJiraParent = (hData && hData.closestJiraParent) || null;
      var depth = (chain && chain.length) || 1;

      // Tree HTML Visualization
      var treeHtml = "";
      if(chain.length > 1){
        treeHtml = (
          '<div style="margin:8px 0 10px; padding:10px 12px; background:var(--bg-subtle, #f8fafc); border:1px solid var(--border-light, #e2e8f0); border-radius:8px; font-size:12px; max-height:160px; overflow-y:auto;">' +
            '<div style="font-weight:700; color:var(--text-muted); margin-bottom:6px; font-size:11px; text-transform:uppercase; letter-spacing:0.5px;">업무 계층 구조 (' + depth + '단계)</div>' +
            chain.map(function(node, idx){
              var indent = idx * 14;
              var isCur = Boolean(node.isCurrent);
              var badge = node.hasJira
                ? '<span style="color:#10b981; font-weight:700; margin-left:4px; font-size:11px;">[Jira: ' + escapeHtml(node.jiraKey) + ']</span>'
                : '<span style="color:var(--text-muted); font-size:11px; margin-left:4px;">(로컬)</span>';
              var codePart = escapeHtml(node.cardCode || '');
              var titlePart = escapeHtml(node.title || '');
              var shortTitle = titlePart.length > 25 ? (titlePart.substring(0, 25) + '…') : titlePart;
              return (
                '<div style="padding-left:' + indent + 'px; margin-bottom:3px; font-size:12px; color:' + (isCur ? 'var(--vs-cyan, #0284c7)' : 'var(--text-main)') + '; font-weight:' + (isCur ? '700' : '500') + ';">' +
                  (idx > 0 ? '└── ' : '■ ') + '[' + codePart + '] ' + shortTitle +
                  (isCur ? ' <span style="background:var(--vs-cyan-ghost, #e0f2fe); color:var(--vs-cyan, #0284c7); padding:1px 5px; border-radius:4px; font-size:10px; font-weight:700;">현재 작업</span>' : '') +
                  badge +
                '</div>'
              );
            }).join('') +
          '</div>'
        );
      }

      // Case A: Has unpushed parents in hierarchy
      if(hasUnpushedParents){
        showCanvasConfirmDialog({
          icon: "",
          title: "Jira 계층 연동 및 발행 안내",
          bodyHtml: (
            '<div style="display:flex; flex-direction:column; gap:8px;">' +
              '<div style="font-weight:600; color:var(--text-main); font-size:13.5px;">상위 작업이 아직 Jira에 등록되지 않았습니다.</div>' +
              '<div style="font-size:12px; color:var(--text-muted); line-height:1.5;">' +
                'Jira Cloud 정책상 상위 작업이 Jira에 존재해야 하위 작업(Sub-task)으로 연동할 수 있습니다. 아래 2가지 방법 중 하나를 선택해 주세요:' +
              '</div>' +
              treeHtml +
              '<div style="padding:10px 12px; background:var(--bg-subtle, #f8fafc); border-radius:8px; border-left:3px solid var(--vs-cyan, #0284c7); font-size:12px; line-height:1.45; color:var(--text-muted);">' +
                '<strong style="color:var(--text-main);">① 독립 작업으로 발행 (권장):</strong><br>' +
                '이 작업을 Jira의 표준 Task로 등록하고, 전체 계층 경로(Breadcrumb)를 본문에 자동으로 기록합니다.<br><br>' +
                '<strong style="color:var(--text-main);">② 상위 작업과 함께 순차 발행:</strong><br>' +
                '아직 Jira에 없는 상위 작업을 최상위부터 순차 발행한 후, 현재 작업을 하위 작업으로 연결합니다.' +
              '</div>' +
            '</div>'
          ),
          buttons: [
            {
              text: "취소",
              className: "canvas-confirm-btn-cancel",
              onClick: function(cleanup){ cleanup(); }
            },
            {
              text: "🔗 상위 작업과 함께 발행",
              className: "canvas-confirm-btn-secondary",
              onClick: function(cleanup){ return doPush(true, cleanup); }
            },
            {
              text: "🚀 독립 작업으로 발행 (권장)",
              className: "canvas-confirm-btn-primary",
              onClick: function(cleanup){ return doPush(false, cleanup); }
            }
          ]
        });
      } else {
        // Case B: No unpushed parents (Root or parent already in Jira)
        var noticeSubtask = closestJiraParent
          ? ('<div style="font-size:12px; color:#10b981; font-weight:600; margin-top:2px;">🔗 상위 Jira 티켓 [' + escapeHtml(closestJiraParent) + ']의 하위 작업(Sub-task)으로 자동 연동됩니다.</div>')
          : '<div style="font-size:12px; color:var(--text-muted); margin-top:2px;">발행 즉시 Jira Cloud에 실제 이슈가 등록되고 로컬 기록과 실시간 동기화됩니다.</div>';

        showCanvasConfirmDialog({
          icon: "🚀",
          title: "Jira Cloud로 내보내기",
          bodyHtml: (
            '<div style="display:flex; flex-direction:column; gap:8px;">' +
              '<div style="font-weight:600; color:var(--text-main); font-size:14px;">이 로컬 업무를 Jira 티켓으로 발행하시겠습니까?</div>' +
              '<div style="padding:10px 12px; background:var(--bg-subtle, #f8fafc); border-radius:8px; border:1px solid var(--border-light, #e2e8f0); color:var(--text-muted); font-size:12.5px; word-break:break-all;">' +
                '<strong>대상:</strong> #' + escapeHtml(recordId) + ' ' + escapeHtml(displayTitle) +
              '</div>' +
              treeHtml +
              noticeSubtask +
            '</div>'
          ),
          confirmText: "Jira로 발행",
          cancelText: "취소",
          isDanger: false,
          onConfirm: function(){
            return doPush(false);
          }
        });
      }
    }).catch(function(){
      // Fallback to simple confirm dialog if hierarchy API fails
      showCanvasConfirmDialog({
        icon: "🚀",
        title: "Jira Cloud로 내보내기",
        bodyHtml: (
          '<div style="display:flex; flex-direction:column; gap:8px;">' +
            '<div style="font-weight:600; color:var(--text-main); font-size:14px;">이 로컬 업무를 Jira 티켓으로 발행하시겠습니까?</div>' +
            '<div style="padding:10px 12px; background:var(--bg-subtle, #f8fafc); border-radius:8px; border:1px solid var(--border-light, #e2e8f0); color:var(--text-muted); font-size:12.5px; word-break:break-all;">' +
              '<strong>대상:</strong> #' + escapeHtml(recordId) + ' ' + escapeHtml(displayTitle) +
            '</div>' +
            '<div style="font-size:12px; color:var(--text-muted); margin-top:2px;">발행 즉시 Jira Cloud에 실제 이슈가 등록되고 로컬 기록과 실시간 동기화됩니다.</div>' +
          '</div>'
        ),
        confirmText: "Jira로 발행",
        cancelText: "취소",
        isDanger: false,
        onConfirm: function(){
          return doPush(false);
        }
      });
    });
  };

  // --- Attachment Preview Modal ---
  window.previewAttachment = function(url, filename, size, mimetype){
    var modal = document.getElementById("attachment-preview-modal");
    var iconEl = document.getElementById("preview-modal-icon");
    var fnameEl = document.getElementById("preview-modal-filename");
    var sizeEl = document.getElementById("preview-modal-size");
    var dlBtn = document.getElementById("preview-modal-download-btn");
    var bodyEl = document.getElementById("preview-modal-body");

    if(!modal || !bodyEl) return;

    if(fnameEl) fnameEl.textContent = filename || "파일";
    if(sizeEl) sizeEl.textContent = size > 0 ? ("(" + Math.round(size / 1024) + " KB)") : "";
    if(dlBtn){
      dlBtn.href = url;
      dlBtn.download = filename || "download";
    }

    modal.hidden = false;
    bodyEl.innerHTML = '<div style="padding:24px; color:var(--vs-cyan, #33aad3); font-weight:600; text-align:center;">미리보기 불러오는 중...</div>';

    window._currentPreviewBlobUrl = null;

    var ext = ((filename || "").split('.').pop() || '').toLowerCase();
    var isImg = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'bmp'].indexOf(ext) !== -1 || (mimetype && mimetype.indexOf('image/') === 0);
    var isPdf = ext === 'pdf' || mimetype === 'application/pdf';
    var isText = ['txt', 'csv', 'log', 'md', 'json', 'xml', 'sql', 'html', 'js', 'py'].indexOf(ext) !== -1;
    var previewUrl = url + (url.indexOf('?') !== -1 ? '&preview=1' : '?preview=1');
    var authHeaders = (typeof getAuthHeaders === 'function') ? getAuthHeaders() : {};

    if(isImg){
      if(iconEl) iconEl.textContent = '🖼️';
      bodyEl.innerHTML = '<div style="padding:16px; display:flex; align-items:center; justify-content:center; width:100%; height:100%;">' +
        '<img src="' + escapeHtml(previewUrl) + '" alt="" style="max-width:100%; max-height:100%; object-fit:contain; border-radius:6px; box-shadow:0 4px 16px rgba(0,0,0,0.4);">' +
        '</div>';
    } else if(isPdf){
      if(iconEl) iconEl.textContent = '📄';
      fetch(previewUrl, { headers: authHeaders })
        .then(function(r){
          if(!r.ok) throw new Error("HTTP " + r.status);
          return r.blob();
        })
        .then(function(blob){
          var pdfBlob = new Blob([blob], { type: 'application/pdf' });
          window._currentPreviewBlobUrl = URL.createObjectURL(pdfBlob);
          bodyEl.innerHTML = '<iframe src="' + window._currentPreviewBlobUrl + '#toolbar=1&navpanes=0" style="width:100%; height:100%; min-height:550px; border:none; background:#ffffff;"></iframe>';
        })
        .catch(function(err){
          bodyEl.innerHTML = '<div style="padding:28px 20px; color:#ef4444; text-align:center;">' +
            '<div style="font-size:36px; margin-bottom:8px;">📄</div>' +
            '<div style="font-weight:600; font-size:14px; margin-bottom:6px;">PDF 문서를 미리보기 창에 불러오지 못했습니다.</div>' +
            '<div style="font-size:12px; color:var(--text-muted); margin-bottom:18px;">(' + escapeHtml(err.message || String(err)) + ')</div>' +
            '<a href="' + escapeHtml(url) + '" download="' + escapeHtml(filename) + '" class="preview-header-btn" style="padding:8px 18px; font-size:13px; text-decoration:none; display:inline-flex; align-items:center; gap:8px;">' +
              '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>' +
              '<span>파일 다운로드하여 열기</span>' +
            '</a>' +
          '</div>';
        });
    } else if(isText){
      if(iconEl) iconEl.textContent = '📝';
      fetch(previewUrl, { headers: authHeaders })
        .then(function(r){ return r.text(); })
        .then(function(text){
          bodyEl.innerHTML = '<div style="width:100%; height:100%; padding:18px 24px; overflow:auto; background:#131d2e;">' +
            '<pre style="margin:0; font-family:Consolas, monospace; font-size:12.5px; line-height:1.6; color:#f8fafc; white-space:pre-wrap; word-break:break-word;">' + escapeHtml(text) + '</pre>' +
            '</div>';
        })
        .catch(function(err){
          bodyEl.innerHTML = '<div style="padding:24px; color:#ef4444; text-align:center;">텍스트 내용을 불러올 수 없습니다: ' + escapeHtml(err.message) + '</div>';
        });
    } else {
      if(iconEl) iconEl.textContent = '📎';
      bodyEl.innerHTML = '<div style="text-align:center; padding:40px 20px;">' +
        '<div style="font-size:48px; margin-bottom:12px;">📁</div>' +
        '<div style="font-size:15px; font-weight:600; color:#f8fafc; margin-bottom:6px;">' + escapeHtml(filename) + '</div>' +
        '<div style="font-size:13px; color:#94a3b8; margin-bottom:20px;">브라우저에서 직접 미리보기를 지원하지 않는 형식입니다.</div>' +
        '<a href="' + escapeHtml(url) + '" download="' + escapeHtml(filename) + '" class="preview-header-btn" style="padding:8px 18px; font-size:13px; text-decoration:none; display:inline-flex; align-items:center; gap:8px;">' +
          '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>' +
          '<span>파일 다운로드</span>' +
        '</a>' +
        '</div>';
    }
  };

  window.closeAttachmentPreview = function(){
    if(window._currentPreviewBlobUrl){
      try { URL.revokeObjectURL(window._currentPreviewBlobUrl); } catch(e){}
      window._currentPreviewBlobUrl = null;
    }
    var modal = document.getElementById("attachment-preview-modal");
    if(modal){
      modal.hidden = true;
      var bodyEl = document.getElementById("preview-modal-body");
      if(bodyEl) bodyEl.innerHTML = "";
    }
  };

  // --- Upload Files To Canvas Issue (Direct to Jira REST API) ---
  window.uploadFilesToCanvasIssue = function(issueKey, files){
    if(!files || !files.length || !issueKey) return;
    var fileArr = Array.from(files);
    var validFiles = [];
    var maxBytes = 25 * 1024 * 1024; // 25MB

    for(var i = 0; i < fileArr.length; i++){
      var f = fileArr[i];
      if(f.size > maxBytes){
        if(typeof showToast === "function"){
          showToast("⚠️ 파일이 너무 큽니다 (최대 25MB): " + f.name, 1000, true);
        }
      } else {
        validFiles.push(f);
      }
    }
    if(validFiles.length === 0) return;

    var titleEl = document.getElementById("canvasTitleText");
    var origTitle = titleEl ? titleEl.textContent : "";
    if(titleEl) titleEl.textContent = "⏳ " + validFiles.length + "개 파일 Jira에 업로드 중...";

    var formData = new FormData();
    formData.append("issue_key", issueKey);
    validFiles.forEach(function(file){
      formData.append("files", file, file.name);
    });

    var headers = (typeof getAuthHeaders === "function") ? getAuthHeaders() : {};
    var csrfToken = sessionStorage.getItem("argosCsrfToken") || localStorage.getItem("argosCsrfToken");
    if(csrfToken) headers["X-CSRF-Token"] = csrfToken;

    fetch("/api/issues/attachments", {
      method: "POST",
      headers: headers,
      credentials: "same-origin",
      body: formData
    })
    .then(function(r){ return r.json(); })
    .then(function(res){
      if(titleEl) titleEl.textContent = origTitle;
      if(res && res.ok){
        if(typeof showToast === "function"){
          showToast("✅ Jira에 파일 " + validFiles.length + "개가 업로드되었습니다.", 2000);
        }
        window.showIssueInCanvas(issueKey);
        if(typeof loadRecords === "function") loadRecords();
      } else {
        var errMsg = (res && res.error) ? res.error : "Jira 파일 업로드 실패";
        // User requested: Nếu Jira từ chối thì hiện chữ nổi thông báo lỗi tầm 1s
        if(typeof showToast === "function"){
          showToast("⚠️ " + errMsg, 1000, true);
        }
      }
    })
    .catch(function(err){
      if(titleEl) titleEl.textContent = origTitle;
      if(typeof showToast === "function"){
        showToast("⚠️ 업로드 통신 오류: " + (err.message || String(err)), 1000, true);
      }
    });
  };

  // --- Upload from File Input (+ 파일 추가) ---
  window.uploadLocalAttachment = function(event, key){
    if(!event || !event.target || !event.target.files) return;
    window.uploadFilesToCanvasIssue(key, event.target.files);
    event.target.value = "";
  };

  // --- Delete Local Attachment ---
  window.deleteLocalAttachment = function(key, attachmentId){
    if(!key || !attachmentId) return;
    if(!confirm("해당 첨부파일을 삭제하시겠습니까?")) return;

    var postFn = (typeof apiPostJson === "function") ? apiPostJson : (typeof apiPost === "function" ? apiPost : null);
    if(!postFn) return;

    postFn("/api/records/attachments/delete", { key: key, attachment_id: attachmentId })
      .then(function(res){
        if(res && res.ok){
          if(typeof showToast === "function") showToast("✅ 첨부파일이 삭제되었습니다.");
          window.showIssueInCanvas(key);
          if(typeof loadRecords === "function") loadRecords();
        } else {
          var errMsg = (res && res.error) || "첨부파일 삭제 실패";
          if(typeof showToast === "function") showToast("⚠️ " + errMsg, 1500, true);
        }
      })
      .catch(function(err){
        if(typeof showToast === "function") showToast("⚠️ 삭제 통신 오류: " + (err.message || String(err)), 1500, true);
      });
  };

  // --- Canvas Drag & Drop Overlay Handler ---
  function initCanvasDragAndDrop(){
    var canvasPanel = document.getElementById("canvasPanel");
    var dragOverlay = document.getElementById("canvasDragOverlay");
    var cardKeyEl = document.getElementById("canvasDragCardKey");
    var dragDepth = 0;

    // Prevent default browser file open on window
    window.addEventListener("dragover", function(e){
      if(e.dataTransfer && e.dataTransfer.types && Array.from(e.dataTransfer.types).indexOf("Files") !== -1){
        e.preventDefault();
      }
    }, false);

    window.addEventListener("drop", function(e){
      if(e.dataTransfer && e.dataTransfer.types && Array.from(e.dataTransfer.types).indexOf("Files") !== -1){
        e.preventDefault();
      }
    }, false);

    if(!canvasPanel) return;

    canvasPanel.addEventListener("dragenter", function(e){
      if(canvasPanel.hidden || !currentIssueKey) return;
      if(e.dataTransfer && e.dataTransfer.types && Array.from(e.dataTransfer.types).indexOf("Files") !== -1){
        e.preventDefault();
        dragDepth++;
        if(cardKeyEl) cardKeyEl.textContent = "🎫 " + currentIssueKey;
        if(dragOverlay) dragOverlay.hidden = false;
      }
    });

    canvasPanel.addEventListener("dragover", function(e){
      if(canvasPanel.hidden || !currentIssueKey) return;
      if(e.dataTransfer && e.dataTransfer.types && Array.from(e.dataTransfer.types).indexOf("Files") !== -1){
        e.preventDefault();
        e.dataTransfer.dropEffect = "copy";
      }
    });

    canvasPanel.addEventListener("dragleave", function(e){
      if(canvasPanel.hidden || !currentIssueKey) return;
      dragDepth--;
      if(dragDepth <= 0){
        dragDepth = 0;
        if(dragOverlay) dragOverlay.hidden = true;
      }
    });

    canvasPanel.addEventListener("drop", function(e){
      if(canvasPanel.hidden || !currentIssueKey) return;
      e.preventDefault();
      dragDepth = 0;
      if(dragOverlay) dragOverlay.hidden = true;

      var files = e.dataTransfer ? e.dataTransfer.files : null;
      if(files && files.length > 0){
        window.uploadFilesToCanvasIssue(currentIssueKey, files);
      }
    });
  }

  // --- Initial Event Listeners on DOMContentLoaded ---
  document.addEventListener("DOMContentLoaded", function(){
    function handleResize(){
      updateTopbarHeight();
      var canvas = document.getElementById("canvasPanel");
      if(canvas && !canvas.hidden){
        var mode = window.getCanvasDisplayMode();
        window.setCanvasDisplayMode(mode);
      }
    }
    updateTopbarHeight();
    window.addEventListener("resize", handleResize);

    initCanvasDragAndDrop();

    if(typeof window.initCanvasResizer === "function"){
      window.initCanvasResizer();
    }

    var btnClose = document.getElementById("btnCanvasClose");
    if(btnClose) btnClose.addEventListener("click", window.closeCanvas);

    var backdrop = document.getElementById("canvasBackdrop");
    if(backdrop) backdrop.addEventListener("click", window.closeCanvas);

    document.addEventListener("click", function(e){
      var unassignBtn = e.target.closest(".btn-canvas-unassign-sched");
      if(unassignBtn){
        e.stopPropagation();
        var code = unassignBtn.getAttribute("data-code");
        if(code && window.unassignTask){
          window.unassignTask(code);
          window.closeCanvas();
        }
        return;
      }

      var restoreBtn = e.target.closest(".btn-canvas-restore-sched");
      if(restoreBtn){
        e.stopPropagation();
        var code = restoreBtn.getAttribute("data-code");
        if(code && window.showScheduleTask){
          window.showScheduleTask(code);
          window.closeCanvas();
        }
        return;
      }
    });

    ["docked", "overlay", "modal"].forEach(function(m){
      var btn = document.getElementById("btnCanvasMode" + m.charAt(0).toUpperCase() + m.slice(1));
      if(btn){
        btn.addEventListener("click", function(){
          window.setCanvasDisplayMode(m);
        });
      }
    });

    // Initialize record edit modal
    initRecordEditModal();

    document.addEventListener("keydown", function(e){
      if(e.key === "Escape"){
        var editModal = document.getElementById("recordEditModal");
        if(editModal && !editModal.hidden){
          editModal.hidden = true;
          return;
        }
        var previewModal = document.getElementById("attachment-preview-modal");
        if(previewModal && !previewModal.hidden){
          window.closeAttachmentPreview();
          return;
        }
        var canvas = document.getElementById("canvasPanel");
        if(canvas && !canvas.hidden){
          window.closeCanvas();
        }
      }
    });
  });

  // ── Record Edit Modal (Comprehensive: Title, Assignee, Participants, Dates, Memo) ──
  function initRecordEditModal(){
    var modal = document.getElementById("recordEditModal");
    var form = document.getElementById("formRecordEdit");
    var closeBtn = document.getElementById("btnRecordEditClose");
    var cancelBtn = document.getElementById("btnRecordEditCancel");
    var headerEditBtn = document.getElementById("btnCanvasEditTask");
    var submitBtn = document.getElementById("btnRecordEditSubmit");
    var errEl = document.getElementById("recordEditError");

    if(!modal || !form) return;

    function closeModal(){
      modal.hidden = true;
      if(errEl) errEl.hidden = true;
      if(window.recordEditParentTomSelect){
        try { window.recordEditParentTomSelect.setValue("", false); } catch(e){}
      }
    }

    var editPrioSelect = document.getElementById("recordEditPrioritySelect");
    if(editPrioSelect){
      editPrioSelect.addEventListener("change", function(){
        this.style.color = getPriorityColor(this.value);
      });
      editPrioSelect.addEventListener("input", function(){
        this.style.color = getPriorityColor(this.value);
      });
    }

    if(closeBtn) closeBtn.addEventListener("click", closeModal);
    if(cancelBtn) cancelBtn.addEventListener("click", closeModal);
    modal.addEventListener("click", function(e){
      if(e.target === modal) closeModal();
    });

    if(headerEditBtn){
      headerEditBtn.addEventListener("click", function(){
        if(window.currentCanvasIssueKey){
          window.openEditRecordModal(window.currentCanvasIssueKey);
        }
      });
    }

    function populateAssignees(selectedName){
      var select = document.getElementById("recordEditAssigneeSelect");
      if(!select) return;
      select.innerHTML = '<option value="">미배정 (선택 안 함)</option>';

      function fillOptions(members){
        select.innerHTML = '<option value="">미배정 (선택 안 함)</option>';
        var curClean = (selectedName || "").toLowerCase().trim();
        members.forEach(function(m){
          var n = (m.name || m.canonical_name || "").trim();
          if(!n || n === "미배정" || n === "Unassigned") return;
          var org = m.org ? (" (" + m.org + ")") : "";
          var opt = document.createElement("option");
          opt.value = n;
          opt.textContent = n + org;
          if(m.email) opt.setAttribute("data-email", m.email);
          if(curClean && (n.toLowerCase() === curClean || curClean.indexOf(n.toLowerCase()) !== -1)){
            opt.selected = true;
          }
          select.appendChild(opt);
        });
      }

      if(window.__companyMembers && window.__companyMembers.length > 0){
        fillOptions(window.__companyMembers);
      } else if(typeof apiGet === "function"){
        apiGet("/api/members").then(function(res){
          if(res && res.ok && Array.isArray(res.members)){
            window.__companyMembers = res.members;
            fillOptions(res.members);
          }
        }).catch(function(){});
      }
    }

    window.openEditRecordModal = function(issueKey){
      var key = issueKey || window.currentCanvasIssueKey;
      if(!key) return;

      var d = window.currentCanvasIssueDetail || {};
      // RBAC Security Check: Kiem tra quyen sua truoc khi mo modal
      var curUser = (typeof getCurrentUser === "function") ? getCurrentUser() : null;
      var canEdit = false;
      if(curUser){
        var curRole = (typeof getSessionRole === "function") ? getSessionRole() : (curUser.role || ((curUser.isAdmin || curUser.is_admin) ? "admin" : (curUser.isManager ? "manager" : "member")));
        if(curRole === "admin" || curUser.isAdmin || curUser.is_admin){
          canEdit = true;
        } else if(curRole !== "viewer"){
          var uId = String(curUser.id || curUser.user_id || "");
          var uName = String(curUser.name || "").trim().toLowerCase();
          var uUsername = String(curUser.username || "").trim().toLowerCase();
          var uDept = String(curUser.dept_id || curUser.org || "").trim().toLowerCase();

          var rDept = String(d.dept_id || d.org || "").trim().toLowerCase();
          var rAssigneeId = String(d.assignee_id || "");
          var rAssignee = String(d.assignee_name || d.assignee || "").trim().toLowerCase();

          if((curRole === "manager" || curUser.isManager) && uDept && rDept && uDept === rDept){
            canEdit = true;
          } else if(uId && rAssigneeId && uId === rAssigneeId){
            canEdit = true;
          } else if(uUsername && rAssignee && uUsername === rAssignee){
            canEdit = true;
          } else if(uName && rAssignee && uName === rAssignee){
            canEdit = true;
          }
        }
      }
      if(!canEdit){
        alert("해당 업무 카드를 수정할 권한이 없습니다.\n(작성자, 담당자 또는 해당 부서의 관리자만 수정 가능합니다)");
        return;
      }
      if(d.key !== key && d.cardCode !== key && d.id !== key){
        // Fetch fresh if detail not matching
        if(typeof apiGet === "function"){
          apiGet("/api/issues?key=" + encodeURIComponent(key)).then(function(res){
            if(res){
              window.currentCanvasIssueDetail = res;
              fillModalFields(res, key);
            }
          });
        }
        return;
      }
      fillModalFields(d, key);
    };

    function fillModalFields(d, key){
      var keyEl = document.getElementById("recordEditKey");
      var badgeEl = document.getElementById("recordEditCardCodeBadge");
      var titleInput = document.getElementById("recordEditTitleInput");
      var partsInput = document.getElementById("recordEditParticipantsInput");
      var startInput = document.getElementById("recordEditStartDateInput");
      var dueInput = document.getElementById("recordEditDueDateInput");
      var memoInput = document.getElementById("recordEditMemoInput");

      if(keyEl) keyEl.value = key;
      if(badgeEl) badgeEl.textContent = d.cardCode || key;

      var titleVal = (d.jira && d.jira.summary) ? d.jira.summary : (d.title || d.summary || "");
      if(titleInput) titleInput.value = titleVal;

      var rawStart = d.startDate || d.start_date || "";
      var rawDue = d.dueDate || d.due_date || "";
      if(startInput) startInput.value = rawStart ? rawStart.slice(0, 10) : "";
      if(dueInput) dueInput.value = rawDue ? rawDue.slice(0, 10) : "";

      var partsVal = "";
      if(d.participants){
        if(Array.isArray(d.participants)) partsVal = d.participants.join(", ");
        else partsVal = String(d.participants);
      }
      if(partsInput) partsInput.value = partsVal;

      var memoVal = d.memo || d.description || "";
      if(memoInput) memoInput.value = memoVal;

      var editPrioEl = document.getElementById("recordEditPrioritySelect");
      if(editPrioEl){
        var curPrio = formatPriority(d.priority || ((d.jira && d.jira.priority) ? d.jira.priority : "보통"));
        editPrioEl.value = curPrio;
        editPrioEl.style.color = getPriorityColor(curPrio);
        editPrioEl.style.fontWeight = "600";
      }

      // Optimistic Locking: 현재 편집 중인 레코드의 버전 보관
      window.__editingRecordVersion = (d.version !== undefined && d.version !== null) ? Number(d.version) : 1;

      if(errEl){
        errEl.hidden = true;
        errEl.textContent = "";
        errEl.innerHTML = "";
      }

      populateAssignees(d.assignee || "");
      populateParentOptions(d.parentKey || (d.jira && d.jira.parentKey) || "", key, d.id);
      modal.hidden = false;
      if(titleInput) titleInput.focus();
    }

    function populateParentOptions(selectedParentKey, currentKey, currentId){
      var select = document.getElementById("recordEditParentSelect");
      if(!select) return;

      var isEn = (window.i18n && typeof window.i18n.getLang === "function")
        ? (window.i18n.getLang() === "en")
        : (localStorage.getItem("argos_lang") === "en" || localStorage.getItem("jarvisLang") === "en");

      var emptyLabel = (window.i18n && typeof window.i18n.t === "function")
        ? (window.i18n.t("record_edit.parent_none") || (isEn ? "(No Parent / Set as Root Task)" : "(상위 작업 없음 / 최상위 작업으로 설정)"))
        : (isEn ? "(No Parent / Set as Root Task)" : "(상위 작업 없음 / 최상위 작업으로 설정)");

      var placeholderText = (window.i18n && typeof window.i18n.t === "function")
        ? (window.i18n.t("record_edit.parent_ph") || (isEn ? "Search parent task (code or title)..." : "상위 작업 검색 (코드 또는 제목 입력)"))
        : (isEn ? "Search parent task (code or title)..." : "상위 작업 검색 (코드 또는 제목 입력)");

      var allPool = (typeof records !== "undefined" && Array.isArray(records)) ? records : [];
      var cleanCurKey = String(currentKey || "").trim().toUpperCase();
      var cleanCurId = String(currentId || "").trim();
      var cleanSelParent = String(selectedParentKey || "").trim().toUpperCase();

      // Collect all descendants of current record so we don't allow setting a descendant as parent (cycle prevention)
      var descendantKeys = new Set();
      if(cleanCurKey) descendantKeys.add(cleanCurKey);
      if(cleanCurId) {
        descendantKeys.add(cleanCurId);
        descendantKeys.add("REC-" + cleanCurId);
        descendantKeys.add("#" + cleanCurId);
      }

      var addedAny = true;
      for(var pass = 0; pass < 5 && addedAny; pass++){
        addedAny = false;
        for(var i = 0; i < allPool.length; i++){
          var item = allPool[i];
          var itemParent = String(item.parentKey || (item.jira && item.jira.parentKey) || "").trim().toUpperCase();
          if(itemParent && descendantKeys.has(itemParent)){
            var itemKey = (item.cardCode || (item.jira && item.jira.key) || String(item.id || "")).toUpperCase();
            if(itemKey && !descendantKeys.has(itemKey)){
              descendantKeys.add(itemKey);
              if(item.id) descendantKeys.add(String(item.id));
              addedAny = true;
            }
          }
        }
      }

      var optionsForSelect = [
        {
          value: "",
          text: emptyLabel,
          search: isEn ? "none root no parent" : "없음 최상위 루트 none"
        }
      ];

      var matchedValue = "";

      allPool.forEach(function(rec){
        var recKey = (rec.cardCode || (rec.jira && rec.jira.key) || ("#" + rec.id)).toUpperCase();
        var recCleanKey = recKey.replace(/^#/, "");
        var recId = String(rec.id || "");

        // Exclude self and descendants
        if(descendantKeys.has(recKey) || descendantKeys.has(recCleanKey) || descendantKeys.has(recId)){
          return;
        }

        var title = (rec.title || (rec.jira && rec.jira.summary) || "").trim();
        var shortTitle = title.length > 36 ? (title.slice(0, 35).trim() + "...") : title;
        var assigneePart = rec.assignee ? (" · " + rec.assignee) : "";

        var text = "[" + recKey + "] " + shortTitle + assigneePart;
        var searchStr = (recKey + " " + title + " " + (rec.assignee || "")).toLowerCase();

        optionsForSelect.push({
          value: recKey,
          text: text,
          search: searchStr
        });

        if(cleanSelParent && (recKey === cleanSelParent || recCleanKey === cleanSelParent || recId === cleanSelParent)){
          matchedValue = recKey;
        }
      });

      // Destroy old TomSelect instance if present
      if(window.recordEditParentTomSelect){
        try { window.recordEditParentTomSelect.destroy(); } catch(e){}
        window.recordEditParentTomSelect = null;
      }

      var tomSuccess = false;
      if(window.TomSelect && select){
        try {
          select.innerHTML = "";
          window.recordEditParentTomSelect = new TomSelect(select, {
            allowEmptyOption: true,
            create: false,
            sortField: null,
            searchField: ["text", "value", "search"],
            options: optionsForSelect,
            maxOptions: 100,
            placeholder: placeholderText,
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
          if(matchedValue){
            window.recordEditParentTomSelect.setValue(matchedValue, false);
          } else {
            window.recordEditParentTomSelect.setValue("", false);
          }
          tomSuccess = true;
        } catch(err){
          console.warn("[TomSelect] recordEditParentSelect init error, fallback to native:", err);
        }
      }

      if(!tomSuccess && select){
        select.innerHTML = optionsForSelect.map(function(o){
          var sel = (o.value === matchedValue) ? " selected" : "";
          return '<option value="' + escapeHtml(o.value) + '"' + sel + '>' + escapeHtml(o.text) + '</option>';
        }).join("");
      }
    }

    form.addEventListener("submit", function(e){
      e.preventDefault();
      var key = (document.getElementById("recordEditKey") || {}).value;
      var title = (document.getElementById("recordEditTitleInput") || {}).value.trim();
      var assigneeSelect = document.getElementById("recordEditAssigneeSelect");
      var assignee = assigneeSelect ? assigneeSelect.value.trim() : "";
      var assigneeEmail = "";
      if(assigneeSelect && assigneeSelect.selectedIndex >= 0){
        var opt = assigneeSelect.options[assigneeSelect.selectedIndex];
        assigneeEmail = opt.getAttribute("data-email") || "";
      }
      var participants = (document.getElementById("recordEditParticipantsInput") || {}).value.trim();
      var startDate = (document.getElementById("recordEditStartDateInput") || {}).value;
      var dueDate = (document.getElementById("recordEditDueDateInput") || {}).value;
      var memo = (document.getElementById("recordEditMemoInput") || {}).value.trim();
      var parentKey = "";
      if(window.recordEditParentTomSelect){
        parentKey = String(window.recordEditParentTomSelect.getValue() || "").trim();
      } else {
        var parentSelect = document.getElementById("recordEditParentSelect");
        parentKey = parentSelect ? parentSelect.value.trim() : "";
      }

      if(!title){
        if(errEl){
          errEl.hidden = false;
          errEl.textContent = "제목을 입력해주세요.";
        }
        return;
      }

      if(startDate && dueDate && dueDate < startDate){
        if(errEl){
          errEl.hidden = false;
          var isEnLang = (window.i18n && typeof window.i18n.getLang === "function") 
            ? (window.i18n.getLang() === "en") 
            : (localStorage.getItem("argos_lang") === "en" || localStorage.getItem("jarvisLang") === "en");
          errEl.textContent = isEnLang ? "Due date cannot be earlier than start date." : "마감일은 시작일보다 빠를 수 없습니다.";
        }
        return;
      }

      if(submitBtn){
        submitBtn.disabled = true;
        submitBtn.textContent = "저장 중...";
      }

      var editPrioEl = document.getElementById("recordEditPrioritySelect");
      var priorityVal = editPrioEl ? (editPrioEl.value || "보통") : "보통";

      var payload = {
        key: key,
        expected_version: window.__editingRecordVersion || 1,
        title: title,
        priority: priorityVal,
        assignee: assignee,
        assigneeEmail: assigneeEmail,
        participants: participants,
        startDate: startDate,
        dueDate: dueDate,
        memo: memo,
        parentKey: parentKey
      };

      apiPost("/api/records/update", payload).then(function(res){
        if(submitBtn){
          submitBtn.disabled = false;
          submitBtn.textContent = "저장하기";
        }
        if(!res || !res.ok){
          if(errEl){
            errEl.hidden = false;
            if(res && res.conflict){
              var isEn = (window.i18n && typeof window.i18n.getLang === "function") 
                ? (window.i18n.getLang() === "en") 
                : (localStorage.getItem("argos_lang") === "en" || localStorage.getItem("jarvisLang") === "en");
              var conflictHtml = isEn
                ? '<div style="background:#fef2f2; border:1px solid #f87171; color:#991b1b; padding:10px 12px; border-radius:6px; font-size:12.5px; line-height:1.45;">' +
                  '<strong>⚠️ Conflict Detected (Optimistic Lock)</strong><br>' +
                  'This card was just updated by another user.<br>' +
                  'To prevent accidental overwriting, please reload the latest data.' +
                  '<div style="margin-top:8px;"><button type="button" class="btn-secondary" style="padding:4px 10px; font-size:11.5px; font-weight:700; cursor:pointer;" onclick="window.showIssueInCanvas(\'' + key + '\'); document.getElementById(\'recordEditModalBackdrop\').hidden=true;">🔄 Reload Latest Data</button></div>' +
                  '</div>'
                : '<div style="background:#fef2f2; border:1px solid #f87171; color:#991b1b; padding:10px 12px; border-radius:6px; font-size:12.5px; line-height:1.45;">' +
                  '<strong>⚠️ 충돌 감지 (Optimistic Lock)</strong><br>' +
                  '이 카드가 방금 다른 사용자에 의해 업데이트되었습니다.<br>' +
                  '작업 내용을 덮어쓰지 않도록 최신 데이터를 다시 불러와주세요.' +
                  '<div style="margin-top:8px;"><button type="button" class="btn-secondary" style="padding:4px 10px; font-size:11.5px; font-weight:700; cursor:pointer;" onclick="window.showIssueInCanvas(\'' + key + '\'); document.getElementById(\'recordEditModalBackdrop\').hidden=true;">🔄 최신 데이터 불러오기</button></div>' +
                  '</div>';
              errEl.innerHTML = conflictHtml;
            } else {
              errEl.textContent = (res && res.error) || "수정 중 오류가 발생했습니다.";
            }
          }
          return;
        }

        closeModal();
        if(typeof showToast === "function"){
          showToast("업무 정보가 성공적으로 수정되었습니다.");
        }

        // 1. Refresh Canvas Panel with new data
        if(typeof window.showIssueInCanvas === "function"){
          window.showIssueInCanvas(key);
        }

        // 2. Refresh Dashboard (Kanban, List)
        if(typeof window.loadDashboard === "function"){
          window.loadDashboard();
        }

        // 3. Refresh Schedule
        if(typeof window.loadScheduleEvents === "function"){
          window.loadScheduleEvents();
        }

        // 4. Refresh Home
        if(typeof window.renderHomeRecordsTable === "function"){
          window.renderHomeRecordsTable();
        }

        // 5. Refresh Notifications
        if(typeof window.reloadNotifications === "function"){
          window.reloadNotifications();
        }
      }).catch(function(err){
        if(submitBtn){
          submitBtn.disabled = false;
          submitBtn.textContent = "저장하기";
        }
        if(errEl){
          errEl.hidden = false;
          errEl.textContent = "서버 통신 실패: " + err.message;
        }
      });
    });
  }

})();
