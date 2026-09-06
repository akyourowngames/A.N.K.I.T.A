'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  Send, Mic, Plus, Trash2, Volume2, VolumeX, Loader2, Wrench,
  ChevronDown, ChevronRight, Terminal, Globe, Database, Brain,
  Copy, Check, Menu, X, Zap, Circle, AlertTriangle, CheckCircle2
} from 'lucide-react';
import { streamAgent, getSessions, getModels, Msg, ToolStep, API_URL } from '../lib/api';

const SUGGESTIONS = ['Plan my day', 'What can you do?', 'Search latest AI news', 'Check python version'];

type ToolKind = 'shell' | 'web' | 'memory' | 'style' | 'other';

function toolKind(name: string): ToolKind {
  const n = name.toLowerCase();
  if (n.includes('shell') || n.includes('run') || n.includes('exec')) return 'shell';
  if (n.includes('web') || n.includes('search') || n.includes('fetch') || n.includes('news')) return 'web';
  if (n.includes('memory') || n.includes('vault') || n.includes('goal') || n.includes('brief')) return 'memory';
  if (n.includes('soul')) return 'style';
  return 'other';
}

const KIND_STYLE: Record<ToolKind, { icon: any; chip: string; dot: string; label: string }> = {
  shell: { icon: Terminal, chip: 'bg-emerald-400/10 text-emerald-300 border-emerald-400/20', dot: 'bg-emerald-400', label: 'shell' },
  web: { icon: Globe, chip: 'bg-sky-400/10 text-sky-300 border-sky-400/20', dot: 'bg-sky-400', label: 'web' },
  memory: { icon: Database, chip: 'bg-violet-400/10 text-violet-300 border-violet-400/20', dot: 'bg-violet-400', label: 'memory' },
  style: { icon: Brain, chip: 'bg-amber-400/10 text-amber-300 border-amber-400/20', dot: 'bg-amber-400', label: 'style' },
  other: { icon: Wrench, chip: 'bg-zinc-400/10 text-zinc-300 border-white/10', dot: 'bg-zinc-400', label: 'tool' },
};

function isErrorResult(step: ToolStep): boolean {
  const r = (step.result || '').trimStart().toLowerCase();
  return r.startsWith('error') || r.startsWith('traceback') || r.startsWith('http 4') || r.startsWith('http 5') || r.includes('failed');
}

function primaryArg(args: Record<string, any>): string {
  const vals = Object.entries(args || {});
  if (!vals.length) return '';
  const pick = vals.find(([k]) => ['query', 'url', 'command', 'text', 'cmd', 'q'].includes(k.toLowerCase())) || vals[0];
  const v = pick[1];
  const s = typeof v === 'string' ? v : JSON.stringify(v);
  const oneLine = s.replace(/\s+/g, ' ').trim();
  return oneLine.length > 120 ? oneLine.slice(0, 120) + '…' : oneLine;
}

function resultPreview(result: string): string {
  const t = (result || '').trim();
  if (!t) return '';
  const lines = t.split('\n').filter((l) => l.trim());
  const first = (lines[0] || '').replace(/\s+/g, ' ').trim();
  const extra = lines.length > 1 ? `  ·  +${lines.length - 1} more line${lines.length - 1 > 1 ? 's' : ''}` : '';
  const head = first.length > 130 ? first.slice(0, 130) + '…' : first;
  return head + extra;
}

function ToolCard({ step }: { step: ToolStep }) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const kind = toolKind(step.name);
  const meta = KIND_STYLE[kind];
  const Icon = meta.icon;
  const err = step.done && isErrorResult(step);
  const label = step.name.replace(/^zumba__/, '').replace(/_/g, ' ');
  const argLine = primaryArg(step.args);
  const preview = step.done ? resultPreview(step.result) : '';

  useEffect(() => {
    if (step.done) return;
    const t0 = Date.now();
    const iv = setInterval(() => setElapsed((Date.now() - t0) / 1000), 200);
    return () => clearInterval(iv);
  }, [step.done]);

  const copyResult = (e: React.MouseEvent) => {
    e.stopPropagation();
    navigator.clipboard.writeText(step.result || '').catch(() => {});
    setCopied(true);
    setTimeout(() => setCopied(false), 1200);
  };

  return (
    <div className={`tool-card ${err ? 'tool-error' : ''}`}>
      <button onClick={() => setOpen(!open)} className="tool-header w-full text-left">
        <span className={`grid place-items-center w-7 h-7 rounded-lg shrink-0 border ${meta.chip}`}>
          {step.done
            ? (err ? <AlertTriangle size={13} /> : <Icon size={13} />)
            : <Loader2 size={13} className="animate-spin" />}
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-2 min-w-0">
            <span className="text-[13px] font-medium text-zinc-200 truncate">{label}</span>
            <span className={`text-[9px] uppercase tracking-[0.12em] font-semibold border rounded-full px-1.5 py-px shrink-0 ${meta.chip}`}>
              {meta.label}
            </span>
          </span>
          {(argLine || preview) && (
            <span className="block text-[11px] text-zinc-500 truncate font-mono mt-0.5">
              {step.done && preview ? preview : argLine}
            </span>
          )}
        </span>
        <span className="flex items-center gap-1.5 shrink-0">
          {!step.done && (
            <span className="text-[10px] font-mono text-zinc-500 tabular-nums">{elapsed.toFixed(1)}s</span>
          )}
          <span className={`flex items-center gap-1 text-[10px] uppercase tracking-[0.14em] font-semibold ${err ? 'text-red-400' : step.done ? 'text-emerald-400' : 'text-zinc-500'}`}>
            {step.done
              ? (err ? <><AlertTriangle size={11} /> error</> : <><CheckCircle2 size={11} /> done</>)
              : <><Loader2 size={11} className="animate-spin" /> running</>}
          </span>
        </span>
        {open ? <ChevronDown size={14} className="text-zinc-500 shrink-0" /> : <ChevronRight size={14} className="text-zinc-500 shrink-0" />}
      </button>
      {open && (
        <div className="tool-body">
          {Object.keys(step.args || {}).length > 0 && (
            <div className="mb-2">
              <div className="tool-section-title">input</div>
              <pre className="tool-mono">
                {JSON.stringify(step.args, null, 1).slice(0, 1500)}
              </pre>
            </div>
          )}
          <div>
            <div className="tool-section-title flex items-center justify-between">
              <span>result</span>
              {step.result && (
                <button onClick={copyResult} className="flex items-center gap-1 text-zinc-500 hover:text-zinc-200 transition">
                  {copied ? <Check size={11} /> : <Copy size={11} />}
                  {copied ? 'copied' : 'copy'}
                </button>
              )}
            </div>
            <pre className={`tool-mono tool-result ${err ? 'tool-result-error' : ''}`}>
              {step.result || (step.done ? '(empty result)' : 'running…')}
            </pre>
          </div>
        </div>
      )}
    </div>
  );
}

function CodeBlock({ lang, code }: { lang: string; code: string }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard.writeText(code).catch(() => {});
    setCopied(true);
    setTimeout(() => setCopied(false), 1200);
  };
  return (
    <div className="md-codeblock">
      <div className="md-codeblock-bar">
        <span className="md-codeblock-lang">{lang || 'code'}</span>
        <button onClick={copy} className="md-codeblock-copy">
          {copied ? <Check size={11} /> : <Copy size={11} />}
          {copied ? 'copied' : 'copy'}
        </button>
      </div>
      <pre><code>{code}</code></pre>
    </div>
  );
}

function mdComponents() {
  return {
    a: (p: any) => <a {...p} target="_blank" rel="noreferrer" />,
    h1: (p: any) => <h1 {...p} />,
    h2: (p: any) => <h2 {...p} />,
    h3: (p: any) => <h3 {...p} />,
    h4: (p: any) => <h4 {...p} />,
    hr: (p: any) => <hr {...p} />,
    blockquote: (p: any) => <blockquote {...p} />,
    ul: (p: any) => <ul {...p} />,
    ol: (p: any) => <ol {...p} />,
    li: (p: any) => <li {...p} />,
    table: (p: any) => <div className="md-table-wrap"><table {...p} /></div>,
    code: (p: any) => {
      const text = String(p.children ?? '');
      if (p.inline || !text.includes('\n')) return <code {...p} />;
      const cls: string = p.className || '';
      const lang = (cls.match(/language-(\w+)/) || [])[1] || '';
      return <CodeBlock lang={lang} code={text.replace(/\n$/, '')} />;
    },
    pre: (p: any) => <>{p.children}</>,
  };
}

function ToolGroup({ tools, pending }: { tools: ToolStep[]; pending?: boolean }) {
  const [collapsed, setCollapsed] = useState(false);
  const done = tools.filter((t) => t.done).length;
  const errs = tools.filter((t) => t.done && isErrorResult(t)).length;
  return (
    <div className="mb-3 rounded-xl border border-white/[0.06] bg-black/20 overflow-hidden">
      <button onClick={() => setCollapsed(!collapsed)} className="w-full flex items-center gap-2 px-3 py-2 hover:bg-white/[0.02] transition">
        <Wrench size={11} className="text-zinc-500 shrink-0" />
        <span className="text-[11px] uppercase tracking-[0.14em] text-zinc-400 font-semibold">
          {tools.length} tool{tools.length > 1 ? 's' : ''}
        </span>
        <span className="text-[10px] font-mono text-zinc-600">
          {done}/{tools.length} done
        </span>
        {errs > 0 && (
          <span className="text-[10px] font-semibold text-red-400 flex items-center gap-1">
            <AlertTriangle size={10} /> {errs} error{errs > 1 ? 's' : ''}
          </span>
        )}
        {pending && (
          <span className="flex items-center gap-1 text-[10px] text-zinc-500">
            <Loader2 size={10} className="animate-spin" /> working…
          </span>
        )}
        <span className="flex-1" />
        <span className="text-[10px] text-zinc-600">{collapsed ? 'expand' : 'collapse'}</span>
        {collapsed ? <ChevronRight size={13} className="text-zinc-500" /> : <ChevronDown size={13} className="text-zinc-500" />}
      </button>
      {!collapsed && (
        <div className="space-y-1.5 px-2 pb-2">
          {tools.map((t) => <ToolCard key={t.id} step={t} />)}
        </div>
      )}
    </div>
  );
}

function AssistantBubble({ msg, live }: { msg: Msg; live?: boolean }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard.writeText(msg.content || '').catch(() => {});
    setCopied(true);
    setTimeout(() => setCopied(false), 1200);
  };
  return (
    <div className="flex gap-3 group animate-in">
      <div className="w-8 h-8 rounded-xl bg-white/[0.07] border border-white/[0.12] grid place-items-center shrink-0 mt-0.5">
        <Zap size={14} className="text-zinc-300" />
      </div>
      <div className="min-w-0 flex-1 card-elevated px-4 py-3.5">
        {msg.tools && msg.tools.length > 0 && (
          <ToolGroup tools={msg.tools} pending={msg.pendingTools} />
        )}
        <div className="prose-custom">
          {msg.content
            ? <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents()}>{msg.content}</ReactMarkdown>
            : <span className="flex items-center gap-2 text-zinc-500 text-[13px]">
              {live ? <><Loader2 size={13} className="animate-spin" /> thinking…</> : '…'}
            </span>}
          {live && msg.content && (
            <span className="inline-block w-[2px] h-[15px] ml-1 align-middle bg-white rounded-[1px] animate-pulse-subtle" />
          )}
        </div>
        {msg.content && (
          <div className="flex items-center gap-3 mt-2.5 pt-2.5 border-t border-white/[0.05] opacity-0 group-hover:opacity-100 transition-opacity duration-200">
            <button onClick={copy} className="text-[11px] text-zinc-500 hover:text-zinc-300 flex items-center gap-1">
              {copied ? <Check size={11} /> : <Copy size={11} />}
              {copied ? 'copied' : 'copy'}
            </button>
            {msg.toolsUsed ? <span className="text-[11px] text-zinc-600 font-mono">· {msg.toolsUsed} tools</span> : null}
            {msg.model ? <span className="text-[11px] text-zinc-600 font-mono">· {msg.model}</span> : null}
          </div>
        )}
      </div>
    </div>
  );
}

export default function Page() {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState('');
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessions, setSessions] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [listening, setListening] = useState(false);
  const [voiceOn, setVoiceOn] = useState(false);
  const [models, setModels] = useState<any[]>([]);
  const [model, setModel] = useState('');
  const [sideOpen, setSideOpen] = useState(false);
  const [backendOk, setBackendOk] = useState<boolean | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);
  const recRef = useRef<any>(null);

  const refreshSessions = useCallback(async () => {
    try { const d = await getSessions(); setSessions(d.sessions || []); } catch {}
    try {
      const h = await fetch(`${API_URL}/api/health`).then((r) => r.ok);
      setBackendOk(h);
    } catch { setBackendOk(false); }
  }, []);

  useEffect(() => {
    refreshSessions();
    getModels().then((d) => { setModels(d.models || []); if (d.default) setModel(d.default); }).catch(() => {});
  }, [refreshSessions]);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }); }, [messages]);

  useEffect(() => {
    const ta = taRef.current;
    if (ta) { ta.style.height = 'auto'; ta.style.height = Math.min(140, ta.scrollHeight) + 'px'; }
  }, [input]);

  function speak(text: string) {
    if (!voiceOn || !text.trim()) return;
    try {
      speechSynthesis.cancel();
      speechSynthesis.speak(new SpeechSynthesisUtterance(text.slice(0, 500)));
    } catch {}
  }

  async function send(text?: string) {
    const content = (text ?? input).trim();
    if (!content || loading) return;
    setInput('');
    setMessages((m) => [...m, { role: 'user', content }]);
    setLoading(true);
    const idx = messages.length + 1;
    setMessages((m) => [...m, { role: 'assistant', content: '', tools: [], pendingTools: true }]);
    let acc = '';
    const steps: ToolStep[] = [];
    const patch = (fn: (m: Msg) => Msg) =>
      setMessages((prev) => prev.map((mm, i) => (i === idx ? fn({ ...mm }) : mm)));
    try {
      const { session_id, full, toolsUsed } = await streamAgent(content, sessionId, {
        onToken: (t) => { acc += t; patch((m) => ({ ...m, content: acc })); },
        onToolStart: (name, args, id) => {
          steps.push({ id: id || steps.length + 1, name, args, result: '', done: false });
          patch((m) => ({ ...m, tools: steps.map((s) => ({ ...s })), pendingTools: true }));
        },
        onToolEnd: (id, name, result) => {
          const s = steps.find((x) => x.id === id) || steps[steps.length - 1];
          if (s) { s.done = true; s.result = result; s.name = name || s.name; }
          patch((m) => ({ ...m, tools: steps.map((x) => ({ ...x })) }));
        },
        onMeta: (mt) => { if (mt.session_id) setSessionId(mt.session_id); if (mt.model) patch((m) => ({ ...m, model: mt.model })); },
      }, { model: model || undefined });
      setSessionId(session_id);
      patch((m) => ({ ...m, content: full || acc, tools: steps.map((s) => ({ ...s, done: true })), toolsUsed, pendingTools: false }));
      speak(full || acc);
      refreshSessions();
    } catch (e: any) {
      const err = String(e?.message || e);
      patch((m) => ({ ...m, content: `Backend unreachable — start with \`python server/run.py\` (port 8000).\n\n\`${err.slice(0, 200)}\``, pendingTools: false }));
    }
    setLoading(false);
  }

  function toggleMic() {
    const SR: any = (window as any).webkitSpeechRecognition || (window as any).SpeechRecognition;
    if (!SR) { alert('Voice input works best in Chrome.'); return; }
    if (listening) { recRef.current?.stop(); setListening(false); return; }
    const rec = new SR();
    rec.lang = 'en-US'; rec.interimResults = true;
    rec.onresult = (e: any) => {
      const t = Array.from(e.results).map((r: any) => r[0].transcript).join('');
      setInput(t);
      if (e.results[e.results.length - 1].isFinal) { setListening(false); send(t); }
    };
    rec.onend = () => setListening(false);
    rec.onerror = () => setListening(false);
    recRef.current = rec;
    try { rec.start(); setListening(true); } catch {}
  }

  async function loadSession(id: string) {
    try {
      const r = await fetch(`${API_URL}/api/sessions/${id}`);
      const d = await r.json();
      setSessionId(d.id);
      setMessages((d.messages || []).filter((m: any) => m.role !== 'system').map((m: any) => ({ role: m.role === 'user' ? 'user' : 'assistant', content: m.content })));
      setSideOpen(false);
    } catch {}
  }

  async function delSession(id: string) {
    try { await fetch(`${API_URL}/api/sessions/${id}`, { method: 'DELETE' }); } catch {}
    refreshSessions();
    if (id === sessionId) { setSessionId(null); setMessages([]); }
  }

  return (
    <div className="h-screen w-screen flex overflow-hidden bg-[#07070a] text-zinc-100">
      <div className="bg-orb" />

      {/* mobile overlay */}
      {sideOpen && <div className="fixed inset-0 z-30 bg-black/60 md:hidden" onClick={() => setSideOpen(false)} />}

      {/* ── sidebar ── */}
      <aside className={`sidebar fixed md:static z-40 h-full w-[280px] shrink-0 flex flex-col transition-transform duration-200 ${sideOpen ? 'translate-x-0' : '-translate-x-full md:translate-x-0'}`}>
        <div className="flex items-center gap-3 px-4 pt-5 pb-4">
          <div className="w-9 h-9 rounded-xl bg-white border border-white/20 grid place-items-center">
            <span className="text-black font-black text-[15px]">Z</span>
          </div>
          <div className="min-w-0 flex-1">
            <div className="font-semibold text-[14px] tracking-wide text-zinc-100">ZUMBA</div>
            <div className="flex items-center gap-1.5 text-[11px] text-zinc-500 mt-0.5">
              <span className={`dot ${backendOk === false ? 'dot-offline' : backendOk ? 'dot-online' : 'dot-idle'}`} />
              {backendOk === false ? 'offline · port 8000' : backendOk ? 'connected' : 'personal ai'}
            </div>
          </div>
          <button className="md:hidden p-1.5 text-zinc-500" onClick={() => setSideOpen(false)}><X size={15} /></button>
        </div>

        <div className="px-3">
          <button onClick={() => { setSessionId(null); setMessages([]); setSideOpen(false); }}
            className="btn btn-primary w-full">
            <Plus size={14} /> New chat
          </button>
        </div>

        <div className="mt-2.5 flex-1 overflow-y-auto px-3 pb-2 space-y-0.5">
          {sessions.map((s) => (
            <div key={s.id} onClick={() => loadSession(s.id)}
              className={`group flex items-center gap-2.5 rounded-xl px-3 py-2.5 cursor-pointer border transition min-w-0 ${s.id === sessionId ? 'bg-white/[0.05] border-white/[0.12]' : 'border-transparent hover:bg-white/[0.03]'}`}>
              <Circle size={10} className={`shrink-0 ${s.id === sessionId ? 'text-white' : 'text-zinc-600'}`} />
              <div className="min-w-0 flex-1">
                <div className="truncate text-[13px] text-zinc-300">{s.title || 'Untitled'}</div>
                <div className="text-[10px] text-zinc-600 font-mono mt-0.5">
                  {(s.message_count ?? 0)} msgs
                </div>
              </div>
              <button onClick={(e) => { e.stopPropagation(); delSession(s.id); }}
                className="opacity-0 group-hover:opacity-100 p-1 text-zinc-600 hover:text-red-400 shrink-0 transition"><Trash2 size={12} /></button>
            </div>
          ))}
          {!sessions.length && (
            <div className="text-center text-[12px] text-zinc-600 py-10 leading-relaxed">
              No saved chats yet.<br />Start one below.
            </div>
          )}
        </div>

        <div className="px-4 py-3 border-t border-white/[0.06] text-[10px] font-mono text-zinc-600 leading-relaxed">
          {API_URL}
        </div>
      </aside>

      {/* ── main ── */}
      <main className="relative flex-1 flex flex-col min-w-0">
        <header className="relative z-10 flex items-center gap-3 px-4 md:px-7 pt-4 pb-3.5 border-b border-white/[0.06]">
          <button className="md:hidden p-2 rounded-xl border border-white/10 hover:bg-white/[0.04]" onClick={() => setSideOpen(true)}>
            <Menu size={15} className="text-zinc-400" />
          </button>

          <div className="flex items-center justify-center w-8 h-8 rounded-xl bg-white border border-white/20">
            <Zap size={14} className="text-black" />
          </div>

          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="font-semibold text-[14px] tracking-tight">Zumba</span>
              {model && (
                <span className="hidden sm:inline text-[10.5px] font-mono text-zinc-500 bg-white/[0.04] border border-white/[0.08] rounded-full px-2 py-0.5 truncate max-w-[240px]">
                  {model}
                </span>
              )}
            </div>
            <div className="text-[11px] text-zinc-600 mt-0.5 font-mono">
              {loading ? 'running tools…' : listening ? 'listening…' : 'agent · tools · streaming'}
            </div>
          </div>

          {models.length > 0 && (
            <select value={model} onChange={(e) => setModel(e.target.value)}
              className="hidden lg:block max-w-[200px] text-[11.5px] bg-white/[0.04] border border-white/[0.08] rounded-xl px-2.5 py-1.5 outline-none text-zinc-300 cursor-pointer">
              {models.slice(0, 30).map((m: any) => <option key={m.id} value={m.id} className="bg-[#0f0f14]">{m.id}</option>)}
            </select>
          )}

          <button onClick={() => setVoiceOn(!voiceOn)} title="voice replies"
            className={`p-2 rounded-xl border transition ${voiceOn ? 'bg-white/[0.08] border-white/20 text-white' : 'border-white/[0.08] text-zinc-500 hover:bg-white/[0.04] hover:text-zinc-300'}`}>
            {voiceOn ? <Volume2 size={14} /> : <VolumeX size={14} />}
          </button>
        </header>

        {/* messages */}
        <div className="relative z-10 flex-1 overflow-y-auto px-4 md:px-8 py-6">
          <div className="max-w-[800px] mx-auto">
            {messages.length === 0 && (
              <div className="text-center pt-10 md:pt-16 pb-8">
                <div className="hero-title">Talk to <span className="text-zinc-100">Zumba</span></div>
                <p className="hero-sub mt-4 max-w-md mx-auto">
                  Agentic assistant with full tool visibility.<br />
                  Shell, web, vault, memory — every step shown.
                </p>
                <div className="flex gap-2 justify-center mt-7 flex-wrap">
                  {SUGGESTIONS.map((s) => (
                    <button key={s} onClick={() => send(s)}
                      className="btn btn-ghost text-[12.5px]">
                      {s}
                    </button>
                  ))}
                </div>
                <div className="grid sm:grid-cols-3 gap-2.5 mt-10 text-left max-w-lg mx-auto">
                  {[['Shell', 'Run any PowerShell command'], ['Web', 'Search & fetch any page'], ['Memory', 'Remembers everything']].map(([t, d]) => (
                    <div key={t} className="card-elevated px-4 py-3">
                      <div className="text-[13px] font-semibold text-zinc-300">{t}</div>
                      <div className="text-[11.5px] text-zinc-500 mt-1 leading-relaxed">{d}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div className="space-y-4">
              {messages.map((m, i) =>
                m.role === 'user' ? (
                  <div key={i} className="flex justify-end animate-in">
                    <div className="max-w-[85%] md:max-w-[70%] rounded-2xl rounded-br-md bg-white text-black px-4 py-2.5 text-[14px] leading-relaxed font-medium break-words whitespace-pre-wrap shadow-[0_4px_20px_rgba(255,255,255,0.08)]">
                      {m.content}
                    </div>
                  </div>
                ) : (
                  <AssistantBubble key={i} msg={m} live={loading && i === messages.length - 1} />
                )
              )}
              <div ref={bottomRef} />
            </div>
          </div>
        </div>

        {/* composer */}
        <div className="relative z-10 px-4 md:px-8 pb-4 md:pb-6">
          <div className="max-w-[800px] mx-auto">
            <div className="composer">
              <textarea ref={taRef} rows={1} value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } }}
                placeholder="Message Zumba…  (Enter to send)"
                className="flex-1 bg-transparent text-[14px] placeholder:text-zinc-600 resize-none max-h-[140px] py-2.5 leading-relaxed"
              />
              <button onClick={toggleMic} title="voice input"
                className={`p-2.5 rounded-xl border transition shrink-0 ${listening ? 'bg-white text-black border-white animate-pulse' : 'border-white/[0.08] text-zinc-400 hover:bg-white/[0.05] hover:text-zinc-200'}`}>
                <Mic size={15} />
              </button>
              <button onClick={() => send()} disabled={loading || !input.trim()}
                className="p-2.5 rounded-xl bg-white hover:bg-zinc-200 disabled:opacity-30 disabled:hover:bg-white text-black font-semibold shrink-0 transition">
                {loading ? <Loader2 size={15} className="animate-spin" /> : <Send size={15} />}
              </button>
            </div>
            <div className="text-center text-[10px] text-zinc-600 mt-2.5 font-mono tracking-wide">
              {backendOk === false ? 'backend offline' : API_URL} · agent mode
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
