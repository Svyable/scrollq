"""Pre-registered scan-score stability test, version 2 (October goal O5).

Protocol: docs/stability-v2-protocol.md. Everything a verdict depends on is
fixed here before any run is made; ``decide()`` computes the verdict, not a
person. The commit adding this module is the pre-registration timestamp.

Design. The published campaigns consume shard candidates in x-major order,
so a 24-chunk sample can come from one or two x-slabs, and the 2026-10-01
truly-disjoint resample's second run drew from neighbouring positions of the
same slabs. Version 2 orders the same lattice so every prefix fills the
volume (``score._candidates(order="balanced")``) and gives run A and run B
interleaved, shard-disjoint halves of it (``part=(2, 0)`` and ``(2, 1)``).
"""

from __future__ import annotations

from typing import Any

from .score import score_from_metrics

PROTOCOL = "docs/stability-v2-protocol.md"
SPREAD = 7
ORDER = "balanced"
PARTS = ((2, 0), (2, 1))
N_PRIMARY = 48
N_SECONDARY = 24
GATE_RHO = 0.85
MIN_ELIGIBLE = 48
METRIC_KEYS = ("nonzero_frac", "std", "dyn_range", "sat_frac", "grad_energy")

VERDICTS = ("PASS", "FAIL", "INSUFFICIENT")


def preregistered_constants() -> dict[str, Any]:
    return {
        "protocol": PROTOCOL,
        "spread": SPREAD,
        "order": ORDER,
        "parts": [list(p) for p in PARTS],
        "n_primary": N_PRIMARY,
        "n_secondary": N_SECONDARY,
        "gate_rho": GATE_RHO,
        "min_eligible": MIN_ELIGIBLE,
    }


def _ranks(values: list[float]) -> list[float]:
    """1-based ranks, ties get their average rank."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for t in range(i, j + 1):
            ranks[order[t]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def spearman(a: list[float], b: list[float]) -> float | None:
    if len(a) != len(b) or len(a) < 3:
        return None
    ra, rb = _ranks(a), _ranks(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va = sum((x - ma) ** 2 for x in ra)
    vb = sum((y - mb) ** 2 for y in rb)
    if va == 0 or vb == 0:
        return None
    return cov / (va * vb) ** 0.5


def eligible(run: dict | None, n: int) -> bool:
    """A run counts only if it scored and decoded exactly the requested n."""
    return bool(
        run
        and run.get("ok")
        and run.get("sampling", {}).get("decoded") == n
        and run.get("sampling", {}).get("requested") == n
    )


def pooled_score(run_a: dict, run_b: dict) -> float:
    """Score of the 2n-chunk union: metrics are per-chunk means, and both runs
    hold n chunks, so the union's means are the average of the two."""
    metrics = {k: (run_a["metrics"][k] + run_b["metrics"][k]) / 2 for k in METRIC_KEYS}
    metrics["dead_slices"] = run_a["metrics"]["dead_slices"] + run_b["metrics"]["dead_slices"]
    return round(score_from_metrics(metrics), 1)


def rank_bands(rows: dict[str, dict[str, float]]) -> dict[str, dict[str, int]]:
    """Per volume, the lowest and highest rank (1 = best) it takes across run
    A, run B and the pooled score. This replaces a single rank if the gate
    fails."""
    bands: dict[str, dict[str, int]] = {root: {} for root in rows}
    for column in ("a", "b", "pooled"):
        ordered = sorted(rows, key=lambda r: (-rows[r][column], r))
        for rank, root in enumerate(ordered, start=1):
            band = bands[root]
            band["best"] = min(band.get("best", rank), rank)
            band["worst"] = max(band.get("worst", rank), rank)
    return bands


def arm_summary(runs_a: dict[str, dict], runs_b: dict[str, dict], n: int) -> dict[str, Any]:
    roots = sorted(set(runs_a) | set(runs_b))
    ok = [r for r in roots if eligible(runs_a.get(r), n) and eligible(runs_b.get(r), n)]
    excluded = {
        r: {
            "a": (runs_a.get(r) or {}).get("sampling", {}).get("decoded"),
            "b": (runs_b.get(r) or {}).get("sampling", {}).get("decoded"),
            "a_error": (runs_a.get(r) or {}).get("error"),
            "b_error": (runs_b.get(r) or {}).get("error"),
        }
        for r in roots
        if r not in ok
    }
    a = [runs_a[r]["score"] for r in ok]
    b = [runs_b[r]["score"] for r in ok]
    shift = [y - x for x, y in zip(a, b)]
    top_a = set(sorted(ok, key=lambda r: (-runs_a[r]["score"], r))[:10])
    top_b = set(sorted(ok, key=lambda r: (-runs_b[r]["score"], r))[:10])
    mean_shift = sum(shift) / len(shift) if shift else None
    return {
        "n_chunks": n,
        "volumes": len(roots),
        "eligible": len(ok),
        "excluded": excluded,
        "spearman_rho": spearman(a, b),
        "mean_abs_diff": sum(abs(s) for s in shift) / len(shift) if shift else None,
        "mean_shift_b_minus_a": mean_shift,
        "sd_shift": (
            (sum((s - mean_shift) ** 2 for s in shift) / (len(shift) - 1)) ** 0.5
            if len(shift) > 1 else None
        ),
        "top10_overlap": len(top_a & top_b) if len(ok) >= 10 else None,
        "eligible_roots": ok,
    }


def decide(primary: dict[str, Any]) -> dict[str, Any]:
    """The verdict, from the primary arm only.

    INSUFFICIENT  fewer than MIN_ELIGIBLE volumes supplied N_PRIMARY chunks to
                  both runs, or rho is undefined
    PASS          rho >= GATE_RHO on the eligible volumes
    FAIL          otherwise
    """
    rho = primary.get("spearman_rho")
    if primary.get("n_chunks") != N_PRIMARY:
        raise ValueError("decide() takes the primary arm")
    if primary.get("eligible", 0) < MIN_ELIGIBLE or rho is None:
        verdict = "INSUFFICIENT"
    elif rho >= GATE_RHO:
        verdict = "PASS"
    else:
        verdict = "FAIL"
    return {
        "verdict": verdict,
        "rho": rho,
        "eligible": primary.get("eligible"),
        "gate_rho": GATE_RHO,
        "min_eligible": MIN_ELIGIBLE,
        "consequence": (
            "publish the ranking with the stability gate passed"
            if verdict == "PASS"
            else "replace the leaderboard rank column with rank bands (best..worst across run A, run B and pooled)"
        ),
    }
