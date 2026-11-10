import test from 'node:test';
import assert from 'node:assert/strict';
import { Agent } from '../../src/core/agent.mjs';
import { McpManager } from '../../src/integrations/mcp-manager.mjs';
import { fileURLToPath } from 'node:url';
import { MAX_MCP_IMAGES_PER_TURN, MAX_MCP_IMAGE_BYTES, messagesForModel } from '../../src/integrations/mcp-images.mjs';
import { COMPUTER_MCP_ID, COMPUTER_DIRECT_CONFIG, COMPUTER_TARGET_LIMIT, COMPUTER_TARGET_MAX_BYTES, computerObservationMetadata } from '../../src/integrations/computer-use.mjs';
import { TIER_ALWAYS, TIER_DENY } from '../../src/integrations/mcp-tiers.mjs';

const IMAGE = { type: 'image', mimeType: 'image/png', data: 'aGVsbG8=' };
test('real stdio discovery filters maintenance tools and delivers screenshots through Agent', async t => {
  const mcp = new McpManager(); t.after(() => mcp.closeAll());
  const record = await mcp.connect({ id: 'computer', command: process.execPath,
    args: [fileURLToPath(new URL('../../scripts/fixtures/computer-mcp.mjs', import.meta.url))], allowedTools: ['get_window_state', 'click'] });
  assert.deepEqual(record.tools.map(tool => tool.name), ['get_window_state', 'click']);
  assert.equal(mcp.findTool('mcp__computer__install_ffmpeg'), null);
  await assert.rejects(mcp.callToolResult('mcp__computer__install_ffmpeg'), /no connected/);
  await record.client.refreshTools(); assert.equal(record.tools.length, 2);
  const a = agent(null); a.mcp = mcp;
  assert.match(await a.runMcpToolCall(call), /Observed fixture state/);
  assert.equal(a.mcpImagesThisTurn, 1);
});
function agent(result, vision = true) {
  const a = Object.create(Agent.prototype);
  a.config = {}; a.client = { modelCapabilities: new Map([['test', { vision }]]) }; a.model = 'test';
  a.messages = [{ role: 'user', content: 'Use my desktop' }]; a.mcpImagesThisTurn = 0;
  a.mcp = { findTool: () => ({}), needsApproval: () => false, callToolResult: async () => result };
  return a;
}
const call = { id: 'snapshot-1', function: { name: 'mcp__computer__get_window_state', arguments: '{}' } };

test('desktop computer actions run without prompts while CLI, other services and explicit blocks keep their policy', async () => {
  for (const [direct, server, tool, tier, expected] of [
    [true, COMPUTER_MCP_ID, 'click', TIER_ALWAYS, 'executed'],
    [false, COMPUTER_MCP_ID, 'click', TIER_ALWAYS, 'prompted'],
    [true, 'other-service', 'click', TIER_ALWAYS, 'prompted'],
    [true, COMPUTER_MCP_ID, 'install_ffmpeg', TIER_ALWAYS, 'prompted'],
    [true, COMPUTER_MCP_ID, 'click', TIER_DENY, 'blocked'],
  ]) {
    let prompts = 0, executions = 0;
    const a = agent({ text: 'Done' }); a.config[COMPUTER_DIRECT_CONFIG] = direct;
    a.confirm = async () => { prompts++; return false; };
    a.mcp.tierFor = () => ({ tier, label: tool }); a.mcp.needsApproval = () => true;
    a.mcp.approvalDetail = () => 'Fixture action';
    a.mcp.callToolResult = async () => { executions++; return { text: 'Done' }; };
    await a.runMcpToolCall({ ...call, function: { name: `mcp__${server}__${tool}`, arguments: '{}' } });
    assert.equal(prompts, expected === 'prompted' ? 1 : 0);
    assert.equal(executions, expected === 'executed' ? 1 : 0);
  }
});

test('native observations preserve the structured snapshot and control token for the model', async () => {
  const result = { text: '[0] Edit Text Editor', raw: { structuredContent: {
    snapshot_id: 'fixture-snapshot', elements: [{ index: 0, role: 'Edit', label: 'Text Editor', element_token: 'fixture-current-token' }],
  } } };
  const nativeCall = { ...call, function: { ...call.function, name: `mcp__${COMPUTER_MCP_ID}__get_window_state` } };
  const text = await agent(result, false).runMcpToolCall(nativeCall);
  assert.match(text, /fixture-snapshot/); assert.match(text, /fixture-current-token/);
  assert.match(text, /Text Editor/);
  assert.doesNotMatch(await agent({ ...result, isError: true }).runMcpToolCall(nativeCall), /fixture-current-token/);
});

test('native target metadata is bounded and does not copy unrelated screenshot data', () => {
  const make = elements => ({ raw: { structuredContent: { snapshot_id: 'current', elements, screenshot: 'private-image-payload' } } });
  const controls = Array.from({ length: COMPUTER_TARGET_LIMIT + 1 }, (_, index) => ({ index, label: `Fixture ${index}`, element_token: `token-${index}` }));
  const text = computerObservationMetadata(make(controls));
  assert.match(text, /"omitted_targets":1/); assert.doesNotMatch(text, /private-image-payload/);
  const oversized = computerObservationMetadata(make([{ element_token: 'x'.repeat(COMPUTER_TARGET_MAX_BYTES) }]));
  assert.ok(Buffer.byteLength(oversized) <= COMPUTER_TARGET_MAX_BYTES); assert.match(oversized, /Targets omitted/);
});

test('final model reply retains complete native identifiers with multibyte trees and small budgets', async () => {
  const snapshot = 'fixture-fresh-snapshot';
  const controls = Array.from({ length: COMPUTER_TARGET_LIMIT }, (_, index) => ({ index, label: '文'.repeat(100), element_token: `token-${index}-${'x'.repeat(60)}` }));
  for (const [maxToolChars, contextWindow] of [[65536, 1000000], [2048, 1000000], [65536, 32768]]) {
    const mcp = { summaries: () => [], alwaysOnIds: () => [], specs: () => [], findTool: () => ({}), needsApproval: () => false,
      callToolResult: async () => ({ text: 'Readable 文 tree\n'.repeat(7000), raw: { structuredContent: { snapshot_id: snapshot, elements: controls } } }) };
    const a = new Agent({ client: {}, mcp, autoProject: false, config: { model: 'fixture', tools: true, autoApprove: true, maxToolChars, contextWindow, maxTokens: 1000, maxToolSteps: 3, memoryConsolidation: false }, print: () => {}, write: () => {} });
    let round = 0;
    let reply;
    a.streamTurn = async () => {
      if (round) reply = a.messages.find(message => message.tool_call_id === 'large-native')?.content;
      return { content: round ? 'Done' : '', model: 'fixture', toolCalls: round++ ? [] : [{ id: 'large-native', type: 'function', function: { name: `mcp__${COMPUTER_MCP_ID}__get_window_state`, arguments: '{}' } }] };
    };
    await a.send('Read the fixture desktop');
    assert.ok(Buffer.byteLength(reply) <= maxToolChars);
    assert.match(reply, /Native target metadata/);
    const proof = JSON.parse(reply.split('\n').find(line => line.startsWith('{"snapshot_id"')));
    assert.equal(proof.snapshot_id, snapshot);
    assert.equal(proof.targets[0].element_token, controls[0].element_token);
    assert.ok(proof.omitted_targets > 0);
    assert.equal(proof.targets.length + proof.omitted_targets, controls.length);
  }
});
test('screenshots survive the real MCP client result envelope', async () => {
  const a = agent({ text: 'snapshot [image]', isError: false, raw: { content: [IMAGE] } });
  await a.runMcpToolCall(call);
  assert.equal(a.mcpImagesThisTurn, 1);
});
test('MCP screenshots reach the model while tool replies stay text', async () => {
  const a = agent({ text: 'Current state', content: [{ type: 'text', text: 'Current state' }, IMAGE] });
  const result = await a.runMcpToolCall(call);
  assert.match(result, /Current state/); assert.match(result, /snapshot-1/);
  assert.equal(a.messages[0].content.at(-1).image_url.url, 'data:image/png;base64,aGVsbG8=');
  assert.doesNotMatch(result, /aGVsbG8/);
});
test('text-only models get an explicit visual limitation and keep the tree', async () => {
  const a = agent({ text: 'Save button', content: [IMAGE] }, false);
  assert.match(await a.runMcpToolCall(call), /text-only/);
  assert.equal(a.messages[0].content, 'Use my desktop');
});
test('unknown capabilities allow images and failed tools never attach them', async () => {
  const a = agent({ text: 'Failure', isError: true, content: [IMAGE] });
  assert.match(await a.runMcpToolCall(call), /^Error:/); assert.equal(a.mcpImagesThisTurn, 0);
  const b = agent({ text: 'Observed', content: [IMAGE] }, undefined);
  b.client.modelCapabilities.clear(); await b.runMcpToolCall(call);
  assert.equal(b.mcpImagesThisTurn, 1);
});
test('MCP image count, type and byte limits are enforced', async () => {
  const a = agent({ text: 'state', content: Array(MAX_MCP_IMAGES_PER_TURN + 1).fill(IMAGE) });
  assert.match(await a.runMcpToolCall(call), /limit/);
  assert.equal(a.mcpImagesThisTurn, MAX_MCP_IMAGES_PER_TURN);
  const b = agent({ text: 'state', content: [{ ...IMAGE, data: 'A'.repeat(Math.ceil(MAX_MCP_IMAGE_BYTES / 3) * 4 + 4) }, { ...IMAGE, mimeType: 'text/html' }] });
  assert.match(await b.runMcpToolCall(call), /unsupported|oversized/); assert.equal(b.mcpImagesThisTurn, 0);
});
test('recipient filtering preserves images in history for a later vision model', () => {
  const messages = [{ role: 'user', content: [{ type: 'text', text: 'Inspect' }, { type: 'image_url', image_url: { url: 'data:image/png;base64,aGVsbG8=' } }] }];
  const textOnly = messagesForModel(messages, false);
  assert.equal(textOnly[0].content.some(part => part.type === 'image_url'), false);
  assert.match(textOnly[0].content.at(-1).text, /text-only/);
  assert.equal(messages[0].content[1].type, 'image_url');
  assert.equal(messagesForModel(messages, true), messages);
});
test('vision-to-text-only tool model handoff never sends unsupported images', async t => {
  const nativeName = 'mcp__ankita-computer__get_window_state';
  const nativeCall = { id: 'observe', type: 'function', function: { name: nativeName, arguments: '{}' } };
  const makeClient = (id, vision) => ({ baseUrl: 'https://fixture.invalid', headers: () => ({}), modelCapabilities: new Map([[id, { vision }]]) });
  const client = makeClient('vision', true), textClient = makeClient('text-only', false);
  const mcp = { summaries: () => [], alwaysOnIds: () => [], specs: () => [], findTool: () => ({}), needsApproval: () => false,
    callToolResult: async () => ({ text: 'Observed', raw: { content: [IMAGE] } }) };
  const a = new Agent({ client, tool: { client: textClient, model: 'text-only' }, mcp,
    config: { model: 'vision', tools: true, autoApprove: true, contextWindow: 100000, maxToolSteps: 3, memoryConsolidation: false }, print: () => {}, write: () => {} });
  a.totalToolCalls = 0; a.requestStarted = Date.now(); a.ranThisTurn = []; a.repeatsThisTurn = new Map();
  const requests = []; const originalFetch = globalThis.fetch; t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = async (_, options) => {
    const body = JSON.parse(options.body);
    const images = body.messages.flatMap(message => Array.isArray(message.content) ? message.content : []).filter(part => part.type === 'image_url').length;
    requests.push({ model: body.model, images });
    if (body.model === 'text-only' && images) return new Response(JSON.stringify({ error: { message: 'images unsupported' } }), { status: 400 });
    return new Response(JSON.stringify({ choices: [{ message: requests.length === 1 ? { content: null, tool_calls: [nativeCall] } : { content: 'Done' }, finish_reason: requests.length === 1 ? 'tool_calls' : 'stop' }] }), { headers: { 'content-type': 'application/json' } });
  };
  await a.sendTurn('Inspect desktop');
  assert.deepEqual(requests.slice(0, 2), [{ model: 'vision', images: 0 }, { model: 'text-only', images: 0 }]);
});
test('native reads may repeat after successful actions while unchanged read loops still stop', async () => {
  const snapshot = 'mcp__ankita-computer__get_window_state';
  const action = 'mcp__ankita-computer__click';
  const mcp = { summaries: () => [], alwaysOnIds: () => [], specs: () => [], findTool: name => ({ tool: { annotations: { readOnlyHint: name === snapshot } } }),
    needsApproval: () => false, callToolResult: async () => ({ text: 'Observed updated state' }) };
  for (const [names, shouldStop] of [[[snapshot, action, snapshot, action, snapshot], false], [[snapshot, snapshot, snapshot], true]]) {
    const a = new Agent({ client: {}, mcp, config: { model: 'fixture', tools: true, autoApprove: true, maxToolSteps: 8, memoryConsolidation: false }, print: () => {}, write: () => {} });
    let round = 0;
    a.streamTurn = async () => ({ content: round < names.length ? '' : 'Done', model: 'fixture', toolCalls: round < names.length ? [{ id: `native-${round}`, function: { name: names[round++], arguments: '{"pid":1,"window_id":2}' } }] : [] });
    await a.send('Use the test desktop');
    assert.equal(Boolean(a.terminationReason), shouldStop);
  }
});
