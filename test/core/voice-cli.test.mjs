import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import { spawn } from 'node:child_process';

const CLI_URL = new URL('../../src/core/cli.mjs', import.meta.url).href;
const CHILD_TIMEOUT_MS = 15000; // Test-only ceiling: no real microphone or cloud service is used.
async function runCli(t, mode) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'voice-cli-'));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 }));
  const runtime = path.join(directory, 'config');
  const file = path.join(directory, 'note.txt');
  const models = [];
  const server = http.createServer(async (request, response) => {
    response.setHeader('Content-Type', 'application/json');
    if (request.url.endsWith('/models')) { response.end(JSON.stringify({ data: [{ id: 'typed-model', context_length: 131072, supported_parameters: ['tools'] }] })); return; }
    let raw = ''; for await (const chunk of request) raw += chunk;
    const body = JSON.parse(raw); models.push(body.model);
    if (mode === 'failure' && body.model === 'voice-model') { response.statusCode = 403; response.end('Planner access denied'); return; }
    const voice = body.model === 'voice-model';
    if (voice) { assert.equal(body.reasoning_effort, 'low'); assert.ok(body.max_tokens >= 400); }
    const tool = voice && !body.messages.some(message => message.role === 'tool');
    response.end(JSON.stringify({ choices: [{ message: tool ? {
      role: 'assistant', content: '', tool_calls: [{ id: 'write-1', type: 'function', function: {
        name: 'write_file', arguments: JSON.stringify({ path: file, content: 'Workspace ready' }),
      } }],
    } : { role: 'assistant', content: voice ? 'Workspace tayyar hai.' : 'Hi from chat.' } }] }));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => { server.closeAllConnections(); server.close(); });
  const endpoint = `http://127.0.0.1:${server.address().port}/v1`;
  fs.writeFileSync(path.join(directory, '.env'), [
    'PROVIDER=kilo', 'MODEL=typed-model', `API_BASE=${endpoint}`, 'VOICE_PROVIDER=baseten',
    'VOICE_MODEL=voice-model', 'VOICE_CONTEXT_WINDOW=131072', `VOICE_API_BASE=${endpoint}`, 'BASETEN_API_KEY=fixture-planner',
    'STT_PROVIDER=sarvam', `SARVAM_API_KEY=${mode === 'probe' ? '' : 'fixture-speech'}`, 'TTS_PROVIDER=sarvam',
    'TOOL_PROVIDER=kilo', 'TOOL_MODEL=unwanted-tool-model', `TOOL_API_BASE=${endpoint}`,
    'AUTO_APPROVE=off', 'VOICE_BARGE_IN=off', 'VOICE_HFP_ROUTING=off', 'MEMORY_CONSOLIDATION=off',
    'EMBEDDINGS=off', 'PROJECT_AUTO_DETECT=off', 'PROJECT_WORK_CAPTURE=off', 'PROJECT_AUTO_MAINTENANCE=off',
    'SUBAGENTS_ENABLED=off',
  ].join('\n'));
  const harness = path.join(directory, 'harness.mjs');
  fs.writeFileSync(harness, `
    import fs from 'node:fs';
    import { main } from ${JSON.stringify(CLI_URL)};
    let capture = 0;
    const fetchOriginal = globalThis.fetch;
    globalThis.fetch = async (url, options) => {
      if (${JSON.stringify(mode)} === 'cancel' && options?.body && JSON.parse(options.body).model === 'voice-model') {
        setImmediate(() => process.emit('SIGINT'));
      }
      return fetchOriginal(url, options);
    };
    process.argv = [process.execPath, ${JSON.stringify(harness)}, '--voice', '--plain', '--no-banner'];
    // Capture the CLI's requested exit and allow test sockets to close naturally.
    // Immediate process.exit with mocked, zero-duration audio hits Node's Windows
    // libuv shutdown assertion; this harness tests the loop, not forced teardown.
    const requestedExit = new Error('requested CLI exit');
    process.exit = code => { process.exitCode = code; throw requestedExit; };
    try { await main({ voiceIO: {
      voiceRuntimeCheck: () => ${mode === 'probe' ? JSON.stringify('VOICE_IO_PROBE') : 'null'},
      audioDeps: () => ({ ffmpeg: true, ffplay: true }),
      detectMic: async () => ({ name: 'fixture mic' }),
      openVoiceInput: ({outFile}) => {
        fs.writeFileSync(outFile, 'fixture');
        console.log('CAPTURE_READY');
        return { ready: Promise.resolve(), stop: async () => true };
      },
      transcribeAudio: async () => ({ text: capture++ ? 'exit' : 'Workspace kholo', languageCode: 'hi-IN', confidence: 0.99 }),
      synthesizeSarvam: async ({text}) => {
        if (${JSON.stringify(mode)} === 'tts-failure') throw new Error('fixture Sarvam outage');
        if (${JSON.stringify(mode)} === 'approval-cancel' && text.startsWith('Permission chahiye')) {
          setImmediate(() => process.emit('SIGINT'));
          await new Promise(resolve => setTimeout(resolve, 500));
        }
        return Buffer.from(text);
      },
      synthesizeEdge: async ({text}) => Buffer.from(text),
      playMp3: async audio => { console.log('PLAYED: ' + audio.toString()); },
      stopPlayback: () => {},
    } }); } catch (error) { if (error !== requestedExit) throw error; }
  `);
  const child = spawn(process.execPath, [harness], { cwd: directory, env: { ...process.env, CONFIG_DIR: runtime, NO_COLOR: '1', SARVAM_API_KEY: '', BASETEN_API_KEY: '' }, stdio: ['pipe', 'pipe', 'pipe'], windowsHide: true });
  let stdout = ''; let stderr = ''; let captures = 0; let approval = false; let typed = false;
  child.stdout.on('data', data => {
    stdout += data;
    const seen = stdout.split('CAPTURE_READY').length - 1;
    while (captures < seen) { captures++; child.stdin.write('\n'); }
    if (!approval && stdout.includes('allow?')) { approval = true; child.stdin.write('y\n'); }
    if (!typed && (stdout.includes('leaving voice mode') || stdout.includes('VOICE_IO_PROBE') || stdout.includes('voice needs SARVAM_API_KEY'))) {
      typed = true; child.stdin.end('Say hello\n/task\n/exit\n');
    }
  });
  child.stderr.on('data', data => { stderr += data; });
  const code = await new Promise((resolve, reject) => {
    const timer = setTimeout(() => { child.kill(); reject(new Error(`CLI timeout: ${stdout}\n${stderr}`)); }, CHILD_TIMEOUT_MS);
    child.on('exit', code => { clearTimeout(timer); resolve(code); });
    child.on('error', error => { clearTimeout(timer); reject(error); });
  });
  assert.equal(code, 0, stdout + stderr);
  const tasks = path.join(runtime, 'voice-tasks');
  const records = fs.existsSync(tasks) ? fs.readdirSync(tasks).filter(name => name.endsWith('.json')).map(name => JSON.parse(fs.readFileSync(path.join(tasks, name), 'utf8'))) : [];
  return { stdout, models, records, written: fs.existsSync(file) ? fs.readFileSync(file, 'utf8') : null };
}

test('CLI voice devices can be supplied without opening a physical microphone', async t => {
  const result = await runCli(t, 'probe');
  assert.match(result.stdout, /VOICE_IO_PROBE/);
});

for (const mode of ['success', 'tts-failure', 'failure', 'cancel', 'approval-cancel']) test(`real CLI voice loop: ${mode}, saved task, then unchanged typed chat`, async t => {
  const result = await runCli(t, mode);
  assert.equal(result.records.length, 1);
  const task = result.records[0];
  assert.equal(task.status, ['success', 'tts-failure'].includes(mode) ? 'done' : mode.includes('cancel') ? 'cancelled' : 'failed', JSON.stringify(task) + '\n' + result.stdout);
  assert.equal(task.transcript, 'Workspace kholo');
  assert.match(result.stdout, /PLAYED: Haan\./);
  assert.match(result.stdout, new RegExp(task.id));
  assert.match(result.stdout, /Hi from chat/);
  assert.equal(result.models.at(-1), 'typed-model');
  assert.ok(!result.models.includes('unwanted-tool-model'));
  if (['success', 'tts-failure'].includes(mode)) {
    assert.equal(result.written, 'Workspace ready');
    assert.match(result.stdout, /waiting_for_approval/);
    assert.match(result.stdout, /PLAYED: Workspace tayyar hai/);
    if (mode === 'tts-failure') assert.match(result.stdout, /using Edge/);
  } else if (mode === 'failure') {
    assert.match(task.error, /403/);
    assert.ok(!result.stdout.includes('token refreshed'));
  } else {
    assert.match(result.stdout, /PLAYED: Cancelled/);
    if (mode === 'approval-cancel') {
      assert.ok(!result.stdout.includes('PLAYED: Permission'), result.stdout);
      assert.ok(!result.stdout.includes('allow?'), result.stdout);
      assert.equal(result.written, null);
    }
  }
});
