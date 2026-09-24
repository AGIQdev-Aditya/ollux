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
        opt.textContent = `${m.name} (${m.size})`;
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
        const item = document.createElement("div");
        item.className = `session-item ${s.id === state.currentSessionId ? "active" : ""}`;
        item.dataset.id = s.id;

        const nameSpan = document.createElement("span");
        nameSpan.className = "session-name";
        nameSpan.textContent = s.title;

        const delBtn = document.createElement("button");
        delBtn.className = "session-del-btn";
        delBtn.innerHTML = `✕`;
        delBtn.title = "Delete chat";
        delBtn.addEventListener("click", async (e) => {
          e.stopPropagation();
          await window.pywebview.api.delete_session(s.id);
          if (state.currentSessionId === s.id) {
            state.currentSessionId = null;
          }
          await loadSessions();
        });

        item.appendChild(nameSpan);
        item.appendChild(delBtn);

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

  // --- Message Feed Rendering ---

  function renderMessages(messages) {
    messagesFeed.innerHTML = "";
    if (messages.length === 0) {
      welcomeScreen.style.display = "block";
      messagesFeed.style.display = "none";
    } else {
      welcomeScreen.style.display = "none";
      messagesFeed.style.display = "flex";
      messages.forEach((msg) => appendMessageToFeed(msg));
      scrollToBottom();
    }
  }

  function appendMessageToFeed(msg) {
    welcomeScreen.style.display = "none";
    messagesFeed.style.display = "flex";

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

    messagesFeed.appendChild(row);
    scrollToBottom();
    return row;
  }

  // --- Attachments & Large Paste Handler ---

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

  window.onStreamChunk = function (chunk) {
    if (!state.activeAssistantBubble) return;

    if (chunk.type === "thinking") {
      state.accumulatedThinking += chunk.token;
      state.activeAssistantBubble.drawer.style.display = "block";
      state.activeAssistantBubble.drawer.open = true;
      state.activeAssistantBubble.thoughtContent.textContent = state.accumulatedThinking;
    } else if (chunk.type === "content") {
      state.accumulatedContent += chunk.token;
      state.activeAssistantBubble.contentDiv.innerHTML = renderMarkdown(state.accumulatedContent) + `<span class="cursor-pulse">▋</span>`;
    }
    scrollToBottom();
  };

  window.onStreamComplete = function (metrics) {
    if (!state.activeAssistantBubble) return;

    // Remove cursor
    state.activeAssistantBubble.contentDiv.innerHTML = renderMarkdown(state.accumulatedContent);

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
    if (metrics && metrics.eval_count) {
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
    scrollToBottom();
  };

  window.onStreamError = function (err) {
    if (state.activeAssistantBubble) {
      state.activeAssistantBubble.contentDiv.innerHTML += `<div style="color: var(--accent-red); margin-top: 8px;">⚠️ ${escapeHtml(err)}</div>`;
    }
    state.isGenerating = false;
    updateSendButtonState(false);
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
    chatTextarea.style.height = Math.min(chatTextarea.scrollHeight, 180) + "px";
  }

  function scrollToBottom() {
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
  }

  function renderMarkdown(text) {
    if (typeof marked !== "undefined") {
      const html = marked.parse(text || "");
      setTimeout(() => {
        if (typeof hljs !== "undefined") {
          document.querySelectorAll("pre code").forEach((el) => {
            if (!el.dataset.highlighted) {
              hljs.highlightElement(el);
              el.dataset.highlighted = "true";
              addCopyButtonToCode(el.parentElement);
            }
          });
        }
      }, 10);
      return html;
    }
    return escapeHtml(text).replace(/\n/g, "<br>");
  }

  function addCopyButtonToCode(preEl) {
    if (preEl.querySelector(".code-header")) return;
    const header = document.createElement("div");
    header.className = "code-header";
    header.innerHTML = `
      <span>Code</span>
      <button class="code-copy-btn">Copy</button>
    `;
    const btn = header.querySelector(".code-copy-btn");
    btn.addEventListener("click", () => {
      const code = preEl.querySelector("code").innerText;
      navigator.clipboard.writeText(code);
      btn.textContent = "Copied!";
      setTimeout(() => (btn.textContent = "Copy"), 2000);
    });
    preEl.prepend(header);
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
