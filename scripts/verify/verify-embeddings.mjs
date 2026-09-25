// Opt-in Cloudflare smoke test. Uses synthetic facts in a disposable cache.
// node scripts/verify/verify-embeddings.mjs --live
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import assert from 'node:assert/strict';
import { loadConfig } from '../../src/core/config.mjs';
import { ProfileStore } from '../../src/memory/profile.mjs';
import { CloudflareEmbeddings, embeddingsEnabled } from '../../src/memory/embeddings.mjs';
import { run as recall } from '../../tools/personal/recall.mjs';

if (!process.argv.includes('--live')) throw new Error('Pass --live to call Cloudflare with synthetic memory examples.');
const config = loadConfig();
const timeoutArg = process.argv.find(arg => arg.startsWith('--timeout-ms='));
if (timeoutArg) config.embedTimeoutMs = Number(timeoutArg.split('=')[1]);
assert.ok(embeddingsEnabled(config), 'Configure CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN');
const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-embed-live-'));
try {
  const ctx = { config, profileFile: path.join(dir, 'profile.json'), embeddingCacheDir: path.join(dir, 'vectors') };
  const store = new ProfileStore(ctx.profileFile).load();
  const examples = [
    ['I enjoy ceramics and making things from clay.', 'Suggest an artistic hobby I would like.'],
    ['My preferred dinner is pizza.', 'I am hungry. What would I enjoy eating?'],
    ['I travel by bicycle whenever possible.', 'How do I usually commute?'],
    ['My dog is called Pixel.', 'What is the name of my pet?'],
  ];
  const expected = examples.map(([text]) => store.add({ text }));
  for (let i = 0; i < 36; i++) store.add({ text: `Reference number ${i} for archived equipment inventory.` });
  let calls = 0;
  ctx.embeddingFetch = (...args) => { calls++; return fetch(...args); };
  for (let i = 0; i < examples.length; i++) {
    const start = performance.now();
    const result = JSON.parse(await recall({ query: examples[i][1], project: 'personal', limit: 3 }, ctx));
    console.log(JSON.stringify({ check: i + 1, mode: result.mode, embedding: result.embedding, ms: Math.round(performance.now() - start), top: result.results?.map(r => ({ text: r.text, score: Number(r.score.toFixed(3)) })) }));
    assert.equal(result.mode, 'semantic', 'Cloudflare must respond and finish indexing within the configured deadline');
    assert.equal(result.results[0].id, expected[i].id, 'semantic paraphrase must rank the expected memory first');
  }
  const before = calls;
  const start = performance.now();
  await recall({ query: examples[0][1], project: 'personal' }, ctx);
  assert.equal(calls, before, 'repeated query is cached');
  console.log(`PASS: repeated query, zero HTTP calls, ${Math.round(performance.now() - start)} ms`);
  const fresh = new CloudflareEmbeddings(config, { cacheDir: ctx.embeddingCacheDir, fetchImpl: async (...args) => {
    const body = JSON.parse(args[1].body);
    assert.equal(body.text.length, 1, 'a fresh process reuses persisted document vectors');
    return fetch(...args);
  } });
  const reloaded = await fresh.rank(examples[0][1], new ProfileStore(ctx.profileFile).load().facts);
  assert.equal(reloaded.indexed, 40);
  assert.equal(reloaded.status, 'ready');
  console.log('PASS: persistent document cache, fresh semantic query, no re-embedding of stored facts');
} finally { fs.rmSync(dir, { recursive: true, force: true }); }
