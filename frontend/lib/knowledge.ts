'use client';
import { useEffect, useState } from 'react';
import { API_URL } from './api';

export type Evidence = { id?: string; document_id: string; document: string; chunk_id: string; page: number | null; section: string; quote: string; confidence?: number; method?: string; created_at?: number };
export type Entity = { id: string; name: string; normalized_name: string; type: string; description: string; aliases: string[]; confidence: number; created_at: number; updated_at: number; sourceDocuments: string[]; sourceChunks: string[]; evidence: Evidence[]; hasEmbedding: boolean };
export type Edge = { id: string; source: string; target: string; type: string; evidence: Evidence[]; confidence: number; sourceCount: number };
export type Document = { id: string; name: string; kind: string; source_key: string; status: string; stage: string; completed: number; total: number; bytes: number; error: string; warning: string; created_at: number; updated_at: number };
export type Graph = { nodes: Entity[]; edges: Edge[]; documents: Document[]; profile: string; revision: string; audit: { id: number; entity_id: string; mention: string; decision: string; reason: string; created_at: number }[]; sync: Record<string, string>; counts: { chunks: number; embedded: number } };

export async function knowledgeRequest<T>(path = '', options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}/api/knowledge${path}`, options);
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(typeof data.detail === 'string' ? data.detail : `Request failed (${response.status})`);
  }
  return response.json();
}

export function useKnowledge() {
  const [graph, setGraph] = useState<Graph | null>(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    const events = new EventSource(`${API_URL}/api/knowledge/events`);
    events.addEventListener('graph', event => {
      try {
        setGraph(JSON.parse((event as MessageEvent).data));
        setConnected(true); setError('');
      } catch { setError('Received an unreadable graph update. Reconnecting…'); }
    });
    events.onopen = () => { setConnected(true); setError(''); };
    events.onerror = () => { setConnected(false); setError('Connection lost. Reconnecting to Zumba…'); };
    return () => events.close();
  }, []);
  return { graph, connected, error };
}

const COLORS = ['#7b9cff', '#65d9d0', '#b49aff', '#e6b879', '#7dc2e7', '#d696b8', '#a2c784'];
export function entityColor(type: string) {
  let hash = 0;
  for (const char of type.toLowerCase()) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return COLORS[hash % COLORS.length];
}
