import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createServer } from 'vite';
import { chromium } from 'playwright';
import { DesktopVoice } from '../../desktop/electron/voice.mjs';
import { runVoiceAction } from '../../desktop/electron/voice-actions.mjs';

const ROOT = fileURLToPath(new URL('../../desktop/renderer/', import.meta.url));
const ROUTE = '/voice-controls-preview'; // Local renderer with real voice IPC dispatcher and injected hardware only.
const UI_WAIT_MS = 5000; // Milliseconds: fail boundedly when controls do not appear.
const SENTENCE = 'The note is ready.';

async function openPreview(t, compact) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'voice-controls-ui-'));
  const config = { provider: 'custom', voiceProvider: 'baseten', basetenApiKey: 'fixture-planner', sarvamApiKey: 'fixture-speech',
    voiceTaskLimit: 20, voiceMaxParallelJobs: 2, voiceBargeIn: false, voiceHfpRouting: false, voiceWakeWord: false,
    voiceSilenceMs: 800, voiceMaxUtteranceMs: 100000, voiceSpeechGapMs: 0, voiceSpeakMaxChars: 1200 };
  let plannerCalls = 0, page;
  const actions = [], played = [], errors = [];
  const engine = { listTeammates: () => [{ id: 'owner' }], captureVoiceContext: () => ({}),
    runVoiceJob: async () => { plannerCalls++; return { text: SENTENCE, error: null }; }, deliverVoiceJob: async () => {} };
  const voice = new DesktopVoice({ engine, directory, getConfig: () => config,
    emit: event => { if (page) void page.evaluate(event => window.voiceListeners?.forEach(listener => listener(event)), event).catch(() => {}); },
    io: { audioDeps: async () => ({ ffmpeg: true, ffplay: true }), listMicrophones: async () => [{ name: 'Fixture mic' }],
      listAudioDevices: async () => [{ id: 'speaker', name: 'Fixture speaker', flow: 'render' }], getDefaultRenderId: async () => 'speaker',
      openVoiceInput: ({ outFile }) => { fs.writeFileSync(outFile, 'fixture'); return { ready: Promise.resolve(), stop: async () => true }; },
      synthesizeSarvam: async ({ text }) => Buffer.from(text), narrate: async () => '', stopPlayback: () => {},
      playMp3: async (audio, { signal }) => { played.push(audio.toString()); if (audio.toString() === SENTENCE && !signal.aborted) await new Promise(resolve => signal.addEventListener('abort', resolve, { once: true })); },
    } });
  engine.voice = () => voice;
  await voice.start({ threadId: 'owner' });
  const vite = await createServer({ configFile: false, root: ROOT, define: { __ANKITA_VERSION__: JSON.stringify('0.0.0-test') }, server: { middlewareMode: true, hmr: false }, appType: 'custom' });
  const server = http.createServer(async (req, res) => {
    if (req.url !== ROUTE) return vite.middlewares(req, res);
    res.setHeader('content-type', 'text/html');
    res.end(await vite.transformIndexHtml(ROUTE, `<!doctype html><html data-theme="graphite"><body><div id="root"></div><script type="module">
      import React from 'react'; import {createRoot} from 'react-dom/client';
      import {VoicePanel} from '/src/components/voice/VoicePanel.tsx'; import {useVoice} from '/src/components/voice/useVoice.ts';
      import '/src/styles.css'; window.voiceListeners = [];
      window.ankita = { invoke: (action, payload) => window.invokeVoice(action, payload), onEvent: listener => { window.voiceListeners.push(listener); return () => { window.voiceListeners = window.voiceListeners.filter(item => item !== listener); }; } };
      function Preview() { const voice = useVoice(); return React.createElement(VoicePanel, { compact: ${JSON.stringify(compact)}, voice: voice.state, busy: voice.busy, error: voice.error,
        onEnd: voice.end, onPause: voice.pause, onResume: voice.resume, onCancel: voice.cancel, onSpeech: voice.speech }); }
      createRoot(document.getElementById('root')).render(React.createElement(Preview));
    </script></body></html>`));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({ headless: true });
  t.after(async () => { page = null; await voice.close(); await browser.close(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); await vite.close(); fs.rmSync(directory, { recursive: true, force: true }); });
  page = await browser.newPage({ viewport: compact ? { width: 480, height: 650 } : { width: 1000, height: 835 } });
  page.setDefaultTimeout(UI_WAIT_MS);
  page.on('pageerror', error => errors.push(error.message));
  await page.exposeFunction('invokeVoice', async (action, payload) => { actions.push({ action, payload }); return runVoiceAction({ engine, action, payload }); });
  await page.goto(`http://127.0.0.1:${server.address().port}${ROUTE}`);
  await page.getByRole('button', { name: 'Pause microphone', exact: true }).waitFor();
  await voice.delegate(voice.current, { text: 'Prepare my note', languageCode: 'en-IN', speechTurn: voice.current.speech.turn });
  return { page, voice, actions, played, errors, plannerCalls: () => plannerCalls };
}

for (const compact of [false, true]) test(`voice report buttons round-trip through real service ownership (compact=${compact})`, async t => {
  const h = await openPreview(t, compact);
  await h.page.waitForFunction(sentence => document.querySelector('.voice-caption')?.textContent === sentence, SENTENCE);
  await h.page.getByRole('button', { name: 'Stop speaking', exact: true }).waitFor();
  await h.page.getByText('Listening pauses during replies. Use Stop speaking.', { exact: true }).waitFor();
  if (process.env.ANKITA_UI_CAPTURE_DIR) {
    fs.mkdirSync(process.env.ANKITA_UI_CAPTURE_DIR, { recursive: true });
    await h.page.screenshot({ path: path.join(process.env.ANKITA_UI_CAPTURE_DIR, `voice-controls-${compact ? 'island' : 'main'}.png`) });
  }
  await h.page.getByRole('button', { name: 'Stop speaking', exact: true }).click();
  await h.page.getByRole('button', { name: 'Continue report', exact: true }).waitFor();
  assert.equal(h.voice.snapshot().speech.reports[0].state, 'suspended');
  assert.equal(h.voice.jobs.list('owner')[0].status, 'done');
  await h.page.getByRole('button', { name: 'Continue report', exact: true }).click();
  await h.page.waitForFunction(() => document.querySelector('[aria-label="Skip report"]') != null);
  await h.page.getByRole('button', { name: 'Skip report', exact: true }).click();
  await h.page.getByRole('button', { name: 'Skip report', exact: true }).waitFor({ state: 'hidden' });
  assert.equal(h.voice.snapshot().speech.reports[0].state, 'dismissed');
  await h.page.getByRole('button', { name: 'Repeat report', exact: true }).click();
  await h.page.getByRole('button', { name: 'Stop speaking', exact: true }).waitFor();
  await h.page.getByRole('button', { name: 'Pause microphone', exact: true }).click();
  await h.page.getByText('Microphone is off. Use Resume microphone to listen again.', { exact: true }).waitFor();
  assert.equal(h.voice.snapshot().paused, true);
  await h.page.getByRole('button', { name: 'Resume microphone', exact: true }).click();
  await h.page.getByRole('button', { name: 'Pause microphone', exact: true }).waitFor();
  assert.equal(h.voice.snapshot().paused, false);
  assert.equal(h.plannerCalls(), 1, 'all controls reuse one original task without planner calls');
  assert.ok(h.actions.filter(item => item.action === 'voiceSpeechControl').length >= 4);
  assert.deepEqual(h.errors, []);
});

test('a suspended report stays selectable ahead of another queued result', async t => {
  const h = await openPreview(t, false);
  await h.page.waitForFunction(sentence => document.querySelector('.voice-caption')?.textContent === sentence, SENTENCE);
  const originalId = h.voice.snapshot().speech.reports[0].id;
  await h.voice.delegate(h.voice.current, { text: 'Other note', languageCode: 'en-IN', speechTurn: h.voice.current.speech.turn });
  await h.page.getByRole('button', { name: 'Stop speaking', exact: true }).click();
  await h.page.getByRole('button', { name: 'Continue report', exact: true }).waitFor();
  await h.page.getByRole('button', { name: 'Continue report', exact: true }).click();
  await h.page.getByRole('button', { name: 'Stop speaking', exact: true }).waitFor();
  const control = h.actions.filter(item => item.action === 'voiceSpeechControl').at(-1);
  assert.equal(control.payload.id, originalId);
  assert.equal(h.plannerCalls(), 2);
});

test('voice surface shows observed streaming latency and honest buffered recognition/fallback', async t => {
  const h = await openPreview(t, false);
  await h.page.getByText('Replies are buffered. Words appear after you pause.', { exact: true }).waitFor();
  await h.page.getByTitle('This audio runtime uses buffered speech.', { exact: true }).waitFor();
  h.voice.publish(h.voice.current, { delivery: { mode: 'streaming', fallback: '', firstChunkMs: 128 } });
  await h.page.getByText('Streaming replies. Words appear after you pause. Last first audio: 128 ms.', { exact: true }).waitFor();
  h.voice.publish(h.voice.current, { delivery: { mode: 'buffered', fallback: 'provider', firstChunkMs: 256 } });
  await h.page.getByTitle('The speech service did not accept streaming; buffered speech is available.', { exact: true }).waitFor();
  assert.deepEqual(h.errors, []);
});
