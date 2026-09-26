import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import { chromium } from 'playwright';

const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-browser-agent-'));
const CLEANUP_RETRIES = 10;
const CLEANUP_RETRY_DELAY_MS = 100;
process.env.CONFIG_DIR = path.join(directory, 'config');
test.after(async () => {
  assert.equal(fs.realpathSync(path.dirname(directory)), fs.realpathSync(os.tmpdir()));
  await fs.promises.rm(directory, { recursive: true, force: true, maxRetries: CLEANUP_RETRIES, retryDelay: CLEANUP_RETRY_DELAY_MS });
});
const { Agent } = await import('../../src/core/agent.mjs');
const { browserScreenshotImage, MAX_BROWSER_SCREENSHOTS_PER_TURN } = await import('../../tools/browser/screenshots.mjs');
// Valid synthetic 1x1 PNG: never read a user's screenshot or personal data.
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jZQAAAABJRU5ErkJggg==', 'base64');
const config = { tools: true, autoApprove: true, historyMessages: 40, maxTokens: 1000, memoryConsolidation: false };
const call = (id, name, args) => ({ id, type: 'function', function: { name, arguments: JSON.stringify(args) } });

test('browser screenshots reach the next model round as pixels while tool messages stay valid', async () => {
  const folder = path.join(directory, 'downloaded-images'); fs.mkdirSync(folder, { recursive: true });
  const file = path.join(folder, 'browser-1-abcd.png'); fs.writeFileSync(file, PNG);
  const receipt = JSON.stringify({ type: 'browser_screenshot', path: file, bytes: PNG.length });
  const agent = new Agent({ client: {}, config, workspacePath: directory, browserManager: { run: async () => receipt } });
  let round = 0;
  agent.streamTurn = async () => {
    round++;
    if (round === 1) return { content: '', toolCalls: [call('load', 'find_tools', { query: 'browser' })] };
    if (round === 2) return { content: '', toolCalls: [call('shot', 'browser', { action: 'screenshot' })] };
    const request = agent.messages.findLast(message => message.role === 'user');
    const image = Array.isArray(request.content) && request.content.find(part => part.type === 'image_url');
    assert.ok(image, 'the model needs pixels, not a binary filename');
    assert.equal(image.image_url.url, `data:image/png;base64,${PNG.toString('base64')}`);
    assert.match(request.content[0].text, /Inspect the page/);
    const toolReply = agent.messages.find(message => message.tool_call_id === 'shot');
    assert.equal(typeof toolReply.content, 'string', 'OpenAI-compatible tool content stays text');
    assert.match(toolReply.content, /browser_screenshot/);
    return { content: 'Screenshot inspected', toolCalls: [] };
  };
  assert.equal(await agent.send('Inspect the page'), 'Screenshot inspected');
});

test('screenshot vision rejects external paths, non-PNG bytes and incorrect receipts', () => {
  const ctx = { cwd: directory, workspacePath: directory };
  const file = path.join(directory, 'downloaded-images', 'browser-2-abcd.png'); fs.writeFileSync(file, PNG);
  const receipt = { type: 'browser_screenshot', path: file, bytes: PNG.length };
  assert.ok(browserScreenshotImage(JSON.stringify(receipt), ctx));
  assert.equal(browserScreenshotImage({ ...receipt, path: path.join(directory, '..', 'browser-2-abcd.png') }, ctx), null);
  assert.equal(browserScreenshotImage({ ...receipt, bytes: PNG.length + 1 }, ctx), null);
  fs.writeFileSync(file, Buffer.alloc(PNG.length));
  assert.equal(browserScreenshotImage(receipt, ctx), null);
});

test('automatic screenshot images stay bounded within one request', async () => {
  const file = path.join(directory, 'downloaded-images', 'browser-3-abcd.png'); fs.writeFileSync(file, PNG);
  const receipt = JSON.stringify({ type: 'browser_screenshot', path: file, bytes: PNG.length });
  const agent = new Agent({ client: {}, config, workspacePath: directory, browserManager: { run: async () => receipt } });
  let round = 0;
  agent.streamTurn = async () => {
    round++;
    if (round <= MAX_BROWSER_SCREENSHOTS_PER_TURN + 1) return { content: '', toolCalls: [call(`shot-${round}`, 'browser', { action: 'screenshot', tab: String(round) })] };
    const request = agent.messages.findLast(message => message.role === 'user');
    const imageCount = request.content.filter(part => part.type === 'image_url').length;
    assert.ok(imageCount > 0 && imageCount <= MAX_BROWSER_SCREENSHOTS_PER_TURN, 'attachments obey both the screenshot cap and the context budget');
    assert.equal(agent.browserScreenshotsThisTurn, MAX_BROWSER_SCREENSHOTS_PER_TURN);
    return { content: 'done', toolCalls: [] };
  };
  assert.equal(await agent.send('Inspect these pages'), 'done');
});

test('real browser refs survive discovery, tool results and model rounds through a complete form flow', async t => {
  if (!fs.existsSync(chromium.executablePath())) return t.skip('Chromium has not been downloaded');
  const { BrowserPluginStore } = await import('../../src/integrations/browser-plugins.mjs');
  const { BrowserSessionManager } = await import('../../tools/browser/session.mjs');
  const { PlaywrightBrowserAdapter } = await import('../../tools/browser/playwright.mjs');
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-agent-form-'));
  const server = http.createServer((_request, response) => {
    response.writeHead(200, { 'content-type': 'text/html' });
    response.end('<title>Agent form</title><label>Origin <input></label><label>Destination <input></label><button onclick="document.querySelector(\'main\').textContent=\'Confirmed test submission\'">Search</button><main></main>');
  });
  const store = new BrowserPluginStore(path.join(root, 'browser.json')).load(); store.setEnabled('isolated', true);
  const adapter = new PlaywrightBrowserAdapter({ profile: path.join(root, 'profile') });
  const manager = new BrowserSessionManager({ store, isolatedFactory: () => adapter });
  t.after(async () => {
    await manager.close(); await adapter.close(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve));
    assert.equal(fs.realpathSync(path.dirname(root)), fs.realpathSync(os.tmpdir()));
    await fs.promises.rm(root, { recursive: true, force: true, maxRetries: CLEANUP_RETRIES, retryDelay: CLEANUP_RETRY_DELAY_MS });
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const agent = new Agent({ client: {}, config: { ...config, allowPrivateHosts: true }, workspacePath: root, browserManager: manager });
  let round = 0;
  const refFor = (output, label) => output.split('\n').find(line => line.includes(label) && line.includes('[ref='))?.match(/\[ref=([^\]]+)\]/)?.[1];
  agent.streamTurn = async () => {
    round++;
    const output = agent.messages.findLast(message => message.role === 'tool')?.content || '';
    const next = args => ({ content: '', toolCalls: [call(`flow-${round}`, 'browser', args)] });
    if (round === 1) return { content: '', toolCalls: [call('discover', 'find_tools', { query: 'book flight' })] };
    if (round === 2) return next({ action: 'open', mode: 'auto', url: `http://127.0.0.1:${server.address().port}/` });
    if (round === 3) return next({ action: 'act', op: 'click', ref: 'combobox Origin' });
    if (round === 4) {
      assert.match(output, /Unknown browser ref/);
      return next({ action: 'fill_form', fields: [{ ref: refFor(output, 'Origin'), text: 'Test origin' }, { ref: refFor(output, 'Destination'), text: 'Test destination' }] });
    }
    if (round === 5) { assert.match(output, /Filled 2 fields/); return next({ action: 'act', op: 'click', ref: refFor(output, 'Search') }); }
    if (round === 6) { assert.match(output, /click complete/); return next({ action: 'read' }); }
    if (round === 7) { assert.match(output, /Confirmed test submission/); return next({ action: 'screenshot' }); }
    assert.match(output, /"visionAttached":true/);
    const request = agent.messages.findLast(message => message.role === 'user');
    const image = request.content.find(part => part.type === 'image_url');
    assert.ok(image.image_url.url.startsWith('data:image/png;base64,'));
    return { content: 'Form task completed', toolCalls: [] };
  };
  const actions = [];
  assert.equal(await agent.send('Complete this synthetic flight search form', { onToolCall: item => {
    if (item.function.name === 'browser') actions.push(JSON.parse(item.function.arguments).action);
  } }), 'Form task completed');
  assert.equal(round, 8);
  assert.ok(agent.messages.some(message => message.role === 'user' && (typeof message.content === 'string' ? message.content : message.content[0].text) === 'Complete this synthetic flight search form'));
  assert.deepEqual(actions, ['open', 'act', 'fill_form', 'act', 'read', 'screenshot']);
  console.log(`AGENT_BROWSER_LIVE_OK: ${actions.join(' -> ')}; one invalid-ref recovery; no separate snapshots`);
});
