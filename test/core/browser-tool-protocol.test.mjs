import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import { chromium } from 'playwright';
import { transformWithEsbuild } from 'vite';

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-browser-protocol-'));
process.env.CONFIG_DIR = path.join(root, 'config');
test.after(async () => {
  assert.equal(fs.realpathSync(path.dirname(root)), fs.realpathSync(os.tmpdir()));
  await fs.promises.rm(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 });
});
const { Agent } = await import('../../src/core/agent.mjs');
const { BrowserPluginStore, CHROME_MCP_ID, chromeMcpCommand } = await import('../../src/integrations/browser-plugins.mjs');
const { BrowserSessionManager } = await import('../../tools/browser/session.mjs');
const { PlaywrightBrowserAdapter } = await import('../../tools/browser/playwright.mjs');
const { ChromeBrowserAdapter } = await import('../../tools/browser/chrome.mjs');
const { McpManager } = await import('../../src/integrations/mcp-manager.mjs');
const MCP_TIMEOUT_MS = 30_000; // Milliseconds: bounded local bridge initialization/requests; never contacts a user browser profile.
const config = { tools: true, autoApprove: true, memoryConsolidation: false };
const call = (id, name, args) => ({ id, type: 'function', function: { name, arguments: JSON.stringify(args) } });
const printed = '[Tool call: browser]\n{"action":"act","op":"click","ref":"unexecuted-proposal"}';
// Shapes captured from the isolated remote Ling checkout diagnostic; fixture refs are deliberately unusable.
const printedInline = '[Tool call: browser]{"action":"fill_form","fields":[{"ref":"unexecuted-proposal","text":"SAVE10"}]}';
const printedXml = '<browser mode="auto"><action>fill_form</action><fields>[{"ref":"unexecuted-proposal","text":"2"}]</fields></browser>';
const makeAgent = extra => new Agent({ client: {}, config, skillsEnabled: false,
  print: () => {}, write: () => {}, browserManager: { run: async () => 'Observed browser state' }, ...extra });

for (const runtimeV2 of [false, true]) for (const mode of ['isolated', 'local']) {
  test(`real HTTP/browser correction does not replay a completed cart mutation (${mode}, runtimeV2=${runtimeV2})`, async t => {
    const directory = path.join(root, `live-${mode}-${runtimeV2}`);
    fs.mkdirSync(directory);
    let writes = 0;
    const requests = [];
    const server = http.createServer(async (req, res) => {
      if (req.method === 'POST' && req.url === '/add') {
        writes++;
        res.writeHead(303, { location: '/' }); res.end(); return;
      }
      if (req.url !== '/chat/completions') {
        res.setHeader('content-type', 'text/html');
        res.end(`<title>Static cart</title><form method="post" action="/add"><button>Add item</button></form><p>Cart quantity: ${writes}</p>`);
        return;
      }
      let input = '';
      for await (const chunk of req) input += chunk;
      const body = JSON.parse(input);
      requests.push(body);
      const step = requests.length;
      const snapshot = body.messages.findLast(message => message.role === 'tool' && String(message.content).includes('[ref='))?.content || '';
      const ref = String(snapshot).split('\n').find(line => line.includes('Add item'))?.match(/\[ref=([^\]]+)\]/)?.[1];
      let message;
      if (step === 1) message = { tool_calls: [call('discover', 'find_tools', { query: 'browser' })] };
      if (step === 2) message = { tool_calls: [call('open', 'browser', { action: 'open', mode, url: `http://127.0.0.1:${server.address().port}/` })] };
      if (step === 3) message = { tool_calls: [call('add', 'browser', { action: 'act', op: 'click', ref })] };
      if (step === 4) message = { content: 'Let me check the cart.\n\n' + (mode === 'local' ? printedXml : printedInline) };
      if (step === 5) message = { tool_calls: [call('read-back', 'browser', { action: 'read' })] };
      if (step >= 6) message = { content: 'Observed cart quantity one.' };
      res.setHeader('content-type', 'application/json');
      res.end(JSON.stringify({ choices: [{ message }] }));
    });
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    const store = new BrowserPluginStore(path.join(directory, 'browser.json')).load();
    store.setEnabled('isolated', true);
    store.setEnabled('local', true);
    const adapter = new PlaywrightBrowserAdapter({ profile: path.join(directory, 'profile') });
    const mcp = new McpManager();
    const chrome = new ChromeBrowserAdapter(mcp, { ensureConnected: async context => {
      const entry = chromeMcpCommand({ connection: 'profile' }).args[0];
      await mcp.connect({ id: CHROME_MCP_ID, command: process.execPath,
        args: [entry, '--no-usage-statistics', '--no-performance-crux', '--headless',
          `--executablePath=${chromium.executablePath()}`, `--user-data-dir=${path.join(directory, 'chrome')}`],
        signal: context.signal, initTimeoutMs: MCP_TIMEOUT_MS, requestTimeoutMs: MCP_TIMEOUT_MS, hidden: true });
    } });
    const manager = new BrowserSessionManager({ store, isolatedFactory: () => adapter, chromeFactory: () => chrome });
    t.after(async () => {
      await manager.close(); await adapter.close(); await mcp.closeAll(); server.closeAllConnections();
      await new Promise(resolve => server.close(resolve));
    });
    const agent = makeAgent({ client: { baseUrl: `http://127.0.0.1:${server.address().port}`, headers: () => ({}) },
      config: { ...config, allowPrivateHosts: true, browserRuntimeV2: runtimeV2 },
      workspacePath: directory, browserManager: manager });
    const declared = [];
    let resets = 0;
    const output = await agent.send('Add exactly one item, then read back the cart quantity.', {
      onToolCall: value => declared.push(value.id), onMessageReset: () => { resets++; } });
    console.log('BROWSER_PROTOCOL_HTTP_LIVE ' + JSON.stringify({ mode, runtimeV2, modelRequests: requests.length,
      independentWrites: writes, correctionObserved: requests.some(body => JSON.stringify(body.messages).includes('native tool calls')),
      finalIsPretend: output.includes('unexecuted-proposal') }));
    assert.equal(output, 'Observed cart quantity one.');
    assert.equal(requests.length, 6);
    assert.equal(writes, 1, 'printed click JSON must never run or replay a completed write');
    assert.equal(resets, 1, 'the transient pretend request is retracted from the current streamed bubble');
    assert.match(agent.messages.find(message => message.tool_call_id === 'read-back').content, /Cart quantity: 1/);
    assert.deepEqual(declared, ['discover', 'open', 'add', 'read-back']);
    for (const id of declared) assert.equal(agent.messages.filter(message => message.tool_call_id === id).length, 1);
    assert.equal(agent.terminationReason, null);
  });
}

test('repeated foreground pretend calls stop after one counted correction with a typed incomplete error', async () => {
  const agent = makeAgent();
  let rounds = 0, executions = 0;
  agent.browserManager.run = async () => { executions++; return 'Observed state'; };
  agent.streamTurn = async () => ++rounds === 1
    ? { content: '', toolCalls: [call('start', 'browser', { action: 'read' })] }
    : { content: printed, toolCalls: [] };
  await assert.rejects(agent.send('Continue browser work'), error => error.code === 'invalid_tool_protocol' && /unfinished/.test(error.message));
  assert.equal(rounds, 3); assert.equal(executions, 1);
  assert.equal(agent.terminationReason, 'invalid_tool_protocol');
});

for (const [shape, text] of [['inline', printedInline], ['xml', printedXml]]) {
  test(`observed ${shape} proposal receives one native-call correction without executing its payload`, async () => {
    const agent = makeAgent();
    let rounds = 0, executions = 0;
    agent.browserManager.run = async () => { executions++; return 'Observed state'; };
    agent.streamTurn = async () => {
      rounds++;
      if (rounds === 1 || rounds === 3) return { content: '', toolCalls: [call(`read-${rounds}`, 'browser', { action: 'read' })] };
      return { content: rounds === 2 ? text : 'Observed final result.', toolCalls: [] };
    };
    assert.equal(await agent.send('Finish browser work'), 'Observed final result.');
    assert.equal(rounds, 4);
    assert.equal(executions, 2, 'only the two native read calls may execute');
  });

  test(`repeated ${shape} proposals still stop at the shared one-correction cap`, async () => {
    const agent = makeAgent();
    let rounds = 0;
    agent.streamTurn = async () => ++rounds === 1
      ? { content: '', toolCalls: [call('start', 'browser', { action: 'read' })] }
      : { content: text, toolCalls: [] };
    await assert.rejects(agent.send('Finish browser work'), { code: 'invalid_tool_protocol' });
    assert.equal(rounds, 3);
  });
}

test('a foreground printed request at the step ceiling cannot buy another tool or summary round', async () => {
  const agent = makeAgent({ config: { ...config, maxToolSteps: 2 } });
  let rounds = 0;
  agent.streamTurn = async () => ++rounds === 1
    ? { content: '', toolCalls: [call('start', 'browser', { action: 'read' })] }
    : { content: printed, toolCalls: [] };
  await assert.rejects(agent.send('Continue browser work'), { code: 'invalid_tool_protocol' });
  assert.equal(rounds, 2);
});

test('browser explanations, fenced examples and malformed proposals remain ordinary final text', async () => {
  for (const text of ['Explain [Tool call: browser] as documentation.', `Example:\n\n\`\`\`json\n${printed}\n\`\`\``,
    `> ${printed.split('\n').join('\n> ')}`, '[Tool call: browser]\n{broken json', '[Tool call: browser]\n[]',
    `Example:\n\`\`\`xml\n${printedXml}\n\`\`\``, `> ${printedXml}`, `Explain ${printedInline} as documentation.`,
    printedXml.replace('"text":"2"', '"text":'), printedXml.replace('[{"ref":"unexecuted-proposal","text":"2"}]', '[]')]) {
    const agent = makeAgent();
    let rounds = 0;
    agent.streamTurn = async () => ++rounds === 1
      ? { content: '', toolCalls: [call('start', 'browser', { action: 'read' })] }
      : { content: text, toolCalls: [] };
    assert.equal(await agent.send('Inspect this page and explain tool syntax'), text);
    assert.equal(rounds, 2);
  }
});

test('previous browser activity does not trigger recovery on a new explanatory chat turn', async () => {
  const agent = makeAgent();
  let rounds = 0;
  agent.streamTurn = async () => ++rounds === 1
    ? { content: '', toolCalls: [call('start', 'browser', { action: 'read' })] }
    : { content: rounds === 2 ? 'Observed page' : printed, toolCalls: [] };
  assert.equal(await agent.send('Read this page'), 'Observed page');
  assert.equal(await agent.send('Show the tool request as text'), printed);
  assert.equal(rounds, 3);
});

test('a tools-free final writer cannot turn printed requests into observed browser completion', async () => {
  const agent = makeAgent({ tool: { client: {}, model: 'fixture-executor' } });
  let rounds = 0;
  agent.streamTurn = async () => {
    if (++rounds === 1) return { content: '', toolCalls: [call('start', 'browser', { action: 'read' })] };
    return { content: rounds === 2 ? 'The browser tool loop is finished.' : printed, toolCalls: [] };
  };
  await assert.rejects(agent.send('Continue browser work'), { code: 'invalid_tool_protocol' });
  assert.equal(rounds, 3);
});

test('recovery still enforces browser focus and routes only native calls through the tool boundary', async () => {
  const agent = makeAgent({ config: { ...config, browserToolFocus: true } });
  let rounds = 0, approvals = 0;
  agent.confirm = async () => { approvals++; return false; };
  agent.streamTurn = async () => {
    rounds++;
    if (rounds === 1) return { content: '', toolCalls: [call('focus', 'find_tools', { query: 'browser', scope: 'focus' })] };
    if (rounds === 2) return { content: '', toolCalls: [call('read', 'browser', { action: 'read' })] };
    if (rounds === 3) return { content: printed, toolCalls: [] };
    if (rounds === 4) return { content: '', toolCalls: [call('outside', 'run_command', { command: 'fixture-not-executed' })] };
    assert.match(agent.messages.find(message => message.tool_call_id === 'outside').content, /outside the current tool focus/);
    return { content: 'Observed remaining work.', toolCalls: [] };
  };
  assert.equal(await agent.send('Continue focused browser work'), 'Observed remaining work.');
  assert.equal(rounds, 5); assert.equal(approvals, 0);
});

test('Stop during correction prevents a subsequent HTTP model request and browser action', async t => {
  let requests = 0, executions = 0;
  const server = http.createServer(async (req, res) => {
    for await (const _chunk of req) {};
    requests++;
    const message = requests === 1 ? { tool_calls: [call('start', 'browser', { action: 'read' })] } : { content: printed };
    res.setHeader('content-type', 'application/json');
    res.end(JSON.stringify({ choices: [{ message }] }));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(async () => { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); });
  const agent = makeAgent({ client: { baseUrl: `http://127.0.0.1:${server.address().port}`, headers: () => ({}) },
    browserManager: { run: async () => { executions++; return 'Observed state'; } } });
  await assert.rejects(agent.send('Continue browser work', { onMessageReset: () => agent.cancel() }), { name: 'AbortError' });
  assert.equal(requests, 2); assert.equal(executions, 1);
  console.log(`BROWSER_PROTOCOL_STOP_HTTP requests=${requests} executions=${executions} cancelled=${agent.cancelled()}`);
});

test('the actual desktop message reducer removes the retracted proposal bubble before recovery finishes', async () => {
  const source = fs.readFileSync(new URL('../../desktop/renderer/src/state/store.ts', import.meta.url), 'utf8');
  // Execute the shipped reducer with its types erased, on every supported Node
  // version; do not copy its cleanup logic into a test fake.
  const compiled = await transformWithEsbuild(source, 'store.ts', { loader: 'ts', format: 'esm', target: 'es2022' });
  const { initialState, reducer } = await import(`data:text/javascript;base64,${Buffer.from(compiled.code).toString('base64')}`);
  let state = structuredClone(initialState), messageId, messages = 0, rounds = 0;
  const emit = fields => { state = reducer(state, { type: 'engine', event: { threadId: 'fixture', messageId, ...fields } }); };
  const agent = makeAgent();
  agent.streamTurn = async ({ onDelta }) => {
    rounds++;
    if (rounds === 1 || rounds === 3) return { content: '', toolCalls: [call(`read-${rounds}`, 'browser', { action: 'read' })] };
    const content = rounds === 2 ? printed : 'Observed final result.';
    onDelta(content);
    return { content, toolCalls: [] };
  };
  await agent.send('Continue browser work', {
    onMessageStart: () => { messageId = `reply-${++messages}`; emit({ type: 'message-start' }); },
    onMessageEnd: () => emit({ type: 'message-end' }),
    onMessageReset: () => emit({ type: 'message-reset' }),
    onDelta: text => emit({ type: 'assistant-delta', text }),
  });
  assert.deepEqual(state.threads.fixture.map(message => message.content), ['Observed final result.']);
  console.log(`BROWSER_PROTOCOL_DESKTOP_REDUCER messages=${state.threads.fixture.length} emptyBubbles=0`);
});
