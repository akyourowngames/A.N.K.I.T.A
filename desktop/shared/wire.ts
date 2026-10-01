export type Teammate = {
  id: string; name: string; color: string; emoji: string; persona: string;
  projectId: string | null; model: string | null; createdAt: string; updatedAt: string;
  lastMessage: string; lastMessageAt: string | null;
};

export type Model = { id: string; name?: string; vendor?: string; context?: number; tools?: boolean };
export type DesktopSkill = { name: string; description: string; suggestedTools: string; body: string; enabled: boolean };
export type DesktopPreferences = {
  secretScrubbing?: boolean; secretWarningSeen?: boolean;
  provider: string; model: string; customApiBase: string; appearance: 'graphite' | 'mono' | 'slate';
  contextWindow: number; maxTokens: number;
  imageApiBase: string; imageModel: string;
  username: string; timeZone: string; profileSetupDone: boolean;
  hasCustomApiKey: boolean; hasGroqKey: boolean; hasKiloKey: boolean; hasComposioKey: boolean;
  hasImageApiKey: boolean; hasUnsplashAccessKey: boolean; hasPixabayApiKey: boolean;
};
export type DesktopSettingsUpdate = Partial<Pick<DesktopPreferences, 'provider' | 'model' | 'customApiBase' | 'appearance' | 'contextWindow' | 'maxTokens' | 'imageApiBase' | 'imageModel' | 'username' | 'timeZone' | 'profileSetupDone'>> & {
  secretScrubbing?: boolean; secretWarningSeen?: boolean;
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
export type PluginCard = { slug: string; label: string; blurb: string; noAuth: boolean; logo: string };
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
export type SecureStoreRecord = { id: string; website: string; username: string; updatedAt: string; hasPassword: boolean };
export type SecureStoreRequest = { type: 'secure-store-request'; requestId: string; threadId: string; callId: string; website: string; username: string; canSave: boolean; message: string };
export type SecureStoreStatus = { type: 'secure-store-status'; threadId: string; callId: string; website: string; username: string; state: string; message: string };
export type RoutineAllow = { read: boolean; interact: boolean; login: boolean; sites: string[]; mode: 'isolated' | 'local' };
export type RoutineBudget = { maxRunsPerDay: number; maxTokensPerDay: number; maxMinutesPerDay: number };
export type JobReceipt = { runId: string; routineId: string; threadId: string; name: string; status: string; text: string; ownerMissing?: boolean; proof: { url: string | null; screenshot: string | null } | null; at: string };
export type Routine = { id: string; name: string; description?: string; kind?: 'routine' | 'heartbeat'; browserPolicy?: 'autonomous' | 'scoped'; executionPolicy?: 'complete' | 'bounded'; cron: string; cronLabel: string; prompt: string; threadId: string | null; deliveryThreadId: string | null; allow: RoutineAllow; budget: RoutineBudget; timeoutMs: number; headless: boolean; onNewRequest: 'pause-ask' | 'deny'; enabled: boolean; ownerMissing: boolean; pausedReason: string | null; nextRunAt: string | null; nextRunIn: number | null; timeZone: string; running: boolean; step: number; scope: string | null; needsApproval: boolean; lastStatus: string | null; lastSummary: string | null; lastReceipt?: JobReceipt; draft?: boolean; draftPatch?: Partial<Routine>; pendingApproval?: { requestId: string; runId: string; redactedDetail: string; expiresAt: string } | null };
export type ChatMessage =
  | { id: string; role: 'user' | 'assistant'; content: string; job?: JobReceipt; reasoning?: string; attachments?: { name: string; image?: boolean }[] }
  | { id: string; role: 'tool'; callId: string; name: string; args: unknown; result: string; isError: boolean; startedAt?: number; endedAt?: number; hidden?: boolean };

export type MenuCommand = 'new-teammate' | 'find' | 'toggle-sidebar' | 'settings' | 'about';

export type IslandAction = 'show-main' | 'tuck' | 'petit' | 'home' | 'home-expanded';

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
  | { type: 'secret-notice'; message: string }
  | { type: 'schedule-changed'; jobs: Routine[] }
  | { type: 'routine-draft'; threadId: string; routineId: string }
  | { type: 'routine-run-start' | 'routine-run-step' | 'routine-run-end' | 'routine-queued'; threadId: string; routineId: string; runId: string; scope?: string; step?: number; detail?: string; status?: string }
  | ({ type: 'routine-result'; messageId: string; content: string } & JobReceipt)
  | { type: 'routine-failed'; threadId?: string; routineId: string; status: string; text?: string }
  | { type: 'routine-approval-ended'; requestId: string; routineId: string; threadId: string; outcome: string }
  | { type: 'scheduler-error' | 'scheduler-stopped'; message: string }
  | SecureStoreRequest | SecureStoreStatus
  | { type: 'secure-store-resolved'; requestId: string; threadId: string; callId: string }
  | { type: 'secure-store-changed' }
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
  | { type: 'turn-start'; threadId: string; turnId: string; model: string; text: string; source?: 'routine'; attachments?: { name: string; image?: boolean }[] }
  | { type: 'turn-end'; threadId: string; turnId: string }
  | { type: 'message-start' | 'message-end' | 'message-reset'; threadId: string; messageId: string }
  | { type: 'assistant-delta' | 'reasoning-delta'; threadId: string; messageId?: string; text: string }
  | { type: 'tool-call'; threadId: string; callId: string; name: string; args: unknown }
  | { type: 'tool-result'; threadId: string; callId: string; text: string; isError: boolean }
  | { type: 'usage'; threadId: string; prompt_tokens?: number; completion_tokens?: number; estimated_cost?: number }
  | { type: 'approval-request'; requestId: string; threadId: string; toolName: string; detail: string; routineId?: string; runId?: string; expiresAt?: string }
  | { type: 'thread-cleared'; threadId: string }
  | { type: 'error'; threadId: string | null; message: string };

export type DesktopApi = {
  redact(text: string): Promise<string>;
  invoke<T = unknown>(action: string, payload?: unknown): Promise<T>;
  onEvent(callback: (event: EngineEvent) => void): () => void;
  onMenuCommand(callback: (command: MenuCommand) => void): () => void;
  onUpdateEvent(callback: (event: UpdateEvent) => void): () => void;
  updateAction(action: 'check' | 'install'): Promise<boolean>;
  appAction(action: 'open-config-folder' | 'open-data-folder' | 'relaunch'): Promise<unknown>;
  windowAction(action: 'minimize' | 'maximize' | 'close'): Promise<boolean>;
  islandAction(action: IslandAction): Promise<boolean>;
  onCursor(callback: (point: { x: number; y: number }) => void): () => void;
  openExternal(url: string): Promise<void>;
};

declare global { interface Window { ankita: DesktopApi } }
