// Persistence-boundary detection: compiled patterns, no network or model calls.
const MIN_GENERIC_LENGTH = 12; // Characters; short unlabeled tokens are too ambiguous.
const MIN_GENERIC_ENTROPY = 4.2; // Shannon bits per character for contextual tokens.
const MIN_BEARER_LENGTH = 20; // Characters; shorter bearer candidates must pass entropy too.
const MIN_ENCODED_LENGTH = 16; // Characters; avoids decoding ordinary small words.
const MAX_ENCODED_LENGTH = 16_384; // Characters; bounds each decode on pasted payloads.
const MAX_ENCODING_DEPTH = 2; // URL/base64 wrappers; split messages are outside v1.
const PASSWORD_LABEL = /(?:password|passwd|pwd)$/i;
const CONTEXT_KEY = /^[a-z0-9_]*(?:api_key|apikey|access_token|token|secret|password|passwd|pwd)$/i;
const MARKER = /^\[(?:REDACTED:|STORED:keychain:)/;
const ENCODED_CANDIDATE = /[A-Za-z0-9_%+\/=.:-]{16,}/g;
const LABEL = /\b([a-z0-9_]*(?:api_key|apikey|access_token|token|secret|password|passwd|pwd))\s*["']?\s*[:=]\s*(?:"([^"\r\n]*)"|'([^'\r\n]*)'|([^\s,;}]+))/gi;
const PATTERNS = [
  ['aws_key', /\b(?:AKIA|ASIA)[A-Z0-9]{16}\b/g],
  ['github_token', /\b(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]{16,}\b/g],
  ['slack_token', /\bxox[baprs]-[A-Za-z0-9-]{16,}\b/g],
  ['stripe_key', /\b(?:sk|rk)_live_[A-Za-z0-9]{16,}\b/g],
  ['private_key', /-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----[\s\S]*?-----END (?:[A-Z0-9]+ )*PRIVATE KEY-----/g],
  ['bearer_token', /\bBearer\s+([A-Za-z0-9._~+\/-]{12,}=*)/gi, 1],
  ['connection_password', /\b[a-z][a-z0-9+.-]*:\/\/[^\s/:@]+:([^\s@]+)@/gi, 1],
];

function entropy(value) {
  const counts = new Map();
  for (const char of value) counts.set(char, (counts.get(char) || 0) + 1);
  let result = 0;
  for (const count of counts.values()) { const probability = count / value.length; result -= probability * Math.log2(probability); }
  return result;
}
function decodedValues(raw) {
  if (raw.length < MIN_ENCODED_LENGTH || raw.length > MAX_ENCODED_LENGTH) return [];
  const decoded = [];
  if (/%[a-f0-9]{2}/i.test(raw)) { try { decoded.push(decodeURIComponent(raw)); } catch {} }
  if (/^[A-Za-z0-9+/]+={0,2}$/.test(raw)) {
    const value = Buffer.from(raw, 'base64').toString('utf8');
    if (/^[\x09\x0a\x0d\x20-\x7e]+$/.test(value)) decoded.push(value);
  }
  return decoded.filter(value => value !== raw);
}
function collect(text, depth) {
  const hits = [];
  for (const [type, expression, group] of PATTERNS) {
    expression.lastIndex = 0;
    for (const match of text.matchAll(expression)) {
      const value = group ? match[group] : match[0];
      if (type === 'bearer_token' && value.length < MIN_BEARER_LENGTH && entropy(value) <= MIN_GENERIC_ENTROPY) continue;
      const start = match.index + (group ? match[0].lastIndexOf(value) : 0);
      hits.push({ type, start, end: start + value.length });
    }
  }
  LABEL.lastIndex = 0;
  for (const match of text.matchAll(LABEL)) {
    const value = match[2] ?? match[3] ?? match[4];
    if (!value || MARKER.test(value)) continue;
    const password = PASSWORD_LABEL.test(match[1]);
    if (!password && (value.length < MIN_GENERIC_LENGTH || entropy(value) <= MIN_GENERIC_ENTROPY)) continue;
    const start = match.index + match[0].lastIndexOf(value);
    hits.push({ type: password ? 'generic_password' : 'generic_token', start, end: start + value.length });
  }
  if (depth < MAX_ENCODING_DEPTH && text.length >= MIN_ENCODED_LENGTH && !/^data:image\//i.test(text)) {
    ENCODED_CANDIDATE.lastIndex = 0;
    // Snapshot matches before recursion: the module's shared regex state cannot leak between calls.
    const candidates = [...text.matchAll(ENCODED_CANDIDATE)];
    for (const match of candidates) {
      const raw = match[0];
      if (raw.length > MAX_ENCODED_LENGTH || hits.some(hit => hit.start <= match.index && hit.end >= match.index + raw.length)) continue;
      const found = decodedValues(raw).some(value => collect(value, depth + 1).length);
      if (found) hits.push({ type: 'encoded_secret', start: match.index, end: match.index + raw.length });
    }
  }
  return hits;
}
export function detect(value) {
  const text = String(value ?? '');
  const ordered = collect(text, 0).sort((a, b) => a.start - b.start || b.end - a.end);
  const result = [];
  for (const hit of ordered) {
    const prior = result.at(-1);
    if (prior && hit.start < prior.end) prior.end = Math.max(prior.end, hit.end);
    else result.push({ ...hit });
  }
  return result;
}
export function containsSecret(text) { return detect(text).length > 0; }
/** Main-process transient values, including decoded wrappers, for echo protection. */
export function secretValues(text, depth = 0) {
  const values = [];
  for (const hit of detect(text)) {
    const value = String(text).slice(hit.start, hit.end); values.push({ type: hit.type, value });
    if (hit.type === 'encoded_secret' && depth < MAX_ENCODING_DEPTH) for (const decoded of decodedValues(value)) values.push(...secretValues(decoded, depth + 1));
  }
  return values;
}
export function redact(value) {
  const text = String(value ?? '');
  let result = '', offset = 0;
  for (const hit of detect(text)) { result += text.slice(offset, hit.start) + `[REDACTED:${hit.type}]`; offset = hit.end; }
  return result + text.slice(offset);
}
/** A fresh copy for disk/log/export. Never mutate the live model's messages. */
export function redactValue(value) {
  if (typeof value === 'string') {
    if (/^data:image\//i.test(value)) return value;
    if (/^\s*[\[{]/.test(value)) {
      try { const data = JSON.parse(value), clean = redactValue(data); if (JSON.stringify(clean) !== JSON.stringify(data)) return JSON.stringify(clean); } catch {}
    }
    return redact(value);
  }
  if (Array.isArray(value)) return value.map(redactValue);
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([key, item]) => {
    const contextual = typeof item === 'string' && item && !MARKER.test(item) && CONTEXT_KEY.test(key) &&
      (PASSWORD_LABEL.test(key) || (item.length >= MIN_GENERIC_LENGTH && entropy(item) > MIN_GENERIC_ENTROPY));
    return [key, contextual ? `[REDACTED:${PASSWORD_LABEL.test(key) ? 'generic_password' : 'generic_token'}]` : redactValue(item)];
  }));
  return value;
}
