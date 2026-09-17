import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { PassThrough } from 'node:stream';
import { Agent } from '../src/agent.mjs';
import * as shared from '../tools/_shared.mjs';
import { Terminal } from '../src/ui.mjs';

const config = { tools: true, autoApprove: true, historyMessages: 8, historyLines: 8, maxTokens: 1000, temperature: null };
const makeAgent = (extra = {}) => new Agent({ client: {}, config: { ...config }, ...extra });
const call = (id, name, args) => ({ id, type: 'function', function: { name, arguments: JSON.stringify(args) } });

test('output cap preserves both ends within a UTF-8 byte budget', () => {
  assert.equal(typeof shared.capOutput, 'function');
  const result = shared.capOutput('START' + '😀'.repeat(50000) + 'END', 1024);
  assert.ok(Buffer.byteLength(result) <= 1024);
  assert.ok(result.startsWith('START') && result.endsWith('END'));
  assert.match(result, /truncated/);
});

test('autoApprove is enforced by Agent independently of the CLI', async (t) => {
  const cwd = fs.mkdtempSync(path.join(os.tmpdir(), 'agent-'));
  t.after(() => fs.rmSync(cwd, { recursive: true, force: true }));
  const agent = makeAgent({ confirm: () => { throw new Error('must not prompt'); } });
  agent.cwd = cwd;
  await agent.runToolCall(call('1', 'write_file', { path: 'a.txt', content: 'ok' }));
  assert.equal(fs.readFileSync(path.join(cwd, 'a.txt'), 'utf8'), 'ok');
});

test('history trimming keeps the current request and complete recent tool groups', () => {
  const agent = makeAgent();
  agent.messages.push({ role: 'user', content: 'current task' });
  for (let i = 0; i < 12; i++) agent.messages.push(
    { role: 'assistant', content: null, tool_calls: [call(String(i), 'read_file', {})] },
    { role: 'tool', tool_call_id: String(i), content: 'output' });
  agent.trimHistory(8);
  assert.ok(agent.messages.length <= 9);
  assert.ok(agent.messages.some(m => m.content === 'current task'));
  assert.equal(agent.messages.at(-1).tool_call_id, '11');
  for (const m of agent.messages.filter(m => m.role === 'tool')) {
    assert.ok(agent.messages.some(a => a.tool_calls?.some(c => c.id === m.tool_call_id)));
  }
});

test('stream failure retains partial reply and an interruption marker', async () => {
  const agent = makeAgent();
  agent.streamTurn = async ({ onDelta }) => { onDelta('partial answer'); throw new Error('broken stream'); };
  await assert.rejects(agent.send('hello', { onDelta() {} }), /broken stream/);
  assert.ok(agent.messages.some(m => m.role === 'assistant' && m.content.includes('partial answer')));
  assert.match(agent.messages.at(-1).content, /interrupt|cut off/i);
});

test('mid-task history is bounded before each subsequent request', async () => {
  const agent = makeAgent();
  let turns = 0;
  agent.runToolCall = async () => 'x';
  agent.streamTurn = async () => {
    assert.ok(agent.messages.length <= 9);
    return ++turns < 12 ? { content: '', toolCalls: [call(String(turns), 'read_file', {})] } : { content: 'done', toolCalls: [] };
  };
  assert.equal(await agent.send('work'), 'done');
});

test('saved readline history rewrites and deduplicates', (t) => {
  const cwd = fs.mkdtempSync(path.join(os.tmpdir(), 'history-'));
  t.after(() => fs.rmSync(cwd, { recursive: true, force: true }));
  const term = new Terminal({ input: new PassThrough(), output: new PassThrough() });
  t.after(() => term.close());
  const file = path.join(cwd, 'history');
  term.rl.history = ['new', 'old', 'new'];
  term.saveHistory(file);
  term.saveHistory(file);
  assert.deepEqual(fs.readFileSync(file, 'utf8').trim().split('\n'), ['old', 'new']);
});
