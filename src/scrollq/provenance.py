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
from .submission_image import (
    SCHEMA_VERSION as SUBMISSION_IMAGE_SCHEMA_VERSION,
    TOOL as SUBMISSION_IMAGE_TOOL,
    vc_render_um_per_pixel,
)
from .vc3d_replay import (
    VC3D_RECEIPT_SCHEMA_VERSION,
    VC3D_RECEIPT_TOOL,
    verify_receipt as verify_vc3d_receipt,
)

SCHEMA_VERSION = 7
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


def _load_local_json_artifact(
    record: dict[str, Any],
    path: str,
    root_dir: Path | None,
    errors: list[dict[str, str]],
    *,
    code: str,
) -> dict[str, Any] | None:
    """Open a hash-pinned package-local JSON artifact after path checks."""

    if root_dir is None:
        return None
    rel = record.get("path")
    if not isinstance(rel, str) or not rel:
        return None
    candidate = root_dir / rel
    target = candidate.resolve()
    try:
        target.relative_to(root_dir.resolve())
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    try:
        value = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        _error(errors, code, path, f"cannot parse proof JSON: {exc}")
        return None
    if not isinstance(value, dict):
        _error(errors, code, path, "proof JSON must be an object")
        return None
    return value


def _check_render_scale_proof(
    *,
    render_id: str,
    render: dict[str, Any],
    target: dict[str, Any] | None,
    root_dir: Path | None,
    errors: list[dict[str, str]],
) -> dict[str, Any]:
    """Verify a rendered 1 cm bar against VC3D's physical output scale."""

    p = f"renders[{render_id}].scale_proof"
    proof = render.get("scale_proof")
    summary: dict[str, Any] = {
        "render_id": render_id,
        "path": None,
        "sha256": None,
        "base_voxel_size_um": None,
        "group_idx": None,
        "render_scale": None,
        "micrometers_per_output_pixel": None,
        "scale_bar_pixels": None,
        "input_path": None,
        "input_sha256": None,
        "input_size_xy": None,
        "artifact_checked": False,
    }
    if not isinstance(proof, dict):
        _error(
            errors,
            "GP_SCALE_PROOF",
            p,
            "hash-pinned scroliq-submission-image column proof is required",
        )
        return summary

    summary.update(
        {
            key: proof.get(key)
            for key in (
                "path",
                "sha256",
                "base_voxel_size_um",
                "group_idx",
                "render_scale",
                "micrometers_per_output_pixel",
                "scale_bar_pixels",
            )
        }
    )
    if proof.get("tool") != SUBMISSION_IMAGE_TOOL:
        _error(
            errors,
            "GP_SCALE_PROOF",
            f"{p}.tool",
            f"tool must be {SUBMISSION_IMAGE_TOOL!r}",
        )
    if not isinstance(proof.get("path"), str) or not proof.get("path"):
        _error(
            errors,
            "GP_SCALE_PROOF",
            f"{p}.path",
            "package-relative scale proof path is required",
        )
    _check_sha(proof, p, errors)

    eligible_voxel = (
        target.get("voxel_size_um") if isinstance(target, dict) else None
    )
    base_voxel = proof.get("base_voxel_size_um")
    if (
        isinstance(base_voxel, bool)
        or not isinstance(base_voxel, (int, float))
        or not math.isfinite(float(base_voxel))
        or float(base_voxel) <= 0
    ):
        _error(
            errors,
            "GP_SCALE_PROOF_VOXEL",
            f"{p}.base_voxel_size_um",
            "positive finite eligible-volume voxel size is required",
        )
    elif isinstance(eligible_voxel, (int, float)) and not math.isclose(
        float(base_voxel),
        float(eligible_voxel),
        rel_tol=1e-9,
        abs_tol=1e-6,
    ):
        _error(
            errors,
            "GP_SCALE_PROOF_VOXEL",
            f"{p}.base_voxel_size_um",
            (
                f"scale proof uses {base_voxel} um but eligible volume uses "
                f"{eligible_voxel} um"
            ),
        )

    group_idx = proof.get("group_idx")
    render_scale = proof.get("render_scale")
    params_ok = True
    if (
        isinstance(group_idx, bool)
        or not isinstance(group_idx, int)
        or group_idx < 0
    ):
        params_ok = False
    if (
        isinstance(render_scale, bool)
        or not isinstance(render_scale, (int, float))
        or not math.isfinite(float(render_scale))
        or float(render_scale) <= 0
    ):
        params_ok = False
    if not params_ok:
        _error(
            errors,
            "GP_SCALE_PROOF_PARAMS",
            p,
            "group_idx must be non-negative and render_scale positive/finite",
        )

    expected_umpp: float | None = None
    if (
        params_ok
        and isinstance(base_voxel, (int, float))
        and not isinstance(base_voxel, bool)
        and math.isfinite(float(base_voxel))
        and float(base_voxel) > 0
    ):
        expected_umpp = vc_render_um_per_pixel(
            float(base_voxel), int(group_idx), float(render_scale)
        )
        declared_umpp = proof.get("micrometers_per_output_pixel")
        if (
            isinstance(declared_umpp, bool)
            or not isinstance(declared_umpp, (int, float))
            or not math.isfinite(float(declared_umpp))
            or not math.isclose(
                float(declared_umpp),
                expected_umpp,
                rel_tol=1e-9,
                abs_tol=1e-9,
            )
        ):
            _error(
                errors,
                "GP_SCALE_PROOF_PIXEL_SIZE",
                f"{p}.micrometers_per_output_pixel",
                f"must equal VC3D-derived value {expected_umpp:.12g} um/pixel",
            )
        expected_pixels = int(round(10_000.0 / expected_umpp))
        declared_pixels = proof.get("scale_bar_pixels")
        if (
            isinstance(declared_pixels, bool)
            or not isinstance(declared_pixels, int)
            or declared_pixels != expected_pixels
        ):
            _error(
                errors,
                "GP_SCALE_PROOF_PIXELS",
                f"{p}.scale_bar_pixels",
                f"1 cm must be exactly {expected_pixels} output pixels",
            )

    _verify_local_file(proof, p, root_dir, errors)
    artifact = _load_local_json_artifact(
        proof,
        p,
        root_dir,
        errors,
        code="GP_SCALE_PROOF_MISMATCH",
    )
    if artifact is None:
        return summary
    summary["artifact_checked"] = True
    input_artifact = artifact.get("input")
    if isinstance(input_artifact, dict):
        summary["input_path"] = input_artifact.get("path")
        summary["input_sha256"] = input_artifact.get("sha256")
        summary["input_size_xy"] = input_artifact.get("size_xy")

    mismatches: list[str] = []
    if artifact.get("schema_version") != SUBMISSION_IMAGE_SCHEMA_VERSION:
        mismatches.append("schema_version")
    if artifact.get("tool") != SUBMISSION_IMAGE_TOOL:
        mismatches.append("tool")
    if artifact.get("operation") != "column":
        mismatches.append("operation")
    if artifact.get("column") != render.get("column"):
        mismatches.append("column")

    output = artifact.get("output")
    if not isinstance(output, dict):
        mismatches.append("output")
    else:
        render_path = render.get("path")
        expected_name = (
            Path(render_path).name if isinstance(render_path, str) else None
        )
        if output.get("path") != expected_name:
            mismatches.append("output.path")
        if output.get("sha256") != render.get("sha256"):
            mismatches.append("output.sha256")

    physical = artifact.get("vc_render_tifxyz")
    if not isinstance(physical, dict):
        mismatches.append("vc_render_tifxyz")
    else:
        for key in (
            "base_voxel_size_um",
            "group_idx",
            "render_scale",
            "micrometers_per_output_pixel",
        ):
            left, right = physical.get(key), proof.get(key)
            if isinstance(left, (int, float)) and isinstance(right, (int, float)):
                if not math.isclose(float(left), float(right), rel_tol=1e-9, abs_tol=1e-9):
                    mismatches.append(key)
            elif left != right:
                mismatches.append(key)

    bar = artifact.get("scale_bar")
    if not isinstance(bar, dict):
        mismatches.append("scale_bar")
    else:
        if bar.get("centimeters") != 1:
            mismatches.append("scale_bar.centimeters")
        if bar.get("micrometers") != 10_000:
            mismatches.append("scale_bar.micrometers")
        if bar.get("pixels") != proof.get("scale_bar_pixels"):
            mismatches.append("scale_bar.pixels")

    if mismatches:
        _error(
            errors,
            "GP_SCALE_PROOF_MISMATCH",
            p,
            "manifest/proof mismatch: " + ", ".join(sorted(set(mismatches))),
        )
    return summary


def _vc3d_numbers_equal(left: Any, right: Any, *, abs_tol: float = 1e-9) -> bool:
    if (
        isinstance(left, bool)
        or isinstance(right, bool)
        or not isinstance(left, (int, float))
        or not isinstance(right, (int, float))
    ):
        return left == right
    return math.isclose(
        float(left),
        float(right),
        rel_tol=1e-9,
        abs_tol=abs_tol,
    )


def _check_vc3d_receipt(
    *,
    render_id: str,
    render: dict[str, Any],
    mesh: dict[str, Any] | None,
    eligible_volume_id: str,
    target: dict[str, Any] | None,
    scale_proof: dict[str, Any],
    root_dir: Path | None,
    errors: list[dict[str, str]],
) -> dict[str, Any]:
    """Bind an executed vc_render_tifxyz run into the final column-image chain."""

    p = f"renders[{render_id}].vc3d_receipt"
    declared = render.get("vc3d_receipt")
    summary: dict[str, Any] = {
        "render_id": render_id,
        "path": None,
        "sha256": None,
        "artifact_checked": False,
        "receipt_verified": False,
        "villa_commit": None,
        "binary_sha256": None,
        "mesh_path": None,
        "mesh_sha256": None,
        "raw_render_path": None,
        "raw_render_sha256": None,
        "log_path": None,
        "log_sha256": None,
        "base_voxel_size_um": None,
        "group_idx": None,
        "render_scale": None,
    }
    if not isinstance(declared, dict):
        _error(
            errors,
            "GP_VC3D_RECEIPT",
            p,
            "hash-pinned scroliq-vc3d render receipt is required",
        )
        return summary

    summary["path"] = declared.get("path")
    summary["sha256"] = declared.get("sha256")
    if declared.get("tool") != VC3D_RECEIPT_TOOL:
        _error(
            errors,
            "GP_VC3D_RECEIPT",
            f"{p}.tool",
            f"tool must be {VC3D_RECEIPT_TOOL!r}",
        )
    if not isinstance(declared.get("path"), str) or not declared.get("path"):
        _error(
            errors,
            "GP_VC3D_RECEIPT",
            f"{p}.path",
            "package-relative VC3D receipt path is required",
        )
    _check_sha(declared, p, errors)
    _verify_local_file(declared, p, root_dir, errors)
    artifact = _load_local_json_artifact(
        declared,
        p,
        root_dir,
        errors,
        code="GP_VC3D_RECEIPT_MISMATCH",
    )
    if artifact is None:
        return summary
    summary["artifact_checked"] = True

    mismatches: list[str] = []
    if artifact.get("schema_version") != VC3D_RECEIPT_SCHEMA_VERSION:
        mismatches.append("schema_version")
    if artifact.get("tool") != VC3D_RECEIPT_TOOL:
        mismatches.append("tool")
    if artifact.get("operation") != "render-column":
        mismatches.append("operation")
    if artifact.get("column") != render.get("column"):
        mismatches.append("column")

    vc3d = artifact.get("vc3d")
    if not isinstance(vc3d, dict):
        mismatches.append("vc3d")
        vc3d = {}
    summary["villa_commit"] = vc3d.get("commit")
    binary = vc3d.get("binary")
    if isinstance(binary, dict):
        summary["binary_sha256"] = binary.get("sha256")
    else:
        mismatches.append("vc3d.binary")

    inputs = artifact.get("inputs")
    if not isinstance(inputs, dict):
        mismatches.append("inputs")
        inputs = {}
    volume = inputs.get("volume")
    if not isinstance(volume, dict):
        mismatches.append("inputs.volume")
        volume = {}
    summary["base_voxel_size_um"] = volume.get("base_voxel_size_um")
    if volume.get("volume_id") != eligible_volume_id:
        mismatches.append("inputs.volume.volume_id")
    eligible_voxel = (
        target.get("voxel_size_um") if isinstance(target, dict) else None
    )
    if not _vc3d_numbers_equal(
        volume.get("base_voxel_size_um"),
        eligible_voxel,
        abs_tol=1e-6,
    ):
        mismatches.append("inputs.volume.base_voxel_size_um")
    if not _vc3d_numbers_equal(
        volume.get("base_voxel_size_um"),
        scale_proof.get("base_voxel_size_um"),
        abs_tol=1e-6,
    ):
        mismatches.append("scale_proof.base_voxel_size_um")

    receipt_mesh = inputs.get("mesh")
    if not isinstance(receipt_mesh, dict):
        mismatches.append("inputs.mesh")
        receipt_mesh = {}
    summary["mesh_path"] = receipt_mesh.get("path")
    summary["mesh_sha256"] = receipt_mesh.get("sha256")
    if not isinstance(mesh, dict):
        mismatches.append("manifest.mesh")
    else:
        if receipt_mesh.get("path") != mesh.get("path"):
            mismatches.append("inputs.mesh.path")
        if receipt_mesh.get("sha256") != mesh.get("sha256"):
            mismatches.append("inputs.mesh.sha256")

    render_call = artifact.get("render")
    if not isinstance(render_call, dict):
        mismatches.append("render")
        render_call = {}
    summary["group_idx"] = render_call.get("group_idx")
    summary["render_scale"] = render_call.get("scale")
    if render_call.get("num_slices") != 1:
        mismatches.append("render.num_slices")
    if render_call.get("exit_code") != 0:
        mismatches.append("render.exit_code")
    if not _vc3d_numbers_equal(
        render_call.get("group_idx"),
        scale_proof.get("group_idx"),
    ):
        mismatches.append("scale_proof.group_idx")
    if not _vc3d_numbers_equal(
        render_call.get("scale"),
        scale_proof.get("render_scale"),
    ):
        mismatches.append("scale_proof.render_scale")

    raw_output = artifact.get("output")
    if not isinstance(raw_output, dict):
        mismatches.append("output")
        raw_output = {}
    summary["raw_render_path"] = raw_output.get("path")
    summary["raw_render_sha256"] = raw_output.get("sha256")
    if raw_output.get("sha256") != scale_proof.get("input_sha256"):
        mismatches.append("scale_proof.input.sha256")
    scale_input_path = scale_proof.get("input_path")
    raw_path = raw_output.get("path")
    if (
        not isinstance(scale_input_path, str)
        or not isinstance(raw_path, str)
        or Path(raw_path).name != scale_input_path
    ):
        mismatches.append("scale_proof.input.path")

    log = artifact.get("log")
    if not isinstance(log, dict):
        mismatches.append("log")
        log = {}
    summary["log_path"] = log.get("path")
    summary["log_sha256"] = log.get("sha256")

    if root_dir is not None and isinstance(declared.get("path"), str):
        receipt_report = verify_vc3d_receipt(
            root_dir / declared["path"],
            root_dir=root_dir,
        )
        summary["receipt_verified"] = receipt_report.get("valid") is True
        if receipt_report.get("valid") is not True:
            detail = "; ".join(str(v) for v in receipt_report.get("errors", [])[:4])
            _error(
                errors,
                "GP_VC3D_RECEIPT_INVALID",
                p,
                "VC3D receipt/artifact verification failed"
                + (f": {detail}" if detail else ""),
            )

    if mismatches:
        _error(
            errors,
            "GP_VC3D_RECEIPT_MISMATCH",
            p,
            "manifest/receipt/scale-proof mismatch: "
            + ", ".join(sorted(set(mismatches))),
        )
    return summary


def _check_banner_proof(
    *,
    banner: dict[str, Any],
    renders: dict[str, dict[str, Any]],
    root_dir: Path | None,
    errors: list[dict[str, str]],
) -> dict[str, Any]:
    """Bind the numbered overview banner to the exact frozen column renders."""

    p = "banner.proof"
    proof = banner.get("proof")
    summary: dict[str, Any] = {
        "path": None,
        "sha256": None,
        "artifact_checked": False,
        "columns": [],
    }
    if not isinstance(proof, dict):
        _error(
            errors,
            "GP_BANNER_PROOF",
            p,
            "hash-pinned scroliq-submission-image banner proof is required",
        )
        return summary

    summary["path"] = proof.get("path")
    summary["sha256"] = proof.get("sha256")
    if proof.get("tool") != SUBMISSION_IMAGE_TOOL:
        _error(
            errors,
            "GP_BANNER_PROOF",
            f"{p}.tool",
            f"tool must be {SUBMISSION_IMAGE_TOOL!r}",
        )
    if not isinstance(proof.get("path"), str) or not proof.get("path"):
        _error(
            errors,
            "GP_BANNER_PROOF",
            f"{p}.path",
            "package-relative banner proof path is required",
        )
    _check_sha(proof, p, errors)
    _verify_local_file(proof, p, root_dir, errors)
    artifact = _load_local_json_artifact(
        proof,
        p,
        root_dir,
        errors,
        code="GP_BANNER_PROOF_MISMATCH",
    )
    if artifact is None:
        return summary
    summary["artifact_checked"] = True

    mismatches: list[str] = []
    if artifact.get("schema_version") != SUBMISSION_IMAGE_SCHEMA_VERSION:
        mismatches.append("schema_version")
    if artifact.get("tool") != SUBMISSION_IMAGE_TOOL:
        mismatches.append("tool")
    if artifact.get("operation") != "banner":
        mismatches.append("operation")
    if artifact.get("column_numbers_overlaid") is not True:
        mismatches.append("column_numbers_overlaid")

    output = artifact.get("output")
    if not isinstance(output, dict):
        mismatches.append("output")
    else:
        banner_path = banner.get("path")
        expected_name = (
            Path(banner_path).name if isinstance(banner_path, str) else None
        )
        if output.get("path") != expected_name:
            mismatches.append("output.path")
        if output.get("sha256") != banner.get("sha256"):
            mismatches.append("output.sha256")

    expected_columns = sorted(
        (
            int(render.get("column")),
            Path(str(render.get("path"))).name,
            render.get("sha256"),
        )
        for render in renders.values()
        if isinstance(render.get("column"), int)
        and not isinstance(render.get("column"), bool)
        and isinstance(render.get("path"), str)
    )
    observed: list[tuple[int, str, Any]] = []
    rows = artifact.get("columns")
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict):
                observed.append(
                    (row.get("column"), row.get("path"), row.get("sha256"))
                )
        observed.sort(key=lambda item: item[0] if isinstance(item[0], int) else -1)
    else:
        mismatches.append("columns")
    if observed != expected_columns:
        mismatches.append("columns")
    summary["columns"] = observed

    if mismatches:
        _error(
            errors,
            "GP_BANNER_PROOF_MISMATCH",
            p,
            "manifest/proof mismatch: " + ", ".join(sorted(set(mismatches))),
        )
    return summary


def _verify_vc3d_mesh_context(
    *,
    mesh_id: str,
    mesh: dict[str, Any],
    root_dir: Path | None,
    eligible_volume_id: str,
    scroll_id: str,
    errors: list[dict[str, str]],
) -> dict[str, Any] | None:
    """Bind an unpacked TIFXYZ mesh to the eligible CT using its own metadata.

    Modern VC3D writers record target_volume in meta.json. When a local
    submission root is available we require that evidence for directory-format
    TIFXYZ meshes, rather than trusting only the provenance manifest's
    self-declared ct_volume_id.
    """

    if root_dir is None:
        return None

    p = f"meshes[{mesh_id}]"
    rel = mesh.get("path")
    proof: dict[str, Any] = {
        "mesh_id": mesh_id,
        "path": rel,
        "checked": False,
        "target_volume": None,
        "scroll_source": None,
        "source": None,
        "scale": None,
        "meta_sha256": None,
    }
    if not isinstance(rel, str) or not rel:
        return proof

    candidate = root_dir / rel
    target = candidate.resolve()
    try:
        target.relative_to(root_dir.resolve())
    except ValueError:
        return proof
    if not candidate.exists():
        return proof
    if not candidate.is_dir():
        _error(
            errors,
            "GP_MESH_TIFXYZ_LAYOUT",
            f"{p}.path",
            "Grand Prize TIFXYZ mesh must be an unpacked directory with meta.json",
        )
        return proof

    meta_path = candidate / "meta.json"
    if not meta_path.is_file():
        _error(
            errors,
            "GP_MESH_META",
            f"{p}.path",
            "unpacked TIFXYZ mesh is missing meta.json",
        )
        return proof

    try:
        raw = meta_path.read_bytes()
        meta = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        _error(
            errors,
            "GP_MESH_META",
            f"{p}.path",
            f"cannot parse TIFXYZ meta.json: {exc}",
        )
        return proof
    if not isinstance(meta, dict):
        _error(
            errors,
            "GP_MESH_META",
            f"{p}.path",
            "TIFXYZ meta.json must be a JSON object",
        )
        return proof

    proof.update(
        {
            "checked": True,
            "target_volume": meta.get("target_volume"),
            "scroll_source": meta.get("scroll_source"),
            "source": meta.get("source"),
            "scale": meta.get("scale"),
            "meta_sha256": hashlib.sha256(raw).hexdigest(),
        }
    )

    if meta.get("format") != "tifxyz":
        _error(
            errors,
            "GP_MESH_META_FORMAT",
            f"{p}.path",
            "mesh meta.json must declare format='tifxyz'",
        )

    target_volume = meta.get("target_volume")
    if not isinstance(target_volume, str) or eligible_volume_id not in target_volume:
        _error(
            errors,
            "GP_MESH_TARGET_VOLUME",
            f"{p}.path",
            (
                "VC3D meta.json target_volume must identify the exact eligible "
                f"volume {eligible_volume_id!r}"
            ),
        )

    scroll_source = meta.get("scroll_source")
    if (
        isinstance(scroll_source, str)
        and scroll_source
        and scroll_id not in scroll_source
    ):
        _error(
            errors,
            "GP_MESH_SCROLL_SOURCE",
            f"{p}.path",
            (
                f"VC3D meta.json scroll_source {scroll_source!r} does not "
                f"identify submitted scroll {scroll_id!r}"
            ),
        )

    scale = meta.get("scale")
    if not (
        isinstance(scale, list)
        and len(scale) == 2
        and all(
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
            and float(value) > 0
            for value in scale
        )
    ):
        _error(
            errors,
            "GP_MESH_SCALE",
            f"{p}.path",
            "TIFXYZ meta.json must carry a positive finite 2D scale",
        )

    return proof


def _verify_zpa_evidence(
    *,
    zarr_audit: dict[str, Any],
    root_dir: Path | None,
    volume_id: str,
    errors: list[dict[str, str]],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Validate the declared ZPA artifact and return report plus attestation.

    Without a local package root the manifest declarations are checked. With
    a package root, the exact artifact is hash-checked, parsed, validated
    against ZPA's bundled schema, and matched back to those declarations.
    """

    p = "ct_volume.zarr_audit"
    if zarr_audit.get("tool") != "zarr-pyramid-audit":
        _error(errors, "GP_CT_AUDIT", f"{p}.tool", "tool must be 'zarr-pyramid-audit'")

    rel = zarr_audit.get("path")
    if not isinstance(rel, str) or not rel:
        _error(
            errors,
            "GP_CT_AUDIT_PATH",
            f"{p}.path",
            "package-relative ZPA report path is required",
        )
    _check_sha(zarr_audit, p, errors)

    report_root = zarr_audit.get("root")
    if not isinstance(report_root, str) or volume_id not in report_root:
        _error(
            errors,
            "GP_CT_AUDIT_ROOT",
            f"{p}.root",
            "ZPA report root must identify the exact eligible volume",
        )

    if zarr_audit.get("integrity") != "PASS":
        _error(
            errors,
            "GP_CT_AUDIT_INTEGRITY",
            f"{p}.integrity",
            "Grand Prize source CT requires a ZPA integrity PASS",
        )

    declared = zarr_audit.get("source_attestation")
    if not isinstance(declared, dict):
        declared = {}
        _error(
            errors,
            "GP_CT_SOURCE_ATTESTATION",
            f"{p}.source_attestation",
            "ZPA metadata source attestation is required",
        )
    if declared.get("algorithm") != "zpa-metadata-semantics-v1":
        _error(
            errors,
            "GP_CT_SOURCE_ATTESTATION",
            f"{p}.source_attestation.algorithm",
            "source attestation must use zpa-metadata-semantics-v1",
        )
    if declared.get("state") != "PRESENT":
        _error(
            errors,
            "GP_CT_SOURCE_ATTESTATION",
            f"{p}.source_attestation.state",
            "eligible CT metadata must have PRESENT source evidence",
        )
    metadata_sha = declared.get("metadata_semantics_sha256")
    if not isinstance(metadata_sha, str) or not SHA256_RE.fullmatch(metadata_sha):
        _error(
            errors,
            "GP_CT_SOURCE_ATTESTATION",
            f"{p}.source_attestation.metadata_semantics_sha256",
            "lowercase 64-hex audited metadata semantics digest is required",
        )
    axes = declared.get("axes")
    if (
        not isinstance(axes, list)
        or not axes
        or not all(isinstance(v, str) and v for v in axes)
        or len(set(axes)) != len(axes)
    ):
        _error(
            errors,
            "GP_CT_SOURCE_AXES",
            f"{p}.source_attestation.axes",
            "non-empty unique source axis names are required",
        )

    if root_dir is None:
        return None, declared

    _verify_local_file(zarr_audit, p, root_dir, errors)
    if not isinstance(rel, str) or not rel:
        return None, declared
    target = (root_dir / rel).resolve()
    try:
        target.relative_to(root_dir.resolve())
    except ValueError:
        return None, declared
    if not target.is_file():
        return None, declared

    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        _error(
            errors,
            "GP_CT_AUDIT_REPORT",
            f"{p}.path",
            f"cannot parse ZPA report artifact: {exc}",
        )
        return None, declared

    report: dict[str, Any] | None = None
    if isinstance(payload, dict) and payload.get("tool") == "zarr-pyramid-audit":
        report = payload
    elif isinstance(payload, dict) and isinstance(payload.get("results"), list):
        matches = [
            row.get("report")
            for row in payload["results"]
            if isinstance(row, dict)
            and isinstance(row.get("report"), dict)
            and row["report"].get("root") == report_root
        ]
        if len(matches) == 1:
            report = matches[0]
        else:
            _error(
                errors,
                "GP_CT_AUDIT_REPORT",
                f"{p}.path",
                "ZPA gate artifact must contain exactly one report for the declared root",
            )
            return None, declared
    else:
        _error(
            errors,
            "GP_CT_AUDIT_REPORT",
            f"{p}.path",
            "artifact is neither a ZPA audit report nor a ZPA gate report",
        )
        return None, declared

    schema_errors = validate_zpa_report(report)
    if schema_errors:
        _error(
            errors,
            "GP_CT_AUDIT_REPORT",
            f"{p}.path",
            "ZPA report fails its bundled schema: " + "; ".join(schema_errors[:3]),
        )
        return report, declared

    if report.get("root") != report_root:
        _error(
            errors,
            "GP_CT_AUDIT_ROOT",
            f"{p}.root",
            "declared root does not match the ZPA report root",
        )
    if report.get("integrity") != "PASS":
        _error(
            errors,
            "GP_CT_AUDIT_INTEGRITY",
            f"{p}.integrity",
            f"embedded ZPA report integrity is {report.get('integrity')!r}, not PASS",
        )

    actual = report.get("source_attestation")
    if not isinstance(actual, dict):
        _error(
            errors,
            "GP_CT_SOURCE_ATTESTATION",
            f"{p}.path",
            "validated ZPA report has no source_attestation block",
        )
        return report, declared

    for key in ("algorithm", "state", "metadata_semantics_sha256", "axes"):
        if actual.get(key) != declared.get(key):
            _error(
                errors,
                "GP_CT_SOURCE_ATTESTATION_MISMATCH",
                f"{p}.source_attestation.{key}",
                "manifest declaration does not match the validated ZPA report",
            )

    return report, actual


def _validate_model_input_contract(
    *,
    model_id: str,
    model: dict[str, Any],
    target: dict[str, Any] | None,
    source_attestation: dict[str, Any] | None,
    errors: list[dict[str, str]],
) -> dict[str, Any] | None:
    """Validate the model's physical input/preprocessing contract."""

    p = f"models[{model_id}].input_contract"
    contract = model.get("input_contract")
    if not isinstance(contract, dict):
        _error(
            errors,
            "GP_MODEL_INPUT_CONTRACT",
            p,
            "explicit physical/model input contract is required",
        )
        return None

    axes = contract.get("axes")
    if (
        not isinstance(axes, list)
        or len(axes) != 3
        or not all(isinstance(v, str) and v for v in axes)
        or len(set(axes)) != len(axes)
    ):
        _error(
            errors,
            "GP_MODEL_INPUT_AXES",
            f"{p}.axes",
            "model input axes must be three unique axis names",
        )
    source_axes = (
        source_attestation.get("axes")
        if isinstance(source_attestation, dict)
        else None
    )
    if isinstance(axes, list) and isinstance(source_axes, list) and axes != source_axes:
        _error(
            errors,
            "GP_MODEL_INPUT_AXES",
            f"{p}.axes",
            f"model axes {axes!r} do not match audited source axes {source_axes!r}",
        )

    source_voxel = contract.get("source_voxel_size_um")
    if (
        isinstance(source_voxel, bool)
        or not isinstance(source_voxel, (int, float))
        or float(source_voxel) <= 0
    ):
        _error(
            errors,
            "GP_MODEL_SOURCE_VOXEL",
            f"{p}.source_voxel_size_um",
            "positive source voxel size in micrometers is required",
        )
    else:
        eligible_voxel = target.get("voxel_size_um") if isinstance(target, dict) else None
        if isinstance(eligible_voxel, (int, float)) and not math.isclose(
            float(source_voxel), float(eligible_voxel), rel_tol=1e-9, abs_tol=1e-6
        ):
            _error(
                errors,
                "GP_MODEL_SOURCE_VOXEL",
                f"{p}.source_voxel_size_um",
                (
                    f"declared source voxel size {source_voxel} um does not match "
                    f"eligible volume {eligible_voxel} um"
                ),
            )

    model_voxel = contract.get("model_voxel_size_um")
    if (
        isinstance(model_voxel, bool)
        or not isinstance(model_voxel, (int, float))
        or float(model_voxel) <= 0
    ):
        _error(
            errors,
            "GP_MODEL_VOXEL",
            f"{p}.model_voxel_size_um",
            "positive model voxel size in micrometers is required",
        )

    resampling = contract.get("resampling")
    if resampling not in {"none", "explicit"}:
        _error(
            errors,
            "GP_MODEL_RESAMPLING",
            f"{p}.resampling",
            "resampling must be 'none' or 'explicit'",
        )
    elif (
        resampling == "none"
        and isinstance(source_voxel, (int, float))
        and not isinstance(source_voxel, bool)
        and isinstance(model_voxel, (int, float))
        and not isinstance(model_voxel, bool)
        and not math.isclose(
            float(source_voxel), float(model_voxel), rel_tol=1e-9, abs_tol=1e-6
        )
    ):
        _error(
            errors,
            "GP_MODEL_RESAMPLING",
            f"{p}.model_voxel_size_um",
            "resampling='none' requires model and source voxel sizes to match",
        )

    window = contract.get("window_voxels_zyx")
    if (
        not isinstance(window, list)
        or len(window) != 3
        or not all(isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in window)
    ):
        _error(
            errors,
            "GP_MODEL_WINDOW",
            f"{p}.window_voxels_zyx",
            "positive integer [z,y,x] model window is required",
        )

    profile = contract.get("preprocessing_profile")
    if not isinstance(profile, dict):
        _error(
            errors,
            "GP_MODEL_PREPROCESSING",
            f"{p}.preprocessing_profile",
            "public hash-pinned preprocessing profile is required",
        )
    else:
        _check_public_url(
            profile.get("public_url"),
            f"{p}.preprocessing_profile.public_url",
            errors,
            "GP_MODEL_PREPROCESSING",
        )
        sha = profile.get("sha256")
        if not isinstance(sha, str) or not SHA256_RE.fullmatch(sha):
            _error(
                errors,
                "GP_MODEL_PREPROCESSING",
                f"{p}.preprocessing_profile.sha256",
                "preprocessing profile must be pinned by lowercase 64-hex sha256",
            )

    return contract


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

    contract = model.get("input_contract")
    contract_window = (
        contract.get("window_voxels_zyx") if isinstance(contract, dict) else None
    )
    if (
        isinstance(window, list)
        and isinstance(contract_window, list)
        and window != contract_window
    ):
        _error(
            errors,
            "GP_INK_EVIDENCE_WINDOW",
            f"{p}.model_window_voxels_zyx",
            "held-out evaluation window must match the submitted model input contract",
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
    mesh_context_proofs: list[dict[str, Any]] = []
    scale_proofs: list[dict[str, Any]] = []
    vc3d_render_proofs: list[dict[str, Any]] = []
    banner_proof: dict[str, Any] | None = None

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
    zpa_report: dict[str, Any] | None = None
    source_attestation: dict[str, Any] | None = None
    if not isinstance(zarr_audit, dict):
        _error(
            errors,
            "GP_CT_AUDIT",
            "ct_volume.zarr_audit",
            "zarr-pyramid-audit provenance record is required",
        )
    else:
        zpa_report, source_attestation = _verify_zpa_evidence(
            zarr_audit=zarr_audit,
            root_dir=root_dir,
            volume_id=str(volume_id),
            errors=errors,
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

        _validate_model_input_contract(
            model_id=model_id,
            model=model,
            target=target,
            source_attestation=source_attestation,
            errors=errors,
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
        context_proof = _verify_vc3d_mesh_context(
            mesh_id=mesh_id,
            mesh=mesh,
            root_dir=root_dir,
            eligible_volume_id=str(volume_id),
            scroll_id=str(scroll_id),
            errors=errors,
        )
        if context_proof is not None:
            mesh_context_proofs.append(context_proof)

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
        scale_proof_summary = _check_render_scale_proof(
            render_id=render_id,
            render=render,
            target=target,
            root_dir=root_dir,
            errors=errors,
        )
        scale_proofs.append(scale_proof_summary)
        vc3d_proof = _check_vc3d_receipt(
            render_id=render_id,
            render=render,
            mesh=meshes.get(mesh_id) if isinstance(mesh_id, str) else None,
            eligible_volume_id=str(volume_id),
            target=target,
            scale_proof=scale_proof_summary,
            root_dir=root_dir,
            errors=errors,
        )
        vc3d_render_proofs.append(vc3d_proof)

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
                "input_contract": (
                    models.get(model_id, {}).get("input_contract")
                    if isinstance(model_id, str)
                    else None
                ),
                "source_metadata_semantics_sha256": (
                    source_attestation.get("metadata_semantics_sha256")
                    if isinstance(source_attestation, dict)
                    else None
                ),
                "region_exclusion": proof,
                "vc3d_receipt": vc3d_proof,
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
        banner_proof = _check_banner_proof(
            banner=banner,
            renders=renders,
            root_dir=root_dir,
            errors=errors,
        )

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
        "mesh_context_proofs": mesh_context_proofs,
        "scale_proofs": scale_proofs,
        "vc3d_render_proofs": vc3d_render_proofs,
        "banner_proof": banner_proof,
        "zarr_audit_proof": {
            "root": zpa_report.get("root") if isinstance(zpa_report, dict) else None,
            "integrity": (
                zpa_report.get("integrity") if isinstance(zpa_report, dict) else None
            ),
            "source_attestation": source_attestation,
        },
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
