'use client';

import { useEffect, useRef, useState } from 'react';
import { API_URL } from './api';

/** Record ordinary browser audio; recognition and language selection live on the server. */
export function useLocalStt(onText: (text: string) => void, onSubmit: (text: string) => void) {
  const [listening, setListening] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [language, setLanguage] = useState('auto');
  const [error, setError] = useState('');
  const recorder = useRef<MediaRecorder | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const request = useRef<AbortController | null>(null);
  const active = useRef(false);
  const acquiring = useRef(false);
  const callbacks = useRef({ onText, onSubmit });
  callbacks.current = { onText, onSubmit };

  function release() {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    stream.current?.getTracks().forEach(track => track.stop());
    stream.current = null;
  }

  useEffect(() => {
    active.current = true;
    const configRequest = new AbortController();
    fetch(`${API_URL}/api/voice/config`, { signal: configRequest.signal })
      .then(r => r.json()).then(config => { if (active.current) setLanguage(config.language || 'auto'); })
      .catch(() => {});
    return () => {
      active.current = false;
      configRequest.abort();
      request.current?.abort();
      const rec = recorder.current;
      if (rec) {
        rec.onstop = null;
        rec.ondataavailable = null;
        rec.onerror = null;
        if (rec.state !== 'inactive') rec.stop();
      }
      release();
    };
  }, []);

  async function transcribe(blob: Blob) {
    const abort = new AbortController();
    request.current = abort;
    setTranscribing(true);
    try {
      const body = new FormData();
      body.append('file', blob, 'recording');
      const response = await fetch(`${API_URL}/api/voice/stt?stream=true`, { method: 'POST', body, signal: abort.signal });
      if (!response.ok) {
        const problem = await response.json().catch(() => ({}));
        throw new Error(problem.detail || `Speech recognition failed (${response.status}).`);
      }
      if (!response.body) throw new Error('No speech recognition response.');
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '', completed = false;
      try {
        while (true) {
          const { done, value } = await reader.read();
          buffer += decoder.decode(value, { stream: !done });
          const frames = buffer.split(/\r?\n\r?\n/);
          buffer = frames.pop() || '';
          for (const frame of frames) {
            const lines = frame.split(/\r?\n/);
            const event = lines.find(line => line.startsWith('event:'))?.slice(6).trim();
            const data = lines.filter(line => line.startsWith('data:')).map(line => line.slice(5).trim()).join('\n');
            if (!data) continue;
            const result = JSON.parse(data);
            if (event === 'error') throw new Error(result.error || 'Speech recognition failed.');
            if (event === 'partial' && active.current) callbacks.current.onText(result.transcript || '');
            if (event === 'done') {
              completed = true;
              const text = (result.transcript || '').trim();
              if (!text) throw new Error('No speech detected. Check the microphone and try again.');
              if (active.current) {
                callbacks.current.onText(text);
                callbacks.current.onSubmit(text);
              }
            }
          }
          if (done) break;
        }
        if (!completed) throw new Error('Speech recognition connection ended early.');
      } finally {
        await reader.cancel().catch(() => {});
        reader.releaseLock();
      }
    } catch (exc) {
      if (active.current && !abort.signal.aborted) setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      request.current = null;
      if (active.current) setTranscribing(false);
    }
  }

  async function toggleMic() {
    if (recorder.current?.state === 'recording') {
      recorder.current.stop();
      return;
    }
    if (acquiring.current || request.current) return;
    setError('');
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      setError('Microphone recording requires HTTPS or localhost and MediaRecorder support.');
      return;
    }
    acquiring.current = true;
    try {
      const audio = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
      if (!active.current) { audio.getTracks().forEach(track => track.stop()); return; }
      stream.current = audio;
      const rec = new MediaRecorder(audio);
      recorder.current = rec;
      const chunks: Blob[] = [];
      let failed = false, bytes = 0;
      rec.ondataavailable = event => {
        bytes += event.data.size;
        if (bytes > 10 * 1024 * 1024) {
          failed = true;
          setError('Recording exceeds 10 MB. Try a shorter message.');
          if (rec.state !== 'inactive') rec.stop();
        } else if (event.data.size) chunks.push(event.data);
      };
      rec.onerror = () => { failed = true; setError('Microphone recording failed.'); release(); setListening(false); };
      rec.onstop = () => {
        release();
        recorder.current = null;
        if (!active.current) return;
        setListening(false);
        if (!failed) void transcribe(new Blob(chunks, { type: rec.mimeType }));
      };
      rec.start(1000);
      setListening(true);
      timer.current = setTimeout(() => { if (rec.state === 'recording') rec.stop(); }, 59000);
    } catch (exc) {
      release();
      if (active.current) { setListening(false); setError(exc instanceof Error ? exc.message : String(exc)); }
    } finally {
      acquiring.current = false;
    }
  }

  return { listening, transcribing, language, error, toggleMic };
}
