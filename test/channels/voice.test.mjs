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
  resolveSttProvider,
  resolveSarvamSpeaker,
  chooseSarvamLanguage,
  sttKeysMissing,
  parseKeyterms,
  transcribeSarvam,
  transcribeAudio,
  synthesizeSarvam,
  generateSecMsGec,
  edgeDateString,
  edgeWsTarget,
  buildSilenceFilter,
  parseSilenceLine,
  parseSilenceEvents,
  createSilenceParser,
  createTurnDetector,
  createVoiceMeterParser,
  buildVoiceInputFilter,
  splitListItems,
  splitSentences,
  renderSummaryNote,
  summarizeForSpeech,
  DEFAULT_SUMMARY_NOTE,
  DEFAULT_STT_MODEL,
  DEFAULT_TTS_MODEL,
  DEFAULT_SARVAM_STT_MODEL,
  DEFAULT_SARVAM_STT_MODE,
  DEFAULT_SARVAM_TTS_MODEL,
  DEFAULT_SARVAM_SPEAKER_HI,
  DEFAULT_SARVAM_SPEAKER_EN,
  SARVAM_MAX_KEYTERMS,
  SARVAM_TTS_MAX_CHARS,
} = await import('../../src/channels/voice.mjs');
const { loadConfig } = await import('../../src/core/config.mjs');
const { findHandsFreePlayback } = await import('../../src/channels/audio-device.mjs');

test('optional metering adds real RMS metadata without changing terminal silence detection', () => {
  const options = { noiseDb: -35, silenceSec: 0.8 };
  assert.equal(buildVoiceInputFilter(options), buildSilenceFilter(options));
  const filter = buildVoiceInputFilter({ ...options, meter: true });
  assert.ok(filter.startsWith(buildSilenceFilter(options)));
  assert.ok(filter.includes('astats=metadata=1:reset=1'));
  assert.ok(filter.includes('lavfi.astats.Overall.RMS_level'));
});

test('RMS input meter parses chunk boundaries, silence and malformed lines without inventing levels', () => {
  const meter = createVoiceMeterParser();
  assert.deepEqual(meter.push('lavfi.astats.Overall.RMS_'), []);
  const events = meter.push('level=-25.0\n[silencedetect] silence_start: 1.0\nlavfi.astats.Overall.RMS_level=-inf\n');
  assert.equal(events.length, 2);
  assert.equal(events[0].type, 'level');
  assert.ok(events[0].level > 0 && events[0].level < 1);
  assert.equal(events[1].level, 0);
  assert.deepEqual(meter.push('lavfi.astats.Overall.RMS_level=garbage\n'), []);
  assert.deepEqual(meter.push('lavfi.astats.Overall.RMS_level=0\n'), [{ type: 'level', level: 1 }]);
});

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
  const { synthesizeGroq } = await import('../../src/channels/voice.mjs');
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
  const { synthesizeGroq } = await import('../../src/channels/voice.mjs');
  const original = globalThis.fetch;
  t.after(() => { globalThis.fetch = original; });
  globalThis.fetch = async () => new Response('rate limited', { status: 429 });
  await assert.rejects(synthesizeGroq({ apiKey: 'k', text: 'hi' }), /Groq TTS 429/);
});

/* ------------------------------------------------------------------ */
/* Sarvam AI (Hinglish STT + TTS)                                      */
/* ------------------------------------------------------------------ */

const sarvamFixture = (t) => {
  const wav = tmpVoiceFile('wav');
  fs.writeFileSync(wav, Buffer.from('RIFF0000WAVEfmt ', 'latin1'));
  t.after(() => fs.rmSync(wav, { force: true }));
  return wav;
};

const stubFetch = (t, handler) => {
  const original = globalThis.fetch;
  t.after(() => { globalThis.fetch = original; });
  globalThis.fetch = handler;
};

test('sarvam stt posts the documented form and returns the detected language', async (t) => {
  const wav = sarvamFixture(t);
  let seen = null;
  stubFetch(t, async (url, init) => {
    const fields = {};
    for (const [k, v] of init.body.entries()) fields[k] = typeof v === 'string' ? v : v.name;
    seen = { url, headers: init.headers, fields };
    return new Response(
      JSON.stringify({ transcript: '  Ankita VS Code kholo.  ', language_code: 'hi-IN', language_probability: 0.91 }),
      { status: 200, headers: { 'Content-Type': 'application/json' } }
    );
  });

  const out = await transcribeSarvam({ apiKey: 'k-123', wavPath: wav, keyterms: ['Ankita', '   ', 'VS Code'] });

  assert.equal(seen.url, 'https://api.sarvam.ai/speech-to-text');
  // Sarvam uses its own header; a Bearer token is silently rejected.
  assert.equal(seen.headers['api-subscription-key'], 'k-123');
  assert.ok(!seen.headers.Authorization, 'never sends a Bearer header');
  assert.equal(seen.fields.model, DEFAULT_SARVAM_STT_MODEL);
  assert.equal(seen.fields.language_code, 'unknown', 'auto-detects rather than assuming English');
  assert.equal(seen.fields.mode, DEFAULT_SARVAM_STT_MODE);
  assert.equal(seen.fields.file, 'mic.wav');
  assert.equal(seen.fields.keyterms, JSON.stringify(['Ankita', 'VS Code']));
  assert.equal(out.text, 'Ankita VS Code kholo.');
  assert.equal(out.languageCode, 'hi-IN');
  assert.equal(out.confidence, 0.91);
});

test('sarvam stt omits keyterms when the list is empty', async (t) => {
  const wav = sarvamFixture(t);
  let fields = null;
  stubFetch(t, async (_url, init) => {
    fields = [...init.body.keys()];
    return new Response(JSON.stringify({ transcript: 'hi' }), { status: 200 });
  });
  await transcribeSarvam({ apiKey: 'k', wavPath: wav, keyterms: [] });
  assert.ok(!fields.includes('keyterms'), 'no empty array is sent');
});

test('sarvam key rejection names the variable to set', async (t) => {
  const wav = sarvamFixture(t);
  stubFetch(t, async () => new Response(JSON.stringify({ error: 'invalid key' }), { status: 403 }));
  await assert.rejects(
    transcribeSarvam({ apiKey: 'bad', wavPath: wav }),
    (err) => /SARVAM_API_KEY/.test(err.message) && /dashboard\.sarvam\.ai/.test(err.message)
  );
});

test('sarvam retries once on a rate limit, then succeeds', async (t) => {
  const wav = sarvamFixture(t);
  let calls = 0;
  stubFetch(t, async () => {
    calls++;
    if (calls === 1) return new Response('slow down', { status: 429 });
    return new Response(JSON.stringify({ transcript: 'second try', language_code: 'en-IN' }), { status: 200 });
  });
  const out = await transcribeSarvam({ apiKey: 'k', wavPath: wav });
  assert.equal(calls, 2);
  assert.equal(out.text, 'second try');
});

test('sarvam tts decodes base64 audio and requests mp3 for the chosen speaker', async (t) => {
  const audio = Buffer.from([0xff, 0xf3, 0xc0, 0xc4, 0x00, 0x11]);
  let seen = null;
  stubFetch(t, async (url, init) => {
    seen = { url, headers: init.headers, body: JSON.parse(init.body) };
    return new Response(JSON.stringify({ audios: [audio.toString('base64')] }), { status: 200 });
  });

  const out = await synthesizeSarvam({
    apiKey: 'k-123',
    speaker: DEFAULT_SARVAM_SPEAKER_HI,
    languageCode: 'hi-IN',
    text: 'Namaste, kaam ho gaya.',
  });

  assert.deepEqual(out, audio);
  assert.equal(seen.url, 'https://api.sarvam.ai/text-to-speech');
  assert.equal(seen.headers['api-subscription-key'], 'k-123');
  assert.equal(seen.headers['Content-Type'], 'application/json');
  assert.equal(seen.body.model, DEFAULT_SARVAM_TTS_MODEL);
  assert.equal(seen.body.speaker, DEFAULT_SARVAM_SPEAKER_HI);
  assert.equal(seen.body.language_code, 'hi-IN');
  // mp3 keeps the existing ffplay path working untouched.
  assert.equal(seen.body.output_audio_codec, 'mp3');
});

test('sarvam tts chunks a long reply instead of truncating it', async (t) => {
  const sentence = (i) => `Sentence ${i} ${'word '.repeat(40)}.`;
  const text = Array.from({ length: 12 }, (_, i) => sentence(i)).join(' ');
  assert.ok(text.length > SARVAM_TTS_MAX_CHARS, 'fixture is longer than one request');

  const parts = [];
  stubFetch(t, async (_url, init) => {
    const body = JSON.parse(init.body);
    assert.ok(body.text.length <= SARVAM_TTS_MAX_CHARS, 'each request respects the cap');
    parts.push(body.text);
    const audio = Buffer.from([0x01, parts.length]);
    return new Response(JSON.stringify({ audios: [audio.toString('base64')] }), { status: 200 });
  });

  const out = await synthesizeSarvam({ apiKey: 'k', text });
  assert.ok(parts.length >= 2, 'split into multiple requests');
  assert.equal(out.length, parts.length * 2, 'every chunk contributes audio');
});

test('sarvam tts with no audio is an error, not silence', async (t) => {
  stubFetch(t, async () => new Response(JSON.stringify({ audios: [] }), { status: 200 }));
  await assert.rejects(synthesizeSarvam({ apiKey: 'k', text: 'hello' }), /empty audio/i);
});

test('stt provider auto keeps groq and only falls back to sarvam', () => {
  assert.equal(resolveSttProvider({ sttProvider: 'auto', groqApiKey: 'g', sarvamApiKey: 's' }), 'groq');
  assert.equal(resolveSttProvider({ sttProvider: 'auto', groqApiKey: '', sarvamApiKey: 's' }), 'sarvam');
  assert.equal(resolveSttProvider({ sttProvider: 'sarvam', groqApiKey: 'g', sarvamApiKey: 's' }), 'sarvam');
  assert.equal(resolveSttProvider({ sttProvider: 'nonsense', groqApiKey: 'g' }), 'groq');
  assert.equal(sttKeysMissing({ sttProvider: 'sarvam', sarvamApiKey: '' }), 'SARVAM_API_KEY');
  assert.equal(sttKeysMissing({ sttProvider: 'groq', groqApiKey: '' }), 'GROQ_API_KEY');
  assert.equal(sttKeysMissing({ sttProvider: 'groq', groqApiKey: 'g' }), '');
});

test('sarvam speaker follows the detected language, TTS_VOICE still wins', () => {
  assert.equal(resolveSarvamSpeaker({}, 'hi-IN'), DEFAULT_SARVAM_SPEAKER_HI);
  assert.equal(resolveSarvamSpeaker({}, 'en-IN'), DEFAULT_SARVAM_SPEAKER_EN);
  assert.equal(resolveSarvamSpeaker({}, ''), DEFAULT_SARVAM_SPEAKER_EN);
  assert.equal(resolveSarvamSpeaker({ ttsVoice: 'custom' }, 'hi-IN'), 'custom');
  assert.equal(resolveTtsVoice({ ttsVoice: '' }, 'sarvam', 'hi-IN'), DEFAULT_SARVAM_SPEAKER_HI);
});

test('sarvam speech language follows the reply script, not a jumpy detector', () => {
  // A Hindi reply is always spoken by the Hindi voice, even if STT guessed wrong.
  assert.equal(chooseSarvamLanguage({ text: 'काम हो गया।', detected: 'en-IN' }), 'hi-IN');
  // Latin-script Hinglish still means a Hindi voice when the user spoke Hindi.
  assert.equal(chooseSarvamLanguage({ text: 'Kaam ho gaya.', detected: 'hi-IN' }), 'hi-IN');
  assert.equal(chooseSarvamLanguage({ text: 'Done.', detected: 'en-IN' }), 'en-IN');
  // Auto-detect really did return pa-IN for Hinglish one run; that must not pick
  // a Punjabi voice for an English sentence.
  assert.equal(chooseSarvamLanguage({ text: 'Done.', detected: 'pa-IN' }), 'en-IN');
  assert.equal(chooseSarvamLanguage({ text: 'Done.', detected: '' }), 'en-IN');
  assert.equal(chooseSarvamLanguage({ text: 'Done.', detected: 'ta-IN', fallback: 'ta-IN' }), 'ta-IN');
});

test('sarvam keyterms split, trim, drop blanks and cap at the documented limit', () => {
  assert.deepEqual(parseKeyterms('Ankita, VS Code ; ankit'), ['Ankita', 'VS Code', 'ankit']);
  assert.deepEqual(parseKeyterms(''), []);
  assert.deepEqual(parseKeyterms(undefined), []);
  assert.equal(parseKeyterms(Array.from({ length: SARVAM_MAX_KEYTERMS + 10 }, (_, i) => `t${i}`)).length, SARVAM_MAX_KEYTERMS);
});

test('transcription dispatch follows STT_PROVIDER and reports the language', async (t) => {
  const wav = sarvamFixture(t);
  const urls = [];
  stubFetch(t, async (url) => {
    urls.push(String(url));
    if (String(url).includes('groq')) return new Response(JSON.stringify({ text: 'groq text' }), { status: 200 });
    return new Response(
      JSON.stringify({ transcript: 'sarvam text', language_code: 'hi-IN', language_probability: 0.9 }),
      { status: 200 }
    );
  });

  const viaGroq = await transcribeAudio({
    config: { sttProvider: 'groq', groqApiKey: 'g', sttModel: DEFAULT_STT_MODEL },
    wavPath: wav,
  });
  assert.equal(viaGroq.text, 'groq text');
  assert.equal(viaGroq.provider, 'groq');
  assert.equal(viaGroq.languageCode, '', 'groq reports no language, so speech falls back');

  const viaSarvam = await transcribeAudio({
    config: {
      sttProvider: 'sarvam',
      sarvamApiKey: 's',
      sarvamSttModel: DEFAULT_SARVAM_STT_MODEL,
      sarvamSttMode: DEFAULT_SARVAM_STT_MODE,
      sarvamKeyterms: ['Ankita'],
    },
    wavPath: wav,
  });
  assert.equal(viaSarvam.text, 'sarvam text');
  assert.equal(viaSarvam.languageCode, 'hi-IN');
  assert.equal(viaSarvam.provider, 'sarvam');

  assert.ok(urls[0].includes('api.groq.com'), 'groq config hits groq');
  assert.ok(urls[1].includes('api.sarvam.ai'), 'sarvam config hits sarvam');
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
  // Sarvam stays opt-in: its key comes from the environment only, and the
  // provider gate is "auto", so nobody's existing Groq/Edge setup changes.
  assert.equal(config.sarvamApiKey, process.env.SARVAM_API_KEY || '', 'read from env, never baked in');
  assert.equal(config.sttProvider, 'auto');
  assert.equal(config.sarvamSttModel, DEFAULT_SARVAM_STT_MODEL);
  assert.equal(config.sarvamSttMode, DEFAULT_SARVAM_STT_MODE);
  assert.equal(config.sarvamTtsModel, DEFAULT_SARVAM_TTS_MODEL);
  assert.equal(config.sarvamSpeakerHi, DEFAULT_SARVAM_SPEAKER_HI);
  assert.equal(config.sarvamSpeakerEn, DEFAULT_SARVAM_SPEAKER_EN);
  assert.equal(config.sarvamTtsLanguage, 'en-IN');
  // Keyterms default to the assistant's own name; a recogniser mangles names.
  assert.ok(config.sarvamKeyterms.includes(config.agentName), 'agent name is a default keyterm');
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
  // Sarvam is explicit-only, so an auto setup never silently changes voice.
  assert.equal(resolveTtsProvider({ ttsProvider: 'sarvam', groqApiKey: 'k' }), 'sarvam');
  assert.equal(resolveTtsProvider({ ttsProvider: 'auto', groqApiKey: 'k', sarvamApiKey: 's' }), 'groq');
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
