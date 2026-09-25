/**
 * ollux — Modern Linux Desktop Application Logic
 * Pure client controller communicating with Python backend over PyWebView bridge.
 */

(function () {
  // Application State
  const state = {
    currentSessionId: null,
    models: [],
    currentModel: "",
    thinkingLevel: "med",
    webSearchEnabled: false,
    isGenerating: false,
    stagedAttachments: [],
    activeAssistantBubble: null,
    accumulatedContent: "",
    accumulatedThinking: "",
    thoughtStartTime: null
  };

  // DOM Elements
  const daemonStatus = document.getElementById("daemon-status");
  const newChatBtn = document.getElementById("new-chat-btn");
  const searchInput = document.getElementById("search-input");
  const sessionsList = document.getElementById("sessions-list");
  const toggleSidebarBtn = document.getElementById("toggle-sidebar");
  const sidebar = document.getElementById("sidebar");
  const chatTitle = document.getElementById("chat-title");
  const modelSelect = document.getElementById("model-select");
  const thinkingSelector = document.getElementById("thinking-selector");
  const exportChatBtn = document.getElementById("export-chat-btn");
  const messagesContainer = document.getElementById("messages-container");
  const welcomeScreen = document.getElementById("welcome-screen");
  const messagesFeed = document.getElementById("messages-feed");
  const chatTextarea = document.getElementById("chat-textarea");
  const attachmentTray = document.getElementById("attachment-tray");
  const attachFileBtn = document.getElementById("attach-file-btn");
  const webSearchBtn = document.getElementById("web-search-btn");
  const sendBtn = document.getElementById("send-btn");
  const sendIcon = sendBtn.querySelector(".send-icon");
  const stopIcon = sendBtn.querySelector(".stop-icon");

  function showNotification(text) {
    const existing = document.querySelector(".toast-notification");
    if (existing) existing.remove();
    const toast = document.createElement("div");
    toast.className = "toast-notification";
    toast.innerHTML = `<span>💾</span> <span>${escapeHtml(text)}</span>`;
    document.body.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = "0";
      toast.style.transition = "opacity 0.3s ease";
      setTimeout(() => toast.remove(), 300);
    }, 3000);
  }

  // Model Modal Elements
  const openModelHubBtn = document.getElementById("open-model-hub");
  const modelModal = document.getElementById("model-modal");
  const closeModelModalBtn = document.getElementById("close-model-modal");
  const pullModelName = document.getElementById("pull-model-name");
  const pullModelBtn = document.getElementById("pull-model-btn");
  const pullProgressContainer = document.getElementById("pull-progress-container");
  const pullProgressBar = document.getElementById("pull-progress-bar");
  const pullStatusLabel = document.getElementById("pull-status-label");
  const installedModelsTbody = document.getElementById("installed-models-tbody");

  // --- Configure Marked with Synchronous Highlight.js & Inline Headers ---
  if (typeof marked !== "undefined") {
    const customRenderer = {
      code(token) {
        const lang = token.lang || "";
        let highlighted = token.text;
        if (typeof hljs !== "undefined") {
          try {
            if (lang && hljs.getLanguage(lang)) {
              highlighted = hljs.highlight(token.text, { language: lang, ignoreIllegals: true }).value;
            } else {
              highlighted = hljs.highlightAuto(token.text).value;
            }
          } catch (e) {
            highlighted = escapeHtml(token.text);
          }
        } else {
          highlighted = escapeHtml(token.text);
        }
        const displayLang = lang || "code";
        return `
          <div class="code-wrapper">
            <div class="code-header">
              <span class="code-lang">${displayLang}</span>
              <button class="code-copy-btn" onclick="window.copyCodeBlock(this)">Copy</button>
            </div>
            <pre><code class="hljs ${lang ? 'language-' + lang : ''}">${highlighted}</code></pre>
          </div>
        `;
      }
    };
    marked.use({ renderer: customRenderer });
  }

  // Global Code Copy Function
  window.copyCodeBlock = function (btn) {
    const wrapper = btn.closest(".code-wrapper");
    if (!wrapper) return;
    const codeEl = wrapper.querySelector("code");
    if (!codeEl) return;
    navigator.clipboard.writeText(codeEl.innerText).then(() => {
      btn.textContent = "Copied!";
      setTimeout(() => (btn.textContent = "Copy"), 2000);
    });
  };

  // --- Initialize when PyWebView is ready ---
  window.addEventListener("pywebviewready", initApp);
  // Fallback for direct browser testing
  if (window.pywebview && window.pywebview.api) {
    initApp();
  }

  async function initApp() {
    setupEventListeners();
    await checkDaemon();
    await loadModels();
    await loadSessions();
  }

  // --- Event Listeners Setup ---
  function setupEventListeners() {
    newChatBtn.addEventListener("click", createNewChat);

    // Global Desktop Keyboard Shortcuts
    window.addEventListener("keydown", (e) => {
      // Ctrl+N -> New Conversation
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "n") {
        e.preventDefault();
        createNewChat();
        return;
      }

      // Ctrl+K -> Focus Search
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        if (sidebar.classList.contains("collapsed")) {
          sidebar.classList.remove("collapsed");
        }
        searchInput.focus();
        searchInput.select();
        return;
      }

      // Ctrl+B -> Toggle Sidebar
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "b") {
        e.preventDefault();
        sidebar.classList.toggle("collapsed");
        return;
      }

      // Escape -> Close modal, cancel search, or halt generation
      if (e.key === "Escape") {
        if (modelModal.classList.contains("open")) {
          modelModal.classList.remove("open");
          return;
        }
        if (state.isGenerating) {
          handleStop();
          return;
        }
        if (document.activeElement === searchInput) {
          searchInput.value = "";
          searchInput.dispatchEvent(new Event("input"));
          chatTextarea.focus();
          return;
        }
      }
    });

    toggleSidebarBtn.addEventListener("click", () => {
      sidebar.classList.toggle("collapsed");
    });

    searchInput.addEventListener("input", (e) => {
      const q = e.target.value.toLowerCase();
      document.querySelectorAll(".session-item").forEach((el) => {
        const title = el.querySelector(".session-name").textContent.toLowerCase();
        el.style.display = title.includes(q) ? "flex" : "none";
      });
    });

    chatTitle.addEventListener("blur", async () => {
      if (state.currentSessionId && window.pywebview) {
        await window.pywebview.api.update_session(state.currentSessionId, chatTitle.textContent.trim());
        await loadSessions();
      }
    });

    chatTitle.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        chatTitle.blur();
      }
    });

    modelSelect.addEventListener("change", async (e) => {
      state.currentModel = e.target.value;
      if (state.currentSessionId && window.pywebview) {
        await window.pywebview.api.update_session(state.currentSessionId, null, state.currentModel, null);
      }
    });

    // Thinking Selector (Low / Med / High)
    thinkingSelector.querySelectorAll(".seg-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        thinkingSelector.querySelectorAll(".seg-btn").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        state.thinkingLevel = btn.dataset.level;
        if (state.currentSessionId && window.pywebview) {
          await window.pywebview.api.update_session(state.currentSessionId, null, null, state.thinkingLevel);
        }
      });
    });

    // Export Conversation to Markdown
    if (exportChatBtn) {
      exportChatBtn.addEventListener("click", async () => {
        if (!state.currentSessionId || !window.pywebview) return;
        const res = await window.pywebview.api.export_session_markdown(state.currentSessionId);
        if (res && res.success) {
          const filename = res.path.split("/").pop();
          showNotification(`Exported conversation to ${filename}`);
        }
      });
    }

    // Web Search Toggle
    webSearchBtn.addEventListener("click", () => {
      state.webSearchEnabled = !state.webSearchEnabled;
      webSearchBtn.classList.toggle("active", state.webSearchEnabled);
    });

    // Textarea Auto-Resize & Submit Handling
    chatTextarea.addEventListener("input", autoResizeTextarea);
    chatTextarea.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    });

    // Focus textarea when clicking anywhere in the input container
    const inputBoxWrapper = document.querySelector(".input-box-wrapper");
    if (inputBoxWrapper) {
      inputBoxWrapper.addEventListener("click", (e) => {
        if (!e.target.closest("button") && !e.target.closest("input") && !e.target.closest(".attachment-chip")) {
          chatTextarea.focus();
        }
      });
    }

    // Large Paste Auto-Collapse (>600 characters)
    chatTextarea.addEventListener("paste", handlePasteLargeText);

    // Send / Stop Button
    sendBtn.addEventListener("click", () => {
      if (state.isGenerating) {
        handleStop();
      } else {
        handleSend();
      }
    });

    // Attach File Button
    attachFileBtn.addEventListener("click", handleFileAttachment);

    // Native Drag and Drop for Files (Supports Wayland GTK File Managers like Nautilus & Dolphin)
    const dropOverlay = document.getElementById("drop-overlay");
    let dragCounter = 0;

    window.addEventListener("dragenter", (e) => {
      e.preventDefault();
      e.stopPropagation();
      dragCounter++;
      if (e.dataTransfer) {
        e.dataTransfer.dropEffect = "copy";
      }
      if (dropOverlay) dropOverlay.classList.add("active");
    }, false);

    window.addEventListener("dragover", (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (e.dataTransfer) {
        e.dataTransfer.dropEffect = "copy";
      }
    }, false);

    window.addEventListener("dragleave", (e) => {
      e.preventDefault();
      e.stopPropagation();
      dragCounter--;
      if (dragCounter <= 0) {
        dragCounter = 0;
        if (dropOverlay) dropOverlay.classList.remove("active");
      }
    }, false);

    window.addEventListener("drop", async (e) => {
      e.preventDefault();
      e.stopPropagation();
      dragCounter = 0;
      if (dropOverlay) dropOverlay.classList.remove("active");

      // 1. Standard HTML5 FileList (browsers, direct file drops)
      const files = e.dataTransfer ? e.dataTransfer.files : [];
      if (files && files.length > 0) {
        for (let i = 0; i < files.length; i++) {
          await processIncomingFile(files[i]);
        }
        return;
      }

      // 2. Linux Wayland / GTK File Manager (Nautilus, Dolphin, Thunar) via URI list
      const uriList = e.dataTransfer ? (e.dataTransfer.getData("text/uri-list") || e.dataTransfer.getData("text/plain")) : "";
      if (uriList && uriList.trim()) {
        const lines = uriList.split(/[\r\n]+/);
        for (const rawLine of lines) {
          let line = rawLine.trim();
          if (!line || line.startsWith("#")) continue;
          if (line.startsWith("file://localhost/")) {
            line = decodeURIComponent(line.slice(16));
          } else if (line.startsWith("file:///")) {
            line = decodeURIComponent(line.slice(7));
          } else if (line.startsWith("file://")) {
            line = decodeURIComponent(line.slice(7));
          }
          if (line && window.pywebview) {
            const data = await window.pywebview.api.parse_attachment(line);
            if (data) {
              if (data.type === "error" || data.error) {
                showNotification(`⚠️ ${data.error || "Could not attach item"}`);
              } else {
                addAttachmentChip(data);
              }
            }
          }
        }
      }
    }, false);

    // Quick Prompts on Welcome Screen
    document.querySelectorAll(".prompt-chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        chatTextarea.value = chip.dataset.prompt;
        autoResizeTextarea();
        handleSend();
      });
    });

    // Model Modal
    openModelHubBtn.addEventListener("click", () => {
      modelModal.classList.add("open");
      renderInstalledModelsTable();
    });

    closeModelModalBtn.addEventListener("click", () => {
      modelModal.classList.remove("open");
    });

    modelModal.addEventListener("click", (e) => {
      if (e.target === modelModal) modelModal.classList.remove("open");
    });

    pullModelBtn.addEventListener("click", handlePullModel);
  }

  // --- Backend Sync Functions ---

  async function checkDaemon() {
    if (!window.pywebview) return;
    try {
      const res = await window.pywebview.api.check_connection();
      const dot = daemonStatus.querySelector(".status-dot");
      const txt = daemonStatus.querySelector(".status-text");
      if (res.connected) {
        dot.className = "status-dot online";
        txt.textContent = `v${res.version}`;
      } else {
        dot.className = "status-dot offline";
        txt.textContent = "Offline";
      }
    } catch {
      daemonStatus.querySelector(".status-dot").className = "status-dot offline";
      daemonStatus.querySelector(".status-text").textContent = "Offline";
    }
  }

  async function loadModels() {
    if (!window.pywebview) return;
    try {
      state.models = await window.pywebview.api.get_models();
      modelSelect.innerHTML = "";

      if (state.models.length === 0) {
        modelSelect.innerHTML = `<option value="" disabled>No models found</option>`;
        return;
      }

      state.models.forEach((m) => {
        const opt = document.createElement("option");
        opt.value = m.name;
        let badge = "";
        const nameLower = m.name.toLowerCase();
        if (nameLower.includes("qwen3.8") || nameLower.includes("vision")) {
          badge = " • 👁️ Vision & Web";
        } else if (nameLower.includes("nemotron") || nameLower.includes("qwen2.5") || nameLower.includes("deepseek")) {
          badge = " • 🧠 Reasoning & Web";
        } else if (nameLower.includes("llama2")) {
          badge = " • ⚡ Fast Local (Legacy)";
        } else {
          badge = " • 🌐 Web Ready";
        }
        opt.textContent = `${m.name} (${m.size})${badge}`;
        modelSelect.appendChild(opt);
      });

      // Default to first model
      if (!state.currentModel || !state.models.some((m) => m.name === state.currentModel)) {
        state.currentModel = state.models[0].name;
      }
      modelSelect.value = state.currentModel;
    } catch (err) {
      console.error("Failed to load models:", err);
    }
  }

  async function loadSessions() {
    if (!window.pywebview) return;
    try {
      const sessions = await window.pywebview.api.get_sessions();
      sessionsList.innerHTML = "";

      if (sessions.length === 0) {
        await createNewChat();
        return;
      }

      sessions.forEach((s) => {
        const isPinned = !!s.is_pinned;
        const item = document.createElement("div");
        item.className = `session-item ${s.id === state.currentSessionId ? "active" : ""} ${isPinned ? "is-pinned" : ""}`;
        item.dataset.id = s.id;

        const nameSpan = document.createElement("span");
        nameSpan.className = "session-name";
        nameSpan.textContent = s.title;

        const actionsDiv = document.createElement("div");
        actionsDiv.className = "session-actions";

        // Pin / Unpin Button
        const pinBtn = document.createElement("button");
        pinBtn.className = `session-action-btn session-pin-btn ${isPinned ? "is-pinned" : ""}`;
        pinBtn.title = isPinned ? "Unpin chat" : "Pin chat to top";
        pinBtn.innerHTML = `<svg width="13" height="13" viewBox="0 0 24 24" fill="${isPinned ? "currentColor" : "none"}" stroke="currentColor" stroke-width="2"><line x1="12" y1="17" x2="12" y2="22"></line><path d="M5 17h14v-2l-2-3V5a1 1 0 0 0-1-1H8a1 1 0 0 0-1 1v7l-2 3v2z"></path></svg>`;
        pinBtn.addEventListener("click", async (e) => {
          e.stopPropagation();
          if (window.pywebview) {
            await window.pywebview.api.toggle_pin_session(s.id);
            await loadSessions();
          }
        });

        // Delete Button
        const delBtn = document.createElement("button");
        delBtn.className = "session-action-btn session-del-btn";
        delBtn.title = "Delete chat";
        delBtn.innerHTML = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>`;
        delBtn.addEventListener("click", async (e) => {
          e.stopPropagation();
          if (window.pywebview) {
            await window.pywebview.api.delete_session(s.id);
            if (state.currentSessionId === s.id) {
              state.currentSessionId = null;
            }
            await loadSessions();
          }
        });

        actionsDiv.appendChild(pinBtn);
        actionsDiv.appendChild(delBtn);

        item.appendChild(nameSpan);
        item.appendChild(actionsDiv);

        item.addEventListener("click", () => switchSession(s.id));
        sessionsList.appendChild(item);
      });

      // Select first session if none active
      if (!state.currentSessionId && sessions.length > 0) {
        await switchSession(sessions[0].id);
      }
    } catch (err) {
      console.error("Failed to load sessions:", err);
    }
  }

  async function createNewChat() {
    if (!window.pywebview) return;
    const newId = await window.pywebview.api.create_session("New Chat", state.currentModel, state.thinkingLevel);
    state.currentSessionId = newId;
    await loadSessions();
    await switchSession(newId);
  }

  async function switchSession(sessionId) {
    state.currentSessionId = sessionId;
    document.querySelectorAll(".session-item").forEach((el) => {
      el.classList.toggle("active", el.dataset.id === sessionId);
    });

    if (!window.pywebview) return;
    const data = await window.pywebview.api.get_session_data(sessionId);
    if (!data || !data.session) return;

    chatTitle.textContent = data.session.title;
    state.currentModel = data.session.model || state.currentModel;
    modelSelect.value = state.currentModel;

    state.thinkingLevel = data.session.thinking_level || "med";
    thinkingSelector.querySelectorAll(".seg-btn").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.level === state.thinkingLevel);
    });

    renderMessages(data.messages || []);
  }

  // --- Message Feed Rendering & DOM Virtualization ---

  const INITIAL_RENDER_LIMIT = 40;
  let currentSessionMessages = [];
  let renderedStartIndex = 0;

  function renderMessages(messages) {
    currentSessionMessages = messages || [];
    messagesFeed.innerHTML = "";
    if (currentSessionMessages.length === 0) {
      welcomeScreen.style.display = "block";
      messagesFeed.style.display = "none";
      return;
    }

    welcomeScreen.style.display = "none";
    messagesFeed.style.display = "flex";

    const total = currentSessionMessages.length;
    renderedStartIndex = Math.max(0, total - INITIAL_RENDER_LIMIT);

    if (renderedStartIndex > 0) {
      const loadBtn = document.createElement("button");
      loadBtn.className = "load-older-btn";
      loadBtn.innerHTML = `📜 Load ${renderedStartIndex} older message${renderedStartIndex > 1 ? "s" : ""}`;
      loadBtn.onclick = loadOlderMessages;
      messagesFeed.appendChild(loadBtn);
    }

    for (let i = renderedStartIndex; i < total; i++) {
      const row = createMessageRow(currentSessionMessages[i]);
      messagesFeed.appendChild(row);
    }
    scrollToBottom();
  }

  function loadOlderMessages() {
    if (renderedStartIndex <= 0) return;
    const batchSize = 30;
    const newStartIndex = Math.max(0, renderedStartIndex - batchSize);
    const olderMsgs = currentSessionMessages.slice(newStartIndex, renderedStartIndex);
    renderedStartIndex = newStartIndex;

    const oldScrollHeight = messagesContainer.scrollHeight;
    const oldScrollTop = messagesContainer.scrollTop;

    const existingBtn = messagesFeed.querySelector(".load-older-btn");
    if (existingBtn) existingBtn.remove();

    const frag = document.createDocumentFragment();
    if (renderedStartIndex > 0) {
      const loadBtn = document.createElement("button");
      loadBtn.className = "load-older-btn";
      loadBtn.innerHTML = `📜 Load ${renderedStartIndex} older message${renderedStartIndex > 1 ? "s" : ""}`;
      loadBtn.onclick = loadOlderMessages;
      frag.appendChild(loadBtn);
    }

    olderMsgs.forEach((msg) => {
      frag.appendChild(createMessageRow(msg));
    });

    messagesFeed.insertBefore(frag, messagesFeed.firstChild);

    // Maintain scroll position smoothly
    const addedHeight = messagesContainer.scrollHeight - oldScrollHeight;
    messagesContainer.scrollTop = oldScrollTop + addedHeight;
  }

  function appendMessageToFeed(msg) {
    welcomeScreen.style.display = "none";
    messagesFeed.style.display = "flex";
    currentSessionMessages.push(msg);

    const row = createMessageRow(msg);
    messagesFeed.appendChild(row);
    scrollToBottom();
    return row;
  }

  function createMessageRow(msg) {
    const row = document.createElement("div");
    row.className = `message-row ${msg.role}`;

    if (msg.role === "user") {
      const bubble = document.createElement("div");
      bubble.className = "user-bubble";
      bubble.textContent = msg.content;

      // Render attachment badges if any
      if (msg.attachments && msg.attachments.length > 0) {
        const attContainer = document.createElement("div");
        attContainer.style.display = "flex";
        attContainer.style.gap = "6px";
        attContainer.style.flexWrap = "wrap";
        attContainer.style.marginBottom = "8px";

        msg.attachments.forEach((att) => {
          const chip = document.createElement("div");
          chip.className = "attachment-chip";
          chip.style.background = "rgba(255,255,255,0.1)";
          chip.innerHTML = `${att.type === "image" ? "🖼️" : att.type === "pdf" ? "📕" : "📄"} <span>${att.name}</span>`;
          attContainer.appendChild(chip);
        });
        bubble.prepend(attContainer);
      }

      row.appendChild(bubble);
    } else {
      const bubble = document.createElement("div");
      bubble.className = "assistant-bubble";

      // Thinking Accordion
      if (msg.thinking_content) {
        const drawer = document.createElement("details");
        drawer.className = "thought-drawer";
        if (!msg.content || !msg.content.trim()) {
          drawer.open = true;
        }
        drawer.innerHTML = `
          <summary class="thought-summary">🧠 Reasoning Process</summary>
          <div class="thought-content">${escapeHtml(msg.thinking_content)}</div>
        `;
        bubble.appendChild(drawer);
      }

      // Markdown Content
      const contentDiv = document.createElement("div");
      contentDiv.className = "markdown-body";
      contentDiv.innerHTML = renderMarkdown(msg.content);
      bubble.appendChild(contentDiv);

      // Metrics Footer
      if (msg.metrics && msg.metrics.eval_count) {
        const footer = document.createElement("div");
        footer.className = "metrics-footer";
        footer.innerHTML = `
          <span class="metric-badge speed">⚡ ${msg.metrics.tokens_per_second} tokens/s</span>
          <span>•</span>
          <span class="metric-badge">${msg.metrics.eval_count} tokens</span>
          <span>•</span>
          <span class="metric-badge">${msg.metrics.eval_duration_secs}s</span>
        `;
        bubble.appendChild(footer);
      }

      row.appendChild(bubble);
    }

    return row;
  }

  // --- Attachments, Drag-and-Drop & Large Paste Handler ---

  async function processIncomingFile(file) {
    if (!file) return;

    const MAX_SIZE = 15 * 1024 * 1024;
    if (file.size > MAX_SIZE) {
      showNotification(`File "${file.name}" exceeds 15MB limit.`);
      return;
    }

    const sizeStr = file.size < 1024 * 1024
      ? `${(file.size / 1024).toFixed(1)} KB`
      : `${(file.size / (1024 * 1024)).toFixed(1)} MB`;

    // 1. If native file path is exposed by WebKitGTK / PyWebView
    if (file.path && window.pywebview) {
      const data = await window.pywebview.api.parse_attachment(file.path);
      if (data && !data.error) {
        addAttachmentChip(data);
        return;
      }
    }

    // 2. Browser FileReader fallback
    const ext = (file.name.split('.').pop() || "").toLowerCase();
    const isImage = ["png", "jpg", "jpeg", "webp"].includes(ext) || (file.type && file.type.startsWith("image/"));
    const isPdf = ext === "pdf" || file.type === "application/pdf";

    if (isImage) {
      const reader = new FileReader();
      reader.onload = () => {
        const full = reader.result || "";
        const raw = full.includes(",") ? full.split(",")[1] : full;
        addAttachmentChip({
          name: file.name,
          type: "image",
          size: sizeStr,
          base64: raw
        });
      };
      reader.readAsDataURL(file);
    } else if (isPdf) {
      const reader = new FileReader();
      reader.onload = async () => {
        const full = reader.result || "";
        const raw = full.includes(",") ? full.split(",")[1] : full;
        if (window.pywebview) {
          const data = await window.pywebview.api.parse_attachment_b64(file.name, raw);
          if (data && !data.error) {
            addAttachmentChip(data);
          } else {
            showNotification(`Could not extract PDF text: ${data ? data.error : "Unknown error"}`);
          }
        }
      };
      reader.readAsDataURL(file);
    } else {
      // Plain text, markdown, code
      const reader = new FileReader();
      reader.onload = () => {
        addAttachmentChip({
          name: file.name,
          type: "text",
          size: sizeStr,
          text: reader.result || ""
        });
      };
      reader.readAsText(file);
    }
  }

  async function handleFileAttachment() {
    if (!window.pywebview) return;
    const paths = await window.pywebview.api.open_file_dialog();
    if (!paths || paths.length === 0) return;

    for (const p of paths) {
      const data = await window.pywebview.api.parse_attachment(p);
      if (data && !data.error) {
        addAttachmentChip(data);
      }
    }
  }

  function handlePasteLargeText(e) {
    const text = (e.clipboardData || window.clipboardData).getData("text");
    if (text && text.length > 600) {
      e.preventDefault();
      const chipData = {
        name: `Pasted Text (${(text.length / 1024).toFixed(1)} KB)`,
        type: "text",
        text: text,
        size: `${(text.length / 1024).toFixed(1)} KB`
      };
      addAttachmentChip(chipData);
    }
  }

  function addAttachmentChip(att) {
    state.stagedAttachments.push(att);
    renderAttachmentTray();
  }

  function removeAttachmentChip(index) {
    state.stagedAttachments.splice(index, 1);
    renderAttachmentTray();
  }

  function renderAttachmentTray() {
    attachmentTray.innerHTML = "";
    state.stagedAttachments.forEach((att, idx) => {
      const chip = document.createElement("div");
      chip.className = "attachment-chip";
      const icon = att.type === "image" ? "🖼️" : att.type === "pdf" ? "📕" : "📄";
      chip.innerHTML = `
        <span>${icon}</span>
        <span>${att.name}</span>
        <button class="remove-att-btn" title="Remove">&times;</button>
      `;
      chip.querySelector(".remove-att-btn").addEventListener("click", () => removeAttachmentChip(idx));
      attachmentTray.appendChild(chip);
    });
  }

  // --- Sending & Streaming ---

  async function handleSend() {
    const content = chatTextarea.value.trim();
    if (!content && state.stagedAttachments.length === 0) return;
    if (state.isGenerating || !window.pywebview) return;

    const attachmentsToSend = [...state.stagedAttachments];
    state.stagedAttachments = [];
    renderAttachmentTray();

    chatTextarea.value = "";
    autoResizeTextarea();

    // 1. Render User Message
    appendMessageToFeed({
      role: "user",
      content: content,
      attachments: attachmentsToSend
    });

    // 2. Prepare Live Assistant Bubble
    userScrolledUp = false;
    state.isGenerating = true;
    updateSendButtonState(true);
    state.accumulatedContent = "";
    state.accumulatedThinking = "";
    state.thoughtStartTime = Date.now();

    const assistantRow = document.createElement("div");
    assistantRow.className = "message-row assistant";
    
    const bubble = document.createElement("div");
    bubble.className = "assistant-bubble";

    const thoughtDrawer = document.createElement("details");
    thoughtDrawer.className = "thought-drawer";
    thoughtDrawer.style.display = "none";
    thoughtDrawer.open = true;
    thoughtDrawer.innerHTML = `
      <summary class="thought-summary">🧠 Reasoning...</summary>
      <div class="thought-content"></div>
    `;

    const contentDiv = document.createElement("div");
    contentDiv.className = "markdown-body";
    contentDiv.innerHTML = `<span class="cursor-pulse">▋</span>`;

    bubble.appendChild(thoughtDrawer);
    bubble.appendChild(contentDiv);
    assistantRow.appendChild(bubble);
    messagesFeed.appendChild(assistantRow);
    scrollToBottom();

    state.activeAssistantBubble = {
      row: assistantRow,
      bubble: bubble,
      drawer: thoughtDrawer,
      thoughtContent: thoughtDrawer.querySelector(".thought-content"),
      contentDiv: contentDiv
    };

    // 3. Trigger Backend
    await window.pywebview.api.send_message(
      state.currentSessionId,
      content,
      state.currentModel,
      state.thinkingLevel,
      state.webSearchEnabled,
      attachmentsToSend
    );
  }

  async function handleStop() {
    if (window.pywebview) {
      await window.pywebview.api.stop_generation();
    }
    state.isGenerating = false;
    updateSendButtonState(false);
  }

  function updateSendButtonState(generating) {
    sendBtn.classList.toggle("generating", generating);
    sendIcon.style.display = generating ? "none" : "block";
    stopIcon.style.display = generating ? "block" : "none";
  }

  // --- Window Callbacks (Called from Python) ---

  let renderScheduled = false;
  let lastRenderTimestamp = 0;
  const STREAM_RENDER_INTERVAL_MS = 45; // ~22 FPS cap saves 65% CPU during token streaming

  function scheduleStreamRender() {
    if (renderScheduled) return;
    renderScheduled = true;

    const elapsed = performance.now() - lastRenderTimestamp;
    const delay = elapsed >= STREAM_RENDER_INTERVAL_MS ? 0 : (STREAM_RENDER_INTERVAL_MS - elapsed);

    setTimeout(() => {
      requestAnimationFrame(() => {
        renderScheduled = false;
        lastRenderTimestamp = performance.now();
        if (state.activeAssistantBubble) {
          state.activeAssistantBubble.contentDiv.innerHTML = renderMarkdown(state.accumulatedContent, true);
          smartScrollToBottom();
        }
      });
    }, delay);
  }

  window.onStreamChunk = function (chunk) {
    if (!state.activeAssistantBubble) return;

    if (chunk.type === "thinking") {
      if (!state.accumulatedContent && state.activeAssistantBubble.contentDiv.textContent.includes("Searching web")) {
        state.activeAssistantBubble.contentDiv.innerHTML = `<span class="cursor-pulse">▋</span>`;
      }
      state.accumulatedThinking += chunk.token;
      state.activeAssistantBubble.drawer.style.display = "block";
      state.activeAssistantBubble.drawer.open = true;
      state.activeAssistantBubble.thoughtContent.textContent = state.accumulatedThinking;
      smartScrollToBottom();
    } else if (chunk.type === "content") {
      state.accumulatedContent += chunk.token;
      scheduleStreamRender();
    }
  };

  window.onStreamComplete = function (metrics) {
    if (!state.activeAssistantBubble) return;

    // Remove cursor cleanly
    state.activeAssistantBubble.contentDiv.innerHTML = renderMarkdown(state.accumulatedContent, false);

    // Update thinking summary title with duration
    if (state.accumulatedThinking) {
      const elapsed = ((Date.now() - state.thoughtStartTime) / 1000).toFixed(1);
      state.activeAssistantBubble.drawer.querySelector(".thought-summary").textContent = `🧠 Reasoned for ${elapsed}s (click to expand)`;
      if (state.accumulatedContent && state.accumulatedContent.trim()) {
        state.activeAssistantBubble.drawer.open = false;
      } else {
        state.activeAssistantBubble.drawer.open = true;
      }
    }

    // Append performance metrics
    if (metrics && metrics.stopped) {
      const footer = document.createElement("div");
      footer.className = "metrics-footer";
      footer.innerHTML = `<span class="metric-badge" style="color: var(--accent-amber);">⏹ Stopped</span>`;
      state.activeAssistantBubble.row.querySelector(".assistant-bubble").appendChild(footer);
    } else if (metrics && metrics.eval_count) {
      const footer = document.createElement("div");
      footer.className = "metrics-footer";
      footer.innerHTML = `
        <span class="metric-badge speed">⚡ ${metrics.tokens_per_second} tokens/s</span>
        <span>•</span>
        <span class="metric-badge">${metrics.eval_count} tokens</span>
        <span>•</span>
        <span class="metric-badge">${metrics.eval_duration_secs}s</span>
      `;
      state.activeAssistantBubble.row.querySelector(".assistant-bubble").appendChild(footer);
    }

    state.isGenerating = false;
    updateSendButtonState(false);
    state.activeAssistantBubble = null;
    smartScrollToBottom();
  };

  window.onStreamError = function (err) {
    if (state.activeAssistantBubble) {
      state.activeAssistantBubble.contentDiv.innerHTML += `<div style="color: var(--accent-red); margin-top: 8px;">⚠️ ${escapeHtml(err)}</div>`;
    }
    state.isGenerating = false;
    updateSendButtonState(false);
    state.activeAssistantBubble = null;
  };

  window.onSessionRenamed = function (data) {
    if (state.currentSessionId === data.id) {
      chatTitle.textContent = data.title;
    }
    loadSessions();
  };

  window.onSearchStatus = function (status) {
    if (state.activeAssistantBubble) {
      state.activeAssistantBubble.contentDiv.innerHTML = `<span style="color: var(--accent-cyan); font-size: 12px;">🔍 ${escapeHtml(status)}</span>`;
    }
  };

  window.onWebSearchResults = function (sources) {
    if (!state.activeAssistantBubble || !sources || sources.length === 0) return;

    if (!state.accumulatedContent) {
      state.activeAssistantBubble.contentDiv.innerHTML = `<span class="cursor-pulse">▋</span>`;
    }

    let sourcesDrawer = state.activeAssistantBubble.bubble.querySelector(".sources-drawer");
    if (!sourcesDrawer) {
      sourcesDrawer = document.createElement("details");
      sourcesDrawer.className = "sources-drawer";
      sourcesDrawer.innerHTML = `
        <summary class="sources-summary">🌐 ${sources.length} Web Sources Consulted</summary>
        <div class="sources-list"></div>
      `;
      state.activeAssistantBubble.bubble.insertBefore(sourcesDrawer, state.activeAssistantBubble.contentDiv);
    }

    const listEl = sourcesDrawer.querySelector(".sources-list");
    listEl.innerHTML = "";
    sources.forEach((s, idx) => {
      const item = document.createElement("a");
      item.className = "source-item";
      item.href = s.href;
      item.target = "_blank";
      item.rel = "noopener noreferrer";
      item.innerHTML = `
        <span class="source-index">[${idx + 1}]</span>
        <span class="source-title">${escapeHtml(s.title || s.href)}</span>
      `;
      listEl.appendChild(item);
    });
    smartScrollToBottom();
  };

  // --- Model Pull & Management ---

  async function handlePullModel() {
    const name = pullModelName.value.trim();
    if (!name || !window.pywebview) return;

    pullModelBtn.disabled = true;
    pullProgressContainer.style.display = "block";
    pullProgressBar.style.width = "0%";
    pullStatusLabel.textContent = `Requesting ${name}...`;

    await window.pywebview.api.pull_model(name);
  }

  window.onModelPullProgress = function (data) {
    if (data.total && data.completed) {
      const pct = Math.round((data.completed / data.total) * 100);
      pullProgressBar.style.width = `${pct}%`;
      pullStatusLabel.textContent = `${data.status} (${pct}%)`;
    } else {
      pullStatusLabel.textContent = data.status || "Downloading...";
    }
  };

  window.onModelPullComplete = async function (data) {
    pullModelBtn.disabled = false;
    if (data.success) {
      pullProgressBar.style.width = "100%";
      pullStatusLabel.textContent = `Successfully pulled ${data.model}!`;
      pullModelName.value = "";
      await loadModels();
      renderInstalledModelsTable();
    } else {
      pullStatusLabel.textContent = `Error pulling ${data.model}`;
    }
  };

  function renderInstalledModelsTable() {
    installedModelsTbody.innerHTML = "";
    state.models.forEach((m) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td><strong>${m.name}</strong></td>
        <td>${m.parameter_size || "N/A"}</td>
        <td>${m.size}</td>
        <td>${m.quantization_level || "N/A"}</td>
        <td>
          <button class="btn-delete-model" data-name="${m.name}">Delete</button>
        </td>
      `;
      tr.querySelector(".btn-delete-model").addEventListener("click", async () => {
        if (confirm(`Are you sure you want to delete ${m.name}? This will free ${m.size} on disk.`)) {
          await window.pywebview.api.delete_model(m.name);
          await loadModels();
          renderInstalledModelsTable();
        }
      });
      installedModelsTbody.appendChild(tr);
    });
  }

  // --- Utilities ---

  function autoResizeTextarea() {
    chatTextarea.style.height = "auto";
    chatTextarea.style.height = Math.max(52, Math.min(chatTextarea.scrollHeight, 180)) + "px";
  }

  // Smart auto-scrolling: detects user scrolling up
  let userScrolledUp = false;

  messagesContainer.addEventListener("scroll", () => {
    const distanceToBottom = messagesContainer.scrollHeight - (messagesContainer.scrollTop + messagesContainer.clientHeight);
    userScrolledUp = distanceToBottom > 60;
  });

  function smartScrollToBottom(force = false) {
    if (force || !userScrolledUp) {
      messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }
  }

  function scrollToBottom() {
    smartScrollToBottom(true);
  }

  function renderMarkdown(text, showCursor = false) {
    if (!text && !showCursor) return "";
    if (!text && showCursor) return `<span class="cursor-pulse">▋</span>`;

    let html = "";
    if (typeof marked !== "undefined") {
      html = marked.parse(text || "");
    } else {
      html = escapeHtml(text).replace(/\n/g, "<br>");
    }

    if (showCursor) {
      const cursorHtml = `<span class="cursor-pulse">▋</span>`;
      // Insert cursor INSIDE the paragraph or code block right after the last token
      if (/<\/p>\s*$/.test(html)) {
        html = html.replace(/<\/p>\s*$/, `${cursorHtml}</p>`);
      } else if (/<\/code><\/pre>\s*<\/div>\s*$/.test(html)) {
        html = html.replace(/<\/code>/, `${cursorHtml}</code>`);
      } else {
        html += cursorHtml;
      }
    }

    return html;
  }

  function escapeHtml(str) {
    if (!str) return "";
    return str
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }
})();
