import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const configDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-wireless-config-'));
process.env.CONFIG_DIR = configDir;

const wireless = await import('../../src/integrations/phone-wireless.mjs');
const core = await import('../../src/integrations/phone-control.mjs');
const { PhoneSession } = await import('../../tools/phone/session.mjs');
const phone = await import('../../tools/phone/phone.mjs');
const { MCP_FILE } = await import('../../src/core/config.mjs');

test.after(() => fs.rmSync(configDir, { recursive: true, force: true }));

const MDNS = [
  'List of discovered mdns services',
  'adb-9F2C1A-_adb-tls-connect._tcp.          192.168.1.42:5555',
  'adb-9F2C1A-_adb-tls-pairing._tcp.          192.168.1.42:37123',
].join('\n');

/** Fake adb: records every argv and answers per subcommand. */
function fakeAdb(answers = {}) {
  const calls = [];
  const run = async (command, args, options) => {
    calls.push({ command, args, input: options?.input ?? null });
    const key = args.join(' ');
    const answer = answers[key] ?? answers[args[0]];
    if (typeof answer === 'function') return answer(args, options);
    return answer || { code: 0, stdout: '', stderr: '' };
  };
  return { calls, run };
}

function session(adb, mcp = null) {
  return new PhoneSession({ mcp, mcpFile: MCP_FILE, exec: adb.run, exists: () => true, env: { ANDROID_HOME: path.join(os.tmpdir(), 'sdk') }, platform: 'win32' });
}

test('mDNS output parses into pairing and connect endpoints', () => {
  const services = wireless.parseMdnsServices(MDNS);
  assert.equal(services.length, 2);
  assert.deepEqual(services.map(s => s.kind), ['connect', 'pairing']);
  assert.equal(services[1].address, '192.168.1.42:37123');
  assert.equal(wireless.parseMdnsServices('').length, 0);
  assert.equal(wireless.parseMdnsServices('garbage line here').length, 0);
});

test('pairing and connect use different addresses and never guess between phones', () => {
  const services = wireless.parseMdnsServices(MDNS);
  assert.equal(wireless.pickService(services, 'pairing').address, '192.168.1.42:37123');
  assert.equal(wireless.pickService(services, 'connect').address, '192.168.1.42:5555');
  const two = [...services, ...wireless.parseMdnsServices('adb-OTHER-_adb-tls-pairing._tcp. 192.168.1.99:40000')];
  assert.equal(wireless.pickService(two, 'pairing'), null, 'two phones must not be guessed between');
});

test('adb is found in the SDK first, then on PATH', () => {
  const sdk = path.join('C:', 'android-sdk');
  const found = wireless.findAdb({ env: { ANDROID_HOME: sdk }, platform: 'win32', exists: () => true });
  assert.equal(found, path.join(sdk, 'platform-tools', 'adb.exe'));
  const missing = wireless.findAdb({ env: { ANDROID_HOME: sdk }, platform: 'win32', exists: () => false });
  assert.equal(missing, 'adb.exe', 'falls back to PATH (with the platform extension) rather than inventing a path');
  const linuxMissing = wireless.findAdb({ env: {}, platform: 'linux', exists: () => false });
  assert.equal(linuxMissing, 'adb');
  const local = wireless.findAdb({ env: { LOCALAPPDATA: 'C:\\Users\\x\\AppData\\Local' }, platform: 'win32', exists: () => true });
  assert.match(local, /platform-tools[\\/]adb\.exe$/);
});

test('pairing codes and addresses are validated before reaching adb', () => {
  assert.equal(wireless.requirePairingCode('123456'), '123456');
  assert.throws(() => wireless.requirePairingCode('12345'), /six digits/);
  assert.throws(() => wireless.requirePairingCode('1234567'), /six digits/);
  assert.throws(() => wireless.requirePairingCode('12ab56'), /six digits/);
  assert.equal(wireless.requireAddress('192.168.1.42:5555'), '192.168.1.42:5555');
  assert.throws(() => wireless.requireAddress('192.168.1.42'), /host:port/);
  assert.throws(() => wireless.requireAddress('$(rm -rf /)'), /host:port/);
});

test('wireless finds a phone waiting to pair', async () => {
  const adb = fakeAdb({ 'mdns services': { code: 0, stdout: MDNS, stderr: '' } });
  const s = session(adb);
  const out = await s.run({ action: 'wireless' }, {});
  assert.match(out, /192\.168\.1\.42:37123/);
  assert.match(out, /six-digit code/);
  assert.equal(s.wirelessAddress, '192.168.1.42:5555', 'the connect address is remembered for later reconnects');
});

test('wireless with nothing on the network explains what to do on the phone', async () => {
  const adb = fakeAdb({ 'mdns services': { code: 0, stdout: 'List of discovered mdns services', stderr: '' } });
  const out = await session(adb).run({ action: 'wireless' }, {});
  assert.match(out, /No phone is advertising wireless debugging/);
  assert.match(out, /Wireless debugging/);
});

test('pairing sends the code over stdin, never in the arguments', async () => {
  const adb = fakeAdb({
    'mdns services': { code: 0, stdout: MDNS, stderr: '' },
    pair: { code: 0, stdout: 'Successfully paired to 192.168.1.42:37123', stderr: '' },
    connect: { code: 0, stdout: 'connected to 192.168.1.42:5555', stderr: '' },
  });
  const s = session(adb);
  const out = await s.run({ action: 'wireless_pair', code: '482915' }, {});
  assert.match(out, /Paired and connected/);
  const pairCall = adb.calls.find(c => c.args[0] === 'pair');
  assert.equal(pairCall.args.length, 2, 'only `pair <address>` is passed as arguments');
  assert.ok(!pairCall.args.some(a => a.includes('482915')), 'the code must never be an argument');
  assert.equal(pairCall.input, '482915\n', 'the code goes over stdin');
});

test('a rejected code tells the assistant to ask for a fresh one', async () => {
  const adb = fakeAdb({
    'mdns services': { code: 0, stdout: MDNS, stderr: '' },
    pair: { code: 1, stdout: '', stderr: 'Failed: Wrong pairing code' },
  });
  const out = await session(adb).run({ action: 'wireless_pair', code: '000000' }, {});
  assert.match(out, /pairing code was rejected/i);
  assert.match(out, /read the new six-digit code/);
});

test('a malformed code is refused without touching adb', async () => {
  const adb = fakeAdb({});
  const out = await session(adb).run({ action: 'wireless_pair', code: 'abc' }, {});
  assert.match(out, /six digits/);
  assert.equal(adb.calls.length, 0);
});

test('pairing succeeds but connecting fails asks for a reconnect, never a port', async () => {
  const adb = fakeAdb({
    'mdns services': { code: 0, stdout: MDNS, stderr: '' },
    pair: { code: 0, stdout: 'Successfully paired to 192.168.1.42:37123', stderr: '' },
    connect: { code: 1, stdout: '', stderr: 'failed to connect to 192.168.1.42:5555' },
  });
  const out = await session(adb).run({ action: 'wireless_pair', code: '482915' }, {});
  assert.match(out, /Paired successfully/);
  assert.match(out, /did not accept the connection/);
  assert.match(out, /reconnect/i);
  assert.doesNotMatch(out, /IP address & port/);
});

test('wireless never remembers an address when several phones advertise connect', async () => {
  const mdns = [
    'List of discovered mdns services',
    'adb-A-_adb-tls-connect._tcp. 192.168.1.42:5555',
    'adb-B-_adb-tls-connect._tcp. 192.168.1.99:6666',
  ].join('\n');
  const adb = fakeAdb({ 'mdns services': { code: 0, stdout: mdns, stderr: '' } });
  const s = session(adb);
  const out = await s.run({ action: 'wireless' }, {});
  assert.match(out, /192\.168\.1\.42:5555/);
  assert.equal(s.wirelessAddress, null, 'two phones must not be guessed between');
});

test('pairing rescans and connects when the connect endpoint appears only after pairing', async () => {
  const pairingOnly = 'List of discovered mdns services\nadb-9F2C1A-_adb-tls-pairing._tcp. 192.168.1.42:37123';
  const both = `${pairingOnly}\nadb-9F2C1A-_adb-tls-connect._tcp. 192.168.1.42:46551`;
  let scans = 0;
  const adb = fakeAdb({
    'mdns services': () => ({ code: 0, stdout: ++scans === 1 ? pairingOnly : both, stderr: '' }),
    pair: { code: 0, stdout: 'Successfully paired', stderr: '' },
    connect: { code: 0, stdout: 'connected to 192.168.1.42:46551', stderr: '' },
  });
  const s = session(adb);
  const out = await s.run({ action: 'wireless_pair', code: '482915' }, {});
  assert.match(out, /Paired and connected/);
  assert.equal(scans, 2, 'a second scan finds the post-pair connect endpoint');
  const connect = adb.calls.find(c => c.args[0] === 'connect');
  assert.deepEqual(connect.args.slice(0, 2), ['connect', '192.168.1.42:46551']);
  assert.equal(s.wirelessAddress, '192.168.1.42:46551');
});

test('wireless_connect reuses the discovered address and reports failures clearly', async () => {
  const ok = fakeAdb({ connect: { code: 0, stdout: 'connected to 192.168.1.42:5555', stderr: '' } });
  const s = session(ok);
  s.wirelessAddress = '192.168.1.42:5555';
  assert.match(await s.run({ action: 'wireless_connect' }, {}), /Connected to 192\.168\.1\.42:5555/);

  const refused = fakeAdb({ connect: { code: 1, stdout: '', stderr: 'Connection refused' } });
  const out = await session(refused).run({ action: 'wireless_connect', address: '192.168.1.42:5555' }, {});
  assert.match(out, /Could not reach the phone/);
});

test('a dropped wireless phone is reconnected automatically before reporting', async () => {
  const listed = JSON.stringify({ devices: [{ id: '192.168.1.42:5555', platform: 'android', type: 'real' }] });
  let listingCount = 0;
  const mcp = {
    has: () => true,
    findTool: full => ({ record: {}, tool: { name: full } }),
    callToolResult: async full => {
      if (full.endsWith('mobile_list_available_devices')) {
        listingCount++;
        return { raw: { content: [{ type: 'text', text: listingCount === 1 ? JSON.stringify({ devices: [] }) : listed }] }, isError: false };
      }
      return { raw: { content: [{ type: 'text', text: 'ok' }] }, isError: false };
    },
  };
  const adb = fakeAdb({ connect: { code: 0, stdout: 'connected to 192.168.1.42:5555', stderr: '' } });
  const s = session(adb, mcp);
  s.wirelessAddress = '192.168.1.42:5555';
  const ctx = {};
  const out = await s.listDevices(ctx);
  assert.equal(adb.calls.filter(c => c.args[0] === 'connect').length, 1, 'one silent reconnect attempt');
  assert.match(out, /192\.168\.1\.42:5555/);
  assert.match(out, /reconnected .* automatically/);
});

test('no automatic reconnect when nothing was ever paired wirelessly', async () => {
  const mcp = { has: () => true, findTool: () => ({ record: {}, tool: {} }), callToolResult: async () => ({ raw: { content: [{ type: 'text', text: JSON.stringify({ devices: [] }) }] }, isError: false }) };
  const adb = fakeAdb({});
  const out = await session(adb, mcp).listDevices({});
  assert.equal(adb.calls.length, 0, 'USB-only users never pay for an adb call');
  assert.match(out, /No local phone/);
});

test('wireless actions never mutate the phone and never prompt', () => {
  for (const action of ['wireless', 'wireless_connect']) assert.equal(core.phoneReadOnly(action), true, action);
  assert.equal(core.phoneReadOnly('wireless_pair'), false, 'pairing changes what the phone trusts');
  // Even with no session connected, wireless setup must not trigger the connect prompt.
  for (const action of core.PHONE_WIRELESS_ACTIONS) assert.equal(phone.needsApproval({ action }, {}), false, action);
});

test('the pairing code is hidden from the approval preview', () => {
  const shown = phone.display({ action: 'wireless_pair', code: '482915' });
  assert.equal(shown.code, '[pairing code hidden]');
  assert.ok(!JSON.stringify(shown).includes('482915'));
});

test('wireless actions are part of the tool schema', () => {
  for (const action of core.PHONE_WIRELESS_ACTIONS) assert.ok(phone.parameters.properties.action.enum.includes(action), action);
  assert.ok(phone.parameters.properties.code, 'the schema must let the model pass the code it was told');
});
