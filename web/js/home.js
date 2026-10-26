// home.js
var homeAskForm = document.getElementById("homeAskForm");
var homeAskInput = document.getElementById("homeAskInput");
var homeAskBtn = document.getElementById("homeAskBtn");
var homeAskResult = document.getElementById("homeAskResult");
var homeAskAnswer = document.getElementById("homeAskAnswer");
var homeAskSources = document.getElementById("homeAskSources");
var homeAskEmpty = document.getElementById("homeAskEmpty");
var homeAskThinking = document.getElementById("homeAskThinking");
var thinkingStatusText = document.getElementById("thinkingStatusText");
var thinkingIcon = document.getElementById("thinkingIcon");

var homeTileDash = document.getElementById("homeTileDash");
var homeTileForm = document.getElementById("homeTileForm");
var homeTileSchedule = document.getElementById("homeTileSchedule");
var homeTilePim = document.getElementById("homeTilePim");

var thinkingSteps = [
  { icon: "🔍", text: "질문 의도 분석 및 사내 데이터(업무·제품·일정) 검색 중..." },
  { icon: "⚡", text: "AI 벡터 시맨틱 유사도 대조 중..." },
  { icon: "📑", text: "관련 업무 카드 및 제품/일정 기록 선별 중..." },
  { icon: "🧠", text: "관련 문맥을 종합하여 신뢰할 수 있는 답변 작성 중..." }
];
var thinkingTimer = null;
var thinkingStepIdx = 0;

var typewriterTimer = null;
var isTyping = false;

function stopThinkingAnimation(){
  if(thinkingTimer){
    clearInterval(thinkingTimer);
    thinkingTimer = null;
  }
  if(!homeAskThinking) homeAskThinking = document.getElementById("homeAskThinking");
  if(homeAskThinking) homeAskThinking.hidden = true;
}

function updateHomeHasResult(hasResult){
  var viewHome = document.getElementById("viewHome");
  if(viewHome){
    viewHome.classList.toggle("has-result", !!hasResult);
  }
  if(hasResult){
    stopHomeBrandAnimation();
  } else {
    // If search is emptied/cleared, trigger animation after 2s
    triggerHomeBrandAnimation();
  }
}

// ---------- Bottom Branding Pill Animation Controller ----------
// Behavior:
// 1. Initially hidden for 2s.
// 2. At 2s: Light burst explosion & expands horizontally from center revealing the pill banner.
// 3. Remains visible in static pristine state for 7s (enough time to read comfortably).
// 4. After 7s: Collapses with CRT TV turn-off animation (collapses to thin slit, then center dot, and vanishes).
// 5. Does not loop automatically. Only re-triggers if returning to Home tab while search is empty.
var homeBrandTimer1 = null; // 2s delay -> burst expand
var homeBrandTimer2 = null; // 2s + 0.75s -> static visible
var homeBrandTimer3 = null; // 2s + 15s -> TV off
var homeBrandTimer4 = null; // after TV off -> clean up

function stopHomeBrandAnimation(){
  if(homeBrandTimer1){ clearTimeout(homeBrandTimer1); homeBrandTimer1 = null; }
  if(homeBrandTimer2){ clearTimeout(homeBrandTimer2); homeBrandTimer2 = null; }
  if(homeBrandTimer3){ clearTimeout(homeBrandTimer3); homeBrandTimer3 = null; }
  if(homeBrandTimer4){ clearTimeout(homeBrandTimer4); homeBrandTimer4 = null; }
  var footer = document.getElementById("homeBrandFooter");
  if(footer){
    footer.classList.remove("anim-burst-expand", "is-visible", "anim-tv-off");
  }
}

function triggerHomeBrandAnimation(){
  stopHomeBrandAnimation();

  var footer = document.getElementById("homeBrandFooter");
  var viewHome = document.getElementById("viewHome");
  if(!footer || !viewHome) return;

  // Only trigger if Home tab is currently active and search is empty with no results
  if(viewHome.hidden) return;
  var inputVal = (homeAskInput && homeAskInput.value) ? homeAskInput.value.trim() : "";
  if(inputVal || viewHome.classList.contains("has-result")) return;

  // Step 1: Wait 2s in hidden state
  homeBrandTimer1 = setTimeout(function(){
    var currentInput = (homeAskInput && homeAskInput.value) ? homeAskInput.value.trim() : "";
    if(viewHome.hidden || currentInput || viewHome.classList.contains("has-result")) return;

    // Trigger light burst + expand animation (~0.75s)
    footer.classList.remove("anim-tv-off", "is-visible");
    footer.classList.add("anim-burst-expand");

    // Settle into static visible pill banner (Stage 2: stays pristine as-is)
    homeBrandTimer2 = setTimeout(function(){
      footer.classList.remove("anim-burst-expand");
      footer.classList.add("is-visible");
    }, 750);

    // After 7s in visible stage (at 7,000ms): trigger Turn Off TV animation (~0.55s)
    homeBrandTimer3 = setTimeout(function(){
      var nowInput = (homeAskInput && homeAskInput.value) ? homeAskInput.value.trim() : "";
      if(viewHome.hidden || nowInput || viewHome.classList.contains("has-result")) {
        footer.classList.remove("anim-burst-expand", "is-visible", "anim-tv-off");
        return;
      }
      footer.classList.remove("anim-burst-expand", "is-visible");
      footer.classList.add("anim-tv-off");

      // Once TV turn-off finishes, remove classes (footer returns to base hidden state)
      homeBrandTimer4 = setTimeout(function(){
        footer.classList.remove("anim-tv-off");
      }, 600);
    }, 7000);

  }, 2000);
}

// Export for app.js tab switcher
window.triggerHomeBrandAnimation = triggerHomeBrandAnimation;
window.stopHomeBrandAnimation = stopHomeBrandAnimation;

function startThinkingAnimation(){
  stopThinkingAnimation();
  stopTypewriter();
  updateHomeHasResult(true);
  if(!homeAskThinking) homeAskThinking = document.getElementById("homeAskThinking");
  if(!thinkingStatusText) thinkingStatusText = document.getElementById("thinkingStatusText");
  if(!thinkingIcon) thinkingIcon = document.getElementById("thinkingIcon");

  if(homeAskThinking) homeAskThinking.hidden = false;
  if(homeAskResult) homeAskResult.hidden = false;
  if(homeAskEmpty) homeAskEmpty.hidden = true;
  if(homeAskAnswer) homeAskAnswer.innerHTML = "";
  if(homeAskSources) homeAskSources.innerHTML = "";

  thinkingStepIdx = 0;
  function updateStep(){
    var step = thinkingSteps[thinkingStepIdx % thinkingSteps.length];
    if(thinkingStatusText) thinkingStatusText.textContent = step.text;
    if(thinkingIcon) thinkingIcon.textContent = step.icon;
    thinkingStepIdx++;
  }
  updateStep();
  thinkingTimer = setInterval(updateStep, 1500);
}

function stopTypewriter(){
  if(typewriterTimer){
    clearInterval(typewriterTimer);
    typewriterTimer = null;
  }
  isTyping = false;
}

function streamTypewriterAnswer(rawText, onComplete){
  stopTypewriter();
  if(!rawText){
    homeAskAnswer.innerHTML = "";
    if(onComplete) onComplete();
    return;
  }

  isTyping = true;
  var cursorHtml = '<span class="typing-cursor">▋</span>';
  var len = rawText.length;
  // Natural typing speed: 1.2s to 2.2s total duration
  var targetTimeMs = Math.min(2200, Math.max(1000, len * 8));
  var tickMs = 18;
  var totalTicks = Math.max(1, Math.floor(targetTimeMs / tickMs));
  var charsPerTick = Math.max(1, Math.ceil(len / totalTicks));

  var currentIdx = 0;

  function finishImmediately(){
    stopTypewriter();
    homeAskAnswer.innerHTML = '<div class="home-answer-text">' + formatMarkdownAnswer(rawText) + '</div>';
    if(onComplete) onComplete();
  }

  homeAskAnswer.onclick = function(e){
    if(e && e.target && e.target.closest("a, button, .home-jira-canvas-link")){
      return;
    }
    if(isTyping){
      finishImmediately();
    }
  };

  typewriterTimer = setInterval(function(){
    currentIdx += charsPerTick;
    if(currentIdx >= len){
      finishImmediately();
      return;
    }
    var slice = rawText.substring(0, currentIdx);
    homeAskAnswer.innerHTML = '<div class="home-answer-text" title="클릭 시 전체 즉시 표시">' + 
      formatMarkdownAnswer(slice) + cursorHtml + 
      '<span class="home-skip-hint">(클릭 시 즉시 표시)</span></div>';
  }, tickMs);
}

function formatMarkdownAnswer(text){
  if(!text) return "";
  var s = escapeHtml(text);
  // Markdown links: strip URL and keep plain text (links should be accessed via bottom source cards)
  s = s.replace(/\[([^\]]+)\]\((https?:\/\/[^\s\)\"\']+)\)/g, '$1');
  // Bold: **text** -> <strong>text</strong>
  s = s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  // Citation badges: [1], [2] -> highlighted pill
  s = s.replace(/\[(\d+)\]/g, '<span class="citation-badge">[$1]</span>');
  // Auto-link Jira issue keys and local card codes (e.g. VS-50, DEV-1, SEC-2, TS-1, PR-12, #12, etc.) to open canvas modal
  var NON_ISSUE_KEYS = { "RS-485": 1, "RS-232": 1, "RS-422": 1, "RJ-45": 1, "RJ-11": 1, "CAT-5": 1, "CAT-6": 1 };
  s = s.replace(/\b([A-Za-z]{2,10}-\d+)\b/g, function(match, key){
    if(NON_ISSUE_KEYS[key.toUpperCase()]) return match;
    return '<a href="javascript:void(0)" class="home-jira-canvas-link" onclick="if(window.showIssueInCanvas){window.showIssueInCanvas(\'' + key.toUpperCase() + '\');}return false;" title="' + key.toUpperCase() + ' 상세 정보 보기 (모달)">' + key.toUpperCase() + '</a>';
  });
  s = s.replace(/#(\d+)\b/g, function(match, num){
    return '<a href="javascript:void(0)" class="home-jira-canvas-link" onclick="if(window.showIssueInCanvas){window.showIssueInCanvas(\'#' + num + '\');}return false;" title="#' + num + ' 상세 정보 보기 (모달)">#' + num + '</a>';
  });


  var lines = s.split("\n");
  var out = [];
  var inList = false;

  for(var i = 0; i < lines.length; i++){
    var line = lines[i].trim();
    if(!line){
      if(inList){ out.push("</ul>"); inList = false; }
      continue;
    }
    var bulletMatch = line.match(/^[\*\-]\s+(.*)$/);
    var numMatch = line.match(/^(\d+)\.\s+(.*)$/);
    if(bulletMatch){
      if(!inList){ out.push('<ul class="home-answer-list">'); inList = true; }
      out.push("<li>" + bulletMatch[1] + "</li>");
    } else if(numMatch){
      if(inList){ out.push("</ul>"); inList = false; }
      out.push('<div class="home-answer-num"><strong>' + numMatch[1] + '.</strong> ' + numMatch[2] + '</div>');
    } else {
      if(inList){ out.push("</ul>"); inList = false; }
      out.push('<p class="home-answer-p">' + line + '</p>');
    }
  }
  if(inList) out.push("</ul>");
  return out.join("");
}

function renderAskResult(data){
  stopThinkingAnimation();
  var sources = data.sources || [];
  if(!data.answer && !sources.length){
    homeAskResult.hidden = true;
    homeAskEmpty.hidden = false;
    updateHomeHasResult(false);
    return;
  }
  homeAskEmpty.hidden = true;
  homeAskResult.hidden = false;
  updateHomeHasResult(true);

  var INITIAL_SOURCES_LIMIT = 5;
  var currentSourcesLimit = INITIAL_SOURCES_LIMIT;

  function renderSourcesHtml(){
    if(!sources.length){
      homeAskSources.innerHTML = "";
      return;
    }

    var methodBadge = data.searchMethod === "voyage_vector" 
      ? ' <span class="home-search-method-badge">AI 검색</span>' 
      : '';
    var visibleSources = sources.slice(0, currentSourcesLimit);
    var html = '<div class="home-sources-header">' +
      '<p class="home-sources-title">관련 자료 ' + sources.length + '건' + methodBadge + '</p>' +
      (sources.length > INITIAL_SOURCES_LIMIT ? '<span class="home-sources-count-badge">' + visibleSources.length + ' / ' + sources.length + ' 표시</span>' : '') +
      '</div>';

    visibleSources.forEach(function(s, i){
      var metaParts = [orgLabel(s.org), s.category || "", s.date || ""].filter(Boolean).map(escapeHtml);
      if(typeof s.similarity === "number"){
        metaParts.unshift('<span class="home-similarity-tag">유사도 ' + Math.round(s.similarity * 100) + '%</span>');
      }

      var isProduct = Boolean(s.isProduct || (s.id && (String(s.id).startsWith("product-") || String(s.id).startsWith("pim-"))));
      var prodId = s.productId || (isProduct ? String(s.id).replace(/^(product-|pim-)/, "") : "");

      var cardCode = s.cardCode || (s.jira && s.jira.key) || (s.id && !isProduct ? '#' + s.id : '');
      if(cardCode && !isProduct){
        var cCodeEsc = escapeHtml(cardCode);
        metaParts.push('<a href="javascript:void(0)" class="home-jira-canvas-link" data-issue-key="' + cCodeEsc + '" onclick="if(window.showIssueInCanvas){window.showIssueInCanvas(\'' + cCodeEsc + '\');}return false;" title="' + cCodeEsc + ' 상세 정보 보기 (모달)">' + cCodeEsc + '</a>');
      } else if(isProduct && prodId){
        metaParts.push('<span class="home-product-pill">공식 제품 사양</span>');
      }

      var titleHtml = "";
      if(isProduct && prodId){
        titleHtml = '<div class="home-source-title">' +
          '<a href="javascript:void(0)" class="home-product-card-link" onclick="if(window.openProductDetailModal){window.openProductDetailModal(\'' + escapeHtml(prodId) + '\');}return false;" title="제품 사양 및 카달로그 보기">' +
          '📦 ' + escapeHtml(s.title || "(제품)") + ' <span class="home-product-badge-btn">🔍 상세정보</span></a>' +
          '</div>';
      } else if(cardCode){
        titleHtml = '<div class="home-source-title">' +
          '<a href="javascript:void(0)" class="home-source-card-link" onclick="if(window.showIssueInCanvas){window.showIssueInCanvas(\'' + escapeHtml(cardCode) + '\');}return false;" title="카드 상세 보기">' +
          escapeHtml(s.title || "(제목 없음)") + '</a>' +
          '</div>';
      } else {
        titleHtml = '<div class="home-source-title">' + escapeHtml(s.title || "(제목 없음)") + '</div>';
      }

      html += '<div class="home-source-item' + (isProduct ? ' home-source-item-product' : '') + '">' +
        '<span class="home-source-idx">' + (i + 1) + '</span>' +
        '<div class="home-source-body">' +
          titleHtml +
          '<div class="home-source-meta">' + metaParts.join(" · ") + '</div>' +
        '</div>' +
      '</div>';
    });

    if(sources.length > visibleSources.length){
      var remaining = sources.length - visibleSources.length;
      html += '<div class="home-sources-more-wrap">' +
        '<button type="button" class="home-sources-more-btn" id="homeSourcesMoreBtn">' +
          '<span>더보기 (+' + remaining + '건)</span>' +
          '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"></polyline></svg>' +
        '</button>' +
      '</div>';
    } else if(sources.length > INITIAL_SOURCES_LIMIT && visibleSources.length === sources.length){
      html += '<div class="home-sources-more-wrap">' +
        '<button type="button" class="home-sources-more-btn fold" id="homeSourcesFoldBtn">' +
          '<span>접기 (기본 5건)</span>' +
          '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="18 15 12 9 6 15"></polyline></svg>' +
        '</button>' +
      '</div>';
    }

    homeAskSources.innerHTML = html;

    var moreBtn = document.getElementById("homeSourcesMoreBtn");
    if(moreBtn){
      moreBtn.addEventListener("click", function(){
        currentSourcesLimit = Math.min(sources.length, currentSourcesLimit + 5);
        renderSourcesHtml();
      });
    }
    var foldBtn = document.getElementById("homeSourcesFoldBtn");
    if(foldBtn){
      foldBtn.addEventListener("click", function(){
        currentSourcesLimit = INITIAL_SOURCES_LIMIT;
        renderSourcesHtml();
      });
    }
  }

  // Render sources immediately so user can glance at them while AI is typing
  renderSourcesHtml();
  homeAskSources.style.opacity = "0";
  homeAskSources.style.transition = "opacity 0.35s ease-in";
  setTimeout(function(){ homeAskSources.style.opacity = "1"; }, 30);

  if(data.answer){
    streamTypewriterAnswer(data.answer);
  } else if(!data.aiEnabled){
    homeAskAnswer.innerHTML = '<div class="home-answer-hint">AI 답변 기능은 아직 꺼져 있습니다 ' +
      '(API 설정 탭에서 AI 설정을 켜면 활성화됩니다). 아래는 관련 자료 검색 결과입니다.</div>';
  } else {
    homeAskAnswer.innerHTML = '<div class="home-answer-hint">⚡ AI 응답 지연/제한으로 인해 관련 자료 검색 결과를 즉시 표시합니다. 아래 목록을 확인해주세요.</div>';
  }
}

if(homeAskForm){
  homeAskForm.addEventListener("submit", function(e){
    e.preventDefault();
    var q = homeAskInput.value.trim();
    if(!q) return;
    homeAskBtn.disabled = true;
    startThinkingAnimation();
    fetch("/api/ask?q=" + encodeURIComponent(q), { headers: authHeaders(), cache: "no-store" })
      .then(function(r){ return r.json().then(function(data){ return { status: r.status, data: data }; }); })
      .then(function(res){
        homeAskBtn.disabled = false;
        if(!res.data.ok){
          stopThinkingAnimation();
          showToast(res.data.error || "검색에 실패했습니다.");
          return;
        }
        renderAskResult(res.data);
      })
      .catch(function(){
        homeAskBtn.disabled = false;
        stopThinkingAnimation();
        showToast("서버에 연결할 수 없습니다.");
      });
  });
}

// Clear button logic
var homeAskClearBtn = document.getElementById("homeAskClearBtn");
if(homeAskInput && homeAskClearBtn){
  homeAskInput.addEventListener("input", function(){
    homeAskClearBtn.hidden = !homeAskInput.value.trim();
    if(!homeAskInput.value.trim()){
      if(homeAskResult) homeAskResult.hidden = true;
      if(homeAskEmpty) homeAskEmpty.hidden = true;
      stopThinkingAnimation();
      updateHomeHasResult(false);
    }
  });
  homeAskClearBtn.addEventListener("click", function(){
    homeAskInput.value = "";
    homeAskClearBtn.hidden = true;
    if(homeAskResult) homeAskResult.hidden = true;
    if(homeAskEmpty) homeAskEmpty.hidden = true;
    stopThinkingAnimation();
    updateHomeHasResult(false);
    homeAskInput.focus();
  });
}


// Global delegated click handler for all Jira issue links on Home tab
if(homeAskResult){
  homeAskResult.addEventListener("click", function(e){
    var target = e.target ? e.target.closest(".home-jira-canvas-link") : null;
    if(!target) return;
    e.preventDefault();
    e.stopPropagation();
    var key = target.getAttribute("data-issue-key") || target.textContent.trim();
    if(key && typeof window.showIssueInCanvas === "function"){
      window.showIssueInCanvas(key);
    }
  });
}

// --------------------------------------------------------------------------
// Google-style Quick Action Navigation Buttons with Auth Requirement Check
// --------------------------------------------------------------------------
// --------------------------------------------------------------------------
// Executive Portal & Role-based Quick Actions (Option 2)
// --------------------------------------------------------------------------

function getPortalUserRole(){
  var user = (typeof getCurrentUser === "function") ? getCurrentUser() : (window.loggedInUser || null);
  if(!user) return { user: null, role: "guest" };
  if(user.isAdmin || user.role === "admin" || user.is_admin) return { user: user, role: "admin" };
  if(user.isManager || user.role === "manager") return { user: user, role: "manager" };
  if(user.role === "viewer") return { user: user, role: "viewer" };
  return { user: user, role: "member" };
}

function renderHomeQuickActions(){
  var container = document.getElementById("homeQuickActions");
  if(!container) return;

  var info = getPortalUserRole();
  var role = info.role;

  // Define action buttons configuration per role
  var allActions = [
    { target: "dash", icon: "📋", label: "업무 보드 (Board)", roles: ["guest", "viewer", "member", "manager", "admin"] },
    { target: "form", icon: "✍️", label: "업무 등록 (New)", roles: ["member", "manager", "admin"] },
    { target: "schedule", icon: "📅", label: "일정 관리 (Calendar)", roles: ["viewer", "member", "manager", "admin"] },
    { target: "chat", icon: "💬", label: "AI 어시스턴트 (Chat)", roles: ["viewer", "member", "manager", "admin"] },
    { target: "history", icon: "📊", label: "주간 보고 / 이력", roles: ["manager", "admin"] },
    { target: "settings", icon: "⚙️", label: "시스템 설정", roles: ["manager", "admin"] },
    { target: "pim", icon: "🔍", label: "PIM 부품 카탈로그", roles: ["guest", "viewer", "member", "manager", "admin"] },
    { target: "login", icon: "🔐", label: "로그인 (Login)", roles: ["guest"] }
  ];

  var filtered = allActions.filter(function(item){
    return item.roles.indexOf(role) !== -1;
  });

  var html = filtered.map(function(act){
    return '<button type="button" class="home-quick-btn" data-target="' + act.target + '">' +
      '<span class="home-quick-icon">' + act.icon + '</span>' +
      '<span class="home-quick-label">' + act.label + '</span>' +
    '</button>';
  }).join("");

  container.innerHTML = html;

  // Attach event handlers
  var btns = container.querySelectorAll(".home-quick-btn");
  btns.forEach(function(btn){
    btn.addEventListener("click", function(e){
      e.preventDefault();
      var target = btn.getAttribute("data-target");
      if(!target) return;

      if(target === "login"){
        window.location.href = "/login";
        return;
      }

      if(target === "chat"){
        var user = (typeof getCurrentUser === "function") ? getCurrentUser() : window.loggedInUser;
        if(!user){
          if(typeof showToast === "function"){
            showToast("챗봇은 로그인 후 이용할 수 있는 기능입니다. 먼저 로그인해 주세요.");
          }
          setTimeout(function(){
            window.location.href = "/login";
          }, 800);
          return;
        }
      }

      if(typeof showTab === "function"){
        showTab(target);
      }
    });
  });
}

function getPortalStatusBadge(status){
  var s = (status || "todo").toLowerCase();
  var label = "대기";
  var cls = "status-todo";
  if(s === "inprogress" || s === "inprog" || s === "doing"){
    label = "진행중";
    cls = "status-inprog";
  } else if(s === "review" || s === "pending"){
    label = "검토중";
    cls = "status-review";
  } else if(s === "delayed"){
    label = "지연";
    cls = "status-delayed";
  } else if(s === "done" || s === "completed"){
    label = "완료";
    cls = "status-done";
  }
  return '<span class="portal-status-pill ' + cls + '">' + label + '</span>';
}

function renderPortalTaskItem(r){
  var taskId = r.id || (r.jira && r.jira.key) || r.cardCode || "";
  var title = r.title || r.summary || "(제목 없음)";
  var dept = r.org || "";
  var date = r.date || r.dueDate || "";
  var metaParts = [];
  if(dept) metaParts.push(dept);
  if(r.assignee) metaParts.push(r.assignee);
  if(date) metaParts.push(date);

  var escapeFn = (typeof escapeHtml === "function") ? escapeHtml : function(s){ return String(s || ""); };

  return '<div class="portal-task-item" data-task-id="' + escapeFn(String(taskId)) + '">' +
    getPortalStatusBadge(r.status) +
    '<span class="portal-task-title" title="' + escapeFn(title) + '">' + escapeFn(title) + '</span>' +
    '<span class="portal-task-meta">' + escapeFn(metaParts.join(" · ")) + '</span>' +
  '</div>';
}

function renderHomePortalSection(){
  var section = document.getElementById("homePortalSection");
  var greetingEl = document.getElementById("homePortalGreeting") || document.getElementById("homePortalTitle");
  var roleBadgeEl = document.getElementById("homePortalRoleBadge");
  var gridEl = document.getElementById("homePortalGrid");
  if(!section || !gridEl) return;

  var info = getPortalUserRole();
  var user = info.user;
  var role = info.role;

  var escapeFn = (typeof escapeHtml === "function") ? escapeHtml : function(s){ return String(s || ""); };

  // 1. Header greeting & role badge
  var roleConfig = {
    guest: { text: "게스트 (Guest)", cls: "badge-guest", greeting: "ARGOS WORKS 엔터프라이즈 포털에 오신 것을 환영합니다!" },
    viewer: { text: "조회 전용 (Viewer)", cls: "badge-viewer", greeting: "안녕하세요, " + (user ? (user.name || user.id) : "") + " 님!" },
    member: { text: "팀원 (Member)", cls: "badge-member", greeting: "안녕하세요, " + (user ? (user.name || user.id) : "") + " 님!" },
    manager: { text: "부서 관리자 (Manager)", cls: "badge-manager", greeting: "안녕하세요, " + (user ? (user.name || user.id) : "") + " 관리자님!" },
    admin: { text: "시스템 최고관리자 (Admin)", cls: "badge-admin", greeting: "시스템 최고관리자 포털 — " + (user ? (user.name || user.id) : "") + " 님" }
  };

  var cfg = roleConfig[role] || roleConfig.guest;
  if(greetingEl) greetingEl.textContent = cfg.greeting;
  if(roleBadgeEl){
    roleBadgeEl.textContent = cfg.text;
    roleBadgeEl.className = "home-portal-badge " + cfg.cls;
  }

  // 2. Data pool
  var allRecords = (typeof records !== "undefined" && Array.isArray(records)) ? records : ((window.records && Array.isArray(window.records)) ? window.records : []);
  var userName = user ? (user.name || user.id || "") : "";
  var userOrg = user ? (user.org || "") : "";

  // 3. Render grid cards based on role
  var cardsHtml = "";

  if(role === "guest"){
    cardsHtml += '<div class="portal-widget-card">' +
      '<div class="portal-card-header">' +
        '<h3 class="portal-card-title">👋 시작하기 (Login)</h3>' +
      '</div>' +
      '<div class="portal-card-body" style="display:flex; flex-direction:column; justify-content:space-between; flex:1;">' +
        '<p style="font-size:12px; color:var(--ink-soft); line-height:1.45; margin:0 0 8px 0;">부서별 업무 현황 확인, 내 할 일 관리, AI 어시스턴트 대화를 이용하세요.</p>' +
        '<button type="button" class="portal-guest-btn" id="portalGuestLoginBtn" onclick="window.location.href=\'/login\'" style="width:100%; justify-content:center; padding:6px 12px; font-size:12.5px; cursor:pointer;">🔐 지금 로그인하기</button>' +
      '</div>' +
    '</div>';

    cardsHtml += '<div class="portal-widget-card">' +
      '<div class="portal-card-header">' +
        '<h3 class="portal-card-title">🔍 부품 & 기술 카탈로그 (PIM)</h3>' +
      '</div>' +
      '<div class="portal-card-body" style="display:flex; flex-direction:column; justify-content:space-between; flex:1;">' +
        '<p style="font-size:12px; color:var(--ink-soft); line-height:1.45; margin:0 0 8px 0;">로그인 없이도 부품 규격서, 데이터시트, 카탈로그 PDF를 검색할 수 있습니다.</p>' +
        '<button type="button" class="portal-guest-btn btn-secondary" style="width:100%; justify-content:center; padding:6px 12px; font-size:12.5px;" onclick="showTab(\'pim\')">카탈로그 바로가기 →</button>' +
      '</div>' +
    '</div>';

    cardsHtml += '<div class="portal-widget-card">' +
      '<div class="portal-card-header">' +
        '<h3 class="portal-card-title">📋 업무 보드 미리보기</h3>' +
      '</div>' +
      '<div class="portal-card-body" style="display:flex; flex-direction:column; justify-content:space-between; flex:1;">' +
        '<p style="font-size:12px; color:var(--ink-soft); line-height:1.45; margin:0 0 8px 0;">조직의 공개 업무 진행 상황과 프로젝트 일정을 한눈에 파악하세요.</p>' +
        '<button type="button" class="portal-guest-btn btn-secondary" style="width:100%; justify-content:center; padding:6px 12px; font-size:12.5px;" onclick="showTab(\'dash\')">업무 보드 열기 →</button>' +
      '</div>' +
    '</div>';

  } else if(role === "member" || role === "viewer"){
    // Member: My Tasks & Department Tasks
    var myTasks = allRecords.filter(function(r){
      var isMine = (r.assignee === userName || (user && r.assignee === user.id) || (r.all_assignees && r.all_assignees.indexOf(userName) !== -1));
      var isNotDone = r.status !== "done" && r.status !== "completed";
      return isMine && isNotDone;
    });

    var deptTasks = allRecords.filter(function(r){
      return userOrg ? (r.org === userOrg) : true;
    }).slice(0, 5);

    // Card 1: My Tasks
    cardsHtml += '<div class="portal-widget-card">' +
      '<div class="portal-card-header">' +
        '<h3 class="portal-card-title">📌 내 진행 중인 업무</h3>' +
        '<span class="portal-counter">' + myTasks.length + '건</span>' +
      '</div>' +
      '<div class="portal-card-body">' +
        (myTasks.length === 0
          ? '<div class="portal-empty-state"><div class="portal-empty-icon">🎉</div><div>진행 중인 배정 업무가 없습니다.</div></div>'
          : '<div class="portal-task-list">' + myTasks.slice(0, 5).map(renderPortalTaskItem).join("") + '</div>'
        ) +
      '</div>' +
      '<div class="portal-widget-footer">' +
        '<a href="javascript:void(0)" onclick="showTab(\'dash\')">업무 보드에서 전체 확인하기 →</a>' +
      '</div>' +
    '</div>';

    // Card 2: Dept Tasks
    var deptLabel = userOrg ? (typeof orgLabel === "function" ? orgLabel(userOrg) : userOrg) : "전체";
    cardsHtml += '<div class="portal-widget-card">' +
      '<div class="portal-card-header">' +
        '<h3 class="portal-card-title">🏢 ' + escapeFn(deptLabel) + ' 팀 업무 현황</h3>' +
        '<span class="portal-counter">' + deptTasks.length + '건</span>' +
      '</div>' +
      '<div class="portal-card-body">' +
        (deptTasks.length === 0
          ? '<div class="portal-empty-state"><div class="portal-empty-icon">📂</div><div>등록된 팀 업무가 없습니다.</div></div>'
          : '<div class="portal-task-list">' + deptTasks.map(renderPortalTaskItem).join("") + '</div>'
        ) +
      '</div>' +
      '<div class="portal-widget-footer">' +
        '<a href="javascript:void(0)" onclick="showTab(\'dash\')">팀 전체 업무 보기 →</a>' +
      '</div>' +
    '</div>';

  } else if(role === "manager"){
    // Manager: Pending Approvals & Dept Overview Stats
    var reviewTasks = allRecords.filter(function(r){
      var isReview = (r.status === "review" || r.status === "pending" || r.status_review);
      var matchOrg = userOrg ? (r.org === userOrg) : true;
      return isReview && matchOrg;
    });

    var deptRecords = userOrg ? allRecords.filter(function(r){ return r.org === userOrg; }) : allRecords;
    var inprogCount = deptRecords.filter(function(r){ return r.status === "inprogress" || r.status === "inprog" || r.status === "doing"; }).length;
    var delayedCount = deptRecords.filter(function(r){ return r.status === "delayed"; }).length;
    var doneCount = deptRecords.filter(function(r){ return r.status === "done" || r.status === "completed"; }).length;

    // Card 1: Pending Approvals
    cardsHtml += '<div class="portal-widget-card">' +
      '<div class="portal-card-header">' +
        '<h3 class="portal-card-title">⏳ 결재 / 검토 대기 업무</h3>' +
        '<span class="portal-counter ' + (reviewTasks.length > 0 ? 'warning' : '') + '">' + reviewTasks.length + '건</span>' +
      '</div>' +
      '<div class="portal-card-body">' +
        (reviewTasks.length === 0
          ? '<div class="portal-empty-state"><div class="portal-empty-icon">✅</div><div>모든 검토가 완료되었습니다. 대기 중인 업무가 없습니다.</div></div>'
          : '<div class="portal-task-list">' + reviewTasks.slice(0, 5).map(renderPortalTaskItem).join("") + '</div>'
        ) +
      '</div>' +
      '<div class="portal-widget-footer">' +
        '<a href="javascript:void(0)" onclick="showTab(\'dash\')">보드에서 결재 진행하기 →</a>' +
      '</div>' +
    '</div>';

    // Card 2: Department Health & Overview Stats
    var deptLabel = userOrg ? (typeof orgLabel === "function" ? orgLabel(userOrg) : userOrg) : "부서";
    cardsHtml += '<div class="portal-widget-card">' +
      '<div class="portal-card-header">' +
        '<h3 class="portal-card-title">📊 ' + escapeFn(deptLabel) + ' 업무 지표</h3>' +
        '<span class="portal-counter">' + deptRecords.length + '건</span>' +
      '</div>' +
      '<div class="portal-card-body">' +
        '<div class="portal-stat-grid">' +
          '<div class="portal-stat-item"><span class="portal-stat-num" style="color:#2563eb;">' + inprogCount + '</span><span class="portal-stat-lbl">진행 중</span></div>' +
          '<div class="portal-stat-item"><span class="portal-stat-num" style="color:#d97706;">' + reviewTasks.length + '</span><span class="portal-stat-lbl">검토 대기</span></div>' +
          '<div class="portal-stat-item"><span class="portal-stat-num" style="color:#dc2626;">' + delayedCount + '</span><span class="portal-stat-lbl">지연/병목</span></div>' +
          '<div class="portal-stat-item"><span class="portal-stat-num" style="color:#059669;">' + doneCount + '</span><span class="portal-stat-lbl">완료</span></div>' +
        '</div>' +
      '</div>' +
      '<div class="portal-widget-footer">' +
        '<a href="javascript:void(0)" onclick="showTab(\'history\')">주간 업무 보고서 작성 및 확인 →</a>' +
      '</div>' +
    '</div>';

  } else if(role === "admin"){
    // Admin: System-wide Reviews & System Overview
    var globalReviews = allRecords.filter(function(r){
      return (r.status === "review" || r.status === "pending" || r.status_review);
    });

    var urgentTasks = allRecords.filter(function(r){
      return (r.priority === "urgent" || r.priority === "high" || r.status === "delayed") && (r.status !== "done" && r.status !== "completed");
    });

    var inprogAll = allRecords.filter(function(r){ return r.status === "inprogress" || r.status === "inprog" || r.status === "doing"; }).length;
    var doneAll = allRecords.filter(function(r){ return r.status === "done" || r.status === "completed"; }).length;

    // Card 1: Global Reviews
    cardsHtml += '<div class="portal-widget-card">' +
      '<div class="portal-card-header">' +
        '<h3 class="portal-card-title">⏳ 전사 검토 / 승인 대기</h3>' +
        '<span class="portal-counter ' + (globalReviews.length > 0 ? 'warning' : '') + '">' + globalReviews.length + '건</span>' +
      '</div>' +
      '<div class="portal-card-body">' +
        (globalReviews.length === 0
          ? '<div class="portal-empty-state"><div class="portal-empty-icon">✅</div><div>전사 검토 대기 건이 없습니다.</div></div>'
          : '<div class="portal-task-list">' + globalReviews.slice(0, 5).map(renderPortalTaskItem).join("") + '</div>'
        ) +
      '</div>' +
      '<div class="portal-widget-footer">' +
        '<a href="javascript:void(0)" onclick="showTab(\'dash\')">전체 보드 바로가기 →</a>' +
      '</div>' +
    '</div>';

    // Card 2: System Health & Overview
    cardsHtml += '<div class="portal-widget-card">' +
      '<div class="portal-card-header">' +
        '<h3 class="portal-card-title">⚙️ 시스템 현황 & 데이터 지표</h3>' +
        '<span class="portal-counter">정상 가동</span>' +
      '</div>' +
      '<div class="portal-card-body">' +
        '<div class="portal-stat-grid">' +
          '<div class="portal-stat-item"><span class="portal-stat-num">' + allRecords.length + '</span><span class="portal-stat-lbl">총 업무 건수</span></div>' +
          '<div class="portal-stat-item"><span class="portal-stat-num" style="color:#2563eb;">' + inprogAll + '</span><span class="portal-stat-lbl">진행 중</span></div>' +
          '<div class="portal-stat-item"><span class="portal-stat-num" style="color:#dc2626;">' + urgentTasks.length + '</span><span class="portal-stat-lbl">긴급/지연</span></div>' +
          '<div class="portal-stat-item"><span class="portal-stat-num" style="color:#059669;">' + doneAll + '</span><span class="portal-stat-lbl">완료 누적</span></div>' +
        '</div>' +
      '</div>' +
      '<div class="portal-widget-footer">' +
        '<a href="javascript:void(0)" onclick="showTab(\'settings\')">시스템 설정 및 사용자 관리 →</a>' +
      '</div>' +
    '</div>';
  }

  gridEl.innerHTML = cardsHtml;

  // Add click handlers to task items
  var taskItems = gridEl.querySelectorAll(".portal-task-item");
  taskItems.forEach(function(item){
    item.addEventListener("click", function(){
      var tid = item.getAttribute("data-task-id");
      if(tid && typeof window.showIssueInCanvas === "function"){
        window.showIssueInCanvas(tid);
      }
    });
  });

  // Guest login button
  var guestLoginBtn = document.getElementById("portalGuestLoginBtn");
  if(guestLoginBtn){
    guestLoginBtn.addEventListener("click", function(e){
      e.preventDefault();
      window.location.href = "/login";
    });
  }
}

// Make functions available globally
window.renderHomeQuickActions = renderHomeQuickActions;
window.renderHomePortalSection = renderHomePortalSection;

// Initialize Refresh button
(function initHomePortalRefresh(){
  var btn = document.getElementById("homePortalRefreshBtn");
  if(!btn) return;
  btn.addEventListener("click", function(e){
    e.preventDefault();
    btn.classList.add("spinning");
    if(typeof loadRecords === "function"){
      loadRecords().then(function(){
        renderHomePortalSection();
      }).finally(function(){
        setTimeout(function(){ btn.classList.remove("spinning"); }, 400);
      });
    } else {
      renderHomePortalSection();
      setTimeout(function(){ btn.classList.remove("spinning"); }, 400);
    }
  });
})();

// Auto-run on script load
try {
  renderHomeQuickActions();
  renderHomePortalSection();
} catch(e){}


// ==========================================================================
// REALTIME INTERACTIVE CANVAS BACKGROUND ANIMATION
// ==========================================================================
(function initHomeInteractiveBg(){
  var canvas = document.getElementById("homeInteractiveBg");
  var container = document.getElementById("viewHome");
  if(!canvas || !container) return;

  var ctx = canvas.getContext("2d");
  if(!ctx) return;

  var width = 0;
  var height = 0;
  var dpr = window.devicePixelRatio || 1;

  var mouse = {
    x: -9999,
    y: -9999,
    targetX: -9999,
    targetY: -9999,
    active: false,
    radius: 160
  };

  var particles = [];
  var PARTICLE_COUNT = 48;
  var animFrameId = null;

  function isDarkTheme(){
    return document.documentElement.getAttribute("data-theme") === "dark" ||
      (!document.documentElement.getAttribute("data-theme") && window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches);
  }

  function resize(){
    if(!container) return;
    var rect = container.getBoundingClientRect();
    width = rect.width;
    height = rect.height;
    if(width <= 0 || height <= 0) return;

    dpr = window.devicePixelRatio || 1;
    canvas.width = Math.floor(width * dpr);
    canvas.height = Math.floor(height * dpr);
    canvas.style.width = width + "px";
    canvas.style.height = height + "px";
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    if(particles.length === 0){
      initParticles();
    } else {
      particles.forEach(function(p){
        if(p.x > width) p.x = Math.random() * width;
        if(p.y > height) p.y = Math.random() * height;
      });
    }
  }

  function initParticles(){
    particles = [];
    var count = Math.min(PARTICLE_COUNT, Math.max(24, Math.floor(width * height / 12000)));
    for(var i = 0; i < count; i++){
      particles.push({
        x: Math.random() * width,
        y: Math.random() * height,
        vx: (Math.random() - 0.5) * 0.45,
        vy: (Math.random() - 0.5) * 0.45,
        radius: 1.6 + Math.random() * 1.6,
        alpha: 0.25 + Math.random() * 0.45,
        colorIndex: Math.random() > 0.4 ? 0 : 1 // 0: cyan/blue, 1: purple/indigo
      });
    }
  }

  function onMouseMove(e){
    if(container.hidden || container.style.display === "none") return;
    var rect = container.getBoundingClientRect();
    mouse.targetX = e.clientX - rect.left;
    mouse.targetY = e.clientY - rect.top;
    mouse.active = true;
  }

  function onMouseLeave(){
    mouse.active = false;
  }

  window.addEventListener("mousemove", onMouseMove, { passive: true });
  document.addEventListener("mouseleave", onMouseLeave);
  window.addEventListener("resize", function(){
    resize();
  });
  window.resizeHomeInteractiveBg = resize;

  function render(){
    // Check if viewHome is currently visible
    if(container.hidden || container.style.display === "none"){
      animFrameId = requestAnimationFrame(render);
      return;
    }

    ctx.clearRect(0, 0, width, height);

    // Smooth mouse interpolation
    if(mouse.active){
      if(mouse.x === -9999){
        mouse.x = mouse.targetX;
        mouse.y = mouse.targetY;
      } else {
        mouse.x += (mouse.targetX - mouse.x) * 0.1;
        mouse.y += (mouse.targetY - mouse.y) * 0.1;
      }
    }

    var dark = isDarkTheme();

    // 1. Draw glowing interactive cursor spotlight
    if(mouse.active && mouse.x >= 0 && mouse.x <= width && mouse.y >= 0 && mouse.y <= height){
      var spotGrad = ctx.createRadialGradient(mouse.x, mouse.y, 0, mouse.x, mouse.y, 280);
      if(dark){
        spotGrad.addColorStop(0, "rgba(56, 189, 248, 0.14)");
        spotGrad.addColorStop(0.45, "rgba(56, 189, 248, 0.05)");
        spotGrad.addColorStop(1, "rgba(0, 0, 0, 0)");
      } else {
        spotGrad.addColorStop(0, "rgba(2, 132, 199, 0.11)");
        spotGrad.addColorStop(0.45, "rgba(14, 165, 233, 0.03)");
        spotGrad.addColorStop(1, "rgba(255, 255, 255, 0)");
      }
      ctx.fillStyle = spotGrad;
      ctx.beginPath();
      ctx.arc(mouse.x, mouse.y, 280, 0, Math.PI * 2);
      ctx.fill();
    }

    // 2. Update and draw particles
    var particleColor1 = dark ? "56, 189, 248" : "2, 132, 199";   // cyan/sky primary
    var particleColor2 = dark ? "14, 165, 233" : "56, 189, 248";  // sky/cyan secondary

    for(var i = 0; i < particles.length; i++){
      var p = particles[i];

      // Move particle
      p.x += p.vx;
      p.y += p.vy;

      // Wrap around bounds with margin
      if(p.x < -10) p.x = width + 10;
      else if(p.x > width + 10) p.x = -10;
      if(p.y < -10) p.y = height + 10;
      else if(p.y > height + 10) p.y = -10;

      // Cursor magnetic repulsion interaction
      if(mouse.active){
        var dx = p.x - mouse.x;
        var dy = p.y - mouse.y;
        var dist = Math.sqrt(dx * dx + dy * dy);
        if(dist < mouse.radius && dist > 1){
          var force = (mouse.radius - dist) / mouse.radius;
          p.x += (dx / dist) * force * 1.8;
          p.y += (dy / dist) * force * 1.8;
        }
      }

      // Draw particle dot
      var baseRgb = p.colorIndex === 0 ? particleColor1 : particleColor2;
      ctx.fillStyle = "rgba(" + baseRgb + ", " + p.alpha + ")";
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2);
      ctx.fill();

      // Connect to mouse cursor if nearby
      if(mouse.active){
        var cdx = p.x - mouse.x;
        var cdy = p.y - mouse.y;
        var cdist = Math.sqrt(cdx * cdx + cdy * cdy);
        if(cdist < 140){
          var lineAlpha = (1 - cdist / 140) * 0.45;
          ctx.strokeStyle = "rgba(" + particleColor1 + ", " + lineAlpha + ")";
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.moveTo(p.x, p.y);
          ctx.lineTo(mouse.x, mouse.y);
          ctx.stroke();
        }
      }

      // Connect to nearby particles (constellation mesh)
      for(var j = i + 1; j < particles.length; j++){
        var p2 = particles[j];
        var pdx = p.x - p2.x;
        var pdy = p.y - p2.y;
        var pdist = Math.sqrt(pdx * pdx + pdy * pdy);
        if(pdist < 100){
          var meshAlpha = (1 - pdist / 100) * (dark ? 0.22 : 0.16);
          ctx.strokeStyle = "rgba(" + particleColor1 + ", " + meshAlpha + ")";
          ctx.lineWidth = 0.8;
          ctx.beginPath();
          ctx.moveTo(p.x, p.y);
          ctx.lineTo(p2.x, p2.y);
          ctx.stroke();
        }
      }
    }

    // If paused or container hidden, do not request another frame (0% CPU)
    if(isPaused || container.hidden || container.style.display === "none" || document.hidden){
      animFrameId = null;
      return;
    }

    animFrameId = requestAnimationFrame(render);
  }

  var isPaused = false;

  function startLoop(){
    if(!animFrameId && !isPaused && !container.hidden && container.style.display !== "none" && !document.hidden){
      animFrameId = requestAnimationFrame(render);
    }
  }

  function pauseLoop(){
    isPaused = true;
    if(animFrameId){
      cancelAnimationFrame(animFrameId);
      animFrameId = null;
    }
  }

  function resumeLoop(){
    isPaused = false;
    resize();
    startLoop();
  }

  // Automatically pause when browser tab is inactive/minimized, resume when visible
  document.addEventListener("visibilitychange", function(){
    if(document.hidden){
      pauseLoop();
    } else {
      var vHome = document.getElementById("viewHome");
      if(vHome && !vHome.hidden && vHome.style.display !== "none"){
        resumeLoop();
      }
    }
  });

  // Initial sizing & kickoff
  setTimeout(function(){
    resize();
    startLoop();
  }, 50);

  // Expose global controls for tab switching in app.js
  window.resumeHomeBgAnimation = function(){
    resize();
    resumeLoop();
  };
  window.pauseHomeBgAnimation = function(){
    pauseLoop();
  };
})();

// ==========================================
// Product Detail Modal Trigger (Home -> PIM Modal)
// ==========================================
window.openProductDetailModal = function(productId){
  var pimDetailModal = document.getElementById("pimDetailModal");
  if(!pimDetailModal) return;
  var pimModalModel = document.getElementById("pimModalModel");
  var pimModalCatBadge = document.getElementById("pimModalCatBadge");
  var pimModalProcBadge = document.getElementById("pimModalProcBadge");
  var pimModalPdfBtn = document.getElementById("pimModalPdfBtn");
  var pimModalWebLink = document.getElementById("pimModalWebLink");
  var pimModalBody = document.getElementById("pimModalBody");

  var closeBtn = document.getElementById("pimModalCloseBtn");
  var dismissBtn = document.getElementById("pimModalDismissBtn");
  if(closeBtn) closeBtn.onclick = function(){ pimDetailModal.hidden = true; };
  if(dismissBtn) dismissBtn.onclick = function(){ pimDetailModal.hidden = true; };
  pimDetailModal.onclick = function(e){
    if(e.target === pimDetailModal) pimDetailModal.hidden = true;
  };

  pimDetailModal.hidden = false;
  if(pimModalModel) pimModalModel.textContent = "제품 사양 불러오는 중...";
  if(pimModalCatBadge) pimModalCatBadge.textContent = "제품";
  if(pimModalProcBadge) pimModalProcBadge.hidden = true;
  if(pimModalPdfBtn) pimModalPdfBtn.hidden = true;
  if(pimModalBody){
    pimModalBody.innerHTML = '<div style="text-align: center; padding: 60px 20px; color: var(--ink-soft); font-size: 13.5px;">' +
      '상세 사양과 조달 정보를 가져오고 있습니다...</div>';
  }

  fetch("/api/products/detail?id=" + encodeURIComponent(productId), { cache: "no-store" })
    .then(function(r){ return r.json(); })
    .then(function(res){
      if(!res || !res.ok || !res.detail){
        if(pimModalBody){
          pimModalBody.innerHTML = '<div style="color:var(--danger); text-align:center; padding:50px;">' +
            '제품 상세 정보를 불러오지 못했습니다.<br>' +
            '<span style="font-size:12px; color:var(--ink-soft);">' + ((res && res.error) || "알 수 없는 오류") + '</span></div>';
        }
        return;
      }
      var d = res.detail;
      if(pimModalModel) pimModalModel.textContent = d.model || d.displayName || "제품 상세";
      if(pimModalCatBadge) pimModalCatBadge.textContent = d.category || "제품";

      if(pimModalProcBadge){
        if(d.procurementNo){
          pimModalProcBadge.textContent = "조달식별번호: " + d.procurementNo;
          pimModalProcBadge.hidden = false;
        } else {
          pimModalProcBadge.hidden = true;
        }
      }

      if(pimModalWebLink){
        if(d.sourceUrl){
          pimModalWebLink.href = d.sourceUrl;
          pimModalWebLink.hidden = false;
        } else {
          pimModalWebLink.hidden = true;
        }
      }

      if(pimModalPdfBtn){
        if(d.catalogPdf){
          pimModalPdfBtn.href = d.catalogPdf;
          pimModalPdfBtn.hidden = false;
        } else {
          pimModalPdfBtn.hidden = true;
        }
      }

      var fallbackImg = "data:image/svg+xml;charset=utf-8,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20width%3D%22200%22%20height%3D%22150%22%20viewBox%3D%220%200%20200%20150%22%3E%3Crect%20fill%3D%22%23f3f4f6%22%20width%3D%22200%22%20height%3D%22150%22%2F%3E%3Ctext%20fill%3D%22%239ca3af%22%20font-family%3D%22sans-serif%22%20font-size%3D%2213%22%20x%3D%2250%25%22%20y%3D%2250%25%22%20text-anchor%3D%22middle%22%20dy%3D%22.3em%22%3ENo%20Image%3C%2Ftext%3E%3C%2Fsvg%3E";
      var imgSrc = d.image ? escapeHtml(d.image) : fallbackImg;

      var bulletsHtml = "";
      if(d.displayName && d.displayName !== d.model){
        bulletsHtml += '<p style="font-size:13px; font-weight:600; color:var(--ink); margin-bottom:10px; line-height:1.4;">' + escapeHtml(d.displayName) + '</p>';
      }
      if(d.bullets && d.bullets.length){
        bulletsHtml += '<div class="pim-modal-bullets">' +
          d.bullets.map(function(b){
            return '<div class="pim-modal-bullet-item">' + escapeHtml(b) + '</div>';
          }).join("") +
          '</div>';
      } else if(d.summary){
        bulletsHtml += '<p style="font-size:13px; color:var(--ink-soft); line-height:1.5;">' + escapeHtml(d.summary) + '</p>';
      }

      var specsTableHtml = "";
      if(d.specs && Object.keys(d.specs).length > 0){
        var rows = Object.keys(d.specs).map(function(key){
          return '<tr><th>' + escapeHtml(key) + '</th><td>' + escapeHtml(d.specs[key]) + '</td></tr>';
        }).join("");
        specsTableHtml = '<div class="pim-modal-specs-table-wrap">' +
          '<h3 class="pim-modal-specs-title">📋 제품 세부 규격 사양 (총 ' + Object.keys(d.specs).length + '개 항목)</h3>' +
          '<table class="pim-specs-table"><tbody>' + rows + '</tbody></table>' +
          '</div>';
      } else {
        specsTableHtml = '<div class="pim-modal-specs-table-wrap">' +
          '<h3 class="pim-modal-specs-title">📋 제품 세부 규격 사양</h3>' +
          '<p style="font-size:12.5px; color:var(--ink-soft); padding:16px 0;">제공된 규격 사양표가 없습니다. 상단 카달로그 PDF를 다운로드하여 확인하세요.</p>' +
          '</div>';
      }

      if(pimModalBody){
        pimModalBody.innerHTML = '<div class="pim-modal-top-section">' +
          '<div class="pim-modal-img-wrap">' +
            '<img class="pim-modal-img" src="' + imgSrc + '" alt="' + escapeHtml(d.model || "") + '" onerror="this.src=\'' + fallbackImg + '\'">' +
          '</div>' +
          '<div>' + bulletsHtml + '</div>' +
        '</div>' +
        specsTableHtml;
      }
    })
    .catch(function(err){
      if(pimModalBody){
        pimModalBody.innerHTML = '<div style="color:var(--danger); text-align:center; padding:50px;">서버와의 통신 오류로 상세 정보를 가져올 수 없습니다.</div>';
      }
    });
};

// 주간 업무 보고서 다운로드 링크: HttpOnly 쿠키 인증을 기본으로 사용
document.addEventListener("click", function(e){
  var a = e.target && e.target.closest ? e.target.closest('a[href*="/api/reports/download"]') : null;
  if(!a) return;
  e.preventDefault();
  var href = a.getAttribute("href");
  window.location.href = href;
}, true);

// 초기 진입 시 홈 탭이 활성화되어 있고 검색창이 비어있으면 2초 후 애니메이션 시작
try {
  var vHome = document.getElementById("viewHome");
  if(vHome && !vHome.hidden){
    triggerHomeBrandAnimation();
  }
} catch(e){}
