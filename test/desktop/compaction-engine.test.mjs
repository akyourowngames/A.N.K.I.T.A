import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';

const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-compaction-engine-'));
process.env.CONFIG_DIR = directory;
const { DesktopEngine, threadMessages } = await import('../../desktop/electron/engine.mjs');
const { CompatibleClient } = await import('../../src/core/provider.mjs');
const { SUBAGENT_INBOX_PREFIX } = await import('../../src/core/subagents/registry.mjs');
test.after(() => fs.rmSync(directory, { recursive: true, force: true }));

test('desktop sends recap completion before turn end and restores the labelled recap', async t => {
  const server = http.createServer(async (req, res) => {
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    const body = JSON.parse(Buffer.concat(chunks));
    res.setHeader('content-type', 'application/json');
    res.end(JSON.stringify({ choices: [{ finish_reason: 'stop', message: {
      content: body.stream ? 'Work continued.' : 'Original goal and decisions retained.',
    } }] }));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => { server.closeAllConnections(); return new Promise(resolve => server.close(resolve)); });
  const client = new CompatibleClient({ apiBase: `http://127.0.0.1:${server.address().port}`, model: 'fixture' });
  const events = [];
  const engine = new DesktopEngine({
    teammateFile: path.join(directory, 'teammates.json'), sessionsDir: directory,
    settingsFile: path.join(directory, 'settings.json'), channelsFile: path.join(directory, 'channels.json'),
    envPath: path.join(directory, '.env'),
    config: { provider: 'custom', model: 'fixture', tools: false, contextWindow: 128000,
      historyMessages: 40, maxTokens: 1000, contextCompaction: true, memoryConsolidation: false },
    bootstrap: async () => ({ client, models: [{ id: 'fixture', context: 128000 }], model: 'fixture', provider: { name: 'custom' } }),
    emit: event => events.push(event),
    mcp: { reconcile: async () => {}, ensureComposio: async () => {}, summaries: () => [], closeAll: async () => {} },
  });
  await engine.init();
  t.after(() => engine.channels?.stopAll());
  const id = engine.listTeammates()[0].id;
  const agent = engine.agentFor(id);
  for (let i = 0; i < 20; i++) agent.messages.push(
    { role: 'user', content: `request ${i}` }, { role: 'assistant', content: `decision ${i}` });
  await engine.send(id, 'Continue the task.');
  await engine.waitForTurn(id);
  const completed = events.findIndex(event => event.type === 'context-compaction' && event.phase === 'completed');
  assert.ok(completed >= 0, 'the engine forwards the successful recap');
  assert.ok(completed < events.findIndex(event => event.type === 'turn-end'));
  assert.equal(events[completed].threadId, id);
  const saved = JSON.parse(fs.readFileSync(engine.sessionFile(id), 'utf8'));
  const restored = threadMessages(saved.messages);
  assert.equal(restored.filter(message => message.compacted).length, 1);
  assert.equal(restored.find(message => message.compacted).content, 'Original goal and decisions retained.');
  console.log('DESKTOP_COMPACTION_HTTP_OK', JSON.stringify({ completionBeforeTurnEnd: true, persistedRecaps: 1 }));
});

test('restored transcript hides internal agent mailboxes while keeping the real request', () => {
  const transcript = threadMessages([{ role: 'user', content: 'Real request' },
    { role: 'user', content: `${SUBAGENT_INBOX_PREFIX}\nInternal update` }]);
  assert.deepEqual(transcript.map(message => message.content), ['Real request']);
});
