"""Graph algorithms: Personalized PageRank over the knowledge graph, salience
reinforcement/decay, and community detection (Leiden via igraph, with a
deterministic Label Propagation fallback).
"""

from __future__ import annotations

import time


def build_graph(con):
    """Build node->id index and an undirected weighted adjacency from active
    relations (invalid_at IS NULL). Returns (id_of, edges)."""
    id_of: dict[str, int] = {}
    edges: list[tuple[int, int, float]] = []
    rows = con.execute(
        """SELECT r.id, e1.canonical_name AS a, e2.canonical_name AS b, r.weight
           FROM relations r
           JOIN entities e1 ON e1.id=r.source_id
           JOIN entities e2 ON e2.id=r.target_id
           WHERE r.invalid_at IS NULL
           ORDER BY r.id"""
    ).fetchall()
    for r in rows:
        a = id_of.setdefault(r["a"], len(id_of))
        b = id_of.setdefault(r["b"], len(id_of))
        edges.append((a, b, float(r["weight"] or 1.0)))
    return id_of, edges


def personalized_pagerank(id_of: dict, edges: list, seeds: dict, alpha: float = 0.85, n_iter: int = 60, tol: float = 1e-7):
    """Personalized PageRank (HippoRAG-style) over the graph.

    seeds: {node_id: initial_rank} where node_id is the integer index into id_of.
    Returns a dict {node_id: rank} for all reachable nodes.
    """
    import numpy as np

    n = len(id_of)
    if n == 0:
        return {}
    # Adjacency (row-normalized out). Symmetrize-undirected graph.
    adj = {i: {} for i in range(n)}
    for a, b, w in edges:
        adj[a][b] = adj[a].get(b, 0.0) + w
        adj[b][a] = adj[b].get(a, 0.0) + w
    # Row-stochastic transition matrix.
    P = np.zeros((n, n))
    for i in adj:
        nb = adj[i]
        s = sum(nb.values())
        if s > 0:
            for j, w in nb.items():
                P[i, j] = w / s
    # Seed vector normalized.
    if not seeds:
        seeds = {0: 1.0}
    rank = np.zeros(n)
    for k, v in seeds.items():
        if 0 <= k < n:
            rank[k] += float(v)
    tot = rank.sum()
    if tot <= 0:
        return {}
    rank /= tot
    teleport = alpha
    for _ in range(n_iter):
        new = np.zeros(n)
        if teleport > 0:
            out_deg = P.sum(axis=1)
            dangling = (out_deg == 0)
            base = np.zeros(n)
            if dangling.any():
                base += rank[dangling].sum() * (np.ones(n) / n)
            new = (1 - teleport) * rank.copy()
            new += teleport * (rank @ P)
            new += base
        else:
            new = rank.copy()
        new = new / new.sum() if new.sum() > 0 else new
        if np.abs(new - rank).sum() < tol:
            rank = new
            break
        rank = new
    return {i: float(rank[i]) for i in range(n)}


def detect_communities(id_of: dict, edges: list) -> list[(set, int)]:
    """Detect communities. Returns list of (set_of_canonical_names, level)."""
    if not edges:
        return []
    names = {v: k for k, v in id_of.items()}
    from igraph import Graph

    g = Graph(n=len(id_of))
    g.add_edges([(a, b) for a, b, _ in edges])
    try:
        cl = g.community_leiden(objective="modularity", weights=[w for _, _, w in edges])
    except Exception:
        cl = g.community_label_propagation()
    out = []
    for i, mem in enumerate(cl):
        members = set()
        for node in mem:
            members.add(names.get(node))
        members.discard(None)
        if members:
            out.append((members, 0))
    return out


def reinforce(con, entity_ids: list[int], boost: float = 0.12) -> None:
    """Increase decay/access for touched entities (strengthening by use)."""
    if not entity_ids:
        return
    t = time.time()
    for eid in entity_ids:
        con.execute(
            """UPDATE entities SET decay=MIN(1.0, decay+?), access_count=access_count+1,
               last_access=?, updated_at=? WHERE id=?""",
            (boost, t, t, eid),
        )


def apply_time_decay(con, half_life_days: float = 90.0) -> None:
    """Exponential decay of entity 'decay' over time since last_access."""
    import math

    now_t = time.time()
    lam = math.log(2) / max(half_life_days * 86400.0, 1.0)
    rows = con.execute("SELECT id, last_access, decay FROM entities").fetchall()
    for r in rows:
        dt = max(0.0, now_t - float(r["last_access"] or r["decay"] or 0))
        new = float(r["decay"] or 0) * math.exp(-lam * dt)
        if abs(new - float(r["decay"])) > 1e-6:
            con.execute("UPDATE entities SET decay=? WHERE id=?", (min(1.0, new), r["id"]))