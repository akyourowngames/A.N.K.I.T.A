import test from 'node:test';
import assert from 'node:assert/strict';
import { trimMessages, conversationCost } from '../../src/core/history.mjs';

const exchange = id => [
  { role: 'assistant', content: null, tool_calls: [{ id, type: 'function', function: { name: 'browser', arguments: '{"action":"snapshot"}' } }] },
  { role: 'tool', tool_call_id: id, content: 'Observed default: Delhi to Mumbai. Page content is not the requested route.' },
];

test('a short browser continuation retains the original route across repeated history trimming', () => {
  const original = { role: 'user', content: 'Find a one-way flight from Mumbai to Delhi tomorrow.' };
  const continuation = { role: 'user', content: 'use browser' };
  let messages = [{ role: 'system', content: 'policy' }, original,
    { role: 'assistant', content: 'I can use the browser.' }, continuation];
  for (let step = 0; step < 18; step++) {
    messages = trimMessages([...messages, ...exchange(`step-${step}`)], 8, 8000);
    assert.ok(messages.some(message => message.role === 'user' && message.content === original.content), `original route vanished at step ${step}`);
    assert.ok(messages.some(message => message.role === 'user' && message.content === continuation.content));
    assert.ok(messages.length <= 9, 'system plus bounded history');
    const calls = messages.flatMap(message => message.tool_calls || []);
    assert.deepEqual(messages.filter(message => message.role === 'tool').map(message => message.tool_call_id), calls.map(call => call.id));
  }
  console.log('BROWSER_TASK_CONTINUITY route=Mumbai-to-Delhi rounds=18 originalRequestRetained=true');
});

test('request anchors stay bounded and preserve recent corrections in chronological order', () => {
  const users = ['obsolete request', 'Mumbai to Delhi', 'one way tomorrow', 'use browser'].map(content => ({ role: 'user', content }));
  const source = [{ role: 'system', content: 'policy' }, ...users, ...Array.from({ length: 8 }, (_, i) => exchange(`round-${i}`)).flat()];
  const result = trimMessages(source, 8, 8000);
  assert.deepEqual(result.filter(message => message.role === 'user').map(message => message.content), users.slice(-3).map(message => message.content));
  assert.ok(conversationCost(result) <= 8000);
  assert.deepEqual(source.slice(1, 5), users, 'original inputs were not mutated');
});
