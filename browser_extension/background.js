const DEFAULT_BRIDGE_BASE_URL = "http://127.0.0.1:8766";
const STORAGE_KEYS = {
  bridgeBaseUrl: "ankitaBridgeBaseUrl",
  clientId: "ankitaBridgeClientId",
  sessions: "ankitaBridgeSessions",
  lastError: "ankitaBridgeLastError",
};

const CAPABILITIES = [
  "tabs",
  "dom",
  "snapshot",
  "screenshot",
  "forms",
  "navigation",
  "session-attach",
];

const state = {
  bridgeBaseUrl: DEFAULT_BRIDGE_BASE_URL,
  clientId: null,
  sessions: {},
  polling: false,
  connected: false,
  lastError: "",
  lastBridgeStatus: null,
  lastActiveTab: null,
};

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function nowIso() {
  return new Date().toISOString();
}

function normalizeBridgeUrl(url) {
  return String(url || DEFAULT_BRIDGE_BASE_URL).trim().replace(/\/+$/, "");
}

function randomId(prefix) {
  return `${prefix}-${crypto.randomUUID().split("-")[0]}`;
}

function isScriptableUrl(url) {
  return /^(https?|file):/i.test(String(url || ""));
}

async function loadState() {
  const stored = await chrome.storage.local.get({
    [STORAGE_KEYS.bridgeBaseUrl]: DEFAULT_BRIDGE_BASE_URL,
    [STORAGE_KEYS.clientId]: null,
    [STORAGE_KEYS.sessions]: {},
    [STORAGE_KEYS.lastError]: "",
  });

  state.bridgeBaseUrl = normalizeBridgeUrl(stored[STORAGE_KEYS.bridgeBaseUrl]);
  state.clientId = stored[STORAGE_KEYS.clientId];
  state.sessions = stored[STORAGE_KEYS.sessions] || {};
  state.lastError = stored[STORAGE_KEYS.lastError] || "";
}

async function persistState() {
  await chrome.storage.local.set({
    [STORAGE_KEYS.bridgeBaseUrl]: state.bridgeBaseUrl,
    [STORAGE_KEYS.clientId]: state.clientId,
    [STORAGE_KEYS.sessions]: state.sessions,
    [STORAGE_KEYS.lastError]: state.lastError,
  });
}

async function getActiveTab() {
  let tabs = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  if (!tabs || !tabs.length) {
    tabs = await chrome.tabs.query({ active: true });
  }
  return tabs && tabs.length ? tabs[0] : null;
}

function tabSummary(tab) {
  if (!tab) {
    return null;
  }
  return {
    tab_id: tab.id,
    window_id: tab.windowId,
    url: tab.url || "",
    title: tab.title || "",
    status: tab.status || "",
    index: typeof tab.index === "number" ? tab.index : null,
    fav_icon_url: tab.favIconUrl || null,
  };
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });

  const text = await response.text();
  let data;
  try {
    data = text ? JSON.parse(text) : {};
  } catch (error) {
    throw new Error(`Invalid JSON from bridge: ${error}`);
  }

  if (!response.ok) {
    throw new Error(data.error || `${response.status} ${response.statusText}`);
  }

  return data;
}

async function getBridgeStatus() {
  return fetchJson(`${state.bridgeBaseUrl}/status`, { method: "GET" });
}

async function registerWithBridge(forceNew = false) {
  const activeTab = await getActiveTab();
  const payload = {
    client_id: forceNew ? undefined : state.clientId,
    name: "ankita-browser-extension",
    version: chrome.runtime.getManifest().version,
    capabilities: CAPABILITIES,
    active_tab: tabSummary(activeTab),
  };
  const response = await fetchJson(`${state.bridgeBaseUrl}/extension/register`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
  state.clientId = response.client_id;
  state.connected = true;
  state.lastBridgeStatus = response.bridge || null;
  state.lastError = "";
  state.lastActiveTab = tabSummary(activeTab);
  await persistState();
  return response;
}

async function sendHeartbeat() {
  if (!state.clientId) {
    return registerWithBridge(false);
  }
  const activeTab = await getActiveTab();
  const response = await fetchJson(`${state.bridgeBaseUrl}/extension/heartbeat`, {
    method: "POST",
    body: JSON.stringify({
      client_id: state.clientId,
      capabilities: CAPABILITIES,
      active_tab: tabSummary(activeTab),
    }),
  });
  state.connected = !!response.ok;
  state.lastError = "";
  state.lastActiveTab = tabSummary(activeTab);
  await persistState();
  return response;
}

async function ensureBridgeConnection() {
  if (!state.clientId) {
    return registerWithBridge(false);
  }
  try {
    return await sendHeartbeat();
  } catch (error) {
    return registerWithBridge(true);
  }
}

async function ensureContentScript(tabId) {
  try {
    const pong = await chrome.tabs.sendMessage(tabId, { type: "ankita_ping" });
    if (pong && pong.ok) {
      return;
    }
  } catch (error) {
    // Fall through to injection.
  }

  await chrome.scripting.executeScript({
    target: { tabId },
    files: ["content.js"],
  });

  const pong = await chrome.tabs.sendMessage(tabId, { type: "ankita_ping" });
  if (!pong || !pong.ok) {
    throw new Error("Content script did not respond after injection");
  }
}

async function waitForTabComplete(tabId, timeoutMs = 20000) {
  const existing = await chrome.tabs.get(tabId);
  if (existing.status === "complete") {
    return existing;
  }

  return new Promise((resolve, reject) => {
    const deadline = setTimeout(() => {
      chrome.tabs.onUpdated.removeListener(listener);
      reject(new Error(`Timed out waiting for tab ${tabId} to finish loading`));
    }, timeoutMs);

    const listener = (updatedTabId, changeInfo, tab) => {
      if (updatedTabId !== tabId) {
        return;
      }
      if (changeInfo.status === "complete") {
        clearTimeout(deadline);
        chrome.tabs.onUpdated.removeListener(listener);
        resolve(tab);
      }
    };

    chrome.tabs.onUpdated.addListener(listener);
  });
}

async function refreshSession(sessionId) {
  const session = state.sessions[sessionId];
  if (!session) {
    throw new Error(`Unknown session '${sessionId}'`);
  }

  try {
    const tab = await chrome.tabs.get(session.tab_id);
    session.tab_id = tab.id;
    session.window_id = tab.windowId;
    session.url = tab.url || "";
    session.title = tab.title || "";
    session.index = typeof tab.index === "number" ? tab.index : null;
    session.last_used_at = nowIso();
    state.sessions[sessionId] = session;
    await persistState();
    return session;
  } catch (error) {
    delete state.sessions[sessionId];
    await persistState();
    throw new Error(`Session '${sessionId}' is stale`);
  }
}

async function createOrAttachSession(command) {
  const sessionId = command.session_id || randomId("browser");
  if (state.sessions[sessionId]) {
    const existing = await refreshSession(sessionId);
    return { sessionId, session: existing, reused: true };
  }

  const attachMode = command.attach_mode || "active";
  let tab = null;

  if (command.tab_id) {
    tab = await chrome.tabs.get(command.tab_id);
  } else if (attachMode !== "new_tab") {
    tab = await getActiveTab();
  }

  if (!tab || !isScriptableUrl(tab.url || "")) {
    const createUrl = command.url || "about:blank";
    tab = await chrome.tabs.create({ url: createUrl, active: true });
    if (createUrl !== "about:blank") {
      tab = await waitForTabComplete(tab.id, Math.max(20000, Number(command.timeout_sec || 20) * 1000));
    }
  } else if (command.url && tab.url !== command.url) {
    tab = await chrome.tabs.update(tab.id, { url: command.url, active: true });
    tab = await waitForTabComplete(tab.id, Math.max(20000, Number(command.timeout_sec || 20) * 1000));
  }

  if (!isScriptableUrl(tab.url || "")) {
    throw new Error(`Unsupported tab URL for automation: ${tab.url || "(blank)"}`);
  }

  await ensureContentScript(tab.id);

  const record = {
    session_id: sessionId,
    tab_id: tab.id,
    window_id: tab.windowId,
    url: tab.url || "",
    title: tab.title || "",
    index: typeof tab.index === "number" ? tab.index : null,
    created_at: nowIso(),
    last_used_at: nowIso(),
    attach_mode: attachMode,
  };
  state.sessions[sessionId] = record;
  await persistState();
  return { sessionId, session: record, reused: false };
}

async function activateSessionTab(session) {
  await chrome.windows.update(session.window_id, { focused: true }).catch(() => {});
  await chrome.tabs.update(session.tab_id, { active: true }).catch(() => {});
  await sleep(150);
}

async function collectSnapshot(tabId, maxItems = 10) {
  await ensureContentScript(tabId);
  const response = await chrome.tabs.sendMessage(tabId, {
    type: "ankita_snapshot",
    maxItems,
  });
  if (!response || !response.ok) {
    throw new Error((response && response.error) || "Failed to collect snapshot");
  }
  return response.snapshot;
}

async function runDomStep(tabId, step) {
  await ensureContentScript(tabId);
  const response = await chrome.tabs.sendMessage(tabId, {
    type: "ankita_dom_step",
    step,
  });
  if (!response || !response.ok) {
    throw new Error((response && response.error) || "DOM step failed");
  }
  return response;
}

async function executeBackgroundStep(session, step, index, command) {
  const stepType = String(step.type || "").toLowerCase();

  if (stepType === "goto") {
    if (!step.url) {
      throw new Error("goto step requires url");
    }
    await chrome.tabs.update(session.tab_id, { url: step.url, active: true });
    await waitForTabComplete(session.tab_id, Math.max(20000, Number(step.timeout_sec || command.timeout_sec || 20) * 1000));
    const updated = await refreshSession(command.session_id);
    return [{ index, type: stepType, ok: true, url: updated.url }, null];
  }

  if (stepType === "reload") {
    await chrome.tabs.reload(session.tab_id);
    await waitForTabComplete(session.tab_id, Math.max(20000, Number(step.timeout_sec || command.timeout_sec || 20) * 1000));
    const updated = await refreshSession(command.session_id);
    return [{ index, type: stepType, ok: true, url: updated.url }, null];
  }

  if (stepType === "back" || stepType === "forward") {
    await chrome.scripting.executeScript({
      target: { tabId: session.tab_id },
      func: (direction) => {
        if (direction === "back") {
          history.back();
        } else {
          history.forward();
        }
      },
      args: [stepType],
    });
    await sleep(1000);
    const updated = await refreshSession(command.session_id);
    return [{ index, type: stepType, ok: true, url: updated.url }, null];
  }

  if (stepType === "new_tab") {
    const newTab = await chrome.tabs.create({
      windowId: session.window_id,
      url: step.url || "about:blank",
      active: true,
    });
    if (step.url) {
      await waitForTabComplete(newTab.id, Math.max(20000, Number(step.timeout_sec || command.timeout_sec || 20) * 1000));
    }
    await ensureContentScript(newTab.id);
    session.tab_id = newTab.id;
    session.window_id = newTab.windowId;
    session.url = newTab.url || "";
    session.title = newTab.title || "";
    session.index = typeof newTab.index === "number" ? newTab.index : null;
    session.last_used_at = nowIso();
    state.sessions[command.session_id] = session;
    await persistState();
    return [{ index, type: stepType, ok: true, tab_id: newTab.id, url: session.url }, null];
  }

  if (stepType === "switch_tab") {
    const tabs = await chrome.tabs.query({ windowId: session.window_id });
    const tabIndex = Number.isInteger(step.tab_index) ? step.tab_index : 0;
    const targetTab = step.tab_id
      ? await chrome.tabs.get(step.tab_id)
      : tabs.find((tab) => tab.index === tabIndex);
    if (!targetTab) {
      throw new Error(`No tab found for switch_tab with tab_index=${tabIndex}`);
    }
    await chrome.tabs.update(targetTab.id, { active: true });
    session.tab_id = targetTab.id;
    session.window_id = targetTab.windowId;
    session.url = targetTab.url || "";
    session.title = targetTab.title || "";
    session.index = typeof targetTab.index === "number" ? targetTab.index : null;
    session.last_used_at = nowIso();
    state.sessions[command.session_id] = session;
    await persistState();
    return [{ index, type: stepType, ok: true, tab_id: targetTab.id, url: session.url }, null];
  }

  if (stepType === "close_tab") {
    const targetTabId = step.tab_id || session.tab_id;
    await chrome.tabs.remove(targetTabId);
    const fallbackTabs = await chrome.tabs.query({ windowId: session.window_id });
    if (fallbackTabs.length) {
      const fallback = fallbackTabs[0];
      session.tab_id = fallback.id;
      session.url = fallback.url || "";
      session.title = fallback.title || "";
      session.index = typeof fallback.index === "number" ? fallback.index : null;
      state.sessions[command.session_id] = session;
    } else {
      delete state.sessions[command.session_id];
    }
    await persistState();
    return [{ index, type: stepType, ok: true, closed_tab_id: targetTabId }, null];
  }

  if (stepType === "screenshot") {
    await activateSessionTab(session);
    const dataUrl = await chrome.tabs.captureVisibleTab(session.window_id, { format: "png" });
    const filename = step.filename || `screenshot_step_${index + 1}.png`;
    const artifact = {
      type: "screenshot",
      filename,
      data_url: dataUrl,
      source: "captureVisibleTab",
    };
    return [{ index, type: stepType, ok: true, filename }, artifact];
  }

  if (stepType === "snapshot") {
    const snapshot = await collectSnapshot(session.tab_id, step.max_items || 10);
    return [{ index, type: stepType, ok: true, snapshot }, null];
  }

  return [null, null];
}

async function handleStartSession(command) {
  const { sessionId, session, reused } = await createOrAttachSession(command);
  const snapshot = await collectSnapshot(session.tab_id, command.max_items || 10).catch(() => null);
  return {
    ok: true,
    action: "start_session",
    session_id: sessionId,
    reused,
    tab_id: session.tab_id,
    window_id: session.window_id,
    url: session.url,
    title: session.title,
    snapshot,
  };
}

async function handleSnapshot(command) {
  const session = await refreshSession(command.session_id);
  const snapshot = await collectSnapshot(session.tab_id, command.max_items || 10);
  return {
    ok: true,
    action: "snapshot",
    session_id: command.session_id,
    tab_id: session.tab_id,
    window_id: session.window_id,
    url: session.url,
    title: session.title,
    snapshot,
  };
}

async function handleListSessions() {
  const sessions = Object.values(state.sessions);
  return {
    ok: true,
    action: "list_sessions",
    sessions,
  };
}

async function handleCloseSession(command) {
  const session = await refreshSession(command.session_id);
  if (command.close_tab) {
    await chrome.tabs.remove(session.tab_id).catch(() => {});
  }
  delete state.sessions[command.session_id];
  await persistState();
  return {
    ok: true,
    action: "close_session",
    session_id: command.session_id,
  };
}

async function handleRunSteps(command) {
  const session = await refreshSession(command.session_id);
  const steps = Array.isArray(command.steps) ? command.steps : [];
  const results = [];
  const artifacts = [];

  for (let index = 0; index < steps.length; index += 1) {
    const step = steps[index];
    const stepType = String(step.type || "").toLowerCase();
    try {
      const [backgroundResult, artifact] = await executeBackgroundStep(session, step, index, command);
      if (backgroundResult) {
        results.push(backgroundResult);
        if (artifact) {
          artifacts.push(artifact);
        }
        continue;
      }

      if (stepType === "upload") {
        throw new Error("upload is not supported via the extension yet");
      }

      const domResult = await runDomStep(session.tab_id, step);
      const result = {
        index,
        type: stepType,
        ok: true,
      };

      if (domResult.output !== undefined) {
        result.output = domResult.output;
      }
      if (domResult.value !== undefined) {
        result.value = domResult.value;
      }
      if (domResult.count !== undefined) {
        result.count = domResult.count;
      }
      if (domResult.note) {
        result.note = domResult.note;
      }
      if (domResult.snapshot) {
        result.snapshot = domResult.snapshot;
      }
      if (Array.isArray(domResult.artifacts)) {
        artifacts.push(...domResult.artifacts);
      }

      results.push(result);
    } catch (error) {
      results.push({
        index,
        type: stepType,
        ok: false,
        error: String(error.message || error),
      });
      throw {
        ok: false,
        action: "run_steps",
        session_id: command.session_id,
        url: session.url,
        title: session.title,
        steps: results,
        artifacts,
        error: String(error.message || error),
      };
    }
  }

  const updated = await refreshSession(command.session_id);
  return {
    ok: true,
    action: "run_steps",
    session_id: command.session_id,
    url: updated.url,
    title: updated.title,
    steps: results,
    artifacts,
    error: null,
  };
}

async function executeCommand(command) {
  const action = String(command.action || "").toLowerCase();
  switch (action) {
    case "start_session":
      return handleStartSession(command);
    case "run_steps":
      return handleRunSteps(command);
    case "snapshot":
      return handleSnapshot(command);
    case "close_session":
      return handleCloseSession(command);
    case "list_sessions":
      return handleListSessions(command);
    default:
      return {
        ok: false,
        action,
        error: `unsupported_action:${action}`,
      };
  }
}

async function submitCommandResult(command, result) {
  await fetchJson(`${state.bridgeBaseUrl}/extension/result`, {
    method: "POST",
    body: JSON.stringify({
      client_id: state.clientId,
      command_id: command.command_id,
      ...result,
    }),
  });
}

async function processBridgeCommand(command) {
  try {
    const result = await executeCommand(command);
    await submitCommandResult(command, result);
    state.lastError = "";
    await persistState();
  } catch (error) {
    const failure = error && typeof error === "object" && error.ok === false
      ? error
      : {
          ok: false,
          action: command.action,
          session_id: command.session_id,
          error: String(error.message || error),
        };
    await submitCommandResult(command, failure).catch(() => {});
    state.lastError = String(failure.error || error);
    await persistState();
  }
}

async function pollLoop() {
  if (state.polling) {
    return;
  }
  state.polling = true;

  while (state.polling) {
    try {
      await ensureBridgeConnection();
      const response = await fetchJson(
        `${state.bridgeBaseUrl}/extension/next?client_id=${encodeURIComponent(state.clientId)}&timeout_sec=20`,
        { method: "GET" }
      );
      state.connected = true;
      if (response.command) {
        await processBridgeCommand(response.command);
      } else {
        await sendHeartbeat().catch(() => {});
      }
    } catch (error) {
      state.connected = false;
      state.lastError = String(error.message || error);
      await persistState();
      await sleep(1500);
    }
  }
}

async function bootstrap() {
  await loadState();
  chrome.alarms.create("ankita-bridge-keepalive", { periodInMinutes: 1 });
  void pollLoop();
}

chrome.runtime.onInstalled.addListener(() => {
  void bootstrap();
});

chrome.runtime.onStartup.addListener(() => {
  void bootstrap();
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (!message || !message.type) {
    sendResponse({ ok: false, error: "invalid_message" });
    return false;
  }

  if (message.type === "ankita_popup_status") {
    Promise.resolve()
      .then(async () => {
        const activeTab = await getActiveTab();
        return {
          ok: true,
          connected: state.connected,
          bridgeBaseUrl: state.bridgeBaseUrl,
          clientId: state.clientId,
          lastError: state.lastError,
          activeTab: tabSummary(activeTab),
          sessions: Object.values(state.sessions),
          bridgeStatus: state.lastBridgeStatus,
        };
      })
      .then(sendResponse)
      .catch((error) => sendResponse({ ok: false, error: String(error.message || error) }));
    return true;
  }

  if (message.type === "ankita_popup_reconnect") {
    Promise.resolve()
      .then(async () => {
        await registerWithBridge(true);
        return { ok: true };
      })
      .then(sendResponse)
      .catch((error) => sendResponse({ ok: false, error: String(error.message || error) }));
    return true;
  }

  if (message.type === "ankita_popup_attach_active_tab") {
    Promise.resolve()
      .then(async () => {
        const sessionId = message.sessionId || randomId("browser");
        return handleStartSession({
          action: "start_session",
          session_id: sessionId,
          attach_mode: "active",
        });
      })
      .then(sendResponse)
      .catch((error) => sendResponse({ ok: false, error: String(error.message || error) }));
    return true;
  }

  sendResponse({ ok: false, error: `unsupported_message:${message.type}` });
  return false;
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "ankita-bridge-keepalive") {
    void bootstrap();
  }
});

void bootstrap();
