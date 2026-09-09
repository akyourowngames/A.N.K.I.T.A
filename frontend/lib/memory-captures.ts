'use client';
import { useEffect, useState } from 'react';
import { API_URL } from './api';

export type Captures = { counts: Record<string, number>; recent: { id: string; user_text: string; status: string; error: string; created_at: number }[] };
export function useMemoryCaptures() {
  const [captures, setCaptures] = useState<Captures | null>(null);
  const [connected, setConnected] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const read = async () => {
      try {
        const response = await fetch(`${API_URL}/api/memory/captures`, { signal: controller.signal });
        if (!response.ok) throw new Error('Memory unavailable');
        const data = await response.json();
        if (!controller.signal.aborted) { setCaptures(data); setConnected(true); }
      } catch { if (!controller.signal.aborted) setConnected(false); }
      finally { if (!controller.signal.aborted) timer = setTimeout(read, 3000); }
    };
    read();
    return () => { controller.abort(); clearTimeout(timer); };
  }, []);
  return { captures, connected };
}
