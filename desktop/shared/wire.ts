export type Teammate = {
  id: string; name: string; color: string; emoji: string; persona: string;
  projectId: string | null; model: string | null; createdAt: string; updatedAt: string;
  lastMessage: string; lastMessageAt: string | null;
};

export type Model = { id: string; name?: string; vendor?: string; context?: number; tools?: boolean };
export type DesktopPreferences = {
  provider: string; model: string; customApiBase: string; appearance: 'graphite' | 'mono' | 'slate';
  hasCustomApiKey: boolean; hasGroqKey: boolean; hasKiloKey: boolean; hasComposioKey: boolean;
};
export type DesktopSettingsUpdate = Partial<Pick<DesktopPreferences, 'provider' | 'model' | 'customApiBase' | 'appearance'>> & {
  customApiKey?: string; groqApiKey?: string; kiloApiKey?: string; composioApiKey?: string;
};
export type DesktopSettingsResult = {
  preferences: DesktopPreferences;
  settings: { username: string; provider: string; model: string; tools: string[] };
  models: Model[];
};
export type PluginCard = { slug: string; label: string; blurb: string; noAuth: boolean };
export type PluginAccount = { id: string; alias: string; status: string };
export type PluginService = { connected: boolean; pending: boolean; status: string; accounts: PluginAccount[] };
export type PluginsOverview = { mode: 'direct' | 'broker' | 'unavailable'; live: boolean; services: Record<string, PluginService> };
export type PluginsCatalogPage = { cards: PluginCard[]; nextCursor: string | null };
export type ChatMessage =
  | { id: string; role: 'user' | 'assistant'; content: string; reasoning?: string }
  | { id: string; role: 'tool'; callId: string; name: string; args: unknown; result: string; isError: boolean; startedAt?: number; endedAt?: number };

export type MenuCommand = 'new-teammate' | 'find' | 'toggle-sidebar' | 'settings' | 'about';

export type UpdateEvent =
  | { type: 'checking'; manual?: boolean }
  | { type: 'available'; version?: string; releaseName?: string | null }
  | { type: 'progress'; percent: number }
  | { type: 'downloaded'; version?: string; releaseName?: string | null }
  | { type: 'current' }
  | { type: 'unsupported' }
  | { type: 'error'; message: string };

export type EngineEvent =
  | { type: 'status'; phase: string }
  | ({ type: 'settings-updated' } & DesktopSettingsResult)
  | { type: 'auth-device-code'; user_code: string; verification_uri: string }
  | { type: 'teammates-changed' | 'tools-changed'; connected?: string[] }
  | { type: 'model-changed'; threadId: string; model: string }
  | { type: 'turn-start'; threadId: string; turnId: string; model: string; text: string }
  | { type: 'turn-end'; threadId: string; turnId: string }
  | { type: 'message-start' | 'message-end'; threadId: string; messageId: string }
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
  appAction(action: 'open-config-folder' | 'open-data-folder'): Promise<unknown>;
  windowAction(action: 'minimize' | 'maximize' | 'close'): Promise<boolean>;
  openExternal(url: string): Promise<void>;
};

declare global { interface Window { ankita: DesktopApi } }
