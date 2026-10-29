import test from 'node:test';
import assert from 'node:assert/strict';
const module = await import('../../desktop/browser-helper/connection.mjs').catch(() => null);

test('extension reconnect preserves saved credentials and has a single receiver', async () => {
  assert.ok(module, 'persistent extension connection is implemented');
  let saved = { token: 'private-test-token', helperId: 'helper', control: true };
  const calls = [], waits = [];
  const connection = new module.BrowserConnection({ load: async () => saved, save: async value => { saved = value; },
    post: async (_session, route, body, signal) => {
      calls.push({ route, body });
      if (route.endsWith('/connect')) return { sessionId: 'session' };
      if (route.endsWith('/next')) return new Promise((resolve, reject) => signal.addEventListener('abort', () => reject(signal.reason), { once: true }));
    }, execute: async () => null, schedule: callback => { waits.push(callback); return () => {}; } });
  await Promise.all([connection.wake(), connection.wake()]);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls.filter(c => c.route.endsWith('/connect')).length, 1);
  assert.equal(connection.status().connected, true);
  await connection.pause();
  assert.equal(saved.token, 'private-test-token');
  assert.equal(saved.paused, true);
  assert.equal(connection.status().connected, false);
  assert.equal(waits.length, 0);
});
test('a failed transport schedules recovery without deleting pairing or replaying an action', async () => {
  assert.ok(module, 'persistent extension connection is implemented');
  const saved = { token: 'private-test-token', helperId: 'helper', control: true }, callbacks = [];
  let executed = 0, resultPosts = 0;
  const connection = new module.BrowserConnection({ load: async () => saved, save: async () => assert.fail('connection failure must not rewrite pairing'),
    post: async (_session, route) => {
      if (route.endsWith('/connect')) return { sessionId: 'session' };
      if (route.endsWith('/next')) return { command: { id: 'request', operation: { action: 'act' } } };
      resultPosts++; throw new Error('Desktop closed after the click');
    }, execute: async () => { executed++; return 'clicked'; }, schedule: callback => { callbacks.push(callback); return () => {}; } });
  await connection.wake();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(executed, 1);
  assert.equal(resultPosts, 1);
  assert.equal(callbacks.length, 1);
  assert.equal(saved.token, 'private-test-token');
  connection.stop();
});
test('desktop Reconnect resumes a popup-paused pairing, while an ordinary restart keeps it paused', async () => {
  assert.ok(module);
  let saved = { token: 'private-test-token', helperId: 'helper', control: true, paused: true, resumeVersion: 0 };
  let resumeVersion = 0, connects = 0;
  const connection = new module.BrowserConnection({ load: async () => saved, save: async value => { saved = value; },
    post: async (_session, route, _body, signal) => {
      if (route.endsWith('/status')) return { resumeVersion };
      if (route.endsWith('/connect')) { connects++; return { sessionId: 'session', resumeVersion }; }
      return new Promise((_resolve, reject) => signal.addEventListener('abort', () => reject(signal.reason), { once: true }));
    }, execute: async () => null });
  await connection.wake(); await new Promise(resolve => setImmediate(resolve));
  assert.equal(connects, 0, 'restarting the app does not override Disconnect');
  resumeVersion++;
  await connection.wake(); await new Promise(resolve => setImmediate(resolve));
  assert.equal(connects, 1, 'an explicit desktop Reconnect releases the local pause');
  assert.equal(saved.paused, false);
  connection.stop(); await connection.running;
});
test('revoked credentials expose pairing recovery instead of claiming desktop is unavailable', async () => {
  const connection = new module.BrowserConnection({ load: async () => ({ token: 'old', control: true }), save: async () => {},
    post: async () => { throw Object.assign(new Error('Access removed'), { status: 403, code: 'browser_access_removed' }); }, execute: async () => {}, schedule: () => () => {} });
  await connection.wake(); await new Promise(resolve => setImmediate(resolve));
  assert.equal(connection.status().needsPairing, true);
  connection.stop();
});
