"""Pre-registration wrapper for ink-blind flattening experiments.

This module closes the timing loophole left by a generic comparator: the
baseline geometry, candidate implementation identity/license, and all decision
thresholds are frozen in a deterministic JSON spec *before* candidate
evaluation. Git history or another immutable publication mechanism establishes
the temporal ordering; this tool establishes exact byte/geometry binding.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

from scrollq.flattening_compare import (
    _file_sha256,
    _geometry_sha256,
    _metric,
    compare_flattenings,
)
from scrollq.obj_audit import audit_obj, parse_obj

TOOL = "scroliq-flatten-plan"
SCHEMA_VERSION = 1


def _validate_thresholds(
    max_p95_ratio: float,
    max_median_ratio: float,
    min_p95_improvement_fraction: float,
) -> None:
    if (
        not math.isfinite(max_p95_ratio)
        or not math.isfinite(max_median_ratio)
        or max_p95_ratio <= 0
        or max_median_ratio <= 0
    ):
        raise ValueError("distortion ratios must be finite positive numbers")
    if (
        not math.isfinite(min_p95_improvement_fraction)
        or not 0 <= min_p95_improvement_fraction < 1
    ):
        raise ValueError("min_p95_improvement_fraction must be in [0, 1)")


def seal_spec(
    baseline_obj: str | Path,
    *,
    experiment_id: str,
    candidate_method: str,
    implementation_ref: str,
    implementation_license: str,
    source_ref: str | None = None,
    corpus_role: str | None = None,
    source_mesh_ref: str | None = None,
    max_p95_ratio: float = 1.0,
    max_median_ratio: float = 1.0,
    min_p95_improvement_fraction: float = 0.01,
) -> dict[str, Any]:
    """Freeze a baseline and decision rule before candidate evaluation."""
    if not experiment_id.strip():
        raise ValueError("experiment_id must be non-empty")
    if not candidate_method.strip():
        raise ValueError("candidate_method must be non-empty")
    if not implementation_ref.strip():
        raise ValueError("implementation_ref must be non-empty")
    if not implementation_license.strip():
        raise ValueError("implementation_license must be non-empty")
    _validate_thresholds(
        max_p95_ratio, max_median_ratio, min_p95_improvement_fraction
    )

    baseline_path = Path(baseline_obj)
    try:
        mesh = parse_obj(baseline_path)
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot parse baseline OBJ: {exc}") from exc

    audit = audit_obj(baseline_path)
    if audit.get("status") == "fail":
        raise ValueError("baseline OBJ audit failed; refusing to seal an invalid baseline")
    try:
        baseline_metrics = _metric(audit)
    except ValueError as exc:
        raise ValueError(f"baseline is not parameterized: {exc}") from exc

    return {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "mode": "sealed-flattening-experiment",
        "experiment_id": experiment_id,
        "selection_contract": {
            "selection_signal": "geometry-only",
            "ink_inputs_consumed": False,
            "candidate_metrics_observed_when_sealed": False,
            "statement": (
                "The baseline bytes/geometry, candidate implementation identity/license, "
                "and decision thresholds are frozen before candidate evaluation. Ink, "
                "renders, OCR, and legibility are excluded from selection."
            ),
            "temporal_proof": (
                "Commit or publish this spec before evaluating the candidate. The tool "
                "binds bytes and rules; repository history establishes temporal order."
            ),
        },
        "corpus": {
            "role": corpus_role,
            "source_mesh_ref": source_mesh_ref,
        },
        "baseline": {
            "obj_path_recorded": str(baseline_path),
            "sha256": _file_sha256(baseline_path),
            "geometry_sha256": _geometry_sha256(mesh),
            "metrics_at_seal": baseline_metrics,
        },
        "candidate_method": {
            "name": candidate_method,
            "source_ref": source_ref,
            "implementation_ref": implementation_ref,
            "implementation_license": implementation_license,
        },
        "thresholds": {
            "max_p95_ratio": float(max_p95_ratio),
            "max_median_ratio": float(max_median_ratio),
            "min_p95_improvement_fraction": float(
                min_p95_improvement_fraction
            ),
        },
    }


def _load_spec(path: str | Path) -> tuple[bytes, dict[str, Any]]:
    raw = Path(path).read_bytes()
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot parse flattening spec: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("flattening spec must be a JSON object")
    return raw, value


def evaluate_spec(
    spec: dict[str, Any],
    baseline_obj: str | Path,
    candidate_obj: str | Path,
    *,
    spec_sha256: str | None = None,
) -> dict[str, Any]:
    """Evaluate a candidate using only rules frozen in a sealed spec."""
    errors: list[str] = []
    if spec.get("schema_version") != SCHEMA_VERSION or spec.get("tool") != TOOL:
        errors.append(
            f"spec must be {TOOL} schema_version {SCHEMA_VERSION}"
        )
    if spec.get("mode") != "sealed-flattening-experiment":
        errors.append("spec mode must be sealed-flattening-experiment")

    selection = spec.get("selection_contract")
    if not isinstance(selection, dict):
        errors.append("spec selection_contract must be an object")
    else:
        if selection.get("selection_signal") != "geometry-only":
            errors.append("spec selection signal must be geometry-only")
        if selection.get("ink_inputs_consumed") is not False:
            errors.append("spec must declare ink_inputs_consumed=false")
        if selection.get("candidate_metrics_observed_when_sealed") is not False:
            errors.append(
                "spec must declare candidate_metrics_observed_when_sealed=false"
            )

    baseline = spec.get("baseline")
    candidate = spec.get("candidate_method")
    thresholds = spec.get("thresholds")
    if not isinstance(baseline, dict):
        errors.append("spec baseline must be an object")
        baseline = {}
    if not isinstance(candidate, dict):
        errors.append("spec candidate_method must be an object")
        candidate = {}
    if not isinstance(thresholds, dict):
        errors.append("spec thresholds must be an object")
        thresholds = {}

    baseline_path = Path(baseline_obj)
    try:
        baseline_mesh = parse_obj(baseline_path)
        observed_baseline_sha = _file_sha256(baseline_path)
        observed_geometry_sha = _geometry_sha256(baseline_mesh)
    except (OSError, ValueError) as exc:
        observed_baseline_sha = None
        observed_geometry_sha = None
        errors.append(f"cannot bind baseline OBJ: {exc}")

    if observed_baseline_sha is not None and observed_baseline_sha != baseline.get("sha256"):
        errors.append("baseline OBJ SHA-256 differs from the sealed spec")
    if observed_geometry_sha is not None and observed_geometry_sha != baseline.get(
        "geometry_sha256"
    ):
        errors.append("baseline ordered 3-D geometry differs from the sealed spec")

    candidate_method = candidate.get("name")
    implementation_ref = candidate.get("implementation_ref")
    implementation_license = candidate.get("implementation_license")
    source_ref = candidate.get("source_ref")
    if not isinstance(candidate_method, str) or not candidate_method.strip():
        errors.append("spec candidate method must be a non-empty string")
    if not isinstance(implementation_ref, str) or not implementation_ref.strip():
        errors.append("spec implementation_ref must be a non-empty string")
    if not isinstance(implementation_license, str) or not implementation_license.strip():
        errors.append("spec implementation_license must be a non-empty string")

    try:
        max_p95_ratio = float(thresholds["max_p95_ratio"])
        max_median_ratio = float(thresholds["max_median_ratio"])
        min_improvement = float(thresholds["min_p95_improvement_fraction"])
        _validate_thresholds(max_p95_ratio, max_median_ratio, min_improvement)
    except (KeyError, TypeError, ValueError) as exc:
        errors.append(f"invalid sealed thresholds: {exc}")
        max_p95_ratio = max_median_ratio = 1.0
        min_improvement = 0.01

    if errors:
        return {
            "schema_version": SCHEMA_VERSION,
            "diagnostic": "flattening-compare",
            "status": "fail",
            "preregistration": {
                "tool": TOOL,
                "experiment_id": spec.get("experiment_id"),
                "spec_sha256": spec_sha256,
                "binding_passed": False,
                "errors": errors,
            },
            "decision": {
                "verdict": "REJECT",
                "reason": "sealed flattening spec is invalid or does not bind the supplied baseline",
            },
            "errors": errors,
        }

    result = compare_flattenings(
        baseline_path,
        candidate_obj,
        candidate_method=candidate_method,
        implementation_ref=implementation_ref,
        implementation_license=implementation_license,
        source_ref=source_ref if isinstance(source_ref, str) else None,
        max_p95_ratio=max_p95_ratio,
        max_median_ratio=max_median_ratio,
        min_p95_improvement_fraction=min_improvement,
    )
    result["preregistration"] = {
        "tool": TOOL,
        "experiment_id": spec.get("experiment_id"),
        "spec_sha256": spec_sha256,
        "binding_passed": True,
        "baseline_sha256_matches": True,
        "baseline_geometry_sha256_matches": True,
        "candidate_metadata_source": "sealed-spec",
        "threshold_source": "sealed-spec",
        "corpus": spec.get("corpus"),
    }
    return result


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _seal(args: argparse.Namespace) -> int:
    try:
        spec = seal_spec(
            args.baseline_obj,
            experiment_id=args.experiment_id,
            candidate_method=args.candidate_method,
            implementation_ref=args.implementation_ref,
            implementation_license=args.implementation_license,
            source_ref=args.source_ref,
            corpus_role=args.corpus_role,
            source_mesh_ref=args.source_mesh_ref,
            max_p95_ratio=args.max_p95_ratio,
            max_median_ratio=args.max_median_ratio,
            min_p95_improvement_fraction=args.min_p95_improvement_fraction,
        )
    except (OSError, ValueError) as exc:
        print(f"{TOOL}: {exc}", file=sys.stderr)
        return 2

    _write_json(args.out, spec)
    raw = args.out.read_bytes()
    print(
        f"{TOOL}: sealed {spec['experiment_id']} "
        f"sha256={hashlib.sha256(raw).hexdigest()}"
    )
    return 0


def _evaluate(args: argparse.Namespace) -> int:
    try:
        raw, spec = _load_spec(args.spec)
        result = evaluate_spec(
            spec,
            args.baseline_obj,
            args.candidate_obj,
            spec_sha256=hashlib.sha256(raw).hexdigest(),
        )
    except (OSError, ValueError) as exc:
        print(f"{TOOL}: {exc}", file=sys.stderr)
        return 2

    _write_json(args.out, result)
    decision = result.get("decision", {})
    print(
        f"{TOOL}: {decision.get('verdict', 'REJECT')} "
        f"{spec.get('experiment_id')}: {decision.get('reason', '')}"
    )
    if result.get("status") == "fail" or (
        args.require_promote and decision.get("verdict") != "PROMOTE"
    ):
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Seal and evaluate ink-blind flattening experiments"
    )
    sub = ap.add_subparsers(dest="command", required=True)

    seal = sub.add_parser(
        "seal",
        help="freeze baseline identity, candidate implementation metadata, and thresholds",
    )
    seal.add_argument("--baseline-obj", required=True, type=Path)
    seal.add_argument("--experiment-id", required=True)
    seal.add_argument("--candidate-method", required=True)
    seal.add_argument("--source-ref", default=None)
    seal.add_argument("--implementation-ref", required=True)
    seal.add_argument("--implementation-license", required=True)
    seal.add_argument("--corpus-role", default=None)
    seal.add_argument("--source-mesh-ref", default=None)
    seal.add_argument("--max-p95-ratio", type=float, default=1.0)
    seal.add_argument("--max-median-ratio", type=float, default=1.0)
    seal.add_argument("--min-p95-improvement-fraction", type=float, default=0.01)
    seal.add_argument("--out", required=True, type=Path)
    seal.set_defaults(func=_seal)

    evaluate = sub.add_parser(
        "evaluate",
        help="evaluate a candidate using only the rules frozen in a spec",
    )
    evaluate.add_argument("--spec", required=True, type=Path)
    evaluate.add_argument("--baseline-obj", required=True, type=Path)
    evaluate.add_argument("--candidate-obj", required=True, type=Path)
    evaluate.add_argument("--out", required=True, type=Path)
    evaluate.add_argument("--require-promote", action="store_true")
    evaluate.set_defaults(func=_evaluate)

    args = ap.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
