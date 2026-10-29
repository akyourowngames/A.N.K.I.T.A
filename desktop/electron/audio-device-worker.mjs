import { parentPort } from 'node:worker_threads';
import { randomUUID } from 'node:crypto';
import { AUDIO_DEVICE_OPS as OPS, AUDIO_OUTPUT_CHANGED } from '../shared/audio-devices.mjs';
import { audioDeps, listMicrophones } from '../../src/channels/voice.mjs';
import { listAudioDevices, getDefaultRenderId, usePlaybackDevice, useHandsFreePlayback, restorePlaybackDevice, watchAudioOutput } from '../../src/channels/audio-device.mjs';

const routes = new Map();
let monitor;
let queue = Promise.resolve(); // Serialize OS switches so a close/restore cannot overtake a pending switch.
async function execute(op, payload) {
  if (op === OPS.inspect) {
    const deps = audioDeps();
    const microphones = deps.ffmpeg ? await listMicrophones().catch(() => []) : [];
    let devices = [], defaultRenderId = '', outputError = '';
    try { devices = listAudioDevices(); defaultRenderId = getDefaultRenderId(); }
    catch (error) { outputError = error.message; }
    return { deps, microphones, devices, defaultRenderId, outputError };
  }
  if (op === OPS.route) {
    const route = payload.outputDevice ? usePlaybackDevice(payload.outputDevice) : payload.hfp ? useHandsFreePlayback(payload.microphone) : null;
    if (!route) return null;
    const token = randomUUID(); routes.set(token, route);
    return { token, device: route.device, receipt: route.receipt };
  }
  if (op === OPS.restore) {
    const route = routes.get(payload.token); routes.delete(payload.token);
    if (route) return route.restore();
    if (payload.receipt) return restorePlaybackDevice(payload.receipt);
    throw new Error('Audio routing receipt was lost. Check your Windows output settings.');
  }
  if (op === OPS.watch) {
    await monitor?.stop();
    monitor = watchAudioOutput(() => parentPort.postMessage({ event: AUDIO_OUTPUT_CHANGED }));
    return await monitor.ready;
  }
  if (op === OPS.unwatch) {
    await monitor?.stop(); monitor = null; return true;
  }
  if (op === OPS.close) {
    await monitor?.stop(); monitor = null;
    for (const route of [...routes.values()].reverse()) route.restore();
    routes.clear(); return true;
  }
  throw new Error('Unknown audio device operation.');
}
parentPort.on('message', ({ id, op, payload }) => {
  queue = queue.then(async () => {
    try { parentPort.postMessage({ id, value: await execute(op, payload) }); }
    catch (error) { parentPort.postMessage({ id, error: error.message }); }
  });
});
