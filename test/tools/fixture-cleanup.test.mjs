import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const cleanup = await import('../helpers/fixture-cleanup.mjs').catch(() => ({}));

test('shared fixture cleanup yields while asynchronous removal retries released native handles', async t => {
  assert.equal(typeof cleanup.removeFixtureDirectory, 'function');
  let completed = false;
  t.mock.method(fs, 'rmSync', () => assert.fail('fixture cleanup must leave the event loop free'));
  t.mock.method(fs.promises, 'rm', async (directory, options) => {
    assert.equal(directory, 'fixture-directory');
    assert.equal(options.recursive, true);
    assert.equal(options.force, true);
    assert.ok(Number.isSafeInteger(options.maxRetries) && options.maxRetries > 0);
    assert.ok(Number.isSafeInteger(options.retryDelay) && options.retryDelay > 0);
    await new Promise(resolve => setImmediate(resolve));
    completed = true;
  });
  const pending = cleanup.removeFixtureDirectory('fixture-directory');
  assert.equal(completed, false);
  await pending;
  assert.equal(completed, true);
});
