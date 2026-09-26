export type Teammate = {
  id: string; name: string; color: string; emoji: string; persona: string;
  projectId: string | null; model: string | null; createdAt: string; updatedAt: string;
  lastMessage: string; lastMessageAt: string | null;
};

export type Model = { id: string; name?: string; vendor?: string; context?: number; tools?: boolean };
export type DesktopSkill = { name: string; description: string; suggestedTools: string; body: string; enabled: boolean };
export type DesktopPreferences = {
  provider: string; model: string; customApiBase: string; appearance: 'graphite' | 'mono' | 'slate';
  contextWindow: number; maxTokens: number;
  imageApiBase: string; imageModel: string;
  username: string; timeZone: string; profileSetupDone: boolean;
  hasCustomApiKey: boolean; hasGroqKey: boolean; hasKiloKey: boolean; hasComposioKey: boolean;
  hasImageApiKey: boolean; hasUnsplashAccessKey: boolean; hasPixabayApiKey: boolean;
};
export type DesktopSettingsUpdate = Partial<Pick<DesktopPreferences, 'provider' | 'model' | 'customApiBase' | 'appearance' | 'contextWindow' | 'maxTokens' | 'imageApiBase' | 'imageModel' | 'username' | 'timeZone' | 'profileSetupDone'>> & {
  customApiKey?: string; groqApiKey?: string; kiloApiKey?: string; composioApiKey?: string;
  imageApiKey?: string; unsplashAccessKey?: string; pixabayApiKey?: string;
};
export type DesktopSettingsResult = {
  preferences: DesktopPreferences;
  settings: { username: string; provider: string; model: string; tools: string[] };
  models: Model[];
};
export type ChannelStatus = { running: boolean; account: string | null; error: string | null };
export type TelegramChannelPreferences = {
  enabled: boolean; hasToken: boolean; allowedChatIds: string; ownerChatId: string;
  teammateId: string | null; voiceReply: boolean; confirmTimeout: number; status: ChannelStatus;
};
export type ChannelsView = { telegram: TelegramChannelPreferences };
export type TelegramChannelUpdate = Partial<Pick<TelegramChannelPreferences, 'enabled' | 'allowedChatIds' | 'ownerChatId' | 'teammateId' | 'voiceReply' | 'confirmTimeout'>> & { token?: string };
export type PluginCard = { slug: string; label: string; blurb: string; noAuth: boolean };
export type Project = { id: string; name: string; summary: string; path: string; repo: string; client: string; conventions: string[]; status: string; archived: boolean; decisions: { at: string; text: string }[]; notes: { at: string; text: string }[]; todos: { id: string; at: string; text: string; done: boolean }[]; lastUsedAt: string | null };
export type ChangedFile = { path: string; status: string; untracked: boolean };
export type WorkspaceJob = { id: string; state: string; command: string; cwd: string; exit_code: number | null; started_at: string; output: string };
export type WorkspaceSnapshot = { root: string; cwd: string; files: ChangedFile[]; artifacts: { path: string; name: string }[]; jobs: WorkspaceJob[] };
export type WorkspaceDiff = { path: string; diff: string; untracked?: boolean; truncated?: boolean; message?: string };
export type PluginAccount = { id: string; alias: string; status: string };
export type PluginService = { connected: boolean; pending: boolean; status: string; accounts: PluginAccount[] };
export type PluginsOverview = { mode: 'direct' | 'broker' | 'unavailable'; live: boolean; services: Record<string, PluginService> };
export type PluginsCatalogPage = { cards: PluginCard[]; nextCursor: string | null };
export type BrowserPlugin = { id: string; name: string; description: string; mode: 'isolated' | 'local'; enabled: boolean; ready: boolean; reason: string; allowedSites: string[]; blockedSites: string[]; headless?: boolean; connection?: 'profile' | 'port' | 'active'; port?: number };
export type BrowserPluginsOverview = { isolated: BrowserPlugin; local: BrowserPlugin };
export type BrowserSessionView = { mode: 'isolated' | 'local' | 'external' | null; status: string; step: string; tabs: { id: string; url: string; title: string; active: boolean }[]; screenshot: string | null; notice?: import('../../src/integrations/browser-errors.mjs').BrowserNotice | null };
export type ChatMessage =
  | { id: string; role: 'user' | 'assistant'; content: string; reasoning?: string; attachments?: { name: string; image?: boolean }[] }
  | { id: string; role: 'tool'; callId: string; name: string; args: unknown; result: string; isError: boolean; startedAt?: number; endedAt?: number; hidden?: boolean };

export type MenuCommand = 'new-teammate' | 'find' | 'toggle-sidebar' | 'settings' | 'about';

export type UpdateEvent =
  | { type: 'checking'; manual?: boolean }
  | { type: 'available'; version?: string; releaseName?: string | null }
  | { type: 'progress'; percent: number }
  | { type: 'stalled'; percent: number; version?: string }
  | { type: 'downloaded'; version?: string; releaseName?: string | null }
  | { type: 'current' }
  | { type: 'unsupported' }
  | { type: 'error'; message: string };

export type EngineEvent =
  | { type: 'status'; phase: string }
  | ({ type: 'settings-updated' } & DesktopSettingsResult)
  | { type: 'auth-device-code'; user_code: string; verification_uri: string }
  | { type: 'teammates-changed' | 'tools-changed'; connected?: string[] }
  | { type: 'projects-changed' }
  | { type: 'channels-updated'; channels: ChannelsView }
  | { type: 'browser-plugins-changed' }
  | { type: 'browser-install-progress'; text: string }
  | { type: 'browser-state'; threadId: string | null; state: BrowserSessionView }
  | { type: 'approval-resolved'; requestId: string }
  | { type: 'workspace-changed'; threadId: string; open?: boolean }
  | { type: 'model-changed'; threadId: string; model: string }
  | { type: 'turn-start'; threadId: string; turnId: string; model: string; text: string; attachments?: { name: string; image?: boolean }[] }
  | { type: 'turn-end'; threadId: string; turnId: string }
  | { type: 'message-start' | 'message-end' | 'message-reset'; threadId: string; messageId: string }
  | { type: 'assistant-delta' | 'reasoning-delta'; threadId: string; messageId?: string; text: string }
  | { type: 'tool-call'; threadId: string; callId: string; name: string; args: unknown }
  | { type: 'tool-result'; threadId: string; callId: string; text: string; isError: boolean }
  | { type: 'usage'; threadId: string; prompt_tokens?: number; completion_tokens?: number; estimated_cost?: number }
  | { type: 'approval-request'; requestId: string; threadId: string; toolName: string; detail: string }
  | { type: 'thread-cleared'; threadId: string }
  | { type: 'error'; threadId: string | null; message: string };

export type DesktopApi = {
  invoke<T = unknown>(action: string, payload?: unknown): Promise<T>;
  onEvent(callback: (event: EngineEvent) => void): () => void;
  onMenuCommand(callback: (command: MenuCommand) => void): () => void;
  onUpdateEvent(callback: (event: UpdateEvent) => void): () => void;
  updateAction(action: 'check' | 'install'): Promise<boolean>;
  appAction(action: 'open-config-folder' | 'open-data-folder' | 'relaunch'): Promise<unknown>;
  windowAction(action: 'minimize' | 'maximize' | 'close'): Promise<boolean>;
  openExternal(url: string): Promise<void>;
};

declare global { interface Window { ankita: DesktopApi } }
