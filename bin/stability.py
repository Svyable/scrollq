"""Resampling stability for ScrolIQ scan-health scores.

Scores every volume in volumes.txt twice with different deterministic
samples (rotate=0 vs rotate=13 by default — cyclically shifted
shard-candidate order; 13 gives fully disjoint candidate sets at 4 or 12
samples from the 27-spread) and reports:
  - Spearman rank correlation between the two runs
  - mean absolute score difference
  - top-10 overlap

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
WORKERS = 8


def load_volumes(path="volumes.txt"):
    with open(path) as fh:
        return [ln.strip() for ln in fh if ln.strip()]


def run(roots, rotate):
    def one(root):
        try:
            return score_volume(BASE, root, samples=SAMPLES, rotate=rotate)
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

    out = {
        "n_volumes": len(common),
        "samples": SAMPLES,
        "rotate_a": 0,
        "rotate_b": rotate_b,
        "spearman_rho": round(rho, 4),
        "mean_abs_diff": round(mad, 3),
        "top10_overlap": overlap,
        "gate": {"rho_min": 0.85},
        "gate_pass": bool(rho >= 0.85),
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
