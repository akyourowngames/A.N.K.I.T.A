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
  assert.equal(body.max_tokens, 1024, 'optional narration must not inherit the full file-generation budget');
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

test('narration distinguishes confirmed saving from a pending app launch without leaking arguments', async t => {
  let data, prompt;
  t.mock.method(globalThis, 'fetch', async (_url, options) => {
    const body = JSON.parse(options.body); data = JSON.parse(body.messages[1].content); prompt = body.messages[0].content;
    return Response.json({ choices: [{ message: { content: 'Your poem is saved; I am launching Notepad.' } }] });
  });
  const narrate = api.createVoiceNarrator({ client: { baseUrl: 'https://fixture.invalid', headers: () => ({}) }, model: 'voice-model' });
  await narrate({ kind: 'step', phase: 'started', transcript: 'Save a poem and open it',
    call: { function: { name: 'run_command', arguments: JSON.stringify({ command: 'notepad "private/poem.txt" secret=DO_NOT_SEND', background: true }) } },
    steps: [{ tool: 'write_file', state: 'done', target: 'poem.txt', confirmation: 'confirmed' }],
    previousUpdate: 'I am saving your poem.' });
  assert.equal(data.action.program, 'notepad');
  assert.equal(data.action.background, true);
  assert.equal(data.phase, 'started');
  assert.equal(data.steps[0].confirmation, 'confirmed');
  assert.equal(data.steps[0].target, 'poem.txt');
  assert.equal(data.previousUpdate, 'I am saving your poem.');
  assert.ok(!JSON.stringify(data).includes('DO_NOT_SEND'));
  assert.ok(!JSON.stringify(data).includes('private/'));
  assert.match(prompt, /background/i);
});
