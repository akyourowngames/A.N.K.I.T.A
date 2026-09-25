import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { setupUpdater } from '../../desktop/electron/updater.mjs';

function fakeUpdater() {
  const updater = new EventEmitter();
  updater.checkForUpdates = async () => true;
  updater.quitAndInstall = () => {};
  return updater;
}

test('a stopped update reports its last progress and can resume', async () => {
  const updater = fakeUpdater();
  const events = [];
  setupUpdater({ isPackaged: true, updater, stallMs: 15, emit: event => events.push(event) });
  updater.emit('update-available', { version: '2.1.0' });
  updater.emit('download-progress', { percent: 70.4 });
  await new Promise(resolve => setTimeout(resolve, 40));
  assert.deepEqual(events.find(event => event.type === 'stalled'), { type: 'stalled', percent: 70, version: '2.1.0' });
  updater.emit('download-progress', { percent: 75 });
  assert.equal(events.at(-1).type, 'progress');
  updater.emit('update-downloaded', { version: '2.1.0' });
});

test('completed and failed downloads cancel the stall notice', async () => {
  for (const terminal of ['update-downloaded', 'error']) {
    const updater = fakeUpdater();
    const events = [];
    setupUpdater({ isPackaged: true, updater, stallMs: 15, emit: event => events.push(event) });
    updater.emit('update-available', { version: '2.1.0' });
    updater.emit(terminal, terminal === 'error' ? new Error('network failed') : { version: '2.1.0' });
    await new Promise(resolve => setTimeout(resolve, 30));
    assert.equal(events.some(event => event.type === 'stalled'), false);
  }
});

test('checks are shared and do not restart an active download', async () => {
  const updater = fakeUpdater();
  let checks = 0;
  updater.checkForUpdates = async () => { checks++; await new Promise(resolve => setTimeout(resolve, 10)); return true; };
  const controller = setupUpdater({ isPackaged: true, updater, stallMs: 100 });
  await Promise.all([controller.check(), controller.check()]);
  assert.equal(checks, 1);
  updater.emit('update-available', { version: '2.1.0' });
  assert.equal(controller.isDownloading(), true);
  await controller.check();
  assert.equal(checks, 1);
  updater.emit('update-downloaded', { version: '2.1.0' });
  assert.equal(controller.isDownloading(), false);
});
