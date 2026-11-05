/** Live sub-agent activity for the desktop workbench. No DOM or Electron dependency. */
import { SUBAGENT_EVENT, SUBAGENT_STATUS, SUBAGENT_INBOX_LIMIT } from '../../src/core/subagents/registry.mjs';
export { SUBAGENT_PARENT_TARGET, SUBAGENT_MESSAGE_LABELS } from '../../src/core/subagents/registry.mjs';

// Characters kept from one child's stream. The parent receives the complete
// answer in the delegate_task result; the live card only needs enough context
// to stay useful without letting a chatty child grow renderer memory forever.
export const SUBAGENT_TEXT_LIMIT = 48_000;
// Tool rows kept per child, newest last. A transcript still has the full list.
export const SUBAGENT_TOOL_LIMIT = 60;
const OMITTED = '\n… earlier output omitted; open the transcript for the full run.';
// UI-only state before the runtime reports a terminal SUBAGENT_STATUS value.
const RUNNING = 'running';

function capText(text) {
  return text.length > SUBAGENT_TEXT_LIMIT ? text.slice(0, SUBAGENT_TEXT_LIMIT) + OMITTED : text;
}

function parseArgs(value) {
  if (typeof value !== 'string') return value ?? {};
  try { return JSON.parse(value); } catch { return value; }
}

function blank(event) {
  return {
    subagentId: event.subagentId,
    parentCallId: event.parentCallId ?? null,
    subagentType: event.subagentType || '',
    description: event.description || '',
    prompt: event.prompt || '',
    depth: Number.isFinite(event.depth) ? event.depth : 1,
    status: RUNNING,
    text: '',
    tools: [],
    messages: [],
    summary: '',
    usage: null,
    durationMs: 0,
    transcript: null,
    toolsUsed: [],
    error: null,
    startedAt: Date.now(),
    endedAt: null,
  };
}

function toolCall(event) {
  const call = event.call || {};
  return {
    callId: String(call.id || call.callId || ''),
    name: call.function?.name || 'tool',
    args: parseArgs(call.function?.arguments),
  };
}

function appendTool(tools, row) {
  return [...tools, row].slice(-SUBAGENT_TOOL_LIMIT);
}

/**
 * Fold one subagent-* engine event into live activity keyed by
 * threadId → parent tool callId, so a delegate_task card can find its child.
 * Unknown events and malformed payloads pass through.
 */
export function reduceSubagents(state, event) {
  if (!event?.threadId || !event.subagentId) return state;
  const key = event.parentCallId || event.subagentId;
  const records = state[event.threadId] || {};
  const current = records[key] || blank(event);
  let next = current;

  switch (event.type) {
    case SUBAGENT_EVENT.queued:
      next = { ...current, status: SUBAGENT_STATUS.queued };
      break;
    case SUBAGENT_EVENT.message:
      if (!event.messageId || typeof event.message !== 'string' || current.messages?.some(item => item.messageId === event.messageId)) return state;
      next = { ...current, messages: [...(current.messages || []), {
        messageId: event.messageId, from: event.from, to: event.to, message: capText(event.message), createdAt: event.createdAt,
      }].slice(-SUBAGENT_INBOX_LIMIT) };
      break;
    case SUBAGENT_EVENT.start:
      next = {
        ...current,
        subagentType: event.subagentType || current.subagentType,
        description: event.description || current.description,
        prompt: event.prompt ?? current.prompt,
        depth: Number.isFinite(event.depth) ? event.depth : current.depth,
        parentCallId: event.parentCallId ?? current.parentCallId,
        status: RUNNING,
      };
      break;
    case SUBAGENT_EVENT.delta:
      next = { ...current, text: capText(current.text + String(event.text || '')) };
      break;
    case SUBAGENT_EVENT.toolCall: {
      const row = toolCall(event);
      if (!row.callId || current.tools.some(item => item.callId === row.callId)) break;
      next = { ...current, tools: appendTool(current.tools, { ...row, result: '', isError: false, state: RUNNING }) };
      break;
    }
    case SUBAGENT_EVENT.toolResult: {
      const row = toolCall(event);
      const result = String(event.result ?? '');
      const isError = /^Error\b/i.test(result);
      const state = isError ? 'error' : 'ok';
      const existing = current.tools.find(item => item.callId === row.callId);
      next = existing
        ? { ...current, tools: current.tools.map(item => item.callId === row.callId ? { ...item, result, isError, state } : item) }
        : { ...current, tools: appendTool(current.tools, { ...row, result, isError, state }) };
      break;
    }
    case SUBAGENT_EVENT.end: {
      const status = event.status || SUBAGENT_STATUS.failed;
      next = {
        ...current,
        status,
        summary: event.summary || current.summary,
        usage: event.usage || current.usage,
        durationMs: Number.isFinite(event.durationMs) ? event.durationMs : current.durationMs,
        transcript: event.transcript || current.transcript,
        toolsUsed: Array.isArray(event.toolsUsed) ? event.toolsUsed : current.toolsUsed,
        subagentType: event.subagentType || current.subagentType,
        description: event.description || current.description,
        depth: Number.isFinite(event.depth) ? event.depth : current.depth,
        error: status === SUBAGENT_STATUS.failed ? event.summary || current.error || 'The sub-agent failed.' : null,
        endedAt: Date.now(),
        // A terminal status freezes in-flight tool rows so the card stops
        // spinning even when the child was cancelled mid-tool.
        tools: current.tools.map(item => item.state === RUNNING ? { ...item, state: 'stopped' } : item),
      };
      break;
    }
    default:
      return state;
  }

  if (next === current && records[key]) return state;
  return { ...state, [event.threadId]: { ...records, [key]: next } };
}

export function clearThreadSubagents(state, threadId) {
  if (!state[threadId]) return state;
  const next = { ...state };
  delete next[threadId];
  return next;
}

/**
 * Rebuild a completed card from the delegate_task result stored in the parent
 * transcript. This keeps the card useful after a reload or a missed live event.
 */
export function activityFromReceipt(result) {
  let receipt;
  try { receipt = JSON.parse(String(result || '')); } catch { return null; }
  if (!receipt || typeof receipt !== 'object' || !receipt.subagentId) return null;
  return {
    ...blank({
      subagentId: receipt.subagentId,
      parentCallId: receipt.parentCallId,
      subagentType: receipt.subagentType,
      description: receipt.description,
      depth: receipt.depth,
    }),
    status: receipt.status || SUBAGENT_STATUS.failed,
    summary: receipt.summary || '',
    usage: receipt.usage || null,
    durationMs: Number.isFinite(receipt.durationMs) ? receipt.durationMs : 0,
    transcript: receipt.transcript || null,
    toolsUsed: Array.isArray(receipt.toolsUsed) ? receipt.toolsUsed : [],
    error: receipt.status === SUBAGENT_STATUS.failed ? receipt.error || receipt.summary || 'The sub-agent failed.' : null,
    endedAt: null,
  };
}
