import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { removeFixtureDirectory } from '../helpers/fixture-cleanup.mjs';

const ROOT = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-cli-shutdown-'));
process.env.CONFIG_DIR = ROOT;
test.after(() => removeFixtureDirectory(ROOT));
const { BrowserPluginStore, BROWSER_FILE } = await import('../../src/integrations/browser-plugins.mjs');
const { McpStore } = await import('../../src/integrations/mcp-store.mjs');
const { ProjectStore } = await import('../../src/memory/projects.mjs');
const { MCP_FILE, SESSIONS_DIR, PROJECTS_FILE } = await import('../../src/core/config.mjs');
const CLI_FILE = fileURLToPath(new URL('../../chat.mjs', import.meta.url));
const CHILD_TIMEOUT_MS = 25_000; // Test-only ceiling for local HTTP and owned process cleanup.
const READY_TIMEOUT_MS = 5_000; // Test-only deadline for the background child to prove it started.
const POLL_MS = 20; // Milliseconds between fixture readiness checks.
const ANSWER = 'One-shot work finished.';
const FILE_CONTENT = 'Filesystem worker fixture contents.';
const RESUME_NAME = 'compaction-fixture'; // Saved test session used by the real --continue entry point.
const call = (name, args) => ({ id: `fixture-${name}`, type: 'function', function: { name, arguments: JSON.stringify(args) } });
const alive = pid => { try { process.kill(pid, 0); return true; } catch { return false; } };
const quote = value => `'${value.replace(/'/g, process.platform === 'win32' ? "''" : "'\\''")}'`;

async function runCli(t, { json = false, prompt = 'Finish the task', mode = 'plain' } = {}) {
  const directory = fs.mkdtempSync(path.join(ROOT, 'case-'));
  const runtime = path.join(directory, 'config');
  const pidFile = path.join(directory, 'owned.pid');
  let pageOpened = false;
  let modelRequests = 0;
  let recapRequests = 0;
  const compact = ['compaction', 'compaction-failure'].includes(mode);
  if (compact) {
    const sessions = path.join(runtime, path.basename(SESSIONS_DIR));
    fs.mkdirSync(sessions, { recursive: true });
    const messages = Array.from({ length: 12 }, (_, index) => [
      { role: 'user', content: `Earlier fixture goal ${index}` },
      { role: 'assistant', content: `Earlier fixture decision ${index}` },
    ]).flat();
    fs.writeFileSync(path.join(sessions, `${RESUME_NAME}.json`), JSON.stringify({ model: 'fixture', messages }));
  }
  const inspectionFile = path.join(directory, 'inspection.txt');
  if (mode === 'project') new ProjectStore(path.join(runtime, path.basename(PROJECTS_FILE))).load().add({ name: 'Fixture project', path: directory });
  if (mode === 'file') fs.writeFileSync(inspectionFile, FILE_CONTENT);
  if (mode === 'background') fs.writeFileSync(path.join(directory, 'owned.cjs'),
    `require('node:fs').writeFileSync(${JSON.stringify(pidFile)},String(process.pid));setInterval(()=>{},1000);`);
  if (mode === 'mcp') {
    const serverFile = path.join(directory, 'mcp.cjs');
    fs.writeFileSync(serverFile, `
      require('node:fs').writeFileSync(${JSON.stringify(pidFile)},String(process.pid));
      require('node:readline').createInterface({input:process.stdin}).on('line',line=>{
        const request=JSON.parse(line); if(request.id===undefined)return;
        const result=request.method==='initialize'
          ? {protocolVersion:'2024-11-05',capabilities:{tools:{}},serverInfo:{name:'fixture',version:'1'}}
          : {tools:[]};
        console.log(JSON.stringify({jsonrpc:'2.0',id:request.id,result}));
      });
    `);
    const store = new McpStore(path.join(runtime, path.basename(MCP_FILE))).load();
    const record = store.add({ name: 'Fixture', command: process.execPath, args: [serverFile] });
    store.markApproved(record.id);
  }
  if (mode === 'browser') new BrowserPluginStore(path.join(runtime, path.basename(BROWSER_FILE))).load().setEnabled('isolated', true);
  const server = http.createServer(async (request, response) => {
    if (request.url === '/page') { pageOpened = true; response.setHeader('content-type', 'text/html'); response.end('<h1>Owned browser fixture</h1>'); return; }
    response.setHeader('content-type', 'application/json');
    if (request.url.endsWith('/models')) { response.end(JSON.stringify({ data: [{ id: 'fixture', context_length: 256_000, supported_parameters: ['tools'] }] })); return; }
    modelRequests++;
    if (mode === 'failure') { response.statusCode = 403; response.end(JSON.stringify({ error: { message: 'Fixture access denied' } })); return; }
    let raw = ''; for await (const chunk of request) raw += chunk;
    const body = JSON.parse(raw);
    if (compact && body.stream === false) {
      recapRequests++;
      if (mode === 'compaction-failure') {
        response.statusCode = 500;
        response.end(JSON.stringify({ error: { message: 'Fixture recap unavailable' } }));
      } else response.end(JSON.stringify({ choices: [{ finish_reason: 'stop', message: { content: 'Earlier fixture goals and decisions retained.' } }] }));
      return;
    }
    const tools = body.messages.filter(message => message.role === 'tool');
    let next;
    if (mode === 'browser') {
      if (!tools.length) next = call('find_tools', { query: 'browser' });
      else if (!tools.some(message => message.tool_call_id === 'fixture-browser')) next = call('browser', { action: 'open', mode: 'isolated', url: `http://127.0.0.1:${server.address().port}/page` });
    }
    if (mode === 'background' && !tools.length) next = call('run_command', {
      command: `${process.platform === 'win32' ? '& ' : ''}${quote(process.execPath)} ${quote(path.join(directory, 'owned.cjs'))}`, background: true,
    });
    if (mode === 'file' && !tools.length) next = call('read_file', { path: inspectionFile });
    if (mode === 'background' && tools.length) {
      const deadline = Date.now() + READY_TIMEOUT_MS;
      while (!fs.existsSync(pidFile) && Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, POLL_MS));
    }
    response.end(JSON.stringify({ choices: [{ finish_reason: next ? 'tool_calls' : 'stop', message: next
      ? { content: '', tool_calls: [next] } : { content: ANSWER } }] }));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const child = spawn(process.execPath, [CLI_FILE, '--prompt', prompt, '--plain', '--no-banner', '--yes', ...(json ? ['--json'] : []), ...(compact ? ['--continue', RESUME_NAME] : [])], {
    cwd: directory, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'],
    env: { ...process.env, CONFIG_DIR: runtime, PROVIDER: mode === 'no-key' ? 'groq' : 'kilo', MODEL: mode === 'unknown-model' ? 'unavailable-fixture' : 'fixture',
      API_BASE: `http://127.0.0.1:${server.address().port}/v1`, API_KEY: mode === 'no-key' ? '' : 'fixture-only', GROQ_API_KEY: '',
      TOOL_PROVIDER: '', TOOL_MODEL: '', COMPOSIO_API_KEY: '', COMPOSIO_BROKER_URL: mode === 'app-failure' ? `http://127.0.0.1:${server.address().port}/broker` : '',
      ALLOW_PRIVATE_HOSTS: '1', // This fixture intentionally opens its own loopback HTTP page.
      CONTEXT_COMPACTION: compact ? 'on' : 'off', HISTORY_MESSAGES: compact ? '8' : '40',
      TOOLS: ['background', 'browser', 'mcp', 'file', 'app-failure'].includes(mode) ? 'on' : 'off', MEMORY_CONSOLIDATION: 'off', EMBEDDINGS: 'off',
      PROJECT_AUTO_DETECT: mode === 'project' ? 'on' : 'off', PROJECT_WORK_CAPTURE: 'off', PROJECT_AUTO_MAINTENANCE: 'off', SUBAGENTS_ENABLED: 'off', SPEAK: 'off' },
  });
  let stdout = '', stderr = '', timedOut = false;
  child.stdout.on('data', chunk => { stdout += chunk; });
  child.stderr.on('data', chunk => { stderr += chunk; });
  const closed = new Promise((resolve, reject) => { child.once('error', reject); child.once('close', resolve); });
  const timer = setTimeout(() => { timedOut = true; child.kill(); }, CHILD_TIMEOUT_MS);
  t.after(async () => {
    clearTimeout(timer);
    if (child.exitCode === null && child.signalCode === null) child.kill();
    await closed;
    if (fs.existsSync(pidFile)) { const pid = Number(fs.readFileSync(pidFile, 'utf8')); if (alive(pid)) process.kill(pid); }
    server.closeAllConnections(); await new Promise(resolve => server.close(resolve));
  });
  const code = await closed;
  clearTimeout(timer);
  assert.equal(timedOut, false, `CLI retained an owned handle\n${stdout}\n${stderr}`);
  return { code, stdout, stderr, pageOpened, pidFile, childPid: child.pid, modelRequests, recapRequests };
}

for (const json of [false, true]) {
  test(`one-shot ${json ? 'JSON' : 'plain'} output exits naturally and preserves its result`, async t => {
    const result = await runCli(t, { json });
    assert.equal(result.code, 0, result.stderr);
    if (json) { const response = JSON.parse(result.stdout); assert.equal(response.ok, true); assert.equal(response.text, ANSWER); }
    else assert.match(result.stdout, new RegExp(ANSWER));
  });
  test(`empty one-shot ${json ? 'JSON' : 'plain'} prompt retains usage-error exit code`, async t => {
    const result = await runCli(t, { json, prompt: '' });
    assert.equal(result.code, 2);
    if (json) assert.deepEqual(JSON.parse(result.stdout), { ok: false, error: 'empty prompt' });
    else assert.match(result.stderr, /empty prompt/);
  });
}

test('one-shot JSON provider failure retains its error result and exit code', async t => {
  const result = await runCli(t, { json: true, mode: 'failure' });
  assert.equal(result.code, 1);
  const response = JSON.parse(result.stdout);
  assert.equal(response.ok, false);
  assert.match(response.error, /Fixture access denied|403/);
});

for (const json of [false, true]) test(`resumed ${json ? 'JSON' : 'plain'} one-shot compaction preserves its output format`, async t => {
  const result = await runCli(t, { json, mode: 'compaction' });
  assert.equal(result.code, 0, JSON.stringify(result));
  assert.ok(result.recapRequests > 0, 'the real CLI requested a recap before replying');
  if (json) {
    let response;
    assert.doesNotThrow(() => { response = JSON.parse(result.stdout); }, result.stdout);
    assert.equal(response.ok, true);
    assert.equal(response.text, ANSWER);
  } else {
    assert.match(result.stdout, /resumed/);
    assert.match(result.stdout, /earlier conversation summarized/);
    assert.match(result.stdout, new RegExp(ANSWER));
  }
});

test('a skipped recap leaves resumed one-shot JSON parseable', async t => {
  const result = await runCli(t, { json: true, mode: 'compaction-failure' });
  assert.equal(result.code, 0, JSON.stringify(result));
  assert.ok(result.recapRequests > 0, 'the recap failure path actually ran');
  let response;
  assert.doesNotThrow(() => { response = JSON.parse(result.stdout); }, result.stdout);
  assert.equal(response.ok, true);
  assert.equal(response.text, ANSWER);
});

const STARTUP_NOTICES = [
  ['mcp', /connecting MCP servers[\s\S]*mcp: connected fixture/],
  ['no-key', /no API_KEY set/],
  ['unknown-model', /unknown model.*using fixture instead/],
  ['project', /project ~ Fixture project/],
  ['app-failure', /connected apps:.*HTTPS/],
];
for (const [mode, notice] of STARTUP_NOTICES) for (const json of [false, true]) {
  test(`${mode} startup notices preserve ${json ? 'JSON' : 'human'} one-shot output`, async t => {
    const result = await runCli(t, { mode, json });
    assert.equal(result.code, 0, JSON.stringify(result));
    if (json) {
      let response;
      assert.doesNotThrow(() => { response = JSON.parse(result.stdout); }, result.stdout);
      assert.equal(response.ok, true);
      assert.equal(response.model, 'fixture');
      assert.equal(response.text, ANSWER);
    } else {
      assert.match(result.stdout, notice);
      assert.match(result.stdout, new RegExp(ANSWER));
    }
    if (mode === 'mcp') {
      assert.ok(fs.existsSync(result.pidFile), 'the approved MCP fixture actually started');
      assert.equal(alive(Number(fs.readFileSync(result.pidFile, 'utf8'))), false);
    }
  });
}

test('one-shot file inspection finishes naturally after using the filesystem worker', async t => {
  const result = await runCli(t, { mode: 'file' });
  assert.equal(result.code, 0, result.stderr);
  assert.match(result.stdout, new RegExp(FILE_CONTENT));
  assert.match(result.stdout, new RegExp(ANSWER));
});

for (const mode of ['background', 'mcp']) test(`one-shot shutdown stops its owned ${mode} process`, async t => {
  const result = await runCli(t, { mode });
  assert.equal(result.code, 0, JSON.stringify(result));
  assert.match(result.stdout, new RegExp(ANSWER));
  assert.ok(fs.existsSync(result.pidFile), `${mode} process actually started`);
  assert.equal(alive(Number(fs.readFileSync(result.pidFile, 'utf8'))), false, `${mode} process stopped before CLI close`);
});

test('one-shot browser work closes real isolated Chromium before natural process exit', async t => {
  const result = await runCli(t, { mode: 'browser' });
  assert.equal(result.code, 0, result.stderr);
  assert.match(result.stdout, new RegExp(ANSWER));
  assert.equal(result.pageOpened, true, `the normal browser tool reached the loopback page\n${result.stdout}\n${result.stderr}`);
  console.log('CLI_BROWSER_SHUTDOWN_OK opened=1 exit=0');
});
