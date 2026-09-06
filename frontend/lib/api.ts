export const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export type ToolStep = { id: number; name: string; args: Record<string, any>; result: string; done: boolean };
export type Msg = {
  role: 'user' | 'assistant';
  content: string;
  tools?: ToolStep[];
  toolsUsed?: number;
  model?: string;
  pendingTools?: boolean;
};

export type AgentCallbacks = {
  onToken: (t: string) => void;
  onToolStart: (name: string, args: any, id: number) => void;
  onToolEnd: (id: number, name: string, result: string) => void;
  onMeta?: (m: any) => void;
};

export async function streamAgent(
  message: string, sessionId: string | null, cb: AgentCallbacks,
  opts?: { model?: string }
): Promise<{ session_id: string; full: string; toolsUsed: number }> {
  const res = await fetch(`${API_URL}/api/chat/agent`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, session_id: sessionId, model: opts?.model }),
  });
  if (!res.ok) {
    const t = await res.text().catch(() => '');
    throw new Error(`HTTP ${res.status}: ${t.slice(0, 300)}`);
  }
  if (!res.body) throw new Error('no stream');
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = '';
  let full = '';
  let sid = sessionId || '';
  let toolsUsed = 0;
  const flush = (chunk: string) => {
    buf += chunk;
    const parts = buf.split('\n\n');
    buf = parts.pop() || '';
    for (const p of parts) {
      const lines = p.split('\n');
      let ev = '', data = '';
      for (const l of lines) {
        if (l.startsWith('event:')) ev = l.slice(6).trim();
        else if (l.startsWith('data:')) data += l.slice(5).trim();
      }
      if (!data) continue;
      try {
        const j = JSON.parse(data);
        if (ev === 'meta') { if (j.session_id) { sid = j.session_id; cb.onMeta?.(j); } }
        else if (ev === 'token' || (!ev && j.token)) { const t = j.token || ''; full += t; cb.onToken(t); }
        else if (ev === 'tool_start') cb.onToolStart(j.name || 'tool', j.args || {}, j.id || 0);
        else if (ev === 'tool_end') { toolsUsed++; cb.onToolEnd(j.id || 0, j.name || 'tool', j.result || ''); }
        else if (ev === 'done') { if (j.full) full = j.full; if (j.session_id) sid = j.session_id; if (j.tools_used) toolsUsed = j.tools_used; }
        else if (ev === 'error') throw new Error(j.error || 'agent error');
        else if (j.token) { full += j.token; cb.onToken(j.token); }
        else if (j.full && !full) full = j.full;
      } catch (e: any) {
        if (e?.message && !String(e.message).startsWith('Unexpected')) throw e;
      }
    }
  };
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    flush(dec.decode(value, { stream: true }));
  }
  flush('');
  return { session_id: sid, full, toolsUsed };
}

export async function streamChat(message: string, sessionId: string | null, onToken: (t: string) => void, onMeta?: (m: any) => void) {
  const full: string[] = [''];
  await streamAgent(message, sessionId, {
    onToken: (t) => { full[0] += t; onToken(t); },
    onToolStart: () => {}, onToolEnd: () => {}, onMeta,
  });
  return { session_id: sessionId || '', full: full[0] };
}

export async function getSessions(limit = 40) {
  const r = await fetch(`${API_URL}/api/sessions?limit=${limit}`);
  if (!r.ok) throw new Error(`sessions ${r.status}`);
  return r.json();
}

export async function getModels() {
  const r = await fetch(`${API_URL}/api/models`);
  return r.json();
}
