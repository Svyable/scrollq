"""Deterministic sensitivity analysis for the v1 dead-slice penalty.

This module does not propose or apply a new scoring policy.  It makes one
property of the frozen v1 policy explicit: continuous metrics are averaged
over decoded chunks, while detected dead slices are summed.  A fixed anomaly
prevalence can therefore receive a larger penalty when more chunks are
sampled.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .score import SCORE_POLICY_VERSION, score_components, score_from_metrics


BASE_METRICS = {
    "nonzero_frac": 0.9,
    "grad_energy": 12.0,
    "dyn_range": 200.0,
    "sat_frac": 0.0,
}
FIXED_PREVALENCE_BUDGETS = (6, 12, 24, 48)
FIXED_HIT_BUDGETS = (1, 3, 6, 12, 24, 48)


def _row(*, decoded_chunks: int, dead_slices: int) -> dict[str, Any]:
    metrics = {**BASE_METRICS, "dead_slices": dead_slices}
    components = score_components(metrics)
    return {
        "decoded_chunks": decoded_chunks,
        "dead_slices": dead_slices,
        "dead_slice_prevalence_per_chunk": round(
            dead_slices / decoded_chunks, 6
        ),
        "dead_slice_penalty": components["pen_dead"],
        "score": score_from_metrics(metrics),
    }


def build_report() -> dict[str, Any]:
    """Return the complete network-free controlled analysis."""
    fixed_prevalence = [
        _row(decoded_chunks=budget, dead_slices=budget // 6)
        for budget in FIXED_PREVALENCE_BUDGETS
    ]
    fixed_hit = [
        _row(decoded_chunks=budget, dead_slices=1)
        for budget in FIXED_HIT_BUDGETS
    ]
    return {
        "schema_version": 1,
        "score_policy_version": SCORE_POLICY_VERSION,
        "scope": "synthetic sensitivity analysis; no corpus evidence",
        "baseline_metrics": BASE_METRICS,
        "dead_slice_policy": {
            "aggregation": "sum across decoded chunks",
            "points_per_detected_slice": 15.0,
            "penalty_cap": 30.0,
        },
        "controlled_cases": {
            "fixed_prevalence_one_slice_per_six_chunks": fixed_prevalence,
            "fixed_one_observed_slice": fixed_hit,
        },
        "finding": {
            "budget_sensitive": True,
            "reason": (
                "At fixed one-per-six prevalence, the v1 summed penalty rises "
                "from 15 to its 30-point cap as the decoded budget grows. A "
                "single observed hit also remains a 15-point penalty as clean "
                "chunks are added, because v1 does not normalize by coverage."
            ),
            "policy_change": "none",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Write the deterministic v1 dead-slice sensitivity report"
    )
    parser.add_argument("--out", required=True, help="output JSON path")
    args = parser.parse_args()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(build_report(), indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
