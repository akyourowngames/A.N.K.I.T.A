import fs from 'node:fs';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import * as channel from '../../src/channels/voice.mjs';
import { DesktopAudioDevices } from './audio-devices.mjs';
import { isPrivateAudioOutput } from '../../src/channels/audio-device.mjs';
import { createVoiceBrain, createAcknowledgements, createVoiceReportSpeech } from '../../src/core/voice-session.mjs';
import { createVoiceNarrator } from '../../src/core/voice-narrator.mjs';
import { configuredSecrets, redactText } from '../../src/core/redact.mjs';
import { VoiceTaskStore, voiceTaskReport } from '../../src/automation/voice-task.mjs';
import { VoiceJobs } from '../../src/automation/voice-jobs.mjs';
import { VOICE_FINAL_STATES } from '../../src/automation/voice-task-policy.mjs';
import { VoiceSpeechQueue } from '../../src/automation/voice-speech-queue.mjs';
import { emptyVoiceState, voiceStatePatch, voiceCommand, VOICE_EVENT, VOICE_METER_INTERVAL_MS, VOICE_BARGE_GUARD_MS, VOICE_POLL_MS, VOICE_CAPTION_CHARS, VOICE_ERROR_CHARS, VOICE_UPDATE_CHARS, VOICE_API_REQUIRED_MESSAGE, VOICE_PUBLIC_STEPS } from '../shared/voice.mjs';
import { CHATGPT_BROWSER_PROVIDER } from '../shared/chatgpt-browser.mjs';

const DESKTOP_VOICE_PROVIDER = 'baseten'; // Desktop voice uses the Meta planner without changing typed-chat settings.
const DESKTOP_SPEECH_PROVIDER = 'sarvam'; // Both speech directions use the configured Sarvam credentials.
const WAV_EXTENSION = 'wav'; // Existing channel helper expects an extension without a dot.
const MILLISECONDS_PER_SECOND = 1000;
const PLAYBACK_TEST_LINE = 'Hi, this is Ankita. If you can hear me clearly, your voice output is ready.'; // One short spoken setup check, never a planner request.
const PLAYBACK_TEST_LANGUAGE = 'en-IN'; // Same Sarvam language path as normal English speech.
const PLAYBACK_TEST_BUSY = 'Finish the speaker test before starting voice.';
const PLAYBACK_TEST_ACTIVE = 'End voice before testing your speakers.';
const SPEAKER_ECHO_SETTLE_MS = 300; // Milliseconds: let output buffers/room echo fade before reopening a speaker microphone.
const STANDBY_CUE_MS = 1400; // Milliseconds: a one-shot wake ring, longer than the CSS animation to be seen once.
const STOPPED_LINE = 'Stopped.'; // Spoken confirmation after a stop word cancels work.
// Fallbacks mirror config.mjs defaults, so a host that omits these keys (older
// configs, test harnesses) still gets a sane ladder instead of a zero-length timer.
const FALLBACK_IDLE_MS = 90000;
const FALLBACK_STANDBY_MS = 600000;
const positive = (value, fallback) => Number.isFinite(Number(value)) && Number(value) > 0 ? Number(value) : fallback;
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
    this.devices = new DesktopAudioDevices();
    this.io = { ...channel,
      audioDeps: async () => (await this.devices.inspect()).deps,
      listMicrophones: async () => (await this.devices.inspect()).microphones,
      listAudioDevices: async () => { const result = await this.devices.inspect(); if (result.outputError) throw new Error(result.outputError); return result.devices; },
      getDefaultRenderId: async () => (await this.devices.inspect()).defaultRenderId,
      useHandsFreePlayback: microphone => this.devices.route({ microphone, hfp: true }),
      usePlaybackDevice: outputDevice => this.devices.route({ outputDevice }),
      playbackIsolated: async ({ outputDevice, device }) => {
        if (device) return isPrivateAudioOutput(device);
        const found = await this.devices.inspect();
        return isPrivateAudioOutput(found.devices.find(item => item.id === (outputDevice || found.defaultRenderId)));
      }, watchPlayback: listener => this.devices.watch(listener), ...io };
    this.state = emptyVoiceState();
    this.current = null;
    const config = getConfig();
    this.jobs = new VoiceJobs({ store: new VoiceTaskStore({ directory, limit: config.voiceTaskLimit, secrets: configuredSecrets(config) }),
      concurrency: config.voiceMaxParallelJobs,
      run: (entry, options) => engine.runVoiceJob(entry, { ...options, brain: entry.context.audioSession.brain, jobs: this.jobs }),
      onUpdate: task => this.updateJobs(task.ownerId),
      onComplete: async (task, result) => {
        const context = this.jobs.entries.get(task.id)?.context;
        const session = context?.audioSession;
        if (session && this.owns(session)) {
          if (!(task.status === 'done' && result.outcome.speechHandled)) this.report(session, task, context.speech?.turn);
          session.speech.finishTurn(context.speech?.turn);
          // Named work is over: go back to the resting level (standby with a
          // wake word) instead of leaving a free-listening mic open.
          if (!this.busy(session)) this.settle(session);
        }
        await engine.deliverVoiceJob(task);
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
  restingPhase(session) {
    if (this.jobs.list(session.threadId).some(job => job.status === 'waiting_for_approval')) return 'approval';
    return session.asleep === true ? 'standby' : 'listening';
  }

  async status({ refresh = false } = {}) {
    if (refresh) this.devices.invalidate();
    const config = this.getConfig();
    const issues = [];
    if (!config.sarvamApiKey) issues.push(ERRORS.key);
    try { createVoiceBrain({ ...config, voiceProvider: config.voiceProvider || DESKTOP_VOICE_PROVIDER }, this.engine); }
    catch (error) { issues.push(this.clean(error.message)); }
    const deps = await this.io.audioDeps();
    if (!deps.ffmpeg || !deps.ffplay) issues.push(ERRORS.audio);
    const microphones = deps.ffmpeg ? await this.io.listMicrophones().catch(() => []) : [];
    if (!microphones.length) issues.push(ERRORS.mic);
    let outputs = [], defaultOutput = '';
    try {
      outputs = (await this.io.listAudioDevices()).filter(device => device.flow === 'render').map(({ id, name }) => ({ id, name: this.clean(name) }));
      const defaultId = await this.io.getDefaultRenderId();
      defaultOutput = outputs.find(device => device.id === defaultId)?.name || '';
    } catch (error) { issues.push(this.clean(error.message)); }
    return { state: this.snapshot(), ready: !issues.length, issues, microphones: microphones.map(mic => ({ name: this.clean(mic.name) })), microphone: config.micDevice || '',
      outputs, defaultOutput, outputDevice: config.voiceOutputDevice || '' };
  }

  async start({ threadId } = {}) {
    if (this.ending) await this.ending;
    if (this.preview) throw new Error(PLAYBACK_TEST_BUSY);
    if (this.current && this.owns(this.current)) {
      if (this.current.threadId !== threadId) throw new Error(ERRORS.takeover);
      await this.current.ready;
      return this.snapshot();
    }
    if (!this.engine.listTeammates().some(thread => thread.id === threadId)) throw new Error(ERRORS.owner);
    const config = { ...this.getConfig(), sttProvider: DESKTOP_SPEECH_PROVIDER, ttsProvider: DESKTOP_SPEECH_PROVIDER };
    if (config.provider === CHATGPT_BROWSER_PROVIDER) throw new Error(ERRORS.browser);
    if (!config.sarvamApiKey) throw new Error(ERRORS.key);
    const brain = createVoiceBrain({ ...config, voiceProvider: config.voiceProvider || DESKTOP_VOICE_PROVIDER }, this.engine);
    const session = { id: randomUUID(), threadId, config, brain, audio: new AbortController(), paused: false, asleep: false,
      input: null, task: null, taskAbort: null, lastMeterAt: 0, language: '', routing: null, idleTimer: null, standbyTimer: null };
    this.current = session;
    this.publish(session, { ...emptyVoiceState(), sessionId: session.id, threadId, active: true, phase: 'starting' });
    session.ready = this.prepare(session).catch(async error => {
      // End during discovery/prewarm is expected, including callers sharing this startup.
      if (error.name === 'AbortError' && session.audio.signal.aborted) return;
      await this.fail(session, error); throw error;
    });
    await session.ready;
    if (this.owns(session)) {
      // A session with a wake word starts asleep: the first thing you say must be
      // the wake word, rather than any nearby speech being transcribed.
      if (this.behavior(session).wake) this.rest(session);
      else this.armIdle(session);
      session.loop = this.loop(session).catch(error => this.fail(session, error));
    }
    return this.snapshot();
  }

  async prepare(session) {
    const deps = await abortable(this.io.audioDeps(), session.audio.signal);
    if (!deps.ffmpeg || !deps.ffplay) throw new Error(ERRORS.audio);
    const microphones = await abortable(this.io.listMicrophones(), session.audio.signal);
    const preferred = session.config.micDevice?.toLowerCase();
    session.microphone = (preferred && microphones.find(mic => mic.name.toLowerCase().includes(preferred))) || microphones[0];
    if (!session.microphone) throw new Error(ERRORS.mic);
    this.publish(session, { microphone: session.microphone.name });
    session.acks = createAcknowledgements({ synthesize: (text, language) => this.synthesize(session, text, language) });
    session.narrate = this.io.narrate || createVoiceNarrator({ client: session.brain?.client || this.engine.client,
      model: session.brain?.model || this.engine.model, secrets: configuredSecrets(session.config) });
    session.speech = new VoiceSpeechQueue({ gapMs: session.config.voiceSpeechGapMs, historyLimit: session.config.voiceTaskLimit,
      play: (audio, options) => this.play(session, audio, options), stop: () => this.io.stopPlayback(),
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
    session.routingReady = this.routeOutput(session.config, session.microphone.name);
    session.routing = await session.routingReady;
    if (!this.owns(session)) return; // End owns restoration after the pending switch settles.
    session.bargeIn = Boolean(session.config.voiceBargeIn && await this.io.playbackIsolated({ outputDevice: session.config.voiceOutputDevice, device: session.routing?.device }));
    if (!this.owns(session)) return;
    if (session.bargeIn) {
      session.monitorReady = this.io.watchPlayback(() => this.outputChanged(session));
      session.monitor = await session.monitorReady.catch(() => null);
      session.bargeIn = Boolean(session.monitor?.isolated && !session.outputChanged);
    }
    if (!this.owns(session)) return;
    await abortable(session.acks.prewarm(), session.audio.signal);
  }

  async routeOutput(config, microphone) {
    if (config.voiceOutputDevice) return this.io.usePlaybackDevice(config.voiceOutputDevice);
    return config.voiceHfpRouting ? this.io.useHandsFreePlayback(microphone) : null;
  }

  async testPlayback() {
    if (this.ending) await this.ending;
    if (this.current && this.owns(this.current)) throw new Error(PLAYBACK_TEST_ACTIVE);
    if (this.preview) throw new Error(PLAYBACK_TEST_BUSY);
    const config = { ...this.getConfig() };
    if (!config.sarvamApiKey) throw new Error(ERRORS.key);
    const preview = { audio: new AbortController(), config };
    this.preview = preview;
    let routing;
    try {
      const deps = await abortable(this.io.audioDeps(), preview.audio.signal);
      if (!deps.ffplay) throw new Error(ERRORS.audio);
      const microphones = await abortable(this.io.listMicrophones(), preview.audio.signal);
      const preferred = config.micDevice?.toLowerCase();
      const microphone = (preferred && microphones.find(mic => mic.name.toLowerCase().includes(preferred))) || microphones[0];
      routing = await this.routeOutput(config, microphone?.name);
      if (preview.audio.signal.aborted) return { cancelled: true };
      const audio = await abortable(this.synthesize(preview, PLAYBACK_TEST_LINE, PLAYBACK_TEST_LANGUAGE), preview.audio.signal);
      await this.io.playMp3(audio, { signal: preview.audio.signal, rejectOnFailure: true });
      return { cancelled: preview.audio.signal.aborted };
    } catch (error) {
      if (error.name === 'AbortError' && preview.audio.signal.aborted) return { cancelled: true };
      throw error;
    } finally {
      try { await routing?.restore(); } finally { if (this.preview === preview) this.preview = null; }
    }
  }

  async synthesize(session, text, detected = session.language) {
    const languageCode = this.io.chooseSarvamLanguage({ text, detected });
    return this.io.synthesizeSarvam({ apiKey: session.config.sarvamApiKey, model: session.config.sarvamTtsModel,
      speaker: this.io.resolveSarvamSpeaker(session.config, languageCode), languageCode, text });
  }

  async play(session, audio, { signal }) {
    if (session.bargeIn) return this.io.playMp3(audio, { signal, rejectOnFailure: true });
    let release;
    const quiet = new Promise(resolve => { release = resolve; });
    session.outputQuiet = quiet;
    try {
      await this.stopInput(session); // Close capture before any speaker audio can be recorded.
      if (signal.aborted || !this.owns(session)) return;
      await this.io.playMp3(audio, { signal, rejectOnFailure: true });
      if (this.owns(session)) await abortable(wait(SPEAKER_ECHO_SETTLE_MS), session.audio.signal);
    } finally {
      if (session.outputQuiet === quiet) session.outputQuiet = null;
      release();
    }
  }

  outputChanged(session) {
    if (!this.owns(session)) return;
    session.outputChanged = true; session.bargeIn = false;
    session.outputVersion = (session.outputVersion || 0) + 1;
    if (session.input) session.input.feedback = true;
    session.speech?.interrupt({ requeueReports: true });
    void this.stopInput(session).then(() => {
      if (this.owns(session) && !session.paused) session.speech?.resume();
    }).catch(error => this.fail(session, error));
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
    const outputVersion = session.outputVersion || 0;
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
          if (session.playingAt && (!session.bargeIn || Date.now() - session.playingAt < VOICE_BARGE_GUARD_MS)) return;
          const action = detector.feed(event);
          // Any real sound restarts the quiet countdown at the current stage, so a
          // wake-only mic only closes after a genuinely silent spell.
          if (action === 'speech') this.touchIdle(session);
          if (action === 'speech') {
            if (!heardSpeech) entry.speechTurn = session.speech.interrupt();
            heardSpeech = true; session.userSpeaking = true;
          }
          if (action === 'speech' && barge && !interrupted) { interrupted = true; onSpeech?.(); }
          if (action === 'end') finish();
        } });
      const disconnected = () => { if (!entry.stopping) entry.error = new Error(ERRORS.disconnected); finish(); };
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
      if (!recorded || !heardSpeech || entry.feedback || !this.owns(session) || session.paused || (barge && !interrupted)) {
        if (this.owns(session) && !session.paused) await session.speech.falseInterruption(entry.speechTurn);
        return null;
      }
      this.publish(session, { phase: 'transcribing' });
      const heard = await abortable(this.io.transcribeAudio({ config: session.config, wavPath: outFile }), session.audio.signal);
      if (this.owns(session) && outputVersion === (session.outputVersion || 0) && !entry.feedback && heard?.text?.trim()) return { ...heard, speechTurn: entry.speechTurn };
      if (this.owns(session) && !session.paused) await session.speech.falseInterruption(entry.speechTurn);
      return null;
    } finally {
      clearTimeout(timeout); session.audio.signal.removeEventListener('abort', abort);
      if (session.input === entry) await this.stopInput(session);
      fs.rmSync(outFile, { force: true });
    }
  }

  /** True while the session is asleep: only the wake word is acted on. */
  asleep(session) { return session.asleep === true; }

  /**
   * Attention ladder timers. Quiet listening sleeps to wake-only after the idle
   * delay, then closes the microphone after the standby delay. Any accepted turn
   * or resume restarts the ladder from full listening.
   */
  armIdle(session) {
    this.clearIdle(session);
    if (!this.owns(session) || session.paused) return;
    session.asleep = false;
    this.startIdleTimer(session);
  }

  /** The default resting state for a session with a wake word. */
  rest(session) {
    this.clearIdle(session);
    if (!this.owns(session) || session.paused) return;
    session.asleep = true;
    this.publish(session, { phase: 'standby', update: '' });
    this.startIdleTimer(session);
  }

  /**
   * Return to the resting state after a finished request: standby when a wake
   * word is on (so the mic never listens freely), otherwise keep listening.
   */
  settle(session) {
    if (!this.owns(session) || session.paused) return;
    if (this.busy(session)) { this.ensureIdle(session); return; }
    if (this.behavior(session).wake) this.rest(session);
    else this.armIdle(session);
  }

  /**
   * The loop re-opens the microphone after every capture, so a missing timer
   * (a long job, a resumed session) must be repaired there rather than trusted
   * to an earlier turn.
   */
  ensureIdle(session) {
    if (!this.owns(session) || session.paused) return;
    if (!session.idleTimer && !session.standbyTimer) this.startIdleTimer(session);
  }

  clearIdle(session) {
    if (session.idleTimer) { clearTimeout(session.idleTimer); session.idleTimer = null; }
    if (session.standbyTimer) { clearTimeout(session.standbyTimer); session.standbyTimer = null; }
  }

  /** One countdown for the current stage: quiet listening, or quiet wake-only. */
  startIdleTimer(session) {
    const behavior = this.behavior(session);
    if (session.asleep) {
      session.standbyTimer = setTimeout(() => {
        session.standbyTimer = null;
        if (this.owns(session) && !session.paused) void this.sleepToPaused(session);
      }, behavior.standbyMs);
      return;
    }
    session.idleTimer = setTimeout(() => {
      session.idleTimer = null;
      if (!this.owns(session) || session.paused) return;
      // With the wake word off there is no middle rung: quiet goes straight to
      // a closed microphone.
      if (this.behavior(session).wake) this.sleep(session);
      else void this.sleepToPaused(session);
    }, behavior.idleMs);
  }

  /** Restart the countdown for the stage we are already in, without changing it. */
  touchIdle(session) {
    if (!this.owns(session) || session.paused) return;
    this.clearIdle(session);
    this.startIdleTimer(session);
  }

  /**
   * Behaviour toggles are read live, not from the session's startup snapshot, so
   * saving them in Settings takes effect without ending voice.
   */
  behavior(session) {
    const live = this.getConfig?.() || {};
    const pick = (key, fallback) => live[key] === undefined ? session.config[key] ?? fallback : live[key];
    return {
      wake: pick('voiceWakeWord', true) !== false,
      stop: pick('voiceStopWord', true) !== false,
      // 0 is meaningful here: a bare wake word returns to standby immediately.
      idleMs: pick('voiceIdleMs', FALLBACK_IDLE_MS) >= 0 ? Number(pick('voiceIdleMs', FALLBACK_IDLE_MS)) : FALLBACK_IDLE_MS,
      standbyMs: positive(pick('voiceStandbyMs', FALLBACK_STANDBY_MS), FALLBACK_STANDBY_MS),
    };
  }

  /** True while real work should keep the mic at full attention. */
  busy(session) {
    if (session.playingAt) return true;
    return this.jobs.list(session.threadId).some(job => !VOICE_FINAL_STATES.includes(job.status) || job.resourcesHeld);
  }

  /**
   * Drop to wake-only listening and start the countdown to closing the mic.
   * Sleeping during speech or active work would hide the "speaking"/"approval"
   * state and could silence a report, so those defer the transition.
   */
  sleep(session) {
    if (!this.owns(session) || session.paused || session.asleep) return;
    if (this.busy(session)) { this.startIdleTimer(session); return; }
    session.asleep = true;
    this.publish(session, { phase: 'standby', update: '' });
    this.startIdleTimer(session);
  }

  /** Close the microphone until the user resumes voice. */
  async sleepToPaused(session) {
    if (!this.owns(session) || session.paused) return;
    await this.pause();
  }

  /** Wake from standby: back to full listening with a one-shot visual cue. */
  wake(session) {
    this.clearIdle(session);
    session.asleep = false;
    const { idleMs, wake: wakeWord } = this.behavior(session);
    // A zero window means "say the word, then speak the request": go straight
    // back to standby instead of leaving the mic in free listening.
    if (wakeWord && idleMs <= 0) {
      this.rest(session);
      this.publish(session, { wakeCue: Date.now() + STANDBY_CUE_MS });
      return;
    }
    this.startIdleTimer(session);
    this.publish(session, { phase: this.restingPhase(session), update: '', wakeCue: Date.now() + STANDBY_CUE_MS });
  }

  async loop(session) {
    let heard = null;
    while (this.owns(session)) {
      if (session.paused) { await wait(VOICE_POLL_MS); continue; }
      if (session.outputQuiet) { await session.outputQuiet; continue; }
      heard ||= await this.capture(session);
      if (!heard || !this.owns(session)) {
        if (this.owns(session) && !session.paused) { session.userSpeaking = false; session.speech.resume(); }
        this.ensureIdle(session);
        continue;
      }
      const behavior = this.behavior(session);
      const command = voiceCommand(heard.text, { wake: behavior.wake, stop: behavior.stop, listening: !this.asleep(session) });
      if (command.kind === 'end') { await this.end(); return; }
      if (command.kind === 'stop') {
        // Interrupt speech here; cancel in-flight work only when nothing is playing,
        // so a mid-reply "stop" silences it without killing the job behind it.
        session.speech.interrupt();
        if (!session.playingAt) await this.cancelWork({ all: true });
        const wasAsleep = this.asleep(session);
        if (wasAsleep) this.wake(session); else { this.armIdle(session); this.publish(session, { phase: this.restingPhase(session) }); }        // The caption survives the next capture (which resets only phase/update),
        // so the confirmation does not flash away when listening resumes.
        this.publish(session, { caption: STOPPED_LINE, captionRole: 'assistant', update: '' });
        session.speech.falseInterruption(heard.speechTurn);
        session.userSpeaking = false;
        session.speech.resume();
        heard = null;
        continue;
      }
      // Asleep: anything without the wake word is dropped here - never captioned,
      // delegated, journaled or saved. This is the accepted cost of standby.
      if (command.kind === 'ignored') {
        session.speech.falseInterruption(heard.speechTurn);
        heard = null;
        session.userSpeaking = false;
        continue;
      }
      if (this.asleep(session)) this.wake(session);
      else this.armIdle(session);
      if (command.kind === 'wake') {
        session.speech.falseInterruption(heard.speechTurn);
        heard = null;
        session.userSpeaking = false;
        continue;
      }
      const text = command.text;
      session.language = heard.languageCode || '';
      this.publish(session, { caption: text, captionRole: 'user', phase: 'working', error: null });
      session.speech.acceptTurn(heard.speechTurn);
      try { await this.delegate(session, { ...heard, text }); }
      catch (error) { session.speech.finishTurn(heard.speechTurn); this.publish(session, { error: error.message }); }
      heard = null;
      if (!this.owns(session)) return;
      session.userSpeaking = false;
      session.speech.resume();
      // Back to standby after each request when a wake word is on, so nothing is
      // transcribed unless it starts with the wake word.
      this.settle(session);
    }
  }

  async delegate(session, heard) {
    const config = session.config;
    const ack = session.acks.next(session.language);
    const context = { ...this.engine.captureVoiceContext(session.threadId), audioSession: session,
      speech: { queue: session.speech, turn: heard.speechTurn, signal: session.audio.signal } };
    const task = await this.jobs.submit({ ownerId: session.threadId, transcript: heard.text, language: heard.languageCode,
      confidence: heard.confidence, context,
      speech: { minIntervalMs: config.voiceJobSpeakMinIntervalMs, gapMs: 0, waitUpdateMs: config.voiceJobWaitUpdateMs },
      speak: (event, options) => this.progress(session, event, options, heard.speechTurn),
    });
    if (ack) void session.speech.offer({ jobId: task.id, kind: 'receipt', turn: heard.speechTurn, line: { text: ack.text }, prepare: async () => ack.audio, signal: session.audio.signal });
    return task;
  }

  updateJobs(ownerId) {
    const session = this.current;
    if (!session || session.threadId !== ownerId) return;
    const jobs = this.jobs.list(ownerId).map(task => ({ id: task.id, label: task.label, status: task.status, resourcesHeld: task.resourcesHeld,
      waitingFor: task.waitingFor, summary: task.summary.slice(0, VOICE_CAPTION_CHARS), error: task.error?.slice(0, VOICE_ERROR_CHARS) || null,
      steps: task.steps.slice(-VOICE_PUBLIC_STEPS).map(({ index, label, tool, state }) => ({ index, label: label.slice(0, VOICE_UPDATE_CHARS), tool: tool.slice(0, VOICE_UPDATE_CHARS), state })) }));
    this.publish(session, { jobs, task: jobs[0] || null,
      ...(this.owns(session) && !session.paused ? jobs.some(job => job.status === 'waiting_for_approval') ? { phase: 'approval' } :
        this.state.phase === 'approval' ? { phase: session.playingAt ? 'speaking' : 'listening' } : {} : {}) });
  }

  progress(session, event, { signal, beginPlayback }, turn) {
    const combined = AbortSignal.any([signal, session.audio.signal]), line = { text: '' };
    return session.speech.offer({ jobId: event.taskId, kind: 'progress', turn, signal: combined, line,
      prepare: async queueSignal => {
        line.text = await session.narrate(event, { signal: queueSignal });
        return line.text && this.owns(session) ? this.synthesize(session, line.text) : null;
      }, beginPlayback: () => this.owns(session) && beginPlayback(line.text) });
  }

  report(session, task, turn) {
    const item = createVoiceReportSpeech({ jobId: task.id, label: task.label, text: voiceTaskReport(task),
      maxChars: session.config.voiceSpeakMaxChars, signal: session.audio.signal, turn,
      synthesize: text => this.synthesize(session, text, task.language) });
    if (item) void session.speech.offer(item);
  }

  async pause() {
    const session = this.current;
    if (!session || !this.owns(session)) return this.snapshot();
    session.paused = true;
    this.clearIdle(session);
    session.asleep = false;
    session.speech?.interrupt({ requeueReports: true });
    this.publish(session, { paused: true, phase: 'paused', inputLevel: 0 });
    await this.stopInput(session);
    return this.snapshot();
  }
  async resume() {
    const session = this.current;
    if (session && this.owns(session)) {
      session.paused = false;
      await session.speech?.falseInterruption(session.speech.turn);
      session.speech?.resume(); this.publish(session, { paused: false, phase: 'starting' });
      // Resume is an explicit "I'm back": with a wake word, wait for the wake
      // word rather than listening freely.
      if (this.behavior(session).wake) this.rest(session);
      else this.armIdle(session);
    }
    return this.snapshot();
  }
  async end() {
    if (this.ending) return this.ending;
    this.ending = this.endAudio();
    try { return await this.ending; } finally { this.ending = null; }
  }
  async endAudio() {
    if (this.preview) { this.preview.audio.abort(); this.io.stopPlayback(); }
    const session = this.current;
    if (!session) return this.snapshot();
    this.clearIdle(session);
    session.audio.abort(); this.io.stopPlayback();
    await session.speech?.close();
    this.publish(session, { active: false, paused: false, phase: 'idle', inputLevel: 0, update: '' });
    await this.stopInput(session);
    await session.routingReady?.catch(() => null); // Startup still reports routing failure; teardown must finish.
    await session.monitorReady?.catch(() => null);
    await session.monitor?.stop(); session.monitor = null;
    await session.routing?.restore?.(); session.routing = null;
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
    if (!this.owns(session)) return;
    await this.end();
    this.publish(session, { phase: 'error', error: error.message });
  }
  async close() {
    await this.end();
    await this.jobs.close();
    await this.devices.close();
  }
}
