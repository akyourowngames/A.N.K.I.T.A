import { ChannelSurface } from './surface.mjs';
import { sessionKey } from './contract.mjs';
import { TELEGRAM_CHANNEL_ID } from '../manifests/telegram.mjs';

/** The daemon retains agent creation and routine permits; channel work uses one port. */
export class DaemonChannelSurface extends ChannelSurface {
  constructor(host) {
    const port = {}; super({ engine: port });
    this.host = host; this.running = new Map(); this.lastAgents = new Map();
    Object.assign(port, { agents: host.chatAgents, send: (...args) => this.send(...args), waitForTurn: target => this.waitForTurn(target), cancel: target => this.cancel(target), agentFor: target => host.chatAgent(target) });
  }
  targetFor(_teammateId, ref) { return ref.channel === TELEGRAM_CHANNEL_ID ? String(ref.chatId) : sessionKey(ref); }
  agentForTarget(target) { return this.host.chatAgent(target); }
  async send(target, text, { owner, ref, signal } = {}) {
    let acquired = false;
    const work = (async () => {
      acquired = await this.host.acquire();
      if (!acquired || this.host.stopping) throw new DOMException('Daemon stopped', 'AbortError');
      signal?.throwIfAborted();
      const agent = this.host.chatAgent(target), start = agent.messages?.length || 0;
      owner.agent = agent; this.lastAgents.set(target, agent); agent.browserCredentialAllowed = false;
      const publish = event => this.host.channelRuntimeFor(ref.channel).handleEngineEvent({ ...event, threadId: target });
      const reply = await agent.send(text, {
        onToolCall: call => {
          let args = {}; try { args = JSON.parse(call.function?.arguments || '{}'); } catch {}
          publish({ type: 'tool-call', callId: call.id, name: call.function?.name, args });
        },
        onToolResult: (call, result) => publish({ type: 'tool-result', callId: call.id, name: call.function?.name, text: String(result || ''), isError: /^Error\b/i.test(String(result || '')) }),
      });
      if (agent.messages) owner.artifacts.push(...agent.messages.slice(start));
      return reply;
    })().finally(() => { if (acquired) this.host.release(); this.running.delete(target); });
    this.running.set(target, work); void work.catch(() => {});
    return {};
  }
  waitForTurn(target) { return this.running.get(target) || Promise.resolve(); }
  cancel(target) { return (this.lastAgents.get(target) || this.host.chatAgents.get(target))?.cancel?.(); }
  workspaceFor(target) { return (this.lastAgents.get(target) || this.host.chatAgents.get(target))?.cwd || null; }
}
