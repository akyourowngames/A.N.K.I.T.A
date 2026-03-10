async function sendMessage(message) {
  return chrome.runtime.sendMessage(message);
}

function renderStatus(status) {
  const bridgeUrl = document.getElementById("bridge-url");
  const bridgeStatus = document.getElementById("bridge-status");
  const clientId = document.getElementById("client-id");
  const activeTab = document.getElementById("active-tab");
  const sessions = document.getElementById("sessions");
  const lastError = document.getElementById("last-error");

  bridgeUrl.textContent = status.bridgeBaseUrl || "-";
  bridgeStatus.textContent = status.connected ? "connected" : "offline";
  bridgeStatus.className = `pill ${status.connected ? "online" : "offline"}`;
  clientId.textContent = status.clientId || "-";

  if (status.activeTab) {
    activeTab.textContent = `${status.activeTab.title || "(untitled)"}\n${status.activeTab.url || ""}`;
  } else {
    activeTab.textContent = "No active tab";
  }

  if (Array.isArray(status.sessions) && status.sessions.length) {
    sessions.textContent = status.sessions
      .map((session) => `${session.session_id} -> ${session.title || session.url || session.tab_id}`)
      .join("\n");
  } else {
    sessions.textContent = "No sessions";
  }

  lastError.textContent = status.lastError || "None";
}

async function refreshStatus() {
  const status = await sendMessage({ type: "ankita_popup_status" });
  if (!status.ok) {
    throw new Error(status.error || "Failed to load popup status");
  }
  renderStatus(status);
}

async function reconnectBridge() {
  const response = await sendMessage({ type: "ankita_popup_reconnect" });
  if (!response.ok) {
    throw new Error(response.error || "Failed to reconnect bridge");
  }
  await refreshStatus();
}

async function attachActiveTab() {
  const response = await sendMessage({ type: "ankita_popup_attach_active_tab" });
  if (!response.ok) {
    throw new Error(response.error || "Failed to attach active tab");
  }
  await refreshStatus();
}

async function runAction(action) {
  try {
    await action();
  } catch (error) {
    document.getElementById("last-error").textContent = String(error.message || error);
  }
}

document.getElementById("refresh-btn").addEventListener("click", () => {
  void runAction(refreshStatus);
});

document.getElementById("reconnect-btn").addEventListener("click", () => {
  void runAction(reconnectBridge);
});

document.getElementById("attach-btn").addEventListener("click", () => {
  void runAction(attachActiveTab);
});

void refreshStatus();
