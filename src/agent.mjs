import os from "node:os";
import { specs, coreSpecs, specsFor, get, needsApproval, coreNames, CATEGORIES } from "../tools/index.mjs";
import { fetchWithRetry } from "./net.mjs";
import { c, preview, short, clip } from "./ui.mjs";
import { renderDiff } from "../tools/_diff.mjs";
import { capOutput } from "../tools/_shared.mjs";
import { trimMessages } from "./history.mjs";

const toolUi = { ...c, preview, short, clip };
toolUi.diff = (oldText, newText, opts = {}) => renderDiff(oldText, newText, { ui: toolUi, ...opts });

const MAX_TOOL_STEPS = 16;

export function buildSystemPrompt(config, cwd, project = null, mcpServers = []) {
  const today = new Date().toISOString().slice(0, 10);
  const shell =
    process.platform === "win32" ? "PowerShell 5.1 (so: no && chaining, use ; instead)" : "/bin/sh";

  return [
    `You are ${config.agentName}, a command-line coding assistant running on the user's machine.`,
    `The user's name is ${config.username}. Address them by name when it fits naturally.`,
    "",
    `Working directory: ${cwd}`,
    `Home directory: ${os.homedir()}`,
    `Platform: ${process.platform} · shell: ${shell}`,
    `Today: ${today}`,
    "",
    `You have these tools: ${coreNames().join(", ")}.`,
    "More tools are available but not loaded yet, because every schema costs context on every turn. " +
      "Call find_tools to load them when a task needs them - they become callable straight away. Groups:",
    ...CATEGORIES.map((group) => `  ${group.id}: ${group.tools.map((t) => t.name).join(", ")} - ${group.summary}`),
    "For anything time-sensitive or factual about the world, load `web` with find_tools and search " +
      "rather than guessing.",
    mcpServers.length
      ? "Connected MCP servers provide extra tools you can call directly, named mcp__<server>__<tool>:\n" +
        mcpServers.map((s) => `  ${s.id}: ${s.tools.join(", ")}`).join("\n")
      : "",
    "",
    "You are NOT confined to the working directory. Any absolute path works, and every path a tool " +
      "prints (including search results outside the working directory) is directly usable in your next " +
      "call — pass it back verbatim, never re-relativise it.",
    "When a tool fails, diagnose the cause and try again with a corrected path, quoting, or command " +
      "before reporting a problem. One failed attempt is not an answer.",
    "Do not ask the user to confirm things they already asked for, and do not ask permission to run " +
      "read-only discovery (searches, listings, reads) — just run it. Only ask when you truly need a " +
      "decision you cannot make yourself (e.g. which of two files to overwrite).",
    "Ground every claim in a tool result. Read a file before editing it.",
    "Prefer edit_file over rewriting whole files with write_file.",
    "Chain several tool calls when a task needs them, then summarise in one or two sentences.",
    "",
    "You are also a personal assistant. You can set up your own recurring work and track pages " +
      "that should not change silently (numbers like signups or logins). When the user asks for " +
      "something to happen regularly, or to be told when something changes, load the `automation` " +
      "group with find_tools and set it up instead of saying you cannot. Scheduled work runs in " +
      "`ankita --daemon`, so mention that if it is not already running.",
    project ? `\n${project}` : "",
    "Skip preamble and pleasantries. Report failures honestly instead of guessing.",
    config.systemExtra ? `\nAdditional instructions from the user:\n${config.systemExtra}` : "",
  ]
    .filter(Boolean)
    .join("\n");
}

export class Agent {
  constructor({
    client,
    config,
    confirm,
    print = console.log,
    write = (s) => process.stdout.write(s),
    project = "",
    projectId = null,
    deferTools = true,
    mcp = null,
  }) {
    this.client = client;
    this.config = config;
    this.confirm = confirm;
    this.print = print;
    this.write = write;
    this.ui = toolUi;

    this.model = config.model || null;
    this.useTools = config.tools;
    this.autoApprove = config.autoApprove;
    this.cwd = process.cwd();
    // Bounded block describing the active project, or "" when none is set.
    this.project = project || "";
    // Id of that project, so tools can tag what they create. Null when none.
    this.projectId = this.project ? projectId || null : null;
    this.abort = null;
    // activatedTools: deferred tool names find_tools has loaded this session.
    this.state = { todos: [], jobs: new Map(), activatedTools: new Set() };
    // One-shot agents (routines, briefings, alerts) always send everything:
    // there is no session to amortise a discovery round trip across.
    this.deferTools = deferTools !== false;
    // A reference, not ownership: the manager is process-level so every
    // freshAgent worker shares the same live server processes.
    this.mcp = mcp;
    this.contextWindow = config.contextWindow || 32768;
    this.sessionUsage = { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0, estimated_cost: 0 };
    this.turnUsage = { ...this.sessionUsage };
    this.messages = [
      { role: "system", content: buildSystemPrompt(config, this.cwd, this.project, this.mcp?.summaries() || []) },
    ];
  }

  clear() {
    this.messages = [
      {
        role: "system",
        content: buildSystemPrompt(this.config, this.cwd, this.project, this.mcp?.summaries() || []),
      },
    ];
  }

  rebase() {
    this.cwd = process.cwd();
    this.messages[0] = {
      role: "system",
      content: buildSystemPrompt(this.config, this.cwd, this.project, this.mcp?.summaries() || []),
    };
  }

  /**
   * Point the agent at a different project (or none) and rebuild the prompt.
   * `id` is the stable handle tools tag new routines/watches with; `block` is
   * the rendered text that goes into the system prompt.
   */
  setProject(block, id = null) {
    this.project = block || "";
    this.projectId = this.project ? id || null : null;
    this.rebase();
    return this;
  }

  /**
   * The tool specs to send right now.
   *
   * Core only until find_tools loads a group, unless this agent is a one-shot
   * worker. The saving is not just a shorter list for the model to read: the
   * budget below is computed from this, so a normal session gets far more
   * room for history.
   */
  currentSpecs() {
    if (!this.useTools) return [];

    // Which static branch applies is independent of MCP. A deferTools:false
    // worker returns the whole static catalog without ever consulting
    // activatedTools, so hanging MCP specs off that branch would make MCP
    // invisible to daemon workers - the opposite of what is wanted.
    let base;
    if (!this.deferTools) {
      base = specs;
    } else {
      const active = this.state?.activatedTools;
      base = active && active.size ? [...coreSpecs, ...specsFor([...active])] : coreSpecs;
    }

    const mcp = this.mcp ? this.mcp.specs() : [];
    return mcp.length ? [...base, ...mcp] : base;
  }

  /** Rebuild messages[0] so the model sees the current tool groups. */
  refreshPrompt() {
    if (!this.messages?.length) return this;
    this.messages[0] = {
      role: "system",
      content: buildSystemPrompt(this.config, this.cwd, this.project, this.mcp ? this.mcp.summaries() : []),
    };
    return this;
  }

  /** Drop old turns, never splitting an assistant tool_calls from its tool replies. */
  trimHistory(max) {
    // UTF-8 bytes are a conservative token upper bound; reserve output + tools.
    const available = this.contextWindow - (this.config.maxTokens || 4096) - 1024 -
      Buffer.byteLength(JSON.stringify(this.currentSpecs()));
    if (available < 512) throw new Error('Model context window is too small for the configured output and tools. Reduce MAX_TOKENS or disable tools.');
    this.messages = trimMessages(this.messages, max, available);
  }

  cancelled() {
    return this.abort?.signal.aborted === true;
  }

  cancel() {
    if (!this.abort) return false;
    this.abort.abort();
    return true;
  }

  recordUsage(usage, onUsage) {
    if (!usage) return;
    const normalized = {
      prompt_tokens: Math.max(0, Number(usage.prompt_tokens) || 0),
      completion_tokens: Math.max(0, Number(usage.completion_tokens) || 0),
    };
    normalized.total_tokens = Number(usage.total_tokens) || normalized.prompt_tokens + normalized.completion_tokens;
    normalized.estimated_cost = (normalized.prompt_tokens * (this.config.inputCostPerMillion || 0) +
      normalized.completion_tokens * (this.config.outputCostPerMillion || 0)) / 1e6;
    for (const key of Object.keys(normalized)) {
      this.turnUsage[key] += normalized[key];
      this.sessionUsage[key] += normalized[key];
    }
    onUsage?.({ ...normalized });
  }

  async streamTurn({ onDelta, onReasoning, onUsage } = {}) {
    const body = {
      model: this.model,
      messages: this.messages,
      stream: true,
      max_tokens: this.config.maxTokens || 4096,
      stream_options: { include_usage: true },
    };
    if (this.config.temperature != null) body.temperature = this.config.temperature;
    if (this.useTools) {
      body.tools = this.currentSpecs();
      body.tool_choice = "auto";
    }

    this.abort ??= new AbortController();
    const signal = this.abort.signal;

    const res = await fetchWithRetry(
      `${this.client.baseUrl}/chat/completions`,
      {
        method: "POST",
        headers: this.client.headers(true),
        body: JSON.stringify(body),
        signal,
      },
      { onRetry: (status, waitMs) => this.print(`  (rate limited ${status}, retrying in ${Math.round(waitMs / 1000)}s)`)}
    );

    if (!res.ok) {
      const text = await res.text();
      const err = new Error(`API error ${res.status}: ${text}`);
      err.status = res.status;
      throw err;
    }

    const ctype = res.headers.get("content-type") || "";
    if (ctype.includes("application/json")) {
      const data = await res.json();
      const msg = data.choices?.[0]?.message || {};
      if (msg.content) onDelta?.(msg.content);
      if (msg.reasoning_content || msg.reasoning_text) onReasoning?.(msg.reasoning_content || msg.reasoning_text);
      this.recordUsage(data.usage, onUsage);
      return { content: msg.content || "", toolCalls: msg.tool_calls || [] };
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let content = "";
    const acc = [];
    let finished = false;

    const consume = (json) => {
      this.recordUsage(json.usage, onUsage);
      if (json.choices?.[0]?.finish_reason) finished = true;
      const delta = json.choices?.[0]?.delta;
      if (!delta) return;
      if (delta.content) {
        content += delta.content;
        onDelta?.(delta.content);
      }
      if (delta.reasoning_content || delta.reasoning_text) onReasoning?.(delta.reasoning_content || delta.reasoning_text);
      for (const tc of delta.tool_calls || []) {
        const i = tc.index ?? 0;
        acc[i] ??= { id: "", type: "function", function: { name: "", arguments: "" } };
        if (tc.id) acc[i].id = tc.id;
        if (tc.function?.name && !acc[i].function.name) acc[i].function.name = tc.function.name;
        if (tc.function?.arguments) acc[i].function.arguments += tc.function.arguments;
      }
    };

    const consumeLine = (line) => {
      if (!line.startsWith('data:')) return;
      const payload = line.slice(5).trim();
      if (payload === '[DONE]') { finished = true; return; }
      if (!payload) return;
      consume(JSON.parse(payload));
    };
    try { while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let idx;
      while ((idx = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, idx).trim();
        buffer = buffer.slice(idx + 1);
        consumeLine(line);
      }
    }
    buffer += decoder.decode();
    if (buffer.trim()) consumeLine(buffer.trim());
    if (!finished) throw new Error('Response stream was cut off before completion.');
    } finally { reader.releaseLock(); }

    return { content, toolCalls: acc.filter(Boolean) };
  }

  /**
   * An MCP tool call: namespaced, resolved against the live connections, and
   * approved according to the server's own hints. Routed here before the local
   * registry is consulted, since no local tool starts with the prefix.
   */
  async runMcpToolCall(call) {
    const name = call.function.name;
    const found = this.mcp?.findTool(name);
    if (!found) return `Error: no connected MCP server provides "${name}".`;

    let args;
    try {
      args = call.function.arguments ? JSON.parse(call.function.arguments) : {};
    } catch (err) {
      return `Error: arguments were not valid JSON (${err.message}).`;
    }

    if (this.mcp.needsApproval(name) && !this.autoApprove) {
      const detail = this.mcp.approvalDetail(name, args);
      const ok = await this.confirm?.(name, detail);
      if (!ok) return "The user denied permission for this action. Do not retry it; ask what to do instead.";
    }

    try {
      return await this.mcp.callTool(name, args);
    } catch (err) {
      return `Error while running ${name}: ${err.message}`;
    }
  }

  async runToolCall(call) {
    if (String(call.function.name || "").startsWith("mcp__")) return this.runMcpToolCall(call);

    const tool = get(call.function.name);
    if (!tool) return `Error: unknown tool "${call.function.name}".`;

    let args;
    try {
      args = call.function.arguments ? JSON.parse(call.function.arguments) : {};
    } catch (err) {
      return `Error: arguments were not valid JSON (${err.message}).`;
    }

    const ctx = {
      cwd: this.cwd,
      config: this.config,
      ui: this.ui,
      width: process.stdout.columns || 80,
      signal: this.abort?.signal,
      state: this.state,
      // Lets the schedule/watch tools default a new entry to the active project.
      projectId: this.projectId,
    };

    const budget = this.config.maxToolChars > 0 ? this.config.maxToolChars : 65536;
    try {
      if (this.cancelled()) return 'Action cancelled by user.';
      if (needsApproval(tool.name) && !this.autoApprove) {
        // A tool may declare approval() and return nothing for the harmless
        // half of its actions (mcp_manage: listing is fine, starting a
        // third-party process is not). Falsy means "no gate", not "unset".
        const detail = tool.approval ? await tool.approval(args, ctx, this.ui) : JSON.stringify(args, null, 2);
        if (detail) {
          const ok = await this.confirm?.(tool.name, detail);
          if (!ok) return "The user denied permission for this action. Do not retry it; ask what to do instead.";
        }
      }
      if (this.cancelled()) return 'Action cancelled by user.';
      return capOutput(await tool.run(args, ctx), budget);
    } catch (err) {
      return `Error while running ${tool.name}: ${err.message}`;
    }
  }

  /**
   * Sends `text` and drives the tool-calling loop until the model replies
   * without requesting a tool. Returns the final assistant text.
   */
  async send(text, { onDelta, onReasoning, onUsage, onToolCall, onToolResult, onMessageStart, onMessageEnd } = {}) {
    this.abort = new AbortController();
    this.turnUsage = { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0, estimated_cost: 0 };
    if (text !== null) this.messages.push({ role: "user", content: text });

    for (let step = 0; step < MAX_TOOL_STEPS; step++) {
      this.trimHistory(this.config.historyMessages ?? this.config.historyLines);
      onMessageStart?.();
      let content, toolCalls;
      let partial = '';
      try {
        ({ content, toolCalls } = await this.streamTurn({
          onDelta: d => { partial += d; onDelta?.(d); }, onReasoning, onUsage,
        }));
      } catch (err) {
        if (partial) this.messages.push({ role: 'assistant', content: partial + '\n[This response was interrupted and cut off. Continue only when requested.]' });
        throw err;
      } finally {
        onMessageEnd?.();
      }

      const assistant = { role: "assistant", content: content || null };
      if (toolCalls.length) assistant.tool_calls = toolCalls;
      this.messages.push(assistant);

      if (!toolCalls.length) {
        this.trimHistory(this.config.historyMessages ?? this.config.historyLines);
        return content;
      }

      const budget = this.config.maxToolChars > 0 ? this.config.maxToolChars : 65536;
      const run = async (call) => {
        onToolCall?.(call);
        const result = await this.runToolCall(call);
        onToolResult?.(call, result);
        return { role: "tool", tool_call_id: call.id, content: capOutput(result, budget) };
      };
      // Mutations are barriers: only contiguous read-only calls overlap.
      for (let i = 0; i < toolCalls.length;) {
        if (get(toolCalls[i].function.name)?.readOnly === true) {
          const batch = [];
          while (i < toolCalls.length && get(toolCalls[i].function.name)?.readOnly === true) batch.push(toolCalls[i++]);
          this.messages.push(...await Promise.all(batch.map(run)));
        } else this.messages.push(await run(toolCalls[i++]));
      }

      if (this.cancelled()) {
        this.messages.push({ role: "user", content: "(previous action was cancelled by the user)" });
        return null;
      }
    }

    const stopped = '(stopped: too many tool calls in a row)';
    this.messages.push({ role: 'assistant', content: stopped });
    onDelta?.(stopped);
    this.trimHistory(this.config.historyMessages ?? this.config.historyLines);
    return stopped;
  }
}
