import { useEffect, useId, useMemo, useRef } from 'react';
import type { DraftAttachment } from '../../../shared/companion-drafts.mjs';
import './context-preview.css';

const PREVIEW_CHAR_LIMIT = 12000; // Visible characters; full accepted attachment stays available to the request.

export function ContextPreview({ attachment, onClose, onRemove }: { attachment: DraftAttachment; onClose: () => void; onRemove: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null), titleId = useId();
  const text = useMemo(() => {
    if (attachment.image) return '';
    try { return new TextDecoder().decode(Uint8Array.from(atob(attachment.data), character => character.charCodeAt(0))); }
    catch { return 'This attachment cannot be previewed. Remove it and attach the original again.'; }
  }, [attachment]);
  useEffect(() => { dialog.current?.showModal(); }, []);
  return <dialog ref={dialog} className="context-preview" aria-labelledby={titleId} onCancel={event => { event.preventDefault(); onClose(); }}>
    <header><div><h2 id={titleId}>{attachment.name}</h2><p>Attached to this request. Check its source and content before sending.</p></div><button type="button" onClick={onClose}>Close preview</button></header>
    <div className="context-preview-body">{attachment.image ? attachment.preview ? <img src={attachment.preview} alt={attachment.name} /> : <p>An image is attached. A preview is unavailable.</p> : <pre>{text.slice(0, PREVIEW_CHAR_LIMIT)}</pre>}
      {text.length > PREVIEW_CHAR_LIMIT && <p>Showing the beginning of this attachment. The full accepted file is still attached.</p>}
    </div><footer><button type="button" onClick={onRemove}>Remove attachment</button><button type="button" className="button-primary" onClick={onClose}>Keep attachment</button></footer>
  </dialog>;
}
