"""Robust winding reconciliation: L1 integer synchronization vs BFS propagation.

A winding-constraint graph holds noisy pairwise observations
``d_ij ≈ w_i − w_j`` between nodes (patches, seeds, points) whose integer
winding numbers ``w`` are unknown. This module separates *reconciliation* of
such observations from *measuring* them: it never generates constraints and
never reads ink.

Three reconcilers on the identical observations:

- ``bfs``: reference BFS spanning-tree propagation. One root per connected
  component (smallest node id) gets 0, and each tree edge (discovered in
  edge-id order) fixes the next node. Redundant edges are ignored, so one wrong
  tree edge shifts the whole subtree below it. This is a reference
  implementation of the procedure, not a copy of any upstream code.
- ``l1``: minimise ``Σ weight_e · |w_i − w_j − d_e|`` with one gauge-fixed root
  per component. The constraint matrix (graph incidence plus slack identity)
  is totally unimodular, so with integer ``d`` a vertex optimum of the LP is
  integral without rounding. The solver returns a basic solution (HiGHS dual
  simplex) and the result is *checked* for integrality; a non-integral
  optimum fails closed instead of being rounded.
- ``l2_rounded``: least squares, then rounding. Reported as a baseline only.

``campaign`` runs a frozen corruption experiment on a trusted graph. It plants
signed ±k errors at preregistered rates into preregistered edge classes
(``uniform``; ``bridge``, where no redundant evidence exists;
``bfs_tree``; and ``bfs_tree_high``, tree edges carrying a large subtree),
reconciles the identical observations with each method, and scores
gauge-aligned node identity against the untouched solution. It promotes L1
only if both methods reproduce the uncorrupted solution exactly, L1 is
materially better on the primary cells, and L1 is never worse than BFS
beyond tolerance in any cell.

The graph schema has no place for ink. Any field whose name contains ``ink``
is refused.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, deque
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from scipy.optimize import linprog
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import lsqr

SCHEMA_VERSION = 1
TOOL = "scroliq-winding-sync"
METHODS = ("bfs", "l1", "l2_rounded")
LOCATIONS = ("uniform", "bridge", "bfs_tree", "bfs_tree_high")
PRIMARY_LOCATIONS = ("uniform", "bfs_tree", "bfs_tree_high")
INTEGRAL_TOL = 1e-6
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
INK_KEY_RE = re.compile(r"(^|[^a-z])ink")  # ink_prob, has_ink; not linked


class SyncError(ValueError):
    pass


def _canonical(document: Any) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def digest(document: Any) -> str:
    return hashlib.sha256(_canonical(document)).hexdigest()


def _refuse_ink(obj: Any, where: str) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if INK_KEY_RE.search(str(k).lower()):
                raise SyncError(
                    f"{where}: field {k!r} looks like ink evidence; winding "
                    "reconciliation must never consult ink")
            _refuse_ink(v, f"{where}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _refuse_ink(v, f"{where}[{i}]")


# ----------------------------------------------------------------- the graph


class Graph:
    """Validated winding-constraint graph with integer observations."""

    def __init__(self, nodes: Sequence[str], edges: Sequence[dict]):
        self.nodes = list(nodes)
        self.index = {n: k for k, n in enumerate(self.nodes)}
        self.edges = list(edges)
        self.ei = np.array([self.index[e["i"]] for e in edges], dtype=np.int64)
        self.ej = np.array([self.index[e["j"]] for e in edges], dtype=np.int64)
        self.d = np.array([e["d"] for e in edges], dtype=np.int64)
        self.w = np.array([e.get("weight", 1.0) for e in edges], dtype=float)
        self.adj: list[list[int]] = [[] for _ in self.nodes]
        for k in range(len(edges)):
            self.adj[self.ei[k]].append(k)
            self.adj[self.ej[k]].append(k)
        self.component = self._components()

    @classmethod
    def from_document(cls, document: Any) -> "Graph":
        if not isinstance(document, dict) or document.get("schema_version") != 1:
            raise SyncError("graph: schema_version must be 1")
        _refuse_ink(document, "graph")
        raw = document.get("edges")
        if not isinstance(raw, list) or not raw:
            raise SyncError("graph: edges must be a non-empty list")
        edges, ids, nodes = [], set(), set(document.get("nodes") or [])
        for k, e in enumerate(raw):
            if not isinstance(e, dict):
                raise SyncError(f"edges[{k}] must be an object")
            eid, i, j, d = e.get("edge_id"), e.get("i"), e.get("j"), e.get("d")
            for name, v in (("edge_id", eid), ("i", i), ("j", j)):
                if not isinstance(v, str) or not NAME_RE.match(v):
                    raise SyncError(f"edges[{k}].{name}: expected an id string")
            if i == j:
                raise SyncError(f"edges[{k}] is a self-loop")
            if type(d) is not int:
                raise SyncError(f"edges[{k}].d must be an integer winding "
                                "difference (w_i - w_j)")
            wt = e.get("weight", 1.0)
            if (isinstance(wt, bool) or not isinstance(wt, (int, float))
                    or not np.isfinite(wt) or wt <= 0):
                raise SyncError(f"edges[{k}].weight must be finite and > 0")
            if eid in ids:
                raise SyncError(f"duplicate edge_id {eid}")
            ids.add(eid)
            nodes.update((i, j))
            edges.append({"edge_id": eid, "i": i, "j": j, "d": d,
                          "weight": float(wt)})
        edges.sort(key=lambda e: e["edge_id"])
        return cls(sorted(nodes), edges)

    def to_document(self, provenance: Mapping[str, Any] | None = None) -> dict:
        doc = {"schema_version": 1, "nodes": list(self.nodes),
               "edges": [dict(e) for e in self.edges]}
        if provenance:
            doc["provenance"] = dict(provenance)
        return doc

    def with_observations(self, d: np.ndarray) -> "Graph":
        edges = [dict(e, d=int(v)) for e, v in zip(self.edges, d)]
        return Graph(self.nodes, edges)

    def _components(self) -> np.ndarray:
        comp = np.full(len(self.nodes), -1, dtype=np.int64)
        c = 0
        for s in range(len(self.nodes)):
            if comp[s] >= 0:
                continue
            comp[s] = c
            q = deque([s])
            while q:
                u = q.popleft()
                for k in self.adj[u]:
                    v = self.ej[k] if self.ei[k] == u else self.ei[k]
                    if comp[v] < 0:
                        comp[v] = c
                        q.append(v)
            c += 1
        return comp

    @property
    def n_components(self) -> int:
        return int(self.component.max()) + 1 if len(self.nodes) else 0

    @property
    def cyclomatic(self) -> int:
        """Independent cycles = redundant observations beyond a spanning forest."""
        return len(self.edges) - len(self.nodes) + self.n_components

    def roots(self) -> list[int]:
        seen, roots = set(), []
        for k in range(len(self.nodes)):  # nodes are sorted: smallest id first
            c = int(self.component[k])
            if c not in seen:
                seen.add(c)
                roots.append(k)
        return roots

    def bridges(self) -> set[int]:
        """Edge indices whose removal disconnects the graph (Tarjan, iterative)."""
        n = len(self.nodes)
        disc = [-1] * n
        low = [0] * n
        out: set[int] = set()
        t = 0
        for s in range(n):
            if disc[s] >= 0:
                continue
            disc[s] = low[s] = t
            t += 1
            stack = [(s, -1, iter(self.adj[s]))]
            while stack:
                u, pe, it = stack[-1]
                advanced = False
                for k in it:
                    if k == pe:
                        continue
                    v = int(self.ej[k] if self.ei[k] == u else self.ei[k])
                    if disc[v] < 0:
                        disc[v] = low[v] = t
                        t += 1
                        stack.append((v, k, iter(self.adj[v])))
                        advanced = True
                        break
                    low[u] = min(low[u], disc[v])
                if advanced:
                    continue
                stack.pop()
                if stack:
                    p = stack[-1][0]
                    low[p] = min(low[p], low[u])
                    if low[u] > disc[p]:
                        out.add(pe)
        return out


# --------------------------------------------------------------- reconcilers


def solve_bfs(g: Graph) -> tuple[np.ndarray, dict]:
    """BFS spanning-tree propagation; returns windings and tree structure."""
    n = len(g.nodes)
    w = np.zeros(n, dtype=np.int64)
    seen = np.zeros(n, dtype=bool)
    parent_edge = np.full(n, -1, dtype=np.int64)
    order: list[int] = []
    for r in g.roots():
        seen[r] = True
        q = deque([r])
        while q:
            u = q.popleft()
            order.append(u)
            for k in g.adj[u]:  # edge-id order (edges are sorted)
                i, j = int(g.ei[k]), int(g.ej[k])
                v = j if i == u else i
                if seen[v]:
                    continue
                seen[v] = True
                w[v] = w[u] - g.d[k] if i == u else w[u] + g.d[k]
                parent_edge[v] = k
                q.append(v)
    # subtree size below each tree edge (child side)
    size = np.ones(n, dtype=np.int64)
    for v in reversed(order):
        k = parent_edge[v]
        if k >= 0:
            p = int(g.ei[k] if g.ej[k] == v else g.ej[k])
            size[p] += size[v]
    comp_size = Counter(g.component.tolist())
    tree = {int(parent_edge[v]): {
        "child": v, "subtree": int(size[v]),
        "subtree_frac": size[v] / comp_size[int(g.component[v])]}
        for v in range(n) if parent_edge[v] >= 0}
    return w, {"tree_edges": tree}


def solve_l1(g: Graph) -> tuple[np.ndarray, dict]:
    """Integer L1 synchronization by LP over a totally unimodular system."""
    n, m = len(g.nodes), len(g.edges)
    rows = np.repeat(np.arange(2 * m), 3)
    cols = np.empty(6 * m, dtype=np.int64)
    vals = np.empty(6 * m)
    k = np.arange(m)
    # row 2k  :  w_i - w_j - t_k <= d_k
    # row 2k+1: -w_i + w_j - t_k <= -d_k
    cols[0::6], vals[0::6] = g.ei, 1.0
    cols[1::6], vals[1::6] = g.ej, -1.0
    cols[2::6], vals[2::6] = n + k, -1.0
    cols[3::6], vals[3::6] = g.ei, -1.0
    cols[4::6], vals[4::6] = g.ej, 1.0
    cols[5::6], vals[5::6] = n + k, -1.0
    a_ub = coo_matrix((vals, (rows, cols)), shape=(2 * m, n + m)).tocsr()
    b_ub = np.empty(2 * m)
    b_ub[0::2], b_ub[1::2] = g.d, -g.d
    c = np.concatenate([np.zeros(n), g.w])
    roots = set(g.roots())
    bounds = [(0, 0) if v in roots else (None, None) for v in range(n)]
    bounds += [(0, None)] * m
    res = linprog(c, A_ub=a_ub, b_ub=b_ub, bounds=bounds, method="highs-ds")
    if res.status != 0:
        raise SyncError(f"L1 LP failed: {res.message}")
    x = res.x[:n]
    w = np.rint(x).astype(np.int64)
    gap = float(np.max(np.abs(x - w))) if n else 0.0
    if gap > INTEGRAL_TOL:
        raise SyncError(
            f"L1 LP optimum is not integral (max gap {gap:.3g}); refusing to "
            "round")
    resid = np.abs(w[g.ei] - w[g.ej] - g.d)
    return w, {"objective": float(res.fun), "max_integrality_gap": gap,
               "edges_with_residual": int((resid != 0).sum())}


def solve_l2_rounded(g: Graph) -> tuple[np.ndarray, dict]:
    n, m = len(g.nodes), len(g.edges)
    roots = g.roots()
    rows = np.concatenate([np.arange(m), np.arange(m),
                           m + np.arange(len(roots))])
    cols = np.concatenate([g.ei, g.ej, np.array(roots, dtype=np.int64)])
    vals = np.concatenate([np.sqrt(g.w), -np.sqrt(g.w), np.full(len(roots),
                                                                1e3)])
    a = coo_matrix((vals, (rows, cols)), shape=(m + len(roots), n)).tocsr()
    b = np.concatenate([g.d * np.sqrt(g.w), np.zeros(len(roots))])
    x = lsqr(a, b, atol=1e-12, btol=1e-12, iter_lim=50 * (n + m))[0]
    return np.rint(x).astype(np.int64), {}


SOLVERS = {"bfs": solve_bfs, "l1": solve_l1, "l2_rounded": solve_l2_rounded}


# ------------------------------------------------------------------- scoring


def node_accuracy(g: Graph, pred: np.ndarray, truth: np.ndarray) -> float:
    """Fraction of nodes correct after the best integer shift per component."""
    correct = 0
    for c in range(g.n_components):
        idx = np.nonzero(g.component == c)[0]
        diffs = Counter((truth[idx] - pred[idx]).tolist())
        best = max(diffs.values())
        correct += best
    return correct / len(g.nodes)


def edge_accuracy(g: Graph, pred: np.ndarray, truth: np.ndarray) -> float:
    """Fraction of graph edges whose reconciled difference is the true one."""
    ok = (pred[g.ei] - pred[g.ej]) == (truth[g.ei] - truth[g.ej])
    return float(ok.mean())


def clean_truth(g: Graph) -> dict:
    """The untouched solution, defined only if the graph is cycle-consistent."""
    w, _ = solve_bfs(g)
    resid = w[g.ei] - w[g.ej] - g.d
    bad = int((resid != 0).sum())
    return {"windings": w, "consistent": bad == 0,
            "inconsistent_edges": bad}


# ----------------------------------------------------------------- campaign


def validate_campaign_spec(document: Any) -> dict:
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise SyncError("spec: schema_version must be 1")
    _refuse_ink(document, "spec")
    spec = {"schema_version": 1}
    spec["campaign_id"] = str(document.get("campaign_id") or "")
    if not NAME_RE.match(spec["campaign_id"]):
        raise SyncError("spec.campaign_id must be a simple name")
    sha = document.get("graph_sha256")
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise SyncError("spec.graph_sha256 must bind the frozen clean graph")
    spec["graph_sha256"] = sha
    spec["graph_source"] = str(document.get("graph_source") or "").strip()
    if not spec["graph_source"]:
        raise SyncError("spec.graph_source must say where the trusted "
                        "(human-verified or synthetic) graph came from")
    rates = document.get("rates")
    if (not isinstance(rates, list) or not rates
            or not all(isinstance(r, (int, float)) and 0 < r < 1
                       for r in rates)):
        raise SyncError("spec.rates must be fractions in (0, 1)")
    spec["rates"] = sorted(float(r) for r in rates)
    mags = document.get("magnitudes", [1, 2])
    if (not isinstance(mags, list) or not mags
            or not all(type(k) is int and k >= 1 for k in mags)):
        raise SyncError("spec.magnitudes must be positive integers")
    spec["magnitudes"] = sorted(set(mags))
    locs = document.get("locations", list(LOCATIONS))
    if not isinstance(locs, list) or not locs or set(locs) - set(LOCATIONS):
        raise SyncError(f"spec.locations must be a subset of {LOCATIONS}")
    spec["locations"] = [x for x in LOCATIONS if x in locs]
    for key, lo, default in (("replicates", 1, 20), ("seed", 0, 0)):
        v = document.get(key, default)
        if type(v) is not int or v < lo:
            raise SyncError(f"spec.{key} must be an integer >= {lo}")
        spec[key] = v
    rule = document.get("rule", {})
    spec["rule"] = {
        "min_mean_gain": float(rule.get("min_mean_gain", 0.05)),
        "non_inferiority_tol": float(rule.get("non_inferiority_tol", 0.01)),
        "primary_min_rate": float(rule.get("primary_min_rate", 0.05)),
        "high_subtree_frac": float(rule.get("high_subtree_frac", 0.10)),
    }
    return spec


def _eligible(g: Graph, loc: str, tree: dict, bridges: set[int],
              high_frac: float) -> np.ndarray:
    m = len(g.edges)
    if loc == "uniform":
        return np.arange(m)
    if loc == "bridge":
        return np.array(sorted(bridges), dtype=np.int64)
    if loc == "bfs_tree":
        return np.array(sorted(tree), dtype=np.int64)
    return np.array(sorted(k for k, t in tree.items()
                           if t["subtree_frac"] >= high_frac), dtype=np.int64)


def run_campaign(spec_doc: Any, graph_doc: Any, *,
                 methods: Sequence[str] = METHODS) -> dict:
    spec = validate_campaign_spec(spec_doc)
    g = Graph.from_document(graph_doc)
    gsha = digest(g.to_document())
    if gsha != spec["graph_sha256"]:
        raise SyncError(
            f"graph sha256 {gsha} does not match the frozen spec "
            f"{spec['graph_sha256']}")
    rule = spec["rule"]
    truth = clean_truth(g)
    base = {
        "schema_version": SCHEMA_VERSION, "tool": TOOL,
        "spec_sha256": digest(spec), "graph_sha256": gsha,
        "graph": {"nodes": len(g.nodes), "edges": len(g.edges),
                  "components": g.n_components,
                  "edges_per_node": round(len(g.edges) / len(g.nodes), 3),
                  "cyclomatic_number": g.cyclomatic},
        "rule": rule, "ink_consulted": False,
    }
    if not truth["consistent"]:
        return {**base, "verdict": "UNVERIFIED",
                "reason": (f"clean graph has {truth['inconsistent_edges']} "
                           "edges inconsistent with any integer assignment; "
                           "the untouched solution is undefined")}
    t = truth["windings"]
    clean = {}
    for name in methods:
        w, _ = SOLVERS[name](g)
        clean[name] = {"node_accuracy": node_accuracy(g, w, t),
                       "edge_accuracy": edge_accuracy(g, w, t)}
    base["clean_reproduction"] = clean
    reproduced = all(clean[mm]["node_accuracy"] == 1.0
                     and clean[mm]["edge_accuracy"] == 1.0
                     for mm in ("bfs", "l1") if mm in clean)

    _, info = solve_bfs(g)
    tree = info["tree_edges"]
    bridges = g.bridges()
    rng = np.random.default_rng(spec["seed"])
    cells = []
    for loc in spec["locations"]:
        elig = _eligible(g, loc, tree, bridges, rule["high_subtree_frac"])
        for rate in spec["rates"]:
            for mag in spec["magnitudes"]:
                cell = {"location": loc, "rate": rate, "magnitude": mag,
                        "eligible_edges": int(elig.size)}
                if elig.size == 0:
                    cells.append({**cell, "status": "not_applicable"})
                    continue
                n_bad = max(1, int(round(rate * elig.size)))
                acc = {mm: [] for mm in methods}
                eacc = {mm: [] for mm in methods}
                for _ in range(spec["replicates"]):
                    pick = rng.choice(elig, size=n_bad, replace=False)
                    sign = rng.choice((-1, 1), size=n_bad)
                    d = g.d.copy()
                    d[pick] += sign * mag
                    gc = g.with_observations(d)
                    for mm in methods:
                        w, _ = SOLVERS[mm](gc)
                        acc[mm].append(node_accuracy(g, w, t))
                        eacc[mm].append(edge_accuracy(g, w, t))
                cell.update({
                    "status": "measured", "corrupted_edges": n_bad,
                    "node_accuracy": {mm: round(float(np.mean(v)), 4)
                                      for mm, v in acc.items()},
                    "node_accuracy_min": {mm: round(float(np.min(v)), 4)
                                          for mm, v in acc.items()},
                    "edge_accuracy": {mm: round(float(np.mean(v)), 4)
                                      for mm, v in eacc.items()},
                })
                if "l1" in acc and "bfs" in acc:
                    diff = np.array(acc["l1"]) - np.array(acc["bfs"])
                    cell["l1_minus_bfs"] = round(float(diff.mean()), 4)
                    cell["replicates_l1_worse"] = int((diff < 0).sum())
                cells.append(cell)

    measured = [c for c in cells if c["status"] == "measured"
                and "l1_minus_bfs" in c]
    primary = [c for c in measured if c["location"] in PRIMARY_LOCATIONS
               and c["rate"] >= rule["primary_min_rate"]]
    worst = min((c["l1_minus_bfs"] for c in measured), default=None)
    gain = (round(float(np.mean([c["l1_minus_bfs"] for c in primary])), 4)
            if primary else None)
    if not reproduced:
        verdict, reason = ("CLEAN_NOT_REPRODUCED",
                           "a reconciler changed the uncorrupted solution")
    elif g.cyclomatic == 0:
        verdict, reason = ("NO_REDUNDANCY",
                           "the graph is a forest; no redundant edge exists "
                           "for any reconciler to use")
    elif not primary:
        verdict, reason = "UNVERIFIED", "no primary cell was measured"
    elif worst is not None and worst < -rule["non_inferiority_tol"]:
        verdict, reason = ("L1_INFERIOR",
                           f"L1 is worse than BFS by {-worst:.4f} in a cell")
    elif gain < rule["min_mean_gain"]:
        verdict, reason = ("NO_MATERIAL_GAIN",
                           f"mean primary gain {gain} < {rule['min_mean_gain']}")
    else:
        verdict, reason = ("PROMOTE",
                           f"mean primary gain {gain}; never worse than BFS "
                           "beyond tolerance; clean solution reproduced")
    return {**base, "verdict": verdict, "reason": reason,
            "primary_mean_gain": gain, "worst_cell_l1_minus_bfs": worst,
            "bridges": len(bridges), "bfs_tree_edges": len(tree),
            "cells": cells,
            "scope": ("reconciliation of trusted observations only; says "
                      "nothing about whether any constraint generator's "
                      "observations are correct (see scroliq-constraint-gauge)")}


# --------------------------------------------------------- synthetic graphs


def synthetic_graph(nodes: int, edges_per_node: float, seed: int, *,
                    span: int = 3, windings: int = 40) -> dict:
    """A connected local graph with exact observations of known windings.

    Nodes are ordered by winding; each links to a random earlier node within
    ``span`` positions (a spanning tree), then extra local edges are added
    until the target density is reached.
    """
    if nodes < 2 or edges_per_node < (nodes - 1) / nodes:
        raise SyncError("need >= 2 nodes and enough edges for a spanning tree")
    rng = np.random.default_rng(seed)
    w = np.sort(rng.integers(0, windings, size=nodes))
    names = [f"n{k:05d}" for k in range(nodes)]
    pairs = set()
    for k in range(1, nodes):
        pairs.add((int(rng.integers(max(0, k - span), k)), k))
    target = int(round(edges_per_node * nodes))
    tries = 0
    while len(pairs) < target and tries < 100 * target:
        tries += 1
        k = int(rng.integers(1, nodes))
        j = int(rng.integers(max(0, k - span), k))
        pairs.add((j, k))
    edges = [{"edge_id": f"e{x:06d}", "i": names[a], "j": names[b],
              "d": int(w[a] - w[b])}
             for x, (a, b) in enumerate(sorted(pairs))]
    return {"schema_version": 1, "nodes": names, "edges": edges,
            "provenance": {"kind": "synthetic", "nodes": nodes,
                           "edges_per_node": edges_per_node, "seed": seed,
                           "span": span, "windings": windings}}


def positive_control() -> dict:
    """L1 must beat BFS on a redundant graph and tie it on a tree."""
    dense = Graph.from_document(synthetic_graph(120, 3.0, 7))
    tree = Graph.from_document(synthetic_graph(120, 119 / 120, 7))
    rng = np.random.default_rng(11)
    got = {}
    for name, g in (("dense", dense), ("tree", tree)):
        t = clean_truth(g)["windings"]
        d = g.d.copy()
        pick = rng.choice(len(d), size=max(1, len(d) // 10), replace=False)
        d[pick] += rng.choice((-1, 1), size=pick.size)
        gc = g.with_observations(d)
        got[name] = {m: node_accuracy(g, SOLVERS[m](gc)[0], t)
                     for m in ("bfs", "l1")}
    clean_ok = all(
        node_accuracy(g, solve_l1(g)[0], clean_truth(g)["windings"]) == 1.0
        for g in (dense, tree))
    obs = {
        "clean_reproduced": clean_ok,
        "dense_l1_beats_bfs_by_0.1": got["dense"]["l1"]
        >= got["dense"]["bfs"] + 0.1,
        "tree_l1_equals_bfs": got["tree"]["l1"] == got["tree"]["bfs"],
        "ink_field_refused": False,
    }
    try:
        Graph.from_document({"schema_version": 1, "edges": [
            {"edge_id": "e", "i": "a", "j": "b", "d": 1, "ink_score": 0.9}]})
    except SyncError:
        obs["ink_field_refused"] = True
    return {"passed": all(obs.values()), "observed": obs,
            "accuracy": {k: {m: round(v, 4) for m, v in r.items()}
                         for k, r in got.items()}}


# ---------------------------------------------------------------------- CLI


def _load(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_create_only(path: str, document: Any) -> None:
    with open(path, "x", encoding="utf-8") as fh:
        json.dump(document, fh, indent=1, sort_keys=True, allow_nan=False)
        fh.write("\n")


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog=TOOL, description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("solve", help="reconcile one graph")
    s.add_argument("--graph", required=True)
    s.add_argument("--method", choices=METHODS, default="l1")
    s.add_argument("--out", required=True)
    h = sub.add_parser("graph-hash", help="sha256 of the canonical graph")
    h.add_argument("--graph", required=True)
    c = sub.add_parser("campaign", help="frozen planted-corruption benchmark")
    c.add_argument("--spec", required=True)
    c.add_argument("--graph", required=True)
    c.add_argument("--out", required=True, help="create-only result")
    y = sub.add_parser("synthetic", help="write a synthetic trusted graph")
    y.add_argument("--nodes", type=int, default=400)
    y.add_argument("--edges-per-node", type=float, default=3.0)
    y.add_argument("--seed", type=int, default=0)
    y.add_argument("--out", required=True)
    sub.add_parser("self-test", help="run the built-in positive control")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "solve":
            g = Graph.from_document(_load(args.graph))
            w, info = SOLVERS[args.method](g)
            info.pop("tree_edges", None)
            _write_create_only(args.out, {
                "schema_version": 1, "tool": TOOL, "method": args.method,
                "graph_sha256": digest(g.to_document()),
                "windings": {n: int(v) for n, v in zip(g.nodes, w)},
                "gauge": "smallest node id per component is 0",
                "info": info})
            return 0
        if args.cmd == "graph-hash":
            print(digest(Graph.from_document(_load(args.graph)).to_document()))
            return 0
        if args.cmd == "campaign":
            r = run_campaign(_load(args.spec), _load(args.graph))
            _write_create_only(args.out, r)
            print(f"{r['verdict']}: {r['reason']}")
            return 0 if r["verdict"] != "UNVERIFIED" else 2
        if args.cmd == "synthetic":
            _write_create_only(args.out, synthetic_graph(
                args.nodes, args.edges_per_node, args.seed))
            return 0
        if args.cmd == "self-test":
            ctl = positive_control()
            print(json.dumps(ctl, indent=1))
            return 0 if ctl["passed"] else 2
    except (SyncError, OSError, json.JSONDecodeError) as exc:
        print(f"{TOOL}: {exc}", file=sys.stderr)
        return 2
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
