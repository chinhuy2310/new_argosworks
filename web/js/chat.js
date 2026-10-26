/**
 * chat.js — JARVIS AI 채팅 모듈
 * SSE 스트리밍, ReAct 에이전트 도구 실행, 세션 관리, 액션 제안 카드
 */

var chatState = {
    currentSessionId: null,
    isSubmitting: false,
    sessions: [],
    hasMoreHistory: false,
    oldestLoadedMsgId: null,
    sidebarOpen: true
};

function detectLanguage(text) {
    if(!text) return (typeof getLang === "function" ? getLang() : "ko");
    // 1. Nếu người dùng gõ Tiếng Việt hoặc yêu cầu Tiếng Việt
    if(/(?:trả lời\s+(?:bằng\s+)?tiếng việt|nói\s+tiếng việt|giải thích\s+(?:bằng\s+)?tiếng việt|dịch\s+(?:sang\s+)?tiếng việt|bằng\s+tiếng việt|tiếng việt\s+đi|베트남어로|[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ])/i.test(text)) {
        return "vi";
    }
    // 2. Nếu người dùng gõ Tiếng Anh hoặc yêu cầu Tiếng Anh
    if(/(?:reply\s+in\s+english|answer\s+in\s+english|explain\s+in\s+english|in\s+english\s+please|speak\s+in\s+english|영어로)/i.test(text)) {
        return "en";
    }
    // 3. Nếu người dùng gõ ký tự Hangul tiếng Hàn
    if(/[\u3131-\u314e\u314f-\u3163\uac00-\ud7a3]/.test(text)) {
        return "ko";
    }
    // 4. Mặc định theo ngôn ngữ giao diện mà người dùng đang chọn trên thanh Topbar
    if(typeof getLang === "function") {
        return getLang();
    }
    return "ko";
}

function initChat() {
    var btnNew = document.getElementById("btnNewChat");
    if(btnNew) {
        btnNew.onclick = function(e) {
            e.preventDefault();
            createNewChatSession();
        };
    }

    var btnMainNew = document.getElementById("btnMainNewChat");
    if(btnMainNew) {
        btnMainNew.onclick = function(e) {
            e.preventDefault();
            createNewChatSession();
        };
    }

    var btnCollapse = document.getElementById("btnCollapseSidebar");
    if(btnCollapse) {
        btnCollapse.onclick = function(e) {
            e.preventDefault();
            toggleChatSidebar();
        };
    }

    var btnExpand = document.getElementById("btnExpandSidebar");
    if(btnExpand) {
        btnExpand.onclick = function(e) {
            e.preventDefault();
            toggleChatSidebar();
        };
    }

    var backdrop = document.getElementById("chatSidebarBackdrop");
    if(backdrop) {
        backdrop.onclick = function(e) {
            e.preventDefault();
            toggleChatSidebar(true);
        };
    }

    // 사이드바 접힘 상태 복원 (모바일 기본: 접힘)
    try {
        var savedState = localStorage.getItem("jarvis_chat_sidebar_collapsed");
        if(savedState === "1" || (savedState === null && window.innerWidth <= 768)) {
            var sidebar = document.getElementById("chatSidebar");
            if(sidebar) sidebar.classList.add("collapsed");
        }
    } catch(e){}
    
    var form = document.getElementById("chatForm");
    if(form) {
        form.onsubmit = handleChatSubmit;
    }

    var input = document.getElementById("chatInput");
    if(input) {
        input.onkeydown = function(e) {
            if(e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleChatSubmit(e);
            }
        };
    }
    
    var msgs = document.getElementById("chatMessages");
    if(msgs) {
        msgs.onscroll = function() {
            if (msgs.scrollTop === 0 && chatState.hasMoreHistory && !chatState.isSubmitting) {
                loadMoreChatHistory();
            }
        };
    }

    if(typeof getCurrentUser === 'function' && !getCurrentUser()) {
        return;
    }
    loadChatSessions();
    initChatModelSelector();
}

function loadChatSessions() {
    apiGet("/api/chat/sessions").then(function(res) {
        if(res && res.ok) {
            chatState.sessions = res.sessions || [];
            renderSessionsList(chatState.sessions);
            if(chatState.sessions.length > 0 && !chatState.currentSessionId) {
                switchChatSession(chatState.sessions[0].id);
            }
        }
    }).catch(function(err) {
        console.error("loadChatSessions 오류:", err);
    });
}

function renderSessionsList(sessions) {
    var container = document.getElementById("chatSessionsList");
    if(!container) return;
    
    container.innerHTML = "";
    if (!sessions || sessions.length === 0) {
        container.innerHTML = '<div class="chat-session-empty">대화 내역이 없습니다.<br><small style="opacity:0.7;">+ 버튼을 눌러 새 대화를 시작하세요</small></div>';
        return;
    }
    
    sessions.forEach(function(sess) {
        var el = document.createElement("div");
        el.className = "chat-session-item" + (sess.id === chatState.currentSessionId ? " active" : "");
        el.onclick = function() { switchChatSession(sess.id); };
        
        var icon = document.createElement("span");
        icon.className = "chat-session-icon";
        icon.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>';
        
        var title = document.createElement("span");
        title.className = "chat-session-title";
        title.textContent = sess.title || "새로운 대화";
        
        var delBtn = document.createElement("button");
        delBtn.type = "button";
        delBtn.className = "chat-session-del";
        delBtn.innerHTML = "&times;";
        delBtn.title = "삭제";
        delBtn.onclick = function(e) {
            e.stopPropagation();
            deleteChatSession(sess.id);
        };
        
        el.appendChild(icon);
        el.appendChild(title);
        el.appendChild(delBtn);
        container.appendChild(el);
    });
}

function switchChatSession(sessionId) {
    if(chatState.isSubmitting) return;
    chatState.currentSessionId = sessionId;
    chatState.oldestLoadedMsgId = null;
    chatState.hasMoreHistory = false;
    renderSessionsList(chatState.sessions);

    var titleEl = document.getElementById("chatActiveTitle");
    if(titleEl) {
        var sess = chatState.sessions.find(function(s) { return s.id === sessionId; });
        titleEl.textContent = sess && sess.title ? "· " + sess.title : "";
    }
    
    var msgs = document.getElementById("chatMessages");
    if(msgs) msgs.innerHTML = "";
    
    // 모바일 환경에서 세션 선택 시 사이드바 자동 닫기
    if(window.innerWidth <= 768) {
        toggleChatSidebar(true);
    }

    loadChatHistory(sessionId);
}

function createNewChatSession() {
    if(chatState.isSubmitting) return;
    apiPostJson("/api/chat/sessions", { title: "새로운 대화" }).then(function(res) {
        if(res && res.ok && res.session) {
            chatState.sessions.unshift(res.session);
            switchChatSession(res.session.id);
            if(window.innerWidth <= 768) {
                toggleChatSidebar(true);
            }
            var input = document.getElementById("chatInput");
            if(input) input.focus();
        }
    }).catch(function(err) {
        console.error("createNewChatSession 오류:", err);
        showToast("새 대화 생성에 실패했습니다.");
    });
}

function deleteChatSession(sessionId) {
    if(!confirm("이 대화를 삭제하시겠습니까?")) return;
    apiPostJson("/api/chat/sessions/delete", { sessionId: sessionId }).then(function(res) {
        if(res && res.ok) {
            chatState.sessions = chatState.sessions.filter(function(s) { return s.id !== sessionId; });
            if(chatState.currentSessionId === sessionId) {
                chatState.currentSessionId = null;
                var msgs = document.getElementById("chatMessages");
                if(msgs) msgs.innerHTML = "";
                if(chatState.sessions.length > 0) {
                    switchChatSession(chatState.sessions[0].id);
                } else {
                    renderSessionsList(chatState.sessions);
                    if(msgs) {
                        var welcomeText = (typeof t === "function") ? t("chat.welcome") : "무엇이든 물어보세요. 업무 카드 검색, 일정 확인, 업무 관리를 도와드립니다.";
                        msgs.innerHTML = '<div class="chat-welcome"><p data-i18n="chat.welcome">' + welcomeText + '</p></div>';
                    }
                }
            } else {
                renderSessionsList(chatState.sessions);
            }
        } else {
            showToast((res && res.error) || "삭제 실패");
        }
    }).catch(function(err) {
        console.error("deleteChatSession 오류:", err);
        showToast("삭제 중 오류가 발생했습니다.");
    });
}

function loadChatHistory(sessionId) {
    apiGet("/api/chat/history?sessionId=" + encodeURIComponent(sessionId) + "&limit=20").then(function(res) {
        if(res && res.ok) {
            var msgs = document.getElementById("chatMessages");
            if(!msgs) return;
            msgs.innerHTML = "";
            chatState.hasMoreHistory = res.hasMore;
            
            if(res.messages && res.messages.length > 0) {
                // res.messages는 서버에서 시간순 [오래된 것, ..., 최신 것]으로 정렬되어 옴
                chatState.oldestLoadedMsgId = res.messages[0].id;
                res.messages.forEach(function(msg) {
                    appendMessageToDOM(msg.role, msg.content, msg.metadata, msg.id, sessionId);
                });
                scrollChatToBottom();
            } else {
                var welcomeText = (typeof t === "function") ? t("chat.welcome") : "무엇이든 물어보세요. 업무 카드 검색, 일정 확인, 업무 관리를 도와드립니다.";
                msgs.innerHTML = '<div class="chat-welcome"><p data-i18n="chat.welcome">' + welcomeText + '</p></div>';
            }
        }
    }).catch(function(err) {
        console.error("loadChatHistory 오류:", err);
    });
}

function loadMoreChatHistory() {
    if(!chatState.currentSessionId || !chatState.oldestLoadedMsgId) return;
    var msgs = document.getElementById("chatMessages");
    var oldScrollHeight = msgs.scrollHeight;
    
    apiGet("/api/chat/history?sessionId=" + encodeURIComponent(chatState.currentSessionId) + "&limit=20&beforeId=" + chatState.oldestLoadedMsgId).then(function(res) {
        if(res && res.ok && res.messages && res.messages.length > 0) {
            chatState.hasMoreHistory = res.hasMore;
            chatState.oldestLoadedMsgId = res.messages[0].id;
            
            var frag = document.createDocumentFragment();
            res.messages.forEach(function(msg) {
                var el = createMessageElement(msg.role, msg.content, msg.metadata, msg.id, chatState.currentSessionId);
                frag.appendChild(el);
            });
            msgs.insertBefore(frag, msgs.firstChild);
            msgs.scrollTop = msgs.scrollHeight - oldScrollHeight;
        }
    }).catch(function(err) {
        console.error("loadMoreChatHistory 오류:", err);
    });
}

function createMessageElement(role, text, metadata, msgId, sessionId) {
    var wrapper = document.createElement("div");
    wrapper.className = "chat-msg " + role;
    
    // Avatar
    var avatar = document.createElement("div");
    avatar.className = "chat-avatar " + role;
    if(role === "user") {
        avatar.textContent = "👤";
    } else {
        avatar.innerHTML = '<svg width="18" height="18" viewBox="0 0 200 200" fill="none"><path d="M100 38 L146 144" stroke="#38bdf8" stroke-width="26" stroke-linecap="round"/><path d="M100 38 L54 144" stroke="#0284c7" stroke-width="26" stroke-linecap="round"/><circle cx="100" cy="130" r="14" fill="#38bdf8"/></svg>';
    }
    wrapper.appendChild(avatar);
    
    var content = document.createElement("div");
    content.className = "chat-msg-content";
    content.innerHTML = renderChatMarkdown(text);
    
    if(metadata && metadata.action_proposal) {
        try {
            var card = createActionCard(metadata.action_proposal, msgId, sessionId);
            if(card) content.appendChild(card);
        } catch(e) {
            console.error("createActionCard error:", e);
        }
    }
    
    if(metadata && metadata.quick_actions && metadata.quick_actions.length > 0) {
        var chips = document.createElement("div");
        chips.className = "chat-quick-chips";
        renderQuickChips(metadata.quick_actions, chips);
        content.appendChild(chips);
    }
    
    wrapper.appendChild(content);
    return wrapper;
}

function appendMessageToDOM(role, text, metadata, msgId, sessionId) {
    var msgs = document.getElementById("chatMessages");
    if(!msgs) return;
    
    var welcome = msgs.querySelector(".chat-welcome");
    if(welcome) welcome.remove();
    
    var el = createMessageElement(role, text, metadata, msgId, sessionId);
    msgs.appendChild(el);
    return el;
}

function handleChatSubmit(e) {
    if(e && e.preventDefault) e.preventDefault();
    if(typeof getCurrentUser === 'function' && !getCurrentUser()) {
        showToast("로그인 후 이용할 수 있는 기능입니다. 먼저 로그인해 주세요.");
        setTimeout(function(){
            window.location.href = "/login";
        }, 800);
        return;
    }

    if(chatState.isSubmitting) return;
    
    var input = document.getElementById("chatInput");
    if(!input) return;
    var text = input.value.trim();
    if(!text) return;
    
    input.value = "";
    input.style.height = "auto";
    
    // Automatically collapse chat history sidebar if it is currently open
    var sidebar = document.getElementById("chatSidebar");
    if(sidebar && !sidebar.classList.contains("collapsed")) {
        toggleChatSidebar(true);
    }
    
    chatState.isSubmitting = true;
    appendMessageToDOM("user", text);
    scrollChatToBottom();
    
    var msgs = document.getElementById("chatMessages");
    var assistantBubble = document.createElement("div");
    assistantBubble.className = "chat-msg assistant streaming";
    
    var avatar = document.createElement("div");
    avatar.className = "chat-avatar assistant";
    avatar.innerHTML = '<svg width="18" height="18" viewBox="0 0 200 200" fill="none"><path d="M100 38 L146 144" stroke="#38bdf8" stroke-width="26" stroke-linecap="round"/><path d="M100 38 L54 144" stroke="#0284c7" stroke-width="26" stroke-linecap="round"/><circle cx="100" cy="130" r="14" fill="#38bdf8"/></svg>';
    assistantBubble.appendChild(avatar);
    
    var assistantContent = document.createElement("div");
    assistantContent.className = "chat-msg-content";
    
    var dots = document.createElement("div");
    dots.className = "typing-dots";
    dots.innerHTML = "<span></span><span></span><span></span>";
    
    assistantContent.appendChild(dots);
    assistantBubble.appendChild(assistantContent);
    msgs.appendChild(assistantBubble);
    scrollChatToBottom();
    
    var fullText = "";
    var statusEl = null;
    var detectedLang = detectLanguage(text);
    var body = {
        message: text,
        sessionId: chatState.currentSessionId,
        lang: detectedLang
    };
    
    // Attach custom model configuration if user selected a custom BYOK model
    var customAi = getActivePersonalModelConfig();
    if(customAi) {
        body.customAi = customAi;
    }
    
    var headers = typeof getAuthHeaders === 'function' ? getAuthHeaders() : {};
    headers["Content-Type"] = "application/json";
    
    fetch("/api/chat/stream", {
        method: "POST",
        headers: headers,
        body: JSON.stringify(body)
    }).then(function(res) {
        if(!res.ok) throw new Error("Network response was not ok");
        var reader = res.body.getReader();
        var decoder = new TextDecoder("utf-8");
        var buffer = "";
        var isStreamFinished = false;
        
        function read() {
            reader.read().then(function(result) {
                if(result.done) {
                    if(!isStreamFinished) {
                        finishStreaming();
                    }
                    return;
                }
                buffer += decoder.decode(result.value, {stream: true});
                var lines = buffer.split("\n");
                buffer = lines.pop();
                
                for(var i=0; i<lines.length; i++) {
                    var line = lines[i].trim();
                    if(line.startsWith("data: ")) {
                        var dataStr = line.substring(6);
                        if(dataStr === "[DONE]") {
                            if(!isStreamFinished) {
                                finishStreaming();
                            }
                            return;
                        }
                        try {
                            var data = JSON.parse(dataStr);
                            if(data.error) {
                                if(statusEl) { statusEl.remove(); statusEl = null; }
                                fullText += "\n**오류:** " + data.error;
                                updateBubble();
                            } else if(data.status) {
                                if(!statusEl) {
                                    statusEl = document.createElement("div");
                                    statusEl.className = "chat-agent-status";
                                    assistantContent.insertBefore(statusEl, dots);
                                }
                                statusEl.innerHTML = '<span class="status-pulse">⚡</span> <span>' + escapeHtml(data.status) + '</span>';
                                scrollChatToBottom();
                            } else if(data.text) {
                                if(statusEl) {
                                    statusEl.remove();
                                    statusEl = null;
                                }
                                fullText += data.text;
                                updateBubble();
                            } else if(data.done) {
                                if(statusEl) {
                                    statusEl.remove();
                                    statusEl = null;
                                }
                                if(data.sessionId) {
                                    chatState.currentSessionId = data.sessionId;
                                }
                                loadChatSessions(); // 세션 목록 항상 새로고침
                                finishStreaming(data.metadata, data.messageId, data.sessionId);
                                return;
                            }
                        } catch(err) {
                            console.error("SSE parse error", err, dataStr);
                        }
                    }
                }
                read();
            }).catch(function(err) {
                console.error("Stream read error", err);
                if(statusEl) { statusEl.remove(); statusEl = null; }
                if(!isStreamFinished) {
                    fullText += "\n**통신 오류가 발생했습니다.**";
                    finishStreaming();
                }
            });
        }
        
        function updateBubble() {
            if(dots && dots.parentNode) {
                dots.parentNode.removeChild(dots);
            }
            assistantContent.innerHTML = renderChatMarkdown(fullText) + '<span class="typing-dots inline"><span></span><span></span><span></span></span>';
            scrollChatToBottom();
        }
        
        function finishStreaming(metadata, msgId, sessionId) {
            if(isStreamFinished) return;
            isStreamFinished = true;
            chatState.isSubmitting = false;
            assistantBubble.classList.remove("streaming");
            if(statusEl) {
                statusEl.remove();
                statusEl = null;
            }
            assistantContent.innerHTML = renderChatMarkdown(fullText);
            
            var meta = metadata || parseMetadataFromText(fullText);
            if(meta) {
                if(meta.action_proposal) {
                    try {
                        var card = createActionCard(meta.action_proposal, msgId, sessionId || chatState.currentSessionId);
                        if(card) assistantContent.appendChild(card);
                    } catch(e) {
                        console.error("createActionCard error:", e);
                    }
                }
                if(meta.quick_actions && meta.quick_actions.length > 0) {
                    var chips = document.createElement("div");
                    chips.className = "chat-quick-chips";
                    renderQuickChips(meta.quick_actions, chips);
                    assistantContent.appendChild(chips);
                }
            }
            scrollChatToBottom();
        }
        
        read();
    }).catch(function(err) {
        console.error("Fetch error", err);
        chatState.isSubmitting = false;
        if(dots && dots.parentNode) dots.parentNode.removeChild(dots);
        assistantContent.innerHTML = "**서버와 연결할 수 없습니다. 로그인 상태를 확인해 주세요.**";
        assistantBubble.classList.remove("streaming");
    });
}

function parseMetadataFromText(text) {
    if (!text) return null;
    var result = { action: "none", action_proposal: null, quick_actions: [] };
    var apMatch = text.match(/:::action-proposal\r?\n([\s\S]*?)\r?\n:::/);
    if (apMatch) {
        var rawContent = apMatch[1].trim();
        var proposal = {};
        if (rawContent.startsWith("{") && rawContent.endsWith("}")) {
            try {
                var parsedObj = JSON.parse(rawContent);
                var params = parsedObj.parameters || {};
                proposal = Object.assign({}, params, parsedObj);
            } catch(e){}
        }
        if (Object.keys(proposal).length === 0) {
            var currentKey = null;
            var lines = rawContent.split(/\r?\n/);
            for (var i = 0; i < lines.length; i++) {
                var m = lines[i].match(/^([a-zA-Z_]+)\s*:\s*(.*)$/);
                if (m) {
                    currentKey = m[1].trim();
                    proposal[currentKey] = m[2].trim();
                } else if (currentKey && lines[i].trim()) {
                    proposal[currentKey] += "\n" + lines[i].trim();
                }
            }
        }
        if(!proposal.action_type && (proposal.action || proposal.type)) {
            var act = proposal.action || proposal.type;
            proposal.action_type = act === "create_issue" ? "create_task" : act;
        }
        if(!proposal.summary && proposal.title) {
            proposal.summary = proposal.title;
        }
        result.action_proposal = proposal;
        result.action = "propose_action";
    }
    var qaMatch = text.match(/:::quick-actions\r?\n([\s\S]*?)\r?\n:::/);
    if (qaMatch) {
        var actions = [];
        var qlines = qaMatch[1].trim().split(/\r?\n/);
        for (var j = 0; j < qlines.length; j++) {
            var ql = qlines[j].trim().replace(/^-\s*/, '').trim();
            if (ql) actions.push(ql);
        }
        result.quick_actions = actions.slice(0, 5);
    }
    return (result.action_proposal || result.quick_actions.length > 0) ? result : null;
}

function renderChatMarkdown(text) {
    if(!text) return "";
    
    // :::action-proposal 및 :::quick-actions 블록은 본문에서 제거
    var clean = text.replace(/:::action-proposal[\s\S]*?:::/g, "")
                    .replace(/:::quick-actions[\s\S]*?:::/g, "")
                    .replace(/:::task-proposal[\s\S]*?:::/g, "")
                    .replace(/^[>|\s]*\*?⚡\s*\[도구 실행\].*?\*?\s*$/gm, "")
                    .replace(/^>\s*\*?⚡.*?\*?\s*$/gm, "")
                    .trim();
    
    var html = escapeHtml(clean);
    
    // Report download links: [label](/api/reports/download?file=...) -> download button
    // (내부 보고서 경로만 허용 — 외부 URL은 링크로 만들지 않음)
    html = html.replace(/\[([^\]]+)\]\((\/api\/reports\/download\?[^\s)]+)\)/g, function(_m, label, url){
      return '<a href="' + url + '" class="chat-report-download-btn">' + label + '</a>';
    });
    
    // Bold: **text**
    html = html.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");
    
    // Italic: *text*
    html = html.replace(/\*(.*?)\*/g, "<em>$1</em>");
    
    // Inline code: `code`
    html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
    
    // Blockquote: > text
    html = html.replace(/^&gt;\s*(.*)$/gm, '<blockquote class="chat-status-quote">$1</blockquote>');
    
    // Lists: - item or * item
    html = html.replace(/^[\-\*]\s+(.*)$/gm, "<li>$1</li>");
    html = html.replace(/(<li>.*<\/li>(\n|$)(\s*))+/g, "<ul>$&</ul>");
    
    // Numbered lists: 1. item
    html = html.replace(/^\d+\.\s+(.*)$/gm, "<li>$1</li>");
    
    // Line breaks
    html = html.replace(/\n\n/g, "</p><p>");
    html = html.replace(/\n/g, "<br>");
    html = "<p>" + html + "</p>";
    html = html.replace(/<p><\/p>/g, "");
    
    // Auto-link Issue Keys (e.g. VS-11, TS-5, MS-2, KAN-12, etc.)
    // Hardware/network standards (RS-485, RS-232, RJ-45, CAT-5, etc.) are excluded
    var NON_ISSUE_KEYS = { "RS-485": true, "RS-232": true, "RS-422": true, "RJ-45": true, "RJ-11": true, "CAT-5": true, "CAT-6": true };
    html = html.replace(/\b([A-Za-z]{2,10}-\d+)\b/g, function(match) {
        var key = match.toUpperCase();
        if(NON_ISSUE_KEYS[key]) return match;
        return '<span class="chat-issue-badge" onclick="if(window.onChatIssueClick) window.onChatIssueClick(\'' + key + '\'); else if(window.showIssueInCanvas) window.showIssueInCanvas(\'' + key + '\');" title="Canvas에서 이슈 열기">' + key + ' ↗</span>';
    });

    // Auto-link explicit PIM IDs e.g. [PIM:prod_xxx] or PIM:prod_xxx
    html = html.replace(/\[?PIM:([a-zA-Z0-9_\-]+)\]?/gi, function(match, pid) {
        return '<span class="chat-pim-badge" onclick="onChatPimClick(\'' + pid + '\')" title="제품 정보 보기">📦 ' + pid + ' ↗</span>';
    });
    
    return html;
}

// =========================================================
// Quick View Modal & Cross-Tab Deep Linking
// =========================================================

function closeChatQuickModal() {
    var modal = document.getElementById("chatQuickModal");
    if(modal) modal.hidden = true;
}

function onChatIssueClick(key) {
    if(!key) return;
    var cleanKey = String(key).trim().toUpperCase().replace(/^JIRA-/, "").replace(/^#/, "");
    closeChatQuickModal();
    if(typeof window.showIssueInCanvas === "function") {
        window.showIssueInCanvas(cleanKey);
    } else {
        console.warn("[Chat] showIssueInCanvas is not available");
    }
}
window.onChatIssueClick = onChatIssueClick;

function onChatPimClick(productIdOrModel) {
    var modal = document.getElementById("chatQuickModal");
    var badge = document.getElementById("chatQuickModalBadge");
    var title = document.getElementById("chatQuickModalTitle");
    var body = document.getElementById("chatQuickModalBody");
    var actionBtn = document.getElementById("chatQuickModalActionBtn");
    var closeBtn = document.getElementById("chatQuickModalClose");
    var dismissBtn = document.getElementById("chatQuickModalDismissBtn");

    if(!modal || !body) return;

    badge.className = "chat-quick-modal-badge badge-pim";
    badge.textContent = "PIM 제품";
    title.textContent = "제품 정보 조회 중...";
    body.innerHTML = '<div style="text-align:center;padding:30px 0;color:var(--ink-soft);"><span class="typing-dots"><span></span><span></span><span></span></span><div style="margin-top:10px;">제품 상세 스펙을 불러오는 중...</div></div>';
    
    actionBtn.textContent = "제품정보 탭으로 이동 ↗";
    actionBtn.onclick = function() {
        closeChatQuickModal();
        if(typeof showTab === 'function') {
            showTab("pim");
            var search = document.getElementById("pimSearchInput");
            if(search) {
                search.value = productIdOrModel;
                if(typeof loadProducts === 'function') loadProducts(productIdOrModel);
            }
        }
    };
    closeBtn.onclick = closeChatQuickModal;
    dismissBtn.onclick = closeChatQuickModal;
    modal.onclick = function(e) {
        if(e.target === modal) closeChatQuickModal();
    };

    modal.hidden = false;

    fetch("/api/products", { cache: "no-store" })
        .then(function(r){ return r.json(); })
        .then(function(data){
            var products = data.products || [];
            var prod = products.find(function(p){
                return p.id === productIdOrModel || 
                       (p.model && p.model.toLowerCase() === productIdOrModel.toLowerCase()) ||
                       (p.displayName && p.displayName.indexOf(productIdOrModel) !== -1);
            });

            if(!prod) {
                title.textContent = productIdOrModel;
                body.innerHTML = '<div style="text-align:center;padding:24px 0;color:var(--ink-soft);"><p>해당 제품 정보를 찾을 수 없습니다.</p></div>';
                return;
            }

            title.textContent = (prod.model || "") + (prod.displayName ? " — " + prod.displayName : "");
            var proc = prod.procurement;
            var procHtml = "";
            if(proc && proc.registeredName) {
                procHtml = '<div style="margin-top:12px;"><div class="modal-section-title">🏛️ 나라장터 조달 등록 정보</div>' +
                    '<div class="modal-grid-meta">' +
                        '<div class="modal-meta-item"><span class="modal-meta-label">조달 식별명</span><span class="modal-meta-value">' + escapeHtml(proc.registeredName) + '</span></div>' +
                        '<div class="modal-meta-item"><span class="modal-meta-label">물품식별번호</span><span class="modal-meta-value">' + escapeHtml(proc.identificationNo || "-") + '</span></div>' +
                        '<div class="modal-meta-item"><span class="modal-meta-label">가격</span><span class="modal-meta-value">' + (proc.price != null ? Number(proc.price).toLocaleString() + "원" : "미정") + '</span></div>' +
                        '<div class="modal-meta-item"><span class="modal-meta-label">공급 구성</span><span class="modal-meta-value">' + escapeHtml(proc.configuration || "-") + '</span></div>' +
                    '</div></div>';
            }

            var specsHtml = "";
            if(prod.specs && Object.keys(prod.specs).length > 0) {
                specsHtml = '<div style="margin-top:12px;"><div class="modal-section-title">⚙️ 주요 사양 (Specs)</div>' +
                    '<div class="modal-grid-meta">' +
                    Object.keys(prod.specs).map(function(k){
                        return '<div class="modal-meta-item"><span class="modal-meta-label">' + escapeHtml(k) + '</span><span class="modal-meta-value">' + escapeHtml(prod.specs[k]) + '</span></div>';
                    }).join("") +
                    '</div></div>';
            }

            var attachHtml = "";
            if(prod.attachments && prod.attachments.length > 0) {
                attachHtml = '<div style="margin-top:12px;"><div class="modal-section-title">📎 규격서 / 첨부문서</div>' +
                    '<div class="modal-attach-chips">' +
                    prod.attachments.map(function(att){
                        var name = typeof att === 'string' ? att : (att.name || "");
                        return '<span class="modal-attach-chip">📄 ' + escapeHtml(name) + '</span>';
                    }).join("") +
                    '</div></div>';
            }

            body.innerHTML = 
                '<div class="modal-grid-meta">' +
                    '<div class="modal-meta-item"><span class="modal-meta-label">모델명</span><span class="modal-meta-value">' + escapeHtml(prod.model || "") + '</span></div>' +
                    '<div class="modal-meta-item"><span class="modal-meta-label">판매 상태</span><span class="modal-meta-value">' + escapeHtml(prod.lifecycle || "판매 중") + '</span></div>' +
                    '<div class="modal-meta-item"><span class="modal-meta-label">카테고리</span><span class="modal-meta-value">' + escapeHtml(prod.category || "일반") + '</span></div>' +
                    '<div class="modal-meta-item"><span class="modal-meta-label">제품군</span><span class="modal-meta-value">' + escapeHtml(prod.family || "-") + '</span></div>' +
                '</div>' +
                (prod.summary ? '<div><div class="modal-section-title">📄 제품 요약</div><div class="modal-desc-box">' + escapeHtml(prod.summary) + '</div></div>' : '') +
                specsHtml +
                procHtml +
                attachHtml;
        })
        .catch(function(err){
            body.innerHTML = '<div style="color:var(--red);padding:20px;text-align:center;">제품 정보를 불러오는 중 오류가 발생했습니다.</div>';
        });
}

// Global Escape Key to close Quick Modal
document.addEventListener("keydown", function(e) {
    if(e.key === "Escape") {
        closeChatQuickModal();
    }
});

function createActionCard(proposal, msgId, sessionId) {
    var sid = sessionId || chatState.currentSessionId || "";
    var proposalKey = sid + "_" + (msgId || "") + "_" + (proposal.action_type || "") + "_" + (proposal.summary || "");
    
    var localStatus = null;
    try {
        localStatus = localStorage.getItem("jarvis_proposal_" + proposalKey);
    } catch(e){}
    
    // proposal_status: 'pending' | 'executed' | 'cancelled'
    // Lưu ý: không nhầm với proposal.status (trạng thái task: 대기, 진행중, 완료)
    var proposalState = proposal.proposal_status || localStatus;
    if(!proposalState && (proposal.status === "cancelled" || proposal.status === "executed")) {
        proposalState = proposal.status;
    }
    
    // Nếu đề xuất đã bị hủy (từ server hoặc từ localStorage) -> hiển thị ngay dạng nhãn hủy
    if(proposalState === "cancelled") {
        var cancelledMsg = document.createElement("div");
        cancelledMsg.className = "chat-action-cancelled-pill";
        cancelledMsg.innerHTML = '<span class="cancelled-icon">✕</span> <span>실행 취소됨 (' + escapeHtml(getActionTitle(proposal.action_type)) + ')</span>';
        return cancelledMsg;
    }

    var card = document.createElement("div");
    var actionType = proposal.action_type || "default";
    card.className = "chat-action-card type-" + actionType.replace(/_/g, "-");
    
    var header = document.createElement("div");
    header.className = "chat-action-header";
    header.innerHTML = '<span class="chat-action-tag">⚡ 실행 제안</span> <strong>' + escapeHtml(getActionTitle(proposal.action_type)) + '</strong>';
    
    var body = document.createElement("div");
    body.className = "chat-action-body";
    var ul = document.createElement("ul");
    
    if(actionType === "add_comment") {
        // Jira 댓글은 작업 제목(summary)이 없으며, 오직 대상 이슈와 댓글 본문으로만 구성됨
        var commentBody = proposal.comment || proposal.description || proposal.summary || "";
        if(proposal.summary && proposal.description && proposal.summary !== proposal.description) {
            commentBody = proposal.summary + "\n\n" + proposal.description;
        }
        proposal.comment = commentBody;

        var liIssue = document.createElement("li");
        liIssue.innerHTML = '<span class="action-field-label">대상 이슈:</span> <span class="action-field-val"><strong style="cursor:pointer;color:var(--vs-cyan, #38bdf8);" onclick="onChatIssueClick(\'' + escapeHtml(proposal.issue_key || "") + '\')" title="Canvas에서 이슈 열기">' + escapeHtml(proposal.issue_key || "") + ' ↗</strong></span>';
        ul.appendChild(liIssue);

        var liComment = document.createElement("li");
        liComment.innerHTML = '<span class="action-field-label">댓글 내용:</span> <div class="action-field-val action-comment-preview" style="white-space:pre-wrap;margin-top:6px;line-height:1.5;">' + escapeHtml(commentBody) + '</div>';
        ul.appendChild(liComment);
    } else {
        var labels = {
            "issue_key": "대상 이슈",
            "summary": "작업 제목",
            "description": "상세 내용",
            "assignee": "담당자",
            "target_status": "변경 상태",
            "status": "상태",
            "comment": "댓글 내용",
            "start_date": "시작일",
            "due_date": "마감일",
            "priority": "우선순위"
        };
        
        // Desired display order
        var order = ["issue_key", "summary", "description", "assignee", "status", "target_status", "start_date", "due_date", "priority", "comment"];
        var renderedKeys = {};

        function renderField(k) {
            if(k === "action_type" || k === "proposal_status" || !proposal[k]) return;
            renderedKeys[k] = true;
            var li = document.createElement("li");
            var label = labels[k] || k;
            var valHtml = escapeHtml(proposal[k]);
            if(k === "issue_key" && proposal[k]) {
                valHtml = '<strong style="cursor:pointer;color:var(--vs-cyan, #38bdf8);" onclick="onChatIssueClick(\'' + escapeHtml(proposal[k]) + '\')" title="Canvas에서 이슈 열기">' + valHtml + ' ↗</strong>';
            }
            li.innerHTML = '<span class="action-field-label">' + escapeHtml(label) + ':</span> <span class="action-field-val">' + valHtml + '</span>';
            ul.appendChild(li);
        }

        order.forEach(function(k) {
            if(proposal[k]) renderField(k);
        });

        for(var k in proposal) {
            if(!renderedKeys[k] && proposal[k]) {
                renderField(k);
            }
        }
    }
    body.appendChild(ul);
    
    var footer = document.createElement("div");
    footer.className = "chat-action-footer";

    var cancelBtn = document.createElement("button");
    cancelBtn.type = "button";
    cancelBtn.className = "chat-action-cancel-btn";
    cancelBtn.textContent = "✕ 취소";
    cancelBtn.title = "이 제안을 취소합니다";

    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "chat-action-btn";
    btn.textContent = "✓ 확인 및 실행";

    if(proposalState === "executed") {
        btn.textContent = "✓ 실행 완료";
        btn.disabled = true;
        btn.classList.add("success");
        cancelBtn.style.display = "none";
    } else {
        btn.onclick = function() {
            cancelBtn.disabled = true;
            cancelBtn.style.display = "none";
            executeAction(proposal, btn, msgId, sid, proposalKey);
        };

        cancelBtn.onclick = function() {
            // 1. Lưu ngay vào localStorage để khi F5 tải lại không bao giờ bị hiện lại
            try {
                localStorage.setItem("jarvis_proposal_" + proposalKey, "cancelled");
            } catch(e){}

            // 2. Thay thế DOM bằng thẻ [✕ 실행 취소됨]
            var cancelledMsg = document.createElement("div");
            cancelledMsg.className = "chat-action-cancelled-pill";
            cancelledMsg.innerHTML = '<span class="cancelled-icon">✕</span> <span>실행 취소됨 (' + escapeHtml(getActionTitle(proposal.action_type)) + ')</span>';
            
            if(card.parentNode) {
                card.parentNode.replaceChild(cancelledMsg, card);
            } else {
                card.remove();
            }

            // 3. Gửi API lưu vĩnh viễn trạng thái cancelled lên session JSONL trên server
            apiPostJson("/api/chat/cancel-action", {
                sessionId: sid,
                messageId: msgId,
                summary: proposal.summary,
                action_type: proposal.action_type
            }).catch(function(err) {
                console.error("취소 상태 동기화 오류:", err);
            });
        };
    }

    footer.appendChild(cancelBtn);
    footer.appendChild(btn);
    
    card.appendChild(header);
    card.appendChild(body);
    card.appendChild(footer);
    return card;
}

function getActionTitle(type) {
    switch(type) {
        case "create_task": return "새 작업(Task) 생성";
        case "create_subtask": return "하위 작업(Subtask) 생성";
        case "add_comment": return "진행 댓글 / 메모 추가";
        case "update_status": return "작업 상태 변경";
        case "schedule_issue": return "캘린더 일정 등록 / 변경";
        default: return "작업 실행 제안";
    }
}

function executeAction(proposal, btn, msgId, sessionId, proposalKey) {
    btn.disabled = true;
    btn.textContent = "⏳ 실행 중...";
    var sid = sessionId || chatState.currentSessionId || "";
    var payload = Object.assign({}, proposal, {
        message_id: msgId,
        session_id: sid
    });
    apiPostJson("/api/chat/execute-action", payload).then(function(res) {
        if(res && res.ok) {
            btn.textContent = "✓ 실행 완료";
            btn.classList.add("success");
            showToast("성공적으로 실행되었습니다.");
            if(proposalKey) {
                try {
                    localStorage.setItem("jarvis_proposal_" + proposalKey, "executed");
                } catch(e){}
            }
            if(typeof loadRecords === 'function') loadRecords();
            if(typeof loadSchedule === 'function') loadSchedule();
        } else {
            btn.disabled = false;
            btn.textContent = "다시 시도";
            showToast((res && res.error) || "실행에 실패했습니다.");
        }
    }).catch(function(err) {
        console.error("executeAction 오류:", err);
        btn.disabled = false;
        btn.textContent = "다시 시도";
        showToast("오류가 발생했습니다.");
    });
}

function renderQuickChips(actions, container) {
    container.innerHTML = "";
    actions.forEach(function(act) {
        var chip = document.createElement("button");
        chip.type = "button";
        chip.className = "chat-quick-chip";
        chip.innerHTML = '<span class="chip-sparkle">✨</span> ' + escapeHtml(act);
        chip.onclick = function() {
            var input = document.getElementById("chatInput");
            if(input) {
                input.value = act;
                handleChatSubmit(new Event('submit'));
            }
        };
        container.appendChild(chip);
    });
}

function scrollChatToBottom() {
    var msgs = document.getElementById("chatMessages");
    if(msgs) {
        msgs.scrollTop = msgs.scrollHeight;
    }
}

function escapeHtml(s) {
    return String(s || "").replace(/[&<>"']/g, function(c) {
        return ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c];
    });
}

function toggleChatSidebar(forceState) {
    var sidebar = document.getElementById("chatSidebar");
    if(!sidebar) return;
    var isCollapsed;
    if(typeof forceState === "boolean") {
        isCollapsed = forceState;
        if(isCollapsed) sidebar.classList.add("collapsed");
        else sidebar.classList.remove("collapsed");
    } else {
        isCollapsed = sidebar.classList.toggle("collapsed");
    }
    var backdrop = document.getElementById("chatSidebarBackdrop");
    if(backdrop) {
        backdrop.hidden = isCollapsed || window.innerWidth > 768;
    }
    try {
        localStorage.setItem("jarvis_chat_sidebar_collapsed", isCollapsed ? "1" : "0");
    } catch(e){}
}

/* =========================================================
   BYOK (Bring Your Own Key) & Model Selector Logic
   ========================================================= */

var BYOK_STORAGE_KEY = "argos_user_ai_models";
var BYOK_SELECTED_KEY = "argos_selected_ai_model_id";

function getStoredPersonalModels() {
    try {
        var raw = localStorage.getItem(BYOK_STORAGE_KEY);
        return raw ? JSON.parse(raw) : [];
    } catch(e) {
        return [];
    }
}

function saveStoredPersonalModels(models) {
    try {
        localStorage.setItem(BYOK_STORAGE_KEY, JSON.stringify(models || []));
    } catch(e) {}
}

function getSelectedModelId() {
    try {
        return localStorage.getItem(BYOK_SELECTED_KEY) || "system";
    } catch(e) {
        return "system";
    }
}

function setSelectedModelId(id) {
    try {
        localStorage.setItem(BYOK_SELECTED_KEY, id || "system");
    } catch(e) {}
}

function getActivePersonalModelConfig() {
    var selectedId = getSelectedModelId();
    if (!selectedId || selectedId === "system") {
        return null;
    }
    var models = getStoredPersonalModels();
    for (var i = 0; i < models.length; i++) {
        if (models[i].id === selectedId) {
            return models[i];
        }
    }
    return null;
}

function initChatModelSelector() {
    // 1. Check workspace config to see if Master enabled BYOK
    apiGet("/api/workspace-config").then(function(res) {
        if (res && res.ok && res.ai && res.ai.allow_user_keys) {
            var bar = document.getElementById("chatModelSelectorBar");
            if (bar) bar.hidden = false;
            
            var sysModelName = res.ai.model || "Gemini 3.8 Flash Medium";
            chatState.systemModelName = sysModelName;
            
            renderChatModelDropdown();
            setupChatModelEvents();
        } else {
            var bar = document.getElementById("chatModelSelectorBar");
            if (bar) bar.hidden = true;
        }
    }).catch(function() {
        var bar = document.getElementById("chatModelSelectorBar");
        if (bar) bar.hidden = true;
    });
}

function renderChatModelDropdown() {
    var list = document.getElementById("chatModelDropdownList");
    var currentNameEl = document.getElementById("chatModelCurrentName");
    if (!list) return;

    var selectedId = getSelectedModelId();
    var personalModels = getStoredPersonalModels();
    var sysName = chatState.systemModelName || "Gemini 3.8 Flash Medium";

    list.innerHTML = "";

    // 1. Dòng trên cùng: Model mặc định master đã thêm
    var defText = (typeof t === "function") ? t("chat.model_default") : "기본";
    var sysRow = document.createElement("div");
    sysRow.className = "cmd-row" + (selectedId === "system" ? " active" : "");
    sysRow.innerHTML = 
        '<div class="cmd-row-left">' +
            '<span class="cmd-model-title">' + escapeHtml(sysName) + '</span>' +
            '<span class="cmd-tag">' + escapeHtml(defText) + '</span>' +
        '</div>' +
        '<div class="cmd-row-right">' +
            (selectedId === "system" ? '<span class="cmd-check">✓</span>' : '') +
        '</div>';

    sysRow.onclick = function() {
        setSelectedModelId("system");
        renderChatModelDropdown();
        closeChatModelDropdown();
    };
    list.appendChild(sysRow);

    // 2. Những cái dưới: Model cá nhân có chữ [Sửa] bên cạnh
    var editText = (typeof t === "function") ? t("chat.model_edit") : "수정";
    personalModels.forEach(function(m) {
        var isSelected = (selectedId === m.id);
        var row = document.createElement("div");
        row.className = "cmd-row" + (isSelected ? " active" : "");

        var tagLabel = (m.provider || "AI").toUpperCase();
        row.innerHTML = 
            '<div class="cmd-row-left">' +
                '<span class="cmd-model-title">' + escapeHtml(m.name || m.model) + '</span>' +
                '<span class="cmd-tag">' + escapeHtml(tagLabel) + '</span>' +
            '</div>' +
            '<div class="cmd-row-right">' +
                '<button type="button" class="cmd-edit-btn" data-edit-id="' + escapeHtml(m.id) + '">' + escapeHtml(editText) + '</button>' +
                (isSelected ? '<span class="cmd-check">✓</span>' : '<span style="width:14px;"></span>') +
            '</div>';

        // Click row selects this model
        row.onclick = function(e) {
            if (e.target && e.target.classList.contains("cmd-edit-btn")) {
                return; // Let edit button handle click
            }
            setSelectedModelId(m.id);
            renderChatModelDropdown();
            closeChatModelDropdown();
        };

        // Click [Sửa] opens edit modal
        var editBtn = row.querySelector(".cmd-edit-btn");
        if (editBtn) {
            editBtn.onclick = function(e) {
                e.stopPropagation();
                openEditChatModelModal(m.id);
                closeChatModelDropdown();
            };
        }

        list.appendChild(row);
    });

    // Update active button title
    if (currentNameEl) {
        if (selectedId === "system") {
            currentNameEl.textContent = sysName;
        } else {
            var activeModel = getActivePersonalModelConfig();
            currentNameEl.textContent = activeModel ? (activeModel.name || activeModel.model) : sysName;
        }
    }
}

function setupChatModelEvents() {
    var btn = document.getElementById("btnChatModelSelect");
    var menu = document.getElementById("chatModelDropdownMenu");
    var btnAdd = document.getElementById("btnChatAddModel");

    if (btn && menu) {
        btn.onclick = function(e) {
            e.stopPropagation();
            var isOpen = !menu.hidden;
            if (isOpen) {
                closeChatModelDropdown();
            } else {
                openChatModelDropdown();
            }
        };

        document.addEventListener("click", function(e) {
            if (!menu.hidden && !menu.contains(e.target) && e.target !== btn) {
                closeChatModelDropdown();
            }
        });
    }

    if (btnAdd) {
        btnAdd.onclick = function(e) {
            e.stopPropagation();
            closeChatModelDropdown();
            openAddChatModelModal();
        };
    }

    setupChatModelModal();
}

function openChatModelDropdown() {
    var menu = document.getElementById("chatModelDropdownMenu");
    var btn = document.getElementById("btnChatModelSelect");
    if (menu) menu.hidden = false;
    if (btn) btn.classList.add("open");
}

function closeChatModelDropdown() {
    var menu = document.getElementById("chatModelDropdownMenu");
    var btn = document.getElementById("btnChatModelSelect");
    if (menu) menu.hidden = true;
    if (btn) btn.classList.remove("open");
}

function setupChatModelModal() {
    var modal = document.getElementById("chatModelEditModal");
    var form = document.getElementById("chatModelModalForm");
    var btnClose = document.getElementById("btnChatModelModalClose");
    var btnCancel = document.getElementById("btnCancelChatModel");
    var btnDelete = document.getElementById("btnDeleteChatModel");
    var btnToggleKey = document.getElementById("btnToggleChatModelKey");
    var inputKey = document.getElementById("inputChatModelKey");

    if (btnClose) btnClose.onclick = closeChatModelModal;
    if (btnCancel) btnCancel.onclick = closeChatModelModal;
    if (modal) {
        modal.onclick = function(e) {
            if (e.target === modal) closeChatModelModal();
        };
    }
    document.addEventListener("keydown", function(e) {
        if (e.key === "Escape" && modal && !modal.hidden) {
            closeChatModelModal();
        }
    });

    if (btnToggleKey && inputKey) {
        btnToggleKey.onclick = function() {
            var eyeOpen = btnToggleKey.querySelector(".eye-open");
            var eyeClosed = btnToggleKey.querySelector(".eye-closed");
            if (inputKey.type === "password") {
                inputKey.type = "text";
                if(eyeOpen) eyeOpen.style.display = "none";
                if(eyeClosed) eyeClosed.style.display = "inline-block";
            } else {
                inputKey.type = "password";
                if(eyeOpen) eyeOpen.style.display = "inline-block";
                if(eyeClosed) eyeClosed.style.display = "none";
            }
        };
    }

    if (btnDelete) {
        btnDelete.onclick = function() {
            var editId = document.getElementById("inputChatModelEditId").value;
            if (!editId) return;
            var confirmMsg = (typeof t === "function") ? t("chat.byok_confirm_delete") : "이 모델 설정을 삭제하시겠습니까?";
            if (!confirm(confirmMsg)) return;
            
            var models = getStoredPersonalModels().filter(function(m) { return m.id !== editId; });
            saveStoredPersonalModels(models);

            if (getSelectedModelId() === editId) {
                setSelectedModelId("system");
            }
            closeChatModelModal();
            renderChatModelDropdown();
        };
    }

    if (form) {
        form.onsubmit = function(e) {
            e.preventDefault();
            var editId = document.getElementById("inputChatModelEditId").value;
            var name = document.getElementById("inputChatModelName").value.trim();
            var provider = document.getElementById("selectChatModelProvider").value;
            var model = document.getElementById("inputChatModelId").value.trim();
            var apiKey = document.getElementById("inputChatModelKey").value.trim();
            var baseUrl = document.getElementById("inputChatModelBaseUrl").value.trim();

            if (!name || !model) {
                var alertMsg = (typeof t === "function") ? t("chat.byok_alert_required") : "표시 이름과 모델 ID를 입력해주세요.";
                alert(alertMsg);
                return;
            }

            var models = getStoredPersonalModels();
            if (editId) {
                // Update
                for (var i = 0; i < models.length; i++) {
                    if (models[i].id === editId) {
                        models[i].name = name;
                        models[i].provider = provider;
                        models[i].model = model;
                        models[i].apiKey = apiKey;
                        models[i].baseUrl = baseUrl;
                        break;
                    }
                }
            } else {
                // Create
                var newId = "m_" + Date.now();
                models.push({
                    id: newId,
                    name: name,
                    provider: provider,
                    model: model,
                    apiKey: apiKey,
                    baseUrl: baseUrl
                });
                setSelectedModelId(newId);
            }

            saveStoredPersonalModels(models);
            closeChatModelModal();
            renderChatModelDropdown();
        };
    }
}

function openAddChatModelModal() {
    var modal = document.getElementById("chatModelEditModal");
    var title = document.getElementById("chatModelModalTitle");
    var btnDelete = document.getElementById("btnDeleteChatModel");
    var inputKey = document.getElementById("inputChatModelKey");
    var btnToggleKey = document.getElementById("btnToggleChatModelKey");

    if (title) title.textContent = (typeof t === "function") ? t("chat.byok_title_add") : "개인 AI 모델 / 키 추가";
    if (btnDelete) btnDelete.style.display = "none";
    if (inputKey) inputKey.type = "password";
    if (btnToggleKey) {
        var eyeOpen = btnToggleKey.querySelector(".eye-open");
        var eyeClosed = btnToggleKey.querySelector(".eye-closed");
        if(eyeOpen) eyeOpen.style.display = "inline-block";
        if(eyeClosed) eyeClosed.style.display = "none";
    }

    document.getElementById("inputChatModelEditId").value = "";
    document.getElementById("inputChatModelName").value = "";
    document.getElementById("selectChatModelProvider").value = "gemini";
    document.getElementById("inputChatModelId").value = "gemini-2.0-flash";
    document.getElementById("inputChatModelKey").value = "";
    document.getElementById("inputChatModelBaseUrl").value = "";

    if (modal) modal.hidden = false;
}

function openEditChatModelModal(modelId) {
    var modal = document.getElementById("chatModelEditModal");
    var title = document.getElementById("chatModelModalTitle");
    var btnDelete = document.getElementById("btnDeleteChatModel");
    var inputKey = document.getElementById("inputChatModelKey");
    var btnToggleKey = document.getElementById("btnToggleChatModelKey");

    var models = getStoredPersonalModels();
    var target = null;
    for (var i = 0; i < models.length; i++) {
        if (models[i].id === modelId) {
            target = models[i];
            break;
        }
    }
    if (!target) return;

    if (title) title.textContent = (typeof t === "function") ? t("chat.byok_title_edit") : "개인 AI 모델 수정";
    if (btnDelete) btnDelete.style.display = "block";
    if (inputKey) inputKey.type = "password";
    if (btnToggleKey) {
        var eyeOpen = btnToggleKey.querySelector(".eye-open");
        var eyeClosed = btnToggleKey.querySelector(".eye-closed");
        if(eyeOpen) eyeOpen.style.display = "inline-block";
        if(eyeClosed) eyeClosed.style.display = "none";
    }

    document.getElementById("inputChatModelEditId").value = target.id;
    document.getElementById("inputChatModelName").value = target.name || "";
    document.getElementById("selectChatModelProvider").value = target.provider || "gemini";
    document.getElementById("inputChatModelId").value = target.model || "";
    document.getElementById("inputChatModelKey").value = target.apiKey || "";
    document.getElementById("inputChatModelBaseUrl").value = target.baseUrl || "";

    if (modal) modal.hidden = false;
}

function closeChatModelModal() {
    var modal = document.getElementById("chatModelEditModal");
    if (modal) modal.hidden = true;
}

