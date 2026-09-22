import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

// Isolate the config layer BEFORE anything loads it. Without this the suite
// reads the machine's real ~/.copilot-chat-cli/config.env, so the defaults
// assertions below would pass or fail depending on whose computer it runs on.
const SANDBOX = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-voice-cfg-'));
process.env.CONFIG_DIR = SANDBOX;
test.after(() => fs.rmSync(SANDBOX, { recursive: true, force: true }));

const {
  stripForSpeech,
  buildSsml,
  escapeXml,
  parseMicList,
  tmpVoiceFile,
  chunkSentences,
  concatWav,
  resolveTtsProvider,
  resolveTtsVoice,
  generateSecMsGec,
  edgeDateString,
  edgeWsTarget,
  buildSilenceFilter,
  parseSilenceLine,
  parseSilenceEvents,
  createSilenceParser,
  createTurnDetector,
  splitListItems,
  splitSentences,
  renderSummaryNote,
  summarizeForSpeech,
  DEFAULT_SUMMARY_NOTE,
  DEFAULT_STT_MODEL,
  DEFAULT_TTS_MODEL,
} = await import('../src/voice.mjs');
const { loadConfig } = await import('../src/config.mjs');
const { findHandsFreePlayback } = await import('../src/audio-device.mjs');

test('speech text drops code fences but keeps inline code', () => {
  const out = stripForSpeech('Here is how:\n```js\nconst x = 1;\n```\nUse `npm test` to verify.');
  assert.ok(!out.includes('const x'));
  assert.ok(out.includes('npm test'));
  assert.ok(!out.includes('```'));
});

test('speech text strips markdown formatting, links and tables', () => {
  const out = stripForSpeech('# Title\n\nSome **bold** and *italic* with a [link](https://x.test/y).\n\n- one\n- two\n\n| a | b |\n|---|---|\n| 1 | 2 |');
  assert.ok(!out.includes('#') && !out.includes('**') && !out.includes('https://'));
  assert.ok(out.includes('Title') && out.includes('bold') && out.includes('link'));
  assert.ok(out.includes('one') && out.includes('two'));
});

test('speech text truncates at a sentence boundary', () => {
  const long = Array.from({ length: 200 }, (_, i) => `Sentence number ${i} here.`).join(' ');
  const out = stripForSpeech(long, 300);
  assert.ok(out.length <= 320);
  assert.ok(out.endsWith('.'));
});

test('ssml escapes xml and wraps voice plus rate', () => {
  const ssml = buildSsml({ voice: 'en-US-AriaNeural', rate: '+10%', text: 'a < b & "c"' });
  assert.ok(ssml.includes("name='en-US-AriaNeural'"));
  assert.ok(ssml.includes("rate='+10%'"));
  assert.ok(ssml.includes('a &lt; b &amp; &quot;c&quot;'));
  assert.equal(escapeXml(`it's "fine"`), 'it&apos;s &quot;fine&quot;');
});

test('mic list parses ffmpeg dshow device output', () => {
  const stderr = [
    '[dshow @ 000001] "Microphone (Realtek(R) Audio)" (audio)',
    '[dshow @ 000001]   Alternative name "mic0"',
    '[dshow @ 000001] "Stereo Mix (Realtek(R) Audio)" (audio)',
  ].join('\n');
  const mics = parseMicList(stderr);
  assert.equal(mics.length, 2);
  assert.equal(mics[0].name, 'Microphone (Realtek(R) Audio)');
  assert.equal(mics[0].alt, 'mic0');
  assert.deepEqual(parseMicList('no devices here'), []);
});

test('silence filter builds an ffmpeg silencedetect expression', () => {
  assert.equal(buildSilenceFilter({ noiseDb: -35, silenceSec: 1.2 }), 'silencedetect=noise=-35dB:d=1.2');
  assert.equal(buildSilenceFilter({ noiseDb: -20, silenceSec: 0.05 }), 'silencedetect=noise=-20dB:d=0.2');
  assert.equal(buildSilenceFilter({ noiseDb: 'junk', silenceSec: 'junk' }), 'silencedetect=noise=-35dB:d=1.2');
});

test('silence lines parse start/end and ignore everything else', () => {
  assert.deepEqual(parseSilenceLine('[Parsed_silencedetect_0 @ 0x1] silence_start: 0.5'), {
    type: 'silence_start',
    at: 0.5,
  });
  assert.deepEqual(
    parseSilenceLine('[Parsed_silencedetect_0 @ 0x1] silence_end: 2.500062 | silence_duration: 2.000062'),
    { type: 'silence_end', at: 2.500062, duration: 2.000062 }
  );
  assert.equal(parseSilenceLine('frame= 100 fps=0.0'), null);
});

test('silence events parse in order from a stderr blob', () => {
  const stderr = [
    'ffmpeg version 7',
    '[Parsed_silencedetect_0 @ 0x1] silence_start: 0.5',
    'size=N/A time=00:00:01.02',
    '[Parsed_silencedetect_0 @ 0x1] silence_end: 2.5 | silence_duration: 2.0',
    '[Parsed_silencedetect_0 @ 0x1] silence_start: 3',
  ].join('\n');
  assert.deepEqual(parseSilenceEvents(stderr), [
    { type: 'silence_start', at: 0.5 },
    { type: 'silence_end', at: 2.5, duration: 2 },
    { type: 'silence_start', at: 3 },
  ]);
});

test('streaming silence parser survives split chunks', () => {
  const parser = createSilenceParser();
  assert.deepEqual(parser.push('[Parsed] silence_st'), []);
  const evs = [
    ...parser.push('art: 0.5\n[Parsed] silence_end: 2.5 | sil'),
    ...parser.push('ence_duration: 2.0\npartial tail'),
    ...parser.flush(),
  ];
  assert.deepEqual(evs, [
    { type: 'silence_start', at: 0.5 },
    { type: 'silence_end', at: 2.5, duration: 2 },
  ]);
});

test('turn detector reports speech start then utterance end', () => {
  const d = createTurnDetector();
  // Leading silence before any speech is not an utterance end.
  assert.equal(d.feed({ type: 'silence_start', at: 0 }), null);
  assert.equal(d.heard, false);
  // Speech starts when silence ends.
  assert.equal(d.feed({ type: 'silence_end', at: 1, duration: 1 }), 'speech');
  assert.equal(d.heard, true);
  // A later pause closes the utterance.
  assert.equal(d.feed({ type: 'silence_start', at: 3 }), 'end');
  // The same pause does not fire twice.
  assert.equal(d.feed({ type: 'silence_start', at: 3 }), null);
});

test('hands-free playback match pairs a Bluetooth mic with its render endpoint', () => {
  const devices = [
    { flow: 'render', id: 'r1', name: 'Headphones (Airdopes 181 Pro Stereo)' },
    { flow: 'render', id: 'r2', name: 'Headset (Airdopes 181 Pro Hands-Free AG Audio)' },
    { flow: 'capture', id: 'c1', name: 'Headset (Airdopes 181 Pro Hands-Free AG Audio)' },
    { flow: 'render', id: 'r3', name: 'Speakers (Realtek Audio)' },
  ];
  const hit = findHandsFreePlayback('Headset (Airdopes 181 Pro Hands-Free AG Audio)', devices);
  assert.equal(hit && hit.id, 'r2', 'picks the render twin, not the capture endpoint');
  assert.equal(findHandsFreePlayback('  HEADSET (airdopes 181 pro hands-free ag audio) ', devices)?.id, 'r2');
  assert.equal(findHandsFreePlayback('Microphone Array (Realtek Audio)', devices), null);
  assert.equal(findHandsFreePlayback('', devices), null);
  assert.equal(findHandsFreePlayback('Headset (Airdopes 181 Pro Hands-Free AG Audio)', []), null);
});

test('list items are detected from bullets and numbers', () => {
  const md = ['Intro line.', '- first', '* second', '2. third', '  1) fourth', 'outro'].join('\n');
  assert.deepEqual(splitListItems(md), ['first', 'second', 'third', 'fourth']);
  assert.deepEqual(splitListItems('no list here'), []);
  assert.deepEqual(splitSentences('One. Two! Three?'), ['One.', 'Two!', 'Three?']);
});

test('summary note fills placeholders and tidies an empty address', () => {
  assert.equal(
    renderSummaryNote({ address: 'sir', spoken: 8, total: 20, remaining: 12 }),
    "sir, that's 8 of 20. The rest is on your screen, sir."
  );
  assert.equal(
    renderSummaryNote({ address: '', spoken: 8, total: 20, remaining: 12 }),
    "that's 8 of 20. The rest is on your screen."
  );
  assert.equal(
    renderSummaryNote({ template: '{address}: {spoken}/{total} ({remaining} left)', address: 'boss', spoken: 1, total: 5, remaining: 4 }),
    'boss: 1/5 (4 left)'
  );
});

test('long lists are read in part with a dynamic note', () => {
  const items = Array.from({ length: 12 }, (_, i) => `- Point number ${i + 1}`);
  const out = summarizeForSpeech(items.join('\n'), { address: 'sir', maxItems: 4 });
  assert.ok(out.includes('Point number 1'));
  assert.ok(out.includes('Point number 4'));
  assert.ok(!out.includes('Point number 5'), 'items past the cap are not read');
  assert.ok(out.includes("Point number 4. sir, that's 4 of 12. The rest is on your screen, sir."));
});

test('short lists are read whole with no note', () => {
  const out = summarizeForSpeech('- alpha\n- beta\n- gamma', { address: 'sir', maxItems: 8 });
  assert.equal(out, 'alpha. beta. gamma');
  assert.ok(!out.includes('on your screen'));
});

test('long prose is read in part with a dynamic note', () => {
  const prose = Array.from({ length: 10 }, (_, i) => `Sentence number ${i + 1} here.`).join(' ');
  const out = summarizeForSpeech(prose, { address: 'sir', maxSentences: 3 });
  assert.ok(out.includes('Sentence number 1 here.'));
  assert.ok(out.includes('Sentence number 3 here.'));
  assert.ok(!out.includes('Sentence number 4 here.'));
  assert.ok(out.includes("sir, that's 3 of 10. The rest is on your screen, sir."));
});

test('fullRead ignores the caps and empty input is silent', () => {
  const items = Array.from({ length: 12 }, (_, i) => `- Point ${i + 1}`).join('\n');
  const out = summarizeForSpeech(items, { fullRead: true, maxItems: 2 });
  assert.ok(out.includes('Point 12'));
  assert.ok(!out.includes('on your screen'));
  assert.equal(summarizeForSpeech('   '), '');
  assert.equal(summarizeForSpeech(''), '');
});

test('voice temp files are unique per call', () => {
  const a = tmpVoiceFile('wav');
  const b = tmpVoiceFile('wav');
  assert.ok(a.endsWith('.wav') && b.endsWith('.wav'));
  assert.notEqual(a, b);
});

test('groq tts translates a terms-acceptance 400 into something actionable', async (t) => {
  const { synthesizeGroq } = await import('../src/voice.mjs');
  const original = globalThis.fetch;
  t.after(() => { globalThis.fetch = original; });
  globalThis.fetch = async () =>
    new Response(
      JSON.stringify({ error: { message: 'The model `canopylabs/orpheus-v1-english` requires terms acceptance.' } }),
      { status: 400, headers: { 'Content-Type': 'application/json' } }
    );
  await assert.rejects(
    synthesizeGroq({ apiKey: 'k', model: 'canopylabs/orpheus-v1-english', text: 'hi' }),
    (err) => /terms accepted/.test(err.message) && /console\.groq\.com/.test(err.message) && /TTS_PROVIDER=edge/.test(err.message)
  );
});

test('groq tts surfaces other failures verbatim', async (t) => {
  const { synthesizeGroq } = await import('../src/voice.mjs');
  const original = globalThis.fetch;
  t.after(() => { globalThis.fetch = original; });
  globalThis.fetch = async () => new Response('rate limited', { status: 429 });
  await assert.rejects(synthesizeGroq({ apiKey: 'k', text: 'hi' }), /Groq TTS 429/);
});

test('voice config defaults and rate validation', () => {
  const config = loadConfig('definitely-not-a-real-file.env');
  // Assert falsiness rather than emptiness: `assert.equal(key, '')` prints the
  // actual value on failure, which would put a real API key in the test log.
  assert.ok(!config.groqApiKey, 'no key is set by default');
  assert.equal(config.sttModel, DEFAULT_STT_MODEL);
  assert.equal(config.ttsProvider, 'edge');
  assert.equal(config.ttsModel, DEFAULT_TTS_MODEL);
  assert.equal(config.ttsVoice, '');
  assert.equal(config.ttsRate, '+0%');
  assert.equal(config.speak, false);
  assert.equal(config.micDevice, '');
});

test('voice activity defaults are on with sane bounds', () => {
  const config = loadConfig('definitely-not-a-real-file.env');
  assert.equal(config.voiceVad, true);
  assert.equal(config.voiceSilenceMs, 1200);
  assert.equal(config.voiceNoiseDb, -35);
  assert.equal(config.voiceMaxUtteranceMs, 30000);
  assert.equal(config.voiceBargeIn, true);
  assert.equal(config.voiceBargeDb, -25);
  assert.equal(config.voiceHfpRouting, true);
  assert.equal(config.voiceAddress, 'sir');
  assert.equal(config.voiceSpeakItems, 8);
  assert.equal(config.voiceSpeakSentences, 6);
  assert.equal(config.voiceSpeakMaxChars, 1200);
  assert.equal(config.voiceFullRead, false);
  assert.equal(config.voiceSummaryNote, DEFAULT_SUMMARY_NOTE);
});

test('voice env overrides parse and clamp', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-voice-env-'));
  const file = path.join(dir, '.env');
  fs.writeFileSync(
    file,
    [
      'VOICE_VAD=off',
      'VOICE_SILENCE_MS=99999', // clamps to 10000
      'VOICE_NOISE_DB=-12.5',
      'VOICE_BARGE_IN=0',
      'VOICE_ADDRESS=none', // disables the salutation
      'VOICE_SPEAK_ITEMS=3',
      'VOICE_FULL_READ=on',
      'VOICE_SUMMARY_NOTE=Heads up {address}: {spoken}/{total} shown.',
    ].join('\n')
  );
  const config = loadConfig(file);
  fs.rmSync(dir, { recursive: true, force: true });
  assert.equal(config.voiceVad, false);
  assert.equal(config.voiceSilenceMs, 10000);
  assert.equal(config.voiceNoiseDb, -12.5);
  assert.equal(config.voiceBargeIn, false);
  assert.equal(config.voiceAddress, '');
  assert.equal(config.voiceSpeakItems, 3);
  assert.equal(config.voiceFullRead, true);
  assert.equal(config.voiceSummaryNote, 'Heads up {address}: {spoken}/{total} shown.');
});

test('tts provider resolves to groq with a key, edge without', () => {
  assert.equal(resolveTtsProvider({ ttsProvider: 'auto', groqApiKey: 'k' }), 'groq');
  assert.equal(resolveTtsProvider({ ttsProvider: 'auto', groqApiKey: '' }), 'edge');
  assert.equal(resolveTtsProvider({ ttsProvider: 'edge', groqApiKey: 'k' }), 'edge');
  assert.equal(resolveTtsVoice({ ttsVoice: '' }, 'groq'), 'tara');
  assert.equal(resolveTtsVoice({ ttsVoice: '' }, 'edge'), 'en-US-AriaNeural');
  assert.equal(resolveTtsVoice({ ttsVoice: 'mia' }, 'groq'), 'mia');
});

test('sentence chunking respects the size cap', () => {
  const text = 'First sentence here. Second one is longer than the rest. Short.';
  const chunks = chunkSentences(text, 30);
  assert.ok(chunks.length >= 2);
  assert.ok(chunks.every((c) => c.length <= 30));
  assert.equal(chunks.join(' '), text);
  const giant = `word `.repeat(100).trim();
  assert.ok(chunkSentences(giant, 30).every((c) => c.length <= 30));
});

function makeWav(samples) {
  const pcm = Buffer.alloc(samples.length * 2);
  samples.forEach((s, i) => pcm.writeInt16LE(s, i * 2));
  const head = Buffer.alloc(44);
  head.write('RIFF', 0);
  head.writeUInt32LE(36 + pcm.length, 4);
  head.write('WAVE', 8);
  head.write('fmt ', 12);
  head.writeUInt32LE(16, 16);
  head.writeUInt16LE(1, 20);
  head.writeUInt16LE(1, 22);
  head.writeUInt32LE(24000, 24);
  head.writeUInt32LE(48000, 28);
  head.writeUInt16LE(2, 32);
  head.writeUInt16LE(16, 34);
  head.write('data', 36);
  head.writeUInt32LE(pcm.length, 40);
  return Buffer.concat([head, pcm]);
}

test('edge handshake token is a stable 64-hex windowed hash', () => {
  const fixed = 1789633200.5;
  const a = generateSecMsGec(fixed);
  const b = generateSecMsGec(fixed + 60);
  const c = generateSecMsGec(fixed + 600);
  assert.match(a, /^[0-9A-F]{64}$/);
  assert.equal(a, b);
  assert.notEqual(a, c);
});

test('edge handshake target carries token, connection id and browser headers', () => {
  const { host, path, headers } = edgeWsTarget();
  assert.equal(host, 'speech.platform.bing.com');
  assert.match(path, /TrustedClientToken=[0-9A-F]{32}/);
  assert.match(path, /ConnectionId=[0-9a-f]{32}/);
  assert.match(path, /Sec-MS-GEC=[0-9A-F]{64}/);
  assert.match(path, /Sec-MS-GEC-Version=1-/);
  assert.ok(headers.Origin.startsWith('chrome-extension://'));
  assert.ok(headers.Cookie.startsWith('muid='));
  assert.match(headers['User-Agent'], /Edg\//);
});

test('edge date string matches the JS-style format', () => {
  const s = edgeDateString(new Date(Date.UTC(2026, 8, 17, 8, 59, 42)));
  assert.equal(s, 'Thu Sep 17 2026 08:59:42 GMT+0000 (Coordinated Universal Time)');
});

test('ssml carries pitch and volume', () => {
  const ssml = buildSsml({ voice: 'en-US-AriaNeural', rate: '+0%', text: 'hi' });
  assert.ok(ssml.includes("pitch='+0Hz'") && ssml.includes("volume='+0%'"));
});

test('wav concat joins pcm under one header', () => {
  const joined = concatWav([makeWav([1, 2]), makeWav([3])]);
  assert.equal(joined.subarray(0, 4).toString(), 'RIFF');
  assert.equal(joined.readInt16LE(44), 1);
  assert.equal(joined.readInt16LE(48), 3);
  assert.equal(joined.readUInt32LE(40), 6);
  assert.deepEqual(concatWav([makeWav([9])]), makeWav([9]));
});
