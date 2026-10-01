"""Pre-registration inputs for the O5 stability test, from published data only.

Reads the frozen 2026-09-30 n24-dense campaign and the 2026-10-01
truly-disjoint resample; reads no new scan data. Writes the numbers the
protocol (docs/stability-v2-protocol.md) cites as motivation:

- the iid variance-components prediction of resample reliability at 24
  chunks versus the observed disjoint correlation;
- the systematic score shift between the two disjoint runs and the spread of
  their per-volume differences versus the iid expectation;
- how many x planes the first 12 grid-order candidates span.

    python bin/stability_v2_prereg.py OUT.json
"""

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from scrollq.score import _candidates  # noqa: E402
from scrollq.stability_protocol import spearman  # noqa: E402

CAMPAIGN = ROOT / "artifacts/2026-09-30-scrollq-n24-dense/volumes.json"
DISJOINT = ROOT / "artifacts/2026-10-01-truly-disjoint/stability-truly-disjoint.json"


def _pearson(a, b):
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    return cov / math.sqrt(sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b))


def analyse() -> dict:
    vols = [v for v in json.loads(CAMPAIGN.read_text()) if v.get("ok")]
    scores = [v["score"] for v in vols]
    var_total = sum((s - sum(scores) / len(scores)) ** 2 for s in scores) / (len(scores) - 1)
    within = [v["score_std"] ** 2 for v in vols]
    noise_mean_n = sum(w / v["sampling"]["decoded"] for w, v in zip(within, vols)) / len(vols)
    between = var_total - noise_mean_n
    mean_within = sum(within) / len(within)

    def reliability(n):
        return between / (between + mean_within / n)

    dj = json.loads(DISJOINT.read_text())
    roots = sorted(set(dj["run0"]) & set(dj["run1"]))
    a = [dj["run0"][r] for r in roots]
    b = [dj["run1"][r] for r in roots]
    diff = [y - x for x, y in zip(a, b)]
    mean_diff = sum(diff) / len(diff)
    sd_diff = math.sqrt(sum((d - mean_diff) ** 2 for d in diff) / (len(diff) - 1))

    grid12 = _candidates((40, 40, 40), 5)[:12]
    bal12 = _candidates((40, 40, 40), 5, order="balanced")[:12]
    return {
        "inputs": {"campaign": str(CAMPAIGN.relative_to(ROOT)), "disjoint": str(DISJOINT.relative_to(ROOT))},
        "variance_components_n24_campaign": {
            "volumes": len(vols),
            "between_volume_variance": round(between, 2),
            "mean_within_volume_chunk_variance": round(mean_within, 2),
            "iid_predicted_reliability": {str(n): round(reliability(n), 3) for n in (24, 48, 96)},
        },
        "observed_truly_disjoint_n24": {
            "volumes": len(roots),
            "pearson": round(_pearson(a, b), 3),
            "spearman": round(spearman(a, b), 3),
            "mean_shift_run1_minus_run0": round(mean_diff, 2),
            "sd_of_differences": round(sd_diff, 2),
            "iid_expected_sd_of_differences": round(math.sqrt(2 * mean_within / 24), 2),
        },
        "first_12_candidates_x_planes_on_a_40_cube_spread_5": {
            "grid_order": len({c[0] for c in grid12}),
            "balanced_order": len({c[0] for c in bal12}),
        },
    }


if __name__ == "__main__":
    result = analyse()
    out = Path(sys.argv[1])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
