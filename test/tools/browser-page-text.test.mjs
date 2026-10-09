import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-page-text-'));
process.env.CONFIG_DIR = path.join(root, 'config');
const { PlaywrightBrowserAdapter } = await import('../../tools/browser/playwright.mjs');
const { ChromeBrowserAdapter } = await import('../../tools/browser/chrome.mjs');
const pageText = await import('../../tools/browser/page-find.mjs').catch(() => ({}));
test.after(() => fs.rmSync(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 }));

test('page find treats query as literal text, preserves Unicode offsets, and bounds matches', () => {
  assert.equal(typeof pageText.pageTextResult, 'function');
  const source = { text: 'İ.. price [19]. price [19].', sourceUrl: 'https://fixture.test', frameId: 'main', truncated: false };
  const result = pageText.pageTextResult({ sources: [source], args: { action: 'find', query: 'price [19]' } });
  assert.equal(result.chunks.length, 2);
  assert.equal(result.matches[0].start, source.text.indexOf('price'));
  assert.equal(result.matches[0].end, result.matches[0].start + 'price [19]'.length);
  assert.ok(result.output.includes('[19]'));
});

test('chunk continuation requires its source identity and refuses text changed at the same URL', () => {
  assert.equal(typeof pageText.pageTextResult, 'function');
  const sources = [{ text: 'first second third', sourceUrl: 'https://fixture.test', frameId: 'main', truncated: false }];
  const first = pageText.pageTextResult({ sources, args: { action: 'read', start: 0, length: 5 } });
  assert.equal(first.chunks[0].text, 'first');
  assert.throws(() => pageText.pageTextResult({ sources, args: { action: 'read', start: 5 } }), /observation/);
  const next = pageText.pageTextResult({ sources, previous: first, args: { action: 'read', start: 5, length: 7, observation_id: first.id } });
  assert.equal(next.chunks[0].text, ' second');
  assert.throws(() => pageText.pageTextResult({ sources: [{ ...sources[0], text: 'replaced content' }], previous: first, args: { action: 'read', start: 5, observation_id: first.id } }), /changed/);
});

test('real Chromium finds late-page evidence and returns native control state with provenance', async t => {
  const server = http.createServer((_req, res) => { res.setHeader('content-type', 'text/html'); res.end('<title>Long page</title><label>Name<input readonly value="locked"></label><button disabled>Blocked</button><p>' + 'Reference material. '.repeat(1400) + 'Evidence marker: cobalt-417</p>'); });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const adapter = new PlaywrightBrowserAdapter({ profile: path.join(root, 'long') });
  t.after(async () => { await adapter.close(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); });
  const ctx = { config: { allowPrivateHosts: true, browserRuntimeV2: true }, settings: { headless: true } };
  await adapter.run({ action: 'open', url: `http://127.0.0.1:${server.address().port}` }, ctx);
  const observation = await adapter.observe({}, ctx);
  assert.equal(observation.controls.find(control => control.name === 'Name')?.states.readonly, true);
  assert.equal(observation.controls.find(control => control.name === 'Blocked')?.states.disabled, true);
  const found = await adapter.execute({ action: 'find', query: 'Evidence marker' }, ctx);
  assert.equal(found.status, 'executed');
  assert.match(String(found.output), /cobalt-417/);
  assert.ok(found.evidence[0].sourceUrl.startsWith('http://'));
  assert.ok(found.evidence[0].observationId);
  console.log('PAGE_FIND_LIVE', JSON.stringify({ status: found.status, evidence: found.evidence.length, lateOffset: adapter.textResult.matches[0].start }));
  await adapter.run({ action: 'read', start: 0, length: 5 }, ctx);
  const previousId = adapter.textResult.id;
  await adapter.page.reload();
  await assert.rejects(adapter.run({ action: 'read', start: 5, observation_id: previousId }, ctx), /requires|changed/);
  console.log('PAGE_CURSOR_RELOAD_LIVE', JSON.stringify({ staleCursorRefused: true, sameUrl: true }));
});

test('Chrome refuses a cursor from another tab with identical URL and text', async () => {
  const adapter = new ChromeBrowserAdapter({ has: () => true, callTool: async name => {
    if (name.endsWith('__list_pages')) return '1: Page (https://fixture.test/) [selected]\n2: Page (https://fixture.test/)';
    return JSON.stringify({ text: 'identical page text', sourceUrl: 'https://fixture.test/', truncated: false });
  } });
  await adapter.run({ action: 'read', tab: '1', start: 0, length: 5 });
  const observation_id = adapter.textResult.id;
  await assert.rejects(adapter.run({ action: 'read', tab: '2', start: 5, observation_id }), /requires|changed/);
});

test('Chrome text search uses approved MCP and fails closed on malformed source data', async () => {
  const calls = [];
  const adapter = new ChromeBrowserAdapter({ has: () => true, callTool: async (name, args) => {
    calls.push({ name, args });
    if (name.endsWith('__list_pages')) return '1: Page (https://fixture.test/) [selected]';
    if (name.endsWith('__evaluate_script')) return '```json\n' + JSON.stringify({ text: 'Read price [19] from source.', sourceUrl: 'https://fixture.test/', truncated: false }) + '\n```';
    return 'ok';
  } });
  const result = await adapter.execute({ action: 'find', query: 'price [19]' });
  assert.equal(result.status, 'executed');
  assert.match(String(result.output), /price \[19\]/);
  assert.equal(result.observation?.capabilities.documentIdentity, false);
  assert.equal(calls.filter(call => call.name.endsWith('__evaluate_script')).length, 1);
  adapter.mcp.callTool = async name => name.endsWith('__list_pages') ? '1: Page (https://fixture.test/) [selected]' : 'not source data';
  const bad = await adapter.execute({ action: 'find', query: 'price' });
  assert.equal(bad.status, 'failed');
});

test('Chrome control labels do not become disabled/checked state flags', async () => {
  const adapter = new ChromeBrowserAdapter({ has: () => true, callTool: async name => {
    if (name.endsWith('__list_pages')) return '1: Page (https://fixture.test/) [selected]';
    return 'uid=1_0 RootWebArea "Page" url="https://fixture.test/"\nuid=1_1 button "Explain disabled and checked controls"';
  } });
  const observation = await adapter.observe();
  assert.equal(observation.controls[0].name, 'Explain disabled and checked controls');
  assert.notEqual(observation.controls[0].states.disabled, true);
  assert.notEqual(observation.controls[0].states.checked, true);
});

test('Chrome snapshot state inspection is bounded and uninspected controls stay unknown', async () => {
  const PROBE_UID_LIMIT = 16; // Native UID resolutions per observation: cap state enrichment separately from the 160-ref catalogue.
  const CONTROL_COUNT = 80; // Exceeds the state-probe ceiling without reaching the snapshot clipping ceiling.
  const calls = [];
  const adapter = new ChromeBrowserAdapter({ has: () => true, findTool: () => ({}), callTool: async (name, args) => {
    if (name.endsWith('__list_pages')) return '1: Page (https://fixture.test/) [selected]';
    if (name.endsWith('__evaluate_script')) {
      calls.push(args);
      return JSON.stringify(args.args.map(() => ({ states: { covered: false }, actionable: true, editable: false })));
    }
    return Array.from({ length: CONTROL_COUNT }, (_, index) => `uid=1_${index} button "Control ${index}"`).join('\n');
  } });
  const observation = await adapter.observe();
  assert.equal(observation.controls.length, CONTROL_COUNT);
  assert.equal(calls.length, 1);
  assert.ok(calls[0].args.length <= PROBE_UID_LIMIT, 'large pages must not resolve every native UID for optional metadata');
  assert.equal(observation.controls.at(-1).actionable, null);
  assert.equal(observation.controls[0].actionable, true);
});

test('live known popup click returns tab metadata before the next fast model turn', async t => {
  const server = http.createServer((req, res) => { res.setHeader('content-type', 'text/html'); res.end(req.url === '/detail'
    ? '<title>Detail</title><p>Opened detail tab.</p>' : '<title>Main</title><a href="/detail" target="_blank">Open detail</a>'); });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const adapter = new PlaywrightBrowserAdapter({ profile: path.join(root, 'popup') });
  t.after(async () => { await adapter.close(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); });
  const ctx = { config: { allowPrivateHosts: true }, settings: { headless: true } };
  const snapshot = await adapter.run({ action: 'open', url: `http://127.0.0.1:${server.address().port}` }, ctx);
  const ref = /\[ref=([^\]]+)\] a Open detail/.exec(snapshot)[1];
  await adapter.run({ action: 'act', op: 'click', ref }, ctx);
  const tabs = await adapter.tabs();
  console.log('POPUP_TAB_LIVE', JSON.stringify(tabs.map(tab => ({ id: tab.id, active: tab.active, url: tab.url }))));
  assert.equal(tabs.length, 2);
  assert.match(tabs.at(-1).url, /\/detail$/);
});
