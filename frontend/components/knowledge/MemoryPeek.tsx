'use client';
import Link from 'next/link';
import { ArrowUpRight, Network } from 'lucide-react';
import { useMemoryCaptures } from '@/lib/memory-captures';

export default function MemoryPeek() {
  const { captures, connected } = useMemoryCaptures();
  const latest = captures?.recent[0];
  return <Link href="/knowledge" className="block mx-3 mb-3 p-3 rounded-lg border border-blue-400/20 bg-blue-400/[.04] hover:bg-blue-400/[.08] transition">
    <div className="flex items-center gap-2 text-[12px] text-blue-200"><Network size={14} /> Live memory <ArrowUpRight size={13} className="ml-auto" /></div>
    <div className="text-[11px] text-zinc-400 mt-2">{connected ? `${Object.values(captures?.counts || {}).reduce((a, b) => a + b, 0)} exchanges saved locally · ${captures?.counts.pending || 0} processing` : 'Connecting to saved memory…'}</div>
    {latest && <div className="text-[11px] text-zinc-400 mt-2 line-clamp-2">“{latest.user_text}”</div>}
    {!!captures?.counts.failed && <div className="text-[10px] text-amber-300/80 mt-2">{captures.counts.failed} need processing retry · originals are saved</div>}
  </Link>;
}
