import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-browser-efficiency-'));
process.env.CONFIG_DIR = path.join(root, 'config');
test.after(() => fs.rmSync(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 }));
const { Agent } = await import('../../src/core/agent.mjs');
const call = (id, name, args) => ({ id, type: 'function', function: { name, arguments: JSON.stringify(args) } });
const config = { tools: true, model: 'fixture-model', contextWindow: 131072, historyMessages: 40, maxTokens: 1000, memoryConsolidation: false, browserToolFocus: true, browserHistoryCompaction: true };

test('live multi-page evidence reaches the actual model request without an extra routing call', async t => {
  let modelRequests = 0, body;
  const server = http.createServer((req, res) => {
    if (req.method === 'POST') {
      modelRequests++;
      let text = ''; req.on('data', chunk => { text += chunk; }); req.on('end', () => {
        body = JSON.parse(text); res.setHeader('content-type', 'application/json'); res.end('{"choices":[{"message":{"content":"Compared observed prices"}}]}');
      });
    } else { res.setHeader('content-type', 'text/html'); res.end(`<p>Price ${req.url === '/a' ? 19 : 27}</p><button>Continue</button>`); }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const url = `http://127.0.0.1:${server.address().port}`;
  const { PlaywrightBrowserAdapter } = await import('../../tools/browser/playwright.mjs');
  const { BrowserSessionManager } = await import('../../tools/browser/session.mjs');
  const { BrowserPluginStore } = await import('../../src/integrations/browser-plugins.mjs');
  const store = new BrowserPluginStore(path.join(root, 'evidence-browser.json')); store.setEnabled('isolated', true);
  const manager = new BrowserSessionManager({ store, isolatedFactory: () => new PlaywrightBrowserAdapter({ profile: path.join(root, 'evidence-profile') }) });
  t.after(async () => { await manager.close(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); });
  const agent = new Agent({ client: { baseUrl: url, headers: () => ({ 'content-type': 'application/json' }) }, config: {
    ...config, autoApprove: true, allowPrivateHosts: true, browserRuntimeV2: true, browserEvidenceRetention: true, browserProgressTracking: true,
  }, workspacePath: root, browserManager: manager });
  agent.messages.push({ role: 'user', content: 'Compare both observed prices.' });
  for (const id of ['a', 'b']) {
    const tool = call(id, 'browser', { action: 'open', url: `${url}/${id}` });
    const output = await agent.runToolCall(tool);
    agent.messages.push({ role: 'assistant', tool_calls: [tool] }, { role: 'tool', tool_call_id: id, content: output });
  }
  const stored = JSON.stringify(agent.messages);
  await agent.streamAttempt();
  assert.match(body.messages.find(message => message.tool_call_id === 'b').content, /Price 19/);
  assert.match(body.messages.find(message => message.tool_call_id === 'b').content, /Price 27/);
  assert.doesNotMatch(body.messages.find(message => message.tool_call_id === 'a').content, /\[ref=/);
  assert.equal(JSON.stringify(agent.messages), stored);
  assert.equal(modelRequests, 1);
  assert.equal(agent.browserProgress.goalVerified, false);
  console.log('EVIDENCE_REQUEST_LIVE', JSON.stringify({ sources: agent.browserEvidence.items.length, modelRequests, bothPricesRetained: true }));
});

test('real model HTTP request compacts old browser trees but preserves current refs, failures, evidence and stored history', async t => {
  let body;
  const server = http.createServer((req, res) => { let text = ''; req.on('data', chunk => { text += chunk; }); req.on('end', () => { body = JSON.parse(text); res.setHeader('content-type', 'application/json'); res.end('{"choices":[{"message":{"content":"Observed"}}]}'); }); });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => { server.closeAllConnections(); server.close(); });
  const agent = new Agent({ client: { baseUrl: `http://127.0.0.1:${server.address().port}`, headers: () => ({ 'content-type': 'application/json' }) }, config, workspacePath: root });
  agent.messages = [{ role: 'system', content: 'Read observed evidence' }, { role: 'user', content: 'Compare prices then check cart quantity' }];
  for (let i = 0; i < 8; i++) agent.messages.push({ role: 'assistant', content: null, tool_calls: [call(`page-${i}`, 'browser', { action: 'snapshot' })] }, { role: 'tool', tool_call_id: `page-${i}`, content: `Shop ${i} — https://fixture.test/${i}\n` + Array.from({ length: 40 }, (_, n) => `[ref=${i}-${n}] button Product ${n} with a long synthetic description and visible price`).join('\n') });
  agent.messages.push({ role: 'assistant', content: null, tool_calls: [call('failure', 'browser', { action: 'act', op: 'fill', ref: 'bad' })] }, { role: 'tool', tool_call_id: 'failure', content: 'Error: field changed. Do not repeat mutation.' }, { role: 'assistant', content: null, tool_calls: [call('file', 'read_file', { path: 'receipt' })] }, { role: 'tool', tool_call_id: 'file', content: 'Order receipt: item A quantity 1' });
  const before = JSON.stringify(agent.messages), bytesBefore = Buffer.byteLength(before);
  await agent.streamAttempt();
  const projectedBytes = Buffer.byteLength(JSON.stringify(body.messages));
  console.log(`BROWSER_CONTEXT_REPRO before=${bytesBefore} after=${projectedBytes}`);
  assert.ok(projectedBytes < bytesBefore / 2);
  assert.doesNotMatch(body.messages.find(message => message.tool_call_id === 'page-0').content, /\[ref=/);
  assert.match(body.messages.find(message => message.tool_call_id === 'page-7').content, /\[ref=7-39\]/);
  assert.match(body.messages.find(message => message.tool_call_id === 'failure').content, /Do not repeat mutation/);
  assert.match(body.messages.find(message => message.tool_call_id === 'file').content, /quantity 1/);
  assert.equal(JSON.stringify(agent.messages), before, 'request compaction must not erase stored observations');
});

test('model-selected browser focus reduces schemas and enforces routing until discovery explicitly restores general tools', async () => {
  const agent = new Agent({ client: {}, config, workspacePath: root });
  agent.state.activatedTools.add('http_request');
  const originalBytes = Buffer.byteLength(JSON.stringify(agent.currentSpecs()));
  const output = await agent.runToolCall(call('focus', 'find_tools', { query: 'browser', scope: 'focus' }));
  assert.match(output, /focus/i);
  const focused = agent.currentSpecs();
  assert.ok(focused.some(spec => spec.function.name === 'browser'));
  assert.ok(focused.some(spec => spec.function.name === 'recall'));
  assert.ok(!focused.some(spec => ['http_request', 'run_command', 'read_file'].includes(spec.function.name)));
  assert.ok(Buffer.byteLength(JSON.stringify(focused)) < originalBytes);
  assert.match(await agent.runToolCall(call('bypass', 'http_request', { url: 'https://fixture.test', method: 'POST' })), /focus|discover/i);
  const activated = [...agent.state.activatedTools];
  for (const scope of [undefined, 'focus']) {
    const refused = await agent.runToolCall(call('discovery-bypass', 'find_tools', { query: 'git', scope }));
    assert.match(refused, /^Error:.*scope="general"/);
    assert.deepEqual([...agent.state.activatedTools], activated, 'refusal must not load schemas');
    assert.ok(!agent.currentSpecs().some(spec => spec.function.name === 'git'));
  }
  await agent.runToolCall(call('general', 'find_tools', { query: 'web', scope: 'general' }));
  assert.ok(agent.currentSpecs().some(spec => spec.function.name === 'http_request'));
  assert.equal(agent.state.toolFocusTransitions.length, 2);
  console.log(`TOOL_SCHEMA_REPRO general=${originalBytes} focused=${Buffer.byteLength(JSON.stringify(focused))}`);
});

test('browser scrape then save exits focus once, writes a real file and keeps memory/session continuity', async t => {
  const server = http.createServer((req, res) => { res.setHeader('content-type', 'text/html'); res.end('<title>Scrape fixture</title><p>Observed source price: 19</p><button>Next</button>'); });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const { PlaywrightBrowserAdapter } = await import('../../tools/browser/playwright.mjs');
  const adapter = new PlaywrightBrowserAdapter({ profile: path.join(root, 'mixed-profile') });
  t.after(async () => { await adapter.close(); server.closeAllConnections(); server.close(); });
  const manager = { run: (args, ctx) => adapter.run(args, { ...ctx, settings: { headless: true } }) };
  const agent = new Agent({ client: {}, config: { ...config, allowPrivateHosts: true, autoApprove: true }, workspacePath: root, browserManager: manager });
  let step = 0, receipt = '';
  const calls = [call('focus', 'find_tools', { query: 'browser', scope: 'focus' }), call('open', 'browser', { action: 'open', url: `http://127.0.0.1:${server.address().port}` }), call('read', 'browser', { action: 'read' }), call('general', 'find_tools', { query: 'files', scope: 'general' })];
  agent.streamTurn = async () => {
    if (step === 3) receipt = agent.messages.at(-1).content;
    if (step < calls.length) return { content: '', toolCalls: [calls[step++]] };
    if (step++ === calls.length) return { content: '', toolCalls: [call('save', 'write_file', { path: 'observed-page.txt', content: receipt })] };
    return { content: 'Saved observed page', toolCalls: [] };
  };
  await agent.send('Read the page and save its observed text', { onToolResult: (tool, result) => console.log(`MIXED_STEP ${tool.function.name}: ${String(result).slice(0, 180)}`) });
  assert.match(fs.readFileSync(path.join(root, 'observed-page.txt'), 'utf8'), /Observed source price: 19/);
  assert.deepEqual(agent.focusAudit.transitions.map(transition => transition.scope), ['focus', 'general']);
  assert.equal(agent.focusAudit.endedFocused, false); assert.equal(agent.state.toolFocus, null);
  assert.equal(agent.totalToolCalls, 5, 'discovery transitions consume ordinary tool calls');
  console.log(`MIXED_WORKFLOW_REPRO calls=${agent.totalToolCalls} switches=${agent.focusAudit.switches} fileReadBack=true`);
});

test('focus can be disabled for A/B without replacing conversation or restoring credentials/memory', async () => {
  const agent = new Agent({ client: {}, config: { ...config, browserToolFocus: false }, workspacePath: root });
  await agent.runToolCall(call('focus', 'find_tools', { query: 'browser', scope: 'focus' }));
  assert.ok(!agent.state.toolFocus); assert.ok(agent.currentSpecs().some(spec => spec.function.name === 'write_file'));
});

test('focus cannot enter a mixed browser/connector group and rejects MCP discovery outside its active boundary', async () => {
  const { run } = await import('../../tools/find-tools.mjs');
  const state = { activatedTools: new Set() };
  const ctx = { state, config };
  assert.match(run({ query: 'browser flights', scope: 'focus' }, ctx), /^Error:.*browser/);
  assert.equal(state.activatedTools.size, 0);
  run({ query: 'browser', scope: 'focus' }, ctx);
  const active = [...state.activatedTools];
  const mcp = { summaries: () => [{ id: 'fixture-data', deferred: true, tools: ['read_record'] }] };
  assert.match(run({ query: 'fixture-data' }, { ...ctx, mcp }), /^Error:.*scope="general"/);
  assert.deepEqual([...state.activatedTools], active);
  assert.equal(state.toolFocus.size, 1);
});

test('documented browser A/B flags load through ordinary layered configuration', async () => {
  const { loadConfig } = await import('../../src/core/config.mjs');
  const file = path.join(root, 'browser-flags.env');
  fs.writeFileSync(file, 'BROWSER_TOOL_FOCUS=off\nBROWSER_HISTORY_COMPACTION=off\n');
  const loaded = loadConfig(file);
  assert.equal(loaded.browserToolFocus, false); assert.equal(loaded.browserHistoryCompaction, false);
});

test('real HTTP provider failure envelopes are errors even on HTTP 200 and do not expose remote secrets', async t => {
  let requests = 0;
  const server = http.createServer((req, res) => { requests++; res.setHeader('content-type', 'text/event-stream'); res.end('data: {"error":{"code":429,"message":"private-provider-secret"}}\n\ndata: [DONE]\n\n'); });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => { server.closeAllConnections(); server.close(); });
  const agent = new Agent({ client: { baseUrl: `http://127.0.0.1:${server.address().port}`, headers: () => ({}) }, config: { ...config, tools: false }, workspacePath: root });
  await assert.rejects(agent.send('Check connection'), error => {
    console.log(`PROVIDER_STREAM_REPRO code=${error.code} requests=${requests}`);
    return error.code === 'provider_rate_limit' && !error.message.includes('private-provider-secret');
  });
  assert.equal(requests, 1);
});

test('declared text-only model keeps screenshot artifact without attaching unsupported pixels', async () => {
  const folder = path.join(root, 'downloaded-images'); fs.mkdirSync(folder, { recursive: true });
  const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jZQAAAABJRU5ErkJggg==', 'base64');
  const file = path.join(folder, 'browser-1-abcd.png'); fs.writeFileSync(file, png);
  const manager = { run: async args => args.action === 'screenshot' ? JSON.stringify({ type: 'browser_screenshot', path: file, bytes: png.length }) : 'Page: unavailable stock\n[ref=1-0-0] button Next' };
  const client = { modelCapabilities: new Map([['fixture-model', { vision: false }]]) };
  const agent = new Agent({ client, config, workspacePath: root, browserManager: manager }); agent.messages.push({ role: 'user', content: 'Read this page' });
  const output = await agent.runToolCall(call('shot', 'browser', { action: 'screenshot' }));
  assert.match(output, /visionAttached.*false/);
  assert.match(output, /unavailable stock/);
  assert.equal(agent.messages.at(-1).content, 'Read this page');
  assert.ok(fs.existsSync(file));
});

test('a forced summary cannot hide the runtime limit by claiming an ordinary completion', async () => {
  const agent = new Agent({ client: {}, config: { ...config, maxToolSteps: 1 }, workspacePath: root });
  agent.runToolCall = async () => 'Actual observation';
  agent.streamTurn = async options => options?.useTools === false ? { content: 'All done', toolCalls: [] } : { content: '', toolCalls: [call('a', 'browser', { action: 'snapshot' })] };
  let displayed = '';
  const output = await agent.send('Complete all steps', { onDelta: text => { displayed += text; } });
  assert.match(output, /limit|budget|stopped/i);
  assert.match(displayed, /limit|budget|stopped/i);
  assert.equal(output, agent.messages.at(-1).content);
});

test('real browser default snapshot exposes missing stock, and quantity fill/navigation never silently repeats a cart mutation', async t => {
  const { PlaywrightBrowserAdapter } = await import('../../tools/browser/playwright.mjs');
  let quantity = 0, writes = 0;
  const server = http.createServer((req, res) => {
    if (req.method === 'POST') { let body = ''; req.on('data', chunk => { body += chunk; }); req.on('end', () => { writes++; quantity += Number(new URLSearchParams(body).get('qty')); res.writeHead(303, { location: '/cart' }); res.end(); }); return; }
    res.setHeader('content-type', 'text/html');
    res.end(req.url === '/cart' ? `<title>Cart</title><h1>Cart</h1><p>Alternative memory quantity ${quantity}</p><label>Quantity <input type="number" value="${quantity}"></label>` : '<title>Memory shop</title><h1>Requested memory</h1><p>Out of stock</p><p>Alternative memory available</p><form method="post"><label>Quantity <input type="number" name="qty" value="1"></label><button>Add alternative to cart</button></form>');
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const adapter = new PlaywrightBrowserAdapter({ profile: path.join(root, 'stock-profile') }), ctx = { cwd: root, config: { allowPrivateHosts: true }, settings: { headless: true } };
  t.after(async () => { await adapter.close(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); });
  const find = (text, label) => text.split('\n').find(line => line.includes('[ref=') && line.includes(label))?.match(/\[ref=([^\]]+)\]/)?.[1];
  let snapshot = await adapter.run({ action: 'open', url: `http://127.0.0.1:${server.address().port}` }, ctx);
  console.log(`STOCK_SNAPSHOT_REPRO stockVisible=${snapshot.includes('Out of stock')}`);
  assert.match(snapshot, /Out of stock/);
  assert.ok(!snapshot.split('\n').some(line => line.includes('[ref=') && line.includes('Out of stock')));
  snapshot = await adapter.run({ action: 'fill_form', fields: [{ ref: find(snapshot, 'Quantity'), text: '1' }] }, ctx);
  const beforeNavigation = find(snapshot, 'Quantity');
  snapshot = await adapter.run({ action: 'act', op: 'fill', ref: beforeNavigation, text: '1' }, ctx);
  snapshot = await adapter.run({ action: 'act', op: 'click', ref: find(snapshot, 'Add alternative') }, ctx);
  await assert.rejects(adapter.run({ action: 'act', op: 'fill', ref: beforeNavigation, text: '2' }, ctx), /Stale ref/);
  assert.equal(writes, 1); assert.equal(quantity, 1);
  assert.match(await adapter.run({ action: 'read' }, ctx), /Alternative memory quantity 1/);
});
