import {
  SUBAGENT_TOOL,
  SUBAGENT_TYPES,
  SUBAGENT_LIMITS,
  presetFor,
  presetReadOnly,
} from '../src/core/subagents/registry.mjs';

export const name = SUBAGENT_TOOL;

// The schema ships in every request, so it stays compact: guidance that is
// longer than the call itself is context spent on every turn.
export const description =
  'Delegate a self-contained task to a sub-agent that cannot see this conversation. ' +
  'Set background=true to get an ID immediately, then use subagent_control to send, list, wait or cancel. Workers share a serialized workspace. Verify reports.';

export const parameters = {
  type: 'object',
  properties: {
    background: { type: 'boolean', description: 'Return immediately while the child works. Default false preserves blocking delegation.' },
    subagent_type: {
      type: 'string',
      enum: [...SUBAGENT_TYPES],
      description: 'Preset deciding child tools and role.',
    },
    description: {
      type: 'string',
      description: 'Short label for progress UI and logs.',
    },
    prompt: {
      type: 'string',
      description: 'Complete brief: goal, paths, constraints, verification, expected answer.',
    },
    max_steps: {
      type: 'integer',
      minimum: 1,
      maximum: SUBAGENT_LIMITS.maxToolSteps,
      description: 'Optional tool-step cap for this call; clamped to the configured limit.',
    },
    timeout_ms: {
      type: 'integer',
      minimum: SUBAGENT_LIMITS.minTimeoutMs,
      maximum: SUBAGENT_LIMITS.maxTimeoutMs,
      description: 'Optional wall-clock cap in milliseconds; clamped to the configured limit.',
    },
  },
  required: ['subagent_type', 'description', 'prompt'],
  additionalProperties: false,
};

export const readOnly = (args = {}) => presetReadOnly(args?.subagent_type);
export const needsApproval = false;

export function run(args, ctx) {
  const preset = presetFor(args?.subagent_type);
  if (!preset) return `Error: subagent_type must be one of ${SUBAGENT_TYPES.join(', ')}.`;
  if (typeof args?.prompt !== 'string' || !args.prompt.trim()) return 'Error: prompt must be a nonempty string describing the complete task.';
  if (!ctx?.runSubagent) return 'Error: sub-agents are unavailable in this execution context.';
  return ctx.runSubagent(args, ctx);
}
