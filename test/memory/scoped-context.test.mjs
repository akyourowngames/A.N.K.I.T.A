import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-scoped-memory-'));
process.env.CONFIG_DIR = path.join(root, 'global');
test.after(() => fs.rmSync(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 }));
const { Agent } = await import('../../src/core/agent.mjs');
const { ProfileStore } = await import('../../src/memory/profile.mjs');
const { PROFILE_FILE, PROJECTS_FILE, MEMORY_INDEX_FILE } = await import('../../src/core/config.mjs');

test('scoped prompt pins, automatic recall and memory tools use the same store with no extra model request', async t => {
  const global = new ProfileStore(PROFILE_FILE).load();
  global.add({ text: 'GLOBAL_USER_SENTINEL', always: true });
  const before = fs.readFileSync(PROFILE_FILE, 'utf8');
  const scoped = path.join(root, 'attempt-one', path.basename(PROFILE_FILE));
  new ProfileStore(scoped).load().add({ text: 'LOCAL_ATTEMPT_SENTINEL', always: true });
  const requests = [];
  const server = http.createServer(async (req, res) => {
    let text = '';
    for await (const chunk of req) text += chunk;
    requests.push(JSON.parse(text));
    res.setHeader('content-type', 'application/json');
    res.end(JSON.stringify({ choices: [{ message: { content: 'Observed scoped memory.' } }] }));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(async () => { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); });
  const client = { baseUrl: `http://127.0.0.1:${server.address().port}`, headers: () => ({}) };
  const config = { tools: true, memoryConsolidation: false };
  const context = directory => ({ profileFile: path.join(directory, path.basename(PROFILE_FILE)),
    projectsFile: path.join(directory, path.basename(PROJECTS_FILE)),
    memoryIndexFile: path.join(directory, path.basename(MEMORY_INDEX_FILE)) });
  const agent = new Agent({ client, config, workspacePath: root,
    toolContext: context(path.dirname(scoped)), print: () => {}, write: () => {} });
  await agent.send('Inspect my local attempt memory.');
  assert.equal(requests.length, 1);
  assert.doesNotMatch(JSON.stringify(requests[0]), /GLOBAL_USER_SENTINEL/);
  assert.match(requests[0].messages[0].content, /LOCAL_ATTEMPT_SENTINEL/);
  assert.match(agent.memoryContext.result, /LOCAL_ATTEMPT_SENTINEL/);
  const call = { id: 'scoped-write', type: 'function', function: { name: 'remember',
    arguments: JSON.stringify({ action: 'add', text: 'Written only in attempt one', always: true }) } };
  assert.doesNotMatch(await agent.runToolCall(call), /^Error:/);
  agent.refreshPrompt();
  assert.match(agent.messages[0].content, /Written only in attempt one/);
  const second = new Agent({ client, config, workspacePath: root,
    toolContext: context(path.join(root, 'attempt-two')), print: () => {}, write: () => {} });
  await second.send('Inspect my local attempt memory.');
  assert.equal(requests.length, 2);
  assert.equal(second.memoryContext, null);
  assert.doesNotMatch(JSON.stringify(requests[1]), /GLOBAL_USER_SENTINEL|LOCAL_ATTEMPT_SENTINEL|Written only in attempt one/);
  assert.equal(fs.readFileSync(PROFILE_FILE, 'utf8'), before);
  console.log('SCOPED_MEMORY_HTTP_LIVE requests=2 globalUnchanged=true attemptLeak=false');
});
