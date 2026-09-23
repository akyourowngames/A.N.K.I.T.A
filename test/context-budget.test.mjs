import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

// Build stores never touch the real ~/.copilot-chat-cli.
const SANDBOX = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-budget-'));
process.env.CONFIG_DIR = SANDBOX;
test.after(() => fs.rmSync(SANDBOX, { recursive: true, force: true }));

const { Agent } = await import('../src/agent.mjs');
const { McpManager } = await import('../src/mcp-manager.mjs');
const { coreSpecs } = await import('../tools/index.mjs');

const bytes = (value) => Buffer.byteLength(JSON.stringify(value));

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

/** An agent stub with just the fields currentSpecs/trimHistory read. */
function agentStub({ contextWindow, config = {}, mcp, activated = [] } = {}) {
  const agent = Object.create(Agent.prototype);
  agent.useTools = true;
  agent.deferTools = true;
  agent.mcp = mcp;
  agent.state = { activatedTools: new Set(activated) };
  agent.config = config;
  agent.contextWindow = contextWindow;
  agent.memoryContext = null;
  agent.messages = [{ role: 'system', content: 'system' }];
  return agent;
}

/* --------------------------- the output reserve -------------------------- */

test('an unset MAX_TOKENS reserves less on a small window, an explicit one wins', () => {
  const small = agentStub({ contextWindow: 8000, config: { maxTokens: 4096 } });
  assert.equal(small.outputReserve(), 2000, 'a quarter of the window, not the full 4096 default');

  const normal = agentStub({ contextWindow: 32768, config: { maxTokens: 4096 } });
  assert.equal(normal.outputReserve(), 4096, 'unchanged when the window is roomy');

  const pinned = agentStub({ contextWindow: 8000, config: { maxTokens: 4096, maxTokensExplicit: true } });
  assert.equal(pinned.outputReserve(), 4096, 'a deliberate cap is honoured even if it is large');
});

/* ------------------------ shedding a loaded group ------------------------ */

test('a large loaded server is dropped rather than starving the window', () => {
  // The real shape: an OpenAI-compatible provider advertises no context, so the
  // 32768 default applies, and the model has loaded Playwright's 25 tools.
  const mcp = managerWith({ time: 2, browser: 25 });
  const agent = agentStub({ contextWindow: 32768, config: { maxTokens: 4096 }, mcp, activated: ['browser'] });

  const names = agent.currentSpecs().map((spec) => spec.function.name);
  assert.ok(names.some((name) => name.startsWith('mcp__time__')), 'the small always-on server still ships');
  assert.ok(!names.some((name) => name.startsWith('mcp__browser__')), 'the big group is shed, not half-sent');

  // And the turn still builds: the guard must not fire now that the tools fit.
  assert.doesNotThrow(() => agent.trimHistory(8));
});

test('the same loaded server is kept once the window is large enough', () => {
  const mcp = managerWith({ time: 2, browser: 25 });
  const agent = agentStub({ contextWindow: 60000, config: { maxTokens: 4096 }, mcp, activated: ['browser'] });
  const names = agent.currentSpecs().map((spec) => spec.function.name);
  assert.ok(names.some((name) => name.startsWith('mcp__browser__')), 'with room to spare the whole group ships');
  assert.doesNotThrow(() => agent.trimHistory(8));
});

test('core tools always ship even when they alone exceed the budget', () => {
  const agent = agentStub({ contextWindow: 32768, config: { maxTokens: 4096 }, mcp: managerWith({ browser: 25 }), activated: ['browser'] });
  const names = agent.currentSpecs().map((spec) => spec.function.name);
  for (const spec of coreSpecs) assert.ok(names.includes(spec.function.name), `${spec.function.name} is core`);
});

/* ------------------------------ the guard -------------------------------- */

test('the guard only fires when even the core set cannot fit', () => {
  const tiny = agentStub({ contextWindow: 1000, config: { maxTokens: 4096 } });
  assert.throws(() => tiny.trimHistory(8), /context window is too small/);

  const coreOnly = bytes(coreSpecs);
  const justFits = agentStub({ contextWindow: coreOnly + 1024 + 512 + 512, config: { maxTokens: 256, maxTokensExplicit: true } });
  assert.doesNotThrow(() => justFits.trimHistory(8));
});
