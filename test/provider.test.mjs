import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fetchWithRetry } from '../src/net.mjs';

const provider = await import('../src/provider.mjs').catch(() => ({}));
const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'provider-test-'));
process.env.CONFIG_DIR = path.join(temp, 'config');
const { loadConfig, CONFIG_DIR } = await import('../src/config.mjs');
test.after(() => fs.rmSync(temp, { recursive: true, force: true }));

test('configuration layers project over global settings and retains message alias', () => {
  assert.equal(CONFIG_DIR, process.env.CONFIG_DIR);
  fs.mkdirSync(CONFIG_DIR, { recursive: true });
  fs.writeFileSync(path.join(CONFIG_DIR, 'config.env'), 'MODEL=global\nMAX_TOKENS=512\nHISTORY_MESSAGES=17\nAPI_BASE=http://localhost:1234/v1\nINPUT_COST_PER_MILLION=0.25\n');
  const project = path.join(temp, '.env');
  fs.writeFileSync(project, 'MODEL=project\nMAX_TOKENS=1024\nHISTORY_LINES=9\n');
  const config = loadConfig(project);
  assert.equal(config.model, 'project');
  assert.equal(config.maxTokens, 1024);
  assert.equal(config.historyMessages, 9);
  assert.equal(config.historyLines, 9);
  assert.equal(config.apiBase, 'http://localhost:1234/v1');
  assert.equal(config.contextWindow, 32768);
  assert.equal(config.inputCostPerMillion, 0.25);
  assert.equal(loadConfig(path.join(temp, 'missing')).model, 'global');
});

test('invalid positive settings fall back to usable defaults', () => {
  const project = path.join(temp, 'invalid.env');
  fs.writeFileSync(project, 'MAX_TOKENS=-1\nCONTEXT_WINDOW=0\nHISTORY_MESSAGES=NaN\nOUTPUT_COST_PER_MILLION=-3\n');
  const config = loadConfig(project);
  assert.equal(config.maxTokens, 4096);
  assert.equal(config.contextWindow, 32768);
  assert.equal(config.historyMessages, 40);
  assert.equal(config.outputCostPerMillion, null);
});

test('gpt-4o is preferred over gpt-4.1 for auto-pick (measured throughput)', () => {
  const models = [
    { id: 'gpt-4.1', tools: true },
    { id: 'gpt-4o', tools: true },
    { id: 'gpt-4o-mini', tools: true },
  ];
  assert.equal(provider.pickModel(models, '', true).id, 'gpt-4o');
  // Explicit choice still wins over the preference order.
  assert.equal(provider.pickModel(models, 'gpt-4.1', true).id, 'gpt-4.1');
  // Falls through to the next preference when 4o is unavailable.
  const without4o = models.filter((m) => m.id !== 'gpt-4o');
  assert.equal(provider.pickModel(without4o, '', true).id, 'gpt-4.1');
});

test('model selection respects tool support and server default without stale preferences', () => {
  assert.equal(typeof provider.pickModel, 'function');
  const models = [{ id: 'chat-only', tools: false }, { id: 'first', tools: null }, { id: 'preferred', tools: true, default: true }];
  assert.equal(provider.pickModel(models, '', true).id, 'preferred');
  assert.equal(provider.pickModel(models.slice(0, 2), '', true).id, 'first');
  assert.throws(() => provider.pickModel(models, 'chat-only', true), /tool/i);
  assert.equal(provider.pickModel(models, 'chat-only', false).id, 'chat-only');
  assert.equal(provider.pickModel([], 'configured', true).id, 'configured');
  assert.throws(() => provider.pickModel([{ id: 'chat', tools: false }], '', true), /tool/i);
});

test('named providers resolve to a keyless gateway or fail loudly', () => {
  assert.equal(provider.resolveProvider('').name, 'copilot');
  assert.equal(provider.resolveProvider('copilot').apiBase, '');
  const kilo = provider.resolveProvider('kilo');
  assert.equal(kilo.apiBase, 'https://api.kilo.ai/api/gateway');
  assert.equal(kilo.keyless, true);
  assert.equal(kilo.defaultModel, 'nex-agi/nex-n2.5-mini:free');
  assert.equal(provider.resolveProvider('KILO').name, 'kilo');
  assert.equal(provider.resolveProvider('nope'), null);
});

test('PROVIDER is read from config and normalized', () => {
  const project = path.join(temp, 'provider.env');
  fs.writeFileSync(project, 'PROVIDER=Kilo\n');
  assert.equal(loadConfig(project).provider, 'kilo');
  assert.equal(loadConfig(path.join(temp, 'missing-provider')).provider, '');
});

test('compatible client normalizes models and uses only configured API credentials', async t => {
  assert.equal(typeof provider.CompatibleClient, 'function');
  const client = new provider.CompatibleClient({ apiBase: 'http://localhost:1234/v1/', apiKey: 'secret', model: 'fallback' });
  await client.ensureToken();
  assert.equal(client.baseUrl, 'http://localhost:1234/v1');
  assert.equal(client.headers(true).Authorization, 'Bearer secret');
  assert.equal(client.headers(true).Accept, 'text/event-stream');
  t.mock.method(globalThis, 'fetch', async url => {
    assert.equal(url, 'http://localhost:1234/v1/models');
    return Response.json({ data: [{ id: 'local', owned_by: 'local-vendor', supported_parameters: ['tools'], context_length: 12345, default: true }] });
  });
  const [model] = await client.models();
  assert.equal(model.id, 'local');
  assert.equal(model.vendor, 'local-vendor');
  assert.equal(model.tools, true);
  assert.equal(model.context, 12345);
  assert.equal(model.default, true);
});

test('configured compatible model remains usable when model discovery is unavailable', async t => {
  assert.equal(typeof provider.CompatibleClient, 'function');
  const client = new provider.CompatibleClient({ apiBase: 'http://localhost:1234/v1', model: 'offline-list', contextWindow: 8192 });
  t.mock.method(globalThis, 'fetch', async () => new Response('not found', { status: 404 }));
  assert.equal(provider.pickModel(await client.models(), 'offline-list').id, 'offline-list');
  assert.equal(client.headers(false).Authorization, undefined);
});

test('hard DNS failures return immediately without retrying', async t => {
  let attempts = 0;
  t.mock.method(globalThis, 'fetch', async () => { attempts++; throw new TypeError('fetch failed', { cause: { code: 'ENOTFOUND' } }); });
  await assert.rejects(fetchWithRetry('http://invalid', {}, { retries: 1 }), /fetch failed/);
  assert.equal(attempts, 1);
});

test('retry waits honor abort signals immediately', async t => {
  const controller = new AbortController();
  t.mock.method(globalThis, 'fetch', async () => new Response('', { status: 429, headers: { 'Retry-After': '1' } }));
  const start = Date.now();
  await assert.rejects(fetchWithRetry('http://local', { signal: controller.signal }, { retries: 1, onRetry: () => controller.abort() }), { name: 'AbortError' });
  assert.ok(Date.now() - start < 500);
});

test('transient network failures retry with bounded delay', async t => {
  let attempts = 0;
  t.mock.method(globalThis, 'fetch', async () => {
    if (++attempts === 1) throw new TypeError('fetch failed', { cause: { code: 'ECONNRESET' } });
    return new Response('ok');
  });
  const response = await fetchWithRetry('http://local', {}, { retries: 1, maxDelayMs: 1 });
  assert.equal(await response.text(), 'ok');
  assert.equal(attempts, 2);
});
