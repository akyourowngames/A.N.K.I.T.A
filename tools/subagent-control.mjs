import {
  SUBAGENT_CONTROL_TOOL, SUBAGENT_MESSAGE_BYTES, SUBAGENT_MAX_WAIT_MS,
} from '../src/core/subagents/registry.mjs';

export const name = SUBAGENT_CONTROL_TOOL;
export const description = 'List, send messages to, wait for or cancel your background children. Children can only send to subagent_id="parent". Messages arrive at the next model decision.';
export const parameters = {
  type: 'object',
  properties: {
    action: { type: 'string', enum: ['list', 'send', 'wait', 'cancel'] },
    subagent_id: { type: 'string', description: 'Child ID from delegate_task, or parent when called by a child.' },
    message: { type: 'string', maxLength: SUBAGENT_MESSAGE_BYTES },
    wait_ms: { type: 'integer', minimum: 0, maximum: SUBAGENT_MAX_WAIT_MS },
  },
  required: ['action'],
  additionalProperties: false,
};
// This changes only runtime mailboxes, never workspace or external state.
export const readOnly = true;
export const needsApproval = false;
export function run(args, ctx) {
  if (typeof ctx?.subagentControl !== 'function') return 'Error: sub-agent controls are unavailable in this execution context.';
  return ctx.subagentControl(args, ctx);
}
