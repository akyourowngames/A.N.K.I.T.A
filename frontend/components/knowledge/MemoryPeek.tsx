'use client';
import Link from 'next/link';
import { ArrowUpRight, Network } from 'lucide-react';
import { useMemoryCaptures } from '@/lib/memory-captures';

export default function MemoryPeek() {
  const { captures, connected } = useMemoryCaptures();
  const latest = captures?.recent[0];
  return <Link href="/memory" className="block mx-3 mb-3 p-3 rounded-lg border border-blue-400/20 bg-blue-400/[.04] hover:bg-blue-400/[.08] transition">
    <div className="flex items-center gap-2 text-[12px] text-blue-200"><Network size={14} /> Saved conversation <ArrowUpRight size={13} className="ml-auto" /></div>
    <div className="text-[11px] text-zinc-400 mt-2">{connected ? `${captures?.counts.saved || 0} recent exchanges` : 'Loading saved conversation…'}</div>
    {latest && <div className="text-[11px] text-zinc-400 mt-2 line-clamp-2">“{latest.user_text}”</div>}
  </Link>;
}
