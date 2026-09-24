const PHRASES: Record<string, string> = {
  read_file: 'Read a file',
  write_file: 'Wrote a file',
  edit_file: 'Edited a file',
  edit_lines: 'Edited lines',
  apply_patch: 'Applied a patch',
  list_dir: 'Listed a folder',
  search_files: 'Searched files',
  glob: 'Found files',
  move_file: 'Moved a file',
  delete_file: 'Deleted a file',
  create_dir: 'Created a folder',
  run_command: 'Ran a command',
  web_search: 'Searched the web',
  image_generate: 'Generated an image',
  image_download: 'Downloaded a stock image',
  unsplash_search: 'Searched Unsplash',
  pixabay_search: 'Searched Pixabay',
  web_fetch: 'Read a page',
  scrape: 'Scraped a page',
  http_request: 'Called an API',
  recall: 'Recalled memory',
  remember: 'Saved a memory',
  git: 'Used git',
  schedule: 'Scheduled a routine',
  watch: 'Set up a watch',
  composio: 'Used a connected app',
  project_memory: 'Checked project notes',
};

/** Turn raw tool names into something readable in a tool card header. */
export function humanizeTool(name: string): string {
  const raw = String(name || 'tool');
  const scoped = /^mcp__([^_]+(?:_[^_]+)*?)__(.+)$/.exec(raw);
  const key = (scoped ? scoped[2] : raw).toLowerCase();
  if (PHRASES[key]) return PHRASES[key];
  if (scoped) return `${scoped[2].replace(/_/g, ' ')} · ${scoped[1]}`;
  const words = key.replace(/_/g, ' ').trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** A one-line hint of what a tool call was about, for the collapsed row. */
export function summarizeArgs(args: unknown): string {
  if (args == null) return '';
  if (typeof args === 'string') return args.replace(/\s+/g, ' ').trim().slice(0, 80);
  if (typeof args !== 'object') return String(args);
  const record = args as Record<string, unknown>;
  for (const key of ['path', 'file', 'file_path', 'command', 'query', 'url', 'name', 'id', 'toolkit', 'action', 'operation']) {
    const value = record[key];
    if (typeof value === 'string' && value.trim()) return value.replace(/\s+/g, ' ').trim().slice(0, 80);
  }
  return '';
}

export function formatDuration(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return '';
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)}s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${Math.round(seconds % 60)}s`;
}

export function formatTokens(value: number, unit = ''): string {
  if (!Number.isFinite(value) || value <= 0) return `0${unit}`;
  if (value < 1000) return `${Math.round(value)}${unit}`;
  if (value < 1_000_000) return `${(value / 1000).toFixed(value < 10_000 ? 1 : 0)}k${unit}`;
  return `${(value / 1_000_000).toFixed(1)}M${unit}`;
}
