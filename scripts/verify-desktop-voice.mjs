import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import assert from 'node:assert/strict';
import { _electron as electron } from 'playwright';

// Real Sarvam STT/TTS + Meta planner + filesystem tools in actual Electron.
// Input is generated speech, and the player records a handoff rather than playing it aloud.
const ROOT = fileURLToPath(new URL('..', import.meta.url));
const ENV_FLAG = '--env';
const envIndex = process.argv.indexOf(ENV_FLAG);
const envPath = path.resolve(envIndex < 0 ? '.env' : process.argv[envIndex + 1]);
const TIMEOUT_MS = 120000; // Milliseconds: real cloud requests and multi-step tool execution.
const POLL_MS = 100; // Milliseconds: lifecycle polling, independent of real microphone VAD.
const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-desktop-voice-'));
const configDirectory = path.join(directory, 'config');
const captures = path.join(ROOT, '.tmp-ui-captures');
fs.mkdirSync(configDirectory); fs.mkdirSync(captures, { recursive: true });
const harnessFile = path.join(directory, 'voice-main.cjs');
fs.writeFileSync(harnessFile, `
const path = require('node:path'), fs = require('node:fs');
const root = process.env.VOICE_VERIFY_ROOT, directory = process.env.VOICE_VERIFY_DIRECTORY;
const scopedRequire = require('node:module').createRequire(path.join(root, 'package.json'));
const { app, BrowserWindow, ipcMain } = scopedRequire('electron');
app.setPath('userData', path.join(directory, 'user-data'));
const url = require('node:url');
const load = file => import(url.pathToFileURL(path.join(root, file)).href);
(async () => {
 await app.whenReady();
 const { loadConfig } = await load('src/core/config.mjs');
 const { DesktopEngine } = await load('desktop/electron/engine.mjs');
 const { DesktopVoice } = await load('desktop/electron/voice.mjs');
 const { runVoiceAction } = await load('desktop/electron/voice-actions.mjs');
 const { VOICE_ACTIONS } = await load('desktop/shared/voice.mjs');
 const { IPC_CONTRACT } = await load('desktop/shared/version.mjs');
 const channel = await load('src/channels/voice.mjs');
 const version = scopedRequire('./package.json').version;
 const config = { ...loadConfig(process.env.VOICE_VERIFY_ENV), memoryConsolidation: false, projectInlineConsolidation: false,
   autoApprove: true, voiceHfpRouting: false, voiceBargeIn: false, memoryRecall: false, subagentsEnabled: false };
 if (!config.sarvamApiKey || !config.basetenApiKey) throw new Error('Set Sarvam and Baseten keys locally before the real desktop check.');
 const request = 'Ek chhoti si kavita likho aur file mein save karo.';
 const source = await channel.synthesizeSarvam({ apiKey: config.sarvamApiKey, model: config.sarvamTtsModel,
   speaker: channel.resolveSarvamSpeaker(config, 'hi-IN'), languageCode: 'hi-IN', text: request });
 const wav = await channel.convertAudio(source, { to: 'wav' });
 const workspace = path.join(directory, 'workspace'); fs.mkdirSync(workspace);
 const state = globalThis.voiceVerification = { inputs: [], events: [], playedBytes: [], windows: [], ready: false };
 const engine = state.engine = new DesktopEngine({ config, settingsFile: path.join(configDirectory(), 'settings.json'),
   teammateFile: path.join(configDirectory(), 'teammates.json'), sessionsDir: path.join(configDirectory(), 'sessions'),
   channelsFile: path.join(configDirectory(), 'channels.json'), projectsFile: path.join(configDirectory(), 'projects.json'),
   credentialFile: path.join(configDirectory(), 'credentials.json'), composioFile: path.join(configDirectory(), 'composio.json'),
   composioGrantsFile: path.join(configDirectory(), 'grants.json'),
   bootstrap: async () => ({ client: {}, model: 'typed-verification', models: [{ id: 'typed-verification', tools: true }], provider: { name: 'kilo' } }),
   mcp: { reconcile: async () => {}, closeAll: async () => {}, summaries: () => [], specs: () => [], alwaysOnIds: () => [], toolsFor: () => [], connectedIds: [], has: () => false },
   emit: event => { state.events.push(event); for (const window of state.windows) if (!window.isDestroyed()) window.webContents.send('engine:event', event); } });
 function configDirectory() { return process.env.CONFIG_DIR; }
 await engine.init(); engine.desktopSettings.update({ profileSetupDone: true });
 const project = engine.createProject({ name: 'Disposable voice check', path: workspace });
 const id = state.threadId = engine.listTeammates()[0].id;
 for (const teammate of engine.listTeammates()) engine.assignProject(teammate.id, project.id);
 engine._voice = new DesktopVoice({ engine, getConfig: () => engine.config, emit: event => engine.emit(event), directory: path.join(configDirectory(), 'voice-tasks'),
   io: { listMicrophones: async () => [{ name: 'Generated speech fixture (no microphone)' }],
     openVoiceInput(options) { fs.writeFileSync(options.outFile, wav); const first = state.inputs.length === 0; const input = { options, stopped: false, ready: Promise.resolve(), stop: async () => { input.stopped = true; return first; } }; state.inputs.push(input); return input; },
     playMp3: async (audio, { signal } = {}) => { if (!signal?.aborted) state.playedBytes.push(audio.length); }, stopPlayback() {}, narrate: async () => '' } });
 const main = state.main = new BrowserWindow({ show: true, width: 1280, height: 850, webPreferences: { preload: path.join(root, 'desktop/electron/preload.cjs'), contextIsolation: true, sandbox: true, nodeIntegration: false, backgroundThrottling: false } });
 state.windows.push(main);
 ipcMain.handle('engine:invoke', async (event, action, payload) => {
   if (!state.windows.some(window => window.webContents === event.sender) || event.senderFrame !== event.sender.mainFrame) throw new Error('Untrusted verification sender');
   if (Object.values(VOICE_ACTIONS).includes(action)) return runVoiceAction({ engine, action, payload, focus: voice => engine.emit({ type: 'voice-focus', threadId: voice.threadId }) });
   if (action === 'initialize') return { ...engine.settingsPayload(), teammates: engine.listTeammates(), version, contract: IPC_CONTRACT, chrome: 'native', jobs: [] };
   if (action === 'listTeammates') return engine.listTeammates();
   if (action === 'loadThread') return engine.loadThread(payload.id);
   if (action === 'listProjects') return engine.listProjects();
   if (action === 'workspaceSnapshot') return engine.workspaceSnapshot(payload.id);
   if (action === 'workspaceDiff') return engine.workspaceDiff(payload.id, payload.path);
   if (action === 'islandSnapshot') return engine.islandSnapshot();
   if (action === 'approvalList') return engine.listApprovals();
   if (action === 'respondApproval') return engine.respondApproval(payload.requestId, payload.answer);
   if (action === 'scheduleList') return [];
   if (action === 'browserSessionView') return { mode: null, status: 'idle', step: '', tabs: [], screenshot: null };
   return {};
 });
 ipcMain.handle('window:action', async () => true); ipcMain.handle('island:action', async () => true);
 await main.loadFile(path.join(root, 'desktop/renderer/dist/index.html'));
 state.workspace = workspace; state.ready = true;
})().catch(error => { console.error(error.message); app.exit(1); });
`);
const require = createRequire(import.meta.url);
const env = { ...process.env, CONFIG_DIR: configDirectory, VOICE_VERIFY_ROOT: ROOT, VOICE_VERIFY_DIRECTORY: directory, VOICE_VERIFY_ENV: envPath };
delete env.ELECTRON_RUN_AS_NODE;
let app;
const until = async check => { const deadline = Date.now() + TIMEOUT_MS; while (!await check()) { assert.ok(Date.now() < deadline, 'real desktop voice check timed out'); await new Promise(resolve => setTimeout(resolve, POLL_MS)); } };
try {
  app = await electron.launch({ executablePath: require('electron'), args: [harnessFile], cwd: ROOT, env, timeout: TIMEOUT_MS });
  await until(() => app.evaluate(() => Boolean(globalThis.voiceVerification?.ready)));
  console.log('DESKTOP_VOICE_NATIVE_STAGE ready');
  const main = await app.firstWindow(); main.setDefaultTimeout(TIMEOUT_MS);
  const pageErrors = []; main.on('pageerror', error => pageErrors.push(error.message));
  await main.getByRole('button', { name: 'Start voice conversation' }).click();
  await until(() => app.evaluate(() => globalThis.voiceVerification.engine.voice().snapshot().phase === 'listening'));
  console.log('DESKTOP_VOICE_NATIVE_STAGE listening');
  const started = Date.now();
  await app.evaluate(() => { const input = globalThis.voiceVerification.inputs.at(-1); input.options.onEvent({ type: 'silence_end', at: 1 }); input.options.onEvent({ type: 'silence_start', at: 2 }); });
  await until(() => app.evaluate(() => {
    const state = globalThis.voiceVerification; const voice = state.engine.voice().snapshot();
    return voice.task && !['queued', 'running', 'waiting_for_approval'].includes(voice.task.status) && voice.phase === 'listening';
  }));
  const result = await app.evaluate(() => {
    const state = globalThis.voiceVerification, voice = state.engine.voice().snapshot();
    const fs = process.getBuiltinModule('node:fs'), path = process.getBuiltinModule('node:path');
    const files = fs.readdirSync(state.workspace).filter(name => /\.(md|txt)$/i.test(name)).map(name => ({ name, characters: fs.readFileSync(path.join(state.workspace, name), 'utf8').length }));
    return { voice, files, inputs: state.inputs.length, playedBytes: state.playedBytes, model: state.events.find(event => event.type === 'turn-start')?.model,
      typedModel: state.engine.agentFor(voice.threadId).model, history: state.engine.loadThread(voice.threadId).map(message => message.role) };
  });
  assert.equal(result.voice.task.status, 'done', result.voice.task.error);
  assert.ok(result.files.some(file => file.characters > 20), JSON.stringify(result));
  assert.ok(result.voice.task.steps.some(step => step.tool === 'write_file' && step.state === 'done'));
  assert.ok(result.playedBytes.length >= 2 && result.playedBytes.every(bytes => bytes > 0));
  assert.equal(result.typedModel, 'typed-verification'); assert.notEqual(result.model, result.typedModel);
  assert.ok(result.history.includes('user') && result.history.includes('assistant'));
  console.log('DESKTOP_VOICE_NATIVE_STAGE real-file-and-speech-passed');
  await app.evaluate(() => globalThis.voiceVerification.main.showInactive());
  await main.waitForTimeout(700); await main.screenshot({ path: path.join(captures, 'voice-native-main.png') });
  await app.evaluate(async (_electron, { root }) => {
    const path = process.getBuiltinModule('node:path');
    const require = process.getBuiltinModule('node:module').createRequire(path.join(root, 'package.json'));
    const { BrowserWindow } = require('electron'); const state = globalThis.voiceVerification;
    const island = new BrowserWindow({ show: true, width: 640, height: 420, frame: false, webPreferences: { preload: path.join(root, 'desktop/electron/preload.cjs'), contextIsolation: true, sandbox: true, nodeIntegration: false, backgroundThrottling: false } });
    state.windows.push(island); await island.loadFile(path.join(root, 'desktop/renderer/dist/island.html')); island.showInactive();
  }, { root: ROOT });
  const island = app.windows().at(-1);
  await island.getByRole('button', { name: 'End voice', exact: true }).waitFor({ timeout: TIMEOUT_MS });
  await island.waitForTimeout(700); await island.screenshot({ path: path.join(captures, 'voice-native-island.png') });
  await island.getByRole('button', { name: 'End voice', exact: true }).click();
  await until(() => app.evaluate(() => !globalThis.voiceVerification.engine.voice().snapshot().active));
  assert.deepEqual(pageErrors, []);
  console.log('DESKTOP_VOICE_NATIVE_OK', JSON.stringify({ task: result.voice.task.status, files: result.files, model: result.model, typedModel: result.typedModel,
    realSpeechHandoffs: result.playedBytes.length, elapsedMs: Date.now() - started, input: 'generated Sarvam speech, simulated VAD', playback: 'captured MP3 handoff, no speaker', pageErrors: 0 }));
} finally {
  if (app) { await app.evaluate(async () => { await globalThis.voiceVerification?.engine.close(); }).catch(() => {}); await app.close().catch(() => {}); }
  fs.rmSync(directory, { recursive: true, force: true });
}
