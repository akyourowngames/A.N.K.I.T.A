import { useEffect, useRef, useState } from 'react';
import type { Model } from '../../../shared/wire';
import { Icon } from './Icons';
import { ModelPicker } from './ModelPicker';

const MAX_IMAGE_BYTES = 10 * 1024 * 1024;
const MAX_TEXT_BYTES = 200 * 1024;
const MAX_DOC_BYTES = 20 * 1024 * 1024;
const IMAGE_NAME = /\.(png|jpe?g|webp|gif)$/i;
const OFFICE_NAME = /\.(pdf|docx|xlsx|pptx)$/i;
const TEXT_NAME = /\.(txt|md|markdown|json|jsonc|m?js|c?js|tsx?|jsx|py|rb|go|rs|java|cs|c|h|cpp|hpp|css|scss|html?|xml|ya?ml|toml|ini|cfg|env|sh|bash|ps1|sql|csv|tsv|log)$/i;
const ACCEPT = '.png,.jpg,.jpeg,.webp,.gif,.pdf,.docx,.xlsx,.pptx,.txt,.md,.markdown,.json,.js,.mjs,.cjs,.ts,.tsx,.jsx,.py,.rb,.go,.rs,.java,.cs,.c,.h,.cpp,.hpp,.css,.scss,.html,.htm,.xml,.yml,.yaml,.toml,.ini,.cfg,.env,.sh,.bash,.ps1,.sql,.csv,.tsv,.log';

type Attachment = { name: string; image: boolean; data: string; preview?: string; kind?: 'document'; images?: string[] };

/**
 * Base64 without `String.fromCharCode(...bytes)`: spreading a multi-megabyte
 * array blows the call stack ("Maximum call stack size exceeded"). This walks
 * fixed-size blocks and feeds each through a mapper.
 */
function toBase64(bytes: Uint8Array): string {
  const CHUNK = 0x8000;
  let binary = '';
  for (let i = 0; i < bytes.length; i += CHUNK) {
    binary += String.fromCharCode(...bytes.subarray(i, i + CHUNK));
  }
  return btoa(binary);
}

function fromBase64(data: string): Uint8Array {
  const binary = atob(data);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

const IMAGE_MAX_SIDE = 1600;
const IMAGE_JPEG_QUALITY = 0.82;
const IMAGE_WEBP_QUALITY = 0.82;

/** Preserve the uploader's image format; GIFs keep their original animation. */
function imageOutputType(name: string, mimeType?: string): string | null {
  const lower = name.toLowerCase();
  if (lower.endsWith('.gif') || mimeType === 'image/gif') return null;
  if (lower.endsWith('.jpg') || lower.endsWith('.jpeg') || mimeType === 'image/jpeg') return 'image/jpeg';
  if (lower.endsWith('.webp') || mimeType === 'image/webp') return 'image/webp';
  return 'image/png';
}

function loadImageElement(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error('image failed to load'));
    image.src = src;
  });
}

/**
 * Normalize an uploaded image before it enters history.
 *
 * Vision endpoints resize images themselves, so sending a 1700x2200 PNG mostly
 * adds upload bytes and session bloat. This keeps the original format, caps
 * the longest side, and falls back to the original file whenever compression
 * does not help or decoding is unavailable.
 */
async function prepareImage(name: string, bytes: Uint8Array, mimeType?: string): Promise<{ data: string; preview: string } | null> {
  const output = imageOutputType(name, mimeType);
  if (!output) return null;
  let source: ImageBitmap | HTMLImageElement | null = null;
  try {
    const blob = new Blob([bytes.slice()], { type: mimeType || output });
    if (typeof createImageBitmap === 'function') {
      try {
        source = await createImageBitmap(blob, { imageOrientation: 'from-image' });
      } catch {
        source = null;
      }
    }
    let objectUrl = '';
    if (!source) {
      objectUrl = URL.createObjectURL(blob);
      source = await loadImageElement(objectUrl);
      URL.revokeObjectURL(objectUrl);
    }
    const width = source.width;
    const height = source.height;
    if (!width || !height) return null;
    const scale = Math.min(1, IMAGE_MAX_SIDE / Math.max(width, height));
    if (scale === 1 && output === 'image/png') return null;
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(width * scale));
    canvas.height = Math.max(1, Math.round(height * scale));
    const context = canvas.getContext('2d');
    if (!context) return null;
    if (output === 'image/jpeg') {
      context.fillStyle = '#ffffff';
      context.fillRect(0, 0, canvas.width, canvas.height);
    }
    context.drawImage(source, 0, 0, canvas.width, canvas.height);
    const preview = output === 'image/png'
      ? canvas.toDataURL(output)
      : canvas.toDataURL(output, output === 'image/jpeg' ? IMAGE_JPEG_QUALITY : IMAGE_WEBP_QUALITY);
    const data = preview.split(',')[1] || '';
    // Never replace the upload with a larger normalized copy.
    if (!data || data.length >= Math.ceil(bytes.length / 3) * 4) return null;
    return { data, preview };
  } catch {
    return null;
  } finally {
    if (source instanceof ImageBitmap) source.close();
  }
}

/**
 * Turn a PDF into either its text layer or page images.
 *
 * A born-digital PDF yields text and no images - cheap and exact. A scan has no
 * text layer, so its pages are rendered and sent as images for a vision model
 * to read, with OCR as the fallback when the model cannot see.
 */
async function readPdf(name: string, bytes: Uint8Array): Promise<Attachment> {
  const { extractDocumentText, pdfTextCoverage, looksLikeProse } = await import('../lib/extract-document');
  const text = await extractDocumentText(name, bytes);
  const prose = looksLikeProse(text);
  // Only prose counts as a text layer. Decoded noise can be longer than it is
  // readable, and it used to reach the model as though it were the document.
  if (prose && !pdfTextCoverage(bytes, text).scanned) {
    return { name, image: false, kind: 'document', data: toBase64(new TextEncoder().encode(text)) };
  }
  // Scanned or unreadable: offer the rendered pages to a vision model.
  const pages = await renderPdfPages(bytes);
  if (pages.length) {
    return {
      name,
      image: false,
      kind: 'document',
      data: toBase64(new TextEncoder().encode(prose ? text : '(scanned pages attached as images)')),
      images: pages,
    };
  }
  // No pages either: use OCR when available, but never fall back to decoded
  // noise simply because extraction returned a long string.
  const ocr = await ocrPages(pages);
  const readable = ocr.trim() ? ocr : (prose ? text : '');
  if (!readable.trim()) throw new Error(`${name} could not be read: it has no text layer and its pages could not be rendered`);
  return { name, image: false, kind: 'document', data: toBase64(new TextEncoder().encode(readable)) };
}

/** Render PDF pages in the main process; [] when unavailable. */
async function renderPdfPages(bytes: Uint8Array): Promise<string[]> {
  try {
    const pages = await window.ankita.invoke<string[]>('renderPdfPages', { data: toBase64(bytes) });
    return Array.isArray(pages) ? pages : [];
  } catch {
    return [];
  }
}

/** OCR page images on demand; '' when OCR is unavailable. */
async function ocrPages(pages: string[]): Promise<string> {
  if (!pages.length) return '';
  try {
    const { ocrImages } = await import('../lib/ocr');
    return await ocrImages(pages);
  } catch {
    return '';
  }
}

/** Read a File into an attachment, with a size cap per kind. */
async function readFile(file: File): Promise<Attachment> {
  const image = IMAGE_NAME.test(file.name);
  const office = OFFICE_NAME.test(file.name);
  if (!image && !office && !TEXT_NAME.test(file.name)) throw new Error(`${file.name} is not a supported file type`);
  const limit = image ? MAX_IMAGE_BYTES : office ? MAX_DOC_BYTES : MAX_TEXT_BYTES;
  if (file.size > limit) throw new Error(`${file.name} is larger than ${image ? '10 MB' : office ? '20 MB' : '200 KB'}`);
  const bytes = new Uint8Array(await file.arrayBuffer());
  const data = toBase64(bytes);
  if (image) {
    const mimeType = file.type.startsWith('image/') ? file.type : undefined;
    const prepared = await prepareImage(file.name, bytes, mimeType);
    if (prepared) return { name: file.name, image, data: prepared.data, preview: prepared.preview };
    return { name: file.name, image, data, preview: `data:${file.type || 'image/png'};base64,${data}` };
  }
  if (file.name.toLowerCase().endsWith('.pdf')) return readPdf(file.name, bytes);
  if (office) {
    // Office formats carry compressed XML rather than text, so extract here and
    // send the readable result, flagged so the engine keeps the original name.
    const { extractDocumentText } = await import('../lib/extract-document');
    const text = await extractDocumentText(file.name, bytes);
    if (!text.trim()) throw new Error(`No readable text found in ${file.name}`);
    return { name: file.name, image: false, kind: 'document', data: toBase64(new TextEncoder().encode(text)) };
  }
  return { name: file.name, image: false, data: toBase64(new TextEncoder().encode(new TextDecoder().decode(bytes))) };
}

export function Composer({ threadId, name, running, models, model, onModel, onSend, onStop }: {
  threadId: string; name: string; running: boolean; models: Model[]; model: string;
  onModel: (id: string) => void; onSend: (text: string, attachments?: { name: string; data: string; kind?: 'document'; images?: string[] }[]) => void; onStop: () => void;
}) {
  const [text, setText] = useState('');
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [notice, setNotice] = useState('');
  const [reading, setReading] = useState(false);
  const input = useRef<HTMLTextAreaElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => { if (input.current) { input.current.style.height = 'auto'; input.current.style.height = `${Math.min(input.current.scrollHeight, 170)}px`; } }, [text]);
  useEffect(() => { setText(''); setAttachments([]); setNotice(''); }, [threadId]);
  // Ctrl/Cmd+U opens the file picker. It is ignored while typing in a field
  // elsewhere in the app, but the composer's own message box is exactly where
  // the shortcut is expected to work.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey) || event.altKey || event.key.toLowerCase() !== 'u') return;
      const target = event.target as HTMLElement | null;
      const own = target === input.current;
      const editing = Boolean(target && (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)));
      if (editing && !own) return;
      event.preventDefault();
      fileInput.current?.click();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const addFiles = async (files: FileList | null) => {
    if (!files?.length) return;
    setNotice('');
    setReading(true);
    const added: Attachment[] = [];
    for (const file of Array.from(files).slice(0, 8)) {
      try { added.push(await readFile(file)); }
      catch (error) { setNotice((error as Error).message); }
    }
    if (added.length) setAttachments(current => [...current, ...added].slice(0, 8));
    setReading(false);
  };

  const removeAttachment = (index: number) => setAttachments(current => current.filter((_, i) => i !== index));
  const submit = () => {
    if (running || reading || (!text.trim() && !attachments.length)) return;
    onSend(text.trim(), attachments.map(({ name: fileName, data, kind, images }) => ({ name: fileName, data, kind, ...(images?.length ? { images } : {}) })));
    setText(''); setAttachments([]); setNotice(''); input.current?.focus();
  };

  return <div className="composer-area"><div className="composer-shell"
    onDragOver={event => { event.preventDefault(); }}
    onDrop={event => { event.preventDefault(); void addFiles(event.dataTransfer?.files || null); }}>
    <textarea ref={input} rows={1} value={text} onChange={event => setText(event.target.value)} onKeyDown={event => {
      if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); submit(); }
    }} onPaste={event => { if (event.clipboardData?.files?.length) { event.preventDefault(); void addFiles(event.clipboardData.files); } }}
      placeholder={`Ask ${name} anything…`} aria-label={`Message ${name}`} disabled={running} />
    {(attachments.length > 0 || notice || reading) && <div className="composer-attachments">
      {attachments.map((file, index) => <span className="attachment-chip" key={`${file.name}-${index}`}>
        {file.preview ? <img src={file.preview} alt="" /> : <Icon name="file" size={14} />}
        <span className="attachment-name" title={file.name}>{file.name}</span>
        <button type="button" onClick={() => removeAttachment(index)} aria-label={`Remove ${file.name}`}><Icon name="close" size={12} /></button>
      </span>)}
      {reading && <span className="attachment-notice dim" role="status">Reading files…</span>}
      {notice && <span className="attachment-notice" role="status">{notice}</span>}
    </div>}
    <div className="composer-bottom">
      <div className="composer-tools">
        <input ref={fileInput} type="file" multiple hidden accept={ACCEPT}
          onChange={event => { void addFiles(event.target.files); event.target.value = ''; }} />
        <button type="button" className="composer-icon" onClick={() => fileInput.current?.click()} disabled={running} title="Attach images, documents or code (Ctrl+U)" aria-label="Attach files"><Icon name="plus" size={18} /></button>
        <span className="composer-key-hint">Enter to send <span aria-hidden="true">·</span> Shift + Enter for a new line <span aria-hidden="true">·</span> Ctrl + U to attach</span>
      </div>
      <div className="composer-controls">
        <ModelPicker models={models} value={model} onChange={onModel} openUp />
        {running ? <button type="button" className="composer-action stop" onClick={onStop} title="Stop response" aria-label="Stop response"><Icon name="stop" size={17} /></button>
          : <button type="button" className="composer-action send" onClick={submit} disabled={(!text.trim() && !attachments.length) || reading} title="Send message" aria-label="Send message"><Icon name="send" size={19} stroke={2.1} /></button>}
      </div>
    </div>
  </div></div>;
}
