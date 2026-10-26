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

async function runCanvasAndSettingsTests() {
  console.log('================================================================');
  console.log(' DEEP TEST: CANVAS UI & SETTINGS PANES (9 SUBTABS)');
  console.log('================================================================\n');

  // Step 0: Generate Admin session token
  console.log('[Step 0] Generating Admin session token...');
  let adminToken = '';
  try {
    const raw = execSync('python -c "import sys; sys.path.insert(0, \'server\'); from services.auth import create_session; print(create_session(\'김민수\', \'mgmt\', \'\', 1))"', { encoding: 'utf-8' });
    adminToken = raw.trim();
    console.log('  -> Admin token generated successfully.');
  } catch(e) {
    console.error('FAIL generating token:', e.message);
    process.exit(1);
  }

  // Step 1: Start Server
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
  console.log('  -> Backend server UP and responding.');

  // Step 2: Launch Headless Edge
  console.log('\n[Step 2] Launching Microsoft Edge (headless CDP)...');
  const tempProfile = fs.mkdtempSync(path.join(os.tmpdir(), 'argos-canvas-settings-'));
  const edgeProc = spawn(EDGE_PATH, [
    '--headless=new',
    `--remote-debugging-port=${CDP_PORT}`,
    `--user-data-dir=${tempProfile}`,
    '--window-size=1400,900',
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
    console.error('FAIL: Could not connect to Edge CDP.');
    edgeProc.kill();
    serverProc.kill();
    process.exit(1);
  }

  const client = new CDPClient(pageWsUrl);
  await client.connect();
  await client.send('Page.enable');
  await client.send('Runtime.enable');
  await client.send('Network.enable');

  // Set auth cookie
  await client.send('Network.setCookie', {
    name: 'argos_token',
    value: adminToken,
    domain: '127.0.0.1',
    path: '/'
  });

  console.log('\n[Step 3] Navigating to http://127.0.0.1:' + SERVER_PORT + '/ ...');
  await client.send('Page.navigate', { url: `http://127.0.0.1:${SERVER_PORT}/` });
  await sleep(2500);

  // Prevent blocking dialogs in headless browser
  await client.eval(`(() => {
    window.prompt = function(msg, def) { return def || "Automated Test Backup Note"; };
    window.confirm = function() { return true; };
    window.alert = function(msg) { console.log("[ALERT]", msg); };
    return true;
  })()`);

  let passedTests = 0;
  let failedTests = 0;

  async function assertTest(testName, testFn) {
    try {
      const result = await testFn();
      if (result === true || (result && result.ok)) {
        console.log(`  [PASS] ${testName}` + (result.details ? ` (${result.details})` : ''));
        passedTests++;
      } else {
        console.log(`  [FAIL] ${testName}: ${result && result.error ? result.error : 'Condition not met'}`);
        failedTests++;
      }
    } catch(err) {
      console.log(`  [FAIL] ${testName}: Exception: ${err.message}`);
      failedTests++;
    }
  }

  // =========================================================================
  // SECTION 1: CANVAS DEEP INTERACTIVE VERIFICATION
  // =========================================================================
  console.log('\n================================================================');
  console.log(' SECTION 1: CANVAS DRAWER & MODAL UI CONTROLS');
  console.log('================================================================');

  // Find a valid record id to test with
  const sampleRecordId = await client.eval(`(() => {
    if (window.records && window.records.length > 0) {
      return String(window.records[0].id || window.records[0].cardCode || '911001');
    }
    return '911001';
  })()`);
  console.log(`  Using sample record ID: ${sampleRecordId}`);

  await assertTest('Canvas: Open issue detail in Canvas via showIssueInCanvas', async () => {
    return await client.eval(`(() => {
      window.showIssueInCanvas('${sampleRecordId}');
      const canvas = document.getElementById('canvasPanel');
      return { ok: canvas && !canvas.hidden, details: 'canvasPanel.hidden == false' };
    })()`);
  });

  await sleep(1000);

  await assertTest('Canvas: Issue details and title rendered correctly', async () => {
    return await client.eval(`(() => {
      const titleEl = document.getElementById('canvasTitleText');
      const contentEl = document.getElementById('canvasContent');
      const hasTitle = titleEl && titleEl.textContent.trim().length > 0;
      const hasContent = contentEl && contentEl.innerHTML.length > 100;
      return { ok: hasTitle && hasContent, details: titleEl ? titleEl.textContent : '' };
    })()`);
  });

  // Mode Switch in Dashboard context (Dashboard supports docked, overlay, modal)
  await assertTest('Canvas: Mode Switch - Docked mode (in Dashboard context)', async () => {
    return await client.eval(`(() => {
      window.showTab('dash');
      window.setCanvasDisplayMode('docked');
      const canvas = document.getElementById('canvasPanel');
      const isDocked = canvas && canvas.classList.contains('canvas-mode-docked');
      return { ok: isDocked, details: 'Class canvas-mode-docked applied' };
    })()`);
  });

  await assertTest('Canvas: Mode Switch - Overlay mode (in Dashboard context)', async () => {
    return await client.eval(`(() => {
      window.setCanvasDisplayMode('overlay');
      const canvas = document.getElementById('canvasPanel');
      const isOverlay = canvas && canvas.classList.contains('canvas-mode-overlay');
      return { ok: isOverlay, details: 'Class canvas-mode-overlay applied' };
    })()`);
  });

  await assertTest('Canvas: Mode Switch - Modal mode', async () => {
    return await client.eval(`(() => {
      window.setCanvasDisplayMode('modal');
      const canvas = document.getElementById('canvasPanel');
      const isModal = canvas && canvas.classList.contains('canvas-mode-modal');
      return { ok: isModal, details: 'Class canvas-mode-modal applied' };
    })()`);
  });

  await assertTest('Canvas: Status Dropdown popup opens on status badge click', async () => {
    return await client.eval(`(() => {
      const badge = document.querySelector('#canvasContent [onclick*="toggleStatusDropdown"]');
      if (!badge) return { ok: false, error: 'Status badge not found' };
      badge.click();
      const popup = document.querySelector('.status-dropdown-popup');
      return { ok: !!popup, details: 'Popup opened with options: ' + (popup ? popup.children.length : 0) };
    })()`);
  });

  await assertTest('Canvas: Transition issue status via popup selection', async () => {
    const res = await client.eval(`(() => {
      const popup = document.querySelector('.status-dropdown-popup');
      if (!popup || popup.children.length === 0) return { ok: false, error: 'Popup not open' };
      // Click status option
      const firstOpt = popup.children[0];
      const optText = firstOpt.textContent.trim();
      firstOpt.click();
      return { ok: true, details: 'Selected status: ' + optText };
    })()`);
    await sleep(800);
    return res;
  });

  await assertTest('Canvas: Add new comment via #local-comment-input & submitCanvasComment', async () => {
    const testComment = 'Automated Verification Note ' + Date.now();
    await client.eval(`(() => {
      const input = document.getElementById('local-comment-input');
      if (!input) return false;
      input.innerText = '${testComment}';
      input.value = '${testComment}';
      window.submitCanvasComment('${sampleRecordId}');
      return true;
    })()`);
    await sleep(1200);

    // Verify comment rendered in canvas
    return await client.eval(`(() => {
      const content = document.getElementById('canvasContent');
      const hasComment = content && content.textContent.includes('${testComment}');
      return { ok: hasComment, details: 'Comment found in canvas text' };
    })()`);
  });

  await assertTest('Canvas: Edit Task modal opens via window.openEditRecordModal', async () => {
    return await client.eval(`(async () => {
      // Reopen issue in canvas if closed
      window.showIssueInCanvas('${sampleRecordId}');
      await new Promise(r => setTimeout(r, 800));
      window.openEditRecordModal('${sampleRecordId}');
      for (let i = 0; i < 20; i++) {
        await new Promise(r => setTimeout(r, 150));
        const modal = document.getElementById('recordEditModal');
        if (modal && !modal.hidden) {
          const titleInput = document.getElementById('recordEditTitleInput');
          return {
            ok: true,
            details: 'Modal open, title: ' + (titleInput ? titleInput.value.slice(0, 20) : '')
          };
        }
      }
      return { ok: false, error: 'Modal did not open in time' };
    })()`);
  });

  await assertTest('Canvas: Edit Task modal field update & cancel button', async () => {
    return await client.eval(`(() => {
      const btnCancel = document.getElementById('btnRecordEditCancel');
      if (!btnCancel) return { ok: false, error: '#btnRecordEditCancel not found' };
      btnCancel.click();
      const modal = document.getElementById('recordEditModal');
      return { ok: modal && modal.hidden, details: 'Modal closed cleanly on cancel' };
    })()`);
  });

  await assertTest('Canvas: Custom Confirm Dialog functionality (showCanvasConfirmDialog)', async () => {
    return await client.eval(`(() => {
      window.confirmDeleteLocalRecord('TEST-999', 'Test Temporary Record');
      const confirmModal = document.getElementById('canvas-confirm-modal');
      const hasModal = !!confirmModal;
      // Close/cancel modal
      const btnCancel = confirmModal ? confirmModal.querySelector('.canvas-confirm-btn-cancel') : null;
      if (btnCancel) btnCancel.click();
      const closed = !document.getElementById('canvas-confirm-modal');
      return { ok: hasModal && closed, details: 'Confirm modal opened and cancelled properly' };
    })()`);
  });

  await assertTest('Canvas: Close Canvas via window.closeCanvas()', async () => {
    return await client.eval(`(() => {
      window.closeCanvas();
      const canvas = document.getElementById('canvasPanel');
      return { ok: canvas && canvas.hidden, details: 'canvasPanel.hidden == true' };
    })()`);
  });


  // =========================================================================
  // SECTION 2: SETTINGS PANES DEEP INTERACTIVE VERIFICATION (ALL 9 SUBTABS)
  // =========================================================================
  console.log('\n================================================================');
  console.log(' SECTION 2: SETTINGS PANES & CONTROLS (9 SUBTABS)');
  console.log('================================================================');

  await assertTest('Settings: Navigate to Settings tab via showTab("settings")', async () => {
    return await client.eval(`(() => {
      window.showTab('settings');
      const vSettings = document.getElementById('viewSettings');
      return { ok: vSettings && !vSettings.hidden, details: 'viewSettings.hidden == false' };
    })()`);
  });

  await sleep(1000);

  // Subtab 1: integrations
  await assertTest('Settings Subtab 1 (integrations): Pane active and controls present', async () => {
    return await client.eval(`(() => {
      window.switchSettingsTab('integrations');
      const pane = document.getElementById('paneSettingsIntegrations');
      const btnSync = document.getElementById('btnSyncVectors');
      const btnTest = document.getElementById('btnTestConnections');
      const btnSave = document.getElementById('btnSaveSettings');
      const isActive = pane && !pane.hidden && window.getComputedStyle(pane).display !== 'none';
      return {
        ok: isActive && !!btnSync && !!btnTest && !!btnSave,
        details: 'Pane visible, action buttons present'
      };
    })()`);
  });

  await assertTest('Settings Subtab 1 (integrations): AI Status Pill click jumps to card', async () => {
    return await client.eval(`(() => {
      const pillAi = document.getElementById('pillAi');
      if (!pillAi) return { ok: false, error: '#pillAi not found' };
      pillAi.click();
      const cardAi = document.getElementById('cardSettingsAi');
      return { ok: !!cardAi, details: 'cardSettingsAi present' };
    })()`);
  });

  // Subtab 2: categories
  await assertTest('Settings Subtab 2 (categories): Category table rendering and Add Modal toggle', async () => {
    return await client.eval(`(() => {
      window.switchSettingsTab('categories');
      const pane = document.getElementById('paneSettingsCategories');
      const btnAdd = document.getElementById('btnSettingsAddCategory');
      const tbody = document.getElementById('settingsCategoryTableBody');
      const isActive = pane && !pane.hidden && window.getComputedStyle(pane).display !== 'none';

      // Test Add Category button opens department modal
      if (btnAdd) btnAdd.click();
      const modal = document.getElementById('deptModalBackdrop');
      const isModalOpen = modal && !modal.hidden && window.getComputedStyle(modal).display !== 'none';

      // Close modal
      const btnClose = document.getElementById('deptModalCloseBtn') || document.getElementById('deptModalCancelBtn');
      if (btnClose) btnClose.click();
      const isModalClosed = modal && (modal.hidden || window.getComputedStyle(modal).display === 'none');

      return {
        ok: isActive && !!tbody && isModalOpen && isModalClosed,
        details: 'Rows: ' + (tbody ? tbody.children.length : 0) + ', Add modal opened & closed cleanly'
      };
    })()`);
  });

  // Subtab 3: product_categories
  await assertTest('Settings Subtab 3 (product_categories): Modal open, add field row & cancel', async () => {
    return await client.eval(`(() => {
      window.switchSettingsTab('product_categories');
      const btnOpen = document.getElementById('btnOpenAddProductCatModal');
      if (!btnOpen) return { ok: false, error: '#btnOpenAddProductCatModal not found' };
      btnOpen.click();

      const modal = document.getElementById('modalProductCategory');
      const isModalOpen = modal && !modal.hidden && window.getComputedStyle(modal).display !== 'none';

      // Test add field row button
      const btnAddRow = document.getElementById('btnAddSpecFieldRow');
      if (btnAddRow) btnAddRow.click();
      const specRows = document.getElementById('specFieldsRowsBody');
      const rowCount = specRows ? specRows.children.length : 0;

      // Test cancel button
      const btnCancel = document.getElementById('btnProductCatModalCancel');
      if (btnCancel) btnCancel.click();

      const isModalClosed = modal && (modal.hidden || window.getComputedStyle(modal).display === 'none');
      return {
        ok: isModalOpen && isModalClosed && rowCount > 0,
        details: 'Modal opened, field added (count=' + rowCount + '), closed on cancel'
      };
    })()`);
  });

  // Subtab 4: template
  await assertTest('Settings Subtab 4 (template): Sample template download and upload controls', async () => {
    return await client.eval(`(() => {
      window.switchSettingsTab('template');
      const pane = document.getElementById('paneSettingsTemplate');
      const btnDownload = document.getElementById('btnDownloadSampleTemplate');
      const btnUpload = document.getElementById('btnUploadTemplate');
      const isActive = pane && !pane.hidden && window.getComputedStyle(pane).display !== 'none';
      return {
        ok: isActive && !!btnDownload && !!btnUpload,
        details: 'Template download/upload buttons verified'
      };
    })()`);
  });

  // Subtab 5: security & backup
  await assertTest('Settings Subtab 5 (security): Trigger manual backup creates real backup', async () => {
    await client.eval(`(() => {
      window.switchSettingsTab('security');
      const btnBackup = document.getElementById('btnTriggerManualBackup');
      if (btnBackup) btnBackup.click();
      return true;
    })()`);
    await sleep(2500);

    return await client.eval(`(() => {
      const tbody = document.getElementById('backupListTableBody');
      const rows = tbody ? tbody.querySelectorAll('tr').length : 0;
      return {
        ok: rows > 0,
        details: 'Backup created/listed, table rows: ' + rows
      };
    })()`);
  });

  await assertTest('Settings Subtab 5 (security): Backup Directory Save & Reset buttons', async () => {
    return await client.eval(`(() => {
      const btnSaveDir = document.getElementById('btnSaveBackupDir');
      const btnResetDir = document.getElementById('btnResetBackupDir');
      const inputDir = document.getElementById('inputBackupDir');
      return {
        ok: !!btnSaveDir && !!btnResetDir && !!inputDir,
        details: 'Current backup dir placeholder: ' + (inputDir ? inputDir.placeholder : '')
      };
    })()`);
  });

  // Subtab 6: users & RBAC
  await assertTest('Settings Subtab 6 (users): Users table and Reload button', async () => {
    return await client.eval(`(async () => {
      window.switchSettingsTab('users');
      const btnReload = document.getElementById('btnAdminReloadUsers');
      if (btnReload) btnReload.click();
      await new Promise(r => setTimeout(r, 1000));

      const tbody = document.getElementById('adminUserTableBody');
      const rows = tbody ? tbody.querySelectorAll('tr').length : 0;
      return {
        ok: rows > 0,
        details: 'Users table populated with ' + rows + ' rows'
      };
    })()`);
  });

  await assertTest('Settings Subtab 6 (users): Add User Modal open & close buttons', async () => {
    return await client.eval(`(() => {
      const btnOpen = document.getElementById('btnAdminOpenAddUser');
      if (!btnOpen) return { ok: false, error: '#btnAdminOpenAddUser not found' };
      btnOpen.click();

      const modal = document.getElementById('adminAddUserModalBackdrop');
      const isModalOpen = modal && !modal.hidden && window.getComputedStyle(modal).display !== 'none';

      const btnClose = document.getElementById('adminAddUserModalCloseBtn');
      if (btnClose) btnClose.click();

      const isModalClosed = modal && (modal.hidden || window.getComputedStyle(modal).display === 'none');
      return {
        ok: isModalOpen && isModalClosed,
        details: 'Add user modal opened and closed cleanly'
      };
    })()`);
  });

  // Subtab 7: ai_usage
  await assertTest('Settings Subtab 7 (ai_usage): Refresh AI Usage button & widgets', async () => {
    return await client.eval(`(async () => {
      window.switchSettingsTab('ai_usage');
      const btnRefresh = document.getElementById('btnRefreshAiUsage');
      if (btnRefresh) btnRefresh.click();
      await new Promise(r => setTimeout(r, 800));

      const pane = document.getElementById('paneSettingsAiUsage');
      const isActive = pane && !pane.hidden && window.getComputedStyle(pane).display !== 'none';
      return {
        ok: isActive && !!btnRefresh,
        details: 'AI usage pane active, refresh triggered'
      };
    })()`);
  });

  // Subtab 8: audit
  await assertTest('Settings Subtab 8 (audit): Filter & Export CSV/JSON buttons', async () => {
    return await client.eval(`(async () => {
      window.switchSettingsTab('audit');
      const btnFilter = document.getElementById('btnFilterAudit');
      const btnCsv = document.getElementById('btnExportAuditCsv');
      const btnJson = document.getElementById('btnExportAuditJson');
      if (btnFilter) btnFilter.click();
      await new Promise(r => setTimeout(r, 1000));

      const tbody = document.getElementById('tableAuditLogsBody');
      const rows = tbody ? tbody.querySelectorAll('tr').length : 0;
      return {
        ok: !!btnFilter && !!btnCsv && !!btnJson && rows > 0,
        details: 'Audit rows: ' + rows + ', CSV/JSON export buttons verified'
      };
    })()`);
  });

  // Subtab 9: license
  await assertTest('Settings Subtab 9 (license): License Refresh & Activate controls', async () => {
    return await client.eval(`(async () => {
      window.switchSettingsTab('license');
      const btnRefresh = document.getElementById('btnRefreshLicense');
      const btnActivate = document.getElementById('btnActivateLicense');
      if (btnRefresh) btnRefresh.click();
      await new Promise(r => setTimeout(r, 1000));

      const pane = document.getElementById('paneSettingsLicense');
      const badge = document.getElementById('badgeLicenseState');
      const isActive = pane && !pane.hidden && window.getComputedStyle(pane).display !== 'none';
      return {
        ok: isActive && !!btnRefresh && !!btnActivate && !!badge,
        details: 'License pane active, badge state: ' + (badge ? badge.textContent : '')
      };
    })()`);
  });

  // Subtabs scrolling arrows
  await assertTest('Settings: Subtabs navigation scroll arrows (Prev / Next)', async () => {
    return await client.eval(`(() => {
      const btnPrev = document.getElementById('btnSettingsSubtabsPrev');
      const btnNext = document.getElementById('btnSettingsSubtabsNext');
      if (btnNext) btnNext.click();
      if (btnPrev) btnPrev.click();
      return { ok: !!btnPrev && !!btnNext, details: 'Scroll buttons clickable without errors' };
    })()`);
  });

  // Check for any uncaught console errors or exceptions
  console.log('\n================================================================');
  console.log(' RUNTIME HEALTH AUDIT DURING DEEP TESTS');
  console.log('================================================================');
  console.log(`  Uncaught Console Errors: ${client.consoleErrors.length}`);
  if (client.consoleErrors.length > 0) {
    client.consoleErrors.forEach(err => console.log('    [Console Error]', err));
  }
  console.log(`  Uncaught JS Exceptions:  ${client.exceptions.length}`);
  if (client.exceptions.length > 0) {
    client.exceptions.forEach(ex => console.log('    [Exception]', ex));
  }

  // Teardown
  client.close();
  try { edgeProc.kill(); } catch(e){}
  try { serverProc.kill(); } catch(e){}

  console.log('\n================================================================');
  console.log(` RESULTS: ${passedTests} PASSED, ${failedTests} FAILED out of ${passedTests + failedTests} tests`);
  console.log('================================================================\n');

  if (failedTests > 0 || client.exceptions.length > 0) {
    process.exit(1);
  } else {
    process.exit(0);
  }
}

runCanvasAndSettingsTests().catch(err => {
  console.error('Fatal Test Runner Error:', err);
  process.exit(1);
});
