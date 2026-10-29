import test from 'node:test';
import assert from 'node:assert/strict';
import { Worker } from 'node:worker_threads';

const { DesktopAudioDevices } = await import('../../desktop/electron/audio-devices.mjs').catch(() => ({}));
const PROBE_MS = 150; // Controlled CPU work in a real background thread, never production device truth.
function fixture(options = {}) {
  let workers = 0;
  const requests = [];
  const createWorker = () => {
    workers++;
    const worker = new Worker(`
      const { parentPort, workerData } = require('node:worker_threads'); let scans = 0, restores = 0;
      parentPort.on('message', ({ id, op }) => {
        let value;
        if (op === 'restore' && workerData.failRestore && restores++ === 0) { parentPort.postMessage({ id, error: 'Restore interrupted' }); return; }
        if (op === 'inspect') {
          scans++; const end = Date.now() + workerData.delay;
          while (Date.now() < end) {}
          if (workerData.failFirst && scans === 1) { parentPort.postMessage({ id, error: 'Probe failed' }); return; }
          value = { sequence: scans, deps: { ffmpeg: true, ffplay: true }, microphones: [{ name: 'Fixture mic' }], devices: [], defaultRenderId: '' };
        } else if (op === 'route') value = { token: 'route-token', device: { name: 'Fixture speaker' }, receipt: { proof: 'fixture receipt' } };
        else value = true;
        parentPort.postMessage({ id, value });
      });`, { eval: true, execArgv: [], workerData: { delay: PROBE_MS, ...options } });
    const post = worker.postMessage.bind(worker);
    worker.postMessage = value => { requests.push(value.op); if (value.op === 'restore') assert.deepEqual(value.payload.receipt, { proof: 'fixture receipt' }); post(value); };
    return worker;
  };
  return { createWorker, requests, workers: () => workers };
}

test('one lazy worker shares concurrent scans, keeps the event loop responsive and caches independent results', async t => {
  const h = fixture();
  assert.equal(typeof DesktopAudioDevices, 'function');
  const devices = new DesktopAudioDevices({ createWorker: h.createWorker }); t.after(() => devices.close());
  assert.equal(h.workers(), 0);
  let ticks = 0; const timer = setInterval(() => ticks++, 10); t.after(() => clearInterval(timer));
  const [first, second] = await Promise.all([devices.inspect(), devices.inspect()]);
  assert.equal(h.workers(), 1); assert.equal(first.sequence, 1); assert.equal(second.sequence, 1);
  assert.ok(ticks >= 2, 'main-thread timers run while worker probes hardware');
  first.microphones[0].name = 'Mutated caller';
  assert.equal((await devices.inspect()).microphones[0].name, 'Fixture mic');
  devices.invalidate(); assert.equal((await devices.inspect()).sequence, 2);
  assert.equal(h.requests.filter(op => op === 'inspect').length, 2);
});

test('routing recovery data reaches a replacement worker after an unexpected exit', async t => {
  const h = fixture();
  const devices = new DesktopAudioDevices({ createWorker: h.createWorker }); t.after(() => devices.close());
  const route = await devices.route({ outputDevice: 'fixture-speaker' });
  await devices.worker.terminate();
  await route.restore();
  assert.equal(h.workers(), 2); assert.equal(devices.routes.size, 0);
});

test('a failed restore keeps its recovery receipt and can retry', async t => {
  const h = fixture({ failRestore: true });
  const devices = new DesktopAudioDevices({ createWorker: h.createWorker }); t.after(() => devices.close());
  const route = await devices.route({ outputDevice: 'fixture-speaker' });
  await assert.rejects(route.restore(), /Restore interrupted/);
  assert.equal(devices.routes.size, 1);
  await route.restore(); assert.equal(devices.routes.size, 0);
});

test('failed scans can retry and speaker routing invalidates cached defaults', async t => {
  const h = fixture({ failFirst: true });
  assert.equal(typeof DesktopAudioDevices, 'function');
  const devices = new DesktopAudioDevices({ createWorker: h.createWorker }); t.after(() => devices.close());
  await assert.rejects(devices.inspect(), /Probe failed/);
  assert.equal((await devices.inspect()).sequence, 2);
  const route = await devices.route({ outputDevice: 'fixture-speaker' });
  assert.equal(route.device.name, 'Fixture speaker');
  assert.equal((await devices.inspect()).sequence, 3);
  await route.restore(); await route.restore();
  assert.equal(h.requests.filter(op => op === 'restore').length, 1);
  await devices.close();
  await assert.rejects(devices.inspect(), /closed/i);
});
