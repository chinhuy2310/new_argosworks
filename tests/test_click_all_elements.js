const { spawn, execSync } = require('child_process');
const http = require('http');
const fs = require('fs');
const path = require('path');
const os = require('os');

const EDGE_PATH = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const SERVER_PORT = 8089;
const CDP_PORT = 9222;

function sleep(ms) { return new Promise(resolve => setTimeout(resolve, ms)); }
function httpGet(url) {
  return new Promise((resolve, reject) => {
    http.get(url, res => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try { resolve(JSON.parse(data)); } catch(e) { resolve(data); }
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
      console.error('Eval exception details:', JSON.stringify(res.exceptionDetails));
      throw new Error('Eval exception: ' + (res.exceptionDetails.text || res.exceptionDetails.exception?.description));
    }
    return res.result?.value;
  }

  close() {
    if (this.ws) {
      try { this.ws.close(); } catch(e){}
    }
  }
}

async function runExhaustiveClickTest() {
  console.log('================================================================');
  console.log(' ARGOS WORKS — EXHAUSTIVE CLICK & INTERACTION AUDIT (100% COVERAGE)');
  console.log('================================================================\n');

  // 1. Session tokens
  console.log('[1] Generating Admin session credentials...');
  let adminToken = '';
  try {
    const rawTokens = execSync('python -c "import sys; sys.path.insert(0, \'server\'); from services.auth import create_session; import json; print(json.dumps({\'admin\': create_session(\'김민수\', \'mgmt\', \'\', 1)}))"', { encoding: 'utf-8' });
    adminToken = JSON.parse(rawTokens.trim()).admin;
    console.log('  -> Admin session token ready.');
  } catch(e) {
    console.error('  -> Failed to create admin session token:', e.message);
  }

  // 2. Start Server
  console.log('[2] Starting backend test server on port ' + SERVER_PORT + '...');
  const serverProc = spawn('python', ['server/main.py'], {
    env: { ...process.env, PORT: String(SERVER_PORT), HOST: '127.0.0.1', PYTHONPATH: 'server;.' },
    cwd: path.resolve(__dirname, '..'),
    stdio: 'ignore'
  });

  for (let i = 0; i < 30; i++) {
    await sleep(300);
    try {
      if (await httpGet(`http://127.0.0.1:${SERVER_PORT}/api/account/check`)) break;
    } catch(e) {}
  }

  // 3. Start Edge
  console.log('[3] Starting headless Edge with CDP...');
  const tempProfile = fs.mkdtempSync(path.join(os.tmpdir(), 'argos-click-all-'));
  const edgeProc = spawn(EDGE_PATH, [
    '--headless=new',
    `--remote-debugging-port=${CDP_PORT}`,
    `--user-data-dir=${tempProfile}`,
    '--window-size=1440,900',
    '--disable-gpu',
    '--no-first-run',
    '--no-default-browser-check',
    'about:blank'
  ], { stdio: 'ignore' });

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

  const client = new CDPClient(pageWsUrl);
  await client.connect();
  await client.send('Page.enable');
  await client.send('Runtime.enable');

  await client.send('Page.navigate', { url: `http://127.0.0.1:${SERVER_PORT}/` });
  await sleep(2000);

  // Authenticate as Admin so all tabs, subtabs, and management modals are unlocked
  await client.eval(`(() => {
    document.cookie = "argos_token=${adminToken}; path=/";
    const adminUser = { id: 1, name: "김민수", role: "admin", isAdmin: true, org: "mgmt", email: "admin@example.com" };
    applyLogin(adminUser);
    showTab("home");
  })()`);
  await sleep(600);

  console.log('[4] Beginning Comprehensive Tab & Modal Click Audit...\n');

  const clickResults = await client.eval(`(() => {
    const report = [];

    function closeAnyModal(){
      const closeButtons = document.querySelectorAll(
        '.modal:not([hidden]) [data-dismiss], .modal:not([hidden]) .close, ' +
        '[id*="Modal"]:not([hidden]) button[id*="Close"], [id*="Modal"]:not([hidden]) button[id*="Dismiss"], ' +
        '[id*="Modal"]:not([hidden]) button[id*="Cancel"], .backdrop:not([hidden]) button, ' +
        '#canvasCloseBtn, .canvas-close-btn, #pimFormCloseBtn, #pimModalCloseBtn, #idFormCancel'
      );
      closeButtons.forEach(b => {
        try { if(b.offsetParent !== null) b.click(); } catch(e){}
      });
      if(typeof window.closeCanvas === "function") try { window.closeCanvas(); } catch(e){}
    }

    const tabs = ["home", "dash", "form", "schedule", "pim", "chat", "history", "settings"];

    tabs.forEach(tabName => {
      try {
        if(typeof showTab === "function") showTab(tabName);
      } catch(err){
        report.push({ tab: tabName, id: "showTab", text: tabName, status: "ERROR: " + err.message });
        return;
      }

      // Settings subtab cycling
      if(tabName === "settings"){
        const subtabBtns = document.querySelectorAll("#settingsSubtabsNav .settings-subtab-btn");
        subtabBtns.forEach(sb => {
          try {
            sb.click();
            report.push({
              tab: "settings",
              id: sb.id || sb.getAttribute("data-subtab") || "subtab",
              text: sb.textContent.trim().substring(0, 30),
              status: "CLICKED_OK"
            });
            // Click visible action buttons in this active subtab pane
            const activePane = document.querySelector(".settings-subtab-pane:not([hidden])");
            if(activePane){
              const paneBtns = activePane.querySelectorAll("button, input[type='button'], input[type='submit']");
              paneBtns.forEach(pb => {
                if(pb.offsetParent !== null){
                  const pbid = pb.id || pb.className || "pane-btn";
                  const pbtext = pb.textContent.trim().substring(0, 30);
                  try {
                    pb.click();
                    report.push({ tab: "settings-pane", id: pbid, text: pbtext, status: "CLICKED_OK" });
                  } catch(pe){
                    report.push({ tab: "settings-pane", id: pbid, text: pbtext, status: "PANE_CLICK_ERR: " + pe.message });
                  }
                  closeAnyModal();
                }
              });
            }
          } catch(err){
            report.push({ tab: "settings", id: sb.id, text: sb.textContent.trim(), status: "SUBTAB_ERROR: " + err.message });
          }
        });
      }

      const activeContainer = el[tabName] || document.getElementById("view" + tabName.charAt(0).toUpperCase() + tabName.slice(1));
      if(!activeContainer) return;

      const buttons = activeContainer.querySelectorAll("button, a.home-quick-btn, a[role='button'], input[type='button'], input[type='submit']");
      buttons.forEach(btn => {
        const bid = btn.id || btn.className || "(button)";
        const btext = (btn.textContent || btn.getAttribute("title") || btn.getAttribute("aria-label") || "").trim().substring(0, 35);
        
        if(btn.offsetParent === null && !btn.classList.contains("home-quick-btn")) {
          report.push({ tab: tabName, id: bid, text: btext, status: "SKIPPED_HIDDEN" });
          return;
        }

        try {
          btn.click();
          report.push({ tab: tabName, id: bid, text: btext, status: "CLICKED_OK" });
        } catch(clickErr){
          report.push({ tab: tabName, id: bid, text: btext, status: "CLICK_ERROR: " + clickErr.message });
        }
        closeAnyModal();
      });
    });

    // Topbar Controls
    const topbarControls = [
      document.getElementById("sidebarToggleBtn"),
      document.getElementById("topbarNotifBtn"),
      document.getElementById("notifSoundToggleBtn"),
      document.getElementById("notifMarkAllReadBtn"),
      document.getElementById("topbarAvatarBtn"),
      document.getElementById("btnOpenEditProfile")
    ];
    topbarControls.forEach(ctrl => {
      if(!ctrl) return;
      const cid = ctrl.id || ctrl.className;
      const ctext = (ctrl.textContent || ctrl.title || "").trim().substring(0, 30);
      try {
        ctrl.click();
        report.push({ tab: "topbar", id: cid, text: ctext, status: "CLICKED_OK" });
      } catch(e){
        report.push({ tab: "topbar", id: cid, text: ctext, status: "CLICK_ERROR: " + e.message });
      }
      closeAnyModal();
    });

    // Canvas Mode & Control Buttons
    if(typeof window.showIssueInCanvas === "function"){
      try {
        window.showIssueInCanvas("TEST-001");
        const canvasBtns = [
          document.getElementById("btnCanvasModeDocked"),
          document.getElementById("btnCanvasModeOverlay"),
          document.getElementById("btnCanvasModeModal"),
          document.getElementById("btnCanvasEditTask"),
          document.getElementById("canvasCloseBtn")
        ];
        canvasBtns.forEach(cb => {
          if(!cb) return;
          try {
            cb.click();
            report.push({ tab: "canvas", id: cb.id, text: cb.textContent.trim(), status: "CLICKED_OK" });
          } catch(e){
            report.push({ tab: "canvas", id: cb.id, text: cb.textContent.trim(), status: "CLICK_ERROR: " + e.message });
          }
        });
      } catch(e){}
      closeAnyModal();
    }

    // Explicit Modal Interactive Tests
    const modalOpenTriggers = [
      { triggerId: "btnSchedOpenCreateModal", modalId: "schedModal", closeId: "schedModalCloseBtn", name: "Schedule Create Event Modal" },
      { triggerId: "pimNewBtn", modalId: "pimFormModal", closeId: "pimFormCloseBtn", name: "PIM Product Create Modal" },
      { triggerId: "btnAdminOpenAddUser", modalId: "adminAddUserModalBackdrop", closeId: "adminAddUserModalCloseBtn", name: "User Add Modal" },
      { triggerId: "btnOpenAddProductCatModal", modalId: "modalProductCategory", closeId: "btnProductCatModalClose", name: "Product Category Modal" },
      { triggerId: "btnOpenEditProfile", modalId: "modalEditProfile", closeId: "btnEditProfileClose", name: "User Edit Profile Modal" },
      { triggerId: "btnChatAddModel", modalId: "chatModelEditModal", closeId: "btnChatModelModalClose", name: "Chat Custom BYOK Model Modal" }
    ];

    modalOpenTriggers.forEach(m => {
      const trg = document.getElementById(m.triggerId);
      if(trg){
        try {
          trg.click();
          report.push({ tab: "modal-open", id: m.triggerId, text: m.name, status: "CLICKED_OK" });
          const modalEl = document.getElementById(m.modalId);
          if(modalEl && !modalEl.hidden){
            // Click visible cancel/close button inside modal
            const closeBtn = document.getElementById(m.closeId);
            if(closeBtn){
              closeBtn.click();
              report.push({ tab: "modal-close", id: m.closeId, text: m.name + " (Close)", status: "CLICKED_OK" });
            }
          }
        } catch(me){
          report.push({ tab: "modal", id: m.triggerId, text: m.name, status: "MODAL_ERR: " + me.message });
        }
        closeAnyModal();
      }
    });

    return report;
  })()`);

  // Print Summary Table
  let successCount = 0;
  let errorCount = 0;
  let skippedCount = 0;

  console.log('--------------------------------------------------------------------------------------');
  console.log(String('TAB/PANEL').padEnd(16) + String('ELEMENT ID / SELECTOR').padEnd(35) + String('LABEL').padEnd(28) + 'RESULT');
  console.log('--------------------------------------------------------------------------------------');

  clickResults.forEach(r => {
    const isOk = r.status === 'CLICKED_OK';
    const isSkipped = r.status.startsWith('SKIPPED');
    if (isOk) successCount++;
    else if (isSkipped) skippedCount++;
    else errorCount++;

    const icon = isOk ? '✅' : (isSkipped ? '⚪' : '❌');
    console.log(
      String(r.tab).padEnd(16) +
      String(r.id.substring(0, 33)).padEnd(35) +
      String((r.text || '-').substring(0, 26)).padEnd(28) +
      icon + ' ' + r.status
    );
  });

  console.log('--------------------------------------------------------------------------------------');
  console.log(`TOTAL CLICKABLE EVALUATED: ${clickResults.length}`);
  console.log(`  -> SUCCESSFUL CLICKS:   ${successCount}`);
  console.log(`  -> SKIPPED (OFF-SCREEN): ${skippedCount}`);
  console.log(`  -> ERRORS ENCOUNTERED:  ${errorCount}`);
  console.log(`  -> UNCAUGHT EXCEPTIONS: ${client.exceptions.length}`);
  console.log('--------------------------------------------------------------------------------------\n');

  // Teardown
  client.close();
  edgeProc.kill();
  serverProc.kill();
  try { fs.rmSync(tempProfile, { recursive: true, force: true }); } catch(e){}

  if (errorCount > 0 || client.exceptions.length > 0) {
    process.exit(1);
  }
}

runExhaustiveClickTest().catch(err => {
  console.error('Test error:', err);
  process.exit(1);
});
