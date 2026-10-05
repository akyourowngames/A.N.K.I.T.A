/** ANKITA's companion event model. No renderer or Electron dependency. */
export const ISLAND_HISTORY_LIMIT = 40; // Rows; bounded history for a small companion window.
export const ISLAND_TOOL_DETAIL_LIMIT = 90; // Characters; keep a tool identity readable in one line.
export const ISLAND_TOOL_RESULT_LIMIT = 12000; // Characters; expandable output without unbounded DOM growth.
const TOOL_FIELDS = ['command', 'file_path', 'path', 'url', 'query', 'pattern', 'prompt', 'action'];
const PATH_FIELDS = new Set(['file_path', 'path']);
const SEARCH_TOOL = /search|fetch|browse|research/i; // Tool identifiers that show the searching expression.
const ELLIPSIS = '…';

export function summarizeIslandTool(name, args) {
  const values = typeof args === 'string' ? [args] : TOOL_FIELDS.map(key => {
    const value = args?.[key];
    return typeof value === 'string' && PATH_FIELDS.has(key) ? value.split(/[\\/]/).pop() : value;
  });
  const value = values.find(item => typeof item === 'string' && item.trim());
  if (!value) return name;
  const detail = value.trim();
  return `${name} · ${detail.length > ISLAND_TOOL_DETAIL_LIMIT ? detail.slice(0, ISLAND_TOOL_DETAIL_LIMIT) + ELLIPSIS : detail}`;
}

const emptyThread = () => ({ running: false, error: '', log: [], messageId: null });
const finish = log => log.map(row => row.kind === 'chat' ? { ...row, streaming: false } : row);
const output = text => {
  const value = String(text || '');
  return value.length > ISLAND_TOOL_RESULT_LIMIT ? `${value.slice(0, ISLAND_TOOL_RESULT_LIMIT)}\n${ELLIPSIS} Output truncated. Open ANKITA for the full result.` : value;
};

export function hydrateIslandState(snapshot, pendingEvents = []) {
  const state = { threads: {} };
  for (const thread of snapshot.threads || []) {
    const log = (thread.messages || []).filter(message => !message.hidden).slice(-ISLAND_HISTORY_LIMIT).map(message => message.role === 'tool' ? {
      id: message.id, kind: 'tool', callId: message.callId, name: message.name,
      detail: summarizeIslandTool(message.name, message.args), args: message.args,
      state: message.isError ? 'error' : message.endedAt || message.result ? 'ok' : thread.running ? 'running' : 'ok',
      result: output(message.result),
    } : {
      id: message.id, kind: 'chat', role: message.role, content: message.content,
      job: message.job || null, attachments: message.attachments || [], streaming: false,
    });
    state.threads[thread.id] = { ...emptyThread(), running: thread.running === true, log };
  }
  const base = snapshot.state || state;
  return pendingEvents.filter(event => !Number.isFinite(event.sequence) || !Number.isFinite(snapshot.sequence) || event.sequence > snapshot.sequence)
    .reduce(reduceIslandState, base);
}

export function reduceIslandState(state, event) {
  if (!event.threadId) return state;
  const id = event.threadId;
  const thread = state.threads[id] || emptyThread();
  let next = thread;
  const messageId = event.messageId || thread.messageId;
  switch (event.type) {
    case 'turn-start': {
      const user = { id: event.turnId, kind: 'chat', role: 'user', content: event.text || '', attachments: event.attachments || [], streaming: false };
      next = { ...thread, running: true, error: '', messageId: null,
        log: event.source === 'routine' || thread.log.some(row => row.id === user.id) ? finish(thread.log) : [...finish(thread.log), user] };
      break;
    }
    case 'message-start': next = { ...thread, messageId }; break;
    case 'assistant-delta': {
      if (!messageId) return state;
      const existing = thread.log.find(row => row.kind === 'chat' && row.id === messageId);
      next = { ...thread, messageId, log: existing
        ? thread.log.map(row => row === existing ? { ...row, content: row.content + event.text, streaming: true } : row)
        : [...thread.log, { id: messageId, kind: 'chat', role: 'assistant', content: event.text, streaming: true, attachments: [] }] };
      break;
    }
    // Reasoning has its own engine channel; it must never become answer text.
    case 'reasoning-delta': return state;
    case 'message-reset': next = { ...thread, log: thread.log.filter(row => row.id !== messageId) }; break;
    case 'message-end': next = { ...thread, log: thread.log.map(row => row.id === messageId ? { ...row, streaming: false } : row) }; break;
    case 'tool-call': {
      if (thread.log.some(row => row.kind === 'tool' && row.callId === event.callId)) return state;
      next = { ...thread, running: true, log: [...thread.log, { id: event.callId, kind: 'tool', callId: event.callId,
        name: event.name, args: event.args, detail: summarizeIslandTool(event.name, event.args), state: 'running', result: '' }] };
      break;
    }
    case 'tool-result': next = { ...thread, log: thread.log.map(row => row.kind === 'tool' && row.callId === event.callId
      ? { ...row, state: event.isError ? 'error' : 'ok', result: output(event.text) } : row) }; break;
    case 'routine-result': {
      if (thread.log.some(row => row.id === event.messageId)) return state;
      next = { ...thread, log: [...thread.log, { id: event.messageId, kind: 'chat', role: 'assistant', content: event.content,
        streaming: false, job: { name: event.name, status: event.status, at: event.at }, attachments: [] }] };
      break;
    }
    case 'error': next = { ...thread, error: event.message, log: finish(thread.log) }; break;
    case 'turn-end': next = { ...thread, running: false, messageId: null, log: finish(thread.log).slice(-ISLAND_HISTORY_LIMIT) }; break;
    case 'thread-cleared': next = emptyThread(); break;
    default: return state;
  }
  return { ...state, threads: { ...state.threads, [id]: next } };
}

export function islandThreadState(thread) {
  if (!thread) return 'idle';
  if (thread.error) return 'error';
  if (!thread.running) return 'idle';
  const running = thread.log.filter(row => row.kind === 'tool' && row.state === 'running');
  if (running.some(row => islandToolState(row.name) === 'searching')) return 'searching';
  return running.length ? 'working' : 'thinking';
}

export function islandToolState(name) {
  return SEARCH_TOOL.test(name) ? 'searching' : 'working';
}
