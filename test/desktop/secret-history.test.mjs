import test from 'node:test';
import assert from 'node:assert/strict';
const key = 'ghp_aB3cD4eF5gH6iJ7kL8mN9oP0qR1sT2uV3wX4';
test('explicit save intent encrypts raw value and persists only a named reference', async () => {
  const { SecretHistory } = await import('../../desktop/electron/secret-history.mjs');
  const saved = [];
  const history = new SecretHistory({ saveSecret: async (name, value) => saved.push({ name, value }) });
  const prompt = `Save this as my Github API key: ${key}`;
  await history.prepare(prompt);
  assert.equal(saved[0].value, key); assert.equal(saved[0].name, 'github-api-key');
  assert.match(history.clean(prompt), /\[STORED:keychain:github-api-key\]/);
  assert.equal(prompt.includes(key), true);
});
test('ordinary secret pastes do not write vault records and disabled setting is explicit', async () => {
  const { SecretHistory } = await import('../../desktop/electron/secret-history.mjs');
  const history = new SecretHistory({ saveSecret: () => assert.fail('no store intent') });
  await history.prepare(key); assert.ok(!history.clean(key).includes(key));
  history.enabled = false; assert.equal(history.clean(key), key);
});

test('ordinary labeled passwords stay hidden when echoed later without their labels', async () => {
  const { SecretHistory } = await import('../../desktop/electron/secret-history.mjs');
  const history = new SecretHistory({ saveSecret: () => assert.fail('no store intent') });
  await history.prepare('password=hunter2');
  assert.ok(!history.clean({ role: 'assistant', content: 'I used hunter2 to sign in.' }).content.includes('hunter2'));
  await history.prepare(encodeURIComponent('password=another-private-password'));
  assert.ok(!history.clean('Echo another-private-password').includes('another-private-password'));
});

test('explicit named API-key intent recognizes a high-entropy value without a known vendor shape', async () => {
  const { SecretHistory } = await import('../../desktop/electron/secret-history.mjs');
  const value = 'aB3cD4eF5gH6iJ7kL8mN9oP0qR1sT2uV3wX4';
  const saved = [];
  const history = new SecretHistory({ saveSecret: async (name, value) => saved.push({ name, value }) });
  await history.prepare(`Save this as my OpenAI key: ${value}`);
  assert.deepEqual(saved, [{ name: 'openai-key', value }]);
  assert.ok(!history.clean(`Later echo ${value}`).includes(value));
});
