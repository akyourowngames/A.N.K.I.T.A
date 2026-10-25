import type { ChatMessage } from '../../../shared/wire';

export type ToolMessage = Extract<ChatMessage, { role: 'tool' }>;

export type LocalToolImage = {
  type: 'generated_image' | 'downloaded_image';
  path: string;
  prompt?: string;
  photographer?: string;
  source?: string;
  pageUrl?: string;
  mime?: string;
};

export type StockToolImage = {
  id: string;
  title: string;
  previewUrl: string;
  imageUrl: string;
  pageUrl: string;
  photographer: string;
  source: string;
};

export type StockToolResults = {
  type: 'stock_image_results';
  provider: string;
  query: string;
  results: StockToolImage[];
};

export type ActivityItem =
  | { kind: 'tool'; id: string; message: ToolMessage }
  | { kind: 'thought'; id: string; text: string };

export type EditedFile = { path: string; added: number; removed: number };

export type TranscriptBlock =
  | { kind: 'message'; id: string; message: ChatMessage }
  | { kind: 'activity'; id: string; items: ActivityItem[]; live: boolean }
  | { kind: 'edits'; id: string; files: EditedFile[] };

const STANDALONE_TOOL_NAMES = new Set(['delegate_task', 'schedule']);
const EDIT_TOOL_NAMES = new Set(['edit_file', 'edit_lines', 'write_file', 'apply_patch']);
const PATCH_LINE = /^(?:Create|Update|Delete|Move) (.+?) \(\+(\d+)(?:[ \t]+-(\d+))?\)$/gm;
const STATS_LINE = /^\+(\d+)(?:[ \t]+-(\d+))?/m;
const CREATED_LINES = /^Created .*\((\d+) lines?\)/m;

export function imagePayload(result: string): LocalToolImage | StockToolResults | null {
  try {
    const value = JSON.parse(result);
    if ((value?.type === 'generated_image' || value?.type === 'downloaded_image') && typeof value.path === 'string') return value as LocalToolImage;
    if (value?.type === 'stock_image_results' && Array.isArray(value.results)) return value as StockToolResults;
  } catch { /* A plain-text result is the normal case. */ }
  return null;
}

export function isBrowserLoginCall(message: { name: string; args: unknown }): boolean {
  if (message.name !== 'browser') return false;
  const args = message.args;
  return typeof args === 'object' && args !== null && (args as { action?: string }).action === 'login';
}

/** Tools that need their own card: live sub-agents, scheduled work, sign-in, and image grids. */
export function isStandaloneTool(message: ToolMessage): boolean {
  if (message.hidden) return true;
  if (STANDALONE_TOOL_NAMES.has(message.name)) return true;
  if (isBrowserLoginCall(message)) return true;
  return Boolean(message.result) && Boolean(imagePayload(message.result));
}

function normalizedToolPath(args: unknown): string {
  if (!args || typeof args !== 'object') return '';
  const value = (args as Record<string, unknown>).path;
  return typeof value === 'string' ? value.replace(/\\/g, '/').replace(/^\.\//, '') : '';
}

function addEdit(edits: Map<string, EditedFile>, path: string, added: number, removed: number) {
  if (!path) return;
  const current = edits.get(path) || { path, added: 0, removed: 0 };
  current.added += added;
  current.removed += removed;
  edits.set(path, current);
}

function collectPatchEdits(result: string, edits: Map<string, EditedFile>) {
  for (const match of result.matchAll(PATCH_LINE)) {
    const path = match[1].split(' -> ').pop() || match[1];
    addEdit(edits, path.replace(/\\/g, '/'), Number(match[2]), Number(match[3] || 0));
  }
}

/**
 * Reads the line stats the filesystem tools already print in their receipts.
 * Returns nothing for a receipt without a recognizable change summary, so an
 * unparseable tool never invents an edit.
 */
export function collectEdits(message: ToolMessage, edits: Map<string, EditedFile>): void {
  if (message.hidden || message.isError || !message.result || !EDIT_TOOL_NAMES.has(message.name)) return;
  if (message.name === 'apply_patch') { collectPatchEdits(message.result, edits); return; }
  const path = normalizedToolPath(message.args);
  if (!path || /^No change\b/i.test(message.result)) return;
  const created = CREATED_LINES.exec(message.result);
  const stats = STATS_LINE.exec(message.result);
  if (!created && !stats && !/^(?:Edited|Created|Overwrote)\b/m.test(message.result)) return;
  addEdit(edits, path, created ? Number(created[1]) : Number(stats?.[1] || 0), created ? 0 : Number(stats?.[2] || 0));
}

/**
 * Folds a flat transcript into readable blocks without changing the stored
 * message shape. Consecutive tool calls and reasoning-only assistant messages
 * become one collapsible activity group; edits found in the turn become a
 * summary card after the turn's final answer.
 */
export function buildTranscript(messages: ChatMessage[], running: boolean): TranscriptBlock[] {
  const blocks: TranscriptBlock[] = [];
  let items: ActivityItem[] = [];
  let edits = new Map<string, EditedFile>();
  let editSequence = 0;

  const flushActivity = () => {
    if (!items.length) return;
    blocks.push({ kind: 'activity', id: `activity-${items[0].id}`, items, live: false });
    items = [];
  };
  const flushEdits = () => {
    if (!edits.size) return;
    blocks.push({ kind: 'edits', id: `edits-${editSequence++}`, files: [...edits.values()] });
    edits = new Map();
  };

  for (const message of messages) {
    if (message.role === 'user') {
      flushActivity();
      flushEdits();
      blocks.push({ kind: 'message', id: message.id, message });
      continue;
    }
    if (message.role === 'tool') {
      if (message.hidden) continue;
      collectEdits(message, edits);
      if (isStandaloneTool(message)) {
        flushActivity();
        blocks.push({ kind: 'message', id: message.id, message });
      } else {
        items.push({ kind: 'tool', id: message.id, message });
      }
      continue;
    }
    if (message.content.trim()) {
      flushActivity();
      blocks.push({ kind: 'message', id: message.id, message });
      continue;
    }
    if (message.reasoning?.trim()) items.push({ kind: 'thought', id: message.id, text: message.reasoning });
  }
  flushActivity();
  flushEdits();

  if (running) {
    for (let index = blocks.length - 1; index >= 0; index--) {
      const block = blocks[index];
      if (block.kind === 'activity') { block.live = true; break; }
      if (block.kind === 'message') break;
    }
  }
  return blocks;
}
