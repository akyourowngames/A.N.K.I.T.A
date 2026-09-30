import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { performance } from 'node:perf_hooks';

const moduleUrl = new URL('../../src/security/secret-scrubber.mjs', import.meta.url);
const fakeToken = 'aB3cD4eF5gH6iJ7kL8mN9oP0qR1sT2uV3wX4';
const shaped = [
  `AKIA${'A1B2C3D4'.repeat(2)}`, `ghp_${fakeToken}`, `gho_${fakeToken}`, `github_pat_${fakeToken}`,
  `xoxb-${fakeToken}`, `xoxp-${fakeToken}`, `sk_live_${fakeToken}`, `Bearer ${fakeToken}`,
  `-----BEGIN RSA PRIVATE KEY-----\n${fakeToken}\n-----END RSA PRIVATE KEY-----`,
  `postgresql://alice:${fakeToken}@host.test/db`, `mongodb+srv://alice:${fakeToken}@host.test/db`,
  `OPENAI_API_KEY=${fakeToken}`, `{"token":"${fakeToken}"}`, 'password = "hunter2"',
  `{"private_key":"-----BEGIN PRIVATE KEY-----\\n${fakeToken}\\n-----END PRIVATE KEY-----"}`,
];
const corpus = [...shaped, ...shaped.map(encodeURIComponent), ...shaped.map(value => Buffer.from(value).toString('base64')),
  `apikey:'${fakeToken}'`, `secret=${fakeToken}`, `passwd=hunter2`, `pwd: "hunter2"`, `api_key=${fakeToken}`];

test('secret scrubber catches 50 shaped, labeled and encoded fake samples with stable ranges', async () => {
  assert.ok(fs.existsSync(moduleUrl), 'secret scrubber module exists');
  const { detect, redact, containsSecret } = await import(moduleUrl.href);
  assert.equal(corpus.length, 50);
  for (const sample of corpus) {
    const text = `Here is a test: ${sample} end.`;
    assert.equal(containsSecret(text), true, sample);
    const hits = detect(text);
    assert.ok(hits.length, sample);
    for (const hit of hits) assert.ok(hit.start >= 0 && hit.end > hit.start && hit.end <= text.length);
    const clean = redact(text);
    assert.notEqual(clean, text, sample);
    assert.equal(redact(clean), clean, 'redaction is idempotent');
    assert.ok(!clean.includes(sample), sample);
  }
});
test('normal conversation has zero false positives and typical messages average below one millisecond', async () => {
  const { redact } = await import(moduleUrl.href);
  const normal = ['Please remind me at 9 tomorrow.', 'How do I reset my password?', 'Use the token count to estimate cost.', 'I need a secret birthday surprise.', 'The API_KEY variable is missing.', 'Discuss the Bearer authentication scheme.', 'Show me a connection string example without credentials.', 'Schedule weekly performance analysis.'];
  for (const value of normal) assert.equal(redact(value), value);
  assert.ok(!redact('DB_PASSWORD=hunter2').includes('hunter2'));
  const repetitions = 1000; // Amortized benchmark reduces timer noise on Windows.
  const start = performance.now();
  for (let i = 0; i < repetitions; i++) redact(normal.join('\n'));
  assert.ok((performance.now() - start) / repetitions < 1);
});
test('session and immutable journal writes scrub copied tool output while live data remains raw', async t => {
  const { saveSession, recordTurn } = await import('../../src/core/sessions.mjs');
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'scrubber-persist-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const secret = `ghp_${fakeToken}`;
  const data = { messages: [{ role: 'user', content: secret }, { role: 'tool', content: JSON.stringify({ token: fakeToken }) }] };
  const file = path.join(dir, 'session.json');
  saveSession(file, data);
  assert.ok(!fs.readFileSync(file, 'utf8').includes(secret));
  assert.ok(!fs.readFileSync(file, 'utf8').includes(fakeToken));
  assert.equal(data.messages[0].content, secret);
  const journal = recordTurn({ text: secret, reply: secret }, { journalDir: dir });
  assert.ok(!fs.readFileSync(journal, 'utf8').includes(secret));
});

test('migration scrubs JSON and exports, is repeatable, and never traverses symlinks or config files', async t => {
  const { migrateSecrets } = await import('../../src/security/secret-migration.mjs');
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'scrubber-migrate-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const secret = `ghp_${fakeToken}`;
  const transcripts = path.join(dir, 'sessions'); fs.mkdirSync(transcripts);
  fs.writeFileSync(path.join(transcripts, 'old.json'), JSON.stringify({ messages: [{ content: secret }] }));
  fs.writeFileSync(path.join(transcripts, 'export.md'), secret);
  fs.writeFileSync(path.join(dir, 'settings.json'), secret);
  const privateDirectory = path.join(dir, 'private'); fs.mkdirSync(privateDirectory); fs.writeFileSync(path.join(privateDirectory, 'secret.json'), secret);
  fs.symlinkSync(privateDirectory, path.join(transcripts, 'linked-private'), process.platform === 'win32' ? 'junction' : 'dir');
  fs.writeFileSync(path.join(transcripts, 'damaged.json'), `{\"content\":\"${secret}\"`);
  const first = migrateSecrets({ roots: [transcripts] });
  assert.equal(first.redactions, 3); assert.equal(first.changedFiles, 3);
  assert.equal(migrateSecrets({ roots: [transcripts] }).redactions, 0);
  assert.equal(fs.readFileSync(path.join(dir, 'settings.json'), 'utf8'), secret);
  assert.equal(fs.readFileSync(path.join(privateDirectory, 'secret.json'), 'utf8'), secret);
});
