"""Compare a reviewed winding rerun against its exact frozen baseline."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

TOOL = "scroliq-winding-review-compare"
SCHEMA_VERSION = 1
APPLICATION_TOOL = "scroliq-winding-apply-review"
APPLICATION_KIND = "winding-review-application"
RELATIVE_HASH_KEY = "relative_windings.json"

LIMITATION = (
    "This comparison measures the effect of reviewed winding-number edits on "
    "the pre-registered winding-attachment diagnostic while holding attachment "
    "geometry and other declared inputs fixed. A lower residual count does not "
    "by itself prove physical correctness or downstream text improvement."
)


class ReviewCompareError(ValueError):
    """The before/after evidence cannot be compared safely."""


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json_bytes(value: Any) -> bytes:
    try:
        text = json.dumps(
            value,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ReviewCompareError(f"cannot serialize comparison: {exc}") from exc
    return (text + "\n").encode("utf-8")


def _digest(value: Any, *, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise ReviewCompareError(f"{label} must be lowercase 64-hex")
    return value


def _number(value: Any, *, label: str) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
    ):
        raise ReviewCompareError(f"{label} must be a finite number")
    return float(value)


def _integer(value: Any, *, label: str) -> int:
    number = _number(value, label=label)
    if not number.is_integer():
        raise ReviewCompareError(f"{label} must be an integer")
    return int(number)


def _result_inputs(result: Any, *, label: str) -> tuple[dict[str, Any], dict[str, str]]:
    if not isinstance(result, dict):
        raise ReviewCompareError(f"{label} result must be a JSON object")
    inputs = result.get("inputs")
    if not isinstance(inputs, dict):
        raise ReviewCompareError(f"{label} result is missing inputs")
    hashes = inputs.get("sha256")
    if not isinstance(hashes, dict) or not hashes:
        raise ReviewCompareError(f"{label} result is missing inputs.sha256")

    validated: dict[str, str] = {}
    for name, digest in hashes.items():
        if not isinstance(name, str) or not name:
            raise ReviewCompareError(f"{label} input hash key must be non-empty")
        validated[name] = _digest(
            digest,
            label=f"{label}.inputs.sha256[{name!r}]",
        )
    return inputs, validated


def _summary(result: dict[str, Any], *, label: str) -> dict[str, Any]:
    summary = result.get("summary")
    if not isinstance(summary, dict):
        raise ReviewCompareError(f"{label} result is missing summary")
    required = (
        "constraints",
        "independent_cycles",
        "residual_0",
        "residual_abs_1",
        "residual_abs_ge_2",
        "edges_with_disagreeing_points",
    )
    out = dict(summary)
    for key in required:
        out[key] = _integer(summary.get(key), label=f"{label}.summary.{key}")
    return out


def _control(result: dict[str, Any], *, label: str) -> dict[str, Any]:
    control = result.get("control")
    if not isinstance(control, dict):
        raise ReviewCompareError(f"{label} result is missing control")
    out = dict(control)
    for key in ("trials", "detected", "localized"):
        out[key] = _integer(control.get(key), label=f"{label}.control.{key}")
    for key in ("detection_rate", "localization_rate"):
        value = control.get(key)
        out[key] = None if value is None else _number(
            value, label=f"{label}.control.{key}"
        )
    return out


def _review_targets(result: dict[str, Any], *, label: str) -> tuple[list[dict[str, Any]], set[tuple[str, str]]]:
    queue = result.get("review_queue")
    if not isinstance(queue, list):
        raise ReviewCompareError(f"{label} result review_queue must be a list")
    targets: set[tuple[str, str]] = set()
    rows: list[dict[str, Any]] = []
    for index, row in enumerate(queue):
        if not isinstance(row, dict):
            raise ReviewCompareError(f"{label}.review_queue[{index}] must be an object")
        frame = row.get("frame")
        point_id = row.get("point_id")
        if not isinstance(frame, str) or not frame:
            raise ReviewCompareError(
                f"{label}.review_queue[{index}].frame must be non-empty"
            )
        if not isinstance(point_id, str) or not point_id:
            raise ReviewCompareError(
                f"{label}.review_queue[{index}].point_id must be non-empty"
            )
        targets.add((frame, point_id))
        rows.append(row)
    return rows, targets


def _sorted_targets(targets: set[tuple[str, str]]) -> list[dict[str, str]]:
    return [
        {"frame": frame, "point_id": point_id}
        for frame, point_id in sorted(targets)
    ]


def _validate_application(
    application: Any,
    *,
    application_sha256: str,
    before_result_sha256: str,
) -> tuple[str, str, list[tuple[str, str]]]:
    _digest(application_sha256, label="application_sha256")
    if not isinstance(application, dict):
        raise ReviewCompareError("application manifest must be a JSON object")
    if application.get("schema_version") != 1:
        raise ReviewCompareError("unsupported application schema_version")
    if (
        application.get("tool") != APPLICATION_TOOL
        or application.get("kind") != APPLICATION_KIND
    ):
        raise ReviewCompareError("input is not a winding review application manifest")

    diagnostic_sha = _digest(
        application.get("diagnostic_source_sha256"),
        label="application.diagnostic_source_sha256",
    )
    if diagnostic_sha != before_result_sha256:
        raise ReviewCompareError(
            "before result SHA-256 does not match the diagnostic bound by the application"
        )
    source_sha = _digest(
        application.get("source_sha256"),
        label="application.source_sha256",
    )
    corrected_sha = _digest(
        application.get("corrected_sha256"),
        label="application.corrected_sha256",
    )
    count = _integer(
        application.get("corrections_applied"),
        label="application.corrections_applied",
    )
    changes = application.get("changes")
    if count <= 0 or not isinstance(changes, list) or len(changes) != count:
        raise ReviewCompareError(
            "application must contain one or more declared correction changes"
        )

    targets: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for index, change in enumerate(changes):
        if not isinstance(change, dict):
            raise ReviewCompareError(f"application.changes[{index}] must be an object")
        frame = change.get("frame")
        point_id = change.get("point_id")
        if not isinstance(frame, str) or not frame.startswith("relative:"):
            raise ReviewCompareError(
                f"application.changes[{index}].frame must be a relative frame"
            )
        if not isinstance(point_id, str) or not point_id:
            raise ReviewCompareError(
                f"application.changes[{index}].point_id must be non-empty"
            )
        before = _integer(
            change.get("before_winding"),
            label=f"application.changes[{index}].before_winding",
        )
        after = _integer(
            change.get("after_winding"),
            label=f"application.changes[{index}].after_winding",
        )
        if before == after:
            raise ReviewCompareError(
                f"application.changes[{index}] does not change the winding"
            )
        target = (frame, point_id)
        if target in seen:
            raise ReviewCompareError(
                f"application contains duplicate correction target {frame}/{point_id}"
            )
        seen.add(target)
        targets.append(target)

    return source_sha, corrected_sha, targets


def _delta(after: float | int | None, before: float | int | None) -> float | int | None:
    if after is None or before is None:
        return None
    return after - before


def compare_review_rerun(
    before_result: Any,
    before_attachments: Any,
    after_result: Any,
    after_attachments: Any,
    application: Any,
    *,
    before_result_sha256: str,
    before_attachments_sha256: str,
    after_result_sha256: str,
    after_attachments_sha256: str,
    application_sha256: str,
) -> dict[str, Any]:
    """Validate the controlled rerun and return a deterministic comparison."""
    before_result_sha256 = _digest(
        before_result_sha256, label="before_result_sha256"
    )
    before_attachments_sha256 = _digest(
        before_attachments_sha256, label="before_attachments_sha256"
    )
    after_result_sha256 = _digest(
        after_result_sha256, label="after_result_sha256"
    )
    after_attachments_sha256 = _digest(
        after_attachments_sha256, label="after_attachments_sha256"
    )

    source_sha, corrected_sha, corrected_targets = _validate_application(
        application,
        application_sha256=application_sha256,
        before_result_sha256=before_result_sha256,
    )

    before_inputs, before_hashes = _result_inputs(before_result, label="before")
    after_inputs, after_hashes = _result_inputs(after_result, label="after")

    if before_hashes.get(RELATIVE_HASH_KEY) != source_sha:
        raise ReviewCompareError(
            "before result relative_windings.json hash does not match application source"
        )
    if after_hashes.get(RELATIVE_HASH_KEY) != corrected_sha:
        raise ReviewCompareError(
            "after result relative_windings.json hash does not match corrected output"
        )
    if set(before_hashes) != set(after_hashes):
        raise ReviewCompareError("before/after diagnostic input hash keys differ")
    for name in sorted(before_hashes):
        if name == RELATIVE_HASH_KEY:
            continue
        if before_hashes[name] != after_hashes[name]:
            raise ReviewCompareError(
                f"non-correction input {name!r} changed between diagnostic runs"
            )

    before_input_meta = {k: v for k, v in before_inputs.items() if k != "sha256"}
    after_input_meta = {k: v for k, v in after_inputs.items() if k != "sha256"}
    if before_input_meta != after_input_meta:
        raise ReviewCompareError(
            "diagnostic input/attachment accounting changed between runs"
        )

    before_constants = before_result.get("constants")
    after_constants = after_result.get("constants")
    if not isinstance(before_constants, dict) or not before_constants:
        raise ReviewCompareError("before result is missing preregistered constants")
    if before_constants != after_constants:
        raise ReviewCompareError("preregistered constants changed between runs")

    if not isinstance(before_attachments, list) or not isinstance(after_attachments, list):
        raise ReviewCompareError("before/after attachments must be JSON lists")
    if before_attachments != after_attachments:
        raise ReviewCompareError(
            "patch-attachment geometry changed between runs; comparison is not controlled"
        )

    before_summary = _summary(before_result, label="before")
    after_summary = _summary(after_result, label="after")
    before_control = _control(before_result, label="before")
    after_control = _control(after_result, label="after")
    before_rows, before_targets = _review_targets(before_result, label="before")
    after_rows, after_targets = _review_targets(after_result, label="after")

    before_decision = before_result.get("decision")
    after_decision = after_result.get("decision")
    if not isinstance(before_decision, dict) or not isinstance(after_decision, dict):
        raise ReviewCompareError("before/after results must contain decision objects")
    before_verdict = before_decision.get("verdict")
    after_verdict = after_decision.get("verdict")
    if not isinstance(before_verdict, str) or not isinstance(after_verdict, str):
        raise ReviewCompareError("before/after decision verdicts must be strings")

    corrected_set = set(corrected_targets)
    corrected_disposition = []
    for frame, point_id in sorted(corrected_set):
        corrected_disposition.append(
            {
                "frame": frame,
                "point_id": point_id,
                "before_flagged": (frame, point_id) in before_targets,
                "after_flagged": (frame, point_id) in after_targets,
                "disposition": (
                    "still_flagged"
                    if (frame, point_id) in after_targets
                    else "not_flagged_after"
                ),
            }
        )

    metric_names = (
        "constraints",
        "independent_cycles",
        "residual_0",
        "residual_abs_1",
        "residual_abs_ge_2",
        "edges_with_disagreeing_points",
    )
    summary_delta = {
        key: after_summary[key] - before_summary[key]
        for key in metric_names
    }

    control_min = before_constants.get("control_min_detection")
    control_min = _number(
        control_min, label="constants.control_min_detection"
    )
    before_detection = before_control["detection_rate"]
    after_detection = after_control["detection_rate"]

    return {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "kind": "winding-review-before-after",
        "scroll": application.get("scroll"),
        "provenance": {
            "before_result_sha256": before_result_sha256,
            "before_attachments_sha256": before_attachments_sha256,
            "after_result_sha256": after_result_sha256,
            "after_attachments_sha256": after_attachments_sha256,
            "application_sha256": application_sha256,
            "original_relative_windings_sha256": source_sha,
            "corrected_relative_windings_sha256": corrected_sha,
        },
        "controls": {
            "same_non_correction_input_hashes": True,
            "same_input_accounting": True,
            "same_preregistered_constants": True,
            "same_attachment_geometry": True,
            "attachment_rows": len(before_attachments),
        },
        "before": {
            "verdict": before_verdict,
            "primary": before_result.get("primary"),
            "summary": before_summary,
            "control": before_control,
            "flagged_constraints": len(before_rows),
            "flagged_physical_points": len(before_targets),
        },
        "after": {
            "verdict": after_verdict,
            "primary": after_result.get("primary"),
            "summary": after_summary,
            "control": after_control,
            "flagged_constraints": len(after_rows),
            "flagged_physical_points": len(after_targets),
        },
        "delta_after_minus_before": {
            "summary": summary_delta,
            "flagged_constraints": len(after_rows) - len(before_rows),
            "flagged_physical_points": len(after_targets) - len(before_targets),
            "control_detection_rate": _delta(
                after_control["detection_rate"],
                before_control["detection_rate"],
            ),
            "control_localization_rate": _delta(
                after_control["localization_rate"],
                before_control["localization_rate"],
            ),
        },
        "review_queue_change": {
            "resolved_points": _sorted_targets(before_targets - after_targets),
            "introduced_points": _sorted_targets(after_targets - before_targets),
            "persisted_points": _sorted_targets(before_targets & after_targets),
        },
        "corrected_points": corrected_disposition,
        "control_gate": {
            "minimum_detection_rate": control_min,
            "before_passes": (
                before_detection is not None and before_detection >= control_min
            ),
            "after_passes": (
                after_detection is not None and after_detection >= control_min
            ),
        },
        "limitation": LIMITATION,
    }


def _read_json(path: Path, *, label: str) -> tuple[bytes, Any]:
    try:
        raw = path.read_bytes()
        return raw, json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReviewCompareError(f"cannot read {label}: {exc}") from exc


def compare_files(
    before_result_path: str | Path,
    before_attachments_path: str | Path,
    after_result_path: str | Path,
    after_attachments_path: str | Path,
    application_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    out = Path(output_path)
    if out.exists():
        raise ReviewCompareError(f"refusing to overwrite existing output: {out}")

    before_result_raw, before_result = _read_json(
        Path(before_result_path), label="before result"
    )
    before_attachments_raw, before_attachments = _read_json(
        Path(before_attachments_path), label="before attachments"
    )
    after_result_raw, after_result = _read_json(
        Path(after_result_path), label="after result"
    )
    after_attachments_raw, after_attachments = _read_json(
        Path(after_attachments_path), label="after attachments"
    )
    application_raw, application = _read_json(
        Path(application_path), label="application manifest"
    )

    comparison = compare_review_rerun(
        before_result,
        before_attachments,
        after_result,
        after_attachments,
        application,
        before_result_sha256=_sha256(before_result_raw),
        before_attachments_sha256=_sha256(before_attachments_raw),
        after_result_sha256=_sha256(after_result_raw),
        after_attachments_sha256=_sha256(after_attachments_raw),
        application_sha256=_sha256(application_raw),
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(_json_bytes(comparison))
    return comparison


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog=TOOL,
        description=(
            "Verify and compare a post-review winding-attachment rerun against "
            "its exact frozen baseline."
        ),
    )
    parser.add_argument("--before-result", required=True)
    parser.add_argument("--before-attachments", required=True)
    parser.add_argument("--after-result", required=True)
    parser.add_argument("--after-attachments", required=True)
    parser.add_argument("--application", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    try:
        comparison = compare_files(
            args.before_result,
            args.before_attachments,
            args.after_result,
            args.after_attachments,
            args.application,
            args.out,
        )
    except ReviewCompareError as exc:
        print(f"{TOOL}: FAIL: {exc}", file=sys.stderr)
        return 2

    before = comparison["before"]
    after = comparison["after"]
    delta = comparison["delta_after_minus_before"]
    print(
        f"{TOOL}: PASS: residual |r|>=2 "
        f"{before['summary']['residual_abs_ge_2']} -> "
        f"{after['summary']['residual_abs_ge_2']} "
        f"(delta {delta['summary']['residual_abs_ge_2']:+d})"
    )
    print(
        f"flagged physical points: {before['flagged_physical_points']} -> "
        f"{after['flagged_physical_points']}"
    )
    print(
        f"control detection: {before['control']['detection_rate']} -> "
        f"{after['control']['detection_rate']}"
    )
    print(f"output: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
