import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'skill-access-'));
process.env.CONFIG_DIR = path.join(root, 'profile');
test.after(() => fs.rmSync(root, { recursive: true, force: true }));

async function api() {
  const url = new URL('../../tools/skills/skill-manage.mjs', import.meta.url);
  assert.ok(fs.existsSync(url), 'skill manager is available to chat');
  return import(url.href);
}

test('manager is deferred, discoverable, and install alone requires approval and writes', async () => {
  const tool = await api();
  const { coreNames, needsApproval, isReadOnly } = await import('../../tools/index.mjs');
  const { run } = await import('../../tools/find-tools.mjs');
  const state = { activatedTools: new Set() };
  assert.ok(!coreNames().includes(tool.name));
  assert.match(run({ query: 'skill_manage' }, { state, skillsEnabled: true }), /skill_manage/);
  for (const action of ['list', 'search', 'preview']) {
    assert.equal(needsApproval(tool.name, { action }), false);
    assert.equal(isReadOnly(tool.name, { action }), true);
  }
  assert.equal(needsApproval(tool.name, { action: 'install' }), true);
  assert.equal(isReadOnly(tool.name, { action: 'install' }), false);
  assert.match(tool.approval({ action: 'install', source: 'example/repo', name: 'mobile-helper', commit: 'a'.repeat(40), path: 'skills/mobile-helper/SKILL.md', sha256: 'b'.repeat(64) }), /bbbbbbbb/);
  assert.doesNotMatch(run({ query: 'skill_manage' }, { state: {}, skillsEnabled: false }), /Now callable: skill_manage/);
});

test('local list and help work through the real CLI without provider authentication', async () => {
  await api(); // Missing feature must fail before a child could enter provider startup.
  const list = execFileSync(process.execPath, ['chat.mjs', 'skills', 'list'], { encoding: 'utf8', timeout: 10000 });
  const parsed = JSON.parse(list);
  assert.ok(parsed.some(item => item.name === 'commit-review'));
  const help = execFileSync(process.execPath, ['chat.mjs', 'skills', '--help'], { encoding: 'utf8', timeout: 10000 });
  assert.match(help, /search.*preview.*install/);
});

test('local commands forward exact preview pins and reject unknown actions before model startup', async () => {
  const { runLocalCommand } = await import('../../src/core/local-commands.mjs');
  const requests = [], output = [];
  const manager = {
    search: async query => { requests.push(query); return [{ name: 'mobile-helper' }]; },
    preview: async args => { requests.push(args); return { name: args.name }; },
    install: async args => { requests.push(args); return { name: args.name }; },
  };
  assert.equal(await runLocalCommand(['skills', 'search', 'mobile', 'actions'], { skillManager: manager, write: text => output.push(text) }), true);
  assert.equal(requests[0], 'mobile actions');
  await runLocalCommand(['skills', 'install', 'example/repo', 'mobile-helper', '--commit', 'a'.repeat(40), '--path', 'SKILL.md', '--sha256', 'b'.repeat(64)], { skillManager: manager, write: text => output.push(text) });
  assert.equal(requests[1].commit, 'a'.repeat(40));
  assert.equal(requests[1].path, 'SKILL.md');
  await assert.rejects(runLocalCommand(['skills', 'oops']), /Usage|skills/i);
});

test('real tool host refuses denied installs and rejects manager calls outside interactive chat', async () => {
  const tool = await api();
  const { ToolHost } = await import('../../src/core/tool-host.mjs');
  let approval = '';
  const host = new ToolHost({ context: () => ({ skillsInteractive: true, config: {}, cwd: root }), authorize: async (name, detail) => { approval = detail; return false; } });
  const result = await host.execute({ id: 'denied', name: tool.name, arguments: { action: 'install', source: 'example/repo', name: 'mobile-helper', commit: 'a'.repeat(40), path: 'SKILL.md', sha256: 'b'.repeat(64) } });
  assert.match(result.content[0].text, /denied/i);
  assert.match(approval, /example\/repo/);
  assert.ok(!fs.existsSync(path.join(root, 'profile', 'skills')));
  const background = new ToolHost({ context: () => ({ skillsInteractive: false, config: {}, cwd: root }) });
  const refused = await background.execute({ id: 'background', name: tool.name, arguments: { action: 'list' } });
  assert.match(refused.content[0].text, /interactive/);
});

test('background agents never advertise the manager even with non-deferred schemas', async () => {
  const { Agent } = await import('../../src/core/agent.mjs');
  const agent = new Agent({ client: {}, config: { tools: true }, deferTools: false, skillsEnabled: false });
  assert.ok(!agent.currentSpecs().some(spec => spec.function.name === 'skill_manage'));
  assert.doesNotMatch(agent.messages[0].content, /skill-manager|skill_manage/);
});
