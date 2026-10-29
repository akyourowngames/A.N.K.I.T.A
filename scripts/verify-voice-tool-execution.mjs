/** Live planner + native browser/file tools, disposable profiles, no microphone.
 * node scripts/verify-voice-tool-execution.mjs [--env path/to/.env] [--youtube-only]
 * The silent local player proves browser execution, not YouTube or audible music.
 */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import { randomUUID } from 'node:crypto';
import { chromium } from 'playwright';
import { loadConfig } from '../src/core/config.mjs';
import { Agent } from '../src/core/agent.mjs';
import { createVoiceBrain } from '../src/core/voice-session.mjs';
import { captureVoiceContext, runVoiceWorker } from '../src/core/voice-worker.mjs';
import { VoiceTaskStore, runVoiceTask } from '../src/automation/voice-task.mjs';
import { VoiceResourceBroker } from '../src/automation/voice-resources.mjs';
import { configuredSecrets, redactText } from '../src/core/redact.mjs';
import { BrowserPluginStore, CHROME_MCP_ID, chromeMcpCommand } from '../src/integrations/browser-plugins.mjs';
import { McpManager } from '../src/integrations/mcp-manager.mjs';
import { BrowserSessionManager } from '../tools/browser/session.mjs';
import { PlaywrightBrowserAdapter } from '../tools/browser/playwright.mjs';
import { ChromeBrowserAdapter } from '../tools/browser/chrome.mjs';

const HOST = '127.0.0.1'; // Disposable HTTP fixture; the OS chooses its port.
const REQUEST_MS = 90000; // Milliseconds per live voice request, including provider and browser setup.
const CONNECT_MS = 25000; // Milliseconds for the installed Chrome bridge handshake.
const MCP_REQUEST_MS = 15000; // Milliseconds per installed bridge call.
const SAMPLE_RATE = 16000, AUDIO_SECONDS = 1, WAV_HEADER_BYTES = 44, SAMPLE_BYTES = 2; // Mono silent PCM fixture.
const CLEANUP = { recursive: true, force: true, maxRetries: 10, retryDelay: 100 }; // Disposable Windows browser-profile cleanup only.
const YOUTUBE_HOSTS = new Set(['youtube.com', 'www.youtube.com', 'youtu.be']); // Optional public-site probe, never an account profile.
const arguments_ = process.argv.slice(2), envIndex = arguments_.indexOf('--env');
const youtubeOnly = arguments_.includes('--youtube-only');
const loaded = loadConfig(envIndex < 0 ? undefined : path.resolve(arguments_[envIndex + 1]));
const config = { ...loaded, voiceProvider: 'baseten', voiceModel: '', tools: true, autoApprove: true,
  subagentsEnabled: false, memoryConsolidation: false, projectWorkCapture: false, allowPrivateHosts: true };
const brain = createVoiceBrain(config), secrets = configuredSecrets(config);
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'voice-tool-execution-live-'));
const audio = Buffer.alloc(WAV_HEADER_BYTES + SAMPLE_RATE * AUDIO_SECONDS * SAMPLE_BYTES);
audio.write('RIFF'); audio.writeUInt32LE(audio.length - 8, 4); audio.write('WAVEfmt ', 8);
audio.writeUInt32LE(16, 16); audio.writeUInt16LE(1, 20); audio.writeUInt16LE(1, 22);
audio.writeUInt32LE(SAMPLE_RATE, 24); audio.writeUInt32LE(SAMPLE_RATE * SAMPLE_BYTES, 28);
audio.writeUInt16LE(SAMPLE_BYTES, 32); audio.writeUInt16LE(SAMPLE_BYTES * 8, 34);
audio.write('data', 36); audio.writeUInt32LE(audio.length - WAV_HEADER_BYTES, 40);
let played = 0;
const server = http.createServer((request, response) => {
  if (request.url === '/tone.wav') { response.setHeader('Content-Type', 'audio/wav'); response.end(audio); return; }
  if (request.url === '/played' && request.method === 'POST') { played++; response.end('observed'); return; }
  response.setHeader('Content-Type', 'text/html');
  response.end(`<title>Haryanvi test player</title><h1>Haryanvi demo beat</h1>
    <audio id="audio" src="/tone.wav" loop></audio><button id="play">Play demo beat</button><main>Playback stopped</main>
    <script>const audio=document.querySelector('audio');document.querySelector('button').onclick=()=>audio.play();
    audio.onplaying=()=>{document.querySelector('main').textContent='Playback running';fetch('/played',{method:'POST'});};</script>`);
});
const mcp = new McpManager(), broker = new VoiceResourceBroker();
const store = new BrowserPluginStore(path.join(root, 'browser.json')).load();
const isolated = new PlaywrightBrowserAdapter({ profile: path.join(root, 'playwright') });
const chrome = new ChromeBrowserAdapter(mcp, { ensureConnected: async ctx => {
  await mcp.connect({ id: CHROME_MCP_ID, command: process.execPath,
    args: [chromeMcpCommand({ connection: 'profile' }).args[0], '--no-usage-statistics', '--no-performance-crux', '--headless',
      `--executablePath=${chromium.executablePath()}`, `--user-data-dir=${path.join(root, 'chrome')}`],
    signal: ctx.signal, initTimeoutMs: CONNECT_MS, requestTimeoutMs: MCP_REQUEST_MS, hidden: true });
} });
const manager = new BrowserSessionManager({ store, isolatedFactory: () => isolated, chromeFactory: () => chrome });
const taskStore = new VoiceTaskStore({ directory: path.join(root, 'tasks'), secrets });
try {
  await new Promise(resolve => server.listen(0, HOST, resolve));
  const url = `http://${HOST}:${server.address().port}`;
  const parent = new Agent({ client: brain.client, config, workspacePath: root, browserManager: manager, mcp,
    memoryEnabled: false, skillsEnabled: false, autoProject: false, print: () => {}, write: () => {} });
  async function run(transcript) {
    const entry = { id: randomUUID(), ownerId: parent.sessionId, transcript, context: captureVoiceContext(parent) };
    const started = performance.now(), signal = AbortSignal.timeout(REQUEST_MS);
    try {
      const result = await runVoiceTask({ store: taskStore, transcript, taskId: entry.id, signal,
        run: (observer, task) => runVoiceWorker(entry, { observer, task, signal,
          controlTool: { name: 'voice_jobs', description: 'No other jobs in this disposable check.', parameters: { type: 'object' }, readOnly: true, needsApproval: false, run: () => '[]' } },
        { brain, acquire: (...args) => broker.acquire(...args), confirm: async () => true,
          onWorker: worker => {
            const runToolCall = worker.runToolCall.bind(worker);
            worker.runToolCall = async (...args) => {
              const result = await runToolCall(...args);
              console.log(redactText(JSON.stringify({ stage: 'tool-trace', name: args[0].function.name,
                arguments: args[0].function.arguments, result: String(result).slice(0, 600) }), { secrets }));
              return result;
            };
          },
          toolContext: { beforeToolExecute: async call => {
            if (call.name === 'browser' && call.arguments.url) assert.ok(youtubeOnly
              ? YOUTUBE_HOSTS.has(new URL(call.arguments.url).hostname) : call.arguments.url.startsWith(url), 'Live probe stays on its designated public site or disposable player.');
          } } }),
      });
      console.log(JSON.stringify({ stage: 'live-task', transcript, status: result.task.status, summary: result.task.summary,
        error: result.task.error, tools: result.task.steps.map(step => ({ tool: step.tool, state: step.state })),
        rounds: entry.worker.requestMetrics.filter(row => !row.kind).length,
        checkMs: entry.worker.requestMetrics.filter(row => row.kind === 'voice_result_check').map(row => row.durationMs),
        ms: Math.round(performance.now() - started) }));
      assert.equal(result.task.status, 'done', result.task.error);
      return result.task;
    } finally { broker.release(entry.id); }
  }
  if (youtubeOnly) {
    store.setEnabled('isolated', true); store.setEnabled('local', false);
    await run('Play some Haryanvi bangers on YouTube.');
    const playback = await isolated.page.evaluate(() => {
      const video = document.querySelector('video');
      return { title: document.title, url: location.href, paused: video?.paused, readyState: video?.readyState,
        currentTime: video?.currentTime, adShowing: Boolean(document.querySelector('.ad-showing')) };
    });
    console.log(JSON.stringify({ stage: 'youtube-proof', ...playback }));
    assert.equal(playback.paused, false); assert.ok(playback.readyState >= 2); assert.equal(playback.adShowing, false);
    console.log('VOICE_YOUTUBE_LIVE_OK physicalAudio=false accountProfile=false');
  } else {
  for (const mode of ['isolated', 'local']) {
    store.setEnabled('isolated', mode === 'isolated'); store.setEnabled('local', mode === 'local');
    const before = played;
    const task = await run(`Play some Haryanvi bangers from the disposable demo player at ${url}.`);
    assert.ok(task.steps.some(step => step.tool === 'browser' && step.state === 'done'));
    assert.ok(played > before, `${mode}: real browser must dispatch playback, not just open the page`);
    assert.match(await manager.run({ action: 'read', mode }, { cwd: root, config }), /Playback running/);
    console.log(JSON.stringify({ stage: 'browser-proof', mode, playbackEvents: played - before, readback: 'Playback running' }));
  }
  await run('Write a short poem in checked-poem.md and read the file back to check it saved.');
  assert.ok(fs.readFileSync(path.join(root, 'checked-poem.md'), 'utf8').trim());
  const chat = await run('How are you?'); assert.deepEqual(chat.steps, []);
  console.log('VOICE_TOOL_EXECUTION_LIVE_OK browserBackends=2 fileReadback=true chat=true physicalAudio=false youtube=false');
  }
} catch (error) {
  console.error(redactText(error.stack || error.message, { secrets })); process.exitCode = 1;
} finally {
  await manager.close(); await mcp.closeAll(); server.closeAllConnections();
  await new Promise(resolve => server.close(resolve));
  assert.equal(fs.realpathSync(path.dirname(root)), fs.realpathSync(os.tmpdir()));
  await fs.promises.rm(root, CLEANUP);
}
