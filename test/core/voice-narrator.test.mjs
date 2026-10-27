import test from 'node:test';
import assert from 'node:assert/strict';
const api = await import('../../src/core/voice-narrator.mjs').catch(() => ({}));

test('progress is generated from the request and observed action without raw content or credentials', async t => {
  let body;
  t.mock.method(globalThis, 'fetch', async (_url, options) => {
    body = JSON.parse(options.body);
    return Response.json({ choices: [{ message: { reasoning_content: 'Private planning', content: "I'm writing your poem now." } }] });
  });
  const narrate = api.createVoiceNarrator({ client: { baseUrl: 'https://fixture.invalid', headers: () => ({}), requestDefaults: { max_tokens: 1024, reasoning_effort: 'low' } }, model: 'voice-model' });
  const line = await narrate({ kind: 'step', transcript: 'Write a poem', call: { function: { name: 'write_file', arguments: JSON.stringify({ path: 'poem.txt', content: 'private file body', api_key: 'fixture-secret' }) } } });
  assert.equal(line, "I'm writing your poem now.");
  assert.equal(body.model, 'voice-model');
  assert.equal(body.reasoning_effort, 'low');
  assert.equal(body.tools, undefined);
  assert.ok(body.messages[1].content.includes('write_file'));
  assert.ok(!JSON.stringify(body).includes('private file body'));
  assert.ok(!JSON.stringify(body).includes('fixture-secret'));
});

test('a long task gets a generated waiting update; failed narration stays silent', async t => {
  t.mock.method(globalThis, 'fetch', async (_url, options) => {
    const body = JSON.parse(options.body);
    assert.match(body.messages[1].content, /waiting/);
    assert.equal(body.reasoning_effort, undefined, 'generic providers do not inherit Baseten-only fields');
    return Response.json({ choices: [{ message: { content: "I'm still working on your poem and will tell you when it's ready." } }] });
  });
  const narrate = api.createVoiceNarrator({ client: { baseUrl: 'https://fixture.invalid', headers: () => ({}) }, model: 'voice-model' });
  assert.match(await narrate({ kind: 'waiting', transcript: 'Write a poem', elapsedMs: 10000 }), /still working/);
  t.mock.method(globalThis, 'fetch', async () => new Response('offline', { status: 503 }));
  assert.equal(await narrate({ kind: 'waiting', transcript: 'Write a poem' }), '');
});
