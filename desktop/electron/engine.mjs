import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { randomUUID } from 'node:crypto';
import { Agent } from '../../src/agent.mjs';
import { loadConfig, ensureDirs, CONFIG_DIR, SESSIONS_DIR, MCP_FILE, COMPOSIO_FILE } from '../../src/config.mjs';
import { createSession } from '../../src/bootstrap.mjs';
import { McpManager } from '../../src/mcp-manager.mjs';
import { McpStore } from '../../src/mcp-store.mjs';
import { ComposioStore } from '../../src/composio-store.mjs';
import { ProjectStore } from '../../src/projects.mjs';
import { PROJECTS_FILE } from '../../src/config.mjs';
import { saveSession, recordTurn } from '../../src/sessions.mjs';
import { sanitizeMessages } from '../../src/history.mjs';
import { displayArgs } from '../../tools/index.mjs';
import { TeammateStore } from './teammates.mjs';
import { ApprovalRegistry } from './approvals.mjs';
import { DesktopSettingsStore, applyDesktopSettings, testCustomProvider } from './settings.mjs';
import { DesktopPlugins } from './plugins.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');

function messageText(value) {
  if (typeof value === 'string') return value;
  if (Array.isArray(value)) return value.filter(item => item?.type === 'text').map(item => item.text || '').join('\n');
  return '';
}

/** Map provider history into a transcript without passing system prompts to the renderer. */
export function threadMessages(messages = []) {
  const out = [];
  const byCall = new Map();
  for (let i = 0; i < messages.length; i++) {
    const entry = messages[i];
    if (entry.role === 'system') continue;
    if (entry.role === 'user' || entry.role === 'assistant') {
      const content = messageText(entry.content);
      if (content) out.push({ id: `message-${i}`, role: entry.role, content });
      for (const call of entry.tool_calls || []) {
        let args = {};
        try { args = JSON.parse(call.function?.arguments || '{}'); } catch {}
        const name = call.function?.name || 'tool';
        const tool = { id: `tool-${call.id || i}`, role: 'tool', callId: call.id, name, args: displayArgs(name, args), result: '', isError: false };
        byCall.set(call.id, tool);
        out.push(tool);
      }
    } else if (entry.role === 'tool') {
      const tool = byCall.get(entry.tool_call_id);
      if (tool) {
        tool.result = messageText(entry.content);
        tool.isError = /^Error\b/i.test(tool.result);
      }
    }
  }
  return out;
}

export class DesktopEngine {
  constructor({
    teammateFile = path.join(CONFIG_DIR, 'desktop-teammates.json'),
    settingsFile = path.join(CONFIG_DIR, 'desktop-settings.json'),
    composioFile = COMPOSIO_FILE,
    sessionsDir = SESSIONS_DIR,
    envPath = path.join(root, '.env'),
    config = null,
    bootstrap = createSession,
    AgentClass = Agent,
    mcp = null,
    emit = () => {},
  } = {}) {
    this.teammates = new TeammateStore(teammateFile);
    this.desktopSettings = new DesktopSettingsStore(settingsFile);
    this.composioFile = composioFile;
    this.plugins = new DesktopPlugins({ getConfig: () => this.config || {}, storeFile: composioFile, isLive: () => Boolean(this.mcp?.has?.('composio')) });
    this.sessionsDir = sessionsDir;
    this.envPath = envPath;
    this.config = config;
    this.bootstrap = bootstrap;
    this.AgentClass = AgentClass;
    this.mcp = mcp || new McpManager({ onChange: () => this.emit({ type: 'tools-changed', connected: this.mcp?.connectedIds || [] }) });
    this.emit = emit;
    this.agents = new Map();
    this.turns = new Map();
    this.approvals = new ApprovalRegistry(event => this.emit({ type: 'approval-request', ...event }));
    this.ready = null;
  }

  async init() {
    if (this.ready) return this.ready;
    this.ready = this._init();
    return this.ready;
  }

  async _init() {
    ensureDirs();
    this.desktopSettings.load();
    this.baseConfig = this.config || loadConfig(this.envPath);
    this.config = applyDesktopSettings(this.baseConfig, this.desktopSettings.data);
    this.teammates.load();
    this.emit({ type: 'status', phase: 'authenticating' });
    try {
      const session = await this.bootstrap({ config: this.config, onDeviceCode: details => this.emit({ type: 'auth-device-code', ...details }) });
      this.client = session.client;
      this.tool = session.tool;
      this.models = session.models;
      this.model = session.model;
      this.provider = session.provider;
      this.emit({ type: 'status', phase: this.client ? 'ready' : 'error' });
    } catch (error) {
      this.client = null;
      this.tool = null;
      this.models = [];
      this.model = '';
      this.provider = { name: this.desktopSettings.data.provider || this.baseConfig.provider || 'copilot' };
      this.emit({ type: 'error', threadId: null, message: `Provider unavailable: ${error.message}. Open Settings to fix the connection.` });
      this.emit({ type: 'status', phase: 'error' });
    }
    // External servers may be slow to start. Make chat usable as soon as the model is ready.
    void this.connectTools();
    return this;
  }

  async connectTools() {
    try {
      this.emit({ type: 'status', phase: 'connecting-tools' });
      await this.mcp.reconcile(new McpStore(MCP_FILE).load());
      if (this.mcp.ensureComposio) {
        await this.mcp.ensureComposio(this.config, new ComposioStore(this.composioFile).load());
      }
      this.emit({ type: 'tools-changed', connected: this.mcp.connectedIds || [] });
      this.emit({ type: 'status', phase: this.client ? 'ready' : 'error' });
    } catch (err) {
      this.emit({ type: 'error', threadId: null, message: `Could not connect tools: ${err.message}` });
      this.emit({ type: 'status', phase: this.client ? 'ready' : 'error' });
    }
  }

  getSettingsSummary() {
    let version = '';
    try { version = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8')).version || ''; } catch {}
    return {
      username: this.config?.username || '',
      provider: this.provider?.name || 'copilot',
      model: this.model,
      tools: this.mcp.connectedIds || [],
      version,
      configDir: CONFIG_DIR,
    };
  }

  getDesktopPreferences() { return this.desktopSettings.publicView(this.config || {}); }

  async refreshPlugins() {
    if (this.mcp.ensureComposio) {
      try {
        await this.mcp.ensureComposio(this.config, new ComposioStore(this.composioFile).load());
        this.emit({ type: 'tools-changed', connected: this.mcp.connectedIds || [] });
      } catch (error) {
        this.emit({ type: 'error', threadId: null, message: `Could not refresh connected apps: ${error.message}` });
      }
    }
    return this.plugins.overview();
  }

  settingsPayload() {
    return { preferences: this.getDesktopPreferences(), settings: this.getSettingsSummary(), models: this.listModels() };
  }

  async saveDesktopSettings(patch) {
    const next = this.desktopSettings.preview(patch);
    if (Object.hasOwn(patch, 'provider') && patch.provider !== this.provider?.name && !Object.hasOwn(patch, 'model')) next.model = '';
    const nextConfig = applyDesktopSettings(this.baseConfig, next);
    const active = this.provider?.name || 'copilot';
    const reconnect = ['provider', 'customApiBase'].some(key => Object.hasOwn(patch, key))
      || (active === 'custom' && Object.hasOwn(patch, 'customApiKey'))
      || (active === 'groq' && Object.hasOwn(patch, 'groqApiKey'))
      || (active === 'kilo' && Object.hasOwn(patch, 'kiloApiKey'));
    if ((reconnect || Object.hasOwn(patch, 'model')) && this.turns.size) throw new Error('Wait for active replies to finish before changing the provider or model');
    if (reconnect) {
      const session = await this.bootstrap({ config: nextConfig, onDeviceCode: details => this.emit({ type: 'auth-device-code', ...details }) });
      this.desktopSettings.save(next);
      this.config = nextConfig;
      this.client = session.client;
      this.tool = session.tool;
      this.models = session.models;
      this.model = session.model;
      this.provider = session.provider;
      this.agents.clear();
      this.emit({ type: 'status', phase: 'ready' });
    } else if (Object.hasOwn(patch, 'model')) {
      const selected = this.models.find(model => model.id === patch.model);
      if (!selected) throw new Error('Choose a model from the available list');
      if (this.config.tools && selected.tools === false) throw new Error('This model cannot use tools');
      this.desktopSettings.save(next);
      this.config.model = selected.id;
      this.model = selected.id;
      for (const [id, agent] of this.agents) if (!this.teammates.find(id)?.model) agent.model = selected.id;
    } else {
      this.desktopSettings.save(next);
    }
    if (Object.hasOwn(patch, 'composioApiKey')) {
      this.config.composioApiKey = nextConfig.composioApiKey;
      void this.connectTools();
    }
    const payload = this.settingsPayload();
    this.emit({ type: 'settings-updated', ...payload });
    return payload;
  }

  testCustomProvider(input = {}) {
    const apiBase = input.apiBase || this.desktopSettings.data.customApiBase || (this.provider?.name === 'custom' ? this.config.apiBase : '');
    const activeBase = this.desktopSettings.data.customApiBase || (this.provider?.name === 'custom' ? this.config.apiBase : '');
    // A saved key belongs to its saved endpoint. Do not send it to a newly entered URL.
    const savedKey = apiBase === activeBase ? this.desktopSettings.data.customApiKey || (this.provider?.name === 'custom' ? this.config.apiKey : '') : '';
    const apiKey = Object.hasOwn(input, 'apiKey') ? input.apiKey : savedKey;
    return testCustomProvider({ apiBase, apiKey });
  }

  listModels() { return (this.models || []).map(({ id, name, vendor, context, tools }) => ({ id, name, vendor, context, tools })); }
  listTeammates() { return this.teammates.load().list(); }
  createTeammate(input) { const item = this.teammates.create(input); this.emit({ type: 'teammates-changed' }); return item; }
  updateTeammate(id, patch) {
    const item = this.teammates.update(id, patch);
    const agent = this.agents.get(id);
    if (agent) {
      agent.config.agentName = item.name;
      agent.config.systemExtra = item.persona;
      if (item.model) agent.model = item.model;
      agent.refreshPrompt?.();
    }
    this.emit({ type: 'teammates-changed' });
    return item;
  }
  setModel(id, modelId) {
    const found = this.models.find(model => model.id === modelId);
    if (!found) throw new Error('Model not found');
    if (this.config.tools && found.tools === false) throw new Error('This model cannot use tools');
    const item = this.updateTeammate(id, { model: modelId });
    this.emit({ type: 'model-changed', threadId: id, model: modelId });
    return item;
  }

  sessionFile(id) { return path.join(this.sessionsDir, `teammate-${id}.json`); }

  _rawThread(id) {
    if (!this.teammates.find(id)) throw new Error('Teammate not found');
    try {
      const saved = JSON.parse(fs.readFileSync(this.sessionFile(id), 'utf8'));
      return sanitizeMessages((saved.messages || []).filter(message => message.role !== 'system'));
    } catch (err) {
      if (err.code === 'ENOENT') return [];
      throw err;
    }
  }

  loadThread(id) {
    const agent = this.agents.get(id);
    return threadMessages(agent ? agent.messages : this._rawThread(id));
  }

  agentFor(id) {
    if (!this.client) throw new Error('Set up a provider in Settings before sending a message');
    const item = this.teammates.find(id);
    if (!item) throw new Error('Teammate not found');
    if (this.agents.has(id)) return this.agents.get(id);
    const config = { ...this.config, agentName: item.name, systemExtra: item.persona };
    let project = '', projectId = null;
    if (item.projectId) {
      const projects = new ProjectStore(PROJECTS_FILE).load();
      const selected = projects.find(item.projectId);
      if (selected) {
        projects.data.active = selected.id;
        project = projects.promptBlock();
        projectId = selected.id;
      }
    }
    const agent = new this.AgentClass({
      client: this.client, tool: this.tool, mcp: this.mcp, config, project, projectId,
      journal: turn => recordTurn(turn, { timeZone: config.timeZone }),
      confirm: (name, detail) => this.approvals.request(id, name, detail),
      print: () => {}, write: () => {},
    });
    agent.model = item.model && this.models.some(model => model.id === item.model) ? item.model : this.model;
    agent.messages.push(...this._rawThread(id));
    this.agents.set(id, agent);
    return agent;
  }

  async send(id, text) {
    const prompt = String(text || '').trim();
    if (!prompt) throw new Error('Write a message first');
    if (this.turns.has(id)) throw new Error('This teammate is already replying');
    const agent = this.agentFor(id);
    const turnId = randomUUID();
    this.emit({ type: 'turn-start', threadId: id, turnId, model: agent.model, text: prompt });
    let currentMessageId = null;
    const callbacks = {
      onMessageStart: () => { currentMessageId = randomUUID(); this.emit({ type: 'message-start', threadId: id, messageId: currentMessageId }); },
      onMessageEnd: () => this.emit({ type: 'message-end', threadId: id, messageId: currentMessageId }),
      onDelta: delta => this.emit({ type: 'assistant-delta', threadId: id, messageId: currentMessageId, text: delta }),
      onReasoning: delta => this.emit({ type: 'reasoning-delta', threadId: id, messageId: currentMessageId, text: delta }),
      onUsage: usage => this.emit({ type: 'usage', threadId: id, ...usage }),
      onToolCall: call => {
        const name = call.function?.name || 'tool';
        let args = {};
        try { args = JSON.parse(call.function?.arguments || '{}'); } catch {}
        this.emit({ type: 'tool-call', threadId: id, callId: call.id, name, args: displayArgs(name, args) });
      },
      onToolResult: (call, result) => this.emit({ type: 'tool-result', threadId: id, callId: call.id, text: String(result || ''), isError: /^Error\b/i.test(String(result || '')) }),
    };
    const work = Promise.resolve().then(() => agent.send(prompt, callbacks)).then(reply => {
      this.teammates.touch(id, reply || prompt);
      this.emit({ type: 'teammates-changed' });
      return reply;
    }).catch(err => {
      this.emit({ type: 'error', threadId: id, message: err.message || String(err) });
      throw err;
    }).finally(() => {
      saveSession(this.sessionFile(id), { savedAt: new Date().toISOString(), model: agent.model, messages: agent.messages, projectId: agent.projectId, journaled: agent.journalComplete });
      this.turns.delete(id);
      this.approvals.cancelThread(id);
      this.emit({ type: 'turn-end', threadId: id, turnId });
    });
    this.turns.set(id, work);
    // IPC returns immediately; errors are delivered as events and observed here.
    void work.catch(() => {});
    return { turnId };
  }

  waitForTurn(id) { return this.turns.get(id) || Promise.resolve(); }

  cancel(id) {
    this.approvals.cancelThread(id);
    return this.agents.get(id)?.cancel() || false;
  }

  respondApproval(requestId, answer) {
    const entry = this.approvals.pending.get(requestId);
    if (!entry) return false;
    if (answer === 'always') {
      const agent = this.agents.get(entry.threadId);
      if (agent) agent.autoApprove = true;
    }
    return this.approvals.respond(requestId, answer);
  }

  clearThread(id) {
    if (this.turns.has(id)) throw new Error('Stop the reply before clearing this thread');
    const agent = this.agents.get(id);
    agent?.clear();
    try { fs.unlinkSync(this.sessionFile(id)); } catch (err) { if (err.code !== 'ENOENT') throw err; }
    this.teammates.touch(id, '');
    this.emit({ type: 'thread-cleared', threadId: id });
    this.emit({ type: 'teammates-changed' });
    return true;
  }

  async deleteTeammate(id) {
    if (this.turns.has(id)) {
      this.cancel(id);
      await this.turns.get(id)?.catch(() => {});
    }
    this.agents.delete(id);
    const removed = this.teammates.delete(id);
    if (removed) {
      try { fs.unlinkSync(this.sessionFile(id)); } catch (err) { if (err.code !== 'ENOENT') throw err; }
      this.emit({ type: 'teammates-changed' });
    }
    return removed;
  }

  async close() {
    this.approvals.cancelAll();
    for (const id of this.turns.keys()) this.agents.get(id)?.cancel();
    await this.mcp.closeAll();
  }
}
