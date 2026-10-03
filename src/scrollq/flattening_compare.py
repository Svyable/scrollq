"""Ink-blind candidate-vs-baseline flattening proof gate.

The comparison intentionally consumes only Wavefront OBJ geometry/UVs. It
verifies that both parameterizations describe the exact same ordered 3-D
triangle mesh, reuses ScrolIQ's OBJ audit for local isometry/foldover metrics,
and makes promotion contingent on permissive implementation licensing plus
predeclared geometric non-regression gates.

It does not inspect ink, renders, OCR, text, or legibility.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from scrollq.obj_audit import audit_obj, parse_obj

DIAGNOSTIC = "flattening-compare"
SCHEMA_VERSION = 1

# The Grand Prize requires the submitted pipeline to be permissively licensed.
# Keep this intentionally conservative; a caller can benchmark other methods,
# but they cannot receive PROMOTE from this gate until the implementation
# license is one of these permissive SPDX identifiers.
PERMISSIVE_LICENSES = {
    "0BSD",
    "Apache-2.0",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "ISC",
    "MIT",
    "Unlicense",
}


def _file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _geometry_sha256(mesh: dict[str, Any]) -> str:
    """Hash only ordered 3-D vertices/faces, deliberately excluding UVs."""
    vertices = np.asarray(mesh["vertices"], dtype="<f8").copy(order="C")
    # Canonicalize signed zero without rounding real geometry.
    vertices[vertices == 0] = 0.0
    faces = np.asarray(mesh["faces"], dtype="<i8", order="C")

    digest = hashlib.sha256()
    digest.update(b"scroliq-ordered-triangle-geometry-v1\0")
    for arr in (vertices, faces):
        digest.update(json.dumps(list(arr.shape), separators=(",", ":")).encode("ascii"))
        digest.update(b"\0")
        digest.update(arr.tobytes(order="C"))
    return digest.hexdigest()


def _metric(report: dict[str, Any]) -> dict[str, Any]:
    iso = report.get("isometry")
    if not isinstance(iso, dict) or iso.get("status") != "measured":
        raise ValueError("OBJ audit has no measured UV-to-3D isometry")
    stretch = iso.get("symmetric_stretch_distortion")
    if not isinstance(stretch, dict):
        raise ValueError("OBJ audit isometry is missing stretch summary")

    p95 = stretch.get("p95")
    median = stretch.get("median")
    if not all(
        isinstance(v, (int, float)) and math.isfinite(float(v)) and float(v) > 0
        for v in (p95, median)
    ):
        raise ValueError("OBJ audit stretch p95/median must be finite positive numbers")

    return {
        "p95_symmetric_stretch": float(p95),
        "median_symmetric_stretch": float(median),
        "max_symmetric_stretch": stretch.get("max"),
        "flipped_uv_triangles": int(iso.get("flipped_uv_triangles", 0)),
        "degenerate_uv_triangles": int(iso.get("degenerate_uv_triangles", 0)),
        "textured_triangles": int(iso.get("textured_triangles", 0)),
        "untextured_triangles": int(iso.get("untextured_triangles", 0)),
    }


def compare_flattenings(
    baseline_obj: str | Path,
    candidate_obj: str | Path,
    *,
    candidate_method: str,
    implementation_ref: str,
    implementation_license: str,
    source_ref: str | None = None,
    max_p95_ratio: float = 1.0,
    max_median_ratio: float = 1.0,
    min_p95_improvement_fraction: float = 0.01,
) -> dict[str, Any]:
    """Compare two UV parameterizations of the exact same ordered 3-D mesh."""
    if not candidate_method.strip():
        raise ValueError("candidate_method must be non-empty")
    if not implementation_ref.strip():
        raise ValueError("implementation_ref must be non-empty")
    if max_p95_ratio <= 0 or max_median_ratio <= 0:
        raise ValueError("distortion ratios must be positive")
    if not 0 <= min_p95_improvement_fraction < 1:
        raise ValueError("min_p95_improvement_fraction must be in [0, 1)")

    baseline_path = Path(baseline_obj)
    candidate_path = Path(candidate_obj)
    errors: list[str] = []

    try:
        baseline_mesh = parse_obj(baseline_path)
        candidate_mesh = parse_obj(candidate_path)
    except (OSError, ValueError) as exc:
        return {
            "schema_version": SCHEMA_VERSION,
            "diagnostic": DIAGNOSTIC,
            "status": "fail",
            "decision": {"verdict": "REJECT", "reason": f"cannot parse input OBJ: {exc}"},
            "errors": [f"cannot parse input OBJ: {exc}"],
        }

    baseline_geometry = _geometry_sha256(baseline_mesh)
    candidate_geometry = _geometry_sha256(candidate_mesh)
    same_geometry = baseline_geometry == candidate_geometry

    baseline_audit = audit_obj(baseline_path)
    candidate_audit = audit_obj(candidate_path)
    if baseline_audit.get("status") == "fail":
        errors.append("baseline OBJ audit failed")
    if candidate_audit.get("status") == "fail":
        errors.append("candidate OBJ audit failed")
    if not same_geometry:
        errors.append(
            "candidate does not preserve the exact ordered 3-D vertices/faces of the baseline"
        )

    baseline_metrics: dict[str, Any] | None = None
    candidate_metrics: dict[str, Any] | None = None
    try:
        baseline_metrics = _metric(baseline_audit)
    except ValueError as exc:
        errors.append(f"baseline: {exc}")
    try:
        candidate_metrics = _metric(candidate_audit)
    except ValueError as exc:
        errors.append(f"candidate: {exc}")

    permissive = implementation_license in PERMISSIVE_LICENSES
    gates: list[dict[str, Any]] = [
        {
            "name": "geometry_identity",
            "required": True,
            "passed": same_geometry,
            "detail": "ordered 3-D vertices/faces must hash identically; UVs are excluded",
        },
        {
            "name": "permissive_implementation_license",
            "required": True,
            "passed": permissive,
            "detail": (
                implementation_license
                if permissive
                else f"{implementation_license!r} is not in the conservative permissive allowlist"
            ),
        },
    ]

    improvement: float | None = None
    if baseline_metrics is not None and candidate_metrics is not None:
        p95_ratio = (
            candidate_metrics["p95_symmetric_stretch"]
            / baseline_metrics["p95_symmetric_stretch"]
        )
        median_ratio = (
            candidate_metrics["median_symmetric_stretch"]
            / baseline_metrics["median_symmetric_stretch"]
        )
        improvement = 1.0 - p95_ratio
        gates.extend(
            [
                {
                    "name": "candidate_all_triangles_textured",
                    "required": True,
                    "passed": candidate_metrics["untextured_triangles"] == 0,
                    "value": candidate_metrics["untextured_triangles"],
                },
                {
                    "name": "candidate_zero_uv_foldovers",
                    "required": True,
                    "passed": candidate_metrics["flipped_uv_triangles"] == 0,
                    "value": candidate_metrics["flipped_uv_triangles"],
                },
                {
                    "name": "candidate_zero_degenerate_uv_triangles",
                    "required": True,
                    "passed": candidate_metrics["degenerate_uv_triangles"] == 0,
                    "value": candidate_metrics["degenerate_uv_triangles"],
                },
                {
                    "name": "p95_isometry_nonregression",
                    "required": True,
                    "passed": p95_ratio <= max_p95_ratio,
                    "value": p95_ratio,
                    "threshold_max_ratio": max_p95_ratio,
                },
                {
                    "name": "median_isometry_nonregression",
                    "required": True,
                    "passed": median_ratio <= max_median_ratio,
                    "value": median_ratio,
                    "threshold_max_ratio": max_median_ratio,
                },
            ]
        )

    required_pass = bool(gates) and all(
        gate.get("passed") is True for gate in gates if gate.get("required") is True
    )
    material_improvement = (
        improvement is not None and improvement >= min_p95_improvement_fraction
    )

    if errors or not required_pass:
        verdict = "REJECT"
        status = "fail"
        reason = "one or more geometry, UV-safety, distortion, provenance, or license gates failed"
    elif material_improvement:
        verdict = "PROMOTE"
        status = "pass"
        reason = (
            "candidate preserves identical 3-D geometry, passes UV safety/non-regression "
            f"gates, and improves p95 stretch by {improvement:.2%}"
        )
    else:
        verdict = "HOLD"
        status = "partial"
        reason = (
            "candidate is geometrically safe but does not meet the predeclared minimum "
            "p95 distortion improvement"
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "diagnostic": DIAGNOSTIC,
        "status": status,
        "selection_contract": {
            "selection_signal": "geometry-only",
            "ink_inputs_consumed": False,
            "statement": (
                "This comparator reads only OBJ 3-D geometry and UVs. Ink, rendered text, "
                "OCR, and legibility are outside the decision path."
            ),
        },
        "candidate_method": {
            "name": candidate_method,
            "source_ref": source_ref,
            "implementation_ref": implementation_ref,
            "implementation_license": implementation_license,
            "permissive_license_gate": permissive,
        },
        "inputs": {
            "baseline_obj": str(baseline_path),
            "baseline_sha256": _file_sha256(baseline_path),
            "candidate_obj": str(candidate_path),
            "candidate_sha256": _file_sha256(candidate_path),
            "baseline_geometry_sha256": baseline_geometry,
            "candidate_geometry_sha256": candidate_geometry,
            "geometry_identical": same_geometry,
        },
        "thresholds": {
            "max_p95_ratio": max_p95_ratio,
            "max_median_ratio": max_median_ratio,
            "min_p95_improvement_fraction": min_p95_improvement_fraction,
        },
        "metrics": {
            "baseline": baseline_metrics,
            "candidate": candidate_metrics,
            "p95_improvement_fraction": improvement,
        },
        "gates": gates,
        "decision": {"verdict": verdict, "reason": reason},
        "errors": errors,
        "limitation": (
            "This is a parameterization comparison, not proof of correct papyrus sheet "
            "identity, CT support, physical 1-cm scale, self-intersection freedom, or ink "
            "legibility. A promoted parameterization still has to pass the ordinary "
            "TIFXYZ/VC3D submission gates after conversion."
        ),
    }


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Compare two ink-blind flattenings of the exact same ordered OBJ geometry"
    )
    ap.add_argument("--baseline-obj", required=True)
    ap.add_argument("--candidate-obj", required=True)
    ap.add_argument("--candidate-method", required=True)
    ap.add_argument("--source-ref", default=None)
    ap.add_argument("--implementation-ref", required=True)
    ap.add_argument("--implementation-license", required=True)
    ap.add_argument("--max-p95-ratio", type=float, default=1.0)
    ap.add_argument("--max-median-ratio", type=float, default=1.0)
    ap.add_argument("--min-p95-improvement-fraction", type=float, default=0.01)
    ap.add_argument("--out", required=True)
    ap.add_argument(
        "--require-promote",
        action="store_true",
        help="exit 2 unless the candidate receives PROMOTE",
    )
    args = ap.parse_args()

    report = compare_flattenings(
        args.baseline_obj,
        args.candidate_obj,
        candidate_method=args.candidate_method,
        implementation_ref=args.implementation_ref,
        implementation_license=args.implementation_license,
        source_ref=args.source_ref,
        max_p95_ratio=args.max_p95_ratio,
        max_median_ratio=args.max_median_ratio,
        min_p95_improvement_fraction=args.min_p95_improvement_fraction,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        f"{report['decision']['verdict']} {args.candidate_method}: "
        f"{report['decision']['reason']}"
    )
    if report["status"] == "fail" or (
        args.require_promote and report["decision"]["verdict"] != "PROMOTE"
    ):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
