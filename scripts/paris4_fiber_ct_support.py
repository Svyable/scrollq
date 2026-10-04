#!/usr/bin/env python3
"""Pre-registered CT support test for the public PHercParis4 fibers (goal O9).

Frozen design: ``artifacts/2026-10-04-paris4-fiber-ct-support-prereg/spec.json``
(SHA-256 pinned below). The candidate volume is the only public PHercParis4
volume whose shape can contain every census fiber point
(``artifacts/2026-10-04-paris4-fiber-binding/``). The dataset itself declares
no volume, so even SUPPORTED is evidence for, not a declaration of, a binding.

Groups, all read as single level-1 voxels by HTTP range request from the
uncompressed Zarr v2 store (a missing chunk is fill value 0, counted):

* F  -- K evenly spaced line points per fiber;
* S  -- the same points displaced by each frozen offset (positive control:
        support must drop when a fiber is moved off its traced position);
* R  -- K uniform random points in each fiber's own bounding box (background);
* X  -- the same points with x and y swapped (wrong-frame control).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "artifacts/2026-10-04-paris4-fiber-ct-support-prereg/spec.json"
SPEC_SHA256 = "e2b0f6ff41c333cf4f9f28bfc69c76f3d9b591c2584a8b294af677c49ee79e42"
CENSUS = ROOT / "artifacts/2026-10-04-fiber-corpus-census/summary.json"
UA = {"User-Agent": "scrollq-paris4-fiber-ct-support/1"}


# ------------------------------------------------------------------ sampling

def fiber_points(line: np.ndarray, k: int) -> np.ndarray:
    idx = np.unique(np.linspace(0, len(line) - 1, k).round().astype(int))
    return line[idx]


def random_points(line: np.ndarray, k: int, rng: np.random.Generator) -> np.ndarray:
    lo, hi = line.min(axis=0), line.max(axis=0)
    return lo + rng.random((k, 3)) * (hi - lo)


def to_level(xyz: np.ndarray, scale: int) -> np.ndarray:
    """VC3D xyz (level-0 voxels) -> integer level-n (z, y, x)."""
    lvl = np.floor(xyz / scale).astype(np.int64)
    return lvl[:, ::-1]


# --------------------------------------------------------------- statistics

def auc(a: np.ndarray, b: np.ndarray) -> float:
    """P(A > B) + 0.5 P(A = B), exact via ranks."""
    a = np.asarray(a, float)
    b = np.asarray(b, float)
    if not len(a) or not len(b):
        return float("nan")
    allv = np.concatenate([a, b])
    order = allv.argsort(kind="mergesort")
    ranks = np.empty(len(allv))
    sorted_v = allv[order]
    i = 0
    while i < len(sorted_v):
        j = i
        while j + 1 < len(sorted_v) and sorted_v[j + 1] == sorted_v[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2 + 1
        i = j + 1
    ra = ranks[: len(a)].sum()
    return float((ra - len(a) * (len(a) + 1) / 2) / (len(a) * len(b)))


def cluster_bootstrap(groups: dict[str, list[np.ndarray]],
                      stat: Callable[[dict[str, np.ndarray]], float],
                      reps: int, seed: int) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    n = len(next(iter(groups.values())))
    vals = []
    for _ in range(reps):
        pick = rng.integers(0, n, n)
        vals.append(stat({g: np.concatenate([v[i] for i in pick]) for g, v in groups.items()}))
    vals = np.asarray(vals)
    vals = vals[np.isfinite(vals)]
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def decide(groups: dict[str, list[np.ndarray]], spec: dict[str, Any]) -> dict[str, Any]:
    d = spec["decision"]
    pooled = {g: np.concatenate(v) for g, v in groups.items()}

    def auc_fr(p):
        return auc(p["F"], p["R"])

    def diff(p):
        return auc(p["F"], p["R"]) - auc(p["S"], p["R"])

    def auc_xr(p):
        return auc(p["X"], p["R"])

    out = {
        "auc_F_vs_R": auc_fr(pooled),
        "auc_S_vs_R": auc(pooled["S"], pooled["R"]),
        "auc_X_vs_R": auc_xr(pooled),
        "auc_F_vs_R_ci95": cluster_bootstrap(groups, auc_fr, d["bootstrap_reps"], d["seed"]),
        "specificity_F_minus_S_ci95": cluster_bootstrap(groups, diff, d["bootstrap_reps"], d["seed"] + 1),
        "auc_X_vs_R_ci95": cluster_bootstrap(groups, auc_xr, d["bootstrap_reps"], d["seed"] + 2),
        "zero_fraction": {g: float(np.mean(v == 0)) for g, v in pooled.items()},
    }
    swapped_supported = out["auc_X_vs_R_ci95"][0] > 0.5
    supported = out["auc_F_vs_R_ci95"][0] > 0.5 and out["specificity_F_minus_S_ci95"][0] > 0
    out["control_wrong_frame_supported"] = swapped_supported
    out["verdict"] = ("CONTROL FAILURE" if swapped_supported
                      else "SUPPORTED" if supported else "NOT SUPPORTED")
    return out


def per_fiber_flags(groups: dict[str, list[np.ndarray]]) -> dict[str, Any]:
    """A fiber is flagged when its own points are not brighter than its own background."""
    f = [auc(a, r) <= 0.5 for a, r in zip(groups["F"], groups["R"])]
    s = [auc(a, r) <= 0.5 for a, r in zip(groups["S"], groups["R"])]
    return {"flag_rate_fibers": float(np.mean(f)), "flag_rate_shifted": float(np.mean(s)),
            "flagged": [i for i, x in enumerate(f) if x]}


# ------------------------------------------------------------------- reading

class RangeReader:
    def __init__(self, base: str, level: int, chunks: tuple[int, int, int], shape: tuple[int, int, int]):
        self.base, self.level, self.chunks, self.shape = base, level, chunks, shape
        self.missing = self.out_of_bounds = 0
        self.errors: list[str] = []

    def voxel(self, zyx: tuple[int, int, int]) -> int:
        if any(c < 0 or c >= s for c, s in zip(zyx, self.shape)):
            self.out_of_bounds += 1
            return 0
        cz, cy, cx = (c // n for c, n in zip(zyx, self.chunks))
        oz, oy, ox = (c % n for c, n in zip(zyx, self.chunks))
        offset = (oz * self.chunks[1] + oy) * self.chunks[2] + ox
        url = f"{self.base}/{self.level}/{cz}/{cy}/{cx}"
        req = urllib.request.Request(url, headers={**UA, "Range": f"bytes={offset}-{offset}"})
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    body = r.read()
                    return body[0] if r.status == 206 else body[offset]
            except urllib.error.HTTPError as exc:
                if exc.code in (403, 404):
                    self.missing += 1
                    return 0  # absent chunk = fill value (masked background)
                err = exc
            except Exception as exc:  # retried network error
                err = exc
        self.errors.append(f"{url}@{offset}: {err}")
        return 0


def run(out_dir: Path, workers: int) -> int:
    raw = SPEC_PATH.read_bytes()
    spec_sha = hashlib.sha256(raw).hexdigest()
    if spec_sha != SPEC_SHA256:
        print(f"spec hash {spec_sha} != frozen {SPEC_SHA256}", file=sys.stderr)
        return 3
    spec = json.loads(raw)
    census = json.loads(CENSUS.read_text())
    if census["manifest_sha256"] != spec["inputs"]["census_manifest_sha256"]:
        print("census manifest differs from the frozen one", file=sys.stderr)
        return 3
    vol = spec["volume"]
    base = f"{vol['bucket_https']}/{vol['root']}"
    level = vol["level"]
    attrs = json.loads(urllib.request.urlopen(urllib.request.Request(f"{base}/.zattrs", headers=UA)).read())
    ds = attrs["multiscales"][0]["datasets"][level]
    scale = ds["coordinateTransformations"][0]["scale"]
    if scale != [float(vol["scale"])] * 3:
        print(f"level {level} scale {scale} != frozen {vol['scale']}", file=sys.stderr)
        return 3
    zarray = json.loads(urllib.request.urlopen(urllib.request.Request(f"{base}/{level}/.zarray", headers=UA)).read())
    if zarray["compressor"] is not None or zarray["dtype"] != "|u1" or zarray["order"] != "C":
        print("volume layout is not uncompressed C-order uint8", file=sys.stderr)
        return 3
    reader = RangeReader(base, level, tuple(zarray["chunks"]), tuple(zarray["shape"]))

    k = spec["sampling"]["points_per_fiber"]
    offsets = [np.asarray(o, float) for o in spec["sampling"]["shift_offsets_level0_xyz"]]
    rng = np.random.default_rng(spec["sampling"]["seed"])
    plan: dict[str, list[np.ndarray]] = {"F": [], "S": [], "R": [], "X": []}
    errors = []
    for row in census["rows"]:
        try:
            req = urllib.request.Request(row["source_url"] + "?download=true", headers=UA)
            payload = urllib.request.urlopen(req, timeout=120).read()
        except Exception as exc:
            errors.append(f"{row['file']}: {exc}")
            continue
        if hashlib.sha256(payload).hexdigest() != row["sha256"]:
            errors.append(f"{row['file']}: hash mismatch")
            continue
        line = np.asarray(json.loads(payload)["line_points"], float)
        f = fiber_points(line, k)
        plan["F"].append(f)
        plan["S"].append(np.concatenate([f + o for o in offsets]))
        plan["R"].append(random_points(line, len(f), rng))
        plan["X"].append(f[:, [1, 0, 2]])
    if errors:
        result = {"verdict": "RUN FAILED", "errors": errors}
    else:
        flat = [(g, i, to_level(p, int(vol["scale"]))) for g, arrs in plan.items() for i, p in enumerate(arrs)]
        jobs = [(g, i, tuple(int(c) for c in zyx)) for g, i, pts in flat for zyx in pts]
        with ThreadPoolExecutor(max_workers=workers) as pool:
            values = list(pool.map(lambda j: reader.voxel(j[2]), jobs))
        groups: dict[str, list[list[int]]] = {g: [[] for _ in plan[g]] for g in plan}
        for (g, i, _), v in zip(jobs, values):
            groups[g][i].append(v)
        arr = {g: [np.asarray(v, float) for v in lst] for g, lst in groups.items()}
        if reader.errors:
            result = {"verdict": "RUN FAILED", "errors": reader.errors[:50]}
        else:
            result = {**decide(arr, spec), "per_fiber": per_fiber_flags(arr),
                      "fibers": [r["file"] for r in census["rows"]],
                      "per_fiber_auc_F_vs_R": [auc(a, r) for a, r in zip(arr["F"], arr["R"])]}
        result["reads"] = {"voxels": len(jobs), "missing_chunk_reads": reader.missing,
                           "out_of_bounds": reader.out_of_bounds}
    result = {"spec_sha256": spec_sha, "volume": vol["root"], **result}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k not in ("fibers", "per_fiber_auc_F_vs_R")}, indent=2))
    return 0 if result["verdict"] in ("SUPPORTED", "NOT SUPPORTED") else 2


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--workers", type=int, default=32)
    a = ap.parse_args(argv)
    return run(Path(a.out_dir), a.workers)


if __name__ == "__main__":
    raise SystemExit(main())
