import os from "node:os";
import path from 'node:path';
import { ProfileStore } from '../memory/profile.mjs';
import fs from 'node:fs';
import { PROFILE_FILE, PROJECTS_FILE } from './config.mjs';
import { ProjectStore } from '../memory/projects.mjs';
import { randomUUID, createHash } from 'node:crypto';
import { personalMemoryContext, withMemoryContext } from '../memory/memory-context.mjs';
import { warmRecall } from '../../tools/personal/recall.mjs';
import { specs, coreSpecs, specsFor, get, needsApproval, isReadOnly, coreNames, categoryOfTool, CATEGORIES } from "../../tools/index.mjs";
import { fetchWithRetry } from "./net.mjs";
import { c, preview, short, clip } from "./ui.mjs";
import { renderDiff } from "../../tools/shared/_diff.mjs";
import { capOutput } from "../../tools/shared/_shared.mjs";
import { trimMessages } from "./history.mjs";
import { runFileToolInWorker } from '../tooling/tool-worker.mjs';
import { loadSkills, skillPromptLines } from './skills.mjs';
import { isToolFailure, verdictFor, verificationFooter } from './verify.mjs';

const toolUi = { ...c, preview, short, clip };
toolUi.diff = (oldText, newText, opts = {}) => renderDiff(oldText, newText, { ui: toolUi, ...opts });

// Consecutive tool rounds allowed for one user request before the runtime stops
// asking and has the model answer with what it has. This is a control-flow
// bound, not advice: the loop's own exit condition is "the model stopped asking
// for tools", so a model that never feels finished otherwise keeps researching
// until the budget is gone - observed live, which is what this exists to stop.
// Override per install with MAX_TOOL_STEPS.
export const MAX_TOOL_STEPS = 24;
export const MAX_TOOL_CALLS = 60;
export const MAX_WEB_SEARCHES_PER_TURN = 6;
// How many rounds may repeat one identical call (same tool, same arguments)
// before that repetition counts as no progress and the loop stops. Three allows
// a legitimate re-read after a file changed; it does not allow a cycle. Counted
// once per round, so several identical parallel calls are a batching choice and
// not a loop.
export const MAX_REPEAT_CALLS = 3;

// Reserved per request on top of the output cap: protocol overhead plus a floor
// of history. If even the core tools cannot fit inside this, the request is
// genuinely impossible and trimHistory says so.
const CONTEXT_OVERHEAD_BYTES = 1024;
const MIN_HISTORY_BYTES = 512;

/**
 * Argument identity for the repeat guard. Key order is not a change, so the
 * arguments are re-serialised in sorted key order; anything unparseable falls
 * back to the raw string, which still catches a verbatim repeat.
 */
function normalizeArgs(raw) {
  try {
    const value = JSON.parse(raw || '{}');
    const stable = (item, field = '') => {
      if (Array.isArray(item)) return item.map(value => stable(value));
      if (item && typeof item === 'object') return Object.fromEntries(Object.keys(item).sort().map(key => [key, stable(item[key], key)]));
      if (typeof item === 'string' && ['path', 'directory', 'destination'].includes(field)) return path.normalize(item);
      return item;
    };
    return JSON.stringify(stable(value));
  } catch {
    return String(raw ?? '');
  }
}

/** One tool call's identity: the same tool with the same arguments. */
function callSignature(call) {
  return `${call?.function?.name || ''}(${normalizeArgs(call?.function?.arguments)})`;
}

function traceAgent(event, config) {
  if (config?.agentDebug || process.env.ANKITA_AGENT_DEBUG === '1') console.error(JSON.stringify({ at: new Date().toISOString(), ...event }));
}

/**
 * Turn a prompt and its attachments into the content an OpenAI-compatible
 * provider expects.
 *
 * Images become `image_url` parts (the shape every multimodal provider
 * understands). Documents and text are folded into the prompt as labelled
 * blocks, so any model can read a file the user dropped in even without native
 * document support. With no attachments the plain string form is kept, because
 * some providers reject the array shape even for a single text part.
 */
export function buildUserContent(text, attachments) {
  const items = Array.isArray(attachments) ? attachments.filter(Boolean) : [];
  if (!items.length) return text;
  const parts = [];
  const body = String(text || '').trim();
  if (body) parts.push({ type: 'text', text: body });
  for (const file of items) {
    // A document the window could not turn into text (a scan): send the pages
    // it rendered as images so a vision model can read them directly.
    for (const page of file?.images || []) {
      if (/^data:image\//i.test(page)) parts.push({ type: 'image_url', image_url: { url: page } });
    }
    if (file?.dataUrl && /^data:image\//i.test(file.dataUrl)) {
      parts.push({ type: 'image_url', image_url: { url: file.dataUrl } });
      continue;
    }
    if (typeof file?.text === 'string' && file.text) {
      const label = file.name ? `Attached file: ${file.name}` : 'Attached file';
      const note = file.truncated ? '\n[truncated to fit the context window]' : '';
      parts.push({ type: 'text', text: `${label}\n\`\`\`\n${file.text}${note}\n\`\`\`` });
    }
  }
  if (!parts.length) return text;
  return parts;
}

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
  if (mcpServers.some((s) => s.id === "composio")) {
    lines.push("Connected apps (Gmail, Slack, and more) are reachable through the composio tools: find one with COMPOSIO_SEARCH_TOOLS, read its arguments with COMPOSIO_GET_TOOL_SCHEMAS, run it with COMPOSIO_MULTI_EXECUTE_TOOL, and manage accounts with COMPOSIO_MANAGE_CONNECTIONS.");
  }

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

export function buildSystemPrompt(config, cwd, project = null, mcpServers = [], personal = '', skillLines = [], includeSkills = true) {
  const today = new Date().toISOString().slice(0, 10);
  // The prompt states the same bound the loop enforces, so a model that is about
  // to be cut off knows to summarise rather than stall mid-investigation.
  const toolRounds = config?.maxToolSteps > 0 ? config.maxToolSteps : MAX_TOOL_STEPS;
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
    `You have these tools: ${coreNames().filter(name => includeSkills || name !== 'skill').join(", ")}.`,
    "More tools are available but not loaded yet, because every schema costs context on every turn. " +
      "Call find_tools to load them when a task needs them - they become callable straight away. Groups:",
    ...CATEGORIES.filter(group => !group.alwaysOn && (includeSkills || group.id !== 'skills')).map((group) => `  ${group.id}: ${group.tools.map((t) => t.name).join(", ")} - ${group.summary}`),
    "For anything time-sensitive or factual about the world, load `web` with find_tools and search " +
      "rather than guessing.",
    ...mcpPromptLines(mcpServers),
    ...(skillLines.length ? ['', ...skillLines] : []),
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
    "A tool result marked [UNVERIFIED] means a side effect is unconfirmed. Do not tell the user it succeeded. " +
      "Run a read-back check (fetch the sent message, open the created file, or list the directory) and confirm " +
      "from that result, or say plainly what remains unconfirmed. An attachment, upload, or delivery claim " +
      "requires that evidence even when the action call returned no error.",
    "If you need a capability you do not have - driving a browser, querying a specific service - " +
      'search the MCP registry (find_tools, then mcp_manage action="search") and ask the user ' +
      "before installing, instead of guessing at shell commands for an external program.",
    "Prefer edit_file over rewriting whole files with write_file.",
    "Use apply_patch for unified multi-file changes. Use http_request for APIs and find_tools(git) for Git actions.",
    "Commands return a live job after a short wait. This is not failure or completion. Continue independent work; " +
      "use job_status for incremental output and job_input for stdin. Do not repeatedly wait for servers/watchers to exit. " +
      "Tell the user the job ID and let the conversation continue. Wait only when the next step needs that command's result.",
    "Chain several tool calls when a task needs them, then summarise in one or two sentences.",
    `Use at most ${MAX_WEB_SEARCHES_PER_TURN} web_search calls per user request. Search broad terms first, read the strongest sources, then answer. The runtime enforces this limit.`,
    "",
    "TOOL EXECUTION POLICY",
    "You are an action-oriented assistant, not an autonomous researcher. Before every tool call, ask yourself: " +
      "(1) is this necessary to answer the request, (2) do I already have enough information, (3) will the result " +
      "materially change my answer. If you already have enough, stop calling tools and answer now.",
    "Once the thing the user asked for is done, summarise it and stop. Do not keep looking for more context after " +
      "the task is complete, do not investigate your own investigation, and never re-run a call with the same " +
      "arguments expecting a different result - if a call did not produce what you needed, change the approach or " +
      "report the limitation.",
    "Do not inspect editor, agent or operating-system state that the request did not ask about, and do not wander " +
      "into unrelated files or projects. Investigate what the request implies, not whatever else happens to be reachable.",
    "If you cannot determine something, say so plainly rather than investigating indefinitely, and name what remains " +
      "uncertain when you stop.",
    `The runtime stops the loop after ${toolRounds} consecutive tool rounds in one request, and sooner if you repeat an ` +
      "identical call. When that happens you are asked to answer anyway: report what you completed and what is still " +
      "unknown, instead of starting more research.",
    "",
    "You are also a personal assistant. You can set up your own recurring work and track pages " +
      "that should not change silently (numbers like signups or logins). When the user asks for " +
      "something to happen regularly, or to be told when something changes, load the `automation` " +
      "group with find_tools and set it up instead of saying you cannot. Scheduled work runs in " +
      "`ankita --daemon`, so mention that if it is not already running.",
    project ? `\n${project}` : "",
    "Personal memory tools remember/recall are directly available; no find_tools needed. Before personal questions " +
      "or advice shaped by interests, preferences or circumstances, consult recalled personal context. " +
      "The runtime retrieves bounded memory candidates; use them when relevant and call recall(project=personal) " +
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
  availableSkills() {
    return this.skillsEnabled ? loadSkills().filter(skill => !this.disabledSkills.has(skill.name)) : [];
  }

  constructor({
    client,
    config,
    confirm,
    print = console.log,
    write = (s) => process.stdout.write(s),
    project = "",
    projectId = null,
    workspacePath = null,
    deferTools = true,
    skillsEnabled = false,
    disabledSkills = [],
    mcp = null,
    journal = null,
    // Optional { client, model }: the primary handles chat and the first tool
    // decision; once a turn uses a tool, this model runs the rest of the loop.
    tool = null,
  }) {
    this.client = client;
    this.tool = tool && tool.client && tool.model ? tool : null;
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
    this.workspacePath = workspacePath;
    this.cwd = workspacePath || process.cwd();
    // Bounded block describing the active project, or "" when none is set.
    this.project = project || "";
    // Id of that project, so tools can tag what they create. Null when none.
    this.projectId = this.project ? projectId || null : null;
    this.abort = null;
    // activatedTools: deferred tool names find_tools has loaded this session.
    this.state = { todos: [], jobs: new Map(), activatedTools: new Set() };
    this.searchesThisTurn = 0;
    // Signatures of this request's tool calls, for the no-progress guard. Keyed
    // by callSignature(), valued { name, count }.
    this.repeatsThisTurn = new Map();
    // Distinct tools run this request, so a stopped turn can say what it did.
    this.ranThisTurn = [];
    // One-shot agents (routines, briefings, alerts) always send everything:
    // there is no session to amortise a discovery round trip across.
    this.deferTools = deferTools !== false;
    this.skillsEnabled = skillsEnabled !== false;
    this.disabledSkills = new Set(disabledSkills);
    // A reference, not ownership: the manager is process-level so every
    // freshAgent worker shares the same live server processes.
    this.mcp = mcp;
    this.contextWindow = config.contextWindow || 32768;
    this.sessionUsage = { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0, estimated_cost: 0 };
    this.turnUsage = { ...this.sessionUsage };
    this.toolLoopUsed = false;
    this.replyModel = null;
    this.skillLines = skillPromptLines(this.availableSkills());
    this.messages = [
      { role: "system", content: buildSystemPrompt(config, this.cwd, this.project, this.mcp?.summaries() || [], this.personalBlock(), this.skillLines, this.availableSkills().length > 0) },
    ];
    if (this.useTools) void warmRecall({ config });
  }

  clear() {
    this.skillLines = skillPromptLines(this.availableSkills());
    this.messages = [
      {
        role: "system",
        content: buildSystemPrompt(this.config, this.cwd, this.project, this.mcp?.summaries() || [], this.personalBlock(), this.skillLines, this.availableSkills().length > 0),
      },
    ];
  }

  rebase() {
    this.cwd = this.workspacePath || process.cwd();
    this.skillLines = skillPromptLines(this.availableSkills());
    this.messages[0] = {
      role: "system",
      content: buildSystemPrompt(this.config, this.cwd, this.project, this.mcp?.summaries() || [], this.personalBlock(), this.skillLines, this.availableSkills().length > 0),
    };
  }

  /**
   * Point the agent at a different project (or none) and rebuild the prompt.
   * `id` is the stable handle tools tag new routines/watches with; `block` is
   * the rendered text that goes into the system prompt.
   */
  setProject(block, id = null, workspacePath = null) {
    this.project = block || "";
    this.projectId = this.project ? id || null : null;
    this.workspacePath = workspacePath;
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
    const { core, optional } = this.specParts();
    const budget = this.toolBudgetBytes();
    if (budget === Infinity) return [...core, ...optional.flatMap((group) => group.specs)];

    // Core always ships. Loaded groups are added whole while they fit; one that
    // does not is skipped rather than half-sent, because the model was told the
    // whole group is callable. Skipping is graceful degradation: a small window
    // or a long memory recall costs some tools, never the whole turn.
    let used = Buffer.byteLength(JSON.stringify(core));
    const kept = [];
    for (const group of optional) {
      const size = Buffer.byteLength(JSON.stringify(group.specs));
      if (used + size > budget) continue;
      used += size;
      kept.push(...group.specs);
    }
    return [...core, ...kept];
  }

  /**
   * The tool set split into the part that always ships and the on-demand part,
   * the latter grouped by category or MCP server so a group can be dropped
   * whole. A deferTools:false worker keeps its full catalog in core.
   */
  specParts() {
    if (!this.useTools) return { core: [], optional: [] };
    const active = this.state?.activatedTools;
    const names = active && active.size ? [...active] : [];

    let core = this.deferTools ? coreSpecs : specs;
    if (!this.availableSkills().length) core = core.filter(spec => spec.function?.name !== 'skill');
    let optional = [];

    if (this.deferTools && names.length) {
      // specsFor() only knows deferred static names; group them by category so
      // a family loads or drops together.
      const groups = new Map();
      for (const spec of specsFor(names)) {
        const id = categoryOfTool.get(spec.function?.name) || spec.function?.name;
        if (!groups.has(id)) groups.set(id, []);
        groups.get(id).push(spec);
      }
      optional = [...groups].map(([id, groupSpecs]) => ({ id, specs: groupSpecs }));
    }

    if (this.searchesThisTurn >= MAX_WEB_SEARCHES_PER_TURN) {
      const keep = (spec) => spec.function?.name !== 'web_search';
      core = core.filter(keep);
      optional = optional
        .map((group) => ({ ...group, specs: group.specs.filter(keep) }))
        .filter((group) => group.specs.length);
    }

    // MCP servers follow the same rule as the built-ins: small ones are always
    // in the request, large ones only once find_tools has loaded them by id.
    // specsFor() above ignores these ids, so a server id in activatedTools is
    // inert until here.
    if (this.mcp) {
      const always = new Set(this.mcp.alwaysOnIds());
      if (always.size) core = [...core, ...this.mcp.specs({ only: always })];
      for (const entry of names) {
        const id = String(entry);
        if (!this.mcp.has(id) || always.has(id)) continue;
        const groupSpecs = this.mcp.specs({ only: new Set([id]) });
        if (groupSpecs.length) optional.push({ id, specs: groupSpecs });
      }
    }

    return { core, optional };
  }

  /**
   * How many bytes to hold back for the model's reply. An explicit MAX_TOKENS is
   * a deliberate cap and wins. The default is only a guess - no max_tokens is
   * even sent - so it must not starve a small window: reserve at most a quarter.
   */
  outputReserve() {
    const cap = this.config?.maxTokens || 4096;
    if (this.config?.maxTokensExplicit) return cap;
    const window = Number(this.contextWindow);
    if (!Number.isFinite(window) || window <= 0) return cap;
    return Math.min(cap, Math.max(256, Math.floor(window / 4)));
  }

  /** Bytes left for tool schemas once output, overhead and memory are reserved. */
  toolBudgetBytes() {
    const window = Number(this.contextWindow);
    if (!Number.isFinite(window) || window <= 0) return Infinity;
    const memory = this.memoryContext ? Buffer.byteLength(JSON.stringify(this.memoryContext.messages)) : 0;
    return window - this.outputReserve() - CONTEXT_OVERHEAD_BYTES - MIN_HISTORY_BYTES - memory;
  }

  /** Rebuild messages[0] so the model sees the current tool groups. */
  refreshPrompt() {
    if (!this.messages?.length) return this;
    this.skillLines = skillPromptLines(this.availableSkills());
    const todos = Array.isArray(this.state?.todos) ? this.state.todos : [];
    const checklist = todos.length ? '\nCurrent session checklist (stable IDs):\n' +
      capOutput(todos.map(item => `${item.id} ${item.content} ${item.status}`).join('\n'), 3000) +
      '\nBefore your final reply, use write_todos to mark work actually completed as completed. ' +
      'Leave unfinished work pending or in_progress; do not mark it completed without evidence.' : '';
    this.messages[0] = {
      role: "system",
      content: buildSystemPrompt(this.config, this.cwd, this.project, this.mcp ? this.mcp.summaries() : [], this.personalBlock(), this.skillLines, this.availableSkills().length > 0) + checklist,
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
    // currentSpecs() has already shed on-demand groups that do not fit, so this
    // only throws when even the core tools cannot share the window.
    const available = this.contextWindow - this.outputReserve() - CONTEXT_OVERHEAD_BYTES -
      Buffer.byteLength(JSON.stringify(this.currentSpecs())) -
      (this.memoryContext ? Buffer.byteLength(JSON.stringify(this.memoryContext.messages)) : 0);
    if (available < MIN_HISTORY_BYTES) throw new Error('Model context window is too small for the configured output and tools. Reduce MAX_TOKENS or disable tools.');
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

  /**
   * Records one tool call and returns its running count for this request.
   *
   * The guard lives on the loop, not on runToolCall, because runToolCall is the
   * seam callers and tests replace - a guard there could be stubbed away. This is
   * the single counter both the advisory note and the hard stop read.
   */
  noteRepeat(call) {
    const signature = callSignature(call);
    const entry = this.repeatsThisTurn.get(signature) ||
      { name: call?.function?.name || 'tool', signature, count: 0 };
    entry.count += 1;
    this.repeatsThisTurn.set(signature, entry);
    return entry;
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

  async streamTurn({ onDelta, onReasoning, onUsage, client = this.client, model = this.model, useTools = this.useTools, fallback = null } = {}) {
    this.abort ??= new AbortController();
    const signal = this.abort.signal;

    const request = (cli, mdl, retries) => {
      const body = {
        model: mdl,
        messages: withMemoryContext(this.messages, this.memoryContext),
        stream: true,
        stream_options: { include_usage: true },
      };
      // Only cap the output when the user asked for it; otherwise let the
      // model/provider decide the reply length.
      if (this.config.maxTokensExplicit) body.max_tokens = this.config.maxTokens;
      if (this.config.temperature != null) body.temperature = this.config.temperature;
      if (useTools) {
        body.tools = this.currentSpecs();
        body.tool_choice = "auto";
      }
      return fetchWithRetry(
        `${cli.baseUrl}/chat/completions`,
        {
          method: "POST",
          headers: cli.headers(true),
          body: JSON.stringify(body),
          signal,
        },
        { retries, onRetry: (status, waitMs) => this.print(`  (rate limited ${status}, retrying in ${Math.round(waitMs / 1000)}s)`) }
      );
    };

    // With a fallback available, do not sit out the primary's whole backoff:
    // fail fast so a rate limit switches models instead of stalling the turn.
    const swap = fallback && fallback.client && fallback.model ? fallback : null;
    let served = model;
    let res;
    try {
      res = await request(client, model, swap ? 0 : 3);
    } catch (err) {
      if (!swap || err.name === "AbortError") throw err;
      this.print(`  (${String(err.message).slice(0, 60)} - using ${swap.model})`);
      served = swap.model;
      res = await request(swap.client, swap.model, 3);
    }
    // Rate limit (429), payload too large for the model's per-minute token
    // budget (413), and server errors all mean "this provider cannot take this
    // request right now" - switch models rather than end the turn.
    if (swap && !res.ok && (res.status === 429 || res.status === 413 || res.status >= 500)) {
      try {
        await res.body?.cancel();
      } catch {}
      this.print(`  (${res.status === 413 ? "request too large" : `rate limited ${res.status}`} - using ${swap.model})`);
      served = swap.model;
      res = await request(swap.client, swap.model, 3);
    }

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
      return { content: msg.content || "", toolCalls: msg.tool_calls || [], model: served };
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

    return { content, toolCalls: acc.filter(Boolean), model: served };
  }

  /**
   * An MCP tool call: namespaced, resolved against the live connections, and
   * approved according to the server's own hints. Routed here before the local
   * registry is consulted, since no local tool starts with the prefix.
   */
  async runMcpToolCall(call, parsedArgs) {
    const name = call.function.name;
    const found = this.mcp?.findTool(name);
    if (!found) return `Error: no connected MCP server provides "${name}".`;

    let args = parsedArgs;
    try {
      args ??= call.function.arguments ? JSON.parse(call.function.arguments) : {};
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

  async runToolCall(call, parsedArgs) {
    if (String(call.function.name || "").startsWith("mcp__")) return this.runMcpToolCall(call, parsedArgs);

    if (call.function.name === 'skill' && !this.skillsEnabled) return 'Error: skills are available only in interactive chats.';

    const tool = get(call.function.name);
    if (!tool) return `Error: unknown tool "${call.function.name}".`;

    let args = parsedArgs;
    try {
      args ??= call.function.arguments ? JSON.parse(call.function.arguments) : {};
    } catch (err) {
      return `Error: arguments were not valid JSON (${err.message}).`;
    }

    if (call.function.name === 'skill' && this.disabledSkills.has(String(args?.name || '').trim().toLowerCase())) {
      return `Error: skill "${args.name}" is disabled in Plugins > Skills.`;
    }

    if (tool.name === 'web_search') {
      if (this.searchesThisTurn >= MAX_WEB_SEARCHES_PER_TURN) {
        return `Search limit reached (${MAX_WEB_SEARCHES_PER_TURN} web searches for this request). Use the results already gathered and answer the user; do not try another search tool for the same query.`;
      }
      this.searchesThisTurn++;
    }

    const ctx = {
      cwd: this.cwd,
      config: this.config,
      ui: this.ui,
      width: process.stdout.columns || 80,
      signal: this.abort?.signal,
      state: this.state,
      skillsEnabled: this.availableSkills().length > 0,
      disabledSkills: this.disabledSkills,
      // Lets the schedule/watch tools default a new entry to the active project.
      projectId: this.projectId,
      // mcp_manage reloads through this, and find_tools loads a big server's
      // tools by name. Without it a tool-driven reload cannot reconnect.
      mcp: this.mcp,
    };

    const budget = this.config.maxToolChars > 0 ? this.config.maxToolChars : 65536;
    try {
      if (this.cancelled()) return 'Action cancelled by user.';
      if (needsApproval(tool.name, args, ctx)) {
        // A tool may declare approval() and return nothing for the harmless
        // half of its actions (mcp_manage: listing is fine, starting a
        // third-party process is not). Falsy means "no gate", not "unset".
        const detail = tool.approval ? await tool.approval(args, ctx, this.ui) : JSON.stringify(args, null, 2);
        if (detail && !this.autoApprove) {
          const ok = await this.confirm?.(tool.name, detail);
          if (!ok) return "The user denied permission for this action. Do not retry it; ask what to do instead.";
        }
      }
      if (this.cancelled()) return 'Action cancelled by user.';
      const result = ['search_files', 'glob', 'list_dir', 'read_file'].includes(tool.name)
        ? await runFileToolInWorker(tool.name, args, ctx)
        : await tool.run(args, ctx);
      if (tool.name === 'remember' && args.action !== 'list' && !String(result).startsWith('Error:')) this.memoryContext = null;
      if (['remember', 'project_memory', 'project'].includes(tool.name) && !String(result).startsWith('Error:')) void warmRecall(ctx);
      if (tool.name === 'project' && ['add', 'use', 'archive', 'forget', 'update'].includes(args.action) && !String(result).startsWith('Error:')) {
        const projects = new ProjectStore(PROJECTS_FILE).load();
        if (!['add', 'use'].includes(args.action)) {
          const current = projects.find(this.projectId);
          projects.data.active = current && !current.archived ? current.id : null;
        }
        const workspacePath = projects.active?.path && fs.existsSync(projects.active.path) && fs.statSync(projects.active.path).isDirectory() ? projects.active.path : null;
        this.setProject(projects.promptBlock(), projects.activeId, workspacePath);
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
    this.abort = new AbortController();
    this.requestId = randomUUID();
    this.requestStarted = Date.now();
    this.totalToolCalls = 0;
    this.terminationReason = null;
    traceAgent({ event: 'request', request_id: this.requestId }, this.config);
    this.searchesThisTurn = 0;
    this.repeatsThisTurn = new Map();
    this.ranThisTurn = [];
    this.turnProjects = new Set(this.projectId ? [this.projectId] : []);
    this.memoryContext = this.useTools ? await personalMemoryContext(text, this.config, { signal: this.abort.signal }) : null;
    if (this.abort.signal.aborted) throw this.abort.signal.reason;
    if (this.memoryContext) {
      try { options.onToolCall?.(this.memoryContext.call); } catch {}
      try { options.onToolResult?.(this.memoryContext.call, this.memoryContext.result); } catch {}
    }
    let reply;
    try { reply = await this.sendTurn(text, options); }
    catch (err) {
      this.journalComplete = false;
      traceAgent({ event: 'final', request_id: this.requestId, total_tool_calls: this.totalToolCalls, elapsed_time: Date.now() - this.requestStarted, termination_reason: this.cancelled() ? 'cancelled' : 'error' }, this.config);
      throw err;
    }
    if (this.useTools) void warmRecall({ config: this.config });
    if (this.config.memoryConsolidation === false) this.journalComplete = false;
    if (this.journal && text !== null && this.config.memoryConsolidation !== false) {
      const projectId = this.turnProjects.size === 1 ? [...this.turnProjects][0] : null;
      try { this.journal({ text, reply, projectId, sessionId: this.sessionId }); }
      catch (err) { this.journalComplete = false; this.print(`Could not journal this turn: ${err.message}`); }
    }
    traceAgent({ event: 'final', request_id: this.requestId, total_tool_calls: this.totalToolCalls, elapsed_time: Date.now() - this.requestStarted, termination_reason: this.cancelled() ? 'cancelled' : this.terminationReason || 'model_answer' }, this.config);
    return reply;
  }

  /**
   * Once the tool model has finished the loop, it also writes the user-facing
   * reply (no tools, so it only writes). After tools the context is large - too
   * large for a small per-minute budget on the chat model - so the reply stays
   * on the tool model rather than spending a doomed call. If writing fails, the
   * draft is restored so the turn is never lost.
   */
  async writeReply({ onDelta, onReasoning, onUsage, onMessageStart, onMessageEnd } = {}) {
    const draft = this.messages.pop();
    const client = this.tool ? this.tool.client : this.client;
    const model = this.tool ? this.tool.model : this.model;
    onMessageStart?.();
    try {
      const result = await this.streamTurn({
        client,
        model,
        useTools: false,
        onDelta, onReasoning, onUsage,
      });
      this.replyModel = result.model || model;
      this.messages.push({ role: "assistant", content: result.content || null });
      return result.content;
    } catch (err) {
      this.messages.push(draft);
      this.replyModel = model;
      return draft?.content || "";
    } finally {
      onMessageEnd?.();
    }
  }

  /**
   * Ends a turn the runtime stopped, instead of letting the loop run until the
   * model declares itself finished.
   *
   * A stopped turn still owes the user an answer, so the model gets one
   * tools-free turn to say what it completed, what is uncertain and what is
   * left. Tools are withheld so it writes instead of investigating again, and
   * the model that was running the loop answers - the same reason writeReply
   * keeps the reply there: the context is now large. If even that call fails,
   * the turn returns plain text naming why it stopped, so a limit never costs
   * the user their reply.
   */
  async finishForced(reason, { onDelta, onReasoning, onUsage, onMessageStart, onMessageEnd } = {}) {
    this.terminationReason = reason;
    traceAgent({ event: 'termination', request_id: this.requestId, total_tool_calls: this.totalToolCalls, elapsed_time: Date.now() - this.requestStarted, termination_reason: reason }, this.config);
    // A bracketed synthetic note, like the cancellation notice below: the
    // instruction has to reach the model, and this is not a real user turn.
    this.messages.push({
      role: 'user',
      content: `(the runtime stopped the tool loop: ${reason}. Do not call more tools. Answer now with what you completed, what is still uncertain or unfinished, and the single next step.)`,
    });
    const onToolModel = this.toolLoopUsed && this.tool;
    const client = onToolModel ? this.tool.client : this.client;
    const model = onToolModel ? this.tool.model : this.model;
    const ran = this.ranThisTurn.length ? ` after using ${this.ranThisTurn.join(', ')}` : '';
    const fallback = `I stopped there${ran} because ${reason}. The available tool results are in the conversation; any unverified work remains uncertain. Ask me to continue if you want another bounded request.`;
    onMessageStart?.();
    try {
      const result = await this.streamTurn({ client, model, useTools: false, onDelta, onReasoning, onUsage });
      this.replyModel = result.model || model;
      const content = result.content || fallback;
      if (!result.content) onDelta?.(fallback);
      this.messages.push({ role: 'assistant', content });
      this.trimHistory(this.config.historyMessages ?? this.config.historyLines);
      return content;
    } catch {
      onDelta?.(fallback);
      this.messages.push({ role: 'assistant', content: fallback });
      this.trimHistory(this.config.historyMessages ?? this.config.historyLines);
      return fallback;
    } finally {
      onMessageEnd?.();
    }
  }

  async sendTurn(text, { onDelta, onReasoning, onUsage, onToolCall, onToolResult, onMessageStart, onMessageEnd, attachments = null } = {}) {
    this.abort ??= new AbortController();
    this.turnUsage = { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0, estimated_cost: 0 };
    this.toolLoopUsed = false;
    this.replyModel = null;
    if (text !== null) this.messages.push({ role: "user", content: buildUserContent(text, attachments) });
    // The primary handles chat. Once a turn calls a tool, a configured tool
    // model takes over the loop and the primary writes the final reply; the
    // tool model's own text is intermediate, so it is withheld from the UI.
    let usedTools = false;

    // A bound on the loop itself, not advice to the model. Config may raise it
    // (MAX_TOOL_STEPS); nothing may remove it, because the loop's only other exit
    // is the model deciding it has finished.
    const maxSteps = this.config.maxToolSteps > 0 ? this.config.maxToolSteps : MAX_TOOL_STEPS;
    const maxCalls = this.config.maxToolCalls > 0 ? this.config.maxToolCalls : MAX_TOOL_CALLS;
    for (let step = 0; step < maxSteps; step++) {
      const onToolModel = usedTools && this.tool;
      if (onToolModel) this.toolLoopUsed = true;
      const callClient = onToolModel ? this.tool.client : this.client;
      const callModel = onToolModel ? this.tool.model : this.model;

      this.refreshPrompt();
      this.trimHistory(this.config.historyMessages ?? this.config.historyLines);
      onMessageStart?.();
      const live = !onToolModel;
      let content, toolCalls;
      let partial = '';
      let result;
      try {
        result = await this.streamTurn({
          client: callClient, model: callModel,
          // The chat model falls back to the tool model on a rate limit; the
          // tool model runs the loop on its own.
          fallback: onToolModel ? null : this.tool,
          onDelta: d => { partial += d; if (live) onDelta?.(d); }, onReasoning, onUsage,
        });
        ({ content, toolCalls } = result);
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
        // The tool model finished the loop; the primary writes the reply.
        if (onToolModel) {
          const reply = await this.writeReply({ onDelta, onReasoning, onUsage, onMessageStart, onMessageEnd });
          this.trimHistory(this.config.historyMessages ?? this.config.historyLines);
          return reply;
        }
        this.replyModel = result.model || callModel;
        this.trimHistory(this.config.historyMessages ?? this.config.historyLines);
        return content;
      }

      usedTools = true;
      traceAgent({ event: 'model_decision', request_id: this.requestId, tool_round: step + 1, total_tool_calls: this.totalToolCalls, requested_tool_calls: toolCalls.length, elapsed_time: Date.now() - this.requestStarted }, this.config);
      for (const call of toolCalls) {
        const name = call?.function?.name;
        if (name && !this.ranThisTurn.includes(name)) this.ranThisTurn.push(name);
      }

      // A call repeated with identical arguments is a loop symptom: the model is
      // asking a question it already has the answer to. One round counts a
      // signature once, so several identical parallel calls stay a batching
      // choice rather than being read as a cycle.
      const repeatCounts = new Map();
      const countedThisRound = new Map();
      let noProgress = null;
      for (const call of toolCalls) {
        const signature = callSignature(call);
        let entry = countedThisRound.get(signature);
        if (!entry) {
          entry = this.noteRepeat(call);
          countedThisRound.set(signature, entry);
          if (entry.count >= MAX_REPEAT_CALLS && !noProgress) noProgress = entry;
        }
        repeatCounts.set(call.id, entry.count);
      }

      const budget = this.config.maxToolChars > 0 ? this.config.maxToolChars : 65536;

      // Exactly one reply per declared tool_call, whatever happens. The API
      // rejects the entire next request if any call is unanswered ("must be
      // followed by tool messages responding to each tool_call_id"), so one
      // thrown tool - or one throwing UI callback - would end the session
      // rather than just fail a step.
      const reply = (call, content) => ({ role: "tool", tool_call_id: call.id, content });

      const run = async (call) => {
        const started = Date.now();
        const metadata = { request_id: this.requestId, tool_round: step + 1, total_tool_calls: this.totalToolCalls, tool_name: call?.function?.name || 'tool', normalized_arguments_hash: createHash('sha256').update(callSignature(call)).digest('hex').slice(0, 16) };
        traceAgent({ event: 'tool_call', ...metadata, elapsed_time: started - this.requestStarted }, this.config);
        try {
          onToolCall?.(call);
        } catch {}
        let result;
        let args;
        try { args = call.function.arguments ? JSON.parse(call.function.arguments) : {}; } catch {}
        try {
          result = await this.runToolCall(call, args);
        } catch (err) {
          result = `Error while running ${call?.function?.name || "tool"}: ${err.message}`;
        }
        const verdict = verdictFor(call?.function?.name, args || {}, result, this.mcp);
        const footer = verificationFooter(verdict);
        try {
          onToolResult?.(call, result);
        } catch {}
        traceAgent({ event: 'tool_result', ...metadata, duration_ms: Date.now() - started, success: verdict?.ok === false ? false : !isToolFailure(result), verified: verdict?.ok ?? null, error: verdict?.ok === false || isToolFailure(result) ? 'tool_error' : undefined }, this.config);
        try {
          // The advisory rides in the tool result, where the model actually reads
          // it; the hard stop is the loop-level check below.
          const count = repeatCounts.get(call.id) || 1;
          const note = count > 1
            ? `Repeated call: this exact call already ran ${count - 1} time(s) in this request. Its result is above - use it, or change the approach.\n\n`
            : '';
          const fittedFooter = Buffer.byteLength(footer) <= budget ? footer
            : capOutput(verdict?.ok === true ? '\n[verified: receipt]' : '\n[UNVERIFIED]', budget);
          return reply(call, capOutput(note + result, Math.max(0, budget - Buffer.byteLength(fittedFooter))) + fittedFooter);
        } catch (err) {
          return reply(call, `Error: the result could not be formatted (${err.message}).`);
        }
      };

      // Mutations are barriers: only contiguous read-only calls overlap.
      for (let i = 0; i < toolCalls.length;) {
        if (this.totalToolCalls >= maxCalls) {
          for (; i < toolCalls.length; i++) this.messages.push(reply(toolCalls[i], `Not run: the ${maxCalls}-call budget for this request is exhausted.`));
          break;
        }
        if (this.cancelled()) {
          // Cancelling must stop the remaining work, and still answer every
          // call the assistant already declared, or the next turn is invalid.
          for (; i < toolCalls.length; i++) {
            this.messages.push(reply(toolCalls[i], "Not run: the user cancelled before this step."));
          }
          break;
        }
        const canOverlap = call => {
          try { return isReadOnly(call.function.name, JSON.parse(call.function.arguments || '{}')); } catch { return false; }
        };
        if (canOverlap(toolCalls[i])) {
          const batch = [];
          while (i < toolCalls.length && canOverlap(toolCalls[i]) && this.totalToolCalls < maxCalls) {
            batch.push(toolCalls[i++]);
            this.totalToolCalls++;
          }
          this.messages.push(...await Promise.all(batch.map(run)));
        } else {
          this.totalToolCalls++;
          this.messages.push(await run(toolCalls[i++]));
        }
      }

      if (this.cancelled()) {
        this.messages.push({ role: "user", content: "(previous action was cancelled by the user)" });
        return null;
      }
      if (this.totalToolCalls >= maxCalls) {
        return await this.finishForced(`the ${maxCalls}-call budget for this request is spent`, { onDelta, onReasoning, onUsage, onMessageStart, onMessageEnd });
      }

      // Stopping is the runtime's call once a call stops making progress. Its
      // results are already in context, so what follows is a summary, not
      // another round of investigation.
      if (noProgress) {
        return await this.finishForced(
          `it kept repeating ${noProgress.name} with identical arguments (${noProgress.count} times this request)`,
          { onDelta, onReasoning, onUsage, onMessageStart, onMessageEnd }
        );
      }
    }

    // Reaching here means the round budget was spent - every other exit above
    // returns. One tools-free turn answers with what it has, rather than the
    // canned string this used to end on.
    return await this.finishForced(
      `the tool budget for this request is spent (${maxSteps} rounds)`,
      { onDelta, onReasoning, onUsage, onMessageStart, onMessageEnd }
    );
  }
}
