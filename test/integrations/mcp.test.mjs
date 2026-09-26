import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

const SANDBOX = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-mcp-'));
process.env.CONFIG_DIR = SANDBOX;
test.after(() => fs.rmSync(SANDBOX, { recursive: true, force: true }));

const {
  commandCandidates,
  serverEnv,
  resolveLaunch,
  formatToolResult,
  toolResultText,
  McpClient,
  LATEST_PROTOCOL,
} = await import('../../src/integrations/mcp-client.mjs');
const {
  McpManager,
  toOpenAiSpec,
  needsApprovalFor,
  parseToolName,
  toolFullName,
  slug,
} = await import('../../src/integrations/mcp-manager.mjs');
const { Agent } = await import('../../src/core/agent.mjs');
const { specs, coreSpecs } = await import('../../tools/index.mjs');

/* ----------------------- is the fixture runnable here? ------------------ */
const fixturePath = path.join(process.cwd(), 'scripts', 'fixtures', 'mcp_fixture.py');
const probe = spawnSync('python', ['-c', 'import mcp.server.fastmcp'], { windowsHide: true, stdio: 'ignore' });
const HAVE_FIXTURE = probe.status === 0 && fs.existsSync(fixturePath);
const skip = HAVE_FIXTURE ? false : 'python + mcp package not available';

/* --------------------------- pure client bits --------------------------- */

test('command candidates handle the Windows shim problem', () => {
  const c = commandCandidates('npx');
  if (process.platform === 'win32') {
    // npx.cmd cannot be spawned at all (Node refuses a .cmd without a shell,
    // CVE-2024-27980), and a shell would mean interpolating package names
    // from a registry into a command line. So we run the script it wraps.
    assert.equal(c.length, 1);
    assert.equal(c[0].command, process.execPath, 'runs under the same node');
    assert.equal(c[0].args.length, 1, 'prepends the cli script');
    assert.match(c[0].args[0].replace(/\\/g, '/'), /npm\/bin\/npx-cli\.js$/);
    assert.doesNotMatch(c[0].command, /\.cmd$/i, 'never a batch shim');
  } else {
    assert.deepEqual(c, [{ command: 'npx', args: [] }]);
  }

  // An explicit .exe is left alone on every platform.
  assert.deepEqual(commandCandidates('python.exe'), [{ command: 'python.exe', args: [] }]);
  assert.deepEqual(commandCandidates(''), []);

  // A .cmd we cannot resolve is reported, not attempted - spawning one throws.
  const batch = commandCandidates('some-tool.cmd');
  assert.equal(batch.length, 1);
  assert.match(batch[0].problem || '', /batch shim/);
  assert.match(batch[0].problem || '', /command shell/);
});

test('a cached npx package is launched directly so no console window opens', () => {
  const resolved = resolveLaunch('npx', ['-y', 'some-package@1.0.0']);
  if (process.platform === 'win32' && /_npx/.test(resolved.command)) {
    assert.notEqual(resolved.command, 'npx', 'never shells out to npx on Windows');
    assert.match(resolved.args[0], /_npx[\\/].*\.(js|cjs|mjs)$/i, 'runs the cached entry script with node');
    assert.equal(resolved.args.includes('-y'), false, 'npx flags are dropped');
  }
  // Anything that is not an npx launch is left exactly as configured.
  assert.deepEqual(resolveLaunch('uvx', ['some-uninstalled-tool']), { command: 'uvx', args: ['some-uninstalled-tool'] });
  assert.deepEqual(resolveLaunch('node', ['server.js']), { command: 'node', args: ['server.js'] });
});

test('a full Windows path to npx is still launched without a shell', () => {
  const full = 'C:\\Program Files\\nodejs\\npx.cmd';
  if (process.platform === 'win32') {
    // Server configs often carry the absolute shim path (the Playwright reload
    // failure). Basename matching must rewrite it to node + npx-cli.js instead
    // of reporting an unspawnable batch shim.
    const c = commandCandidates(full);
    assert.equal(c.length, 1);
    assert.equal(c[0].command, process.execPath, 'runs under the same node');
    assert.match(c[0].args[0].replace(/\\/g, '/'), /npm\/bin\/npx-cli\.js$/);
    assert.equal(c[0].problem, undefined, 'no batch-shim complaint');
    // An uncached package keeps the original command; candidates handle it.
    const passthrough = resolveLaunch(full, ['-y', 'some-package-that-is-not-cached-xyz']);
    assert.equal(passthrough.command, full);
    assert.deepEqual(passthrough.args, ['-y', 'some-package-that-is-not-cached-xyz']);
  } else {
    assert.deepEqual(commandCandidates(full), [{ command: full, args: [] }]);
  }
});

test('a full path to uvx keeps its command when the tool is not cached', () => {
  const full = 'C:\\tools\\uv\\uvx.exe';
  const resolved = resolveLaunch(full, ['some-uninstalled-tool']);
  assert.equal(resolved.command, full, 'the configured path must survive, not become bare uvx');
  assert.deepEqual(resolved.args, ['some-uninstalled-tool']);
});

test('a cached uvx tool is launched without the uvx console intermediary', () => {
  const resolved = resolveLaunch('uvx', ['mcp-server-time']);
  if (process.platform === 'win32' && /uv[\\/]cache/.test(resolved.command)) {
    // uvx is `uv tool run`: it always allocates a console. Running the cached
    // entry point directly (through python rather than the .exe, which would
    // also draw a console) is what keeps the window from appearing.
    assert.doesNotMatch(resolved.command, /\buvx?\.exe$/i, 'never spawns uvx/uv itself');
    assert.ok(/\.(exe|cmd)$/i.test(resolved.command), 'runs a concrete cached launcher');
    assert.equal(resolved.args.includes('mcp-server-time'), false, 'the package spec is consumed');
  }
});

  test('spawned servers get a stripped environment, not the whole process', () => {
  const previous = process.env.SECRET_THING;
  process.env.SECRET_THING = 'super-secret-value';
  const previousAppData = process.env.APPDATA, previousLocal = process.env.LOCALAPPDATA;
  process.env.APPDATA = 'C:\\fake-appdata'; process.env.LOCALAPPDATA = 'C:\\fake-local';
  try {
    const env = serverEnv({ MCP_FIXTURE_LOG: 'x' });
    assert.equal(env.SECRET_THING, undefined, 'secrets must not be inherited');
    assert.equal(env.MCP_FIXTURE_LOG, 'x', 'an explicit server env is applied');
    assert.equal(env.PATH, process.env.PATH, 'PATH is kept');
    assert.equal(env.APPDATA, 'C:\\fake-appdata', 'npm/npx cache locations reach npx-spawned servers');
    assert.equal(env.LOCALAPPDATA, 'C:\\fake-local', 'npm/npx cache locations reach npx-spawned servers');
    assert.equal(env.CI, '1', 'MCP servers run as non-interactive background processes');
    assert.equal(env.NO_COLOR, '1', 'server output is not a terminal UI');
  } finally {
    if (previous === undefined) delete process.env.SECRET_THING;
    else process.env.SECRET_THING = previous;
    if (previousAppData === undefined) delete process.env.APPDATA;
    else process.env.APPDATA = previousAppData;
    if (previousLocal === undefined) delete process.env.LOCALAPPDATA;
    else process.env.LOCALAPPDATA = previousLocal;
  }
});

test('namespacing round-trips even when the tool name contains the delimiter', () => {
  assert.deepEqual(parseToolName(toolFullName('fixture', 'echo')), { serverId: 'fixture', toolName: 'echo' });
  assert.deepEqual(parseToolName(toolFullName('fixture', 'my__tool')), { serverId: 'fixture', toolName: 'my__tool' });
  assert.equal(parseToolName('read_file'), null);
  assert.equal(parseToolName('mcp__onlyone'), null);
  assert.equal(slug('My Server!'), 'my-server');
});

test('a server result becomes Error: when the server flags it', () => {
  assert.equal(formatToolResult({ text: 'all good', isError: false }), 'all good');
  assert.equal(formatToolResult({ text: 'boom', isError: true }), 'Error: boom');
  assert.equal(formatToolResult({ text: '', isError: true }), 'Error: (empty result)');

  // Some servers head their error body with a markdown heading. Prefixing that
  // naively yields "Error: ### Error\nError: ...", which reads as two failures.
  const playwright = { text: '### Error\nError: "input#search" does not match any elements.', isError: true };
  assert.equal(formatToolResult(playwright), 'Error: "input#search" does not match any elements.');
  assert.equal(formatToolResult({ text: '### Error\nsomething broke', isError: true }), 'Error: something broke');
  // A heading is only stripped when it is actually an error heading.
  assert.equal(formatToolResult({ text: '### Results\nall fine', isError: false }), '### Results\nall fine');
  assert.equal(toolResultText({ content: [{ type: 'text', text: 'a' }, { type: 'text', text: 'b' }] }), 'a\nb');
  assert.equal(toolResultText({ content: [{ type: 'image' }] }), '[image]');
  assert.equal(toolResultText(null), '(no result)');
});

test('the schema sent to the model is the server schema, verbatim', () => {
  const fromServer = {
    name: 'do_thing',
    description: 'the server wrote this',
    inputSchema: { type: 'object', properties: { a: { type: 'string' } }, required: ['a'] },
  };
  const spec = toOpenAiSpec('srv', fromServer);
  assert.equal(spec.type, 'function');
  assert.equal(spec.function.name, 'mcp__srv__do_thing');
  assert.equal(spec.function.description, 'the server wrote this');
  assert.deepEqual(spec.function.parameters, fromServer.inputSchema, 'never rewritten or trimmed');
});

test('approval follows the hints conservatively', () => {
  assert.equal(needsApprovalFor({ annotations: { readOnlyHint: true } }), false);
  assert.equal(needsApprovalFor({ annotations: { destructiveHint: true } }), true);
  assert.equal(needsApprovalFor({ annotations: {} }), true, 'unset means ask');
  assert.equal(needsApprovalFor({}), true);
  assert.equal(needsApprovalFor(undefined), true);
});

/* ------------------------- manager, no server needed -------------------- */

test('the manager tracks connections and disconnects cleanly', async () => {
  const mcp = new McpManager();
  assert.deepEqual(mcp.connectedIds, []);
  assert.equal(mcp.findTool('mcp__nope__x'), null);
  assert.equal(mcp.needsApproval('mcp__nope__x'), false);
  assert.deepEqual(mcp.specs(), []);
  assert.equal(await mcp.disconnect('nope'), false);
  assert.deepEqual(await mcp.closeAll(), []);
});

test('an unsupported transport is refused rather than silently ignored', async () => {
  const mcp = new McpManager();
  await assert.rejects(mcp.connect({ id: 'x', command: 'python', transport: 'websocket' }), /not supported/);
});

test('a server that exits after connecting stops being reported as connected', async () => {
  // Minimal JSON-RPC stdio server: answers initialize + tools/list, then dies.
  // No fixture dependency so this runs everywhere node runs.
  const server = [
    "const rl = require('readline').createInterface({ input: process.stdin });",
    "rl.on('line', line => {",
    "  let m; try { m = JSON.parse(line); } catch { return; }",
    "  if (m.method === 'initialize') process.stdout.write(JSON.stringify({ jsonrpc: '2.0', id: m.id, result: { protocolVersion: '2025-11-25', serverInfo: { name: 'dying', version: '0' } } }) + '\\n');",
    "  else if (m.method === 'notifications/initialized') setTimeout(() => process.exit(0), 200);",
    "  else if (m.id !== undefined) process.stdout.write(JSON.stringify({ jsonrpc: '2.0', id: m.id, result: {} }) + '\\n');",
    "});",
  ].join('\n');
  const mcp = new McpManager();
  await mcp.connect({ id: 'dying', command: process.execPath, args: ['-e', server] });
  assert.equal(mcp.has('dying'), true);
  const deadline = Date.now() + 5000;
  while (mcp.has('dying') && Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, 50));
  assert.equal(mcp.has('dying'), false, 'an exited server is pruned, not reported ready');
  await mcp.closeAll();
});

/* ---------------------------- against the fixture ----------------------- */

test('the client speaks the real protocol', { skip }, async () => {
  const log = path.join(SANDBOX, 'calls.jsonl');
  const client = new McpClient({ id: 'fx', command: 'python', args: [fixturePath], env: { MCP_FIXTURE_LOG: log } });
  await client.connect();
  try {
    assert.ok(client.serverInfo?.name, 'got serverInfo from initialize');
    assert.equal(typeof client.protocolVersion, 'string');
    assert.equal(client.tools.length, 6, 'all fixture tools listed');

    const names = client.tools.map((t) => t.name).sort();
    assert.deepEqual(names, ['big_schema', 'boom', 'count', 'echo', 'slow', 'write_note']);

    const echo = client.tools.find((t) => t.name === 'echo');
    assert.equal(echo.annotations.readOnlyHint, true, 'annotations survive the trip');
    assert.deepEqual(Object.keys(echo.inputSchema.properties), ['text']);

    assert.equal((await client.callTool('echo', { text: 'hi' })).text, 'echo: hi');

    // A tool that raises comes back in-band, flagged, with no JSON-RPC error.
    const bad = await client.callTool('boom', { reason: 'nope' });
    assert.equal(bad.isError, true, 'the server flagged the failure');
    assert.match(bad.text, /expected failure|nope/);
    assert.equal(formatToolResult(bad).startsWith('Error:'), true, 'and we surface it as one');
  } finally {
    await client.close();
  }
});

test('the server received exactly what we sent', { skip }, async () => {
  const log = path.join(SANDBOX, 'args.jsonl');
  const client = new McpClient({ id: 'fx', command: 'python', args: [fixturePath], env: { MCP_FIXTURE_LOG: log } });
  await client.connect();
  try {
    await client.callTool('echo', { text: 'verbatim check' });
    const recorded = JSON.parse(fs.readFileSync(log, 'utf8').trim().split('\n').at(-1));
    assert.deepEqual(recorded.args, { text: 'verbatim check' }, 'no rewriting on the way out');
  } finally {
    await client.close();
  }
});

test('a hung server times out instead of hanging the session', { skip }, async () => {
  const client = new McpClient({
    id: 'fx',
    command: 'python',
    args: [fixturePath],
    requestTimeoutMs: 1500,
    initTimeoutMs: 30000,
  });
  await client.connect();
  try {
    await assert.rejects(client.callTool('slow', { seconds: 30 }), /timed out after 1500ms/);
  } finally {
    await client.close();
  }
});

test('a bad command fails with a useful message rather than hanging', async () => {
  const client = new McpClient({ id: 'nope', command: 'definitely-not-a-real-binary-xyz', initTimeoutMs: 5000 });
  await assert.rejects(client.connect(), /could not start the MCP server/);
});

/* ------------------- the architecture correction, asserted -------------- */

test('two Agents share one connection - no respawn per Agent', { skip }, async (t) => {
  const log = path.join(SANDBOX, 'reuse.jsonl');
  const mcp = new McpManager();
  await mcp.connect({
    id: 'fx',
    command: 'python',
    args: [fixturePath],
    env: { MCP_FIXTURE_LOG: log },
  });
  t.after(() => mcp.closeAll());

  const record = mcp.servers.get('fx');
  const agentA = new Agent({ client: {}, config: { tools: true }, mcp });
  const agentB = new Agent({ client: {}, config: { tools: true }, deferTools: false, mcp });

  // Both see the same live connection object, not copies.
  assert.equal(mcp.servers.get('fx'), record);

  // Call through the manager from each "agent" and watch the server-side
  // counter continue: a fresh process would restart at 1.
  const first = await mcp.callTool('mcp__fx__count');
  const second = await mcp.callTool('mcp__fx__count');
  assert.equal(first, 'count=1');
  assert.equal(second, 'count=2', 'the same server process answered both');

  // And both agents offer the tools, including the one that sends everything.
  for (const agent of [agentA, agentB]) {
    assert.ok(agent.currentSpecs().some((s) => s.function.name === 'mcp__fx__echo'), 'MCP offered');
  }
  assert.equal(agentB.currentSpecs().length, specs.length - 1 + 6, 'worker: non-REPL static + all mcp');
  assert.equal(agentA.currentSpecs().length, coreSpecs.length - 1 + 6, 'agent: non-REPL core + all mcp');
});

test('MCP specs reach a deferTools:false worker - correction #2', { skip }, async (t) => {
  const mcp = new McpManager();
  await mcp.connect({ id: 'fx', command: 'python', args: [fixturePath] });
  t.after(() => mcp.closeAll());

  const worker = new Agent({ client: {}, config: { tools: true }, deferTools: false, mcp });
  const names = worker.currentSpecs().map((s) => s.function.name);
  assert.ok(names.includes('mcp__fx__echo'), 'the daemon path must not lose MCP tools');
  // The bug this guards: that branch returns the static list and never looks
  // at activatedTools, so MCP had to be added independently of it.
  assert.ok(names.includes('github_notifications'), 'and still sends the full static set');
});

test('the prompt tells the model which MCP servers exist', { skip }, async (t) => {
  const mcp = new McpManager();
  await mcp.connect({ id: 'fx', command: 'python', args: [fixturePath] });
  t.after(() => mcp.closeAll());

  const agent = new Agent({ client: {}, config: { tools: true, username: 'k', agentName: 'a' }, mcp });
  const prompt = agent.messages[0].content;
  assert.match(prompt, /Connected MCP servers/);
  assert.match(prompt, /mcp__<server>__<tool>/);
  assert.match(prompt, /fx: .*echo/);

  // refreshPrompt rebuilds it, which is what disconnect() triggers.
  await mcp.disconnect('fx');
  agent.refreshPrompt();
  assert.doesNotMatch(agent.messages[0].content, /Connected MCP servers/);
});

test('closeAll shuts down clients even if the map was tampered with', { skip }, async () => {
  const mcp = new McpManager();
  await mcp.connect({ id: 'fx', command: 'python', args: [fixturePath] });
  // Simulate a stray map mutation: the client is now unreachable from
  // `servers`, but it must still be closed.
  mcp.servers.delete('fx');
  assert.equal(mcp.servers.size, 0);
  await mcp.closeAll();
  assert.equal(mcp._clients.size, 0, 'no client left open');
});

test('a call to a server that is not connected is refused, not guessed', async () => {
  const mcp = new McpManager();
  await assert.rejects(mcp.callTool('mcp__ghost__do_thing'), /no connected MCP server/);
});

test('an approval detail names the command that will run', { skip }, async (t) => {
  const mcp = new McpManager();
  await mcp.connect({ id: 'fx', command: 'python', args: [fixturePath] });
  t.after(() => mcp.closeAll());

  const detail = mcp.approvalDetail('mcp__fx__write_note', { text: 'x' });
  assert.match(detail, /write_note on MCP server "fx"/);
  assert.match(detail, /destructive/);
  assert.match(detail, /command: python .*mcp_fixture\.py/, 'the user sees what will execute');
});

test('the protocol version we propose is one the SDK knows', () => {
  assert.equal(LATEST_PROTOCOL, '2025-11-25');
});
