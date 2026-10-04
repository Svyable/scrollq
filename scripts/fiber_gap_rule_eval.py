#!/usr/bin/env python3
"""Pre-registered comparison of the whole-fiber gap rule with a span-aware rule
(November N4a, pulled into October).

Frozen design: ``artifacts/2026-10-04-fiber-gap-rule-prereg/spec.json``
(SHA-256 pinned below). Inputs are the 136 hash-pinned PHercParis4 census
fibers. Span boundaries come from ``fiber_span_test.span_table`` on the
unmodified line, so planting a break never moves a span.
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

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fiber_span_test import parse_fiber, span_table  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "artifacts/2026-10-04-fiber-gap-rule-prereg/spec.json"
SPEC_SHA256 = "09ea046e97c5d274d8587dd7aa2b2bade14c418c2b39659cb77a9c450164da56"
# Every frozen spec this runner may execute, by repo-relative path.
FROZEN_SPECS = {
    "artifacts/2026-10-04-fiber-gap-rule-prereg/spec.json": SPEC_SHA256,
}
CENSUS = ROOT / "artifacts/2026-10-04-fiber-corpus-census/summary.json"
UA = {"User-Agent": "scrollq-fiber-gap-rule-eval/1"}


def steps_of(line: np.ndarray) -> np.ndarray:
    return np.linalg.norm(np.diff(line, axis=0), axis=1)


def flagged(steps: np.ndarray, spans: list[dict[str, Any]], rule: str, p: dict[str, Any]) -> set[int]:
    """Indices of steps flagged as gaps by ``rule`` ('old' or 'span')."""
    pos = steps[steps > 0]
    fiber_med = float(np.median(pos))
    thr = np.full(len(steps), p["gap_factor"] * fiber_med)
    if rule == "span":
        for s in spans:
            seg = steps[s["line_lo"]:s["line_hi"]]
            nz = seg[seg > 0]
            if len(nz) >= p["min_span_steps"]:
                thr[s["line_lo"]:s["line_hi"]] = p["gap_factor"] * float(np.median(nz))
    elif rule != "old":
        raise ValueError(rule)
    return {int(j) for j in np.flatnonzero(steps > thr)}


def eligible_spans(steps: np.ndarray, spans: list[dict[str, Any]], fallback: bool, p: dict[str, Any]):
    out = []
    for s in spans:
        if s["fallback"] != fallback:
            continue
        seg = steps[s["line_lo"]:s["line_hi"]]
        if (seg > 0).sum() >= p["min_span_steps"] and s["line_hi"] - s["line_lo"] >= 3:
            out.append(s)
    return out


def plant(line: np.ndarray, steps: np.ndarray, span: dict[str, Any], rng: np.random.Generator,
          factor: float, reference: float) -> tuple[np.ndarray, int]:
    """Stretch one interior non-zero step of ``span`` to ``factor * reference``."""
    lo, hi = span["line_lo"], span["line_hi"]
    candidates = [j for j in range(lo + 1, hi - 1) if steps[j] > 0] or \
                 [j for j in range(lo, hi) if steps[j] > 0]
    j = int(rng.choice(candidates))
    direction = (line[j + 1] - line[j]) / steps[j]
    out = line.copy()
    out[j + 1:] += direction * (factor * reference - steps[j])
    return out, j


def evaluate_fiber(line, controls, modes, p, rng) -> dict[str, Any]:
    line = np.asarray(line, float)
    table = span_table(line.tolist(), controls, modes, gap_factor=p["gap_factor"])
    if table["status"] != "ok":
        return {"status": table["status"]}
    spans = table["spans"]
    steps = steps_of(line)
    res: dict[str, Any] = {"status": "ok", "real": {}, "planted": {}}
    for rule in ("old", "span"):
        f = flagged(steps, spans, rule, p)
        by_mode = {"fallback": 0, "native": 0, "outside": 0}
        for j in f:
            owner = next((s for s in spans if s["line_lo"] <= j < s["line_hi"]), None)
            by_mode["outside" if owner is None else ("fallback" if owner["fallback"] else "native")] += 1
        res["real"][rule] = by_mode
    fiber_med = float(np.median(steps[steps > 0]))
    for cls, is_fb in (("native", False), ("fallback", True)):
        el = eligible_spans(steps, spans, is_fb, p)
        if not el:
            continue
        span = el[int(rng.integers(len(el)))]
        seg = steps[span["line_lo"]:span["line_hi"]]
        span_med = float(np.median(seg[seg > 0]))
        for arm, ref in (("span_relative", span_med), ("fiber_relative", fiber_med)):
            pl, j = plant(line, steps, span, rng, p["plant_factor"], ref)
            ps = steps_of(pl)
            res["planted"].setdefault(arm, {})[cls] = {
                rule: j in flagged(ps, spans, rule, p) for rule in ("old", "span")
            }
    return res


def summarize(per: list[dict[str, Any]], spec: dict[str, Any]) -> dict[str, Any]:
    ok = [r for r in per if r["status"] == "ok"]
    real = {rule: {m: sum(r["real"][rule][m] for r in ok) for m in ("fallback", "native", "outside")}
            for rule in ("old", "span")}
    recall: dict[str, Any] = {}
    for arm in ("span_relative", "fiber_relative"):
        recall[arm] = {}
        for cls in ("native", "fallback"):
            hits = [r["planted"][arm][cls] for r in ok if cls in r["planted"].get(arm, {})]
            recall[arm][cls] = {"n": len(hits), **{rule: (sum(h[rule] for h in hits) / len(hits) if hits else None)
                                                  for rule in ("old", "span")}}
    d = spec["decision"]
    pr = recall["span_relative"]
    checks = {
        "native_recall": pr["native"]["span"] is not None and pr["native"]["span"] >= d["min_recall"],
        "fallback_recall": pr["fallback"]["span"] is not None and pr["fallback"]["span"] >= d["min_recall"],
        "fallback_reduction": real["old"]["fallback"] > 0 and
            real["span"]["fallback"] <= d["max_fallback_ratio"] * real["old"]["fallback"],
        "native_not_worse": pr["native"]["span"] is not None and pr["native"]["old"] is not None and
            pr["native"]["span"] >= pr["native"]["old"] - d["max_native_recall_loss"],
    }
    enough = all(pr[c]["n"] >= d["min_planted_per_class"] for c in ("native", "fallback"))
    verdict = "INSUFFICIENT" if not enough else ("ADOPT" if all(checks.values()) else "KEEP")
    return {"verdict": verdict, "checks": checks, "real_candidates": real, "planted_recall": recall,
            "fibers": len(per), "non_monotone": sum(1 for r in per if r["status"] != "ok")}


def run(out: Path, spec_path: Path = SPEC_PATH) -> int:
    rel = spec_path.resolve().relative_to(ROOT).as_posix()
    if rel not in FROZEN_SPECS:
        print(f"{rel} is not a frozen spec", file=sys.stderr)
        return 3
    raw = spec_path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    if sha != FROZEN_SPECS[rel]:
        print(f"spec hash {sha} != frozen {FROZEN_SPECS[rel]}", file=sys.stderr)
        return 3
    spec = json.loads(raw)
    census = json.loads((ROOT / spec["inputs"]["census"]).read_text())
    if census["manifest_sha256"] != spec["inputs"]["census_manifest_sha256"]:
        print("census manifest differs", file=sys.stderr)
        return 3
    p = spec["parameters"]
    rng = np.random.default_rng(spec["seed"])
    per, errors = [], []
    for row in census["rows"]:
        try:
            payload = urllib.request.urlopen(urllib.request.Request(
                row["source_url"] + "?download=true", headers=UA), timeout=120).read()
        except Exception as exc:
            errors.append(f"{row['file']}: {exc}")
            continue
        if hashlib.sha256(payload).hexdigest() != row["sha256"]:
            errors.append(f"{row['file']}: hash mismatch")
            continue
        line, ctl, modes = parse_fiber(json.loads(payload))
        per.append({"file": row["file"], **evaluate_fiber(line, ctl, modes, p, rng)})
    result = {"spec_sha256": sha, "census_manifest_sha256": census["manifest_sha256"]}
    result.update({"verdict": "RUN FAILED", "errors": errors} if errors else summarize(per, spec))
    result["per_fiber"] = per
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "per_fiber"}, indent=2))
    return 0 if result["verdict"] in ("ADOPT", "KEEP") else 2


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--spec", default=str(SPEC_PATH), help="a frozen spec listed in FROZEN_SPECS")
    a = ap.parse_args(argv)
    return run(Path(a.out_dir), Path(a.spec))


if __name__ == "__main__":
    raise SystemExit(main())
