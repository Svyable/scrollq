#!/usr/bin/env python3
"""Pre-registered span-level test: are fiber gap candidates over-represented in
fallback-interpolated spans? (October stretch goal O7.)

Frozen design: ``artifacts/2026-10-04-fiber-span-test-prereg/spec.json``.
The spec's SHA-256 is pinned below; the run refuses to start if it changed.

Unit of analysis is the control-point span. Each span is ``fallback`` when its
``segment_to_next.interp_mode`` is anything other than ``trace`` and
``native`` otherwise. A span is gap-positive when it contains at least one
step longer than ``gap_factor`` x the fiber's median non-zero line step (the
same rule as ``scroliq-fiber``). Fibers are the resampling cluster.

The run also exports every gap candidate as a VC3D PointCollections file so
the fiber queue is reviewable in VC3D (goal O10).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "artifacts/2026-10-04-fiber-span-test-prereg/spec.json"
SPEC_SHA256 = "670f8091994eda73ad6b962e1fce6b925683e7d367c9ae07c3727bc241a57edf"
CENSUS_PATH = ROOT / "artifacts/2026-10-04-fiber-corpus-census/summary.json"
USER_AGENT = "scrollq-fiber-span-test/1"


# ----------------------------------------------------------------- geometry

def nearest_indices(line: np.ndarray, controls: np.ndarray) -> list[int]:
    return [int(np.argmin(np.sum((line - c) ** 2, axis=1))) for c in controls]


def span_table(
    line_points: list[list[float]],
    controls: list[list[float]],
    modes: list[str],
    *,
    gap_factor: float,
) -> dict[str, Any]:
    """Assign each gap step to a control span.

    ``modes[k]`` is the interpolation mode of the span from control k to k+1.
    Returns per-span rows plus the steps that fall outside every span.
    """
    if len(modes) != len(controls) - 1:
        raise ValueError("need exactly one mode per control span")
    line = np.asarray(line_points, dtype=np.float64)
    steps = np.linalg.norm(np.diff(line, axis=0), axis=1)
    positive = steps[steps > 0]
    if not positive.size:
        raise ValueError("line has no non-zero step")
    median = float(np.median(positive))
    gap_steps = np.flatnonzero(steps > gap_factor * median)

    idx = nearest_indices(line, np.asarray(controls, dtype=np.float64))
    if any(b < a for a, b in zip(idx, idx[1:])):
        return {"status": "non-monotone", "median_step": median}

    spans = []
    for k, mode in enumerate(modes):
        lo, hi = idx[k], idx[k + 1]
        inside = [int(j) for j in gap_steps if lo <= j < hi]
        span_steps = steps[lo:hi]
        nz = span_steps[span_steps > 0]
        spans.append({
            "span": k,
            "mode": mode,
            "fallback": mode != "trace",
            "line_lo": lo,
            "line_hi": hi,
            "steps": int(hi - lo),
            "gap_steps": inside,
            "gap": bool(inside),
            "median_step_ratio": float(np.median(nz) / median) if nz.size else None,
        })
    covered = {j for s in spans for j in s["gap_steps"]}
    return {
        "status": "ok",
        "median_step": median,
        "spans": spans,
        "gap_steps_total": int(gap_steps.size),
        "gap_steps_outside_spans": int(sum(1 for j in gap_steps if int(j) not in covered)),
    }


# --------------------------------------------------------------- statistics

def fiber_counts(spans: list[dict[str, Any]]) -> tuple[int, int, int, int]:
    """(fallback spans, fallback gap spans, native spans, native gap spans)."""
    nf = sum(1 for s in spans if s["fallback"])
    gf = sum(1 for s in spans if s["fallback"] and s["gap"])
    nn = sum(1 for s in spans if not s["fallback"])
    gn = sum(1 for s in spans if not s["fallback"] and s["gap"])
    return nf, gf, nn, gn


def risk_difference(c: np.ndarray) -> float:
    nf, gf, nn, gn = c.sum(axis=0)
    if nf == 0 or nn == 0:
        return float("nan")
    return float(gf / nf - gn / nn)


def mantel_haenszel_or(c: np.ndarray) -> float | None:
    num = den = 0.0
    for nf, gf, nn, gn in c:
        n = nf + nn
        if nf == 0 or nn == 0:
            continue  # uninformative stratum
        num += gf * (nn - gn) / n
        den += gn * (nf - gf) / n
    if den == 0:
        return None if num == 0 else float("inf")
    return float(num / den)


def bootstrap_ci(c: np.ndarray, reps: int, seed: int) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    n = len(c)
    draws = rng.integers(0, n, size=(reps, n))
    totals = c[draws].sum(axis=1)  # reps x 4
    nf, gf, nn, gn = totals.T
    with np.errstate(invalid="ignore", divide="ignore"):
        rd = gf / nf - gn / nn
    rd = rd[np.isfinite(rd)]
    return float(np.percentile(rd, 2.5)), float(np.percentile(rd, 97.5))


def decide(c: np.ndarray, spec: dict[str, Any], seed: int, reps: int | None = None) -> dict[str, Any]:
    rule = spec["decision"]
    informative = int(sum(1 for row in c if row[0] > 0 and row[2] > 0))
    fallback_spans = int(c[:, 0].sum())
    out: dict[str, Any] = {
        "fibers": int(len(c)),
        "informative_fibers": informative,
        "fallback_spans": fallback_spans,
        "native_spans": int(c[:, 2].sum()),
        "fallback_gap_spans": int(c[:, 1].sum()),
        "native_gap_spans": int(c[:, 3].sum()),
    }
    if informative < rule["min_informative_fibers"] or fallback_spans < rule["min_fallback_spans"]:
        out["verdict"] = "INSUFFICIENT"
        return out
    rd = risk_difference(c)
    lo, hi = bootstrap_ci(c, reps or rule["bootstrap_reps"], seed)
    mh = mantel_haenszel_or(c)
    out.update({"risk_difference": rd, "rd_ci95": [lo, hi], "mh_odds_ratio": mh})
    out["verdict"] = "SUPPORTED" if (lo > 0 and mh is not None and mh > 1) else "NOT SUPPORTED"
    return out


def controls(c: np.ndarray, spec: dict[str, Any]) -> dict[str, Any]:
    """Synthetic outcome controls on the real span structure."""
    ctl = spec["controls"]
    rng = np.random.default_rng(ctl["seed"])
    nf, nn = c[:, 0], c[:, 2]

    # Positive: gaps planted only in fallback spans.
    pos = np.stack([nf, rng.binomial(nf, ctl["positive_fallback_rate"]), nn, np.zeros_like(nn)], axis=1)
    positive = decide(pos, spec, seed=ctl["seed"])

    # Null: gap probability independent of mode, at the observed overall rate.
    p = (c[:, 1].sum() + c[:, 3].sum()) / max(1, (nf.sum() + nn.sum()))
    false_pos = 0
    for r in range(ctl["null_replicates"]):
        null = np.stack([nf, rng.binomial(nf, p), nn, rng.binomial(nn, p)], axis=1)
        if decide(null, spec, seed=ctl["seed"] + r + 1, reps=ctl["null_bootstrap_reps"])["verdict"] == "SUPPORTED":
            false_pos += 1
    fpr = false_pos / ctl["null_replicates"]
    passed = positive["verdict"] == "SUPPORTED" and fpr <= ctl["max_null_false_positive_rate"]
    return {"positive": positive, "null_false_positive_rate": fpr,
            "null_rate_used": float(p), "passed": passed}


# ------------------------------------------------------------------- inputs

def parse_fiber(obj: dict[str, Any]) -> tuple[list, list, list[str]]:
    line = obj["line_points"]
    raw = obj["control_points"]
    controls_ = [c["position"] for c in raw]
    modes = [c["segment_to_next"]["interp_mode"] for c in raw[:-1]]
    return line, controls_, modes


def _download(url: str) -> bytes:
    req = urllib.request.Request(url + "?download=true", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def vc3d_bundle(gaps: list[dict[str, Any]], spec_sha: str) -> dict[str, Any]:
    collections = {}
    for i, g in enumerate(gaps, start=1):
        collections[str(i)] = {
            "name": f"ScrolIQ fiber gap · {g['file']}#{g['step']}",
            "points": {str(i): {"p": g["xyz"], "creation_time": 0}},
            "metadata": {},
            "color": [0.72, 0.59, 0.91],
            "tags": {
                "scroliq_kind": "fiber-gap",
                "source_file": g["file"],
                "source_sha256": g["sha256"],
                "line_step": str(g["step"]),
                "span": str(g["span"]),
                "span_mode": g["mode"],
                "step_ratio": f"{g['ratio']:.3f}",
                "spec_sha256": spec_sha,
            },
        }
    return {
        "scroliq_review_bundle": {
            "schema_version": 1,
            "tool": "scripts/fiber_span_test.py",
            "kind": "fiber-gap",
            "scroll": "PHercParis4",
            "coordinate_space": "fiber line_points as published (no CT binding asserted)",
            "review_points": len(collections),
            "limitation": "Gap candidates are review cues; they are not confirmed trace errors.",
        },
        "vc_pointcollections_json_version": "1",
        "collections": collections,
    }


def run(out_dir: Path) -> int:
    spec_bytes = SPEC_PATH.read_bytes()
    spec_sha = hashlib.sha256(spec_bytes).hexdigest()
    if spec_sha != SPEC_SHA256:
        print(f"spec hash {spec_sha} != frozen {SPEC_SHA256}", file=sys.stderr)
        return 3
    spec = json.loads(spec_bytes)
    census = json.loads(CENSUS_PATH.read_text())
    if census["manifest_sha256"] != spec["inputs"]["census_manifest_sha256"]:
        print("census manifest differs from the frozen one", file=sys.stderr)
        return 3

    gap_factor = spec["parameters"]["gap_factor"]
    counts, per_fiber, gaps, errors = [], [], [], []
    ratios = {"fallback": [], "native": []}
    for row in census["rows"]:
        try:
            payload = _download(row["source_url"])
        except Exception as exc:
            errors.append({"file": row["file"], "error": f"download: {exc}"})
            continue
        if hashlib.sha256(payload).hexdigest() != row["sha256"]:
            errors.append({"file": row["file"], "error": "hash mismatch"})
            continue
        line, ctl, modes = parse_fiber(json.loads(payload))
        table = span_table(line, ctl, modes, gap_factor=gap_factor)
        if table["status"] != "ok":
            per_fiber.append({"file": row["file"], "status": table["status"]})
            continue
        spans = table["spans"]
        counts.append(fiber_counts(spans))
        per_fiber.append({
            "file": row["file"], "status": "ok", "spans": len(spans),
            "counts": dict(zip(("fallback", "fallback_gap", "native", "native_gap"), counts[-1])),
            "gap_steps_total": table["gap_steps_total"],
            "gap_steps_outside_spans": table["gap_steps_outside_spans"],
        })
        med = table["median_step"]
        arr = np.asarray(line, dtype=np.float64)
        steps = np.linalg.norm(np.diff(arr, axis=0), axis=1)
        for s in spans:
            if s["median_step_ratio"] is not None:
                ratios["fallback" if s["fallback"] else "native"].append(s["median_step_ratio"])
            for j in s["gap_steps"]:
                mid = ((arr[j] + arr[j + 1]) / 2).tolist()
                gaps.append({"file": row["file"], "sha256": row["sha256"], "step": j,
                             "span": s["span"], "mode": s["mode"], "xyz": mid,
                             "ratio": float(steps[j] / med)})

    if errors:
        verdict_block = {"verdict": "RUN FAILED", "errors": errors}
        c = np.zeros((0, 4), dtype=int)
    else:
        c = np.asarray(counts, dtype=np.int64)
        ctl_result = controls(c, spec)
        primary = decide(c, spec, seed=spec["decision"]["seed"])
        verdict_block = {"controls": ctl_result, "primary": primary,
                         "verdict": primary["verdict"] if ctl_result["passed"] else "CONTROL FAILURE"}

    mech = {k: {"spans": len(v), "median": float(np.median(v)) if v else None,
                "p90": float(np.percentile(v, 90)) if v else None}
            for k, v in ratios.items()}
    result = {
        "spec_sha256": spec_sha,
        "census_manifest_sha256": census["manifest_sha256"],
        **verdict_block,
        "mechanism_descriptive": {
            "measure": "per-span median non-zero step / fiber median step",
            **mech,
        },
        "non_monotone_fibers": [f["file"] for f in per_fiber if f["status"] != "ok"],
        "gap_candidates_exported": len(gaps),
        "per_fiber": per_fiber,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    (out_dir / "fiber-gaps.points.json").write_text(
        json.dumps(vc3d_bundle(gaps, spec_sha), indent=2, sort_keys=True) + "\n")
    head = {k: v for k, v in result.items() if k != "per_fiber"}
    print(json.dumps(head, indent=2))
    return 0 if result["verdict"] in ("SUPPORTED", "NOT SUPPORTED") else 2


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out-dir", required=True)
    return run(Path(ap.parse_args(argv).out_dir))


if __name__ == "__main__":
    raise SystemExit(main())
