import fs from 'node:fs';
import path from 'node:path';
import { createHash, randomUUID } from 'node:crypto';
import { ChannelSurface } from '../../src/channels/core/surface.mjs';
import { CHANNEL_TOOL_CALLS, CHANNEL_SESSION_PREFIX, sessionKey } from '../../src/channels/core/contract.mjs';
import { TELEGRAM_CHANNEL_ID } from '../../src/channels/manifests/telegram.mjs';
import { sanitizeMessages } from '../../src/core/history.mjs';
import { saveSession, recordTurn } from '../../src/core/sessions.mjs';
import { CHATGPT_BROWSER_PROVIDER } from '../shared/chatgpt-browser.mjs';
import { CHANNEL_API_REQUIRED_MESSAGE } from '../shared/channel-settings.mjs';

const CHANNEL_SESSIONS_DIRECTORY = 'channels'; // Child conversations stay separate from desktop teammate files.
const CHANNEL_SESSION_CACHE_LIMIT = 64; // In-memory agents: inactive sessions restore from disk instead of accumulating.

/** Keep legacy Telegram DMs; isolate every group and additional platform's history. */
export class DesktopChannelSurface extends ChannelSurface {
  constructor({ engine }) { super({ engine }); this.agents = new Map(); this.privateTurns = new Map(); this.targets = new Map(); this.dirty = new Set(); }
  assertReady() { if (this.engine?.config?.provider === CHATGPT_BROWSER_PROVIDER) throw new Error(CHANNEL_API_REQUIRED_MESSAGE); }
  busy(teammateId = null) { return [...this.privateTurns.keys()].some(target => !teammateId || this.targets.get(target)?.teammateId === teammateId); }
  invalidate(teammateId = null) {
    for (const [target, binding] of this.targets) if (!teammateId || binding.teammateId === teammateId) {
      this.dirty.add(target); if (!this.privateTurns.has(target)) this.agents.delete(target);
    }
  }
  targetFor(teammateId, ref) {
    if (!this.engine?.AgentClass || (ref.channel === TELEGRAM_CHANNEL_ID && !ref.raw?.isGroup)) return teammateId;
    const hash = createHash('sha256').update(JSON.stringify([sessionKey(ref), teammateId])).digest('hex');
    const target = CHANNEL_SESSION_PREFIX + hash;
    this.targets.set(target, { teammateId, ref });
    return target;
  }
  sessionFile(target) { return path.join(this.engine.sessionsDir, CHANNEL_SESSIONS_DIRECTORY, `${target}.json`); }
  agentForTarget(target, toolBudget) { this.assertReady(); return this.targets.has(target) ? this.privateAgent(target, toolBudget) : this.engine.agentFor?.(target) || super.agentForTarget(target); }
  privateAgent(target, toolBudget) {
    if (this.dirty.has(target) && !this.privateTurns.has(target)) { this.agents.delete(target); this.dirty.delete(target); }
    if (this.agents.has(target)) { const agent = this.agents.get(target); this.agents.delete(target); this.agents.set(target, agent); return agent; }
    if (this.agents.size >= CHANNEL_SESSION_CACHE_LIMIT) {
      const oldest = [...this.agents.keys()].find(id => !this.privateTurns.has(id));
      if (!oldest) throw new Error('Channel sessions are busy; retry after a request finishes');
      this.agents.delete(oldest);
    }
    const { teammateId } = this.targets.get(target), parent = this.engine.agentFor(teammateId);
    const config = { ...this.engine.config, agentName: parent.config?.agentName, systemExtra: parent.config?.systemExtra,
      subagentsEnabled: false, maxToolCalls: Math.min(this.engine.config?.maxToolCalls || CHANNEL_TOOL_CALLS, toolBudget || CHANNEL_TOOL_CALLS) };
    const agent = new this.engine.AgentClass({
      client: this.engine.client, tool: this.engine.tool, mcp: this.engine.mcp, config,
      project: parent.project, projectId: parent.projectId, workspacePath: parent.cwd, autoProject: false,
      skillsEnabled: true, disabledSkills: this.engine.desktopSettings?.data?.disabledSkills || [],
      browserManager: this.engine.browserManager, browserThreadId: target,
      toolContext: { scheduler: this.engine.schedule?.(), scheduleThreadId: teammateId, projectsFile: this.engine.projectsFile },
      confirm: (name, detail, metadata) => this.engine.approvals.request(target, name, detail, metadata),
      journal: turn => recordTurn(turn, { timeZone: config.timeZone, transform: this.engine.secretHistory?.clean }),
      print: () => {}, write: () => {},
    });
    agent.model = parent.model; agent.browserCredentialAllowed = false;
    try {
      const saved = JSON.parse(fs.readFileSync(this.sessionFile(target), 'utf8'));
      agent.messages.push(...sanitizeMessages((saved.messages || []).filter(message => message.role !== 'system')));
      agent.state ||= {}; agent.state.todos = saved.todos || [];
    } catch (error) { if (error.code !== 'ENOENT') this.engine.emit({ type: 'error', threadId: target, message: 'This channel history could not be restored.' }); }
    this.agents.set(target, agent); return agent;
  }
  async send(target, text, { toolBudget, signal } = {}) {
    if (!this.targets.has(target)) return super.send(target, text);
    if (this.privateTurns.has(target)) throw new Error('This channel session is already replying');
    const agent = this.privateAgent(target, toolBudget), turnId = randomUUID();
    agent.config.maxToolCalls = Math.min(this.engine.config?.maxToolCalls || CHANNEL_TOOL_CALLS, toolBudget || CHANNEL_TOOL_CALLS);
    agent.browserCredentialAllowed = false;
    const emit = event => this.engine.emit(this.engine.secretHistory?.clean?.({ ...event, threadId: target, turnId }) || { ...event, threadId: target, turnId });
    const work = Promise.resolve().then(async () => {
      signal?.throwIfAborted();
      emit({ type: 'turn-start' });
      return agent.send(text, {
        onToolCall: call => {
          let args = {}; try { args = JSON.parse(call.function?.arguments || '{}'); } catch {}
          emit({ type: 'tool-call', callId: call.id, name: call.function?.name, args });
        },
        onToolResult: (call, result) => emit({ type: 'tool-result', callId: call.id, name: call.function?.name, text: String(result || ''), isError: /^Error\b/i.test(String(result || '')) }),
      });
    }).finally(() => {
      agent.browserCredentialAllowed = false;
      saveSession(this.sessionFile(target), { savedAt: new Date().toISOString(), model: agent.model, messages: agent.messages, todos: agent.state?.todos || [], projectId: agent.projectId, journaled: agent.journalComplete }, { transform: this.engine.secretHistory?.clean });
      this.privateTurns.delete(target); this.engine.approvals.cancelThread(target);
      emit({ type: 'turn-end' });
    });
    this.privateTurns.set(target, work); void work.catch(() => {}); return { turnId };
  }
  waitForTurn(target) { return this.targets.has(target) ? this.privateTurns.get(target) || Promise.resolve() : super.waitForTurn(target); }
  cancel(target) { return this.targets.has(target) ? this.agents.get(target)?.cancel() : super.cancel(target); }
  workspaceFor(target) { return this.targets.has(target) ? this.agents.get(target)?.cwd || null : super.workspaceFor(target); }
}
