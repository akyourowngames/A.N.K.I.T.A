import test from 'node:test';
import assert from 'node:assert/strict';
import { Agent } from '../../src/core/agent.mjs';

for (const [rounds, batch] of [[27, 1], [9, 8]]) test(`completion worker finishes ${rounds} browser rounds with ${batch} calls per round without a fixed tool ceiling`, async () => {
  let observed = 0, requested = 0;
  const agent = new Agent({ client: {}, config: { tools: true, backgroundJob: true, backgroundExecutionPolicy: 'complete', memoryConsolidation: false }, skillsEnabled: false,
    allowedTools: new Set(['browser']), browserManager: { run: async args => { observed++; return `Observed ${args.url}`; } }, print: () => {}, write: () => {} });
  agent.streamTurn = async () => ++requested <= rounds ? { content: '', toolCalls: Array.from({ length: batch }, (_, index) => ({ id: `step-${requested}-${index}`, function: { name: 'browser', arguments: JSON.stringify({ action: 'open', url: `https://example.com/step/${requested}/${index}` }) } })) } : { content: 'All steps observed.', toolCalls: [] };
  assert.equal(await agent.send('Complete this multi-step task'), 'All steps observed.');
  assert.equal(observed, rounds * batch); assert.equal(agent.terminationReason, null);
});

test('completion workers still stop a repeated browser observation that makes no progress', async () => {
  const agent = new Agent({ client: {}, config: { tools: true, backgroundJob: true, backgroundExecutionPolicy: 'complete', memoryConsolidation: false }, skillsEnabled: false,
    allowedTools: new Set(['browser']), browserManager: { run: async () => 'Same unchanged page' }, print: () => {}, write: () => {} });
  agent.streamTurn = async () => ({ content: '', toolCalls: [{ id: `repeat-${agent.totalToolCalls}`, function: { name: 'browser', arguments: '{"action":"read"}' } }] });
  await agent.send('Complete the task');
  assert.match(agent.terminationReason, /repeating/);
});

test('a background worker corrects printed pretend tool calls through the model without executing their text', async () => {
  let rounds = 0, calls = 0;
  const agent = new Agent({ client: {}, config: { tools: true, backgroundJob: true, memoryConsolidation: false }, skillsEnabled: false,
    allowedTools: new Set(['browser']), browserManager: { run: async () => { calls++; return 'Observed confirmation'; } }, print: () => {}, write: () => {} });
  agent.streamTurn = async () => {
    if (++rounds === 1) return { content: '[Tool call: browser]\n{"action":"act","ref":"guessed"}', toolCalls: [] };
    if (rounds === 2) return { content: '', toolCalls: [{ id: 'read', function: { name: 'browser', arguments: '{"action":"read"}' } }] };
    return { content: 'Observed completion', toolCalls: [] };
  };
  assert.equal(await agent.send('Finish the scheduled task'), 'Observed completion');
  assert.equal(rounds, 3); assert.equal(calls, 1);
  assert.ok(agent.messages.some(message => message.role === 'user' && typeof message.content === 'string' && /native tool calls/.test(message.content)));
});

test('repeated pretend tool calls stop a background worker instead of reporting a successful job', async () => {
  let rounds = 0;
  const agent = new Agent({ client: {}, config: { tools: true, backgroundJob: true, memoryConsolidation: false }, skillsEnabled: false, print: () => {}, write: () => {} });
  agent.streamTurn = async () => { rounds++; return { content: '[Tool call: browser]\n{"action":"read"}', toolCalls: [] }; };
  await assert.rejects(agent.send('Finish the scheduled task'), /did not execute its requested tools/);
  assert.equal(rounds, 2);
});

test('a printed tool request on the final allowed round cannot become a successful forced summary', async () => {
  let rounds = 0;
  const agent = new Agent({ client: {}, config: { tools: true, backgroundJob: true, maxToolSteps: 1, memoryConsolidation: false }, skillsEnabled: false, print: () => {}, write: () => {} });
  agent.streamTurn = async () => ({ content: ++rounds === 1 ? '[Tool call: browser]' : 'Task completed successfully.', toolCalls: [] });
  await assert.rejects(agent.send('Finish the task'), /did not execute its requested tools/); assert.equal(rounds, 1);
});

test('a scheduled worker receives execution guidance without the foreground job-creation instructions', () => {
  const agent = new Agent({ client: {}, config: { tools: true, desktopBackgroundJobs: true, backgroundJob: true }, skillsEnabled: false });
  const prompt = agent.messages[0].content;
  assert.match(prompt, /executing an existing scheduled task/);
  assert.match(prompt, /whole requested task is complete/);
  assert.doesNotMatch(prompt, /create and update active jobs from the conversation/);
});

test('job browser schemas advertise only isolated Chromium while foreground Chrome remains available', () => {
  const options = { client: {}, skillsEnabled: false, deferTools: false, allowedTools: new Set(['browser']) };
  const job = new Agent({ ...options, config: { tools: true, backgroundJob: true } });
  const foreground = new Agent({ ...options, config: { tools: true } });
  assert.deepEqual(job.currentSpecs()[0].function.parameters.properties.mode.enum, ['isolated']);
  assert.match(job.currentSpecs()[0].function.description, /action=login with credential_fields/);
  assert.match(job.currentSpecs()[0].function.description, /status=available means nothing was filled/);
  assert.ok(foreground.currentSpecs()[0].function.parameters.properties.mode.enum.includes('local'));
});
test('background tool policy rejects shell and external MCP before approval or execution', async () => {
  let called = 0;
  const mcp = { summaries: () => [], alwaysOnIds: () => [], specs: () => [], callTool: async () => { called++; return 'wrong'; } };
  const agent = new Agent({ client: {}, config: { tools: true, autoApprove: true }, mcp,
    allowedTools: new Set(['browser']), skillsEnabled: false, deferTools: false });
  for (const name of ['run_command', 'mcp__external__browser_click']) {
    assert.match(await agent.runToolCall({ id: name, function: { name, arguments: '{}' } }), /not available.*background/i);
  }
  assert.equal(called, 0);
  assert.deepEqual(agent.specParts().core.map(spec => spec.function.name), ['browser']);
});
test('background browser context reaches the same built-in tool with runtime permission hooks', async () => {
  let context;
  const hook = async () => {};
  const agent = new Agent({ client: {}, config: { tools: true, autoApprove: true }, skillsEnabled: false,
    allowedTools: new Set(['browser']), toolContext: { backgroundJob: true, authorizeBrowser: hook },
    browserManager: { run: async (_args, ctx) => { context = ctx; return 'ok'; } } });
  assert.equal(await agent.runToolCall({ id: 'call', function: { name: 'browser', arguments: '{"action":"tabs"}' } }), 'ok');
  assert.equal(context.backgroundJob, true); assert.equal(context.authorizeBrowser, hook);
});
