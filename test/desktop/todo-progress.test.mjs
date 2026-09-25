import test from 'node:test';
import assert from 'node:assert/strict';
import { todoProgress } from '../../desktop/shared/todo-progress.mjs';

const call = (id, args, result = '[ ] 1. Investigate (s1)', isError = false) => ({
  id: `tool-${id}`, role: 'tool', callId: id, name: 'write_todos', args, result, isError,
});

test('reconstructs the latest successful checklist and status updates from a thread', () => {
  const messages = [
    call('1', { todos: [
      { content: 'Investigate', status: 'in_progress', activeForm: 'Investigating' },
      { content: 'Implement', status: 'pending' },
    ] }),
    { id: 'other', role: 'tool', name: 'run_command', args: {}, result: 'done', isError: false },
    call('2', { updates: [{ id: 's1', status: 'completed' }, { id: 's2', status: 'in_progress' }] }),
  ];
  assert.deepEqual(todoProgress(messages), [
    { id: 's1', content: 'Investigate', activeForm: 'Investigating', status: 'completed' },
    { id: 's2', content: 'Implement', activeForm: 'Implement', status: 'in_progress' },
  ]);
});

test('ignores unfinished and failed calls, and uses the latest full checklist', () => {
  const messages = [
    call('1', { todos: [{ content: 'Old', status: 'completed' }] }),
    call('2', { todos: [{ content: 'Unfinished', status: 'pending' }] }, ''),
    call('3', { updates: [{ id: 's1', status: 'pending' }] }, 'Error: failed', true),
    call('4', { todos: [{ content: 'New', status: 'in_progress', id: 's1' }] }),
  ];
  assert.deepEqual(todoProgress(messages), [
    { id: 's1', content: 'New', activeForm: 'New', status: 'in_progress' },
  ]);
  assert.deepEqual(todoProgress([]), []);
});

test('restores a checklist from a full tool result when older calls are unavailable', () => {
  const messages = [call('2', { updates: [{ id: 's1', status: 'completed' }] }, '[x] 1. Research (s1)\n[>] 2. Ship (s2)')];
  assert.deepEqual(todoProgress(messages), [
    { id: 's1', content: 'Research', activeForm: 'Research', status: 'completed' },
    { id: 's2', content: 'Ship', activeForm: 'Ship', status: 'in_progress' },
  ]);
});

test('a new user turn keeps the previous plan until the agent updates it', () => {
  const original = call('1', { todos: [{ content: 'Research', status: 'in_progress' }] }, '[>] 1. Research (s1)');
  const prompt = { id: 'user-2', role: 'user', content: 'Now check the result' };
  assert.deepEqual(todoProgress([original, prompt]), [
    { id: 's1', content: 'Research', activeForm: 'Research', status: 'in_progress' },
  ]);
  assert.deepEqual(todoProgress([original, prompt, call('2', { updates: [{ id: 's1', status: 'completed' }] }, '[x] 1. Research (s1)')]), [
    { id: 's1', content: 'Research', activeForm: 'Research', status: 'completed' },
  ]);
});

test('runtime control notes do not clear the current plan after a bounded turn', () => {
  const original = call('1', { todos: [{ content: 'Research', status: 'in_progress' }] }, '[>] 1. Research (s1)');
  const note = { id: 'runtime', role: 'user', content: '(the runtime stopped the tool loop: limit reached. Do not call more tools.)' };
  assert.deepEqual(todoProgress([original, note]), todoProgress([original]));
});
