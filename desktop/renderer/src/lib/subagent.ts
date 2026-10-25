import type { SubagentActivity } from '../../../shared/subagent-state.mjs';
import { summarizeArgs } from './format';

// Presentation only: long source URLs read cleaner without their scheme.
const URL_SCHEME = /^https?:\/\/(?:www\.)?/i;

export const SUBAGENT_TYPE_LABEL: Record<string, string> = {
  explore: 'Explore agent',
  reviewer: 'Review agent',
  worker: 'Worker agent',
};

export const SUBAGENT_STATUS_LABEL: Record<string, string> = {
  running: 'Working',
  completed: 'Done',
  failed: 'Failed',
  timeout: 'Timed out',
  cancelled: 'Cancelled',
  budget_exceeded: 'Budget reached',
  rejected: 'Not started',
};

export const SUBAGENT_TOOL_STATE_LABEL: Record<string, string> = {
  running: 'Running',
  ok: 'Done',
  error: 'Failed',
  stopped: 'Stopped',
};

// Terminal states that should read as a failure in the card and the panel.
export const SUBAGENT_FAILED_STATES = new Set(['failed', 'timeout', 'budget_exceeded', 'rejected']);

export type SubagentTone = 'running' | 'ok' | 'failed' | 'idle';

export function subagentTone(status: string): SubagentTone {
  if (status === 'running') return 'running';
  if (status === 'completed') return 'ok';
  return SUBAGENT_FAILED_STATES.has(status) ? 'failed' : 'idle';
}

export function subagentTypeLabel(type: string) {
  return SUBAGENT_TYPE_LABEL[type] || 'Sub-agent';
}

export function subagentStatusLabel(status: string) {
  return SUBAGENT_STATUS_LABEL[status] || status;
}

export function subagentTokens(activity: SubagentActivity) {
  return activity.usage ? (activity.usage.prompt_tokens || 0) + (activity.usage.completion_tokens || 0) : 0;
}

export function subagentTail(text: string, max: number) {
  const value = text.trim();
  return value.length > max ? `…${value.slice(-max)}` : value;
}

export function subagentToolHint(args: unknown) {
  return summarizeArgs(args).replace(URL_SCHEME, '');
}
