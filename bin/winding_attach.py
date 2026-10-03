"""Patch attachment and cross-collection winding consistency (October goal O2, step 3).

Protocol, constants and decision rule: docs/winding-attachment-protocol.md.
Everything a result depends on is fixed in this file before any patch
geometry is read; ``decide()`` computes the outcome.

Step 1 (bin/winding_recon.py) found that annotations from different
collections almost never sit close enough to link directly. Step 2
(bin/winding_patch_index.py) found that patch bounding boxes are too coarse
to link them. This step uses the patch surfaces themselves:

1. **Attach.** An annotation point attaches to a patch when its distance to
   the patch's triangulated grid is at most ``ATTACH_DISTANCE`` voxels.
2. **Unwrap.** Each connected piece of a patch gets a continuous angle
   ``phi`` around the umbilicus, unwrapped across its grid. A piece whose
   unwrap is path-dependent (it encircles the axis) or that has a grid step
   wider than ``MAX_STEP_RADIANS`` is excluded and counted.
3. **Constrain.** With spiral sense ``s`` and branch-cut angle ``c``, the
   patch's integer winding at an attached point is ``o_P + floor(s(phi - c)/2pi)``
   for an unknown patch offset ``o_P``. The annotation says it equals
   ``wind_a + f_F`` for the frame offset ``f_F`` (0 for the absolute frame,
   unknown for each relative collection). Every attachment is therefore one
   integer constraint ``o_P - f_F = d``.
4. **Solve.** Offsets are fitted per connected component of the
   patch-frame graph (maximum-support spanning tree, then weighted-mode
   refinement). Each attachment's residual says how far its annotation
   disagrees with the rest. |residual| >= 2 is an inconsistency; |residual|
   == 1 can also come from a misplaced branch cut and is reported apart.
5. **Control.** Annotations on redundantly checked attachments are shifted
   by +2 one at a time and the solve is repeated; the checker counts only if
   it detects at least ``CONTROL_MIN_DETECTION`` of them.

Residuals are review cues, not verdicts: a patch can itself be mis-traced
onto a neighbouring winding, so an inconsistency may sit in the patch rather
than in the annotation.

    python bin/winding_attach.py DATASET LISTING.html BASE_URL OUT_DIR [--workers 32]
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import io
import json
import math
import random
import subprocess
import sys
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from scrollq.winding_geometry import _annotated_points, load_umbilicus  # noqa: E402

PROTOCOL = "docs/winding-attachment-protocol.md"
ROLES = ("absolute", "relative")
ATTACH_DISTANCE = 8.0               # voxels, primary threshold
SENSITIVITY_DISTANCES = (4.0, 12.0)  # descriptive arms
BBOX_MARGIN = 12.0                   # >= the largest threshold
MAX_STEP_RADIANS = math.pi / 4
SENSES = (1, -1)
CUT_DEGREES = tuple(range(0, 360, 10))
INCONSISTENT_ABS_RESIDUAL = 2
CONTROL_SHIFT = 2
CONTROL_TRIALS = 200
CONTROL_SEED = 20261003
CONTROL_MIN_DETECTION = 0.9
MAX_REVIEW = 200
REFINE_ROUNDS = 50
TWO_PI = 2 * math.pi


def preregistered_constants() -> dict:
    return {
        "protocol": PROTOCOL,
        "roles": list(ROLES),
        "attach_distance_voxels": ATTACH_DISTANCE,
        "sensitivity_distances_voxels": list(SENSITIVITY_DISTANCES),
        "bbox_margin_voxels": BBOX_MARGIN,
        "max_step_radians": MAX_STEP_RADIANS,
        "senses": list(SENSES),
        "cut_degrees": list(CUT_DEGREES),
        "inconsistent_abs_residual": INCONSISTENT_ABS_RESIDUAL,
        "control_shift": CONTROL_SHIFT,
        "control_trials": CONTROL_TRIALS,
        "control_seed": CONTROL_SEED,
        "control_min_detection": CONTROL_MIN_DETECTION,
    }


# --------------------------------------------------------------------------
# Patch geometry


def load_tifxyz(x: np.ndarray, y: np.ndarray, z: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Stack x/y/z grids to (H, W, 3); a vertex is valid when all three are
    finite and non-negative (VC3D marks holes with -1)."""
    xyz = np.stack([np.asarray(a, dtype=np.float64) for a in (x, y, z)], axis=-1)
    valid = np.isfinite(xyz).all(axis=-1) & (xyz >= 0).all(axis=-1)
    return xyz, valid


def _labels(n: int, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Connected-component labels (smallest member index) of an edge list."""
    lab = np.arange(n)
    if a.size == 0:
        return lab
    while True:
        prev = lab.copy()
        la, lb = lab[a], lab[b]
        np.minimum.at(lab, a, lb)
        np.minimum.at(lab, b, la)
        while True:  # pointer jumping
            jumped = lab[lab]
            if np.array_equal(jumped, lab):
                break
            lab = jumped
        if np.array_equal(lab, prev):
            return lab


def _grid_edges(valid: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    h, w = valid.shape
    idx = np.arange(h * w).reshape(h, w)
    horiz = valid[:, :-1] & valid[:, 1:]
    vert = valid[:-1, :] & valid[1:, :]
    a = np.concatenate([idx[:, :-1][horiz], idx[:-1, :][vert]])
    b = np.concatenate([idx[:, 1:][horiz], idx[1:, :][vert]])
    return a, b


def unwrap_patch(xyz: np.ndarray, valid: np.ndarray, umbilicus) -> dict:
    """Continuous angle around the umbilicus over each connected piece.

    Returns ``phi`` and ``theta`` (H, W, NaN where unusable), ``piece`` (H, W,
    -1 where invalid or excluded) and exclusion counts.
    """
    h, w = valid.shape
    n = h * w
    flat = xyz.reshape(n, 3)
    vflat = valid.reshape(n)
    theta = np.full(n, np.nan)
    if vflat.any():
        axis = umbilicus(flat[vflat, 2])
        theta[vflat] = np.arctan2(flat[vflat, 1] - axis[:, 0], flat[vflat, 0] - axis[:, 1])
    a, b = _grid_edges(valid)
    piece = _labels(n, a, b)
    raw = theta[b] - theta[a]
    wrapped = (raw + math.pi) % TWO_PI - math.pi
    excluded: set[int] = set(np.unique(piece[a[np.abs(wrapped) > MAX_STEP_RADIANS]]).tolist())
    reasons = {"large_angular_step": len(excluded), "encircles_axis": 0}

    smooth = np.abs(raw) <= math.pi
    sub = _labels(n, a[smooth], b[smooth])
    cut_a, cut_b = sub[a[~smooth]], sub[b[~smooth]]
    cut_delta = np.where(raw[~smooth] < 0, 1, -1)  # k_b - k_a
    adj: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for sa, sb, dk in set(zip(cut_a.tolist(), cut_b.tolist(), cut_delta.tolist())):
        adj[sa].append((sb, dk))
        adj[sb].append((sa, -dk))
    k = {}
    for start in adj:
        if start in k:
            continue
        k[start] = 0
        stack = [start]
        while stack:
            s = stack.pop()
            for t, dk in adj[s]:
                if t not in k:
                    k[t] = k[s] + dk
                    stack.append(t)
                elif k[t] != k[s] + dk:
                    p = int(piece[s])
                    if p not in excluded:
                        excluded.add(p)
                        reasons["encircles_axis"] += 1
    kvec = np.zeros(n)
    if k:
        keys = np.fromiter(k.keys(), dtype=np.int64)
        vals = np.fromiter(k.values(), dtype=np.float64)
        lookup = np.zeros(n)
        lookup[keys] = vals
        kvec = lookup[sub]
    phi = theta + TWO_PI * kvec
    usable = vflat & ~np.isin(piece, list(excluded))
    phi[~usable] = np.nan
    piece = np.where(usable, piece, -1)
    return {
        "phi": phi.reshape(h, w),
        "theta": theta.reshape(h, w),
        "piece": piece.reshape(h, w),
        "pieces": int(np.unique(piece[usable]).size) if usable.any() else 0,
        "excluded": reasons,
    }


def _closest_on_triangle(p, a, b, c) -> np.ndarray:
    """Closest point to p on triangle abc (Ericson, Real-Time Collision Detection 5.1.5)."""
    ab, ac, ap = b - a, c - a, p - a
    d1, d2 = ab @ ap, ac @ ap
    if d1 <= 0 and d2 <= 0:
        return a
    bp = p - b
    d3, d4 = ab @ bp, ac @ bp
    if d3 >= 0 and d4 <= d3:
        return b
    vc = d1 * d4 - d3 * d2
    if vc <= 0 and d1 >= 0 and d3 <= 0:
        return a + ab * (d1 / (d1 - d3))
    cp = p - c
    d5, d6 = ab @ cp, ac @ cp
    if d6 >= 0 and d5 <= d6:
        return c
    vb = d5 * d2 - d1 * d6
    if vb <= 0 and d2 >= 0 and d6 <= 0:
        return a + ac * (d2 / (d2 - d6))
    va = d3 * d6 - d5 * d4
    if va <= 0 and (d4 - d3) >= 0 and (d5 - d6) >= 0:
        return b + (c - b) * ((d4 - d3) / ((d4 - d3) + (d5 - d6)))
    denom = 1.0 / (va + vb + vc)
    return a + ab * (vb * denom) + ac * (vc * denom)


def attach_point(p: np.ndarray, xyz: np.ndarray, usable: np.ndarray, k_nearest: int = 4):
    """Distance from p to the patch's triangulated grid near its nearest
    usable vertices; returns (distance, (row, col) of the closest triangle
    vertex) or None."""
    rows, cols = np.nonzero(usable)
    if rows.size == 0:
        return None
    d2 = ((xyz[rows, cols] - p) ** 2).sum(axis=1)
    near = np.argsort(d2)[: min(k_nearest, d2.size)]
    h, w = usable.shape
    best = None
    seen = set()
    for i in near:
        r0, c0 = int(rows[i]), int(cols[i])
        for qr in (r0 - 1, r0):
            for qc in (c0 - 1, c0):
                if (qr, qc) in seen or qr < 0 or qc < 0 or qr + 1 >= h or qc + 1 >= w:
                    continue
                seen.add((qr, qc))
                quad = [(qr, qc), (qr, qc + 1), (qr + 1, qc), (qr + 1, qc + 1)]
                for tri in ((quad[0], quad[1], quad[2]), (quad[1], quad[3], quad[2])):
                    if not all(usable[v] for v in tri):
                        continue
                    q = _closest_on_triangle(p, *(xyz[v] for v in tri))
                    dist = float(np.linalg.norm(p - q))
                    if best is None or dist < best[0]:
                        vertex = min(tri, key=lambda v: float(((xyz[v] - q) ** 2).sum()))
                        best = (dist, vertex)
    return best


def attach_patch(name: str, xyz: np.ndarray, valid: np.ndarray, points: list[dict], umbilicus,
                 max_distance: float = max((ATTACH_DISTANCE,) + SENSITIVITY_DISTANCES)) -> dict:
    """Attachments of ``points`` to one patch, each with its unwrapped angle."""
    out = {"patch": name, "attachments": [], "pieces": 0, "excluded": {}}
    if not points or not valid.any():
        return out
    vx = xyz[valid]
    lo, hi = vx.min(axis=0) - max_distance, vx.max(axis=0) + max_distance
    close = [pt for pt in points if np.all((lo <= pt["xyz"]) & (pt["xyz"] <= hi))]
    if not close:
        return out
    # Cheap rejection before unwrapping: nearest vertex farther than
    # max_distance + the longest grid edge cannot hold a close triangle.
    a, b = _grid_edges(valid)
    flat = xyz.reshape(-1, 3)
    edge = float(np.linalg.norm(flat[a] - flat[b], axis=1).max()) if a.size else 0.0
    keep = []
    for pt in close:
        d = np.sqrt(((vx - pt["xyz"]) ** 2).sum(axis=1).min())
        if d <= max_distance + edge:
            keep.append(pt)
    if not keep:
        return out
    un = unwrap_patch(xyz, valid, umbilicus)
    out["pieces"], out["excluded"] = un["pieces"], un["excluded"]
    usable = un["piece"] >= 0
    for pt in keep:
        hit = attach_point(np.asarray(pt["xyz"]), xyz, usable)
        if hit is None or hit[0] > max_distance:
            continue
        dist, v = hit
        axis = umbilicus(np.asarray([pt["xyz"][2]]))[0]
        theta_pt = math.atan2(pt["xyz"][1] - axis[0], pt["xyz"][0] - axis[1])
        step = (theta_pt - un["theta"][v] + math.pi) % TWO_PI - math.pi
        out["attachments"].append({
            "point": pt["key"],
            "node": f"{name}#{int(un['piece'][v])}",
            "distance": round(dist, 3),
            "phi": float(un["phi"][v] + step),
        })
    return out


# --------------------------------------------------------------------------
# Constraint graph


def constraints(attachments: list[dict], points: dict[str, dict], *, sense: int, cut_degrees: float,
                max_distance: float = ATTACH_DISTANCE) -> list[dict]:
    """One integer constraint ``o_node - f_frame = d`` per attachment."""
    cut = math.radians(cut_degrees)
    out = []
    for att in attachments:
        if att["distance"] > max_distance:
            continue
        pt = points[att["point"]]
        m = math.floor(sense * (att["phi"] - cut) / TWO_PI)
        out.append({"point": att["point"], "node": att["node"], "frame": pt["frame"],
                    "d": pt["wind_a"] - m})
    return out


def _bridges(adj: dict[str, set[str]]) -> set[frozenset]:
    """Bridges of a simple undirected graph (iterative Tarjan)."""
    disc, low, out = {}, {}, set()
    counter = 0
    for root in sorted(adj):
        if root in disc:
            continue
        disc[root] = low[root] = counter
        counter += 1
        stack = [(root, None, iter(sorted(adj[root])))]
        while stack:
            v, parent, it = stack[-1]
            advanced = False
            for u in it:
                if u == parent:
                    continue
                if u in disc:
                    low[v] = min(low[v], disc[u])
                else:
                    disc[u] = low[u] = counter
                    counter += 1
                    stack.append((u, v, iter(sorted(adj[u]))))
                    advanced = True
                    break
            if not advanced:
                stack.pop()
                if parent is not None:
                    low[parent] = min(low[parent], low[v])
                    if low[v] > disc[parent]:
                        out.add(frozenset((v, parent)))
    return out


def solve(cons: list[dict]) -> dict:
    """Fit node and frame offsets; residual per constraint.

    Value convention: ``val[node] - val[frame] = d``. The absolute frame is
    fixed at 0; any other component is anchored at its smallest name.
    """
    edges: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for c in cons:
        edges[(c["node"], c["frame"])][c["d"]] += 1
    adj: dict[str, set[str]] = defaultdict(set)
    for n, f in edges:
        adj[n].add(f)
        adj[f].add(n)
    parent = {v: v for v in adj}

    def find(v):
        while parent[v] != v:
            parent[v] = parent[parent[v]]
            v = parent[v]
        return v

    tree: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for (n, f), counts in sorted(edges.items(), key=lambda e: (-sum(e[1].values()), e[0])):
        if find(n) != find(f):
            parent[find(n)] = find(f)
            d = min(counts, key=lambda x: (-counts[x], x))
            tree[n].append((f, -d))  # val[f] = val[n] - d
            tree[f].append((n, d))   # val[n] = val[f] + d
    comps: dict[str, list[str]] = defaultdict(list)
    for v in adj:
        comps[find(v)].append(v)
    val: dict[str, int] = {}
    anchors = {}
    for members in comps.values():
        anchor = "absolute" if "absolute" in members else min(members)
        for m in members:
            anchors[m] = anchor
        val[anchor] = 0
        stack = [anchor]
        while stack:
            v = stack.pop()
            for u, step in tree[v]:
                if u not in val:
                    val[u] = val[v] + step
                    stack.append(u)
    # Weighted-mode refinement: each free node takes the value most of its
    # constraints imply. Deterministic order; stops when nothing moves.
    implied: dict[str, list[tuple[str, int, int]]] = defaultdict(list)
    for (n, f), counts in edges.items():
        for d, k in counts.items():
            implied[n].append((f, d, k))    # val[n] = val[f] + d
            implied[f].append((n, -d, k))   # val[f] = val[n] - d
    order = sorted(v for v in adj if anchors[v] != v)
    for _ in range(REFINE_ROUNDS):
        moved = False
        for v in order:
            votes: Counter = Counter()
            for u, d, k in implied[v]:
                votes[val[u] + d] += k
            top = max(votes.values())
            winners = sorted(x for x, c in votes.items() if c == top)
            new = val[v] if val[v] in winners else winners[0]
            if new != val[v]:
                val[v] = new
                moved = True
        if not moved:
            break
    residuals = [val[c["node"]] - val[c["frame"]] - c["d"] for c in cons]
    nodes = len(adj)
    return {
        "values": val,
        "anchors": anchors,
        "residuals": residuals,
        "nodes": nodes,
        "components": len(comps),
        "collapsed_edges": len(edges),
        "independent_cycles": len(edges) - nodes + len(comps),
        "redundant_constraints": len(cons) - (nodes - len(comps)),
        "bridges": _bridges(adj),
        "edge_support": {k: sum(c.values()) for k, c in edges.items()},
        "frames_with_absolute": sorted(
            v for v in adj if v.startswith("relative:") and anchors[v] == "absolute"),
    }


def summarize(cons: list[dict], sol: dict) -> dict:
    res = sol["residuals"]
    abs_res = Counter(min(abs(r), INCONSISTENT_ABS_RESIDUAL) for r in res)
    ds: dict[tuple[str, str], set[int]] = defaultdict(set)
    for c in cons:
        ds[(c["node"], c["frame"])].add(c["d"])
    local = sum(1 for v in ds.values() if len(v) > 1)
    frames = {c["frame"] for c in cons}
    return {
        "constraints": len(cons),
        "nodes": sol["nodes"],
        "patch_pieces": sum(1 for v in sol["values"] if "#" in v),
        "frames": len(frames),
        "relative_frames": sum(1 for f in frames if f.startswith("relative:")),
        "relative_frames_tied_to_absolute": len(sol["frames_with_absolute"]),
        "components": sol["components"],
        "independent_cycles": sol["independent_cycles"],
        "redundant_constraints": sol["redundant_constraints"],
        "residual_0": abs_res.get(0, 0),
        "residual_abs_1": abs_res.get(1, 0),
        "residual_abs_ge_2": abs_res.get(INCONSISTENT_ABS_RESIDUAL, 0),
        "edges_with_disagreeing_points": local,
    }


def checkable(cons: list[dict], sol: dict) -> list[int]:
    """Constraints whose removal leaves their node and frame connected: an
    error on them changes a cycle, so a working checker must see it."""
    out = []
    for i, c in enumerate(cons):
        key = (c["node"], c["frame"])
        if sol["edge_support"][key] >= 2 or frozenset(key) not in sol["bridges"]:
            out.append(i)
    return out


def _component_of(cons: list[dict], i: int) -> list[int]:
    adj: dict[str, set[int]] = defaultdict(set)
    for j, c in enumerate(cons):
        adj[c["node"]].add(j)
        adj[c["frame"]].add(j)
    seen_v, seen_c = set(), set()
    stack = [cons[i]["node"]]
    while stack:
        v = stack.pop()
        if v in seen_v:
            continue
        seen_v.add(v)
        for j in adj[v]:
            if j not in seen_c:
                seen_c.add(j)
                stack += [cons[j]["node"], cons[j]["frame"]]
    return sorted(seen_c)


def injection_control(cons: list[dict], sol: dict, *, trials: int = CONTROL_TRIALS,
                      seed: int = CONTROL_SEED, shift: int = CONTROL_SHIFT) -> dict:
    """Shift one checkable, currently consistent annotation by ``shift`` and
    re-solve its component. Detected: the component gains a constraint with
    |residual| >= 2. Localized: the shifted constraint itself is flagged."""
    pool = [i for i in checkable(cons, sol) if sol["residuals"][i] == 0]
    picks = random.Random(seed).sample(pool, min(trials, len(pool)))
    detected = localized = 0
    for i in picks:
        idx = _component_of(cons, i)
        sub = [dict(cons[j]) for j in idx]
        before = sum(1 for j in idx if abs(sol["residuals"][j]) >= INCONSISTENT_ABS_RESIDUAL)
        k = idx.index(i)
        sub[k]["d"] += shift
        res = solve(sub)["residuals"]
        after = sum(1 for r in res if abs(r) >= INCONSISTENT_ABS_RESIDUAL)
        detected += after > before
        localized += abs(res[k]) >= INCONSISTENT_ABS_RESIDUAL
    n = len(picks)
    return {
        "eligible": len(pool),
        "trials": n,
        "shift": shift,
        "seed": seed,
        "detected": detected,
        "localized": localized,
        "detection_rate": detected / n if n else None,
        "localization_rate": localized / n if n else None,
    }


def decide(summary: dict, control: dict) -> dict:
    """UNVERIFIED  no redundant constraint, or the control detects fewer than
                   CONTROL_MIN_DETECTION of injected errors
    CONSISTENT     no constraint with |residual| >= 2
    INCONSISTENT   otherwise; the review queue lists the constraints"""
    rate = control.get("detection_rate")
    if summary["redundant_constraints"] <= 0 or rate is None or rate < CONTROL_MIN_DETECTION:
        verdict = "UNVERIFIED"
    elif summary["residual_abs_ge_2"] == 0:
        verdict = "CONSISTENT"
    else:
        verdict = "INCONSISTENT"
    return {"verdict": verdict, "control_detection_rate": rate,
            "control_min_detection": CONTROL_MIN_DETECTION,
            "inconsistent_constraints": summary["residual_abs_ge_2"]}


def choose_sense_and_cut(attachments, points, max_distance=ATTACH_DISTANCE) -> tuple[list[dict], dict]:
    """Primary (sense, cut): the pair with the fewest nonzero residuals,
    ties to sense +1 then the smallest cut. Every pair is reported."""
    table = []
    for sense in SENSES:
        for cut in CUT_DEGREES:
            cons = constraints(attachments, points, sense=sense, cut_degrees=cut, max_distance=max_distance)
            res = solve(cons)["residuals"]
            table.append({"sense": sense, "cut_degrees": cut,
                          "nonzero": sum(1 for r in res if r),
                          "abs_ge_2": sum(1 for r in res if abs(r) >= INCONSISTENT_ABS_RESIDUAL)})
    best = min(table, key=lambda t: (t["nonzero"], -t["sense"], t["cut_degrees"]))
    return table, best


def review_queue(cons: list[dict], sol: dict, points: dict[str, dict], attachments_by_key: dict) -> list[dict]:
    rows = []
    for c, r in zip(cons, sol["residuals"]):
        if abs(r) >= INCONSISTENT_ABS_RESIDUAL:
            pt = points[c["point"]]
            rows.append({"residual": r, "frame": c["frame"], "point_id": pt["point_id"],
                         "xyz": [float(v) for v in pt["xyz"]], "wind_a": pt["wind_a"], "patch_piece": c["node"],
                         "distance": attachments_by_key[(c["point"], c["node"])]["distance"]})
    rows.sort(key=lambda x: (-abs(x["residual"]), x["frame"], x["point_id"], x["patch_piece"]))
    return rows[:MAX_REVIEW]


def analyse(attachments: list[dict], points: dict[str, dict], control_trials: int = CONTROL_TRIALS) -> dict:
    table, best = choose_sense_and_cut(attachments, points)
    sense, cut = best["sense"], best["cut_degrees"]
    cons = constraints(attachments, points, sense=sense, cut_degrees=cut)
    sol = solve(cons)
    summary = summarize(cons, sol)
    control = injection_control(cons, sol, trials=control_trials)
    by_key = {(a["point"], a["node"]): a for a in attachments}
    sensitivity = {}
    for dist in SENSITIVITY_DISTANCES:
        c2 = constraints(attachments, points, sense=sense, cut_degrees=cut, max_distance=dist)
        sensitivity[str(dist)] = summarize(c2, solve(c2))
    return {
        "primary": {"sense": sense, "cut_degrees": cut, "attach_distance_voxels": ATTACH_DISTANCE},
        "decision": decide(summary, control),
        "summary": summary,
        "control": control,
        "sense_cut_table": table,
        "distance_sensitivity": sensitivity,
        "review_queue": review_queue(cons, sol, points, by_key),
    }


# --------------------------------------------------------------------------
# Real-data runner


def load_annotation_points(dataset: Path) -> dict[str, dict]:
    points = {}
    for role, name in (("absolute", "abs_winding.json"), ("relative", "relative_windings.json")):
        path = dataset / name
        if not path.is_file():
            continue
        for row in _annotated_points(json.loads(path.read_bytes()), role):
            key = f"{row['frame']}/{row['point_id']}"
            row["key"] = key
            row["xyz"] = np.asarray(row["xyz"], dtype=np.float64)
            points[key] = row
    return points


def _http_bytes(url: str, timeout: float = 60.0) -> bytes:
    last = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 - public read-only data
                return resp.read()
        except Exception as exc:  # noqa: BLE001
            last = exc
    raise last


def fetch_patch(base_url: str, name: str, fetch=_http_bytes):
    import tifffile
    grids = [tifffile.imread(io.BytesIO(fetch(f"{base_url.rstrip('/')}/{name}{a}.tif"))) for a in "xyz"]
    return load_tifxyz(*grids)


def run(dataset: Path, listing: str, base_url: str, workers: int = 32, fetch=_http_bytes,
        control_trials: int = CONTROL_TRIALS) -> dict:
    import winding_patch_index as pidx

    umbilicus = load_umbilicus(dataset / "umbilicus.json")
    points = load_annotation_points(dataset)
    entries = pidx.patch_entries(listing)
    index = pidx.fetch_index(base_url, entries, workers=workers * 2, fetch=lambda url: json.loads(fetch(url)))
    rows = [{"role": p["role"], "frame": p["frame"], "xyz": p["xyz"].tolist()} for p in points.values()]
    touching = pidx.patches_touching(rows, index["bbox"], roles=ROLES, margin=BBOX_MARGIN)
    lo_hi = {n: (np.asarray(index["bbox"][n][0]) - BBOX_MARGIN, np.asarray(index["bbox"][n][1]) + BBOX_MARGIN)
             for n in touching}
    plist = list(points.values())
    pxyz = np.asarray([p["xyz"] for p in plist])

    def one(name):
        lo, hi = lo_hi[name]
        inside = np.nonzero(np.all((lo <= pxyz) & (pxyz <= hi), axis=1))[0]
        try:
            xyz, valid = fetch_patch(base_url, name, fetch)
            return attach_patch(name, xyz, valid, [plist[i] for i in inside], umbilicus), None
        except Exception as exc:  # noqa: BLE001 - record and continue
            return None, f"{type(exc).__name__}: {exc}"[:160]

    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(one, touching))
    attachments, errors, excluded = [], {}, Counter()
    pieces = 0
    for name, (res, err) in zip(touching, results):
        if err:
            errors[name] = err
            continue
        attachments += res["attachments"]
        pieces += res["pieces"]
        excluded.update(res["excluded"])
    result = analyse(attachments, points, control_trials=control_trials)
    result["inputs"] = {
        "points": {r: sum(1 for p in plist if p["role"] == r) for r in ROLES},
        "patch_entries": len(entries),
        "patches_with_bbox": len(index["bbox"]),
        "patches_touching": len(touching),
        "patches_read": len(touching) - len(errors),
        "patch_read_errors": len(errors),
        "patch_read_error_examples": dict(list(errors.items())[:10]),
        "usable_pieces_in_touched_patches": pieces,
        "excluded_pieces": dict(excluded),
        "attachments_within_max_distance": len(attachments),
        "points_attached_primary": len({a["point"] for a in attachments if a["distance"] <= ATTACH_DISTANCE}),
        "sha256": {f.name: hashlib.sha256(f.read_bytes()).hexdigest()
                   for f in sorted(dataset.glob("*.json"))},
    }
    result["attachments"] = attachments
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("dataset")
    ap.add_argument("listing")
    ap.add_argument("base_url")
    ap.add_argument("out_dir")
    ap.add_argument("--workers", type=int, default=32)
    args = ap.parse_args()
    result = run(Path(args.dataset), Path(args.listing).read_text(errors="replace"), args.base_url,
                 workers=args.workers)
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:  # noqa: BLE001
        commit = None
    result["constants"] = preregistered_constants()
    result["generated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    result["source_commit"] = commit
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    attachments = result.pop("attachments")
    (out / "attachments.json").write_text(json.dumps(attachments) + "\n", encoding="utf-8")
    (out / "result.json").write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    with open(out / "review-queue.csv", "w", encoding="utf-8") as fh:
        fh.write("residual,frame,point_id,x,y,z,wind_a,patch_piece,distance\n")
        for r in result["review_queue"]:
            x, y, z = r["xyz"]
            fh.write(f"{r['residual']},{r['frame']},{r['point_id']},{x:.1f},{y:.1f},{z:.1f},"
                     f"{r['wind_a']},{r['patch_piece']},{r['distance']}\n")
    print(json.dumps({k: result[k] for k in ("primary", "decision", "summary", "control", "inputs")}, indent=2))


if __name__ == "__main__":
    main()
