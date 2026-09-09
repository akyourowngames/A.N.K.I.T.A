'use client';
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react';
import cytoscape, { Core } from 'cytoscape';
import { Edge, Entity, entityColor } from '@/lib/knowledge';

export type GraphControls = { fit: () => void; zoom: (factor: number) => void; focus: (id: string, depth: number) => void; reset: () => void; hideSelected: () => void };
type Props = { nodes: Entity[]; edges: Edge[]; search: string; layout: string; onSelect: (id: string | null) => void; onCount: (count: number) => void };

export const GraphCanvas = forwardRef<GraphControls, Props>(function GraphCanvas({ nodes, edges, search, layout, onSelect, onCount }, ref) {
  const host = useRef<HTMLDivElement>(null);
  const graph = useRef<Core>();
  const onSelectRef = useRef(onSelect); onSelectRef.current = onSelect;
  const onCountRef = useRef(onCount); onCountRef.current = onCount;
  const [hover, setHover] = useState<{ name: string; type: string } | null>(null);
  const reduced = useRef(false);
  useImperativeHandle(ref, () => ({
    fit: () => { graph.current?.fit(graph.current.elements(':visible'), 70); },
    zoom: factor => { const cy = graph.current; if (cy) cy.zoom({ level: cy.zoom() * factor, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } }); },
    focus: (id, depth) => {
      const cy = graph.current; if (!cy) return;
      let neighborhood = cy.getElementById(id);
      for (let i = 0; i < depth; i++) neighborhood = neighborhood.union(neighborhood.neighborhood());
      cy.elements().addClass('dimmed'); neighborhood.removeClass('dimmed');
      cy.animate({ fit: { eles: neighborhood, padding: 100 } }, { duration: reduced.current ? 0 : 450 });
    },
    reset: () => { graph.current?.elements().removeClass('dimmed hidden'); graph.current?.fit(undefined, 70); },
    hideSelected: () => { const selected = graph.current?.$(':selected'); selected?.connectedEdges().addClass('hidden'); selected?.addClass('hidden'); },
  }), []);
  useEffect(() => {
    if (!host.current) return;
    reduced.current = matchMedia('(prefers-reduced-motion: reduce)').matches;
    const cy = cytoscape({ container: host.current, minZoom: .12, maxZoom: 4, wheelSensitivity: .22, boxSelectionEnabled: true,
      textureOnViewport: true, hideEdgesOnViewport: false,
      style: [
        { selector: 'node', style: {
          'background-color': 'data(color)', width: 'data(size)', height: 'data(size)',
          'border-width': 6, 'border-color': 'data(color)', 'border-opacity': .13,
          label: 'data(name)', color: '#c1cde0', 'font-size': 13, 'font-family': 'Segoe UI, sans-serif',
          'text-valign': 'bottom', 'text-margin-y': 12, 'text-outline-width': 3, 'text-outline-color': '#0b101a',
          'min-zoomed-font-size': 8, 'overlay-opacity': 0,
        } },
        { selector: 'edge', style: { width: 1, 'line-color': '#344660', 'target-arrow-color': '#536784',
          'target-arrow-shape': 'triangle', 'arrow-scale': .65, 'curve-style': 'bezier',
          'opacity': .65, 'overlay-opacity': 0 } },
        { selector: 'edge[uncertain = 1]', style: { 'line-style': 'dashed', 'line-color': '#bf914e', 'target-arrow-color': '#bf914e', 'curve-style': 'bezier' } },
        { selector: ':selected', style: { 'border-color': '#d9e8ff', 'border-width': 3, 'border-opacity': 1, 'color': '#ffffff', 'z-index': 9 } },
        { selector: 'edge:selected', style: { 'line-color': '#8badff', 'target-arrow-color': '#8badff', width: 2.5, opacity: 1, 'curve-style': 'bezier', label: 'data(type)', 'font-size': 9, color: '#b8ccff', 'text-background-color': '#111a2b', 'text-background-opacity': 1, 'text-background-padding': '5px', 'text-rotation': 'autorotate' } },
        { selector: '.matched', style: { 'border-width': 10, 'border-opacity': .6, 'border-color': '#ffffff', color: '#ffffff' } },
        { selector: '.dimmed', style: { opacity: .12 } },
        { selector: '.hidden', style: { display: 'none' } },
      ],
    });
    graph.current = cy;
    cy.on('tap', 'node, edge', event => onSelectRef.current(event.target.id()));
    cy.on('tap', event => { if (event.target === cy) onSelectRef.current(null); });
    cy.on('select unselect', () => onCountRef.current(cy.$(':selected').length));
    cy.on('mouseover', 'node', event => setHover({ name: event.target.data('name'), type: event.target.data('type') }));
    cy.on('mouseout', 'node', () => setHover(null));
    const resize = new ResizeObserver(() => cy.resize()); resize.observe(host.current);
    return () => { resize.disconnect(); cy.destroy(); graph.current = undefined; };
  }, []);
  useEffect(() => {
    const cy = graph.current; if (!cy) return;
    const initial = cy.nodes().length === 0;
    const next = new Set([...nodes.map(n => n.id), ...edges.map(e => e.id)]);
    const topologyChanged = cy.elements().length !== next.size || cy.elements().filter(e => !next.has(e.id())).length > 0;
    const degree = new Map<string, number>();
    edges.forEach(e => { degree.set(e.source, (degree.get(e.source) || 0) + 1); degree.set(e.target, (degree.get(e.target) || 0) + 1); });
    cy.batch(() => {
      cy.elements().filter(e => !next.has(e.id())).remove();
      nodes.forEach((n, i) => {
        const data = { ...n, color: entityColor(n.type), size: 17 + Math.min(23, Math.sqrt(degree.get(n.id) || 0) * 4) };
        const existing = cy.getElementById(n.id);
        if (existing.length) existing.data(data);
        else {
          const angle = i * 2.39996, radius = 65 + Math.sqrt(i) * 37;
          const node = cy.add({ group: 'nodes', data, position: { x: Math.cos(angle) * radius, y: Math.sin(angle) * radius } });
          if (!reduced.current) node.style('opacity', 0).animate({ style: { opacity: 1 } }, { duration: 700, complete: () => node.removeStyle('opacity') });
        }
      });
      edges.forEach(e => {
        const data = { ...e, uncertain: e.confidence < .8 ? 1 : 0 };
        const existing = cy.getElementById(e.id);
        if (existing.length) existing.data(data); else cy.add({ group: 'edges', data });
      });
    });
    if (topologyChanged && nodes.length) {
      const nextLayout = cy.layout({ name: nodes.length > 700 ? 'concentric' : layout, animate: initial ? false : !reduced.current && nodes.length < 500, animationDuration: 650, padding: 90, randomize: false, nodeRepulsion: () => 45000, idealEdgeLength: () => 170, componentSpacing: 130, minNodeSpacing: 35, concentric: (node: cytoscape.NodeSingular) => node.degree(), levelWidth: () => 2 } as cytoscape.LayoutOptions);
      nextLayout.run();
      return () => { nextLayout.stop(); };
    }
  }, [nodes, edges]);
  useEffect(() => {
    const cy = graph.current; if (!cy?.nodes().length) return;
    const chosen = layout === 'cluster' ? 'concentric' : layout;
    cy.layout({ name: chosen, animate: !reduced.current && cy.nodes().length < 500, animationDuration: 600, padding: 80,
      randomize: false, nodeRepulsion: () => 45000, idealEdgeLength: () => 170, componentSpacing: 130,
      minNodeSpacing: 35, concentric: (node: cytoscape.NodeSingular) => node.degree(), levelWidth: () => 2,
    } as cytoscape.LayoutOptions).run();
  }, [layout]);
  useEffect(() => {
    const cy = graph.current; if (!cy) return;
    cy.nodes().removeClass('matched');
    const q = search.trim().toLowerCase();
    if (q) cy.nodes().filter(n => n.data('name').toLowerCase().includes(q) || n.data('aliases').some((a: string) => a.toLowerCase().includes(q))).addClass('matched');
  }, [search, nodes]);
  return <><div ref={host} className="kg-canvas" aria-label={`Interactive knowledge graph with ${nodes.length} entities and ${edges.length} relationships`} role="img" />
    {hover && <div className="kg-hover"><span style={{ background: entityColor(hover.type) }} /><strong>{hover.name}</strong><small>{hover.type} · Click to inspect evidence</small></div>}</>;
});
