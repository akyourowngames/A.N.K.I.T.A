import test from 'node:test';
import assert from 'node:assert/strict';
import { findSimilar, lexicalSimilarity, lexicalRelated, isStale, tokens } from '../../src/memory/memory-similarity.mjs';

const facts = () => [
  { id: 'pg', text: 'I use Postgres', kind: 'preference' },
  { id: 'coffee', text: 'I like black coffee', kind: 'preference' },
  { id: 'city', text: 'I live in Pune', kind: 'fact' },
];

test('content words drop filler so two phrasings can meet', () => {
  assert.deepEqual([...tokens('I use the Postgres database')].sort(), ['postgres']);
  assert.deepEqual([...tokens('Database is Postgres')].sort(), ['postgres']);
});

test('the same fact in different words is a duplicate, without any embedder', async () => {
  const match = await findSimilar('Database is Postgres', facts(), { kind: 'preference' });
  assert.equal(match.kind, 'duplicate');
  assert.equal(match.fact.id, 'pg');
  assert.ok(match.score >= 0.85);
});

test('every content word of the short fact contained in the long one counts as a duplicate', () => {
  assert.ok(lexicalSimilarity('I live in Pune', 'I live in Pune city') >= 0.85);
  // "coffee" vs "black coffee" adds a real qualifier, so it is related, not identical.
  assert.ok(lexicalSimilarity('I like coffee', 'I like black coffee') < 0.85);
});

test('unrelated facts are never merged or flagged', async () => {
  for (const text of ['My name is Krish', 'I prefer tea', 'The build runs on Linux']) {
    const match = await findSimilar(text, facts(), { kind: 'preference' });
    assert.equal(match.kind, null, text);
  }
});

test('a likely contradiction needs a real shared subject, not one short word', async () => {
  // One shared word is ambiguous, so lexical mode never claims a conflict.
  assert.equal(lexicalRelated('I like coffee', 'I like black coffee'), false);
  // Two shared content words in a longer claim is the shape of a changed fact.
  assert.equal(lexicalRelated('My meeting is at 3pm on Monday', 'My meeting is at 5pm on Monday'), true);
});

test('different declared kinds never conflict, only merge', async () => {
  const rows = [{ id: 'a', text: 'I prefer dark roast coffee every morning', kind: 'preference' }];
  const match = await findSimilar('I prefer green tea every morning', rows, { kind: 'fact' });
  assert.equal(match.kind, null, 'a preference and a fact may share words without disagreeing');
});

test('an embedder score is used when present and drives the same two decisions', async () => {
  const rows = facts();
  const byId = id => rows.find(row => row.id === id);
  const embedder = { rank: async () => ({ scores: new Map([[byId('pg'), 0.94], [byId('coffee'), 0.1], [byId('city'), 0.05]]) }) };
  const duplicate = await findSimilar('Postgres is my database', rows, { embedder });
  assert.equal(duplicate.kind, 'duplicate');

  const conflictEmbedder = { rank: async () => ({ scores: new Map([[byId('pg'), 0.66]]) }) };
  const conflict = await findSimilar('I moved off Postgres', rows, { embedder: conflictEmbedder });
  assert.equal(conflict.kind, 'conflict');
});

test('an embedder failure degrades to lexical scoring instead of blocking the write', async () => {
  const broken = { rank: async () => { throw new Error('provider down'); } };
  const match = await findSimilar('Database is Postgres', facts(), { embedder: broken });
  assert.equal(match.kind, 'duplicate', 'the lexical fallback still recognises the duplicate');
});

test('an empty or one-word fact is not compared into a false match', async () => {
  assert.equal((await findSimilar('x', facts())).kind, null);
  assert.equal((await findSimilar('   ', facts())).kind, null);
  assert.deepEqual(await findSimilar('', []), { fact: null, score: 0, kind: null });
});

test('staleness ignores pins and needs a real elapsed window', () => {
  const old = { text: 'a', updatedAt: new Date(Date.now() - 200 * 86400000).toISOString() };
  assert.equal(isStale(old, { staleDays: 90 }), true);
  assert.equal(isStale({ ...old, always: true }, { staleDays: 90 }), false, 'pins never go stale');
  assert.equal(isStale({ text: 'b', updatedAt: new Date().toISOString() }, { staleDays: 90 }), false);
  assert.equal(isStale(old, { staleDays: 0 }), false, 'the feature is off when the window is zero');
  assert.equal(isStale({ text: 'c', lastRecalledAt: new Date().toISOString(), updatedAt: old.updatedAt }, { staleDays: 90 }), false,
    'a recent recall keeps a fact fresh');
});
