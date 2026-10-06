"""Flatten/render measurement-noise floor for small-effect geometry claims.

Before an experiment claims that a small change in geometry changed recovered
ink (or any rendered quantity), it must show that the change is larger than
the noise the flatten/render stage adds to an *unchanged* surface.
``vesuvius-autoresearch`` reports that Villa's Lasagna flattening is
nondeterministic on byte-identical inputs unless deterministic PyTorch
algorithms are enabled. Those are the project's own reports and are not
reproduced here.

The input is one experiment's measurement record:

- ``determinism``: the declared mode (``deterministic`` / ``nondeterministic``)
  and its settings. ``unknown`` or a missing mode makes the record
  ``unverified``.
- ``repeats``: at least ``min_repeats`` flatten+render runs of the same
  unchanged surface, each with the measured value and, optionally, the
  SHA-256 of its outputs (for example ``x.tif`` / ``y.tif`` / ``z.tif``).
- ``claims``: baseline and candidate values for each claimed effect.

The noise floor is the repeat range relative to the repeat mean. A claim
``EXCEEDS_NOISE_FLOOR`` only when ``|relative change| > k × floor``, with the
floor taken as at least ``floor_min`` so that a lucky identical pair cannot
make every change significant. Otherwise the claim is ``WITHIN_NOISE``. The
output is a ``measurement_noise`` block to embed in the experiment passport.

Scope: the floor covers re-running flatten/render on one fixed surface. It
does not cover variation between independently fitted surfaces, where fit
randomness can dominate. A within-surface floor is not evidence about
whole-fit reproducibility.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Sequence

SCHEMA_VERSION = 1
TOOL = "scroliq-render-noise"
MODES = ("deterministic", "nondeterministic")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class NoiseError(ValueError):
    pass


def _finite(v: Any, field: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise NoiseError(f"{field} must be a finite number")
    return float(v)


def evaluate(document: Any) -> dict:
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise NoiseError("record: schema_version must be 1")
    exp = document.get("experiment_id")
    if not isinstance(exp, str) or not NAME_RE.match(exp):
        raise NoiseError("experiment_id must be a simple name")
    metric = str(document.get("metric") or "").strip()
    if not metric:
        raise NoiseError("metric must name the measured quantity")
    rule = document.get("rule") or {}
    k = _finite(rule.get("k", 3.0), "rule.k")
    min_repeats = rule.get("min_repeats", 3)
    floor_min = _finite(rule.get("floor_min", 1e-6), "rule.floor_min")
    if type(min_repeats) is not int or min_repeats < 2 or k <= 0:
        raise NoiseError("rule needs k > 0 and integer min_repeats >= 2")

    det = document.get("determinism") or {}
    mode = det.get("mode")
    repeats = document.get("repeats") or []
    if not isinstance(repeats, list):
        raise NoiseError("repeats must be a list")
    values, hashes = [], []
    for i, r in enumerate(repeats):
        if not isinstance(r, dict):
            raise NoiseError(f"repeats[{i}] must be an object")
        values.append(_finite(r.get("value"), f"repeats[{i}].value"))
        h = r.get("outputs_sha256")
        if h is not None and not isinstance(h, dict):
            raise NoiseError(f"repeats[{i}].outputs_sha256 must be an object")
        hashes.append(h)

    out: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION, "tool": TOOL,
        "experiment_id": exp, "metric": metric,
        "determinism": {"mode": mode, "settings": det.get("settings") or {}},
        "rule": {"k": k, "min_repeats": min_repeats, "floor_min": floor_min},
        "repeats": len(values),
        "scope": ("re-render of one fixed surface only; not evidence about "
                  "variation between independently fitted surfaces"),
    }
    if all(h is not None for h in hashes) and hashes:
        canon = [json.dumps(h, sort_keys=True) for h in hashes]
        out["outputs_bit_identical"] = len(set(canon)) == 1
    else:
        out["outputs_bit_identical"] = None

    problems = []
    if mode not in MODES:
        problems.append("determinism.mode must be declared as "
                        f"{' or '.join(MODES)}")
    if len(values) < min_repeats:
        problems.append(f"need >= {min_repeats} repeats of the unchanged "
                        "surface")
    mean = sum(values) / len(values) if values else 0.0
    if values and mean == 0:
        problems.append("repeat mean is zero; relative floor undefined")
    if problems:
        return {**out, "status": "unverified", "reason": "; ".join(problems),
                "claims": []}

    spread = max(values) - min(values)
    floor = spread / abs(mean)
    eff = max(floor, floor_min)
    out.update({
        "repeat_mean": mean,
        "repeat_range": spread,
        "noise_floor_relative": floor,
        "effective_floor_relative": eff,
        "threshold_relative": k * eff,
    })
    if mode == "deterministic" and out["outputs_bit_identical"] is False:
        out["warning"] = ("declared deterministic, but repeat outputs differ; "
                          "the declaration is not supported by the outputs")

    claims = []
    for i, c in enumerate(document.get("claims") or []):
        if not isinstance(c, dict):
            raise NoiseError(f"claims[{i}] must be an object")
        cid = c.get("claim_id")
        if not isinstance(cid, str) or not NAME_RE.match(cid):
            raise NoiseError(f"claims[{i}].claim_id must be a simple name")
        base = _finite(c.get("baseline"), f"claims[{i}].baseline")
        cand = _finite(c.get("candidate"), f"claims[{i}].candidate")
        if base == 0:
            raise NoiseError(f"claims[{i}].baseline must be non-zero")
        rel = (cand - base) / abs(base)
        claims.append({
            "claim_id": cid, "baseline": base, "candidate": cand,
            "relative_change": rel,
            "multiple_of_floor": abs(rel) / eff,
            "verdict": ("EXCEEDS_NOISE_FLOOR" if abs(rel) > k * eff
                        else "WITHIN_NOISE"),
        })
    return {**out, "status": "measured", "claims": claims}


def positive_control() -> dict:
    noisy = {"schema_version": 1, "experiment_id": "ctl", "metric": "fg_px",
             "determinism": {"mode": "nondeterministic"},
             "repeats": [{"value": 1000}, {"value": 1030}, {"value": 1012}],
             "claims": [{"claim_id": "small", "baseline": 1000,
                         "candidate": 1020},
                        {"claim_id": "large", "baseline": 1000,
                         "candidate": 800}]}
    r = evaluate(noisy)
    v = {c["claim_id"]: c["verdict"] for c in r["claims"]}
    undeclared = evaluate(dict(noisy, determinism={}))
    obs = {
        "small_within_noise": v.get("small") == "WITHIN_NOISE",
        "large_exceeds": v.get("large") == "EXCEEDS_NOISE_FLOOR",
        "undeclared_mode_unverified": undeclared["status"] == "unverified",
        "two_repeats_unverified": evaluate(
            dict(noisy, repeats=noisy["repeats"][:2]))["status"] == "unverified",
    }
    return {"passed": all(obs.values()), "observed": obs}


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog=TOOL, description=__doc__.splitlines()[0])
    ap.add_argument("--record", help="measurement record JSON")
    ap.add_argument("--out", help="write the measurement_noise block here")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        ctl = positive_control()
        print(json.dumps(ctl, indent=1))
        return 0 if ctl["passed"] else 2
    if not args.record:
        ap.print_help()
        return 0
    try:
        r = evaluate(json.loads(Path(args.record).read_text(encoding="utf-8")))
    except (NoiseError, OSError, json.JSONDecodeError) as exc:
        print(f"{TOOL}: {exc}", file=sys.stderr)
        return 2
    text = json.dumps({"measurement_noise": r}, indent=1, sort_keys=True) + "\n"
    if args.out:
        with open(args.out, "x", encoding="utf-8") as fh:
            fh.write(text)
    else:
        sys.stdout.write(text)
    for c in r["claims"]:
        print(f"{c['claim_id']}: {c['verdict']} ({c['relative_change']:+.4%})",
              file=sys.stderr)
    return 0 if r["status"] == "measured" else 2


if __name__ == "__main__":
    raise SystemExit(main())
