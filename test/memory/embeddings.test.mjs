import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-embeddings-'));
process.env.CONFIG_DIR = root;
test.after(() => fs.rmSync(root, { recursive: true, force: true }));
const { run: recall } = await import('../../tools/personal/recall.mjs');
const { ProfileStore } = await import('../../src/memory/profile.mjs');
const { ProjectStore } = await import('../../src/memory/projects.mjs');

function setup(t) {
  const dir = fs.mkdtempSync(path.join(root, 'case-'));
  const ctx = { profileFile: path.join(dir, 'profile.json'), projectsFile: path.join(dir, 'projects.json'), memoryIndexFile: path.join(dir, 'summaries.json'), embeddingCacheDir: path.join(dir, 'vectors'), config: {
    cloudflareAccountId: 'account', cloudflareApiToken: 'test-secret', embedModel: '@cf/qwen/qwen3-embedding-0.6b', embedTimeoutMs: 1000,
  } };
  const store = new ProfileStore(ctx.profileFile).load();
  const preferred = store.add({ text: 'Enjoys ceramics', kind: 'preference' });
  store.add({ text: 'Lives in Oslo' });
  const calls = [];
  ctx.embeddingFetch = async (url, options) => {
    calls.push({ url, ...options, body: JSON.parse(options.body) });
    const vectors = calls.at(-1).body.text.map(text => text.includes('ceramics') || text.startsWith('Instruct:') ? [1, 0, 0] : [0, 1, 0]);
    return new Response(JSON.stringify({ success: true, result: { data: vectors, shape: [vectors.length, 3] } }));
  };
  return { ctx, store, preferred, calls };
}

test('semantic recall retrieves a paraphrase without keyword overlap and uses the configured Cloudflare endpoint', async t => {
  const { ctx, preferred, calls } = setup(t);
  const found = JSON.parse(await recall({ query: 'What artistic hobby suits me?', project: 'personal', limit: 1 }, ctx));
  assert.equal(found.mode, 'semantic');
  assert.equal(found.results[0].id, preferred.id);
  assert.equal(found.embedding.indexed, 2);
  assert.equal(calls.length, 1, 'cold query and small corpus share one request');
  assert.equal(calls[0].url, 'https://api.cloudflare.com/client/v4/accounts/account/ai/run/@cf/qwen/qwen3-embedding-0.6b');
  assert.equal(calls[0].headers.Authorization, 'Bearer test-secret');
  assert.doesNotMatch(JSON.stringify(found), /test-secret/);
});

test('unchanged documents and repeated queries are cached; edits and model changes invalidate vectors', async t => {
  const { ctx, store, preferred, calls } = setup(t);
  const query = { query: 'An artistic pastime?', project: 'personal' };
  await recall(query, ctx);
  await recall(query, ctx);
  assert.equal(calls.length, 1);
  await recall({ ...query, query: 'A different pastime?' }, ctx);
  assert.equal(calls.length, 2);
  assert.equal(calls[1].body.text.length, 1, 'warm corpus only embeds query');
  store.update(preferred.id, { text: 'Enjoys glass blowing' });
  const updated = JSON.parse(await recall(query, ctx));
  assert.equal(calls.length, 3);
  assert.equal(calls[2].body.text.length, 1);
  assert.doesNotMatch(JSON.stringify(updated), /Enjoys ceramics/);
  store.forget(preferred.id);
  const forgotten = JSON.parse(await recall(query, ctx));
  assert.equal(forgotten.results.length, 1);
  assert.equal(calls.length, 3);
  ctx.config = { ...ctx.config, embedModel: '@cf/other/model' };
  await recall(query, ctx);
  assert.equal(calls.length, 4);
  assert.equal(calls[3].body.text.length, 2);
});

test('semantic recall respects project boundaries and searches notes, decisions, todos and summaries', async t => {
  const { ctx } = setup(t);
  const projects = new ProjectStore(ctx.projectsFile).load();
  const p = projects.add({ name: 'Studio' });
  projects.addNote(p.id, 'ceramics glaze delivery');
  projects.addDecision(p.id, 'ceramics fired on Tuesdays');
  projects.addTodo(p.id, 'ceramics workshop signup');
  const other = projects.add({ name: 'Private project' });
  projects.addNote(other.id, 'ceramics other project');
  fs.writeFileSync(ctx.memoryIndexFile, JSON.stringify({ entries: [{ id: 's', projectId: p.id, summary: 'ceramics planning' }] }));
  const result = JSON.parse(await recall({ query: 'art', project: p.id }, ctx));
  assert.equal(result.mode, 'semantic');
  assert.deepEqual(new Set(result.results.map(r => r.type)), new Set(['note', 'decision', 'todo', 'summary']));
  assert.ok(result.results.every(r => r.projectId === p.id));
});

test('provider failure is sanitized and backs off; unconfigured and browse requests stay local', async t => {
  const { ctx } = setup(t);
  let calls = 0;
  ctx.embeddingFetch = async () => { calls++; return new Response('test-secret', { status: 403 }); };
  const result = JSON.parse(await recall({ query: 'ceramics' }, ctx));
  assert.equal(result.mode, 'search');
  assert.equal(result.embedding.status, 'unavailable');
  assert.doesNotMatch(JSON.stringify(result), /test-secret/);
  await recall({ query: 'other' }, ctx);
  assert.equal(calls, 1, 'failed provider does not delay every turn');
  await recall({}, ctx);
  await recall({ query: 'ceramics' }, { ...ctx, config: {} });
  assert.equal(calls, 1);
});

test('one deadline covers the entire embedding operation and falls back without blocking chat', async t => {
  const { ctx } = setup(t);
  ctx.config.embedTimeoutMs = 40;
  ctx.embeddingFetch = (_url, { signal }) => new Promise((resolve, reject) => {
    signal.addEventListener('abort', () => reject(signal.reason), { once: true });
  });
  const start = performance.now();
  const result = JSON.parse(await recall({ query: 'ceramics' }, ctx));
  assert.equal(result.embedding.status, 'timeout');
  assert.equal(result.results[0].text, 'Enjoys ceramics');
  assert.ok(performance.now() - start < 500);
});

test('background warming persists documents without embedding a query and coalesces concurrent work', async t => {
  const { ctx, store, calls } = setup(t);
  const { CloudflareEmbeddings } = await import('../../src/memory/embeddings.mjs');
  const service = new CloudflareEmbeddings(ctx.config, { cacheDir: ctx.embeddingCacheDir, fetchImpl: ctx.embeddingFetch });
  const first = service.warm(store.facts);
  const second = service.warm(store.facts);
  await Promise.all([first, second]);
  assert.equal(calls.length, 1);
  assert.ok(calls[0].body.text.every(text => !text.startsWith('Instruct:')));
  const reloaded = new CloudflareEmbeddings(ctx.config, { cacheDir: ctx.embeddingCacheDir, fetchImpl: ctx.embeddingFetch });
  const result = await reloaded.rank('An artistic pastime?', store.facts);
  assert.equal(result.indexed, 2);
  assert.equal(calls.length, 2);
  assert.equal(calls[1].body.text.length, 1);
});

test('malformed provider vectors never enter the cache or replace local recall', async t => {
  const { ctx } = setup(t);
  ctx.embeddingFetch = async () => new Response(JSON.stringify({ success: true, result: { data: [[0, 0], [1, 0]] } }));
  const result = JSON.parse(await recall({ query: 'ceramics', project: 'personal' }, ctx));
  assert.equal(result.mode, 'search');
  assert.equal(result.embedding.status, 'unavailable');
  assert.equal(fs.existsSync(ctx.embeddingCacheDir), false);
});

test('forgetting or correcting a memory during an embedding request never returns the stale text', async t => {
  for (const action of ['forget', 'update']) {
    const { ctx, store, preferred } = setup(t);
    const fetch = ctx.embeddingFetch;
    ctx.embeddingFetch = async (...args) => {
      if (action === 'forget') store.forget(preferred.id);
      else store.update(preferred.id, { text: 'Now enjoys woodworking' });
      return fetch(...args);
    };
    const result = JSON.parse(await recall({ query: 'artistic pastime', project: 'personal' }, ctx));
    assert.doesNotMatch(JSON.stringify(result), /Enjoys ceramics/);
    assert.equal(result.total, action === 'forget' ? 1 : 2);
  }
});

test('cancellation aborts the embedding request without waiting for its timeout', async t => {
  const { ctx } = setup(t);
  const controller = new AbortController();
  ctx.signal = controller.signal;
  ctx.embeddingFetch = (_url, { signal }) => new Promise((resolve, reject) => {
    signal.addEventListener('abort', () => reject(signal.reason), { once: true });
    controller.abort(new Error('User cancelled'));
  });
  const start = performance.now();
  const result = JSON.parse(await recall({ query: 'ceramics' }, ctx));
  assert.equal(result.embedding.status, 'cancelled');
  assert.ok(performance.now() - start < 250);
});

test('partial cold indexing keeps successful batches and continues on the next search', async t => {
  const { ctx, store } = setup(t);
  for (let i = 0; i < 34; i++) store.add({ text: `Unrelated record ${i}` });
  const goodFetch = ctx.embeddingFetch;
  let request = 0;
  ctx.config.embedTimeoutMs = 40;
  ctx.embeddingFetch = (url, options) => {
    request++;
    if (request !== 2) return goodFetch(url, options);
    return new Promise((resolve, reject) => options.signal.addEventListener('abort', () => reject(options.signal.reason), { once: true }));
  };
  const args = { query: 'An artistic pastime?', project: 'personal' };
  const partial = JSON.parse(await recall(args, ctx));
  assert.equal(partial.mode, 'hybrid');
  assert.equal(partial.embedding.indexed, 31);
  assert.equal(partial.embedding.status, 'timeout');
  const complete = JSON.parse(await recall(args, ctx));
  assert.equal(complete.mode, 'semantic');
  assert.equal(complete.embedding.indexed, 36);
  assert.equal(request, 3, 'only the unfinished batch is sent on the next search');
});

test('automatic runtime context uses semantic recall without adding another chat-model request', async t => {
  const { ctx, store, preferred } = setup(t);
  const { personalMemoryContext } = await import('../../src/memory/memory-context.mjs');
  const result = await personalMemoryContext('What artistic hobby suits me?', { ...ctx.config, memoryRecallChars: 900 }, ctx);
  assert.equal(JSON.parse(result.result).mode, 'semantic');
  assert.equal(JSON.parse(result.result).results[0].id, preferred.id);
  assert.ok(Buffer.byteLength(result.result) <= 900);
  assert.equal(result.messages[1].tool_call_id, result.messages[0].tool_calls[0].id);
});

test('automatic recall defers a slow provider instead of blocking the reply, then serves the next recall semantically', async t => {
  const { ctx, preferred } = setup(t);
  const { personalMemoryContext } = await import('../../src/memory/memory-context.mjs');
  const good = ctx.embeddingFetch;
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  let first = true;
  ctx.embeddingFetch = async (url, options) => {
    if (first) { first = false; await gate; }
    return good(url, options);
  };
  const start = performance.now();
  const result = await personalMemoryContext(
    'What artistic hobby suits me?',
    { ...ctx.config, memoryRecallChars: 900, memoryRecallBudgetMs: 80 },
    ctx
  );
  assert.ok(performance.now() - start < 500, 'automatic context must not wait out a slow embedding provider');
  assert.equal(JSON.parse(result.result).embedding.status, 'deferred');
  release();
  await new Promise(resolve => setTimeout(resolve, 60));
  const again = JSON.parse(await recall({ query: 'What artistic hobby suits me?', project: 'personal', limit: 1 }, ctx));
  assert.equal(again.mode, 'semantic', 'the deferred vector is cached for the explicit recall');
  assert.equal(again.results[0].id, preferred.id);
});

test('embedding configuration is layered and has bounded timeout defaults', async () => {
  const { loadConfig } = await import('../../src/core/config.mjs');
  const file = path.join(root, 'test.env');
  fs.writeFileSync(file, 'CLOUDFLARE_ACCOUNT_ID=custom-account\nCLOUDFLARE_API_TOKEN=test-key\nEMBED_MODEL=@cf/custom/embed\nEMBED_TIMEOUT_MS=999999\nEMBEDDINGS=off\n');
  const configured = loadConfig(file);
  assert.equal(configured.cloudflareAccountId, 'custom-account');
  assert.equal(configured.cloudflareApiToken, 'test-key');
  assert.equal(configured.embedModel, '@cf/custom/embed');
  assert.equal(configured.embedTimeoutMs, 30000);
  assert.equal(configured.embeddings, false);
  fs.writeFileSync(file, 'EMBED_TIMEOUT_MS=invalid\nEMBED_INDEX_TIMEOUT_MS=-1\n');
  const defaults = loadConfig(file);
  assert.equal(defaults.embedModel, '@cf/qwen/qwen3-embedding-0.6b');
  assert.equal(defaults.embedTimeoutMs, 2000);
  assert.equal(defaults.embedIndexTimeoutMs, 30000);
});

test('CLI config shows the selected embedding model but redacts its API token', () => {
  const cwd = fs.mkdtempSync(path.join(root, 'cli-'));
  fs.writeFileSync(path.join(cwd, 'config.env'), 'CLOUDFLARE_ACCOUNT_ID=sample-account\nCLOUDFLARE_API_TOKEN=never-display-this-token\nEMBED_MODEL=@cf/qwen/qwen3-embedding-0.6b\n');
  const cli = path.resolve('chat.mjs');
  const result = spawnSync(process.execPath, [cli, '--config'], { cwd, env: { ...process.env, CONFIG_DIR: cwd }, encoding: 'utf8' });
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /@cf\/qwen\/qwen3-embedding-0.6b/);
  assert.match(result.stdout, /CLOUDFLARE_API_TOKEN\s+\(set\)/);
  assert.doesNotMatch(result.stdout + result.stderr, /never-display-this-token/);
});
