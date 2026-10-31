import type { ChatMessage, EngineEvent, Model, Teammate, Routine } from '../../../shared/wire';
import type { Compat } from '../../../shared/version.mjs';
import type { SubagentState } from '../../../shared/subagent-state.mjs';
import { clearThreadSubagents, reduceSubagents } from '../../../shared/subagent-state.mjs';

export type Approval = Extract<EngineEvent, { type: 'approval-request' }>;
export type Usage = { prompt_tokens: number; completion_tokens: number; estimated_cost: number };
// One finished result waiting for the owning turn to end. Shape matches the
// scheduler's pendingDeliveries() and the routine-queued event detail.
export type PendingDelivery = { runId: string; routineId: string; name: string; status: string; at: string };
export type State = {
  jobs: Routine[];
  phase: string;
  chrome: string;
  teammates: Teammate[];
  models: Model[];
  settings: { username: string; provider: string; model: string; tools: string[] } | null;
  selectedId: string | null;
  threads: Record<string, ChatMessage[]>;
  running: Record<string, boolean>;
  loadedSkills: Record<string, string[]>;
  unread: Record<string, boolean>;
  usage: Record<string, Usage>;
  subagents: SubagentState;
  approvals: Approval[];
  deviceCode: { user_code: string; verification_uri: string } | null;
  error: string | null;
  compat: Compat | null;
  compatDismissed: boolean;
  // Results that finished while the owning teammate was busy. They wait for the
  // turn to end; the jobs panel lists them so the work is visible immediately.
  deliveries: Record<string, PendingDelivery[]>;
};

export const initialState: State = {
  jobs: [],
  phase: 'starting', chrome: 'custom', teammates: [], models: [], settings: null,
  selectedId: null, threads: {}, running: {}, loadedSkills: {}, unread: {}, usage: {}, subagents: {}, approvals: [],
  deviceCode: null, error: null, compat: null, compatDismissed: false, deliveries: {},
};

type Action =
  | { type: 'bootstrap'; teammates: Teammate[]; models: Model[]; settings: NonNullable<State['settings']>; chrome: string; selectedId?: string | null; jobs?: Routine[] }
  | { type: 'select'; id: string }
  | { type: 'thread-loaded'; id: string; messages: ChatMessage[] }
  | { type: 'teammates-loaded'; teammates: Teammate[] }
  | { type: 'approval-dismissed'; requestId: string }
  | { type: 'compat'; compat: Compat }
  | { type: 'compat-dismissed' }
  | { type: 'dismiss-error' }
  | { type: 'event'; event: EngineEvent };

function patchThread(state: State, threadId: string, update: (messages: ChatMessage[]) => ChatMessage[]): State {
  return { ...state, threads: { ...state.threads, [threadId]: update(state.threads[threadId] || []) } };
}

function keepSelection(state: State, teammates: Teammate[]): string | null {
  return state.selectedId && teammates.some(t => t.id === state.selectedId)
    ? state.selectedId
    : teammates[0]?.id || null;
}

export function reducer(state: State, action: Action): State {
  if (action.type === 'bootstrap') return {
    ...state, phase: 'ready', teammates: action.teammates, models: action.models, jobs: action.jobs || state.jobs,
    settings: action.settings, chrome: action.chrome,
    selectedId: action.selectedId && action.teammates.some(t => t.id === action.selectedId)
      ? action.selectedId
      : keepSelection(state, action.teammates),
  };
  if (action.type === 'select') return {
    ...state, selectedId: action.id, error: null,
    unread: { ...state.unread, [action.id]: false },
  };
  if (action.type === 'teammates-loaded') return { ...state, teammates: action.teammates, selectedId: keepSelection(state, action.teammates) };
  // The backend transcript is authoritative. Previously a non-empty in-memory
  // thread won, so a reload kept stale turns and old replies appeared to repeat;
  // now the loaded history always replaces what is shown.
  if (action.type === 'thread-loaded') return patchThread(state, action.id, () => action.messages);
  if (action.type === 'dismiss-error') return { ...state, error: null };
  if (action.type === 'approval-dismissed') return { ...state, approvals: state.approvals.filter(item => item.requestId !== action.requestId) };
  if (action.type === 'compat') return { ...state, compat: action.compat };
  if (action.type === 'compat-dismissed') return { ...state, compatDismissed: true };

  const event = action.event;
  if (event.type === 'schedule-changed') return { ...state, jobs: event.jobs };
  // Live run progress: the panel shows the step as it happens. No chat traffic.
  if (event.type === 'routine-run-start') return {
    ...state, jobs: state.jobs.map(job => job.id === event.routineId ? { ...job, running: true, step: 0, scope: event.scope || job.scope } : job),
  };
  if (event.type === 'routine-run-step') return {
    ...state, jobs: state.jobs.map(job => job.id === event.routineId ? { ...job, running: true, step: event.step ?? job.step } : job),
  };
  if (event.type === 'routine-run-end') return {
    ...state, jobs: state.jobs.map(job => job.id === event.routineId ? { ...job, running: false, lastStatus: event.status || job.lastStatus } : job),
  };
  // A finished result waiting for the owning turn. Both the direct queue notice
  // and the periodic delivery-state refresh land here so the list self-heals.
  if (event.type === 'routine-queued') {
    const list = state.deliveries[event.threadId || ''] || [];
    if (list.some(item => item.runId === event.runId)) return state;
    const job = state.jobs.find(item => item.id === event.routineId);
    const entry: PendingDelivery = { runId: event.runId, routineId: event.routineId, name: event.detail || job?.name || 'Scheduled task', status: event.status || 'ok', at: new Date().toISOString() };
    return { ...state, deliveries: { ...state.deliveries, [event.threadId || '']: [...list, entry] } };
  }
  if (event.type === 'routine-delivery-state') return { ...state, deliveries: { ...state.deliveries, [event.threadId || '']: event.pending || [] } };
  if (event.type === 'scheduler-error' || event.type === 'scheduler-stopped') return { ...state, error: event.message };
  if (event.type === 'routine-result') {
    const next = patchThread(state, event.threadId, messages => messages.map(message =>
      message.role === 'assistant' && message.id === event.messageId ? { ...message, content: event.content, job: event } : message));
    return { ...next, unread: { ...state.unread, [event.threadId]: state.selectedId !== event.threadId } };
  }
  if (event.type === 'status') return { ...state, phase: event.phase, deviceCode: event.phase === 'ready' ? null : state.deviceCode };
  if (event.type === 'settings-updated') return { ...state, settings: event.settings, models: event.models };
  if (event.type === 'auth-device-code') return { ...state, deviceCode: event };
  if (event.type === 'error') return { ...state, error: event.message, phase: state.phase === 'starting' ? 'error' : state.phase };
  if (event.type === 'approval-request') return event.routineId ? state : { ...state, approvals: [...state.approvals, event] };
  if (event.type === 'approval-resolved') return { ...state, approvals: state.approvals.filter(item => item.requestId !== event.requestId) };
  if (event.type === 'thread-cleared') return {
    ...state, threads: { ...state.threads, [event.threadId]: [] },
    loadedSkills: { ...state.loadedSkills, [event.threadId]: [] },
    usage: { ...state.usage, [event.threadId]: { prompt_tokens: 0, completion_tokens: 0, estimated_cost: 0 } },
    subagents: clearThreadSubagents(state.subagents, event.threadId),
  };
  if (event.type === 'turn-start') return {
    ...state,
    running: { ...state.running, [event.threadId]: true },
    loadedSkills: { ...state.loadedSkills, [event.threadId]: [] },
    threads: event.source === 'routine' ? state.threads : { ...state.threads, [event.threadId]: [...(state.threads[event.threadId] || []), { id: `user-${event.turnId}`, role: 'user', content: event.text, attachments: event.attachments }] },
  };
  if (event.type === 'turn-end') return {
    ...state,
    running: { ...state.running, [event.threadId]: false },
    unread: event.threadId === state.selectedId ? state.unread : { ...state.unread, [event.threadId]: true },
    approvals: state.approvals.filter(item => item.threadId !== event.threadId ||
      (item.voiceTaskId ? item.voiceTaskId !== event.turnId : event.source === 'voice')),
  };
  if (event.type === 'skills-loaded') return {
    ...state, loadedSkills: { ...state.loadedSkills, [event.threadId]: [...new Set([...(state.loadedSkills[event.threadId] || []), ...event.names])] },
  };
  if (event.type === 'message-start') return {
    ...state,
    threads: { ...state.threads, [event.threadId]: [...(state.threads[event.threadId] || []), { id: event.messageId, role: 'assistant', content: '', reasoning: '' }] },
  };
  if (event.type === 'message-reset') return patchThread(state, event.threadId, messages => messages.map(message =>
    message.id === event.messageId && message.role === 'assistant' ? { ...message, content: '', reasoning: '' } : message));
  if (event.type === 'assistant-delta') return patchThread(state, event.threadId, messages => messages.map(message =>
    message.id === event.messageId && message.role === 'assistant' ? { ...message, content: message.content + event.text } : message));
  if (event.type === 'reasoning-delta') {
    if (!event.messageId) return state;
    return patchThread(state, event.threadId, messages => messages.map(message =>
      message.id === event.messageId && message.role === 'assistant'
        ? { ...message, reasoning: (message.reasoning || '') + event.text }
        : message));
  }
  if (event.type === 'message-end') return patchThread(state, event.threadId, messages =>
    messages.filter(message => message.id !== event.messageId || message.role !== 'assistant' || Boolean(message.content) || Boolean(message.reasoning)));
  if (event.type === 'usage') {
    const previous = state.usage[event.threadId] || { prompt_tokens: 0, completion_tokens: 0, estimated_cost: 0 };
    return {
      ...state,
      usage: {
        ...state.usage,
        [event.threadId]: {
          prompt_tokens: previous.prompt_tokens + (event.prompt_tokens || 0),
          completion_tokens: previous.completion_tokens + (event.completion_tokens || 0),
          estimated_cost: previous.estimated_cost + (event.estimated_cost || 0),
        },
      },
    };
  }
  if (event.type === 'tool-call') return {
    ...state,
    threads: { ...state.threads, [event.threadId]: [...(state.threads[event.threadId] || []),
      { id: `tool-${event.callId}`, role: 'tool', callId: event.callId, name: event.name, args: event.args, result: '', isError: false, startedAt: Date.now() }] },
  };
  if (event.type === 'tool-result') return patchThread(state, event.threadId, messages => messages.map(message =>
    message.role === 'tool' && message.callId === event.callId ? { ...message, result: event.text, isError: event.isError, endedAt: Date.now() } : message));
  if (event.type.startsWith('subagent-')) return { ...state, subagents: reduceSubagents(state.subagents, event) };
  return state;
}
