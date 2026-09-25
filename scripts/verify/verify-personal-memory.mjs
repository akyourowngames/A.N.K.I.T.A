// Explicit live smoke check. Uses synthetic conversations in a temporary home.
// Run: node scripts/verify/verify-personal-memory.mjs --live
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import assert from 'node:assert/strict';

if (!process.argv.includes('--live')) throw new Error('Pass --live to make model calls using your configured provider.');
const originalHome = process.env.CONFIG_DIR || path.join(os.homedir(), '.copilot-chat-cli');
const scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-memory-live-'));
// Read credentials only into memory; never echo them or copy the auth file.
let auth = {};
try { auth = JSON.parse(fs.readFileSync(path.join(originalHome, 'auth.json'), 'utf8')); } catch {}
try {
  const globalConfig = fs.readFileSync(path.join(originalHome, 'config.env'), 'utf8');
  fs.writeFileSync(path.join(scratch, 'config.env'), globalConfig, { mode: 0o600 });
} catch {}
process.env.CONFIG_DIR = scratch;
try {
  const { loadConfig, PROFILE_FILE, PROJECTS_FILE } = await import('../../src/core/config.mjs');
  const { Agent } = await import('../../src/core/agent.mjs');
  const { CopilotClient } = await import('../../src/core/auth.mjs');
  const { CompatibleClient, pickModel } = await import('../../src/core/provider.mjs');
  const { ProfileStore } = await import('../../src/memory/profile.mjs');
  const { ProjectStore } = await import('../../src/memory/projects.mjs');
  const { recordTurn } = await import('../../src/core/sessions.mjs');
  const { MemoryConsolidator } = await import('../../src/memory/consolidate.mjs');
  const { extractMemory } = await import('../../src/memory/memory-extract.mjs');
  const { run: recall } = await import('../../tools/personal/recall.mjs');
  const config = { ...loadConfig(), tools: true, autoApprove: false, memoryTimeout: 60, timeZone: 'UTC' };
  const client = config.apiBase ? new CompatibleClient(config) : new CopilotClient(process.env.GITHUB_TOKEN || auth.github_token);
  await client.ensureToken();
  const picked = pickModel(await client.models(), config.model, true);
  config.model = picked.id;
  config.contextWindow = picked.context || config.contextWindow;
  const createAgent = () => {
    const agent = new Agent({ client, config, confirm: async () => false, print: () => {}, write: () => {} });
    const stream = agent.streamTurn.bind(agent);
    agent.modelRequests = 0;
    agent.streamTurn = async options => { agent.modelRequests++; return stream(options); };
    return agent;
  };
  const first = createAgent();
  const calls = [];
  await first.send('Remember that I always prefer terse replies and avoid em dashes. These preferences apply across projects.', { onToolCall: c => calls.push(c.function.name) });
  assert.ok(calls.includes('remember'), 'model must persist the preference through remember');
  const pins = new ProfileStore(PROFILE_FILE).load().facts.filter(f => f.always);
  assert.ok(pins.length, 'model must pin explicit always preferences');
  const second = createAgent();
  assert.ok(pins.some(f => second.messages[0].content.includes(f.text)), 'fresh session must receive pinned facts');
  const listCalls = [];
  const listed = await second.send('What preferences do you have saved about me? Use remember to list them.', { onToolCall: c => listCalls.push(c.function.name) });
  assert.ok(listCalls.includes('remember'), `Expected a memory lookup. Calls: ${listCalls.join(', ')}. Reply: ${listed}`);
  const projects = new ProjectStore(PROJECTS_FILE).load();
  const project = projects.add({ name: 'Sample Observatory' });
  recordTurn({ text: "My dog's name is Pixel. For Sample Observatory we decided to use SQLite because it works offline. We still need to add daily backups.", reply: 'Understood.', projectId: project.id, at: new Date(Date.now() - 86400000).toISOString() }, { timeZone: 'UTC' });
  const c = new MemoryConsolidator({ config, extract: prompt => extractMemory(prompt, { client, config, model: config.model }) });
  const result = await c.run();
  assert.equal(result.processed, 1);
  assert.ok(new ProfileStore(PROFILE_FILE).load().facts.some(f => f.text.includes('Pixel') && !f.always));
  const p = new ProjectStore(PROJECTS_FILE).load().find(project.id);
  assert.ok(p.decisions.some(d => /SQLite/i.test(d.text)));
  assert.ok(p.todos.some(t => /backup/i.test(t.text)));
  assert.ok(JSON.parse(await recall({ query: 'Pixel' }, { config })).results.length);
  assert.equal((await c.run()).processed, 0);
  const personalized = [];
  for (const scenario of [
    { fact: 'I love pizza.', request: "I'm hungry and want something I'd enjoy.", term: /pizza/i },
    { fact: 'I really enjoy making pottery.', request: 'Help me pick something fun to do this weekend.', term: /pottery|ceramic/i },
  ]) {
    fs.writeFileSync(PROFILE_FILE, JSON.stringify({ version: 1, facts: [] }));
    const saving = createAgent();
    await saving.send(scenario.fact);
    await saving.send('Please remember that about me.');
    assert.ok(new ProfileStore(PROFILE_FILE).load().facts.some(f => scenario.term.test(f.text)), 'save acknowledgement must correspond to durable storage');
    const fresh = createAgent();
    const used = [];
    const reply = await fresh.send(scenario.request, { onToolCall: c => used.push(c.function.name) });
    assert.ok(used.some(n => ['recall', 'remember'].includes(n)), `Personalized advice must consult memory. Calls: ${used}. Reply: ${reply}`);
    assert.ok(scenario.term.test(reply), `Advice should reflect the saved preference. Reply: ${reply}`);
    assert.ok(!used.includes('find_tools'), 'personal memory should not require discovery round trips');
    assert.equal(fresh.modelRequests, 1, 'local recall should avoid an additional model round trip');
    personalized.push({ request: scenario.request, toolCalls: used, modelRequests: fresh.modelRequests, result: 'passed' });
  }
  console.log(JSON.stringify({ model: config.model, explicitMemory: 'passed', freshSessionPins: 'passed', modelConsolidation: 'passed', projectDecisionAndTodo: 'passed', recall: 'passed', replay: 'passed', personalized, toolCalls: calls }, null, 2));
} finally {
  // scratch is the exact mkdtemp directory created above, never a computed home.
  fs.rmSync(scratch, { recursive: true, force: true });
}
