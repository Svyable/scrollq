"""Held-out TIFXYZ surface recovery evaluation for ScrolIQ.

This trusted scorer compares predicted papyrus surfaces against private held-out
truth without exposing truth geometry to model-submission code. The public
evaluation spec freezes the exact volume, metric tolerance, hard vertex cap,
region IDs, optional topology gates, and a salted commitment to the private
truth before predictions are scored.

Primary metric:
    bidirectional_coverage =
        min(P(prediction vertices within tolerance of truth),
            P(truth vertices within tolerance of prediction))

The minimum penalizes both missing surface and extra / wrong-sheet surface.
Distances are exact over all valid TIFXYZ vertices up to the preregistered hard
cap. The evaluator never silently subsamples an oversized surface.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from PIL import Image
from scipy.ndimage import label as connected_components
from scipy.spatial import cKDTree

from .model_eval import ValidationError, validate_dataset_manifest
from .package_hash import sha256_path

SCHEMA_VERSION = 1
PRIMARY_METRIC = "bidirectional_coverage"
COORDINATE_SYSTEM = "base_voxel_xyz"
COMMITMENT_VERSION = "scroliq-segmentation-truth-commitment-v1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class SegmentationValidationError(ValidationError):
    """Raised when a segmentation evaluation contract or surface is invalid."""


def _canonical_bytes(document: Mapping[str, Any]) -> bytes:
    return json.dumps(
        document, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def digest(document: Mapping[str, Any]) -> str:
    """Canonical SHA-256 for JSON evaluation contracts."""
    return hashlib.sha256(_canonical_bytes(document)).hexdigest()


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SegmentationValidationError(
            f"cannot read {label} {path}: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise SegmentationValidationError(f"{label} must be a JSON object")
    return value


def _schema_v1(document: Mapping[str, Any], label: str) -> None:
    if type(document.get("schema_version")) is not int or document["schema_version"] != 1:
        raise SegmentationValidationError(f"{label}.schema_version must be 1")


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SegmentationValidationError(f"{field} must be a non-empty string")
    return value.strip()


def _identifier(value: Any, field: str) -> str:
    text = _text(value, field)
    if not NAME_RE.fullmatch(text):
        raise SegmentationValidationError(
            f"{field} must match {NAME_RE.pattern!r}; got {text!r}"
        )
    return text


def _sha(value: Any, field: str) -> str:
    text = _text(value, field)
    if not SHA256_RE.fullmatch(text):
        raise SegmentationValidationError(f"{field} must be lowercase 64-hex")
    return text


def _positive_number(value: Any, field: str) -> float:
    if (
        type(value) not in (int, float)
        or not math.isfinite(float(value))
        or float(value) <= 0
    ):
        raise SegmentationValidationError(f"{field} must be a finite number > 0")
    return float(value)


def _positive_int(value: Any, field: str) -> int:
    if type(value) is not int or value < 1:
        raise SegmentationValidationError(f"{field} must be an integer >= 1")
    return value


def _fraction(value: Any, field: str) -> float:
    if (
        type(value) not in (int, float)
        or not math.isfinite(float(value))
        or not 0 <= float(value) <= 1
    ):
        raise SegmentationValidationError(f"{field} must be in [0, 1]")
    return float(value)


def _relative_path(value: Any, field: str) -> str:
    text = _text(value, field)
    path = Path(text)
    if path.is_absolute() or ".." in path.parts:
        raise SegmentationValidationError(
            f"{field} must be a relative path without '..'"
        )
    return path.as_posix()


def _resolve_under(root: Path, relative: str) -> Path:
    base = root.expanduser().resolve()
    candidate = (base / relative).resolve()
    if candidate != base and base not in candidate.parents:
        raise SegmentationValidationError(f"path escapes root: {relative}")
    return candidate


def _validate_dataset(document: Mapping[str, Any]) -> dict[str, Any]:
    dataset = validate_dataset_manifest(document)
    if dataset["task"] != "segmentation":
        raise SegmentationValidationError("dataset.task must be segmentation")
    metric = dataset["primary_metric"]
    if (
        metric["name"] != PRIMARY_METRIC
        or metric["higher_is_better"] is not True
        or metric["failure_value"] != 0.0
    ):
        raise SegmentationValidationError(
            "segmentation datasets must preregister primary_metric "
            "bidirectional_coverage, higher_is_better=true, failure_value=0"
        )
    return dataset


def validate_spec(
    document: Mapping[str, Any], *, dataset_document: Mapping[str, Any]
) -> dict[str, Any]:
    """Validate the public, preregistered segmentation metric contract."""
    _schema_v1(document, "spec")
    dataset = _validate_dataset(dataset_document)
    dataset_id = _identifier(document.get("dataset"), "spec.dataset")
    if dataset_id != dataset["id"]:
        raise SegmentationValidationError("spec.dataset does not match dataset manifest")

    dataset_sha = _sha(
        document.get("dataset_manifest_sha256"), "spec.dataset_manifest_sha256"
    )
    expected_dataset_sha = digest(dataset_document)
    if dataset_sha != expected_dataset_sha:
        raise SegmentationValidationError(
            "spec.dataset_manifest_sha256 does not match the dataset manifest"
        )

    truth_commitment = _sha(
        document.get("truth_commitment_sha256"), "spec.truth_commitment_sha256"
    )
    volume_root = _text(document.get("volume_root"), "spec.volume_root")
    coordinate_system = _text(
        document.get("coordinate_system"), "spec.coordinate_system"
    )
    if coordinate_system != COORDINATE_SYSTEM:
        raise SegmentationValidationError(
            f"spec.coordinate_system must be {COORDINATE_SYSTEM}"
        )
    tolerance = _positive_number(
        document.get("tolerance_voxels"), "spec.tolerance_voxels"
    )
    max_vertices = _positive_int(
        document.get("max_vertices_per_surface"),
        "spec.max_vertices_per_surface",
    )

    rows = document.get("regions")
    if not isinstance(rows, list) or not rows:
        raise SegmentationValidationError("spec.regions must be a non-empty list")
    normalized_regions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise SegmentationValidationError("each spec.regions entry must be an object")
        region_id = _identifier(row.get("id"), "spec.regions[].id")
        if region_id in seen:
            raise SegmentationValidationError(f"duplicate spec region id: {region_id}")
        seen.add(region_id)
        normalized: dict[str, Any] = {"id": region_id}
        if row.get("max_prediction_components") is not None:
            normalized["max_prediction_components"] = _positive_int(
                row["max_prediction_components"],
                f"spec region {region_id}.max_prediction_components",
            )
        if row.get("min_largest_component_fraction") is not None:
            normalized["min_largest_component_fraction"] = _fraction(
                row["min_largest_component_fraction"],
                f"spec region {region_id}.min_largest_component_fraction",
            )
        normalized_regions.append(normalized)

    expected_ids = {row["id"] for row in dataset["regions"]}
    if seen != expected_ids:
        missing = sorted(expected_ids - seen)
        extra = sorted(seen - expected_ids)
        raise SegmentationValidationError(
            f"spec regions must exactly match dataset regions; missing={missing}, extra={extra}"
        )

    return {
        "schema_version": 1,
        "dataset": dataset_id,
        "dataset_manifest_sha256": dataset_sha,
        "truth_commitment_sha256": truth_commitment,
        "volume_root": volume_root,
        "coordinate_system": coordinate_system,
        "tolerance_voxels": tolerance,
        "max_vertices_per_surface": max_vertices,
        "regions": normalized_regions,
    }


def validate_truth_manifest(
    document: Mapping[str, Any],
    *,
    dataset: Mapping[str, Any],
    volume_root: str | None = None,
    coordinate_system: str | None = None,
) -> dict[str, Any]:
    """Validate the private truth locations without exposing their content hashes."""
    _schema_v1(document, "truth")
    dataset_id = _identifier(document.get("dataset"), "truth.dataset")
    if dataset_id != dataset["id"]:
        raise SegmentationValidationError("truth.dataset does not match dataset manifest")
    declared_volume = _text(document.get("volume_root"), "truth.volume_root")
    declared_coords = _text(
        document.get("coordinate_system"), "truth.coordinate_system"
    )
    if declared_coords != COORDINATE_SYSTEM:
        raise SegmentationValidationError(
            f"truth.coordinate_system must be {COORDINATE_SYSTEM}"
        )
    if volume_root is not None and declared_volume != volume_root:
        raise SegmentationValidationError("truth.volume_root does not match spec")
    if coordinate_system is not None and declared_coords != coordinate_system:
        raise SegmentationValidationError("truth.coordinate_system does not match spec")

    salt = _sha(document.get("commitment_salt"), "truth.commitment_salt")
    rows = document.get("regions")
    if not isinstance(rows, list) or not rows:
        raise SegmentationValidationError("truth.regions must be a non-empty list")
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise SegmentationValidationError("each truth.regions entry must be an object")
        region_id = _identifier(row.get("id"), "truth.regions[].id")
        if region_id in seen:
            raise SegmentationValidationError(f"duplicate truth region id: {region_id}")
        seen.add(region_id)
        normalized.append(
            {
                "id": region_id,
                "tifxyz": _relative_path(
                    row.get("tifxyz"), f"truth region {region_id}.tifxyz"
                ),
            }
        )
    expected = {row["id"] for row in dataset["regions"]}
    if seen != expected:
        missing = sorted(expected - seen)
        extra = sorted(seen - expected)
        raise SegmentationValidationError(
            f"truth regions must exactly match dataset regions; missing={missing}, extra={extra}"
        )
    return {
        "schema_version": 1,
        "dataset": dataset_id,
        "volume_root": declared_volume,
        "coordinate_system": declared_coords,
        "commitment_salt": salt,
        "regions": normalized,
    }


def _validate_provenance(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise SegmentationValidationError("predictions.provenance must be an object")
    out: dict[str, str] = {}
    for field in (
        "checkpoint_sha256",
        "inference_script_sha256",
        "inference_config_sha256",
    ):
        out[field] = _sha(value.get(field), f"predictions.provenance.{field}")
    return out


def validate_predictions(
    document: Mapping[str, Any],
    *,
    dataset: Mapping[str, Any],
    spec_sha256: str,
    volume_root: str,
    coordinate_system: str,
) -> dict[str, Any]:
    """Validate untrusted inference output before hidden truth is consulted."""
    _schema_v1(document, "predictions")
    model = _identifier(document.get("model"), "predictions.model")
    dataset_id = _identifier(document.get("dataset"), "predictions.dataset")
    if dataset_id != dataset["id"]:
        raise SegmentationValidationError(
            "predictions.dataset does not match dataset manifest"
        )
    if _sha(document.get("spec_sha256"), "predictions.spec_sha256") != spec_sha256:
        raise SegmentationValidationError("predictions.spec_sha256 does not match spec")
    if _text(document.get("volume_root"), "predictions.volume_root") != volume_root:
        raise SegmentationValidationError("predictions.volume_root does not match spec")
    if (
        _text(document.get("coordinate_system"), "predictions.coordinate_system")
        != coordinate_system
    ):
        raise SegmentationValidationError(
            "predictions.coordinate_system does not match spec"
        )
    provenance = _validate_provenance(document.get("provenance"))

    rows = document.get("regions")
    if not isinstance(rows, list):
        raise SegmentationValidationError("predictions.regions must be a list")
    expected = {row["id"] for row in dataset["regions"]}
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise SegmentationValidationError(
                "each predictions.regions entry must be an object"
            )
        region_id = _identifier(row.get("id"), "predictions.regions[].id")
        if region_id not in expected:
            raise SegmentationValidationError(
                f"predictions contains unknown region id: {region_id}"
            )
        if region_id in seen:
            raise SegmentationValidationError(
                f"duplicate prediction region id: {region_id}"
            )
        seen.add(region_id)
        status = row.get("status")
        if status == "ok":
            normalized.append(
                {
                    "id": region_id,
                    "status": "ok",
                    "tifxyz": _relative_path(
                        row.get("tifxyz"), f"prediction region {region_id}.tifxyz"
                    ),
                }
            )
        elif status == "failed":
            normalized.append(
                {
                    "id": region_id,
                    "status": "failed",
                    "reason": _text(
                        row.get("reason"), f"prediction region {region_id}.reason"
                    ),
                }
            )
        else:
            raise SegmentationValidationError(
                f"prediction region {region_id}: status must be ok or failed"
            )

    return {
        "schema_version": 1,
        "model": model,
        "dataset": dataset_id,
        "spec_sha256": spec_sha256,
        "volume_root": volume_root,
        "coordinate_system": coordinate_system,
        "provenance": provenance,
        "regions": normalized,
    }


def _read_tiff(path: Path) -> np.ndarray:
    try:
        with Image.open(path) as image:
            array = np.asarray(image)
    except OSError as exc:
        raise SegmentationValidationError(f"cannot read TIFF {path}: {exc}") from exc
    if array.ndim == 3:
        array = array[..., 0]
    if array.ndim != 2:
        raise SegmentationValidationError(f"{path} must be a 2D TIFF")
    return array


def _mask_keep(mask_path: Path, shape: tuple[int, int]) -> np.ndarray:
    raw = _read_tiff(mask_path)
    h, w = shape
    mh, mw = raw.shape
    if mh < h or mw < w or mh % h or mw % w:
        raise SegmentationValidationError(
            f"{mask_path}: mask dimensions must be positive integer multiples "
            "of the coordinate grid"
        )
    sy, sx = mh // h, mw // w
    return (raw >= 255).reshape(h, sy, w, sx).all(axis=(1, 3))


def _load_tifxyz(
    root: Path, *, max_vertices: int
) -> dict[str, Any]:
    if not root.is_dir():
        raise SegmentationValidationError(f"TIFXYZ surface is not a directory: {root}")
    required = [root / name for name in ("x.tif", "y.tif", "z.tif", "meta.json")]
    missing = [str(path.name) for path in required if not path.is_file()]
    if missing:
        raise SegmentationValidationError(
            f"{root}: missing required TIFXYZ file(s): {', '.join(missing)}"
        )

    x = _read_tiff(root / "x.tif")
    y = _read_tiff(root / "y.tif")
    z = _read_tiff(root / "z.tif")
    if x.shape != y.shape or x.shape != z.shape:
        raise SegmentationValidationError(
            f"{root}: x/y/z coordinate shapes differ: {x.shape}, {y.shape}, {z.shape}"
        )

    try:
        meta = json.loads((root / "meta.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SegmentationValidationError(f"{root}: invalid meta.json: {exc}") from exc
    if not isinstance(meta, dict) or meta.get("format") != "tifxyz":
        raise SegmentationValidationError(
            f"{root}: meta.json must declare format='tifxyz'"
        )

    z_float = np.asarray(z, dtype=np.float64)
    valid = z_float > 0
    finite = (
        np.isfinite(np.asarray(x, dtype=np.float64))
        & np.isfinite(np.asarray(y, dtype=np.float64))
        & np.isfinite(z_float)
    )
    if np.any(valid & ~finite):
        raise SegmentationValidationError(
            f"{root}: valid TIFXYZ vertices contain non-finite coordinates"
        )
    valid &= finite

    mask_path = root / "mask.tif"
    if mask_path.exists():
        valid &= _mask_keep(mask_path, x.shape)

    count = int(valid.sum())
    if count == 0:
        raise SegmentationValidationError(f"{root}: no valid TIFXYZ vertices")
    if count > max_vertices:
        raise SegmentationValidationError(
            f"{root}: {count} valid vertices exceeds preregistered cap "
            f"{max_vertices}; split the held-out region rather than subsampling"
        )

    xyz = np.column_stack(
        (
            np.asarray(x, dtype=np.float64)[valid],
            np.asarray(y, dtype=np.float64)[valid],
            z_float[valid],
        )
    )
    if not np.all(np.isfinite(xyz)):
        raise SegmentationValidationError(f"{root}: non-finite valid XYZ coordinates")

    structure = np.array(
        [[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=np.uint8
    )
    labels, component_count = connected_components(valid, structure=structure)
    if component_count:
        sizes = np.bincount(labels[labels > 0].reshape(-1))
        largest = int(sizes.max()) if sizes.size else 0
    else:
        largest = 0

    return {
        "points": xyz,
        "valid_vertices": count,
        "components": int(component_count),
        "largest_component_fraction": float(largest / count),
        "grid_shape_yx": [int(x.shape[0]), int(x.shape[1])],
        "sha256": sha256_path(root),
    }


def _nearest_distances(query: np.ndarray, reference: np.ndarray) -> np.ndarray:
    tree = cKDTree(reference)
    distances, _ = tree.query(query, k=1, workers=1)
    distances = np.asarray(distances, dtype=np.float64)
    if not np.all(np.isfinite(distances)):
        raise SegmentationValidationError("nearest-surface distances are non-finite")
    return distances


def _distance_summary(distances: np.ndarray) -> tuple[float, float, float]:
    q = np.quantile(distances, [0.5, 0.95, 1.0])
    return float(q[0]), float(q[1]), float(q[2])


def _region_metrics(
    truth_surface: Mapping[str, Any],
    prediction_surface: Mapping[str, Any],
    *,
    tolerance: float,
) -> dict[str, float]:
    truth = np.asarray(truth_surface["points"], dtype=np.float64)
    pred = np.asarray(prediction_surface["points"], dtype=np.float64)
    truth_to_pred = _nearest_distances(truth, pred)
    pred_to_truth = _nearest_distances(pred, truth)

    t_cov = float(np.mean(truth_to_pred <= tolerance))
    p_cov = float(np.mean(pred_to_truth <= tolerance))
    t50, t95, tmax = _distance_summary(truth_to_pred)
    p50, p95, pmax = _distance_summary(pred_to_truth)

    return {
        PRIMARY_METRIC: min(t_cov, p_cov),
        "truth_to_prediction_coverage": t_cov,
        "prediction_to_truth_coverage": p_cov,
        "truth_to_prediction_p50_voxels": t50,
        "truth_to_prediction_p95_voxels": t95,
        "truth_to_prediction_max_voxels": tmax,
        "prediction_to_truth_p50_voxels": p50,
        "prediction_to_truth_p95_voxels": p95,
        "prediction_to_truth_max_voxels": pmax,
        "symmetric_p95_voxels": max(t95, p95),
        "truth_valid_vertices": float(truth_surface["valid_vertices"]),
        "prediction_valid_vertices": float(prediction_surface["valid_vertices"]),
        "truth_components": float(truth_surface["components"]),
        "prediction_components": float(prediction_surface["components"]),
        "truth_largest_component_fraction": float(
            truth_surface["largest_component_fraction"]
        ),
        "prediction_largest_component_fraction": float(
            prediction_surface["largest_component_fraction"]
        ),
    }


def _truth_commitment(
    *,
    salt_hex: str,
    dataset_manifest_sha256: str,
    volume_root: str,
    coordinate_system: str,
    surface_hashes: Mapping[str, str],
) -> str:
    payload = {
        "dataset_manifest_sha256": dataset_manifest_sha256,
        "volume_root": volume_root,
        "coordinate_system": coordinate_system,
        "regions": [
            {"id": region_id, "surface_sha256": surface_hashes[region_id]}
            for region_id in sorted(surface_hashes)
        ],
    }
    h = hashlib.sha256()
    h.update(COMMITMENT_VERSION.encode("ascii"))
    h.update(b"\0")
    h.update(bytes.fromhex(salt_hex))
    h.update(b"\0")
    h.update(_canonical_bytes(payload))
    return h.hexdigest()


def compute_truth_commitment(
    *,
    dataset_document: Mapping[str, Any],
    truth_document: Mapping[str, Any],
    truth_root: Path,
    max_vertices: int | None = None,
) -> dict[str, Any]:
    """Hash private truth surfaces into a salted public commitment."""
    dataset = _validate_dataset(dataset_document)
    truth = validate_truth_manifest(truth_document, dataset=dataset)
    hashes: dict[str, str] = {}
    counts: dict[str, int] = {}
    cap = max_vertices if max_vertices is not None else 2**63 - 1
    for row in truth["regions"]:
        surface = _load_tifxyz(
            _resolve_under(truth_root, row["tifxyz"]), max_vertices=cap
        )
        hashes[row["id"]] = surface["sha256"]
        counts[row["id"]] = surface["valid_vertices"]
    commitment = _truth_commitment(
        salt_hex=truth["commitment_salt"],
        dataset_manifest_sha256=digest(dataset_document),
        volume_root=truth["volume_root"],
        coordinate_system=truth["coordinate_system"],
        surface_hashes=hashes,
    )
    return {
        "commitment_version": COMMITMENT_VERSION,
        "truth_commitment_sha256": commitment,
        "region_count": len(hashes),
        "valid_vertices": counts,
    }


def evaluate(
    *,
    dataset_document: Mapping[str, Any],
    spec_document: Mapping[str, Any],
    truth_document: Mapping[str, Any],
    predictions_document: Mapping[str, Any],
    truth_root: Path,
    prediction_root: Path,
) -> dict[str, Any]:
    """Evaluate one model's TIFXYZ predictions against private held-out truth."""
    dataset = _validate_dataset(dataset_document)
    spec = validate_spec(spec_document, dataset_document=dataset_document)
    spec_sha = digest(spec_document)
    truth = validate_truth_manifest(
        truth_document,
        dataset=dataset,
        volume_root=spec["volume_root"],
        coordinate_system=spec["coordinate_system"],
    )
    predictions = validate_predictions(
        predictions_document,
        dataset=dataset,
        spec_sha256=spec_sha,
        volume_root=spec["volume_root"],
        coordinate_system=spec["coordinate_system"],
    )

    truth_rows = {row["id"]: row for row in truth["regions"]}
    truth_surfaces: dict[str, dict[str, Any]] = {}
    truth_hashes: dict[str, str] = {}
    for region in spec["regions"]:
        region_id = region["id"]
        loaded = _load_tifxyz(
            _resolve_under(truth_root, truth_rows[region_id]["tifxyz"]),
            max_vertices=spec["max_vertices_per_surface"],
        )
        truth_surfaces[region_id] = loaded
        truth_hashes[region_id] = loaded["sha256"]

    observed_commitment = _truth_commitment(
        salt_hex=truth["commitment_salt"],
        dataset_manifest_sha256=spec["dataset_manifest_sha256"],
        volume_root=spec["volume_root"],
        coordinate_system=spec["coordinate_system"],
        surface_hashes=truth_hashes,
    )
    if observed_commitment != spec["truth_commitment_sha256"]:
        raise SegmentationValidationError(
            "private truth does not match spec.truth_commitment_sha256"
        )

    prediction_rows = {row["id"]: row for row in predictions["regions"]}
    output_rows: list[dict[str, Any]] = []
    for region in spec["regions"]:
        region_id = region["id"]
        pred_row = prediction_rows.get(region_id)
        base_evidence = {
            "dataset_manifest": spec["dataset_manifest_sha256"],
            "segmentation_spec": spec_sha,
            "truth_commitment": observed_commitment,
        }
        if pred_row is None:
            output_rows.append(
                {
                    "id": region_id,
                    "status": "failed",
                    "reason": "prediction manifest emitted no result for region",
                    "evidence_sha256": base_evidence,
                }
            )
            continue
        if pred_row["status"] == "failed":
            output_rows.append(
                {
                    "id": region_id,
                    "status": "failed",
                    "reason": pred_row["reason"],
                    "evidence_sha256": base_evidence,
                }
            )
            continue

        try:
            pred_surface = _load_tifxyz(
                _resolve_under(prediction_root, pred_row["tifxyz"]),
                max_vertices=spec["max_vertices_per_surface"],
            )
            metrics = _region_metrics(
                truth_surfaces[region_id],
                pred_surface,
                tolerance=spec["tolerance_voxels"],
            )
            evidence = {
                **base_evidence,
                "prediction_surface": pred_surface["sha256"],
            }

            failures: list[str] = []
            max_components = region.get("max_prediction_components")
            if (
                max_components is not None
                and pred_surface["components"] > max_components
            ):
                failures.append(
                    f"prediction has {pred_surface['components']} components; "
                    f"maximum is {max_components}"
                )
            min_fraction = region.get("min_largest_component_fraction")
            if (
                min_fraction is not None
                and pred_surface["largest_component_fraction"] < min_fraction
            ):
                failures.append(
                    "prediction largest-component fraction "
                    f"{pred_surface['largest_component_fraction']:.6g} is below "
                    f"{min_fraction:.6g}"
                )

            if failures:
                output_rows.append(
                    {
                        "id": region_id,
                        "status": "failed",
                        "reason": "; ".join(failures),
                        "metrics": metrics,
                        "evidence_sha256": evidence,
                    }
                )
            else:
                output_rows.append(
                    {
                        "id": region_id,
                        "status": "ok",
                        "metrics": metrics,
                        "evidence_sha256": evidence,
                    }
                )
        except (OSError, ValueError, SegmentationValidationError) as exc:
            output_rows.append(
                {
                    "id": region_id,
                    "status": "failed",
                    "reason": f"surface evaluation failed: {exc}",
                    "evidence_sha256": base_evidence,
                }
            )

    return {
        "schema_version": 1,
        "model": predictions["model"],
        "dataset": dataset["id"],
        "task": "segmentation",
        "provenance": predictions["provenance"],
        "regions": output_rows,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Trusted held-out TIFXYZ segmentation scorer. Public model inference "
            "must run separately without access to --truth or truth surfaces."
        )
    )
    parser.add_argument("--dataset", required=True, help="held-out dataset manifest JSON")
    parser.add_argument("--spec", help="public frozen segmentation evaluation spec JSON")
    parser.add_argument("--truth", help="private truth manifest JSON; trusted modes only")
    parser.add_argument(
        "--predictions",
        help="prediction manifest from the untrusted inference phase",
    )
    parser.add_argument(
        "--truth-root",
        help="root for truth TIFXYZ relative paths; defaults to truth manifest directory",
    )
    parser.add_argument(
        "--prediction-root",
        help="root for prediction TIFXYZ paths; defaults to prediction manifest directory",
    )
    parser.add_argument(
        "--print-truth-commitment",
        action="store_true",
        help=(
            "hash private truth into a salted public commitment before the final "
            "spec is frozen; does not require --spec or --predictions"
        ),
    )
    parser.add_argument(
        "--print-spec-hash",
        action="store_true",
        help="validate --spec against --dataset and print its canonical SHA-256",
    )
    parser.add_argument("--out", help="new common region-results JSON path")
    args = parser.parse_args(argv)

    try:
        dataset_path = Path(args.dataset)
        dataset_document = _load_object(dataset_path, "dataset manifest")

        if args.print_spec_hash:
            if not args.spec:
                parser.error("--spec is required with --print-spec-hash")
            if args.predictions or args.out or args.truth or args.truth_root:
                parser.error(
                    "--print-spec-hash is public-only and cannot be combined with "
                    "--truth/--truth-root/--predictions/--out"
                )
            spec_document = _load_object(Path(args.spec), "segmentation spec")
            validate_spec(spec_document, dataset_document=dataset_document)
            print(digest(spec_document))
            return 0

        if not args.truth:
            parser.error("--truth is required for trusted truth/evaluation modes")
        truth_path = Path(args.truth)
        truth_document = _load_object(truth_path, "truth manifest")
        truth_root = Path(args.truth_root) if args.truth_root else truth_path.parent

        if args.print_truth_commitment:
            if args.predictions or args.out:
                parser.error(
                    "--print-truth-commitment cannot be combined with --predictions/--out"
                )
            result = compute_truth_commitment(
                dataset_document=dataset_document,
                truth_document=truth_document,
                truth_root=truth_root,
            )
            print(result["truth_commitment_sha256"])
            return 0

        if not args.spec:
            parser.error("--spec is required unless --print-truth-commitment is used")
        spec_path = Path(args.spec)
        spec_document = _load_object(spec_path, "segmentation spec")

        if not args.predictions:
            parser.error("--predictions is required for evaluation")
        predictions_path = Path(args.predictions)
        predictions_document = _load_object(predictions_path, "prediction manifest")
        prediction_root = (
            Path(args.prediction_root)
            if args.prediction_root
            else predictions_path.parent
        )

        result = evaluate(
            dataset_document=dataset_document,
            spec_document=spec_document,
            truth_document=truth_document,
            predictions_document=predictions_document,
            truth_root=truth_root,
            prediction_root=prediction_root,
        )
    except (SegmentationValidationError, ValidationError, OSError, ValueError) as exc:
        parser.error(str(exc))

    encoded = json.dumps(result, indent=2, allow_nan=False) + "\n"
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            with out.open("x", encoding="utf-8") as fh:
                fh.write(encoded)
        except OSError as exc:
            parser.error(str(exc))
    else:
        print(encoded, end="")

    failed = any(row["status"] == "failed" for row in result["regions"])
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
