"""Persistent topology of a surface patch under a support filtration.

A TIFXYZ patch is a grid of vertices. Given a per-vertex *support* field (for
example CT intensity or surface probability sampled at each vertex), the
superlevel sets ``S_tau = {valid vertices with support >= tau}`` shrink as
``tau`` rises. This module tracks, across ``tau``:

* **H0** — connected pieces of ``S_tau`` (4-connected on the grid), by the
  elder rule: a piece is born at its highest support and dies at the saddle
  where it joins an older piece;
* **H1** — holes of ``S_tau``, computed through the complementary
  8-connected sublevel filtration (invalid cells and the grid's outer ring are
  always in the complement, so a genuine tear is a hole at every level).

Two things are reported:

1. persistence diagrams, compared between surfaces by Wasserstein-1 and
   bottleneck distance (L-infinity ground metric, diagonal matching);
2. **bridge-witness candidates** (EXPERIMENT): H0 merges where *both* sides
   are large and the saddle support is low, so the patch's identity depends on
   a narrow, weakly supported connection. Each candidate names the saddle
   vertex (grid row/col and XYZ) and both sides' areas.

``benchmark`` plants faults in a deterministic synthetic sheet stack and asks
the narrow question: does persistent topology detect planted structural faults
that ordinary mesh metrics and a plain low-support count miss, while staying
quiet on benign edits? It is a calibration of the method, not a measurement of
any scroll. Topology is a comparative witness here, never a prior: a valid
papyrus patch may legitimately have several pieces and holes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Sequence

import numpy as np
from scipy.optimize import linear_sum_assignment
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import maximum_bipartite_matching

SCHEMA_VERSION = 1
TOOL = "scroliq-topology"
METHOD = "scroliq-persistent-topology-v1"

# Frozen constants (written before any benchmark output was read).
MIN_PERSISTENCE = 0.1  # features below this (support units) are not compared
BRIDGE_MIN_AREA_FRACTION = 0.05  # both sides of a witnessed merge, of valid vertices
BRIDGE_MIN_PERSISTENCE = 0.3  # younger side's birth minus saddle support
LOW_SUPPORT = 0.5  # the plain local score: fraction of vertices below this
NULL_DRAWS = 19  # clean-vs-clean noise redraws; detection = exceed all of them

LIMITATION = (
    "Persistent topology describes how the patch's connectivity depends on the "
    "supplied support field. A flagged merge is a review cue: a legitimately "
    "faint band of papyrus splits the patch exactly as a wrong-winding bridge "
    "does, so topology alone cannot tell them apart. It does not establish "
    "sheet identity, CT support quality, ink or readability."
)


class _UF:
    def __init__(self, n: int):
        self.parent = np.arange(n)
        self.size = np.ones(n, dtype=np.int64)
        self.birth_vertex = np.arange(n)

    def find(self, a: int) -> int:
        parent = self.parent
        root = a
        while parent[root] != root:
            root = parent[root]
        while parent[a] != root:
            parent[a], a = root, parent[a]
        return root


def _offsets(connectivity: int):
    four = [(-1, 0), (1, 0), (0, -1), (0, 1)]
    return four if connectivity == 4 else four + [(-1, -1), (-1, 1), (1, -1), (1, 1)]


def _h0(values: np.ndarray, active: np.ndarray, *, descending: bool, connectivity: int,
        eldest: np.ndarray | None = None) -> list[dict[str, Any]]:
    """Elder-rule 0-dimensional persistence on a grid.

    Vertices enter in order of ``values`` (descending for superlevel,
    ascending for sublevel). ``eldest`` marks vertices whose component wins
    every tie (the outside ring in the H1 computation)."""
    h, w = values.shape
    flat = values.ravel()
    idx = np.flatnonzero(active.ravel())
    key = -flat[idx] if descending else flat[idx]
    order = idx[np.lexsort((idx, key))]
    uf = _UF(h * w)
    added = np.zeros(h * w, dtype=bool)
    rank = np.full(h * w, np.iinfo(np.int64).max)
    rank[order] = np.arange(order.size)
    if eldest is not None:
        rank[np.flatnonzero(eldest.ravel())] = -1
    pairs: list[dict[str, Any]] = []
    offs = _offsets(connectivity)
    for v in order:
        r, c = divmod(int(v), w)
        added[v] = True
        for dr, dc in offs:
            rr, cc = r + dr, c + dc
            if not (0 <= rr < h and 0 <= cc < w):
                continue
            u = rr * w + cc
            if not added[u]:
                continue
            a, b = uf.find(int(v)), uf.find(u)
            if a == b:
                continue
            # The elder component is the one whose birth vertex entered first.
            if rank[uf.birth_vertex[a]] > rank[uf.birth_vertex[b]]:
                a, b = b, a  # a is elder
            young_birth = int(uf.birth_vertex[b])
            if flat[young_birth] != flat[v]:  # a zero-length pair is not a feature
                pairs.append({
                    "birth": float(flat[young_birth]),
                    "death": float(flat[v]),
                    "birth_vertex": young_birth,
                    "saddle_vertex": int(v),
                    "younger_size": int(uf.size[b]),
                    "elder_size": int(uf.size[a]),
                })
            uf.parent[b] = a
            uf.size[a] += uf.size[b]
    roots = {uf.find(int(v)) for v in order}
    for root in roots:
        bv = int(uf.birth_vertex[root])
        pairs.append({"birth": float(flat[bv]), "death": None, "birth_vertex": bv,
                      "saddle_vertex": None, "younger_size": int(uf.size[root]),
                      "elder_size": 0})
    return pairs


def persistence(support: np.ndarray, valid: np.ndarray) -> dict[str, Any]:
    """H0 and H1 superlevel persistence of ``support`` over ``valid`` cells.

    Points are ``(birth, death)`` in support units with ``birth >= death``;
    essential features have ``death = None``."""
    support = np.asarray(support, dtype=np.float64)
    valid = np.asarray(valid, dtype=bool) & np.isfinite(support)
    h0 = _h0(np.where(valid, support, -np.inf), valid, descending=True, connectivity=4)
    # H1 through the complement: pad with an outside ring, invalid cells and
    # the ring enter first (value -inf); the ring is eldest.
    padded = np.full((support.shape[0] + 2, support.shape[1] + 2), -np.inf)
    padded[1:-1, 1:-1] = np.where(valid, support, -np.inf)
    ring = np.zeros(padded.shape, dtype=bool)
    ring[0, :] = ring[-1, :] = ring[:, 0] = ring[:, -1] = True
    comp = _h0(padded, np.ones(padded.shape, dtype=bool), descending=False, connectivity=8,
               eldest=ring)
    w2 = padded.shape[1]
    h1 = []
    for p in comp:
        if p["death"] is None:
            continue  # the outside component
        # A complement piece alive on (birth, death] is a hole of S on that range.
        sr, sc = divmod(p["saddle_vertex"], w2)
        h1.append({"birth": p["death"], "death": None if p["birth"] == -np.inf else p["birth"],
                   "saddle_vertex": (sr - 1) * support.shape[1] + (sc - 1),
                   "area": p["younger_size"]})
    return {"h0": h0, "h1": h1}


def _finite(points: list[dict[str, Any]], floor: float) -> np.ndarray:
    rows = [(p["birth"], floor if p["death"] is None else p["death"]) for p in points]
    arr = np.asarray(rows, dtype=np.float64).reshape(-1, 2)
    return arr[arr[:, 0] - arr[:, 1] >= MIN_PERSISTENCE]


def _diagram_costs(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    n, m = len(a), len(b)
    big = 1e18
    cost = np.zeros((n + m, n + m))
    if n and m:
        cost[:n, :m] = np.max(np.abs(a[:, None, :] - b[None, :, :]), axis=2)
    da = (a[:, 0] - a[:, 1]) / 2.0
    db = (b[:, 0] - b[:, 1]) / 2.0
    cost[:n, m:] = big
    cost[n:, :m] = big
    if n:
        cost[np.arange(n), m + np.arange(n)] = da
    if m:
        cost[n + np.arange(m), np.arange(m)] = db
    return cost


def wasserstein1(a: np.ndarray, b: np.ndarray) -> float:
    if not len(a) and not len(b):
        return 0.0
    cost = _diagram_costs(a, b)
    r, c = linear_sum_assignment(cost)
    return float(cost[r, c].sum())


def bottleneck(a: np.ndarray, b: np.ndarray) -> float:
    if not len(a) and not len(b):
        return 0.0
    cost = _diagram_costs(a, b)
    size = cost.shape[0]
    candidates = np.unique(cost[cost < 1e17])
    lo, hi = 0, len(candidates) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        graph = csr_matrix(cost <= candidates[mid])
        if np.all(maximum_bipartite_matching(graph, perm_type="column") >= 0) and size:
            hi = mid
        else:
            lo = mid + 1
    return float(candidates[lo])


def diagram_distance(p: dict[str, Any], q: dict[str, Any], floor: float) -> dict[str, float]:
    out = {}
    for dim in ("h0", "h1"):
        a, b = _finite(p[dim], floor), _finite(q[dim], floor)
        out[f"{dim}_w1"] = wasserstein1(a, b)
        out[f"{dim}_bottleneck"] = bottleneck(a, b)
    return out


def bridge_witnesses(diagrams: dict[str, Any], valid: np.ndarray, xyz: np.ndarray | None = None,
                     max_items: int = 20) -> list[dict[str, Any]]:
    """H0 merges whose both sides are large and whose saddle is weak."""
    total = int(np.asarray(valid).sum())
    if not total:
        return []
    w = valid.shape[1]
    out = []
    for p in diagrams["h0"]:
        if p["death"] is None:
            continue
        persist = p["birth"] - p["death"]
        smaller = min(p["younger_size"], p["elder_size"]) / total
        if persist >= BRIDGE_MIN_PERSISTENCE and smaller >= BRIDGE_MIN_AREA_FRACTION:
            r, c = divmod(p["saddle_vertex"], w)
            row = {"saddle_rc": [r, c], "saddle_support": p["death"],
                   "younger_birth": p["birth"], "persistence": persist,
                   "smaller_side_fraction": smaller,
                   "sides_vertices": [p["younger_size"], p["elder_size"]]}
            if xyz is not None:
                row["saddle_xyz"] = [float(v) for v in xyz[r, c]]
            out.append(row)
    out.sort(key=lambda row: (-row["persistence"] * row["smaller_side_fraction"],
                              row["saddle_rc"]))
    return out[:max_items]


# --------------------------------------------------------------------------
# Ordinary metrics: what a local mesh QA and a plain support count see.


def ordinary_metrics(xyz: np.ndarray, valid: np.ndarray, support: np.ndarray) -> dict[str, float]:
    from scipy.ndimage import label

    valid = np.asarray(valid, dtype=bool)
    comps = label(valid)[1]
    padded = np.pad(~valid, 1, constant_values=True)
    holes = label(padded, structure=np.ones((3, 3)))[1] - 1  # minus the outside piece
    edges = []
    for axis in (0, 1):
        a = valid & np.roll(valid, -1, axis=axis)
        if axis == 0:
            a[-1, :] = False
        else:
            a[:, -1] = False
        d = np.linalg.norm(np.roll(xyz, -1, axis=axis) - xyz, axis=-1)
        edges.append(d[a])
    edge = np.concatenate(edges) if edges else np.empty(0)
    sup = support[valid]
    return {
        "valid_fraction": float(valid.mean()),
        "components": float(comps),
        "holes": float(max(holes, 0)),
        "edge_median": float(np.median(edge)) if edge.size else 0.0,
        "edge_p99": float(np.percentile(edge, 99)) if edge.size else 0.0,
        "support_mean": float(sup.mean()) if sup.size else 0.0,
        "low_support_fraction": float((sup < LOW_SUPPORT).mean()) if sup.size else 0.0,
    }


# --------------------------------------------------------------------------
# Synthetic sheet stack and planted faults.

SYNTH = {
    "grid": 96,
    "step_voxels": 2.0,
    "pitch_voxels": 20.0,
    "sheet_sigma_voxels": 3.0,
    "noise_sigma": 0.05,
    "undulation_voxels": 4.0,
    "tear": {"rows": [10, 22], "cols": [10, 30]},  # genuine missing material
    "bridge_transition_cols": 16,
    "gentle_transition_cols": 40,
    "vertex_jitter_voxels": 0.25,  # re-tracing noise, so geometry metrics have a null too
}


def _sheet_height(k: int, x: np.ndarray, y: np.ndarray, p: dict[str, Any]) -> np.ndarray:
    und = p["undulation_voxels"] * np.sin(x / 37.0) * np.cos(y / 53.0)
    return k * p["pitch_voxels"] + und


def _support(xyz: np.ndarray, p: dict[str, Any], rng: np.random.Generator,
             faint: np.ndarray | None = None) -> np.ndarray:
    """CT-like support: Gaussian in distance to the nearest sheet, zero where
    material is missing (the tear), times an optional faint-material factor."""
    x, y, z = xyz[..., 0], xyz[..., 1], xyz[..., 2]
    base = _sheet_height(0, x, y, p)
    rel = (z - base) / p["pitch_voxels"]
    dist = np.abs(rel - np.round(rel)) * p["pitch_voxels"]
    s = np.exp(-0.5 * (dist / p["sheet_sigma_voxels"]) ** 2)
    # Missing material is a 3-D region (in x/y), so it follows the geometry,
    # not the grid indexing.
    t = p["tear"]
    gx, gy = x / p["step_voxels"], y / p["step_voxels"]
    missing = ((gy >= t["rows"][0]) & (gy < t["rows"][1])
               & (gx >= t["cols"][0]) & (gx < t["cols"][1]))
    s = np.where(missing, 0.0, s)
    if faint is not None:
        s = s * faint
    return np.clip(s + rng.normal(0.0, p["noise_sigma"], s.shape), 0.0, 1.0)


def synthetic_patch(p: dict[str, Any] | None = None, *, sheet: int = 2):
    """A clean trusted patch on one sheet: grid XYZ, validity (the tear is
    invalid, as trusted geometry does not cover missing material)."""
    p = dict(SYNTH if p is None else p)
    n = p["grid"]
    rr, cc = np.mgrid[0:n, 0:n].astype(np.float64)
    x = cc * p["step_voxels"]
    y = rr * p["step_voxels"]
    xyz = np.stack([x, y, _sheet_height(sheet, x, y, p)], axis=-1)
    valid = np.ones((n, n), dtype=bool)
    t = p["tear"]
    valid[t["rows"][0]:t["rows"][1], t["cols"][0]:t["cols"][1]] = False
    return xyz, valid


FAULTS = ("bridge", "bridge_gentle", "deleted_strip", "false_fill", "island")
MESH_METRICS = ("valid_fraction", "components", "holes", "edge_median", "edge_p99")
SUPPORT_METRICS = ("support_mean", "low_support_fraction")
BENIGN = ("orientation_reversal", "narrow_neck", "faint_band")


def plant(kind: str, xyz: np.ndarray, valid: np.ndarray, rng: np.random.Generator,
          p: dict[str, Any] | None = None):
    """Return (xyz, valid, faint, truth) for a planted fault or benign edit.

    ``truth`` is the grid region the edit touched (for localization)."""
    p = dict(SYNTH if p is None else p)
    n = p["grid"]
    xyz, valid = xyz.copy(), valid.copy()
    faint = None
    truth = np.zeros((n, n), dtype=bool)
    if kind in ("bridge", "bridge_gentle"):
        # Columns beyond c0 move to the next winding through a transition strip
        # that crosses the inter-sheet gap; geometry stays smooth.
        w = p["bridge_transition_cols"] if kind == "bridge" else p["gentle_transition_cols"]
        c0 = int(rng.integers(min(40, n - w - 9), n - w - 8))
        cols = np.arange(n)
        frac = np.clip((cols - c0) / w, 0.0, 1.0)
        xyz[..., 2] = xyz[..., 2] + p["pitch_voxels"] * frac[None, :]
        truth[:, c0:c0 + w] = True
    elif kind == "deleted_strip":
        r0 = int(rng.integers(40, n - 20))
        c0 = int(rng.integers(36, n - 50))
        valid[r0:r0 + 4, c0:c0 + 40] = False
        truth[r0:r0 + 4, c0:c0 + 40] = True
    elif kind == "false_fill":
        t = p["tear"]
        valid[t["rows"][0]:t["rows"][1], t["cols"][0]:t["cols"][1]] = True
        truth[t["rows"][0]:t["rows"][1], t["cols"][0]:t["cols"][1]] = True
    elif kind == "island":
        t = p["tear"]
        r = int(rng.integers(t["rows"][0] + 3, t["rows"][1] - 5))
        c = int(rng.integers(t["cols"][0] + 3, t["cols"][1] - 5))
        valid[r:r + 3, c:c + 3] = True
        truth[r:r + 3, c:c + 3] = True
    elif kind == "orientation_reversal":
        xyz = xyz[:, ::-1].copy()
        valid = valid[:, ::-1].copy()
    elif kind == "narrow_neck":
        r0 = int(rng.integers(40, n - 20))
        valid[r0:r0 + 6, 0:n // 2 - 2] = False
        valid[r0:r0 + 6, n // 2 + 2:] = False
        truth[r0:r0 + 6, :] = True
    elif kind == "faint_band":
        c0 = int(rng.integers(40, n - 20))
        faint = np.ones((n, n))
        faint[:, c0:c0 + 6] = 0.25  # thin but real papyrus, on the same sheet
        truth[:, c0:c0 + 6] = True
    else:
        raise ValueError(f"unknown edit {kind!r}")
    return xyz, valid, faint, truth


def _jitter(xyz: np.ndarray, p: dict[str, Any], rng: np.random.Generator) -> np.ndarray:
    return xyz + rng.normal(0.0, p["vertex_jitter_voxels"], xyz.shape)


def _exceeds(value: float, null: list[float]) -> bool:
    return value > max(null)


def benchmark(*, seeds: int = 10, p: dict[str, Any] | None = None) -> dict[str, Any]:
    p = dict(SYNTH if p is None else p)
    floor = 0.0
    kinds = FAULTS + BENIGN
    per_kind = {k: {"topology": 0, "mesh": 0, "support": 0, "bridge_witness": 0,
                    "witness_localized": 0, "trials": 0} for k in kinds}
    rows = []
    for seed in range(seeds):
        base_xyz, valid = synthetic_patch(p)
        rng = np.random.default_rng([20261006, seed])
        xyz = _jitter(base_xyz, p, rng)
        clean_support = _support(xyz, p, rng)
        clean = persistence(clean_support, valid)
        clean_metrics = ordinary_metrics(xyz, valid, clean_support)
        clean_witness = bridge_witnesses(clean, valid)
        null_topo: dict[str, list[float]] = {}
        null_ord: dict[str, list[float]] = {}
        for draw in range(NULL_DRAWS):
            draw_rng = np.random.default_rng([20261006, seed, 1000 + draw])
            dxyz = _jitter(base_xyz, p, draw_rng)
            s = _support(dxyz, p, draw_rng)
            for key, value in diagram_distance(clean, persistence(s, valid), floor).items():
                null_topo.setdefault(key, []).append(value)
            for key, value in ordinary_metrics(dxyz, valid, s).items():
                null_ord.setdefault(key, []).append(abs(value - clean_metrics[key]))
        for kind in kinds:
            edit_rng = np.random.default_rng([20261006, seed, kinds.index(kind)])
            exyz, evalid, faint, truth = plant(kind, base_xyz, valid, edit_rng, p)
            noise_rng = np.random.default_rng([20261006, seed, 5000 + kinds.index(kind)])
            exyz = _jitter(exyz, p, noise_rng)
            esupport = _support(exyz, p, noise_rng, faint)
            diag = persistence(esupport, evalid)
            dist = diagram_distance(clean, diag, floor)
            metrics = ordinary_metrics(exyz, evalid, esupport)
            topo_fired = sorted(k for k, v in dist.items() if _exceeds(v, null_topo[k]))
            ord_fired = sorted(k for k, v in metrics.items()
                               if _exceeds(abs(v - clean_metrics[k]), null_ord[k]))
            witnesses = bridge_witnesses(diag, evalid, exyz)
            new_witness = len(witnesses) > len(clean_witness)
            localized = any(truth[w["saddle_rc"][0], w["saddle_rc"][1]] for w in witnesses)
            agg = per_kind[kind]
            agg["trials"] += 1
            agg["topology"] += bool(topo_fired)
            agg["mesh"] += bool(set(ord_fired) & set(MESH_METRICS))
            agg["support"] += bool(set(ord_fired) & set(SUPPORT_METRICS))
            agg["bridge_witness"] += new_witness
            agg["witness_localized"] += bool(new_witness and localized)
            rows.append({"seed": seed, "edit": kind, "topology_fired": topo_fired,
                         "ordinary_fired": ord_fired, "distances": dist,
                         "bridge_witnesses": len(witnesses), "witness_localized": localized})
    summary = {}
    for kind, agg in per_kind.items():
        t = agg["trials"]
        summary[kind] = {
            "class": "fault" if kind in FAULTS else "benign",
            "trials": t,
            "topology_detect_rate": agg["topology"] / t,
            "mesh_metric_detect_rate": agg["mesh"] / t,
            "local_support_detect_rate": agg["support"] / t,
            "bridge_witness_rate": agg["bridge_witness"] / t,
            "witness_localized_rate": agg["witness_localized"] / t,
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "diagnostic": "persistent-topology-benchmark",
        "method": METHOD,
        "substrate": {"kind": "synthetic", "parameters": p},
        "seeds": seeds,
        "null_draws": NULL_DRAWS,
        "detection_rule": (
            "an edit is detected by a metric when its distance from the clean patch exceeds every "
            f"one of {NULL_DRAWS} clean-vs-clean support-noise redraws (exact level 1/{NULL_DRAWS + 1})"),
        "constants": {"min_persistence": MIN_PERSISTENCE,
                      "bridge_min_area_fraction": BRIDGE_MIN_AREA_FRACTION,
                      "bridge_min_persistence": BRIDGE_MIN_PERSISTENCE,
                      "low_support": LOW_SUPPORT},
        "mesh_metrics": list(MESH_METRICS),
        "local_support_metrics": list(SUPPORT_METRICS),
        "summary": summary,
        "rows": rows,
        "limitation": LIMITATION,
    }


def _load_grid(path: str) -> np.ndarray:
    from .ink_validation import _load_2d

    return np.asarray(_load_2d(path), dtype=np.float64)


def _sha(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    m = sub.add_parser("measure", help="persistence diagrams + bridge witnesses for one patch")
    m.add_argument("--surface", required=True, help="TIFXYZ directory")
    m.add_argument("--support", required=True,
                   help="per-vertex support on the TIFXYZ grid (.npy/.tif), larger = stronger")
    m.add_argument("--support-source", required=True,
                   help="how the support was computed (recorded, never inferred)")
    m.add_argument("--out", required=True)
    b = sub.add_parser("benchmark", help="planted-fault benchmark on the synthetic sheet stack")
    b.add_argument("--seeds", type=int, default=10)
    b.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    out = Path(args.out)
    if out.exists():
        parser.error(f"output already exists: {out}")
    if args.command == "benchmark":
        report = benchmark(seeds=args.seeds)
    else:
        from .tifxyz_audit import geometry_digest, load_valid_vertices

        xyz, valid, _ = load_valid_vertices(args.surface)
        support = _load_grid(args.support)
        if support.shape != valid.shape:
            parser.error(f"support shape {list(support.shape)} != grid {list(valid.shape)}")
        diagrams = persistence(support, valid)
        finite_valid = valid & np.isfinite(support)
        floor = float(np.nanmin(support[finite_valid])) if finite_valid.any() else 0.0
        report = {
            "schema_version": SCHEMA_VERSION,
            "tool": TOOL,
            "method": METHOD,
            "status": "measured" if finite_valid.any() else "unverified",
            "surface": {"path": args.surface, **geometry_digest(args.surface)},
            "support": {"path": args.support, "sha256": _sha(args.support),
                        "source": args.support_source},
            "constants": {"min_persistence": MIN_PERSISTENCE,
                          "bridge_min_area_fraction": BRIDGE_MIN_AREA_FRACTION,
                          "bridge_min_persistence": BRIDGE_MIN_PERSISTENCE},
            "diagram_floor": floor,
            "h0": [[float(a), float(b)] for a, b in _finite(diagrams["h0"], floor)],
            "h1": [[float(a), float(b)] for a, b in _finite(diagrams["h1"], floor)],
            "bridge_witnesses": bridge_witnesses(diagrams, finite_valid, xyz),
            "ordinary_metrics": ordinary_metrics(xyz, finite_valid,
                                                 np.where(finite_valid, support, 0.0)),
            "limitation": LIMITATION,
        }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
