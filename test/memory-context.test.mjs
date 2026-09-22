import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';

const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-context-'));
process.env.CONFIG_DIR = dir;
test.after(() => fs.rmSync(dir, { recursive: true, force: true }));
const { Agent } = await import('../src/agent.mjs');
const { ProfileStore } = await import('../src/profile.mjs');
const { PROFILE_FILE } = await import('../src/config.mjs');

test('a fresh request sees bounded real memory even when the model skips recall; no extra model request', async t => {
  const s = new ProfileStore(PROFILE_FILE).load();
  s.add({ text: 'Enjoys pottery', kind: 'preference' });
  for (let i = 0; i < 30; i++) s.add({ text: `Other detail ${i}: ` + 'x'.repeat(2000) });
  const requests = [];
  const server = http.createServer(async (req, res) => {
    let body = '';
    for await (const part of req) body += part;
    requests.push(JSON.parse(body));
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ choices: [{ message: { content: 'A pottery session could be fun.' } }] }));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => { server.closeAllConnections(); server.close(); });
  const client = { baseUrl: `http://127.0.0.1:${server.address().port}`, headers: () => ({}) };
  const agent = new Agent({ client, config: { tools: true, memoryRecallChars: 1600 }, print: () => {}, write: () => {} });
  await agent.send('What pottery activity would I enjoy?');
  assert.equal(requests.length, 1);
  const memory = requests[0].messages.find(m => m.role === 'tool' && m.tool_call_id.startsWith('personal_context_'));
  assert.ok(memory, 'runtime retrieval must not depend on the model choosing recall');
  assert.match(memory.content, /Enjoys pottery/);
  assert.ok(Buffer.byteLength(memory.content) <= 1600);
  assert.doesNotMatch(requests[0].messages[0].content, /Enjoys pottery/);
  assert.equal(agent.messages.some(m => m.tool_call_id?.startsWith('personal_context_')), false, 'temporary retrieval must not inflate history/autosaves');
  s.update(s.facts.find(f => f.text === 'Enjoys pottery').id, { text: 'Enjoys astronomy' });
  await agent.send('What astronomy activity would I enjoy?');
  assert.equal(requests.length, 2);
  const next = requests[1].messages.filter(m => m.role === 'tool' && m.tool_call_id.startsWith('personal_context_'));
  assert.equal(next.length, 1);
  assert.match(next[0].content, /Enjoys astronomy/);
  assert.doesNotMatch(next[0].content, /Enjoys pottery/);
});

test('disabling automatic recall or tools does not load personal candidates', async () => {
  for (const config of [{ tools: false }, { tools: true, memoryRecallChars: 0 }]) {
    const agent = new Agent({ client: {}, config });
    agent.streamTurn = async () => ({ content: 'hello', toolCalls: [] });
    await agent.send('hello');
    assert.equal(agent.memoryContext, null);
  }
});
