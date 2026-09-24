import { capOutput } from '../tools/_shared.mjs';

/**
 * Vision attachments are billed by pixels, not by base64 length. A 1.6 MB PNG
 * can cost fewer than a thousand tokens, while measuring its data URL as text
 * guarantees history trimming deletes it before the model ever sees it.
 */
const IMAGE_DATA_URL = /^data:image\/(png|jpe?g|gif|webp);base64,([A-Za-z0-9+/=]+)$/i;
const IMAGE_TOKEN_BYTES = 4;

function bytesFromDataUrl(url) {
  const match = typeof url === 'string' ? url.match(IMAGE_DATA_URL) : null;
  if (!match) return null;
  try {
    return Buffer.from(match[2], 'base64');
  } catch {
    return null;
  }
}

function pngDimensions(bytes) {
  if (bytes.length < 24) return null;
  if (!bytes.subarray(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]))) return null;
  if (bytes.toString('latin1', 12, 16) !== 'IHDR') return null;
  return { width: bytes.readUInt32BE(16), height: bytes.readUInt32BE(20) };
}

function gifDimensions(bytes) {
  if (bytes.length < 10) return null;
  const signature = bytes.toString('latin1', 0, 6);
  if (signature !== 'GIF87a' && signature !== 'GIF89a') return null;
  return { width: bytes.readUInt16LE(6), height: bytes.readUInt16LE(8) };
}

function jpegDimensions(bytes) {
  if (bytes.length < 4 || bytes[0] !== 0xff || bytes[1] !== 0xd8) return null;
  let offset = 2;
  while (offset + 4 <= bytes.length) {
    if (bytes[offset] !== 0xff) return null;
    const marker = bytes[offset + 1];
    offset += 2;
    if (marker === 0xd8 || (marker >= 0xd0 && marker <= 0xd7)) continue;
    if (marker === 0xd9 || marker === 0x00) return null;
    if (offset + 2 > bytes.length) return null;
    const size = (bytes[offset] << 8) | bytes[offset + 1];
    if (size < 2 || offset + size > bytes.length) return null;
    if ([0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf].includes(marker)) {
      if (size < 7) return null;
      return { width: (bytes[offset + 5] << 8) | bytes[offset + 6], height: (bytes[offset + 3] << 8) | bytes[offset + 4] };
    }
    offset += size;
  }
  return null;
}

function webpDimensions(bytes) {
  if (bytes.length < 30) return null;
  if (bytes.toString('latin1', 0, 4) !== 'RIFF' || bytes.toString('latin1', 8, 12) !== 'WEBP') return null;
  const kind = bytes.toString('latin1', 12, 16);
  if (kind === 'VP8 ') {
    return {
      width: (bytes[26] | (bytes[27] << 8)) & 0x3fff,
      height: (bytes[28] | (bytes[29] << 8)) & 0x3fff,
    };
  }
  if (kind === 'VP8L') {
    if (bytes.length < 25 || bytes[20] !== 0x2f) return null;
    const packed = (bytes[21] | (bytes[22] << 8) | (bytes[23] << 16) | (bytes[24] << 24)) >>> 0;
    return { width: (packed & 0x3fff) + 1, height: ((packed >> 14) & 0x3fff) + 1 };
  }
  if (kind === 'VP8X') {
    return {
      width: (bytes[24] | (bytes[25] << 8) | (bytes[26] << 16)) + 1,
      height: (bytes[27] | (bytes[28] << 8) | (bytes[29] << 16)) + 1,
    };
  }
  return null;
}

/** Pixel dimensions for a supported image data URL; null when unreadable. */
export function imageDimensions(url) {
  const bytes = bytesFromDataUrl(url);
  if (!bytes) return null;
  return pngDimensions(bytes) || gifDimensions(bytes) || jpegDimensions(bytes) || webpDimensions(bytes);
}

/**
 * Conservative visual-token estimate for an image URL.
 *
 * This follows the common high-detail recipe: fit inside 2048px, resize the
 * short side to 768px, then count 512px tiles. It is intentionally an upper
 * bound across OpenAI-compatible vision endpoints.
 */
export function estimateImageTokens(url) {
  const dimensions = imageDimensions(url);
  if (!dimensions) return null;
  let { width, height } = dimensions;
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) return null;
  const fit = 2048 / Math.max(width, height);
  if (fit < 1) {
    width = Math.max(1, Math.floor(width * fit));
    height = Math.max(1, Math.floor(height * fit));
  }
  const detail = 768 / Math.min(width, height);
  if (detail !== 1) {
    width = Math.max(1, Math.floor(width * detail));
    height = Math.max(1, Math.floor(height * detail));
  }
  return 85 + 170 * Math.ceil(width / 512) * Math.ceil(height / 512);
}

/**
 * Budget bytes for an image URL. Decodable images use visual tokens; anything
 * else keeps the old conservative behavior of measuring the URL itself.
 */
export function estimateImageBytes(url) {
  const tokens = estimateImageTokens(url);
  if (tokens == null) return Buffer.byteLength(String(url || ''));
  return Math.max(1, tokens * IMAGE_TOKEN_BYTES);
}

function partCost(part) {
  if (part?.type === 'text') return Buffer.byteLength(String(part.text ?? ''));
  if (part?.type === 'image_url') return estimateImageBytes(part.image_url?.url);
  if (typeof part === 'string') return Buffer.byteLength(part);
  return Buffer.byteLength(JSON.stringify(part ?? null));
}

/** Budget cost for message content, with images measured as vision tokens. */
export function contentCost(content) {
  if (typeof content === 'string') return Buffer.byteLength(content);
  if (Array.isArray(content)) return content.reduce((total, part) => total + partCost(part), 0);
  return Buffer.byteLength(JSON.stringify(content ?? null));
}

/** Budget cost for a message, with images measured as vision tokens. */
export function messageCost(message) {
  if (!message || typeof message !== 'object') return Buffer.byteLength(JSON.stringify(message ?? null));
  const { content, ...rest } = message;
  return Buffer.byteLength(JSON.stringify(rest)) + contentCost(content);
}

/** Budget cost for a conversation, with images measured as vision tokens. */
export function conversationCost(messages) {
  if (!Array.isArray(messages)) return 0;
  return messages.reduce((total, message) => total + messageCost(message), 0);
}

/** True when a message carries usable content: a string or multimodal parts. */
function usableContent(content) {
  if (typeof content === 'string') return content;
  if (Array.isArray(content)) return content.length ? content : null;
  return null;
}

/** Discard malformed/orphan tool messages from interrupted saved sessions. */
export function sanitizeMessages(messages) {
  if (!Array.isArray(messages)) throw new Error('Session messages must be an array.');
  const out = [];
  for (let i = 0; i < messages.length; i++) {
    const m = messages[i];
    if (!m || !['user', 'assistant', 'system', 'tool'].includes(m.role)) continue;
    if (m.role === 'tool') continue;
    // A user turn with attachments stores an array of content parts. Dropping
    // non-strings here silently deleted those turns from restored history, so
    // the model lost the attachment (and re-answered stale context).
    const content = usableContent(m.content);
    const asText = typeof content === 'string' ? content : null;
    if (m.role === 'assistant' && Array.isArray(m.tool_calls) && m.tool_calls.length) {
      const calls = m.tool_calls;
      const ids = new Set(calls.map(c => c?.id));
      const replies = [];
      let j = i + 1;
      while (messages[j]?.role === 'tool') replies.push(messages[j++]);
      const valid = ids.size === calls.length && calls.every(c => typeof c?.id === 'string' && c.id &&
        c.type === 'function' && typeof c.function?.name === 'string' && typeof c.function?.arguments === 'string') &&
        replies.length === calls.length && new Set(replies.map(r => r.tool_call_id)).size === calls.length &&
        replies.every(r => ids.has(r.tool_call_id) && typeof r.content === 'string');
      if (valid) {
        out.push({ role: 'assistant', content, tool_calls: calls.map(c => ({ id: c.id, type: 'function', function: { name: c.function.name, arguments: c.function.arguments } })) });
        out.push(...replies.map(r => ({ role: 'tool', tool_call_id: r.tool_call_id, content: capOutput(r.content) })));
      } else if (asText) out.push({ role: 'assistant', content: asText + '\n[Incomplete tool calls removed from restored session.]' });
      i = j - 1;
    } else if (content !== null) out.push({ role: m.role, content });
  }
  return out;
}

function groups(messages) {
  const out = [];
  for (let i = 0; i < messages.length; i++) {
    const group = [messages[i]];
    if (messages[i].tool_calls) while (messages[i + 1]?.role === 'tool') group.push(messages[++i]);
    out.push(group);
  }
  return out;
}

/** Count messages, preserve the current task, and remove tool exchanges atomically. */
export function trimMessages(messages, maxMessages = 40, maxBytes = Infinity) {
  const clean = sanitizeMessages(messages);
  const system = clean[0]?.role === 'system' ? clean.shift() : { role: 'system', content: '' };
  const max = Math.max(2, Number(maxMessages) || 40);
  let userIndex = -1;
  for (let i = clean.length - 1; i >= 0; i--) if (clean[i].role === 'user') { userIndex = i; break; }
  const anchor = userIndex < 0 ? null : clean[userIndex];
  const candidates = groups(clean.filter((_, i) => i !== userIndex));
  let selected = [];
  let count = anchor ? 1 : 0;
  for (let i = candidates.length - 1; i >= 0; i--) {
    if (count + candidates[i].length > max) break;
    selected.unshift(candidates[i]);
    count += candidates[i].length;
  }
  // Preserve chronological ordering around the anchored user message.
  const assemble = () => {
    const keep = new Set(selected.flat());
    if (anchor) keep.add(anchor);
    return [system, ...clean.filter(m => keep.has(m))];
  };
  let result = assemble();
  const size = () => conversationCost(result);
  while (size() > maxBytes && selected.length > 1) { selected.shift(); result = assemble(); }
  if (size() > maxBytes) {
    result = result.map(m => ({ ...m }));
    // The largest message is usually the current user turn with an attachment,
    // whose content is an array of parts rather than a string. Trimming only
    // strings left that turn untouched, so it still exceeded the budget and the
    // turn failed outright.
    const textUnits = (m) => {
      if (typeof m.content === 'string') return [{ kind: 'string', get: () => m.content, set: (v) => { m.content = v; } }];
      if (!Array.isArray(m.content)) return [];
      const units = m.content
        .filter(part => part?.type === 'text' && typeof part.text === 'string')
        .map(part => ({
          kind: /^Attached file:/.test(part.text) ? 'attachment' : 'string',
          drop: () => { m.content = m.content.filter(item => item !== part); },
          get: () => part.text,
          set: (v) => { part.text = v; },
        }));
      // A page render or pasted image cannot be shrunk like text. It is budgeted
      // as visual tokens, so a decodable image is only dropped when those
      // tokens genuinely do not fit - losing an image is still better than
      // failing the whole turn.
      for (const part of m.content) {
        if (part?.type !== 'image_url' || typeof part.image_url?.url !== 'string') continue;
        units.push({
          kind: 'image',
          drop: () => { m.content = m.content.filter(item => item !== part); },
          get: () => part.image_url.url,
          set: () => {},
        });
      }
      return units;
    };
    const units = [];
    for (const m of result) {
      if (m.role === 'system') continue;
      for (const part of textUnits(m)) units.push(part);
    }
    const unitCost = (unit) => (unit.kind === 'image' ? estimateImageBytes(unit.get()) : Buffer.byteLength(unit.get()));
    // Shrink the biggest text first. An attachment block is droppable as a last
    // resort: losing the file body is far better than failing the whole turn.
    for (const part of units.sort((a, b) => unitCost(b) - unitCost(a))) {
      const excess = size() - maxBytes;
      if (excess <= 0) break;
      const current = part.get();
      part.set(capOutput(current, Math.max(128, unitCost(part) - excess - 64)));
    }
    // Images go first: they are the largest single unit and cannot be shrunk.
    for (const part of units.filter(unit => unit.kind === 'image')) {
      if (size() <= maxBytes) break;
      part.drop?.();
    }
    for (const part of units.filter(unit => unit.kind === 'attachment')) {
      if (size() <= maxBytes) break;
      part.drop?.();
    }
  }
  if (size() > maxBytes) throw new Error('The current request/tool schema exceeds the model context budget. Use a larger context model or clear/reduce the request.');
  return result;
}
