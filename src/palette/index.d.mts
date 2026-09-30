export type PaletteEntry = { id: string; title: string; hint: string; source: 'command' | 'skill' | 'job'; keywords?: string[]; nextRunAt?: string | null; command?: string; skill?: string; jobId?: string };
export function buildIndex(input: { skills?: unknown[]; jobs?: unknown[] }): PaletteEntry[];
export function search(entries: PaletteEntry[], input?: string): PaletteEntry[];
export function validatePalette(input: unknown): { id: string; title: string; hint: string; keywords: string[] }[];
