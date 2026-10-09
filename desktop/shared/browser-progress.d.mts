export type BrowserPhase = 'thinking' | 'reading' | 'acting' | 'checking' | 'recovering' | 'waiting-for-user' | 'stopped' | 'finished';
export type BrowserProgress = { phase: BrowserPhase; label: string; completed: number; total: number | null; outcome: 'unverified' | 'executed' | 'failed' | 'partial' | 'uncertain'; recoverable: boolean; goalVerified: false; attention: { kind: 'dialog'; dialogType: string | null } | null };
export const BROWSER_PROGRESS_LIMITS: Readonly<{ label: number }>;
export const BROWSER_PREVIEW_POLL: Readonly<{ active: number; thumbnail: number; idle: number; failed: number; hidden: number }>;
export const BROWSER_PHASES: readonly BrowserPhase[];
export const BROWSER_PHASE_TITLES: Readonly<Record<BrowserPhase, string>>;
export function publicBrowserView<T extends { dialog?: unknown }>(view: T): Omit<T, 'dialog'>;
export function browserActionPhase(args: { action?: string }): BrowserPhase;
export function browserProgress(input?: { phase?: BrowserPhase; args?: Record<string, unknown> | null; completed?: number; result?: unknown; previous?: BrowserProgress | null }): BrowserProgress;
