import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import { transcribeGroq, convertAudio, resolveTtsProvider, resolveTtsVoice, synthesizeGroq, synthesizeEdge, voiceRuntimeCheck } from '../voice.mjs';

const VOICE_TEMP_PREFIX = 'ankita-channel-'; // Shared, collision-free temporary transcription files.
const VOICE_FILENAME = 'reply.ogg'; // Ogg output preserves the existing Telegram voice-note format.
const VOICE_MIME = 'audio/ogg'; // MIME for converted outbound channel speech.

/** Preserve the established channel speech providers while sharing lifecycle/cleanup. */
export async function transcribeChannelVoice(adapter, ref, config, { signal, cancelled = () => false } = {}) {
  const check = () => { signal?.throwIfAborted(); if (cancelled()) throw new DOMException('Channel stopped', 'AbortError'); };
  check();
  const unavailable = voiceRuntimeCheck();
  if (unavailable) throw new Error(unavailable);
  if (!config.groqApiKey) throw new Error('set a Groq API key to transcribe voice notes');
  const audio = await adapter.download(ref); check();
  const wav = await convertAudio(audio, { to: 'wav' }); check();
  const wavPath = path.join(os.tmpdir(), `${VOICE_TEMP_PREFIX}${randomUUID()}.wav`);
  try { await fs.writeFile(wavPath, wav); check(); const text = await transcribeGroq({ apiKey: config.groqApiKey, model: config.sttModel, wavPath }); check(); return text; }
  finally { try { await fs.unlink(wavPath); } catch {} }
}

export async function speakChannelReply(adapter, ref, text, config, log = () => {}) {
  try {
    const provider = resolveTtsProvider(config);
    const audio = provider === 'groq'
      ? await synthesizeGroq({ apiKey: config.groqApiKey, model: config.ttsModel, voice: resolveTtsVoice(config, 'groq'), text })
      : await synthesizeEdge({ voice: resolveTtsVoice(config, 'edge'), rate: config.ttsRate, text });
    const ogg = await convertAudio(audio, { to: 'ogg' });
    const file = { base64: ogg.toString('base64'), filename: VOICE_FILENAME, mime: VOICE_MIME, photo: false };
    if (adapter.voice) await adapter.voice(ref, file);
    else await adapter.upload(ref, file);
  } catch (error) { log(`channel voice reply failed: ${error.message}`); }
}
