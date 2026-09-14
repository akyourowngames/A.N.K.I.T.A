'use client';
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { API_URL } from '@/lib/api';

type SavedMessage = { id: string; role: 'user' | 'assistant'; content: string; created_at: number };

export default function MemoryPage() {
  const [messages, setMessages] = useState<SavedMessage[]>([]);
  const [error, setError] = useState('');
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    fetch(`${API_URL}/api/memory/history`, { signal: controller.signal })
      .then(r => { if (!r.ok) throw new Error('Could not load saved conversations.'); return r.json(); })
      .then(data => { setMessages(data.messages); setLoaded(true); })
      .catch(e => { if (!controller.signal.aborted) setError(e.message); });
    return () => controller.abort();
  }, []);
  return <main className="min-h-screen bg-zinc-950 text-zinc-200 px-6 py-10">
    <div className="max-w-2xl mx-auto">
      <Link href="/" className="text-sm text-zinc-400 hover:text-white">← Back to chat</Link>
      <h1 className="text-2xl font-semibold mt-8">Saved conversation</h1>
      <p className="text-sm text-zinc-400 mt-2 mb-8">Recent messages Zumba can remember across chats. Older messages make room for new ones.</p>
      {error && <p role="alert" className="text-red-300">{error}</p>}
      {!loaded && !error && <p className="text-zinc-500">Loading…</p>}
      {loaded && !messages.length && <p className="text-zinc-500">Nothing saved yet. Start a conversation.</p>}
      <div className="space-y-6">{messages.map((m, i) => <article key={`${m.id}-${m.role}-${i}`} className="border-b border-zinc-800 pb-6">
        <div className="text-xs text-zinc-500 mb-2">{m.role === 'user' ? 'You' : 'Zumba'} · {new Date(m.created_at * 1000).toLocaleString()}</div>
        <p className="whitespace-pre-wrap break-words text-sm leading-6">{m.content}</p>
      </article>)}</div>
    </div>
  </main>;
}
