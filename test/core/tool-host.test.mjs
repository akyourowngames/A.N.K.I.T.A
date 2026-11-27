import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { ToolHost } from '../../src/core/tool-host.mjs';
import { TIER_DENY } from '../../src/integrations/mcp-tiers.mjs';
import { COMPUTER_MCP_ID } from '../../src/integrations/computer-use.mjs';
import { CHROME_MCP_ID } from '../../src/integrations/browser-plugins.mjs';
import { MAX_MCP_IMAGES_PER_TOOL_RESULT } from '../../src/integrations/mcp-images.mjs';

const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-tool-host-'));
test.after(() => fs.rmSync(directory, { recursive: true, force: true }));
const context = { cwd: directory, workspacePath: directory, config: { memoryConsolidation: false }, readOnly: true };
const call = (name, args = {}) => ({ id: 'host-proof', name, arguments: args });
const text = result => result.content.filter(part => part.type === 'text').map(part => part.text).join('\n');

test('read-only host refuses mutation even with automatic approval', async () => {
  const host = new ToolHost({ context: { ...context, config: { autoApprove: true } } });
  const result = await host.execute(call('write_file', { path: 'denied.txt', content: 'never' }));
  assert.equal(result.isError, true);
  assert.match(text(result), /read-only/i);
  assert.equal(fs.existsSync(path.join(directory, 'denied.txt')), false);
});

test('real reads keep the host workspace and reject argument-based escape', async () => {
  fs.writeFileSync(path.join(directory, 'proof.txt'), 'host-owned bytes');
  const host = new ToolHost({ context });
  assert.match(text(await host.execute(call('read_file', { path: 'proof.txt', cwd: os.tmpdir() }))), /host-owned bytes/);
  const result = await host.execute(call('read_file', { path: '../outside.txt' }));
  assert.equal(result.isError, true);
  assert.match(text(result), /outside|escape|workspace/i);
});

test('a stopped call never reaches the MCP handler', async () => {
  let executed = 0;
  const controller = new AbortController(); controller.abort();
  const mcp = { findTool: () => ({}), needsApproval: () => false, callToolResult: () => { executed++; return { content: [] }; } };
  const host = new ToolHost({ context: { ...context, readOnly: false }, mcp });
  assert.equal((await host.execute(call('mcp__proof__read'), { signal: controller.signal })).isError, true);
  assert.equal(executed, 0);
});

test('explicit blocked MCP tier survives auto approval and direct desktop mode', async () => {
  let executed = 0;
  const mcp = { findTool: () => ({}), tierFor: () => ({ tier: TIER_DENY, label: 'proof' }), callToolResult: () => { executed++; } };
  const host = new ToolHost({ context: { ...context, readOnly: false, config: { autoApprove: true, computerUseDirect: true } }, mcp });
  assert.match(text(await host.execute(call('mcp__proof__read'))), /blocked/);
  assert.equal(executed, 0);
});

test('native MCP images and text remain native without API history or client', async () => {
  const content = [{ type: 'text', text: 'observed' }, { type: 'image', mimeType: 'image/png', data: 'aGVsbG8=' }];
  const mcp = { findTool: () => ({ tool: { annotations: { readOnlyHint: true } } }), needsApproval: () => false, callToolResult: async () => ({ raw: { content }, isError: false }) };
  const result = await new ToolHost({ context, mcp }).execute(call('mcp__proof__read'), { resultMode: 'mcp' });
  assert.deepEqual(result, { content, isError: false });
});

test('cancellation during approval cannot execute a newly approved mutation', async () => {
  const controller = new AbortController();
  let prompts = 0;
  const host = new ToolHost({ context: { ...context, readOnly: false }, authorize: async () => { prompts++; controller.abort(); return true; } });
  const result = await host.execute(call('write_file', { path: 'cancelled.txt', content: 'never' }), { signal: controller.signal });
  assert.equal(result.isError, true);
  assert.equal(fs.existsSync(path.join(directory, 'cancelled.txt')), false);
  assert.equal(prompts, 1);
});

test('Stop releases pending local and plugin approvals before a human responds', async () => {
  for (const name of ['write_file', 'mcp__proof__write']) {
    let entered, finishApproval, executions = 0;
    const waiting = new Promise(resolve => { entered = resolve; });
    const mcp = { findTool: () => ({}), needsApproval: () => true, approvalDetail: () => 'Fixture mutation',
      callToolResult: async () => { executions++; return { content: [] }; } };
    const host = new ToolHost({ context: { ...context, readOnly: false }, mcp,
      authorize: () => { entered(); return new Promise(resolve => { finishApproval = resolve; }); } });
    const work = host.execute(call(name, { path: 'pending-approval.txt', content: 'never' }));
    await waiting; await host.cancel();
    // Immediate task boundary: cancellation must settle independently of a pending human decision.
    const result = await Promise.race([work, new Promise(resolve => setImmediate(() => resolve(null)))]);
    finishApproval(true);
    assert.ok(result, 'Stop cannot wait for the approval dialog');
    assert.equal(result.isError, true); assert.equal(executions, 0);
    assert.equal(fs.existsSync(path.join(directory, 'pending-approval.txt')), false);
  }
});

test('native MCP output bounds untrusted text and omits malformed image blocks', async () => {
  const mcp = { findTool: () => ({ tool: { annotations: { readOnlyHint: true } } }), needsApproval: () => false,
    callToolResult: async () => ({ content: [{ type: 'text', text: 'x'.repeat(8000) }, { type: 'image', mimeType: 'image/png', data: '<unsafe>' }] }) };
  const result = await new ToolHost({ context: { ...context, config: { maxToolChars: 1024 } }, mcp }).execute(call('mcp__proof__read'));
  assert.ok(Buffer.byteLength(text(result)) <= 1024);
  assert.equal(result.content.filter(part => part.type === 'image').length, 0);
});

test('an explicit current approval setting takes priority over older config for local and MCP writes', async () => {
  let prompts = 0, executions = 0;
  const mcp = { findTool: () => ({}), needsApproval: () => true, approvalDetail: () => 'Fixture mutation', callToolResult: async () => { executions++; return { content: [] }; } };
  const host = new ToolHost({ context: { ...context, readOnly: false, autoApprove: false, config: { autoApprove: true } }, mcp,
    authorize: async () => { prompts++; return false; } });
  const result = await host.execute(call('write_file', { path: 'current-policy.txt', content: 'never' }));
  assert.equal(result.isError, true);
  assert.equal(fs.existsSync(path.join(directory, 'current-policy.txt')), false);
  const native = await host.execute(call('mcp__proof__write'));
  assert.equal(native.isError, true);
  assert.equal(executions, 0); assert.equal(prompts, 2, text(native));
});

test('a thrown native tool error is an MCP error result rather than a successful receipt', async () => {
  const mcp = { findTool: () => ({}), needsApproval: () => false, callToolResult: async () => { throw new Error('fixture transport disconnected'); } };
  const host = new ToolHost({ context: { ...context, readOnly: false }, mcp });
  const result = await host.execute(call('mcp__proof__read'));
  assert.equal(result.isError, true);
  assert.match(text(result), /fixture transport disconnected/);
});

test('native Core, Desktop and Plugins expose current admitted capabilities without cross-surface leakage', async () => {
  const tools = new Map([
    ['mcp__plugin__read', { name: 'read', inputSchema: { type: 'object' }, annotations: { readOnlyHint: true } }],
    ['mcp__plugin__blocked', { name: 'blocked', inputSchema: { type: 'object' } }],
    [`mcp__${COMPUTER_MCP_ID}__get_window_state`, { name: 'get_window_state', inputSchema: { type: 'object' }, annotations: { readOnlyHint: true } }],
    [`mcp__${CHROME_MCP_ID}__take_snapshot`, { name: 'take_snapshot', inputSchema: { type: 'object' } }],
  ]);
  const mcp = { specs: () => [...tools].map(([name, tool]) => ({ function: { name, description: name, parameters: tool.inputSchema } })),
    findTool: name => tools.has(name) ? { tool: tools.get(name), record: { tools: name.startsWith(`mcp__${CHROME_MCP_ID}__`)
      ? [tools.get(name), { name: 'list_pages' }] : [tools.get(name)] } } : null,
    tierFor: name => name.endsWith('__blocked') ? { tier: TIER_DENY } : null };
  const host = new ToolHost({ context: { ...context, readOnly: false }, mcp });
  const names = surface => host.specs(surface).map(tool => tool.name);
  assert.ok(names('core').includes('read_file'));
  assert.equal(names('core').includes('browser'), false);
  assert.deepEqual(names('plugins'), ['find_tools', 'mcp__plugin__read']);
  assert.ok(names('desktop').includes('browser'));
  assert.ok(names('desktop').includes(`mcp__${COMPUTER_MCP_ID}__get_window_state`));
  assert.equal(names('desktop').includes('read_file'), false);
  assert.equal(names('desktop').includes(`mcp__${CHROME_MCP_ID}__take_snapshot`), false);
  assert.equal((await host.execute(call('write_file', { path: 'cross-surface.txt', content: 'never' }), { surface: 'plugins' })).isError, true);
  assert.equal(fs.existsSync(path.join(directory, 'cross-surface.txt')), false);
  tools.delete('mcp__plugin__read');
  assert.deepEqual(names('plugins'), ['find_tools'], 'disconnected plugins leave only surface-scoped discovery');
});

test('native discovery advertises only interfaces callable on its own surface and cannot load desktop tools through Core', async () => {
  const nativeName = `mcp__${COMPUTER_MCP_ID}__get_window_state`;
  const tool = { name: 'get_window_state', inputSchema: { type: 'object' }, annotations: { readOnlyHint: true } };
  const state = {};
  const mcp = { specs: () => [{ function: { name: nativeName, description: 'Native window', parameters: tool.inputSchema } }],
    summaries: () => [{ id: COMPUTER_MCP_ID, tools: [tool.name], deferred: true }],
    findTool: name => name === nativeName ? { tool, record: { tools: [tool] } } : null };
  const host = new ToolHost({ context: { ...context, readOnly: false, state }, mcp });
  const core = await host.execute(call('find_tools', { query: COMPUTER_MCP_ID, scope: 'general' }), { surface: 'core' });
  assert.equal(text(core).includes(nativeName), false, 'Core cannot claim a Desktop-only interface is now callable');
  assert.equal(state.activatedTools?.has('mcp:' + COMPUTER_MCP_ID), false);
  const files = await host.execute(call('find_tools', { query: 'create_dir' }), { surface: 'core' });
  assert.match(text(files), /create_dir/);
  const desktop = await host.execute(call('find_tools', { query: COMPUTER_MCP_ID, scope: 'general' }), { surface: 'desktop' });
  assert.equal(desktop.isError, false); assert.ok(text(desktop).includes(nativeName));
});

test('native Core neither advertises nor executes global connection management while keeping workspace tools', async () => {
  const state = { activatedTools: new Set() };
  const host = new ToolHost({ context: { ...context, readOnly: false, state } });
  const published = host.specs('core').map(tool => tool.name);
  for (const name of ['mcp_manage', 'composio']) {
    assert.equal(published.includes(name), false, 'connection settings belong to the desktop owner');
    const result = await host.execute(call(name, { action: 'add' }), { surface: 'core' });
    assert.equal(result.isError, true);
    assert.match(text(result), /unavailable.*native surface/);
    await host.execute(call('find_tools', { query: name, scope: 'general' }), { surface: 'core' });
    assert.equal(state.activatedTools.has(name), false);
  }
  assert.ok(published.includes('write_file'));
  assert.ok(published.includes('run_command'));
});

test('native image limits apply per tool result, not across later screenshot checks', async () => {
  const image = { type: 'image', mimeType: 'image/png', data: 'aGVsbG8=' };
  let returnedImages = [image];
  const mcp = { findTool: () => ({ tool: { annotations: { readOnlyHint: true } } }), needsApproval: () => false,
    callToolResult: async () => ({ content: [{ type: 'text', text: 'fresh screenshot' }, ...returnedImages], isError: false }) };
  const host = new ToolHost({ context, mcp });
  for (let index = 0; index < MAX_MCP_IMAGES_PER_TOOL_RESULT + 2; index++) {
    const result = await host.execute(call('mcp__proof__read'));
    assert.equal(result.isError, false); assert.equal(result.content.filter(part => part.type === 'image').length, 1);
  }
  returnedImages = Array(MAX_MCP_IMAGES_PER_TOOL_RESULT + 1).fill(image);
  const limited = await host.execute(call('mcp__proof__read'));
  assert.equal(limited.content.filter(part => part.type === 'image').length, MAX_MCP_IMAGES_PER_TOOL_RESULT);
  assert.equal(limited.isError, true, 'omitted images in one oversized result are reported');
  assert.match(text(limited), /visual.*unavailable/i); assert.match(text(limited), /image.*limit/i);
  returnedImages = [{ ...image, data: '<invalid>' }];
  const malformed = await new ToolHost({ context: { ...context, config: { maxToolChars: 256 } }, mcp }).execute(call('mcp__proof__read'));
  assert.equal(malformed.isError, true); assert.match(text(malformed), /visual.*unavailable/i);
  assert.equal(malformed.content.filter(part => part.type === 'image').length, 0);
  assert.ok(Buffer.byteLength(text(malformed)) <= 256);
});

test('managed browser verification screenshots remain available after earlier MCP screenshots', async () => {
  const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aGXYAAAAASUVORK5CYII=', 'base64');
  const relative = 'downloaded-images/browser-1-11111111-1111-1111-1111-111111111111.png';
  fs.mkdirSync(path.dirname(path.join(directory, relative)), { recursive: true }); fs.writeFileSync(path.join(directory, relative), png);
  const mcp = { findTool: () => ({ tool: { annotations: { readOnlyHint: true } } }), needsApproval: () => false,
    callToolResult: async () => ({ content: [{ type: 'image', mimeType: 'image/png', data: png.toString('base64') }], isError: false }) };
  const browserManager = { run: async () => JSON.stringify({ type: 'browser_screenshot', path: relative, bytes: png.length }) };
  const host = new ToolHost({ context: { ...context, browserManager }, mcp });
  for (let index = 0; index < MAX_MCP_IMAGES_PER_TOOL_RESULT + 2; index++) assert.equal((await host.execute(call('mcp__proof__read'))).isError, false);
  const screenshot = await host.execute(call('browser', { action: 'screenshot' }));
  assert.equal(screenshot.content.filter(part => part.type === 'image').length, 1, 'the later verification call still returns its screenshot image');
  assert.equal(screenshot.isError, false);
});
