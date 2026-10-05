import test from 'node:test';
import assert from 'node:assert/strict';

import * as api from '../../desktop/shared/island-state.mjs';
const reduce = (events, initial = { threads: {} }) => {
  assert.equal(typeof api.reduceIslandState, 'function', 'the island needs a shared event reducer');
  return events.reduce(api.reduceIslandState, initial);
};
const event = (type, fields = {}) => ({ type, threadId: 'chief', ...fields });

test('reasoning stays separate and distinct assistant messages keep distinct identities', () => {
  const state = reduce([
    event('turn-start', { turnId: 'turn', text: 'Inspect this' }),
    event('message-start', { messageId: 'one' }),
    event('reasoning-delta', { messageId: 'one', text: 'Private reasoning' }),
    event('assistant-delta', { messageId: 'one', text: 'First answer' }),
    event('message-end', { messageId: 'one' }),
    event('message-start', { messageId: 'two' }),
    event('assistant-delta', { messageId: 'two', text: 'Second answer' }),
  ]);
  const answers = state.threads.chief.log.filter(row => row.role === 'assistant');
  assert.deepEqual(answers.map(row => row.content), ['First answer', 'Second answer']);
  assert.deepEqual(answers.map(row => row.id), ['one', 'two']);
  assert.equal(answers[0].streaming, false);
  assert.equal(answers[1].streaming, true);
});

test('tool calls finish by call identity, show complete output, and survive interleaved streams', () => {
  const state = reduce([
    event('turn-start', { turnId: 'turn', text: 'Read and run' }),
    event('tool-call', { callId: 'read', name: 'read_file', args: { path: 'src/app.ts' } }),
    event('tool-call', { callId: 'run', name: 'run_command', args: { command: 'npm test' } }),
    event('assistant-delta', { messageId: 'answer', text: 'Results' }),
    event('tool-result', { callId: 'read', text: 'x'.repeat(350), isError: false }),
    event('tool-result', { callId: 'run', text: 'Error: failed', isError: true }),
  ]);
  const tools = state.threads.chief.log.filter(row => row.kind === 'tool');
  assert.deepEqual(tools.map(row => row.state), ['ok', 'error']);
  assert.equal(tools[0].result.length, 350);
  assert.match(tools[0].detail, /app.ts/);
  assert.equal(api.islandThreadState(state.threads.chief), 'thinking');
});

test('message reset removes partial content and turn end preserves an error instead of celebrating', () => {
  const state = reduce([
    event('turn-start', { turnId: 'turn', text: 'Try' }),
    event('assistant-delta', { messageId: 'answer', text: 'Partial' }),
    event('message-reset', { messageId: 'answer' }),
    event('assistant-delta', { messageId: 'answer', text: 'Replacement' }),
    event('error', { message: 'Provider disconnected' }),
    event('turn-end', { turnId: 'turn' }),
  ]);
  assert.equal(state.threads.chief.log.at(-1).content, 'Replacement');
  assert.equal(state.threads.chief.running, false);
  assert.equal(api.islandThreadState(state.threads.chief), 'error');
});

test('parallel teammates remain independent and search tools drive the searching expression', () => {
  const state = reduce([
    event('turn-start', { turnId: 'a', text: 'Search' }),
    event('turn-start', { threadId: 'research', turnId: 'b', text: 'Think' }),
    event('tool-call', { callId: 'search', name: 'web_search', args: { query: 'animation' } }),
    event('turn-end', { threadId: 'research', turnId: 'b' }),
  ]);
  assert.equal(api.islandThreadState(state.threads.chief), 'searching');
  assert.equal(state.threads.chief.running, true);
  assert.equal(state.threads.research.running, false);
});

test('hydration keeps persisted tools and replays events received while the snapshot was loading', () => {
  assert.equal(typeof api.hydrateIslandState, 'function');
  const state = api.hydrateIslandState({ threads: [{ id: 'chief', running: true, messages: [
    { id: 'old', role: 'user', content: 'Earlier' },
    { id: 'tool-old', role: 'tool', callId: 'old', name: 'read_file', args: { path: 'old.md' }, result: 'contents', isError: false },
  ] }] }, [event('assistant-delta', { messageId: 'fresh', text: 'Live answer' })]);
  assert.equal(state.threads.chief.log[1].kind, 'tool');
  assert.equal(state.threads.chief.log[1].result, 'contents');
  assert.equal(state.threads.chief.log.at(-1).content, 'Live answer');
  assert.equal(state.threads.chief.running, true);
});

test('routine results and attachments retain their metadata and clear-thread empties only its owner', () => {
  const state = reduce([
    event('turn-start', { turnId: 'a', text: '', attachments: [{ name: 'notes.md' }] }),
    event('routine-result', { messageId: 'job', name: 'Daily', status: 'completed', at: '2026-10-04T00:00:00Z', content: 'Job answer' }),
    event('turn-start', { threadId: 'research', turnId: 'b', text: 'Keep this' }),
    event('thread-cleared', { threadId: 'research' }),
  ]);
  assert.equal(state.threads.chief.log[0].attachments[0].name, 'notes.md');
  assert.equal(state.threads.chief.log.at(-1).job.name, 'Daily');
  assert.equal(state.threads.research.log.length, 0);
});

test('snapshot watermark replays only newer events and hidden history tools stay hidden', () => {
  const state = api.hydrateIslandState({ sequence: 5, threads: [{ id: 'chief', running: false, messages: [
    { id: 'answer', role: 'assistant', content: 'Already captured' },
    { id: 'hidden', role: 'tool', callId: 'hidden', name: 'write_todos', result: 'Checklist', hidden: true },
  ] }] }, [event('assistant-delta', { sequence: 4, messageId: 'answer', text: 'Duplicate' }),
    event('assistant-delta', { sequence: 6, messageId: 'fresh', text: 'Newer' })]);
  assert.deepEqual(state.threads.chief.log.map(row => row.content), ['Already captured', 'Newer']);
});
