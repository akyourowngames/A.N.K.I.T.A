export const SUBAGENT_TOOL = 'delegate_task';
export const SUBAGENT_CONTROL_TOOL = 'subagent_control';
export const SUBAGENT_PARENT_TARGET = 'parent';
// Shared direction labels keep terminal and desktop message receipts consistent.
export const SUBAGENT_MESSAGE_LABELS = Object.freeze({ toChild: 'Parent to agent', toParent: 'Agent to parent' });
export const SUBAGENT_INBOX_PREFIX = '[Sub-agent inbox]';
// Bytes/message and queued messages/recipient bound cross-agent context growth.
export const SUBAGENT_MESSAGE_BYTES = 8_000;
export const SUBAGENT_INBOX_LIMIT = 64;
// Milliseconds/control wait keeps the parent responsive while children work.
export const SUBAGENT_WAIT_MS = 1_000;
export const SUBAGENT_MAX_WAIT_MS = 30_000;
export const SUBAGENT_TYPES = Object.freeze(['explore', 'reviewer', 'worker']);
// Parent-facing digest size; the complete answer travels in the result field.
export const SUMMARY_MAX_BYTES = 2_000;
// Transcript file prefix; child sessions must never overwrite teammate-<id>.json.
export const SUBAGENT_TRANSCRIPT_PREFIX = 'subagent-';
// Transcripts kept per workspace store; older child runs are pruned first.
export const SUBAGENT_TRANSCRIPT_KEEP = 200;
// Event payload caps keep UI state bounded regardless of child verbosity.
export const SUBAGENT_EVENT_RESULT_BYTES = 12_000;
export const SUBAGENT_DESCRIPTION_MAX_CHARS = 200;
// Bounds shared with config validation and the tool schema, so the ranges the
// model sees match the ranges the runtime enforces.
export const SUBAGENT_LIMITS = Object.freeze({
  maxDepth: 3,
  maxConcurrent: 16,
  maxPerTurn: 64,
  maxToolSteps: 400,
  maxToolCalls: 500,
  minTimeoutMs: 10_000,
  maxTimeoutMs: 7_200_000,
  minTokens: 1_000,
  maxTokens: 10_000_000,
  minResultBytes: 1_000,
  maxResultBytes: 128_000,
});

// Shared fallbacks so config defaults, runtime guards and tests cannot drift.
// Long implementation tasks are the common case, so the defaults are sized for
// a real edit-test-fix loop rather than a single reconnaissance pass.
export const SUBAGENT_DEFAULTS = Object.freeze({
  enabled: true,
  maxDepth: 1,
  concurrency: 8,
  perTurn: 24,
  toolSteps: 100,
  toolCalls: 200,
  timeoutMs: 1_800_000,
  tokens: 1_000_000,
  resultBytes: 48_000,
});

export const SUBAGENT_STATUS = Object.freeze({
  queued: 'queued',
  running: 'running',
  completed: 'completed',
  failed: 'failed',
  timeout: 'timeout',
  cancelled: 'cancelled',
  budgetExceeded: 'budget_exceeded',
  rejected: 'rejected',
});

export const SUBAGENT_EVENT = Object.freeze({
  queued: 'subagent-queued',
  message: 'subagent-message',
  start: 'subagent-start',
  delta: 'subagent-delta',
  toolCall: 'subagent-tool-call',
  toolResult: 'subagent-tool-result',
  end: 'subagent-end',
});

export const CHILD_RULES = [
  'You are a sub-agent in an isolated context. Use subagent_control(action="send", subagent_id="parent", message="...") to send progress, questions or findings to your parent during work. Parent messages arrive between model decisions.',
  'You cannot ask the user directly or delegate. Send questions to your parent and continue independent safe work while awaiting a reply. If the brief stays ambiguous, state your interpretation.',
  'Your final answer must be complete: what you did or found, evidence (file:line where relevant), files changed, commands/tests run and their results, and remaining risks.',
  'Never claim work you did not verify.',
].join(' ');

const READ_ONLY_TOOLS = Object.freeze([
  SUBAGENT_CONTROL_TOOL,
  'read_file',
  'list_dir',
  'search_files',
  'glob',
  // git is argument-aware: status/diff/log/show/blame and list operations pass
  // the host read-only gate; mutations stay blocked.
  'git',
  'web_search',
  'web_fetch',
  'scrape',
]);

// Children stay inside the local tool loop. Browser, connectors, skills, memory,
// scheduled work and recursion are parent-only capabilities in v1.
export const BLOCKED_CHILD_TOOLS = new Set([
  SUBAGENT_TOOL,
  'browser',
  'schedule',
  'watch',
  'schedule_status',
  'mcp_manage',
  'composio',
  'skill',
  'project',
  'project_memory',
  'remember',
  'recall',
  'find_tools',
]);

export const PRESETS = Object.freeze({
  explore: Object.freeze({
    description: 'Read-only research agent for codebase and web reconnaissance.',
    readOnly: true,
    tools: READ_ONLY_TOOLS,
    systemPrompt: 'You are an exploration sub-agent. Investigate the assigned question and return evidence, not speculation. Read files and research the web as needed. You cannot edit files, run commands, or change state. Report findings with file:line references and list anything you could not verify.',
  }),
  reviewer: Object.freeze({
    description: 'Read-only code reviewer for correctness, regressions and missing tests.',
    readOnly: true,
    tools: READ_ONLY_TOOLS,
    systemPrompt: 'You are a code-review sub-agent. Inspect the requested code, diff, or change for correctness bugs, regressions, security issues, and missing tests. Do not edit files or run mutating commands. Report findings in priority order with file:line references and concrete fixes.',
  }),
  worker: Object.freeze({
    description: 'Implementation agent with the full local toolset, run one at a time.',
    readOnly: false,
    tools: 'all',
    systemPrompt: 'You are an implementation sub-agent. Complete the assigned change end to end with the tools available. You share the workspace with the parent, so make only the edits the task requires and do not start overlapping work. Run the relevant tests or checks and report exactly what passed, failed, or remains unverified.',
  }),
});

export function presetFor(name) {
  return PRESETS[name] || null;
}

export function presetReadOnly(name) {
  return PRESETS[name]?.readOnly === true;
}

/** Explicit preset tools or the full local catalog, minus parent-only capabilities. */
export function resolveTools(preset, allNames) {
  if (!preset) return [];
  const available = new Set(allNames);
  const names = preset.tools === 'all' ? allNames : preset.tools;
  return [...new Set(names)].filter(name => available.has(name) && !BLOCKED_CHILD_TOOLS.has(name));
}
