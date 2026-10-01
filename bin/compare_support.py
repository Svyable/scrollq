"""Agreement between native scroliq-support and imported external surveys.

Usage: python bin/compare_support.py <support_native.json> <support_external.json> [out.json]

Compares only scrolls where BOTH sources are usable exact-scan evidence.
Reports per-scroll values, whether the external value falls inside the native
bootstrap 95% interval, mean/max |difference| and Spearman rho.
"""
import json
import sys

import numpy as np

sys.path.insert(0, "bin")
from subset_stability import avg_rank  # noqa: E402


def usable(doc):
    return {r["scroll"]: r for r in doc["rows"] if r.get("usable_for_qualification")}


def main():
    native, external = (usable(json.load(open(p))) for p in sys.argv[1:3])
    both = sorted(set(native) & set(external))
    rows = []
    for s in both:
        n, e = native[s], external[s]
        lo, hi = n["support_ci95"]
        rows.append({
            "scroll": s,
            "native": n["sampled_support_frac"],
            "native_ci95": [lo, hi],
            "external": round(e["sampled_support_frac"], 4),
            "diff": round(n["sampled_support_frac"] - e["sampled_support_frac"], 4),
            "external_in_native_ci": lo <= e["sampled_support_frac"] <= hi,
        })
    d = np.array([abs(r["diff"]) for r in rows])
    rho = float(np.corrcoef(avg_rank([r["native"] for r in rows]),
                            avg_rank([r["external"] for r in rows]))[0, 1])
    out = {
        "n_compared": len(rows),
        "external_inside_native_ci95": sum(r["external_in_native_ci"] for r in rows),
        "mean_abs_diff": round(float(d.mean()), 4),
        "max_abs_diff": round(float(d.max()), 4),
        "spearman_rho": round(rho, 4),
        "native_only": sorted(set(native) - set(external)),
        "external_only": sorted(set(external) - set(native)),
        "rows": rows,
    }
    if len(sys.argv) > 3:
        open(sys.argv[3], "w").write(json.dumps(out, indent=1) + "\n")
    for r in rows:
        flag = "in" if r["external_in_native_ci"] else "OUT"
        print(f"{r['scroll']:11} native={r['native']:.3f} {r['native_ci95']} "
              f"external={r['external']:.3f} diff={r['diff']:+.3f} {flag}")
    print({k: v for k, v in out.items() if k != "rows"})


if __name__ == "__main__":
    main()
