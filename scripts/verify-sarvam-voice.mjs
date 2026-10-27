/**
 * Live check of the Sarvam speech path used by `/voice`.
 *
 * Everything here goes through the real modules, not stubs:
 *   text -> Bulbul TTS -> MP3 -> ffmpeg 16 kHz mono WAV (exactly what
 *   startRecording() writes) -> Saaras STT -> transcript.
 *
 * Usage:  node scripts/verify-sarvam-voice.mjs
 * Needs:  SARVAM_API_KEY in the environment or the repo .env, plus ffmpeg.
 * Costs:  a few paise per run (STT + TTS pricing).
 * Exit:   0 when both languages round-trip, 1 otherwise.
 */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import {
  synthesizeSarvam,
  transcribeSarvam,
  resolveSarvamSpeaker,
  chooseSarvamLanguage,
  parseKeyterms,
} from '../src/channels/voice.mjs';

function readKey() {
  if (process.env.SARVAM_API_KEY) return process.env.SARVAM_API_KEY;
  try {
    const env = fs.readFileSync(new URL('../.env', import.meta.url), 'utf8');
    const line = env.split(/\r?\n/).find((l) => /^\s*SARVAM_API_KEY\s*=/.test(l));
    return line ? line.slice(line.indexOf('=') + 1).trim().replace(/^["']|["']$/g, '') : '';
  } catch {
    return '';
  }
}

const CASES = [
  {
    label: 'hinglish',
    languageCode: 'hi-IN',
    spoken: 'Ankita, VS Code kholo aur mera workspace set up karo.',
    keyterms: 'Ankita,VS Code,workspace',
    reply: 'Workspace tayyar hai. VS Code khul gaya.',
    // Only the command words are pass/fail. The assistant's own name is
    // reported separately: Saaras has returned "Anpeta" for "Ankita" even with
    // the name in keyterms, so failing on it would make this check flaky.
    expect: [/vs\s*code/i, /workspace/i],
    reportsName: true,
  },
  {
    label: 'english',
    languageCode: 'en-IN',
    spoken: 'Ankita, open VS Code and set up my workspace.',
    keyterms: 'Ankita',
    reply: 'Your workspace is ready. VS Code is open.',
    expect: [/vs\s*code/i, /workspace/i],
  },
];

const key = readKey();
if (!key) {
  console.error('SARVAM_API_KEY is not set (environment or .env) — nothing to verify.');
  process.exit(1);
}
if (spawnSync('ffmpeg', ['-version'], { stdio: 'ignore' }).status !== 0) {
  console.error('ffmpeg is not on PATH — the mic path needs it too.');
  process.exit(1);
}

const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'sarvam-verify-'));
const mp3 = path.join(dir, 'reply.mp3');
const wav = path.join(dir, 'mic.wav');
const rows = [];
let failed = false;

try {
  for (const item of CASES) {
    const ttsStarted = Date.now();
    const audio = await synthesizeSarvam({
      apiKey: key,
      speaker: resolveSarvamSpeaker({}, item.languageCode),
      languageCode: item.languageCode,
      text: item.spoken,
    });
    const ttsMs = Date.now() - ttsStarted;
    fs.writeFileSync(mp3, audio);

    const ff = spawnSync('ffmpeg', [
      '-hide_banner', '-loglevel', 'error', '-y',
      '-i', mp3, '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', wav,
    ]);
    if (ff.status !== 0) throw new Error(`ffmpeg failed: ${String(ff.stderr)}`);

    const sttStarted = Date.now();
    const heard = await transcribeSarvam({
      apiKey: key,
      wavPath: wav,
      keyterms: parseKeyterms(item.keyterms),
    });
    const sttMs = Date.now() - sttStarted;

    const missing = item.expect.filter((re) => !re.test(heard.text));
    if (missing.length || !heard.text) failed = true;

    // Now the reply direction, exactly as /voice does it: the transcript
    // language is a hint, the reply's own script decides the voice.
    const replyLanguage = chooseSarvamLanguage({ text: item.reply, detected: heard.languageCode });
    const replyStarted = Date.now();
    const replyAudio = await synthesizeSarvam({
      apiKey: key,
      speaker: resolveSarvamSpeaker({}, replyLanguage),
      languageCode: replyLanguage,
      text: item.reply,
    });
    const replyMs = Date.now() - replyStarted;

    rows.push({
      case: item.label,
      ttsMs,
      ttsBytes: audio.length,
      mp3Header: audio.subarray(0, 2).toString('hex'),
      sttMs,
      detected: heard.languageCode,
      confidence: heard.confidence,
      transcript: heard.text,
      replyLanguage,
      replyMs,
      replyBytes: replyAudio.length,
      nameHeard: item.reportsName ? /ankita/i.test(heard.text) : null,
      ok: missing.length === 0 && Boolean(heard.text) && replyAudio.length > 0,
    });
  }
} finally {
  fs.rmSync(dir, { recursive: true, force: true });
}

console.table(rows);
const bad = rows.filter((r) => !r.ok);
if (bad.length) {
  console.error(`FAIL: ${bad.map((r) => r.case).join(', ')} did not round-trip cleanly.`);
  process.exit(1);
}
const named = rows.filter((r) => r.nameHeard !== null);
if (named.some((r) => r.nameHeard === false)) {
  console.warn('WARN: the assistant name was misheard in this run. The transcript is shown before');
  console.warn('      anything runs, so the flow survives it — but never film a take that shows it.');
}
console.log(`OK: ${rows.length}/${rows.length} cases round-tripped through Sarvam.`);
