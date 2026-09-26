import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { Daemon } from '../../src/automation/daemon.mjs';
import { RoutineStore } from '../../src/automation/routines.mjs';

function daemonWith(t, extra = {}) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-daemon-reliability-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const daemon = new Daemon({
    store: new RoutineStore(path.join(dir, 'state.json')).load(),
    config: {}, client: {}, runPrompt: async () => '', deliver: async () => {},
    maxConcurrent: 1, ...extra,
  });
  t.after(() => {
    daemon.stop();
    for (const pending of daemon.pending.values()) pending.settle('no');
  });
  return daemon;
}

function deferred() {
  let resolve;
  const promise = new Promise(r => { resolve = r; });
  return { promise, resolve };
}

test('stop settles queued turns before the active turn finishes and does not start them', async t => {
  const daemon = daemonWith(t);
  const started = deferred();
  const finish = deferred();
  t.after(() => finish.resolve());
  const completed = [];
  daemon.chain('active', async () => { started.resolve(); await finish.promise; completed.push('active'); });
  await started.promise;
  let cancelledWorkRan = false;
  const queued = daemon.chain('queued', () => { cancelledWorkRan = true; });
  const sameKey = daemon.chain('active', () => { cancelledWorkRan = true; });
  await new Promise(resolve => setImmediate(resolve));
  let queuedSettled = false;
  queued.then(() => { queuedSettled = true; });
  daemon.stop();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(queuedSettled, true, 'queued permits must settle even while active work is blocked');
  assert.equal(daemon.waiting.length, 0);
  finish.resolve();
  await Promise.all([queued, sameKey, daemon.drain()]);
  assert.deepEqual(completed, ['active']);
  assert.equal(cancelledWorkRan, false, 'neither another key nor a following turn may start after stop');
  assert.equal(daemon.active, 0);
});

test('stop denies pending approvals so an active turn can drain', async t => {
  const daemon = daemonWith(t, { bot: { enabled: true, send: async () => {} } });
  let allowed;
  daemon.chain('approval', async () => { allowed = await daemon.confirmFrom('42', 'write_file', 'x'); });
  await new Promise(resolve => setImmediate(resolve));
  daemon.stop();
  await daemon.drain(100);
  assert.equal(allowed, false);
  assert.equal(daemon.pending.size, 0);
});

test('stop while sending an approval does not create a new parked approval', async t => {
  const sent = deferred();
  const daemon = daemonWith(t, { bot: { enabled: true, send: () => sent.promise } });
  const decision = daemon.confirmFrom('42', 'write_file', 'x');
  daemon.stop();
  sent.resolve();
  let settled = false;
  decision.then(() => { settled = true; });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(settled, true);
  assert.equal(await decision, false);
  assert.equal(daemon.pending.size, 0);
});

test('stop wakes the daemon tick sleep promptly', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const logs = [];
  const daemon = daemonWith(t, { tickMs: 60000, log: message => logs.push(message) });
  const ticked = deferred();
  daemon.tickOnce = async () => { ticked.resolve(); return { routines: 0, checked: 0, messages: 0 }; };
  const running = daemon.run();
  await ticked.promise;
  await new Promise(resolve => setImmediate(resolve));
  daemon.stop();
  let ended = false;
  running.then(() => { ended = true; });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(ended, true, 'shutdown must not wait for the next 60 second tick');
  await running;
  assert.ok(logs.some(message => message.startsWith('daemon stopping')));
});

test('shutdown drains an alert composition that already started', async t => {
  const started = deferred();
  const finish = deferred();
  t.after(() => finish.resolve('prepared alert'));
  const delivered = [];
  const daemon = daemonWith(t, {
    runPrompt: async () => { started.resolve(); return finish.promise; },
    deliver: async text => { delivered.push(text); },
    checker: async () => ({ value: '2', text: 'reading' }),
    now: () => new Date(Date.now() + 60000),
  });
  const watch = daemon.store.addWatch({ name: 'Metric', url: 'https://ex.test/', interval: '20s' });
  daemon.store.recordWatchCheck(watch.id, { value: '1', text: 'baseline' });
  daemon.dispatchWatches();
  await started.promise;
  await new Promise(resolve => setImmediate(resolve));
  daemon.stop();
  let drained = false;
  const draining = daemon.drain().then(() => { drained = true; });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(drained, false, 'the in-flight alert must be included in shutdown work');
  finish.resolve('prepared alert');
  await draining;
  assert.deepEqual(delivered, ['prepared alert']);
});

test('a watch finishing after stop does not start a queued alert composition', async t => {
  const started = deferred();
  const finish = deferred();
  t.after(() => finish.resolve({ value: '2', text: 'reading' }));
  let composed = false;
  const daemon = daemonWith(t, {
    runPrompt: async () => { composed = true; return 'alert'; },
    checker: async () => { started.resolve(); return finish.promise; },
    now: () => new Date(Date.now() + 60000),
  });
  const watch = daemon.store.addWatch({ name: 'Metric', url: 'https://ex.test/', interval: '20s' });
  daemon.store.recordWatchCheck(watch.id, { value: '1', text: 'baseline' });
  daemon.dispatchWatches();
  await started.promise;
  daemon.stop();
  finish.resolve({ value: '2', text: 'reading' });
  await daemon.drain();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(composed, false);
});

test('daemon CLI SIGINT drains the active turn before exiting', async t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-daemon-cli-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  fs.writeFileSync(path.join(dir, 'config.env'), 'API_BASE=http://127.0.0.1:1\nMODEL=test-model\nTOOLS=off\nMEMORY_CONSOLIDATION=off\nDESKTOP_NOTIFICATIONS=off\n');
  const script = `
    import { CompatibleClient } from ${JSON.stringify(new URL('../../src/core/provider.mjs', import.meta.url).href)};
    import { Daemon } from ${JSON.stringify(new URL('../../src/automation/daemon.mjs', import.meta.url).href)};
    import { main } from ${JSON.stringify(new URL('../../src/core/cli.mjs', import.meta.url).href)};
    globalThis.fetch = async () => { throw new Error('Network forbidden in SIGINT regression'); };
    CompatibleClient.prototype.models = async () => [{ id: 'test-model', tools: false }];
    Daemon.prototype.tickOnce = async function () {
      this.chain('in-flight', async () => {
        process.emit('SIGINT');
        await new Promise(resolve => setTimeout(resolve, 40));
        process.stdout.write('ACTIVE_TURN_DRAINED\\n');
      });
      return { routines: 1, checked: 0, messages: 0 };
    };
    process.argv = [process.execPath, 'chat.mjs', '--daemon'];
    await main();
  `;
  const child = spawn(process.execPath, ['--input-type=module', '-e', script], {
    cwd: dir,
    env: { PATH: process.env.PATH, SystemRoot: process.env.SystemRoot, TEMP: process.env.TEMP, CONFIG_DIR: dir },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  t.after(() => child.kill());
  let output = '';
  child.stdout.on('data', data => { output += data; });
  child.stderr.on('data', data => { output += data; });
  const result = await new Promise((resolve, reject) => {
    const timer = setTimeout(() => { child.kill(); reject(new Error(`CLI child timed out: ${output}`)); }, 10000);
    child.once('error', reject);
    child.once('exit', code => { clearTimeout(timer); resolve(code); });
  });
  assert.equal(result, 0, output);
  assert.match(output, /ACTIVE_TURN_DRAINED/, output);
  assert.match(output, /daemon stopping/, output);
});

test('CLI flushes the latest partial render before reporting a stream failure', async t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-cli-render-failure-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  fs.writeFileSync(path.join(dir, 'config.env'), 'API_BASE=http://127.0.0.1:1\nMODEL=test-model\nTOOLS=off\nMEMORY_CONSOLIDATION=off\nDESKTOP_NOTIFICATIONS=off\n');
  const script = `
    import { CompatibleClient } from ${JSON.stringify(new URL('../../src/core/provider.mjs', import.meta.url).href)};
    import { Agent } from ${JSON.stringify(new URL('../../src/core/agent.mjs', import.meta.url).href)};
    import { main } from ${JSON.stringify(new URL('../../src/core/cli.mjs', import.meta.url).href)};
    globalThis.fetch = async () => { throw new Error('Network forbidden in render regression'); };
    Object.defineProperty(process.stdout, 'isTTY', { value: true });
    CompatibleClient.prototype.models = async () => [{ id: 'test-model', tools: false }];
    Agent.prototype.send = async function (text, hooks) {
      hooks.onMessageStart();
      hooks.onDelta('PARTIAL');
      hooks.onDelta(' LATEST_CHUNK');
      throw new Error('STREAM_FAILURE');
    };
    process.argv = [process.execPath, 'chat.mjs', '--prompt', 'render test'];
    await main();
  `;
  const child = spawn(process.execPath, ['--input-type=module', '-e', script], {
    cwd: dir,
    env: { PATH: process.env.PATH, SystemRoot: process.env.SystemRoot, TEMP: process.env.TEMP, CONFIG_DIR: dir },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  t.after(() => child.kill());
  let output = '';
  child.stdout.on('data', data => { output += data; });
  child.stderr.on('data', data => { output += data; });
  const result = await new Promise((resolve, reject) => {
    const timer = setTimeout(() => { child.kill(); reject(new Error(`CLI child timed out: ${output}`)); }, 10000);
    child.once('error', reject);
    child.once('exit', code => { clearTimeout(timer); resolve(code); });
  });
  assert.equal(result, 0, output);
  assert.match(output, /LATEST_CHUNK/, 'pending streamed text must be flushed before exit');
  assert.ok(output.indexOf('LATEST_CHUNK') < output.indexOf('STREAM_FAILURE'), output);
});
