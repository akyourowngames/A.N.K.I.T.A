import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import childProcess from 'node:child_process';
import { EventEmitter } from 'node:events';
import { syncBuiltinESMExports } from 'node:module';
import { Daemon } from '../../src/automation/daemon.mjs';

function voiceJob(t, { stopDuringWrite = false } = {}) {
  const wav = Buffer.from('converted voice bytes');
  const prompts = [], sent = [];
  let convertedPath, stagedPath, transcriptions = 0;
  const daemon = new Daemon({
    store: { telegramOffset: 0 }, client: {}, config: { groqApiKey: 'test' },
    runPrompt: async () => '', deliver: async () => {},
    bot: { enabled: true, download: async () => Buffer.from('voice note'), sendTyping: async () => {}, send: async (_id, text) => sent.push(text) },
  });
  daemon.chatAgent = () => ({ send: async prompt => { prompts.push(prompt); return 'reply'; } });
  daemon.saveChat = () => {};
  t.mock.method(childProcess, 'spawn', (_command, args) => {
    const child = new EventEmitter(); child.stderr = new EventEmitter(); child.kill = () => {};
    convertedPath = args.at(-1);
    fs.promises.writeFile(convertedPath, wav).then(() => child.emit('close', 0), error => child.emit('error', error));
    return child;
  });
  syncBuiltinESMExports();
  t.after(() => { t.mock.restoreAll(); syncBuiltinESMExports(); });
  const write = fs.promises.writeFile.bind(fs.promises);
  t.mock.method(fs.promises, 'writeFile', async (file, audio, options) => {
    await write(file, audio, options);
    if (file !== convertedPath && Buffer.isBuffer(audio) && audio.equals(wav)) {
      stagedPath = file;
      if (stopDuringWrite) daemon.stop();
    }
  });
  if (stopDuringWrite) {
    const syncWrite = fs.writeFileSync;
    t.mock.method(fs, 'writeFileSync', (file, audio) => { syncWrite(file, audio); stagedPath = file; daemon.stop(); });
  } else {
    t.mock.method(fs, 'writeFileSync', () => { throw new Error('blocking audio staging'); });
    t.mock.method(fs, 'unlinkSync', () => { throw new Error('blocking audio cleanup'); });
  }
  t.mock.method(globalThis, 'fetch', async (_url, options) => {
    transcriptions++;
    assert.deepEqual(Buffer.from(await options.body.get('file').arrayBuffer()), wav);
    return new Response(JSON.stringify({ text: 'transcribed voice' }), { headers: { 'content-type': 'application/json' } });
  });
  return { daemon, prompts, sent, get stagedPath() { return stagedPath; }, get transcriptions() { return transcriptions; } };
}

const job = { kind: 'voice', chatId: 'test', fileId: 'voice-file', messageId: 'message' };

test('daemon stages voice bytes asynchronously, transcribes them and cleans up', async t => {
  const run = voiceJob(t);
  await run.daemon.handleJob(job);
  assert.deepEqual(run.prompts, ['transcribed voice']);
  assert.deepEqual(run.sent, ['reply']);
  assert.equal(run.daemon.stats.errors, 0);
  await assert.rejects(fs.promises.access(run.stagedPath), { code: 'ENOENT' });
});

test('stopping during voice staging skips transcription and cleans up', async t => {
  const run = voiceJob(t, { stopDuringWrite: true });
  await run.daemon.handleJob(job);
  assert.equal(run.transcriptions, 0);
  assert.deepEqual(run.prompts, []);
  assert.deepEqual(run.sent, []);
  await assert.rejects(fs.promises.access(run.stagedPath), { code: 'ENOENT' });
});
