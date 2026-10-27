import fs from 'node:fs';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import * as channel from '../../src/channels/voice.mjs';
import { useHandsFreePlayback } from '../../src/channels/audio-device.mjs';
import { createVoiceBrain, createAcknowledgements, voiceReplyForSpeech } from '../../src/core/voice-session.mjs';
import { createVoiceNarrator } from '../../src/core/voice-narrator.mjs';
import { configuredSecrets, redactText } from '../../src/core/redact.mjs';
import { VoiceTaskStore, runVoiceTask, voiceTaskReport } from '../../src/automation/voice-task.mjs';
import { emptyVoiceState, voiceStatePatch, VOICE_EVENT, VOICE_METER_INTERVAL_MS, VOICE_BARGE_GUARD_MS, VOICE_POLL_MS, VOICE_CAPTION_CHARS, VOICE_ERROR_CHARS, VOICE_UPDATE_CHARS } from '../shared/voice.mjs';
import { CHATGPT_BROWSER_PROVIDER } from '../shared/chatgpt-browser.mjs';

const DESKTOP_VOICE_PROVIDER = 'baseten'; // Desktop voice uses the Meta planner without changing typed-chat settings.
const DESKTOP_SPEECH_PROVIDER = 'sarvam'; // Both speech directions use the configured Sarvam credentials.
const PUBLIC_STEPS = 12; // Most recent observed actions shown in a bounded cross-window snapshot.
const WAV_EXTENSION = 'wav'; // Existing channel helper expects an extension without a dot.
const MILLISECONDS_PER_SECOND = 1000;
const ERRORS = Object.freeze({ owner: 'Choose an existing conversation to start voice.', busy: 'This conversation is already working. Wait for it to finish.',
  takeover: 'End voice in the other conversation first.', key: 'Add your Sarvam key in Voice settings.',
  browser: 'Voice needs an API-backed conversation. Choose a model in Settings first.',
  audio: 'Voice needs ffmpeg and ffplay. Install them, then try again.', mic: 'No microphone found. Connect one and try again.',
  ended: 'Voice ended.', disconnected: 'The microphone disconnected. Check it and start voice again.' });
const abortError = () => new DOMException(ERRORS.ended, 'AbortError');
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));

/** Detach slow network preparation on end; its completion still cannot play stale audio. */
function abortable(promise, signal) {
  if (signal.aborted) return Promise.reject(abortError());
  return new Promise((resolve, reject) => {
    const abort = () => { cleanup(); reject(abortError()); };
    const cleanup = () => signal.removeEventListener('abort', abort);
    signal.addEventListener('abort', abort, { once: true });
    Promise.resolve(promise).then(value => { cleanup(); resolve(value); }, error => { cleanup(); reject(error); });
  });
}

/** One main-process audio owner. Renderer windows receive only this public state. */
export class DesktopVoice {
  constructor({ engine, getConfig, emit, directory, io = {} }) {
    this.engine = engine;
    this.getConfig = getConfig;
    this.emit = emit;
    this.directory = directory;
    this.io = { ...channel, useHandsFreePlayback, ...io };
    this.state = emptyVoiceState();
    this.current = null;
    this.work = new Set();
  }

  snapshot() { return structuredClone(this.state); }
  clean(text, config = this.getConfig()) { return redactText(String(text ?? ''), { secrets: configuredSecrets(config) }); }
  publish(session, patch) {
    if (this.current !== session) return;
    const safe = { ...patch };
    for (const key of ['caption', 'update', 'error', 'microphone']) if (safe[key] != null) safe[key] = this.clean(safe[key], session.config);
    this.state = voiceStatePatch(this.state, safe);
    try { this.emit({ type: VOICE_EVENT, state: this.snapshot() }); } catch { /* A closed window does not own the job. */ }
  }
  owns(session) { return this.current === session && !session.audio.signal.aborted; }

  async status() {
    const config = this.getConfig();
    const issues = [];
    if (!config.sarvamApiKey) issues.push(ERRORS.key);
    try { createVoiceBrain({ ...config, voiceProvider: config.voiceProvider || DESKTOP_VOICE_PROVIDER }, this.engine); }
    catch (error) { issues.push(this.clean(error.message)); }
    const deps = this.io.audioDeps();
    if (!deps.ffmpeg || !deps.ffplay) issues.push(ERRORS.audio);
    const microphones = deps.ffmpeg ? await this.io.listMicrophones().catch(() => []) : [];
    if (!microphones.length) issues.push(ERRORS.mic);
    return { state: this.snapshot(), ready: !issues.length, issues, microphones: microphones.map(mic => ({ name: this.clean(mic.name) })), microphone: config.micDevice || '' };
  }

  async start({ threadId } = {}) {
    if (this.current && this.owns(this.current)) {
      if (this.current.threadId !== threadId) throw new Error(ERRORS.takeover);
      await this.current.ready;
      return this.snapshot();
    }
    if (!this.engine.listTeammates().some(thread => thread.id === threadId)) throw new Error(ERRORS.owner);
    if (this.engine.turns.has(threadId)) throw new Error(ERRORS.busy);
    const config = { ...this.getConfig(), sttProvider: DESKTOP_SPEECH_PROVIDER, ttsProvider: DESKTOP_SPEECH_PROVIDER };
    if (config.provider === CHATGPT_BROWSER_PROVIDER) throw new Error(ERRORS.browser);
    if (!config.sarvamApiKey) throw new Error(ERRORS.key);
    const deps = this.io.audioDeps();
    if (!deps.ffmpeg || !deps.ffplay) throw new Error(ERRORS.audio);
    const brain = createVoiceBrain({ ...config, voiceProvider: config.voiceProvider || DESKTOP_VOICE_PROVIDER }, this.engine);
    const session = { id: randomUUID(), threadId, config, brain, audio: new AbortController(), paused: false,
      input: null, task: null, taskAbort: null, lastMeterAt: 0, language: '', routing: null };
    this.current = session;
    this.publish(session, { ...emptyVoiceState(), sessionId: session.id, threadId, active: true, phase: 'starting' });
    session.ready = this.prepare(session);
    try { await session.ready; }
    catch (error) { await this.fail(session, error); throw error; }
    if (this.owns(session)) session.loop = this.loop(session).catch(error => this.fail(session, error));
    return this.snapshot();
  }

  async prepare(session) {
    const microphones = await abortable(this.io.listMicrophones(), session.audio.signal);
    const preferred = session.config.micDevice?.toLowerCase();
    session.microphone = (preferred && microphones.find(mic => mic.name.toLowerCase().includes(preferred))) || microphones[0];
    if (!session.microphone) throw new Error(ERRORS.mic);
    this.publish(session, { microphone: session.microphone.name });
    session.acks = createAcknowledgements({ synthesize: (text, language) => this.synthesize(session, text, language) });
    session.narrate = this.io.narrate || createVoiceNarrator({ client: session.brain?.client || this.engine.client,
      model: session.brain?.model || this.engine.model, secrets: configuredSecrets(session.config) });
    await abortable(session.acks.prewarm(), session.audio.signal);
    if (session.config.voiceHfpRouting && this.owns(session)) session.routing = this.io.useHandsFreePlayback(session.microphone.name);
  }

  async synthesize(session, text, detected = session.language) {
    const languageCode = this.io.chooseSarvamLanguage({ text, detected });
    return this.io.synthesizeSarvam({ apiKey: session.config.sarvamApiKey, model: session.config.sarvamTtsModel,
      speaker: this.io.resolveSarvamSpeaker(session.config, languageCode), languageCode, text });
  }

  async stopInput(session) {
    const entry = session.input;
    if (!entry) return false;
    entry.finish();
    entry.stopping ||= Promise.resolve().then(() => entry.handle?.stop() || false);
    try { return await entry.stopping; }
    finally { if (session.input === entry) session.input = null; this.publish(session, { inputLevel: 0 }); }
  }

  async capture(session, { barge = false, onSpeech } = {}) {
    const outFile = this.io.tmpVoiceFile(WAV_EXTENSION);
    const detector = this.io.createTurnDetector();
    let finish;
    let interrupted = false;
    let ended = false;
    const done = new Promise(resolve => { finish = () => { ended = true; resolve(); }; });
    const entry = { finish, handle: null, stopping: null };
    session.input = entry;
    const abort = () => finish();
    session.audio.signal.addEventListener('abort', abort, { once: true });
    let timeout;
    try {
      entry.handle = this.io.openVoiceInput({ device: session.microphone.name, outFile, meter: true,
        noiseDb: barge ? session.config.voiceBargeDb : session.config.voiceNoiseDb,
        silenceSec: session.config.voiceSilenceMs / MILLISECONDS_PER_SECOND,
        onEvent: event => {
          if (!this.owns(session) || session.paused || ended) return;
          if (event.type === 'level' && Date.now() - session.lastMeterAt >= VOICE_METER_INTERVAL_MS) {
            session.lastMeterAt = Date.now(); this.publish(session, { inputLevel: event.level });
          }
          if (barge && !interrupted && (!session.playingAt || Date.now() - session.playingAt < VOICE_BARGE_GUARD_MS)) return;
          const action = detector.feed(event);
          if (action === 'speech' && barge && !interrupted) { interrupted = true; onSpeech?.(); }
          if (action === 'end') finish();
        } });
      const disconnected = () => { entry.error = new Error(ERRORS.disconnected); finish(); };
      entry.handle.child?.once('close', disconnected);
      await abortable(entry.handle.ready, session.audio.signal);
      if (!this.owns(session) || session.paused) finish();
      if (!barge && !ended) this.publish(session, { phase: 'listening', update: '' });
      timeout = setTimeout(finish, session.config.voiceMaxUtteranceMs);
      await done;
      entry.handle.child?.removeListener('close', disconnected);
      const recorded = await this.stopInput(session);
      if (entry.error) throw entry.error;
      if (!recorded || !this.owns(session) || session.paused || (barge && !interrupted)) return null;
      this.publish(session, { phase: 'transcribing' });
      const heard = await abortable(this.io.transcribeAudio({ config: session.config, wavPath: outFile }), session.audio.signal);
      return this.owns(session) && heard?.text?.trim() ? heard : null;
    } finally {
      clearTimeout(timeout); session.audio.signal.removeEventListener('abort', abort);
      if (session.input === entry) await this.stopInput(session);
      fs.rmSync(outFile, { force: true });
    }
  }

  async loop(session) {
    let heard = null;
    while (this.owns(session)) {
      if (session.paused) { await wait(VOICE_POLL_MS); continue; }
      heard ||= await this.capture(session);
      if (!heard || !this.owns(session)) continue;
      const text = heard.text.trim();
      if (/^(exit|quit|end voice)[.!?]?$/i.test(text)) { await this.end(); return; }
      session.language = heard.languageCode || '';
      this.publish(session, { caption: text, captionRole: 'user', phase: 'working', error: null });
      const task = await this.delegate(session, heard);
      heard = null;
      if (!this.owns(session)) return;
      const report = voiceReplyForSpeech(voiceTaskReport(task), { maxChars: session.config.voiceSpeakMaxChars });
      if (report) heard = await this.reply(session, report);
    }
  }

  async delegate(session, heard) {
    const config = session.config;
    const controller = new AbortController();
    session.taskAbort = controller;
    const store = new VoiceTaskStore({ directory: this.directory, limit: config.voiceTaskLimit, secrets: configuredSecrets(config) });
    const ack = session.acks.next(session.language);
    const acknowledgement = ack ? this.play(session, ack.audio).catch(() => {}) : Promise.resolve();
    const work = { session, controller };
    this.work.add(work);
    try {
      const result = await runVoiceTask({ store, transcript: heard.text, language: heard.languageCode, confidence: heard.confidence,
        signal: controller.signal, minIntervalMs: config.voiceJobSpeakMinIntervalMs, gapMs: config.voiceSpeechGapMs,
        waitUpdateMs: config.voiceJobWaitUpdateMs,
        onUpdate: task => {
          session.taskRecord = task;
          this.publish(session, { task: { id: task.id, status: task.status, summary: task.summary.slice(0, VOICE_CAPTION_CHARS), error: task.error?.slice(0, VOICE_ERROR_CHARS) || null,
            steps: task.steps.slice(-PUBLIC_STEPS).map(({ index, label, tool, state }) => ({ index, label: label.slice(0, VOICE_UPDATE_CHARS), tool: tool.slice(0, VOICE_UPDATE_CHARS), state })) },
            ...(task.status === 'waiting_for_approval' ? { phase: 'approval' } : this.owns(session) ? { phase: 'working' } : {}) });
        },
        speak: async (event, { signal, beginPlayback }) => {
          const combined = AbortSignal.any([signal, session.audio.signal]);
          const line = await abortable(session.narrate(event, { signal: combined }), combined);
          if (!line || !this.owns(session)) return;
          const audio = await abortable(this.synthesize(session, line), combined);
          await acknowledgement;
          if (combined.aborted || !this.owns(session) || !beginPlayback()) return;
          this.publish(session, { update: line });
          await this.play(session, audio, combined);
        },
        run: (observer, task) => {
          session.task = task;
          observer.approval = (tool, ask) => task.approval(tool, ask);
          return this.engine.runVoiceTurn(session.threadId, heard.text, observer, session.brain);
        } });
      await acknowledgement;
      return result.task;
    } finally { this.work.delete(work); session.task = null; session.taskAbort = null; }
  }

  async play(session, audio, signal = session.audio.signal) {
    if (!this.owns(session) || signal.aborted) return;
    await this.io.playMp3(audio, { signal });
    if (!signal.aborted && session.config.voiceSpeechGapMs > 0) await abortable(wait(session.config.voiceSpeechGapMs), signal);
  }

  async reply(session, text) {
    const controller = new AbortController();
    const signal = AbortSignal.any([controller.signal, session.audio.signal]);
    let speech;
    let capture;
    let barge = false;
    try {
      const synthesis = abortable(this.synthesize(session, text), signal);
      // Prepare the barge-in input alongside TTS, so ffmpeg startup adds no extra wait before speech.
      if (session.config.voiceBargeIn && !session.paused) {
        capture = this.capture(session, { barge: true, onSpeech: () => { barge = true; controller.abort(); this.io.stopPlayback(); } });
        // Attach immediately; a device failure must not become an unhandled rejection during TTS.
        capture.catch(() => {});
      }
      speech = await synthesis;
      if (!this.owns(session)) return null;
      this.publish(session, { phase: 'speaking', caption: text, captionRole: 'assistant', update: '' });
      session.playingAt = Date.now();
      await this.play(session, speech, signal);
    } catch (error) { if (error.name !== 'AbortError') throw error; }
    finally { session.playingAt = 0; if (!barge) await this.stopInput(session); }
    if (capture) return await capture;
    return null;
  }

  async pause() {
    const session = this.current;
    if (!session || !this.owns(session)) return this.snapshot();
    session.paused = true;
    this.publish(session, { paused: true, phase: 'paused', inputLevel: 0 });
    await this.stopInput(session);
    return this.snapshot();
  }
  async resume() {
    const session = this.current;
    if (session && this.owns(session)) { session.paused = false; this.publish(session, { paused: false, phase: session.task ? 'working' : 'starting' }); }
    return this.snapshot();
  }
  async end() {
    const session = this.current;
    if (!session) return this.snapshot();
    session.audio.abort(); session.task?.interruptSpeech(); this.io.stopPlayback();
    this.publish(session, { active: false, paused: false, phase: 'idle', inputLevel: 0, update: '' });
    await this.stopInput(session);
    session.routing?.restore?.(); session.routing = null;
    return this.snapshot();
  }
  async cancelWork() {
    const session = this.current;
    if (!session?.taskAbort) return this.snapshot();
    session.taskAbort.abort(); session.task?.interruptSpeech(); this.io.stopPlayback();
    this.engine.cancel(session.threadId);
    return this.snapshot();
  }
  async ownerDeleted(threadId) { if (this.current?.threadId === threadId) await this.end(); }
  async fail(session, error) {
    if (error.name === 'AbortError' || !this.owns(session)) return;
    await this.end();
    this.publish(session, { phase: 'error', error: error.message });
  }
  async close() {
    await this.end();
    for (const work of this.work) { work.controller.abort(); this.engine.cancel(work.session.threadId); }
  }
}
