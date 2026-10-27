import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import assert from 'node:assert/strict';
import { chromium } from 'playwright';
import { IPC_CONTRACT } from '../desktop/shared/version.mjs';
import { emptyVoiceState } from '../desktop/shared/voice.mjs';

// Local, deterministic renderer fixtures. Real cloud/audio checks are a separate script.
const root = path.resolve('desktop/renderer/dist');
const captures = path.resolve('.tmp-ui-captures');
const version = JSON.parse(fs.readFileSync('package.json', 'utf8')).version;
const MIME = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.woff2': 'font/woff2', '.woff': 'font/woff' };
fs.mkdirSync(captures, { recursive: true });
const server = http.createServer((request, response) => {
  const pathname = decodeURIComponent(new URL(request.url, 'http://localhost').pathname);
  const file = path.resolve(root, `.${pathname === '/' ? '/index.html' : pathname}`);
  if (!file.startsWith(root + path.sep)) { response.writeHead(403); response.end(); return; }
  try { response.writeHead(200, { 'content-type': MIME[path.extname(file)] || 'application/octet-stream' }); response.end(fs.readFileSync(file)); }
  catch { response.writeHead(404); response.end(); }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const target = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch({ headless: true });
const errors = [];
const receipt = { views: [], assertions: [] };

async function pageFor({ island = false, width = 1280, height = 850, reduced = false, fallback = false, initial = emptyVoiceState() } = {}) {
  const page = await browser.newPage({ viewport: { width, height }, reducedMotion: reduced ? 'reduce' : 'no-preference' });
  page.on('pageerror', error => { errors.push(error.message); console.error('VOICE_FIXTURE_PAGE_ERROR', error.message); });
  page.setDefaultTimeout(10000);
  await page.addInitScript(({ contract, version, fallback, initial }) => {
    if (fallback) {
      const original = HTMLCanvasElement.prototype.getContext;
      HTMLCanvasElement.prototype.getContext = function (type, ...args) { return String(type).includes('webgl') ? null : original.call(this, type, ...args); };
    }
    const callbacks = new Set();
    let voice = initial;
    window.__voiceCalls = [];
    const emit = event => { for (const callback of callbacks) callback(event); };
    window.__voiceEmit = emit;
    window.__voicePatch = patch => { voice = { ...voice, ...patch, revision: voice.revision + 1 }; emit({ type: 'voice-state', state: voice }); };
    window.__voiceSnapshot = () => voice;
    const teammates = [{ id: 'chief', name: 'Ankita', persona: 'Your space to think and get things done.', color: '#7aa2ff', emoji: '', projectId: null, model: null },
      { id: 'other', name: 'Studio', persona: 'A second conversation.', color: '#bfa9ff', emoji: '', projectId: null, model: null }];
    const preferences = { provider: 'kilo', model: 'fixture-model', appearance: 'graphite', profileSetupDone: true, hasSarvamKey: true, hasBasetenKey: true, hasComposioKey: true, micDevice: '' };
    const settings = { username: 'Krish', provider: 'Kilo', model: 'fixture-model', tools: [] };
    window.ankita = {
      invoke: async (action, payload) => {
        window.__voiceCalls.push({ action, payload });
        if (action === 'initialize') return { teammates, models: [{ id: 'fixture-model' }], settings, preferences, version, contract, chrome: 'native', jobs: [] };
        if (action === 'listTeammates') return teammates;
        if (action === 'voiceStatus') return { state: voice, ready: true, issues: [], microphones: [{ name: 'Headset microphone' }], microphone: '' };
        if (action === 'voiceStart') { window.__voicePatch({ ...voice, active: true, sessionId: 'fixture-session', threadId: payload.threadId, phase: 'listening', microphone: 'Headset microphone' }); return voice; }
        if (action === 'voicePause') { window.__voicePatch({ paused: true, phase: 'paused', inputLevel: 0 }); return voice; }
        if (action === 'voiceResume') { window.__voicePatch({ paused: false, phase: 'listening' }); return voice; }
        if (action === 'voiceEnd') { window.__voicePatch({ active: false, phase: 'idle', inputLevel: 0 }); return voice; }
        if (action === 'voiceCancel') { window.__voicePatch({ task: { ...voice.task, status: 'cancelled' } }); return voice; }
        if (action === 'voiceShowMain') { emit({ type: 'voice-focus', threadId: voice.threadId }); return voice; }
        if (action === 'islandSnapshot') return { teammates, threads: teammates.map(item => ({ id: item.id, running: false, messages: [] })), voice, sequence: 0 };
        if (['loadThread', 'listProjects', 'scheduleList', 'approvalList', 'skillsList', 'listSkills'].includes(action)) return [];
        if (action === 'chatGptConnectionState') return {};
        if (action === 'saveDesktopSettings') return { preferences: { ...preferences, ...payload }, settings, models: [{ id: 'fixture-model' }] };
        if (action === 'browserSessionView') return { mode: null, status: 'idle', tabs: [], step: '', screenshot: null };
        if (action === 'companionSetup') return { paired: false, connected: false };
        return {};
      },
      onEvent: callback => { callbacks.add(callback); return () => callbacks.delete(callback); },
      onMenuCommand: () => () => {}, onUpdateEvent: () => () => {}, onCaptureEvent: () => () => {}, onCursor: () => () => {},
      islandAction: async action => { window.__voiceCalls.push({ action }); return true; },
      windowAction: async action => { window.__voiceCalls.push({ action }); return true; },
      openExternal: async () => true, version: async () => version,
    };
  }, { contract: IPC_CONTRACT, version, fallback, initial });
  await page.goto(`${target}/${island ? 'island.html' : ''}`);
  return page;
}
const patch = (page, value) => page.evaluate(value => window.__voicePatch(value), value);
const task = { id: 'fixture-task', status: 'running', steps: [{ index: 1, label: 'Write', tool: 'write_file', state: 'running' }], summary: '', error: null };

try {
  const main = await pageFor();
  await main.getByRole('button', { name: 'Start voice conversation' }).click();
  await main.getByText('Go ahead. I’m listening.', { exact: true }).waitFor();
  await main.waitForTimeout(700); await main.screenshot({ path: path.join(captures, 'voice-main-listening.png') });
  await patch(main, { phase: 'working', task, caption: 'Ek chhoti si poem likho aur file mein save kar do.', captionRole: 'user', update: 'Poem likh rahi hoon, phir file save kar dungi.' });
  await main.getByRole('button', { name: 'Stop work', exact: true }).waitFor();
  await main.getByText('Poem likh rahi hoon, phir file save kar dungi.', { exact: true }).waitFor();
  await main.waitForTimeout(700); await main.screenshot({ path: path.join(captures, 'voice-main-working.png') });
  await main.getByRole('button', { name: 'Pause microphone' }).click();
  await main.getByRole('button', { name: 'Resume microphone' }).waitFor();
  await main.getByRole('button', { name: 'Resume microphone' }).click();
  await patch(main, { phase: 'speaking', caption: 'Poem ready hai. Isi conversation mein file save kar di.', captionRole: 'assistant', task: { ...task, status: 'done' }, update: '' });
  await main.getByText('Poem ready hai. Isi conversation mein file save kar di.', { exact: true }).waitFor();
  assert.equal(await main.getByRole('button', { name: 'Stop work', exact: true }).count(), 0);
  await main.waitForTimeout(700); await main.screenshot({ path: path.join(captures, 'voice-main-speaking.png') });
  receipt.views.push('wide main: listening, working, speaking');
  const snapshot = await main.evaluate(() => window.__voiceSnapshot());
  const island = await pageFor({ island: true, width: 640, height: 420, initial: snapshot });
  await island.getByRole('button', { name: 'End voice', exact: true }).waitFor();
  assert.equal(await island.locator('.voice-caption').innerText(), snapshot.caption);
  await island.waitForTimeout(700); await island.screenshot({ path: path.join(captures, 'voice-island-speaking.png') });
  await island.evaluate(() => window.__voiceEmit({ type: 'approval-request', threadId: 'chief', requestId: 'permission', toolName: 'Write file', detail: 'Allow this file to be saved?' }));
  await island.getByText('Allow this file to be saved?', { exact: false }).waitFor();
  assert.equal(await island.getByRole('button', { name: 'End voice', exact: true }).count(), 0);
  receipt.assertions.push('late island snapshot uses same session and exact caption; permission wins');
  await main.getByRole('button', { name: 'Continue in island' }).click();
  assert.ok(await main.evaluate(() => window.__voiceCalls.some(call => call.action === 'minimize')));
  await patch(main, { phase: 'working', task });
  await main.getByRole('button', { name: 'Stop work', exact: true }).click();
  await main.getByText('Work stopped', { exact: true }).waitFor();
  await patch(main, { phase: 'working', task });
  await main.keyboard.press('Escape');
  await main.getByRole('button', { name: 'Start voice conversation' }).waitFor();
  const ended = await main.evaluate(() => window.__voiceSnapshot());
  assert.equal(ended.active, false); assert.equal(ended.task.status, 'running');
  receipt.assertions.push('Escape ends audio; delegated work remains running');
  await main.getByRole('button', { name: 'Start voice conversation' }).click();
  await main.getByText('Studio', { exact: true }).click();
  await main.getByRole('button', { name: 'Start voice conversation' }).waitFor();
  assert.equal(await main.evaluate(() => window.__voiceSnapshot().active), false);
  await patch(main, { active: true, threadId: 'chief', phase: 'listening' });
  await main.evaluate(() => window.__voiceEmit({ type: 'voice-focus', threadId: 'chief' }));
  await main.getByRole('button', { name: 'End voice', exact: true }).waitFor();
  receipt.assertions.push('switching conversations ends voice; island focus restores its original conversation');
  await main.getByRole('button', { name: 'Voice settings' }).click();
  await main.getByLabel('Sarvam API key', { exact: true }).waitFor();
  assert.equal(await main.getByLabel('Sarvam API key', { exact: true }).inputValue(), '');
  receipt.assertions.push('voice settings discoverable with empty password fields');
  const small = await pageFor({ width: 620, height: 720, reduced: true, fallback: true });
  await small.getByRole('button', { name: 'Start voice conversation' }).click();
  await patch(small, { phase: 'speaking', captionRole: 'assistant', caption: 'आपकी कविता तैयार है। मैंने उसे इसी बातचीत में सुरक्षित कर दिया है। आप अपना बाकी काम जारी रख सकते हैं।', task: { ...task, status: 'done' } });
  await small.getByText('आपकी कविता तैयार है। मैंने उसे इसी बातचीत में सुरक्षित कर दिया है। आप अपना बाकी काम जारी रख सकते हैं।', { exact: true }).waitFor();
  await small.locator('.voice-orb.is-fallback').waitFor();
  assert.equal(await small.locator('.voice-caption span').first().evaluate(element => getComputedStyle(element).animationName), 'none');
  const geometry = await small.locator('.voice-panel').evaluate(element => ({ client: element.clientWidth, scroll: element.scrollWidth }));
  assert.ok(geometry.scroll <= geometry.client);
  await small.screenshot({ path: path.join(captures, 'voice-narrow-reduced-fallback.png') });
  await patch(small, { active: false, phase: 'error', error: 'Microphone disconnected. Connect it and try again.' });
  await small.getByText('Microphone disconnected. Connect it and try again.', { exact: true }).waitFor();
  await small.getByRole('button', { name: 'Try voice again' }).waitFor();
  receipt.views.push('narrow Hindi captions, reduced motion, WebGL fallback, recoverable error');
  const short = await pageFor({ width: 1280, height: 703 });
  await short.getByRole('button', { name: 'Start voice conversation' }).click();
  await patch(short, { phase: 'speaking', captionRole: 'assistant', caption: 'Your poem is ready. I saved the complete file in this conversation for you to read.' });
  await short.getByText('Your poem is ready. I saved the complete file in this conversation for you to read.', { exact: true }).waitFor();
  const lines = await short.locator('.voice-caption').evaluate(element => ({ text: element.getBoundingClientRect().height, box: element.parentElement.getBoundingClientRect().height }));
  assert.ok(lines.box >= lines.text, `short-window caption clipped: ${JSON.stringify(lines)}`);
  receipt.assertions.push('short window preserves both caption lines');
  assert.deepEqual(errors, []);
  console.log('DESKTOP_VOICE_UI_OK', JSON.stringify({ ...receipt, pageErrors: errors.length, captures }));
} finally { await browser.close(); await new Promise(resolve => server.close(resolve)); }
