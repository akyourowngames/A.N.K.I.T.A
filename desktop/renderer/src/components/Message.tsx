import { useEffect, useState } from 'react';
import ReactMarkdown, { defaultUrlTransform } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { ChatMessage, Teammate } from '../../../shared/wire';
import { ToolCallCard } from './ToolCallCard';
import { ThinkingPanel } from './ThinkingPanel';
import { CopyButton } from './CopyButton';
import { Icon } from './Icons';

function localWorkspaceImage(src: string): string | null {
  let value = src;
  if (/^https?:|^data:/i.test(value)) return null;
  if (/^file:/i.test(value)) {
    try {
      const url = new URL(value);
      value = decodeURIComponent(url.pathname);
      if (/^\/[a-z]:\//i.test(value)) value = value.slice(1);
    } catch { return null; }
  } else {
    try { value = decodeURIComponent(value); } catch {}
  }
  return /(?:^|[\\/])(?:generated-images|downloaded-images)[\\/]/i.test(value) ? value : null;
}

function normalizeWorkspaceImageMarkdown(markdown: string) {
  // Windows paths commonly contain spaces, which Markdown otherwise treats as
  // the end of an image URL. Keep the complete workspace path and encode those
  // spaces before ReactMarkdown parses the destination.
  return markdown.replace(/!\[([^\]]*)\]\(([^)\r\n]+)\)/g, (whole, alt: string, destination: string) => {
    const pathMatch = destination.match(/(?:file:\/\/\/)?[a-z]:[\\/].*?(?:generated-images|downloaded-images)[\\/].*?\.(?:png|jpe?g|webp)(?:\?[^\s]*)?/i)
      || destination.match(/(?:^|<)?((?:\.\.?[\\/])?(?:generated-images|downloaded-images)[\\/].*?\.(?:png|jpe?g|webp)(?:\?[^\s]*)?)/i);
    const local = pathMatch?.[1] || (pathMatch && pathMatch[0]);
    if (!local) return whole;
    const encoded = encodeURI(local.trim()).replace(/#/g, '%23');
    return `![${alt}](<${encoded}>)`;
  });
}

function WorkspaceImage({ src, alt, threadId }: { src?: string; alt?: string; threadId: string }) {
  const [dataUrl, setDataUrl] = useState('');
  const [failed, setFailed] = useState(false);
  const localPath = src ? localWorkspaceImage(src) : null;
  useEffect(() => {
    setDataUrl('');
    setFailed(false);
    if (!localPath) return;
    let active = true;
    void window.ankita.invoke<{ dataUrl: string }>('readGeneratedImage', { id: threadId, path: localPath })
      .then(result => { if (active) setDataUrl(result.dataUrl); })
      .catch(() => { if (active) setFailed(true); });
    return () => { active = false; };
  }, [localPath, threadId]);

  if (!src) return null;
  if (localPath) {
    if (failed) return <span className="markdown-image-unavailable">Image unavailable in this workspace: {alt || 'image'}</span>;
    if (!dataUrl) return <span className="markdown-image-loading">Loading image…</span>;
    return <img className="markdown-workspace-image" src={dataUrl} alt={alt || 'Workspace image'} loading="lazy" />;
  }
  return <img src={defaultUrlTransform(src)} alt={alt || ''} loading="lazy" referrerPolicy="no-referrer" />;
}

export function Message({ message, teammate, threadId, streaming }: { message: ChatMessage; teammate: Teammate; threadId: string; streaming: boolean }) {
  if (message.role === 'tool') return <ToolCallCard message={message} threadId={threadId} />;
  if (message.role === 'user') return <div className="message user-message">
    <div className="user-bubble">
      {message.attachments?.length ? <div className="user-attachments">{message.attachments.map((file, index) => <span className="user-attachment" key={`${file.name}-${index}`}><Icon name="file" size={13} />{file.name}</span>)}</div> : null}
      {message.content}
    </div>
  </div>;
  const thinking = Boolean(message.reasoning?.trim()) && streaming && !message.content;
  return <div className="message assistant-message">
    <span className="message-avatar" style={{ '--avatar-color': teammate.color } as React.CSSProperties}>{teammate.emoji || '✦'}</span>
    <div className="assistant-content">
      <span className="assistant-name">{teammate.name}</span>
      {message.reasoning ? <ThinkingPanel reasoning={message.reasoning} streaming={thinking} /> : null}
      <div className="markdown-body">
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={{
          a: ({ href, children }) => <a href={href} onClick={event => { event.preventDefault(); if (href) void window.ankita.openExternal(href); }}>{children}</a>,
          img: ({ src, alt }) => <WorkspaceImage src={src} alt={alt} threadId={threadId} />,
        }} urlTransform={url => {
          // Preserve local image paths so WorkspaceImage can request them over
          // the constrained main-process IPC instead of the renderer trying to
          // load a file:// URL (which Electron correctly blocks).
          if (/^file:/i.test(url) || /^[a-z]:[\\/]/i.test(url) || /(?:^|[\\/])(?:generated-images|downloaded-images)[\\/]/i.test(url) || /^data:image\/(?:png|jpeg|webp);base64,/i.test(url)) return url;
          return defaultUrlTransform(url);
        }}>{normalizeWorkspaceImageMarkdown(message.content)}</ReactMarkdown>{streaming && <span className="stream-caret" aria-hidden="true" />}
      </div>
      {!streaming && message.content && <div className="message-actions"><CopyButton text={message.content} /></div>}
    </div>
  </div>;
}
