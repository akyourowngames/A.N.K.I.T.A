import { useEffect, useState } from 'react';
import type { ChatMessage } from '../../../shared/wire';
import { Icon } from './Icons';
import { CopyButton } from './CopyButton';
import { formatDuration, humanizeTool, summarizeArgs } from '../lib/format';
import { SecureStoreCard } from './SecureStore';
import { imagePayload, isBrowserLoginCall } from '../lib/activity';

type ToolMessage = Extract<ChatMessage, { role: 'tool' }>;

export function ToolCallCard({ message, threadId, onOpenBrowserPlugins, variant = 'card' }: { message: ToolMessage; threadId: string; onOpenBrowserPlugins?: () => void; variant?: 'card' | 'row' }) {
  const [open, setOpen] = useState(variant === 'card' && message.isError);
  const [generatedPreview, setGeneratedPreview] = useState('');
  const [previewError, setPreviewError] = useState('');
  useEffect(() => { if (variant === 'card' && message.isError) setOpen(true); }, [message.isError, variant]);

  const running = !message.result && !message.isError;
  const image = !message.isError ? imagePayload(message.result) : null;
  const localImage = image && image.type !== 'stock_image_results' ? image : null;
  const stock = image?.type === 'stock_image_results' ? image : null;
  const title = humanizeTool(message.name);
  const hint = summarizeArgs(message.args);
  const duration = message.startedAt && message.endedAt ? formatDuration(message.endedAt - message.startedAt) : '';
  const input = typeof message.args === 'string' ? message.args : JSON.stringify(message.args, null, 2);
  const browserSetupNeeded = message.name === 'browser' && message.isError && /Enable (?:Chrome local|Playwright Browser)|Chrome is not connected|Playwright is missing|Chromium could not start/.test(message.result);

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

  if (isBrowserLoginCall(message)) return <SecureStoreCard threadId={threadId} callId={message.callId} website={String((message.args as { website?: string }).website || '')} result={message.result} />;

  const previews = <>
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
  </>;

  const details = <div className={`tool-card-body ${variant === 'row' ? 'activity-detail' : ''}`}>
    <div className="tool-card-toolbar"><span className="tool-section-label">Input</span><CopyButton text={input} compact /></div>
    <pre>{input}</pre>
    <div className="tool-card-toolbar"><span className="tool-section-label">Result</span>{message.result && <CopyButton text={message.result} compact />}</div>
    <pre>{message.result || (running ? 'Waiting for the tool…' : '(no output)')}</pre>
    {browserSetupNeeded && onOpenBrowserPlugins && <button type="button" className="tool-browser-setup" onClick={onOpenBrowserPlugins}>Open browser setup <Icon name="arrowRight" size={14} /></button>}
  </div>;

  if (variant === 'row') return <div className={`activity-tool ${message.isError ? 'failed' : ''} ${running ? 'running' : ''}`}>
    <button type="button" className="activity-row" onClick={() => setOpen(!open)} aria-expanded={open}>
      <span className={`activity-glyph ${message.isError ? 'failed' : ''}`}>{running ? <span className="tool-spinner" /> : <Icon name={message.isError ? 'alert' : 'check'} size={13} />}</span>
      <span className="activity-label">{title}</span>
      {hint && <span className="activity-arg" title={hint}>{hint}</span>}
      {message.isError ? <span className="activity-error">Failed</span> : !running && duration ? <span className="activity-state">{duration}</span> : null}
      <span className={`activity-chevron ${open ? 'open' : ''}`}><Icon name="chevron" size={13} /></span>
    </button>
    {previews}
    {open && details}
  </div>;

  return <div className={`tool-card ${message.isError ? 'failed' : ''} ${running ? 'running' : ''}`}>
    <button type="button" className="tool-card-header" onClick={() => setOpen(!open)} aria-expanded={open}>
      <span className="tool-glyph">{running ? <span className="tool-spinner" /> : <Icon name={message.isError ? 'alert' : 'check'} size={15} />}</span>
      <span className="tool-card-title">{title}</span>
      {hint && <span className="tool-card-hint">{hint}</span>}
      <span className="tool-card-state">{message.isError ? 'Needs attention' : running ? 'Running' : duration || 'Completed'}</span>
      <span className={`tool-card-chevron ${open ? 'open' : ''}`}><Icon name="chevron" size={16} /></span>
    </button>
    {previews}
    {open && details}
  </div>;
}
