"""Finite-sample structural uncertainty audit for held-out segmentation.

This module independently implements a narrow split-conformal audit over trusted
`scroliq-segmentation-validate` outputs. It intentionally separates:

* boundary error: symmetric p95 surface distance in base voxels; and
* structural error: whether any disconnected truth component received zero
  prediction support within the preregistered segmentation tolerance.

The calibration/test partition, region IDs, alpha, and the maximum useful
boundary radius are frozen in a public spec. Failed or omitted regions are never
silently dropped. A mathematically valid but operationally useless bound is
reported as vacuous rather than as successful evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = 1
METHOD = "split_conformal"
BOUNDARY_METRIC = "symmetric_p95_voxels"
COMPONENT_METRIC = "truth_component_recall_any"
SHA256_FIELDS = (
    "checkpoint_sha256",
    "inference_script_sha256",
    "inference_config_sha256",
)


class StructuralUncertaintyError(ValueError):
    """Raised when a conformal audit contract or input is invalid."""


def _canonical_bytes(document: Mapping[str, Any]) -> bytes:
    return json.dumps(
        document, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def digest(document: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes(document)).hexdigest()


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StructuralUncertaintyError(f"cannot read {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise StructuralUncertaintyError(f"{label} must be a JSON object")
    return value


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StructuralUncertaintyError(f"{field} must be a non-empty string")
    return value.strip()


def _fraction_open(value: Any, field: str) -> float:
    if (
        type(value) not in (int, float)
        or not math.isfinite(float(value))
        or not 0.0 < float(value) < 1.0
    ):
        raise StructuralUncertaintyError(f"{field} must be a finite number in (0,1)")
    return float(value)


def _positive(value: Any, field: str) -> float:
    if (
        type(value) not in (int, float)
        or not math.isfinite(float(value))
        or float(value) <= 0.0
    ):
        raise StructuralUncertaintyError(f"{field} must be a finite number > 0")
    return float(value)


def _ids(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise StructuralUncertaintyError(f"{field} must be a non-empty list")
    result = [_text(v, field) for v in value]
    if len(result) != len(set(result)):
        raise StructuralUncertaintyError(f"{field} contains duplicate region IDs")
    return result


def validate_spec(document: Mapping[str, Any]) -> dict[str, Any]:
    if type(document.get("schema_version")) is not int or document["schema_version"] != 1:
        raise StructuralUncertaintyError("spec.schema_version must be 1")
    if document.get("method") != METHOD:
        raise StructuralUncertaintyError(f"spec.method must be {METHOD}")
    alpha = _fraction_open(document.get("alpha"), "spec.alpha")
    if document.get("boundary_metric") != BOUNDARY_METRIC:
        raise StructuralUncertaintyError(
            f"spec.boundary_metric must be {BOUNDARY_METRIC}"
        )
    if document.get("component_metric") != COMPONENT_METRIC:
        raise StructuralUncertaintyError(
            f"spec.component_metric must be {COMPONENT_METRIC}"
        )

    normalized: dict[str, Any] = {
        "schema_version": 1,
        "method": METHOD,
        "alpha": alpha,
        "boundary_metric": BOUNDARY_METRIC,
        "component_metric": COMPONENT_METRIC,
        "max_nonvacuous_boundary_voxels": _positive(
            document.get("max_nonvacuous_boundary_voxels"),
            "spec.max_nonvacuous_boundary_voxels",
        ),
    }
    for split in ("calibration", "test"):
        raw = document.get(split)
        if not isinstance(raw, dict):
            raise StructuralUncertaintyError(f"spec.{split} must be an object")
        normalized[split] = {
            "dataset": _text(raw.get("dataset"), f"spec.{split}.dataset"),
            "region_ids": _ids(raw.get("region_ids"), f"spec.{split}.region_ids"),
        }

    if normalized["calibration"]["dataset"] == normalized["test"]["dataset"]:
        overlap = set(normalized["calibration"]["region_ids"]) & set(
            normalized["test"]["region_ids"]
        )
        if overlap:
            raise StructuralUncertaintyError(
                "calibration and test region IDs overlap within the same dataset"
            )
    return normalized


def _provenance(document: Mapping[str, Any], label: str) -> dict[str, str]:
    raw = document.get("provenance")
    if not isinstance(raw, dict):
        raise StructuralUncertaintyError(f"{label}.provenance must be an object")
    result: dict[str, str] = {}
    for field in SHA256_FIELDS:
        value = raw.get(field)
        if not isinstance(value, str) or len(value) != 64:
            raise StructuralUncertaintyError(
                f"{label}.provenance.{field} must be 64 hex characters"
            )
        try:
            bytes.fromhex(value)
        except ValueError as exc:
            raise StructuralUncertaintyError(
                f"{label}.provenance.{field} must be hexadecimal"
            ) from exc
        if value.lower() != value:
            raise StructuralUncertaintyError(
                f"{label}.provenance.{field} must be lowercase"
            )
        result[field] = value
    return result


def _validate_results(
    document: Mapping[str, Any],
    *,
    label: str,
    dataset: str,
    expected_ids: Sequence[str],
) -> dict[str, Any]:
    if type(document.get("schema_version")) is not int or document["schema_version"] != 1:
        raise StructuralUncertaintyError(f"{label}.schema_version must be 1")
    if document.get("task") != "segmentation":
        raise StructuralUncertaintyError(f"{label}.task must be segmentation")
    if document.get("dataset") != dataset:
        raise StructuralUncertaintyError(f"{label}.dataset does not match spec")
    model = _text(document.get("model"), f"{label}.model")
    provenance = _provenance(document, label)
    rows = document.get("regions")
    if not isinstance(rows, list):
        raise StructuralUncertaintyError(f"{label}.regions must be a list")

    by_id: dict[str, dict[str, Any]] = {}
    for raw in rows:
        if not isinstance(raw, dict):
            raise StructuralUncertaintyError(f"{label}.regions entries must be objects")
        region_id = _text(raw.get("id"), f"{label}.regions[].id")
        if region_id in by_id:
            raise StructuralUncertaintyError(f"{label} has duplicate region {region_id}")
        by_id[region_id] = dict(raw)

    expected = set(expected_ids)
    observed = set(by_id)
    if observed != expected:
        raise StructuralUncertaintyError(
            f"{label} region IDs do not match spec; "
            f"missing={sorted(expected-observed)}, extra={sorted(observed-expected)}"
        )
    return {"model": model, "provenance": provenance, "regions": by_id}


def _score_rows(
    rows: Mapping[str, Mapping[str, Any]],
    ordered_ids: Sequence[str],
    *,
    label: str,
) -> tuple[list[float], list[float], list[str]]:
    boundary: list[float] = []
    component: list[float] = []
    reasons: list[str] = []

    for region_id in ordered_ids:
        row = rows[region_id]
        if row.get("status") != "ok":
            reasons.append(f"{label} region {region_id} status is not ok")
            continue
        metrics = row.get("metrics")
        if not isinstance(metrics, dict):
            reasons.append(f"{label} region {region_id} has no metrics")
            continue
        b = metrics.get(BOUNDARY_METRIC)
        c = metrics.get(COMPONENT_METRIC)
        if (
            type(b) not in (int, float)
            or not math.isfinite(float(b))
            or float(b) < 0.0
        ):
            reasons.append(
                f"{label} region {region_id} has invalid {BOUNDARY_METRIC}"
            )
            continue
        if (
            type(c) not in (int, float)
            or not math.isfinite(float(c))
            or not 0.0 <= float(c) <= 1.0
        ):
            reasons.append(
                f"{label} region {region_id} has invalid {COMPONENT_METRIC}"
            )
            continue
        boundary.append(float(b))
        component.append(0.0 if math.isclose(float(c), 1.0, abs_tol=1e-12) else 1.0)

    return boundary, component, reasons


def _conformal_upper(scores: Sequence[float], alpha: float) -> tuple[float | None, int]:
    """Finite-sample one-sided split-conformal upper quantile.

    The standard corrected rank is ceil((n + 1) * (1 - alpha)). When that rank
    is n + 1 there is no finite distribution-free upper bound from the supplied
    calibration sample, so this function returns None rather than pretending
    the calibration is informative.
    """
    n = len(scores)
    if n == 0:
        return None, 0
    rank = int(math.ceil((n + 1) * (1.0 - alpha)))
    if rank > n:
        return None, rank
    ordered = sorted(float(v) for v in scores)
    return ordered[rank - 1], rank


def evaluate(
    spec_document: Mapping[str, Any],
    calibration_document: Mapping[str, Any],
    test_document: Mapping[str, Any],
) -> dict[str, Any]:
    spec = validate_spec(spec_document)
    calibration = _validate_results(
        calibration_document,
        label="calibration",
        dataset=spec["calibration"]["dataset"],
        expected_ids=spec["calibration"]["region_ids"],
    )
    test = _validate_results(
        test_document,
        label="test",
        dataset=spec["test"]["dataset"],
        expected_ids=spec["test"]["region_ids"],
    )

    reasons: list[str] = []
    if calibration["model"] != test["model"]:
        reasons.append("calibration and test model names differ")
    if calibration["provenance"] != test["provenance"]:
        reasons.append("calibration and test model provenance differs")

    cal_boundary, cal_component, cal_reasons = _score_rows(
        calibration["regions"], spec["calibration"]["region_ids"], label="calibration"
    )
    test_boundary, test_component, test_reasons = _score_rows(
        test["regions"], spec["test"]["region_ids"], label="test"
    )
    reasons.extend(cal_reasons)
    reasons.extend(test_reasons)

    complete = (
        not reasons
        and len(cal_boundary) == len(spec["calibration"]["region_ids"])
        and len(test_boundary) == len(spec["test"]["region_ids"])
    )

    boundary_q: float | None = None
    component_q: float | None = None
    boundary_rank = component_rank = 0
    boundary_coverage: float | None = None
    component_coverage: float | None = None
    nominal = 1.0 - spec["alpha"]

    if complete:
        boundary_q, boundary_rank = _conformal_upper(cal_boundary, spec["alpha"])
        component_q, component_rank = _conformal_upper(cal_component, spec["alpha"])
        if boundary_q is None or component_q is None:
            reasons.append(
                "calibration sample is too small for a finite bound at the "
                f"preregistered alpha={spec['alpha']}"
            )
        else:
            boundary_coverage = sum(v <= boundary_q for v in test_boundary) / len(
                test_boundary
            )
            component_coverage = sum(v <= component_q for v in test_component) / len(
                test_component
            )

    boundary_vacuous = (
        boundary_q is None
        or boundary_q > spec["max_nonvacuous_boundary_voxels"]
    )
    component_vacuous = component_q is None or component_q >= 1.0
    vacuous = boundary_vacuous or component_vacuous
    if boundary_q is not None and boundary_vacuous:
        reasons.append(
            "boundary conformal radius exceeds preregistered nonvacuous limit"
        )
    if component_q is not None and component_vacuous:
        reasons.append(
            "component conformal bound permits a completely missed truth component"
        )

    boundary_verified = (
        boundary_coverage is not None and boundary_coverage + 1e-12 >= nominal
    )
    component_verified = (
        component_coverage is not None and component_coverage + 1e-12 >= nominal
    )
    if boundary_coverage is not None and not boundary_verified:
        reasons.append("test boundary coverage is below the nominal level")
    if component_coverage is not None and not component_verified:
        reasons.append("test component coverage is below the nominal level")

    proof_gate_pass = (
        complete
        and not vacuous
        and boundary_verified
        and component_verified
        and not reasons
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "tool": "scroliq-segmentation-uq",
        "method": METHOD,
        "spec_sha256": digest(spec_document),
        "calibration_results_sha256": digest(calibration_document),
        "test_results_sha256": digest(test_document),
        "model": {
            "name": calibration["model"],
            "provenance": calibration["provenance"],
        },
        "alpha": spec["alpha"],
        "nominal_coverage": nominal,
        "calibration": {
            "dataset": spec["calibration"]["dataset"],
            "regions": len(spec["calibration"]["region_ids"]),
            "boundary_rank": boundary_rank,
            "component_rank": component_rank,
        },
        "boundary": {
            "metric": BOUNDARY_METRIC,
            "upper_voxels": boundary_q,
            "max_nonvacuous_voxels": spec["max_nonvacuous_boundary_voxels"],
            "test_empirical_coverage": boundary_coverage,
            "coverage_verified": boundary_verified,
            "vacuous": boundary_vacuous,
        },
        "component": {
            "metric": COMPONENT_METRIC,
            "nonconformity": "0=all truth components have support; 1=at least one has none",
            "upper": component_q,
            "test_empirical_coverage": component_coverage,
            "coverage_verified": component_verified,
            "vacuous": component_vacuous,
        },
        "vacuous": vacuous,
        "proof_gate": "SURFACE_STRUCTURAL_UQ_NONVACUOUS",
        "proof_gate_pass": proof_gate_pass,
        "reasons": reasons,
        "limitations": (
            "Split-conformal coverage assumes exchangeable calibration/test regions. "
            "This audit detects complete disconnected-component omission and p95 "
            "boundary error; it does not prove topology, sheet identity, readability, "
            "or coverage under distribution shift."
        ),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Audit held-out segmentation boundary and missing-component uncertainty "
            "with finite-sample split conformal bounds."
        )
    )
    parser.add_argument("--spec", required=True)
    parser.add_argument("--calibration", help="calibration segmentation results JSON")
    parser.add_argument("--test", help="test segmentation results JSON")
    parser.add_argument("--print-spec-hash", action="store_true")
    parser.add_argument("--out", help="new output JSON; refuses overwrite")
    parser.add_argument("--format", choices=("text", "json", "github"), default="text")
    args = parser.parse_args(argv)

    try:
        spec_path = Path(args.spec)
        spec_document = _load_object(spec_path, "spec")
        validate_spec(spec_document)
        if args.print_spec_hash:
            if args.calibration or args.test or args.out:
                parser.error(
                    "--print-spec-hash cannot be combined with "
                    "--calibration/--test/--out"
                )
            print(digest(spec_document))
            return 0
        if not args.calibration or not args.test:
            parser.error("--calibration and --test are required")
        calibration_document = _load_object(Path(args.calibration), "calibration")
        test_document = _load_object(Path(args.test), "test")
        report = evaluate(spec_document, calibration_document, test_document)
    except (OSError, StructuralUncertaintyError, ValueError) as exc:
        parser.error(str(exc))

    encoded = json.dumps(report, indent=2, allow_nan=False) + "\n"
    if args.out:
        try:
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            with out.open("x", encoding="utf-8") as fh:
                fh.write(encoded)
        except OSError as exc:
            parser.error(str(exc))

    if args.format == "json":
        print(encoded, end="")
    elif args.format == "github":
        if report["proof_gate_pass"]:
            print(
                "::notice title=SEGMENTATION_UQ_PASS::"
                f"boundary_q={report['boundary']['upper_voxels']} "
                f"component_q={report['component']['upper']}"
            )
        else:
            for reason in report["reasons"] or ["structural uncertainty gate failed"]:
                print(f"::error title=SEGMENTATION_UQ_NOT_READY::{reason}")
    else:
        verdict = "PASS" if report["proof_gate_pass"] else "NOT READY"
        print(f"Structural segmentation uncertainty: {verdict}")
        print(
            f"boundary_q={report['boundary']['upper_voxels']} "
            f"component_q={report['component']['upper']} "
            f"vacuous={report['vacuous']}"
        )
        for reason in report["reasons"]:
            print(f"- {reason}")

    return 0 if report["proof_gate_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
