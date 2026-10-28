import { specs, get, needsApproval, isReadOnly, displayArgs } from '../../tools/index.mjs';
import { DEFAULT_TOOL_OUTPUT_BYTES } from './config.mjs';
import { capOutput } from '../../tools/shared/_shared.mjs';
import { redactText, configuredSecrets } from './redact.mjs';
import { focusAllows } from './tool-focus.mjs';
import { runFileToolInWorker } from '../tooling/tool-worker.mjs';
import { primitiveBrowserCost } from '../../tools/browser/operations.mjs';
import { captureBrowserEvidence, recordBrowserProgress } from './browser-progress.mjs';
import { isToolFailure } from './verify.mjs';
import { browserScreenshotImage } from '../../tools/browser/screenshots.mjs';
import { isBrowserMcpTool, MANAGED_BROWSER_REQUIRED } from '../integrations/browser-routing.mjs';
import { parseToolName } from '../integrations/mcp-manager.mjs';
import { TIER_DENY } from '../integrations/mcp-tiers.mjs';
import { COMPUTER_MCP_ID, COMPUTER_DIRECT_CONFIG, COMPUTER_POINTER_SESSION, COMPUTER_TOOLS, computerObservationTargets, formatComputerTargets } from '../integrations/computer-use.mjs';
import { validMcpImage, MAX_MCP_IMAGES_PER_TURN } from '../integrations/mcp-images.mjs';
import { JOB_EXECUTION_COMPLETE } from '../automation/job-policy.mjs';
import { killTree } from '../../tools/shared/_job-tree.mjs';
import { waitForExit } from '../../tools/shared/_jobs.mjs';
import { TOOL_RESULT_MODE, NATIVE_TOOL_SURFACES } from '../integrations/chatgpt-browser/protocol.mjs';
import { c, preview, short, clip } from './ui.mjs';
import { renderDiff } from '../../tools/shared/_diff.mjs';
import { name as TOOL_DISCOVERY_NAME } from '../../tools/find-tools.mjs';
import { SUBAGENT_TOOL } from './subagents/registry.mjs';
import { runtimeVoiceTool, runtimeToolFlag } from './runtime-tools.mjs';

export const TOOL_UI = { ...c, preview, short, clip };
TOOL_UI.diff = (oldText, newText, opts = {}) => renderDiff(oldText, newText, { ui: TOOL_UI, ...opts });

// Calls/request: shared with the API loop so browser hosts use the same limits.
export const MAX_TOOL_CALLS = 60;
export const MAX_WEB_SEARCHES_PER_TURN = 6;
export const MAX_REPEAT_CALLS = 3;
const FILE_WORKER_TOOLS = new Set(['search_files', 'glob', 'list_dir', 'read_file']);
const NATIVE_CONNECTION_MANAGEMENT_TOOLS = new Set(['mcp_manage', 'composio']); // Native models use already connected capabilities; the desktop owner controls global connection settings.
const DEFAULT_OUTPUT_COLUMNS = 80; // Terminal columns when no interactive TTY supplies a width.
const CANCELLED = 'Action cancelled by user.';
const DENIED = 'The user denied permission for this action. Do not retry it; ask what to do instead.';
const MCP_PREFIX = 'mcp__'; // Existing namespaced registry contract.
const MCP_MODE = TOOL_RESULT_MODE.mcp;
const READ_ONLY_DENIAL = 'Error: this host is read-only.';
const JOB_STOP_WAIT_MS = 5000; // Milliseconds/owned job termination before native Stop acknowledges completion.
const NATIVE_IMAGE_LIMIT_NOTICE = 'Omitted visual state is unavailable: the image limit for this generation was reached. Do not infer the undelivered image contents.';
const NATIVE_IMAGE_INVALID_NOTICE = 'Omitted visual state is unavailable: image data failed format or size validation. Do not infer the undelivered image contents.';
const stoppingJobs = new WeakMap(); // Shared workflow hosts terminate each owned child only once concurrently.
const automaticApproval = ctx => ctx.autoApprove === undefined ? ctx.config.autoApprove === true : ctx.autoApprove === true; // Current host policy wins over an older config snapshot.
const textResult = text => ({ content: [{ type: 'text', text: String(text) }], isError: isToolFailure(String(text)) || text === CANCELLED || text === DENIED });
function nativeProjection(result, state, budget, targets = null) {
  const images = [], omissions = new Set();
  for (const part of result.content) {
    if (result.isError || part?.type !== 'image') continue;
    if (!validMcpImage(part)) { omissions.add(NATIVE_IMAGE_INVALID_NOTICE); continue; }
    if ((state.nativeImagesThisTurn || 0) >= MAX_MCP_IMAGES_PER_TURN) { omissions.add(NATIVE_IMAGE_LIMIT_NOTICE); continue; }
    images.push({ type: 'image', mimeType: part.mimeType, data: part.data });
    state.nativeImagesThisTurn = (state.nativeImagesThisTurn || 0) + 1;
  }
  const notice = omissions.size ? capOutput([...omissions].join('\n') + '\n', budget) : '';
  const targetText = formatComputerTargets(targets, Math.max(0, budget - Buffer.byteLength(notice)));
  const remaining = Math.max(0, budget - Buffer.byteLength(notice) - Buffer.byteLength(targetText));
  const text = result.content.filter(part => part?.type === 'text').map(part => part.text).join('\n');
  return { content: [{ type: 'text', text: notice + (remaining ? capOutput(text, remaining) : '') + targetText }, ...images],
    isError: result.isError || omissions.size > 0 };
}
function deniedTier(decision, mcp, name) {
  mcp.recordTierDecision?.(name, 'denied');
  return textResult(`Error: ${decision.label} is blocked by the approval tiers. Do not retry it; ask the user whether the tier rule should change.`);
}

/** Execution only: no model client, conversation loop or API history. Context is host-owned.
 * A context getter lets an API Agent share its current request counters after project/Stop changes.
 */
export class ToolHost {
  constructor({ context, mcp = null, authorize, onEvent } = {}) {
    if (!context) throw new TypeError('ToolHost requires an explicit host context');
    this.context = context; this.mcp = mcp; this.authorize = authorize; this.onEvent = onEvent;
    this.controller = new AbortController();
    this.requestState = { searchesThisTurn: 0, browserActionsThisTurn: 0, activeSkillTools: new Set() };
  }

  currentContext() { return typeof this.context === 'function' ? this.context() : this.context; }
  async approve(name, detail, signal) {
    if (signal.aborted) return false;
    let aborted;
    const cancellation = new Promise(resolve => { aborted = () => resolve(false); });
    signal.addEventListener('abort', aborted, { once: true });
    try { return await Promise.race([Promise.resolve().then(() => signal.aborted ? false : this.authorize?.(name, detail)), cancellation]); }
    finally { signal.removeEventListener('abort', aborted); }
  }
  specs(surface = NATIVE_TOOL_SURFACES.core) {
    const ctx = this.currentContext();
    if (!Object.values(NATIVE_TOOL_SURFACES).includes(surface)) throw new Error('Unknown native tool surface');
    const local = specs.filter(spec => !NATIVE_CONNECTION_MANAGEMENT_TOOLS.has(spec.function.name) && (spec.function.name === TOOL_DISCOVERY_NAME || (surface !== NATIVE_TOOL_SURFACES.plugins &&
      (surface === NATIVE_TOOL_SURFACES.desktop ? spec.function.name === 'browser' : spec.function.name !== 'browser'))) &&
      (!ctx.allowedTools || ctx.allowedTools.has(spec.function.name)) &&
      (spec.function.name !== SUBAGENT_TOOL || Boolean(ctx.runSubagent)) &&
      (!ctx.readOnly || isReadOnly(spec.function.name, {}, ctx))).map(spec => ({
      name: spec.function.name, description: spec.function.description, inputSchema: spec.function.parameters,
      annotations: { readOnlyHint: isReadOnly(spec.function.name, {}, ctx) },
    }));
    if (surface === NATIVE_TOOL_SURFACES.core) return local;
    const manager = ctx.mcp ?? this.mcp;
    const native = (manager?.specs?.() ?? []).flatMap(spec => {
      const name = spec.function.name, parsed = parseToolName(name), found = manager.findTool(name);
      if (!found || (ctx.allowedTools && !ctx.allowedTools.has(name)) || manager.tierFor?.(name, {})?.tier === TIER_DENY) return [];
      if (ctx.readOnly && found.tool.annotations?.readOnlyHint !== true) return [];
      if (isBrowserMcpTool(name, [{ id: parsed?.serverId, tools: found.record?.tools ?? [] }])) return []; // Normal browser operations stay under their managed adapter.
      const computer = parsed?.serverId === COMPUTER_MCP_ID;
      if (computer !== (surface === NATIVE_TOOL_SURFACES.desktop) || (computer && !COMPUTER_TOOLS.includes(parsed.toolName))) return [];
      return [{ name, description: spec.function.description, inputSchema: spec.function.parameters, annotations: found.tool.annotations ?? {} }];
    });
    return [...local, ...native];
  }

  async cancel() {
    this.controller.abort();
    let ctx = this.executedContext;
    if (!ctx) { try { ctx = this.currentContext(); } catch { ctx = null; } }
    await Promise.all([...(ctx?.state?.jobs?.values() ?? [])].filter(job => !job.done).map(job => {
      if (!stoppingJobs.has(job.child)) {
        job.stopped = true;
        const stopping = (async () => {
          await killTree(job.child); await waitForExit(job, JOB_STOP_WAIT_MS);
          if (!job.done) throw new Error('Owned command termination was not confirmed');
        })();
        stoppingJobs.set(job.child, stopping);
        void stopping.finally(() => stoppingJobs.delete(job.child)).catch(() => {});
      }
      return stoppingJobs.get(job.child);
    }));
  }

  async execute(call, { signal, resultMode = MCP_MODE, surface = null } = {}) {
    const base = this.currentContext();
    const config = base.config ?? {};
    const state = base.executionState ?? this.requestState;
    const args = call.arguments ?? {};
    const name = call.name;
    const combined = AbortSignal.any([this.controller.signal, signal, base.signal].filter(Boolean));
    const ctx = { ...base, config, state: base.state ?? { activatedTools: new Set() }, signal: combined, ui: base.ui ?? TOOL_UI,
      width: base.width ?? process.stdout.columns ?? DEFAULT_OUTPUT_COLUMNS,
      browserCallId: call.id, callId: call.id, mcp: base.mcp ?? this.mcp };
    this.executedContext = ctx;
    const budget = config.maxToolChars > 0 ? config.maxToolChars : DEFAULT_TOOL_OUTPUT_BYTES;
    if (combined.aborted) return textResult(CANCELLED);
    if (surface) {
      ctx.toolAvailability = new Set(this.specs(surface).map(spec => spec.name)); // Discovery and execution share the same host-only native interface boundary.
      if (!ctx.toolAvailability.has(name)) return textResult('Error: this tool is unavailable on the current native surface.');
    }
    if (!args || typeof args !== 'object' || Array.isArray(args)) return textResult('Error: arguments must be an object.');
    if (!focusAllows(ctx.state, name) && runtimeVoiceTool(ctx, name)?.alwaysAvailable !== true) return textResult('Error: This tool is outside the current tool focus. Use find_tools with scope="general" to explicitly change methods before executing it.');
    if (ctx.allowedTools && !ctx.allowedTools.has(name)) return textResult(ctx.backgroundToolScope
      ? 'Error: This tool is not available in background browser jobs.'
      : 'Error: This tool is not available in this execution context.');
    this.onEvent?.({ type: 'tool-call', call });
    let result;
    try {
      if (ctx.beforeToolExecute) await ctx.beforeToolExecute(call, ctx);
      result = combined.aborted ? textResult(CANCELLED) : String(name).startsWith(MCP_PREFIX)
        ? await this.executeMcp(call, args, ctx, state, resultMode, budget)
        : await this.executeLocal(call, args, ctx, state, resultMode, budget);
    } catch (error) { result = textResult(`Error while running ${name}: ${error.message}`); }
    this.onEvent?.({ type: 'tool-result', call, result });
    return result;
  }

  async executeMcp(call, args, ctx, state, resultMode, budget) {
    const name = call.name;
    const mcp = ctx.mcp;
    const found = mcp?.findTool(name);
    const native = parseToolName(name);
    if (ctx.browserManager && isBrowserMcpTool(name, [{ id: native?.serverId, tools: found?.record?.tools || [] }])) {
      ctx.state.activatedTools.add('browser'); return textResult(MANAGED_BROWSER_REQUIRED);
    }
    if (!found) return textResult(`Error: no connected MCP server provides "${name}".`);
    if (ctx.readOnly && found.tool?.annotations?.readOnlyHint !== true) return textResult(READ_ONLY_DENIAL);
    const direct = ctx.config[COMPUTER_DIRECT_CONFIG] === true && native?.serverId === COMPUTER_MCP_ID && COMPUTER_TOOLS.includes(native.toolName);
    if (direct && ctx.beforeComputerAction) {
      const preliminary = mcp.tierFor?.(name, args);
      if (preliminary?.tier === TIER_DENY) return deniedTier(preliminary, mcp, name);
      await ctx.beforeComputerAction(found.record, { signal: ctx.signal });
    }
    const pointer = found.record?.[COMPUTER_POINTER_SESSION];
    if (direct && pointer && found.tool?.inputSchema?.properties?.session) args = { ...args, session: pointer };
    const decision = mcp.tierFor?.(name, args);
    if (decision?.tier === TIER_DENY) {
      return deniedTier(decision, mcp, name);
    }
    if (direct) mcp.recordTierDecision?.(name, 'allowed');
    if (!direct && mcp.needsApproval(name, args) && !automaticApproval(ctx)) {
      const ok = await this.approve(name, mcp.approvalDetail(name, args), ctx.signal);
      mcp.recordTierDecision?.(name, ok === true ? 'allowed' : 'denied');
      if (ctx.signal.aborted) return textResult(CANCELLED);
      if (ok !== true) return textResult(DENIED);
    }
    if (ctx.signal.aborted) return textResult(CANCELLED);
    if (ctx.onToolStart) await ctx.onToolStart(call, ctx);
    if (ctx.signal.aborted) return textResult(CANCELLED);
    if (!mcp.callToolResult) return textResult(await mcp.callTool(name, args, { signal: ctx.signal }));
    const result = await mcp.callToolResult(name, args, { signal: ctx.signal });
    const raw = result?.raw ?? result;
    const nativeResult = { content: Array.isArray(raw?.content) ? raw.content : [{ type: 'text', text: result?.text ?? '' }],
      ...(result?.text !== undefined ? { text: result.text } : {}),
      ...(raw?.structuredContent ? { structuredContent: raw.structuredContent } : {}),
      isError: Boolean(result?.isError || raw?.isError) };
    if (resultMode !== MCP_MODE) return nativeResult;
    const targets = native?.serverId === COMPUTER_MCP_ID ? computerObservationTargets(nativeResult) : null;
    return nativeProjection(nativeResult, state, budget, targets);
  }

  async executeLocal(call, args, ctx, state, resultMode, budget) {
    const native = get(call.name);
    const tool = native || runtimeVoiceTool(ctx, call.name);
    if (!tool) return textResult(`Error: unknown tool "${call.name}".`);
    if (ctx.readOnly && !(native ? isReadOnly(tool.name, args, ctx) : runtimeToolFlag(tool, 'readOnly', args, ctx) === true)) return textResult(READ_ONLY_DENIAL);
    if (tool.name === 'skill' && !(ctx.skillsInteractive ?? ctx.skillsEnabled)) return textResult('Error: skills are available only in interactive chats.');
    if (tool.name === 'skill' && ctx.disabledSkills?.has(String(args.name || '').trim().toLowerCase())) return textResult(`Error: skill "${args.name}" is disabled in Plugins > Skills.`);
    if (tool.name === 'web_search') {
      const completion = ctx.config.backgroundJob && ctx.config.backgroundExecutionPolicy === JOB_EXECUTION_COMPLETE;
      if (!completion && state.searchesThisTurn >= MAX_WEB_SEARCHES_PER_TURN) return textResult(`Search limit reached (${MAX_WEB_SEARCHES_PER_TURN} web searches for this request). Use the results already gathered and answer the user; do not try another search tool for the same query.`);
      state.searchesThisTurn++;
    }
    ctx.onToolsActivated = names => { for (const name of names) state.activeSkillTools.add(name); };
    ctx.onBrowserActionResult = result => {
      ctx.browserResultCallback?.(result);
      if (ctx.config.browserEvidenceRetention === true) state.browserEvidence = captureBrowserEvidence(state.browserEvidence, result, call.id);
      if (ctx.config.browserProgressTracking === true) state.browserProgress = recordBrowserProgress(state.browserProgress, result, { maxRepeats: MAX_REPEAT_CALLS });
    };
    const automatic = automaticApproval(ctx);
    if (native ? needsApproval(tool.name, args, ctx) : runtimeToolFlag(tool, 'needsApproval', args, ctx) !== false) {
      if (automatic && tool.neverAutoApprove?.(args, ctx) === true) return textResult(`Error: ${tool.name} can change approval settings, which auto-approve is not allowed to do. Ask the user to run it interactively.`);
      const preview = tool.approval ? await tool.approval(args, ctx, ctx.ui) : null;
      const detail = redactText(typeof preview === 'string' && preview.trim() ? preview :
        `${tool.name}\n\n${JSON.stringify(displayArgs(tool.name, args, ctx), null, 2)}`, { secrets: configuredSecrets(process.env, ctx.config) });
      if (!automatic) {
        const ok = await this.approve(tool.name, detail, ctx.signal);
        if (ctx.signal.aborted) return textResult(CANCELLED);
        if (ok !== true) return textResult(DENIED);
      }
    }
    if (ctx.signal.aborted) return textResult(CANCELLED);
    state.activeSkillTools.add(tool.name);
    if (tool.name === 'browser' && ctx.config.browserRuntimeV2 === true) {
      const limit = ctx.config.maxToolCalls > 0 ? ctx.config.maxToolCalls : MAX_TOOL_CALLS;
      const cost = primitiveBrowserCost(args);
      if ((state.browserActionsThisTurn || 0) + cost > limit) return textResult(`Error: Browser primitive action budget (${limit} this turn) is exhausted. Inspect existing receipts and report unfinished work.`);
      state.browserActionsThisTurn = (state.browserActionsThisTurn || 0) + cost;
    }
    if (ctx.onToolStart) await ctx.onToolStart(call, ctx);
    if (ctx.signal.aborted) return textResult(CANCELLED);
    let output = FILE_WORKER_TOOLS.has(tool.name) ? await runFileToolInWorker(tool.name, args, ctx) : await tool.run(args, ctx);
    if (tool.name === 'browser' && typeof output === 'string' && !isToolFailure(output)) {
      const guidance = [ctx.config.browserProgressTracking === true ? state.browserProgress?.guidance : null,
        ctx.config.browserEvidenceRetention === true ? state.browserEvidence?.notice : null].filter(Boolean);
      if (guidance.length) output += '\nBrowser read-back guidance: ' + guidance.join(' ');
    }
    await ctx.onLocalResult?.(tool.name, args, output, ctx);
    const result = textResult(capOutput(output, budget));
    if (resultMode === MCP_MODE && tool.name === 'browser' && args.action === 'screenshot' && !result.isError) {
      const image = browserScreenshotImage(output, ctx);
      if (!image) return nativeProjection({ content: [{ type: 'text', text: NATIVE_IMAGE_INVALID_NOTICE }], isError: true }, state, budget);
      const [mimeType, data] = image.dataUrl.slice('data:'.length).split(';base64,');
      result.content.push({ type: 'image', mimeType, data });
      return nativeProjection(result, state, budget);
    }
    return result;
  }
}
