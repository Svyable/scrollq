"""Patch bounding-box index for winding attachment (October goal O2, step 2).

Step 1 (bin/winding_recon.py) showed that annotations from different
collections almost never sit close enough to link directly, so cross-
collection winding consistency has to go through surface patches, as the
upstream spiral fitter does. Downloading every verified patch is out of
reach, so this step fetches only each patch's small ``meta.json``, indexes
its ``bbox``, and measures how far patch attachment could reach:

- how many annotation points fall inside at least one patch bbox
- which collections (frames) share a patch bbox, and the components and
  independent cycles of that frame graph

A bbox is an upper bound on the surface (and can be stale), so every count
here is an upper bound on real attachment; step 3 must confirm links against
the patch geometry itself.

    python bin/winding_patch_index.py DATASET LISTING.html BASE_URL OUT.json
        [--margin 8] [--workers 64]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from winding_recon import load_points  # noqa: E402


def patch_entries(listing_html: str) -> list[str]:
    """Directory entries of an autoindex page (names ending in '/')."""
    names = re.findall(r'href="([^"?/][^"]*/)"', listing_html)
    return sorted(set(n for n in names if not n.startswith(("..", "http"))))


def parse_bbox(meta) -> list[list[float]] | None:
    bbox = meta.get("bbox") if isinstance(meta, dict) else None
    if (isinstance(bbox, list) and len(bbox) == 2
            and all(isinstance(r, list) and len(r) == 3 for r in bbox)):
        try:
            arr = np.asarray(bbox, dtype=float)
        except (TypeError, ValueError):
            return None
        if np.isfinite(arr).all():
            return [arr.min(axis=0).tolist(), arr.max(axis=0).tolist()]
    return None


def _http_json(url: str, timeout: float = 30.0):
    with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 - public read-only data
        return json.loads(resp.read())


def fetch_index(base_url: str, entries: list[str], workers: int = 64, fetch=_http_json) -> dict:
    def one(name):
        try:
            return name, parse_bbox(fetch(f"{base_url.rstrip('/')}/{name}meta.json")), None
        except Exception as exc:  # noqa: BLE001 - record and continue
            return name, None, f"{type(exc).__name__}: {exc}"[:160]

    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(one, entries))
    return {
        "bbox": {n: b for n, b, _ in results if b is not None},
        "no_bbox": sorted(n for n, b, e in results if b is None and e is None),
        "errors": {n: e for n, _, e in results if e is not None},
    }


def reach(rows: list[dict], bboxes: dict[str, list[list[float]]], margin: float = 8.0) -> dict:
    names = sorted(bboxes)
    if names:
        lo = np.asarray([bboxes[n][0] for n in names]) - margin
        hi = np.asarray([bboxes[n][1] for n in names]) + margin
    covered = 0
    hits_per_point = []
    frames_by_patch: dict[int, set[str]] = {}
    for row in rows:
        if not names:
            hits_per_point.append(0)
            continue
        p = np.asarray(row["xyz"])
        inside = np.nonzero(np.all((lo <= p) & (p <= hi), axis=1))[0]
        hits_per_point.append(int(inside.size))
        if inside.size:
            covered += 1
        for k in inside:
            frames_by_patch.setdefault(int(k), set()).add(row["frame"])
    edges = set()
    for frames in frames_by_patch.values():
        fs = sorted(frames)
        for i in range(len(fs)):
            for j in range(i + 1, len(fs)):
                edges.add((fs[i], fs[j]))
    nodes = {n for e in edges for n in e}
    parent = {n: n for n in nodes}

    def find(n):
        while parent[n] != n:
            parent[n] = parent[parent[n]]
            n = parent[n]
        return n

    for a, b in edges:
        parent[find(a)] = find(b)
    roots = {find(n) for n in nodes}
    sizes: dict[str, int] = {}
    for n in nodes:
        sizes[find(n)] = sizes.get(find(n), 0) + 1
    hp = np.asarray(hits_per_point) if hits_per_point else np.zeros(0)
    by_role = {}
    for role in ("absolute", "relative", "same_winding"):
        idx = [i for i, r in enumerate(rows) if r["role"] == role]
        by_role[role] = {"points": len(idx), "inside_a_bbox": int(sum(1 for i in idx if hp[i] > 0))}
    return {
        "margin_voxels": margin,
        "points": len(rows),
        "points_inside_a_bbox": covered,
        "by_role": by_role,
        "bboxes_per_point": {
            "median": float(np.median(hp)) if hp.size else None,
            "p95": float(np.quantile(hp, 0.95)) if hp.size else None,
        },
        "patches_touching_annotations": len(frames_by_patch),
        "patches_linking_two_or_more_frames": sum(1 for f in frames_by_patch.values() if len(f) > 1),
        "frame_graph": {
            "frames_linked": len(nodes),
            "relative_frames_linked": sum(1 for n in nodes if n.startswith("relative:")),
            "absolute_frame_linked": "absolute" in nodes,
            "edges": len(edges),
            "components": len(roots),
            "largest_component": max(sizes.values()) if sizes else 0,
            "independent_cycles": len(edges) - len(nodes) + len(roots),
        },
    }


def patches_touching(rows: list[dict], bboxes: dict[str, list[list[float]]],
                     roles=("absolute", "relative"), margin: float = 8.0) -> list[str]:
    """Patch names whose (expanded) bbox contains a point of the given roles."""
    names = sorted(bboxes)
    if not names:
        return []
    lo = np.asarray([bboxes[n][0] for n in names]) - margin
    hi = np.asarray([bboxes[n][1] for n in names]) + margin
    hit = np.zeros(len(names), dtype=bool)
    for row in rows:
        if row["role"] in roles:
            p = np.asarray(row["xyz"])
            hit |= np.all((lo <= p) & (p <= hi), axis=1)
    return [n for n, h in zip(names, hit) if h]


def _http_size(url: str, timeout: float = 30.0) -> int | None:
    req = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - public read-only data
        length = resp.headers.get("Content-Length")
        return int(length) if length is not None else None


def size_sample(base_url: str, names: list[str], n: int, seed: int = 0,
                files=("x.tif", "y.tif", "z.tif", "meta.json"), workers: int = 32,
                head=_http_size) -> dict:
    """Estimate the download cost of ``names`` from a seeded sample of patches."""
    import random
    sample = random.Random(seed).sample(names, min(n, len(names)))

    def one(name):
        sizes = {}
        for f in files:
            try:
                sizes[f] = head(f"{base_url.rstrip('/')}/{name}{f}")
            except Exception:  # noqa: BLE001
                sizes[f] = None
        return name, sizes

    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(one, sample))
    totals = [sum(v for v in s.values() if v) for _, s in results if all(v is not None for v in s.values())]
    mean = sum(totals) / len(totals) if totals else None
    return {
        "population": len(names),
        "sampled": len(sample),
        "complete_samples": len(totals),
        "mean_bytes_per_patch": round(mean) if mean else None,
        "median_bytes_per_patch": sorted(totals)[len(totals) // 2] if totals else None,
        "estimated_total_gb": round(mean * len(names) / 1e9, 2) if mean else None,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("dataset")
    ap.add_argument("listing")
    ap.add_argument("base_url")
    ap.add_argument("out")
    ap.add_argument("--margin", type=float, default=8.0)
    ap.add_argument("--workers", type=int, default=64)
    ap.add_argument("--size-sample", type=int, default=0,
                    help="HEAD-sample this many patches touching absolute/relative points to estimate download cost")
    args = ap.parse_args()
    entries = patch_entries(Path(args.listing).read_text(errors="replace"))
    index = fetch_index(args.base_url, entries, workers=args.workers)
    rows = load_points(Path(args.dataset))
    report = {
        "entries": len(entries),
        "with_bbox": len(index["bbox"]),
        "without_bbox": len(index["no_bbox"]),
        "fetch_errors": len(index["errors"]),
        "error_examples": dict(list(index["errors"].items())[:5]),
        "reach": reach(rows, index["bbox"], margin=args.margin),
    }
    if args.size_sample:
        touching = patches_touching(rows, index["bbox"], margin=args.margin)
        report["download_cost_for_annotation_patches"] = size_sample(
            args.base_url, touching, args.size_sample)
    Path(args.out).write_text(json.dumps({"report": report, "index": index}) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
