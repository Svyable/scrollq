"""External calibration for winding-constraint producers.

Rule: internal consistency is not external correctness. Cycle consistency,
constraint-satisfaction rate and recovered winding range are statements a
producer makes about itself. A producer that smooths its field can raise its
own agreement while recovering the wrong number of windings. This gate scores
any producer the same way against sealed, independently verified winding
differences. The producer may be human annotation, a ScrollQ generator,
``winding-sync``'s automatic detector, a future Villa generator, or a
reconciled solution.

1. ``freeze`` commits a truth file of verified pairs ``(a, b, truth_delta)``
   with ``truth_delta = w_a − w_b``. Only its hash, its size and the frozen
   thresholds are published. The pairs themselves stay sealed, so a producer
   cannot target them.
2. A producer submits, bound to the spec hash, either pairwise ``constraints``
   ``{a, b, d, confidence?}`` or a node ``windings`` map. It may also submit
   ``internal_metrics``; those are copied into the report under
   ``internal_metrics_not_evidence`` and never affect a verdict.
3. ``score`` reveals the truth file, checks its hash, and reports per producer:
   - coverage of the truth pairs;
   - exact and within-one agreement of the winding difference;
   - mean, median and signed absolute residual;
   - confidence calibration. Declared confidence ``earns_weight`` only if every
     frozen bin has enough scored constraints, exact agreement never falls as
     confidence rises, and the top bin beats the bottom bin by the frozen
     margin. Otherwise confidence must be ignored.

   Where a producer submits constraints, the report also gives its own L1
   internal consistency next to its external agreement, so the two can be
   seen to diverge.

A producer is ``admissible`` as winding evidence only above the frozen
coverage and exact-agreement floors. Otherwise it is ``not_admissible``, or
``unverified`` if nothing was scored.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from .winding_sync import Graph, SyncError, digest, solve_l1
from .winding_sync import _refuse_ink as _refuse_ink_sync

SCHEMA_VERSION = 1
TOOL = "scroliq-constraint-gauge"
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class GaugeError(ValueError):
    pass


def _refuse_ink(obj: Any, where: str) -> None:
    try:
        _refuse_ink_sync(obj, where)
    except SyncError as exc:
        raise GaugeError(str(exc)) from None


def _id(v: Any, field: str) -> str:
    if not isinstance(v, str) or not NAME_RE.match(v):
        raise GaugeError(f"{field}: expected an id string, got {v!r}")
    return v


def validate_truth(document: Any) -> dict:
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise GaugeError("truth: schema_version must be 1")
    _refuse_ink(document, "truth")
    source = str(document.get("truth_source") or "").strip()
    if not source:
        raise GaugeError("truth.truth_source is required (who verified the "
                         "pairs, independently of every producer)")
    raw = document.get("pairs")
    if not isinstance(raw, list) or not raw:
        raise GaugeError("truth.pairs must be a non-empty list")
    pairs, seen = [], set()
    for k, p in enumerate(raw):
        if not isinstance(p, dict):
            raise GaugeError(f"truth.pairs[{k}] must be an object")
        a, b = _id(p.get("a"), f"pairs[{k}].a"), _id(p.get("b"), f"pairs[{k}].b")
        t = p.get("truth_delta")
        if a == b or type(t) is not int:
            raise GaugeError(f"truth.pairs[{k}] needs a != b and an integer "
                             "truth_delta = w_a - w_b")
        key = (a, b) if a < b else (b, a)
        if key in seen:
            raise GaugeError(f"truth.pairs[{k}] duplicates pair {key}")
        seen.add(key)
        pairs.append({"a": a, "b": b, "truth_delta": t})
    return {"schema_version": 1, "truth_source": source, "pairs": pairs}


def freeze(truth_doc: Any, *, benchmark_id: str, frozen_at: str,
           bins: Sequence[float] = (0.0, 0.5, 0.8, 1.0),
           min_coverage: float = 0.5, min_exact: float = 0.9,
           min_scored: int = 30, min_per_bin: int = 20,
           calibration_margin: float = 0.1) -> dict:
    truth = validate_truth(truth_doc)
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", frozen_at):
        raise GaugeError("frozen_at must be YYYY-MM-DD")
    edges = [float(b) for b in bins]
    if len(edges) < 3 or any(b2 <= b1 for b1, b2 in zip(edges, edges[1:])):
        raise GaugeError("bins must be >= 3 strictly increasing edges")
    return {
        "schema_version": 1, "tool": TOOL,
        "benchmark_id": _id(benchmark_id, "benchmark_id"),
        "frozen_at": frozen_at,
        "truth_sha256": digest(truth),
        "truth_pairs": len(truth["pairs"]),
        "truth_source": truth["truth_source"],
        "confidence_bins": edges,
        "thresholds": {"min_coverage": min_coverage, "min_exact": min_exact,
                       "min_scored": min_scored, "min_per_bin": min_per_bin,
                       "calibration_margin": calibration_margin},
        "convention": "delta = w_a - w_b; pairs are unordered, sign follows order",
    }


def _producer_constraints(doc: Mapping[str, Any], label: str
                          ) -> tuple[list[dict] | None, dict | None]:
    cons, wind = doc.get("constraints"), doc.get("windings")
    if (cons is None) == (wind is None):
        raise GaugeError(f"{label}: submit exactly one of constraints or "
                         "windings")
    if wind is not None:
        if not isinstance(wind, dict) or not wind:
            raise GaugeError(f"{label}.windings must be a non-empty object")
        for n, v in wind.items():
            _id(n, f"{label}.windings key")
            if type(v) is not int:
                raise GaugeError(f"{label}.windings[{n}] must be an integer")
        return None, wind
    if not isinstance(cons, list) or not cons:
        raise GaugeError(f"{label}.constraints must be a non-empty list")
    out = []
    for k, c in enumerate(cons):
        if not isinstance(c, dict):
            raise GaugeError(f"{label}.constraints[{k}] must be an object")
        a = _id(c.get("a"), f"{label}.constraints[{k}].a")
        b = _id(c.get("b"), f"{label}.constraints[{k}].b")
        d, conf = c.get("d"), c.get("confidence")
        if a == b or type(d) is not int:
            raise GaugeError(f"{label}.constraints[{k}] needs a != b and an "
                             "integer d = w_a - w_b")
        if conf is not None and (isinstance(conf, bool)
                                 or not isinstance(conf, (int, float))
                                 or not np.isfinite(conf)):
            raise GaugeError(f"{label}.constraints[{k}].confidence must be "
                             "finite")
        out.append({"a": a, "b": b, "d": d,
                    "confidence": None if conf is None else float(conf)})
    return out, None


def _calibration(conf: np.ndarray, exact: np.ndarray, edges: list[float],
                 th: Mapping[str, Any]) -> dict:
    idx = np.clip(np.searchsorted(edges, conf, side="right") - 1, 0,
                  len(edges) - 2)
    bins = []
    for b in range(len(edges) - 1):
        sel = idx == b
        n = int(sel.sum())
        bins.append({"lo": edges[b], "hi": edges[b + 1], "n": n,
                     "exact": round(float(exact[sel].mean()), 4) if n else None})
    if any(x["n"] < th["min_per_bin"] for x in bins):
        status = "unverified"
        reason = f"a bin has fewer than {th['min_per_bin']} scored constraints"
    else:
        acc = [x["exact"] for x in bins]
        mono = all(a2 >= a1 for a1, a2 in zip(acc, acc[1:]))
        lift = acc[-1] - acc[0]
        if mono and lift >= th["calibration_margin"]:
            status, reason = "earns_weight", (
                f"exact agreement rises with confidence (lift {lift:.3f})")
        else:
            status, reason = "not_calibrated", (
                "higher declared confidence does not predict higher external "
                "accuracy; ignore confidence")
    return {"status": status, "reason": reason, "bins": bins}


def _internal_consistency(cons: list[dict]) -> float | None:
    """Fraction of a producer's own constraints satisfied by its L1 solution."""
    doc = {"schema_version": 1, "edges": [
        {"edge_id": f"c{k:07d}", "i": c["a"], "j": c["b"], "d": c["d"]}
        for k, c in enumerate(cons)]}
    try:
        g = Graph.from_document(doc)
        w, _ = solve_l1(g)
    except SyncError:
        return None
    return round(float(((w[g.ei] - w[g.ej]) == g.d).mean()), 4)


def score_producer(spec: Mapping[str, Any], truth: Mapping[str, Any],
                   doc: Any, label: str) -> dict:
    if not isinstance(doc, dict) or doc.get("schema_version") != 1:
        raise GaugeError(f"{label}: schema_version must be 1")
    _refuse_ink(doc, label)
    if doc.get("spec_sha256") != digest(spec):
        raise GaugeError(f"{label}: spec_sha256 does not match the frozen "
                         "benchmark")
    prod = doc.get("producer")
    if not isinstance(prod, dict) or not prod.get("name") or not (
            prod.get("commit") or prod.get("version")):
        raise GaugeError(f"{label}: producer needs name and commit or version")
    cons, wind = _producer_constraints(doc, label)
    th = spec["thresholds"]

    truth_map = {}
    for p in truth["pairs"]:
        truth_map[(p["a"], p["b"])] = p["truth_delta"]
        truth_map[(p["b"], p["a"])] = -p["truth_delta"]
    residual, conf, covered = [], [], set()
    if wind is not None:
        for p in truth["pairs"]:
            if p["a"] in wind and p["b"] in wind:
                residual.append(wind[p["a"]] - wind[p["b"]] - p["truth_delta"])
                covered.add(frozenset((p["a"], p["b"])))
    else:
        for c in cons:
            t = truth_map.get((c["a"], c["b"]))
            if t is None:
                continue
            residual.append(c["d"] - t)
            conf.append(c["confidence"])
            covered.add(frozenset((c["a"], c["b"])))
    r = np.array(residual, dtype=np.int64)
    n = int(r.size)
    coverage = len(covered) / len(truth["pairs"])
    out: dict[str, Any] = {
        "producer": {k: prod.get(k) for k in ("name", "version", "commit",
                                              "kind")},
        "submission": "windings" if wind is not None else "constraints",
        "submitted": len(wind) if wind is not None else len(cons),
        "scored": n,
        "coverage": round(coverage, 4),
        "internal_metrics_not_evidence": doc.get("internal_metrics") or {},
    }
    if n == 0:
        return {**out, "status": "unverified",
                "reason": "no submitted constraint touches a sealed truth pair"}
    exact = (r == 0).astype(float)
    out.update({
        "exact": round(float(exact.mean()), 4),
        "within_1": round(float((np.abs(r) <= 1).mean()), 4),
        "mean_abs_residual": round(float(np.abs(r).mean()), 4),
        "median_abs_residual": float(np.median(np.abs(r))),
        "mean_signed_residual": round(float(r.mean()), 4),
    })
    if cons is not None:
        internal = _internal_consistency(cons)
        out["internal_consistency_not_evidence"] = internal
        if internal is not None:
            out["internal_minus_external"] = round(internal - out["exact"], 4)
        if all(c is not None for c in conf):
            out["confidence"] = _calibration(
                np.array(conf), exact, spec["confidence_bins"], th)
        else:
            out["confidence"] = {"status": "absent" if all(
                c is None for c in conf) else "unverified",
                "reason": "confidence not declared on every scored constraint"}
    else:
        out["confidence"] = {"status": "absent",
                             "reason": "node windings carry no confidence"}
    ok = (n >= th["min_scored"] and coverage >= th["min_coverage"]
          and out["exact"] >= th["min_exact"])
    out["status"] = "admissible" if ok else "not_admissible"
    out["reason"] = (
        "meets the frozen external floors" if ok else
        f"needs scored >= {th['min_scored']}, coverage >= "
        f"{th['min_coverage']}, exact >= {th['min_exact']}")
    return out


def score(spec_doc: Any, truth_doc: Any, producer_docs: Sequence[Any], *,
          run_control: bool = True) -> dict:
    if not isinstance(spec_doc, dict) or spec_doc.get("tool") != TOOL:
        raise GaugeError("spec: not a frozen scroliq-constraint-gauge spec")
    truth = validate_truth(truth_doc)
    if digest(truth) != spec_doc.get("truth_sha256"):
        raise GaugeError("revealed truth does not match the frozen "
                         "truth_sha256")
    rows = [score_producer(spec_doc, truth, d, f"producer[{k}]")
            for k, d in enumerate(producer_docs)]
    control = positive_control() if run_control else None
    return {
        "schema_version": SCHEMA_VERSION, "tool": TOOL,
        "status": ("unverified" if control and not control["passed"]
                   else "scored"),
        "spec_sha256": digest(spec_doc),
        "benchmark_id": spec_doc["benchmark_id"],
        "truth_pairs": len(truth["pairs"]),
        "rule": "internal consistency is not external correctness",
        "producers": rows,
        "positive_control": control,
    }


# ----------------------------------------------------------- positive control


def positive_control() -> dict:
    """Internally perfect but externally wrong must be caught, and so must
    inverted confidence."""
    rng = np.random.default_rng(3)
    nodes = [f"p{k:04d}" for k in range(400)]
    w = np.sort(rng.integers(0, 60, size=400))
    idx = rng.choice(400, size=(300, 2))
    idx = idx[idx[:, 0] != idx[:, 1]]
    truth = {"schema_version": 1, "truth_source": "synthetic control",
             "pairs": []}
    seen = set()
    for a, b in idx:
        key = (min(a, b), max(a, b))
        if key in seen:
            continue
        seen.add(key)
        truth["pairs"].append({"a": nodes[a], "b": nodes[b],
                               "truth_delta": int(w[a] - w[b])})
    spec = freeze(truth, benchmark_id="control", frozen_at="2026-10-06",
                  bins=(0.0, 0.5, 1.0), min_per_bin=10)
    sha = digest(spec)

    def sub(name, **kw):
        return {"schema_version": 1, "spec_sha256": sha,
                "producer": {"name": name, "version": "control"}, **kw}

    halved = {n: int(v // 2) for n, v in zip(nodes, w)}  # smoothed range
    pairs = truth["pairs"]
    good_conf, bad_conf = [], []
    for k, p in enumerate(pairs):
        wrong = k % 3 == 0
        d = p["truth_delta"] + (1 if wrong else 0)
        good_conf.append({"a": p["a"], "b": p["b"], "d": d,
                          "confidence": 0.3 if wrong else 0.9})
        bad_conf.append({"a": p["a"], "b": p["b"], "d": d,
                         "confidence": 0.9 if wrong else 0.3})
    smooth_cons = [{"a": p["a"], "b": p["b"],
                    "d": halved[p["a"]] - halved[p["b"]]} for p in pairs]
    r = score(spec, truth, [
        sub("exact", windings={n: int(v) for n, v in zip(nodes, w)}),
        sub("smoothed", constraints=smooth_cons,
            internal_metrics={"cycle_consistency": 1.0}),
        sub("calibrated", constraints=good_conf),
        sub("inverted", constraints=bad_conf),
    ], run_control=False)
    by = {row["producer"]["name"]: row for row in r["producers"]}
    obs = {
        "exact_admissible": by["exact"]["status"] == "admissible",
        "smoothed_internally_perfect":
            by["smoothed"]["internal_consistency_not_evidence"] == 1.0,
        "smoothed_not_admissible": by["smoothed"]["status"] == "not_admissible",
        "calibrated_earns_weight":
            by["calibrated"]["confidence"]["status"] == "earns_weight",
        "inverted_not_calibrated":
            by["inverted"]["confidence"]["status"] == "not_calibrated",
    }
    try:
        score(spec, dict(truth, truth_source="tampered"), [], run_control=False)
        obs["tampered_truth_refused"] = False
    except GaugeError:
        obs["tampered_truth_refused"] = True
    return {"passed": all(obs.values()), "observed": obs,
            "smoothed_exact": by["smoothed"]["exact"]}


# ---------------------------------------------------------------------- CLI


def _load(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_create_only(path: str, document: Any) -> None:
    with open(path, "x", encoding="utf-8") as fh:
        json.dump(document, fh, indent=1, sort_keys=True, allow_nan=False)
        fh.write("\n")


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog=TOOL, description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd")
    fz = sub.add_parser("freeze", help="commit sealed truth pairs")
    fz.add_argument("--truth", required=True)
    fz.add_argument("--benchmark-id", required=True)
    fz.add_argument("--frozen-at", required=True, help="YYYY-MM-DD")
    fz.add_argument("--bins", default="0,0.5,0.8,1",
                    help="confidence bin edges")
    fz.add_argument("--min-coverage", type=float, default=0.5)
    fz.add_argument("--min-exact", type=float, default=0.9)
    fz.add_argument("--min-scored", type=int, default=30)
    fz.add_argument("--min-per-bin", type=int, default=20)
    fz.add_argument("--calibration-margin", type=float, default=0.1)
    fz.add_argument("--out", required=True, help="create-only frozen spec")
    sc = sub.add_parser("score", help="reveal truth and score producers")
    sc.add_argument("--spec", required=True)
    sc.add_argument("--truth", required=True)
    sc.add_argument("--producer", action="append", default=[], required=True)
    sc.add_argument("--out", required=True, help="create-only report")
    sub.add_parser("self-test", help="run the built-in positive control")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "freeze":
            spec = freeze(_load(args.truth), benchmark_id=args.benchmark_id,
                          frozen_at=args.frozen_at,
                          bins=[float(x) for x in args.bins.split(",")],
                          min_coverage=args.min_coverage,
                          min_exact=args.min_exact,
                          min_scored=args.min_scored,
                          min_per_bin=args.min_per_bin,
                          calibration_margin=args.calibration_margin)
            _write_create_only(args.out, spec)
            print(f"spec_sha256={digest(spec)}")
            return 0
        if args.cmd == "score":
            r = score(_load(args.spec), _load(args.truth),
                      [_load(p) for p in args.producer])
            _write_create_only(args.out, r)
            for row in r["producers"]:
                print(f"{row['producer']['name']}: {row['status']} "
                      f"exact={row.get('exact')} coverage={row['coverage']}")
            return 0 if r["status"] == "scored" else 2
        if args.cmd == "self-test":
            ctl = positive_control()
            print(json.dumps(ctl, indent=1))
            return 0 if ctl["passed"] else 2
    except (GaugeError, SyncError, OSError, json.JSONDecodeError) as exc:
        print(f"{TOOL}: {exc}", file=sys.stderr)
        return 2
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
