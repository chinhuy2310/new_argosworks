
// === DEPARTMENT MANAGEMENT FOR REGISTRATION ===
let availableDepartments = [];

async function loadDepartments() {
  try {
    const res = await fetch('/api/auth/departments', { cache: 'no-store' });
    const data = await res.json();
    if (data && data.ok && Array.isArray(data.departments)) {
      availableDepartments = data.departments;
      renderDepartmentOptions();
    }
  } catch (e) {
    console.warn('Failed to load departments:', e);
  }
}

function renderDepartmentOptions() {
  const select = document.getElementById('auth-dept');
  if (!select) return;
  const t = dict[currentLang] || dict.ko;
  const cur = select.value;
  select.innerHTML = '';

  const placeholder = document.createElement('option');
  placeholder.value = '';
  placeholder.textContent = `-- ${t.phDept || '소속 부서를 선택하세요'} --`;
  placeholder.disabled = true;
  if (!cur) placeholder.selected = true;
  select.appendChild(placeholder);

  availableDepartments.forEach(d => {
    const opt = document.createElement('option');
    opt.value = d.id;
    opt.textContent = d.name || d.id;
    if (cur === d.id) opt.selected = true;
    select.appendChild(opt);
  });
}

// ============================================================================
// ARGOS WORKS - CINEMATIC PUZZLE SPLIT-MERGE AUTH CONTROLLER
// Original Flagship Choivis-style 2D Puzzle Animation (Zero 3D Blur, Zero Glitch)
// Supported Languages: KO (한국어) & EN (English)
// ============================================================================

// === AUTH & INITIAL SETUP GUARD ===
fetch('/api/setup/status', { cache: 'no-store' })
  .then(function(r) { return r.json(); })
  .then(function(res) {
    if (res && res.ok && res.needs_setup) {
      window.location.replace('/setup');
    }
  }).catch(function(){});

var urlParams = new URLSearchParams(window.location.search);
if (urlParams.has('logout')) {
  // Explicit logout request: invalidate session and do not auto-redirect
  fetch('/api/account/logout', { method: 'POST', credentials: 'same-origin', cache: 'no-store' }).catch(function(){});
} else {
  fetch('/api/account/me', { credentials: 'same-origin', cache: 'no-store' })
    .then(function(r) { return r.json(); })
    .then(function(res) {
      if (res && res.ok && res.user) {
        window.location.replace('/');
      }
    }).catch(function(){});
}

let isLoginMode = true; // true = Login, false = Register
let isAnimating = false;
let currentLang = localStorage.getItem('argos_lang') || localStorage.getItem('jarvisLang') || 'ko';
if (currentLang !== 'en') currentLang = 'ko';

// === BILINGUAL DICTIONARY (KO & EN) ===
const dict = {
  ko: {
    langBtn: 'KO',
    signInMain: '로그',
    signInAccent: '인',
    signInSub: '지능형 업무관리 시스템에 오신 것을 환영합니다',
    lblUserLogin: '아이디 또는 이메일',
    phUserLogin: 'ArgosWorks ID 또는 회사 이메일',
    lblPass: '비밀번호',
    phPass: '••••••••',
    btnSignIn: '로그인',
    promptToSignUp: '계정 발급이 필요하신가요?',
    linkToSignUp: '계정 발급 요청',

    signUpMain: '계정',
    signUpAccent: '요청',
    signUpSub: '사내 업무 시스템 계정 발급을 요청합니다. 관리자 승인 후 활성화됩니다.',
    lblUserReg: 'ArgosWorks ID (요청 아이디)',
    phUserReg: '예: hongkd (영문, 숫자 3자 이상)',
    lblName: '이름 (Full Name)',
    lblDept: '소속 부서 (필수)',
    phDept: '소속 부서를 선택하세요',
    lblEmail: '회사 이메일 (선택)',
    phEmail: 'user@company.com (선택 사항)',
    errDeptRequired: '소속 부서를 선택해주세요',
    phName: '예: 홍길동',
    lblPassReg: '비밀번호 (Password)',
    lblConfirmPass: '비밀번호 확인',
    phConfirmPass: '••••••••',
    lblEmail: '이메일 주소 (선택)',
    phEmail: 'user@company.com (선택 사항)',
    btnSignUp: '계정 발급 요청',
    promptToSignIn: '이미 승인된 계정이 있으신가요?',
    linkToSignIn: '로그인',

    btnProcessing: '처리 중...',
    errFillRequired: '아이디, 이름, 비밀번호를 모두 입력해주세요',
    errUsernameShort: 'ArgosWorks ID는 최소 3자 이상이어야 합니다',
    errInvalidEmail: '올바른 이메일 주소(user@company.com)를 입력해주세요',
    errPasswordShort: '비밀번호는 최소 8자 이상이어야 합니다',
    errPasswordMismatch: '비밀번호가 일치하지 않습니다',
    errUserExists: '이미 등록된 아이디 또는 이메일입니다',
    errInvalidCreds: '아이디(이메일) 또는 비밀번호가 올바르지 않습니다',
    errConnection: '서버에 연결할 수 없습니다. 네트워크를 확인해주세요',
    errGeneral: '오류가 발생했습니다. 다시 시도해주세요',
    successRegister: '계정이 성공적으로 생성되었습니다! 이동 중...',
    pendingRegister: '계정 발급 요청이 접수되었습니다. 관리자(Admin) 승인 완료 후 로그인하실 수 있습니다.'
  },
  en: {
    langBtn: 'EN',
    signInMain: 'Sign',
    signInAccent: 'In',
    signInSub: 'Welcome to ARGOS WORKS Intelligent Workspace',
    lblUserLogin: 'ArgosWorks ID or Email',
    phUserLogin: 'Enter ID or work email',
    lblPass: 'Password',
    phPass: '••••••••',
    btnSignIn: 'Sign In',
    promptToSignUp: "Need an enterprise account?",
    linkToSignUp: 'Request Account',

    signUpMain: 'Request',
    signUpAccent: 'Account',
    signUpSub: 'Submit an account request. Access will be activated upon Admin approval.',
    lblUserReg: 'ArgosWorks ID (Requested ID)',
    phUserReg: 'e.g. alex (3+ letters/digits)',
    lblName: 'Full Name (Required)',
    lblDept: 'Department (Required)',
    phDept: 'Select your department',
    lblEmail: 'Work Email (Optional)',
    phEmail: 'user@company.com (optional)',
    errDeptRequired: 'Please select your department',
    phName: 'e.g. Alex Johnson',
    lblPassReg: 'Password (Required)',
    lblConfirmPass: 'Confirm Password (Required)',
    phConfirmPass: '••••••••',
    lblEmail: 'Work Email (Optional)',
    phEmail: 'user@company.com (optional)',
    btnSignUp: 'Submit Request',
    promptToSignIn: 'Already have an approved account?',
    linkToSignIn: 'Sign In',

    btnProcessing: 'Processing...',
    errFillRequired: 'Please enter ID, Full Name, and Password',
    errUsernameShort: 'ArgosWorks ID must be at least 3 characters',
    errInvalidEmail: 'Please enter a valid email (user@company.com)',
    errPasswordShort: 'Password must be at least 8 characters',
    errPasswordMismatch: 'Passwords do not match',
    errUserExists: 'Username or email already registered',
    errInvalidCreds: 'Invalid ID/Email or Password',
    errConnection: 'Cannot connect to server. Check your network',
    errGeneral: 'An error occurred. Please try again',
    successRegister: 'Account created successfully! Redirecting...',
    pendingRegister: 'Your account request has been submitted. You can log in once an Administrator approves your request.'
  }
};

// === RENDER TEXT ACCORDING TO STATE & LANGUAGE ===
function renderFormText() {
  const t = dict[currentLang] || dict.ko;
  const langLabel = document.getElementById('lang-btn-label');
  if (langLabel) langLabel.textContent = t.langBtn;

  // Header Title & Subtitle
  const titleMain = document.getElementById('title-main');
  const titleAccent = document.getElementById('title-accent');
  const formSubtitle = document.getElementById('form-subtitle');

  if (isLoginMode) {
    if (titleMain) titleMain.textContent = t.signInMain;
    if (titleAccent) titleAccent.textContent = t.signInAccent;
    if (formSubtitle) formSubtitle.textContent = t.signInSub;
  } else {
    if (titleMain) titleMain.textContent = t.signUpMain;
    if (titleAccent) titleAccent.textContent = t.signUpAccent;
    if (formSubtitle) formSubtitle.textContent = t.signUpSub;
  }

  // Field Labels & Placeholders
  const lblUser = document.getElementById('lbl-username');
  const inputUser = document.getElementById('auth-username');
  const lblName = document.getElementById('lbl-name');
  const inputName = document.getElementById('auth-name');
  const lblPass = document.getElementById('lbl-password');
  const inputPass = document.getElementById('auth-password');
  const lblConfirm = document.getElementById('lbl-confirm-password');
  const inputConfirm = document.getElementById('auth-confirm-password');

  if (lblUser) lblUser.textContent = isLoginMode ? t.lblUserLogin : t.lblUserReg;
  if (inputUser) inputUser.placeholder = isLoginMode ? t.phUserLogin : t.phUserReg;
  if (lblName) lblName.textContent = t.lblName;
  if (inputName) inputName.placeholder = t.phName;
  const lblDept = document.getElementById('lbl-dept');
  if (lblDept) lblDept.textContent = t.lblDept;
  const lblEmail = document.getElementById('lbl-email');
  const inputEmail = document.getElementById('auth-email');
  if (lblEmail) lblEmail.textContent = t.lblEmail;
  if (inputEmail) inputEmail.placeholder = t.phEmail;
  renderDepartmentOptions();
  if (lblPass) lblPass.textContent = isLoginMode ? t.lblPass : t.lblPassReg;
  if (inputPass) inputPass.placeholder = t.phPass;
  if (lblConfirm) lblConfirm.textContent = t.lblConfirmPass;
  if (inputConfirm) inputConfirm.placeholder = t.phConfirmPass;

  // Submit Button
  const txtSubmit = document.getElementById('txt-submit');
  if (txtSubmit) txtSubmit.textContent = isLoginMode ? t.btnSignIn : t.btnSignUp;

  // Switch Links
  const switchPrompt = document.getElementById('switch-prompt');
  const switchLink = document.getElementById('btn-switch-auth');
  if (switchPrompt) switchPrompt.textContent = isLoginMode ? t.promptToSignUp : t.promptToSignIn;
  if (switchLink) switchLink.textContent = isLoginMode ? t.linkToSignUp : t.linkToSignIn;
}

// === CINEMATIC CARD SPLIT-MERGE PUZZLE ANIMATION ===
async function triggerPuzzleTransition(targetIsLogin) {
  if (isAnimating || isLoginMode === targetIsLogin) return;
  isAnimating = true;

  const formWrap = document.getElementById('form-content-wrap');
  const card = document.getElementById('auth-card-wrapper');
  const shell = document.getElementById('card-shell');
  const pieceTL = document.getElementById('piece-tl');
  const pieceBR = document.getElementById('piece-br');
  const emblem = document.getElementById('center-emblem');
  const seam = document.getElementById('card-seam');
  const flash = document.getElementById('card-flash');
  const banner = document.getElementById('auth-banner');

  if (banner) {
    banner.style.display = 'none';
    banner.innerText = '';
  }

  const animElements = [formWrap, card, shell, pieceTL, pieceBR, emblem, seam, flash].filter(Boolean);

  // Pre-clean: cancel any lingering animations
  animElements.forEach(el => {
    try {
      el.getAnimations().forEach(a => a.cancel());
    } catch(e) {}
  });

  const activeAnims = [];
  function runAnim(el, keyframes, options) {
    if (!el) return null;
    const a = el.animate(keyframes, options);
    activeAnims.push(a);
    return a;
  }

  try {
    // 1. Form content disappears — text & inputs fade out smoothly
    const fadeForm = runAnim(formWrap, [
      { opacity: 1, filter: 'blur(0px)', transform: 'translateY(0)' },
      { opacity: 0, filter: 'blur(8px)', transform: 'translateY(-10px)' }
    ], { duration: 180, easing: 'ease-in', fill: 'forwards' });

    const fadeShell = shell ? runAnim(shell, [
      { opacity: 1 },
      { opacity: 0 }
    ], { duration: 160, easing: 'ease-in', fill: 'forwards' }) : null;

    await Promise.all([
      fadeForm ? fadeForm.finished : Promise.resolve(),
      fadeShell ? fadeShell.finished : Promise.resolve()
    ]);

    // 2. Compute seam length & diagonal angle based on card size
    const W = card.offsetWidth;
    const H = card.offsetHeight;
    const angle = -Math.atan2(H, W) * 180 / Math.PI;
    const diag = Math.hypot(W, H);
    if (seam) seam.style.width = (diag + 40) + 'px';

    // 3. The card splits into two triangular pieces at opposite corners,
    // while the central official Argos Works Emblem manifests with ambient cyber glow
    pieceTL.style.opacity = '1';
    pieceBR.style.opacity = '1';
    if (emblem) emblem.style.opacity = '1';

    const dist = 44; // floating separation gap
    const rot = 5.5; // subtle tilt

    const animTL = runAnim(pieceTL, [
      { transform: `translate(-${dist}px, -${dist}px) rotate(-${rot}deg)` },
      { transform: `translate(-${dist}px, -${dist}px) rotate(-${rot}deg)`, offset: 0.22 },
      { transform: 'translate(0px, 0px) rotate(0deg)' }
    ], { duration: 380, easing: 'cubic-bezier(.7, .05, .25, 1)', fill: 'forwards' });

    const animBR = runAnim(pieceBR, [
      { transform: `translate(${dist}px, ${dist}px) rotate(${rot}deg)` },
      { transform: `translate(${dist}px, ${dist}px) rotate(${rot}deg)`, offset: 0.22 },
      { transform: 'translate(0px, 0px) rotate(0deg)' }
    ], { duration: 380, easing: 'cubic-bezier(.7, .05, .25, 1)', fill: 'forwards' });

    const animEmblemIn = emblem ? runAnim(emblem, [
      { opacity: 0, transform: 'translate(-50%, -50%) scale(0.65)' },
      { opacity: 1, transform: 'translate(-50%, -50%) scale(1)' }
    ], { duration: 380, easing: 'cubic-bezier(.16, 1, .3, 1)', fill: 'forwards' }) : null;

    await Promise.all([
      animTL ? animTL.finished : Promise.resolve(),
      animBR ? animBR.finished : Promise.resolve(),
      animEmblemIn ? animEmblemIn.finished : Promise.resolve()
    ]);

    // 4. The instant they merge:
    // - Emblem radiates
    // - Diagonal seam flashes across the split
    // - Warm cyan blur flash bursts from center
    // - Card blooms with cyan ambient radiance
    const animEmblemPulse = emblem ? runAnim(emblem, [
      { transform: 'translate(-50%, -50%) scale(1)', filter: 'drop-shadow(0 0 25px rgba(51, 170, 211, 0.85))', opacity: 1 },
      { transform: 'translate(-50%, -50%) scale(1.15)', filter: 'drop-shadow(0 0 55px rgba(127, 204, 223, 1)) brightness(1.35)', opacity: 1, offset: 0.2 },
      { transform: 'translate(-50%, -50%) scale(0.92)', opacity: 0 }
    ], { duration: 440, easing: 'ease-out', fill: 'forwards' }) : null;

    const animSeam = seam ? runAnim(seam, [
      { transform: `translate(-50%, -50%) rotate(${angle}deg) scaleX(0.2)`, opacity: 0 },
      { transform: `translate(-50%, -50%) rotate(${angle}deg) scaleX(1)`, opacity: 0.95, offset: 0.18 },
      { transform: `translate(-50%, -50%) rotate(${angle}deg) scaleX(1)`, opacity: 0 }
    ], { duration: 420, easing: 'ease-out', fill: 'forwards' }) : null;

    const animFlash = flash ? runAnim(flash, [
      { transform: 'translate(-50%, -50%) scale(0.12)', opacity: 0.98 },
      { transform: 'translate(-50%, -50%) scale(2.4)', opacity: 0 }
    ], { duration: 440, easing: 'cubic-bezier(.2, .6, .3, 1)', fill: 'forwards' }) : null;

    const animCardGlow = runAnim(card, [
      { boxShadow: '0 30px 70px -10px rgba(0,0,0,.95), 0 0 0 0 rgba(51,170,211,0)' },
      { boxShadow: '0 30px 70px -10px rgba(0,0,0,.95), 0 0 95px 16px rgba(51,170,211,.55)', offset: 0.22 },
      { boxShadow: '0 30px 70px -10px rgba(0,0,0,.95), 0 0 0 0 rgba(51,170,211,0)' }
    ], { duration: 480, easing: 'ease-out', fill: 'forwards' });

    // 5. Card unfolds back into rounded rectangle, revealing new form
    const startHeight = card.offsetHeight;
    isLoginMode = targetIsLogin;

    const nameGroup = document.getElementById('name-group');
    const deptGroup = document.getElementById('dept-group');
    const emailGroup = document.getElementById('email-group');
    const confirmGroup = document.getElementById('confirm-password-group');

    if (nameGroup) nameGroup.style.display = isLoginMode ? 'none' : 'block';
    if (deptGroup) deptGroup.style.display = isLoginMode ? 'none' : 'block';
    if (emailGroup) emailGroup.style.display = isLoginMode ? 'none' : 'block';
    if (confirmGroup) confirmGroup.style.display = isLoginMode ? 'none' : 'block';

    renderFormText();
  loadDepartments();
    const endHeight = card.offsetHeight;

    // Smooth card height morph
    let animHeight = null;
    if (startHeight !== endHeight) {
      animHeight = runAnim(card, [
        { height: `${startHeight}px` },
        { height: `${endHeight}px` }
      ], { duration: 280, easing: 'cubic-bezier(0.2, 0.8, 0.2, 1)', fill: 'forwards' });
    }

    const animFormIn = runAnim(formWrap, [
      { opacity: 0, filter: 'blur(6px)', transform: 'translateY(8px)' },
      { opacity: 1, filter: 'blur(0px)', transform: 'translateY(0px)' }
    ], { duration: 300, easing: 'ease-out', fill: 'forwards' });

    const animShellIn = shell ? runAnim(shell, [
      { opacity: 0, transform: 'scale(0.97)' },
      { opacity: 1, transform: 'scale(1)' }
    ], { duration: 300, easing: 'ease-out', fill: 'forwards' }) : null;

    const animFadeTL = runAnim(pieceTL, [{ opacity: 1 }, { opacity: 0 }], { duration: 220, fill: 'forwards' });
    const animFadeBR = runAnim(pieceBR, [{ opacity: 1 }, { opacity: 0 }], { duration: 220, fill: 'forwards' });

    await Promise.all([
      animFormIn ? animFormIn.finished : Promise.resolve(),
      animShellIn ? animShellIn.finished : Promise.resolve(),
      animFadeTL ? animFadeTL.finished : Promise.resolve(),
      animFadeBR ? animFadeBR.finished : Promise.resolve(),
      animEmblemPulse ? animEmblemPulse.finished : Promise.resolve(),
      animHeight ? animHeight.finished : Promise.resolve()
    ]);
  } catch (err) {
    console.error('Animation error:', err);
  } finally {
    // Reset all animations & styles cleanly
    activeAnims.forEach(a => {
      try { a.cancel(); } catch(e) {}
    });
    animElements.forEach(el => {
      try {
        el.getAnimations().forEach(a => a.cancel());
      } catch(e) {}
    });

    pieceTL.style.opacity = '0';
    pieceBR.style.opacity = '0';
    pieceTL.style.transform = '';
    pieceBR.style.transform = '';
    if (emblem) {
      emblem.style.opacity = '0';
      emblem.style.transform = '';
      emblem.style.filter = '';
    }
    if (seam) {
      seam.style.opacity = '0';
      seam.style.transform = '';
    }
    if (flash) {
      flash.style.opacity = '0';
      flash.style.transform = '';
    }
    if (shell) {
      shell.style.opacity = '1';
      shell.style.transform = '';
    }
    if (card) {
      card.style.height = '';
      card.style.boxShadow = '';
    }
    formWrap.style.opacity = '1';
    formWrap.style.filter = '';
    formWrap.style.transform = '';

    isAnimating = false;
  }
}

// === TOGGLE PASSWORD VISIBILITY ===
window.togglePasswordVisibility = function(inputId) {
  const el = document.getElementById(inputId);
  if (!el) return;
  el.type = el.type === 'password' ? 'text' : 'password';
};

// === BANNER MESSAGING ===
function showBanner(msg, type = 'error') {
  const b = document.getElementById('auth-banner');
  if (!b) return;
  b.className = `auth-banner ${type}`;
  b.innerText = msg;
  b.style.display = 'block';
}

function hideBanner() {
  const b = document.getElementById('auth-banner');
  if (!b) return;
  b.style.display = 'none';
  b.innerText = '';
}

// === SUCCESS TRANSITION TO APP ===
async function playSuccessTransition() {
  const flash = document.getElementById('login-trans-flash');
  if (flash) {
    flash.style.willChange = 'opacity';
    flash.animate([
      { opacity: 0 },
      { opacity: 0.45, offset: 0.4 },
      { opacity: 1 }
    ], { duration: 520, easing: 'ease-in-out', fill: 'forwards' });
  }

  const card = document.getElementById('auth-card-wrapper');
  if (card) {
    card.animate([
      { transform: 'scale(1)', opacity: 1 },
      { transform: 'scale(0.96)', opacity: 0 }
    ], { duration: 420, easing: 'ease-out', fill: 'forwards' });
  }

  await new Promise(r => setTimeout(r, 550));
}

// === INITIALIZATION & EVENT LISTENERS ===
document.addEventListener('DOMContentLoaded', () => {
  renderFormText();
  loadDepartments();

  // Mode Switch Button (Link at bottom)
  document.getElementById('btn-switch-auth')?.addEventListener('click', () => {
    triggerPuzzleTransition(!isLoginMode);
  });

  // Language button (KO <-> EN)
  document.getElementById('btn-login-lang')?.addEventListener('click', () => {
    currentLang = currentLang === 'ko' ? 'en' : 'ko';
    localStorage.setItem('argos_lang', currentLang);
    localStorage.setItem('jarvisLang', currentLang);
    renderFormText();
  loadDepartments();
  });

  // === UNIFIED FORM SUBMISSION ===
  document.getElementById('auth-form')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const t = dict[currentLang] || dict.ko;
    const submitBtn = document.getElementById('btn-submit');
    const submitTxt = document.getElementById('txt-submit');

    const username = document.getElementById('auth-username')?.value.trim();
    const password = document.getElementById('auth-password')?.value;

    hideBanner();

    // ----------------------------------------------------
    // CASE A: LOGIN MODE
    // ----------------------------------------------------
    if (isLoginMode) {
      if (!username || !password) {
        showBanner(t.errFillRequired, 'error');
        return;
      }

      if (submitBtn) submitBtn.disabled = true;
      if (submitTxt) submitTxt.textContent = t.btnProcessing;

      try {
        const res = await fetch('/api/auth/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username, password })
        });
        const data = await res.json();

        if (res.ok) {
          if (data.csrfToken) {
            sessionStorage.setItem("argosCsrfToken", data.csrfToken);
            localStorage.setItem("argosCsrfToken", data.csrfToken);
          }
          const userData = data.user || { name: username, username, email: '' };
          if (userData.token) delete userData.token;
          localStorage.removeItem('argos_token');
          sessionStorage.removeItem('argos_token');
          localStorage.setItem('argosUser', JSON.stringify(userData));
          sessionStorage.setItem('argosUser', JSON.stringify(userData));
          localStorage.setItem('jarvisUser', JSON.stringify(userData));
          sessionStorage.setItem('jarvisUser', JSON.stringify(userData));

          await playSuccessTransition();
          window.location.replace('/');
          return;
        } else {
          let msg = data.error || t.errGeneral;
          if (msg.includes('올바르지 않습니다') || msg.includes('Invalid credentials')) {
            msg = t.errInvalidCreds;
          }
          showBanner(msg, 'error');
        }
      } catch (err) {
        showBanner(t.errConnection, 'error');
      } finally {
        if (submitBtn) submitBtn.disabled = false;
        if (submitTxt) submitTxt.textContent = t.btnSignIn;
      }
      return;
    }

    // ----------------------------------------------------
    // CASE B: REGISTER MODE
    // ----------------------------------------------------
    const name = document.getElementById('auth-name')?.value.trim();
    const dept = document.getElementById('auth-dept')?.value.trim();
    const email = document.getElementById('auth-email')?.value.trim();
    const confirmPassword = document.getElementById('auth-confirm-password')?.value;

    if (!username || !name || !password || !confirmPassword) {
      showBanner(t.errFillRequired, 'error');
      return;
    }

    if (!dept) {
      showBanner(t.errDeptRequired || '소속 부서를 선택해주세요', 'error');
      return;
    }

    if (email) {
      const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
      if (!emailRegex.test(email)) {
        showBanner(t.errInvalidEmail || '올바른 이메일 주소를 입력해주세요', 'error');
        return;
      }
    }

    if (username.length < 3) {
      showBanner(t.errUsernameShort, 'error');
      return;
    }

    if (password.length < 8) {
      showBanner(t.errPasswordShort || "비밀번호는 최소 8자 이상이어야 합니다.", 'error');
      return;
    }

    if (password !== confirmPassword) {
      showBanner(t.errPasswordMismatch, 'error');
      return;
    }

    if (submitBtn) submitBtn.disabled = true;
    if (submitTxt) submitTxt.textContent = t.btnProcessing;

    try {
      const res = await fetch('/api/auth/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, name, org: dept, email: email || '', password })
      });
      const data = await res.json();

      if (res.ok) {
        if (data.pending) {
          showBanner('📋 ' + (data.message || t.pendingRegister), 'success');
          var uIn = document.getElementById('auth-username');
          var nIn = document.getElementById('auth-name');
          var pIn = document.getElementById('auth-password');
          var cpIn = document.getElementById('auth-confirm-password');
          if (uIn) uIn.value = '';
          if (nIn) nIn.value = '';
          if (pIn) pIn.value = '';
          if (cpIn) cpIn.value = '';
          setTimeout(function() {
            triggerPuzzleTransition(true);
          }, 3500);
          return;
        }

        if (data.csrfToken) {
          sessionStorage.setItem('argosCsrfToken', data.csrfToken);
          localStorage.setItem('argosCsrfToken', data.csrfToken);
        }
        const userData = data.user || { name, username, email: '' };
        if (userData.token) delete userData.token;
        localStorage.removeItem('argos_token');
        sessionStorage.removeItem('argos_token');
        localStorage.setItem('argosUser', JSON.stringify(userData));
        sessionStorage.setItem('argosUser', JSON.stringify(userData));
        localStorage.setItem('jarvisUser', JSON.stringify(userData));
        sessionStorage.setItem('jarvisUser', JSON.stringify(userData));

        showBanner(t.successRegister, 'success');
        await new Promise(r => setTimeout(r, 650));
        await playSuccessTransition();
        window.location.replace('/');
        return;
      } else {
        let msg = data.error || t.errGeneral;
        showBanner(msg, 'error');
      }
    } catch (err) {
      showBanner(t.errConnection, 'error');
    } finally {
      if (submitBtn) submitBtn.disabled = false;
      if (submitTxt) submitTxt.textContent = t.btnSignUp;
    }
  });

  // Auto-login test parameter (?auto=admin)
  const urlParams = new URLSearchParams(window.location.search);
  if (urlParams.get('auto') === 'admin') {
    const uInput = document.getElementById('auth-username');
    const pInput = document.getElementById('auth-password');
    if (uInput && pInput) {
      uInput.value = 'uy';
      pInput.value = '1234';
      document.getElementById('auth-form')?.requestSubmit();
    }
  }
});
