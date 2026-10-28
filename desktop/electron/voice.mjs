import fs from 'node:fs';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import * as channel from '../../src/channels/voice.mjs';
import { useHandsFreePlayback } from '../../src/channels/audio-device.mjs';
import { createVoiceBrain, createAcknowledgements, voiceReplyForSpeech } from '../../src/core/voice-session.mjs';
import { createVoiceNarrator } from '../../src/core/voice-narrator.mjs';
import { configuredSecrets, redactText } from '../../src/core/redact.mjs';
import { VoiceTaskStore, voiceTaskReport } from '../../src/automation/voice-task.mjs';
import { VoiceJobs } from '../../src/automation/voice-jobs.mjs';
import { VoiceSpeechQueue } from '../../src/automation/voice-speech-queue.mjs';
import { emptyVoiceState, voiceStatePatch, VOICE_EVENT, VOICE_METER_INTERVAL_MS, VOICE_BARGE_GUARD_MS, VOICE_POLL_MS, VOICE_CAPTION_CHARS, VOICE_ERROR_CHARS, VOICE_UPDATE_CHARS, VOICE_API_REQUIRED_MESSAGE } from '../shared/voice.mjs';
import { CHATGPT_BROWSER_PROVIDER } from '../shared/chatgpt-browser.mjs';

const DESKTOP_VOICE_PROVIDER = 'baseten'; // Desktop voice uses the Meta planner without changing typed-chat settings.
const DESKTOP_SPEECH_PROVIDER = 'sarvam'; // Both speech directions use the configured Sarvam credentials.
const PUBLIC_STEPS = 12; // Most recent observed actions shown in a bounded cross-window snapshot.
const WAV_EXTENSION = 'wav'; // Existing channel helper expects an extension without a dot.
const MILLISECONDS_PER_SECOND = 1000;
const END_VOICE_PATTERN = /^(exit|quit|end voice)[.!?]?$/i; // Only a complete explicit exit phrase ends a session.
const ERRORS = Object.freeze({ owner: 'Choose an existing conversation to start voice.', busy: 'This conversation is already working. Wait for it to finish.',
  takeover: 'End voice in the other conversation first.', key: 'Add your Sarvam key in Voice settings.',
  browser: VOICE_API_REQUIRED_MESSAGE,
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
    const config = getConfig();
    this.jobs = new VoiceJobs({ store: new VoiceTaskStore({ directory, limit: config.voiceTaskLimit, secrets: configuredSecrets(config) }),
      concurrency: config.voiceMaxParallelJobs,
      run: (entry, options) => engine.runVoiceJob(entry, { ...options, brain: entry.context.audioSession.brain, jobs: this.jobs }),
      onUpdate: task => this.updateJobs(task.ownerId),
      onComplete: async task => {
        await engine.deliverVoiceJob(task);
        const session = this.jobs.entries.get(task.id)?.context.audioSession;
        if (session && this.owns(session)) this.report(session, task);
      },
      onError: error => { if (this.current) this.publish(this.current, { error: error.message }); },
    });
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
  restingPhase(session) { return this.jobs.list(session.threadId).some(job => job.status === 'waiting_for_approval') ? 'approval' : 'listening'; }

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
    session.speech = new VoiceSpeechQueue({ gapMs: session.config.voiceSpeechGapMs, historyLimit: session.config.voiceTaskLimit,
      play: (audio, { signal }) => this.io.playMp3(audio, { signal, rejectOnFailure: true }), stop: () => this.io.stopPlayback(),
      onStart: item => {
        session.playingAt = Date.now();
        const line = item.line?.text || '';
        const phase = this.restingPhase(session) === 'approval' ? 'approval' : 'speaking';
        this.publish(session, item.kind === 'progress' ? { phase, update: line } :
          { phase, caption: line, captionRole: 'assistant', update: '' });
      },
      onFinish: () => { session.playingAt = 0; if (this.owns(session) && !session.paused) this.publish(session, { phase: this.restingPhase(session) }); },
      onError: error => this.fail(session, error),
    });
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
    let heardSpeech = false;
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
          if (session.playingAt && (!session.config.voiceBargeIn || Date.now() - session.playingAt < VOICE_BARGE_GUARD_MS)) return;
          const action = detector.feed(event);
          if (action === 'speech') {
            heardSpeech = true; session.userSpeaking = true;
            session.speech?.interrupt();
          }
          if (action === 'speech' && barge && !interrupted) { interrupted = true; onSpeech?.(); }
          if (action === 'end') finish();
        } });
      const disconnected = () => { entry.error = new Error(ERRORS.disconnected); finish(); };
      entry.handle.child?.once('close', disconnected);
      try { await abortable(entry.handle.ready, session.audio.signal); }
      catch (error) {
        // A pause deliberately closes a starting ffmpeg child; its normal exit is not a device failure.
        if (entry.stopping || session.paused || !this.owns(session)) return null;
        throw error;
      }
      if (!this.owns(session) || session.paused) finish();
      if (!barge && !ended && !session.playingAt) this.publish(session, { phase: this.restingPhase(session), update: '' });
      timeout = setTimeout(finish, session.config.voiceMaxUtteranceMs);
      await done;
      entry.handle.child?.removeListener('close', disconnected);
      const recorded = await this.stopInput(session);
      if (entry.error) throw entry.error;
      if (!recorded || !heardSpeech || !this.owns(session) || session.paused || (barge && !interrupted)) return null;
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
      if (!heard || !this.owns(session)) {
        if (this.owns(session) && !session.paused) { session.userSpeaking = false; session.speech.resume(); }
        continue;
      }
      const text = heard.text.trim();
      if (END_VOICE_PATTERN.test(text)) { await this.end(); return; }
      session.language = heard.languageCode || '';
      this.publish(session, { caption: text, captionRole: 'user', phase: 'working', error: null });
      await this.delegate(session, heard);
      heard = null;
      if (!this.owns(session)) return;
      session.userSpeaking = false;
      session.speech.resume();
    }
  }

  async delegate(session, heard) {
    const config = session.config;
    const ack = session.acks.next(session.language);
    const context = { ...this.engine.captureVoiceContext(session.threadId), audioSession: session };
    const task = await this.jobs.submit({ ownerId: session.threadId, transcript: heard.text, language: heard.languageCode,
      confidence: heard.confidence, context,
      speech: { minIntervalMs: config.voiceJobSpeakMinIntervalMs, gapMs: 0, waitUpdateMs: config.voiceJobWaitUpdateMs },
      speak: (event, options) => this.progress(session, event, options),
    });
    if (ack) void session.speech.offer({ jobId: task.id, kind: 'receipt', line: { text: ack.text }, prepare: async () => ack.audio, signal: session.audio.signal });
    return task;
  }

  updateJobs(ownerId) {
    const session = this.current;
    if (!session || session.threadId !== ownerId) return;
    const jobs = this.jobs.list(ownerId).map(task => ({ id: task.id, label: task.label, status: task.status, resourcesHeld: task.resourcesHeld,
      waitingFor: task.waitingFor, summary: task.summary.slice(0, VOICE_CAPTION_CHARS), error: task.error?.slice(0, VOICE_ERROR_CHARS) || null,
      steps: task.steps.slice(-PUBLIC_STEPS).map(({ index, label, tool, state }) => ({ index, label: label.slice(0, VOICE_UPDATE_CHARS), tool: tool.slice(0, VOICE_UPDATE_CHARS), state })) }));
    this.publish(session, { jobs, task: jobs[0] || null,
      ...(this.owns(session) && !session.paused ? jobs.some(job => job.status === 'waiting_for_approval') ? { phase: 'approval' } :
        this.state.phase === 'approval' ? { phase: session.playingAt ? 'speaking' : 'listening' } : {} : {}) });
  }

  progress(session, event, { signal, beginPlayback }) {
    const combined = AbortSignal.any([signal, session.audio.signal]), line = { text: '' };
    return session.speech.offer({ jobId: event.taskId, kind: 'progress', signal: combined, line,
      prepare: async queueSignal => {
        line.text = await session.narrate(event, { signal: queueSignal });
        return line.text && this.owns(session) ? this.synthesize(session, line.text) : null;
      }, beginPlayback: () => this.owns(session) && beginPlayback(line.text) });
  }

  report(session, task) {
    const text = voiceReplyForSpeech(voiceTaskReport(task), { maxChars: session.config.voiceSpeakMaxChars });
    if (!text) return;
    void session.speech.offer({ jobId: task.id, kind: 'report', signal: session.audio.signal, line: { text },
      prepare: () => this.synthesize(session, text, task.language) });
  }

  async pause() {
    const session = this.current;
    if (!session || !this.owns(session)) return this.snapshot();
    session.paused = true;
    session.speech?.interrupt();
    this.publish(session, { paused: true, phase: 'paused', inputLevel: 0 });
    await this.stopInput(session);
    return this.snapshot();
  }
  async resume() {
    const session = this.current;
    if (session && this.owns(session)) { session.paused = false; session.speech?.resume(); this.publish(session, { paused: false, phase: 'starting' }); }
    return this.snapshot();
  }
  async end() {
    const session = this.current;
    if (!session) return this.snapshot();
    session.audio.abort(); this.io.stopPlayback();
    await session.speech?.close();
    this.publish(session, { active: false, paused: false, phase: 'idle', inputLevel: 0, update: '' });
    await this.stopInput(session);
    session.routing?.restore?.(); session.routing = null;
    return this.snapshot();
  }
  async cancelWork({ taskId, all = false } = {}) {
    const session = this.current;
    if (!session) return this.snapshot();
    if (all) this.jobs.cancelOwner(session.threadId);
    else if (taskId || this.state.task?.id) this.jobs.cancel(taskId || this.state.task.id, { ownerId: session.threadId });
    return this.snapshot();
  }
  async ownerDeleted(threadId) { this.jobs.cancelOwner(threadId); if (this.current?.threadId === threadId) await this.end(); }
  async fail(session, error) {
    if (error.name === 'AbortError' || !this.owns(session)) return;
    await this.end();
    this.publish(session, { phase: 'error', error: error.message });
  }
  async close() {
    await this.end();
    await this.jobs.close();
  }
}
