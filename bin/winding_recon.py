"""Read-only reconnaissance of spiral-fitting winding inputs (October goal O2).

Before building cross-collection winding consistency, measure what linkage
the real annotations can support. Prints one JSON document; writes nothing.

- frames: absolute (one frame), each relative collection, each same-winding
  collection; points per frame
- same-winding chains (point-id order): spacing between consecutive points and
  consecutive angle steps around the umbilicus, which decide whether a chain
  can be unwrapped around the axis
- cross-frame proximity: for several distances, how many point pairs from
  different frames lie that close, how many frame pairs that links, and the
  size and cycle count of the resulting frame graph
- optional ``spiral-scroll.json`` (outward sense) and a patch directory listing

    python bin/winding_recon.py DATASET [--patch-listing FILE]
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from scrollq.winding_geometry import load_umbilicus  # noqa: E402

ROLE_FILES = {
    "absolute": "abs_winding.json",
    "relative": "relative_windings.json",
    "same_winding": "same_windings.json",
}
DISTANCES = (2.0, 4.0, 8.0, 16.0)


def load_points(dataset: Path) -> list[dict]:
    rows = []
    for role, name in ROLE_FILES.items():
        path = dataset / name
        if not path.is_file():
            continue
        doc = json.loads(path.read_bytes())
        for cid, coll in (doc.get("collections") or {}).items():
            if not isinstance(coll, dict):
                continue
            frame = "absolute" if role == "absolute" else f"{role}:{cid}"
            for pid, point in (coll.get("points") or {}).items():
                p = point.get("p") if isinstance(point, dict) else None
                if not (isinstance(p, list) and len(p) == 3 and all(isinstance(v, (int, float)) for v in p)):
                    continue
                try:
                    order = int(pid)
                except ValueError:
                    continue
                rows.append({"role": role, "frame": frame, "order": order, "xyz": [float(v) for v in p]})
    return rows


def _quantiles(values: list[float]) -> dict | None:
    if not values:
        return None
    arr = np.asarray(values, dtype=float)
    return {k: round(float(np.quantile(arr, q)), 3) for k, q in
            (("median", 0.5), ("p95", 0.95), ("max", 1.0))}


def chain_stats(rows: list[dict], umbilicus) -> dict:
    by_frame: dict[str, list[dict]] = {}
    for row in rows:
        if row["role"] == "same_winding":
            by_frame.setdefault(row["frame"], []).append(row)
    spacing, dtheta, turns = [], [], []
    for pts in by_frame.values():
        pts.sort(key=lambda r: r["order"])
        if len(pts) < 2:
            continue
        xyz = np.asarray([r["xyz"] for r in pts])
        axis = umbilicus(xyz[:, 2]) if umbilicus else None
        spacing += np.linalg.norm(np.diff(xyz, axis=0), axis=1).tolist()
        if axis is not None:
            theta = np.arctan2(xyz[:, 1] - axis[:, 0], xyz[:, 0] - axis[:, 1])
            step = np.diff(theta)
            step = (step + math.pi) % (2 * math.pi) - math.pi
            dtheta += np.abs(step).tolist()
            turns.append(abs(float(step.sum())) / (2 * math.pi))
    return {
        "chains": len(by_frame),
        "consecutive_spacing_voxels": _quantiles(spacing),
        "consecutive_abs_dtheta_radians": _quantiles(dtheta),
        "steps_over_half_turn": int(sum(1 for d in dtheta if d > math.pi / 2)),
        "net_turns_per_chain": _quantiles(turns),
    }


def proximity(rows: list[dict], distances=DISTANCES) -> dict:
    xyz = np.asarray([r["xyz"] for r in rows], dtype=float)
    frames = [r["frame"] for r in rows]
    frame_id = {f: i for i, f in enumerate(sorted(set(frames)))}
    fid = np.asarray([frame_id[f] for f in frames])
    out = {}
    dmax = max(distances)
    cell = np.floor(xyz / dmax).astype(np.int64)
    buckets: dict[tuple, list[int]] = {}
    for i, c in enumerate(map(tuple, cell)):
        buckets.setdefault(c, []).append(i)
    pairs_i, pairs_j, pairs_d = [], [], []
    offsets = [(a, b, c) for a in (-1, 0, 1) for b in (-1, 0, 1) for c in (-1, 0, 1)]
    for c, members in buckets.items():
        near = [j for o in offsets for j in buckets.get((c[0] + o[0], c[1] + o[1], c[2] + o[2]), [])]
        near = np.asarray(near)
        for i in members:
            cand = near[(near > i) & (fid[near] != fid[i])]
            if cand.size:
                d = np.linalg.norm(xyz[cand] - xyz[i], axis=1)
                keep = d <= dmax
                pairs_i += [i] * int(keep.sum())
                pairs_j += cand[keep].tolist()
                pairs_d += d[keep].tolist()
    pi, pj, pd = map(np.asarray, (pairs_i, pairs_j, pairs_d))
    for dist in distances:
        sel = pd <= dist if pd.size else np.zeros(0, bool)
        edges = {tuple(sorted((int(fid[a]), int(fid[b])))) for a, b in zip(pi[sel], pj[sel])}
        nodes = {n for e in edges for n in e}
        parent = {n: n for n in nodes}

        def find(n):
            while parent[n] != n:
                parent[n] = parent[parent[n]]
                n = parent[n]
            return n

        for a, b in edges:
            parent[find(a)] = find(b)
        components = len({find(n) for n in nodes})
        names = sorted(frame_id)
        linked_frames = {names[n] for n in nodes}
        out[str(dist)] = {
            "point_pairs": int(sel.sum()),
            "frame_pairs": len(edges),
            "linked_frames": len(linked_frames),
            "linked_relative_collections": sum(1 for f in linked_frames if f.startswith("relative:")),
            "linked_same_winding_collections": sum(1 for f in linked_frames if f.startswith("same_winding:")),
            "absolute_frame_linked": "absolute" in linked_frames,
            "components": components,
            "independent_cycles": len(edges) - len(nodes) + components,
        }
    return out


def patch_listing_stats(html: str) -> dict:
    names = re.findall(r'href="([^"?/][^"]*/)"', html)
    return {"entries": len(names), "first": names[:3]}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("dataset")
    ap.add_argument("--patch-listing")
    args = ap.parse_args()
    dataset = Path(args.dataset)
    rows = load_points(dataset)
    umb = load_umbilicus(dataset / "umbilicus.json") if (dataset / "umbilicus.json").is_file() else None
    frames = {}
    for r in rows:
        frames.setdefault(r["role"], set()).add(r["frame"])
    report = {
        "points": {role: sum(1 for r in rows if r["role"] == role) for role in ROLE_FILES},
        "frames": {role: len(f) for role, f in frames.items()},
        "same_winding_chains": chain_stats(rows, umb),
        "cross_frame_proximity": proximity(rows),
    }
    scroll = dataset / "spiral-scroll.json"
    report["spiral_scroll"] = json.loads(scroll.read_text()) if scroll.is_file() else None
    if args.patch_listing and Path(args.patch_listing).is_file():
        report["verified_patches_listing"] = patch_listing_stats(Path(args.patch_listing).read_text(errors="replace"))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
