import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

// Sandbox the config layer: find_tools and the project tool read real paths.
const SANDBOX = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-loading-'));
process.env.CONFIG_DIR = SANDBOX;
test.after(() => fs.rmSync(SANDBOX, { recursive: true, force: true }));

const index = await import('../tools/index.mjs');
const { CATEGORIES, CORE } = index;
const findTools = await import('../tools/find-tools.mjs');
const scrape = await import('../tools/scrape.mjs');
const { Agent, buildSystemPrompt } = await import('../src/agent.mjs');

const bytes = (o) => Buffer.byteLength(JSON.stringify(o));
const ctx = { state: { activatedTools: new Set() } };

/* ------------------------------ partition ------------------------------- */

test('every tool sits in exactly one bucket', () => {
  const coreNames = CORE.map((t) => t.name);
  const deferredNames = CATEGORIES.flatMap((c) => c.tools.map((t) => t.name));

  assert.equal(new Set(coreNames).size, coreNames.length, 'no duplicate core entries');
  assert.equal(new Set(deferredNames).size, deferredNames.length, 'no tool in two categories');

  const overlap = coreNames.filter((n) => deferredNames.includes(n));
  assert.deepEqual(overlap, [], 'core and deferred are disjoint');

  assert.equal(
    coreNames.length + deferredNames.length,
    index.tools.length,
    'the partition is exhaustive - nothing is orphaned'
  );
  // The registry still knows every tool, so the daemon and --config are intact.
  for (const n of [...coreNames, ...deferredNames]) assert.ok(index.get(n), `${n} is registered`);
});

test('find_tools itself is core, or the model could never load anything', () => {
  assert.ok(index.coreNames().includes('find_tools'));
});

test('every category has keywords and at least one tool', () => {
  for (const c of CATEGORIES) {
    assert.ok(c.tools.length > 0, `${c.id} has tools`);
    assert.ok(c.keywords.length > 0, `${c.id} has keywords`);
    assert.ok(c.summary, `${c.id} has a summary for the prompt`);
  }
});

/* ------------------------------ activation ------------------------------ */

test('a matching query loads the whole family', () => {
  const state = { activatedTools: new Set() };
  const out = findTools.run({ query: 'search the web for the latest node release' }, { state });
  assert.match(out, /Loaded web/);
  assert.match(out, /web_search/);
  assert.match(out, /web_fetch/);
  assert.match(out, /scrape/, 'the whole family loads, not just the obvious one');
  assert.deepEqual([...state.activatedTools].sort(), ['scrape', 'web_fetch', 'web_search']);
});

test('matching works per category and by tool name', () => {
  assert.deepEqual(findTools.matchCategories('remind me every morning'), ['automation']);
  assert.deepEqual(findTools.matchCategories('where does the project stand'), ['project']);
  assert.deepEqual(findTools.matchCategories('my github notifications'), ['github']);
  assert.deepEqual(findTools.matchCategories('make a directory'), ['filesystem']);
  assert.deepEqual(findTools.matchCategories('web_search'), ['web'], 'tool names match too');
  assert.deepEqual(findTools.matchCategories('web'), ['web'], 'the bare category id matches');
});

test('a query matching nothing returns the catalogue instead of guessing', () => {
  const state = { activatedTools: new Set() };
  const out = findTools.run({ query: 'zzz completely unrelated' }, { state });
  assert.match(out, /Nothing matched/);
  for (const c of CATEGORIES) assert.match(out, new RegExp(c.id), `lists ${c.id}`);
  assert.equal(state.activatedTools.size, 0, 'nothing was activated on a miss');
});

test('an empty query asks rather than loading everything', () => {
  const state = { activatedTools: new Set() };
  const out = findTools.run({}, { state });
  assert.match(out, /Tell me what you want to do/);
  assert.equal(state.activatedTools.size, 0);
});

test('loading twice is idempotent and says so', () => {
  const state = { activatedTools: new Set() };
  findTools.run({ query: 'github notifications' }, { state });
  const again = findTools.run({ query: 'github notification' }, { state });
  assert.match(again, /Already loaded: github_notifications/);
  assert.equal(state.activatedTools.size, 1);
});

/* ------------------------------- specs ---------------------------------- */

test('an interactive agent starts core-only and grows only when asked', () => {
  const agent = new Agent({ client: {}, config: { tools: true } });
  const fresh = agent.currentSpecs();
  assert.equal(fresh.length, CORE.length);
  assert.equal(bytes(fresh), bytes(index.coreSpecs));
  assert.ok(!fresh.some((s) => s.function.name === 'web_search'), 'deferred absent at rest');

  findTools.run({ query: 'search the web' }, agent);
  const after = agent.currentSpecs();
  assert.ok(after.length > fresh.length);
  assert.ok(after.some((s) => s.function.name === 'web_search'), 'present once loaded');
  assert.ok(after.some((s) => s.function.name === 'read_file'), 'core never drops out');
});

test('activation survives /clear, matching jobs and todos', () => {
  const agent = new Agent({ client: {}, config: { tools: true } });
  findTools.run({ query: 'search the web' }, agent);
  assert.ok(agent.state.activatedTools.has('web_search'));
  agent.clear();
  assert.ok(agent.state.activatedTools.has('web_search'), 'clear only resets messages');
  assert.ok(agent.currentSpecs().some((s) => s.function.name === 'web_search'));
});

test('tools off means no specs at all, activated or not', () => {
  const agent = new Agent({ client: {}, config: { tools: false } });
  assert.deepEqual(agent.currentSpecs(), []);
  findTools.run({ query: 'search the web' }, agent);
  assert.deepEqual(agent.currentSpecs(), []);
});

/* --------------------------- the daemon guard --------------------------- */

test('a one-shot agent always carries every tool', () => {
  const worker = new Agent({ client: {}, config: { tools: true }, deferTools: false });
  assert.equal(worker.currentSpecs().length, index.tools.length, 'no discovery round trip for routines');
  assert.ok(worker.currentSpecs().some((s) => s.function.name === 'github_notifications'));
  assert.ok(worker.currentSpecs().some((s) => s.function.name === 'watch'));
  // Loading more changes nothing for it.
  findTools.run({ query: 'search the web' }, worker);
  assert.equal(worker.currentSpecs().length, index.tools.length);
});

/* ------------------------- the budget, measured -------------------------- */

test('the history budget is materially larger before activation', () => {
  const build = () =>
    new Agent({
      client: {},
      config: { tools: true, contextWindow: 30000, maxTokens: 100, historyMessages: 200 },
      deferTools: true,
    });
  const fill = (agent) => {
    for (let i = 0; i < 60; i++) {
      agent.messages.push({ role: 'user', content: 'u'.repeat(300) });
      agent.messages.push({ role: 'assistant', content: 'a'.repeat(300) });
    }
  };

  const lean = build();
  fill(lean);
  lean.trimHistory(200);

  const heavy = build();
  for (const c of CATEGORIES) findTools.run({ query: c.id }, heavy);
  fill(heavy);
  heavy.trimHistory(200);

  assert.ok(
    lean.messages.length > heavy.messages.length,
    `core-only must keep more history: ${lean.messages.length} vs ${heavy.messages.length}`
  );
});

/* ------------------------------- prompt --------------------------------- */

test('the system prompt never offers a deferred tool as directly available', () => {
  const prompt = buildSystemPrompt({ username: 'k', agentName: 'a', systemExtra: '' }, 'C:/x');
  const toolLine = prompt.split('\n').find((l) => l.startsWith('You have these tools:'));
  assert.ok(toolLine, 'the prompt lists tools');

  for (const name of index.coreNames()) {
    assert.ok(toolLine.includes(name), `core tool ${name} is listed`);
  }
  const deferred = CATEGORIES.flatMap((c) => c.tools.map((t) => t.name));
  for (const name of deferred) {
    assert.ok(!toolLine.includes(name), `${name} must NOT be listed as directly available`);
  }
  // They are still discoverable - named in the group list, behind find_tools.
  for (const c of CATEGORIES) {
    assert.ok(prompt.includes(c.id), `the prompt tells the model about ${c.id}`);
  }
  assert.match(prompt, /find_tools/);
});

/* -------------------------------- gates --------------------------------- */

test('loading gates only what is offered, not what can run', async () => {
  const agent = new Agent({ client: {}, config: { tools: true } });
  assert.ok(!agent.currentSpecs().some((s) => s.function.name === 'project'));

  // Nothing activated, yet a deferred tool still executes when called - the
  // gate is on the offer, never on the registry.
  const out = await agent.runToolCall({
    id: '1',
    type: 'function',
    function: { name: 'project', arguments: JSON.stringify({ action: 'list' }) },
  });
  assert.doesNotMatch(out, /unknown tool/);
});

/* ------------------------------ scrape merge ---------------------------- */

test('scrape picks a tier from the shape of the request', () => {
  assert.equal(scrape.resolveTier({ url: 'https://x.test' }), 'mid', 'one URL is a page');
  assert.equal(scrape.resolveTier({ urls: 'https://a.test https://b.test' }), 'high', 'several is a crawl');
  assert.equal(scrape.resolveTier({ url: 'https://x.test', depth: 1 }), 'high', 'a depth means crawl');
  assert.equal(scrape.resolveTier({ url: 'https://x.test', tier: 'low' }), 'low');
  assert.equal(scrape.resolveTier({ url: 'https://x.test', tier: 'mid' }), 'mid');
  assert.equal(scrape.resolveTier({ url: 'https://x.test', tier: 'high' }), 'high');
  assert.equal(scrape.resolveTier({ url: 'https://x.test', tier: 'nonsense' }), 'mid', 'garbage falls back');
});

test('the consolidated scrape spec is smaller than the three it replaced', () => {
  const one = bytes(index.get('scrape') ? index.specs.find((s) => s.function.name === 'scrape') : {});
  assert.ok(one > 0 && one < 1600, `one spec stays small, got ${one}`);
  const three = 512 + 828 + 923;
  assert.ok(one < three, 'consolidation actually saves');
  assert.equal(index.get('scrape_low'), undefined, 'the old tier names are no longer tools');
  assert.equal(index.get('scrape'), index.get('scrape'));
});
