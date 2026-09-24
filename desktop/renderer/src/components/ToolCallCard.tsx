import { useEffect, useState } from 'react';
import type { ChatMessage } from '../../../shared/wire';
import { Icon } from './Icons';
import { CopyButton } from './CopyButton';
import { formatDuration, humanizeTool, summarizeArgs } from '../lib/format';

type ToolMessage = Extract<ChatMessage, { role: 'tool' }>;
type LocalImage = { type: 'generated_image' | 'downloaded_image'; path: string; prompt?: string; photographer?: string; source?: string; pageUrl?: string; mime?: string };
type StockImage = { id: string; title: string; previewUrl: string; imageUrl: string; pageUrl: string; photographer: string; source: string };
type StockResults = { type: 'stock_image_results'; provider: string; query: string; results: StockImage[] };

function imagePayload(result: string): LocalImage | StockResults | null {
  try {
    const value = JSON.parse(result);
    if (['generated_image', 'downloaded_image'].includes(value?.type) && typeof value.path === 'string') return value as LocalImage;
    if (value?.type === 'stock_image_results' && Array.isArray(value.results)) return value as StockResults;
  } catch {}
  return null;
}

export function ToolCallCard({ message, threadId }: { message: ToolMessage; threadId: string }) {
  const [open, setOpen] = useState(message.isError);
  const [generatedPreview, setGeneratedPreview] = useState('');
  const [previewError, setPreviewError] = useState('');
  useEffect(() => { if (message.isError) setOpen(true); }, [message.isError]);

  const running = !message.result && !message.isError;
  const image = !message.isError ? imagePayload(message.result) : null;
  const localImage = image && image.type !== 'stock_image_results' ? image : null;
  const stock = image?.type === 'stock_image_results' ? image : null;
  const title = humanizeTool(message.name);
  const hint = summarizeArgs(message.args);
  const duration = message.startedAt && message.endedAt ? formatDuration(message.endedAt - message.startedAt) : '';
  const input = typeof message.args === 'string' ? message.args : JSON.stringify(message.args, null, 2);

  useEffect(() => {
    setGeneratedPreview('');
    setPreviewError('');
    if (!localImage?.path || !window.ankita) return;
    let current = true;
    void window.ankita.invoke<{ dataUrl: string }>('readGeneratedImage', { id: threadId, path: localImage.path })
      .then(value => { if (current) setGeneratedPreview(value.dataUrl); })
      .catch(error => { if (current) setPreviewError((error as Error).message || 'Preview unavailable'); });
    return () => { current = false; };
  }, [localImage?.path, threadId]);

  const openExternal = (url: string) => { if (url) void window.ankita.openExternal(url); };

  return <div className={`tool-card ${message.isError ? 'failed' : ''} ${running ? 'running' : ''}`}>
    <button type="button" className="tool-card-header" onClick={() => setOpen(!open)} aria-expanded={open}>
      <span className="tool-glyph">{running ? <span className="tool-spinner" /> : <Icon name={message.isError ? 'alert' : 'check'} size={15} />}</span>
      <span className="tool-card-title">{title}</span>
      {hint && <span className="tool-card-hint">{hint}</span>}
      <span className="tool-card-state">{message.isError ? 'Needs attention' : running ? 'Running' : duration || 'Completed'}</span>
      <span className={`tool-card-chevron ${open ? 'open' : ''}`}><Icon name="chevron" size={16} /></span>
    </button>
    {localImage && <div className="image-tool-preview">
      {generatedPreview ? <img src={generatedPreview} alt={localImage.prompt || `${localImage.source || 'Generated'} image`} /> : <div className="image-preview-placeholder">{previewError || 'Loading image preview…'}</div>}
      <div className="image-preview-caption"><strong>{localImage.type === 'generated_image' ? 'Generated image' : `Downloaded ${localImage.source || 'stock'} image`}</strong><span title={localImage.path}>{localImage.path}</span></div>
    </div>}
    {stock && <div className="stock-image-grid">
      {stock.results.map(item => <figure key={`${stock.provider}-${item.id}`}>
        <button type="button" className="stock-image-preview" onClick={() => openExternal(item.pageUrl)} title={`Open on ${item.source}`}>
          <img src={item.previewUrl} alt={item.title} loading="lazy" referrerPolicy="no-referrer" />
        </button>
        <figcaption><span title={item.title}>{item.title}</span><button type="button" onClick={() => openExternal(item.pageUrl)}>{item.photographer} · {item.source}</button></figcaption>
      </figure>)}
      {!stock.results.length && <p className="image-search-empty">No {stock.provider} images found for “{stock.query}”.</p>}
    </div>}
    {open && <div className="tool-card-body">
      <div className="tool-card-toolbar"><span className="tool-section-label">Input</span><CopyButton text={input} compact /></div>
      <pre>{input}</pre>
      <div className="tool-card-toolbar"><span className="tool-section-label">Result</span>{message.result && <CopyButton text={message.result} compact />}</div>
      <pre>{message.result || (running ? 'Waiting for the tool…' : '(no output)')}</pre>
    </div>}
  </div>;
}
