/**
 * Best-effort text extraction for the document formats people actually attach.
 *
 * Runs in the renderer, where the browser's built-in DecompressionStream gives
 * us gzip/zlib for free, so no dependency is added. The result is plain text
 * that the agent already knows how to read.
 *
 *   .pdf   - inflates FlateDecode streams and pulls the text-showing operators
 *   .docx  - unzips word/document.xml and strips tags
 *   .xlsx  - unzips sharedStrings.xml plus the sheet XML
 *   .pptx  - unzips ppt/slides/*.xml and strips tags
 *
 * It is deliberately shallow: enough to read a document, not a full parser.
 */

const MAX_OUTPUT = 120_000;

function decodeUtf8(bytes: Uint8Array): string {
  return new TextDecoder('utf-8').decode(bytes);
}

/* ------------------------------- ZIP (docx/xlsx/pptx) ------------------- */

export type ZipEntry = { name: string; method: number; compressedSize: number; localOffset: number };

/** Minimal ZIP central-directory reader; entries are stored/deflated. */
export function readZipEntries(bytes: Uint8Array): ZipEntry[] {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  // Find End Of Central Directory (signature 0x06054b50), scanning back over the
  // comment field (max 65535 bytes).
  let eocd = -1;
  for (let i = bytes.length - 22; i >= Math.max(0, bytes.length - 22 - 65535); i--) {
    if (view.getUint32(i, true) === 0x06054b50) { eocd = i; break; }
  }
  if (eocd < 0) throw new Error('Not a valid ZIP container');
  const count = view.getUint16(eocd + 10, true);
  let offset = view.getUint32(eocd + 16, true);
  const entries = [];
  for (let n = 0; n < count && offset + 46 <= bytes.length; n++) {
    if (view.getUint32(offset, true) !== 0x02014b50) break;
    const method = view.getUint16(offset + 10, true);
    const compressedSize = view.getUint32(offset + 20, true);
    const nameLength = view.getUint16(offset + 28, true);
    const extraLength = view.getUint16(offset + 30, true);
    const commentLength = view.getUint16(offset + 32, true);
    const localOffset = view.getUint32(offset + 42, true);
    const name = decodeUtf8(bytes.subarray(offset + 46, offset + 46 + nameLength));
    entries.push({ name, method, compressedSize, localOffset });
    offset += 46 + nameLength + extraLength + commentLength;
  }
  return entries;
}

async function inflateRaw(bytes: Uint8Array) {
  const stream = new Blob([bytes.slice()]).stream().pipeThrough(new DecompressionStream('deflate-raw'));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

/** zlib wrapper (0x78 ..) around raw deflate, the common PDF stream encoding. */
async function inflate(bytes: Uint8Array) {
  // Chromium's DecompressionStream rejects any bytes after the compressed
  // stream's end, so trim the tail before inflating.
  const data = trimTrailing(bytes);
  try {
    const stream = new Blob([data.slice()]).stream().pipeThrough(new DecompressionStream('deflate'));
    return new Uint8Array(await new Response(stream).arrayBuffer());
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    if (message && !/junk|unexpected|invalid/i.test(message)) throw error;
    // Fall back to raw deflate for a missing/odd zlib header.
    const stream = new Blob([data.slice(2)]).stream().pipeThrough(new DecompressionStream('deflate-raw'));
    return new Uint8Array(await new Response(stream).arrayBuffer());
  }
}

/** Drop trailing whitespace/newlines that follow the deflate end marker. */
function trimTrailing(bytes: Uint8Array) {
  let end = bytes.length;
  while (end > 0 && [0x00, 0x09, 0x0a, 0x0d, 0x20].includes(bytes[end - 1])) end--;
  return bytes.subarray(0, end);
}

async function zipFileText(bytes: Uint8Array, matcher: (name: string) => boolean) {
  const entries = readZipEntries(bytes).filter((entry) => matcher(entry.name));
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const chunks = [];
  for (const entry of entries) {
    // Local header length varies with its own name/extra fields.
    const nameLength = view.getUint16(entry.localOffset + 26, true);
    const extraLength = view.getUint16(entry.localOffset + 28, true);
    const start = entry.localOffset + 30 + nameLength + extraLength;
    const raw = bytes.subarray(start, start + entry.compressedSize);
    const data = entry.method === 0 ? raw : await inflateRaw(raw);
    chunks.push(decodeUtf8(data));
  }
  return chunks.join('\n');
}

/* --------------------------------- XML ---------------------------------- */

function stripXml(xml: string) {
  return xml
    .replace(/<w:p\b[^>]*>/g, '\n')       // Word: paragraph break
    .replace(/<\/a:p>/g, '\n')            // PowerPoint: paragraph break
    .replace(/<[^>]+>/g, '')
    .replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&')
    .replace(/&quot;/g, '"').replace(/&apos;/g, "'")
    .replace(/[ \t]+/g, ' ')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

/* --------------------------------- PDF ---------------------------------- */

/** ASCII string from a byte range; every byte outside ASCII prints as a space. */
function ascii(bytes: Uint8Array, start: number, end: number) {
  let out = '';
  for (let i = start; i < end; i++) out += bytes[i] < 0x80 ? String.fromCharCode(bytes[i]) : ' ';
  return out;
}

/** Locate each `stream ... endstream` body in the raw bytes. */
function streamRanges(bytes: Uint8Array) {
  const ranges = [];
  const marker = [0x73, 0x74, 0x72, 0x65, 0x61, 0x6d]; // "stream"
  for (let i = 0; i + 6 <= bytes.length; i++) {
    if (bytes[i] !== 0x73 || ascii(bytes, i, i + 6) !== 'stream') continue;
    let start = i + 6;
    // A stream body starts after CRLF or LF.
    if (bytes[start] === 0x0d) start++;
    if (bytes[start] === 0x0a) start++;
    // Find the matching endstream.
    let end = start;
    for (; end + 9 <= bytes.length; end++) if (ascii(bytes, end, end + 9) === 'endstream') break;
    if (end + 9 > bytes.length) break;
    // The body runs right up to `endstream`; a trailing EOL belongs to the
    // delimiter, and leaving it in makes the inflater reject the stream as
    // having junk after its end.
    let bodyEnd = end;
    if (bytes[bodyEnd - 1] === 0x0a) bodyEnd--;
    if (bytes[bodyEnd - 1] === 0x0d) bodyEnd--;
    ranges.push([start, bodyEnd]);
    i = end;
  }
  return ranges;
}

/** Decode a PDF literal string `( ... )` into its raw bytes. */
function decodeLiteralBytes(token: string): Uint8Array {
  const body = token.slice(1, -1);
  const bytes: number[] = [];
  for (let i = 0; i < body.length; i++) {
    const ch = body[i];
    if (ch !== '\\') { bytes.push(ch.charCodeAt(0) & 0xff); continue; }
    const next = body[++i];
    if (next === undefined) break;
    if (next === 'n') bytes.push(0x0a);
    else if (next === 'r') bytes.push(0x0d);
    else if (next === 't') bytes.push(0x09);
    else if (next === 'b' || next === 'f') bytes.push(0x20);
    else if (next >= '0' && next <= '7') {
      // Up to three octal digits form one byte.
      let octal = next;
      while (octal.length < 3 && body[i + 1] >= '0' && body[i + 1] <= '7') octal += body[++i];
      bytes.push(parseInt(octal, 8) & 0xff);
    } else bytes.push(next.charCodeAt(0) & 0xff);
  }
  return Uint8Array.from(bytes);
}

/**
 * Decode a PDF hex string `< ... >` into bytes.
 *
 * Hex strings are the other half of how a PDF stores text - a lot of PDFs
 * (and nearly all CJK and subset-font ones) use them for every glyph, so
 * skipping them loses the whole document.
 */
function decodeHex(token: string) {
  const body = token.slice(1, -1).replace(/[^0-9a-fA-F]/g, '');
  const padded = body.length % 2 ? body + '0' : body;
  const bytes = new Uint8Array(padded.length / 2);
  for (let i = 0; i < bytes.length; i++) bytes[i] = parseInt(padded.slice(i * 2, i * 2 + 2), 16);
  return bytes;
}

/**
 * Turn raw string bytes into text, guessing the encoding.
 *
 * A PDF may store text as UTF-16BE (the BOM gives it away) or as single bytes
 * in a font encoding. Guessing UTF-16 from the BOM and otherwise reading
 * latin1 preserves accented characters, where the old ASCII-only path turned
 * every byte over 0x7f into a space.
 */
function bytesToText(bytes: Uint8Array) {
  if (bytes.length >= 2 && bytes[0] === 0xfe && bytes[1] === 0xff) {
    return new TextDecoder('utf-16be').decode(bytes.subarray(2));
  }
  let out = '';
  for (const byte of bytes) out += byte < 0x80 ? String.fromCharCode(byte) : String.fromCharCode(byte);
  return out;
}

/** Extract the text-showing operands from one content stream. */
function operandsToText(content: string) {
  const parts = [];
  for (const hit of content.matchAll(/\((?:\\.|[^\\()])*\)\s*Tj|\[([\s\S]*?)\]\s*TJ|<([0-9a-fA-F\s]+)>\s*Tj/g)) {
    const token = hit[0];
    // A TJ array holds many strings; a lone Tj holds one. Both may mix literal
    // and hex strings.
    const strings = [...token.matchAll(/\((?:\\.|[^\\()])*\)|<[0-9a-fA-F\s]*>/g)];
    const pieces = strings.map(item => item[0].startsWith('<')
      ? bytesToText(decodeHex(item[0]))
      : bytesToText(decodeLiteralBytes(item[0])));
    if (pieces.length) parts.push(pieces.join(''));
  }
  return parts.join(' ');
}

/**
 * Pull text from a PDF by inflating its streams and reading the `Tj`/`TJ`
 * operators, including hex strings.
 *
 * Bytes are scanned directly rather than through a latin1 text round-trip:
 * Node's `'latin1'` decoder folds 0x80-0x9f onto other code points, which
 * corrupts a compressed stream (0x9c became U+0153) before it can be inflated.
 */
export async function pdfText(bytes: Uint8Array) {
  const parts = [];
  const streams = await pdfStreams(bytes);
  for (const content of streams) {
    const text = operandsToText(content);
    if (text.trim()) parts.push(text);
  }
  // There is intentionally no whole-file ASCII fallback. An uncompressed PDF's
  // text is already found through its content streams above; the bytes left
  // over are dictionaries plus compressed noise. Returning those is how a
  // model ended up reading binary gibberish. An empty result routes the caller
  // to page images or OCR instead.
  return parts.join('\n').replace(/[ \t]{2,}/g, ' ').replace(/\n{3,}/g, '\n\n').trim();
}

/** Decoded `stream ... endstream` bodies, for text extraction. */
async function pdfStreams(bytes: Uint8Array) {
  const out = [];
  for (const [start, end] of streamRanges(bytes)) {
    const raw = bytes.subarray(start, end);
    if (raw.length <= 2) continue;
    // Most content streams are FlateDecode. Inflate first whatever the header
    // looks like, because sending compressed bytes to the operator scanner is
    // what produced binary gibberish.
    try {
      out.push(bytePreserving(await inflate(raw)));
      continue;
    } catch {
      // Not compressed after all; check whether it is readable content below.
    }
    // An uncompressed content stream is printable ASCII throughout. Binary
    // streams (images, fonts, embedded files) cannot contain real `Tj`
    // operands, so scanning them only invents text from noise.
    if (looksLikeContentStream(raw)) out.push(bytePreserving(raw));
  }
  return out;
}

/**
 * An uncompressed content stream is mostly printable ASCII operators and text.
 * Binary streams (images, fonts, embedded files) are much denser, so their
 * bytes must not reach the operator scanner. The cutoff stays below 100%
 * because encoded text strings can legitimately contain binary bytes.
 */
function looksLikeContentStream(raw: Uint8Array) {
  const sample = Math.min(raw.length, 4096);
  if (!sample) return false;
  let printable = 0;
  for (let i = 0; i < sample; i++) {
    const byte = raw[i];
    if (byte === 0x09 || byte === 0x0a || byte === 0x0d || (byte >= 0x20 && byte <= 0x7e)) printable++;
  }
  const density = printable / sample;
  if (density > 0.7) return true;
  // Encoded text strings can make a genuine content stream binary-rich.
  // Retain such a stream only when its readable bytes still contain text-showing
  // PDF operators. Fully random bytes have nearly this density, but almost
  // never contain both a text operator and matching string syntax.
  return density > 0.4 && /(BT|Tj|TJ|Tf)\b/.test(ascii(raw, 0, sample));
}

/**
 * One char per byte, so operator scanning sees ASCII syntax while the literal
 * and hex decoders still receive the original byte values. A UTF-8 decode would
 * fold 0x80-0xff into replacement characters and destroy them.
 */
function bytePreserving(bytes: Uint8Array) {
  let out = '';
  for (let i = 0; i < bytes.length; i += 0x8000) {
    out += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  }
  return out;
}

const PROSE_MIN_LETTERS = 24;
const PROSE_VOWELS = /[aeiouAEIOUàáâãäåèéêëìíîïòóôõöùúûüýÿÀÁÂÃÄÅÈÉÊËÌÍÎÏÒÓÔÕÖÙÚÛÜÝŸ]/g;

/**
 * Whether extracted PDF text reads like language rather than decoded noise.
 *
 * Compressed data, images, and subset-font glyph IDs can produce long strings
 * of punctuation, fragments, and random letters. Language is mostly letters;
 * random bytes are mostly punctuation. Random letters also land on vowels only
 * about one time in five, while words in European languages contain vowels
 * roughly one time in three. A spaced-out glyph stream still passes because
 * its letters and vowel ratio are unchanged.
 */
export function looksLikeProse(text: string) {
  if (typeof text !== 'string' || !text) return false;
  const nonSpace = text.length - (text.match(/\s/g) || []).length;
  if (!nonSpace) return false;
  // Control bytes survive only when the extractor has read binary as text.
  const controls = (text.match(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g) || []).length;
  if (controls / text.length > 0.02) return false;
  const letters = (text.match(/\p{L}/gu) || []).length;
  if (letters < PROSE_MIN_LETTERS) return false;
  if (letters / nonSpace < 0.5) return false;
  const vowels = (text.match(PROSE_VOWELS) || []).length;
  const vowelRatio = vowels / letters;
  return vowelRatio >= 0.26 && vowelRatio <= 0.6;
}

/**
 * How much readable text a PDF yielded, per page-ish, so the caller can tell a
 * real text layer from a scan. A scanned PDF has almost none. Gibberish can be
 * long, so only prose-looking text counts as a text layer.
 */
export function pdfTextCoverage(bytes: Uint8Array, text: string) {
  const pages = Math.max(1, (ascii(bytes, 0, Math.min(bytes.length, 4_000_000)).match(/\/Type\s*\/Page\b/g) || []).length);
  const charsPerPage = text.length / pages;
  return { pages, charsPerPage, scanned: !looksLikeProse(text) || charsPerPage < 50 };
}

/* ------------------------------- entry point ---------------------------- */

export async function extractDocumentText(name: string, bytes: Uint8Array) {
  const lower = name.toLowerCase();
  let text = '';
  if (lower.endsWith('.pdf')) {
    text = await pdfText(bytes);
  } else if (lower.endsWith('.docx')) {
    text = stripXml(await zipFileText(bytes, (entry: string) => entry === 'word/document.xml'));
  } else if (lower.endsWith('.xlsx')) {
    const shared = await zipFileText(bytes, (entry: string) => entry === 'xl/sharedStrings.xml');
    const sheets = await zipFileText(bytes, (entry: string) => /^xl\/worksheets\/sheet\d+\.xml$/.test(entry));
    text = [stripXml(shared), stripXml(sheets)].filter(Boolean).join('\n');
  } else if (lower.endsWith('.pptx')) {
    text = stripXml(await zipFileText(bytes, (entry: string) => /^ppt\/slides\/slide\d+\.xml$/.test(entry)));
  }
  return text.slice(0, MAX_OUTPUT);
}
