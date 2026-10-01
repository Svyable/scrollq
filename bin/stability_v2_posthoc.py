"""Post-hoc analysis of the stability v2 run. NOT part of the pre-registered
decision (docs/stability-v2-protocol.md); it explains the verdict.

Reads artifacts/2026-10-stability-v2/stability-v2.json only.

    python bin/stability_v2_posthoc.py IN.json OUT.json
"""

import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from scrollq.stability_protocol import spearman  # noqa: E402


def _pearson(a, b):
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(
        sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b))


def analyse(data: dict) -> dict:
    out = {"label": "post-hoc, descriptive; the pre-registered verdict is in summary.json", "arms": {}}
    for n, arm in data["arms"].items():
        ok = arm["eligible_roots"]
        A, B = data["runs"][n]["part0"], data["runs"][n]["part1"]
        a = [A[r]["score"] for r in ok]
        b = [B[r]["score"] for r in ok]
        within = [(A[r]["score_std"] ** 2 + B[r]["score_std"] ** 2) / 2 for r in ok]
        pooled = [(x + y) / 2 for x, y in zip(a, b)]
        mp = sum(pooled) / len(pooled)
        xs = sorted(len({p["shard_coord"][0] for p in A[r]["sample_provenance"]}) for r in ok)
        out["arms"][n] = {
            "eligible": len(ok),
            "spearman": round(spearman(a, b), 3),
            "pearson": round(_pearson(a, b), 3),
            "sd_of_differences": round(arm["sd_shift"], 2),
            "iid_expected_sd_of_differences": round(math.sqrt(2 * sum(within) / len(within) / int(n)), 2),
            "between_volume_sd_of_pooled_scores": round(math.sqrt(sum((p - mp) ** 2 for p in pooled) / (len(pooled) - 1)), 2),
            "median_x_planes_per_run_a": xs[len(xs) // 2],
        }
    ok48 = data["arms"]["48"]["eligible_roots"]
    A, B = data["runs"]["24"]["part0"], data["runs"]["24"]["part1"]
    pairs = [(A[r]["score"], B[r]["score"]) for r in ok48
             if A[r].get("ok") and B[r].get("ok")
             and A[r]["sampling"]["decoded"] == 24 and B[r]["sampling"]["decoded"] == 24]
    out["n24_on_the_48_chunk_eligible_set"] = {
        "volumes": len(pairs),
        "spearman": round(spearman([p[0] for p in pairs], [p[1] for p in pairs]), 3),
    }
    sept = Path(__file__).resolve().parents[1] / "artifacts/2026-09-30-scrollq-n24-dense/volumes.json"
    published = {v["root"]: v["score"] for v in json.loads(sept.read_text()) if v.get("ok")}
    common = [r for r in ok48 if r in published]
    diffs = sorted(((data["pooled_scores"][r] - published[r], r) for r in common), reverse=True)
    out["september_grid_scores_vs_v2_pooled"] = {
        "volumes": len(common),
        "pearson": round(_pearson([published[r] for r in common], [data["pooled_scores"][r] for r in common]), 3),
        "spearman": round(spearman([published[r] for r in common], [data["pooled_scores"][r] for r in common]), 3),
        "mean_abs_diff": round(sum(abs(d) for d, _ in diffs) / len(diffs), 2),
        "largest_rises": [{"root": r, "v2_minus_september": round(d, 1)} for d, r in diffs[:5]],
        "largest_drops": [{"root": r, "v2_minus_september": round(d, 1)} for d, r in diffs[-5:][::-1]],
    }
    return out


if __name__ == "__main__":
    result = analyse(json.loads(Path(sys.argv[1]).read_text()))
    Path(sys.argv[2]).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
