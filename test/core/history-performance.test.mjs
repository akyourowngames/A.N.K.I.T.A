import test from 'node:test';
import assert from 'node:assert/strict';
import { trimMessages, conversationCost } from '../../src/core/history.mjs';

test('dropping hundreds of history groups measures messages only a linear number of times', () => {
  const system = { role: 'system', content: 'system' };
  const anchor = { role: 'user', content: 'current request' };
  const latest = { role: 'assistant', content: 'latest answer' };
  const messages = [system, ...Array.from({ length: 400 }, (_, i) => ({
    role: 'assistant', content: `old ${i}: ` + 'x'.repeat(1000),
  })), anchor, latest];
  const stringify = JSON.stringify;
  let measurements = 0;
  let result;
  JSON.stringify = (...args) => {
    measurements++;
    return stringify(...args);
  };
  try {
    result = trimMessages(messages, 1000, 200);
  } finally {
    JSON.stringify = stringify;
  }
  assert.deepEqual(result, [system, anchor, latest]);
  assert.ok(measurements <= messages.length * 3, `${measurements} measurements for ${messages.length} messages`);
});

test('byte trimming preserves the latest tool exchange atomically and keeps chronology around the user', () => {
  const exchange = id => [
    { role: 'assistant', content: null, tool_calls: [{ id, type: 'function', function: { name: 'read', arguments: '{}' } }] },
    { role: 'tool', tool_call_id: id, content: 'x'.repeat(120) },
  ];
  const system = { role: 'system', content: 's' };
  const anchor = { role: 'user', content: 'read again' };
  const newest = exchange('new');
  const messages = [system, { role: 'user', content: 'old request' }, ...exchange('old'), anchor, ...newest];
  assert.deepEqual(trimMessages(messages, 40, 400), [system, anchor, ...newest]);
});

test('trimming attachment text preserves the original input content parts', () => {
  const messages = [
    { role: 'system', content: 'system' },
    { role: 'user', content: [
      { type: 'text', text: 'summarize' },
      { type: 'text', text: 'Attached file: notes.txt\n' + 'x'.repeat(10_000) },
    ] },
  ];
  const original = structuredClone(messages);
  const result = trimMessages(messages, 40, 500);
  assert.deepEqual(messages, original);
  assert.ok(conversationCost(result) <= 500);
  assert.equal(result[1].content[0].text, 'summarize');
  assert.ok(result[1].content[1].text.length < 10_000);
});

test('image costs are measured a bounded number of times while dropping many image parts', () => {
  const messages = [{ role: 'user', content: [
    { type: 'text', text: 'inspect the remaining pages' },
    ...Array.from({ length: 40 }, (_, i) => ({
      type: 'image_url', image_url: { url: 'data:image/png;base64,' + 'A'.repeat(1000 + 4 * i) },
    })),
  ] }];
  const original = structuredClone(messages);
  const from = Buffer.from;
  let decodes = 0;
  let result;
  Buffer.from = (...args) => {
    if (args[1] === 'base64') decodes++;
    return from(...args);
  };
  try {
    result = trimMessages(messages, 40, 1500);
  } finally {
    Buffer.from = from;
  }
  assert.ok(decodes <= 120, `${decodes} decodes for 40 images`);
  assert.ok(conversationCost(result) <= 1500);
  assert.deepEqual(messages, original);
  assert.equal(result[1].content[0].text, 'inspect the remaining pages');
  assert.equal(result[1].content.filter(part => part.type === 'image_url').length, 1);
});

test('an irreducible system or text request still rejects a budget that cannot fit', () => {
  assert.throws(() => trimMessages([{ role: 'system', content: 'x'.repeat(1000) }], 40, 100), /context budget/);
  assert.throws(() => trimMessages([{ role: 'user', content: 'x'.repeat(1000) }], 40, 100), /context budget/);
});
