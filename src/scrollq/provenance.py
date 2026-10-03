"""Machine-checkable provenance and eligibility manifest for the 2027 Grand Prize.

The manifest is deliberately fail-closed: a missing proof is an error when the
published prize rules require that proof. This module does not claim that a
submission is papyrologically legible; it checks provenance/eligibility facts
that can be represented mechanically.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

from zpa.report import validate_report as validate_zpa_report

from .grand_prize import DEFAULT_MANIFEST
from .package_hash import sha256_path
from .recto_coverage import audit_recto_coverage

SCHEMA_VERSION = 5
RULES_URL = "https://scrollprize.org/prizes"
CC_BY_NC_4 = {"CC-BY-NC-4.0", "CC BY-NC 4.0"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
COLUMN_MESH_RE = re.compile(r"^column_(\d{2,})\.tifxyz$")


def _error(errors: list[dict[str, str]], code: str, path: str, message: str) -> None:
    errors.append({"code": code, "path": path, "message": message})


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _index(items: Any, kind: str, errors: list[dict[str, str]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for i, item in enumerate(_as_list(items)):
        path = f"{kind}[{i}]"
        if not isinstance(item, dict):
            _error(errors, "GP_INVALID_RECORD", path, "record must be an object")
            continue
        ident = item.get("id")
        if not isinstance(ident, str) or not ident:
            _error(errors, "GP_MISSING_ID", f"{path}.id", "non-empty id is required")
            continue
        if ident in out:
            _error(errors, "GP_DUPLICATE_ID", f"{path}.id", f"duplicate id {ident!r}")
            continue
        out[ident] = item
    return out


def _eligible_target(scroll_id: str) -> dict[str, Any] | None:
    return next(
        (t for t in DEFAULT_MANIFEST["targets"] if t["scroll"] == scroll_id),
        None,
    )


def _check_sha(
    record: dict[str, Any],
    path: str,
    errors: list[dict[str, str]],
    *,
    required: bool = True,
) -> None:
    value = record.get("sha256")
    if value is None and not required:
        return
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        _error(
            errors,
            "GP_INVALID_SHA256",
            f"{path}.sha256",
            "sha256 must be a lowercase 64-hex digest",
        )


def _check_public_url(
    value: Any, path: str, errors: list[dict[str, str]], code: str
) -> None:
    if not isinstance(value, str) or not value.startswith(("https://", "http://")):
        _error(errors, code, path, "public http(s) URL is required")


def _validate_box(
    box: Any, path: str, errors: list[dict[str, str]]
) -> tuple[tuple[float, ...], tuple[float, ...]] | None:
    if not isinstance(box, dict):
        _error(errors, "GP_INVALID_REGION", path, "region box must be an object")
        return None
    start, stop = box.get("start"), box.get("stop")
    if (
        not isinstance(start, list)
        or not isinstance(stop, list)
        or len(start) != 3
        or len(stop) != 3
        or not all(isinstance(v, (int, float)) for v in start + stop)
    ):
        _error(
            errors,
            "GP_INVALID_REGION",
            path,
            "box start/stop must be numeric [z, y, x] triplets",
        )
        return None
    if not all(float(a) < float(b) for a, b in zip(start, stop)):
        _error(
            errors,
            "GP_INVALID_REGION",
            path,
            "each half-open interval requires start < stop",
        )
        return None
    return tuple(map(float, start)), tuple(map(float, stop))


def _boxes_overlap(
    a: tuple[tuple[float, ...], tuple[float, ...]],
    b: tuple[tuple[float, ...], tuple[float, ...]],
) -> bool:
    # Half-open intervals: touching a boundary is not overlap.
    return all(
        max(a[0][axis], b[0][axis]) < min(a[1][axis], b[1][axis])
        for axis in range(3)
    )


def _check_region_exclusion(
    *,
    render_id: str,
    prediction_id: str,
    model: dict[str, Any],
    region_sets: dict[str, dict[str, Any]],
    datasets: dict[str, dict[str, Any]],
    eligible_volume_id: str,
    errors: list[dict[str, str]],
) -> dict[str, Any]:
    proof: dict[str, Any] = {
        "render_id": render_id,
        "prediction_region_set_id": prediction_id,
        "training_region_set_ids": [],
        "checked_pairs": 0,
        "overlaps": [],
    }
    pred = region_sets.get(prediction_id)
    if pred is None:
        _error(
            errors,
            "GP_MISSING_REGION_SET",
            f"renders[{render_id}].prediction_region_set_id",
            f"unknown region set {prediction_id!r}",
        )
        return proof
    if pred.get("role") != "prediction":
        _error(
            errors,
            "GP_REGION_ROLE",
            f"region_sets[{prediction_id}].role",
            "render prediction region set must have role='prediction'",
        )
    if pred.get("volume_id") != eligible_volume_id:
        _error(
            errors,
            "GP_REGION_VOLUME",
            f"region_sets[{prediction_id}].volume_id",
            "prediction regions must be expressed on the eligible CT volume",
        )
    coord = pred.get("coordinate_space")
    if coord != "level0-voxel-index":
        _error(
            errors,
            "GP_REGION_COORDINATES",
            f"region_sets[{prediction_id}].coordinate_space",
            "leakage checking currently requires level0-voxel-index coordinates",
        )

    pred_boxes = []
    for i, box in enumerate(_as_list(pred.get("boxes"))):
        parsed = _validate_box(
            box, f"region_sets[{prediction_id}].boxes[{i}]", errors
        )
        if parsed:
            pred_boxes.append(parsed)
    if not pred_boxes:
        _error(
            errors,
            "GP_EMPTY_PREDICTION_REGION",
            f"region_sets[{prediction_id}].boxes",
            "at least one prediction box is required",
        )

    training_ids: list[str] = []
    for dataset_id in _as_list(model.get("training_dataset_ids")):
        dataset = datasets.get(dataset_id)
        if dataset is None:
            continue
        region_id = dataset.get("training_region_set_id")
        if region_id:
            training_ids.append(str(region_id))
    proof["training_region_set_ids"] = training_ids
    if not training_ids:
        _error(
            errors,
            "GP_MISSING_TRAINING_REGIONS",
            f"models[{model.get('id')}].training_dataset_ids",
            "every rendered model needs machine-checkable training regions",
        )
        return proof

    for training_id in training_ids:
        train = region_sets.get(training_id)
        if train is None:
            _error(
                errors,
                "GP_MISSING_REGION_SET",
                f"region_sets[{training_id}]",
                f"unknown training region set {training_id!r}",
            )
            continue
        if train.get("role") != "training":
            _error(
                errors,
                "GP_REGION_ROLE",
                f"region_sets[{training_id}].role",
                "training dataset region set must have role='training'",
            )

        # Training on another volume cannot geometrically overlap this exact
        # prediction volume. Same-volume training is checked box-by-box.
        if train.get("volume_id") != eligible_volume_id:
            continue
        if train.get("coordinate_space") != coord:
            _error(
                errors,
                "GP_REGION_COORDINATES",
                f"region_sets[{training_id}].coordinate_space",
                "same-volume training/prediction regions must share a coordinate space",
            )
            continue

        train_boxes = []
        for i, box in enumerate(_as_list(train.get("boxes"))):
            parsed = _validate_box(
                box, f"region_sets[{training_id}].boxes[{i}]", errors
            )
            if parsed:
                train_boxes.append(parsed)
        if not train_boxes:
            _error(
                errors,
                "GP_EMPTY_TRAINING_REGION",
                f"region_sets[{training_id}].boxes",
                "same-volume training region set must contain boxes",
            )
            continue

        for ti, tbox in enumerate(train_boxes):
            for pi, pbox in enumerate(pred_boxes):
                proof["checked_pairs"] += 1
                if _boxes_overlap(tbox, pbox):
                    proof["overlaps"].append(
                        {
                            "training_region_set_id": training_id,
                            "training_box": ti,
                            "prediction_box": pi,
                        }
                    )

    if proof["overlaps"]:
        _error(
            errors,
            "GP_TRAIN_PREDICT_OVERLAP",
            f"renders[{render_id}]",
            (
                "training/prediction region overlap detected "
                f"({len(proof['overlaps'])} pair(s))"
            ),
        )
    return proof


def _check_holdout_exclusion(
    *,
    validation_id: str,
    region_id: str,
    model: dict[str, Any],
    region_sets: dict[str, dict[str, Any]],
    datasets: dict[str, dict[str, Any]],
    errors: list[dict[str, str]],
) -> dict[str, Any]:
    """Prove held-out validation regions do not intersect same-volume training."""

    proof: dict[str, Any] = {
        "validation_id": validation_id,
        "region_set_id": region_id,
        "training_region_set_ids": [],
        "checked_pairs": 0,
        "overlaps": [],
    }
    holdout = region_sets.get(region_id)
    if holdout is None:
        _error(
            errors,
            "GP_MISSING_REGION_SET",
            f"held_out_validations[{validation_id}].region_set_id",
            f"unknown region set {region_id!r}",
        )
        return proof
    if holdout.get("role") != "validation":
        _error(
            errors,
            "GP_REGION_ROLE",
            f"region_sets[{region_id}].role",
            "held-out region set must have role='validation'",
        )
    coord = holdout.get("coordinate_space")
    if coord != "level0-voxel-index":
        _error(
            errors,
            "GP_REGION_COORDINATES",
            f"region_sets[{region_id}].coordinate_space",
            "held-out checking currently requires level0-voxel-index coordinates",
        )

    holdout_boxes = []
    for i, box in enumerate(_as_list(holdout.get("boxes"))):
        parsed = _validate_box(
            box, f"region_sets[{region_id}].boxes[{i}]", errors
        )
        if parsed:
            holdout_boxes.append(parsed)
    if not holdout_boxes:
        _error(
            errors,
            "GP_EMPTY_VALIDATION_REGION",
            f"region_sets[{region_id}].boxes",
            "at least one held-out validation box is required",
        )

    training_ids: list[str] = []
    for dataset_id in _as_list(model.get("training_dataset_ids")):
        dataset = datasets.get(dataset_id)
        if dataset is None:
            continue
        training_id = dataset.get("training_region_set_id")
        if training_id:
            training_ids.append(str(training_id))
    proof["training_region_set_ids"] = training_ids

    for training_id in training_ids:
        train = region_sets.get(training_id)
        if train is None:
            continue
        if train.get("role") != "training":
            _error(
                errors,
                "GP_REGION_ROLE",
                f"region_sets[{training_id}].role",
                "training dataset region set must have role='training'",
            )
        if train.get("volume_id") != holdout.get("volume_id"):
            continue
        if train.get("coordinate_space") != coord:
            _error(
                errors,
                "GP_REGION_COORDINATES",
                f"region_sets[{training_id}].coordinate_space",
                "same-volume training/validation regions must share a coordinate space",
            )
            continue

        train_boxes = []
        for i, box in enumerate(_as_list(train.get("boxes"))):
            parsed = _validate_box(
                box, f"region_sets[{training_id}].boxes[{i}]", errors
            )
            if parsed:
                train_boxes.append(parsed)
        if not train_boxes:
            _error(
                errors,
                "GP_EMPTY_TRAINING_REGION",
                f"region_sets[{training_id}].boxes",
                "same-volume training region set must contain boxes",
            )
            continue

        for ti, tbox in enumerate(train_boxes):
            for vi, vbox in enumerate(holdout_boxes):
                proof["checked_pairs"] += 1
                if _boxes_overlap(tbox, vbox):
                    proof["overlaps"].append(
                        {
                            "training_region_set_id": training_id,
                            "training_box": ti,
                            "validation_box": vi,
                        }
                    )

    if proof["overlaps"]:
        _error(
            errors,
            "GP_TRAIN_HOLDOUT_OVERLAP",
            f"held_out_validations[{validation_id}]",
            (
                "training/held-out validation region overlap detected "
                f"({len(proof['overlaps'])} pair(s))"
            ),
        )
    return proof


def _verify_local_file(
    record: dict[str, Any],
    path: str,
    root_dir: Path | None,
    errors: list[dict[str, str]],
    *,
    path_required: bool = True,
) -> None:
    if root_dir is None:
        return
    rel = record.get("path")
    digest = record.get("sha256")
    if not isinstance(rel, str) or not rel:
        if path_required:
            _error(
                errors,
                "GP_MISSING_PATH",
                f"{path}.path",
                "package-relative path is required",
            )
        return

    candidate = root_dir / rel
    target = candidate.resolve()
    try:
        target.relative_to(root_dir.resolve())
    except ValueError:
        _error(errors, "GP_PATH_ESCAPE", f"{path}.path", "path escapes package root")
        return
    if not candidate.exists():
        _error(errors, "GP_FILE_MISSING", f"{path}.path", f"path not found: {rel}")
        return
    if isinstance(digest, str) and SHA256_RE.fullmatch(digest):
        try:
            actual = sha256_path(candidate)
        except (OSError, ValueError) as exc:
            _error(
                errors,
                "GP_PATH_UNSUPPORTED",
                f"{path}.path",
                f"cannot hash package path {rel}: {exc}",
            )
            return
        if actual != digest:
            _error(
                errors,
                "GP_HASH_MISMATCH",
                f"{path}.sha256",
                f"declared {digest}, actual {actual}",
            )


def _verify_ink_evidence(
    *,
    validation_id: str,
    validation: dict[str, Any],
    model: dict[str, Any],
    root_dir: Path | None,
    errors: list[dict[str, str]],
) -> None:
    """Validate deterministic held-out ink evidence and its falsification controls."""

    p = f"held_out_validations[{validation_id}].ink_evidence"
    evidence = validation.get("ink_evidence")
    if not isinstance(evidence, dict):
        _error(
            errors,
            "GP_INK_EVIDENCE",
            p,
            "scroliq-ink-validate evidence is required for every held-out validation",
        )
        return

    if evidence.get("tool") != "scroliq-ink-validate":
        _error(
            errors,
            "GP_INK_EVIDENCE_TOOL",
            f"{p}.tool",
            "tool must be 'scroliq-ink-validate'",
        )

    checkpoint_sha = evidence.get("model_checkpoint_sha256")
    if not isinstance(checkpoint_sha, str) or not SHA256_RE.fullmatch(checkpoint_sha):
        _error(
            errors,
            "GP_INK_EVIDENCE_CHECKPOINT",
            f"{p}.model_checkpoint_sha256",
            "lowercase 64-hex checkpoint digest is required",
        )
    elif checkpoint_sha != model.get("sha256"):
        _error(
            errors,
            "GP_INK_EVIDENCE_CHECKPOINT",
            f"{p}.model_checkpoint_sha256",
            "ink validation checkpoint must match the submitted model",
        )

    split_id = evidence.get("split_id")
    if not isinstance(split_id, str) or not split_id:
        _error(
            errors,
            "GP_INK_EVIDENCE_SPLIT",
            f"{p}.split_id",
            "non-empty held-out split id is required",
        )
    if evidence.get("held_out") is not True:
        _error(
            errors,
            "GP_INK_EVIDENCE_HELD_OUT",
            f"{p}.held_out",
            "ink validation must explicitly declare a held-out split",
        )
    if evidence.get("training_overlap") != "none":
        _error(
            errors,
            "GP_INK_EVIDENCE_OVERLAP",
            f"{p}.training_overlap",
            "ink validation must explicitly declare no training overlap",
        )
    if evidence.get("known_ground_truth") is not True:
        _error(
            errors,
            "GP_INK_EVIDENCE_GROUND_TRUTH",
            f"{p}.known_ground_truth",
            "ink validation must use known ground truth",
        )
    _check_public_url(
        evidence.get("ground_truth_source_url"),
        f"{p}.ground_truth_source_url",
        errors,
        "GP_INK_EVIDENCE_GROUND_TRUTH",
    )

    window = evidence.get("model_window_voxels_zyx")
    if (
        not isinstance(window, list)
        or len(window) != 3
        or not all(isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in window)
    ):
        _error(
            errors,
            "GP_INK_EVIDENCE_WINDOW",
            f"{p}.model_window_voxels_zyx",
            "positive integer [z,y,x] model window is required",
        )

    control_names = evidence.get("control_names")
    if (
        not isinstance(control_names, list)
        or not control_names
        or not all(isinstance(v, str) and v for v in control_names)
        or len(set(control_names)) != len(control_names)
    ):
        _error(
            errors,
            "GP_INK_EVIDENCE_CONTROLS",
            f"{p}.control_names",
            "at least one unique named falsification control is required",
        )

    evaluated_digest = evidence.get("evaluated_arrays_sha256")
    if (
        not isinstance(evaluated_digest, str)
        or not SHA256_RE.fullmatch(evaluated_digest)
    ):
        _error(
            errors,
            "GP_INK_EVIDENCE_ARRAY_DIGEST",
            f"{p}.evaluated_arrays_sha256",
            "digest of the exact evaluated arrays is required",
        )

    evidence_metrics = evidence.get("metrics")
    if not isinstance(evidence_metrics, dict):
        _error(
            errors,
            "GP_INK_EVIDENCE_METRICS",
            f"{p}.metrics",
            "held-out ink metrics are required",
        )
    else:
        if evidence_metrics.get("both_classes_present") is not True:
            _error(
                errors,
                "GP_INK_EVIDENCE_CLASSES",
                f"{p}.metrics.both_classes_present",
                "validation mask must contain both ink and background",
            )
        for name in ("balanced_accuracy", "false_positive_rate"):
            value = evidence_metrics.get(name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not 0 <= float(value) <= 1
            ):
                _error(
                    errors,
                    "GP_INK_EVIDENCE_METRICS",
                    f"{p}.metrics.{name}",
                    f"{name} must be a numeric value in [0,1]",
                )

    if root_dir is None:
        return

    rel = validation.get("path")
    if not isinstance(rel, str) or not rel:
        return
    target = (root_dir / rel).resolve()
    try:
        target.relative_to(root_dir.resolve())
    except ValueError:
        return
    if not target.is_file():
        return

    try:
        report = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        _error(
            errors,
            "GP_INK_EVIDENCE_REPORT",
            f"held_out_validations[{validation_id}].path",
            f"cannot parse scroliq-ink-validate report: {exc}",
        )
        return

    if report.get("tool") != "scroliq-ink-validate":
        _error(
            errors,
            "GP_INK_EVIDENCE_REPORT",
            f"held_out_validations[{validation_id}].path",
            "held-out artifact was not produced by scroliq-ink-validate",
        )
    if report.get("prize_evidence_ready") is not True:
        _error(
            errors,
            "GP_INK_EVIDENCE_REPORT",
            f"held_out_validations[{validation_id}].path",
            "scroliq-ink-validate report is not prize_evidence_ready",
        )

    report_split = report.get("split") if isinstance(report.get("split"), dict) else {}
    report_model = report.get("model") if isinstance(report.get("model"), dict) else {}
    report_eval = (
        report.get("evaluation") if isinstance(report.get("evaluation"), dict) else {}
    )
    report_controls = _as_list(report.get("controls"))

    mismatches: list[str] = []
    expected_pairs = (
        ("split_id", report_split.get("id"), split_id),
        ("held_out", report_split.get("held_out"), True),
        ("training_overlap", report_split.get("training_overlap"), "none"),
        (
            "known_ground_truth",
            report_split.get("known_ground_truth"),
            True,
        ),
        (
            "ground_truth_source_url",
            report_split.get("ground_truth_source_url"),
            evidence.get("ground_truth_source_url"),
        ),
        (
            "checkpoint_sha256",
            report_model.get("checkpoint_sha256"),
            checkpoint_sha,
        ),
        (
            "model_window_voxels_zyx",
            report_model.get("window_voxels_zyx"),
            window,
        ),
        (
            "evaluated_arrays_sha256",
            report.get("evaluated_arrays_sha256"),
            evaluated_digest,
        ),
    )
    for name, actual, expected in expected_pairs:
        if actual != expected:
            mismatches.append(name)

    actual_controls = sorted(
        str(item.get("name"))
        for item in report_controls
        if isinstance(item, dict) and item.get("name")
    )
    if actual_controls != sorted(control_names if isinstance(control_names, list) else []):
        mismatches.append("control_names")

    if isinstance(evidence_metrics, dict):
        for name in ("balanced_accuracy", "false_positive_rate", "both_classes_present"):
            if report_eval.get(name) != evidence_metrics.get(name):
                mismatches.append(name)

    if mismatches:
        _error(
            errors,
            "GP_INK_EVIDENCE_MISMATCH",
            p,
            "manifest/report mismatch: " + ", ".join(sorted(set(mismatches))),
        )


def validate_manifest(
    manifest: dict[str, Any],
    *,
    root_dir: Path | None = None,
    manifest_sha256: str | None = None,
) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    chains: list[dict[str, Any]] = []
    held_out_proofs: list[dict[str, Any]] = []

    if manifest.get("schema_version") != SCHEMA_VERSION:
        _error(
            errors,
            "GP_SCHEMA_VERSION",
            "schema_version",
            f"expected schema_version={SCHEMA_VERSION}",
        )

    rules = manifest.get("rules")
    if not isinstance(rules, dict) or rules.get("url") != RULES_URL:
        _error(
            errors,
            "GP_RULES_URL",
            "rules.url",
            f"rules.url must be {RULES_URL}",
        )
    if not isinstance(rules, dict) or not isinstance(rules.get("as_of"), str):
        _error(
            errors,
            "GP_RULES_AS_OF",
            "rules.as_of",
            "rules as_of date is required",
        )

    submission = manifest.get("submission")
    if not isinstance(submission, dict):
        submission = {}
        _error(
            errors,
            "GP_SUBMISSION",
            "submission",
            "submission object is required",
        )

    scroll_id = submission.get("scroll_id")
    volume_id = submission.get("eligible_volume_id")
    target = _eligible_target(str(scroll_id)) if scroll_id else None
    if target is None:
        _error(
            errors,
            "GP_SCROLL_NOT_ELIGIBLE",
            "submission.scroll_id",
            "scroll is not in the built-in Grand Prize target manifest",
        )
    elif volume_id != target["volume_id"]:
        _error(
            errors,
            "GP_VOLUME_NOT_ELIGIBLE",
            "submission.eligible_volume_id",
            f"{scroll_id} must use prize volume {target['volume_id']}",
        )

    human_hours = submission.get("human_input_hours")
    if not isinstance(human_hours, (int, float)) or human_hours < 0:
        _error(
            errors,
            "GP_HUMAN_HOURS",
            "submission.human_input_hours",
            "non-negative documented hours are required",
        )
    elif human_hours > 8:
        _error(
            errors,
            "GP_HUMAN_HOURS",
            "submission.human_input_hours",
            "Grand Prize allows at most 8 documented hours of human annotation/input",
        )

    code = manifest.get("code")
    if not isinstance(code, dict):
        code = {}
        _error(
            errors,
            "GP_CODE",
            "code",
            "reproducible code record is required",
        )
    _check_public_url(
        code.get("repository"),
        "code.repository",
        errors,
        "GP_CODE_PUBLIC",
    )
    if not isinstance(code.get("commit"), str) or not COMMIT_RE.fullmatch(
        code["commit"]
    ):
        _error(
            errors,
            "GP_CODE_COMMIT",
            "code.commit",
            "40-hex immutable git commit is required",
        )
    if code.get("license") not in {
        "MIT",
        "Apache-2.0",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "ISC",
    }:
        _error(
            errors,
            "GP_CODE_LICENSE",
            "code.license",
            "permissive open-source license is required",
        )
    docker = code.get("docker_image")
    if not isinstance(docker, str) or "@sha256:" not in docker:
        _error(
            errors,
            "GP_DOCKER_DIGEST",
            "code.docker_image",
            "Docker image must be pinned by sha256 digest",
        )

    ct = manifest.get("ct_volume")
    if not isinstance(ct, dict):
        ct = {}
        _error(
            errors,
            "GP_CT_VOLUME",
            "ct_volume",
            "CT volume record is required",
        )
    if ct.get("id") != "ct:eligible":
        _error(
            errors,
            "GP_CT_ID",
            "ct_volume.id",
            "ct_volume.id must be 'ct:eligible'",
        )
    if ct.get("volume_id") != volume_id:
        _error(
            errors,
            "GP_CT_VOLUME_ID",
            "ct_volume.volume_id",
            "CT volume must match submission.eligible_volume_id",
        )
    if ct.get("scroll_id") != scroll_id:
        _error(
            errors,
            "GP_CT_SCROLL_ID",
            "ct_volume.scroll_id",
            "CT volume must match submission.scroll_id",
        )
    uri = ct.get("uri")
    if not isinstance(uri, str) or (
        isinstance(volume_id, str) and volume_id not in uri
    ):
        _error(
            errors,
            "GP_CT_URI",
            "ct_volume.uri",
            "CT URI must contain the exact eligible volume ID",
        )

    zarr_audit = ct.get("zarr_audit")
    if not isinstance(zarr_audit, dict):
        _error(
            errors,
            "GP_CT_AUDIT",
            "ct_volume.zarr_audit",
            "zarr-pyramid-audit provenance record is required",
        )
    else:
        if zarr_audit.get("tool") != "zarr-pyramid-audit":
            _error(
                errors,
                "GP_CT_AUDIT",
                "ct_volume.zarr_audit.tool",
                "tool must be 'zarr-pyramid-audit'",
            )
        audit_sha = zarr_audit.get("manifest_sha256")
        if not isinstance(audit_sha, str) or not SHA256_RE.fullmatch(audit_sha):
            _error(
                errors,
                "GP_CT_AUDIT",
                "ct_volume.zarr_audit.manifest_sha256",
                "audit manifest sha256 is required",
            )
        audit_root = zarr_audit.get("root")
        if not isinstance(audit_root, str) or (
            isinstance(volume_id, str) and volume_id not in audit_root
        ):
            _error(
                errors,
                "GP_CT_AUDIT",
                "ct_volume.zarr_audit.root",
                "audit root must identify the exact eligible volume",
            )

    datasets = _index(manifest.get("datasets"), "datasets", errors)
    regions = _index(manifest.get("region_sets"), "region_sets", errors)
    models = _index(manifest.get("models"), "models", errors)
    surfaces = _index(manifest.get("surfaces"), "surfaces", errors)
    meshes = _index(manifest.get("meshes"), "meshes", errors)
    renders = _index(manifest.get("renders"), "renders", errors)
    held_out_validations = _index(
        manifest.get("held_out_validations"),
        "held_out_validations",
        errors,
    )

    for name, records in (
        ("datasets", datasets),
        ("region_sets", regions),
        ("models", models),
        ("surfaces", surfaces),
        ("meshes", meshes),
        ("renders", renders),
        ("held_out_validations", held_out_validations),
    ):
        if not records:
            _error(
                errors,
                "GP_REQUIRED_RECORD",
                name,
                f"at least one {name} record is required",
            )

    pseudo_producer_models = {
        str(d.get("producer_model_id"))
        for d in datasets.values()
        if d.get("pseudo_labeled") and d.get("producer_model_id")
    }

    for dataset_id, dataset in datasets.items():
        p = f"datasets[{dataset_id}]"
        _check_public_url(
            dataset.get("public_url"),
            f"{p}.public_url",
            errors,
            "GP_DATASET_PUBLIC",
        )
        if dataset.get("license") not in CC_BY_NC_4:
            _error(
                errors,
                "GP_DATASET_LICENSE",
                f"{p}.license",
                "training datasets must be released under CC-BY-NC 4.0",
            )
        if not dataset.get("training_region_set_id"):
            _error(
                errors,
                "GP_MISSING_TRAINING_REGIONS",
                f"{p}.training_region_set_id",
                "training region set is required",
            )
        if dataset.get("pseudo_labeled"):
            producer = dataset.get("producer_model_id")
            if producer not in models:
                _error(
                    errors,
                    "GP_PSEUDO_STAGE_CHECKPOINT",
                    f"{p}.producer_model_id",
                    "pseudo-labeled datasets must name the released producer checkpoint/model",
                )

        for j, source in enumerate(_as_list(dataset.get("sources"))):
            sp = f"{p}.sources[{j}]"
            if not isinstance(source, dict):
                _error(
                    errors,
                    "GP_DATASET_SOURCE",
                    sp,
                    "source must be an object",
                )
                continue
            if (
                source.get("scroll_id") == scroll_id
                and source.get("volume_id") != volume_id
            ):
                source_voxel = source.get("voxel_size_um")
                eligible_voxel = target.get("voxel_size_um") if target else None
                if not isinstance(source_voxel, (int, float)) or not isinstance(
                    eligible_voxel, (int, float)
                ):
                    _error(
                        errors,
                        "GP_SOURCE_RESOLUTION_UNKNOWN",
                        sp,
                        (
                            "same-scroll alternate-volume sources must declare "
                            "voxel_size_um so higher-resolution use can be excluded"
                        ),
                    )
                elif float(source_voxel) < float(eligible_voxel):
                    _error(
                        errors,
                        "GP_HIGHER_RES_SAME_SCROLL_SOURCE",
                        sp,
                        "training data uses a higher-resolution scan of the submitted scroll",
                    )

    for model_id, model in models.items():
        p = f"models[{model_id}]"
        _check_public_url(
            model.get("checkpoint_url"),
            f"{p}.checkpoint_url",
            errors,
            "GP_CHECKPOINT_PUBLIC",
        )
        _check_sha(model, p, errors)
        if (
            model_id in pseudo_producer_models
            and model.get("checkpoint_license") not in CC_BY_NC_4
        ):
            _error(
                errors,
                "GP_CHECKPOINT_LICENSE",
                f"{p}.checkpoint_license",
                (
                    "checkpoints used in pseudo-label iteration must be "
                    "released under CC-BY-NC 4.0"
                ),
            )

        train_ids = _as_list(model.get("training_dataset_ids"))
        if not train_ids:
            _error(
                errors,
                "GP_MODEL_DATASETS",
                f"{p}.training_dataset_ids",
                "trained model must name its training datasets",
            )
        for dataset_id in train_ids:
            if dataset_id not in datasets:
                _error(
                    errors,
                    "GP_MODEL_DATASET_REF",
                    f"{p}.training_dataset_ids",
                    f"unknown dataset {dataset_id!r}",
                )

        stochastic = model.get("stochastic")
        if not isinstance(stochastic, dict):
            stochastic = {}
            _error(
                errors,
                "GP_STOCHASTIC_DECLARATION",
                f"{p}.stochastic",
                "declare training/inference stochasticity explicitly",
            )
        for phase in ("training", "inference"):
            if stochastic.get(phase) is True and not isinstance(
                model.get(f"{phase}_seed"), int
            ):
                _error(
                    errors,
                    "GP_MISSING_SEED",
                    f"{p}.{phase}_seed",
                    f"integer {phase} seed required for stochastic {phase}",
                )
            run = model.get(f"{phase}_run")
            if not isinstance(run, dict) or run.get("public") is not True:
                _error(
                    errors,
                    "GP_RUN_NOT_PUBLIC",
                    f"{p}.{phase}_run",
                    f"public {phase} experiment run is required",
                )
            else:
                _check_public_url(
                    run.get("url"),
                    f"{p}.{phase}_run.url",
                    errors,
                    "GP_RUN_NOT_PUBLIC",
                )


    held_out_by_model: dict[str, list[str]] = {}
    for validation_id, validation in held_out_validations.items():
        p = f"held_out_validations[{validation_id}]"
        model_id = validation.get("model_id")
        if model_id not in models:
            _error(
                errors,
                "GP_HELD_OUT_MODEL",
                f"{p}.model_id",
                f"unknown model {model_id!r}",
            )
        else:
            held_out_by_model.setdefault(str(model_id), []).append(validation_id)

        _check_public_url(
            validation.get("public_input_url"),
            f"{p}.public_input_url",
            errors,
            "GP_HELD_OUT_INPUT_PUBLIC",
        )
        _check_public_url(
            validation.get("ground_truth_url"),
            f"{p}.ground_truth_url",
            errors,
            "GP_HELD_OUT_GROUND_TRUTH_PUBLIC",
        )
        _check_public_url(
            validation.get("public_url"),
            f"{p}.public_url",
            errors,
            "GP_HELD_OUT_RESULTS_PUBLIC",
        )

        protocol = validation.get("protocol")
        if protocol not in {"held-out", "k-fold"}:
            _error(
                errors,
                "GP_HELD_OUT_PROTOCOL",
                f"{p}.protocol",
                "protocol must be 'held-out' or 'k-fold'",
            )
        elif protocol == "k-fold":
            fold_count = validation.get("fold_count")
            if not isinstance(fold_count, int) or fold_count < 2:
                _error(
                    errors,
                    "GP_HELD_OUT_PROTOCOL",
                    f"{p}.fold_count",
                    "k-fold validation requires integer fold_count >= 2",
                )

        metrics = validation.get("metrics")
        if (
            not isinstance(metrics, dict)
            or not metrics
            or any(
                isinstance(value, bool) or not isinstance(value, (int, float))
                for value in metrics.values()
            )
        ):
            _error(
                errors,
                "GP_HELD_OUT_METRICS",
                f"{p}.metrics",
                "non-empty numeric held-out metric results are required",
            )

        run = validation.get("experiment_run")
        if not isinstance(run, dict) or run.get("public") is not True:
            _error(
                errors,
                "GP_HELD_OUT_RUN",
                f"{p}.experiment_run",
                "public held-out evaluation run is required",
            )
        else:
            _check_public_url(
                run.get("url"),
                f"{p}.experiment_run.url",
                errors,
                "GP_HELD_OUT_RUN",
            )

        if validation.get("code_commit") != code.get("commit"):
            _error(
                errors,
                "GP_HELD_OUT_COMMIT",
                f"{p}.code_commit",
                "held-out validation must pin the submission code commit",
            )

        _check_sha(validation, p, errors)
        _verify_local_file(validation, p, root_dir, errors)

        if model_id in models:
            _verify_ink_evidence(
                validation_id=validation_id,
                validation=validation,
                model=models[str(model_id)],
                root_dir=root_dir,
                errors=errors,
            )

        region_id = validation.get("region_set_id")
        if not isinstance(region_id, str) or not region_id:
            _error(
                errors,
                "GP_HELD_OUT_REGION",
                f"{p}.region_set_id",
                "held-out validation region set is required",
            )
        elif model_id in models:
            held_out_proofs.append(
                _check_holdout_exclusion(
                    validation_id=validation_id,
                    region_id=region_id,
                    model=models[str(model_id)],
                    region_sets=regions,
                    datasets=datasets,
                    errors=errors,
                )
            )

    for model_id in models:
        if not held_out_by_model.get(model_id):
            _error(
                errors,
                "GP_HELD_OUT_VALIDATION",
                f"models[{model_id}]",
                "every trained model requires public held-out validation evidence",
            )

    for surface_id, surface in surfaces.items():
        p = f"surfaces[{surface_id}]"
        if surface.get("ct_volume_id") != "ct:eligible":
            _error(
                errors,
                "GP_SURFACE_LINEAGE",
                f"{p}.ct_volume_id",
                "surface must derive from ct:eligible",
            )
        _check_sha(surface, p, errors, required=False)
        _verify_local_file(
            surface,
            p,
            root_dir,
            errors,
            path_required=False,
        )

    mesh_columns: dict[int, str] = {}
    for mesh_id, mesh in meshes.items():
        p = f"meshes[{mesh_id}]"
        surface_id = mesh.get("surface_id")
        if surface_id not in surfaces:
            _error(
                errors,
                "GP_MESH_LINEAGE",
                f"{p}.surface_id",
                f"unknown surface {surface_id!r}",
            )
        if mesh.get("ct_volume_id") != "ct:eligible":
            _error(
                errors,
                "GP_MESH_LINEAGE",
                f"{p}.ct_volume_id",
                "mesh must derive from ct:eligible",
            )
        if mesh.get("flattening") != "low-distortion-isometric":
            _error(
                errors,
                "GP_MESH_FLATTENING",
                f"{p}.flattening",
                "tifxyz mesh must declare low-distortion-isometric flattening",
            )

        column = mesh.get("column")
        if not isinstance(column, int) or column < 1:
            _error(
                errors,
                "GP_COLUMN",
                f"{p}.column",
                "positive integer column is required",
            )
        else:
            if column in mesh_columns:
                _error(
                    errors,
                    "GP_DUPLICATE_COLUMN",
                    f"{p}.column",
                    f"column {column} already assigned to {mesh_columns[column]}",
                )
            mesh_columns[column] = mesh_id

        rel = mesh.get("path")
        if not isinstance(rel, str):
            _error(
                errors,
                "GP_MESH_FILENAME",
                f"{p}.path",
                "mesh package path is required",
            )
        else:
            name = Path(rel).name
            match = COLUMN_MESH_RE.fullmatch(name)
            if (
                not match
                or not isinstance(column, int)
                or int(match.group(1)) != column
            ):
                _error(
                    errors,
                    "GP_MESH_FILENAME",
                    f"{p}.path",
                    (
                        "mesh must be named column_NN.tifxyz "
                        "with matching column number"
                    ),
                )
        _check_sha(mesh, p, errors)
        _verify_local_file(mesh, p, root_dir, errors)

    recto_coverage = manifest.get("recto_coverage")
    recto_coverage_proof: dict[str, Any] | None = None
    if not isinstance(recto_coverage, dict):
        _error(
            errors,
            "GP_RECTO_COVERAGE",
            "recto_coverage",
            "Grand Prize recto coverage manifest is required",
        )
    else:
        expected_root = ct.get("uri") if isinstance(ct, dict) else None
        recto_coverage_proof = audit_recto_coverage(
            recto_coverage,
            expected_volume_root=expected_root if isinstance(expected_root, str) else None,
        )
        if recto_coverage_proof.get("status") != "pass":
            for message in _as_list(recto_coverage_proof.get("errors")):
                _error(
                    errors,
                    "GP_RECTO_COVERAGE",
                    "recto_coverage",
                    str(message),
                )

        generated_by = recto_coverage.get("generated_by")
        if (
            not isinstance(generated_by, dict)
            or generated_by.get("code_commit") != code.get("commit")
        ):
            _error(
                errors,
                "GP_RECTO_COMMIT",
                "recto_coverage.generated_by.code_commit",
                "recto coverage must pin the same code commit as the submission",
            )

        coverage_mesh_ids = set(
            str(v) for v in _as_list(recto_coverage_proof.get("mesh_ids"))
        )
        package_mesh_ids = set(meshes)
        if coverage_mesh_ids != package_mesh_ids:
            missing = sorted(package_mesh_ids - coverage_mesh_ids)
            extra = sorted(coverage_mesh_ids - package_mesh_ids)
            _error(
                errors,
                "GP_RECTO_MESH_SET",
                "recto_coverage.components",
                (
                    "recto coverage mesh IDs must exactly match submitted meshes; "
                    f"missing={missing}, extra={extra}"
                ),
            )

    render_columns: dict[int, str] = {}
    for render_id, render in renders.items():
        p = f"renders[{render_id}]"
        mesh_id = render.get("mesh_id")
        model_id = render.get("model_id")
        prediction_id = render.get("prediction_region_set_id")

        if mesh_id not in meshes:
            _error(
                errors,
                "GP_RENDER_LINEAGE",
                f"{p}.mesh_id",
                f"unknown mesh {mesh_id!r}",
            )
        if render.get("ct_volume_id") != "ct:eligible":
            _error(
                errors,
                "GP_RENDER_LINEAGE",
                f"{p}.ct_volume_id",
                "render must derive from ct:eligible",
            )
        if model_id not in models:
            _error(
                errors,
                "GP_RENDER_MODEL",
                f"{p}.model_id",
                f"unknown model {model_id!r}",
            )

        column = render.get("column")
        if not isinstance(column, int) or column < 1:
            _error(
                errors,
                "GP_COLUMN",
                f"{p}.column",
                "positive integer column is required",
            )
        else:
            if column in render_columns:
                _error(
                    errors,
                    "GP_DUPLICATE_COLUMN",
                    f"{p}.column",
                    (
                        f"column {column} already rendered by "
                        f"{render_columns[column]}"
                    ),
                )
            render_columns[column] = render_id
            if mesh_id in meshes and meshes[mesh_id].get("column") != column:
                _error(
                    errors,
                    "GP_COLUMN_TRACE",
                    f"{p}.column",
                    "render and mesh column numbers differ",
                )

        rel = render.get("path")
        if isinstance(rel, str) and mesh_id in meshes:
            mesh_stem = Path(str(meshes[mesh_id].get("path", ""))).stem
            if Path(rel).stem != mesh_stem:
                _error(
                    errors,
                    "GP_RENDER_FILENAME",
                    f"{p}.path",
                    "render filename stem must match its tifxyz mesh",
                )
        else:
            _error(
                errors,
                "GP_RENDER_FILENAME",
                f"{p}.path",
                "render package path is required",
            )

        if render.get("scale_bar_cm") != 1:
            _error(
                errors,
                "GP_SCALE_BAR",
                f"{p}.scale_bar_cm",
                "submission render must include a 1 cm scale bar",
            )

        generated_by = render.get("generated_by")
        if not isinstance(generated_by, dict) or not generated_by.get("command"):
            _error(
                errors,
                "GP_RENDER_COMMAND",
                f"{p}.generated_by.command",
                "programmatic render command is required",
            )
        elif generated_by.get("code_commit") != code.get("commit"):
            _error(
                errors,
                "GP_RENDER_COMMAND",
                f"{p}.generated_by.code_commit",
                "render must pin the same code commit as the submission",
            )

        _check_sha(render, p, errors)
        _verify_local_file(render, p, root_dir, errors)

        proof = None
        if (
            isinstance(model_id, str)
            and model_id in models
            and isinstance(prediction_id, str)
        ):
            proof = _check_region_exclusion(
                render_id=render_id,
                prediction_id=prediction_id,
                model=models[model_id],
                region_sets=regions,
                datasets=datasets,
                eligible_volume_id=str(volume_id),
                errors=errors,
            )
        elif not isinstance(prediction_id, str):
            _error(
                errors,
                "GP_MISSING_REGION_SET",
                f"{p}.prediction_region_set_id",
                "prediction region set is required",
            )

        chains.append(
            {
                "render_id": render_id,
                "ct_volume_id": render.get("ct_volume_id"),
                "surface_id": (
                    meshes.get(mesh_id, {}).get("surface_id")
                    if isinstance(mesh_id, str)
                    else None
                ),
                "mesh_id": mesh_id,
                "model_id": model_id,
                "checkpoint_sha256": (
                    models.get(model_id, {}).get("sha256")
                    if isinstance(model_id, str)
                    else None
                ),
                "training_dataset_ids": (
                    models.get(model_id, {}).get("training_dataset_ids", [])
                    if isinstance(model_id, str)
                    else []
                ),
                "training_seed": (
                    models.get(model_id, {}).get("training_seed")
                    if isinstance(model_id, str)
                    else None
                ),
                "inference_seed": (
                    models.get(model_id, {}).get("inference_seed")
                    if isinstance(model_id, str)
                    else None
                ),
                "training_run": (
                    models.get(model_id, {}).get("training_run")
                    if isinstance(model_id, str)
                    else None
                ),
                "inference_run": (
                    models.get(model_id, {}).get("inference_run")
                    if isinstance(model_id, str)
                    else None
                ),
                "region_exclusion": proof,
            }
        )

    if mesh_columns and set(mesh_columns) != set(render_columns):
        _error(
            errors,
            "GP_COLUMN_COVERAGE",
            "renders",
            (
                "every numbered mesh must have exactly one same-numbered "
                "render and vice versa"
            ),
        )

    banner = manifest.get("banner")
    if not isinstance(banner, dict):
        _error(
            errors,
            "GP_BANNER",
            "banner",
            "full-scroll banner record is required",
        )
    else:
        if banner.get("column_numbers_overlaid") is not True:
            _error(
                errors,
                "GP_BANNER_COLUMNS",
                "banner.column_numbers_overlaid",
                "banner must overlay column numbers",
            )
        render_ids = set(_as_list(banner.get("render_ids")))
        if render_ids != set(renders):
            _error(
                errors,
                "GP_BANNER_RENDER_SET",
                "banner.render_ids",
                "banner must span every submitted render",
            )
        _check_sha(banner, "banner", errors)
        _verify_local_file(banner, "banner", root_dir, errors)

    graph_digest = hashlib.sha256(
        json.dumps(
            manifest,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()

    return {
        "validator": "scrollq.provenance",
        "validator_schema_version": SCHEMA_VERSION,
        "rules_url": RULES_URL,
        "manifest_sha256": manifest_sha256,
        "graph_sha256": graph_digest,
        "eligible": not errors,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
        "render_chains": chains,
        "held_out_validation_proofs": held_out_proofs,
        "recto_coverage_proof": recto_coverage_proof,
    }


def main() -> None:
    ap = argparse.ArgumentParser(
        description=(
            "Validate a machine-checkable 2027 Grand Prize provenance manifest"
        )
    )
    ap.add_argument(
        "--manifest",
        required=True,
        help="provenance manifest JSON",
    )
    ap.add_argument(
        "--root-dir",
        help="optional submission package root for local sha256 verification",
    )
    ap.add_argument(
        "--out",
        help="optional JSON validation report path",
    )
    ap.add_argument(
        "--format",
        choices=("text", "json", "github"),
        default="text",
    )
    args = ap.parse_args()

    manifest_path = Path(args.manifest)
    raw = manifest_path.read_bytes()
    manifest = json.loads(raw)
    root_dir = Path(args.root_dir) if args.root_dir else None
    report = validate_manifest(
        manifest,
        root_dir=root_dir,
        manifest_sha256=hashlib.sha256(raw).hexdigest(),
    )

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(report, indent=2) + "\n",
            encoding="utf-8",
        )

    if args.format == "json":
        print(json.dumps(report, indent=2))
    elif args.format == "github":
        for item in report["errors"]:
            print(
                f"::error title={item['code']}::"
                f"{item['path']}: {item['message']}"
            )
        if report["eligible"]:
            print(
                "Grand Prize provenance eligibility: PASS "
                f"({report['graph_sha256']})"
            )
    else:
        verdict = "PASS" if report["eligible"] else "FAIL"
        print(f"Grand Prize provenance eligibility: {verdict}")
        print(f"graph sha256: {report['graph_sha256']}")
        for item in report["errors"]:
            print(
                f"- {item['code']} {item['path']}: "
                f"{item['message']}"
            )

    raise SystemExit(0 if report["eligible"] else 1)


if __name__ == "__main__":
    main()
