import os from "node:os";
import { ProfileStore } from './profile.mjs';
import fs from 'node:fs';
import { PROFILE_FILE, PROJECTS_FILE } from './config.mjs';
import { ProjectStore } from './projects.mjs';
import { randomUUID } from 'node:crypto';
import { personalMemoryContext, withMemoryContext } from './memory-context.mjs';
import { specs, coreSpecs, specsFor, get, needsApproval, coreNames, CATEGORIES } from "../tools/index.mjs";
import { fetchWithRetry } from "./net.mjs";
import { c, preview, short, clip } from "./ui.mjs";
import { renderDiff } from "../tools/_diff.mjs";
import { capOutput } from "../tools/_shared.mjs";
import { trimMessages } from "./history.mjs";

const toolUi = { ...c, preview, short, clip };
toolUi.diff = (oldText, newText, opts = {}) => renderDiff(oldText, newText, { ui: toolUi, ...opts });

const MAX_TOOL_STEPS = 16;

/**
 * How connected MCP servers are described to the model.
 *
 * A small server's tools are already in the request, so it just lists them. A
 * large one (Playwright is 25 tools) is held back to protect the context
 * window, so the model is told it exists and what to call to load it - and
 * explicitly that its tools are NOT callable yet, or it will try anyway.
 */
/**
 * Browser automation has failure modes that read as tool bugs and are not.
 * Observed live on YouTube: a CSS selector that never matched, then a ref
 * harvested from browser_find and reused three times after it had gone stale,
 * each attempt costing a full round trip. None of that is discoverable from
 * the tool schemas, so it is worth three lines.
 */
const BROWSER_HINTS = [
  "Browser tools: prefer navigating straight to a URL - put the search terms in the query string " +
    "(youtube.com/results?search_query=...) - over typing into a site's own search box.",
  "Refs like [ref=e12] come from browser_snapshot and go stale on navigation or any page change. " +
    "Take a fresh snapshot before each interaction, and never retry a ref that just failed.",
  "To read something off a page, browser_evaluate with one small expression is far more reliable " +
    "than parsing a snapshot.",
];

function isBrowserServer(server) {
  const tools = server?.tools || [];
  return tools.includes("browser_snapshot") && tools.some((t) => t.startsWith("browser_"));
}

export function mcpPromptLines(mcpServers = []) {
  if (!mcpServers.length) return [];
  const loaded = mcpServers.filter((s) => !s.deferred);
  const held = mcpServers.filter((s) => s.deferred);
  const lines = [];

  if (mcpServers.some(isBrowserServer)) lines.push(...BROWSER_HINTS);

  if (loaded.length) {
    lines.push(
      "Connected MCP servers provide extra tools you can call directly, named mcp__<server>__<tool>:",
      ...loaded.map((s) => `  ${s.id}: ${s.tools.join(", ")}`)
    );
  }
  if (held.length) {
    lines.push(
      "These MCP servers are connected, but their tool lists are large so they are NOT loaded yet:",
      ...held.map((s) => `  ${s.id}: ${s.tools.length} tool(s) - e.g. ${s.tools.slice(0, 4).join(", ")}`),
      `Call find_tools with the server name (e.g. find_tools("${held[0].id}")) to load one. Do not try ` +
        "to call mcp__ tools from those servers before doing so."
    );
  }
  return lines;
}

export function buildSystemPrompt(config, cwd, project = null, mcpServers = [], personal = '') {
  const today = new Date().toISOString().slice(0, 10);
  const shell =
    process.platform === "win32" ? "PowerShell 5.1 (so: no && chaining, use ; instead)" : "/bin/sh";

  return [
    `You are ${config.agentName}, a coding and personal assistant running on the user's machine.`,
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
    ...CATEGORIES.filter(group => !group.alwaysOn).map((group) => `  ${group.id}: ${group.tools.map((t) => t.name).join(", ")} - ${group.summary}`),
    "For anything time-sensitive or factual about the world, load `web` with find_tools and search " +
      "rather than guessing.",
    ...mcpPromptLines(mcpServers),
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
    "A zero exit code is not proof anything happened. A silent command - no output, no file " +
      "written, no value returned - tells you it did not crash, not that it worked; a browser " +
      "or GUI action printing nothing is unverified, so say it launched but you could not " +
      "confirm the result, rather than asserting success. When you need to know something " +
      "actually happened, prefer a tool whose result you can read (page content, a diff, a " +
      "returned value) over one that reports nothing.",
    "If you need a capability you do not have - driving a browser, querying a specific service - " +
      'search the MCP registry (find_tools, then mcp_manage action="search") and ask the user ' +
      "before installing, instead of guessing at shell commands for an external program.",
    "Prefer edit_file over rewriting whole files with write_file.",
    "Chain several tool calls when a task needs them, then summarise in one or two sentences.",
    "",
    "You are also a personal assistant. You can set up your own recurring work and track pages " +
      "that should not change silently (numbers like signups or logins). When the user asks for " +
      "something to happen regularly, or to be told when something changes, load the `automation` " +
      "group with find_tools and set it up instead of saying you cannot. Scheduled work runs in " +
      "`ankita --daemon`, so mention that if it is not already running.",
    project ? `\n${project}` : "",
    "Personal memory tools remember/recall are directly available; no find_tools needed. Before personal questions " +
      "or advice shaped by interests, preferences or circumstances, consult recalled personal context. " +
      "The runtime retrieves bounded candidates locally; use them when relevant and call recall(project=personal) " +
      "only when you need more facts/detail. Do not repeat a lookup already answered by this context. Check BEFORE " +
      "asking users to repeat personal details or claiming none are saved. Unpinned facts are outside this prompt, " +
      "not forgotten. Interpret candidates by meaning; rephrase, browse or paginate on inconclusive searches. " +
      "Recall past project context too. remember(action=list) lists personal facts; distinguish facts from assumptions.",
    "Use remember for clear lasting personal facts/preferences, especially when asked or when the user answers " +
      "something you offered to save. Skip small talk, guesses and temporary states. Read before correcting facts. " +
      "Never claim saved, updated or forgotten without a successful tool result. always=true is only for instructions " +
      "meant to apply every turn; other facts are recalled on demand. Project facts belong in project_memory.",
    personal,
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
    journal = null,
  }) {
    this.client = client;
    this.journal = journal;
    this.memoryContext = null;
    this.journalComplete = Boolean(journal) && config.memoryConsolidation !== false;
    this.sessionId = randomUUID();
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
      { role: "system", content: buildSystemPrompt(config, this.cwd, this.project, this.mcp?.summaries() || [], this.personalBlock()) },
    ];
  }

  clear() {
    this.messages = [
      {
        role: "system",
        content: buildSystemPrompt(this.config, this.cwd, this.project, this.mcp?.summaries() || [], this.personalBlock()),
      },
    ];
  }

  rebase() {
    this.cwd = process.cwd();
    this.messages[0] = {
      role: "system",
      content: buildSystemPrompt(this.config, this.cwd, this.project, this.mcp?.summaries() || [], this.personalBlock()),
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
    if (this.projectId) this.turnProjects?.add(this.projectId);
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

    // MCP servers follow the same rule as the built-ins: small ones are always
    // in the request, large ones only once find_tools has loaded them by id.
    // specsFor() above ignores these ids (it only knows deferred static names),
    // so a server id sitting in activatedTools is inert until here.
    if (!this.mcp) return base;
    const active = this.state?.activatedTools;
    const wanted = new Set(this.mcp.alwaysOnIds());
    if (active && active.size) {
      for (const entry of active) if (this.mcp.has(entry)) wanted.add(String(entry));
    }
    const mcp = wanted.size ? this.mcp.specs({ only: wanted }) : [];
    return mcp.length ? [...base, ...mcp] : base;
  }

  /** Rebuild messages[0] so the model sees the current tool groups. */
  refreshPrompt() {
    if (!this.messages?.length) return this;
    this.messages[0] = {
      role: "system",
      content: buildSystemPrompt(this.config, this.cwd, this.project, this.mcp ? this.mcp.summaries() : [], this.personalBlock()),
    };
    return this;
  }

  personalBlock() {
    try {
      const stat = fs.statSync(PROFILE_FILE);
      const version = `${stat.mtimeMs}:${stat.ctimeMs}:${stat.size}`;
      if (this.profileCache?.version === version) return this.profileCache.block;
      const profile = new ProfileStore(PROFILE_FILE).load();
      const block = [profile.facts.length
        ? `Personal memory store: ${profile.facts.length} saved fact(s); only pins appear here. ` +
          'Call recall before personal recommendations or asking about interests/preferences.'
        : 'Personal memory store: no saved facts yet.', profile.promptBlock()].filter(Boolean).join('\n');
      this.profileCache = { version, block };
      return block;
    }
    catch { return ''; }
  }

  /** Drop old turns, never splitting an assistant tool_calls from its tool replies. */
  trimHistory(max) {
    // UTF-8 bytes are a conservative token upper bound; reserve output + tools.
    const available = this.contextWindow - (this.config.maxTokens || 4096) - 1024 -
      Buffer.byteLength(JSON.stringify(this.currentSpecs())) -
      (this.memoryContext ? Buffer.byteLength(JSON.stringify(this.memoryContext.messages)) : 0);
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
      messages: withMemoryContext(this.messages, this.memoryContext),
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
      // mcp_manage reloads through this, and find_tools loads a big server's
      // tools by name. Without it a tool-driven reload cannot reconnect.
      mcp: this.mcp,
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
      const result = await tool.run(args, ctx);
      if (tool.name === 'remember' && args.action !== 'list' && !String(result).startsWith('Error:')) this.memoryContext = null;
      if (tool.name === 'project' && ['add', 'use', 'archive', 'forget', 'update'].includes(args.action) && !String(result).startsWith('Error:')) {
        const projects = new ProjectStore(PROJECTS_FILE).load();
        if (!['add', 'use'].includes(args.action)) {
          const current = projects.find(this.projectId);
          projects.data.active = current && !current.archived ? current.id : null;
        }
        this.setProject(projects.promptBlock(), projects.activeId);
      }
      return capOutput(result, budget);
    } catch (err) {
      return `Error while running ${tool.name}: ${err.message}`;
    }
  }

  /**
   * Sends `text` and drives the tool-calling loop until the model replies
   * without requesting a tool. Returns the final assistant text.
   */
  async send(text, options = {}) {
    this.turnProjects = new Set(this.projectId ? [this.projectId] : []);
    this.memoryContext = this.useTools ? personalMemoryContext(text, this.config) : null;
    if (this.memoryContext) {
      try { options.onToolCall?.(this.memoryContext.call); } catch {}
      try { options.onToolResult?.(this.memoryContext.call, this.memoryContext.result); } catch {}
    }
    let reply;
    try { reply = await this.sendTurn(text, options); }
    catch (err) { this.journalComplete = false; throw err; }
    if (this.config.memoryConsolidation === false) this.journalComplete = false;
    if (this.journal && text !== null && this.config.memoryConsolidation !== false) {
      const projectId = this.turnProjects.size === 1 ? [...this.turnProjects][0] : null;
      try { this.journal({ text, reply, projectId, sessionId: this.sessionId }); }
      catch (err) { this.journalComplete = false; this.print(`Could not journal this turn: ${err.message}`); }
    }
    return reply;
  }

  async sendTurn(text, { onDelta, onReasoning, onUsage, onToolCall, onToolResult, onMessageStart, onMessageEnd } = {}) {
    this.abort = new AbortController();
    this.turnUsage = { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0, estimated_cost: 0 };
    if (text !== null) this.messages.push({ role: "user", content: text });

    for (let step = 0; step < MAX_TOOL_STEPS; step++) {
      this.refreshPrompt();
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

      // Exactly one reply per declared tool_call, whatever happens. The API
      // rejects the entire next request if any call is unanswered ("must be
      // followed by tool messages responding to each tool_call_id"), so one
      // thrown tool - or one throwing UI callback - would end the session
      // rather than just fail a step.
      const reply = (call, content) => ({ role: "tool", tool_call_id: call.id, content });

      const run = async (call) => {
        try {
          onToolCall?.(call);
        } catch {}
        let result;
        try {
          result = await this.runToolCall(call);
        } catch (err) {
          result = `Error while running ${call?.function?.name || "tool"}: ${err.message}`;
        }
        try {
          onToolResult?.(call, result);
        } catch {}
        try {
          return reply(call, capOutput(result, budget));
        } catch (err) {
          return reply(call, `Error: the result could not be formatted (${err.message}).`);
        }
      };

      // Mutations are barriers: only contiguous read-only calls overlap.
      for (let i = 0; i < toolCalls.length;) {
        if (this.cancelled()) {
          // Cancelling must stop the remaining work, and still answer every
          // call the assistant already declared, or the next turn is invalid.
          for (; i < toolCalls.length; i++) {
            this.messages.push(reply(toolCalls[i], "Not run: the user cancelled before this step."));
          }
          break;
        }
        if (get(toolCalls[i].function.name)?.readOnly === true) {
          const batch = [];
          while (i < toolCalls.length && get(toolCalls[i].function.name)?.readOnly === true) batch.push(toolCalls[i++]);
          this.messages.push(...await Promise.all(batch.map(run)));
        } else {
          this.messages.push(await run(toolCalls[i++]));
        }
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
