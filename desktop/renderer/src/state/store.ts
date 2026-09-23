import type { ChatMessage, EngineEvent, Model, Teammate } from '../../../shared/wire';

export type Approval = Extract<EngineEvent, { type: 'approval-request' }>;
export type Usage = { prompt_tokens: number; completion_tokens: number; estimated_cost: number };
export type State = {
  phase: string;
  chrome: string;
  teammates: Teammate[];
  models: Model[];
  settings: { username: string; provider: string; model: string; tools: string[] } | null;
  selectedId: string | null;
  threads: Record<string, ChatMessage[]>;
  running: Record<string, boolean>;
  unread: Record<string, boolean>;
  usage: Record<string, Usage>;
  approvals: Approval[];
  deviceCode: { user_code: string; verification_uri: string } | null;
  error: string | null;
};

export const initialState: State = {
  phase: 'starting', chrome: 'custom', teammates: [], models: [], settings: null,
  selectedId: null, threads: {}, running: {}, unread: {}, usage: {}, approvals: [],
  deviceCode: null, error: null,
};

type Action =
  | { type: 'bootstrap'; teammates: Teammate[]; models: Model[]; settings: NonNullable<State['settings']>; chrome: string; selectedId?: string | null }
  | { type: 'select'; id: string }
  | { type: 'thread-loaded'; id: string; messages: ChatMessage[] }
  | { type: 'teammates-loaded'; teammates: Teammate[] }
  | { type: 'approval-dismissed'; requestId: string }
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
    ...state, phase: 'ready', teammates: action.teammates, models: action.models,
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
  if (action.type === 'thread-loaded') return state.threads[action.id]?.length
    ? state : patchThread(state, action.id, () => action.messages);
  if (action.type === 'dismiss-error') return { ...state, error: null };
  if (action.type === 'approval-dismissed') return { ...state, approvals: state.approvals.filter(item => item.requestId !== action.requestId) };

  const event = action.event;
  if (event.type === 'status') return { ...state, phase: event.phase, deviceCode: event.phase === 'ready' ? null : state.deviceCode };
  if (event.type === 'settings-updated') return { ...state, settings: event.settings, models: event.models };
  if (event.type === 'auth-device-code') return { ...state, deviceCode: event };
  if (event.type === 'error') return { ...state, error: event.message, phase: state.phase === 'starting' ? 'error' : state.phase };
  if (event.type === 'approval-request') return { ...state, approvals: [...state.approvals, event] };
  if (event.type === 'thread-cleared') return {
    ...state, threads: { ...state.threads, [event.threadId]: [] },
    usage: { ...state.usage, [event.threadId]: { prompt_tokens: 0, completion_tokens: 0, estimated_cost: 0 } },
  };
  if (event.type === 'turn-start') return {
    ...state,
    running: { ...state.running, [event.threadId]: true },
    threads: { ...state.threads, [event.threadId]: [...(state.threads[event.threadId] || []), { id: `user-${event.turnId}`, role: 'user', content: event.text }] },
  };
  if (event.type === 'turn-end') return {
    ...state,
    running: { ...state.running, [event.threadId]: false },
    unread: event.threadId === state.selectedId ? state.unread : { ...state.unread, [event.threadId]: true },
    approvals: state.approvals.filter(item => item.threadId !== event.threadId),
  };
  if (event.type === 'message-start') return {
    ...state,
    threads: { ...state.threads, [event.threadId]: [...(state.threads[event.threadId] || []), { id: event.messageId, role: 'assistant', content: '', reasoning: '' }] },
  };
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
  return state;
}
