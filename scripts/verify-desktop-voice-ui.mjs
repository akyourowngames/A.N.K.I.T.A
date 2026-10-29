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

async function pageFor({ island = false, width = 1280, height = 850, reduced = false, fallback = false, initial = emptyVoiceState(), statusUnavailable = false } = {}) {
  const page = await browser.newPage({ viewport: { width, height }, reducedMotion: reduced ? 'reduce' : 'no-preference' });
  page.on('pageerror', error => { errors.push(error.message); console.error('VOICE_FIXTURE_PAGE_ERROR', error.message); });
  page.setDefaultTimeout(10000);
  await page.addInitScript(({ contract, version, fallback, initial, statusUnavailable }) => {
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
         if (action === 'voiceSnapshot') return statusUnavailable ? undefined : voice;
         if (action === 'voiceStatus') return statusUnavailable ? {} : { state: voice, ready: true, issues: [], microphones: [{ name: 'Headset microphone' }], microphone: '',
           outputs: [{ id: 'fixture-speakers', name: 'Laptop speakers' }, { id: 'fixture-headset', name: 'Headset output' }], defaultOutput: 'Laptop speakers', outputDevice: '' };
         if (action === 'voiceTestPlayback') return { cancelled: false };
        if (action === 'voiceStart') { window.__voicePatch({ ...voice, active: true, error: null, sessionId: 'fixture-session', threadId: payload.threadId, phase: 'listening', microphone: 'Headset microphone' }); return voice; }
        if (action === 'voicePause') { window.__voicePatch({ paused: true, phase: 'paused', inputLevel: 0 }); return voice; }
        if (action === 'voiceResume') { window.__voicePatch({ paused: false, phase: 'listening' }); return voice; }
        if (action === 'voiceEnd') { window.__voicePatch({ active: false, phase: 'idle', inputLevel: 0 }); return voice; }
        if (action === 'voiceCancel') { window.__voicePatch({ task: { ...voice.task, status: 'cancelled' } }); return voice; }
        if (action === 'voiceShowMain') { emit({ type: 'voice-focus', threadId: voice.threadId, settings: payload?.settings === true }); return voice; }
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
  }, { contract: IPC_CONTRACT, version, fallback, initial, statusUnavailable });
  await page.goto(`${target}/${island ? 'island.html' : ''}`);
  return page;
}
const patch = (page, value) => page.evaluate(value => window.__voicePatch(value), value);
const task = { id: 'fixture-task', status: 'running', steps: [{ index: 1, label: 'Write', tool: 'write_file', state: 'running' }], summary: '', error: null };

try {
  if (process.argv.includes('--settings-only')) {
    const page = await pageFor();
    await page.getByRole('button', { name: 'Start voice conversation' }).click();
    await page.getByRole('button', { name: 'Voice settings' }).click();
    const key = page.getByLabel('Sarvam API key', { exact: true });
    await key.waitFor();
    const dimensions = await key.evaluate(element => ({ width: element.getBoundingClientRect().width, field: element.closest('.settings-field')?.getBoundingClientRect().width || 0 }));
    assert.ok(dimensions.field > 0 && dimensions.width >= dimensions.field - 2, 'key input must fill an existing styled form row');
    assert.equal(await key.isDisabled(), true, 'live voice owns its setup');
    assert.equal(await page.getByRole('button', { name: 'Test speakers', exact: true }).isDisabled(), true);
    await patch(page, { active: false, phase: 'idle' });
    await page.waitForFunction(() => !document.getElementById('voice-sarvam').disabled);
    await patch(page, { active: true, phase: 'listening' });
    await page.waitForFunction(() => document.getElementById('voice-sarvam').disabled);
    await page.getByRole('button', { name: 'Close settings' }).click();
    await page.getByRole('button', { name: 'End voice', exact: true }).click();
    await page.getByRole('button', { name: 'Open settings', exact: true }).click();
    await page.getByRole('button', { name: 'Voice', exact: true }).click();
    await page.getByLabel('Speakers', { exact: true }).selectOption('fixture-speakers');
    assert.equal(await page.getByRole('button', { name: 'Test speakers', exact: true }).isDisabled(), true, 'save output before testing');
    await page.getByRole('button', { name: 'Save voice settings' }).click();
    await page.getByRole('button', { name: 'Test speakers', exact: true }).click();
    await page.getByText('Test played. If you heard nothing, choose another speaker and try again.', { exact: true }).waitFor();
    assert.ok(await page.evaluate(() => window.__voiceCalls.some(call => call.action === 'saveDesktopSettings' && call.payload?.voiceOutputDevice === 'fixture-speakers')));
    assert.ok(await page.evaluate(() => window.__voiceCalls.some(call => call.action === 'voiceTestPlayback')));
    for (const width of [1280, 620, 390]) {
      await page.setViewportSize({ width, height: 850 });
      await page.locator('.settings-scroll').evaluate(element => { element.scrollTop = 0; });
      const layout = await page.locator('.settings-content').evaluate(element => ({ width: element.clientWidth, scroll: element.scrollWidth }));
      assert.ok(layout.scroll <= layout.width, `voice settings overflow at ${width}px`);
      await page.screenshot({ path: path.join(captures, `voice-settings-${width}.png`) });
    }
    assert.deepEqual(errors, []);
    console.log('VOICE_SETTINGS_UI_OK: styled fields; saved output; honest test receipt; 1280/620/390px; zero renderer errors');
  } else {
  const main = await pageFor();
  await main.getByRole('button', { name: 'Start voice conversation' }).click();
  await main.getByText('Go ahead. I’m listening.', { exact: true }).waitFor();
  await main.locator('.voice-orb:not(.is-fallback)').waitFor();
  await main.waitForTimeout(700); await main.screenshot({ path: path.join(captures, 'voice-main-listening.png') });
  await patch(main, { phase: 'transcribing' });
  assert.equal(await main.locator('.voice-orb-process').count(), 1, 'recognizing gets a dedicated orbit');
  assert.notEqual(await main.locator('.voice-orb-process').evaluate(element => getComputedStyle(element).animationName), 'none');
  await patch(main, { phase: 'listening', inputLevel: .8 });
  await main.waitForTimeout(150);
  assert.ok(await main.locator('.voice-orb').evaluate(element => new DOMMatrix(getComputedStyle(element).transform).a > 1), 'listening responds to measured input');
  await patch(main, { inputLevel: 0 });
  await patch(main, { phase: 'working', task, caption: 'Ek chhoti si poem likho aur file mein save kar do.', captionRole: 'user', update: 'Poem likh rahi hoon, phir file save kar dungi.' });
  await main.getByRole('button', { name: 'Stop all work', exact: true }).waitFor();
  await main.getByText('Poem likh rahi hoon, phir file save kar dungi.', { exact: true }).waitFor();
  await main.waitForTimeout(700); await main.screenshot({ path: path.join(captures, 'voice-main-working.png') });
  await main.getByRole('button', { name: 'Pause microphone' }).click();
  await main.getByRole('button', { name: 'Resume microphone' }).waitFor();
  await main.getByRole('button', { name: 'Resume microphone' }).click();
  await patch(main, { phase: 'speaking', caption: 'Poem ready hai. Isi conversation mein file save kar di.', captionRole: 'assistant', task: { ...task, status: 'done' }, update: '' });
  await main.getByText('Poem ready hai. Isi conversation mein file save kar di.', { exact: true }).waitFor();
  assert.equal(await main.locator('.voice-orb-complete').count(), 1, 'successful work gets a completion pulse');
  assert.equal(await main.locator('.voice-orb-complete').evaluate(element => getComputedStyle(element).animationIterationCount), '1');
  assert.equal(await main.locator('.voice-orb canvas').evaluate(element => getComputedStyle(element).animationName), 'voice-orb-speak');
  assert.equal(await main.getByRole('button', { name: 'Stop all work', exact: true }).count(), 0);
  await main.waitForTimeout(700); await main.screenshot({ path: path.join(captures, 'voice-main-speaking.png') });
  receipt.views.push('wide main: listening, working, speaking');
  const snapshot = await main.evaluate(() => window.__voiceSnapshot());
  const island = await pageFor({ island: true, width: 640, height: 420, initial: snapshot });
  await island.getByRole('button', { name: 'End voice', exact: true }).waitFor();
  await island.locator('.voice-orb:not(.is-fallback)').waitFor();
  assert.equal(await island.locator('.voice-caption').innerText(), snapshot.caption);
  await island.waitForTimeout(700); await island.screenshot({ path: path.join(captures, 'voice-island-speaking.png') });
  const voiceFocusEnabled = await island.evaluate(() => window.__voiceCalls.some(call => call.action === 'focus-on'));
  await island.evaluate(() => window.__voiceEmit({ type: 'approval-request', threadId: 'chief', requestId: 'permission', toolName: 'Write file', detail: 'Allow this file to be saved?' }));
  await island.getByText('Allow this file to be saved?', { exact: false }).waitFor();
  assert.equal(await island.getByRole('button', { name: 'End voice', exact: true }).count(), 0);
  receipt.assertions.push('late island snapshot uses same session and exact caption; permission wins');
  await main.getByRole('button', { name: 'Continue in island' }).click();
  assert.ok(await main.evaluate(() => window.__voiceCalls.some(call => call.action === 'minimize')));
  await patch(main, { phase: 'working', task });
  await main.getByRole('button', { name: 'Stop all work', exact: true }).click();
  await main.getByText('Work stopped', { exact: true }).waitFor();
  await patch(main, { phase: 'working', task });
  await main.keyboard.press('Escape');
  await main.getByRole('button', { name: 'Start voice conversation' }).waitFor();
  const ended = await main.evaluate(() => window.__voiceSnapshot());
  assert.equal(ended.active, false); assert.equal(ended.task.status, 'running');
  receipt.assertions.push('Escape ends audio; delegated work remains running');
  await main.getByRole('button', { name: 'Start voice conversation' }).click();
  const parallel = [{ ...task, id: 'poem', label: 'Save a poem' }, { ...task, id: 'research', label: 'Research PHP', status: 'waiting_for_resource', waitingFor: 'Waiting for a shared app.' }];
  await patch(main, { phase: 'listening', task: parallel[0], jobs: parallel });
  await main.getByRole('button', { name: 'Stop Save a poem', exact: true }).click();
  assert.ok(await main.evaluate(() => window.__voiceCalls.some(call => call.action === 'voiceCancel' && call.payload?.taskId === 'poem')));
  await main.getByRole('button', { name: 'Stop all work', exact: true }).click();
  assert.ok(await main.evaluate(() => window.__voiceCalls.some(call => call.action === 'voiceCancel' && call.payload?.all === true)));
  await main.screenshot({ path: path.join(captures, 'voice-parallel-jobs.png') });
  receipt.assertions.push('separate parallel job rows, individual stop ID and explicit Stop all payload');
  await main.setViewportSize({ width: 1366, height: 768 });
  await patch(main, { caption: 'Some sources could not be read. Other findings are ready.',
    jobs: [{ ...task, id: 'long', label: 'Fetch my saved details and write them into a file, then open the document for me.' },
      { ...task, id: 'partial', label: 'Search the latest AI news and save the findings for me.', status: 'partial', summary: 'Useful findings are ready.', error: 'Some sources could not be read.' },
      { ...task, id: 'chat', label: 'Hello Ankita, how are you?', status: 'done' }] });
  const crowded = await main.locator('.voice-panel').evaluate(panel => {
    const work = panel.querySelector('.voice-work-line').getBoundingClientRect(), jobs = panel.querySelector('.voice-jobs').getBoundingClientRect(), controls = panel.querySelector('.voice-controls').getBoundingClientRect();
    return { gap: jobs.top - work.bottom, jobsBottom: jobs.bottom, controlsTop: controls.top };
  });
  assert.ok(crowded.gap >= 8, JSON.stringify(crowded));
  assert.ok(crowded.controlsTop >= crowded.jobsBottom, JSON.stringify(crowded));
  await main.waitForTimeout(700);
  await main.screenshot({ path: path.join(captures, 'voice-parallel-jobs-short-window.png') });
  await main.locator('.voice-job[data-status=partial] summary').focus();
  await main.keyboard.press('Enter');
  await main.getByText('Useful findings are ready.', { exact: true }).waitFor();
  assert.equal(await main.locator('.voice-job[data-status=partial] details[open]').count(), 1);
  await main.screenshot({ path: path.join(captures, 'voice-parallel-partial-result.png') });
  receipt.assertions.push('1366x768 long requests do not overlap; partial results open with the keyboard');
  const multiIsland = await pageFor({ island: true, width: 640, height: 420, initial: await main.evaluate(() => window.__voiceSnapshot()) });
  await multiIsland.getByRole('button', { name: 'End voice', exact: true }).waitFor();
  const compactJobs = await multiIsland.locator('.voice-panel').evaluate(panel => {
    const work = panel.querySelector('.voice-work-line').getBoundingClientRect(), jobs = panel.querySelector('.voice-jobs').getBoundingClientRect(), controls = panel.querySelector('.voice-controls').getBoundingClientRect();
    return { gap: jobs.top - work.bottom, jobsBottom: jobs.bottom, controlsTop: controls.top };
  });
  assert.ok(compactJobs.gap >= 0 && compactJobs.controlsTop >= compactJobs.jobsBottom, JSON.stringify(compactJobs));
  await multiIsland.waitForTimeout(700);
  await multiIsland.screenshot({ path: path.join(captures, 'voice-parallel-island.png') });
  for (const page of [main, multiIsland]) {
    await page.evaluate(() => window.__voiceEmit({ type: 'approval-request', requestId: 'job-B-permission', threadId: 'chief', voiceTaskId: 'job-B', toolName: 'Write file', detail: 'Allow the second voice job to save its file?' }));
    await page.getByText('Allow the second voice job to save its file?', { exact: false }).waitFor();
    await page.evaluate(() => window.__voiceEmit({ type: 'turn-end', threadId: 'chief', turnId: 'job-A', source: 'voice' }));
    assert.equal(await page.getByText('Allow the second voice job to save its file?', { exact: false }).count(), 1);
    await page.evaluate(() => window.__voiceEmit({ type: 'approval-resolved', requestId: 'job-B-permission' }));
    await page.getByText('Allow the second voice job to save its file?', { exact: false }).waitFor({ state: 'hidden' });
  }
  receipt.assertions.push('another job finishing preserves live permission; exact resolution clears both surfaces');
  await patch(main, { jobs: Array.from({ length: 6 }, (_, index) => ({ ...task, id: `many-${index}`, label: `Request ${index + 1}` })) });
  await main.getByRole('button', { name: 'Stop Request 6', exact: true }).scrollIntoViewIfNeeded();
  assert.equal(await main.getByRole('button', { name: 'Stop Request 6', exact: true }).count(), 1, 'every active job stays reachable beyond the first rows');
  await patch(main, { jobs: [], task });
  await main.keyboard.press('Escape');
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
  assert.equal(await small.locator('.voice-orb-complete').evaluate(element => getComputedStyle(element).animationName), 'none');
  const geometry = await small.locator('.voice-panel').evaluate(element => ({ client: element.clientWidth, scroll: element.scrollWidth }));
  assert.ok(geometry.scroll <= geometry.client);
  await small.screenshot({ path: path.join(captures, 'voice-narrow-reduced-fallback.png') });
  await patch(small, { active: false, phase: 'error', error: 'Microphone disconnected. Connect it and try again.' });
  assert.equal(await small.locator('.voice-orb-complete').count(), 1);
  await small.getByText('Microphone disconnected. Connect it and try again.', { exact: true }).waitFor();
  await small.getByRole('button', { name: 'Try voice again' }).waitFor();
  receipt.views.push('narrow Hindi captions, reduced motion, WebGL fallback, recoverable error');
  const still = await pageFor({ reduced: true });
  await still.getByRole('button', { name: 'Start voice conversation' }).click();
  const stillOrb = still.locator('.voice-orb:not(.is-fallback) canvas');
  await stillOrb.waitFor();
  await still.waitForTimeout(150);
  const before = await stillOrb.screenshot();
  await still.waitForTimeout(250);
  assert.deepEqual(await stillOrb.screenshot(), before, 'reduced-motion silver contours must stay still');
  receipt.assertions.push('pearl shader compiles in main/island; reduced-motion geometry stays still');
  const hiddenCue = async page => {
    await page.evaluate(() => { Object.defineProperty(document, 'hidden', { configurable: true, get: () => true }); document.dispatchEvent(new Event('visibilitychange')); });
    const orb = page.locator('.voice-panel .voice-orb');
    assert.equal(await orb.getAttribute('data-visible'), 'false');
    assert.equal(await orb.locator('.voice-orb-process').evaluate(element => getComputedStyle(element).animationPlayState), 'paused');
    await page.evaluate(() => { delete document.hidden; document.dispatchEvent(new Event('visibilitychange')); });
  };
  await patch(main, { phase: 'transcribing' });
  await hiddenCue(main);
  const fallbackMotion = await pageFor({ fallback: true, initial: { ...snapshot, phase: 'transcribing', task: null } });
  await fallbackMotion.locator('.voice-orb.is-fallback').waitFor();
  await hiddenCue(fallbackMotion);
  await patch(still, { task: { ...task, status: 'failed' } });
  assert.equal(await still.locator('.voice-orb-complete').count(), 0, 'failed work must not show success motion');
  receipt.assertions.push('real voice phases select distinct motion; only success pulses once; hidden cues pause including fallback');
  const short = await pageFor({ width: 1280, height: 703 });
  await short.getByRole('button', { name: 'Start voice conversation' }).click();
  await patch(short, { phase: 'speaking', captionRole: 'assistant', caption: 'Your poem is ready. I saved the complete file in this conversation for you to read.' });
  await short.getByText('Your poem is ready. I saved the complete file in this conversation for you to read.', { exact: true }).waitFor();
  const lines = await short.locator('.voice-caption').evaluate(element => ({ text: element.getBoundingClientRect().height, box: element.parentElement.getBoundingClientRect().height }));
  assert.ok(lines.box >= lines.text, `short-window caption clipped: ${JSON.stringify(lines)}`);
  receipt.assertions.push('short window preserves both caption lines');
  const unavailable = await pageFor({ statusUnavailable: true });
  await unavailable.getByRole('button', { name: 'Start voice conversation' }).waitFor();
  const unavailableIsland = await pageFor({ island: true, statusUnavailable: true });
  await unavailableIsland.locator('.island').waitFor();
  receipt.assertions.push('an unavailable voice snapshot cannot blank either renderer');
  const recoveryChecks = [];
  const remount = await pageFor({ initial: { ...snapshot, task } });
  await remount.locator('.chat-header').waitFor(); await remount.waitForTimeout(150);
  recoveryChecks.push({ name: 'active main remount restores end controls', ok: await remount.getByRole('button', { name: 'End voice', exact: true }).count() === 1 });
  assert.equal(await remount.evaluate(() => window.__voiceCalls.filter(call => call.action === 'voiceStart').length), 0);
  const otherOwner = await pageFor({ initial: { ...snapshot, threadId: 'other', task } });
  await otherOwner.getByRole('button', { name: 'End voice', exact: true }).waitFor();
  assert.equal(await otherOwner.locator('.header-name-line h2').innerText(), 'Studio');
  assert.ok(!await otherOwner.evaluate(() => window.__voiceCalls.some(call => call.action === 'voiceStart' || call.action === 'voiceEnd')));
  const failedIsland = await pageFor({ island: true, width: 640, height: 420, initial: { ...snapshot, active: false, phase: 'error', error: 'Microphone disconnected. Try voice again.' } });
  await failedIsland.locator('.island').waitFor(); await failedIsland.waitForTimeout(150);
  recoveryChecks.push({ name: 'island retains inactive microphone error', ok: await failedIsland.getByText('Microphone disconnected. Try voice again.', { exact: true }).count() === 1 });
  const retry = failedIsland.getByRole('button', { name: 'Try voice again', exact: true });
  recoveryChecks.push({ name: 'island retry is enabled', ok: await retry.count() === 1 && await retry.isEnabled() });
  recoveryChecks.push({ name: 'island has voice settings recovery', ok: await failedIsland.getByRole('button', { name: 'Voice settings', exact: true }).count() === 1 });
  recoveryChecks.push({ name: 'expanded voice enables native focus', ok: voiceFocusEnabled });
  assert.deepEqual(recoveryChecks.filter(check => !check.ok), []);
  await failedIsland.getByRole('button', { name: 'Voice settings', exact: true }).click();
  assert.ok(await failedIsland.evaluate(() => window.__voiceCalls.some(call => call.action === 'voiceShowMain' && call.payload?.settings === true)));
  await retry.click();
  assert.ok(await failedIsland.evaluate(() => window.__voiceCalls.some(call => call.action === 'voiceStart' && call.payload?.threadId === 'chief')));
  receipt.assertions.push('active remount, island error/retry/settings and keyboard-focus recovery');
  assert.deepEqual(errors, []);
  console.log('DESKTOP_VOICE_UI_OK', JSON.stringify({ ...receipt, pageErrors: errors.length, captures }));
  }
} finally { await browser.close(); await new Promise(resolve => server.close(resolve)); }
