import { useEffect, useMemo, useRef, useState } from 'react';
import type { Model } from '../../../shared/wire';
import { Icon } from './Icons';
import { formatTokens } from '../lib/format';

/** Searchable model chooser: vendors grouped, context and tool support inline. */
export function ModelPicker({ models, value, onChange, openUp = false }: { models: Model[]; value: string; onChange: (id: string) => void; openUp?: boolean }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const wrap = useRef<HTMLDivElement>(null);
  const current = models.find(model => model.id === value) || models[0];

  useEffect(() => {
    if (!open) return;
    const down = (event: MouseEvent) => { if (wrap.current && !wrap.current.contains(event.target as Node)) setOpen(false); };
    const key = (event: KeyboardEvent) => { if (event.key === 'Escape') setOpen(false); };
    window.addEventListener('mousedown', down);
    window.addEventListener('keydown', key);
    return () => { window.removeEventListener('mousedown', down); window.removeEventListener('keydown', key); };
  }, [open]);
  useEffect(() => { if (!open) setQuery(''); }, [open]);

  const groups = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const filtered = models.filter(model => !needle || `${model.name || ''} ${model.id} ${model.vendor || ''}`.toLowerCase().includes(needle));
    const byVendor = new Map<string, Model[]>();
    for (const model of filtered) {
      const vendor = model.vendor || 'Models';
      const bucket = byVendor.get(vendor) || [];
      bucket.push(model);
      byVendor.set(vendor, bucket);
    }
    return [...byVendor.entries()];
  }, [models, query]);

  return <div className={`model-picker ${openUp ? 'model-picker-up' : ''}`} ref={wrap}>
    <button type="button" className="model-picker-button" onClick={() => setOpen(!open)} aria-haspopup="listbox" aria-expanded={open}>
      <span className="model-picker-label">Model</span>
      <strong>{current?.name || current?.id || 'Select a model'}</strong>
      <Icon name="chevron" size={14} />
    </button>
    {open && <div className="model-menu" role="listbox" aria-label="Choose model">
      <label className="model-search"><Icon name="search" size={15} /><input autoFocus placeholder="Search models…" value={query} onChange={event => setQuery(event.target.value)} /></label>
      <div className="model-list">
        {groups.length ? groups.map(([vendor, items]) => <div key={vendor} className="model-group">
          <div className="model-group-title">{vendor}</div>
          {items.map(model => <button
            type="button"
            key={model.id}
            role="option"
            aria-selected={model.id === value}
            className={`model-option ${model.id === value ? 'active' : ''}`}
            onClick={() => { onChange(model.id); setOpen(false); }}
          >
            <span className="model-option-name">{model.name || model.id}{model.tools === false && <em>no tools</em>}</span>
            <span className="model-option-meta">{model.context ? `${formatTokens(model.context)} ctx` : ''}</span>
            {model.id === value && <Icon name="check" size={15} />}
          </button>)}
        </div>) : <div className="model-empty">No models match “{query}”.</div>}
      </div>
    </div>}
  </div>;
}
