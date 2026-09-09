'use client';
import { useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { RefreshCw, Activity, ArrowDownToLine, ArrowLeft, ArrowRight, ArrowUpRight, Braces, Brain, Check, ChevronDown, ChevronRight, CircleHelp, Crosshair, Database, FileText, FolderOpen, GitBranch, Layers3, Loader2, MessageSquare, Minus, Network, Plus, Search, Settings2, ShieldCheck, SlidersHorizontal, Sparkles, Upload, X } from 'lucide-react';
import { GraphCanvas, GraphControls } from '@/components/knowledge/GraphCanvas';
import { Document, Edge, Entity, Evidence, entityColor, knowledgeRequest, useKnowledge } from '@/lib/knowledge';
import { API_URL } from '@/lib/api';
import { useMemoryCaptures } from '@/lib/memory-captures';
import './knowledge.css';
import './canvas-first.css';

type View = 'Graph' | 'Documents' | 'Queries' | 'Memory';
const nav = [{ label: 'Graph', icon: Network }, { label: 'Documents', icon: FolderOpen }] as const;
const date = (value: number) => new Date(value * 1000).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });

export default function KnowledgePage() {
  const { graph, connected, error } = useKnowledge();
  const { captures } = useMemoryCaptures();
  const [view, setView] = useState<View>('Graph');
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [retrying, setRetrying] = useState('');
  const [search, setSearch] = useState('');
  const [entityType, setEntityType] = useState('');
  const [relationType, setRelationType] = useState('');
  const [sourceFilter, setSourceFilter] = useState('');
  const [confidence, setConfidence] = useState(0);
  const [layout, setLayout] = useState('concentric');
  const [depth, setDepth] = useState(1);
  const [selected, setSelected] = useState<string | null>(null);
  const [selectedCount, setSelectedCount] = useState(0);
  const [uploading, setUploading] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [notice, setNotice] = useState('');
  const [question, setQuestion] = useState('');
  const [asking, setAsking] = useState(false);
  const [answer, setAnswer] = useState<{ answer: string; citations: (Evidence & { index: number })[] } | null>(null);
  const [source, setSource] = useState<{ name: string; id: string; chunks: { id: string; page: number | null; section: string; text: string }[] } | null>(null);
  const controls = useRef<GraphControls>(null);
  const files = useRef<HTMLInputElement>(null);
  const queryInput = useRef<HTMLInputElement>(null);
  const entityTypes = useMemo(() => Array.from(new Set(graph?.nodes.map(n => n.type))).sort(), [graph]);
  const relationTypes = useMemo(() => Array.from(new Set(graph?.edges.map(e => e.type))).sort(), [graph]);
  const visible = useMemo(() => {
    let nodes = (graph?.nodes || []).filter(n => (!entityType || n.type === entityType) && n.confidence >= confidence && (!sourceFilter || n.sourceDocuments.includes(sourceFilter)));
    const ids = new Set(nodes.map(n => n.id));
    const edges = (graph?.edges || []).filter(e => ids.has(e.source) && ids.has(e.target) && e.confidence >= confidence && (!relationType || e.type === relationType) && (!sourceFilter || e.evidence.some(ev => ev.document_id === sourceFilter)));
    return { nodes, edges };
  }, [graph, entityType, relationType, confidence, sourceFilter]);
  const active = graph?.documents.filter(d => !['complete', 'failed'].includes(d.status)) || [];
  const entity = graph?.nodes.find(n => n.id === selected);
  const edge = graph?.edges.find(e => e.id === selected);
  const selectedEvidence = entity?.evidence || edge?.evidence || [];
  const entityName = (id: string) => graph?.nodes.find(n => n.id === id)?.name || id;

  const failed = graph?.documents.filter(d => d.status === 'failed') || [];
  useEffect(() => {
    const handle = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { setView('Graph'); setSelected(null); setUploadOpen(false); setSource(null); }
      if (event.key === '/' && !(event.target instanceof HTMLInputElement) && !(event.target instanceof HTMLTextAreaElement)) { event.preventDefault(); document.querySelector<HTMLInputElement>('[aria-label="Search graph"]')?.focus(); }
    };
    window.addEventListener('keydown', handle);
    return () => window.removeEventListener('keydown', handle);
  }, []);
  async function retryExtraction(id?: string) {
    setRetrying(id || 'all'); setNotice('');
    try { await knowledgeRequest(id ? `/documents/${id}/retry` : '/documents/retry-failed', { method: 'POST' }); }
    catch (e) { setNotice((e as Error).message); }
    finally { setRetrying(''); }
  }
  async function retryMemory() {
    setRetrying('memory');
    try {
      const response = await fetch(`${API_URL}/api/memory/retry`, { method: 'POST' });
      if (!response.ok) throw new Error('Memory retry failed');
      const data = await response.json();
      setNotice(`${data.queued || 0} saved memories queued for processing.`);
    } catch (e) { setNotice((e as Error).message); }
    finally { setRetrying(''); }
  }
  async function upload(items: FileList | File[]) {
    setUploading(true); setNotice('');
    try {
      for (const file of Array.from(items)) {
        const form = new FormData(); form.append('file', file);
        await knowledgeRequest('/documents', { method: 'POST', body: form });
      }
      setUploadOpen(false); setView('Documents');
    } catch (e) { setNotice((e as Error).message); }
    finally { setUploading(false); if (files.current) files.current.value = ''; }
  }
  async function openSource(id: string) {
    try { setSource(await knowledgeRequest(`/documents/${id}`)); } catch (e) { setNotice((e as Error).message); }
  }
  async function ask(event: React.FormEvent) {
    event.preventDefault(); if (!question.trim() || asking) return;
    setAsking(true); setView('Queries'); setNotice('');
    try { setAnswer(await knowledgeRequest('/query', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question }) })); }
    catch (e) { setNotice((e as Error).message); }
    finally { setAsking(false); }
  }
  function exportGraph() {
    if (!graph) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(graph, null, 2)], { type: 'application/json' }));
    const a = document.createElement('a'); a.href = url; a.download = 'zumba-knowledge-graph.json'; a.click(); URL.revokeObjectURL(url);
  }
  const renderEvidence = (ev: Evidence, i: number) => <article className="kg-evidence" key={ev.id || `${ev.chunk_id}-${i}`}>
    <div className="kg-evidence-title"><span><FileText size={13} /> Source {i + 1}</span>{ev.confidence !== undefined && <span className={ev.confidence < .8 ? 'kg-amber' : 'kg-cyan'}>{Math.round(ev.confidence * 100)}% confidence</span>}</div>
    <blockquote>{ev.quote}</blockquote>
    <button className="kg-source-link" onClick={() => openSource(ev.document_id)}><FileText size={13} /><span>{ev.document}</span><ArrowUpRight size={13} /></button>
    <small>{ev.page ? `Page ${ev.page}` : ev.section}</small>
    {ev.method && <details><summary>Extraction details</summary><p>{ev.method}</p><p>Document ID: {ev.document_id}</p><p>Chunk ID: {ev.chunk_id}</p><p>{ev.created_at ? date(ev.created_at) : ''}</p></details>}
  </article>;

  return <div className="kg-app kg-canvas-first">
    <input ref={files} type="file" multiple accept=".pdf,.docx,.txt,.md,.markdown,.csv,.json" className="kg-file-input" onChange={e => e.target.files && upload(e.target.files)} />
    <aside className="kg-sidebar">
      <Link href="/" className="kg-brand" title="Back to Zumba chat" aria-label="Back to Zumba chat"><div className="kg-mark"><Network size={22} /></div><span>zumba<span className="kg-brand-sub">Knowledge workspace</span></span></Link>
      <nav>{nav.map(({ label, icon: Icon }) => <button key={label} title={label} aria-label={label} className={view === label ? 'active' : ''} onClick={() => setView(label)}><Icon size={17} /><span>{label}</span>{label === 'Graph' ? <span className="kg-nav-dot" /> : label === 'Documents' ? <small>{graph?.documents.length || 0}</small> : null}</button>)}</nav>
      <button title="Zumba memory" aria-label="Zumba memory" className={`kg-memory-nav ${view === 'Memory' ? 'active' : ''}`} onClick={() => setView('Memory')}><Brain size={17} /><span className="kg-memory-label">Memory</span> <span className={connected ? 'kg-live-dot' : 'kg-offline-dot'} /></button>
    </aside>

    <main className="kg-main">
      <header className="kg-header"><div className="kg-breadcrumb"><strong>Knowledge graph</strong><span className="kg-beta">Live</span><span className="kg-header-counts">{graph?.nodes.length || 0} entities · {graph?.edges.length || 0} connections</span></div><div className="kg-header-actions">{(active.length > 0 || failed.length > 0) && <button className="kg-button kg-job-button" onClick={() => setView('Documents')}>{active.length > 0 ? <><Loader2 size={13} className="kg-spin" />{active.length} processing</> : <>{failed.length} need attention</>}</button>}<span className="kg-connection"><span className={connected ? 'kg-live-dot' : 'kg-offline-dot'} />{connected ? 'Connected' : 'Reconnecting'}</span><button className="kg-button kg-export" onClick={exportGraph} disabled={!graph}><ArrowDownToLine size={14} /> Export</button><button className="kg-button kg-primary" onClick={() => setUploadOpen(true)}><Plus size={15} /> Add documents</button></div></header>
      <div className={`kg-toolbar ${filtersOpen ? 'kg-filters-open' : ''}`}><div className="kg-search"><Search size={15} /><input aria-label="Search graph" placeholder="Search entities or aliases…" value={search} onChange={e => setSearch(e.target.value)} /><kbd>/</kbd></div><button className="kg-button kg-filter-toggle" aria-expanded={filtersOpen} onClick={() => setFiltersOpen(!filtersOpen)}><SlidersHorizontal size={14} /> Filters{(entityType || relationType || sourceFilter || confidence > 0) && <i className="kg-live-dot" />}</button><label className="kg-select"><Layers3 size={14} /><select aria-label="Entity type" value={entityType} onChange={e => setEntityType(e.target.value)}><option value="">All entities</option>{entityTypes.map(t => <option key={t}>{t}</option>)}</select></label><label className="kg-select"><GitBranch size={14} /><select aria-label="Relationship type" value={relationType} onChange={e => setRelationType(e.target.value)}><option value="">All relationships</option>{relationTypes.map(t => <option key={t}>{t}</option>)}</select></label><label className="kg-confidence"><SlidersHorizontal size={14} /><span>Confidence</span><input aria-label="Minimum confidence" type="range" min="0" max="1" step=".05" value={confidence} onChange={e => setConfidence(Number(e.target.value))} /><b>{Math.round(confidence * 100)}%</b></label><label className="kg-select kg-source-filter"><select aria-label="Source filter" value={sourceFilter} onChange={e => setSourceFilter(e.target.value)}><option value="">All sources</option>{graph?.documents.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}</select></label></div>
      {(notice || error || graph?.sync.error) && <div role="alert" className="kg-notice">{notice || error || graph?.sync.error}{notice && <button aria-label="Dismiss message" onClick={() => setNotice('')}><X size={14} /></button>}</div>}

      <div className="kg-workbench">
        <section className="kg-graph-area">
          <GraphCanvas ref={controls} nodes={visible.nodes} edges={visible.edges} search={search} layout={layout} onSelect={setSelected} onCount={setSelectedCount} />
          <div className="kg-canvas-top"><div className="kg-canvas-label"><Network size={15} /><span>Knowledge graph</span><span className="kg-saved">{visible.nodes.length} visible</span></div><label className="kg-layout"><Layers3 size={13} /><select aria-label="Graph layout" value={layout} onChange={e => setLayout(e.target.value)}><option value="cose">Force layout</option><option value="concentric">Concentric</option><option value="circle">Circular</option><option value="breadthfirst">Hierarchy</option></select></label></div>
          {!visible.nodes.length && view === 'Graph' && <div className="kg-empty"><div className="kg-empty-symbol"><Network size={44} strokeWidth={1} /></div><span className="kg-empty-label">Your knowledge, connected</span><h2>{graph?.nodes.length ? 'A quieter corner of your graph.' : 'Start with something you know.'}</h2><p>{graph?.nodes.length ? 'Adjust your filters to bring more entities into view.' : 'Add a document to uncover its entities and relationships. Every connection leads back to the words that support it.'}</p><button className="kg-button kg-primary" onClick={() => graph?.nodes.length ? (setEntityType(''), setRelationType(''), setConfidence(0), setSourceFilter('')) : setUploadOpen(true)}><Plus size={15} />{graph?.nodes.length ? 'Reset filters' : 'Add your first document'}</button><small>{active.length ? `${active.length} sources queued or processing` : 'PDF · DOCX · Markdown · TXT · CSV · JSON'}</small></div>}
          {view !== 'Graph' && <div className="kg-content-view" role="region" aria-label={`${view} panel`}><div className="kg-view-heading"><h2>{view === 'Memory' ? 'Your persistent memory' : view}</h2><button aria-label="Return to graph" onClick={() => setView('Graph')}><X size={18} /></button></div>
            {view === 'Documents' && <><p className="kg-view-intro">Original sources and live extraction progress.</p><div className="kg-document-actions"><span>{graph?.documents.length || 0} sources · {failed.length} failed</span><button className="kg-button" disabled={!failed.length || !!retrying} onClick={() => retryExtraction()}><RefreshCw size={13} className={retrying === 'all' ? 'kg-spin' : ''} /> Retry all failed</button></div><div className="kg-document-table"><div className="kg-table-head"><span>Document</span><span>Ingestion</span><span>Chunks</span></div>{graph?.documents.map(d => <div key={d.id} className="kg-document-row"><button onClick={() => openSource(d.id)}><div className="kg-file-icon"><FileText size={18} /></div><span>{d.name}<small>{d.kind.toUpperCase()} · {(d.bytes / 1024).toFixed(1)} KB · {date(d.created_at)}</small></span></button><div><span className={`kg-status ${d.status}`}>{d.status === 'processing' && <Loader2 size={12} className="kg-spin" />}{d.stage}</span>{d.error && <p className="kg-amber">{d.error}</p>}{d.warning && <p>{d.warning}</p>}{d.status === 'failed' && <button className="kg-button kg-retry" disabled={!!retrying} onClick={() => retryExtraction(d.id)}><RefreshCw size={13} className={retrying === d.id ? 'kg-spin' : ''} /> Retry extraction</button>}</div><span>{d.completed} / {d.total || '—'}</span></div>)}</div>{!graph?.documents.length && <div className="kg-inline-empty">No documents yet. Add a source to begin.</div>}</>}
            {view === 'Memory' && <><div className="kg-memory-summary"><Brain size={25} /><div><h3>Memory that stays with you</h3><p>The current user.md profile and original user messages sync automatically. Source versions remain available after updates.</p></div><span className="kg-status complete">{graph?.sync.memory_available === 'true' ? 'Memory connected' : 'Waiting for memory'}</span></div><button className="kg-button" disabled={!!retrying} onClick={retryMemory}><RefreshCw size={13} /> Retry failed memory processing</button><h3 className="kg-section-title">Recently saved <span>{captures?.counts.pending || 0} processing · {captures?.counts.failed || 0} failed</span></h3>{captures?.recent.map(c => <article className="kg-capture" key={c.id}><p>{c.user_text}</p><small>{date(c.created_at)} · {c.status === 'complete' ? 'Processed' : c.status === 'failed' ? 'Saved · processing needs retry' : 'Saved · processing'}</small></article>)}<h3 className="kg-section-title">user.md <span>Latest saved profile</span></h3><pre className="kg-profile">{graph?.profile || 'No user.md profile is saved yet. Talk to Zumba or add a document to start building your knowledge.'}</pre><h3 className="kg-section-title">Conversation sources</h3>{graph?.documents.filter(d => d.kind === 'memory').slice(0, 30).map(d => <button className="kg-memory-source" key={d.id} onClick={() => openSource(d.id)}><MessageSquare size={15} /><span>{d.name}</span><small>{d.stage}</small><ArrowUpRight size={14} /></button>)}</>}
            {view === 'Queries' && <><div className="kg-query-welcome"><Sparkles size={26} /><h3>Ask across your knowledge.</h3><p>Answers use your source excerpts and include quotes you can inspect.</p></div>{asking && <p className="kg-query-thinking"><Loader2 size={15} className="kg-spin" /> Searching sources and checking citations…</p>}{answer && <div className="kg-answer"><p>{answer.answer}</p><h3>Supporting sources</h3>{answer.citations.map((c, i) => renderEvidence(c, i))}</div>}</>}
          </div>}
          <div className="kg-canvas-bottom"><div className="kg-legend">{entityTypes.slice(0, 5).map(t => <button key={t} onClick={() => setEntityType(entityType === t ? '' : t)}><i style={{ background: entityColor(t) }} />{t}</button>)}<span><i className="kg-uncertain-line" />Uncertain</span></div><div className="kg-zoom"><button aria-label="Zoom out" onClick={() => controls.current?.zoom(.8)}><Minus size={16} /></button><button aria-label="Fit graph" onClick={() => controls.current?.fit()}><Crosshair size={16} /></button><button aria-label="Zoom in" onClick={() => controls.current?.zoom(1.25)}><Plus size={16} /></button></div></div>
          {selectedCount > 1 && <div className="kg-multiselect">{selectedCount} selected <button onClick={() => controls.current?.hideSelected()}>Hide selection</button><button onClick={() => controls.current?.reset()}>Show all</button></div>}
          <form className="kg-query-bar" onSubmit={ask}><Sparkles size={18} /><input ref={queryInput} aria-label="Ask your knowledge graph" placeholder="Ask your knowledge a question…" value={question} onChange={e => setQuestion(e.target.value)} /><span>Grounded in your sources</span><button aria-label="Submit question" disabled={asking || !question.trim()}>{asking ? <Loader2 size={17} className="kg-spin" /> : <ArrowRight size={18} />}</button></form>
        </section>

        {selected && <aside className="kg-inspector"><div className="kg-inspector-heading"><span>{selected ? 'Evidence inspector' : 'Workspace overview'}</span>{selected ? <button aria-label="Close inspector selection" onClick={() => { setSelected(null); controls.current?.reset(); }}><X size={15} /></button> : <ShieldCheck size={16} />}</div>
          <div className="kg-inspector-scroll">{entity || edge ? <><div className="kg-inspector-identity"><div className="kg-inspector-icon" style={{ color: entity ? entityColor(entity.type) : '#91afff' }}>{entity ? <Braces size={24} /> : <GitBranch size={24} />}</div><span className="kg-overline">{entity?.type || 'Directed relationship'}</span><h2>{entity?.name || `${entityName(edge!.source)} → ${entityName(edge!.target)}`}</h2>{edge && <span className="kg-relation-chip">{edge.type}</span>}<p>{entity?.description || 'This connection is backed by the source excerpts below.'}</p><div className="kg-inspector-metrics"><span><strong>{Math.round((entity?.confidence || edge?.confidence || 0) * 100)}%</strong>Confidence estimate</span><span><strong>{entity?.sourceDocuments.length || edge?.sourceCount}</strong>Source documents</span></div>{(entity?.confidence || edge?.confidence || 0) < .8 && <p className="kg-warning">Uncertain assertion. Review the source before relying on this connection.</p>}{entity && <><div className="kg-focus-controls"><button className="kg-button" onClick={() => controls.current?.focus(entity.id, depth)}><Crosshair size={13} /> Focus neighbors</button><select aria-label="Graph depth" value={depth} onChange={e => setDepth(Number(e.target.value))}><option value="1">1 hop</option><option value="2">2 hops</option><option value="3">3 hops</option></select></div>{entity.aliases.length > 0 && <p className="kg-aliases">Also known as: {entity.aliases.join(', ')}</p>}</>}</div><h3 className="kg-evidence-heading"><ShieldCheck size={14} /> Source evidence <span>{selectedEvidence.length}</span></h3>{selectedEvidence.map(renderEvidence)}{entity && <><h3 className="kg-evidence-heading">Connections</h3>{graph?.edges.filter(e => e.source === entity.id || e.target === entity.id).map(e => <button className="kg-neighbor" key={e.id} onClick={() => setSelected(e.id)}><GitBranch size={13} /><span>{e.type}<small>{entityName(e.source === entity.id ? e.target : e.source)}</small></span><ChevronRight size={13} /></button>)}</>}</> : <><div className="kg-overview-hero"><div className="kg-shield"><ShieldCheck size={26} /></div><h2>Follow the evidence.</h2><p>Select any entity or connection to see exactly where it comes from.</p><div className="kg-evidence-promise"><Check size={13} /> Original source excerpts<Check size={13} /> Page & section references<Check size={13} /> Transparent confidence</div></div><div className="kg-overview-section"><h3>Live ingestion <span>{active.length}</span></h3>{active.length ? active.slice(0, 4).map(d => <div className="kg-job" key={d.id}><div><FileText size={14} /><strong>{d.name}</strong><Loader2 size={12} className="kg-spin" /></div><p>{d.stage}</p><progress value={d.completed} max={Math.max(d.total, 1)} /><small>{d.completed} / {d.total || '—'} chunks processed</small></div>) : <p className="kg-muted">{graph?.documents.length ? 'All current sources have finished processing or need attention in Documents.' : 'Your next document starts here. Add a source to watch its knowledge take shape.'}</p>}</div><div className="kg-overview-section"><h3>Memory connection <Brain size={14} /></h3><p className="kg-muted">user.md and your conversations become sources as you use Zumba.</p><button className="kg-source-link" onClick={() => setView('Memory')}>Explore saved memory <ArrowUpRight size={14} /></button></div><div className="kg-shortcuts"><h3>Make yourself at home</h3><p><span>Pan the canvas</span><span>Drag</span></p><p><span>Zoom in or out</span><span>Scroll</span></p><p><span>Select multiple</span><span>Shift + drag</span></p><p><span>Inspect a connection</span><span>Click an edge</span></p></div></> }</div>
        </aside>}
      </div>
      <footer className="kg-footer"><span><span className={connected ? 'kg-live-dot' : 'kg-offline-dot'} />{connected ? 'Live updates connected' : 'Waiting for connection'}</span><span>{graph?.counts.chunks || 0} source chunks indexed</span><span><ShieldCheck size={12} /> Every connection has evidence</span></footer>
    </main>

    {uploadOpen && <div className="kg-modal-backdrop" onClick={() => !uploading && setUploadOpen(false)}><section className="kg-upload-modal" role="dialog" aria-modal="true" aria-label="Add documents" onClick={e => e.stopPropagation()}><button className="kg-modal-close" aria-label="Close upload" onClick={() => setUploadOpen(false)}><X size={18} /></button><div className="kg-upload-emblem"><Upload size={26} /></div><h2>Give your knowledge a source.</h2><p>Upload documents. Discover their connections.<br />Trace every relationship back to its evidence.</p><button className="kg-dropzone" disabled={uploading} onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); if (!uploading) upload(e.dataTransfer.files); }} onClick={() => files.current?.click()}>{uploading ? <Loader2 size={25} className="kg-spin" /> : <Plus size={27} />}<strong>{uploading ? 'Uploading your documents…' : 'Drop documents here, or browse'}</strong><span>PDF, DOCX, TXT, Markdown, CSV, JSON · Up to 20 MB each</span></button><div className="kg-upload-note"><ShieldCheck size={15} /><span>Originals stay on your machine. Excerpts are processed by your configured Zumba model.</span></div>{notice && <p role="alert" className="kg-amber">{notice}</p>}</section></div>}
    {source && <div className="kg-modal-backdrop" onClick={() => setSource(null)}><section className="kg-source-modal" role="dialog" aria-modal="true" aria-label={source.name} onClick={e => e.stopPropagation()}><header><FileText size={19} /><h2>{source.name}</h2><a href={`${API_URL}/api/knowledge/documents/${source.id}/download`} className="kg-button"><ArrowDownToLine size={14} /> Original</a><button aria-label="Close source" onClick={() => setSource(null)}><X size={19} /></button></header><div className="kg-source-text">{source.chunks.length ? source.chunks.map(c => <article key={c.id}><h3>{c.page ? `Page ${c.page}` : c.section}</h3><pre>{c.text}</pre></article>) : <p>Text extraction has not completed yet. The original file is available above.</p>}</div></section></div>}
  </div>;
}
