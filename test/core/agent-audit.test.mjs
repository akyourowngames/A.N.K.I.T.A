import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const sandbox = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-agent-audit-'));
process.env.CONFIG_DIR = sandbox;
test.after(() => fs.rmSync(sandbox, { recursive: true, force: true }));
const { Agent } = await import('../../src/core/agent.mjs');
const { needsApproval } = await import('../../tools/index.mjs');
const { skillsDir } = await import('../../src/core/skills.mjs');
const call = (name, args) => ({ id: 'audit', type: 'function', function: { name, arguments: JSON.stringify(args) } });
const config = { tools: true, historyMessages: 40, maxTokens: 1000, memoryConsolidation: false };

test('a required approval with no detail still prompts and redacts fallback arguments', async () => {
  let detail, prompts = 0;
  const agent = new Agent({ client: {}, config, confirm: (_, text) => { prompts++; detail = text; return false; } });
  const result = await agent.runToolCall(call('mcp_manage', { action: 'reload', id: 'missing', api_key: 'approval-secret', headers: { Authorization: 'Bearer nested-secret' } }));
  assert.equal(prompts, 1);
  assert.match(result, /denied/);
  assert.doesNotMatch(detail, /approval-secret|nested-secret/);
  assert.match(detail, /reload/);
});
test('read-only mcp configuration actions declare their approval policy explicitly', () => {
  assert.equal(needsApproval('mcp_manage', { action: 'list' }), false);
  assert.equal(needsApproval('mcp_manage', { action: 'reload' }), true);
});
test('truthy non-boolean config cannot silently approve a write', async () => {
  let prompts = 0;
  const agent = new Agent({ client: {}, workspacePath: sandbox, config: { ...config, autoApprove: 'false' }, confirm: () => { prompts++; return false; } });
  assert.match(await agent.runToolCall(call('write_file', { path: 'must-not-exist.txt', content: 'bad' })), /denied/);
  assert.equal(prompts, 1);
  assert.equal(fs.existsSync(path.join(sandbox, 'must-not-exist.txt')), false);
});
test('only an explicit boolean confirmation permits local and MCP mutations', async () => {
  const agent = new Agent({ client: {}, workspacePath: sandbox, config, confirm: () => 'false' });
  assert.match(await agent.runToolCall(call('write_file', { path: 'bad-confirm.txt', content: 'bad' })), /denied/);
  assert.equal(fs.existsSync(path.join(sandbox, 'bad-confirm.txt')), false);
  let called = false;
  agent.mcp = { findTool: () => ({}), needsApproval: () => true, approvalDetail: () => 'MCP mutation', callTool: () => { called = true; return 'bad'; } };
  assert.match(await agent.runToolCall(call('mcp__audit__write', {})), /denied/);
  assert.equal(called, false);
});
test('approval previews redact credentials loaded from config files', async () => {
  let detail;
  const agent = new Agent({ client: {}, config: { ...config, apiKey: 'config-only-credential' }, confirm: (_, text) => { detail = text; return false; } });
  assert.match(await agent.runToolCall(call('run_command', { command: 'echo config-only-credential' })), /denied/);
  assert.doesNotMatch(detail, /config-only-credential/);
  assert.match(detail, /REDACTED/);
});
test('auto-approval still prepares and rechecks the exact write', async () => {
  const agent = new Agent({ client: {}, workspacePath: sandbox, config: { ...config, autoApprove: true }, confirm: () => assert.fail('explicit auto-approval') });
  await agent.runToolCall(call('write_file', { path: 'explicit.txt', content: 'approved' }));
  assert.equal(fs.readFileSync(path.join(sandbox, 'explicit.txt'), 'utf8'), 'approved');
});
test('recall warm-up handles failures before the embedder is constructed', async () => {
  const broken = { ...config, get embeddings() { throw new Error('optional cache unavailable'); } };
  let rejection;
  const listener = error => { rejection = error; };
  process.on('unhandledRejection', listener);
  try {
    new Agent({ client: {}, config: broken });
    await new Promise(resolve => setTimeout(resolve, 30));
    assert.equal(rejection, undefined);
  } finally { process.removeListener('unhandledRejection', listener); }
});
test('skills scan once per turn and refresh for the next turn', async () => {
  const agent = new Agent({ client: {}, config: { ...config, tools: false }, skillsEnabled: true });
  const readdir = fs.readdirSync;
  let scans = 0;
  fs.readdirSync = (dir, ...args) => { if (path.resolve(dir) === path.resolve(skillsDir())) scans++; return readdir(dir, ...args); };
  try {
    agent.streamTurn = async () => {
      agent.availableSkills(); agent.availableSkills(); agent.refreshPrompt();
      return { content: 'done', toolCalls: [] };
    };
    await agent.send('one'); assert.equal(scans, 1);
    await agent.send('two'); assert.equal(scans, 2);
  } finally { fs.readdirSync = readdir; }
});
test('schemas are built once per model round and newly activated tools appear next round', async () => {
  const agent = new Agent({ client: {}, config: { ...config, autoApprove: true } });
  const build = agent.specParts.bind(agent);
  let builds = 0, rounds = 0;
  agent.specParts = () => { builds++; return build(); };
  agent.streamTurn = async () => {
    rounds++;
    agent.currentSpecs(); agent.currentSpecs();
    if (rounds === 1) return { content: '', toolCalls: [call('find_tools', { query: 'git' })] };
    assert.ok(agent.currentSpecs().some(s => s.function.name === 'git'));
    return { content: 'done', toolCalls: [] };
  };
  await agent.send('find git');
  assert.equal(builds, 2);
  agent.state.activatedTools.add('image_generate');
  assert.ok(agent.currentSpecs().some(s => s.function.name === 'image_generate'), 'round cache is released after send');
});
