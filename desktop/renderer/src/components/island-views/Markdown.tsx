// Island markdown — same stack as the main app's Message.tsx
// (react-markdown + remark-gfm, MIT), scaled down for the 368px card.
// Links open externally; workspace images load over the constrained IPC.

import { memo, useEffect, useState } from 'react';
import ReactMarkdown, { defaultUrlTransform } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { formatAssistantMarkdown } from '../../../../shared/assistant-markdown.mjs';

// Shut an unclosed ``` fence for display only (never stored) so a streamed
// code block parses instead of printing raw backticks.
function closeOpenFence(text: string): string {
  const marks = text.match(/^ {0,3}```/gm) || [];
  return marks.length % 2 === 1 ? `${text}\n\`\`\`` : text;
}

function IslandImage({ src, alt, teammateId }: { src?: string; alt?: string; teammateId: string | null }) {
  const [dataUrl, setDataUrl] = useState('');
  const [failed, setFailed] = useState(false);
  const local = src && !/^https?:|^data:/i.test(src)
    ? /(?:^|[\\/])(?:generated-images|downloaded-images)[\\/]/i.test(src) ? src : null
    : null;
  useEffect(() => {
    setDataUrl('');
    setFailed(false);
    if (!local || !teammateId) return;
    let active = true;
    void window.ankita.invoke<{ dataUrl: string }>('readGeneratedImage', { id: teammateId, path: local })
      .then(result => { if (active) setDataUrl(result.dataUrl); })
      .catch(() => { if (active) setFailed(true); });
    return () => { active = false; };
  }, [local, teammateId]);
  if (!src) return null;
  if (local) {
    if (failed) return <span className="island-quiet">Image unavailable: {alt || 'image'}</span>;
    if (!dataUrl) return <span className="island-quiet">Loading image…</span>;
    return <img className="island-md-img" src={dataUrl} alt={alt || 'Workspace image'} loading="lazy" />;
  }
  return <img className="island-md-img" src={defaultUrlTransform(src)} alt={alt || ''} loading="lazy" referrerPolicy="no-referrer" />;
}

export const IslandMarkdown = memo(function IslandMarkdown({
  content, teammateId, streaming = false,
}: {
  content: string;
  teammateId: string | null;
  streaming?: boolean;
}) {
  // Repair completed answers only; a partial table or fence is still being written.
  const displayed = closeOpenFence(streaming ? content : formatAssistantMarkdown(content));
  return (
    <div className="island-md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children }) => (
            <a
              href={href}
              onClick={event => {
                event.preventDefault();
                event.stopPropagation();
                if (href) void window.ankita.openExternal(href);
              }}
            >
              {children}
            </a>
          ),
          img: ({ src, alt }) => <IslandImage src={src} alt={alt} teammateId={teammateId} />,
        }}
        urlTransform={url => {
          if (/^file:/i.test(url) || /^[a-z]:[\\/]/i.test(url) || /(?:^|[\\/])(?:generated-images|downloaded-images)[\\/]/i.test(url) || /^data:image\/(?:png|jpeg|webp);base64,/i.test(url)) return url;
          return defaultUrlTransform(url);
        }}
      >
        {displayed}
      </ReactMarkdown>
    </div>
  );
});
