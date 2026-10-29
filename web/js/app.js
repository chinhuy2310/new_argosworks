function isCurrentUserAdmin(){
  var u = getCurrentUser();
  if(!u) return false;
  return Boolean(u.isAdmin || u.role === "admin" || u.is_admin);
}
window.isCurrentUserAdmin = isCurrentUserAdmin;

function isCurrentUserManagerOrAdmin(){
  var u = getCurrentUser();
  if(!u) return false;
  return Boolean(u.isAdmin || u.role === "admin" || u.is_admin || u.role === "manager" || u.isManager);
}
window.isCurrentUserManagerOrAdmin = isCurrentUserManagerOrAdmin;

function getCurrentUser(){
  if(typeof window.loggedInUser !== "undefined" && window.loggedInUser) return window.loggedInUser;
  if(typeof loggedInUser !== "undefined" && loggedInUser) return loggedInUser;
  try {
    var saved = sessionStorage.getItem("argosUser") || localStorage.getItem("argosUser") || sessionStorage.getItem("jarvisUser") || localStorage.getItem("jarvisUser") || sessionStorage.getItem("batonUser") || localStorage.getItem("batonUser");
    if(saved) return JSON.parse(saved);
  } catch(e){}
  return null;
}
window.getCurrentUser = getCurrentUser;

var currentActiveTab = "home";
var tabScrollPositions = {};

function showTab(which, updateHash){
  if(which === "settings" && !isCurrentUserManagerOrAdmin()){
    showToast("부서장(Manager) 이상의 권한이 있는 사용자만 접근할 수 있습니다.");
    showTab("home");
    return;
  }
  if(which === "history" && !isCurrentUserManagerOrAdmin()){
    showToast("부서장(Manager) 이상의 권한이 있는 사용자만 접근할 수 있습니다.");
    showTab("home");
    return;
  }

  if(which === "form" && typeof isViewerUser === "function" && isViewerUser()){
    showToast("조회 전용(Viewer) 계정은 업무를 등록할 수 없습니다.");
    showTab("home");
    return;
  }

  if(which === "chat" && !getCurrentUser()){
    showToast("로그인 후 이용할 수 있는 기능입니다. 먼저 로그인해 주세요.");
    setTimeout(function(){
      window.location.href = "/login";
    }, 800);
    showTab("home");
    return;
  }

  // Save current tab scroll position before switching away
  if(currentActiveTab && currentActiveTab !== which){
    var curScroll = window.pageYOffset || document.documentElement.scrollTop || document.body.scrollTop || 0;
    tabScrollPositions[currentActiveTab] = curScroll;
  }
  var prevTab = currentActiveTab;
  currentActiveTab = which;
  document.body.classList.toggle("view-home-active", which === "home");
  document.body.classList.remove("sidebar-mobile-open");

  if(el.home) el.home.hidden = which !== "home";
  if(el.dash) el.dash.hidden = which !== "dash";
  if(el.form) el.form.hidden = which !== "form";
  if(el.schedule) el.schedule.hidden = which !== "schedule";
  document.body.classList.toggle("view-schedule-active", which === "schedule");
  if(el.pim) el.pim.hidden = which !== "pim";
  if(el.chat) el.chat.hidden = which !== "chat";
  document.body.classList.toggle("view-chat-active", which === "chat");
  if(el.history) el.history.hidden = which !== "history";
  if(el.settings) el.settings.hidden = which !== "settings";

  // Main LNB sidebar: DO NOT collapse automatically on Schedule tab.
  // Only collapse when the Schedule filter card is open / being opened.
  if(which === "schedule"){
    var schedSide = document.getElementById("schedMembersSidebar");
    var isSchedSideOpen = schedSide && !schedSide.classList.contains("is-collapsed");
    if(isSchedSideOpen){
      if(!document.body.classList.contains("sidebar-collapsed")){
        document.body.setAttribute("data-auto-collapsed-sched", "1");
        document.body.classList.add("sidebar-collapsed");
      }
    }
  } else if(document.body.getAttribute("data-auto-collapsed-sched") === "1"){
    document.body.removeAttribute("data-auto-collapsed-sched");
    document.body.classList.remove("sidebar-collapsed");
  }

  // Close canvas whenever switching tabs
  if(typeof window.closeCanvas === "function"){
    window.closeCanvas();
  }

  var pageWrap = document.querySelector(".page");
  if(pageWrap) pageWrap.hidden = (which === "home");

  // Restore scroll position for the target tab (or default to 0 if entering new tab)
  var targetScroll = tabScrollPositions[which] || 0;
  try {
    window.scrollTo({ top: targetScroll, behavior: "instant" });
  } catch(e) {
    try { window.scrollTo(0, targetScroll); } catch(e2){}
  }

  if(el.tabHome) { el.tabHome.classList.toggle("active", which === "home"); el.tabHome.setAttribute("aria-selected", String(which === "home")); }
  if(el.tabDash) { el.tabDash.classList.toggle("active", which === "dash"); el.tabDash.setAttribute("aria-selected", String(which === "dash")); }
  if(el.tabForm) { el.tabForm.classList.toggle("active", which === "form"); el.tabForm.setAttribute("aria-selected", String(which === "form")); }
  if(el.tabSchedule) { el.tabSchedule.classList.toggle("active", which === "schedule"); el.tabSchedule.setAttribute("aria-selected", String(which === "schedule")); }
  if(el.tabPim) { el.tabPim.classList.toggle("active", which === "pim"); el.tabPim.setAttribute("aria-selected", String(which === "pim")); }
  if(el.tabChat) { el.tabChat.classList.toggle("active", which === "chat"); el.tabChat.setAttribute("aria-selected", String(which === "chat")); }
  if(el.tabHistory) { el.tabHistory.classList.toggle("active", which === "history"); el.tabHistory.setAttribute("aria-selected", String(which === "history")); }
  if(el.tabSettings) { el.tabSettings.classList.toggle("active", which === "settings"); el.tabSettings.setAttribute("aria-selected", String(which === "settings")); }

  var titleEl = document.getElementById("topbarPageTitle");
  if(titleEl){
    var t = (window.i18n && window.i18n.t) ? window.i18n.t : function(k){ return k; };
    titleEl.textContent = t("title." + which) || which;
  }

  if(updateHash !== false){
    var h = (which === "schedule") ? "sched" : which;
    try { history.replaceState(null, "", "#" + h); } catch(e){}
  }

  try {
    var activeBtn = document.querySelector(".tab-btn.active");
    if(activeBtn && activeBtn.scrollIntoView && window.innerWidth <= 640){
      activeBtn.scrollIntoView({ behavior: "smooth", inline: "center", block: "nearest" });
    }
  } catch(e){}

  if(which === "home") {
    if(typeof resumeHomeBgAnimation === "function") resumeHomeBgAnimation();
    if(typeof triggerHomeBrandAnimation === "function") triggerHomeBrandAnimation();
    if(typeof renderHomePortalSection === "function") renderHomePortalSection();
    if(typeof renderHomeQuickActions === "function") renderHomeQuickActions();
  } else {
    if(typeof pauseHomeBgAnimation === "function") pauseHomeBgAnimation();
    if(typeof stopHomeBrandAnimation === "function") stopHomeBrandAnimation();
  }
  if(typeof updateJiraIntegrationUI === "function") updateJiraIntegrationUI();
  if(which === "form") {
    var isUserLoggedIn = Boolean(window.loggedInUser || (typeof loggedInUser !== "undefined" && loggedInUser) || sessionStorage.getItem("argosUser") || localStorage.getItem("argosUser"));
    var guestGate = document.getElementById("viewFormGuestPlaceholder");
    var submitForm = document.getElementById("submitForm");
    if(!isUserLoggedIn){
      if(guestGate) { guestGate.hidden = false; guestGate.style.display = "flex"; }
      if(submitForm) { submitForm.hidden = true; submitForm.style.display = "none"; }
    } else {
      if(guestGate) { guestGate.hidden = true; guestGate.style.display = "none"; }
      if(submitForm) { submitForm.hidden = false; submitForm.style.display = ""; }
      var curOrg = (document.getElementById("orgSelect") && document.getElementById("orgSelect").value) || (typeof loggedInUser !== "undefined" && loggedInUser && loggedInUser.org) || "";
      if(typeof window.populateParentKeySelect === "function") window.populateParentKeySelect(curOrg);
      if(typeof window.populateParticipantsSelect === "function") window.populateParticipantsSelect(curOrg);
    }
  }
  if(which === "schedule" && typeof loadSchedule === "function") loadSchedule();
  if(which === "pim") {
    if(typeof initPimTab === "function") { initPimTab(); }
    else if(typeof loadProducts === "function") { loadProducts(); }
  }
  if(which === "chat" && typeof initChat === "function") initChat();
  if(which === "history") {
    if(typeof initHistoryEventListeners === "function") initHistoryEventListeners();
    if(typeof loadHistoryActivities === "function") loadHistoryActivities();
  }
  if(which === "settings" && typeof loadSettings === "function") loadSettings();
}

if(el.tabHome) el.tabHome.addEventListener("click", function(){ showTab("home"); });
if(el.brand) el.brand.addEventListener("click", function(e){
  e.preventDefault();
  showTab("home");
});
if(el.tabDash) el.tabDash.addEventListener("click", function(){ showTab("dash"); });
if(el.tabForm) el.tabForm.addEventListener("click", function(){ showTab("form"); });
if(el.tabSchedule) el.tabSchedule.addEventListener("click", function(){ showTab("schedule"); });
if(el.tabPim) el.tabPim.addEventListener("click", function(){ showTab("pim"); });
if(el.tabChat) el.tabChat.addEventListener("click", function(){ showTab("chat"); });
if(el.tabHistory) el.tabHistory.addEventListener("click", function(){ showTab("history"); });
if(el.tabSettings) el.tabSettings.addEventListener("click", function(){ showTab("settings"); });

function tabFromHash(){
  var h = (location.hash || "").replace(/^#/, "").toLowerCase();
  if(h === "sched" || h === "schedule") return "schedule";
  if(h === "dash" || h === "dashboard") return "dash";
  if(h === "form" || h === "new"){
    if(typeof isViewerUser === "function" && isViewerUser()){
      if(typeof showToast === "function") showToast("조회 전용(Viewer) 계정은 업무를 등록할 수 없습니다.");
      try { history.replaceState(null, "", "#home"); } catch(e){}
      return "home";
    }
    return "form";
  }
  if(h === "pim" || h === "product") return "pim";
  if(h === "chat" || h === "ai") return getCurrentUser() ? "chat" : "home";
  if(h === "history" || h === "activity" || h === "activities"){
    if(!isCurrentUserManagerOrAdmin()){
      if(typeof showToast === "function") showToast("부서장(Manager) 이상의 권한이 있는 사용자만 접근할 수 있습니다.");
      try { history.replaceState(null, "", "#home"); } catch(e){}
      return "home";
    }
    return "history";
  }
  if(h === "settings" || h === "api"){
    if(!isCurrentUserManagerOrAdmin()){
      if(typeof showToast === "function") showToast("부서장(Manager) 이상의 권한이 있는 사용자만 접근할 수 있습니다.");
      try { history.replaceState(null, "", "#home"); } catch(e){}
      return "home";
    }
    return "settings";
  }
  return "home";
}

window.addEventListener("hashchange", function(){
  showTab(tabFromHash(), false);
});

// ---- 초기 로딩 ----
// 동기적으로 저장된 로그인 사용자 정보를 최우선 복원하여 탭 전환 시 미로그인 플래시 및 데이터 누락 방지
try {
  var earlySavedUser = sessionStorage.getItem("argosUser") || localStorage.getItem("argosUser") || sessionStorage.getItem("jarvisUser") || localStorage.getItem("jarvisUser") || sessionStorage.getItem("batonUser") || localStorage.getItem("batonUser");
  if(earlySavedUser && typeof applyLogin === "function"){
    applyLogin(JSON.parse(earlySavedUser));
  }
} catch(e){}
try {
  if (typeof isViewerUser === "function" && isViewerUser()) {
    if (el.tabForm) el.tabForm.hidden = true;
    var addSchedBtnSync = document.getElementById("btnSchedOpenCreateModal");
    if (addSchedBtnSync) addSchedBtnSync.style.display = "none";
  }
} catch(e){}
var initialTab = tabFromHash();
showTab(initialTab, false);
var antiFlash = document.getElementById("anti-flash-style");
if(antiFlash) antiFlash.remove();

if(typeof loadPimCategories === "function") loadPimCategories();
if(typeof loadDepartments === "function"){
  loadDepartments().then(function(){
    try{
      var saved = sessionStorage.getItem("argosUser") || localStorage.getItem("argosUser") || sessionStorage.getItem("jarvisUser") || localStorage.getItem("jarvisUser") || sessionStorage.getItem("batonUser") || localStorage.getItem("batonUser");
      if(saved && typeof applyLogin === "function"){ 
        applyLogin(JSON.parse(saved)); 
        var justIn = sessionStorage.getItem("justLoggedIn");
        if(justIn){
          sessionStorage.removeItem("justLoggedIn");
          if(typeof showToast === "function") showToast(justIn + "님으로 로그인되었습니다.");
        }
      }
    }catch(e){}
    if(typeof updateSubmitAvailability === "function") updateSubmitAvailability();
    if(initialTab === "schedule" && typeof loadSchedule === "function") loadSchedule();
    if(initialTab === "history" && typeof loadHistoryActivities === "function") {
      if(typeof initHistoryEventListeners === "function") initHistoryEventListeners();
      loadHistoryActivities();
    }
    if(initialTab === "settings" && typeof loadSettings === "function") loadSettings();
    if(typeof loadRecords === "function") return loadRecords();
  });
}

/**
 * Floating Scroll-to-Top Button
 * Appears smoothly when page is scrolled down past 260px, smoothly scrolls back to top on click.
 */
function initScrollToTop(){
  var btn = document.getElementById("btn-floating-scroll-top");
  if(!btn) return;

  function updateButtonVisibility(){
    var scrollY = window.pageYOffset || document.documentElement.scrollTop || document.body.scrollTop || 0;
    if(scrollY > 260){
      btn.classList.add("visible");
    } else {
      btn.classList.remove("visible");
    }
  }

  window.addEventListener("scroll", updateButtonVisibility, { passive: true });
  window.addEventListener("resize", updateButtonVisibility);

  btn.addEventListener("click", function(e){
    e.preventDefault();
    window.scrollTo({ top: 0, behavior: "smooth" });
  });

  updateButtonVisibility();
}

initScrollToTop();

// ── DaouOffice Sidebar & Theme Controls ────────────────────
function initDaouSidebarAndTheme(){
  var sidebarToggle = document.getElementById("sidebarToggleBtn");
  if(sidebarToggle){
    sidebarToggle.addEventListener("click", function(){
      // Close schedule members filter if open to avoid overlapping
      var schedSide = document.getElementById("schedMembersSidebar");
      if(schedSide && !schedSide.classList.contains("is-collapsed")){
        schedSide.classList.add("is-collapsed");
      }

      if(window.innerWidth <= 768){
        document.body.classList.toggle("sidebar-mobile-open");
      } else {
        document.body.classList.toggle("sidebar-collapsed");
        document.body.removeAttribute("data-auto-collapsed-sched");
      }
      setTimeout(function(){
        if(typeof window.resizeHomeInteractiveBg === "function") window.resizeHomeInteractiveBg();
      }, 230);
    });
  }

  // Close mobile sidebar on clicking outside or selecting a tab
  document.addEventListener("click", function(e){
    if(window.innerWidth <= 768 && document.body.classList.contains("sidebar-mobile-open")){
      var sidebar = document.getElementById("daouSidebar");
      var toggleBtn = document.getElementById("sidebarToggleBtn");
      if(sidebar && !sidebar.contains(e.target) && (!toggleBtn || !toggleBtn.contains(e.target))){
        document.body.classList.remove("sidebar-mobile-open");
      }
    }
  });


  var themeToggle = document.getElementById("themeToggleBtn");
  if(themeToggle){
    function updateThemeIcon(){
      var isDark = document.documentElement.getAttribute("data-theme") === "dark" ||
        (!document.documentElement.getAttribute("data-theme") && window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches);
      var icon = themeToggle.querySelector(".theme-icon");
      if(icon) icon.textContent = isDark ? "☀️" : "🌙";
      var themeText = document.getElementById("themeText");
      if(themeText) {
        var t = (window.i18n && window.i18n.t) ? window.i18n.t : function(k){ return k; };
        themeText.textContent = isDark ? t("nav.theme_light") : t("nav.theme_dark");
      }
    }

    var savedTheme = localStorage.getItem("jarvisTheme");
    if(savedTheme){
      document.documentElement.setAttribute("data-theme", savedTheme);
    }
    updateThemeIcon();

    themeToggle.addEventListener("click", function(){
      var current = document.documentElement.getAttribute("data-theme");
      var isDark = current === "dark" || (!current && window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches);
      var nextTheme = isDark ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", nextTheme);
      localStorage.setItem("jarvisTheme", nextTheme);
      updateThemeIcon();
      var pri = document.getElementById("prioritySelect");
      if(pri && typeof window.updatePrioritySelectColor === "function"){
        window.updatePrioritySelectColor(pri);
      }
    });
  }

  // Language Toggle Switcher (KO / EN)
  var langBtn = document.getElementById("langToggleBtn");
  if(langBtn){
    function updateLangBtnUI(){
      if(!window.i18n) return;
      var cur = window.i18n.getLang();
      var flagEl = document.getElementById("langFlag");
      var codeEl = document.getElementById("langCode");
      if(flagEl) flagEl.textContent = "🌐";
      if(codeEl) codeEl.textContent = (cur === "en") ? "EN" : "KO";
    }

    updateLangBtnUI();

    langBtn.addEventListener("click", function(){
      if(!window.i18n) return;
      var cur = window.i18n.getLang();
      var next = (cur === "ko") ? "en" : "ko";
      window.i18n.setLang(next);
      updateLangBtnUI();
      if(typeof renderDeptCards === "function") renderDeptCards();
      // Re-update page title
      var titleEl = document.getElementById("topbarPageTitle");
      var curTab = (location.hash || "").replace(/^#/, "").toLowerCase() || "home";
      if(curTab === "sched") curTab = "schedule";
      if(titleEl && window.i18n.t) {
        titleEl.textContent = window.i18n.t("title." + curTab) || "Home";
      }
    });

    window.addEventListener("langchange", function(){
      updateLangBtnUI();
      if(typeof updateThemeIcon === "function") updateThemeIcon();
      if(typeof updateTopbarUserUI === "function") updateTopbarUserUI(getCurrentUser());
      if(typeof renderDeptCards === "function") renderDeptCards();
      var titleEl = document.getElementById("topbarPageTitle");
      var curTab = (location.hash || "").replace(/^#/, "").toLowerCase() || "home";
      if(curTab === "sched") curTab = "schedule";
      if(titleEl && window.i18n.t) {
        titleEl.textContent = window.i18n.t("title." + curTab) || "Home";
      }
    });
  }
}
initDaouSidebarAndTheme();

// ── Google / Jira / Choivis Style Topbar Account Menu ──────
function initTopbarAccountMenu(){
  var avatarBtn = document.getElementById("topbarAvatarBtn");
  var menu = document.getElementById("topbarAccountMenu");
  var loginBtn = document.getElementById("topbarMenuLoginBtn");
  var logoutBtn = document.getElementById("topbarLogoutBtn");

  if(!avatarBtn || !menu) return;

  function openMenu(){
    var notifMenu = document.getElementById("topbarNotifMenu");
    var notifBtn = document.getElementById("topbarNotifBtn");
    if(notifMenu && !notifMenu.hidden){
      notifMenu.hidden = true;
      if(notifBtn) notifBtn.setAttribute("aria-expanded", "false");
    }
    menu.hidden = false;
    avatarBtn.setAttribute("aria-expanded", "true");
  }

  function closeMenu(){
    menu.hidden = true;
    avatarBtn.setAttribute("aria-expanded", "false");
  }

  function toggleMenu(e){
    if(e) e.stopPropagation();
    if(menu.hidden){
      openMenu();
    } else {
      closeMenu();
    }
  }

  avatarBtn.addEventListener("click", toggleMenu);

  // Close when clicking outside
  document.addEventListener("click", function(e){
    if(!menu.hidden && !menu.contains(e.target) && !avatarBtn.contains(e.target)){
      closeMenu();
    }
  });

  // Close on Escape key
  document.addEventListener("keydown", function(e){
    if(e.key === "Escape" && !menu.hidden){
      closeMenu();
      avatarBtn.focus();
    }
  });

  if(loginBtn){
    loginBtn.addEventListener("click", function(){
      window.location.href = "/login";
    });
  }

  if(logoutBtn){
    logoutBtn.addEventListener("click", function(){
      closeMenu();
      if(typeof showToast === "function") showToast("로그아웃되었습니다. 로그인 페이지로 이동합니다...");
      var p = (typeof applyLogout === "function") ? applyLogout() : null;
      if(p && typeof p.then === "function"){
        p.finally(function(){
          setTimeout(function(){ window.location.href = "/login?logout=1"; }, 100);
        });
      } else {
        setTimeout(function(){ window.location.href = "/login?logout=1"; }, 200);
      }
    });
  }
}
initTopbarAccountMenu();

