import { useEffect, useRef, useState } from 'react';
import type { PaletteEntry } from '../../../../src/palette/index.mjs';
import { Icon } from './Icons';
const QUERY_DEBOUNCE_MS = 80; // Avoid rebuilding the index for every keystroke.

export function PaletteModal({ threadId, revision, onCommand, onClose }: { threadId: string | null; revision: string; onCommand: (command: string) => void; onClose: () => void }) {
  const [query, setQuery] = useState('');
  const [entries, setEntries] = useState<PaletteEntry[]>([]);
  const [selected, setSelected] = useState(0);
  const [loadedQuery, setLoadedQuery] = useState<string | null>(null);
  const [loadedRevision, setLoadedRevision] = useState<string | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const input = useRef<HTMLInputElement>(null), list = useRef<HTMLDivElement>(null);
  useEffect(() => { const prior = document.activeElement as HTMLElement | null; input.current?.focus(); return () => prior?.focus(); }, []);
  useEffect(() => {
    let active = true;
    const timer = window.setTimeout(() => { void window.ankita.invoke<PaletteEntry[]>('palette:query', { query }).then(value => { if (active) { setEntries(value); setSelected(0); setLoadedQuery(query); setLoadedRevision(revision); } }).catch(cause => { if (active) setError(cause.message); }); }, QUERY_DEBOUNCE_MS);
    return () => { active = false; clearTimeout(timer); };
  }, [query, revision]);
  useEffect(() => { list.current?.querySelector<HTMLElement>('[aria-selected=true]')?.scrollIntoView({ block: 'nearest' }); }, [selected]);
  const ready = loadedQuery === query && loadedRevision === revision;
  const run = async (entry: PaletteEntry) => {
    if (busy || !ready) return; setBusy(true); setError('');
    try { const result = await window.ankita.invoke<{ kind: string; command?: string; notice?: string }>('palette:run', { id: entry.id, threadId }); if (result.notice) { setError(result.notice); return; } onClose(); if (result.command) onCommand(result.command); }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setBusy(false); }
  };
  return <div className="palette-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="command-palette" role="dialog" aria-modal="true" aria-label="Command palette" onKeyDown={event => {
      if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); onClose(); }
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') { event.preventDefault(); setSelected(index => entries.length ? (index + (event.key === 'ArrowDown' ? 1 : -1) + entries.length) % entries.length : 0); }
      if (event.key === 'Enter' && event.target === input.current && entries[selected]) { event.preventDefault(); void run(entries[selected]); }
      if (event.key === 'Tab') { event.preventDefault(); if (event.target === input.current) event.currentTarget.querySelector<HTMLButtonElement>('.palette-escape')?.focus(); else input.current?.focus(); }
    }}>
      <div className="palette-search"><Icon name="search" size={19} /><input ref={input} role="combobox" aria-label="Search commands, skills and jobs" aria-controls="palette-results" aria-expanded="true" aria-activedescendant={entries[selected] ? `palette-entry-${selected}` : undefined} value={query} onChange={event => setQuery(event.target.value)} placeholder="Search commands, skills and tasks…" /><button className="palette-escape" onClick={onClose}>esc</button></div>
      <div className="palette-results" ref={list} id="palette-results" role="listbox" aria-label="Matching actions">
        {entries.map((entry, index) => <button disabled={busy || !ready} tabIndex={-1} id={`palette-entry-${index}`} key={entry.id} role="option" aria-selected={selected === index} className={selected === index ? 'selected' : ''} onMouseEnter={() => setSelected(index)} onClick={() => void run(entry)}><Icon name={entry.source === 'job' ? 'clock' : entry.source === 'skill' ? 'sparkle' : 'panel'} size={17} /><span><strong>{entry.title}</strong><small>{entry.hint}</small></span><span className="palette-badge">{entry.source}</span>{entry.nextRunAt && <time>{new Date(entry.nextRunAt).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}</time>}</button>)}
        {!entries.length && <p className="palette-empty">No matching actions.</p>}
      </div>
      <footer><span>{busy ? 'Running…' : '↑ ↓ navigate · Enter run'}</span><span>Commands · Skills · Tasks</span></footer>
      {error && <p className="palette-error" role="status">{error}</p>}
    </section>
  </div>;
}
