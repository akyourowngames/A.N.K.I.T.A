import test from 'node:test';
import assert from 'node:assert/strict';
import { loadSkills, activeAutomaticSkills, skillPromptLines } from '../../src/core/skills.mjs';
import { checkSkillContributions } from '../../src/skills/contributions.mjs';
import { run as findTools } from '../../tools/find-tools.mjs';
import { Agent } from '../../src/core/agent.mjs';

test('five productive workflows load with complete contribution artifacts', () => {
  const skills = loadSkills();
  for (const name of ['mobile-mcp', 'action-chain', 'research-brief', 'workspace-batch', 'skill-discovery']) {
    assert.ok(skills.some(skill => skill.name === name), `${name} is installed`);
  }
  assert.deepEqual(checkSkillContributions().errors, []);
});

test('mobile instructions load during MCP discovery under any server id without an extra skill read', () => {
  const active = [];
  const state = {};
  const output = findTools({ query: 'phone' }, {
    state, skillsEnabled: true,
    mcp: { summaries: () => [{ id: 'phone', deferred: true, tools: ['mobile_list_elements_on_screen', 'mobile_batch_commands'] }] },
    onToolsActivated: names => active.push(...names),
  });
  assert.match(output, /mcp__phone__mobile_batch_commands/);
  const skills = loadSkills();
  const loaded = activeAutomaticSkills(skills, new Set(active));
  assert.ok(loaded.some(skill => skill.name === 'mobile-mcp'));
  const mobile = skills.find(skill => skill.name === 'mobile-mcp');
  assert.ok(skillPromptLines(skills, active).join('\n').includes(mobile.body));
  assert.ok(!activeAutomaticSkills(skills, ['mcp__phone__not_mobile']).some(skill => skill.name === 'mobile-mcp'));
});

test('already callable mobile MCP tools receive instructions before the first decision on every turn', async () => {
  const name = 'mcp__phone__mobile_batch_commands';
  const mcp = {
    summaries: () => [{ id: 'phone', deferred: false, tools: ['mobile_batch_commands'] }],
    alwaysOnIds: () => ['phone'],
    specs: () => [{ type: 'function', function: { name, description: 'Run known stable commands.', parameters: { type: 'object', properties: {} } } }],
  };
  const agent = new Agent({ client: {}, mcp, skillsEnabled: true, config: { tools: true, maxTokens: 1000, contextWindow: 131072, memoryConsolidation: false } });
  const body = loadSkills().find(skill => skill.name === 'mobile-mcp').body;
  agent.streamTurn = async () => {
    assert.ok(agent.messages[0].content.includes(body), 'mobile workflow is present before any action');
    return { content: 'Instructions available.', toolCalls: [] };
  };
  await agent.send('Use the connected phone.');
  assert.ok(agent.skillAudit.automatic.includes('mobile-mcp'));
  await agent.send('Continue the phone task.');
  assert.ok(agent.skillAudit.automatic.includes('mobile-mcp'));
});

test('held-back mobile instructions stay absent until discovery, then persist with admitted MCP schemas', async () => {
  const name = 'mcp__phone__mobile_batch_commands';
  const mcp = {
    summaries: () => [{ id: 'phone', deferred: true, tools: ['mobile_batch_commands'] }],
    has: id => id === 'phone',
    alwaysOnIds: () => [],
    specs: () => [{ type: 'function', function: { name, description: 'Run known stable commands.', parameters: { type: 'object', properties: {} } } }],
  };
  const agent = new Agent({ client: {}, mcp, skillsEnabled: true, config: { tools: true, maxTokens: 1000, contextWindow: 131072, memoryConsolidation: false } });
  const body = loadSkills().find(skill => skill.name === 'mobile-mcp').body;
  let round = 0;
  agent.streamTurn = async () => {
    if (++round === 1) {
      assert.ok(!agent.messages[0].content.includes(body));
      return { content: '', toolCalls: [{ id: 'discover-mobile', function: { name: 'find_tools', arguments: '{"query":"phone"}' } }] };
    }
    assert.ok(agent.messages[0].content.includes(body));
    return { content: 'Ready.', toolCalls: [] };
  };
  await agent.send('Use the phone.');
  await agent.send('Continue.');
  assert.equal(round, 3);
  assert.ok(agent.skillAudit.automatic.includes('mobile-mcp'));
});
