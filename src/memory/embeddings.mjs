import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { EMBEDDINGS_DIR } from '../core/config.mjs';
import { writeTextFile } from '../../tools/shared/_shared.mjs';

export const DEFAULT_EMBED_MODEL = '@cf/qwen/qwen3-embedding-0.6b';
export const DEFAULT_EMBED_INSTRUCTION = 'Given a conversation message, retrieve relevant personal preferences, facts, past decisions and tasks that help answer it.';
const hash = text => createHash('sha256').update(text).digest('hex');
const services = new Map();
const MAX_TEXT_BYTES = 6000; // Safely below the hosted model's token window, even for Unicode.
const documentText = r => boundedText([r.text, r.project, r.kind].filter(Boolean).join('\n'));

function boundedText(text) {
  return Buffer.from(String(text)).subarray(0, MAX_TEXT_BYTES).toString('utf8').replace(/\uFFFD$/, '');
}

function normalize(vector) {
  if (!Array.isArray(vector) || !vector.length || vector.length > 4096 || !vector.every(Number.isFinite)) throw new Error('Invalid embedding');
  const norm = Math.hypot(...vector);
  if (!Number.isFinite(norm) || norm === 0) throw new Error('Invalid embedding');
  return vector.map(n => n / norm);
}

function keep(map, key, value, limit) {
  map.delete(key);
  map.set(key, value);
  if (map.size > limit) map.delete(map.keys().next().value);
}

export function embeddingsEnabled(config = {}) {
  return config.embeddings !== false && !!config.cloudflareAccountId && !!config.cloudflareApiToken;
}

/** One model namespace per cache. No plaintext facts, queries or credentials on disk. */
export class CloudflareEmbeddings {
  constructor(config, { cacheDir = EMBEDDINGS_DIR, fetchImpl = globalThis.fetch } = {}) {
    this.config = { ...config };
    this.model = config.embedModel || DEFAULT_EMBED_MODEL;
    this.instruction = boundedText(config.embedQueryInstruction ?? DEFAULT_EMBED_INSTRUCTION).slice(0, 512);
    this.dir = path.join(cacheDir, hash(`v1:${this.model}`));
    this.fetch = fetchImpl;
    this.documents = new Map();
    this.queries = new Map();
    this.retryAt = 0;
    this.warming = null;
    this.warmPending = new Set();
    this.probed = false;
  }

  document(text) {
    const key = hash(text);
    if (this.documents.has(key)) return this.documents.get(key);
    try {
      const vector = normalize(JSON.parse(fs.readFileSync(path.join(this.dir, `${key}.json`), 'utf8')));
      keep(this.documents, key, vector, 10000);
      return vector;
    } catch { return null; } // A missing/damaged disposable cache is rebuilt.
  }

  saveDocument(text, vector) {
    const key = hash(text);
    keep(this.documents, key, vector, 10000);
    try {
      fs.mkdirSync(this.dir, { recursive: true });
      writeTextFile(path.join(this.dir, `${key}.json`), JSON.stringify(vector));
    } catch {} // Read-only cache storage must not break recall.
  }

  async request(text, signal) {
    const url = `https://api.cloudflare.com/client/v4/accounts/${encodeURIComponent(this.config.cloudflareAccountId)}/ai/run/${this.model.split('/').map(encodeURIComponent).join('/').replace(/^%40/, '@')}`;
    const response = await this.fetch(url, {
      method: 'POST', headers: { Authorization: `Bearer ${this.config.cloudflareApiToken}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }), signal, redirect: 'error',
    });
    // Never include provider bodies or headers in errors; they can contain secrets.
    if (!response.ok) throw new Error('Embedding service unavailable');
    const body = await response.json();
    const data = body?.result?.data;
    if (body.success === false || !Array.isArray(data) || data.length !== text.length) throw new Error('Invalid embedding response');
    const vectors = data.map(normalize);
    if (vectors.some(v => v.length !== vectors[0].length)) throw new Error('Invalid embedding dimensions');
    return vectors;
  }

  warm(rows) {
    if (Date.now() < this.retryAt) return Promise.resolve();
    for (const row of rows) {
      const text = documentText(row);
      if (!this.document(text)) this.warmPending.add(text);
    }
    if (this.warming) return this.warming;
    if (!this.warmPending.size) return Promise.resolve();
    this.warming = this.warmDocuments().finally(() => { this.warming = null; this.warmPending.clear(); });
    return this.warming;
  }

  /**
   * Establish DNS/TLS and any provider-side cold start once, at boot, so the
   * first real query does not pay for it. Best effort: a failure here must not
   * disable embeddings or set a backoff - the next rank() tries normally.
   */
  async probe() {
    if (this.probed || Date.now() < this.retryAt) return;
    this.probed = true;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.config.embedTimeoutMs ?? 2000);
    timer.unref?.();
    try {
      await this.request(['warmup'], controller.signal);
    } catch {
      // Ignored on purpose - see above.
    } finally {
      clearTimeout(timer);
    }
  }

  async warmDocuments() {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.config.embedIndexTimeoutMs ?? 30000);
    timer.unref?.();
    try {
      while (this.warmPending.size && !controller.signal.aborted) {
        const batch = [...this.warmPending].slice(0, 32);
        const vectors = await this.request(batch, controller.signal);
        if (controller.signal.aborted) break;
        batch.forEach((text, i) => { this.saveDocument(text, vectors[i]); this.warmPending.delete(text); });
      }
    } catch {
      if (!controller.signal.aborted) this.retryAt = Date.now() + 30000;
    } finally { clearTimeout(timer); }
  }

  /** A single deadline includes cold indexing, query embedding and response parsing. */
  async rank(query, rows, { signal } = {}) {
    const texts = rows.map(documentText);
    const queryText = `${this.instruction ? `Instruct: ${this.instruction}\nQuery: ` : ''}${boundedText(query)}`;
    const queryKey = hash(queryText);
    let queryVector = this.queries.get(queryKey);
    const vectors = texts.map(text => this.document(text));
    const missing = this.warming ? [] : [...new Set(texts.filter((_, i) => !vectors[i]))];
    let status = 'ready';
    if ((!queryVector || missing.length) && Date.now() < this.retryAt) status = 'unavailable';
    else if (!queryVector || missing.length) {
      const controller = new AbortController();
      const abort = () => controller.abort(signal.reason);
      if (signal?.aborted) abort();
      else signal?.addEventListener('abort', abort, { once: true });
      const timeout = setTimeout(() => controller.abort(new Error('Embedding timeout')), this.config.embedTimeoutMs ?? 2000);
      try {
        // Combine query with the first document batch. Subsequent batches stop at
        // the same deadline; completed documents survive for the next search.
        let first = true;
        while (first || missing.length) {
          first = false;
          if (controller.signal.aborted) throw controller.signal.reason;
          const needsQuery = !queryVector;
          const batch = missing.splice(0, needsQuery ? 31 : 32);
          const result = await this.request([...(needsQuery ? [queryText] : []), ...batch], controller.signal);
          if (controller.signal.aborted) throw controller.signal.reason;
          if (needsQuery) {
            queryVector = result.shift();
            keep(this.queries, queryKey, queryVector, 128);
          }
          for (let i = 0; i < batch.length; i++) this.saveDocument(batch[i], result[i]);
        }
      } catch {
        status = controller.signal.aborted ? (signal?.aborted ? 'cancelled' : 'timeout') : 'unavailable';
        if (status === 'unavailable') this.retryAt = Date.now() + 30000;
      } finally {
        clearTimeout(timeout);
        signal?.removeEventListener('abort', abort);
      }
    }
    const scores = new Map();
    if (queryVector) texts.forEach((text, i) => {
      const vector = vectors[i] || this.document(text);
      if (vector?.length === queryVector.length) scores.set(rows[i], vector.reduce((sum, n, j) => sum + n * queryVector[j], 0));
    });
    return { scores, status, indexed: scores.size, total: rows.length };
  }
}

export function getEmbeddings(config, { cacheDir = EMBEDDINGS_DIR, fetchImpl = globalThis.fetch } = {}) {
  if (!embeddingsEnabled(config)) return null;
  const key = hash(JSON.stringify([cacheDir, config.cloudflareAccountId, config.cloudflareApiToken, config.embedModel, config.embedQueryInstruction, config.embedTimeoutMs, config.embedIndexTimeoutMs]));
  let service = services.get(key);
  if (!service || service.fetch !== fetchImpl) {
    service = new CloudflareEmbeddings(config, { cacheDir, fetchImpl });
    keep(services, key, service, 8);
  }
  return service;
}
