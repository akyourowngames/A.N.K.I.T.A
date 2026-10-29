import { ChannelInbox } from './inbox.mjs';
import { sessionKey, CHANNEL_TOOL_CALLS, CHANNEL_MAX_CONCURRENT } from './contract.mjs';

/** Agent-side port. The shared gate prevents two transports claiming one turn. */
export class ChannelSurface {
  constructor({ engine }) { this.engine = engine; this.turns = new ChannelInbox({ maxConcurrent: CHANNEL_MAX_CONCURRENT }); this.owners = new Map(); }
  agentForTarget(target) { return this.engine.agents?.get(target); }
  targetFor(teammateId) { return teammateId; }
  send(target, text) { return this.engine.send(target, text, null, { surface: 'channel' }); }
  waitForTurn(target) { return this.engine.waitForTurn(target); }
  cancel(target) { return this.engine.cancel?.(target); }
  respondApproval(requestId, answer) { return this.engine.respondApproval?.(requestId, answer); }
  workspaceFor(target) { return (this.engine.agents?.get(target) || this.engine.agentFor?.(target))?.cwd || null; }
  owns(target, owner) { return this.owners.get(target) === owner; }
  async run(ref, target, text, owner, { signal, toolBudget = CHANNEL_TOOL_CALLS, claimed = () => {}, released = () => {} } = {}) {
    return this.turns.enqueue(sessionKey(ref), async () => {
      signal?.throwIfAborted();
      if (this.engine.turns?.has(target)) { await this.waitForTurn(target); signal?.throwIfAborted(); }
      const cancel = () => this.cancel(target);
      signal?.addEventListener('abort', cancel, { once: true });
      const agent = this.agentForTarget(target, toolBudget);
      const previousBudget = agent?.config?.maxToolCalls;
      if (agent?.config) agent.config.maxToolCalls = Math.min(previousBudget || CHANNEL_TOOL_CALLS, toolBudget);
      this.owners.set(target, owner); claimed();
      try {
        try { await this.send(target, text, { ref, toolBudget, signal, owner }); }
        catch (error) {
          if (!/already replying/i.test(String(error.message))) throw error;
          await this.waitForTurn(target); signal?.throwIfAborted();
          await this.send(target, text, { ref, toolBudget, signal, owner });
        }
        return await this.waitForTurn(target);
      } finally {
        signal?.removeEventListener('abort', cancel);
        if (agent?.config) agent.config.maxToolCalls = previousBudget;
        if (this.owners.get(target) === owner) this.owners.delete(target);
        released();
      }
    }, { target, signal });
  }
}
