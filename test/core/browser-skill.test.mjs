import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-browser-skill-'));
process.env.CONFIG_DIR = path.join(root, 'config');
test.after(() => fs.rmSync(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 }));
const { Agent } = await import('../../src/core/agent.mjs');
const { parseSkillFile, loadSkills, skillPromptLines } = await import('../../src/core/skills.mjs');
const config = { tools: true, model: 'fixture-model', contextWindow: 131072, historyMessages: 40, maxTokens: 1000, memoryConsolidation: false, browserToolFocus: true, autoApprove: true };
const call = (id, name, args) => ({ id, type: 'function', function: { name, arguments: JSON.stringify(args) } });
const fixture = extra => `---\nname: workflow\ndescription: Follow this workflow when using a browser.\n${extra}---\nCOMPLETE WORKFLOW BODY\n`;

test('the complete browser guide teaches committed autocomplete and batching without hiding behind runtime v2', async () => {
  const skill = loadSkills().find(item => item.name === 'browser-use');
  const prompt = skillPromptLines([skill], ['browser']).join('\n');
  assert.ok(prompt.includes(skill.body), 'recovery additions must fit the whole-body automatic budget');
  assert.match(skill.body, /autocomplete.*committed/i);
  assert.match(skill.body, /fill_form.*both backends.*experimental/i);
  assert.match(skill.body, /DNS.*path.*same host/i);
  assert.match(skill.body, /ref's segments are not a tab ID/i);
  assert.match(skill.body, /before any edit.*before each step/i);
  const { parameters } = await import('../../tools/browser/browser.mjs');
  assert.match(parameters.properties.fields.description, /Prefer.*separate/i);
});

test('initial browser discovery is explicit even with focus off and the full guide absent', async () => {
  const agent = new Agent({ client: {}, config: { ...config, browserToolFocus: false }, workspacePath: root, skillsEnabled: true });
  const skill = loadSkills().find(item => item.name === 'browser-use');
  let rounds = 0;
  // Scripted policy checks the affordance; it does not claim arbitrary models follow it.
  agent.streamTurn = async () => {
    if (++rounds === 1 && agent.messages[0].content.includes('find_tools(query="browser")')) return { content: '', toolCalls: [call('discover', 'find_tools', { query: 'browser' })] };
    return { content: 'Browser tools available', toolCalls: [] };
  };
  assert.ok(!agent.messages[0].content.includes(skill.body));
  await agent.send('Use the browser to inspect this website.');
  assert.equal(agent.totalToolCalls, 1);
  assert.equal(rounds, 2);
  assert.deepEqual(agent.skillAudit.automatic, ['browser-use']);
  assert.equal(agent.state.toolFocus, null);
});

test('automatic tool metadata is optional, bounded, validated and deduplicated', () => {
  assert.deepEqual(parseSkillFile(fixture(''), 'workflow').autoTools, []);
  assert.deepEqual(parseSkillFile(fixture('auto-tools: browser, browser, read_file\n'), 'workflow').autoTools, ['browser', 'read_file']);
  for (const value of ['browser*', '../browser', 'browser read_file', 'x'.repeat(201)]) {
    assert.match(parseSkillFile(fixture(`auto-tools: ${value}\n`), 'workflow').error || '', /auto-tools/);
  }
});

test('automatic instructions appear only for matching tools, once, with complete-body budgeting', () => {
  const skill = parseSkillFile(fixture('auto-tools: browser\n'), 'workflow');
  assert.doesNotMatch(skillPromptLines([skill]).join('\n'), /COMPLETE WORKFLOW BODY/);
  assert.doesNotMatch(skillPromptLines([skill], ['git']).join('\n'), /COMPLETE WORKFLOW BODY/);
  const active = skillPromptLines([skill], ['browser', 'browser']).join('\n');
  assert.equal(active.split('COMPLETE WORKFLOW BODY').length - 1, 1);
  assert.match(active, /already loaded/i);
  const tooLarge = { ...skill, name: 'large', body: 'x'.repeat(6001) + 'FINAL SAFETY RULE' };
  const bounded = skillPromptLines([skill, tooLarge], ['browser']).join('\n');
  assert.match(bounded, /COMPLETE WORKFLOW BODY/);
  assert.doesNotMatch(bounded, /xxx|FINAL SAFETY RULE/);
  assert.match(bounded, /skill\(\{"name":"large"\}\)/);
});

test('discovery activates instructions only after the refusing focus boundary accepts the group', async () => {
  const agent = new Agent({ client: {}, config, workspacePath: root, skillsEnabled: true });
  const skill = loadSkills().find(item => item.name === 'browser-use');
  assert.ok(skill, 'browser-use is installed');
  assert.match(await agent.runToolCall(call('mixed', 'find_tools', { query: 'drive a real browser', scope: 'focus' })), /^Error:/);
  agent.refreshPrompt();
  assert.ok(!agent.messages[0].content.includes(skill.body));
  await agent.runToolCall(call('accepted', 'find_tools', { query: 'browser', scope: 'focus' }));
  agent.refreshPrompt();
  assert.ok(agent.messages[0].content.includes(skill.body));
  assert.match(await agent.runToolCall(call('manual', 'skill', { name: 'browser-use' })), /^# Skill: browser-use/);
});

test('disabled skills, non-chat agents and unrelated tool use never auto-load browser instructions', async () => {
  const skill = loadSkills().find(item => item.name === 'browser-use');
  assert.ok(skill);
  for (const settings of [{ skillsEnabled: false }, { skillsEnabled: true, disabledSkills: ['browser-use'] }]) {
    const agent = new Agent({ client: {}, config, workspacePath: root, ...settings });
    await agent.runToolCall(call('discover', 'find_tools', { query: 'browser', scope: 'focus' }));
    agent.refreshPrompt();
    assert.ok(!agent.messages[0].content.includes(skill.body));
    assert.match(await agent.runToolCall(call('manual', 'skill', { name: 'browser-use' })), /^Error:/);
    const receipts = [];
    agent.streamTurn = async () => ({ content: 'No guide active', toolCalls: [] });
    await agent.send('Continue', { onSkillsLoaded: names => receipts.push(names) });
    assert.deepEqual(receipts, [], 'disabled bodies must not produce a desktop loaded receipt');
  }
  const agent = new Agent({ client: {}, config, workspacePath: root, skillsEnabled: true });
  await agent.runToolCall(call('git', 'find_tools', { query: 'git' }));
  agent.refreshPrompt();
  assert.ok(!agent.messages[0].content.includes(skill.body));
});

test('an already-discovered browser activates the guide on use and clear removes turn instructions', async () => {
  const skill = loadSkills().find(item => item.name === 'browser-use');
  assert.ok(skill);
  const agent = new Agent({ client: {}, config, workspacePath: root, skillsEnabled: true, browserManager: { run: async () => 'Current page observation' } });
  agent.state.activatedTools.add('browser');
  assert.ok(!agent.messages[0].content.includes(skill.body));
  await agent.runToolCall(call('use', 'browser', { action: 'snapshot' }));
  agent.refreshPrompt();
  assert.ok(agent.messages[0].content.includes(skill.body));
  agent.clear();
  assert.ok(!agent.messages[0].content.includes(skill.body));
});

test('an already-advertised browser receives its complete guide before the first model decision of a continuation', async () => {
  const skill = loadSkills().find(item => item.name === 'browser-use');
  const agent = new Agent({ client: {}, config, workspacePath: root, skillsEnabled: true, print: () => {}, write: () => {} });
  agent.state.activatedTools.add('browser');
  agent.messages.push({ role: 'user', content: 'Find Mumbai to Delhi flights.' }, { role: 'assistant', content: 'I can use the browser.' });
  agent.streamTurn = async () => {
    assert.ok(agent.messages[0].content.includes(skill.body), 'the first decision must receive instructions for the advertised browser');
    return { content: 'Ready to continue', toolCalls: [] };
  };
  await agent.send('continue');
  assert.deepEqual(agent.skillAudit.automatic, ['browser-use']);
});

test('failed model turns release automatic instructions while retaining an activation audit', async () => {
  const skill = loadSkills().find(item => item.name === 'browser-use');
  const agent = new Agent({ client: {}, config, workspacePath: root, skillsEnabled: true, print: () => {}, write: () => {} });
  agent.streamTurn = async () => {
    await agent.runToolCall(call('discover', 'find_tools', { query: 'browser', scope: 'focus' }));
    agent.refreshPrompt();
    assert.ok(agent.messages[0].content.includes(skill.body));
    throw new Error('fixture provider disconnected');
  };
  await assert.rejects(agent.send('Browse'), /fixture provider disconnected/);
  assert.deepEqual(agent.skillAudit.automatic, ['browser-use']);
  assert.ok(!agent.messages[0].content.includes(skill.body));
  assert.equal(agent.activeSkillTools.size, 0);
  assert.equal(agent.state.toolFocus, null);
});

test('Stop after discovery cannot claim a guide was loaded before the next prompt existed', async () => {
  const agent = new Agent({ client: {}, config, workspacePath: root, skillsEnabled: true, print: () => {}, write: () => {} });
  agent.streamTurn = async () => ({ content: '', toolCalls: [call('discover', 'find_tools', { query: 'browser', scope: 'focus' })] });
  const receipts = [];
  await agent.send('Browse', { onToolResult: () => agent.abort.abort(), onSkillsLoaded: names => receipts.push(names) });
  assert.equal(agent.totalToolCalls, 1);
  assert.deepEqual(agent.skillAudit.automatic, [], 'activation eligibility is not evidence that the body was loaded');
  assert.deepEqual(receipts, [], 'Stop before the request must not announce guide inclusion');
});

test('a guide removed from the request cannot produce a loaded receipt', async () => {
  const skill = loadSkills().find(item => item.name === 'browser-use');
  const agent = new Agent({ client: {}, config, workspacePath: root, skillsEnabled: true, print: () => {}, write: () => {} });
  agent.state.activatedTools.add('browser');
  agent.trimHistory = () => { agent.messages[0].content = agent.messages[0].content.replace(skill.body, ''); };
  agent.streamTurn = async () => ({ content: 'Request without automatic body', toolCalls: [] });
  const receipts = [];
  await agent.send('Continue', { onSkillsLoaded: names => receipts.push(names) });
  assert.deepEqual(receipts, []);
});

test('HTTP model receives the guide before real browsing and retains it while the browser remains advertised', async t => {
  const skill = loadSkills().find(item => item.name === 'browser-use');
  assert.ok(skill);
  const requests = [];
  const server = http.createServer((req, res) => {
    if (!req.url.startsWith('/model')) {
      res.setHeader('content-type', 'text/html');
      res.end('<title>Skill round trip</title><label>Name <input name="name"></label>');
      return;
    }
    let text = '';
    req.on('data', chunk => { text += chunk; });
    req.on('end', () => {
      const body = JSON.parse(text); requests.push(body);
      const step = requests.length;
      let next;
      if (step === 1) next = call('discover', 'find_tools', { query: 'browser', scope: 'focus' });
      if (step === 2) next = call('open', 'browser', { action: 'open', url: `http://127.0.0.1:${server.address().port}/page` });
      if (step === 3) {
        const observation = body.messages.findLast(message => message.role === 'tool').content;
        const ref = observation.split('\n').find(line => line.includes('[ref=') && line.includes('Name'))?.match(/\[ref=([^\]]+)\]/)?.[1];
        next = call('fill', 'browser', { action: 'fill_form', fields: [{ ref, text: 'Observed name' }] });
      }
      const message = next ? { content: null, tool_calls: [next] } : { content: 'Observed completed field' };
      res.setHeader('content-type', 'application/json');
      res.end(JSON.stringify({ choices: [{ message }] }));
    });
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const { PlaywrightBrowserAdapter } = await import('../../tools/browser/playwright.mjs');
  const adapter = new PlaywrightBrowserAdapter({ profile: path.join(root, 'live-profile') });
  t.after(async () => { await adapter.close(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); });
  const agent = new Agent({
    client: { baseUrl: `http://127.0.0.1:${server.address().port}/model`, headers: () => ({ 'content-type': 'application/json' }) },
    config: { ...config, allowPrivateHosts: true }, workspacePath: root, skillsEnabled: true,
    browserManager: { run: (args, ctx) => adapter.run(args, { ...ctx, settings: { headless: true } }) }, print: () => {}, write: () => {},
  });
  await agent.send('Open the supplied page and fill the Name field');
  assert.equal(requests.length, 4);
  assert.equal(agent.totalToolCalls, 3);
  assert.ok(!requests[0].messages[0].content.includes(skill.body));
  for (const request of requests.slice(1)) assert.equal(request.messages[0].content.split(skill.body).length - 1, 1);
  assert.deepEqual(agent.skillAudit.automatic, ['browser-use']);
  assert.match(await adapter.run({ action: 'snapshot' }, { config: { allowPrivateHosts: true } }), /Observed name/);
  const observed = agent.messages.filter(message => message.role === 'tool').map(message => message.content);
  assert.ok(observed.length === 3 && !observed.some(content => content.includes(skill.body)));
  await agent.send('Say hello without tools');
  assert.equal(requests.length, 5);
  assert.ok(requests.at(-1).messages[0].content.includes(skill.body), 'advertised browser instructions precede the first continuation decision');
  assert.deepEqual(agent.skillAudit.automatic, ['browser-use']);
  console.log('BROWSER_SKILL_LIVE_OK modelRounds=4 toolCalls=3 extraSkillCalls=0 realFieldReadBack=true advertisedGuide=true');
});
