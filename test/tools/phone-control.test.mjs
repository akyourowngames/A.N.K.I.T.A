import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

// CONFIG_DIR must be set before any module that reads it is imported.
const configDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-phone-config-'));
process.env.CONFIG_DIR = configDir;

const { PhoneSession, connectApprovalText } = await import('../../tools/phone/session.mjs');
const { phoneSessionFor } = await import('../../tools/phone/session.mjs');
const { Agent } = await import('../../src/core/agent.mjs');
const phone = await import('../../tools/phone/phone.mjs');
const { phoneScreenshotImage } = await import('../../tools/phone/screenshots.mjs');
const core = await import('../../src/integrations/phone-control.mjs');
const { McpStore } = await import('../../src/integrations/mcp-store.mjs');
const { MCP_FILE } = await import('../../src/core/config.mjs');
const { matchCategories } = await import('../../tools/find-tools.mjs');
const { CATEGORIES } = await import('../../tools/catalog.mjs');

test.after(() => fs.rmSync(configDir, { recursive: true, force: true }));

const ONE_DEVICE = JSON.stringify({ devices: [{ id: 'emulator-5554', platform: 'android', type: 'emulator', name: 'Pixel_7', version: '14' }] });
const TWO_DEVICES = JSON.stringify({ devices: [
  { id: 'emulator-5554', platform: 'android', type: 'emulator', name: 'Pixel_7' },
  { id: 'R58M12345', platform: 'android', type: 'real', name: 'Galaxy' },
] });

/** A fake McpManager with the same surface the phone session touches. */
function fakeManager({ devices = ONE_DEVICE, fail = null, tools = core.PHONE_MCP_TOOLS } = {}) {
  const calls = [];
  const servers = new Map();
  const manager = {
    calls,
    servers,
    summaries: () => [],
    has: id => servers.has(id),
    findTool: full => {
      const parsed = /^mcp__phone__(.+)$/.exec(full);
      if (!parsed || !servers.has('phone')) return null;
      return tools.includes(parsed[1]) ? { serverId: 'phone', toolName: parsed[1], record: servers.get('phone'), tool: { name: parsed[1] } } : null;
    },
    connect: async (record) => {
      if (fail) throw new Error(fail);
      servers.set('phone', { id: 'phone', tools: tools.map(name => ({ name })), record });
      return servers.get('phone');
    },
    disconnect: async () => { servers.delete('phone'); return true; },
    callToolResult: async (full, args) => {
      const name = /^mcp__phone__(.+)$/.exec(full)?.[1];
      calls.push({ name, args });
      if (name === 'mobile_list_available_devices') return { raw: { content: [{ type: 'text', text: devices }] }, isError: false };
      if (name === 'mobile_list_elements_on_screen') return { raw: { content: [{ type: 'text', text: '[1] Button text="OK"' }] }, isError: false };
      return { raw: { content: [{ type: 'text', text: `${name} ok` }] }, isError: false };
    },
  };
  return manager;
}

function session(t, options) {
  const cwd = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-phone-'));
  t.after(() => fs.rmSync(cwd, { recursive: true, force: true }));
  const mcp = fakeManager(options);
  return { s: new PhoneSession({ mcp, mcpFile: MCP_FILE }), mcp, ctx: { cwd, workspacePath: cwd, mcp } };
}

const PNG_1PX = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jZQAAAABJRU5ErkJggg==', 'base64');
const AGENT_CONFIG = { tools: true, model: 'fixture-model', contextWindow: 131072, historyMessages: 40, maxTokens: 1000, memoryConsolidation: false, autoApprove: true };

/** Makes the fake bridge write a real PNG to the temp path the session asks for. */
function stubScreenshots(mcp, bytes = PNG_1PX) {
  const save = mcp.callToolResult;
  mcp.callToolResult = async (full, args) => {
    if (full.endsWith('mobile_save_screenshot')) { fs.writeFileSync(args.saveTo, bytes); return { raw: { content: [{ type: 'text', text: 'Screenshot saved' }] }, isError: false }; }
    return save(full, args);
  };
}

test('every curated action maps to a tool inside the allowed ceiling', () => {
  // A tool mapped but missing from PHONE_MCP_TOOLS is filtered out by the MCP
  // manager, so the action would fail on a live phone. Catch that here.
  const session = { device: 'd', nextScreenshotPath: () => 'x.png' };
  const sample = {
    tap: { ref: '@e1' }, double_tap: { ref: '@e1' }, long_press: { ref: '@e1' }, swipe: { direction: 'up' },
    type: { text: 'x' }, button: { button: 'HOME' }, open: { url: 'https://example.com' },
    launch: { package: 'com.x' }, terminate: { package: 'com.x' }, install: { path: 'a.apk' },
    uninstall: { package: 'com.x' }, clear_data: { package: 'com.x' }, set_orientation: { orientation: 'portrait' },
    crash: { id: '1' }, batch: { steps: [{ name: 'mobile_press_button', arguments: { button: 'HOME' } }] },
    stop_recording: {}, start_recording: {},
  };
  for (const [action, args] of Object.entries(sample)) {
    const mapped = core.PHONE_ACTIONS[action](args, session);
    assert.ok(core.PHONE_MCP_TOOLS.includes(mapped.tool), `${action} -> ${mapped.tool} is outside the allowed ceiling`);
  }
  for (const [action, build] of Object.entries(core.PHONE_ACTIONS)) {
    if (sample[action] || ['devices', 'use', 'see', 'screenshot', 'apps', 'foreground', 'orientation', 'size', 'fold', 'clipboard', 'location', 'logs', 'crashes'].includes(action)) continue;
    assert.ok(core.PHONE_MCP_TOOLS.includes(build({}, session).tool), `${action} maps outside the ceiling`);
  }
});

test('the raw escape hatch can only reach allow-listed tools', () => {
  const session = { device: 'd' };
  for (const tool of core.PHONE_MCP_TOOLS) assert.ok(core.rawCall({ tool }, session).tool === tool);
  assert.ok(core.rawCall({ tool: 'mobile_login_to_cloud_provider' }, session).error);
});

test('the host turns a phone screenshot receipt into an attached image and text', async (t) => {
  const { ToolHost } = await import('../../src/core/tool-host.mjs');
  const { phoneSessionFor } = await import('../../tools/phone/session.mjs');
  const { s, mcp, ctx } = session(t);
  const pngBytes = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00, 0x00]);
  const save = mcp.callToolResult;
  mcp.callToolResult = async (full, args) => {
    if (full.endsWith('mobile_save_screenshot')) { fs.writeFileSync(args.saveTo, pngBytes); return { raw: { content: [{ type: 'text', text: 'Screenshot saved' }] }, isError: false }; }
    return save(full, args);
  };
  phoneSessionFor(mcp); // attach the session the tool will look up
  await s.run({ action: 'devices' }, ctx); // connect before the host call so no approval gate is involved
  const host = new ToolHost({ context: { ...ctx, config: {} }, authorize: () => assert.fail('a connected screenshot must not ask for approval') });
  const result = await host.execute({ id: 'shot', name: 'phone', arguments: { action: 'screenshot' } }, { resultMode: 'mcp' });
  const image = result.content.find(part => part.type === 'image');
  assert.ok(image, 'the screenshot must be attached as an image part');
  assert.equal(image.mimeType, 'image/png');
  assert.ok(result.content.some(part => part.type === 'text' && part.text.includes('phone_screenshot')));
});

test('the phone family is discoverable and its keywords do not hijack unrelated queries', () => {
  const ids = CATEGORIES.map(c => c.id);
  assert.ok(ids.includes('phone'));
  assert.deepEqual(matchCategories('control my android phone'), ['phone']);
  assert.deepEqual(matchCategories('take a phone screenshot'), ['phone']);
  // "device" belongs to phone, but a browser-only query must not pull it in.
  assert.equal(matchCategories('browse a website').includes('phone'), false);
});

test('connect writes a hidden, manual-start record bound to the mobile-mcp command', async (t) => {
  const { s, ctx } = session(t);
  const out = await s.run({ action: 'devices' }, ctx);
  assert.match(out, /emulator-5554/);
  const record = new McpStore(MCP_FILE).load().find('phone');
  assert.equal(record.hidden, true, 'the phone bridge must stay out of the user managed MCP list');
  assert.equal(record.manualStart, true, 'reconcile must not spawn a phone bridge on its own');
  assert.equal(record.command, core.PHONE_MCP_COMMAND);
  assert.deepEqual(record.args, [...core.PHONE_MCP_ARGS]);
  assert.deepEqual(record.allowedTools, [...core.PHONE_MCP_TOOLS]);
  assert.equal(record.env.MOBILEMCP_DISABLE_TELEMETRY, '1');
  assert.equal(new McpStore(MCP_FILE).load().isApproved(record), true);
});

test('the pinned package version is what the launch command actually asks for', () => {
  assert.match(core.PHONE_PACKAGE_SPEC, /^@mobilenext\/mobile-mcp@\d+\.\d+\.\d+$/);
  assert.ok(core.PHONE_MCP_ARGS.includes(core.PHONE_PACKAGE_SPEC), 'an unpinned @latest would change the tool ceiling silently');
});

test('one device is selected automatically; several require an explicit use', async (t) => {
  const { s, ctx } = session(t, { devices: TWO_DEVICES });
  const out = await s.run({ action: 'devices' }, ctx);
  assert.match(out, /Available phones/);
  assert.match(out, /R58M12345/);
  assert.equal(s.device, null);
  // A non-listing action with several phones reports the choice instead of guessing.
  const tap = await s.run({ action: 'see' }, ctx);
  assert.match(tap, /Several phones are available/);
  assert.match(await s.run({ action: 'use', device: 'R58M12345' }, ctx), /Active phone: R58M12345/);
  assert.match(await s.run({ action: 'see' }, ctx), /mobile_list_elements_on_screen|Button/);
});

test('use refuses a device id that was never listed', async (t) => {
  const { s, ctx } = session(t);
  await s.run({ action: 'devices' }, ctx);
  const before = s.device;
  const out = await s.run({ action: 'use', device: 'invented-9999' }, ctx);
  assert.match(out, /^Error:/);
  assert.match(out, /was not in the last device list/);
  assert.equal(s.device, before, 'a rejected id must not change the active device');
});

test('see and tap act on the selected device with server-issued refs', async (t) => {
  const { s, mcp, ctx } = session(t);
  await s.run({ action: 'devices' }, ctx);
  await s.run({ action: 'see' }, ctx);
  const tap = await s.run({ action: 'tap', ref: '@e5' }, ctx);
  assert.equal(tap, 'mobile_click_on_screen_at_coordinates ok');
  const clicked = mcp.calls.find(c => c.name === 'mobile_click_on_screen_at_coordinates');
  assert.deepEqual(clicked.args, { device: 'emulator-5554', ref: '@e5' });
});

test('tap without a ref or coordinates is refused before any device round-trip', async (t) => {
  const { s, mcp, ctx } = session(t);
  await s.run({ action: 'devices' }, ctx);
  const before = mcp.calls.length;
  const out = await s.run({ action: 'tap' }, ctx);
  assert.match(out, /^Error:/);
  assert.equal(mcp.calls.length, before, 'a malformed tap must not reach the phone');
});

test('typed text, packages and urls are validated', async (t) => {
  const { s, ctx } = session(t);
  await s.run({ action: 'devices' }, ctx);
  assert.match(await s.run({ action: 'type' }, ctx), /text is required/);
  assert.match(await s.run({ action: 'launch', package: 'com.android chrome!' }, ctx), /package must be an app package id/);
  assert.match(await s.run({ action: 'open', url: 'javascript:alert(1)' }, ctx), /http/);
  assert.match(await s.run({ action: 'open', url: 'https://example.com/x' }, ctx), /mobile_open_url ok/);
});

test('obscure mobile-mcp tools stay out of raw unless deliberately allowed', async (t) => {
  const { s, ctx } = session(t);
  await s.run({ action: 'devices' }, ctx);
  assert.match(await s.run({ action: 'raw', tool: 'mobile_unknown_tool' }, ctx), /not in the phone tool/);
  assert.match(await s.run({ action: 'raw', tool: 'mobile_allocate_remote_device' }, ctx), /not available through the phone tool/);
  assert.match(await s.run({ action: 'raw', tool: 'mobile_fold_device', args: { posture: 'folded' } }, ctx), /mobile_fold_device ok/);
});

test('a screenshot is copied into the workspace and its receipt validates', async (t) => {
  const { s, mcp, ctx } = session(t);
  await s.run({ action: 'devices' }, ctx);
  // Intercept the bridge's temp write: a real PNG signature and two bytes.
  const pngBytes = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00, 0x00]);
  const save = mcp.callToolResult;
  mcp.callToolResult = async (full, args) => {
    if (full.endsWith('mobile_save_screenshot')) { fs.writeFileSync(args.saveTo, pngBytes); return { raw: { content: [{ type: 'text', text: 'Screenshot saved' }] }, isError: false }; }
    return save(full, args);
  };
  const receipt = JSON.parse(await s.run({ action: 'screenshot' }, ctx));
  assert.equal(receipt.type, 'phone_screenshot');
  assert.equal(receipt.bytes, pngBytes.length);
  assert.match(receipt.path, /^downloaded-images[\\/]phone-.*\.png$/);
  const image = phoneScreenshotImage(JSON.stringify(receipt), ctx);
  assert.ok(image, 'a real PNG inside the artifact folder must attach');
  assert.match(image.dataUrl, /^data:image\/png;base64,/);
});

test('a receipt pointing outside the artifact folder never attaches', (t) => {
  const { ctx } = session(t);
  const bad = { type: 'phone_screenshot', path: 'src/evil.png', bytes: 8 };
  assert.equal(phoneScreenshotImage(JSON.stringify(bad), ctx), null);
  const escaped = { type: 'phone_screenshot', path: '../evil.png', bytes: 8 };
  assert.equal(phoneScreenshotImage(JSON.stringify(escaped), ctx), null);
});

test('approval asks once to connect, then only for destructive actions', async (t) => {
  const { s, ctx } = session(t);
  assert.equal(phone.needsApproval({ action: 'see' }, ctx), true, 'the first call must ask to start the bridge');
  assert.match(phone.approval({ action: 'see' }, ctx), /Start phone control[\s\S]*@mobilenext\/mobile-mcp@/);
  await s.run({ action: 'devices' }, ctx);
  assert.equal(phone.needsApproval({ action: 'tap', ref: '@e1' }, ctx), false, 'after connect, a tap is not re-approved');
  assert.equal(phone.needsApproval({ action: 'uninstall' }, ctx), true);
  assert.equal(phone.needsApproval({ action: 'clear_data' }, ctx), true);
  assert.equal(phone.needsApproval({ action: 'raw', tool: 'mobile_clear_app_data' }, ctx), true);
  assert.equal(phone.needsApproval({ action: 'raw', tool: 'mobile_get_orientation' }, ctx), false);
});

test('read-only classification matches what changes the phone', () => {
  for (const action of ['devices', 'see', 'screenshot', 'logs', 'apps']) assert.equal(phone.readOnly({ action }), true, action);
  for (const action of ['tap', 'type', 'swipe', 'uninstall', 'clear_data', 'launch']) assert.equal(phone.readOnly({ action }), false, action);
  assert.equal(phone.readOnly({ action: 'clipboard' }), true, 'reading the clipboard is safe');
  assert.equal(phone.readOnly({ action: 'clipboard', text: 'copied' }), false, 'writing the clipboard changes the phone');
});

test('connect failures explain what is missing instead of hanging', async (t) => {
  const { s, ctx } = session(t, { fail: 'spawn npx ENOENT' });
  const out = await s.run({ action: 'devices' }, ctx);
  assert.match(out, /^Error:/);
  assert.match(out, /npx.*ENOENT/i);
  assert.equal(new McpStore(MCP_FILE).load().find('phone').enabled, false);
});

test('the approval text names the exact command and the iOS limitation', () => {
  const text = connectApprovalText();
  assert.match(text, /npx -y @mobilenext\/mobile-mcp@\d+\.\d+\.\d+/);
  assert.match(text, /iOS needs a Mac/);
});

test('display hides typed text from the approval preview', () => {
  const shown = phone.display({ action: 'type', text: 'my secret password' });
  assert.equal(shown.text, '[18 characters hidden]');
});

test('element refs are strictly @eN', () => {
  assert.equal(core.isElementRef('@e5'), true);
  assert.equal(core.isElementRef('e5'), false);
  assert.equal(core.isElementRef('@e'), false);
  assert.equal(core.isElementRef('@e5; rm -rf /'), false);
});

test('at most three phone screenshots attach per turn', async (t) => {
  const { ToolHost } = await import('../../src/core/tool-host.mjs');
  const { s, mcp, ctx } = session(t);
  phoneSessionFor(mcp);
  await s.run({ action: 'devices' }, ctx);
  stubScreenshots(mcp);
  const host = new ToolHost({ context: { ...ctx, config: {} }, authorize: () => true });
  const attached = [];
  for (let index = 0; index < 4; index++) {
    const result = await host.execute({ id: `shot-${index}`, name: 'phone', arguments: { action: 'screenshot' } }, { resultMode: 'mcp' });
    attached.push(result.content.some(part => part.type === 'image'));
  }
  assert.deepEqual(attached, [true, true, true, false], 'the fourth image must stay an artifact');
});

test('a receipt describing a file above the screenshot cap never attaches', (t) => {
  const { ctx } = session(t);
  const folder = path.join(ctx.workspacePath, 'downloaded-images');
  fs.mkdirSync(folder, { recursive: true });
  const file = path.join(folder, 'phone-big.png');
  fs.writeFileSync(file, PNG_1PX);
  const receipt = { type: 'phone_screenshot', path: 'downloaded-images/phone-big.png', bytes: core.PHONE_SCREENSHOT_MAX_BYTES + 1 };
  const realStat = fs.statSync;
  t.mock.method(fs, 'statSync', value => path.resolve(String(value)) === path.resolve(file)
    ? { isFile: () => true, size: core.PHONE_SCREENSHOT_MAX_BYTES + 1 }
    : realStat(value));
  assert.equal(phoneScreenshotImage(JSON.stringify(receipt), ctx), null);
});

test('a text-only model gets a note to use see instead of unsupported pixels', async (t) => {
  const { s, mcp, ctx } = session(t);
  phoneSessionFor(mcp);
  await s.run({ action: 'devices' }, ctx);
  stubScreenshots(mcp);
  const client = { modelCapabilities: new Map([['fixture-model', { vision: false }]]) };
  const agent = new Agent({ client, config: AGENT_CONFIG, workspacePath: ctx.workspacePath, mcp });
  agent.messages.push({ role: 'user', content: 'Take a screenshot' });
  const output = await agent.runToolCall({ id: 'shot', type: 'function', function: { name: 'phone', arguments: JSON.stringify({ action: 'screenshot' }) } });
  const receipt = JSON.parse(output);
  assert.equal(receipt.visionAttached, false);
  assert.match(receipt.note, /action="see"/);
  assert.equal(agent.messages.at(-1).content, 'Take a screenshot', 'no image part may be attached to the user message');
});

test('the phone description stays compact and keeps the critical safety rules', () => {
  const description = phone.description;
  assert.ok(description.length < 1000, `description is ${description.length} chars`);
  assert.match(description, /untrusted/);
  assert.match(description, /PIN/);
  assert.match(description, /action="wireless"/);
});
