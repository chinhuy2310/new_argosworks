// notifications.js — ARGOS WORKS Topbar Notification Popover & Alerts
// =========================================================================

(function(){
  var notifBtn = null;
  var notifMenu = null;
  var notifList = null;
  var notifBadge = null;
  var notifPill = null;
  var markAllBtn = null;
  var soundBtn = null;
  var pushBanner = null;
  var enablePushBtn = null;
  var testPushBtn = null;
  var tabBtns = [];

  var allNotifications = [];
  var currentFilter = "all";
  var READ_STORAGE_KEY = "argos_read_notifications_v1";
  var SOUND_STORAGE_KEY = "argos_notif_sound_enabled";

  var notifiedIds = {};
  var isFirstFetch = true;

  function isSoundEnabled(){
    try {
      var val = localStorage.getItem(SOUND_STORAGE_KEY);
      return val === null ? true : val === "true";
    } catch(e) {
      return true;
    }
  }

  function setSoundEnabled(enabled){
    try {
      localStorage.setItem(SOUND_STORAGE_KEY, enabled ? "true" : "false");
    } catch(e) {}
    updateSoundBtn();
  }

  function updateSoundBtn(){
    if(!soundBtn) return;
    var on = isSoundEnabled();
    soundBtn.textContent = on ? "🔊" : "🔇";
    soundBtn.title = on ? "알림음 토글 (켜짐)" : "알림음 토글 (음소거)";
    soundBtn.setAttribute("aria-label", on ? "알림음 켜짐" : "알림음 음소거");
  }

  function playNotifChime(){
    if(!isSoundEnabled()) return;
    try {
      var AudioCtx = window.AudioContext || window.webkitAudioContext;
      if(!AudioCtx) return;
      var ctx = new AudioCtx();
      var now = ctx.currentTime;

      // Tone 1: D5 (587.33 Hz)
      var osc1 = ctx.createOscillator();
      var gain1 = ctx.createGain();
      osc1.type = "sine";
      osc1.frequency.setValueAtTime(587.33, now);
      gain1.gain.setValueAtTime(0.12, now);
      gain1.gain.exponentialRampToValueAtTime(0.001, now + 0.22);
      osc1.connect(gain1);
      gain1.connect(ctx.destination);
      osc1.start(now);
      osc1.stop(now + 0.25);

      // Tone 2: A5 (880.00 Hz)
      var osc2 = ctx.createOscillator();
      var gain2 = ctx.createGain();
      osc2.type = "sine";
      osc2.frequency.setValueAtTime(880.00, now + 0.12);
      gain2.gain.setValueAtTime(0.14, now + 0.12);
      gain2.gain.exponentialRampToValueAtTime(0.001, now + 0.38);
      osc2.connect(gain2);
      gain2.connect(ctx.destination);
      osc2.start(now + 0.12);
      osc2.stop(now + 0.40);
    } catch(e) {}
  }

  function updatePushBanner(){
    if(!pushBanner) return;
    if(!("Notification" in window)){
      pushBanner.hidden = true;
      return;
    }
    if(Notification.permission === "default"){
      pushBanner.hidden = false;
    } else {
      pushBanner.hidden = true;
    }
  }

  function requestPushPermission(){
    if(!("Notification" in window)){
      if(typeof showToast === "function") showToast("현재 브라우저에서는 데스크톱 알림을 지원하지 않습니다.");
      return;
    }
    Notification.requestPermission().then(function(perm){
      updatePushBanner();
      if(perm === "granted"){
        if(typeof showToast === "function") showToast("✅ 데스크톱 실시간 알림이 허용되었습니다.");
        triggerDesktopNotification({
          title: "ARGOS WORKS",
          desc: "데스크톱 실시간 알림이 성공적으로 활성화되었습니다.",
          tag: "연결성공"
        });
        playNotifChime();
      } else if(perm === "denied"){
        if(typeof showToast === "function") showToast("⚠️ 브라우저 주소창에서 알림 권한을 허용할 수 있습니다.");
      }
    });
  }

  function triggerDesktopNotification(item){
    if(!("Notification" in window) || Notification.permission !== "granted") return;
    try {
      var title = item.title || "ARGOS WORKS 알림";
      var body = item.content || item.desc || "";
      if(item.tag) body = "[" + item.tag + "] " + body;

      var n = new Notification(title, {
        body: body,
        icon: "/favicon.svg",
        tag: item.id || ("argos_" + Date.now()),
        renotify: false
      });

      n.onclick = function(){
        window.focus();
        if(item.id) markIdAsRead(item.id);
        n.close();

        var tag = item.tag || "";
        var title = item.title || "";
        if(tag === "가입요청" || tag === "가입승인" || title.indexOf("가입 승인") !== -1 || title.indexOf("계정 발급") !== -1){
          if(typeof showTab === "function") showTab("settings");
          if(typeof switchSettingsTab === "function") switchSettingsTab("users");
          setTimeout(function(){
            var filterStatus = document.getElementById("adminUserFilterStatus");
            if(filterStatus){
              filterStatus.value = "pending";
              if(typeof renderAdminUsersTable === "function") renderAdminUsersTable();
            }
            if(typeof loadAdminUsers === "function") loadAdminUsers();
          }, 100);
          return;
        }

        if(item.record_id){
          if(typeof window.showIssueInCanvas === "function"){
            window.showIssueInCanvas(item.record_id);
          } else if(typeof showTab === "function"){
            showTab("dash");
          }
          return;
        }

        if(typeof showTab === "function"){
          showTab("dash");
        }
      };
    } catch(e){
      console.warn("Failed to trigger desktop notification:", e);
    }
  }

  function getReadIds(){
    try {
      var raw = localStorage.getItem(READ_STORAGE_KEY);
      return raw ? JSON.parse(raw) : [];
    } catch(e) {
      return [];
    }
  }

  function setReadIds(ids){
    try {
      localStorage.setItem(READ_STORAGE_KEY, JSON.stringify(ids));
    } catch(e) {}
  }

  function markIdAsRead(id){
    if(!id) return;
    var ids = getReadIds();
    if(ids.indexOf(id) === -1){
      ids.push(id);
      setReadIds(ids);
    }
    allNotifications.forEach(function(item){
      if(item.id === id) item.is_read = true;
    });
    updateBadge();
    renderList();
    if(typeof apiPost === "function"){
      apiPost("/api/notifications/read", { id: id }).catch(function(){});
    }
  }

  function markAllAsRead(){
    var ids = getReadIds();
    allNotifications.forEach(function(item){
      item.is_read = true;
      if(ids.indexOf(item.id) === -1){
        ids.push(item.id);
      }
    });
    setReadIds(ids);
    updateBadge();
    renderList();
    if(typeof apiPost === "function"){
      apiPost("/api/notifications/read-all", {}).catch(function(){});
    }
    if(typeof showToast === "function"){
      showToast("모든 알림을 읽음 처리했습니다.");
    }
  }

  function formatRelativeTime(timeStr){
    if(!timeStr) return "";
    try {
      var d = new Date(timeStr.replace(" ", "T"));
      if(isNaN(d.getTime())) return timeStr;
      var now = new Date();
      var diffMs = now.getTime() - d.getTime();
      var diffSec = Math.floor(diffMs / 1000);
      if(diffSec < 60) return "방금 전";
      var diffMin = Math.floor(diffSec / 60);
      if(diffMin < 60) return diffMin + "분 전";
      var diffHour = Math.floor(diffMin / 60);
      if(diffHour < 24) return diffHour + "시간 전";
      var diffDay = Math.floor(diffHour / 24);
      if(diffDay === 1) return "어제";
      if(diffDay < 7) return diffDay + "일 전";
      var mm = String(d.getMonth() + 1).padStart(2, "0");
      var dd = String(d.getDate()).padStart(2, "0");
      return mm + "." + dd;
    } catch(e){
      return timeStr;
    }
  }

  function resolveNotificationCategory(item){
    if(!item) return "assign";
    var type = String(item.type || "").toLowerCase().trim();
    var tag = String(item.tag || "").toLowerCase().trim();
    var tagType = String(item.tag_type || "").toLowerCase().trim();
    var title = String(item.title || "").toLowerCase().trim();

    // 1. Phê duyệt tài khoản mới (Account Signup Approval)
    if(type === "signup" || tagType === "signup" || tag === "가입요청" || tag === "가입" || title.indexOf("가입 승인") !== -1 || title.indexOf("신규 계정") !== -1){
      return "signup";
    }

    // 2. Yêu cầu xem xét / xét duyệt công việc (Review Request)
    if(type === "review" || tagType === "review" || tag === "검토요청" || tag === "검토" || title.indexOf("검토 요청") !== -1 || title.indexOf("검토") !== -1){
      return "review";
    }

    // 3. Hạn chót, D-Day, khẩn cấp (Deadline / Urgent)
    if(type === "deadline" || tag === "지연" || tag === "d-day" || tag === "긴급" || title.indexOf("마감") !== -1 || title.indexOf("지연") !== -1 || tagType === "urgent"){
      return "deadline";
    }

    // 4. Bình luận mới (Comment)
    if(type === "comment" || tag === "댓글" || title.indexOf("댓글") !== -1){
      return "comment";
    }

    // 5. Thay đổi trạng thái công việc (Status Change / Done)
    if(type === "status" || tag === "상태" || title.indexOf("상태 변경") !== -1){
      if(tag === "완료" || title.indexOf("완료") !== -1 || title.indexOf("done") !== -1 || tagType === "done"){
        return "status-done";
      }
      return "status";
    }

    // 6. Liên kết Jira (Jira Sync / Push)
    if(type === "jira" || tag.indexOf("jira") !== -1 || title.indexOf("jira") !== -1){
      return "jira";
    }

    // 7. Lịch biểu / Lịch công tác (Schedule / Calendar)
    if(type === "schedule" || tag === "일정" || tag === "캘린더" || title.indexOf("일정") !== -1){
      return "schedule";
    }

    // 8. Cảnh báo bảo mật / Hệ thống (Security / System / License)
    if(type === "security" || type === "system" || tag === "보안" || tag === "시스템" || tag === "라이선스" || title.indexOf("라이선스") !== -1 || title.indexOf("보안") !== -1){
      return "security";
    }

    // 9. Nhắc tên (@mention)
    if(type === "mention" || tag === "멘션" || title.indexOf("멘션") !== -1){
      return "mention";
    }

    // 10. Phân công người phụ trách (Assignment)
    return "assign";
  }

  function getIconSvg(type, item){
    var cat = item ? resolveNotificationCategory(item) : (type || "assign");
    switch(cat){
      case "review":
        // Clipboard Checkmark - Đánh giá / Phê duyệt công việc
        return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"></path><rect x="8" y="2" width="8" height="4" rx="1" ry="1"></rect><path d="m9 14 2 2 4-4"></path></svg>';
      case "signup":
        // User with Shield / Key - Duyệt tài khoản người dùng mới
        return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"></path><circle cx="9" cy="7" r="4"></circle><polyline points="16 11 18 13 22 9"></polyline></svg>';
      case "deadline":
        // Alarm Clock - Hạn chót / Quá hạn khẩn cấp
        return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="13" r="8"></circle><polyline points="12 9 12 13 15 15"></polyline><line x1="5" y1="3" x2="2" y2="6"></line><line x1="19" y1="3" x2="22" y2="6"></line></svg>';
      case "comment":
        // Chat Bubble - Thảo luận / Bình luận
        return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path><line x1="8" y1="9" x2="16" y2="9"></line><line x1="8" y1="13" x2="13" y2="13"></line></svg>';
      case "status":
        // Status Transition Arrows - Chuyển đổi trạng thái
        return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"></polyline><polyline points="1 20 1 14 7 14"></polyline><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path></svg>';
      case "status-done":
        // Check Circle - Công việc đã hoàn thành
        return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>';
      case "jira":
        // Jira Sync / Integration Link
        return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"></path><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"></path></svg>';
      case "schedule":
        // Calendar Event - Lịch trình / Kế hoạch
        return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect><line x1="16" y1="2" x2="16" y2="6"></line><line x1="8" y1="2" x2="8" y2="6"></line><line x1="3" y1="10" x2="21" y2="10"></line></svg>';
      case "mention":
        // @ Mention - Nhắc tên thành viên
        return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="4"></circle><path d="M16 8v5a3 3 0 0 0 6 0v-1a10 10 0 1 0-3.92 7.94"></path></svg>';
      case "security":
        // Shield - Bảo mật / Giấy phép
        return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path></svg>';
      case "assign":
      default:
        // User with Plus - Phân công công việc mới
        return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path><circle cx="8.5" cy="7" r="4"></circle><line x1="20" y1="8" x2="20" y2="14"></line><line x1="23" y1="11" x2="17" y2="11"></line></svg>';
    }
  }

  function isItemUnread(item){
    if(item.is_read) return false;
    var readIds = getReadIds();
    return readIds.indexOf(item.id) === -1;
  }

  function updateBadge(){
    var unreadCount = 0;
    allNotifications.forEach(function(item){
      if(isItemUnread(item)){
        unreadCount++;
      }
    });

    if(notifBadge){
      if(unreadCount > 0){
        notifBadge.textContent = unreadCount > 99 ? "99+" : unreadCount;
        notifBadge.hidden = false;
      } else {
        notifBadge.hidden = true;
      }
    }

    if(notifPill){
      if(unreadCount > 0){
        notifPill.textContent = unreadCount;
        notifPill.hidden = false;
      } else {
        notifPill.hidden = true;
      }
    }
  }

  function renderList(){
    if(!notifList) return;

    var filtered = allNotifications.filter(function(item){
      var unread = isItemUnread(item);
      if(currentFilter === "unread") return unread;
      if(currentFilter === "mention") return item.category === "mention" || item.type === "assign" || item.is_mine;
      return true;
    });

    if(filtered.length === 0){
      var emptyMsg = "도착한 알림이 없습니다.";
      if(currentFilter === "unread") emptyMsg = "확인하지 않은 새로운 알림이 없습니다.";
      if(currentFilter === "mention") emptyMsg = "배정되거나 멘션된 알림이 없습니다.";

      notifList.innerHTML = '<div class="notif-empty">' +
        '<div class="notif-empty-icon">🔔</div>' +
        '<div>' + emptyMsg + '</div>' +
      '</div>';
      return;
    }

    var html = "";
    filtered.forEach(function(item){
      var isUnread = isItemUnread(item);
      var category = resolveNotificationCategory(item);
      var typeClass = "type-" + category;
      var tagHtml = "";
      if(item.tag){
        var tagTypeClass = item.tag_type ? ("tag-" + item.tag_type) : "";
        if(category === "review") tagTypeClass = "tag-review";
        else if(category === "signup") tagTypeClass = "tag-signup";
        else if(!tagTypeClass) tagTypeClass = "tag-info";
        tagHtml = '<span class="notif-item-tag ' + tagTypeClass + '">' + escapeHtml(item.tag) + '</span>';
      }

      html += '<div class="notif-item ' + (isUnread ? 'unread' : '') + '" data-id="' + escapeHtml(item.id) + '" data-rec-id="' + escapeHtml(item.record_id || '') + '" data-tag="' + escapeHtml(item.tag || '') + '" data-title="' + escapeHtml(item.title || '') + '">' +
        '<div class="notif-item-icon ' + typeClass + '">' + getIconSvg(category, item) + '</div>' +
        '<div class="notif-item-content">' +
          '<div class="notif-item-title">' +
            '<span>' + escapeHtml(item.title) + '</span>' +
            tagHtml +
          '</div>' +
          '<div class="notif-item-desc" title="' + escapeHtml(item.desc || '') + '">' + escapeHtml(item.desc || '') + '</div>' +
          '<div class="notif-item-time">' + formatRelativeTime(item.time) + '</div>' +
        '</div>' +
      '</div>';
    });

    notifList.innerHTML = html;

    // Attach click listeners to notification items
    var itemEls = notifList.querySelectorAll(".notif-item");
    itemEls.forEach(function(el){
      el.addEventListener("click", function(){
        var id = el.getAttribute("data-id");
        var recId = el.getAttribute("data-rec-id");
        var tag = el.getAttribute("data-tag") || "";
        var title = el.getAttribute("data-title") || "";
        markIdAsRead(id);
        closeNotifMenu();

        // 1. 가입 승인 요청 알림 클릭 시 -> 설정 > 사용자 관리 탭으로 즉시 이동 & 승인 대기 필터 적용
        if(tag === "가입요청" || tag === "가입승인" || title.indexOf("가입 승인") !== -1 || title.indexOf("계정 발급") !== -1){
          if(typeof showTab === "function"){
            showTab("settings");
          }
          if(typeof switchSettingsTab === "function"){
            switchSettingsTab("users");
          }
          // 승인 대기 필터 자동 선택 & 새로고침
          setTimeout(function(){
            var filterStatus = document.getElementById("adminUserFilterStatus");
            if(filterStatus){
              filterStatus.value = "pending";
              if(typeof renderAdminUsersTable === "function"){
                renderAdminUsersTable();
              }
            }
            if(typeof loadAdminUsers === "function"){
              loadAdminUsers();
            }
          }, 100);
          return;
        }

        // 2. 업무 카드 알림 클릭 시 -> 대시보드 또는 캔버스 모달 열기
        if(recId){
          if(typeof window.showIssueInCanvas === "function"){
            window.showIssueInCanvas(recId);
          } else if(typeof showTab === "function"){
            showTab("dash");
          }
          return;
        }

        // 3. 기본 일반 알림 -> 대시보드로 이동
        if(typeof showTab === "function"){
          showTab("dash");
        }
      });
    });
  }

  function fetchNotifications(){
    if(typeof apiGet !== "function") return;
    apiGet("/api/notifications")
      .then(function(res){
        if(res && res.ok && Array.isArray(res.notifications)){
          allNotifications = res.notifications;
          updateBadge();
          renderList();

          // Check for new unread notifications to alert
          var newUnreadItems = [];
          allNotifications.forEach(function(item){
            if(isItemUnread(item) && !notifiedIds[item.id]){
              newUnreadItems.push(item);
              notifiedIds[item.id] = true;
            }
          });

          if(!isFirstFetch && newUnreadItems.length > 0){
            if(newUnreadItems.length === 1){
              triggerDesktopNotification(newUnreadItems[0]);
            } else {
              triggerDesktopNotification({
                title: "ARGOS WORKS",
                desc: newUnreadItems.length + "개의 새로운 중요 업무 알림이 도착했습니다.",
                tag: "신규알림"
              });
            }
            playNotifChime();
          }

          isFirstFetch = false;
        }
      })
      .catch(function(err){
        console.warn("Failed to fetch notifications:", err);
      });
  }

  function openNotifMenu(){
    if(!notifMenu) return;
    var accountMenu = document.getElementById("topbarAccountMenu");
    var avatarBtn = document.getElementById("topbarAvatarBtn");
    if(accountMenu && !accountMenu.hidden){
      accountMenu.hidden = true;
      if(avatarBtn) avatarBtn.setAttribute("aria-expanded", "false");
    }

    notifMenu.hidden = false;
    if(notifBtn) notifBtn.setAttribute("aria-expanded", "true");
    updatePushBanner();
    fetchNotifications();
  }

  function closeNotifMenu(){
    if(!notifMenu) return;
    notifMenu.hidden = true;
    if(notifBtn) notifBtn.setAttribute("aria-expanded", "false");
  }

  function toggleNotifMenu(e){
    if(e) e.stopPropagation();
    if(!notifMenu) return;
    if(notifMenu.hidden){
      openNotifMenu();
    } else {
      closeNotifMenu();
    }
  }

  function init(){
    notifBtn = document.getElementById("topbarNotifBtn");
    notifMenu = document.getElementById("topbarNotifMenu");
    notifList = document.getElementById("notifMenuList");
    notifBadge = document.getElementById("topbarNotifBadge");
    notifPill = document.getElementById("notifUnreadCountBadge");
    markAllBtn = document.getElementById("notifMarkAllReadBtn");
    soundBtn = document.getElementById("notifSoundToggleBtn");
    pushBanner = document.getElementById("notifPushBanner");
    enablePushBtn = document.getElementById("notifEnablePushBtn");
    testPushBtn = document.getElementById("notifTestPushBtn");

    if(!notifBtn || !notifMenu) return;

    notifBtn.addEventListener("click", toggleNotifMenu);

    if(markAllBtn){
      markAllBtn.addEventListener("click", function(e){
        e.stopPropagation();
        markAllAsRead();
      });
    }

    if(soundBtn){
      updateSoundBtn();
      soundBtn.addEventListener("click", function(e){
        e.stopPropagation();
        var nextState = !isSoundEnabled();
        setSoundEnabled(nextState);
        if(nextState){
          playNotifChime();
          if(typeof showToast === "function") showToast("알림음이 켜졌습니다.");
        } else {
          if(typeof showToast === "function") showToast("알림음이 음소거되었습니다.");
        }
      });
    }

    if(enablePushBtn){
      enablePushBtn.addEventListener("click", function(e){
        e.stopPropagation();
        requestPushPermission();
      });
    }

    if(testPushBtn){
      testPushBtn.addEventListener("click", function(e){
        e.stopPropagation();
        playNotifChime();
        if(!("Notification" in window)){
          if(typeof showToast === "function") showToast("현재 브라우저는 알림을 지원하지 않습니다.");
          return;
        }
        if(Notification.permission === "granted"){
          triggerDesktopNotification({
            title: "🔔 ARGOS WORKS 알림 테스트",
            desc: "데스크톱 실시간 알림 및 사운드가 정상 작동 중입니다.",
            tag: "테스트"
          });
          if(typeof showToast === "function") showToast("테스트 알림을 발송했습니다.");
        } else if(Notification.permission === "default"){
          requestPushPermission();
        } else {
          if(typeof showToast === "function") showToast("⚠️ 브라우저 주소창에서 알림 권한을 허용해주세요.");
        }
      });
    }

    updatePushBanner();

    // Tabs filter
    var tabsWrap = notifMenu.querySelector(".notif-menu-tabs");
    if(tabsWrap){
      tabBtns = tabsWrap.querySelectorAll(".notif-tab");
      tabBtns.forEach(function(tb){
        tb.addEventListener("click", function(e){
          e.stopPropagation();
          tabBtns.forEach(function(b){ b.classList.remove("active"); });
          tb.classList.add("active");
          currentFilter = tb.getAttribute("data-filter") || "all";
          renderList();
        });
      });
    }

    // Close on outside click
    document.addEventListener("click", function(e){
      if(!notifMenu.hidden && !notifMenu.contains(e.target) && !notifBtn.contains(e.target)){
        closeNotifMenu();
      }
    });

    // Close on Escape key
    document.addEventListener("keydown", function(e){
      if(e.key === "Escape" && !notifMenu.hidden){
        closeNotifMenu();
        notifBtn.focus();
      }
    });

    // Close notif menu if account avatar button is clicked
    var avatarBtn = document.getElementById("topbarAvatarBtn");
    if(avatarBtn){
      avatarBtn.addEventListener("click", function(){
        closeNotifMenu();
      });
    }

    // Initial fetch
    fetchNotifications();

    // Realtime SSE Notification Stream (Tức thì thay vì chờ 45 giây)
    function connectNotificationSSE(){
      var curUser = (typeof getCurrentUser === "function" ? getCurrentUser() : null) || window.loggedInUser;
      if(!curUser) return;

      var url = "/api/notifications/stream";
      var evtSource = new EventSource(url);

      evtSource.addEventListener("new_notification", function(e){
        try {
          var data = JSON.parse(e.data);
          var curUser = typeof getCurrentUser === "function" ? getCurrentUser() : null;
          var curEmail = (curUser && curUser.email) ? curUser.email.toLowerCase() : "";
          var curName = (curUser && curUser.name) ? curUser.name.trim() : "";

          // Nếu thông báo gửi cho chính mình hoặc gửi chung
          if(!data.recipient_email || data.recipient_email === curEmail || data.recipient_name === curName){
            fetchNotifications(); // Cập nhật lại chuông thông báo ngay lập tức
            if(typeof showToast === "function" && data.title){
              showToast("🔔 " + data.title);
            }
            // Tức thì làm mới tab Lịch nếu thông báo liên quan đến phê duyệt, tạo hoặc đổi lịch
            var nTag = (data.tag || "").toLowerCase();
            var nType = (data.notif_type || data.type || "").toLowerCase();
            var nTitle = (data.title || "").toLowerCase();
            if(nTag.indexOf("결재") !== -1 || nTag.indexOf("일정") !== -1 || nTag.indexOf("휴가") !== -1 ||
               nType.indexOf("schedule") !== -1 || nTitle.indexOf("일정") !== -1 || nTitle.indexOf("휴가") !== -1){
              if(typeof window.loadSchedule === "function"){
                window.loadSchedule(true);
              }
            }
          }
        } catch(err){}
      });

      evtSource.addEventListener("schedule_changed", function(e){
        try {
          if(typeof window.loadSchedule === "function"){
            window.loadSchedule(true);
          }
        } catch(err){}
      });

      evtSource.onerror = function(){
        evtSource.close();
        // Tự động kết nối lại sau 10 giây nếu mất mạng
        setTimeout(connectNotificationSSE, 10000);
      };
    }

    connectNotificationSSE();

    // Fallback polling dài hơn (120s) dự phòng mạng ngắt SSE
    setInterval(fetchNotifications, 120000);
  }

  if(document.readyState === "loading"){
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  window.reloadNotifications = fetchNotifications;
})();
