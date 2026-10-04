#!/usr/bin/env python3
"""Which PHercParis4 CT volumes can the public fibers even live in? (goal O9)

The public spiral dataset declares no CT volume (no README/metadata; fiber
manifests name only local ``.volpkg`` paths). This script derives the one fact
that can be checked: the bounding box of every census fiber's line and control
points (VC3D xyz, level-0 voxels) against each public PHercParis4 level-0 shape
(Zarr ``[z, y, x]``). A volume whose shape cannot contain every point is ruled
out. Compatibility of a single volume is **not** a binding: a scan of the same
scroll at the same voxel size could share the frame.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
CENSUS = ROOT / "artifacts/2026-10-04-fiber-corpus-census/summary.json"
BUCKET = "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com"
INDEX = ROOT / "artifacts/2026-10-01-bucket-index/metadata.min.json.gz"
UA = {"User-Agent": "scrollq-paris4-fiber-binding/1"}


def _get(url: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
        return r.read()


def candidate_volumes() -> list[str]:
    import gzip
    import re
    text = gzip.open(INDEX, "rt").read()
    return sorted(set(re.findall(r"PHercParis4/volumes/[^\"/]+\.zarr", text)))


def level0_shape(volume: str) -> list[int] | None:
    for suffix, key in ((".zarray", "shape"), ("zarr.json", "shape")):
        try:
            meta = json.loads(_get(f"{BUCKET}/{volume}/0/{suffix}"))
            return [int(v) for v in meta[key]]
        except Exception:
            continue
    return None


def compatible(bbox_min: list[float], bbox_max: list[float], shape_zyx: list[int]) -> bool:
    z, y, x = shape_zyx
    return all(v >= 0 for v in bbox_min) and bbox_max[0] < x and bbox_max[1] < y and bbox_max[2] < z


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    census = json.loads(CENSUS.read_text())
    lo = np.full(3, np.inf)
    hi = np.full(3, -np.inf)
    errors = []
    for row in census["rows"]:
        try:
            payload = _get(row["source_url"] + "?download=true")
        except Exception as exc:
            errors.append(f"{row['file']}: {exc}")
            continue
        if hashlib.sha256(payload).hexdigest() != row["sha256"]:
            errors.append(f"{row['file']}: hash mismatch")
            continue
        obj = json.loads(payload)
        pts = np.asarray(obj["line_points"] + [c["position"] for c in obj["control_points"]], float)
        lo = np.minimum(lo, pts.min(axis=0))
        hi = np.maximum(hi, pts.max(axis=0))
    volumes = []
    for v in candidate_volumes():
        shape = level0_shape(v)
        volumes.append({
            "volume": v,
            "level0_shape_zyx": shape,
            "compatible": None if shape is None or errors else compatible(lo.tolist(), hi.tolist(), shape),
        })
    ok = [v["volume"] for v in volumes if v["compatible"]]
    unknown = [v["volume"] for v in volumes if v["compatible"] is None]
    if errors:
        verdict = "RUN FAILED"
    elif len(ok) == 1 and not unknown:
        verdict = "ONE COMPATIBLE"
    elif not ok and not unknown:
        verdict = "NONE COMPATIBLE"
    else:
        verdict = "AMBIGUOUS"
    result = {
        "census_manifest_sha256": census["manifest_sha256"],
        "fibers": len(census["rows"]),
        "bbox_xyz_min": lo.tolist(),
        "bbox_xyz_max": hi.tolist(),
        "volumes": volumes,
        "compatible": ok,
        "shape_unreadable": unknown,
        "verdict": verdict,
        "errors": errors,
        "declared_binding": "none: dataset has no README/metadata; fiber manifests name local .volpkg paths only",
        "limitation": "Range compatibility rules volumes out; it never establishes a binding.",
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if verdict != "RUN FAILED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
