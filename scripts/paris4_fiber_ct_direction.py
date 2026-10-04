#!/usr/bin/env python3
"""Pre-registered test: do public PHercParis4 fibers run *within* the papyrus
sheet seen in CT? (November N4c, pulled into October.)

Frozen design: ``artifacts/2026-10-04-paris4-fiber-ct-direction-prereg/spec.json``
(SHA-256 pinned below). The volume is the one the 2026-10-04 CT support test
found the fibers sitting on; that support is evidence for, not a declaration of,
the binding.

At each sampled fiber point the local sheet normal ``n`` is the dominant
eigenvector of a Gaussian-weighted CT structure tensor; the statistic is
``a = |t . n|`` for the fiber tangent ``t``. A fiber lying in the sheet has small
``a``; a random direction has ``a`` uniform on [0, 1].
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
from typing import Any

import numpy as np
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "artifacts/2026-10-04-paris4-fiber-ct-direction-prereg/spec.json"
SPEC_SHA256 = "3690f5ccfeb72ea56b3fb14ffd55c450269f7c8347a515864fc8f6b916a159da"
CENSUS = ROOT / "artifacts/2026-10-04-fiber-corpus-census/summary.json"
UA = {"User-Agent": "scrollq-paris4-fiber-ct-direction/1"}


# ------------------------------------------------------------------ geometry

def sample_indices(n: int, k: int, half: int) -> list[int]:
    if n < 2 * half + 1:
        return []
    return sorted(set(np.linspace(half, n - 1 - half, k).round().astype(int).tolist()))


def tangent(line: np.ndarray, i: int, half: int) -> np.ndarray:
    d = line[i + half] - line[i - half]
    norm = np.linalg.norm(d)
    return d / norm if norm > 0 else d


def sheet_normal(cube: np.ndarray, grad_sigma: float, window_sigma: float) -> tuple[np.ndarray, float]:
    """Dominant structure-tensor eigenvector at the cube centre, in (x, y, z)."""
    c = ndimage.gaussian_filter(cube.astype(np.float64), grad_sigma)
    gz, gy, gx = np.gradient(c)
    w = np.zeros_like(c)
    w[tuple(s // 2 for s in c.shape)] = 1.0
    w = ndimage.gaussian_filter(w, window_sigma)
    comps = (gx, gy, gz)
    t = np.array([[float((w * a * b).sum()) for b in comps] for a in comps])
    vals, vecs = np.linalg.eigh(t)
    l1, l2 = vals[2], vals[1]
    coherence = float((l1 - l2) / (l1 + l2)) if (l1 + l2) > 0 else 0.0
    return vecs[:, 2], coherence


def random_units(n: int, rng: np.random.Generator) -> np.ndarray:
    v = rng.normal(size=(n, 3))
    return v / np.linalg.norm(v, axis=1, keepdims=True)


# ---------------------------------------------------------------- statistics

def cluster_ci(per_fiber: list[np.ndarray], stat, reps: int, seed: int) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    n = len(per_fiber)
    vals = []
    for _ in range(reps):
        pick = rng.integers(0, n, n)
        vals.append(stat(np.concatenate([per_fiber[i] for i in pick])))
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def decide(fiber: list[np.ndarray], rand: list[np.ndarray], swapped: list[np.ndarray],
           swapped_rand: list[np.ndarray], spec: dict[str, Any]) -> dict[str, Any]:
    d = spec["decision"]
    paired = [np.stack([r, f], axis=1) for r, f in zip(rand, fiber)]
    paired_x = [np.stack([r, f], axis=1) for r, f in zip(swapped_rand, swapped)]

    def gap(rows):
        return float(rows[:, 0].mean() - rows[:, 1].mean())

    out = {
        "mean_abs_dot_fiber": float(np.concatenate(fiber).mean()),
        "mean_abs_dot_random": float(np.concatenate(rand).mean()),
        "median_abs_dot_fiber": float(np.median(np.concatenate(fiber))),
        "mean_abs_dot_swapped": float(np.concatenate(swapped).mean()) if swapped else None,
        "D": gap(np.concatenate(paired)),
        "D_ci95": cluster_ci(paired, gap, d["bootstrap_reps"], d["seed"]),
        "D_swapped": gap(np.concatenate(paired_x)) if paired_x else None,
        "D_swapped_ci95": cluster_ci(paired_x, gap, d["bootstrap_reps"], d["seed"] + 1) if paired_x else None,
    }
    swapped_supported = bool(paired_x) and out["D_swapped_ci95"][0] > d["min_D"]
    out["control_wrong_frame_supported"] = swapped_supported
    out["verdict"] = ("CONTROL FAILURE" if swapped_supported else
                      "SUPPORTED" if out["D_ci95"][0] > d["min_D"] else "NOT SUPPORTED")
    return out


# ------------------------------------------------------------------- reading

class ChunkCache:
    def __init__(self, base: str, level: int, chunks, shape):
        self.base, self.level, self.chunks, self.shape = base, level, tuple(chunks), tuple(shape)
        self.cache: dict[tuple[int, int, int], np.ndarray | None] = {}
        self.missing = 0
        self.errors: list[str] = []

    def fetch(self, key: tuple[int, int, int]) -> None:
        if key in self.cache:
            return
        url = f"{self.base}/{self.level}/{key[0]}/{key[1]}/{key[2]}"
        for _ in range(4):
            try:
                raw = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120).read()
                self.cache[key] = np.frombuffer(raw, np.uint8).reshape(self.chunks)
                return
            except urllib.error.HTTPError as exc:
                if exc.code in (403, 404):
                    self.missing += 1
                    self.cache[key] = None
                    return
                err = exc
            except Exception as exc:
                err = exc
        self.errors.append(f"{url}: {err}")
        self.cache[key] = None

    def keys_for(self, lo, hi):
        return [(z, y, x)
                for z in range(lo[0] // self.chunks[0], (hi[0] - 1) // self.chunks[0] + 1)
                for y in range(lo[1] // self.chunks[1], (hi[1] - 1) // self.chunks[1] + 1)
                for x in range(lo[2] // self.chunks[2], (hi[2] - 1) // self.chunks[2] + 1)]

    def cube(self, center_zyx, r: int) -> np.ndarray | None:
        lo = [c - r for c in center_zyx]
        hi = [c + r + 1 for c in center_zyx]
        if any(a < 0 for a in lo) or any(b > s for b, s in zip(hi, self.shape)):
            return None
        out = np.zeros([2 * r + 1] * 3, np.uint8)
        for key in self.keys_for(lo, hi):
            data = self.cache.get(key)
            if data is None:
                continue
            c0 = [k * n for k, n in zip(key, self.chunks)]
            src = tuple(slice(max(lo[d], c0[d]) - c0[d], min(hi[d], c0[d] + self.chunks[d]) - c0[d]) for d in range(3))
            dst = tuple(slice(max(lo[d], c0[d]) - lo[d], min(hi[d], c0[d] + self.chunks[d]) - lo[d]) for d in range(3))
            out[dst] = data[src]
        return out


def run(out_dir: Path, workers: int) -> int:
    raw = SPEC_PATH.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    if sha != SPEC_SHA256:
        print(f"spec hash {sha} != frozen {SPEC_SHA256}", file=sys.stderr)
        return 3
    spec = json.loads(raw)
    census = json.loads(CENSUS.read_text())
    if census["manifest_sha256"] != spec["inputs"]["census_manifest_sha256"]:
        print("census manifest differs", file=sys.stderr)
        return 3
    vol, smp, st = spec["volume"], spec["sampling"], spec["structure_tensor"]
    base = f"{vol['bucket_https']}/{vol['root']}"
    attrs = json.loads(urllib.request.urlopen(urllib.request.Request(f"{base}/.zattrs", headers=UA)).read())
    scale = attrs["multiscales"][0]["datasets"][vol["level"]]["coordinateTransformations"][0]["scale"]
    if scale != [float(vol["scale"])] * 3:
        print("scale mismatch", file=sys.stderr)
        return 3
    za = json.loads(urllib.request.urlopen(urllib.request.Request(f"{base}/{vol['level']}/.zarray", headers=UA)).read())
    if za["compressor"] is not None or za["dtype"] != "|u1" or za["order"] != "C":
        print("unexpected layout", file=sys.stderr)
        return 3
    cache = ChunkCache(base, vol["level"], za["chunks"], za["shape"])
    rng = np.random.default_rng(smp["seed"])
    r = st["radius"]
    jobs = []  # (fiber_idx, group, center_zyx, tangent_xyz)
    errors = []
    for fi, row in enumerate(census["rows"]):
        try:
            payload = urllib.request.urlopen(urllib.request.Request(
                row["source_url"] + "?download=true", headers=UA), timeout=120).read()
        except Exception as exc:
            errors.append(f"{row['file']}: {exc}")
            continue
        if hashlib.sha256(payload).hexdigest() != row["sha256"]:
            errors.append(f"{row['file']}: hash mismatch")
            continue
        line = np.asarray(json.loads(payload)["line_points"], float)
        for i in sample_indices(len(line), smp["points_per_fiber"], smp["tangent_half_window"]):
            t = tangent(line, i, smp["tangent_half_window"])
            p = line[i]
            jobs.append((fi, "F", tuple(int(v) for v in np.floor(p / vol["scale"])[::-1]), t))
            ps = p[[1, 0, 2]]
            jobs.append((fi, "X", tuple(int(v) for v in np.floor(ps / vol["scale"])[::-1]), t[[1, 0, 2]]))
    if errors:
        result = {"verdict": "RUN FAILED", "errors": errors}
    else:
        def process(job):
            _, _, c, _ = job
            local = ChunkCache(cache.base, cache.level, cache.chunks, cache.shape)
            lo = [v - r for v in c]
            hi = [v + r + 1 for v in c]
            if any(a < 0 for a in lo) or any(b > s_ for b, s_ in zip(hi, cache.shape)):
                return None, 0, []
            for key in local.keys_for(lo, hi):
                local.fetch(key)
            cube = local.cube(c, r)
            if cube is None or (cube == 0).mean() > st["max_zero_fraction"]:
                return None, local.missing, local.errors
            return sheet_normal(cube, st["grad_sigma"], st["window_sigma"]), local.missing, local.errors

        with ThreadPoolExecutor(max_workers=workers) as pool:
            outcomes = list(pool.map(process, jobs))
        groups: dict[str, list[list[float]]] = {g: [[] for _ in census["rows"]] for g in ("F", "R", "X", "XR")}
        coh: dict[str, list[float]] = {"F": [], "X": []}
        skipped = {"F": 0, "X": 0}
        for (fi, g, c, t), (nk, missing, errs) in zip(jobs, outcomes):
            cache.missing += missing
            cache.errors.extend(errs)
            if nk is None or nk[1] < st["min_coherence"]:
                skipped[g] += 1
                continue
            n, k = nk
            coh[g].append(k)
            groups[g][fi].append(abs(float(t @ n)))
            groups["R" if g == "F" else "XR"][fi].append(abs(float(random_units(1, rng)[0] @ n)))
        keep = [i for i in range(len(census["rows"])) if groups["F"][i]]
        keep_x = [i for i in range(len(census["rows"])) if groups["X"][i]]
        arr = lambda g, idx: [np.asarray(groups[g][i]) for i in idx]  # noqa: E731
        if cache.errors:
            result = {"verdict": "RUN FAILED", "errors": cache.errors[:50]}
        else:
            result = decide(arr("F", keep), arr("R", keep), arr("X", keep_x), arr("XR", keep_x), spec)
            result.update({
                "fibers_with_points": len(keep),
                "points": {"F": sum(len(groups["F"][i]) for i in keep),
                           "X": sum(len(groups["X"][i]) for i in keep_x)},
                "skipped": skipped,
                "median_coherence": {g: (float(np.median(v)) if v else None) for g, v in coh.items()},
                "per_fiber_mean_abs_dot": {census["rows"][i]["file"]: float(np.mean(groups["F"][i])) for i in keep},
            })
        result["reads"] = {"jobs": len(jobs), "missing_chunk_reads": cache.missing}
    result = {"spec_sha256": sha, "volume": vol["root"], **result}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "per_fiber_mean_abs_dot"}, indent=2))
    return 0 if result["verdict"] in ("SUPPORTED", "NOT SUPPORTED") else 2


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--workers", type=int, default=16)
    a = ap.parse_args(argv)
    return run(Path(a.out_dir), a.workers)


if __name__ == "__main__":
    raise SystemExit(main())
