"use client";

import { GitBranch, RefreshCw, Search, ShieldAlert } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import {
  fetchMemoryGraph,
  fetchMemorySearch,
  refreshMemoryGraph,
  type MemoryGraphData,
  type MemoryGraphEdge,
  type MemoryGraphNode,
  type MemorySearchResult
} from "../lib/assistantClient";

type PositionedNode = MemoryGraphNode & {
  x: number;
  y: number;
};

const GRAPH_WIDTH = 920;
const GRAPH_HEIGHT = 620;
const MAX_VISIBLE_NODES = 72;

export function MemoryGraphView() {
  const [graph, setGraph] = useState<MemoryGraphData | null>(null);
  const [selectedId, setSelectedId] = useState("");
  const [query, setQuery] = useState("");
  const [searchResult, setSearchResult] = useState<MemorySearchResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    let active = true;
    async function load() {
      setLoading(true);
      const nextGraph = await fetchMemoryGraph();
      if (!active) {
        return;
      }
      setGraph(nextGraph);
      setSelectedId(nextGraph?.nodes[0]?.id ?? "");
      setLoading(false);
    }
    load();
    return () => {
      active = false;
    };
  }, []);

  const positioned = useMemo(() => layoutGraph(graph), [graph]);
  const allNodeMap = useMemo(() => new Map((graph?.nodes ?? []).map((node) => [node.id, node])), [graph]);
  const selected = allNodeMap.get(selectedId) ?? positioned.nodes[0];
  const linkedEdges = useMemo(
    () => (graph?.edges ?? []).filter((edge) => edge.source_id === selected?.id || edge.target_id === selected?.id).slice(0, 8),
    [graph?.edges, selected?.id]
  );

  async function runSearch() {
    const clean = query.trim();
    if (!clean) {
      setSearchResult(null);
      return;
    }
    const result = await fetchMemorySearch(clean);
    setSearchResult(result);
    const firstFact = result?.answer_relevant_facts[0]?.fact?.id;
    if (firstFact) {
      setSelectedId(firstFact);
    }
  }

  async function rebuild() {
    setRefreshing(true);
    const ok = await refreshMemoryGraph();
    if (ok) {
      const nextGraph = await fetchMemoryGraph();
      setGraph(nextGraph);
      setSelectedId(nextGraph?.nodes[0]?.id ?? "");
    }
    setRefreshing(false);
  }

  return (
    <section className="memory-brain-view">
      <div className="memory-brain-header">
        <div>
          <span className="memory-eyebrow">Memory Brain</span>
          <h1>Graph recall</h1>
        </div>
        <div className="memory-stats">
          <Stat label="Entities" value={graph?.stats.entities ?? 0} />
          <Stat label="Facts" value={graph?.stats.facts ?? 0} />
          <Stat label="Edges" value={graph?.stats.edges ?? 0} />
        </div>
      </div>

      <div className="memory-brain-layout">
        <div className="memory-graph-surface">
          <div className="memory-graph-toolbar">
            <form
              className="memory-search"
              onSubmit={(event) => {
                event.preventDefault();
                runSearch();
              }}
            >
              <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search memory graph..." />
              <button type="submit" title="Search memory graph" aria-label="Search memory graph">
                <Search size={18} />
              </button>
            </form>
            <button className="memory-icon-button" type="button" onClick={rebuild} disabled={refreshing} title="Reindex memory graph">
              <RefreshCw size={18} className={refreshing ? "spin" : ""} />
            </button>
          </div>

          {loading ? (
            <div className="memory-empty-state">Loading graph...</div>
          ) : positioned.nodes.length ? (
            <svg className="memory-graph-svg" viewBox={`0 0 ${GRAPH_WIDTH} ${GRAPH_HEIGHT}`} role="img" aria-label="Memory graph">
              {positioned.edges.map((edge) => {
                const source = positioned.byId.get(edge.source_id);
                const target = positioned.byId.get(edge.target_id);
                if (!source || !target) {
                  return null;
                }
                const active = source.id === selected?.id || target.id === selected?.id;
                return (
                  <g key={edge.id}>
                    <line
                      x1={source.x}
                      y1={source.y}
                      x2={target.x}
                      y2={target.y}
                      className={active ? "memory-edge active" : "memory-edge"}
                    />
                    {active ? (
                      <text x={(source.x + target.x) / 2} y={(source.y + target.y) / 2 - 6} className="memory-edge-label">
                        {edge.relation_type}
                      </text>
                    ) : null}
                  </g>
                );
              })}
              {positioned.nodes.map((node) => (
                <g
                  key={node.id}
                  className={node.id === selected?.id ? "memory-node active" : "memory-node"}
                  onClick={() => setSelectedId(node.id)}
                >
                  <title>{node.label}</title>
                  <circle cx={node.x} cy={node.y} r={node.kind === "fact" ? 17 : 22} fill={nodeColor(node)} />
                  <circle cx={node.x} cy={node.y} r={node.kind === "fact" ? 21 : 27} className="memory-node-ring" />
                  {node.id === selected?.id ? (
                    <text x={node.x} y={node.y + (node.kind === "fact" ? 34 : 39)} className="memory-node-label">
                      {shortLabel(node.label, 20)}
                    </text>
                  ) : null}
                </g>
              ))}
            </svg>
          ) : (
            <div className="memory-empty-state">No graph yet. Reindex to build it from TXT memory.</div>
          )}
        </div>

        <aside className="memory-detail-panel">
          <div className="memory-detail-title">
            <GitBranch size={19} />
            <h2>{selected ? selected.label : "No node selected"}</h2>
          </div>
          {selected ? (
            <>
              <div className="memory-node-meta">
                <span>{selected.kind}</span>
                <span>{selected.type}</span>
                {selected.confidence ? <span>{Math.round(selected.confidence * 100)}%</span> : null}
              </div>
              <p>{selected.summary || "No summary."}</p>
              {selected.source_paths?.length ? (
                <div className="memory-sources">
                  {selected.source_paths.slice(0, 4).map((path) => (
                    <span key={path}>{selected.source_line ? `${path}:${selected.source_line}` : path}</span>
                  ))}
                </div>
              ) : null}
              <div className="memory-linked-list">
                <h3>Relationships</h3>
                {linkedEdges.length ? (
                  linkedEdges.map((edge) => <RelationshipRow key={edge.id} edge={edge} nodes={allNodeMap} />)
                ) : (
                  <span className="memory-muted">No visible relationships.</span>
                )}
              </div>
            </>
          ) : (
            <p>Select a node to inspect its source-backed memory.</p>
          )}

          {searchResult ? (
            <div className="memory-search-results">
              <h3>Search results</h3>
              {searchResult.warnings?.length ? (
                <div className="memory-warning">
                  <ShieldAlert size={16} />
                  Some results may be superseded.
                </div>
              ) : null}
              {searchResult.answer_relevant_facts.slice(0, 4).map((item) => (
                <button key={item.fact.id} type="button" onClick={() => setSelectedId(item.fact.id)}>
                  <strong>{item.fact.type}</strong>
                  <span>{item.fact.text}</span>
                </button>
              ))}
            </div>
          ) : null}
        </aside>
      </div>
    </section>
  );
}

function layoutGraph(graph: MemoryGraphData | null) {
  const nodes = (graph?.nodes ?? []).slice(0, MAX_VISIBLE_NODES);
  const byId = new Map<string, PositionedNode>();
  const centerX = GRAPH_WIDTH / 2;
  const centerY = GRAPH_HEIGHT / 2;
  const factNodes = nodes.filter((node) => node.kind === "fact");
  const entityNodes = nodes.filter((node) => node.kind !== "fact");
  const arranged = [...entityNodes, ...factNodes].map((node, index) => {
    const groupCount = node.kind === "fact" ? Math.max(1, factNodes.length) : Math.max(1, entityNodes.length);
    const groupIndex = node.kind === "fact" ? factNodes.findIndex((item) => item.id === node.id) : entityNodes.findIndex((item) => item.id === node.id);
    const radius = node.kind === "fact" ? 225 : 126;
    const angle = (Math.PI * 2 * groupIndex) / groupCount + (node.kind === "fact" ? 0.12 : 0.42);
    const offset = index % 2 === 0 ? 0 : 22;
    const positionedNode = {
      ...node,
      x: centerX + Math.cos(angle) * (radius + offset),
      y: centerY + Math.sin(angle) * (radius + offset)
    };
    byId.set(node.id, positionedNode);
    return positionedNode;
  });
  const edges = (graph?.edges ?? []).filter((edge) => byId.has(edge.source_id) && byId.has(edge.target_id)).slice(0, 160);
  return { nodes: arranged, edges, byId };
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="memory-stat">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function RelationshipRow({ edge, nodes }: { edge: MemoryGraphEdge; nodes: Map<string, MemoryGraphNode> }) {
  const source = nodes.get(edge.source_id);
  const target = nodes.get(edge.target_id);
  return (
    <div className="memory-relationship-row">
      <span>{source?.label ?? edge.source_id}</span>
      <strong>{edge.relation_type}</strong>
      <span>{target?.label ?? edge.target_id}</span>
    </div>
  );
}

function shortLabel(value: string, limit: number) {
  const clean = value.trim();
  if (clean.length <= limit) {
    return clean;
  }
  return `${clean.slice(0, Math.max(4, limit - 3)).trim()}...`;
}

function nodeColor(node: MemoryGraphNode) {
  if (node.kind === "fact") {
    return "#8ecae6";
  }
  if (node.type === "person") {
    return "#f4d35e";
  }
  if (node.type === "project") {
    return "#7bd88f";
  }
  if (node.type === "constraint") {
    return "#ee6c4d";
  }
  if (node.type === "preference") {
    return "#f6ad55";
  }
  return "#c3b8ff";
}
