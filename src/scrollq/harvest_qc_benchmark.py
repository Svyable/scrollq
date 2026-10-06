"""Independent harvest-QC benchmark: does an outside rejection metric close a
ScrollQ blind spot without rejecting verified-good surface?

Motivation: ``vesuvius-automesh`` (MIT) harvests Scroll 3 surface by seed-
sweeping VC3D's ``vc_grow_seg_from_seed``, then rejects most candidates with
texture / physical-surface gates and a separate topology re-gate. Its own
records include a cross-roll trace whose fiber-like texture passed every
texture gate but failed surface lock. "Looks like papyrus" is therefore not
evidence of correct sheet geometry, and an outside evaluator is worth
benchmarking against ScrollQ's own gates. Those external results are the
project's own reports and are not reproduced here.

The benchmark is evaluation only. Nothing it reads may influence tracing:

1. ``freeze`` validates and hash-pins a candidate-surface manifest *before*
   any evaluator runs: each surface's content hash, its independently sourced
   truth (``verified_good`` or ``invalid`` with a failure class such as
   ``wrong_wrap`` / ``cross_roll`` / ``drift_into_air`` / ``skim_no_lock`` /
   ``page_edge_runoff``), the ScrollQ gates and candidate metrics to compare,
   and the regions used to seed or calibrate any evaluator. A surface whose
   box intersects a seed region of the same volume is refused (prediction
   leakage).
2. Each evaluator then submits one decisions file bound to that hash, with
   ``influenced_tracing: false``, giving ``accept`` / ``reject`` / ``unknown``
   per surface and gate.
3. ``evaluate`` applies the frozen rule. A *blind spot* is an ``invalid``
   surface that no ScrollQ gate rejects. A candidate metric is ``PROMOTE`` only
   if it decided every leave-one-scroll-out-eligible surface, rejected no
   ``verified_good`` surface anywhere, and rejected at least one blind spot.
   Decisions on surfaces from a scroll the metric was calibrated on (for
   automesh's texture gate, the scroll of its human-verified reference render)
   are reported but never count as promotion evidence, so similarity to one
   known texture cannot become a universal definition of a valid page.

Verdicts: ``PROMOTE``, ``REJECT_FALSE_REJECTS``, ``NO_NEW_COVERAGE``,
``INCOMPLETE``, ``NOT_EVALUABLE_LOSO``. A built-in synthetic control must
produce each verdict as designed; if it does not, the report is
``unverified``. ``PROMOTE`` admits a metric as supporting evidence; it is not
proof that harvested area is correct, and says nothing about ink.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = 1
TOOL = "scroliq-harvest-qc"
DECISIONS = ("accept", "reject", "unknown")
TRUTH = ("verified_good", "invalid")
FAILURE_CLASSES = ("wrong_wrap", "cross_roll", "drift_into_air",
                   "skim_no_lock", "page_edge_runoff", "other")
DEFAULT_SCROLLQ_GATES = ("ct_seating", "ordering", "topology", "seam",
                         "fiber")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class BenchmarkError(ValueError):
    pass


def _canonical(document: Mapping[str, Any]) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def digest(document: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(document)).hexdigest()


def _name(value: Any, field: str) -> str:
    if not isinstance(value, str) or not NAME_RE.match(value):
        raise BenchmarkError(f"{field}: expected a simple name, got {value!r}")
    return value


def _bbox(value: Any, field: str) -> list[list[int]]:
    if (not isinstance(value, list) or len(value) != 3
            or not all(isinstance(r, list) and len(r) == 2 for r in value)):
        raise BenchmarkError(f"{field}: expected [[z0,z1],[y0,y1],[x0,x1]]")
    out = []
    for lo, hi in value:
        if type(lo) is not int or type(hi) is not int or not 0 <= lo < hi:
            raise BenchmarkError(f"{field}: empty or invalid range {lo}..{hi}")
        out.append([lo, hi])
    return out


def _intersects(a: Sequence[Sequence[int]], b: Sequence[Sequence[int]]) -> bool:
    return all(a[d][0] < b[d][1] and b[d][0] < a[d][1] for d in range(3))


def validate_spec(document: Any) -> dict[str, Any]:
    """Validated copy of a candidate-surface manifest; raises on any defect."""
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise BenchmarkError("spec: schema_version must be 1")
    spec = {
        "schema_version": 1,
        "benchmark_id": _name(document.get("benchmark_id"), "benchmark_id"),
        "frozen_at": str(document.get("frozen_at") or ""),
    }
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", spec["frozen_at"]):
        raise BenchmarkError("frozen_at must be YYYY-MM-DD")

    gates = document.get("scrollq_gates", list(DEFAULT_SCROLLQ_GATES))
    if not isinstance(gates, list) or not gates:
        raise BenchmarkError("scrollq_gates must be a non-empty list")
    spec["scrollq_gates"] = [_name(g, "scrollq_gates[]") for g in gates]

    metrics = document.get("candidate_metrics")
    if not isinstance(metrics, list) or not metrics:
        raise BenchmarkError("candidate_metrics must be a non-empty list")
    spec["candidate_metrics"] = []
    for i, m in enumerate(metrics):
        if not isinstance(m, dict):
            raise BenchmarkError(f"candidate_metrics[{i}] must be an object")
        cal = m.get("calibration_scrolls")
        if not isinstance(cal, list):
            raise BenchmarkError(
                f"candidate_metrics[{i}].calibration_scrolls must be a list "
                "(empty only if the metric used no scroll material)")
        spec["candidate_metrics"].append({
            "metric": _name(m.get("metric"), f"candidate_metrics[{i}].metric"),
            "evaluator": _name(m.get("evaluator"),
                               f"candidate_metrics[{i}].evaluator"),
            "calibration_scrolls": sorted(
                _name(s, "calibration_scrolls[]") for s in cal),
            "description": str(m.get("description") or ""),
        })
    names = [m["metric"] for m in spec["candidate_metrics"]]
    if len(set(names)) != len(names) or set(names) & set(spec["scrollq_gates"]):
        raise BenchmarkError("metric and gate names must be unique")

    seeds = document.get("seed_regions", [])
    if not isinstance(seeds, list):
        raise BenchmarkError("seed_regions must be a list")
    spec["seed_regions"] = [{
        "volume_id": _name(r.get("volume_id"), "seed_regions[].volume_id"),
        "bbox_zyx": _bbox(r.get("bbox_zyx"), "seed_regions[].bbox_zyx"),
        "used_by": str(r.get("used_by") or ""),
    } for r in seeds]

    surfaces = document.get("surfaces")
    if not isinstance(surfaces, list) or not surfaces:
        raise BenchmarkError("surfaces must be a non-empty list")
    spec["surfaces"] = []
    seen_ids, seen_sha = set(), set()
    for i, s in enumerate(surfaces):
        f = f"surfaces[{i}]"
        if not isinstance(s, dict):
            raise BenchmarkError(f"{f} must be an object")
        sid = _name(s.get("surface_id"), f"{f}.surface_id")
        sha = s.get("sha256")
        if not isinstance(sha, str) or not SHA_RE.match(sha):
            raise BenchmarkError(f"{f}.sha256 must be 64 lowercase hex")
        truth = s.get("truth")
        if truth not in TRUTH:
            raise BenchmarkError(f"{f}.truth must be one of {TRUTH}")
        fc = s.get("failure_class")
        if truth == "verified_good" and fc is not None:
            raise BenchmarkError(f"{f}: verified_good has no failure_class")
        if truth == "invalid" and fc not in FAILURE_CLASSES:
            raise BenchmarkError(
                f"{f}.failure_class must be one of {FAILURE_CLASSES}")
        source = str(s.get("truth_source") or "").strip()
        if not source:
            raise BenchmarkError(
                f"{f}.truth_source is required (who established the truth, "
                "independently of every evaluator)")
        if sid in seen_ids or sha in seen_sha:
            raise BenchmarkError(f"{f}: duplicate surface_id or sha256")
        seen_ids.add(sid)
        seen_sha.add(sha)
        row = {
            "surface_id": sid,
            "scroll": _name(s.get("scroll"), f"{f}.scroll"),
            "volume_id": _name(s.get("volume_id"), f"{f}.volume_id"),
            "sha256": sha,
            "truth": truth,
            "failure_class": fc,
            "truth_source": source,
            "bbox_zyx": _bbox(s.get("bbox_zyx"), f"{f}.bbox_zyx"),
        }
        for r in spec["seed_regions"]:
            if (r["volume_id"] == row["volume_id"]
                    and _intersects(r["bbox_zyx"], row["bbox_zyx"])):
                raise BenchmarkError(
                    f"{f} ({sid}) intersects a seed/calibration region of "
                    f"{r['volume_id']}: evaluation and seeding must be "
                    "spatially separated")
        spec["surfaces"].append(row)

    floors = {}
    for key in ("min_verified_good", "min_invalid"):
        v = document.get(key, 1)
        if type(v) is not int or v < 1:
            raise BenchmarkError(f"{key} must be an integer >= 1")
        floors[key] = v
    spec.update(floors)
    n_good = sum(s["truth"] == "verified_good" for s in spec["surfaces"])
    n_bad = len(spec["surfaces"]) - n_good
    if n_good < spec["min_verified_good"] or n_bad < spec["min_invalid"]:
        raise BenchmarkError(
            f"corpus has {n_good} verified_good / {n_bad} invalid surfaces; "
            f"frozen minimums are {spec['min_verified_good']} / "
            f"{spec['min_invalid']}")
    return spec


def validate_decisions(document: Any, spec: Mapping[str, Any],
                       spec_sha: str, gates: Sequence[str],
                       label: str) -> dict[str, Any]:
    """One evaluator's decisions, bound to the frozen spec hash."""
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise BenchmarkError(f"{label}: schema_version must be 1")
    if document.get("spec_sha256") != spec_sha:
        raise BenchmarkError(
            f"{label}: spec_sha256 does not match the frozen spec "
            "(decisions must be made against the frozen manifest)")
    if document.get("influenced_tracing") is not False:
        raise BenchmarkError(
            f"{label}: influenced_tracing must be exactly false; an evaluator "
            "that steered tracing is not independent")
    tool = document.get("tool")
    if not isinstance(tool, dict) or not tool.get("name") or not (
            tool.get("commit") or tool.get("version")):
        raise BenchmarkError(f"{label}: tool needs name and commit or version")
    raw = document.get("decisions")
    if not isinstance(raw, dict):
        raise BenchmarkError(f"{label}: decisions must be an object")
    ids = {s["surface_id"] for s in spec["surfaces"]}
    unknown_ids = set(raw) - ids
    if unknown_ids:
        raise BenchmarkError(
            f"{label}: decisions for surfaces outside the frozen spec: "
            f"{sorted(unknown_ids)}")
    out: dict[str, dict[str, str]] = {}
    missing = []
    for sid in sorted(ids):
        row = raw.get(sid) or {}
        if not isinstance(row, dict):
            raise BenchmarkError(f"{label}: decisions[{sid}] must be an object")
        extra = set(row) - set(gates)
        if extra:
            raise BenchmarkError(
                f"{label}: decisions[{sid}] has unregistered gates "
                f"{sorted(extra)}")
        out[sid] = {}
        for g in gates:
            v = row.get(g)
            if v is None:
                missing.append(f"{sid}:{g}")
                v = "unknown"
            if v not in DECISIONS:
                raise BenchmarkError(
                    f"{label}: decisions[{sid}][{g}] must be one of {DECISIONS}")
            out[sid][g] = v
    return {"tool": {k: tool.get(k) for k in ("name", "version", "commit")},
            "decisions": out, "missing": missing}


def _agreement(spec, metric_dec, scrollq_dec, metric, gates) -> dict:
    table = {}
    for g in gates:
        cells = {"both_reject": 0, "both_accept": 0, "metric_only_reject": 0,
                 "gate_only_reject": 0, "undecided": 0}
        for s in spec["surfaces"]:
            a = metric_dec[s["surface_id"]][metric]
            b = scrollq_dec[s["surface_id"]][g]
            if "unknown" in (a, b):
                cells["undecided"] += 1
            elif a == b == "reject":
                cells["both_reject"] += 1
            elif a == b == "accept":
                cells["both_accept"] += 1
            elif a == "reject":
                cells["metric_only_reject"] += 1
            else:
                cells["gate_only_reject"] += 1
        table[g] = cells
    return table


def evaluate(spec_doc: Any, scrollq_doc: Any,
             candidate_docs: Sequence[Any], *, run_control: bool = True
             ) -> dict[str, Any]:
    spec = validate_spec(spec_doc)
    spec_sha = digest(spec)
    gates = spec["scrollq_gates"]
    sq = validate_decisions(scrollq_doc, spec, spec_sha, gates, "scrollq")

    by_eval: dict[str, list[dict]] = {}
    for m in spec["candidate_metrics"]:
        by_eval.setdefault(m["evaluator"], []).append(m)
    cand: dict[str, dict] = {}
    for i, doc in enumerate(candidate_docs):
        ev = doc.get("evaluator") if isinstance(doc, dict) else None
        if ev not in by_eval or ev in cand:
            raise BenchmarkError(
                f"candidate[{i}]: evaluator {ev!r} is not registered in the "
                "spec, or was submitted twice")
        cand[ev] = validate_decisions(
            doc, spec, spec_sha, [m["metric"] for m in by_eval[ev]],
            f"candidate[{ev}]")

    surfaces = spec["surfaces"]
    sq_rows = []
    blind = set()
    for s in surfaces:
        d = sq["decisions"][s["surface_id"]]
        rejected_by = [g for g in gates if d[g] == "reject"]
        combined = ("reject" if rejected_by else
                    "accept" if all(d[g] == "accept" for g in gates)
                    else "unknown")
        if s["truth"] == "invalid" and not rejected_by:
            blind.add(s["surface_id"])
        sq_rows.append({"surface_id": s["surface_id"], "truth": s["truth"],
                        "failure_class": s["failure_class"],
                        "combined": combined, "rejected_by": rejected_by})
    sq_false_rejects = sorted(r["surface_id"] for r in sq_rows
                              if r["truth"] == "verified_good"
                              and r["combined"] == "reject")

    metrics_out = []
    for m in spec["candidate_metrics"]:
        name, ev = m["metric"], m["evaluator"]
        if ev not in cand:
            metrics_out.append({"metric": name, "evaluator": ev,
                                "verdict": "INCOMPLETE",
                                "reason": "no decisions file submitted"})
            continue
        dec = cand[ev]["decisions"]
        cal = set(m["calibration_scrolls"])
        loso = [s for s in surfaces if s["scroll"] not in cal]
        in_domain = [s["surface_id"] for s in surfaces if s["scroll"] in cal]
        false_rejects = sorted(s["surface_id"] for s in surfaces
                               if s["truth"] == "verified_good"
                               and dec[s["surface_id"]][name] == "reject")
        undecided = sorted(s["surface_id"] for s in loso
                           if dec[s["surface_id"]][name] == "unknown")
        detected = sorted(s["surface_id"] for s in loso
                          if s["truth"] == "invalid"
                          and dec[s["surface_id"]][name] == "reject")
        blind_hit = sorted(set(detected) & blind)
        loso_good = sum(s["truth"] == "verified_good" for s in loso)
        loso_bad = len(loso) - loso_good
        if false_rejects:
            verdict = "REJECT_FALSE_REJECTS"
            reason = "rejected independently verified good surface"
        elif not loso_good or not loso_bad:
            verdict = "NOT_EVALUABLE_LOSO"
            reason = ("no verified_good and invalid surfaces outside the "
                      "metric's calibration scrolls")
        elif undecided:
            verdict = "INCOMPLETE"
            reason = "undecided leave-one-scroll-out surfaces"
        elif not blind_hit:
            verdict = "NO_NEW_COVERAGE"
            reason = ("rejects no invalid surface that ScrollQ gates miss"
                      if blind else "frozen corpus has no ScrollQ blind spot")
        else:
            verdict = "PROMOTE"
            reason = (f"closes {len(blind_hit)} ScrollQ blind spot(s) with "
                      "no false rejects")
        metrics_out.append({
            "metric": name,
            "evaluator": ev,
            "tool": cand[ev]["tool"],
            "calibration_scrolls": sorted(cal),
            "verdict": verdict,
            "reason": reason,
            "loso_surfaces": len(loso),
            "in_calibration_domain_surfaces": in_domain,
            "false_rejects": false_rejects,
            "invalid_detected_loso": detected,
            "blind_spots_closed": blind_hit,
            "undecided_loso": undecided,
            "missing_decisions": cand[ev]["missing"],
            "agreement_with_scrollq_gates": _agreement(
                spec, dec, sq["decisions"], name, gates),
        })

    control = positive_control() if run_control else None
    status = ("unverified" if control is not None and not control["passed"]
              else "evaluated")
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "status": status,
        "spec_sha256": spec_sha,
        "benchmark_id": spec["benchmark_id"],
        "rule": ("PROMOTE iff every leave-one-scroll-out surface is decided, "
                 "no verified_good surface is rejected, and >= 1 invalid "
                 "surface that no ScrollQ gate rejects is rejected"),
        "corpus": {
            "surfaces": len(surfaces),
            "verified_good": sum(s["truth"] == "verified_good"
                                 for s in surfaces),
            "invalid_by_class": {
                c: sum(s["failure_class"] == c for s in surfaces)
                for c in FAILURE_CLASSES},
        },
        "scrollq": {"tool": sq["tool"], "gates": gates,
                    "missing_decisions": sq["missing"],
                    "blind_spots": sorted(blind),
                    "false_rejects": sq_false_rejects,
                    "surfaces": sq_rows},
        "candidate_metrics": metrics_out,
        "positive_control": control,
        "scope": ("independent QC comparison only; a PROMOTE metric is "
                  "supporting evidence, not proof that harvested area is "
                  "papyrus on the right sheet, and never ink evidence"),
    }


# ----------------------------------------------------------- positive control


def _control_inputs() -> tuple[dict, dict, list[dict]]:
    def surf(sid, scroll, truth, fc, z):
        return {"surface_id": sid, "scroll": scroll, "volume_id": f"V{scroll}",
                "sha256": hashlib.sha256(sid.encode()).hexdigest(),
                "truth": truth, "failure_class": fc,
                "truth_source": "synthetic control",
                "bbox_zyx": [[z, z + 10], [0, 10], [0, 10]]}

    spec = {
        "schema_version": 1, "benchmark_id": "control",
        "frozen_at": "2026-10-05",
        "scrollq_gates": ["ct_seating", "topology"],
        "candidate_metrics": [
            {"metric": "closes", "evaluator": "ext",
             "calibration_scrolls": []},
            {"metric": "overkill", "evaluator": "ext",
             "calibration_scrolls": []},
            {"metric": "redundant", "evaluator": "ext",
             "calibration_scrolls": []},
            {"metric": "abstains", "evaluator": "ext",
             "calibration_scrolls": []},
            {"metric": "home_only", "evaluator": "ext",
             "calibration_scrolls": ["A", "B"]},
        ],
        "seed_regions": [{"volume_id": "VA", "bbox_zyx":
                          [[500, 600], [0, 10], [0, 10]]}],
        "surfaces": [surf("good1", "A", "verified_good", None, 0),
                     surf("good2", "B", "verified_good", None, 0),
                     surf("drift", "A", "invalid", "drift_into_air", 20),
                     surf("cross", "B", "invalid", "cross_roll", 20)],
    }
    sha = digest(validate_spec(spec))
    acc = {"ct_seating": "accept", "topology": "accept"}
    scrollq = {"schema_version": 1, "spec_sha256": sha,
               "influenced_tracing": False,
               "tool": {"name": "scrollq", "version": "control"},
               "decisions": {"good1": acc, "good2": acc,
                             "drift": {"ct_seating": "reject",
                                       "topology": "accept"},
                             "cross": acc}}  # cross is the blind spot

    def row(closes, overkill, redundant, abstains, home):
        return {"closes": closes, "overkill": overkill,
                "redundant": redundant, "abstains": abstains,
                "home_only": home}

    ext = {"schema_version": 1, "spec_sha256": sha, "evaluator": "ext",
           "influenced_tracing": False,
           "tool": {"name": "ext", "commit": "0" * 40},
           "decisions": {
               "good1": row("accept", "reject", "accept", "accept", "accept"),
               "good2": row("accept", "accept", "accept", "unknown", "accept"),
               "drift": row("reject", "reject", "reject", "reject", "reject"),
               "cross": row("reject", "reject", "accept", "unknown",
                            "reject")}}
    return spec, scrollq, [ext]


def positive_control() -> dict:
    expect = {"closes": "PROMOTE", "overkill": "REJECT_FALSE_REJECTS",
              "redundant": "NO_NEW_COVERAGE", "abstains": "INCOMPLETE",
              "home_only": "NOT_EVALUABLE_LOSO", "blind_spots": ["cross"],
              "leak_refused": True, "unbound_refused": True}
    spec, scrollq, cands = _control_inputs()
    r = evaluate(spec, scrollq, cands, run_control=False)
    got: dict[str, Any] = {m["metric"]: m["verdict"]
                           for m in r["candidate_metrics"]}
    got["blind_spots"] = r["scrollq"]["blind_spots"]
    leaky = json.loads(json.dumps(spec))
    leaky["surfaces"][0]["bbox_zyx"] = [[550, 560], [0, 10], [0, 10]]
    try:
        validate_spec(leaky)
        got["leak_refused"] = False
    except BenchmarkError:
        got["leak_refused"] = True
    steered = dict(cands[0], influenced_tracing=True)
    try:
        evaluate(spec, scrollq, [steered], run_control=False)
        got["unbound_refused"] = False
    except BenchmarkError:
        got["unbound_refused"] = True
    return {"passed": got == expect, "expected": expect, "observed": got}


# ------------------------------------------------------------------------ CLI


def _load(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_create_only(path: str, document: Mapping[str, Any]) -> None:
    with open(path, "x", encoding="utf-8") as fh:
        json.dump(document, fh, indent=2, sort_keys=True, allow_nan=False)
        fh.write("\n")


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog=TOOL, description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd")
    fz = sub.add_parser("freeze", help="validate and hash-pin a manifest")
    fz.add_argument("--spec", required=True)
    fz.add_argument("--out", required=True, help="create-only frozen spec")
    ev = sub.add_parser("evaluate", help="apply the frozen promotion rule")
    ev.add_argument("--spec", required=True)
    ev.add_argument("--scrollq", required=True, help="ScrollQ gate decisions")
    ev.add_argument("--candidate", action="append", default=[],
                    help="candidate evaluator decisions (repeatable)")
    ev.add_argument("--out", required=True, help="create-only report")
    sub.add_parser("self-test", help="run the built-in positive control")
    args = ap.parse_args(argv)

    try:
        if args.cmd == "freeze":
            spec = validate_spec(_load(args.spec))
            _write_create_only(args.out, spec)
            print(f"spec_sha256={digest(spec)}")
            return 0
        if args.cmd == "evaluate":
            report = evaluate(_load(args.spec), _load(args.scrollq),
                              [_load(p) for p in args.candidate])
            _write_create_only(args.out, report)
            for m in report["candidate_metrics"]:
                print(f"{m['metric']}: {m['verdict']} — {m['reason']}")
            return 0 if report["status"] == "evaluated" else 2
        if args.cmd == "self-test":
            ctl = positive_control()
            print(json.dumps(ctl, indent=1))
            return 0 if ctl["passed"] else 2
    except (BenchmarkError, OSError, json.JSONDecodeError) as exc:
        print(f"{TOOL}: {exc}", file=sys.stderr)
        return 2
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
