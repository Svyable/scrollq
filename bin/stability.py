"""Resampling stability for ScrolIQ scan-health scores.

Scores every volume in volumes.txt twice with different deterministic
samples (rotate=0 vs rotate=13 by default — cyclically shifted
shard-candidate order) and reports:
  - Spearman rank correlation between the two runs
  - mean absolute score difference
  - top-10 overlap
  - per-volume decoded-chunk identity overlap (provenance): whether the
    two runs actually read disjoint chunks, not just disjoint candidate
    order. The sampling loop scans all candidates until N chunks decode,
    so on sparse volumes both rotations can re-read the same present
    shards — disjoint candidate ORDER does not imply disjoint chunks READ.

Quality gate (AGENTS.md): rho >= 0.85, small mean |d|, high top-10 overlap.
"""
import json
import math
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, "src")
from scrollq.score import score_volume

BASE = "https://dl.ash2txt.org"
SAMPLES = int(sys.argv[2]) if len(sys.argv) > 2 else 4
ROTATE_B = int(sys.argv[3]) if len(sys.argv) > 3 else 13
SPREAD = int(sys.argv[4]) if len(sys.argv) > 4 else 3
WORKERS = 8


def load_volumes(path="volumes.txt"):
    with open(path) as fh:
        return [ln.strip() for ln in fh if ln.strip()]


def run(roots, rotate):
    def one(root):
        try:
            return score_volume(BASE, root, samples=SAMPLES, rotate=rotate,
                                spread=SPREAD)
        except Exception as exc:  # noqa: BLE001 - keep the campaign alive
            return {"root": root, "ok": False, "error": str(exc)}

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        return list(ex.map(one, roots))


def spearman(a, b):
    n = len(a)
    ra = {v: i for i, v in enumerate(sorted(range(n), key=lambda i: a[i]))}
    rb = {v: i for i, v in enumerate(sorted(range(n), key=lambda i: b[i]))}
    d2 = sum((ra[i] - rb[i]) ** 2 for i in range(n))
    return 1 - 6 * d2 / (n * (n * n - 1))


def main():
    roots = load_volumes()
    rotate_b = ROTATE_B
    r0 = run(roots, rotate=0)
    r1 = run(roots, rotate=rotate_b)
    s0 = {r["root"]: r["score"] for r in r0 if r.get("ok")}
    s1 = {r["root"]: r["score"] for r in r1 if r.get("ok")}
    common = sorted(set(s0) & set(s1))
    a = [s0[r] for r in common]
    b = [s1[r] for r in common]
    rho = spearman(a, b)
    mad = sum(abs(x - y) for x, y in zip(a, b)) / len(a)
    top0 = {r for r in sorted(common, key=lambda r: s0[r], reverse=True)[:10]}
    top1 = {r for r in sorted(common, key=lambda r: s1[r], reverse=True)[:10]}
    overlap = len(top0 & top1)

    # Provenance: per-volume decoded-chunk identity overlap. For each
    # volume, compare the set of chunk identities actually decoded in
    # run0 vs run1. Zero intersection = genuinely disjoint samples.
    prov0 = {r["root"]: {p["identity"] for p in r.get("sample_provenance", [])}
             for r in r0 if r.get("ok")}
    prov1 = {r["root"]: {p["identity"] for p in r.get("sample_provenance", [])}
             for r in r1 if r.get("ok")}
    identity_overlaps = {}
    for r in common:
        i0, i1 = prov0.get(r, set()), prov1.get(r, set())
        inter = len(i0 & i1)
        union = len(i0 | i1)
        identity_overlaps[r] = {
            "intersection": inter,
            "union": union,
            "jaccard": round(inter / union, 3) if union else 0.0,
            "n0": len(i0), "n1": len(i1),
        }
    n_disjoint = sum(1 for v in identity_overlaps.values()
                     if v["intersection"] == 0)
    mean_jaccard = (sum(v["jaccard"] for v in identity_overlaps.values())
                    / len(identity_overlaps)) if identity_overlaps else 0.0

    out = {
        "n_volumes": len(common),
        "samples": SAMPLES,
        "spread": SPREAD,
        "rotate_a": 0,
        "rotate_b": rotate_b,
        "spearman_rho": round(rho, 4),
        "mean_abs_diff": round(mad, 3),
        "top10_overlap": overlap,
        "gate": {"rho_min": 0.85},
        "gate_pass": bool(rho >= 0.85),
        "provenance": {
            "n_truly_disjoint": n_disjoint,
            "n_volumes": len(identity_overlaps),
            "mean_jaccard": round(mean_jaccard, 3),
            "per_volume": identity_overlaps,
        },
        "run0": {r["root"]: round(r["score"], 2) for r in r0 if r.get("ok")},
        "run1": {r["root"]: round(r["score"], 2) for r in r1 if r.get("ok")},
        "errors": [r["root"] for r in r0 if not r.get("ok")],
    }
    print(json.dumps({k: v for k, v in out.items()
                      if k not in ("run0", "run1")}, indent=1))
    return out


if __name__ == "__main__":
    result = main()
    with open(sys.argv[1] if len(sys.argv) > 1 else
              "artifacts/2026-09-30-resampling-stability/stability.json",
              "w") as fh:
        json.dump(result, fh, indent=1)
