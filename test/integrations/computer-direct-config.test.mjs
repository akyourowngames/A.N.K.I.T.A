import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import { once } from 'node:events';
import { fileURLToPath } from 'node:url';

// Import stores only after isolating their files from the user's configuration.
const SANDBOX = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-native-config-'));
const previousConfigDir = process.env.CONFIG_DIR;
process.env.CONFIG_DIR = SANDBOX;
test.after(() => {
  if (previousConfigDir === undefined) delete process.env.CONFIG_DIR;
  else process.env.CONFIG_DIR = previousConfigDir;
  fs.rmSync(SANDBOX, { recursive: true, force: true });
});

const { Agent } = await import('../../src/core/agent.mjs');
const { CompatibleClient } = await import('../../src/core/provider.mjs');
const { McpManager } = await import('../../src/integrations/mcp-manager.mjs');
const { COMPUTER_MCP_ID, COMPUTER_DIRECT_CONFIG } = await import('../../src/integrations/computer-use.mjs');
const FIXTURE = fileURLToPath(new URL('../../scripts/fixtures/computer-mcp.mjs', import.meta.url));
const MODEL = 'native-config-fixture'; // Test-only provider identifier; no external model is contacted.
const OBSERVE = 'get_window_state'; // The fixture's read-only native observation.
const AUTHORIZED = /native desktop controls are already authorized/i;

function manager(t) {
  const mcp = new McpManager();
  t.after(() => mcp.closeAll());
  return mcp;
}

async function connect(mcp) {
  await mcp.connect({ id: COMPUTER_MCP_ID, command: process.execPath, args: [FIXTURE], allowedTools: [OBSERVE] });
}

function agent(mcp, config = {}, client = {}) {
  return new Agent({ client, mcp, workspacePath: SANDBOX,
    // A roomy window on purpose. With tools on, a default 32k window leaves only
    // ~2.3 kB of history after the catalogue and system prompt, so one tool
    // exchange can exceed it and the test fails on a budget error rather than the
    // round trip it exercises. (See AGENTS.md rule 2.8.)
    config: { model: MODEL, tools: false, autoApprove: false, memoryConsolidation: false, contextWindow: 131072, ...config },
    print: () => {}, write: () => {} });
}

for (const [label, flag] of [['authorized desktop', true], ['approval-based CLI', false], ['unset authorization', undefined]]) {
  test(`connected native controls build and refresh the prompt for ${label}`, async t => {
    const mcp = manager(t);
    await connect(mcp);
    const a = agent(mcp, flag === undefined ? {} : { [COMPUTER_DIRECT_CONFIG]: flag });
    for (const refresh of [() => {}, () => a.clear(), () => a.rebase(), () => a.refreshPrompt()]) {
      refresh();
      assert.match(a.messages[0].content, /Computer use on the user's current Windows desktop/);
      assert.equal(AUTHORIZED.test(a.messages[0].content), flag === true);
      assert.equal(a.autoApprove, false, 'native authorization must not enable automatic approval for all tools');
    }
  });
}

test('connecting native controls after Agent creation rebuilds the prompt', async t => {
  const mcp = manager(t);
  const a = agent(mcp, { [COMPUTER_DIRECT_CONFIG]: true });
  assert.doesNotMatch(a.messages[0].content, AUTHORIZED);
  await connect(mcp);
  a.refreshPrompt();
  assert.match(a.messages[0].content, AUTHORIZED);
  await mcp.disconnect(COMPUTER_MCP_ID);
  a.refreshPrompt();
  assert.doesNotMatch(a.messages[0].content, AUTHORIZED);
});

test('Agent send completes a provider and native MCP observation round trip', async t => {
  const requests = [];
  const toolName = `mcp__${COMPUTER_MCP_ID}__${OBSERVE}`;
  const finalReply = 'Observed fixture desktop.';
  const server = http.createServer(async (request, response) => {
    const chunks = [];
    for await (const chunk of request) chunks.push(chunk);
    requests.push(JSON.parse(Buffer.concat(chunks).toString()));
    const first = requests.length === 1;
    response.setHeader('content-type', 'application/json');
    response.end(JSON.stringify({ choices: [{ message: first
      ? { role: 'assistant', content: null, tool_calls: [{ id: 'native-observe', type: 'function', function: { name: toolName, arguments: '{}' } }] }
      : { role: 'assistant', content: finalReply }, finish_reason: first ? 'tool_calls' : 'stop' }] }));
  });
  t.after(() => new Promise(resolve => server.close(resolve)));
  server.listen(0, '127.0.0.1'); // Test-only loopback endpoint; the operating system selects an available port.
  await once(server, 'listening');
  const client = new CompatibleClient({ apiBase: `http://127.0.0.1:${server.address().port}`, model: MODEL });
  const mcp = manager(t);
  await connect(mcp);
  const a = agent(mcp, { tools: true, [COMPUTER_DIRECT_CONFIG]: true }, client);
  assert.equal(await a.send('Read the fixture desktop'), finalReply);
  assert.equal(requests.length, 2);
  assert.match(requests[0].messages[0].content, AUTHORIZED);
  assert.ok(requests[0].tools.some(tool => tool.function.name === toolName));
  assert.match(requests[1].messages.find(message => message.tool_call_id === 'native-observe').content, /Observed fixture state/);
  assert.equal(a.messages.at(-1).content, finalReply);
});
