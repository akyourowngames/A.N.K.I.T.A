import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

// Before anything that reads config.mjs: these tests build stores, and without
// this they would operate on the user's real ~/.copilot-chat-cli.
const SANDBOX = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-mcpctx-'));
process.env.CONFIG_DIR = SANDBOX;
test.after(() => fs.rmSync(SANDBOX, { recursive: true, force: true }));

const { McpManager, ALWAYS_ON_TOKENS } = await import('../../src/integrations/mcp-manager.mjs');
const { mcpPromptLines, buildSystemPrompt } = await import('../../src/core/agent.mjs');
const { matchMcpServers } = await import('../../tools/find-tools.mjs');

/** A manager with servers of a chosen size, without spawning anything. */
function managerWith(sizes) {
  const mcp = new McpManager({ log: () => {} });
  for (const [id, count] of Object.entries(sizes)) {
    const tools = Array.from({ length: count }, (_, i) => ({
      name: `tool_${i}`,
      description: `Tool number ${i} of ${id}, with enough prose to take up space in the schema.`,
      inputSchema: {
        type: 'object',
        properties: Object.fromEntries(
          Array.from({ length: 6 }, (_, p) => [`param_${p}`, { type: 'string', description: `Parameter ${p}` }])
        ),
      },
    }));
    mcp.servers.set(id, { id, tools, command: 'npx', args: [], client: { close: async () => {} } });
  }
  return mcp;
}

/* ------------------------- the size-based split -------------------------- */

test('a small server ships with every request, a big one is held back', () => {
  const mcp = managerWith({ time: 2, browser: 25 });
  assert.ok(mcp.estimatedTokens('time') < ALWAYS_ON_TOKENS, 'the small one is under the bar');
  assert.ok(mcp.estimatedTokens('browser') > ALWAYS_ON_TOKENS, 'the big one is over it');

  assert.deepEqual(mcp.alwaysOnIds(), ['time']);
  assert.deepEqual(mcp.deferredIds(), ['browser']);
});

test('the default specs are only the small servers', () => {
  // This is the regression that broke the session: sending all 25 Playwright
  // tools unconditionally overflowed the context window and failed the request
  // outright before the model ever saw it.
  const mcp = managerWith({ time: 2, browser: 25 });
  const defaultSpecs = mcp.specs({ only: new Set(mcp.alwaysOnIds()) });
  assert.equal(defaultSpecs.length, 2, 'only time is in the request');
  assert.match(defaultSpecs[0].function.name, /^mcp__time__/);
  assert.equal(mcp.specs().length, 27, 'everything is still available on demand');
});

test('summaries flag which servers are held back', () => {
  const mcp = managerWith({ time: 2, browser: 25 });
  const byId = Object.fromEntries(mcp.summaries().map((s) => [s.id, s]));
  assert.equal(byId.time.deferred, false);
  assert.equal(byId.browser.deferred, true, 'the prompt has to know to say so');
  assert.deepEqual(byId.time.tools, ['tool_0', 'tool_1']);
});

/* --------------------------- what the model sees ------------------------- */

test('the prompt lists loaded servers as callable and held ones as not', () => {
  const lines = mcpPromptLines([
    { id: 'time', tools: ['get_current_time', 'convert_time'], deferred: false },
    { id: 'playwright-mcp', tools: ['browser_navigate', 'browser_click'], deferred: true },
  ]).join('\n');

  assert.match(lines, /call directly, named mcp__<server>__<tool>:/);
  assert.match(lines, /  time: get_current_time, convert_time/);
  assert.match(lines, /tool lists are large so they are NOT loaded yet/);
  assert.match(lines, /playwright-mcp: 2 tool\(s\)/);
  assert.match(lines, /Call find_tools with the server name/, 'and says how to get them');
  assert.match(lines, /Do not try\s+to call mcp__ tools from those servers/, 'or it calls them anyway');
});

test('a browser server gets guidance on the failure modes that are not bugs', () => {
  // Observed live: a CSS selector that never matched, then one stale ref
  // retried three times, each attempt a full round trip. None of that is
  // discoverable from the tool schemas.
  const browser = [{ id: 'playwright-mcp', tools: ['browser_navigate', 'browser_snapshot'], deferred: true }];
  const lines = mcpPromptLines(browser).join('\n');
  assert.match(lines, /prefer navigating straight to a URL/);
  assert.match(lines, /go stale on navigation/);
  assert.match(lines, /never retry a ref that just failed/);
  assert.match(lines, /browser_evaluate with one small expression/);
  assert.match(lines, /Prefer the built-in `browser` tool/, 'steers toward the preview-backed tool');
});

test('a non-browser server gets no browser advice', () => {
  const lines = mcpPromptLines([{ id: 'time', tools: ['get_current_time', 'convert_time'], deferred: false }]);
  assert.equal(lines.some((l) => /Refs like/.test(l)), false);
});

test('no MCP servers adds no prompt text', () => {
  assert.deepEqual(mcpPromptLines([]), []);
  const prompt = buildSystemPrompt({}, process.cwd(), null, []);
  assert.doesNotMatch(prompt, /Connected MCP servers/);
  assert.doesNotMatch(prompt, /NOT loaded yet/);
});

test('a held-back server is named in the prompt so the model knows it exists', () => {
  const prompt = buildSystemPrompt({}, process.cwd(), null, [
    { id: 'playwright-mcp', tools: ['browser_navigate'], deferred: true },
  ]);
  assert.match(prompt, /playwright-mcp/);
  assert.match(prompt, /NOT loaded yet/);
});

/* ------------------------------ find_tools ------------------------------- */

test('a query finds a held-back MCP server by id, word, or tool name', () => {
  const held = [
    { id: 'playwright-mcp', tools: ['browser_navigate', 'browser_click'] },
    { id: 'postgres', tools: ['query'] },
  ];
  assert.deepEqual(matchMcpServers('playwright-mcp', held), ['playwright-mcp'], 'exact id');
  assert.deepEqual(matchMcpServers('open a browser page', held), ['playwright-mcp'], 'by word');
  assert.deepEqual(matchMcpServers('run a sql query', held), ['postgres'], 'by tool name');
  assert.deepEqual(matchMcpServers('nothing here', held), [], 'and it does not guess');
});

test('one-letter fragments do not match everything', () => {
  const held = [{ id: 'browser-mcp', tools: ['go'] }];
  assert.deepEqual(matchMcpServers('a b c', held), [], 'short words are ignored');
});

test('loading a server by id makes its tools callable', async () => {
  const findTools = await import('../../tools/find-tools.mjs');
  const mcp = managerWith({ browser: 25 });
  const state = {};
  const out = await findTools.run({ query: 'playwright browser' }, { state, mcp });

  assert.ok(state.activatedTools.has('mcp:browser'), 'the server id is remembered separately from built-in groups');
  assert.match(out, /Now callable: mcp__browser__tool_0/);
});

/* ------------------------ the wire into currentSpecs --------------------- */

test('an activated server id adds exactly that server\u2019s specs', async () => {
  const { Agent } = await import('../../src/core/agent.mjs');
  const mcp = managerWith({ time: 2, browser: 25 });

  const agent = Object.create(Agent.prototype);
  agent.useTools = true;
  agent.deferTools = true;
  agent.mcp = mcp;
  agent.state = { activatedTools: new Set() };

  const before = agent.currentSpecs();
  const mcpOnly = before.filter((s) => s.function.name.startsWith('mcp__'));
  assert.equal(mcpOnly.length, 2, 'only the small server is in the request');
  assert.equal(mcpOnly[0].function.name, 'mcp__time__tool_0');

  agent.state.activatedTools.add('mcp:browser');
  const after = agent.currentSpecs();
  assert.equal(after.length, before.length + 25, 'and now the whole browser server too');
  assert.ok(after.some((s) => s.function.name === 'mcp__browser__tool_24'));
});

test('a small server needs no activation', async () => {
  const { Agent } = await import('../../src/core/agent.mjs');
  const mcp = managerWith({ time: 2 });
  const agent = Object.create(Agent.prototype);
  agent.useTools = true;
  agent.deferTools = true;
  agent.mcp = mcp;
  agent.state = {};
  const mcpNames = agent.currentSpecs().filter((s) => s.function.name.startsWith('mcp__'));
  assert.deepEqual(mcpNames.map((s) => s.function.name), ['mcp__time__tool_0', 'mcp__time__tool_1']);
});

test('an id in activatedTools that is not a server is ignored, not crashed on', async () => {
  const { Agent } = await import('../../src/core/agent.mjs');
  const mcp = managerWith({ time: 2 });
  const agent = Object.create(Agent.prototype);
  agent.useTools = true;
  agent.deferTools = true;
  agent.mcp = mcp;
  agent.state = { activatedTools: new Set(['mcp:browser', 'web_search', 'nonsense']) };
  // specsFor() resolves web_search; the other two are inert here.
  const names = agent.currentSpecs().map((s) => s.function.name);
  assert.ok(names.some((n) => n.startsWith('mcp__time__')));
  assert.ok(names.includes('web_search'));
});
