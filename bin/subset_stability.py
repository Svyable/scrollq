"""Rank stability of one qualifier report against another (same targets).

Usage: python bin/subset_stability.py <targets_run0.json> <targets_run1.json> [out.json]

Spearman rho uses average ranks for ties. Also reports mean/max |delta| and
top-5 overlap, plus each run's Pareto frontier.
"""
import json
import sys

import numpy as np


def avg_rank(x):
    x = np.asarray(x, float)
    r = np.empty(len(x))
    r[x.argsort()] = np.arange(1, len(x) + 1)
    for v in np.unique(x):
        r[x == v] = r[x == v].mean()
    return r


def main():
    a_doc, b_doc = (json.load(open(p)) for p in sys.argv[1:3])
    a = {t["scroll"]: t["quality_score"] for t in a_doc["targets"]}
    b = {t["scroll"]: t["quality_score"] for t in b_doc["targets"]}
    keys = sorted(k for k in a if a[k] is not None and b.get(k) is not None)
    ra = avg_rank([a[k] for k in keys])
    rb = avg_rank([b[k] for k in keys])
    d = np.abs(np.array([a[k] for k in keys]) - np.array([b[k] for k in keys]))
    top = lambda m: set(sorted(keys, key=lambda k: -m[k])[:5])
    out = {
        "n": len(keys),
        "spearman_rho": round(float(np.corrcoef(ra, rb)[0, 1]), 4),
        "mean_abs_diff": round(float(d.mean()), 2),
        "max_abs_diff": round(float(d.max()), 1),
        "top5_overlap": len(top(a) & top(b)),
        "frontier_a": a_doc["frontier"],
        "frontier_b": b_doc["frontier"],
        "frontier_both": sorted(set(a_doc["frontier"]) & set(b_doc["frontier"])),
        "per_scroll": {k: [a[k], b[k]] for k in keys},
    }
    text = json.dumps(out, indent=1)
    if len(sys.argv) > 3:
        open(sys.argv[3], "w").write(text + "\n")
    print(text[: text.index('"per_scroll"')])


if __name__ == "__main__":
    main()
