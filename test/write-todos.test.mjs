import test from 'node:test';
import assert from 'node:assert/strict';
import { run } from '../tools/write-todos.mjs';

test('todo errors show the valid state and corrective IDs without changing it', () => {
  const ctx = { state: {} };
  run({ todos: [{ content: 'First', status: 'completed' }, { content: 'Second', status: 'pending' }] }, ctx);
  assert.throws(() => run({ todos: [{ content: 'Different', status: 'pending' }, { content: 'Second', status: 'pending' }] }, ctx), /cannot replace[\s\S]*First \(s1\)[\s\S]*Second \(s2\)/);
  assert.throws(() => run({ updates: [{ id: 's9', status: 'completed' }] }, ctx), /unknown todo ID: s9[\s\S]*Available IDs: s1, s2/);
  assert.throws(() => run({ todos: [{ content: 'First', status: 'completed' }] }, ctx), /cannot remove[\s\S]*status: cancelled[\s\S]*First \(s1\)/);
  assert.deepEqual(ctx.state.todos.map(item => item.content), ['First', 'Second']);
});

test('corrective todo rendering stays bounded for a long list', () => {
  const ctx = { state: {} };
  run({ todos: Array.from({ length: 1000 }, (_, i) => ({ content: `Task ${i} ${'x'.repeat(100)}`, status: 'pending' })) }, ctx);
  assert.throws(() => run({ todos: [{ content: 'shorter', status: 'pending' }] }, ctx), error => {
    assert.ok(error.message.length < 2300);
    assert.match(error.message, /s1/);
    return true;
  });
  assert.throws(() => run({ updates: [{ id: 'missing', status: 'completed' }] }, ctx), error => {
    assert.ok(error.message.length < 2300);
    assert.match(error.message, /Available IDs: s1/);
    return true;
  });
});
