"""Held-out validation for independently established sparse winding relations.

The evaluator measures signed turn-separation error on frozen pairwise
relationships. Pairwise deltas are deliberate: a winding solver may choose a
different global turn-zero convention while still assigning every physical
sheet correctly. A relation therefore grades the physically meaningful
quantity turn(b) - turn(a), without rewarding or penalizing a harmless global
gauge shift.

The reference specification must be frozen before candidate inference and must
bind an independently established evidence source by SHA-256. This module can
verify that declaration, the frozen-spec hash, and held-out relation IDs. It
cannot independently prove that the reference author truly avoided seeing the
candidate output; that remains a provenance obligation of the published
campaign.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from statistics import median
from typing import Any


SCHEMA_VERSION = 1
SPEC_DIAGNOSTIC = "winding-validation-spec"
PREDICTION_DIAGNOSTIC = "winding-validation-predictions"
TOOL = "scroliq-winding-validate"
COORDINATE_SYSTEM = "base_voxel_xyz"
TURN_SEMANTICS = "signed_pairwise_delta_turns"
REFERENCE_KINDS = {
    "manual-independent",
    "physical-ct",
    "external-heldout",
    "challenge-ground-truth",
}


def digest(document: dict[str, Any]) -> str:
    """Canonical JSON SHA-256 used to bind predictions to the frozen spec."""
    return hashlib.sha256(
        json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _name(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"{field} must be lowercase 64-hex sha256")
    return value


def _ids(values: Any, field: str) -> list[str]:
    if not isinstance(values, list):
        raise ValueError(f"{field} must be a list")
    result = [_name(value, field) for value in values]
    if len(set(result)) != len(result):
        raise ValueError(f"{field} contains duplicate IDs")
    return result


def _turn(value: Any, field: str) -> int:
    if type(value) is not int:
        raise ValueError(f"{field} must be an integer number of turns")
    return value


def _xyz(value: Any, field: str) -> list[float]:
    if (
        not isinstance(value, list)
        or len(value) != 3
        or any(type(item) not in (int, float) for item in value)
    ):
        raise ValueError(f"{field} must contain three finite XYZ values")
    try:
        result = [float(item) for item in value]
    except OverflowError as exc:
        raise ValueError(f"{field} is outside numeric range") from exc
    if not all(math.isfinite(item) for item in result):
        raise ValueError(f"{field} must contain three finite XYZ values")
    return result


def _validate_spec(
    spec: dict[str, Any],
) -> tuple[dict[str, Any], list[str], dict[str, dict[str, Any]]]:
    if not isinstance(spec, dict):
        raise ValueError("specification must be an object")
    if (
        type(spec.get("schema_version")) is not int
        or spec["schema_version"] != SCHEMA_VERSION
    ):
        raise ValueError("schema_version must be 1")
    if spec.get("diagnostic") != SPEC_DIAGNOSTIC:
        raise ValueError(f"diagnostic must be {SPEC_DIAGNOSTIC}")
    if spec.get("status") != "frozen-before-prediction":
        raise ValueError("spec status must be frozen-before-prediction")
    if spec.get("coordinate_system") != COORDINATE_SYSTEM:
        raise ValueError(f"coordinate_system must be {COORDINATE_SYSTEM}")
    if spec.get("turn_semantics") != TURN_SEMANTICS:
        raise ValueError(f"turn_semantics must be {TURN_SEMANTICS}")

    _name(spec.get("volume_root"), "volume_root")

    evidence = spec.get("reference_evidence")
    if not isinstance(evidence, dict):
        raise ValueError("reference_evidence must be an object")
    source_kind = evidence.get("source_kind")
    if source_kind not in REFERENCE_KINDS:
        raise ValueError(
            "reference_evidence.source_kind must be one of "
            + ", ".join(sorted(REFERENCE_KINDS))
        )
    _name(evidence.get("method"), "reference_evidence.method")
    _sha256(evidence.get("source_sha256"), "reference_evidence.source_sha256")
    if evidence.get("established_without_candidate_output") is not True:
        raise ValueError(
            "reference_evidence.established_without_candidate_output must be true"
        )
    if evidence.get("candidate_output_observed_before_freeze") is not False:
        raise ValueError(
            "reference_evidence.candidate_output_observed_before_freeze must be false"
        )

    fit_relation_ids = _ids(spec.get("fit_relation_ids"), "fit_relation_ids")
    fit_set = set(fit_relation_ids)

    targets = spec.get("targets")
    if not isinstance(targets, list) or not targets:
        raise ValueError("targets must be a non-empty list")

    expected: dict[str, dict[str, Any]] = {}
    for target in targets:
        if not isinstance(target, dict):
            raise ValueError("target must be an object")
        identifier = _name(target.get("id"), "target id")
        if identifier in expected:
            raise ValueError("duplicate target id")
        if identifier in fit_set:
            raise ValueError("held-out target overlaps fit_relation_ids")

        a = target.get("a")
        b = target.get("b")
        if not isinstance(a, dict) or not isinstance(b, dict):
            raise ValueError("target a and b must be objects")
        a_id = _name(a.get("id"), "target a.id")
        b_id = _name(b.get("id"), "target b.id")
        if a_id == b_id:
            raise ValueError("target endpoints must be distinct")
        a_xyz = _xyz(a.get("xyz"), "target a.xyz")
        b_xyz = _xyz(b.get("xyz"), "target b.xyz")
        reference_delta = _turn(
            target.get("reference_delta_turns"),
            "reference_delta_turns",
        )
        region_id = target.get("region_id")
        if region_id is not None:
            region_id = _name(region_id, "region_id")

        expected[identifier] = {
            "id": identifier,
            "a": {"id": a_id, "xyz": a_xyz},
            "b": {"id": b_id, "xyz": b_xyz},
            "reference_delta_turns": reference_delta,
            "region_id": region_id,
        }

    return evidence, fit_relation_ids, expected


def _validate_prediction_header(
    spec: dict[str, Any],
    prediction: dict[str, Any],
    fit_relation_ids: list[str],
    expected: dict[str, dict[str, Any]],
) -> tuple[str, list[str]]:
    if not isinstance(prediction, dict):
        raise ValueError("prediction must be an object")
    if (
        type(prediction.get("schema_version")) is not int
        or prediction["schema_version"] != SCHEMA_VERSION
    ):
        raise ValueError("prediction schema_version must be 1")
    if prediction.get("diagnostic") != PREDICTION_DIAGNOSTIC:
        raise ValueError(
            f"prediction diagnostic must be {PREDICTION_DIAGNOSTIC}"
        )
    if prediction.get("coordinate_system") != COORDINATE_SYSTEM:
        raise ValueError(
            f"prediction coordinate_system must be {COORDINATE_SYSTEM}"
        )
    if prediction.get("turn_semantics") != TURN_SEMANTICS:
        raise ValueError(
            f"prediction turn_semantics must be {TURN_SEMANTICS}"
        )
    if prediction.get("volume_root") != spec.get("volume_root"):
        raise ValueError("exact volume_root mismatch")
    if prediction.get("spec_sha256") != digest(spec):
        raise ValueError(
            "spec_sha256 mismatch: evaluation specification changed"
        )

    candidate_method = _name(
        prediction.get("candidate_method"), "candidate_method"
    )
    _sha256(
        prediction.get("candidate_artifact_sha256"),
        "candidate_artifact_sha256",
    )

    used = _ids(prediction.get("used_reference_ids"), "used_reference_ids")
    fit_set = set(fit_relation_ids)
    target_set = set(expected)
    if set(used) & target_set:
        raise ValueError(
            "held-out target relation appears in used_reference_ids"
        )
    if set(used) - fit_set:
        raise ValueError(
            "used_reference_ids contains undeclared fit relation"
        )
    return candidate_method, used


def evaluate(
    spec: dict[str, Any], prediction: dict[str, Any]
) -> dict[str, Any]:
    """Score one candidate against a frozen independent relation set."""
    evidence, fit_relation_ids, expected = _validate_spec(spec)
    candidate_method, used_reference_ids = _validate_prediction_header(
        spec,
        prediction,
        fit_relation_ids,
        expected,
    )

    outputs = prediction.get("predictions")
    if not isinstance(outputs, list):
        raise ValueError("predictions must be a list")

    observed: dict[str, dict[str, Any]] = {}
    allowed_status = {"ok", "suspended", "unscorable", "failed"}
    for output in outputs:
        if not isinstance(output, dict):
            raise ValueError("prediction row must be an object")
        identifier = _name(output.get("id"), "prediction id")
        if identifier not in expected or identifier in observed:
            raise ValueError("unknown or duplicate prediction id")
        status = output.get("status")
        if status not in allowed_status:
            raise ValueError(
                "prediction status must be ok, suspended, unscorable, or failed"
            )
        if status == "ok":
            delta = _turn(
                output.get("predicted_delta_turns"),
                "predicted_delta_turns",
            )
            if output.get("reason") not in (None, ""):
                raise ValueError(
                    "ok prediction cannot also supply a reason"
                )
            observed[identifier] = {
                "status": "ok",
                "predicted_delta_turns": delta,
            }
        else:
            if output.get("predicted_delta_turns") is not None:
                raise ValueError(
                    f"{status} prediction cannot also supply "
                    "predicted_delta_turns"
                )
            observed[identifier] = {
                "status": status,
                "reason": _name(
                    output.get("reason"), f"{status} reason"
                ),
            }

    rows: list[dict[str, Any]] = []
    signed_errors: list[int] = []
    exact = one_wrap = multi_wrap = 0
    for identifier in sorted(expected):
        reference = expected[identifier]
        output = observed.get(identifier, {"status": "missing"})
        row = {
            **reference,
            **output,
            "exact": False,
            "error_class": None,
        }
        if output["status"] == "ok":
            error = (
                output["predicted_delta_turns"]
                - reference["reference_delta_turns"]
            )
            abs_error = abs(error)
            if abs_error == 0:
                error_class = "exact"
                exact += 1
            elif abs_error == 1:
                error_class = "catastrophic-one-wrap-hop"
                one_wrap += 1
            else:
                error_class = "multi-wrap-error"
                multi_wrap += 1
            row.update(
                signed_error_turns=error,
                absolute_error_turns=abs_error,
                exact=abs_error == 0,
                error_class=error_class,
            )
            signed_errors.append(error)
        rows.append(row)

    expected_n = len(rows)
    scored_n = len(signed_errors)
    status_counts = {
        state: sum(row["status"] == state for row in rows)
        for state in ("ok", "suspended", "unscorable", "failed", "missing")
    }
    signed_histogram = {
        str(value): signed_errors.count(value)
        for value in sorted(set(signed_errors))
    }
    absolute_errors = [abs(value) for value in signed_errors]
    absolute_histogram = {
        str(value): absolute_errors.count(value)
        for value in sorted(set(absolute_errors))
    }

    complete = scored_n == expected_n
    pass_all = exact == expected_n
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "status": "measured" if complete else "incomplete",
        "verdict": "pass" if pass_all else "fail",
        "volume_root": spec["volume_root"],
        "coordinate_system": COORDINATE_SYSTEM,
        "turn_semantics": TURN_SEMANTICS,
        "spec_sha256": digest(spec),
        "prediction_sha256": digest(prediction),
        "candidate_method": candidate_method,
        "candidate_artifact_sha256": prediction[
            "candidate_artifact_sha256"
        ],
        "reference_evidence": dict(evidence),
        "heldout_contract": {
            "fit_relation_ids": list(fit_relation_ids),
            "used_reference_ids": list(used_reference_ids),
            "heldout_relation_ids": sorted(expected),
            "target_overlap_with_used_reference_ids": [],
            "non_ok_targets_remain_in_denominator": True,
        },
        "expected": expected_n,
        "scored": scored_n,
        "scorable_rate": scored_n / expected_n,
        "status_counts": status_counts,
        "exact": exact,
        "exact_rate_all_targets": exact / expected_n,
        "exact_rate_scored_only": (
            exact / scored_n if scored_n else None
        ),
        "catastrophic_one_wrap_hops": one_wrap,
        "catastrophic_one_wrap_hop_rate_all_targets": (
            one_wrap / expected_n
        ),
        "multi_wrap_errors": multi_wrap,
        "multi_wrap_error_rate_all_targets": multi_wrap / expected_n,
        "signed_error_histogram_turns": signed_histogram,
        "absolute_error_histogram_turns": absolute_histogram,
        "scored_only_median_absolute_error_turns": (
            median(absolute_errors) if absolute_errors else None
        ),
        "scored_only_max_absolute_error_turns": (
            max(absolute_errors) if absolute_errors else None
        ),
        "limitations": [
            (
                "The metric validates signed turn separation on frozen sparse "
                "relationships. It does not validate surface coverage, local "
                "mesh quality, CT support, flattening distortion, ink, or "
                "legibility."
            ),
            (
                "The reference source is hash-bound and must declare that it "
                "was established without candidate output. ScrolIQ verifies "
                "the declaration and held-out IDs but cannot independently "
                "prove the human or external process that created the "
                "reference."
            ),
            (
                "The evaluator assumes the candidate adapter mapped each "
                "physical reference relationship to the reported "
                "predicted_delta_turns correctly. That correspondence should "
                "be published as separate provenance when it is not intrinsic "
                "to the candidate format."
            ),
            (
                "Pairwise deltas intentionally ignore a global integer gauge "
                "shift; such a shift changes the arbitrary turn-zero label but "
                "not physical sheet identity."
            ),
        ],
        "targets": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True)
    parser.add_argument(
        "--predictions",
        help="candidate relation predictions; omit with --print-spec-hash",
    )
    parser.add_argument("--print-spec-hash", action="store_true")
    parser.add_argument("--out", help="new report path; refuses overwrite")
    args = parser.parse_args(argv)

    try:
        spec = json.loads(
            Path(args.spec).read_text(encoding="utf-8")
        )
        _validate_spec(spec)
        if args.print_spec_hash:
            print(digest(spec))
            return 0
        if not args.predictions:
            parser.error(
                "--predictions is required unless --print-spec-hash is used"
            )
        prediction = json.loads(
            Path(args.predictions).read_text(encoding="utf-8")
        )
        result = evaluate(spec, prediction)
        rendered = (
            json.dumps(result, indent=2, allow_nan=False) + "\n"
        )
        if args.out:
            with Path(args.out).open("x", encoding="utf-8") as handle:
                handle.write(rendered)
        print(rendered, end="")
        return 0 if result["verdict"] == "pass" else 1
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
