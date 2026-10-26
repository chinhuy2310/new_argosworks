// auth.js
var loginBtn = document.getElementById("loginBtn");
var userChip = document.getElementById("userChip");
var userAvatar = document.getElementById("userAvatar");
var userChipName = document.getElementById("userChipName");
var userChipEmail = document.getElementById("userChipEmail");
var logoutBtn = document.getElementById("logoutBtn");
var idForm = document.getElementById("idForm");
var idNameInput = document.getElementById("idNameInput");
var idEmailInput = document.getElementById("idEmailInput");
var idOrgSelect = document.getElementById("idOrgSelect");
var idFormCancel = document.getElementById("idFormCancel");
var idPasswordStage = document.getElementById("idPasswordStage");
var idPasswordInput = document.getElementById("idPasswordInput");
var idPasswordConfirmWrap = document.getElementById("idPasswordConfirmWrap");
var idPasswordConfirmInput = document.getElementById("idPasswordConfirmInput");
var idPasswordLabel = document.getElementById("idPasswordLabel");
var idPasswordHint = document.getElementById("idPasswordHint");
var idFormError = document.getElementById("idFormError");
var idFormSubmitBtn = document.getElementById("idFormSubmitBtn");
var submitterField = document.getElementById("submitterField");
var orgSelect = document.getElementById("orgSelect");
var submitBtn = document.getElementById("submitBtn");
var processingStatus = document.getElementById("processingStatus");

function renderIdOrgOptions(){
  var html = "";
  DEPARTMENTS.forEach(function(d){ html += '<option value="' + d.id + '">' + escapeHtml(d.name) + '</option>'; });
  idOrgSelect.innerHTML = html;
}

function updateSubmitAvailability(){
  if(submitBtn) submitBtn.disabled = !loggedInUser || (processingStatus && processingStatus.classList.contains("show"));
}

function fillSubmitterFromLogin(){
  var isAdm = Boolean(loggedInUser && (loggedInUser.isAdmin || loggedInUser.is_admin || loggedInUser.role === 'admin'));
  var isMgr = Boolean(isAdm || (loggedInUser && (loggedInUser.role === 'manager' || loggedInUser.isManager)));
  if(orgSelect) {
    orgSelect.value = loggedInUser.org;
    orgSelect.disabled = !isMgr;
  }
  if(submitterField) submitterField.value = loggedInUser.name + " (" + orgLabel(loggedInUser.org) + ")" + (loggedInUser.email ? " · " + loggedInUser.email : "");
  if(typeof populateCatSelect === "function") populateCatSelect(loggedInUser.org);
  if(typeof populateParentKeySelect === "function") populateParentKeySelect(loggedInUser.org);
  if(typeof populateParticipantsSelect === "function") populateParticipantsSelect();
}

function updateTopbarUserUI(user){
  var avatarBtn = document.getElementById("topbarAvatarBtn");
  var avatarInner = document.getElementById("topbarAvatarInner");
  var menuLoggedIn = document.getElementById("topbarMenuProfileLoggedIn");
  var menuGuest = document.getElementById("topbarMenuProfileGuest");
  var menuFooter = document.getElementById("topbarMenuFooterLoggedIn");
  var menuAvatar = document.getElementById("topbarMenuAvatar");
  var menuName = document.getElementById("topbarMenuName");
  var menuEmail = document.getElementById("topbarMenuEmail");
  var menuOrg = document.getElementById("topbarMenuOrg");
  var menuAdmin = document.getElementById("topbarMenuAdminBadge");
  var menuEditProfileRow = document.getElementById("topbarMenuEditProfileRow");

  if(user){
    var initial = (user.name || "?").charAt(0).toUpperCase();
    var deptColor = "#0284c7";
    try {
      if(typeof deptById === "function" && typeof colorVar === "function") {
        var d = deptById(user.org);
        if(d) deptColor = colorVar(d.colorIndex);
      }
    } catch(e){}

    if(avatarInner){
      if(user.avatarUrl){
        avatarInner.innerHTML = '<img src="' + escapeHtml(user.avatarUrl) + '" alt="" style="width:100%;height:100%;border-radius:50%;object-fit:cover;display:block;">';
        avatarInner.style.background = "transparent";
      } else {
        avatarInner.textContent = initial;
        avatarInner.style.background = deptColor;
      }
    }
    if(avatarBtn){
      avatarBtn.setAttribute("title", (user.name || "") + (user.email ? " (" + user.email + ")" : ""));
    }

    if(menuLoggedIn) menuLoggedIn.hidden = false;
    if(menuGuest) menuGuest.hidden = true;
    if(menuFooter) menuFooter.hidden = false;
    if(menuEditProfileRow) menuEditProfileRow.hidden = false;

    if(menuAvatar){
      if(user.avatarUrl){
        menuAvatar.innerHTML = '<img src="' + escapeHtml(user.avatarUrl) + '" alt="" style="width:100%;height:100%;border-radius:50%;object-fit:cover;display:block;">';
        menuAvatar.style.background = "transparent";
      } else {
        menuAvatar.textContent = initial;
        menuAvatar.style.background = deptColor;
      }
    }
    if(menuName) menuName.textContent = user.name || "";
    if(menuEmail) menuEmail.textContent = user.email || user.username || "";
    if(menuOrg) menuOrg.textContent = (typeof orgLabel === "function") ? orgLabel(user.org) : (user.org || "");
    if(menuAdmin) menuAdmin.hidden = !(user.isAdmin || user.role === "admin" || user.is_admin);
  } else {
    if(avatarInner){
      avatarInner.innerHTML = '<svg class="topbar-avatar-guest-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>';
      avatarInner.style.background = "transparent";
    }
    if(avatarBtn){
      var t = (window.i18n && window.i18n.t) ? window.i18n.t : function(k){ return k; };
      avatarBtn.setAttribute("title", t("auth.account_menu") || "계정 및 설정");
    }

    if(menuLoggedIn) menuLoggedIn.hidden = true;
    if(menuGuest) menuGuest.hidden = false;
    if(menuFooter) menuFooter.hidden = true;
    if(menuEditProfileRow) menuEditProfileRow.hidden = true;
  }

  if (typeof initSettingsSubtabs === "function") {
    try { initSettingsSubtabs(); } catch(e){}
  }
}
window.updateTopbarUserUI = updateTopbarUserUI;

function resetIdForm(){
  loginStage = "identify";
  pendingAccount = null;
  idNameInput.disabled = false;
  idOrgSelect.disabled = false;
  idEmailInput.disabled = false;
  idPasswordStage.hidden = true;
  idPasswordConfirmWrap.hidden = true;
  idPasswordInput.value = "";
  idPasswordConfirmInput.value = "";
  idPasswordHint.textContent = "";
  idFormError.textContent = "";
  idFormSubmitBtn.disabled = false;
  idFormSubmitBtn.textContent = "다음";
}

function applyLogin(user){
  if (!user) return;
  // Ensure token is never stored in JS user profile
  if (user.token) delete user.token;
  loggedInUser = user;
  window.loggedInUser = user;

  var isAdm = Boolean(user.isAdmin || user.role === 'admin' || user.is_admin);
  user.isAdmin = isAdm;
  user.is_admin = isAdm;

  var isMgr = Boolean(isAdm || user.role === 'manager' || user.isManager);
  user.isManager = isMgr;

  try {
    sessionStorage.setItem("argosUser", JSON.stringify(user)); 
    localStorage.setItem("argosUser", JSON.stringify(user));
    sessionStorage.setItem("jarvisUser", JSON.stringify(user)); 
    localStorage.setItem("jarvisUser", JSON.stringify(user));
  } catch(e){}

  loginBtn.hidden = true;
  userChip.hidden = false;
  if(user.avatarUrl){
    userAvatar.innerHTML = '<img src="' + escapeHtml(user.avatarUrl) + '" alt="" style="width:100%;height:100%;border-radius:50%;object-fit:cover;display:block;">';
    userAvatar.style.background = "transparent";
  } else {
    userAvatar.textContent = (user.name || "?").charAt(0);
    try {
      var d = deptById(user.org);
      if(d) userAvatar.style.background = colorVar(d.colorIndex);
    } catch(e){}
  }
  userChipName.textContent = user.name + " · " + orgLabel(user.org);
  userChipEmail.textContent = user.email || "";
  fillSubmitterFromLogin();
  updateSubmitAvailability();
  updateTopbarUserUI(user);

  // Toggle View Form vs Guest Gate
  var guestGate = document.getElementById("viewFormGuestPlaceholder");
  var submitForm = document.getElementById("submitForm");
  if(guestGate) { guestGate.hidden = true; guestGate.style.display = "none"; }
  if(submitForm) { submitForm.hidden = false; submitForm.style.display = ""; }



  // 관리자(Admin) 및 매니저(Manager) 권한에 따른 관리 탭 표시 제어
  if(el.tabHistory){
    el.tabHistory.hidden = !isMgr;
  }
  if(el.tabSettings){
    el.tabSettings.hidden = !isMgr;
  }
  if(el.navTabsAdmin){
    el.navTabsAdmin.hidden = !isMgr;
  }

  // 로그인 시 AI Chat 탭 표시
  if(el.tabChat){
    el.tabChat.hidden = false;
  }

  // Viewer (read-only): ẩn tab 업무 등록 và nút tạo lịch để tránh 403 sau khi điền form
  var viewerOnly = (typeof isViewerUser === "function") ? isViewerUser() : (user.role === "viewer");
  if(el.tabForm){
    el.tabForm.hidden = viewerOnly;
  }
  if(viewerOnly && currentActiveTab === "form" && typeof showTab === "function"){
    showTab("home");
  }
  var addSchedBtn = document.getElementById("btnSchedOpenCreateModal");
  if(addSchedBtn){
    addSchedBtn.style.display = viewerOnly ? "none" : "";
  }

  // Nút "제품 수정" và "새 제품 등록" chỉ hiển thị với Admin hoặc Manager
  var pimEditBtn = document.getElementById("pimModalEditBtn");
  if(pimEditBtn){
    pimEditBtn.hidden = !(typeof canModifyPimUser === "function" && canModifyPimUser());
  }
  var pimNewBtnEl = document.getElementById("pimNewBtn");
  if(pimNewBtnEl){
    var canModPim = (typeof canModifyPimUser === "function") && canModifyPimUser();
    pimNewBtnEl.style.display = canModPim ? "" : "none";
    pimNewBtnEl.hidden = !canModPim;
  }

  if(!el.schedule.hidden && typeof loadSchedule === "function") loadSchedule();
  if(el.history && !el.history.hidden && typeof loadHistoryActivities === "function") loadHistoryActivities();
  if(typeof renderDeptCards === "function") renderDeptCards();
  if(typeof renderHomePortalSection === "function") renderHomePortalSection();
  if(typeof renderHomeQuickActions === "function") renderHomeQuickActions();
}

function applyLogout(){
  var wasLoggedIn = Boolean(loggedInUser || localStorage.getItem("argosUser") || sessionStorage.getItem("argosUser"));
  var csrfToken = sessionStorage.getItem("argosCsrfToken") || localStorage.getItem("argosCsrfToken") || "";
  loggedInUser = null;
  window.loggedInUser = null;

  // 1. Send server logout request with current CSRF token before clearing storage
  var logoutPromise = Promise.resolve();
  if (wasLoggedIn) {
    try {
      var headers = {
        "Content-Type": "application/json",
        "Cache-Control": "no-store"
      };
      if (csrfToken) headers["X-CSRF-Token"] = csrfToken;
      logoutPromise = fetch("/api/account/logout", {
        method: "POST",
        credentials: "same-origin",
        headers: headers,
        body: "{}"
      }).catch(function(){});
    } catch(e){}
  }

  // 2. Clear all local cache and tokens
  try{ sessionStorage.removeItem("argosUser"); }catch(e){}
  try{ localStorage.removeItem("argosUser"); }catch(e){}
  try{ sessionStorage.removeItem("jarvisUser"); }catch(e){}
  try{ localStorage.removeItem("jarvisUser"); }catch(e){}
  try{ sessionStorage.removeItem("batonUser"); }catch(e){}
  try{ localStorage.removeItem("batonUser"); }catch(e){}
  try{ localStorage.removeItem("argos_token"); }catch(e){}
  try{ sessionStorage.removeItem("argos_token"); }catch(e){}
  try{ localStorage.removeItem("argosToken"); }catch(e){}
  try{ sessionStorage.removeItem("argosToken"); }catch(e){}
  try{ localStorage.removeItem("argosCsrfToken"); }catch(e){}
  try{ sessionStorage.removeItem("argosCsrfToken"); }catch(e){}
  try{ document.cookie = "argos_token=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;"; }catch(e){}

  if(loginBtn) loginBtn.hidden = false;
  if(userChip) userChip.hidden = true;
  updateTopbarUserUI(null);
  if(submitterField) submitterField.value = "우측 상단에서 이름/소속을 입력하면 자동으로 채워집니다";
  updateSubmitAvailability();

  // Toggle View Form vs Guest Gate on logout
  var guestGateLogout = document.getElementById("viewFormGuestPlaceholder");
  var submitFormLogout = document.getElementById("submitForm");
  if(guestGateLogout) { guestGateLogout.hidden = false; guestGateLogout.style.display = "flex"; }
  if(submitFormLogout) { submitFormLogout.hidden = true; submitFormLogout.style.display = "none"; }

  // 로그아웃 시 숨김 상태 복원 (다음 로그인 사용자를 위해)
  if(el.tabForm) el.tabForm.hidden = false;
  var addSchedBtnLogout = document.getElementById("btnSchedOpenCreateModal");
  if(addSchedBtnLogout) addSchedBtnLogout.style.display = "";

  // 로그아웃 시 AI Chat 탭 숨김
  if(el.tabChat){
    el.tabChat.hidden = true;
  }

  // 로그아웃 시 관리자 전용 탭 즉시 숨김 및 홈으로 이동
  if(el.tabHistory){
    el.tabHistory.hidden = true;
  }
  if(el.tabSettings){
    el.tabSettings.hidden = true;
  }
  if(el.navTabsAdmin){
    el.navTabsAdmin.hidden = true;
  }
  if(((el.history && !el.history.hidden) || (el.settings && !el.settings.hidden) || (el.chat && !el.chat.hidden)) && typeof showTab === "function"){
    showTab("home");
  }

  if(el.schedule && !el.schedule.hidden && typeof renderSchedule === "function"){ schedEvents = []; renderSchedule(); }
  if(typeof renderDeptCards === "function") renderDeptCards();
  if(typeof renderHomePortalSection === "function") renderHomePortalSection();
  if(typeof renderHomeQuickActions === "function") renderHomeQuickActions();

  return logoutPromise;
}

var _authExpiredDebounce = null;
function handleAuthExpired(){
  var wasLoggedIn = Boolean(loggedInUser || localStorage.getItem("argosUser") || sessionStorage.getItem("argosUser"));
  if (!wasLoggedIn) return;
  if (_authExpiredDebounce) return;
  _authExpiredDebounce = setTimeout(function(){ _authExpiredDebounce = null; }, 4000);
  applyLogout();
  showToast("로그인이 만료되었습니다. 다시 로그인해주세요.");
}

loginBtn.addEventListener("click", function(){
  window.location.href = "/login";
});
idFormCancel.addEventListener("click", function(){ idForm.hidden = true; resetIdForm(); });

idForm.addEventListener("submit", function(e){
  e.preventDefault();
  idFormError.textContent = "";
  var name = idNameInput.value.trim();
  var org = idOrgSelect.value;
  var email = idEmailInput.value.trim();
  if(!name || !org){
    idFormError.textContent = "이름과 소속 부서를 입력해주세요.";
    return;
  }

  if(loginStage === "identify"){
    idFormSubmitBtn.disabled = true;
    apiPostJson("/api/account/check", { name: name, org: org }).then(function(res){
      idFormSubmitBtn.disabled = false;
      if(!res.ok){
        idFormError.textContent = res.error || "확인 중 오류가 발생했습니다.";
        return;
      }
      pendingAccount = { name: name, org: org, email: email, exists: res.exists };
      idNameInput.disabled = true;
      idOrgSelect.disabled = true;
      idEmailInput.disabled = true;
      idPasswordStage.hidden = false;
      loginStage = "password";
      idPasswordInput.value = "";
      idPasswordConfirmInput.value = "";
      if(res.exists){
        idPasswordLabel.textContent = "비밀번호";
        idPasswordHint.textContent = "";
        idPasswordConfirmWrap.hidden = true;
        idFormSubmitBtn.textContent = "로그인";
      } else {
        idPasswordLabel.textContent = "새 비밀번호 만들기";
        idPasswordHint.textContent = "처음 접속이시네요! 다음에도 본인 확인용으로 쓸 간단한 비밀번호를 만들어주세요 (4자 이상).";
        idPasswordConfirmWrap.hidden = false;
        idFormSubmitBtn.textContent = "계정 만들고 시작";
      }
      idPasswordInput.focus();
    }).catch(function(){
      idFormSubmitBtn.disabled = false;
      idFormError.textContent = "서버에 연결할 수 없습니다.";
    });
    return;
  }

  var password = idPasswordInput.value;
  if(!password){
    idFormError.textContent = "비밀번호를 입력해주세요.";
    return;
  }
  if(!pendingAccount.exists){
    if(password.length < 4){
      idFormError.textContent = "비밀번호는 4자 이상으로 만들어주세요.";
      return;
    }
    if(password !== idPasswordConfirmInput.value){
      idFormError.textContent = "비밀번호 확인이 일치하지 않습니다.";
      return;
    }
  }

  idFormSubmitBtn.disabled = true;
  var endpoint = pendingAccount.exists ? "/api/account/login" : "/api/account/register";
  var body = pendingAccount.exists
    ? { name: pendingAccount.name, org: pendingAccount.org, password: password }
    : { name: pendingAccount.name, org: pendingAccount.org, email: pendingAccount.email, password: password };
  apiPostJson(endpoint, body).then(function(res){
    idFormSubmitBtn.disabled = false;
    if(!res.ok){
      idFormError.textContent = res.error || "로그인에 실패했습니다.";
      return;
    }
    var userData = {
      name: res.user.name,
      org: res.user.org,
      email: res.user.email,
      isAdmin: res.user.isAdmin
    };
    try {
      if(res.token){
        sessionStorage.setItem("argosToken", res.token);
        localStorage.setItem("argosToken", res.token);
      }
      if(res.csrfToken){
        sessionStorage.setItem("argosCsrfToken", res.csrfToken);
        localStorage.setItem("argosCsrfToken", res.csrfToken);
      }
      sessionStorage.setItem("argosUser", JSON.stringify(userData));
      localStorage.setItem("argosUser", JSON.stringify(userData));
      sessionStorage.setItem("jarvisUser", JSON.stringify(userData));
      localStorage.setItem("jarvisUser", JSON.stringify(userData));
      sessionStorage.setItem("justLoggedIn", res.user.name);
    } catch(e){}

    idForm.hidden = true;
    resetIdForm();
    showToast(res.user.name + "님으로 로그인되었습니다. 페이지를 새로고침합니다...");
    setTimeout(function(){
      window.location.reload();
    }, 200);
  }).catch(function(){
    idFormSubmitBtn.disabled = false;
    idFormError.textContent = "서버에 연결할 수 없습니다.";
  });
});

if(logoutBtn){
  logoutBtn.addEventListener("click", function(){
    showToast("로그아웃되었습니다. 로그인 페이지로 이동합니다...");
    var p = applyLogout();
    if(p && typeof p.then === "function"){
      p.finally(function(){
        setTimeout(function(){ window.location.href = "/login?logout=1"; }, 100);
      });
    } else {
      setTimeout(function(){ window.location.href = "/login?logout=1"; }, 200);
    }
  });
}

// Initial guest avatar state
updateTopbarUserUI(null);

// ── Edit Profile Modal Logic ─────────────────────────────────
(function initEditProfileModal(){
  var btnOpen = document.getElementById("btnOpenEditProfile");
  var modal = document.getElementById("modalEditProfile");
  var btnClose = document.getElementById("btnEditProfileClose");
  var btnCancel = document.getElementById("btnEditProfileCancel");
  var form = document.getElementById("formEditProfile");
  var nameInput = document.getElementById("editProfileNameInput");
  var emailInput = document.getElementById("editProfileEmailInput");
  var orgSelect = document.getElementById("editProfileOrgSelect");
  var pwdInput = document.getElementById("editProfilePasswordInput");
  var errBox = document.getElementById("editProfileError");
  var btnSubmit = document.getElementById("btnEditProfileSubmit");
  var avatarPreview = document.getElementById("editProfileAvatarPreview");
  var avatarFileInput = document.getElementById("editProfileAvatarFile");
  var btnAvatarReset = document.getElementById("btnEditProfileAvatarReset");

  var currentAvatarData = null; // base64 if newly selected
  var currentAvatarUrl = null;  // existing url or ""

  function renderAvatarPreview(url, name, org){
    if(!avatarPreview) return;
    if(url){
      avatarPreview.innerHTML = '<img src="' + escapeHtml(url) + '" alt="" style="width:100%;height:100%;object-fit:cover;border-radius:50%;">';
      avatarPreview.style.background = "transparent";
      if(btnAvatarReset) btnAvatarReset.style.display = "inline-flex";
    } else {
      var initial = (name || "?").charAt(0).toUpperCase();
      var deptColor = "#0284c7";
      try {
        if(typeof deptById === "function" && typeof colorVar === "function") {
          var d = deptById(org);
          if(d) deptColor = colorVar(d.colorIndex);
        }
      } catch(e){}
      avatarPreview.textContent = initial;
      avatarPreview.style.background = deptColor;
      if(btnAvatarReset) btnAvatarReset.style.display = "none";
    }
  }

  if(avatarFileInput){
    avatarFileInput.addEventListener("change", function(e){
      var file = e.target.files && e.target.files[0];
      if(!file) return;
      if(file.size > 5 * 1024 * 1024){
        if(errBox){ errBox.style.display = "block"; errBox.textContent = "이미지 크기는 최대 5MB까지 가능합니다."; }
        return;
      }
      var reader = new FileReader();
      reader.onload = function(evt){
        currentAvatarData = evt.target.result;
        currentAvatarUrl = evt.target.result;
        renderAvatarPreview(currentAvatarUrl, nameInput ? nameInput.value : "?", orgSelect ? orgSelect.value : "dev");
      };
      reader.readAsDataURL(file);
    });
  }

  if(btnAvatarReset){
    btnAvatarReset.addEventListener("click", function(){
      currentAvatarData = "";
      currentAvatarUrl = "";
      if(avatarFileInput) avatarFileInput.value = "";
      renderAvatarPreview("", nameInput ? nameInput.value : "?", orgSelect ? orgSelect.value : "dev");
    });
  }

  async function renderOrgOptions(){
    if(!orgSelect) return;
    if((!window.DEPARTMENTS || !window.DEPARTMENTS.length) && typeof fetchDepartments === "function"){
      try { await fetchDepartments(); } catch(e){}
    }
    var html = "";
    if(window.DEPARTMENTS && window.DEPARTMENTS.length){
      window.DEPARTMENTS.forEach(function(d){
        html += '<option value="' + d.id + '">' + (d.name || d.id) + '</option>';
      });
    } else {
      html = '<option value="dev">개발팀</option><option value="rnd">연구소</option>';
    }
    orgSelect.innerHTML = html;
  }

  function openEditModal(){
    var u = (typeof getCurrentUser === "function") ? getCurrentUser() : loggedInUser;
    if(!u) return;
    renderOrgOptions();
    if(nameInput) nameInput.value = u.name || "";
    if(emailInput) emailInput.value = u.email || "";
    if(orgSelect && u.org) orgSelect.value = u.org;
    if(pwdInput) pwdInput.value = "";
    currentAvatarData = null;
    currentAvatarUrl = u.avatarUrl || "";
    if(avatarFileInput) avatarFileInput.value = "";
    renderAvatarPreview(currentAvatarUrl, u.name, u.org);

    if(errBox) { errBox.style.display = "none"; errBox.textContent = ""; }
    if(modal) modal.hidden = false;
    var topbarMenu = document.getElementById("topbarAccountMenu");
    if(topbarMenu) topbarMenu.hidden = true;
    if(nameInput) nameInput.focus();
  }

  function closeEditModal(){
    if(modal) modal.hidden = true;
    if(errBox) { errBox.style.display = "none"; errBox.textContent = ""; }
  }

  if(btnOpen) btnOpen.addEventListener("click", openEditModal);
  if(btnClose) btnClose.addEventListener("click", closeEditModal);
  if(btnCancel) btnCancel.addEventListener("click", closeEditModal);
  if(modal){
    modal.addEventListener("click", function(e){
      if(e.target === modal) closeEditModal();
    });
  }
  document.addEventListener("keydown", function(e){
    if(e.key === "Escape" && modal && !modal.hidden){
      closeEditModal();
    }
  });

  if(form){
    form.addEventListener("submit", async function(e){
      e.preventDefault();
      var newName = (nameInput ? nameInput.value.trim() : "");
      var newEmail = (emailInput ? emailInput.value.trim() : "");
      var newOrg = (orgSelect ? orgSelect.value : "");
      var newPwd = (pwdInput ? pwdInput.value.trim() : "");

      if(!newName){
        if(errBox){ errBox.style.display = "block"; errBox.textContent = "이름을 입력해주세요."; }
        return;
      }

      if(btnSubmit) btnSubmit.disabled = true;
      if(errBox) { errBox.style.display = "none"; errBox.textContent = ""; }

      try {
        var payload = { name: newName, email: newEmail, org: newOrg };
        if(newPwd) payload.password = newPwd;
        if(currentAvatarData !== null) {
          if(currentAvatarData === "") {
            payload.avatar_url = "";
          } else {
            payload.avatar_data = currentAvatarData;
          }
        }

        var res = await apiPostJson("/api/account/update-profile", payload);
        if(res && res.ok){
          showToast("회원 정보가 성공적으로 수정되었습니다.");
          closeEditModal();
          // Update user state in localStorage & UI
          var u = (typeof getCurrentUser === "function") ? getCurrentUser() : loggedInUser;
          if(u){
            u.name = res.user.name;
            u.email = res.user.email;
            u.org = res.user.org;
            u.avatarUrl = res.user.avatarUrl || "";
            sessionStorage.setItem("argosUser", JSON.stringify(u));
            localStorage.setItem("argosUser", JSON.stringify(u));
            sessionStorage.setItem("jarvisUser", JSON.stringify(u));
            localStorage.setItem("jarvisUser", JSON.stringify(u));
            applyLogin(u);
          }
        } else {
          if(errBox){ errBox.style.display = "block"; errBox.textContent = (res && res.error) || "수정에 실패했습니다."; }
        }
      } catch(err){
        if(errBox){ errBox.style.display = "block"; errBox.textContent = "오류: " + err.message; }
      } finally {
        if(btnSubmit) btnSubmit.disabled = false;
      }
    });
  }
})();

// ── Verify Active Session on Page Load (Pure HttpOnly Cookie) ──
(function verifyActiveSession(){
  apiGet("/api/account/me").then(function(res){
    if (res && res.ok && res.user) {
      if (res.csrfToken) {
        sessionStorage.setItem("argosCsrfToken", res.csrfToken);
        localStorage.setItem("argosCsrfToken", res.csrfToken);
      }
      applyLogin(res.user);
    } else {
      applyLogout();
    }
  }).catch(function(){
    // Server offline or connection failed
  });
})();

