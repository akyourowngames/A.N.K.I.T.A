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
import { sanitizeMessages, estimateImageBytes } from '../../src/history.mjs';
import { displayArgs } from '../../tools/index.mjs';
import { TeammateStore } from './teammates.mjs';
import { ApprovalRegistry } from './approvals.mjs';
import { DesktopSettingsStore, applyDesktopSettings, seedFreshDesktopProvider, testCustomProvider } from './settings.mjs';
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

const ATTACHMENT_TEXT_LIMIT = 200_000;
const ATTACHMENT_DOC_LIMIT = 1_000_000;
const ATTACHMENT_IMAGE_LIMIT = 10 * 1024 * 1024;
/**
 * How much of the context window an attachment may occupy.
 *
 * A document can extract to hundreds of thousands of characters, and the tool
 * schemas plus history already use much of the window. Without a ceiling one
 * attachment blows the whole budget and the turn fails before it is sent.
 * UTF-8 bytes bound tokens conservatively, so a share of the window in bytes is
 * a safe cap. The agent trims the attachment further to whatever is really left.
 */
const ATTACHMENT_WINDOW_SHARE = 0.35;
const ATTACHMENT_WINDOW_FLOOR = 16_000;
export function attachmentBudgetBytes(contextWindow) {
  const window = Number(contextWindow);
  if (!Number.isFinite(window) || window <= 0) return 240_000;
  return Math.max(ATTACHMENT_WINDOW_FLOOR, Math.floor(window * ATTACHMENT_WINDOW_SHARE));
}
const IMAGE_MIME = { '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.gif': 'image/gif' };
const TEXT_EXTENSIONS = new Set(['.txt', '.md', '.markdown', '.json', '.jsonc', '.js', '.mjs', '.cjs', '.ts', '.tsx', '.jsx', '.py', '.rb', '.go', '.rs', '.java', '.cs', '.c', '.h', '.cpp', '.hpp', '.css', '.scss', '.html', '.htm', '.xml', '.yml', '.yaml', '.toml', '.ini', '.cfg', '.env', '.sh', '.bash', '.ps1', '.sql', '.csv', '.tsv', '.log']);

/**
 * Turn renderer-side file descriptors into what the agent can send.
 *
 * Files arrive as base64 from the window, are size-capped here, and become
 * either an inline image part or a decoded text block. The name is sanitised
 * before it reaches a prompt so a crafted filename cannot break out of the
 * labelled block.
 */
export function attachmentPayload(files = [], { contextWindow } = {}) {
  const out = [];
  // A single message's attachments share one slice of the window.
  const budget = attachmentBudgetBytes(contextWindow);
  let used = 0;
  for (const file of Array.isArray(files) ? files : []) {
    const rawName = String(file?.name || 'file').replace(/[\r\n\t]/g, ' ').slice(0, 200);
    const ext = path.extname(rawName).toLowerCase();
    const data = String(file?.data || '');
    if (!data) continue;
    let bytes;
    try { bytes = Buffer.from(data, 'base64'); } catch { continue; }
    if (IMAGE_MIME[ext]) {
      if (bytes.length > ATTACHMENT_IMAGE_LIMIT) throw new Error(`${rawName} is larger than 10 MB`);
      const dataUrl = `data:${IMAGE_MIME[ext]};base64,${bytes.toString('base64')}`;
      // Direct images are billed as visual tokens, not upload bytes. A sharp
      // screenshot can be megabytes on the wire while costing roughly a
      // thousand tokens; measuring pixels keeps it in the request.
      const imageCost = estimateImageBytes(dataUrl);
      if (used + imageCost > budget) throw new Error(`${rawName} does not fit the model's context budget; use a larger context window or attach a smaller image`);
      used += imageCost;
      out.push({ name: rawName, dataUrl });
      continue;
    }
    // Documents (pdf/docx/xlsx/pptx) arrive already extracted to text by the
    // window, flagged so the extension check does not reject them here.
    const kind = file?.kind === 'document' ? 'document' : 'text';
    const limit = kind === 'document' ? ATTACHMENT_DOC_LIMIT : ATTACHMENT_TEXT_LIMIT;
    if (bytes.length > limit) throw new Error(`${rawName} is larger than ${kind === 'document' ? '1 MB' : '200 KB'}`);
    if (!TEXT_EXTENSIONS.has(ext) && kind !== 'document') throw new Error(`${rawName} is not a supported file type`);
    // A document is already text by this point, so the NUL check - which is
    // there to reject an accidentally-attached raw binary - must not apply:
    // a PDF extractor can legitimately emit control bytes. Strip them instead.
    if (kind !== 'document' && bytes.includes(0)) throw new Error(`${rawName} looks binary; only text and images can be attached`);
    // Page renders are reserved first: unlike text they cannot be clipped. They
    // are billed as visual tokens, not upload bytes, and only as many leading
    // pages as fit are kept. Rejecting the whole document because page ten did
    // not fit would discard pages the model could have read.
    const images = Array.isArray(file?.images) ? file.images.filter(part => typeof part === 'string' && /^data:image\//i.test(part)) : [];
    const keptImages = [];
    let imageBytes = 0;
    for (const image of images) {
      const cost = estimateImageBytes(image);
      if (used + imageBytes + cost > budget) break;
      keptImages.push(image);
      imageBytes += cost;
    }
    if (images.length && !keptImages.length) throw new Error(`${rawName} with its page images exceeds the model's context budget; use a larger context window or attach fewer pages`);
    used += imageBytes;
    // Trim to what is left of the window, keeping the head and tail so the
    // model still sees how the document starts and ends.
    let text = sanitizeExtracted(bytes.toString('utf8'));
    const room = budget - used;
    if (room <= 0) throw new Error(`${rawName} does not fit the model's context budget; use a larger context window or a smaller file`);
    if (Buffer.byteLength(text) > room) text = clipAttachment(text, room, rawName);
    if (keptImages.length < images.length) {
      text += `\n\n[attached pages 1-${keptImages.length} of ${images.length} as images to fit the context window]`;
    }
    used += Buffer.byteLength(text);
    out.push({ name: rawName, text, ...(keptImages.length ? { images: keptImages } : {}) });
  }
  return out;
}

/**
 * Make extracted document text safe to embed: drop NULs and stray control
 * bytes a PDF parser can emit, and collapse the runs of blank space that
 * usually accompany them.
 */
function sanitizeExtracted(text) {
  return text
    .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, ' ')
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n{4,}/g, '\n\n\n')
    .trim();
}

/** Keep the start and end of an over-long attachment, marking what was cut. */
function clipAttachment(text, maxBytes, name) {
  const marker = `\n\n[... ${name} truncated to fit the context window ...]\n\n`;
  const room = Math.max(0, maxBytes - Buffer.byteLength(marker));
  const head = Math.floor(room * 0.7);
  const tail = room - head;
  const buffer = Buffer.from(text);
  const start = buffer.subarray(0, head).toString('utf8').replace(/\uFFFD$/u, '');
  const end = buffer.subarray(buffer.length - tail).toString('utf8').replace(/^\uFFFD+/u, '');
  return start + marker + end;
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
      const attachments = attachmentNames(entry.content);
      if (content || attachments.length) out.push({ id: `message-${i}`, role: entry.role, content, attachments: attachments.length ? attachments : undefined });
      for (const call of entry.tool_calls || []) {
        let args = {};
        try { args = JSON.parse(call.function?.arguments || '{}'); } catch {}
        const name = call.function?.name || 'tool';
        const tool = { id: `tool-${call.id || i}`, role: 'tool', callId: call.id, name, args: displayArgs(name, args), result: '', isError: false };
        byCall.set(call.id, tool);
        out.push(tool);
      }
      continue;
    }
    if (entry.role === 'tool') {
      const tool = byCall.get(entry.tool_call_id);
      if (tool) {
        tool.result = messageText(entry.content);
        tool.isError = /^Error\b/i.test(tool.result);
      }
    }
  }
  return out;
}

/**
 * The names of files in a multimodal user turn, recovered from the prompt text.
 *
 * Attachments are folded into the message as `Attached file: <name>` blocks (or
 * image parts), so the transcript can show chips again after a reload without
 * storing the file bytes a second time.
 */
function attachmentNames(content) {
  if (!Array.isArray(content)) return [];
  const names = [];
  for (const part of content) {
    if (part?.type === 'image_url') { names.push({ name: 'image', image: true }); continue; }
    if (part?.type !== 'text' || typeof part.text !== 'string') continue;
    for (const match of part.text.matchAll(/^Attached file:\s*(.+)$/gm)) names.push({ name: match[1].trim().slice(0, 200) });
  }
  return names;
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
    const injectedConfig = Boolean(this.config);
    this.baseConfig = this.config || loadConfig(this.envPath);
    seedFreshDesktopProvider(this.desktopSettings, this.teammates.file, this.baseConfig, injectedConfig);
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
    const tune = ['contextWindow', 'maxTokens', 'imageApiBase', 'imageApiKey', 'imageModel', 'unsplashAccessKey', 'pixabayApiKey', 'username', 'timeZone'].some(key => Object.hasOwn(patch, key));
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
        imageApiBase: nextConfig.imageApiBase, imageApiKey: nextConfig.imageApiKey, imageModel: nextConfig.imageModel,
        unsplashAccessKey: nextConfig.unsplashAccessKey, pixabayApiKey: nextConfig.pixabayApiKey,
        username: nextConfig.username, timeZone: nextConfig.timeZone,
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
  async readGeneratedImage(id, requested) {
    const agent = this.agents.get(id);
    const teammate = this.teammates.find(id);
    if (!teammate) throw new Error('Teammate not found');
    const cwd = agent?.cwd || projectWorkspace(new ProjectStore(this.projectsFile).load().find(teammate.projectId)) || process.cwd();
    const requestedPath = String(requested || '');
    if (!requestedPath) throw new Error('Image path is required');
    const root = await fs.promises.realpath(cwd);
    // Assistant Markdown commonly uses an absolute Windows path while the
    // image tools return workspace-relative paths. Accept both, then enforce
    // the same realpath containment check for either form.
    const workspacePath = path.resolve(cwd);
    const candidate = path.isAbsolute(requestedPath) ? path.resolve(requestedPath) : path.resolve(workspacePath, requestedPath);
    // A workspace can be reached through a junction or symlink. Check the
    // path the agent used as well as its canonical path before resolving the
    // image; then enforce canonical containment below for symlink safety.
    const inside = base => {
      const relative = path.relative(base, candidate);
      return Boolean(relative) && relative !== '..' && !relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative);
    };
    if (!inside(workspacePath) && !inside(root)) throw new Error('Image must be inside the workspace');
    const absolute = await fs.promises.realpath(candidate);
    const contained = path.relative(root, absolute);
    if (contained === '..' || contained.startsWith(`..${path.sep}`) || path.isAbsolute(contained)) throw new Error('Image must be inside the workspace');
    const folder = contained.split(path.sep)[0];
    if (!['generated-images', 'downloaded-images'].includes(folder)) throw new Error('Image preview is restricted to generated-images and downloaded-images in the workspace');
    const mime = ({ '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp' })[path.extname(absolute).toLowerCase()];
    if (!mime) throw new Error('Unsupported image format');
    const stat = await fs.promises.stat(absolute);
    if (!stat.isFile() || stat.size > 15 * 1024 * 1024) throw new Error('Image is unavailable or larger than 15 MB');
    const data = await fs.promises.readFile(absolute);
    return { dataUrl: `data:${mime};base64,${data.toString('base64')}` };
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

  async send(id, text, attachments = null) {
    const prompt = String(text || '').trim();
    if (this.turns.has(id)) throw new Error('This teammate is already replying');
    const agent = this.agentFor(id);
    // Cap attachments against this teammate's window, not a fixed number.
    const files = attachmentPayload(attachments, { contextWindow: agent.contextWindow || this.config.contextWindow });
    if (!prompt && !files.length) throw new Error('Write a message or attach a file first');
    const turnId = randomUUID();
    this.emit({ type: 'turn-start', threadId: id, turnId, model: agent.model, text: prompt, attachments: files.map(file => ({ name: file.name, image: Boolean(file.dataUrl) })) });
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
        if (['write_file', 'edit_file', 'edit_lines', 'apply_patch', 'move_file', 'delete_file', 'run_command', 'job_stop', 'git', 'image_generate', 'image_download'].includes(call.function?.name)) this.emit({ type: 'workspace-changed', threadId: id, open: didChange || ['image_generate', 'image_download'].includes(call.function?.name) });
      },
    };
    const work = Promise.resolve().then(() => agent.send(prompt, { ...callbacks, attachments: files })).then(reply => {
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
