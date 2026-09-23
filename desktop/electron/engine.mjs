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
import { ChannelStore, ChannelManager } from './channels.mjs';
import { TelegramBot } from '../../src/telegram.mjs';
import { DesktopPlugins } from './plugins.mjs';
import { projectContext, projectSummary, projectWorkspace } from './projects.mjs';
import { changedFiles, fileDiff, recentArtifacts, jobList, stopAgentJob, captureToolFiles, completedFileDiffs } from './workspace.mjs';

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
    channelsFile = path.join(CONFIG_DIR, 'desktop-channels.json'),
    composioFile = COMPOSIO_FILE,
    sessionsDir = SESSIONS_DIR,
    projectsFile = PROJECTS_FILE,
    envPath = path.join(root, '.env'),
    config = null,
    bootstrap = createSession,
    AgentClass = Agent,
    mcp = null,
    telegramBotFactory = null,
    emit = () => {},
  } = {}) {
    this.teammates = new TeammateStore(teammateFile);
    this.desktopSettings = new DesktopSettingsStore(settingsFile);
    this.channelsFile = channelsFile;
    this.telegramBotFactory = telegramBotFactory;
    this.composioFile = composioFile;
    this.plugins = new DesktopPlugins({ getConfig: () => this.config || {}, storeFile: composioFile, isLive: () => Boolean(this.mcp?.has?.('composio')) });
    this.sessionsDir = sessionsDir;
    this.projectsFile = projectsFile;
    this.envPath = envPath;
    this.config = config;
    this.bootstrap = bootstrap;
    this.AgentClass = AgentClass;
    this.mcp = mcp || new McpManager({ onChange: () => this.emit({ type: 'tools-changed', connected: this.mcp?.connectedIds || [] }) });
    // Keep the raw sink separate so the channel bridge can observe every event
    // (approvals included) without the emit path calling back into itself.
    this._emit = emit;
    this.emit = (event) => {
      try { this._emit(event); } catch {}
      try { this.channels?.handleEngineEvent(event); } catch {}
    };
    this.agents = new Map();
    this.reviewChanges = new Map();
    this.pendingFileEdits = new Map();
    this.turns = new Map();
    this.approvals = new ApprovalRegistry(event => this.emit({ type: 'approval-request', ...event }));
    this.channels = new ChannelManager({
      store: new ChannelStore(channelsFile),
      engine: this,
      getConfig: () => this.config || {},
      emit: event => this.emit(event),
      log: message => { try { console.error('[channels]', message); } catch {} },
      ...(telegramBotFactory ? { botFactory: telegramBotFactory } : {}),
    });
    this.projectFileVersion = null;
    this.projectFileWatcher = null;
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
    this.channels.load();
    this.watchProjects();
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
    // Channels are opt-in: only an enabled, configured one opens its inbox.
    void this.channels.startEnabled().catch(err => this.emit({ type: 'error', threadId: null, message: `Could not start channels: ${err.message}` }));
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
    const tune = ['contextWindow', 'maxTokens'].some(key => Object.hasOwn(patch, key));
    if ((reconnect || Object.hasOwn(patch, 'model') || tune) && this.turns.size) throw new Error('Wait for active replies to finish before changing the provider or model');
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
    // The context window and output cap are per-agent state, not a connection
    // setting: apply them to live agents instead of tearing the session down.
    if (tune) {
      const window = {
        contextWindow: nextConfig.contextWindow, contextWindowExplicit: nextConfig.contextWindowExplicit,
        maxTokens: nextConfig.maxTokens, maxTokensExplicit: nextConfig.maxTokensExplicit,
      };
      Object.assign(this.config, window);
      for (const agent of this.agents.values()) {
        Object.assign(agent.config, window);
        agent.contextWindow = nextConfig.contextWindow;
      }
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

  getChannels() { return this.channels.publicView(); }

  async saveChannelSettings(channel, patch) {
    if (channel !== 'telegram') throw new Error('Unknown channel');
    const next = this.channels.store.preview(patch).telegram;
    if (next.teammateId && !this.teammates.find(next.teammateId)) throw new Error('Choose an available teammate');
    const view = await this.channels.save(patch);
    return view;
  }

  /** Verifies a bot token without persisting it or starting the bridge. */
  async testTelegramChannel(input = {}) {
    const token = String(input.token || '').trim() || this.channels.store.telegram().token;
    if (!token) throw new Error('Enter a bot token first');
    const bot = (this.telegramBotFactory || (options => new TelegramBot(options)))({ token });
    const me = await bot.whoami();
    return { username: me?.username || null, name: [me?.first_name, me?.last_name].filter(Boolean).join(' ') || null };
  }

  listModels() { return (this.models || []).map(({ id, name, vendor, context, tools }) => ({ id, name, vendor, context, tools })); }
  listTeammates() { return this.teammates.load().list(); }
  async workspaceSnapshot(id) {
    const agent = this.agents.get(id);
    const cwd = agent?.cwd || projectWorkspace(new ProjectStore(this.projectsFile).load().find(this.teammates.find(id)?.projectId)) || process.cwd();
    const changes = await changedFiles(cwd);
    const seen = new Set(changes.files.map(item => item.path));
    for (const file of this.reviewChanges.get(id)?.keys() || []) {
      const relative = path.relative(changes.root, file).split(path.sep).join('/');
      if (!relative.startsWith('..') && !seen.has(relative)) changes.files.push({ path: relative, status: ' M', untracked: false, captured: true });
    }
    return { ...changes, cwd, artifacts: recentArtifacts(cwd, this.loadThread(id)), jobs: jobList(agent) };
  }
  async workspaceDiff(id, file) {
    const snapshot = await this.workspaceSnapshot(id);
    const captured = this.reviewChanges.get(id)?.get(path.resolve(snapshot.root, file));
    if (captured && snapshot.files.find(item => item.path === file && item.captured)) return captured;
    return fileDiff(snapshot.cwd, file);
  }
  stopWorkspaceJob(id, jobId) { return stopAgentJob(this.agents.get(id), jobId); }
  listProjects() { return new ProjectStore(this.projectsFile).load().projects.map(projectSummary); }
  watchProjects() {
    if (this.projectFileWatcher) return;
    const read = () => { try { return fs.readFileSync(this.projectsFile, 'utf8'); } catch (err) { if (err.code === 'ENOENT') return ''; throw err; } };
    this.projectFileVersion = read();
    this.projectFileWatcher = () => {
      let next;
      try { next = read(); } catch { return; }
      if (next === this.projectFileVersion) return;
      this.projectFileVersion = next;
      try {
        for (const projectId of new Set(this.teammates.list().map(item => item.projectId).filter(Boolean))) this.refreshProjectAgents(projectId);
        this.emit({ type: 'projects-changed' });
      } catch (err) { this.emit({ type: 'error', threadId: null, message: `Could not refresh projects: ${err.message}` }); }
    };
    fs.watchFile(this.projectsFile, { interval: 750, persistent: false }, this.projectFileWatcher);
  }
  createProject(input) {
    const project = new ProjectStore(this.projectsFile).load().add(input);
    this.emit({ type: 'projects-changed' });
    return projectSummary(project);
  }
  updateProject(id, patch) {
    const project = new ProjectStore(this.projectsFile).load().update(id, patch);
    if (!project) throw new Error('Project not found');
    this.refreshProjectAgents(id);
    this.emit({ type: 'projects-changed' });
    return projectSummary(project);
  }
  addProjectTodo(id, text) {
    const project = new ProjectStore(this.projectsFile).load().addTodo(id, text);
    if (!project || project.error) throw new Error(project?.error || 'Project not found');
    this.refreshProjectAgents(id);
    this.emit({ type: 'projects-changed' });
    return projectSummary(project);
  }
  addProjectRecord(id, kind, text) {
    if (!['note', 'decision'].includes(kind)) throw new Error('Choose note or decision');
    const store = new ProjectStore(this.projectsFile).load();
    const project = kind === 'note' ? store.addNote(id, text) : store.addDecision(id, text);
    if (!project || project.error) throw new Error(project?.error || 'Project not found');
    this.refreshProjectAgents(id);
    this.emit({ type: 'projects-changed' });
    return projectSummary(project);
  }
  completeProjectTodo(id, ref) {
    const result = new ProjectStore(this.projectsFile).load().completeTodo(id, ref);
    if (!result || result.error) throw new Error(result?.error || 'Project not found');
    this.refreshProjectAgents(id);
    this.emit({ type: 'projects-changed' });
    return projectSummary(result.project);
  }
  refreshProjectAgents(id) {
    const project = new ProjectStore(this.projectsFile).load().find(id);
    for (const [threadId, agent] of this.agents) {
      if (this.teammates.find(threadId)?.projectId !== id) continue;
      agent.setProject(projectContext(project), project?.id || null, projectWorkspace(project));
    }
  }
  assignProject(threadId, projectId) {
    if (this.turns.has(threadId)) throw new Error('Wait for this reply to finish before switching projects');
    const project = projectId ? new ProjectStore(this.projectsFile).load().find(projectId) : null;
    if (projectId && (!project || project.archived)) throw new Error('Choose an available project');
    const teammate = this.teammates.update(threadId, { projectId: project?.id || null });
    this.agents.get(threadId)?.setProject(projectContext(project), project?.id || null, projectWorkspace(project));
    this.emit({ type: 'teammates-changed' });
    return teammate;
  }
  createTeammate(input) {
    if (input?.projectId && !new ProjectStore(this.projectsFile).load().find(input.projectId)) throw new Error('Project not found');
    const item = this.teammates.create(input); this.emit({ type: 'teammates-changed' }); return item;
  }
  updateTeammate(id, patch) {
    if (this.turns.has(id) && Object.hasOwn(patch, 'projectId')) throw new Error('Wait for this reply to finish before switching projects');
    const project = patch.projectId ? new ProjectStore(this.projectsFile).load().find(patch.projectId) : null;
    if (patch.projectId && !project) throw new Error('Project not found');
    const item = this.teammates.update(id, patch);
    const agent = this.agents.get(id);
    if (agent) {
      agent.config.agentName = item.name;
      agent.config.systemExtra = item.persona;
      if (item.model) agent.model = item.model;
      if (Object.hasOwn(patch, 'projectId')) agent.setProject(projectContext(project), project?.id || null, projectWorkspace(project));
      else agent.refreshPrompt?.();
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
    let project = '', projectId = null, workspacePath = null;
    if (item.projectId) {
      const projects = new ProjectStore(this.projectsFile).load();
      const selected = projects.find(item.projectId);
      if (selected) {
        project = projectContext(selected);
        projectId = selected.id;
        workspacePath = projectWorkspace(selected);
      }
    }
    const agent = new this.AgentClass({
      client: this.client, tool: this.tool, mcp: this.mcp, config, project, projectId, workspacePath,
      journal: turn => recordTurn(turn, { timeZone: config.timeZone }),
      confirm: (name, detail) => this.approvals.request(id, name, detail),
      print: () => {}, write: () => {},
    });
    agent.model = item.model && this.models.some(model => model.id === item.model) ? item.model : this.model;
    agent.state ||= {};
    agent.state.onJobEvent = () => this.emit({ type: 'workspace-changed', threadId: id });
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
        this.pendingFileEdits.set(`${id}:${call.id}`, captureToolFiles(name, args, agent.cwd));
        this.emit({ type: 'tool-call', threadId: id, callId: call.id, name, args: displayArgs(name, args) });
      },
      onToolResult: (call, result) => {
        const pendingKey = `${id}:${call.id}`;
        const pending = this.pendingFileEdits.get(pendingKey) || [];
        this.pendingFileEdits.delete(pendingKey);
        let didChange = false;
        if (!/^(Error\b|Not run:|The user denied|Action cancelled)/i.test(String(result || ''))) {
          const changes = completedFileDiffs(pending);
          if (changes.length) {
            didChange = true;
            if (!this.reviewChanges.has(id)) this.reviewChanges.set(id, new Map());
            for (const change of changes) this.reviewChanges.get(id).set(change.path, change);
          }
        }
        this.emit({ type: 'tool-result', threadId: id, callId: call.id, text: String(result || ''), isError: /^Error\b/i.test(String(result || '')) });
        if (['project', 'project_memory'].includes(call.function?.name) && !/^Error\b/i.test(String(result || ''))) {
          const assigned = this.teammates.find(id)?.projectId;
          if (call.function.name === 'project' && agent.projectId !== assigned) this.teammates.update(id, { projectId: agent.projectId });
          if (agent.projectId) this.refreshProjectAgents(agent.projectId);
          this.emit({ type: 'teammates-changed' });
          this.emit({ type: 'projects-changed' });
        }
        if (['write_file', 'edit_file', 'edit_lines', 'apply_patch', 'move_file', 'delete_file', 'run_command', 'job_stop', 'git'].includes(call.function?.name)) this.emit({ type: 'workspace-changed', threadId: id, open: didChange });
      },
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
      this.emit({ type: 'workspace-changed', threadId: id });
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
    if (this.projectFileWatcher) { fs.unwatchFile(this.projectsFile, this.projectFileWatcher); this.projectFileWatcher = null; }
    await this.channels.stopAll().catch(() => {});
    this.approvals.cancelAll();
    for (const id of this.turns.keys()) this.agents.get(id)?.cancel();
    await this.mcp.closeAll();
  }
}
