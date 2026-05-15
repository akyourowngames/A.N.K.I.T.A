"use client";

export type AssistantStreamEvent =
  | { type: "token"; content: string }
  | { type: "done"; session_id: string; reply: string }
  | { type: "error"; message: string };

export type AssistantStreamHandlers = {
  onToken: (content: string) => void;
  onDone: (sessionId: string, reply: string) => void;
  onError: (message: string) => void;
};

export type DashboardState = {
  ok: boolean;
  assistant: {
    name: string;
    model: string;
    streaming: boolean;
    tools: number;
  };
};

export async function streamAssistantReply(
  message: string,
  sessionId: string,
  handlers: AssistantStreamHandlers
) {
  const response = await fetch(`${apiBaseUrl()}/api/chat/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      message,
      session_id: sessionId
    })
  });

  if (!response.ok) {
    handlers.onError(`Assistant server returned ${response.status}.`);
    return;
  }

  if (!response.body) {
    handlers.onError("Assistant server did not open a stream.");
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const result = await reader.read();
    if (result.done) {
      break;
    }
    buffer += decoder.decode(result.value, { stream: true });
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() ?? "";
    for (const block of blocks) {
      dispatchBlock(block, handlers);
    }
  }

  if (buffer.trim()) {
    dispatchBlock(buffer, handlers);
  }
}

export async function fetchDashboardState(): Promise<DashboardState | null> {
  const response = await fetch(`${apiBaseUrl()}/api/dashboard`, { cache: "no-store" });
  if (!response.ok) {
    return null;
  }
  return (await response.json()) as DashboardState;
}

function dispatchBlock(block: string, handlers: AssistantStreamHandlers) {
  const lines = block.split("\n");
  let data = "";
  for (const line of lines) {
    if (line.startsWith("data:")) {
      data += line.slice(5).trimStart();
    }
  }
  if (!data) {
    return;
  }
  try {
    const event = JSON.parse(data) as AssistantStreamEvent;
    if (event.type === "token") {
      handlers.onToken(event.content);
      return;
    }
    if (event.type === "done") {
      handlers.onDone(event.session_id, event.reply);
      return;
    }
    if (event.type === "error") {
      handlers.onError(event.message);
    }
  } catch {
    handlers.onError("Assistant stream sent malformed data.");
  }
}

function apiBaseUrl() {
  const configured = process.env.NEXT_PUBLIC_JARVIS_API_URL?.trim();
  if (configured) {
    return configured;
  }
  if (typeof window !== "undefined") {
    return `${window.location.protocol}//${window.location.hostname}:8000`;
  }
  return "http://localhost:8000";
}
