import { VOICE_STREAM_UNSUPPORTED } from './voice.mjs';
const STREAM_CLIP_KIND = 'voice-stream'; // Private reusable clip identity; audio never crosses renderer IPC.
export const isVoiceStreamClip = audio => audio?.kind === STREAM_CLIP_KIND;

/** Prepare only the first provider chunk; retain a reusable descriptor for report controls. */
export async function prepareVoiceStreamClip({ stream, buffer, signal }) {
  let cached, seed;
  const prepare = async currentSignal => {
    currentSignal?.throwIfAborted();
    const controller = new AbortController();
    const requestSignal = currentSignal ? AbortSignal.any([currentSignal, controller.signal]) : controller.signal;
    const started = performance.now();
    const iterator = stream({ signal: requestSignal })[Symbol.asyncIterator]();
    try {
      const first = await iterator.next();
      currentSignal?.throwIfAborted();
      if (first.done) throw new Error('Speech stream ended without audio.');
      return { iterator, first, controller, signal: requestSignal, mode: 'streaming', fallback: '', firstChunkMs: performance.now() - started };
    } catch (error) {
      controller.abort();
      await iterator.return?.();
      if (currentSignal?.aborted || error.code !== VOICE_STREAM_UNSUPPORTED || !buffer) throw error;
      const audio = await buffer({ signal: currentSignal });
      currentSignal?.throwIfAborted();
      cached = audio;
      return { mode: 'buffered', fallback: 'provider', firstChunkMs: performance.now() - started };
    }
  };
  seed = await prepare(signal);
  const clip = { kind: STREAM_CLIP_KIND, mode: seed.mode, fallback: seed.fallback, firstChunkMs: seed.firstChunkMs,
    async *open({ signal: playbackSignal, onDelivery } = {}) {
      playbackSignal?.throwIfAborted();
      if (cached) { onDelivery?.({ mode: clip.mode === 'buffered' ? 'buffered' : 'cached', fallback: clip.fallback, firstChunkMs: clip.firstChunkMs }); yield cached; return; }
      const ready = seed && !seed.signal?.aborted ? seed : await prepare(playbackSignal);
      seed = null;
      Object.assign(clip, { mode: ready.mode, fallback: ready.fallback, firstChunkMs: ready.firstChunkMs });
      onDelivery?.({ mode: ready.mode, fallback: ready.fallback, firstChunkMs: ready.firstChunkMs });
      if (cached) { yield cached; return; }
      const chunks = [];
      const cancel = () => ready.controller.abort();
      playbackSignal?.addEventListener('abort', cancel, { once: true });
      try {
        playbackSignal?.throwIfAborted();
        chunks.push(ready.first.value); yield ready.first.value;
        for (;;) {
          const next = await ready.iterator.next();
          playbackSignal?.throwIfAborted();
          if (next.done) break;
          chunks.push(next.value); yield next.value;
        }
        cached = Buffer.concat(chunks);
      } finally { playbackSignal?.removeEventListener('abort', cancel); ready.controller.abort(); await ready.iterator.return?.(); }
    } };
  return clip;
}
