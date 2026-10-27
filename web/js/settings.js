// ── AI & Voyage API Settings ──────────────────────────────────


async function loadSettings() {
  var msgEl = document.getElementById("settingsMsg");
  if (typeof isCurrentUserAdmin === "function" && !isCurrentUserAdmin()) {
    if (msgEl) {
      msgEl.className = "settings-msg";
      msgEl.textContent = "";
    }
    return;
  }
  try {
    var res = await apiGet("/api/settings");
    if (!res || !res.ok) {
      if (msgEl) {
        msgEl.className = "settings-msg error show";
        msgEl.textContent = "설정을 불러오지 못했습니다: " + ((res && res.error) || "서버 응답 오류");
      }
      return;
    }

    currentSettings = res.settings || {};
    var s = currentSettings;
    var status = res.status || {};
    var stats = res.vectorStats || {};

    // 1. Fill AI Fields
    var setAiEnabled = document.getElementById("setAiEnabled");
    var setAiAllowUserKeys = document.getElementById("setAiAllowUserKeys");
    var setAiProvider = document.getElementById("setAiProvider");
    var setAiModel = document.getElementById("setAiModel");
    var setAiBaseUrl = document.getElementById("setAiBaseUrl");

    if (setAiEnabled) setAiEnabled.checked = (String(s.AI_ENABLED).toLowerCase() === "true");
    if (setAiAllowUserKeys) setAiAllowUserKeys.checked = (String(s.AI_ALLOW_USER_KEYS).toLowerCase() === "true");
    if (setAiProvider && s.AI_PROVIDER) setAiProvider.value = s.AI_PROVIDER;
    if (setAiModel && s.AI_MODEL) setAiModel.value = s.AI_MODEL;
    if (setAiBaseUrl) setAiBaseUrl.value = s.AI_BASE_URL || "";
    var setAiApiKey = document.getElementById("setAiApiKey");
    if (setAiApiKey) setAiApiKey.value = s.AI_API_KEY || "";
    if (typeof onAiProviderChange === "function") {
      onAiProviderChange();
      // Restore explicit custom values if present
      if (s.AI_MODEL && setAiModel) setAiModel.value = s.AI_MODEL;
      if (s.AI_BASE_URL && setAiBaseUrl) setAiBaseUrl.value = s.AI_BASE_URL;
    }

    // 1-1. Fill AI Fallback Fields
    var setAiFallbackEnabled = document.getElementById("setAiFallbackEnabled");
    var setAiFallbackProvider = document.getElementById("setAiFallbackProvider");
    var setAiFallbackModel = document.getElementById("setAiFallbackModel");
    var setAiFallbackApiKey = document.getElementById("setAiFallbackApiKey");
    var setAiFallbackBaseUrl = document.getElementById("setAiFallbackBaseUrl");
    var aiFallbackFields = document.getElementById("aiFallbackFields");

    var isFallbackEnabled = (String(s.AI_FALLBACK_ENABLED).toLowerCase() === "true");
    if (setAiFallbackEnabled) {
      setAiFallbackEnabled.checked = isFallbackEnabled;
      if (aiFallbackFields) {
        aiFallbackFields.style.display = isFallbackEnabled ? "block" : "none";
      }
    }
    if (setAiFallbackProvider && s.AI_FALLBACK_PROVIDER) setAiFallbackProvider.value = s.AI_FALLBACK_PROVIDER;
    if (setAiFallbackModel && s.AI_FALLBACK_MODEL) setAiFallbackModel.value = s.AI_FALLBACK_MODEL;
    if (setAiFallbackApiKey && s.AI_FALLBACK_API_KEY) setAiFallbackApiKey.value = s.AI_FALLBACK_API_KEY;
    if (setAiFallbackBaseUrl) setAiFallbackBaseUrl.value = s.AI_FALLBACK_BASE_URL || "";
    if (typeof onAiFallbackProviderChange === "function") {
      onAiFallbackProviderChange();
      if (s.AI_FALLBACK_MODEL && setAiFallbackModel) setAiFallbackModel.value = s.AI_FALLBACK_MODEL;
      if (s.AI_FALLBACK_BASE_URL && setAiFallbackBaseUrl) setAiFallbackBaseUrl.value = s.AI_FALLBACK_BASE_URL;
    }

    // 2. Fill Voyage / Vector Fields
    var setVoyageEnabled = document.getElementById("setVoyageEnabled");
    var setVoyageProvider = document.getElementById("setVoyageProvider");
    var setVoyageModel = document.getElementById("setVoyageModel");
    var setVoyageBaseUrl = document.getElementById("setVoyageBaseUrl");
    var voyageBaseUrlField = document.getElementById("voyageBaseUrlField");

    if (setVoyageEnabled) setVoyageEnabled.checked = (String(s.VOYAGE_ENABLED).toLowerCase() === "true");
    if (setVoyageProvider) {
      setVoyageProvider.value = s.VOYAGE_PROVIDER || "voyage";
      if (voyageBaseUrlField) {
        voyageBaseUrlField.style.display = (setVoyageProvider.value === "custom" || setVoyageProvider.value === "ollama") ? "block" : "none";
      }
    }
    if (setVoyageModel && s.VOYAGE_MODEL) setVoyageModel.value = s.VOYAGE_MODEL;
    if (setVoyageBaseUrl) setVoyageBaseUrl.value = s.VOYAGE_BASE_URL || "";
    var setVoyageApiKey = document.getElementById("setVoyageApiKey");
    if (setVoyageApiKey) setVoyageApiKey.value = s.VOYAGE_API_KEY || "";

    // 3. Fill Jira Fields
    var setJiraEnabled = document.getElementById("setJiraEnabled");
    var setJiraBaseUrl = document.getElementById("setJiraBaseUrl");
    var setJiraEmail = document.getElementById("setJiraEmail");
    var setJiraApiToken = document.getElementById("setJiraApiToken");
    var setJiraProjectKey = document.getElementById("setJiraProjectKey");

    if (setJiraEnabled) {
      setJiraEnabled.checked = (String(s.JIRA_ENABLED).toLowerCase() === "true");
      var jiraConfigBody = document.getElementById("jiraConfigBody");
      if (jiraConfigBody) {
        jiraConfigBody.style.display = setJiraEnabled.checked ? "block" : "none";
      }
    }
    if (setJiraBaseUrl) setJiraBaseUrl.value = s.JIRA_BASE_URL || "";
    if (setJiraEmail) setJiraEmail.value = s.JIRA_EMAIL || "";
    if (setJiraApiToken && s.JIRA_API_TOKEN) setJiraApiToken.value = s.JIRA_API_TOKEN;
    if (setJiraProjectKey) setJiraProjectKey.value = s.JIRA_PROJECT_KEY || "";

    window.CURRENT_JIRA_PROJECT_MAP = s.JIRA_PROJECT_MAP || {};

    // 4. Fill Webhook Fields
    var setSlackWebhookUrl = document.getElementById("setSlackWebhookUrl");
    var setTeamsWebhookUrl = document.getElementById("setTeamsWebhookUrl");
    var setGenericWebhookUrl = document.getElementById("setGenericWebhookUrl");
    var badgeWebhooksStatus = document.getElementById("badgeWebhooksStatus");

    if (setSlackWebhookUrl) setSlackWebhookUrl.value = s.SLACK_WEBHOOK_URL || "";
    if (setTeamsWebhookUrl) setTeamsWebhookUrl.value = s.TEAMS_WEBHOOK_URL || "";
    if (setGenericWebhookUrl) setGenericWebhookUrl.value = s.GENERIC_WEBHOOK_URL || "";

    if (badgeWebhooksStatus) {
      if (s.SLACK_WEBHOOK_URL || s.TEAMS_WEBHOOK_URL || s.GENERIC_WEBHOOK_URL) {
        badgeWebhooksStatus.className = "card-badge connected";
        badgeWebhooksStatus.textContent = "연동 설정됨";
      } else {
        badgeWebhooksStatus.className = "card-badge";
        badgeWebhooksStatus.textContent = "미설정";
      }
    }

    checkReportTemplateStatus();
    renderSettingsCategoryTable();

    // 5. Update Status Pills & Badges
    updateStatusPills(status, stats);


  } catch (err) {
    console.error("loadSettings error:", err);
    if (msgEl) {
      msgEl.className = "settings-msg error show";
      msgEl.textContent = "설정 로드 중 오류가 발생했습니다: " + err.message;
    }
  }
}

function updateStatusPills(status, stats) {
  // AI Pill & Badge
  var dotAi = document.getElementById("dotAi");
  var valAi = document.getElementById("valAi");
  var badgeAi = document.getElementById("badgeAiStatus");
  if (status.ai) {
    var keyCount = status.ai.key_count || (status.ai.has_key ? 1 : 0);
    var keySuffix = keyCount > 1 ? " (" + keyCount + "개 키)" : "";
    var fbInfo = "";
    if (status.ai.fallback && status.ai.fallback.enabled && status.ai.fallback.has_key) {
      fbInfo = " [보조: " + (status.ai.fallback.provider || "대체") + "]";
    }

    if (!status.ai.enabled) {
      if (dotAi) dotAi.className = "status-dot";
      if (valAi) valAi.textContent = "비활성화";
      if (badgeAi) { badgeAi.className = "card-badge"; badgeAi.textContent = "비활성화"; }
    } else if (status.ai.has_key) {
      if (dotAi) dotAi.className = "status-dot active";
      if (valAi) valAi.textContent = (status.ai.provider || "AI") + " (" + (status.ai.model || "온라인") + ")" + keySuffix + fbInfo;
      if (badgeAi) {
        badgeAi.className = "card-badge connected";
        badgeAi.textContent = keyCount > 1 ? "온라인 (" + keyCount + "개 키)" : "온라인";
      }
    } else {
      if (dotAi) dotAi.className = "status-dot error";
      if (valAi) valAi.textContent = "키 미설정";
      if (badgeAi) { badgeAi.className = "card-badge disconnected"; badgeAi.textContent = "키 필요"; }
    }
  }

  // Voyage / Vector Pill & Badge
  var dotVoyage = document.getElementById("dotVoyage");
  var valVoyage = document.getElementById("valVoyage");
  var badgeVoyage = document.getElementById("badgeVoyageStatus");
  if (status.voyage) {
    var keyCount = status.voyage.key_count || (status.voyage.has_key ? 1 : 0);
    var keySuffix = keyCount > 1 ? " (" + keyCount + "개 키 로테이션)" : "";
    var provTitle = (status.voyage.provider || "voyage").toUpperCase();
    if (!status.voyage.enabled) {
      if (dotVoyage) dotVoyage.className = "status-dot";
      if (valVoyage) valVoyage.textContent = "비활성화";
      if (badgeVoyage) { badgeVoyage.className = "card-badge"; badgeVoyage.textContent = "비활성화"; }
    } else if (status.voyage.has_key) {
      if (dotVoyage) dotVoyage.className = "status-dot active";
      if (valVoyage) valVoyage.textContent = "AI 벡터 임베딩 (" + (status.voyage.model || "온라인") + ")" + keySuffix;
      if (badgeVoyage) {
        badgeVoyage.className = "card-badge connected";
        badgeVoyage.textContent = keyCount > 1 ? "연결됨 (" + keyCount + "개 키)" : "연결됨";
      }
    } else {
      if (dotVoyage) dotVoyage.className = "status-dot warning";
      if (valVoyage) valVoyage.textContent = "키 미설정 (키워드 검색 대체)";
      if (badgeVoyage) { badgeVoyage.className = "card-badge disconnected"; badgeVoyage.textContent = "키 필요"; }
    }
  }

  // Jira Pill & Badge
  var dotJira = document.getElementById("dotJira");
  var valJira = document.getElementById("valJira");
  var badgeJira = document.getElementById("badgeJiraStatus");
  var pillJira = document.getElementById("pillJira");
  if (status.jira) {
    if (!status.jira.enabled) {
      if (dotJira) dotJira.className = "status-dot";
      if (valJira) valJira.textContent = "비활성화";
      if (badgeJira) { badgeJira.className = "card-badge"; badgeJira.textContent = "비활성화"; }
      if (pillJira) pillJira.style.display = "none";
    } else if (status.jira.has_key) {
      if (dotJira) dotJira.className = "status-dot active";
      if (valJira) valJira.textContent = "Cloud REST API 연동";
      if (badgeJira) { badgeJira.className = "card-badge connected"; badgeJira.textContent = "연동 준비 완료"; }
      if (pillJira) pillJira.style.display = "";
    } else {
      if (dotJira) dotJira.className = "status-dot error";
      if (valJira) valJira.textContent = "토큰/이메일 필요";
      if (badgeJira) { badgeJira.className = "card-badge disconnected"; badgeJira.textContent = "인증 필요"; }
      if (pillJira) pillJira.style.display = "";
    }
  } else if (pillJira) {
    pillJira.style.display = "none";
  }

  // Vector Count Pill & Card Badge
  var dotVectors = document.getElementById("dotVectors");
  var valVectors = document.getElementById("valVectors");
  var voyageVectorCountBadge = document.getElementById("voyageVectorCountBadge");
  if (stats && typeof stats.total_vectors !== "undefined") {
    var countStr = (stats.total_vectors || 0).toLocaleString() + "건";
    if (dotVectors) dotVectors.className = (stats.total_vectors > 0) ? "status-dot active" : "status-dot";
    if (valVectors) valVectors.textContent = countStr;
    if (voyageVectorCountBadge) voyageVectorCountBadge.textContent = "현재 " + countStr + " 색인됨";
  }
  if (typeof updateSettingsSubtabsScrollArrows === "function") {
    setTimeout(updateSettingsSubtabsScrollArrows, 80);
  }
}

async function saveSettings(e) {
  if (e && e.preventDefault) e.preventDefault();

  var msgEl = document.getElementById("settingsMsg");
  var btnSave = document.getElementById("btnSaveSettings");
  if (btnSave) btnSave.disabled = true;

  if (msgEl) {
    msgEl.className = "settings-msg loading show";
    msgEl.textContent = "설정을 저장하고 런타임에 동기화하는 중...";
  }

  var updates = {
    AI_ENABLED: document.getElementById("setAiEnabled").checked ? "true" : "false",
    AI_ALLOW_USER_KEYS: (document.getElementById("setAiAllowUserKeys") && document.getElementById("setAiAllowUserKeys").checked) ? "true" : "false",
    AI_PROVIDER: document.getElementById("setAiProvider").value.trim(),
    AI_MODEL: document.getElementById("setAiModel").value.trim(),
    AI_API_KEY: (document.getElementById("setAiApiKey") ? document.getElementById("setAiApiKey").value.trim() : ""),
    AI_BASE_URL: document.getElementById("setAiBaseUrl").value.trim(),

    AI_FALLBACK_ENABLED: (document.getElementById("setAiFallbackEnabled") && document.getElementById("setAiFallbackEnabled").checked) ? "true" : "false",
    AI_FALLBACK_PROVIDER: (document.getElementById("setAiFallbackProvider") ? document.getElementById("setAiFallbackProvider").value.trim() : "openai"),
    AI_FALLBACK_MODEL: (document.getElementById("setAiFallbackModel") ? document.getElementById("setAiFallbackModel").value.trim() : ""),
    AI_FALLBACK_API_KEY: (document.getElementById("setAiFallbackApiKey") ? document.getElementById("setAiFallbackApiKey").value.trim() : ""),
    AI_FALLBACK_BASE_URL: (document.getElementById("setAiFallbackBaseUrl") ? document.getElementById("setAiFallbackBaseUrl").value.trim() : ""),

    VOYAGE_ENABLED: document.getElementById("setVoyageEnabled").checked ? "true" : "false",
    VOYAGE_PROVIDER: (document.getElementById("setVoyageProvider") ? document.getElementById("setVoyageProvider").value.trim() : "voyage"),
    VOYAGE_MODEL: document.getElementById("setVoyageModel").value.trim(),
    VOYAGE_BASE_URL: (document.getElementById("setVoyageBaseUrl") ? document.getElementById("setVoyageBaseUrl").value.trim() : ""),
    VOYAGE_API_KEY: (document.getElementById("setVoyageApiKey") ? document.getElementById("setVoyageApiKey").value.trim() : ""),

    JIRA_ENABLED: document.getElementById("setJiraEnabled").checked ? "true" : "false",
    JIRA_BASE_URL: document.getElementById("setJiraBaseUrl").value.trim(),
    JIRA_EMAIL: document.getElementById("setJiraEmail").value.trim(),
    JIRA_API_TOKEN: document.getElementById("setJiraApiToken").value.trim(),
    JIRA_PROJECT_KEY: document.getElementById("setJiraProjectKey").value.trim(),
    JIRA_PROJECT_MAP: window.CURRENT_JIRA_PROJECT_MAP || {},

    SLACK_WEBHOOK_URL: (document.getElementById("setSlackWebhookUrl") ? document.getElementById("setSlackWebhookUrl").value.trim() : ""),
    TEAMS_WEBHOOK_URL: (document.getElementById("setTeamsWebhookUrl") ? document.getElementById("setTeamsWebhookUrl").value.trim() : ""),
    GENERIC_WEBHOOK_URL: (document.getElementById("setGenericWebhookUrl") ? document.getElementById("setGenericWebhookUrl").value.trim() : "")
  };

  // Validation for Custom Provider
  if (updates.AI_ENABLED === "true" && updates.AI_PROVIDER === "custom") {
    if (!updates.AI_BASE_URL) {
      if (msgEl) {
        msgEl.className = "settings-msg error show";
        msgEl.textContent = "❌ 사용자 정의(Custom) AI 제공자는 Base URL(URL 게이트웨이)을 반드시 입력해야 합니다.";
      }
      showToast("Custom AI Base URL을 입력해주세요.");
      if (btnSave) btnSave.disabled = false;
      var elUrl = document.getElementById("setAiBaseUrl");
      if (elUrl) { elUrl.focus(); elUrl.classList.add("input-error"); }
      return;
    }
    if (!updates.AI_MODEL) {
      if (msgEl) {
        msgEl.className = "settings-msg error show";
        msgEl.textContent = "❌ 사용자 정의(Custom) AI 제공자는 모델명(Model Name)을 반드시 입력해야 합니다.";
      }
      showToast("Custom AI 모델명을 입력해주세요.");
      if (btnSave) btnSave.disabled = false;
      var elModel = document.getElementById("setAiModel");
      if (elModel) { elModel.focus(); elModel.classList.add("input-error"); }
      return;
    }
  }

  // Validation for Custom Fallback Provider
  if (updates.AI_FALLBACK_ENABLED === "true" && updates.AI_FALLBACK_PROVIDER === "custom") {
    if (!updates.AI_FALLBACK_BASE_URL) {
      if (msgEl) {
        msgEl.className = "settings-msg error show";
        msgEl.textContent = "❌ 사용자 정의(Custom) 보조 AI 제공자는 Base URL을 반드시 입력해야 합니다.";
      }
      showToast("Custom 보조 AI Base URL을 입력해주세요.");
      if (btnSave) btnSave.disabled = false;
      var elFbUrl = document.getElementById("setAiFallbackBaseUrl");
      if (elFbUrl) { elFbUrl.focus(); elFbUrl.classList.add("input-error"); }
      return;
    }
    if (!updates.AI_FALLBACK_MODEL) {
      if (msgEl) {
        msgEl.className = "settings-msg error show";
        msgEl.textContent = "❌ 사용자 정의(Custom) 보조 AI 제공자는 모델명을 반드시 입력해야 합니다.";
      }
      showToast("Custom 보조 AI 모델명을 입력해주세요.");
      if (btnSave) btnSave.disabled = false;
      var elFbModel = document.getElementById("setAiFallbackModel");
      if (elFbModel) { elFbModel.focus(); elFbModel.classList.add("input-error"); }
      return;
    }
  }

  try {
    var res = await apiPostJson("/api/settings", updates);
    if (res && res.ok) {
      if (msgEl) {
        msgEl.className = "settings-msg success show";
        msgEl.textContent = "✅ " + (res.message || "설정이 성공적으로 저장 및 적용되었습니다.");
      }
      showToast("API 설정이 저장되었습니다.");
      window.__JIRA_STATUS__ = window.__JIRA_STATUS__ || {};
      window.__JIRA_STATUS__.enabled = (updates.JIRA_ENABLED === "true");
      if(typeof window.updateJiraIntegrationUI === "function"){
        window.updateJiraIntegrationUI();
      }
      if(typeof window.loadRecords === "function"){
        window.loadRecords();
      }
      if(typeof window.loadSchedule === "function"){
        window.loadSchedule();
      }
      await loadSettings();
    } else {
      if (msgEl) {
        msgEl.className = "settings-msg error show";
        msgEl.textContent = "❌ 설정 저장 실패: " + ((res && res.error) || "알 수 없는 오류");
      }
    }

  } catch (err) {
    if (msgEl) {
      msgEl.className = "settings-msg error show";
      msgEl.textContent = "❌ 저장 중 오류 발생: " + err.message;
    }
  } finally {
    if (btnSave) btnSave.disabled = false;
  }
}

async function testConnections() {
  var btnTest = document.getElementById("btnTestConnections");
  if (btnTest) {
    btnTest.disabled = true;
    btnTest.innerHTML = "<span>⏳</span> 테스트 중...";
  }

  var diagAi = document.getElementById("diagAi");
  var diagAiFallback = document.getElementById("diagAiFallback");
  var diagVoyage = document.getElementById("diagVoyage");
  var diagJira = document.getElementById("diagJira");

  var badgeAi = document.getElementById("badgeAiStatus");
  var badgeVoyage = document.getElementById("badgeVoyageStatus");
  var badgeJira = document.getElementById("badgeJiraStatus");

  if (diagAi) { diagAi.className = "test-diag-box show"; diagAi.textContent = "주(Primary) AI 각 API Key 연결 테스트 중..."; }
  if (diagAiFallback) { diagAiFallback.className = "test-diag-box show"; diagAiFallback.textContent = "보조(Fallback) AI 연결 테스트 중..."; }
  if (diagVoyage) { diagVoyage.className = "test-diag-box show"; diagVoyage.textContent = "AI 벡터 임베딩 연결 테스트 중..."; }
  if (diagJira) { diagJira.className = "test-diag-box show"; diagJira.textContent = "Jira REST API 서버 확인 중..."; }

  try {
    var res = await apiPostJson("/api/settings/test", {});
    var results = (res && res.results) || {};

    // Reset row validation styles
    document.querySelectorAll("#aiKeyInputsContainer .api-key-row, #voyageKeyInputsContainer .api-key-row").forEach(function(r) {
      r.classList.remove("has-error", "is-valid");
      var badge = r.querySelector(".api-key-status-badge");
      if (badge) badge.remove();
    });

    // 1. Primary AI Result
    if (results.ai) {
      if (results.ai.ok) {
        var isPartial = results.ai.has_invalid_keys;
        if (diagAi) {
          diagAi.className = isPartial ? "test-diag-box show fail" : "test-diag-box show ok";
          diagAi.textContent = (isPartial ? "⚠️ " : "✅ ") + results.ai.message;
        }
        if (badgeAi) {
          badgeAi.className = isPartial ? "card-badge disconnected" : "card-badge connected";
          badgeAi.textContent = isPartial ? "부분 오류" : "연결 성공 (" + results.ai.latency_ms + "ms)";
        }
      } else {
        if (diagAi) { diagAi.className = "test-diag-box show fail"; diagAi.textContent = "❌ 연결 실패: " + results.ai.error; }
        if (badgeAi) { badgeAi.className = "card-badge disconnected"; badgeAi.textContent = "연결 실패"; }
      }

    }

    // 1-1. Fallback AI Result
    if (results.ai_fallback) {
      if (diagAiFallback) {
        if (results.ai_fallback.ok) {
          diagAiFallback.className = "test-diag-box show ok";
          diagAiFallback.textContent = "✅ " + results.ai_fallback.message;
        } else {
          diagAiFallback.className = "test-diag-box show fail";
          diagAiFallback.textContent = "⚠️ " + results.ai_fallback.error;
        }
      }
    } else if (diagAiFallback) {
      diagAiFallback.className = "test-diag-box";
      diagAiFallback.textContent = "";
    }

    // 2. Voyage AI Result
    if (results.voyage) {
      if (results.voyage.ok) {
        var isVoyagePartial = results.voyage.has_invalid_keys;
        if (diagVoyage) {
          diagVoyage.className = isVoyagePartial ? "test-diag-box show fail" : "test-diag-box show ok";
          diagVoyage.textContent = (isVoyagePartial ? "⚠️ " : "✅ ") + results.voyage.message;
        }
        if (badgeVoyage) {
          badgeVoyage.className = isVoyagePartial ? "card-badge disconnected" : "card-badge connected";
          badgeVoyage.textContent = isVoyagePartial ? "부분 오류" : "연결 성공 (" + results.voyage.latency_ms + "ms)";
        }
      } else {
        if (diagVoyage) { diagVoyage.className = "test-diag-box show fail"; diagVoyage.textContent = "❌ 임베딩 실패: " + results.voyage.error; }
        if (badgeVoyage) { badgeVoyage.className = "card-badge disconnected"; badgeVoyage.textContent = "임베딩 실패"; }
      }

    }

    // 3. Jira Result
    if (results.jira) {
      window.__JIRA_STATUS__ = window.__JIRA_STATUS__ || {};
      if (results.jira.ok) {
        if (diagJira) { diagJira.className = "test-diag-box show ok"; diagJira.textContent = "✅ " + results.jira.message; }
        if (badgeJira) { badgeJira.className = "card-badge connected"; badgeJira.textContent = "인증 성공 (" + results.jira.latency_ms + "ms)"; }
        window.__JIRA_STATUS__.connected = true;
      } else {
        if (diagJira) { diagJira.className = "test-diag-box show fail"; diagJira.textContent = "❌ Jira 연동 실패: " + results.jira.error; }
        if (badgeJira) { badgeJira.className = "card-badge disconnected"; badgeJira.textContent = "연동 실패"; }
        window.__JIRA_STATUS__.connected = false;
      }
    }

    // 4. Outgoing Webhook Test Result
    var diagWebhooks = document.getElementById("diagWebhooks");
    var badgeWebhooks = document.getElementById("badgeWebhooksStatus");
    if (results.webhooks) {
      if (results.webhooks.info) {
        if (diagWebhooks) {
          diagWebhooks.className = "test-diag-box show";
          diagWebhooks.textContent = "ℹ️ " + results.webhooks.info;
        }
      } else {
        var whLines = [];
        var allWhOk = true;
        for (var whKey in results.webhooks) {
          var whObj = results.webhooks[whKey];
          if (whObj.ok) {
            whLines.push("✅ " + (whObj.message || (whKey + " 연동 성공")));
          } else {
            allWhOk = false;
            whLines.push("❌ " + whKey + " 전송 실패: " + whObj.error);
          }
        }
        if (diagWebhooks) {
          diagWebhooks.className = "test-diag-box show " + (allWhOk ? "ok" : "fail");
          diagWebhooks.innerHTML = whLines.join("<br>");
        }
        if (badgeWebhooks) {
          badgeWebhooks.className = allWhOk ? "card-badge connected" : "card-badge disconnected";
          badgeWebhooks.textContent = allWhOk ? "전송 성공" : "일부 실패";
        }
      }
    }

    showToast("연결 진단이 완료되었습니다.");

  } catch (err) {
    console.error("testConnections error:", err);
    showToast("연결 테스트 중 오류가 발생했습니다.");
  } finally {
    if (btnTest) {
      btnTest.disabled = false;
      btnTest.innerHTML = "<span>🔌</span> 연결 테스트";
    }
  }
}

async function syncVectors() {
  var btnSync = document.getElementById("btnSyncVectors");
  if (btnSync) {
    btnSync.disabled = true;
    btnSync.innerHTML = "<span>⏳</span> 검사 중...";
  }

  showToast("벡터 데이터베이스 동기화 상태를 확인하는 중...");

  try {
    // 1. Kiểm tra trạng thái hiện tại (Check-only)
    var checkRes = await apiPostJson("/api/vectors/sync", { check_only: true });

    // 2. Nếu đã đồng bộ hoàn hảo với model hiện tại -> DỪNG NGAY, TIẾT KIỆM 0 TOKEN!
    if (checkRes && checkRes.ok && checkRes.is_fully_synced) {
      showToast("✅ 이미 최신 상태입니다: 전체 " + checkRes.total + "건 데이터가 [" + checkRes.current_model + "] 모델로 완벽히 색인되어 있습니다. (소모 토큰: 0)");
      await loadSettings();
      return;
    }

    // 3. Nếu phát hiện đổi Model AI -> Cảnh báo người dùng trước khi tiêu hao token
    var forceReindex = false;
    if (checkRes && checkRes.ok && checkRes.needs_model_migration_warning) {
      var confirmMsg = "⚠️ [모델 변경 감지] 현재 설정된 모델 [" + checkRes.current_model + "]이 기존 데이터(" + checkRes.diff_model + "건)와 다릅니다.\n\n새 모델로 전체 데이터를 재색인하시겠습니까?\n(약 " + checkRes.total + "건의 데이터가 다시 계산되며 토큰이 소모됩니다)";
      var proceed = confirm(confirmMsg);
      if (!proceed) {
        showToast("⚠️ 재색인 작업이 취소되었습니다. 기존 벡터가 유지됩니다.");
        return;
      }
      forceReindex = true;
    }

    // 4. Bắt đầu đồng bộ
    if (btnSync) {
      btnSync.innerHTML = "<span>⏳</span> 색인 중...";
    }
    showToast(forceReindex ? "🔄 [" + checkRes.current_model + "] 모델로 전체 재색인을 시작합니다..." : "🔄 미색인 신규 데이터(" + checkRes.missing + "건) 동기화를 시작합니다...");

    var res = await apiPostJson("/api/vectors/sync", { force: forceReindex });
    if (res && res.ok) {
      if (res.already_synced) {
        showToast("✅ " + (res.message || "모든 데이터가 최신 상태입니다. (0 토큰)"));
      } else {
        var synced = res.indexed || 0;
        var skipped = res.skipped || 0;
        var total = res.total || 0;
        showToast("✅ 동기화 완료: " + synced + "건 신규 색인됨 (" + skipped + "건 스킵, 총 " + total + "건, 모델: " + (res.current_model || "AI 임베딩") + ")");
      }
      await loadSettings();
    } else {
      showToast("❌ 색인 실패: " + ((res && res.error) || (res && res.reason) || "알 수 없는 오류"));
    }
  } catch (err) {
    showToast("❌ 색인 요청 중 오류 발생: " + err.message);
  } finally {
    if (btnSync) {
      btnSync.disabled = false;
      btnSync.innerHTML = "<span>🔄</span> 전체 벡터 즉시 색인";
    }
  }
}

var DEFAULT_PROVIDER_DEFAULTS = {
  gemini: {
    base_url: "https://generativelanguage.googleapis.com/v1beta/openai",
    model: "gemini-2.5-flash"
  },
  openai: {
    base_url: "https://api.openai.com/v1",
    model: "gpt-4o-mini"
  },
  anthropic: {
    base_url: "https://api.anthropic.com",
    model: "claude-sonnet-4-5"
  },
  deepseek: {
    base_url: "https://api.deepseek.com/v1",
    model: "deepseek-chat"
  },
  groq: {
    base_url: "https://api.groq.com/openai/v1",
    model: "llama-3.3-70b-versatile"
  },
  openrouter: {
    base_url: "https://openrouter.ai/api/v1",
    model: "google/gemini-2.5-flash"
  },
  ollama: {
    base_url: "http://localhost:11434/v1",
    model: "llama3.1"
  },
  custom: {
    base_url: "",
    model: ""
  }
};

function onAiProviderChange() {
  var prov = (document.getElementById("setAiProvider") ? document.getElementById("setAiProvider").value : "gemini").toLowerCase();
  var isCustom = (prov === "custom");

  var modelBadge = document.getElementById("aiModelBadge");
  var baseUrlBadge = document.getElementById("aiBaseUrlBadge");
  var customHint = document.getElementById("aiCustomUrlHint");
  var modelInput = document.getElementById("setAiModel");
  var baseUrlInput = document.getElementById("setAiBaseUrl");

  if (modelBadge) {
    modelBadge.textContent = isCustom ? "(필수)" : "";
    modelBadge.style.color = isCustom ? "#dc2626" : "";
    modelBadge.style.fontWeight = isCustom ? "bold" : "";
  }
  if (baseUrlBadge) {
    baseUrlBadge.textContent = isCustom ? "(필수)" : "(선택)";
    baseUrlBadge.style.color = isCustom ? "#dc2626" : "";
    baseUrlBadge.style.fontWeight = isCustom ? "bold" : "";
  }
  if (customHint) {
    customHint.style.display = isCustom ? "block" : "none";
  }

  if (isCustom) {
    if (baseUrlInput) baseUrlInput.placeholder = "예: https://api.together.xyz/v1 또는 http://localhost:8000/v1";
    if (modelInput) modelInput.placeholder = "사용할 모델명 입력 (예: deepseek-ai/DeepSeek-V3, meta-llama/Llama-3.3-70B)";
  } else {
    var defaults = DEFAULT_PROVIDER_DEFAULTS[prov];
    if (defaults) {
      if (modelInput) {
        modelInput.value = defaults.model;
        modelInput.placeholder = "gemini-2.5-flash / gpt-4o-mini";
      }
      if (baseUrlInput) {
        baseUrlInput.value = defaults.base_url;
        baseUrlInput.placeholder = "기본 게이트웨이 또는 프록시 URL";
      }
    }
  }
}

function onAiFallbackProviderChange() {
  var sel = document.getElementById("setAiFallbackProvider");
  if (!sel) return;
  var prov = (sel.value || "openai").toLowerCase();
  var isCustom = (prov === "custom");

  var modelBadge = document.getElementById("aiFallbackModelBadge");
  var baseUrlBadge = document.getElementById("aiFallbackBaseUrlBadge");
  var customHint = document.getElementById("aiFallbackCustomUrlHint");
  var modelInput = document.getElementById("setAiFallbackModel");
  var baseUrlInput = document.getElementById("setAiFallbackBaseUrl");

  if (modelBadge) {
    modelBadge.textContent = isCustom ? "(필수)" : "";
    modelBadge.style.color = isCustom ? "#dc2626" : "";
    modelBadge.style.fontWeight = isCustom ? "bold" : "";
  }
  if (baseUrlBadge) {
    baseUrlBadge.textContent = isCustom ? "(필수)" : "(선택)";
    baseUrlBadge.style.color = isCustom ? "#dc2626" : "";
    baseUrlBadge.style.fontWeight = isCustom ? "bold" : "";
  }
  if (customHint) {
    customHint.style.display = isCustom ? "block" : "none";
  }

  if (isCustom) {
    if (baseUrlInput) baseUrlInput.placeholder = "예: https://api.together.xyz/v1 또는 http://localhost:8000/v1";
    if (modelInput) modelInput.placeholder = "사용할 보조 모델명 입력";
  } else {
    var defaults = DEFAULT_PROVIDER_DEFAULTS[prov];
    if (defaults) {
      if (modelInput && !modelInput.value) modelInput.value = defaults.model;
      if (baseUrlInput && !baseUrlInput.value) baseUrlInput.value = defaults.base_url;
    }
  }
}

var VECTOR_PROVIDER_DEFAULTS = {
  voyage: {
    base_url: "",
    model: "voyage-3-lite"
  },
  openai: {
    base_url: "https://api.openai.com/v1/embeddings",
    model: "text-embedding-3-small"
  },
  gemini: {
    base_url: "https://generativelanguage.googleapis.com/v1beta",
    model: "gemini-embedding-001"
  },
  ollama: {
    base_url: "http://localhost:11434/v1/embeddings",
    model: "nomic-embed-text"
  },
  custom: {
    base_url: "http://localhost:11434/v1/embeddings",
    model: "nomic-embed-text"
  }
};

function onVoyageProviderChange() {
  var sel = document.getElementById("setVoyageProvider");
  if (!sel) return;
  var prov = (sel.value || "voyage").toLowerCase();
  var defaults = VECTOR_PROVIDER_DEFAULTS[prov];
  var modelInput = document.getElementById("setVoyageModel");
  var baseUrlInput = document.getElementById("setVoyageBaseUrl");
  var baseUrlField = document.getElementById("voyageBaseUrlField");

  if (baseUrlField) {
    baseUrlField.style.display = (prov === "custom" || prov === "ollama") ? "block" : "none";
  }

  if (defaults) {
    if (modelInput) modelInput.value = defaults.model;
    if (baseUrlInput) baseUrlInput.value = defaults.base_url;
  }
}

// ── Jira Connector Wizard ─────────────────────────────────────
async function inspectJiraWizard() {
  var btn = document.getElementById("btnJiraWizardInspect");
  var resBox = document.getElementById("jiraWizardResult");
  if (!resBox) return;

  var baseUrl = (document.getElementById("setJiraBaseUrl") ? document.getElementById("setJiraBaseUrl").value.trim() : "");
  var email = (document.getElementById("setJiraEmail") ? document.getElementById("setJiraEmail").value.trim() : "");
  var token = (document.getElementById("setJiraApiToken") ? document.getElementById("setJiraApiToken").value.trim() : "");

  if (!baseUrl || !email || !token) {
    resBox.style.display = "block";
    resBox.innerHTML = '<div style="color:var(--danger, #e53935); font-weight:600;">⚠️ Jira Base URL, 이메일, API 토큰을 먼저 입력해주세요.</div>';
    return;
  }

  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<span>⏳</span> 스캔 중...';
  }
  resBox.style.display = "block";
  resBox.innerHTML = '<div style="color:var(--primary, #0066cc);">🌐 Jira Cloud 연결 및 조직 데이터 스캔 중...</div>';

  try {
    var data = await apiPostJson("/api/jira/inspect", { base_url: baseUrl, email: email, api_token: token });
    if (!data || !data.ok) {
      resBox.innerHTML = '<div style="color:var(--danger, #e53935); padding:8px; background:rgba(229,57,53,0.08); border-radius:6px;">❌ ' + escapeHtml((data && data.error) || "스캔 실패") + '</div>';
      window.__JIRA_STATUS__ = window.__JIRA_STATUS__ || {};
      window.__JIRA_STATUS__.connected = false;
      return;
    }

    window.__JIRA_STATUS__ = window.__JIRA_STATUS__ || {};
    window.__JIRA_STATUS__.connected = true;

    var projs = data.projects || [];
    var types = data.issueTypes || [];
    var user = data.user || {};

    var html = '<div style="background:var(--bg-card, #fff); border:1px solid var(--border-color, #e0e0e0); border-radius:6px; padding:12px; margin-top:8px;">';
    html += '<div style="color:var(--success, #2e7d32); font-weight:700; margin-bottom:8px;">✅ Jira 연결 성공! (' + escapeHtml(user.displayName || user.emailAddress || "") + ', ' + data.latency_ms + 'ms)</div>';
    
    html += '<div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap:10px; margin-bottom:12px;">';
    html += '<div style="background:var(--bg-hover, #f8f9fa); padding:8px; border-radius:4px;"><strong>📁 감지된 프로젝트 (' + projs.length + '개):</strong><div style="font-size:11px; max-height:80px; overflow-y:auto; margin-top:4px;">';
    projs.forEach(function(p){
      html += '<div>• <strong>' + escapeHtml(p.key) + '</strong>: ' + escapeHtml(p.name) + '</div>';
    });
    html += '</div></div>';

    html += '<div style="background:var(--bg-hover, #f8f9fa); padding:8px; border-radius:4px;"><strong>🏷️ 감지된 이슈 유형 (' + types.length + '개):</strong><div style="font-size:11px; max-height:80px; overflow-y:auto; margin-top:4px;">';
    types.forEach(function(t){
      html += '<div>• ' + escapeHtml(t.name) + (t.subtask ? ' <span style="color:#e65100;">(하위작업)</span>' : '') + '</div>';
    });
    html += '</div></div></div>';

    // Interactive Department Mapping Generator
    html += '<div style="border-top:1px solid var(--border-color, #eee); padding-top:10px;">';
    html += '<div style="font-weight:600; font-size:12px; margin-bottom:6px;">부서별 Jira 프로젝트 및 이슈 유형 매핑:</div>';

    var standardTypes = types.filter(function(t){ return !t.subtask; });
    var subtaskTypes = types.filter(function(t){ return t.subtask; });

    var currentMap = window.CURRENT_JIRA_PROJECT_MAP || {};
    var depts = (typeof DEPARTMENTS !== "undefined" && Array.isArray(DEPARTMENTS) && DEPARTMENTS.length > 0)
      ? DEPARTMENTS
      : [{ id: "dev", name: "개발팀" }];

    depts.forEach(function(d){
      var curProj = (currentMap[d.id] && currentMap[d.id].project_key) || "";
      var curType = (currentMap[d.id] && currentMap[d.id].issue_type) || "";
      var curSub = (currentMap[d.id] && currentMap[d.id].subtask_type) || "";

      html += '<div style="display:flex; align-items:center; gap:8px; margin-bottom:8px; flex-wrap:wrap;">';
      html += '<span style="min-width:130px; font-weight:600;">' + escapeHtml(d.name) + ':</span>';
      
      html += '<select id="map_proj_' + d.id + '" style="padding:4px 8px; font-size:12px; border-radius:4px; border:1px solid var(--border-color);">';
      html += '<option value="">(프로젝트 선택)</option>';
      projs.forEach(function(p){
        var sel = (p.key === curProj) ? ' selected' : '';
        html += '<option value="' + escapeHtml(p.key) + '"' + sel + '>' + escapeHtml(p.key) + ' (' + escapeHtml(p.name) + ')</option>';
      });
      html += '</select>';

      html += '<select id="map_type_' + d.id + '" style="padding:4px 8px; font-size:12px; border-radius:4px; border:1px solid var(--border-color);">';
      html += '<option value="">(기본 이슈 유형)</option>';
      standardTypes.forEach(function(t){
        var sel = (t.name === curType) ? ' selected' : '';
        html += '<option value="' + escapeHtml(t.name) + '"' + sel + '>' + escapeHtml(t.name) + '</option>';
      });
      html += '</select>';

      html += '<select id="map_sub_' + d.id + '" style="padding:4px 8px; font-size:12px; border-radius:4px; border:1px solid var(--border-color);">';
      html += '<option value="">(하위작업 유형)</option>';
      subtaskTypes.forEach(function(st){
        var sel = (st.name === curSub) ? ' selected' : '';
        html += '<option value="' + escapeHtml(st.name) + '"' + sel + '>' + escapeHtml(st.name) + '</option>';
      });
      html += '</select>';

      html += '</div>';
    });

    html += '<button type="button" class="btn-settings-sync" id="btnApplyJiraMapping" style="margin-top:6px; padding:5px 14px; font-size:12px;">매핑 반영</button>';
    html += '</div></div>';

    resBox.innerHTML = html;

    var btnApply = document.getElementById("btnApplyJiraMapping");
    if (btnApply) {
      btnApply.addEventListener("click", function(){
        depts.forEach(function(d){
          var pEl = document.getElementById("map_proj_" + d.id);
          var tEl = document.getElementById("map_type_" + d.id);
          var sEl = document.getElementById("map_sub_" + d.id);
          if (pEl && pEl.value) {
            window.CURRENT_JIRA_PROJECT_MAP[d.id] = {
              project_key: pEl.value,
              issue_type: tEl ? tEl.value : "",
              subtask_type: sEl ? sEl.value : ""
            };
          }
        });
        showToast("Jira 부서 매핑이 반영되었습니다. '설정 저장' 버튼을 눌러 확정하세요.");
      });
    }

  } catch (err) {
    resBox.innerHTML = '<div style="color:var(--danger, #e53935);">❌ 연결 오류: ' + escapeHtml(err.message) + '</div>';
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = '<span>🔍</span> 연결 테스트 & 자동 스캔';
    }
  }
}

// ── Report Template Engine ────────────────────────────────────
async function checkReportTemplateStatus() {
  var badge = document.getElementById("badgeReportTemplateStatus");
  var infoEl = document.getElementById("templateCurrentInfo");
  var detailEl = document.getElementById("templateDetailInfo");
  var btnReset = document.getElementById("btnResetTemplate");

  try {
    var authH = (typeof getAuthHeaders === "function") ? getAuthHeaders() : {};
    var res = await fetch("/api/reports/template/info", {
      headers: authH
    });
    if (res.ok) {
      var data = await res.json();
      if (data && data.has_custom_template) {
        if (badge) { badge.className = "card-badge connected"; badge.textContent = "커스텀 템플릿 사용"; }
        if (infoEl) infoEl.textContent = "현재 서식: 커스텀 엑셀 템플릿 (" + (data.template_name || "") + ")";
        if (detailEl) detailEl.textContent = "크기: " + (data.size_bytes ? Math.round(data.size_bytes/1024) + " KB" : "") + " | 수정일: " + (data.modified_at ? data.modified_at.slice(0, 16).replace("T", " ") : "");
        if (btnReset) btnReset.style.display = "inline-block";
      } else {
        if (badge) { badge.className = "card-badge"; badge.textContent = "기본 서식"; }
        if (infoEl) infoEl.textContent = "현재 서식: 기본 내장 R&D 서식";
        if (detailEl) detailEl.textContent = "별도 등록된 템플릿이 없을 경우 표준 서식으로 생성됩니다.";
        if (btnReset) btnReset.style.display = "none";
      }
    }
  } catch(e){}
}

function initReportTemplateEngine() {
  var btnUpload = document.getElementById("btnUploadTemplate");
  var fileInput = document.getElementById("inputTemplateFile");
  var uploadStatus = document.getElementById("templateUploadStatus");
  var btnDownloadSample = document.getElementById("btnDownloadSampleTemplate");
  var btnReset = document.getElementById("btnResetTemplate");

  if (btnUpload && fileInput) {
    btnUpload.addEventListener("click", function(){
      fileInput.value = "";
      fileInput.click();
    });

    fileInput.addEventListener("change", async function(){
      if (!fileInput.files || fileInput.files.length === 0) return;
      var file = fileInput.files[0];
      if (!file.name.toLowerCase().endsWith(".xlsx")) {
        alert("Excel 통합 문서(.xlsx) 파일만 업로드할 수 있습니다.");
        return;
      }

      if (uploadStatus) uploadStatus.textContent = "템플릿 업로드 및 검증 중...";
      btnUpload.disabled = true;

      try {
        var formData = new FormData();
        formData.append("template", file);
        var authH = (typeof getAuthHeaders === "function") ? getAuthHeaders() : {};
        var csrfToken = sessionStorage.getItem("argosCsrfToken") || localStorage.getItem("argosCsrfToken");
        if(csrfToken) authH["X-CSRF-Token"] = csrfToken;
        var resp = await fetch("/api/reports/template", {
          method: "POST",
          headers: authH,
          credentials: "same-origin",
          body: formData
        });
        var result = await resp.json();
        if (result && result.ok) {
          showToast("커스텀 보고서 템플릿이 성공적으로 등록되었습니다!");
          if (uploadStatus) uploadStatus.textContent = "✅ 등록 완료";
          await checkReportTemplateStatus();
        } else {
          alert("업로드 실패: " + ((result && result.error) || "알 수 없는 오류"));
          if (uploadStatus) uploadStatus.textContent = "❌ 실패";
        }
      } catch (err) {
        alert("업로드 중 오류: " + err.message);
        if (uploadStatus) uploadStatus.textContent = "❌ 오류";
      } finally {
        btnUpload.disabled = false;
        setTimeout(function(){ if (uploadStatus) uploadStatus.textContent = ""; }, 4000);
      }
    });
  }

  if (btnDownloadSample) {
    btnDownloadSample.addEventListener("click", function(){
      var authH = (typeof getAuthHeaders === "function") ? getAuthHeaders() : {};
      var token = (authH["Authorization"] || "").replace(/^Bearer\s+/i, "");
      window.open("/api/reports/template/sample", "_blank");
    });
  }

  if (btnReset) {
    btnReset.addEventListener("click", async function(){
      if (!confirm("커스텀 템플릿을 삭제하고 기본 내장 서식으로 복원하시겠습니까?")) return;
      try {
        var result = await apiPostJson("/api/reports/template/delete", {});
        if (result && result.ok) {
          showToast("기본 서식으로 복원되었습니다.");
          await checkReportTemplateStatus();
        } else {
          alert("복원 실패: " + ((result && result.error) || "알 수 없는 오류"));
        }
      } catch (err) {
        alert("오류: " + err.message);
      }
    });
  }
}

// Event Bindings
document.addEventListener("DOMContentLoaded", function () {
  var btnSave = document.getElementById("btnSaveSettings");
  if (btnSave) btnSave.addEventListener("click", saveSettings);

  var btnTest = document.getElementById("btnTestConnections");
  if (btnTest) btnTest.addEventListener("click", testConnections);

  var btnSync = document.getElementById("btnSyncVectors");
  if (btnSync) btnSync.addEventListener("click", syncVectors);

  var btnJiraWizard = document.getElementById("btnJiraWizardInspect");
  if (btnJiraWizard) btnJiraWizard.addEventListener("click", inspectJiraWizard);

  initReportTemplateEngine();

  var setAiProvider = document.getElementById("setAiProvider");
  if (setAiProvider) setAiProvider.addEventListener("change", onAiProviderChange);

  var setAiFallbackProvider = document.getElementById("setAiFallbackProvider");
  if (setAiFallbackProvider) setAiFallbackProvider.addEventListener("change", onAiFallbackProviderChange);

  var setVoyageProvider = document.getElementById("setVoyageProvider");
  if (setVoyageProvider) setVoyageProvider.addEventListener("change", onVoyageProviderChange);

  var setAiFallbackEnabled = document.getElementById("setAiFallbackEnabled");
  if (setAiFallbackEnabled) {
    setAiFallbackEnabled.addEventListener("change", function () {
      var box = document.getElementById("aiFallbackFields");
      if (box) box.style.display = setAiFallbackEnabled.checked ? "block" : "none";
    });
  }

  var setJiraEnabled = document.getElementById("setJiraEnabled");
  if (setJiraEnabled) {
    setJiraEnabled.addEventListener("change", function () {
      var box = document.getElementById("jiraConfigBody");
      if (box) box.style.display = setJiraEnabled.checked ? "block" : "none";
    });
  }

  // Work Categories Table in Settings
  var btnSettingsAdd = document.getElementById("btnSettingsAddCategory");
  if (btnSettingsAdd) {
    btnSettingsAdd.addEventListener("click", function(){
      if (typeof openDeptModal === "function") openDeptModal(null);
    });
  }

  initSettingsSubtabs();
  renderSettingsCategoryTable();
  initBackupUI();
  initLicenseUI();
});

// ── Settings Sub-Tabs System ───────────────────────────────────

function updateSettingsSubtabsScrollArrows() {
  var nav = document.getElementById("settingsSubtabsNav");
  var wrap = document.getElementById("settingsSubtabsWrap");
  var prevBtn = document.getElementById("btnSettingsSubtabsPrev");
  var nextBtn = document.getElementById("btnSettingsSubtabsNext");
  if (!nav || !wrap) return;

  var maxScroll = Math.max(0, nav.scrollWidth - nav.clientWidth);
  var canScrollLeft = nav.scrollLeft > 6;
  var canScrollRight = (maxScroll - nav.scrollLeft) > 6;

  if (prevBtn) prevBtn.style.display = canScrollLeft ? "flex" : "none";
  if (nextBtn) nextBtn.style.display = canScrollRight ? "flex" : "none";

  wrap.classList.toggle("has-overflow-left", canScrollLeft);
  wrap.classList.toggle("has-overflow-right", canScrollRight);
}
window.updateSettingsSubtabsScrollArrows = updateSettingsSubtabsScrollArrows;

function isCurrentUserAdmin() {
  if (typeof window.getCurrentUser === "function") {
    var u = window.getCurrentUser();
    if (u) return Boolean(u.isAdmin || u.role === "admin" || u.is_admin);
  }
  var curUser = null;
  try {
    curUser = JSON.parse(localStorage.getItem("argosUser") || sessionStorage.getItem("argosUser") || localStorage.getItem("jarvisUser") || sessionStorage.getItem("jarvisUser") || "{}");
  } catch (e) {}
  return Boolean(curUser && (curUser.isAdmin || curUser.role === "admin" || curUser.is_admin));
}
window.isCurrentUserAdmin = isCurrentUserAdmin;

function isCurrentUserManagerOrAdmin() {
  if (typeof window.getCurrentUser === "function") {
    var u = window.getCurrentUser();
    if (u) return Boolean(u.isAdmin || u.role === "admin" || u.is_admin || u.role === "manager" || u.isManager);
  }
  var curUser = null;
  try {
    curUser = JSON.parse(localStorage.getItem("argosUser") || sessionStorage.getItem("argosUser") || localStorage.getItem("jarvisUser") || sessionStorage.getItem("jarvisUser") || "{}");
  } catch (e) {}
  return Boolean(curUser && (curUser.isAdmin || curUser.role === "admin" || curUser.is_admin || curUser.role === "manager" || curUser.isManager));
}
window.isCurrentUserManagerOrAdmin = isCurrentUserManagerOrAdmin;

function initSettingsSubtabs() {
  var tabBtns = document.querySelectorAll(".settings-subtab-btn");
  if (!tabBtns || tabBtns.length === 0) return;

  // Role-based visibility check:
  // 'API 및 외부 연동' (integrations), '보안 & DB 백업' (security), '사용자 & 권한 (RBAC)' (users) are strictly admin-only.
  var isAdm = isCurrentUserAdmin();

  var btnIntegrations = document.querySelector('.settings-subtab-btn[data-settings-tab="integrations"]');
  var btnCategories = document.querySelector('.settings-subtab-btn[data-settings-tab="categories"]');
  var btnSecurity = document.querySelector('.settings-subtab-btn[data-settings-tab="security"]');
  var btnUsers = document.querySelector('.settings-subtab-btn[data-settings-tab="users"]');
  var btnAiUsage = document.querySelector('.settings-subtab-btn[data-settings-tab="ai_usage"]');
  var btnAudit = document.querySelector('.settings-subtab-btn[data-settings-tab="audit"]');
  var btnLicense = document.querySelector('.settings-subtab-btn[data-settings-tab="license"]');

  if (btnIntegrations) btnIntegrations.style.display = isAdm ? "" : "none";
  if (btnCategories) btnCategories.style.display = isAdm ? "" : "none";
  if (btnSecurity) btnSecurity.style.display = isAdm ? "" : "none";
  if (btnUsers) btnUsers.style.display = isAdm ? "" : "none";
  if (btnAiUsage) btnAiUsage.style.display = isAdm ? "" : "none";
  if (btnAudit) btnAudit.style.display = isAdm ? "" : "none";
  if (btnLicense) btnLicense.style.display = isAdm ? "" : "none";
  var btnAddCat = document.getElementById("btnSettingsAddCategory");
  if (btnAddCat) btnAddCat.style.display = isAdm ? "" : "none";

  tabBtns.forEach(function (btn) {
    if (btn.__subtabBound) return;
    btn.__subtabBound = true;
    btn.addEventListener("click", function () {
      var tabName = btn.getAttribute("data-settings-tab");
      var admNow = isCurrentUserAdmin();
      if (!admNow && (tabName === "integrations" || tabName === "categories" || tabName === "security" || tabName === "users" || tabName === "ai_usage" || tabName === "audit" || tabName === "license")) {
        return;
      }
      switchSettingsTab(tabName);
    });
  });

  var savedTab = isAdm ? "integrations" : "product_categories";
  try {
    savedTab = sessionStorage.getItem("argos_settings_tab") || (isAdm ? "integrations" : "product_categories");
    if (savedTab === "all") savedTab = isAdm ? "integrations" : "product_categories";
    if (!isAdm && (savedTab === "integrations" || savedTab === "categories" || savedTab === "security" || savedTab === "users" || savedTab === "ai_usage" || savedTab === "audit" || savedTab === "license")) {
      savedTab = "product_categories";
    }
  } catch (e) {}

  switchSettingsTab(savedTab);

  // Setup subtabs scroll buttons and listeners
  var nav = document.getElementById("settingsSubtabsNav");
  var prevBtn = document.getElementById("btnSettingsSubtabsPrev");
  var nextBtn = document.getElementById("btnSettingsSubtabsNext");

  if (nav) {
    nav.addEventListener("scroll", updateSettingsSubtabsScrollArrows, { passive: true });
    window.addEventListener("resize", updateSettingsSubtabsScrollArrows, { passive: true });

    if (prevBtn) {
      prevBtn.addEventListener("click", function () {
        nav.scrollBy({ left: -160, behavior: "smooth" });
      });
    }

    if (nextBtn) {
      nextBtn.addEventListener("click", function () {
        nav.scrollBy({ left: 160, behavior: "smooth" });
      });
    }

    // Drag-to-scroll swipe support (allows dragging with mouse/finger across devices)
    var isDown = false;
    var startX = 0;
    var scrollLeft = 0;
    var hasDragged = false;

    nav.addEventListener("mousedown", function(e) {
      isDown = true;
      hasDragged = false;
      startX = e.pageX - nav.offsetLeft;
      scrollLeft = nav.scrollLeft;
    });

    window.addEventListener("mouseup", function() {
      if (!isDown) return;
      isDown = false;
    });

    window.addEventListener("mousemove", function(e) {
      if (!isDown || !nav) return;
      var x = e.pageX - nav.offsetLeft;
      var walk = (x - startX) * 1.4;
      if (Math.abs(walk) > 4) {
        hasDragged = true;
      }
      nav.scrollLeft = scrollLeft - walk;
    });

    // Prevent accidental tab switch click when dragging
    nav.addEventListener("click", function(e) {
      if (hasDragged) {
        e.preventDefault();
        e.stopPropagation();
        hasDragged = false;
      }
    }, true);

    setTimeout(updateSettingsSubtabsScrollArrows, 60);
    setTimeout(updateSettingsSubtabsScrollArrows, 300);
  }

  // Make status pills clickable
  var clickablePills = document.querySelectorAll(".settings-status-bar .status-pill[data-jump-tab]");
  clickablePills.forEach(function (pill) {
    pill.addEventListener("click", function () {
      var tabName = pill.getAttribute("data-jump-tab") || "integrations";
      var cardId = pill.getAttribute("data-jump-card");
      switchSettingsTab(tabName);
      if (cardId) {
        setTimeout(function () {
          var targetCard = document.getElementById(cardId);
          if (targetCard) {
            targetCard.scrollIntoView({ behavior: "smooth", block: "start" });
            targetCard.classList.add("highlight-card");
            setTimeout(function () { targetCard.classList.remove("highlight-card"); }, 1500);
          }
        }, 60);
      }
    });
  });
}

function switchSettingsTab(tabName) {
  var isAdm = isCurrentUserAdmin();
  var msgEl = document.getElementById("settingsMsg");
  if (!isAdm && msgEl) {
    msgEl.className = "settings-msg";
    msgEl.textContent = "";
  }

  var validTabs = isAdm
    ? ["integrations", "categories", "product_categories", "template", "security", "users", "ai_usage", "audit", "license"]
    : ["product_categories", "template"];

  if (!tabName || validTabs.indexOf(tabName) === -1) {
    tabName = isAdm ? "integrations" : "product_categories";
  }

  var actionsBar = document.getElementById("settingsActionsBar");
  if (actionsBar) {
    actionsBar.style.display = (isAdm && tabName === "integrations") ? "" : "none";
  }

  var buttons = document.querySelectorAll(".settings-subtab-btn");
  buttons.forEach(function (btn) {
    var isCurrent = (btn.getAttribute("data-settings-tab") === tabName);
    btn.classList.toggle("active", isCurrent);
    btn.setAttribute("aria-selected", isCurrent ? "true" : "false");
    if (isCurrent && typeof btn.scrollIntoView === "function") {
      try {
        btn.scrollIntoView({ behavior: "smooth", inline: "center", block: "nearest" });
      } catch (e) {}
    }
  });

  var panes = document.querySelectorAll(".settings-tab-pane");
  panes.forEach(function (pane) {
    var match = (pane.getAttribute("data-pane") === tabName);
    pane.hidden = !match;
    pane.style.display = match ? "" : "none";
  });

  if (tabName === "categories") {
    if (typeof renderSettingsCategoryTable === "function") {
      renderSettingsCategoryTable();
    }
  } else if (tabName === "product_categories") {
    if (typeof loadSettingsProductCategories === "function") {
      loadSettingsProductCategories();
    }
  } else if (tabName === "security") {
    if (typeof loadAdminBackups === "function") {
      loadAdminBackups();
    }
  } else if (tabName === "users") {
    if (typeof loadAdminUsers === "function") {
      loadAdminUsers();
    }
  } else if (tabName === "ai_usage") {
    if (typeof window.loadAiUsageStats === "function") {
      window.loadAiUsageStats();
    }
  } else if (tabName === "audit") {
    if (typeof window.loadAuditLogs === "function") {
      window.loadAuditLogs();
    }
  } else if (tabName === "license") {
    if (typeof loadLicenseStatus === "function") {
      loadLicenseStatus();
    }
  }

  try {
    sessionStorage.setItem("argos_settings_tab", tabName);
  } catch (e) {}

  setTimeout(updateSettingsSubtabsScrollArrows, 80);
}

window.switchSettingsTab = switchSettingsTab;
window.openSettingsTab = function (tabName, cardId) {
  if (typeof showTab === "function") showTab("settings");
  switchSettingsTab(tabName);
  if (cardId) {
    setTimeout(function () {
      var targetCard = document.getElementById(cardId);
      if (targetCard) {
        targetCard.scrollIntoView({ behavior: "smooth", block: "start" });
        targetCard.classList.add("highlight-card");
        setTimeout(function () { targetCard.classList.remove("highlight-card"); }, 1500);
      }
    }, 60);
  }
};

// Render Settings Category Management Table
function renderSettingsCategoryTable() {
  var tbody = document.getElementById("settingsCategoryTableBody");
  if (!tbody) return;

  var isAdm = (typeof isCurrentUserAdmin === "function") && isCurrentUserAdmin();
  var btnAddCat = document.getElementById("btnSettingsAddCategory");
  if (btnAddCat) {
    btnAddCat.style.display = isAdm ? "" : "none";
  }

  var depts = window.DEPARTMENTS || [];
  var recs = window.records || [];

  var isJiraActive = (typeof isJiraIntegrationActive === "function")
    ? isJiraIntegrationActive()
    : Boolean(window.__JIRA_STATUS__ && window.__JIRA_STATUS__.enabled);

  var thJira = document.getElementById("thSettingsCategoryJiraKey");
  if(thJira) thJira.style.display = isJiraActive ? "" : "none";

  if (depts.length === 0) {
    var colSpan = isJiraActive ? 6 : 5;
    tbody.innerHTML = '<tr><td colspan="' + colSpan + '" style="text-align:center; padding:18px; color:var(--ink-faint, #64748b);">등록된 부서가 없습니다.</td></tr>';
    return;
  }

  var html = depts.map(function(d){
    var cnt = recs.filter(function(r){ return r.org === d.id; }).length;
    var t = (window.i18n && window.i18n.t) ? window.i18n.t : function(k){ return k; };

    var jiraTd = isJiraActive
      ? ('<td style="padding: 10px; font-family: monospace;">' + (d.jiraKey ? '<span style="background:rgba(2,132,199,0.1); color:var(--accent-2, #0284c7); padding:2px 6px; border-radius:4px; font-weight:600;">' + escapeHtml(d.jiraKey) + '</span>' : '-') + '</td>')
      : '';

    var actionTdHtml = "";
    if (isAdm) {
      var delBtnHtml = (cnt === 0)
        ? '<button type="button" class="btn-table-action btn-table-del" data-settings-del-dept="' + escapeHtml(d.id) + '" style="background:none; border:1px solid #ef4444; color:#ef4444; border-radius:4px; padding:3px 8px; font-size:11px; cursor:pointer; font-weight:600;">' + escapeHtml(t("dept.del_btn")) + '</button>'
        : '<span style="font-size:11px; color:var(--ink-faint, #94a3b8); margin-left:4px;" title="작업이 있어 삭제 불가">참조중</span>';

      actionTdHtml = (
        '<td style="padding: 10px; text-align: right; white-space: nowrap;">' +
          '<button type="button" class="btn-table-action btn-table-edit" data-settings-edit-dept="' + escapeHtml(d.id) + '" style="background:var(--code-bg, rgba(0,0,0,0.06)); border:1px solid var(--line, #cbd5e1); color:var(--ink); border-radius:4px; padding:3px 8px; font-size:11px; cursor:pointer; font-weight:600; margin-right:6px;">' + escapeHtml(t("dept.edit_btn")) + '</button>' +
          delBtnHtml +
        '</td>'
      );
    } else {
      actionTdHtml = (
        '<td style="padding: 10px; text-align: right; white-space: nowrap;">' +
          '<span style="font-size:11px; color:var(--ink-faint, #94a3b8); background:var(--code-bg, rgba(0,0,0,0.04)); padding:3px 8px; border-radius:4px; border:1px solid var(--line, #e2e8f0); font-weight:500;">조회 전용</span>' +
        '</td>'
      );
    }

    return (
      '<tr style="border-bottom: 1px solid var(--line, #e2e8f0);">' +
        '<td style="padding: 10px; font-family: monospace; color: var(--ink-faint, #64748b);">' + escapeHtml(d.id) + '</td>' +
        '<td style="padding: 10px; font-weight: 600; color: var(--ink);">' +
          '<span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:' + colorVar(d.colorIndex) + '; margin-right:6px;"></span>' +
          escapeHtml(d.name) +
        '</td>' +
        '<td style="padding: 10px; font-family: monospace;">' + (d.localPrefix ? '<span style="background:var(--code-bg, rgba(0,0,0,0.05)); padding:2px 6px; border-radius:4px;">' + escapeHtml(d.localPrefix) + '</span>' : '-') + '</td>' +
        jiraTd +
        '<td style="padding: 10px; text-align: center; font-weight: 700; font-variant-numeric: tabular-nums;">' + cnt + '</td>' +
        actionTdHtml +
      '</tr>'
    );
  }).join("");

  tbody.innerHTML = html;
}

window.renderSettingsCategoryTable = renderSettingsCategoryTable;

// Event delegation for Settings Category Table
document.addEventListener("click", function(e){
  var editBtn = e.target.closest("[data-settings-edit-dept]");
  if(editBtn){
    if (typeof isCurrentUserAdmin === "function" && !isCurrentUserAdmin()) return;
    var id = editBtn.getAttribute("data-settings-edit-dept");
    var deptObj = deptById(id);
    if(deptObj && typeof openDeptModal === "function"){
      openDeptModal(deptObj);
    }
    return;
  }

  var delBtn = e.target.closest("[data-settings-del-dept]");
  if(delBtn){
    if (typeof isCurrentUserAdmin === "function" && !isCurrentUserAdmin()) return;
    var delId = delBtn.getAttribute("data-settings-del-dept");
    var deptObj = deptById(delId);
    var dName = deptObj ? deptObj.name : delId;
    var t = (window.i18n && window.i18n.t) ? window.i18n.t : function(k){ return k; };
    if(confirm(t("dept.toast_del_confirm", { name: dName }))){
      apiPostJson("/api/departments/delete", { id: delId }).then(function(res){
        if(res.ok){
          DEPARTMENTS = res.departments;
          if(selectedDeptForAssignee === delId) selectedDeptForAssignee = null;
          renderDeptCards();
          renderOrgChips();
          renderOrgSelectOptions();
          if(typeof renderIdOrgOptions === "function") renderIdOrgOptions();
          renderSettingsCategoryTable();
          showToast(t("dept.toast_deleted", { name: dName }));
        } else {
          showToast(res.error || t("dept.toast_failed"));
        }
      }).catch(function(){
        showToast(t("common.server_error"));
      });
    }
  }
});

// ============================================================================
// Product Category & Spec Template Management (제품 규격 템플릿 빌더)
// ============================================================================
window.SETTINGS_PRODUCT_CATEGORIES = [];

async function loadSettingsProductCategories() {
  if (!isCurrentUserManagerOrAdmin()) return;
  try {
    var res = await apiGet("/api/products/categories/admin");
    if (res && res.ok) {
      window.SETTINGS_PRODUCT_CATEGORIES = res.categories || [];
      renderSettingsProductCategoryTable();
    }
  } catch (err) {
    console.error("Failed to load product categories for settings:", err);
  }
}
window.loadSettingsProductCategories = loadSettingsProductCategories;

function renderSettingsProductCategoryTable() {
  var tbody = document.getElementById("settingsProductCategoryTableBody");
  if (!tbody) return;

  var cats = window.SETTINGS_PRODUCT_CATEGORIES || [];
  if (cats.length === 0) {
    tbody.innerHTML = '<tr><td colspan="3" style="text-align:center; padding:24px; color:var(--ink-faint, #64748b);">등록된 제품 카테고리가 없습니다. 우측 상단의 [➕ 새 카테고리 추가]를 눌러 추가하세요.</td></tr>';
    return;
  }

  var html = cats.map(function(c) {
    var rawTpl = c.spec_template || [];
    var tpl = rawTpl.map(function(f) {
      if (typeof f === "string") {
        return { group: "", label: f, key: f };
      }
      if (f && typeof f === "object") {
        var lbl = f.label || f.name || f.key || "";
        var grp = f.group || "";
        var ky = f.key || (lbl ? lbl.toLowerCase().replace(/[^a-zA-Z0-9]/g, "_").replace(/^_+|_+$/g, "") : "");
        return { group: grp, label: lbl, key: ky };
      }
      return null;
    }).filter(Boolean);

    var fieldsBadges = "";
    if (tpl.length === 0) {
      fieldsBadges = '<span class="prod-spec-empty-hint">기본 규격 없음 (자유 서술형)</span>';
    } else {
      fieldsBadges = '<div class="prod-spec-badges-wrap">' + tpl.map(function(f) {
        var groupPrefix = f.group ? ('<span class="spec-pill-group">' + escapeHtml(f.group) + '</span>') : '';
        return '<span class="prod-spec-badge">' +
          groupPrefix +
          '<strong class="spec-pill-label">' + escapeHtml(f.label) + '</strong>' +
        '</span>';
      }).join("") + '</div>';
    }

    return (
      '<tr class="settings-prod-cat-row">' +
        '<td class="prod-cat-cell-name">' +
          '<div class="prod-cat-name-box">' +
            '<span class="prod-cat-badge-icon">🏷️</span>' +
            '<div class="prod-cat-name-content">' +
              '<span class="prod-cat-title">' + escapeHtml(c.name) + '</span>' +
              (c.id ? ('<span class="prod-cat-id-code">' + escapeHtml(c.id) + '</span>') : '') +
            '</div>' +
          '</div>' +
        '</td>' +
        '<td class="prod-cat-cell-fields">' +
          fieldsBadges +
        '</td>' +
        '<td class="prod-cat-cell-actions">' +
          '<div class="prod-cat-actions-box">' +
            '<button type="button" class="btn-table-action btn-cat-edit" data-edit-prod-cat="' + escapeHtml(c.id) + '">수정</button>' +
            '<button type="button" class="btn-table-action btn-cat-del" data-del-prod-cat="' + escapeHtml(c.id) + '">삭제</button>' +
          '</div>' +
        '</td>' +
      '</tr>'
    );
  }).join("");

  tbody.innerHTML = html;
}
window.renderSettingsProductCategoryTable = renderSettingsProductCategoryTable;

// --- Modal & Spec Field Row Logic ---
(function initProductCategoryModalEvents() {
  var modal = document.getElementById("modalProductCategory");
  var btnOpen = document.getElementById("btnOpenAddProductCatModal");
  var btnClose = document.getElementById("btnProductCatModalClose");
  var btnCancel = document.getElementById("btnProductCatModalCancel");
  var btnAddRow = document.getElementById("btnAddSpecFieldRow");
  var form = document.getElementById("formProductCategory");
  var idInput = document.getElementById("productCatEditId");
  var nameInput = document.getElementById("productCatNameInput");
  var rowsBody = document.getElementById("specFieldsRowsBody");
  var errBox = document.getElementById("productCatModalError");
  var titleEl = document.getElementById("productCatModalTitle");

  function openModal(catObj) {
    if (!modal) return;
    if (errBox) { errBox.style.display = "none"; errBox.textContent = ""; }
    if (rowsBody) rowsBody.innerHTML = "";

    if (catObj) {
      if (titleEl) titleEl.textContent = "제품 카테고리 및 규격 수정";
      if (idInput) idInput.value = catObj.id || "";
      if (nameInput) nameInput.value = catObj.name || "";
      var rawTpl = catObj.spec_template || [];
      var usedKeys = catObj.used_keys || [];
      rawTpl.forEach(function(f) {
        var grp = (typeof f === "object" && f.group) ? f.group : "사양";
        var lbl = typeof f === "string" ? f : (f.label || f.name || f.key || "");
        var ky = typeof f === "string" ? f : (f.key || (lbl ? lbl.toLowerCase().replace(/[^a-zA-Z0-9]/g, "_").replace(/^_+|_+$/g, "") : ""));
        var locked = usedKeys.indexOf(ky) !== -1;
        addSpecRow(grp, lbl, ky, locked);
      });
    } else {
      if (titleEl) titleEl.textContent = "새 제품 카테고리 추가";
      if (idInput) idInput.value = "";
      if (nameInput) nameInput.value = "";
    }
    modal.hidden = false;
    if (nameInput) setTimeout(function() { nameInput.focus(); }, 60);
  }

  function closeModal() {
    if (modal) modal.hidden = true;
  }

  function addSpecRow(group, label, key, isLocked) {
    if (!rowsBody) return;
    var tr = document.createElement("tr");
    tr.style.borderBottom = "1px solid var(--border-color, #e2e8f0)";
    var delBtnHtml;
    if (isLocked) {
      delBtnHtml = '<span title="이 항목은 제품 데이터에 사용 중이므로 삭제할 수 없습니다" style="color:var(--ink-faint, #94a3b8); font-size:13px; cursor:not-allowed;">🔒</span>';
    } else {
      delBtnHtml = '<button type="button" class="btn-del-spec-row" style="background:none; border:none; color:#ef4444; font-size:14px; cursor:pointer;">✕</button>';
    }
    tr.innerHTML = (
      '<td style="padding: 6px 8px;">' +
        '<input type="text" class="spec-row-group" style="width:100%; padding:4px 6px; font-size:12px; border:1px solid var(--border-color, #cbd5e1); border-radius:4px;" placeholder="예: 사양" value="' + escapeHtml(group || "사양") + '">' +
      '</td>' +
      '<td style="padding: 6px 8px;">' +
        '<input type="text" class="spec-row-label" style="width:100%; padding:4px 6px; font-size:12px; border:1px solid var(--border-color, #cbd5e1); border-radius:4px;" placeholder="예: 정격 전원, 배터리" value="' + escapeHtml(label || "") + '">' +
      '</td>' +
      '<td style="padding: 6px 8px; display:none;">' +
        '<input type="text" class="spec-row-key" style="width:100%; padding:4px 6px; font-size:12px; font-family:monospace; border:1px solid var(--border-color, #cbd5e1); border-radius:4px;" value="' + escapeHtml(key || "") + '">' +
      '</td>' +
      '<td style="padding: 6px 8px; text-align: center;">' +
        delBtnHtml +
      '</td>'
    );
    rowsBody.appendChild(tr);
  }

  if (btnOpen) btnOpen.addEventListener("click", function() { openModal(null); });
  if (btnClose) btnClose.addEventListener("click", closeModal);
  if (btnCancel) btnCancel.addEventListener("click", closeModal);
  if (btnAddRow) btnAddRow.addEventListener("click", function() { addSpecRow("사양", "", ""); });

  if (rowsBody) {
    rowsBody.addEventListener("click", function(e) {
      var delBtn = e.target.closest(".btn-del-spec-row");
      if (delBtn) {
        var row = delBtn.closest("tr");
        if (row) row.remove();
      }
    });
  }

  // Click handler for Edit / Delete in settings table
  document.addEventListener("click", async function(e) {
    var editBtn = e.target.closest("[data-edit-prod-cat]");
    if (editBtn) {
      var editId = editBtn.getAttribute("data-edit-prod-cat");
      var target = (window.SETTINGS_PRODUCT_CATEGORIES || []).find(function(c) { return c.id === editId; });
      if (target) openModal(target);
      return;
    }

    var delBtn = e.target.closest("[data-del-prod-cat]");
    if (delBtn) {
      var delId = delBtn.getAttribute("data-del-prod-cat");
      var target = (window.SETTINGS_PRODUCT_CATEGORIES || []).find(function(c) { return c.id === delId; });
      var dName = target ? target.name : delId;
      if (confirm('"' + dName + '" 제품 카테고리를 삭제하시겠습니까?')) {
        try {
          var res = await apiPostJson("/api/products/categories/delete", { id: delId });
          if (res && res.ok) {
            window.SETTINGS_PRODUCT_CATEGORIES = res.categories || [];
            renderSettingsProductCategoryTable();
            showToast('"' + dName + '" 카테고리가 삭제되었습니다.');
            if (typeof loadPimCategories === "function") loadPimCategories();
          } else {
            showToast((res && res.error) || "카테고리 삭제에 실패했습니다.");
          }
        } catch (err) {
          showToast("오류가 발생했습니다: " + err.message);
        }
      }
      return;
    }
  });

  // Submit form
  if (form) {
    form.addEventListener("submit", async function(e) {
      e.preventDefault();
      var name = nameInput ? nameInput.value.trim() : "";
      var id = idInput ? idInput.value.trim() : "";

      if (!name) {
        if (errBox) { errBox.style.display = "block"; errBox.textContent = "카테고리명을 입력해주세요."; }
        return;
      }

      var specTemplate = [];
      var rows = rowsBody ? rowsBody.querySelectorAll("tr") : [];
      var keysSet = new Set();
      var autoIdx = 1;
      for (var i = 0; i < rows.length; i++) {
        var r = rows[i];
        var group = (r.querySelector(".spec-row-group") ? r.querySelector(".spec-row-group").value.trim() : "") || "사양";
        var label = (r.querySelector(".spec-row-label") ? r.querySelector(".spec-row-label").value.trim() : "");
        var key = (r.querySelector(".spec-row-key") ? r.querySelector(".spec-row-key").value.trim() : "");

        if (!label) continue;
        if (!key) {
          var slug = label.toLowerCase().replace(/[^a-zA-Z0-9]/g, "_").replace(/^_+|_+$/g, "");
          if (slug && !keysSet.has(slug)) {
            key = slug;
          } else {
            while (keysSet.has("spec_" + autoIdx)) { autoIdx++; }
            key = "spec_" + autoIdx;
            autoIdx++;
          }
        }
        if (keysSet.has(key)) {
          while (keysSet.has("spec_" + autoIdx)) { autoIdx++; }
          key = "spec_" + autoIdx;
          autoIdx++;
        }
        keysSet.add(key);

        specTemplate.push({
          group: group,
          label: label,
          key: key,
          maxlen: 100
        });
      }

      var submitBtn = document.getElementById("btnProductCatModalSubmit");
      if (submitBtn) submitBtn.disabled = true;
      if (errBox) { errBox.style.display = "none"; errBox.textContent = ""; }

      try {
        var res = await apiPostJson("/api/products/categories/save", {
          id: id,
          name: name,
          spec_template: specTemplate
        });
        if (res && res.ok) {
          showToast('"' + name + '" 제품 카테고리가 저장되었습니다.');
          closeModal();
          window.SETTINGS_PRODUCT_CATEGORIES = res.categories || [];
          renderSettingsProductCategoryTable();
          // Reload PIM dropdown dynamically in product tab
          if (typeof loadPimCategories === "function") loadPimCategories();
        } else {
          if (errBox) { errBox.style.display = "block"; errBox.textContent = (res && res.error) || "저장에 실패했습니다."; }
        }
      } catch (err) {
        if (errBox) { errBox.style.display = "block"; errBox.textContent = "오류: " + err.message; }
      } finally {
        if (submitBtn) submitBtn.disabled = false;
      }
    });
  }
})();

// ── Enterprise Security & Disaster Recovery Backup System ────────
async function loadAdminBackups() {
  var tbody = document.getElementById("backupListTableBody");
  var statsEl = document.getElementById("backupDbStatsText");
  var bannerHttpsWarning = document.getElementById("bannerHttpsWarning");
  if (!tbody) return;

  var btnManual = document.getElementById("btnTriggerManualBackup");
  var isAdm = isCurrentUserAdmin();
  if (btnManual) {
    btnManual.style.display = isAdm ? "inline-flex" : "none";
  }

  try {
    var authH = (typeof getAuthHeaders === "function") ? getAuthHeaders() : {};
    var res = await fetch("/api/admin/backups", { headers: authH });
    if (!res.ok) {
      if (btnManual) btnManual.style.display = "none";
      if (res.status === 403) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; color:var(--text-muted); padding:20px;">' +
          '🔒 보안 및 백업 관리는 관리자(Admin) 권한이 필요합니다.</td></tr>';
      } else {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; color:var(--danger, #e53935); padding:20px;">' +
          '백업 정보를 불러오지 못했습니다.</td></tr>';
      }
      return;
    }
    var data = await res.json();
    if (!data.ok) {
      tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; color:var(--danger, #e53935); padding:20px;">' +
        escapeHtml(data.error || "오류") + '</td></tr>';
      return;
    }

    var backups = data.backups || [];
    var sec = data.security || {};

    var inputDir = document.getElementById("inputBackupDir");
    var badgeCustom = document.getElementById("badgeBackupDirCustom");
    var btnSaveDir = document.getElementById("btnSaveBackupDir");
    var btnResetDir = document.getElementById("btnResetBackupDir");
    var btnImport = document.getElementById("btnImportBackup");

    if (inputDir) {
      inputDir.value = sec.backup_dir || "";
      inputDir.disabled = !isAdm;
    }
    if (badgeCustom) {
      badgeCustom.style.display = sec.is_custom_backup_dir ? "inline-block" : "none";
    }
    if (btnSaveDir) btnSaveDir.style.display = isAdm ? "inline-block" : "none";
    if (btnResetDir) btnResetDir.style.display = isAdm ? "inline-block" : "none";
    if (btnImport) btnImport.style.display = isAdm ? "inline-flex" : "none";

    if (statsEl) {
      var kb = Math.round((sec.db_size || 0) / 1024);
      var mb = (kb / 1024).toFixed(2);
      statsEl.innerHTML = '<strong>현재 CSDL 크기:</strong> ' + (mb >= 1 ? mb + ' MB' : kb + ' KB') + ' (총 ' + backups.length + '개 백업 보관 중)';
    }

    if (bannerHttpsWarning) {
      var isHttps = (sec && sec.https_active) || window.location.protocol === "https:";
      bannerHttpsWarning.style.display = isHttps ? "none" : "flex";
    }

    if (backups.length === 0) {
      tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; color:var(--text-muted); padding:24px;">' +
        '저장된 백업 파일이 없습니다. [즉시 백업 생성]을 클릭하여 첫 백업을 생성하세요.</td></tr>';
      return;
    }

    var html = "";
    backups.forEach(function (b) {
      var sizeKb = Math.round((b.gz_size || 0) / 1024);
      var sizeText = sizeKb >= 1024 ? (sizeKb / 1024).toFixed(2) + " MB" : sizeKb + " KB";
      var typeBadge = "";
      if (b.type === "auto") {
        typeBadge = '<span style="background:rgba(56,189,248,0.12); color:var(--stat-info, #38bdf8); border:1px solid rgba(56,189,248,0.25); padding:2px 8px; border-radius:12px; font-size:11px; font-weight:700;">자동</span>';
      } else if (b.type === "safety") {
        typeBadge = '<span style="background:rgba(168,85,247,0.12); color:#c084fc; border:1px solid rgba(168,85,247,0.25); padding:2px 8px; border-radius:12px; font-size:11px; font-weight:700;">안전본</span>';
      } else {
        typeBadge = '<span style="background:rgba(34,197,94,0.12); color:#4ade80; border:1px solid rgba(34,197,94,0.25); padding:2px 8px; border-radius:12px; font-size:11px; font-weight:700;">수동</span>';
      }

      var dt = (b.created_at || "").slice(0, 19).replace("T", " ");

      html += '<tr>';
      html += '<td style="font-family:monospace; font-weight:600; font-size:12px; color:var(--ink);">' + escapeHtml(b.filename) + '</td>';
      html += '<td style="font-size:12px; color:var(--text-muted);">' + escapeHtml(dt) + '</td>';
      html += '<td style="text-align:center;">' + typeBadge + '</td>';
      html += '<td style="text-align:right; font-weight:600; font-size:12px;">' + sizeText + '</td>';
      html += '<td style="font-size:12px; color:var(--text-muted);">' + escapeHtml(b.note || "-") + '</td>';
      html += '<td style="text-align:right; white-space:nowrap;">';
      html += '<button type="button" onclick="triggerRestoreBackup(\'' + escapeHtml(b.filename) + '\')" style="padding:4px 9px; font-size:11.5px; margin-right:6px; font-weight:600; color:#ef4444; background:rgba(239,68,68,0.1); border:1px solid rgba(239,68,68,0.28); border-radius:6px; cursor:pointer;">복구</button>';
      html += '<button type="button" onclick="downloadBackupFile(\'' + escapeHtml(b.filename) + '\')" style="padding:4px 9px; font-size:11.5px; font-weight:600; color:var(--ink-soft); background:var(--code-bg); border:1px solid var(--line); border-radius:6px; cursor:pointer;">다운로드</button>';
      html += '</td>';
      html += '</tr>';
    });

    tbody.innerHTML = html;
  } catch (err) {
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; color:var(--danger, #e53935); padding:20px;">오류: ' + escapeHtml(err.message) + '</td></tr>';
  }
}

async function triggerRestoreBackup(filename) {
  if (!confirm("⚠️ 주의: [" + filename + "] 백업으로 CSDL을 복구하시겠습니까?\n\n현재 데이터베이스는 복구 전 안전 스냅샷으로 자동 보관됩니다.")) {
    return;
  }

  showToast("⏳ 1-Click CSDL 복구 진행 중...");
  try {
    var data = await apiPostJson("/api/admin/backups/restore", { filename: filename });
    if (data && data.ok) {
      alert("✅ CSDL 복구가 성공적으로 완료되었습니다!\n(복원 전 안전 백업: " + (data.safety_backup || "완료") + ")\n\n화면을 새로고침합니다.");
      window.location.reload();
    } else {
      alert("❌ 복구 실패: " + ((data && data.error) || "알 수 없는 오류"));
    }
  } catch (err) {
    alert("❌ 복구 통신 오류: " + err.message);
  }
}

function downloadBackupFile(filename) {
  var authH = (typeof getAuthHeaders === "function") ? getAuthHeaders() : {};
  var token = (authH["Authorization"] || "").replace(/^Bearer\s+/i, "");
  window.open("/api/admin/backups/download?filename=" + encodeURIComponent(filename), "_blank");
}

function initBackupUI() {
  var btnManual = document.getElementById("btnTriggerManualBackup");
  if (btnManual) {
    btnManual.addEventListener("click", async function () {
      var note = prompt("백업에 대한 메모/설명을 입력하세요:", "관리자 즉시 수동 백업");
      if (note === null) return;
      btnManual.disabled = true;
      btnManual.innerHTML = "<span>⏳</span> 백업 생성 중...";
      try {
        var data = await apiPostJson("/api/admin/backups/create", { note: note });
        if (data && data.ok) {
          showToast("✅ 새 백업이 안전하게 생성되었습니다: " + data.filename);
          await loadAdminBackups();
        } else {
          alert("백업 생성 실패: " + ((data && data.error) || "알 수 없는 오류"));
        }
      } catch (err) {
        alert("통신 오류: " + err.message);
      } finally {
        btnManual.disabled = false;
        btnManual.innerHTML = "<span>⚡</span> 즉시 백업 생성";
      }
    });
  }

  // Backup Storage Directory Configuration
  var btnSaveDir = document.getElementById("btnSaveBackupDir");
  var btnResetDir = document.getElementById("btnResetBackupDir");
  var inputDir = document.getElementById("inputBackupDir");
  var badgeCustom = document.getElementById("badgeBackupDirCustom");

  if (btnSaveDir && inputDir) {
    btnSaveDir.addEventListener("click", async function () {
      var newPath = (inputDir.value || "").trim();
      btnSaveDir.disabled = true;
      btnSaveDir.textContent = "저장 중...";
      try {
        var data = await apiPostJson("/api/admin/backups/config", { backup_dir: newPath });
        if (data && data.ok) {
          showToast("✅ 백업 저장 경로가 성공적으로 설정되었습니다.");
          if (inputDir) inputDir.value = data.backup_dir;
          if (badgeCustom) badgeCustom.style.display = data.is_custom ? "inline-block" : "none";
          await loadAdminBackups();
        } else {
          alert("경로 변경 실패: " + ((data && data.error) || "알 수 없는 오류"));
        }
      } catch (err) {
        alert("통신 오류: " + err.message);
      } finally {
        btnSaveDir.disabled = false;
        btnSaveDir.textContent = "경로 저장";
      }
    });
  }

  if (btnResetDir && inputDir) {
    btnResetDir.addEventListener("click", async function () {
      if (!confirm("백업 저장 위치를 시스템 기본 경로(./data/backups)로 초기화하시겠습니까?")) return;
      btnResetDir.disabled = true;
      try {
        var data = await apiPostJson("/api/admin/backups/config", { backup_dir: "" });
        if (data && data.ok) {
          showToast("✅ 기본 백업 경로로 초기화되었습니다.");
          if (inputDir) inputDir.value = data.backup_dir;
          if (badgeCustom) badgeCustom.style.display = "none";
          await loadAdminBackups();
        } else {
          alert("초기화 실패: " + ((data && data.error) || "알 수 없는 오류"));
        }
      } catch (err) {
        alert("통신 오류: " + err.message);
      } finally {
        btnResetDir.disabled = false;
      }
    });
  }

  // Import Backup from Local PC
  var btnImport = document.getElementById("btnImportBackup");
  var inputImport = document.getElementById("inputImportBackupFile");
  if (btnImport && inputImport) {
    btnImport.addEventListener("click", function () {
      inputImport.click();
    });
    inputImport.addEventListener("change", async function () {
      var file = inputImport.files && inputImport.files[0];
      if (!file) return;
      if (!file.name.endsWith(".db.gz") && !file.name.endsWith(".db")) {
        alert("지원하지 않는 파일 형식입니다. (.db.gz 또는 .db 파일만 업로드 가능합니다)");
        inputImport.value = "";
        return;
      }
      var note = prompt("가져올 백업에 대한 설명/메모를 입력하세요:", "외부 가져오기: " + file.name);
      if (note === null) {
        inputImport.value = "";
        return;
      }
      btnImport.disabled = true;
      btnImport.innerHTML = "<span>⏳</span> 가져오는 중...";
      showToast("⏳ 백업 파일 업로드 및 무결성 검증 중...");
      try {
        var formData = new FormData();
        formData.append("file", file);
        formData.append("note", note);
        var authH = (typeof getAuthHeaders === "function") ? getAuthHeaders() : {};
        var headers = Object.assign({}, authH);
        delete headers["Content-Type"];
        var csrfToken = sessionStorage.getItem("argosCsrfToken") || localStorage.getItem("argosCsrfToken");
        if(csrfToken) headers["X-CSRF-Token"] = csrfToken;
        var res = await fetch("/api/admin/backups/upload", {
          method: "POST",
          headers: headers,
          credentials: "same-origin",
          body: formData
        });
        var data = await res.json();
        if (data.ok) {
          showToast("✅ 외부 백업 파일이 정상 등록되었습니다: " + data.filename);
          await loadAdminBackups();
        } else {
          alert("백업 가져오기 실패: " + (data.error || "무결성 검증 실패"));
        }
      } catch (err) {
        alert("통신 오류: " + err.message);
      } finally {
        btnImport.disabled = false;
        btnImport.innerHTML = "<span>📥</span> 외부 백업 가져오기";
        inputImport.value = "";
      }
    });
  }
}

window.loadAdminBackups = loadAdminBackups;
window.triggerRestoreBackup = triggerRestoreBackup;
window.downloadBackupFile = downloadBackupFile;
window.initBackupUI = initBackupUI;

// ── RBAC User Management & Department Assignment ─────────────────────────
var currentAdminUsers = [];

async function loadAdminUsers() {
  var tbody = document.getElementById("adminUserTableBody");
  if (!tbody) return;

  try {
    var res = await apiGet("/api/admin/users");
    if (!res || !res.ok) {
      tbody.innerHTML = '<tr><td colspan="8" style="text-align:center; color: #ef4444; padding: 24px;">' +
        ((res && res.error) || "사용자 목록을 불러오지 못했습니다.") + '</td></tr>';
      return;
    }

    currentAdminUsers = res.users || [];
    var stats = res.stats || {};
    var total = res.total || 0;
    var maxSeats = res.max_seats || 25;

    // Update stats bar
    var elSeats = document.getElementById("statUserSeats");
    var elAdmins = document.getElementById("statUserAdmins");
    var elManagers = document.getElementById("statUserManagers");
    var elMembers = document.getElementById("statUserMembers");
    var elViewers = document.getElementById("statUserViewers");
    var elPending = document.getElementById("statUserPending");

    if (elSeats) elSeats.textContent = total + " / " + maxSeats + " Seats (" + Math.round((total / maxSeats) * 100) + "%)";
    if (elAdmins) elAdmins.textContent = (stats.admins || 0) + "명";
    if (elManagers) elManagers.textContent = (stats.managers || 0) + "명";
    if (elMembers) elMembers.textContent = (stats.members || 0) + "명";
    if (elViewers) elViewers.textContent = (stats.viewers || 0) + "명";
    if (elPending) elPending.textContent = (stats.pending || 0) + "명";

    // Populate department filter and modal department selects
    populateAdminUserDeptSelects();

    // Render table
    renderAdminUsersTable();

  } catch (err) {
    console.error("loadAdminUsers error:", err);
    tbody.innerHTML = '<tr><td colspan="8" style="text-align:center; color: #ef4444; padding: 24px;">통신 오류: ' + (err.message || "") + '</td></tr>';
  }
}

function populateAdminUserDeptSelects() {
  var depts = (typeof DEPARTMENTS !== "undefined" && Array.isArray(DEPARTMENTS) && DEPARTMENTS.length > 0)
    ? DEPARTMENTS
    : ((window.DEPARTMENTS && Array.isArray(window.DEPARTMENTS)) ? window.DEPARTMENTS : []);

  if (depts.length === 0 && typeof loadDepartments === "function") {
    loadDepartments().then(function() {
      populateAdminUserDeptSelects();
    }).catch(function(){});
  }

  var filterDept = document.getElementById("adminUserFilterDept");
  var addDept = document.getElementById("adminAddDept");
  var editDept = document.getElementById("adminEditDept");

  if (filterDept) {
    var curFilterVal = filterDept.value;
    filterDept.innerHTML = '<option value="">전체 워크스페이스 (All Workspaces)</option>' +
      depts.map(function(d){
        return '<option value="' + escapeHtml(d.id) + '">' + escapeHtml(d.name || d.id) + '</option>';
      }).join("");
    if (curFilterVal) filterDept.value = curFilterVal;
  }

  if (addDept) {
    var curAddVal = addDept.value;
    addDept.innerHTML = depts.map(function(d){
      return '<option value="' + escapeHtml(d.id) + '">' + escapeHtml(d.name || d.id) + ' (' + escapeHtml(d.id) + ')</option>';
    }).join("");
    if (curAddVal) addDept.value = curAddVal;
  }

  if (editDept) {
    var curEditVal = editDept.value;
    editDept.innerHTML = depts.map(function(d){
      return '<option value="' + escapeHtml(d.id) + '">' + escapeHtml(d.name || d.id) + ' (' + escapeHtml(d.id) + ')</option>';
    }).join("");
    if (curEditVal) editDept.value = curEditVal;
  }
}

function renderAdminUsersTable() {
  var tbody = document.getElementById("adminUserTableBody");
  if (!tbody) return;

  var searchInput = document.getElementById("adminUserSearchInput");
  var filterStatus = document.getElementById("adminUserFilterStatus");
  var filterRole = document.getElementById("adminUserFilterRole");
  var filterDept = document.getElementById("adminUserFilterDept");

  var q = searchInput ? searchInput.value.trim().toLowerCase() : "";
  var rStatus = filterStatus ? filterStatus.value.trim() : "";
  var rRole = filterRole ? filterRole.value.trim() : "";
  var rDept = filterDept ? filterDept.value.trim() : "";

  var filtered = currentAdminUsers.filter(function(u){
    var uStatus = u.status || "active";
    if (rStatus === "pending" && uStatus !== "pending") return false;
    if (rStatus === "rejected" && uStatus !== "rejected") return false;
    if (rStatus === "active" && (uStatus !== "active" || u.disabled == 1)) return false;
    if (rStatus === "locked" && u.disabled != 1) return false;

    if (rRole && u.role !== rRole) return false;
    if (rDept && u.dept_id !== rDept) return false;
    if (q) {
      var matchU = (u.username || "").toLowerCase().indexOf(q) !== -1;
      var matchN = (u.name || "").toLowerCase().indexOf(q) !== -1;
      var matchE = (u.email || "").toLowerCase().indexOf(q) !== -1;
      var matchD = (u.dept_name || u.dept_id || "").toLowerCase().indexOf(q) !== -1;
      if (!matchU && !matchN && !matchE && !matchD) return false;
    }
    return true;
  });

  if (filtered.length === 0) {
    tbody.innerHTML = '<tr><td colspan="8" style="text-align:center; color: var(--text-muted); padding: 32px;">일치하는 사용자 정보가 없습니다.</td></tr>';
    return;
  }

  var html = filtered.map(function(u){
    var roleBadge = '<span class="badge-role role-member">👤 Member</span>';
    if (u.role === "admin" || u.is_admin) {
      roleBadge = '<span class="badge-role role-admin">🛡️ Admin</span>';
    } else if (u.role === "manager") {
      roleBadge = '<span class="badge-role role-manager">💼 Manager</span>';
    } else if (u.role === "viewer") {
      roleBadge = '<span class="badge-role role-viewer">👁️ Viewer</span>';
    }

    var uStatus = u.status || "active";
    var statusBadge = '';
    var actionButtons = '';

    if (uStatus === "pending") {
      statusBadge = '<span class="badge-status-pending" style="display:inline-block; padding: 2px 8px; border-radius: 9999px; font-size: 11px; font-weight: 600; background: #fef3c7; color: #b45309; border: 1px solid #fde68a;">🟡 승인 대기</span>';
      actionButtons = 
        '<button type="button" class="user-action-btn" style="color: #059669; border-color: #a7f3d0; background: #ecfdf5; font-weight: 600;" onclick="approveAdminUser(' + u.id + ')" title="계정 발급 승인">✅ 승인</button>' +
        '<button type="button" class="user-action-btn" style="color: #dc2626; border-color: #fecaca; background: #fef2f2;" onclick="rejectAdminUser(' + u.id + ')" title="가입 요청 반려">❌ 반려</button>' +
        '<button type="button" class="user-action-btn btn-danger" onclick="deleteAdminUser(' + u.id + ')" title="요청 삭제">🗑️</button>';
    } else if (uStatus === "rejected") {
      statusBadge = '<span class="badge-status-rejected" style="display:inline-block; padding: 2px 8px; border-radius: 9999px; font-size: 11px; font-weight: 600; background: #fee2e2; color: #b91c1c; border: 1px solid #fca5a5;">❌ 반려됨</span>';
      actionButtons = 
        '<button type="button" class="user-action-btn" style="color: #059669; border-color: #a7f3d0; background: #ecfdf5; font-weight: 600;" onclick="approveAdminUser(' + u.id + ')" title="재승인">✅ 재승인</button>' +
        '<button type="button" class="user-action-btn btn-danger" onclick="deleteAdminUser(' + u.id + ')" title="영구 삭제">🗑️</button>';
    } else {
      statusBadge = (u.disabled == 1)
        ? '<span class="badge-status-locked">🔴 잠금</span>'
        : '<span class="badge-status-active">🟢 활성</span>';

      var toggleBtnText = (u.disabled == 1) ? "🔓 해제" : "🔒 잠금";
      var toggleBtnTitle = (u.disabled == 1) ? "계정 활성화" : "계정 로그인 잠금";

      actionButtons = 
        '<button type="button" class="user-action-btn" onclick="openAdminEditUserModal(' + u.id + ')" title="정보 및 권한 수정">✏️ 수정</button>' +
        '<button type="button" class="user-action-btn" onclick="toggleAdminUserStatus(' + u.id + ', ' + (u.disabled || 0) + ')" title="' + toggleBtnTitle + '">' + toggleBtnText + '</button>' +
        '<button type="button" class="user-action-btn btn-danger" onclick="deleteAdminUser(' + u.id + ')" title="계정 삭제">🗑️</button>';
    }

    return '<tr style="border-bottom: 1px solid var(--line, #e2e8f0);">' +
      '<td style="padding: 9px 10px; color: var(--text-muted); font-size: 11px;">' + u.id + '</td>' +
      '<td style="padding: 9px 10px; font-weight: 600; color: var(--ink);">' + escapeHtml(u.username || u.name) + '</td>' +
      '<td style="padding: 9px 10px;">' +
        '<div><strong>' + escapeHtml(u.name) + '</strong></div>' +
        (u.email ? '<div style="font-size: 11px; color: var(--text-muted);">' + escapeHtml(u.email) + '</div>' : '') +
      '</td>' +
      '<td style="padding: 9px 10px;">' + escapeHtml(u.dept_name || u.dept_id) + '</td>' +
      '<td style="padding: 9px 10px; color: var(--text-muted); font-size: 11.5px;">' + escapeHtml(u.email || "-") + '</td>' +
      '<td style="padding: 9px 10px; text-align: center;">' + roleBadge + '</td>' +
      '<td style="padding: 9px 10px; text-align: center;">' + statusBadge + '</td>' +
      '<td style="padding: 9px 10px; text-align: right; white-space: nowrap;">' +
        actionButtons +
      '</td>' +
    '</tr>';
  }).join("");

  tbody.innerHTML = html;
}

function openAdminAddUserModal() {
  populateAdminUserDeptSelects();
  var form = document.getElementById("adminAddUserForm");
  if (form) form.reset();
  var backdrop = document.getElementById("adminAddUserModalBackdrop");
  if (backdrop) {
    backdrop.hidden = false;
    var uInput = document.getElementById("adminAddUsername");
    if (uInput) uInput.focus();
  }
}

function closeAdminAddUserModal() {
  var backdrop = document.getElementById("adminAddUserModalBackdrop");
  if (backdrop) backdrop.hidden = true;
}

async function submitAdminAddUser(e) {
  if (e && e.preventDefault) e.preventDefault();
  var btn = document.getElementById("adminAddUserModalSubmitBtn");
  if (btn) btn.disabled = true;

  var payload = {
    username: (document.getElementById("adminAddUsername").value || "").trim(),
    name: (document.getElementById("adminAddName").value || "").trim(),
    dept_id: (document.getElementById("adminAddDept").value || "").trim(),
    email: (document.getElementById("adminAddEmail").value || "").trim(),
    role: (document.getElementById("adminAddRole").value || "member").trim(),
    password: document.getElementById("adminAddPassword").value || ""
  };

  try {
    var res = await apiPostJson("/api/admin/users/create", payload);
    if (res && res.ok) {
      showToast("✅ " + (res.message || "새 사용자가 등록되었습니다."));
      closeAdminAddUserModal();
      await loadAdminUsers();
    } else {
      alert("사용자 등록 실패: " + ((res && res.error) || "알 수 없는 오류"));
    }
  } catch (err) {
    alert("오류: " + err.message);
  } finally {
    if (btn) btn.disabled = false;
  }
}

function openAdminEditUserModal(userId) {
  var user = currentAdminUsers.find(function(u){ return u.id == userId; });
  if (!user) return;

  populateAdminUserDeptSelects();

  document.getElementById("adminEditUserId").value = user.id;
  document.getElementById("adminEditUsername").value = user.username || user.name;
  document.getElementById("adminEditName").value = user.name || "";
  
  var editDeptSelect = document.getElementById("adminEditDept");
  if (editDeptSelect) {
    editDeptSelect.value = user.dept_id || "";
    // If not matching yet, try selecting after short tick or add option
    if (!editDeptSelect.value && user.dept_id) {
      var opt = document.createElement("option");
      opt.value = user.dept_id;
      opt.textContent = (user.dept_name || user.dept_id) + " (" + user.dept_id + ")";
      opt.selected = true;
      editDeptSelect.appendChild(opt);
    }
  }

  document.getElementById("adminEditEmail").value = user.email || "";
  document.getElementById("adminEditRole").value = user.role || "member";
  document.getElementById("adminEditDisabled").value = (user.disabled == 1) ? "1" : "0";
  document.getElementById("adminEditNewPassword").value = "";
  var confirmPwdInput = document.getElementById("adminEditNewPasswordConfirm");
  if (confirmPwdInput) confirmPwdInput.value = "";
  var errBox = document.getElementById("adminEditUserError");
  if (errBox) { errBox.style.display = "none"; errBox.textContent = ""; }

  var backdrop = document.getElementById("adminEditUserModalBackdrop");
  if (backdrop) backdrop.hidden = false;
}

function closeAdminEditUserModal() {
  var backdrop = document.getElementById("adminEditUserModalBackdrop");
  if (backdrop) backdrop.hidden = true;
  var pwdInput = document.getElementById("adminEditNewPassword");
  if (pwdInput) pwdInput.value = "";
  var confirmPwdInput = document.getElementById("adminEditNewPasswordConfirm");
  if (confirmPwdInput) confirmPwdInput.value = "";
  var errBox = document.getElementById("adminEditUserError");
  if (errBox) { errBox.style.display = "none"; errBox.textContent = ""; }
}

async function submitAdminEditUser(e) {
  if (e && e.preventDefault) e.preventDefault();
  var btn = document.getElementById("adminEditUserModalSubmitBtn");
  if (btn) btn.disabled = true;

  var userId = document.getElementById("adminEditUserId").value;
  var payload = {
    id: parseInt(userId, 10),
    name: (document.getElementById("adminEditName").value || "").trim(),
    dept_id: (document.getElementById("adminEditDept").value || "").trim(),
    email: (document.getElementById("adminEditEmail").value || "").trim(),
    role: (document.getElementById("adminEditRole").value || "member").trim(),
    disabled: parseInt(document.getElementById("adminEditDisabled").value, 10)
  };

  var newPwd = (document.getElementById("adminEditNewPassword").value || "").trim();
  var confirmPwd = (document.getElementById("adminEditNewPasswordConfirm") ? document.getElementById("adminEditNewPasswordConfirm").value : "").trim();
  var errBox = document.getElementById("adminEditUserError");
  function showEditError(msg) {
    // Inline error keeps the modal usable; alert() blocked the whole page.
    if (errBox) {
      errBox.style.display = "block";
      errBox.textContent = msg;
    } else {
      alert(msg);
    }
  }
  if (errBox) { errBox.style.display = "none"; errBox.textContent = ""; }

  if (newPwd || confirmPwd) {
    if (!newPwd) {
      showEditError("새 비밀번호를 입력해주세요.");
      if (btn) btn.disabled = false;
      return;
    }
    if (newPwd.length < 8) {
      showEditError("비밀번호는 최소 8자 이상이어야 합니다.");
      if (btn) btn.disabled = false;
      return;
    }
    if (!confirmPwd) {
      showEditError("새 비밀번호 확인을 입력해주세요.");
      if (btn) btn.disabled = false;
      return;
    }
    if (newPwd !== confirmPwd) {
      showEditError("새 비밀번호가 일치하지 않습니다. 다시 확인해주세요.");
      if (btn) btn.disabled = false;
      return;
    }
    payload.new_password = newPwd;
    payload.new_password_confirm = confirmPwd;
  }

  try {
    var res = await apiPostJson("/api/admin/users/update", payload);
    if (res && res.ok) {
      showToast("✅ " + (res.message || "사용자 정보가 수정되었습니다."));
      closeAdminEditUserModal();
      await loadAdminUsers();
    } else {
      showEditError("사용자 수정 실패: " + ((res && res.error) || "알 수 없는 오류"));
    }
  } catch (err) {
    showEditError("오류: " + err.message);
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function toggleAdminUserStatus(userId, currentDisabled) {
  var nextDisabled = (currentDisabled == 1) ? 0 : 1;
  var actionName = nextDisabled ? "잠금(비활성화)" : "활성화";
  if (!confirm("해당 사용자를 " + actionName + " 처리하시겠습니까?")) return;

  try {
    var res = await apiPostJson("/api/admin/users/update", { id: userId, disabled: nextDisabled });
    if (res && res.ok) {
      showToast("✅ 사용자가 " + actionName + "되었습니다.");
      await loadAdminUsers();
    } else {
      alert("처리 실패: " + ((res && res.error) || "알 수 없는 오류"));
    }
  } catch (err) {
    alert("오류: " + err.message);
  }
}

function getAdminUserById(userId) {
  if (Array.isArray(currentAdminUsers)) {
    for (var i = 0; i < currentAdminUsers.length; i++) {
      if (currentAdminUsers[i].id == userId) return currentAdminUsers[i];
    }
  }
  return null;
}

async function deleteAdminUser(userId, userName) {
  var u = getAdminUserById(userId);
  var name = userName || (u && u.name) || ("User #" + userId);
  if (!confirm("⚠️ 주의: '" + name + "' 사용자를 영구 삭제하시겠습니까?\n삭제된 사용자의 활성 세션도 즉시 파기됩니다.")) return;

  try {
    var res = await apiPostJson("/api/admin/users/delete", { id: userId });
    if (res && res.ok) {
      showToast("✅ " + (res.message || "사용자가 삭제되었습니다."));
      await loadAdminUsers();
    } else {
      alert("삭제 실패: " + ((res && res.error) || "알 수 없는 오류"));
    }
  } catch (err) {
    alert("오류: " + err.message);
  }
}

async function approveAdminUser(userId, userName, currentRole) {
  var u = getAdminUserById(userId);
  var name = userName || (u && u.name) || ("User #" + userId);
  var defaultRole = currentRole || (u && u.role) || "member";
  var rolePrompt = prompt(
    "'" + name + "' 사용자의 계정 발급을 승인하시겠습니까?\n부여할 역할을 입력하세요 (member, manager, admin, viewer):",
    defaultRole
  );
  if (rolePrompt === null) return;
  var role = rolePrompt.trim().toLowerCase();
  if (["admin", "manager", "member", "viewer"].indexOf(role) === -1) {
    alert("올바른 역할(role)이 아닙니다. (admin, manager, member, viewer 중 하나를 입력하세요)");
    return;
  }

  try {
    var res = await apiPostJson("/api/admin/users/approve", { id: userId, role: role });
    if (res && res.ok) {
      showToast("✅ " + (res.message || "계정이 승인되었습니다."));
      await loadAdminUsers();
    } else {
      alert("승인 실패: " + ((res && res.error) || "알 수 없는 오류"));
    }
  } catch (err) {
    alert("오류: " + err.message);
  }
}

async function rejectAdminUser(userId, userName) {
  var u = getAdminUserById(userId);
  var name = userName || (u && u.name) || ("User #" + userId);
  if (!confirm("⚠️ '" + name + "' 사용자의 계정 발급 요청을 반려하시겠습니까?\n반려된 사용자는 로그인이 차단되며 반려 안내가 표시됩니다.")) return;

  try {
    var res = await apiPostJson("/api/admin/users/reject", { id: userId });
    if (res && res.ok) {
      showToast("✅ " + (res.message || "요청이 반려되었습니다."));
      await loadAdminUsers();
    } else {
      alert("반려 실패: " + ((res && res.error) || "알 수 없는 오류"));
    }
  } catch (err) {
    alert("오류: " + err.message);
  }
}

function initAdminUserUI() {
  var btnOpenAdd = document.getElementById("btnAdminOpenAddUser");
  var btnReload = document.getElementById("btnAdminReloadUsers");
  var searchInput = document.getElementById("adminUserSearchInput");
  var filterStatus = document.getElementById("adminUserFilterStatus");
  var filterRole = document.getElementById("adminUserFilterRole");
  var filterDept = document.getElementById("adminUserFilterDept");

  if (btnOpenAdd) btnOpenAdd.addEventListener("click", openAdminAddUserModal);
  if (btnReload) btnReload.addEventListener("click", loadAdminUsers);
  if (searchInput) searchInput.addEventListener("input", renderAdminUsersTable);
  if (filterStatus) filterStatus.addEventListener("change", renderAdminUsersTable);
  if (filterRole) filterRole.addEventListener("change", renderAdminUsersTable);
  if (filterDept) filterDept.addEventListener("change", renderAdminUsersTable);

  var addClose = document.getElementById("adminAddUserModalCloseBtn");
  var addCancel = document.getElementById("adminAddUserModalCancelBtn");
  var addForm = document.getElementById("adminAddUserForm");
  if (addClose) addClose.addEventListener("click", closeAdminAddUserModal);
  if (addCancel) addCancel.addEventListener("click", closeAdminAddUserModal);
  if (addForm) addForm.addEventListener("submit", submitAdminAddUser);

  var editClose = document.getElementById("adminEditUserModalCloseBtn");
  var editCancel = document.getElementById("adminEditUserModalCancelBtn");
  var editForm = document.getElementById("adminEditUserForm");
  if (editClose) editClose.addEventListener("click", closeAdminEditUserModal);
  if (editCancel) editCancel.addEventListener("click", closeAdminEditUserModal);
  if (editForm) editForm.addEventListener("submit", submitAdminEditUser);

  var addModal = document.getElementById("adminAddUserModalBackdrop");
  var editModal = document.getElementById("adminEditUserModalBackdrop");

  if (addModal) {
    addModal.addEventListener("click", function(e) {
      if (e.target === addModal) closeAdminAddUserModal();
    });
  }
  if (editModal) {
    editModal.addEventListener("click", function(e) {
      if (e.target === editModal) closeAdminEditUserModal();
    });
  }

  document.addEventListener("keydown", function(e) {
    if (e.key === "Escape") {
      if (addModal && !addModal.hidden) {
        closeAdminAddUserModal();
        return;
      }
      if (editModal && !editModal.hidden) {
        closeAdminEditUserModal();
        return;
      }
      var catModal = document.getElementById("modalProductCategory");
      if (catModal && !catModal.hidden) {
        catModal.hidden = true;
        return;
      }
    }
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initAdminUserUI);
} else {
  initAdminUserUI();
}

window.loadAdminUsers = loadAdminUsers;
window.openAdminAddUserModal = openAdminAddUserModal;
window.closeAdminAddUserModal = closeAdminAddUserModal;
window.openAdminEditUserModal = openAdminEditUserModal;
window.closeAdminEditUserModal = closeAdminEditUserModal;
window.toggleAdminUserStatus = toggleAdminUserStatus;
window.deleteAdminUser = deleteAdminUser;
window.approveAdminUser = approveAdminUser;
window.rejectAdminUser = rejectAdminUser;
window.initSettingsSubtabs = initSettingsSubtabs;
window.isCurrentUserAdmin = isCurrentUserAdmin;
window.isCurrentUserManagerOrAdmin = isCurrentUserManagerOrAdmin;


// ── Enterprise License & Entitlements Management ────────────────
var LICENSE_MODULE_MAP = {
  "canvas": "🎨 캔버스 (Canvas)",
  "pim": "📦 PIM (품목 관리)",
  "jira": "🎫 Jira 연동 (Jira Integration)",
  "rag": "🤖 AI 지식베이스 (RAG / AI Chat)",
  "schedule": "📅 일정 관리 (Schedule)",
  "audit": "🛡️ 보안 감사 (Audit Logs)",
  "*": "⭐ 전체 모듈 (All Modules)",
  "all": "⭐ 전체 모듈 (All Modules)"
};

async function loadLicenseStatus() {
  var badge = document.getElementById("badgeLicenseState");
  var warnBox = document.getElementById("licenseWarningBox");
  var licCustomer = document.getElementById("licCustomer");
  var licExpiry = document.getElementById("licExpiry");
  var licDaysLeft = document.getElementById("licDaysLeft");
  var licValid = document.getElementById("licValid");
  var licSeats = document.getElementById("licSeats");
  var licSeatsBar = document.getElementById("licSeatsBar");
  var licModules = document.getElementById("licModules");

  if (!badge && !licCustomer) return;

  if (badge) {
    badge.textContent = "확인 중...";
    badge.className = "card-badge";
    badge.style.background = "";
    badge.style.color = "";
    badge.style.border = "";
  }

  try {
    var res = await apiGet("/api/admin/license");
    if (!res || !res.ok || !res.license) {
      if (badge) {
        badge.textContent = "조회 실패";
        badge.style.background = "rgba(239,68,68,0.12)";
        badge.style.color = "#ef4444";
        badge.style.border = "1px solid rgba(239,68,68,0.3)";
      }
      if (warnBox) {
        warnBox.style.display = "block";
        warnBox.style.borderColor = "#ef4444";
        warnBox.style.background = "rgba(239,68,68,0.10)";
        warnBox.style.color = "#b91c1c";
        warnBox.textContent = "⚠️ 라이선스 정보를 불러오지 못했습니다: " + ((res && res.error) || "서버 통신 오류");
      }
      return;
    }

    var lic = res.license;

    // 1. Badge & Warning box
    if (!lic.license_valid) {
      if (badge) {
        badge.textContent = "미인증 / 오류";
        badge.style.background = "rgba(239,68,68,0.12)";
        badge.style.color = "#ef4444";
        badge.style.border = "1px solid rgba(239,68,68,0.3)";
      }
      if (warnBox) {
        warnBox.style.display = "block";
        warnBox.style.borderColor = "#ef4444";
        warnBox.style.background = "rgba(239,68,68,0.10)";
        warnBox.style.color = "#b91c1c";
        warnBox.textContent = "⚠️ 유효하지 않은 라이선스입니다 (" + (lic.license_reason || "서명 검증 실패") + "). 정품 라이선스 키를 활성화하세요.";
      }
    } else if (lic.is_expired) {
      if (badge) {
        badge.textContent = "만료됨 (읽기 전용)";
        badge.style.background = "rgba(239,68,68,0.12)";
        badge.style.color = "#ef4444";
        badge.style.border = "1px solid rgba(239,68,68,0.3)";
      }
      if (warnBox) {
        warnBox.style.display = "block";
        warnBox.style.borderColor = "#ef4444";
        warnBox.style.background = "rgba(239,68,68,0.10)";
        warnBox.style.color = "#b91c1c";
        warnBox.textContent = "⚠️ 라이선스가 만료되어 시스템이 읽기 전용으로 전환되었습니다 (만료일: " + lic.expiry_date + "). 새로운 라이선스 키를 활성화해주세요.";
      }
    } else if (lic.expiry_warning) {
      if (badge) {
        badge.textContent = "만료 임박 (D-" + lic.days_left + ")";
        badge.style.background = "rgba(245,158,11,0.14)";
        badge.style.color = "#f59e0b";
        badge.style.border = "1px solid rgba(245,158,11,0.35)";
      }
      if (warnBox) {
        warnBox.style.display = "block";
        warnBox.style.borderColor = "#f59e0b";
        warnBox.style.background = "rgba(245,158,11,0.10)";
        warnBox.style.color = "#92400e";
        warnBox.textContent = "⚠️ 라이선스 만료가 " + lic.days_left + "일 남았습니다. 계약 갱신 키를 준비해주세요.";
      }
    } else {
      if (badge) {
        badge.textContent = "정상 활성";
        badge.style.background = "rgba(16,185,129,0.14)";
        badge.style.color = "#10b981";
        badge.style.border = "1px solid rgba(16,185,129,0.35)";
      }
      if (warnBox) {
        warnBox.style.display = "none";
      }
    }

    // 2. Info Table
    if (licCustomer) licCustomer.textContent = lic.customer_name || "-";
    if (licExpiry) licExpiry.textContent = lic.expiry_date || "-";
    if (licDaysLeft) {
      if (!lic.license_valid) {
        licDaysLeft.textContent = "-";
      } else if (lic.is_expired) {
        licDaysLeft.innerHTML = '<span style="color:#ef4444; font-weight:600;">만료됨 (0일)</span>';
      } else {
        var daysText = lic.days_left + "일";
        if (lic.days_left <= 30) {
          licDaysLeft.innerHTML = '<span style="color:#f59e0b; font-weight:600;">' + daysText + ' (만료 임박)</span>';
        } else {
          licDaysLeft.innerHTML = '<span style="color:#10b981; font-weight:600;">' + daysText + ' 남음</span>';
        }
      }
    }
    if (licValid) {
      if (lic.license_valid) {
        licValid.innerHTML = '<span style="color:#10b981; font-weight:600;">✅ 정상 검증</span> <span style="font-size:11.5px; color:var(--text-muted);">(' + escapeHtml(lic.license_reason || "Ed25519 서명 확인") + ')</span>';
      } else {
        licValid.innerHTML = '<span style="color:#ef4444; font-weight:600;">❌ 검증 실패</span> <span style="font-size:11.5px; color:var(--text-muted);">(' + escapeHtml(lic.license_reason || "키 확인 불가") + ')</span>';
      }
    }

    // 3. Seats Bar
    var activeSeats = Number(lic.active_seats) || 0;
    var maxSeats = Number(lic.max_seats) || 0;
    var pct = maxSeats > 0 ? Math.min(100, Math.round((activeSeats / maxSeats) * 100)) : 0;
    if (licSeats) {
      if (maxSeats > 0) {
        licSeats.textContent = activeSeats + " / " + maxSeats + "석 (" + pct + "%)";
      } else {
        licSeats.textContent = activeSeats + "석 사용 중 (한도 미설정)";
      }
    }
    if (licSeatsBar) {
      licSeatsBar.style.width = pct + "%";
      if (pct >= 100) {
        licSeatsBar.style.background = "linear-gradient(90deg, #ef4444, #f87171)";
      } else if (pct >= 85) {
        licSeatsBar.style.background = "linear-gradient(90deg, #f59e0b, #fbbf24)";
      } else {
        licSeatsBar.style.background = "linear-gradient(90deg, #0284c7, #38bdf8)";
      }
    }

    // 4. Modules
    if (licModules) {
      licModules.innerHTML = "";
      var mods = Array.isArray(lic.modules) ? lic.modules : [];
      if (mods.length === 0) {
        licModules.innerHTML = '<span style="font-size:12px; color:var(--text-muted);">활성화된 모듈이 없습니다.</span>';
      } else {
        mods.forEach(function (m) {
          var label = LICENSE_MODULE_MAP[m] || ("🧩 " + String(m).toUpperCase());
          var span = document.createElement("span");
          span.style.cssText = "background:rgba(56,189,248,0.12); color:var(--stat-info, #38bdf8); border:1px solid rgba(56,189,248,0.28); padding:3px 9px; border-radius:12px; font-size:11.5px; font-weight:600;";
          span.textContent = label;
          licModules.appendChild(span);
        });
      }
    }

  } catch (err) {
    console.error("[loadLicenseStatus] Error:", err);
    if (badge) {
      badge.textContent = "오류";
      badge.style.color = "#ef4444";
    }
  }
}

async function activateLicense() {
  var input = document.getElementById("inputLicenseKey");
  var btn = document.getElementById("btnActivateLicense");
  var msg = document.getElementById("licenseMsg");
  if (!input) return;

  var key = (input.value || "").trim();
  if (!key) {
    if (msg) {
      msg.style.color = "#ef4444";
      msg.textContent = "⚠️ 라이선스 키를 입력하세요.";
    }
    input.focus();
    return;
  }

  if (btn) btn.disabled = true;
  if (msg) {
    msg.style.color = "var(--text-muted)";
    msg.textContent = "검증 및 활성화 중...";
  }

  try {
    var res = await apiPostJson("/api/admin/license/activate", { license_key: key });
    if (res && res.ok) {
      if (msg) {
        msg.style.color = "#10b981";
        msg.textContent = "✅ " + (res.message || "라이선스가 성공적으로 활성화되었습니다.");
      }
      input.value = "";
      await loadLicenseStatus();
      if (typeof showToast === "function") {
        showToast("라이선스가 성공적으로 활성화되었습니다.", 3000);
      }
    } else {
      var errMsg = (res && res.error) || "라이선스 활성화에 실패했습니다.";
      if (msg) {
        msg.style.color = "#ef4444";
        msg.textContent = "❌ " + errMsg;
      }
      if (typeof showToast === "function") {
        showToast(errMsg, 4000, true);
      }
    }
  } catch (err) {
    if (msg) {
      msg.style.color = "#ef4444";
      msg.textContent = "❌ 오류: " + err.message;
    }
  } finally {
    if (btn) btn.disabled = false;
  }
}

function initLicenseUI() {
  var btnActivate = document.getElementById("btnActivateLicense");
  if (btnActivate && !btnActivate.__bound) {
    btnActivate.__bound = true;
    btnActivate.addEventListener("click", activateLicense);
  }

  var btnRefresh = document.getElementById("btnRefreshLicense");
  if (btnRefresh && !btnRefresh.__bound) {
    btnRefresh.__bound = true;
    btnRefresh.addEventListener("click", function () {
      var msg = document.getElementById("licenseMsg");
      if (msg) {
        msg.style.color = "var(--text-muted)";
        msg.textContent = "새로고침 중...";
      }
      loadLicenseStatus().then(function () {
        if (msg) {
          msg.style.color = "#10b981";
          msg.textContent = "최신 상태로 갱신되었습니다.";
          setTimeout(function () {
            if (msg.textContent === "최신 상태로 갱신되었습니다.") msg.textContent = "";
          }, 2500);
        }
      });
    });
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initLicenseUI);
} else {
  initLicenseUI();
}

window.loadLicenseStatus = loadLicenseStatus;
window.activateLicense = activateLicense;
window.initLicenseUI = initLicenseUI;
