// pim.js
var pimList = document.getElementById("pimList");
var pimListLabel = document.getElementById("pimListLabel");
var pimEmpty = document.getElementById("pimEmpty");
var pimSearchInput = document.getElementById("pimSearchInput");
var pimNewBtn = document.getElementById("pimNewBtn");
var pimForm = document.getElementById("pimForm");
var pimFormModal = document.getElementById("pimFormModal");
var pimFormCloseBtn = document.getElementById("pimFormCloseBtn");
var pimFormDismissBtn = document.getElementById("pimFormDismissBtn");
var pimFormTitle = document.getElementById("pimFormTitle");
var pimFormError = document.getElementById("pimFormError");
var pimSaveBtn = document.getElementById("pimSaveBtn");
var pimCancelEditBtn = document.getElementById("pimCancelEditBtn");
var pimIdField = document.getElementById("pimId");
var pimRevisionField = document.getElementById("pimRevision");
var pimModelInput = document.getElementById("pimModelInput");
var pimDisplayNameInput = document.getElementById("pimDisplayNameInput");
var pimFamilyInput = document.getElementById("pimFamilyInput");
var pimLifecycleSelect = document.getElementById("pimLifecycleSelect");
var pimSummaryInput = document.getElementById("pimSummaryInput");
var pimMemoInput = document.getElementById("pimMemoInput");
var pimProcureCheck = document.getElementById("pimProcureCheck");
var pimProcureFields = document.getElementById("pimProcureFields");
var pimRegNameInput = document.getElementById("pimRegNameInput");
var pimIdNoInput = document.getElementById("pimIdNoInput");
var pimPriceInput = document.getElementById("pimPriceInput");
var pimCurrencySelect = document.getElementById("pimCurrencySelect");
var pimCurrencyCustomWrap = document.getElementById("pimCurrencyCustomWrap");
var pimCurrencyCustomInput = document.getElementById("pimCurrencyCustomInput");

function getSelectedCurrency(){
  if(!pimCurrencySelect) return "KRW";
  if(pimCurrencySelect.value === "OTHER"){
    var custom = (pimCurrencyCustomInput ? pimCurrencyCustomInput.value : "").trim().toUpperCase();
    return custom || "KRW";
  }
  return pimCurrencySelect.value.trim().toUpperCase() || "KRW";
}

function setSelectedCurrency(curr){
  var c = (curr || "KRW").trim().toUpperCase();
  if(!pimCurrencySelect) return;
  if(c === "KRW" || c === "USD"){
    pimCurrencySelect.value = c;
    if(pimCurrencyCustomWrap) pimCurrencyCustomWrap.style.display = "none";
    if(pimCurrencyCustomInput) pimCurrencyCustomInput.value = "";
  } else {
    pimCurrencySelect.value = "OTHER";
    if(pimCurrencyCustomWrap) pimCurrencyCustomWrap.style.display = "block";
    if(pimCurrencyCustomInput) pimCurrencyCustomInput.value = c;
  }
}

if(pimCurrencySelect){
  pimCurrencySelect.addEventListener("change", function(){
    if(pimCurrencySelect.value === "OTHER"){
      if(pimCurrencyCustomWrap) pimCurrencyCustomWrap.style.display = "block";
      if(pimCurrencyCustomInput) pimCurrencyCustomInput.focus();
    } else {
      if(pimCurrencyCustomWrap) pimCurrencyCustomWrap.style.display = "none";
      if(pimCurrencyCustomInput) pimCurrencyCustomInput.value = "";
    }
  });
}

var pimConfigInput = document.getElementById("pimConfigInput");
var pimAttachInput = document.getElementById("pimAttachInput");
var pimAttachList = document.getElementById("pimAttachList");
var pimCategorySelect = document.getElementById("pimCategorySelect");
var pimSpecFields = document.getElementById("pimSpecFields");
var pimImageInput = document.getElementById("pimImageInput");
var pimImagePreview = document.getElementById("pimImagePreview");
var pimImagePlaceholder = document.getElementById("pimImagePlaceholder");
var pimSelectImageBtn = document.getElementById("pimSelectImageBtn");
var pimRemoveImageBtn = document.getElementById("pimRemoveImageBtn");
var pimAddCustomSpecBtn = document.getElementById("pimAddCustomSpecBtn");
var pimCustomSpecsList = document.getElementById("pimCustomSpecsList");

function loadPimCategories(){
  return fetch("/api/products/categories", { cache: "no-store" })
    .then(function(r){ return r.json(); })
    .then(function(data){
      if(!data.ok) return;
      pimCategories = data.categories || ["일반"];
      pimSpecTemplates = data.templates || { "일반": [] };
      if(pimCategorySelect){
        pimCategorySelect.innerHTML = pimCategories.map(function(c){
          return '<option value="' + escapeHtml(c) + '">' + escapeHtml(c) + '</option>';
        }).join("");
        renderPimSpecFields(pimCategorySelect.value, {});
      }
    })
    .catch(function(){});
}

function addCustomSpecRow(key, val){
  if(!pimCustomSpecsList) return;
  var row = document.createElement("div");
  row.className = "pim-custom-spec-row";
  row.style.cssText = "display: flex; gap: 8px; align-items: center; margin-bottom: 6px;";
  row.innerHTML = '<input type="text" class="pim-custom-spec-key" placeholder="항목명 (예: 규격, 인터페이스, 방수등급)" value="' + escapeHtml(key || "") + '" style="width: 38%; font-size: 12.5px;">' +
    '<input type="text" class="pim-custom-spec-val" placeholder="내용/값 (예: 1920x1080, USB 3.0, IP67)" value="' + escapeHtml(val || "") + '" style="flex: 1; font-size: 12.5px;">' +
    '<button type="button" class="btn-secondary pim-custom-spec-del" style="padding: 4px 8px; font-size: 12px; color: #ef4444; border-color: rgba(239,68,68,0.25);" title="항목 삭제">✕</button>';
  row.querySelector(".pim-custom-spec-del").addEventListener("click", function(){
    row.remove();
  });
  pimCustomSpecsList.appendChild(row);
}

var SPEC_LABEL_MAP = {
  "dimensions": "크기 / 규격",
  "weight": "중량 / 무게",
  "color": "색상 / 재질",
  "version": "버전",
  "os": "지원 OS",
  "license": "라이선스",
  "modelNo": "상세 모델 번호",
  "power": "정격 전원",
  "interface": "인터페이스 / 단자",
  "specNote": "주요 사양"
};

function getSpecDisplayLabel(key, category){
  if(!key) return "";
  if(category && pimSpecTemplates && pimSpecTemplates[category]){
    var item = pimSpecTemplates[category].find(function(t){ return t.key === key; });
    if(item && item.label) return item.label;
  }
  if(pimSpecTemplates){
    for(var cat in pimSpecTemplates){
      if(pimSpecTemplates.hasOwnProperty(cat)){
        var found = pimSpecTemplates[cat].find(function(t){ return t.key === key; });
        if(found && found.label) return found.label;
      }
    }
  }
  return SPEC_LABEL_MAP[key] || key;
}

function renderPimSpecFields(category, values){
  if(!pimSpecFields) return;
  var template = pimSpecTemplates[category] || [];
  values = values || {};
  if(pimCustomSpecsList) pimCustomSpecsList.innerHTML = "";

  var handledKeys = {};
  var html = "";
  if(template.length){
    var lastGroup = null;
    template.forEach(function(f){
      if(f.group !== lastGroup){
        html += '<p class="pim-spec-group-title">' + escapeHtml(f.group || "규격") + '</p>';
        lastGroup = f.group;
      }
      var val = (values && (values[f.key] != null ? values[f.key] : values[f.label])) || "";
      handledKeys[f.key] = true;
      if(f.label) handledKeys[f.label] = true;
      html += '<div class="field" style="margin-bottom: 8px;">' +
        '<label for="pimSpec_' + f.key + '">' + escapeHtml(f.label) + ' <span class="optional">(선택)</span></label>' +
        '<input type="text" id="pimSpec_' + f.key + '" data-spec-key="' + f.key + '" maxlength="' + (f.maxlen || 200) + '" value="' + escapeHtml(val) + '">' +
        '</div>';
    });
  } else {
    html = '<p class="pim-spec-empty" style="font-size: 12px; color: var(--ink-faint); margin: 0 0 8px 0;">이 카테고리에는 사전 정의된 양식이 없습니다. [+ 규격 항목 추가] 버튼으로 자유롭게 항목을 추가해주세요.</p>';
  }
  pimSpecFields.innerHTML = html;

  // Add any custom specs from values that are not in the predefined template
  Object.keys(values).forEach(function(k){
    if(!handledKeys[k] && values[k]){
      addCustomSpecRow(k, values[k]);
    }
  });
}

function collectPimSpecs(){
  var specs = {};
  if(pimSpecFields){
    pimSpecFields.querySelectorAll("[data-spec-key]").forEach(function(input){
      var v = input.value.trim();
      if(v) specs[input.getAttribute("data-spec-key")] = v;
    });
  }
  if(pimCustomSpecsList){
    pimCustomSpecsList.querySelectorAll(".pim-custom-spec-row").forEach(function(row){
      var k = (row.querySelector(".pim-custom-spec-key").value || "").trim();
      var v = (row.querySelector(".pim-custom-spec-val").value || "").trim();
      if(k && v){
        specs[k] = v;
      }
    });
  }
  return specs;
}

function pimLifecycleBadgeClass(lifecycle){
  if(lifecycle === "단종 예정") return "life-단종예정";
  if(lifecycle === "단종") return "life-단종";
  return "life-판매중";
}

function formatFileSize(bytes){
  if(bytes == null) return "";
  if(bytes < 1024) return bytes + "B";
  if(bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + "KB";
  return (bytes / (1024 * 1024)).toFixed(1) + "MB";
}

function renderPimList(){
  if(!pimList) return;
  var items = pimProducts;

  if(!items.length){
    pimList.innerHTML = "";
    if(pimEmpty) pimEmpty.hidden = false;
    var isEn = (window.i18n && window.i18n.getLang && window.i18n.getLang() === "en");
    if(pimListLabel) {
      pimListLabel.textContent = (window.i18n && window.i18n.t)
        ? window.i18n.t("pim.list_label", { count: 0 })
        : (isEn ? "Managed Products (0 items)" : "사내 관리 제품 (0개)");
    }
    return;
  }
  if(pimEmpty) pimEmpty.hidden = true;
  var isEn = (window.i18n && window.i18n.getLang && window.i18n.getLang() === "en");
  if(pimListLabel) {
    pimListLabel.textContent = (window.i18n && window.i18n.t)
      ? window.i18n.t("pim.list_label", { count: items.length })
      : (isEn ? ("Managed Products (" + items.length + " items)") : ("사내 관리 제품 (" + items.length + "개)"));
  }
  if(pimNewBtn) {
    var canMod = (typeof canModifyPimUser === "function") && canModifyPimUser();
    pimNewBtn.style.display = canMod ? "" : "none";
    pimNewBtn.hidden = !canMod;
  }

  var fallbackImg = "data:image/svg+xml;charset=utf-8,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20width%3D%22200%22%20height%3D%22150%22%20viewBox%3D%220%200%20200%20150%22%3E%3Crect%20fill%3D%22%23f3f4f6%22%20width%3D%22200%22%20height%3D%22150%22%2F%3E%3Ctext%20fill%3D%22%239ca3af%22%20font-family%3D%22sans-serif%22%20font-size%3D%2213%22%20x%3D%2250%25%22%20y%3D%2250%25%22%20text-anchor%3D%22middle%22%20dy%3D%22.3em%22%3ENo%20Image%3C%2Ftext%3E%3C%2Fsvg%3E";

  var currentId = pimIdField ? pimIdField.value : "";
  var html = items.map(function(p){
    var proc = p.procurement;
    var attachCount = (p.attachments || []).length;
    var imgAttach = (p.attachments || []).find(function(a){
      return /\.(jpg|jpeg|png|webp|gif|svg)$/i.test(a.name);
    });
    var thumb = imgAttach
      ? ("/api/products/attachment?id=" + encodeURIComponent(p.id) + "&file=" + encodeURIComponent(imgAttach.name))
      : fallbackImg;
    var model = escapeHtml(p.model || "");
    var displayName = escapeHtml(p.displayName || "");
    var cat = escapeHtml(p.category || "일반");
    var summary = escapeHtml(p.summary || p.memo || "");
    var lifecycle = escapeHtml(p.lifecycle || "판매 중");
    var lifeClass = pimLifecycleBadgeClass(p.lifecycle);

    return '<div class="pim-web-card pim-internal-card-item' + (p.id === currentId ? ' active' : '') + '" data-id="' + p.id + '">' +
      '<div class="pim-card-thumb-wrap" data-action="view" style="cursor:pointer;" title="클릭하여 상세 정보 보기">' +
        '<img class="pim-card-thumb" src="' + thumb + '" alt="' + model + '" loading="lazy" onerror="this.src=\'' + fallbackImg + '\'">' +
        '<span class="pim-card-category-badge">' + cat + '</span>' +
        (proc ? '<span class="pim-card-proc-badge">조달 · ' + escapeHtml(proc.identificationNo || "") + '</span>' : '') +
      '</div>' +
      '<div class="pim-card-info">' +
        '<div style="display:flex; align-items:center; justify-content:space-between; gap:6px; margin-bottom:4px;">' +
          '<div class="pim-card-model" data-action="view" style="cursor:pointer;" title="' + model + '">' + model + '</div>' +
          '<span class="pim-badge ' + lifeClass + '">' + lifecycle + '</span>' +
        '</div>' +
        (displayName ? '<div class="pim-card-name" data-action="view" style="font-size:13px; font-weight:600; color:var(--ink); margin-bottom:4px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; cursor:pointer;" title="' + displayName + '">' + displayName + '</div>' : '') +
        '<div class="pim-card-summary" data-action="view" style="min-height:36px; -webkit-line-clamp:2; display:-webkit-box; -webkit-box-orient:vertical; overflow:hidden; margin-bottom:10px; cursor:pointer;" title="' + summary + '">' + (summary || '<span style="color:var(--ink-faint); font-style:italic;">등록된 요약 정보가 없습니다.</span>') + '</div>' +
        '<div style="display:flex; gap:6px; flex-wrap:wrap; margin-bottom:12px; margin-top:auto;">' +
          (p.family ? '<span class="pim-badge" style="background:var(--code-bg); color:var(--ink-soft);">' + escapeHtml(p.family) + '</span>' : '') +
          (attachCount ? '<span class="pim-badge attach">📎 ' + attachCount + '개</span>' : '') +
          (function(){
            var displayPrice = (p.price != null && p.price !== "" && Number(p.price) > 0) ? p.price : (proc && proc.price ? proc.price : null);
            var curr = (p.currency || (proc && proc.currency) || "KRW").toUpperCase();
            return displayPrice ? '<span class="pim-badge" style="background:rgba(16,185,129,0.1); color:#10b981; font-weight:600;">' + Number(displayPrice).toLocaleString() + ' ' + curr + '</span>' : '';
          })() +
        '</div>' +
        '<div class="pim-card-actions" style="display:flex; gap:8px; align-items:center;">' +
          '<button type="button" class="pim-btn-spec" data-action="view" style="flex:1;">🔍 상세 보기</button>' +
          ((typeof canModifyPimUser === "function" && canModifyPimUser()) ? '<button type="button" class="pim-btn-spec" data-action="edit" title="수정" style="flex:0 0 34px; width:34px; height:32px; padding:0; display:inline-flex; align-items:center; justify-content:center; background:var(--code-bg); color:var(--ink-soft); border-color:var(--line); font-size:13px;">✏️</button>' : '') +
        '</div>' +
      '</div>' +
    '</div>';
  }).join("");

  pimList.innerHTML = html;
}

function renderPimAttachList(product){
  if(!pimAttachList) return;
  var attachments = (product && product.attachments) || [];
  if(!attachments.length){
    pimAttachList.innerHTML = '<span style="font-size:12px; color:var(--ink-faint); font-style:italic;">등록된 첨부 문서가 없습니다.</span>';
    return;
  }
  var html = "";
  attachments.forEach(function(a){
    var isImg = /\.(jpg|jpeg|png|webp|gif|svg)$/i.test(a.name);
    var icon = isImg ? "🖼️ " : (/\.pdf$/i.test(a.name) ? "📑 " : "📄 ");
    var url = "/api/products/attachment?id=" + encodeURIComponent(product.id) + "&file=" + encodeURIComponent(a.name);
    html += '<div class="pim-attach-item" data-name="' + escapeHtml(a.name) + '">' +
      '<a href="' + url + '" target="_blank" rel="noopener">' + icon + escapeHtml(a.name) +
        '<span class="pim-attach-size">' + formatFileSize(a.size) + '</span></a>' +
      '<button type="button" class="pim-attach-remove" data-name="' + escapeHtml(a.name) + '">삭제</button>' +
    '</div>';
  });
  pimAttachList.innerHTML = html;
}

function updatePimProductInPlace(updated){
  var idx = pimProducts.findIndex(function(p){ return p.id === updated.id; });
  if(idx !== -1) pimProducts[idx] = updated;
}

if(pimAttachList){
  pimAttachList.addEventListener("click", function(e){
    var btn = e.target.closest(".pim-attach-remove");
    if(!btn) return;
    var pid = pimIdField.value;
    var name = btn.getAttribute("data-name");
    if(!pid || !name) return;
    btn.disabled = true;
    var postFn = (typeof apiPostJson === "function") ? apiPostJson : (typeof apiPost === "function" ? apiPost : null);
    if (!postFn) {
      btn.disabled = false;
      return;
    }
    postFn("/api/products/attachments/delete", { id: pid, name: name })
      .then(function(data){
        if(!data || !data.ok){
          showToast((data && data.error) || "첨부파일 삭제에 실패했습니다.");
          btn.disabled = false;
          return;
        }
        updatePimProductInPlace(data.product);
        renderPimAttachList(data.product);
        renderPimList();
        showToast("첨부파일을 삭제했습니다.");
      })
      .catch(function(){
        showToast("서버에 연결할 수 없습니다.");
        btn.disabled = false;
      });
  });
}

function loadProducts(q){
  var url = "/api/products" + (q ? ("?q=" + encodeURIComponent(q)) : "");
  return fetch(url, { cache: "no-store" })
    .then(function(r){ return r.json(); })
    .then(function(data){
      if(!data.ok) return;
      pimProducts = data.products || [];
      renderPimList();
    })
    .catch(function(){ showToast("제품 목록을 불러오지 못했습니다."); });
}

if(pimSearchInput){
  pimSearchInput.addEventListener("input", function(){
    clearTimeout(pimSearchDebounce);
    var q = pimSearchInput.value.trim();
    pimSearchDebounce = setTimeout(function(){ loadProducts(q); }, 200);
  });
}

if(pimList){
  pimList.addEventListener("click", function(e){
    var card = e.target.closest(".pim-internal-card-item");
    if(!card) return;
    var product = pimProducts.find(function(p){ return p.id === card.getAttribute("data-id"); });
    if(!product) return;
    var editBtn = e.target.closest("[data-action='edit']");
    if(editBtn){
      if(typeof canModifyPimUser === "function" && !canModifyPimUser()){
        return;
      }
      openPimEdit(product);
      return;
    }
    openProductDetail(product);
  });
}

function openPimFormModal(){
  if(pimFormModal) pimFormModal.hidden = false;
}

function closePimFormModal(){
  if(pimFormModal) pimFormModal.hidden = true;
  if(pimFormError){
    pimFormError.classList.remove("show");
    pimFormError.textContent = "";
  }
  if(pimIdField) pimIdField.value = "";
  renderPimList();
}

function resetPimForm(){
  if(pimForm) pimForm.reset();
  if(pimIdField) pimIdField.value = "";
  if(pimRevisionField) pimRevisionField.value = "0";
  if(pimFormTitle) pimFormTitle.textContent = "신규 제품 등록";
  if(pimSaveBtn) pimSaveBtn.textContent = "등록";
  if(pimCancelEditBtn) pimCancelEditBtn.hidden = true;
  if(pimProcureCheck) pimProcureCheck.checked = false;
  if(pimProcureFields) pimProcureFields.hidden = true;
  if(pimImageInput) pimImageInput.value = "";
  if(pimImagePreview){
    pimImagePreview.src = "";
    pimImagePreview.style.display = "none";
  }
  if(pimImagePlaceholder) pimImagePlaceholder.style.display = "block";
  if(pimRemoveImageBtn) pimRemoveImageBtn.style.display = "none";
  if(pimAttachInput) pimAttachInput.value = "";
  if(pimAttachList) pimAttachList.innerHTML = "";
  if(pimCustomSpecsList) pimCustomSpecsList.innerHTML = "";
  if(pimCategorySelect) pimCategorySelect.value = pimCategories[0] || "일반";
  if(pimPriceInput) pimPriceInput.value = "";
  setSelectedCurrency("KRW");
  renderPimSpecFields(pimCategorySelect ? pimCategorySelect.value : "일반", {});
  if(pimFormError){
    pimFormError.classList.remove("show");
    pimFormError.textContent = "";
  }
  renderPimList();
}

function openPimEdit(product){
  if(pimIdField) pimIdField.value = product.id;
  if(pimRevisionField) pimRevisionField.value = product.revision || 0;
  if(pimFormTitle) pimFormTitle.textContent = "제품 수정 — " + (product.model || "");
  if(pimSaveBtn) pimSaveBtn.textContent = "수정 저장";
  if(pimCancelEditBtn) pimCancelEditBtn.hidden = false;
  if(pimModelInput) pimModelInput.value = product.model || "";
  if(pimDisplayNameInput) pimDisplayNameInput.value = product.displayName || "";
  if(pimFamilyInput) pimFamilyInput.value = product.family || "";
  if(pimLifecycleSelect) pimLifecycleSelect.value = product.lifecycle || "판매 중";
  if(pimSummaryInput) pimSummaryInput.value = product.summary || "";
  if(pimMemoInput) pimMemoInput.value = product.memo || "";

  var proc = product.procurement;
  var hasProc = !!(proc && (proc.registeredName || proc.identificationNo || proc.configuration));
  if(pimProcureCheck) pimProcureCheck.checked = hasProc;
  if(pimProcureFields) pimProcureFields.hidden = !hasProc;
  if(pimRegNameInput) pimRegNameInput.value = proc ? (proc.registeredName || "") : "";
  if(pimIdNoInput) pimIdNoInput.value = proc ? (proc.identificationNo || "") : "";
  
  var pPrice = (product.price != null && product.price !== "") ? product.price : (proc && proc.price != null ? proc.price : "");
  if(pimPriceInput) pimPriceInput.value = pPrice;
  setSelectedCurrency(product.currency || (proc && proc.currency) || "KRW");
  if(pimConfigInput) pimConfigInput.value = proc ? (proc.configuration || "") : "";

  // Image preview in edit mode
  if(pimImageInput) pimImageInput.value = "";
  var existingImg = (product.attachments || []).find(function(a){
    return /\.(jpg|jpeg|png|webp|gif|svg)$/i.test(a.name);
  });
  if(existingImg && pimImagePreview){
    var imgUrl = "/api/products/attachment?id=" + encodeURIComponent(product.id) + "&file=" + encodeURIComponent(existingImg.name);
    pimImagePreview.src = imgUrl;
    pimImagePreview.style.display = "block";
    if(pimImagePlaceholder) pimImagePlaceholder.style.display = "none";
    if(pimRemoveImageBtn) pimRemoveImageBtn.style.display = "inline-block";
  } else {
    if(pimImagePreview){
      pimImagePreview.src = "";
      pimImagePreview.style.display = "none";
    }
    if(pimImagePlaceholder) pimImagePlaceholder.style.display = "block";
    if(pimRemoveImageBtn) pimRemoveImageBtn.style.display = "none";
  }

  if(pimAttachInput) pimAttachInput.value = "";
  if(pimCategorySelect) pimCategorySelect.value = pimCategories.indexOf(product.category) !== -1 ? product.category : (pimCategories[0] || "일반");
  renderPimSpecFields(pimCategorySelect ? pimCategorySelect.value : "일반", product.specs || {});
  renderPimAttachList(product);
  if(pimFormError){
    pimFormError.classList.remove("show");
    pimFormError.textContent = "";
  }
  renderPimList();
  openPimFormModal();
}

if(pimNewBtn){
  pimNewBtn.addEventListener("click", function(){
    if(typeof canModifyPimUser === "function" && !canModifyPimUser()){
      return;
    }
    resetPimForm();
    openPimFormModal();
  });
}
if(pimCancelEditBtn) pimCancelEditBtn.addEventListener("click", resetPimForm);
if(pimFormCloseBtn) pimFormCloseBtn.addEventListener("click", closePimFormModal);
if(pimFormDismissBtn) pimFormDismissBtn.addEventListener("click", closePimFormModal);
if(pimFormModal){
  pimFormModal.addEventListener("click", function(e){
    if(e.target === pimFormModal) closePimFormModal();
  });
}
if(pimProcureCheck){
  pimProcureCheck.addEventListener("change", function(){
    pimProcureFields.hidden = !pimProcureCheck.checked;
  });
}
if(pimCategorySelect){
  pimCategorySelect.addEventListener("change", function(){
    renderPimSpecFields(pimCategorySelect.value, {});
  });
}

if(pimSelectImageBtn && pimImageInput){
  pimSelectImageBtn.addEventListener("click", function(){
    pimImageInput.click();
  });
}
if(pimImageInput){
  pimImageInput.addEventListener("change", function(){
    var file = pimImageInput.files && pimImageInput.files[0];
    if(file){
      var reader = new FileReader();
      reader.onload = function(e){
        if(pimImagePreview){
          pimImagePreview.src = e.target.result;
          pimImagePreview.style.display = "block";
        }
        if(pimImagePlaceholder) pimImagePlaceholder.style.display = "none";
        if(pimRemoveImageBtn) pimRemoveImageBtn.style.display = "inline-block";
      };
      reader.readAsDataURL(file);
    }
  });
}
if(pimRemoveImageBtn){
  pimRemoveImageBtn.addEventListener("click", function(){
    if(pimImageInput) pimImageInput.value = "";
    if(pimImagePreview){
      pimImagePreview.src = "";
      pimImagePreview.style.display = "none";
    }
    if(pimImagePlaceholder) pimImagePlaceholder.style.display = "block";
    pimRemoveImageBtn.style.display = "none";
  });
}
if(pimAddCustomSpecBtn){
  pimAddCustomSpecBtn.addEventListener("click", function(){
    addCustomSpecRow("", "");
  });
}

if(pimForm){
  pimForm.addEventListener("submit", function(e){
    e.preventDefault();
    var isEdit = !!pimIdField.value;
    var rawPrice = pimPriceInput ? pimPriceInput.value.trim() : "";
    var payload = {
      mode: isEdit ? "edit" : "create",
      model: pimModelInput.value.trim(),
      displayName: pimDisplayNameInput.value.trim(),
      family: pimFamilyInput.value.trim(),
      lifecycle: pimLifecycleSelect.value,
      price: rawPrice,
      currency: getSelectedCurrency(),
      summary: pimSummaryInput.value.trim(),
      memo: pimMemoInput.value.trim(),
      category: pimCategorySelect.value,
      specs: collectPimSpecs()
    };
    if(isEdit){
      payload.id = pimIdField.value;
      payload.revision = Number(pimRevisionField.value || 0);
    }
    if(pimProcureCheck && pimProcureCheck.checked){
      payload.procurement = {
        enabled: true,
        registeredName: pimRegNameInput.value.trim(),
        identificationNo: pimIdNoInput.value.trim(),
        price: rawPrice,
        currency: getSelectedCurrency(),
        configuration: pimConfigInput.value.trim()
      };
    } else {
      payload.procurement = false;
    }
    pimSaveBtn.disabled = true;
    var postFn = (typeof apiPostJson === "function") ? apiPostJson : (typeof apiPost === "function" ? apiPost : null);
    if (!postFn) {
      pimSaveBtn.disabled = false;
      return;
    }
    postFn("/api/products/save", payload)
      .then(function(data){
        if(!data || !data.ok){
          pimSaveBtn.disabled = false;
          var msg = (data && data.errors && data.errors.join(" / ")) || (data && data.error) || "저장에 실패했습니다.";
          pimFormError.textContent = msg;
          pimFormError.classList.add("show");
          return;
        }
        var product = data.product;
        var pendingImg = (pimImageInput && pimImageInput.files && pimImageInput.files.length) ? pimImageInput.files[0] : null;
        var pendingFiles = (pimAttachInput && pimAttachInput.files && pimAttachInput.files.length) ? pimAttachInput.files : null;
        
        var uploadPromises = [];
        if(pendingImg){
          uploadPromises.push(uploadPimAttachments(product.id, [pendingImg]));
        }
        if(pendingFiles && pendingFiles.length){
          uploadPromises.push(uploadPimAttachments(product.id, pendingFiles));
        }

        var allUploads = uploadPromises.length ? Promise.all(uploadPromises) : Promise.resolve();
        allUploads.then(function(){
          pimSaveBtn.disabled = false;
          showToast(isEdit ? "제품 정보를 수정했습니다." : "제품을 등록했습니다.");
          closePimFormModal();
          loadProducts(pimSearchInput.value.trim());
        });
      })
      .catch(function(){
        pimSaveBtn.disabled = false;
        pimFormError.textContent = "서버에 연결할 수 없습니다.";
        pimFormError.classList.add("show");
      });
  });
}

function uploadPimAttachments(productId, fileList){
  var fd = new FormData();
  fd.append("id", productId);
  Array.prototype.forEach.call(fileList, function(file){ fd.append("files", file); });
  var headers = {};
  var csrfToken = sessionStorage.getItem("argosCsrfToken") || localStorage.getItem("argosCsrfToken");
  if(csrfToken) headers["X-CSRF-Token"] = csrfToken;
  return fetch("/api/products/attachments/upload", { method: "POST", headers: headers, credentials: "same-origin", body: fd })
    .then(function(r){ return r.json(); })
    .then(function(data){
      if(!data.ok){
        showToast(data.error || "첨부파일 업로드에 실패했습니다.");
        return null;
      }
      return data.product;
    })
    .catch(function(){
      showToast("첨부파일 업로드 중 서버에 연결할 수 없습니다.");
      return null;
    });
}

// ==========================================
// VISION119.COM LIVE WEB VIEWER (OPTION A)
// ==========================================
var pimMode = "internal"; // "internal" | "web"
var currentWebCateId = "all";
var webProducts = [];
var webSearchTimer = null;

var pimModeWebBtn = document.getElementById("pimModeWebBtn");
var pimModeInternalBtn = document.getElementById("pimModeInternalBtn");
var pimModeCaption = document.getElementById("pimModeCaption");
var pimWebView = document.getElementById("pimWebView");
var pimInternalView = document.getElementById("pimInternalView");
var pimWebCatChips = document.getElementById("pimWebCatChips");
var pimWebSearchInput = document.getElementById("pimWebSearchInput");
var pimWebRefreshBtn = document.getElementById("pimWebRefreshBtn");
var pimWebCounter = document.getElementById("pimWebCounter");
var pimWebGrid = document.getElementById("pimWebGrid");
var pimWebEmpty = document.getElementById("pimWebEmpty");

// Modal Elements
var pimDetailModal = document.getElementById("pimDetailModal");
var pimModalCatBadge = document.getElementById("pimModalCatBadge");
var pimModalModel = document.getElementById("pimModalModel");
var pimModalProcBadge = document.getElementById("pimModalProcBadge");
var pimModalCloseBtn = document.getElementById("pimModalCloseBtn");
var pimModalBody = document.getElementById("pimModalBody");
var pimModalPdfBtn = document.getElementById("pimModalPdfBtn");
var pimModalWebLink = document.getElementById("pimModalWebLink");
var pimModalDismissBtn = document.getElementById("pimModalDismissBtn");
var pimModalEditBtn = document.getElementById("pimModalEditBtn");
var currentDetailProduct = null;

function setPimMode(mode){
  pimMode = mode;
  if(mode === "web"){
    if(pimModeWebBtn) pimModeWebBtn.classList.add("active");
    if(pimModeInternalBtn) pimModeInternalBtn.classList.remove("active");
    if(pimWebView) pimWebView.hidden = false;
    if(pimInternalView) pimInternalView.hidden = true;
    if(pimModeCaption) pimModeCaption.textContent = "";
    if(!webProducts || !webProducts.length){
      loadVision119Products(currentWebCateId);
    }
  } else {
    if(pimModeInternalBtn) pimModeInternalBtn.classList.add("active");
    if(pimModeWebBtn) pimModeWebBtn.classList.remove("active");
    if(pimWebView) pimWebView.hidden = true;
    if(pimInternalView) pimInternalView.hidden = false;
    if(pimModeCaption) pimModeCaption.textContent = "";
    loadProducts(pimSearchInput ? pimSearchInput.value.trim() : "");
  }
}

function loadVision119Products(cateId, query){
  if(cateId != null) currentWebCateId = cateId;
  var q = (query != null) ? query : (pimWebSearchInput ? pimWebSearchInput.value.trim() : "");

  if(pimWebCounter) pimWebCounter.textContent = "제품 목록을 불러오는 중...";
  if(pimWebEmpty) pimWebEmpty.hidden = true;
  if(pimWebGrid){
    pimWebGrid.innerHTML = '<div style="grid-column: 1/-1; text-align: center; padding: 48px 16px; color: var(--ink-soft); font-size: 13.5px;">' +
      '제품 데이터를 조회하고 있습니다...</div>';
  }

  var url = "/api/external/vision119/products?cateId=" + encodeURIComponent(currentWebCateId) + "&q=" + encodeURIComponent(q);

  apiGet(url)
    .then(function(data){
      if(!data || !data.ok){
        if(pimWebCounter) pimWebCounter.textContent = "제품 정보를 불러오지 못했습니다.";
        if(pimWebGrid){
          pimWebGrid.innerHTML = '<div style="grid-column: 1/-1; text-align: center; padding: 40px; color: var(--danger); font-size: 13px;">' +
            '제품 목록을 가져올 수 없거나 응답이 지연되었습니다.<br>' +
            '<button type="button" class="btn-secondary" style="margin-top:12px;" onclick="loadVision119Products()">다시 시도</button></div>';
        }
        return;
      }
      webProducts = data.products || [];
      var total = (data.total != null) ? data.total : webProducts.length;
      if(pimWebCounter) pimWebCounter.textContent = "총 " + total + "개 제품";
      renderVision119Grid(webProducts);
    })
    .catch(function(err){
      if(pimWebCounter) pimWebCounter.textContent = "서버 연결 오류";
      if(pimWebGrid){
        pimWebGrid.innerHTML = '<div style="grid-column: 1/-1; text-align: center; padding: 40px; color: var(--danger); font-size: 13px;">' +
          '서버와 통신하는 중 오류가 발생했습니다.<br>' +
          '<button type="button" class="btn-secondary" style="margin-top:12px;" onclick="loadVision119Products()">다시 시도</button></div>';
      }
    });
}

function renderVision119Grid(items){
  if(!pimWebGrid) return;
  if(!items || !items.length){
    pimWebGrid.innerHTML = "";
    if(pimWebEmpty) pimWebEmpty.hidden = false;
    return;
  }
  if(pimWebEmpty) pimWebEmpty.hidden = true;

  var fallbackImg = "data:image/svg+xml;charset=utf-8,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20width%3D%22200%22%20height%3D%22150%22%20viewBox%3D%220%200%20200%20150%22%3E%3Crect%20fill%3D%22%23f3f4f6%22%20width%3D%22200%22%20height%3D%22150%22%2F%3E%3Ctext%20fill%3D%22%239ca3af%22%20font-family%3D%22sans-serif%22%20font-size%3D%2213%22%20x%3D%2250%25%22%20y%3D%2250%25%22%20text-anchor%3D%22middle%22%20dy%3D%22.3em%22%3ENo%20Image%3C%2Ftext%3E%3C%2Fsvg%3E";

  var html = items.map(function(p){
    var thumb = p.thumb ? escapeHtml(p.thumb) : fallbackImg;
    var model = escapeHtml(p.model || "");
    var cat = escapeHtml(p.category || "기타");
    var summary = escapeHtml(p.summary || "");
    var cateId = escapeHtml(p.cateId || "1");
    var bbsId = escapeHtml(p.bbsId || "");
    var sourceUrl = escapeHtml(p.sourceUrl || "#");

    return '<div class="pim-web-card">' +
      '<div class="pim-card-thumb-wrap">' +
        '<img class="pim-card-thumb" src="' + thumb + '" alt="' + model + '" loading="lazy" onerror="this.src=\'' + fallbackImg + '\'">' +
        '<span class="pim-card-category-badge">' + cat + '</span>' +
      '</div>' +
      '<div class="pim-card-info">' +
        '<div class="pim-card-model" title="' + model + '">' + model + '</div>' +
        '<div class="pim-card-summary" title="' + summary + '">' + summary + '</div>' +
        '<div class="pim-card-actions">' +
          '<button type="button" class="pim-btn-spec" onclick="openVision119Detail(\'' + cateId + '\', \'' + bbsId + '\')">🔍 상세 사양 보기</button>' +
          '<a href="' + sourceUrl + '" target="_blank" rel="noopener noreferrer" class="pim-btn-pdf" title="공식 페이지 새 창 열기">🌐 원본</a>' +
        '</div>' +
      '</div>' +
    '</div>';
  }).join("");

  pimWebGrid.innerHTML = html;
}

function openVision119Detail(cateId, bbsId){
  if(!pimDetailModal) return;
  pimDetailModal.hidden = false;
  if(pimModalModel) pimModalModel.textContent = "제품 사양 불러오는 중...";
  if(pimModalCatBadge) pimModalCatBadge.textContent = "...";
  if(pimModalProcBadge) pimModalProcBadge.hidden = true;
  if(pimModalPdfBtn) pimModalPdfBtn.hidden = true;
  if(pimModalBody){
    pimModalBody.innerHTML = '<div style="text-align: center; padding: 60px 20px; color: var(--ink-soft); font-size: 13.5px;">' +
      '상세 사양과 조달 정보를 가져오고 있습니다...</div>';
  }

  apiGet("/api/external/vision119/detail?cateId=" + encodeURIComponent(cateId) + "&bbsId=" + encodeURIComponent(bbsId))
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
      if(pimModalModel) pimModalModel.textContent = d.model || "제품 상세";
      if(pimModalCatBadge) pimModalCatBadge.textContent = d.category || "공통";

      if(pimModalProcBadge){
        if(d.procurementNo){
          pimModalProcBadge.textContent = "조달식별번호: " + d.procurementNo;
          pimModalProcBadge.hidden = false;
        } else {
          pimModalProcBadge.hidden = true;
        }
      }

      if(pimModalWebLink){
        pimModalWebLink.href = d.sourceUrl || "http://www.vision119.com";
      }

      if(pimModalPdfBtn){
        if(d.catalogPdf){
          pimModalPdfBtn.href = d.catalogPdf;
          pimModalPdfBtn.hidden = false;
        } else {
          pimModalPdfBtn.hidden = true;
        }
      }

      // Build Modal Body
      var fallbackImg = "data:image/svg+xml;charset=utf-8,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20width%3D%22200%22%20height%3D%22150%22%20viewBox%3D%220%200%20200%20150%22%3E%3Crect%20fill%3D%22%23f3f4f6%22%20width%3D%22200%22%20height%3D%22150%22%2F%3E%3Ctext%20fill%3D%22%239ca3af%22%20font-family%3D%22sans-serif%22%20font-size%3D%2213%22%20x%3D%2250%25%22%20y%3D%2250%25%22%20text-anchor%3D%22middle%22%20dy%3D%22.3em%22%3ENo%20Image%3C%2Ftext%3E%3C%2Fsvg%3E";
      var imgSrc = d.image ? escapeHtml(d.image) : fallbackImg;

      var bulletsHtml = "";
      if(d.eng){
        bulletsHtml += '<p style="font-size:13px; font-weight:600; color:var(--ink); margin-bottom:10px; line-height:1.4;">' + escapeHtml(d.eng) + '</p>';
      }
      if(d.bullets && d.bullets.length){
        bulletsHtml += '<div class="pim-modal-bullets">' +
          d.bullets.map(function(b){
            return '<div class="pim-modal-bullet-item">' + escapeHtml(b) + '</div>';
          }).join("") +
          '</div>';
      } else if(!d.eng){
        bulletsHtml += '<p style="font-size:12.5px; color:var(--ink-soft); font-style:italic;">기본 설명이 없습니다.</p>';
      }

      var specsTableHtml = "";
      if(d.specs && Object.keys(d.specs).length > 0){
        var rows = Object.keys(d.specs).map(function(key){
          var lbl = getSpecDisplayLabel(key, null);
          return '<tr><th>' + escapeHtml(lbl) + '</th><td>' + escapeHtml(d.specs[key]) + '</td></tr>';
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
}

function openProductDetail(product){
  if(!pimDetailModal || !product) return;
  currentDetailProduct = product;
  pimDetailModal.hidden = false;

  var model = product.model || "";
  var displayName = product.displayName || "";
  var title = displayName ? (model + " — " + displayName) : model;
  if(pimModalModel) pimModalModel.textContent = title || "제품 상세 정보";
  if(pimModalCatBadge) pimModalCatBadge.textContent = product.category || "일반";

  var proc = product.procurement;
  if(pimModalProcBadge){
    if(proc && proc.identificationNo){
      pimModalProcBadge.textContent = "조달식별번호: " + proc.identificationNo;
      pimModalProcBadge.hidden = false;
    } else {
      pimModalProcBadge.hidden = true;
    }
  }

  // Find image attachment
  var fallbackImg = "data:image/svg+xml;charset=utf-8,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20width%3D%22200%22%20height%3D%22150%22%20viewBox%3D%220%200%20200%20150%22%3E%3Crect%20fill%3D%22%23f3f4f6%22%20width%3D%22200%22%20height%3D%22150%22%20viewBox%3D%220%200%20200%20150%22%3E%3Ctext%20fill%3D%22%239ca3af%22%20font-family%3D%22sans-serif%22%20font-size%3D%2213%22%20x%3D%2250%25%22%20y%3D%2250%25%22%20text-anchor%3D%22middle%22%20dy%3D%22.3em%22%3ENo%20Image%3C%2Ftext%3E%3C%2Fsvg%3E";
  var imgAttach = (product.attachments || []).find(function(a){
    return /\.(jpg|jpeg|png|webp|gif|svg)$/i.test(a.name);
  });
  var imgSrc = imgAttach
    ? ("/api/products/attachment?id=" + encodeURIComponent(product.id) + "&file=" + encodeURIComponent(imgAttach.name))
    : fallbackImg;

  // Find PDF attachment if any
  var pdfAttach = (product.attachments || []).find(function(a){
    return /\.pdf$/i.test(a.name);
  });
  if(pimModalPdfBtn){
    if(pdfAttach){
      pimModalPdfBtn.href = "/api/products/attachment?id=" + encodeURIComponent(product.id) + "&file=" + encodeURIComponent(pdfAttach.name);
      pimModalPdfBtn.hidden = false;
    } else {
      pimModalPdfBtn.hidden = true;
    }
  }
  if(pimModalWebLink){
    pimModalWebLink.hidden = true;
  }
  if(pimModalEditBtn){
    pimModalEditBtn.hidden = !(typeof canModifyPimUser === "function" && canModifyPimUser());
  }

  // Meta items
  var rawPrice = (product.price != null && product.price !== "" && Number(product.price) > 0)
    ? product.price
    : (proc && proc.price ? proc.price : null);
  var curr = (product.currency || (proc && proc.currency) || "KRW").toUpperCase();
  var displayPrice = rawPrice
    ? (Number(rawPrice).toLocaleString() + " " + curr)
    : "미설정";

  var metaHtml = '<div style="display:flex; flex-direction:column; gap:8px;">' +
    '<div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap;">' +
      '<span class="pim-badge ' + pimLifecycleBadgeClass(product.lifecycle) + '">' + escapeHtml(product.lifecycle || "판매 중") + '</span>' +
      (product.family ? '<span class="pim-badge" style="background:var(--code-bg); color:var(--ink-soft); font-weight:600;">' + escapeHtml(product.family) + '</span>' : '') +
      '<span class="pim-badge" style="background:rgba(16,185,129,0.1); color:#10b981; font-weight:700;">' + displayPrice + '</span>' +
    '</div>' +
    '<div style="font-size:17px; font-weight:700; color:var(--ink); margin-top:2px;">' + escapeHtml(displayName || model) + '</div>' +
    '<div style="font-size:12.5px; color:var(--ink-soft);">제품 코드 / 모델명: <strong style="color:var(--ink);">' + escapeHtml(model) + '</strong></div>' +
    (product.summary ? '<div style="font-size:13px; color:var(--ink); line-height:1.5; background:var(--bg-hover, rgba(0,0,0,0.02)); padding:10px 12px; border-radius:6px; border:1px solid var(--line); margin-top:6px;">' + escapeHtml(product.summary) + '</div>' : '') +
  '</div>';

  // Specifications Table
  var specs = product.specs || {};
  var specKeys = Object.keys(specs).filter(function(k){ return specs[k] && String(specs[k]).trim(); });
  var specsTableHtml = "";
  if(specKeys.length > 0){
    var specRows = specKeys.map(function(k){
      var label = getSpecDisplayLabel(k, product.category);
      return '<tr><th style="width:35%; font-weight:600;">' + escapeHtml(label) + '</th><td>' + escapeHtml(specs[k]) + '</td></tr>';
    }).join("");
    specsTableHtml = '<div class="pim-modal-specs-table-wrap">' +
      '<h3 class="pim-modal-specs-title">📋 제품 세부 기술 사양 (총 ' + specKeys.length + '개 항목)</h3>' +
      '<table class="pim-specs-table"><tbody>' + specRows + '</tbody></table>' +
      '</div>';
  } else {
    specsTableHtml = '<div class="pim-modal-specs-table-wrap">' +
      '<h3 class="pim-modal-specs-title">📋 제품 세부 기술 사양</h3>' +
      '<p style="font-size:12.5px; color:var(--ink-soft); padding:12px 0;">등록된 기술 사양이 없습니다.</p>' +
      '</div>';
  }

  // Procurement Section (if registered)
  var procHtml = "";
  if(proc && (proc.identificationNo || proc.registeredName || proc.configuration)){
    procHtml = '<div class="pim-modal-specs-table-wrap">' +
      '<h3 class="pim-modal-specs-title">🏛️ 공공 조달 등록 정보 (G2B)</h3>' +
      '<table class="pim-specs-table"><tbody>' +
        (proc.registeredName ? '<tr><th style="width:35%;">조달 식별명</th><td>' + escapeHtml(proc.registeredName) + '</td></tr>' : '') +
        (proc.identificationNo ? '<tr><th style="width:35%;">물품식별번호</th><td>' + escapeHtml(proc.identificationNo) + '</td></tr>' : '') +
        (proc.configuration ? '<tr><th style="width:35%;">공급 구성</th><td>' + escapeHtml(proc.configuration) + '</td></tr>' : '') +
      '</tbody></table>' +
      '</div>';
  }

  // Attachments & Documents Section
  var attachList = product.attachments || [];
  var attachHtml = "";
  if(attachList.length > 0){
    var attachItems = attachList.map(function(a){
      var isImg = /\.(jpg|jpeg|png|webp|gif|svg)$/i.test(a.name);
      var icon = isImg ? "🖼️ " : (/\.pdf$/i.test(a.name) ? "📑 " : "📄 ");
      var url = "/api/products/attachment?id=" + encodeURIComponent(product.id) + "&file=" + encodeURIComponent(a.name);
      return '<div style="display:flex; align-items:center; justify-content:space-between; background:var(--surface); border:1px solid var(--line); border-radius:6px; padding:8px 12px; font-size:12.5px;">' +
        '<div style="display:flex; align-items:center; gap:8px; overflow:hidden;">' +
          '<span>' + icon + '</span>' +
          '<span style="font-weight:600; color:var(--ink); text-overflow:ellipsis; overflow:hidden; white-space:nowrap;">' + escapeHtml(a.name) + '</span>' +
          '<span style="font-size:11px; color:var(--ink-faint); margin-left:4px;">(' + formatFileSize(a.size) + ')</span>' +
        '</div>' +
        '<a href="' + url + '" target="_blank" rel="noopener" class="btn-secondary" style="padding:4px 10px; font-size:11.5px; text-decoration:none; flex-shrink:0;">열기 / 다운로드 ↗</a>' +
      '</div>';
    }).join("");

    attachHtml = '<div class="pim-modal-specs-table-wrap">' +
      '<h3 class="pim-modal-specs-title">📎 관련 첨부파일 및 문서 (' + attachList.length + '개)</h3>' +
      '<div style="display:flex; flex-direction:column; gap:6px;">' + attachItems + '</div>' +
      '</div>';
  }

  // Internal Memo Section (if any)
  var memoHtml = "";
  if(product.memo){
    memoHtml = '<div class="pim-modal-specs-table-wrap">' +
      '<h3 class="pim-modal-specs-title">📝 사내 참고 메모</h3>' +
      '<div style="font-size:12.5px; color:var(--ink-soft); background:var(--code-bg); padding:10px 12px; border-radius:6px; border:1px solid var(--line); white-space:pre-wrap; line-height:1.5;">' + escapeHtml(product.memo) + '</div>' +
      '</div>';
  }

  if(pimModalBody){
    pimModalBody.innerHTML = '<div class="pim-modal-top-section">' +
      '<div class="pim-modal-img-wrap" style="height:220px; cursor:zoom-in;" onclick="window.open(\'' + imgSrc + '\', \'_blank\')" title="클릭하여 원본 크기로 보기">' +
        '<img class="pim-modal-img" src="' + imgSrc + '" alt="' + escapeHtml(model) + '" onerror="this.src=\'' + fallbackImg + '\'">' +
      '</div>' +
      '<div>' + metaHtml + '</div>' +
    '</div>' +
    specsTableHtml +
    procHtml +
    attachHtml +
    memoHtml;
  }
}

function closeVision119Detail(){
  if(pimDetailModal) pimDetailModal.hidden = true;
  currentDetailProduct = null;
}

// Mode Switcher Listeners
if(pimModeWebBtn){
  pimModeWebBtn.addEventListener("click", function(){ setPimMode("web"); });
}
if(pimModeInternalBtn){
  pimModeInternalBtn.addEventListener("click", function(){ setPimMode("internal"); });
}

// Category Chips Listeners
if(pimWebCatChips){
  pimWebCatChips.querySelectorAll(".pim-cat-chip").forEach(function(chip){
    chip.addEventListener("click", function(){
      pimWebCatChips.querySelectorAll(".pim-cat-chip").forEach(function(c){ c.classList.remove("active"); });
      chip.classList.add("active");
      var cate = chip.getAttribute("data-cate") || "all";
      loadVision119Products(cate, pimWebSearchInput ? pimWebSearchInput.value.trim() : "");
    });
  });
}

// Search Input Listener with Debounce
if(pimWebSearchInput){
  pimWebSearchInput.addEventListener("input", function(){
    clearTimeout(webSearchTimer);
    webSearchTimer = setTimeout(function(){
      loadVision119Products(currentWebCateId, pimWebSearchInput.value.trim());
    }, 300);
  });
}

// Refresh Button Listener
if(pimWebRefreshBtn){
  pimWebRefreshBtn.addEventListener("click", function(){
    loadVision119Products(currentWebCateId, pimWebSearchInput ? pimWebSearchInput.value.trim() : "");
  });
}

// Modal Dismiss Listeners
if(pimModalCloseBtn){
  pimModalCloseBtn.addEventListener("click", closeVision119Detail);
}
if(pimModalDismissBtn){
  pimModalDismissBtn.addEventListener("click", closeVision119Detail);
}
if(pimModalEditBtn){
  pimModalEditBtn.addEventListener("click", function(){
    if(currentDetailProduct){
      var target = currentDetailProduct;
      closeVision119Detail();
      openPimEdit(target);
    }
  });
}
if(pimDetailModal){
  pimDetailModal.addEventListener("click", function(e){
    if(e.target === pimDetailModal) closeVision119Detail();
  });
}
document.addEventListener("keydown", function(e){
  if(e.key === "Escape"){
    if(pimFormModal && !pimFormModal.hidden){
      closePimFormModal();
    } else if(pimDetailModal && !pimDetailModal.hidden){
      closeVision119Detail();
    }
  }
});

var pimSyncLiveBtn = document.getElementById("pimSyncLiveBtn");

function triggerLiveSync(){
  if(typeof loadVision119Products === "function"){
    var q = pimWebSearchInput ? pimWebSearchInput.value.trim() : "";
    return loadVision119Products(currentWebCateId, q);
  }
}
if(pimSyncLiveBtn){
  pimSyncLiveBtn.addEventListener("click", triggerLiveSync);
}

function initPimTab(){
  loadPimCategories();
  loadProducts();
}

// Expose to window for global access
window.loadVision119Products = loadVision119Products;
window.openVision119Detail = openVision119Detail;
window.openProductDetail = openProductDetail;
window.closeVision119Detail = closeVision119Detail;
window.openPimFormModal = openPimFormModal;
window.closePimFormModal = closePimFormModal;
window.triggerLiveSync = triggerLiveSync;
window.setPimMode = setPimMode;
window.initPimTab = initPimTab;


window.addEventListener("langchange", function(){
  if(typeof renderPimList === "function") renderPimList();
});
