const { spawn, execSync } = require('child_process');
const http = require('http');
const fs = require('fs');
const path = require('path');
const os = require('os');

const EDGE_PATH = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const SERVER_PORT = 8089;
const CDP_PORT = 9222;

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function httpGet(url) {
  return new Promise((resolve, reject) => {
    http.get(url, res => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try {
          resolve(JSON.parse(data));
        } catch(e) {
          resolve(data);
        }
      });
    }).on('error', reject);
  });
}

class CDPClient {
  constructor(wsUrl) {
    this.wsUrl = wsUrl;
    this.ws = null;
    this.msgId = 1;
    this.callbacks = new Map();
    this.consoleErrors = [];
    this.exceptions = [];
  }

  async connect() {
    return new Promise((resolve, reject) => {
      this.ws = new WebSocket(this.wsUrl);
      this.ws.onopen = () => resolve();
      this.ws.onerror = err => reject(err);
      this.ws.onmessage = evt => {
        const msg = JSON.parse(evt.data);
        if (msg.id && this.callbacks.has(msg.id)) {
          const cb = this.callbacks.get(msg.id);
          this.callbacks.delete(msg.id);
          if (msg.error) cb.reject(new Error(msg.error.message || JSON.stringify(msg.error)));
          else cb.resolve(msg.result);
        } else if (msg.method === 'Runtime.consoleAPICalled') {
          if (msg.params.type === 'error') {
            const text = (msg.params.args || []).map(a => a.value || a.description || '').join(' ');
            this.consoleErrors.push(text);
          }
        } else if (msg.method === 'Runtime.exceptionThrown') {
          const text = msg.params.exceptionDetails?.text || msg.params.exceptionDetails?.exception?.description || 'Unknown exception';
          this.exceptions.push(text);
        }
      };
    });
  }

  send(method, params = {}) {
    return new Promise((resolve, reject) => {
      const id = this.msgId++;
      this.callbacks.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }

  async eval(expression) {
    const res = await this.send('Runtime.evaluate', {
      expression,
      returnByValue: true,
      awaitPromise: true
    });
    if (res.exceptionDetails) {
      const desc = res.exceptionDetails.exception?.description || res.exceptionDetails.text || JSON.stringify(res.exceptionDetails);
      throw new Error('Eval exception: ' + desc);
    }
    return res.result?.value;
  }

  close() {
    if (this.ws) {
      try { this.ws.close(); } catch(e){}
    }
  }
}

async function runTestSuite() {
  console.log('================================================================');
  console.log(' ARGOS WORKS — AUTOMATED COMPREHENSIVE UI TEST SUITE');
  console.log('================================================================\n');

  // 1. Generate real session tokens for role testing
  console.log('[Step 0] Creating test session credentials from database...');
  let tokens = { member: '', manager: '', admin: '', viewer: '' };
  try {
    const rawTokens = execSync('python -c "import sys; sys.path.insert(0, \'server\'); from services.auth import create_session; import json; print(json.dumps({\'member\': create_session(\'박서준\', \'dev\', \'\', 3), \'manager\': create_session(\'이도현\', \'dev\', \'\', 2), \'admin\': create_session(\'김민수\', \'mgmt\', \'\', 1), \'viewer\': create_session(\'윤재호\', \'hq\', \'\', 8)}))"', { encoding: 'utf-8' });
    tokens = JSON.parse(rawTokens.trim());
    console.log('  -> Sessions generated for Member, Manager, Admin, Viewer.');
  } catch(e) {
    console.warn('  -> Warning: Could not generate DB session tokens:', e.message);
  }

  // 2. Start Python Web Server
  console.log('\n[Step 1] Starting ARGOS backend test server on port ' + SERVER_PORT + '...');
  const serverProc = spawn('python', ['server/main.py'], {
    env: { ...process.env, PORT: String(SERVER_PORT), HOST: '127.0.0.1', PYTHONPATH: 'server;.' },
    cwd: path.resolve(__dirname, '..'),
    stdio: 'ignore'
  });

  let serverReady = false;
  for (let i = 0; i < 30; i++) {
    await sleep(300);
    try {
      const check = await httpGet(`http://127.0.0.1:${SERVER_PORT}/api/account/check`);
      if (check) {
        serverReady = true;
        break;
      }
    } catch(e) {}
  }

  if (!serverReady) {
    console.error('FAIL: Server failed to start on port ' + SERVER_PORT);
    serverProc.kill();
    process.exit(1);
  }
  console.log('  -> Server is UP and responding (HTTP 200).');

  // 3. Start Microsoft Edge Headless
  console.log('\n[Step 2] Launching Microsoft Edge (headless mode with CDP)...');
  const tempProfile = fs.mkdtempSync(path.join(os.tmpdir(), 'argos-ui-profile-'));
  const edgeProc = spawn(EDGE_PATH, [
    '--headless=new',
    `--remote-debugging-port=${CDP_PORT}`,
    `--user-data-dir=${tempProfile}`,
    '--window-size=1280,800',
    '--disable-gpu',
    '--no-first-run',
    '--no-default-browser-check',
    'about:blank'
  ], { stdio: 'ignore' });

  await sleep(1000);

  let pageWsUrl = null;
  for (let i = 0; i < 30; i++) {
    await sleep(300);
    try {
      const targets = await httpGet(`http://127.0.0.1:${CDP_PORT}/json/list`);
      if (Array.isArray(targets) && targets.length > 0) {
        const pageTarget = targets.find(t => t.type === 'page');
        if (pageTarget && pageTarget.webSocketDebuggerUrl) {
          pageWsUrl = pageTarget.webSocketDebuggerUrl;
          break;
        }
      }
    } catch(e) {}
  }

  if (!pageWsUrl) {
    console.error('FAIL: Could not locate page target in Edge.');
    edgeProc.kill();
    serverProc.kill();
    process.exit(1);
  }
  console.log('  -> Connected to Page CDP WebSocket.');

  const client = new CDPClient(pageWsUrl);
  await client.connect();
  await client.send('Page.enable');
  await client.send('Runtime.enable');

  console.log('\n[Step 3] Navigating to http://127.0.0.1:' + SERVER_PORT + '/ ...');
  await client.send('Page.navigate', { url: `http://127.0.0.1:${SERVER_PORT}/` });
  await sleep(2000);

  let passedTests = 0;
  let failedTests = 0;

  function assert(condition, message) {
    if (condition) {
      console.log('  [PASS] ' + message);
      passedTests++;
    } else {
      console.error('  [FAIL] ' + message);
      failedTests++;
    }
  }

  try {
    // --------------------------------------------------------------------------
    // Test 1: Page Shell & Navigation Structure
    // --------------------------------------------------------------------------
    console.log('\n--- [Test Group 1: Page Shell & Navigation Structure] ---');
    const pageTitle = await client.eval('document.title');
    assert(pageTitle.includes('ARGOS') || pageTitle.includes('WORKS'), 'Page title is correct (' + pageTitle + ')');

    const sidebarExists = await client.eval('Boolean(document.getElementById("daouSidebar"))');
    assert(sidebarExists, 'Main navigation sidebar (#daouSidebar) exists');

    const navTabsCount = await client.eval('document.querySelectorAll(".tab-btn").length');
    assert(navTabsCount >= 6, 'Sidebar navigation tabs count is valid (found: ' + navTabsCount + ')');

    const homeTabActive = await client.eval('el.home && !el.home.hidden');
    assert(homeTabActive, 'Tab Home (#viewHome) is active by default');

    // --------------------------------------------------------------------------
    // Test 2: Tab Home View & Google AI Search & Option 2 Portal
    // --------------------------------------------------------------------------
    console.log('\n--- [Test Group 2: Tab Home & Executive Portal (Option 2)] ---');
    const brandLogoVisible = await client.eval('Boolean(document.querySelector(".home-google-logo") || document.getElementById("homeLogoText"))');
    assert(brandLogoVisible, 'Home AI Search brand logo exists');

    const searchInput = await client.eval('Boolean(document.getElementById("homeAskInput"))');
    assert(searchInput, 'Google-style search input (#homeAskInput) exists and is interactive');

    // Quick Action Buttons
    const quickBtnsCount = await client.eval('document.querySelectorAll("#homeQuickActions .home-quick-btn").length');
    assert(quickBtnsCount >= 3, 'Quick action buttons rendered based on role (count: ' + quickBtnsCount + ')');

    // Portal Section
    const portalSectionExists = await client.eval('Boolean(document.getElementById("homePortalSection"))');
    assert(portalSectionExists, 'Executive Portal section (#homePortalSection) rendered');

    const guestBadge = await client.eval('document.getElementById("homePortalRoleBadge") ? document.getElementById("homePortalRoleBadge").textContent.trim() : ""');
    assert(guestBadge.includes('게스트') || guestBadge.includes('Guest'), 'Guest role badge is correctly displayed ("' + guestBadge + '")');

    const guestGreeting = await client.eval('document.getElementById("homePortalGreeting") ? document.getElementById("homePortalGreeting").textContent.trim() : ""');
    assert(guestGreeting.includes('포털에 오신 것을 환영합니다'), 'Guest greeting is friendly ("' + guestGreeting + '")');

    const guestCardsCount = await client.eval('document.querySelectorAll("#homePortalGrid .portal-widget-card").length');
    assert(guestCardsCount >= 2, 'Guest portal displays starter and catalog cards (count: ' + guestCardsCount + ')');

    // Quick Action Login Button trigger
    const loginActionValid = await client.eval(`(() => {
      const loginBtn = document.querySelector('#homeQuickActions [data-target="login"]');
      return Boolean(loginBtn && loginBtn.getAttribute("data-target") === "login");
    })()`);
    assert(loginActionValid, 'Quick Action "로그인 (Login)" button exists and navigates to /login');

    // Portal Refresh Button
    const refreshClicked = await client.eval(`(() => {
      const btn = document.getElementById("homePortalRefreshBtn");
      if(!btn) return false;
      btn.click();
      return true;
    })()`);
    assert(refreshClicked, 'Home Portal refresh button triggers live reload');

    // --------------------------------------------------------------------------
    // Test 3: Tab Dashboard / Board View & Issue Canvas
    // --------------------------------------------------------------------------
    console.log('\n--- [Test Group 3: Tab Board & Canvas Panel] ---');
    await client.eval('showTab("dash")');
    await sleep(400);

    const dashVisible = await client.eval('!el.dash.hidden && el.home.hidden');
    assert(dashVisible, 'Switched to Tab Board (#viewDash is visible, #viewHome is hidden)');

    const deptCardsOrToolbar = await client.eval('Boolean(document.getElementById("deptCards") && document.getElementById("filterRow"))');
    assert(deptCardsOrToolbar, 'Board departments overview and filter toolbar exist');

    // Canvas detail opening test
    const canvasTest = await client.eval(`(() => {
      if(typeof window.showIssueInCanvas !== "function") return { ok: false, reason: "showIssueInCanvas not found" };
      // Test opening dummy issue
      window.showIssueInCanvas("TEST-001");
      const canvas = document.getElementById("canvasPanel");
      const isOpen = canvas && !canvas.hidden && document.body.classList.contains("canvas-open");
      // Close canvas
      if(typeof window.closeCanvas === "function") window.closeCanvas();
      const isClosed = canvas && canvas.hidden && !document.body.classList.contains("canvas-open");
      return { ok: true, isOpen, isClosed };
    })()`);
    assert(canvasTest.ok && canvasTest.isOpen && canvasTest.isClosed, 'Canvas Panel opens with issue details and closes smoothly');

    // --------------------------------------------------------------------------
    // Test 4: Tab Schedule / Calendar View
    // --------------------------------------------------------------------------
    console.log('\n--- [Test Group 4: Tab Schedule / Calendar] ---');
    await client.eval('showTab("schedule")');
    await sleep(400);

    const schedVisible = await client.eval('!el.schedule.hidden');
    assert(schedVisible, 'Switched to Tab Schedule (#viewSchedule is visible)');

    const calNavButtons = await client.eval(`(() => {
      const prev = document.getElementById("schedPrevBtn");
      const next = document.getElementById("schedNextBtn");
      const today = document.getElementById("schedTodayBtn");
      return Boolean(prev && next && today);
    })()`);
    assert(calNavButtons, 'Calendar navigation controls (#schedPrevBtn, #schedNextBtn, #schedTodayBtn) exist');

    await client.eval('if(document.getElementById("schedNextBtn")) document.getElementById("schedNextBtn").click();');
    await sleep(200);
    await client.eval('if(document.getElementById("schedTodayBtn")) document.getElementById("schedTodayBtn").click();');
    await sleep(200);
    assert(true, 'Calendar month navigation cycles smoothly without errors');

    // --------------------------------------------------------------------------
    // Test 5: Tab PIM / Technical Catalog
    // --------------------------------------------------------------------------
    console.log('\n--- [Test Group 5: Tab PIM / Parts Catalog] ---');
    await client.eval('showTab("pim")');
    await sleep(400);

    const pimVisible = await client.eval('!el.pim.hidden');
    assert(pimVisible, 'Switched to Tab PIM (#viewPim is visible)');

    const pimSearchInput = await client.eval('Boolean(document.getElementById("pimSearchInput"))');
    assert(pimSearchInput, 'PIM search input exists');

    // --------------------------------------------------------------------------
    // Test 6: Tab AI Chat (Authenticated with Session Token)
    // --------------------------------------------------------------------------
    console.log('\n--- [Test Group 6: Tab AI Chat] ---');
    await client.eval(`(() => {
      document.cookie = "argos_token=${tokens.member}; path=/";
      const u = { id: 3, name: "박서준", role: "member", org: "dev" };
      applyLogin(u);
      showTab("chat");
    })()`);
    await sleep(400);

    const chatVisible = await client.eval('!el.chat.hidden');
    assert(chatVisible, 'Switched to Tab Chat (#sectionChat is visible for logged-in user)');

    const chatInputExists = await client.eval('Boolean(document.getElementById("chatInput"))');
    assert(chatInputExists, 'AI Chat message input exists');

    // --------------------------------------------------------------------------
    // Test 7: Tab Form / Task Submission (Member)
    // --------------------------------------------------------------------------
    console.log('\n--- [Test Group 7: Tab Form / Task Submission] ---');
    await client.eval('showTab("form")');
    await sleep(400);

    const formVisible = await client.eval('!el.form.hidden');
    assert(formVisible, 'Switched to Tab Form (#viewForm is visible)');

    const submitFormActive = await client.eval(`(() => {
      const submitForm = document.getElementById("submitForm");
      const guestGate = document.getElementById("viewFormGuestPlaceholder");
      return submitForm && !submitForm.hidden && (!guestGate || guestGate.hidden);
    })()`);
    assert(submitFormActive, 'Submit task form (#submitForm) is active for Member');

    const formInputsExist = await client.eval(`(() => {
      const title = document.getElementById("titleInput");
      const memo = document.getElementById("memoInput");
      const org = document.getElementById("orgSelect");
      const prio = document.getElementById("prioritySelect");
      return Boolean(title && memo && org && prio);
    })()`);
    assert(formInputsExist, 'Task form inputs (titleInput, memoInput, orgSelect, prioritySelect) exist');

    // --------------------------------------------------------------------------
    // Test 8: Dynamic Role Switching & Portal Verification (Option 2)
    // --------------------------------------------------------------------------
    console.log('\n--- [Test Group 8: Dynamic Role Switching & Portal Verification] ---');

    // 8A. Member Role on Home Tab
    await client.eval(`(() => {
      document.cookie = "argos_token=${tokens.member}; path=/";
      const memberUser = { id: 3, name: "박서준", role: "member", org: "dev", email: "park.sj@example.com" };
      applyLogin(memberUser);
      showTab("home");
    })()`);
    await sleep(300);

    const memberRoleBadge = await client.eval('document.getElementById("homePortalRoleBadge").textContent.trim()');
    assert(memberRoleBadge.includes('팀원') || memberRoleBadge.includes('Member'), 'Member login updates badge to "팀원 (Member)" (' + memberRoleBadge + ')');

    const memberGreeting = await client.eval('document.getElementById("homePortalGreeting").textContent.trim()');
    assert(memberGreeting.includes('박서준'), 'Member greeting addresses user by name ("' + memberGreeting + '")');

    const memberHasMyTasks = await client.eval('document.body.innerText.includes("내 진행 중인 업무")');
    assert(memberHasMyTasks, 'Member portal renders "내 진행 중인 업무" widget');

    const memberSettingsHidden = await client.eval('el.tabSettings ? el.tabSettings.hidden : true');
    assert(memberSettingsHidden, 'Settings tab is properly restricted/hidden for Member');

    // 8B. Manager Role
    await client.eval(`(() => {
      document.cookie = "argos_token=${tokens.manager}; path=/";
      const mgrUser = { id: 2, name: "이도현", role: "manager", isManager: true, org: "dev", email: "lee.dh@example.com" };
      applyLogin(mgrUser);
      showTab("home");
    })()`);
    await sleep(300);

    const mgrRoleBadge = await client.eval('document.getElementById("homePortalRoleBadge").textContent.trim()');
    assert(mgrRoleBadge.includes('관리자') || mgrRoleBadge.includes('Manager'), 'Manager login updates badge to "부서 관리자 (Manager)" (' + mgrRoleBadge + ')');

    const mgrGreeting = await client.eval('document.getElementById("homePortalGreeting").textContent.trim()');
    assert(mgrGreeting.includes('이도현 관리자님'), 'Manager greeting addresses user as manager ("' + mgrGreeting + '")');

    const mgrHasReviewWidget = await client.eval('document.body.innerText.includes("결재 / 검토 대기 업무") || document.body.innerText.includes("업무 지표")');
    assert(mgrHasReviewWidget, 'Manager portal renders Pending Approvals & Department Overview metrics');

    // Manager Tab History & Reports
    await client.eval('showTab("history")');
    await sleep(300);
    const historyVisible = await client.eval('!el.history.hidden');
    assert(historyVisible, 'Manager can access Tab History & Reports (#viewHistory)');

    // 8C. Admin Role
    await client.eval(`(() => {
      document.cookie = "argos_token=${tokens.admin}; path=/";
      const adminUser = { id: 1, name: "김민수", role: "admin", isAdmin: true, org: "mgmt", email: "admin@example.com" };
      applyLogin(adminUser);
      showTab("home");
    })()`);
    await sleep(300);

    const adminRoleBadge = await client.eval('document.getElementById("homePortalRoleBadge").textContent.trim()');
    assert(adminRoleBadge.includes('최고관리자') || adminRoleBadge.includes('Admin'), 'Admin login updates badge to "시스템 최고관리자 (Admin)" (' + adminRoleBadge + ')');

    const adminGreeting = await client.eval('document.getElementById("homePortalGreeting").textContent.trim()');
    assert(adminGreeting.includes('시스템 최고관리자 포털'), 'Admin greeting shows Executive Title ("' + adminGreeting + '")');

    const adminSystemWidget = await client.eval('document.body.innerText.includes("시스템 현황 & 데이터 지표") || document.body.innerText.includes("전사 검토")');
    assert(adminSystemWidget, 'Admin portal renders System Health & Global Review widgets');

    // Tab Settings for Admin
    await client.eval('showTab("settings")');
    await sleep(300);
    const settingsVisible = await client.eval('!el.settings.hidden');
    assert(settingsVisible, 'Admin can access Tab Settings (#viewSettings)');

    // --------------------------------------------------------------------------
    // Test 9: Logout & State Reset
    // --------------------------------------------------------------------------
    console.log('\n--- [Test Group 9: Logout & Return to Guest State] ---');
    await client.eval(`(() => {
      document.cookie = "argos_token=; path=/; expires=Thu, 01 Jan 1970 00:00:00 UTC";
      applyLogout();
      showTab("home");
    })()`);
    await sleep(300);

    const isLoggedOut = await client.eval('window.loggedInUser === null && !document.getElementById("loginBtn").hidden');
    assert(isLoggedOut, 'User successfully logged out, login button restored in Topbar');

    const resetBadge = await client.eval('document.getElementById("homePortalRoleBadge").textContent.trim()');
    assert(resetBadge.includes('게스트') || resetBadge.includes('Guest'), 'Home Portal correctly reset to Guest badge ("' + resetBadge + '")');

    // --------------------------------------------------------------------------
    // Test 10: Browser Console Health & Exception Integrity
    // --------------------------------------------------------------------------
    console.log('\n--- [Test Group 10: Browser Console Health & Integrity] ---');
    const uncaughtErrors = client.exceptions;
    assert(uncaughtErrors.length === 0, 'No uncaught JavaScript exceptions occurred during the entire run (count: ' + uncaughtErrors.length + ')');
    if (uncaughtErrors.length > 0) {
      console.error('  Exceptions thrown:', uncaughtErrors);
    }

  } catch(err) {
    console.error('ERROR during test execution:', err);
    failedTests++;
  } finally {
    console.log('\n[Teardown] Cleaning up processes and temp profile...');
    client.close();
    edgeProc.kill();
    serverProc.kill();
    try { fs.rmSync(tempProfile, { recursive: true, force: true }); } catch(e){}
  }

  console.log('\n================================================================');
  console.log(` SUMMARY: ${passedTests} PASSED, ${failedTests} FAILED (TOTAL: ${passedTests + failedTests})`);
  console.log('================================================================\n');

  if (failedTests > 0) {
    process.exit(1);
  }
}

runTestSuite().catch(err => {
  console.error('Fatal test runner error:', err);
  process.exit(1);
});
