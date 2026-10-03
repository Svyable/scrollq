"""Fail-closed triage for first-letter ink candidates on unread scrolls.

This command ranks *where to look next*. It intentionally does not recognize
letters and does not claim that any model output is ink. A review candidate has
to repeat across distinct checkpoints and be stronger on the proposed physical
surface than on falsification controls.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from statistics import median
from typing import Any, Sequence

import numpy as np
import tifffile

SCHEMA_VERSION = 1
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_CONTROL_KINDS = {"adjacent_winding", "geometry_perturbation"}
REQUIRED_NORMAL_OFFSETS = (-3.0, 3.0)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _load_2d(path: Path) -> np.ndarray:
    suffix = path.suffix.lower()
    if suffix == ".npy":
        arr = np.load(path, allow_pickle=False)
    elif suffix in {".tif", ".tiff"}:
        arr = tifffile.imread(path)
    else:
        raise ValueError(f"unsupported array format for {path}; expected .npy/.tif/.tiff")
    arr = np.asarray(arr)
    if arr.ndim != 2:
        raise ValueError(f"{path} must be 2D, got shape {arr.shape}")
    return arr


def _normalize(arr: np.ndarray, scale: str) -> np.ndarray:
    x = np.asarray(arr)
    if not np.all(np.isfinite(x)):
        raise ValueError("prediction contains NaN or infinite values")
    if scale == "unit":
        denom = 1.0
    elif scale == "uint8":
        denom = 255.0
    elif scale == "uint16":
        denom = 65535.0
    elif scale == "auto":
        if np.issubdtype(x.dtype, np.floating):
            lo = float(x.min(initial=0.0))
            hi = float(x.max(initial=0.0))
            if lo < 0.0 or hi > 1.0:
                raise ValueError("floating prediction outside [0,1]; declare scale explicitly")
            denom = 1.0
        elif x.dtype == np.uint8:
            denom = 255.0
        elif x.dtype == np.uint16:
            denom = 65535.0
        elif np.issubdtype(x.dtype, np.bool_):
            denom = 1.0
        else:
            raise ValueError(f"cannot infer prediction scale for dtype {x.dtype}")
    else:
        raise ValueError(f"unknown prediction scale {scale!r}")
    out = x.astype(np.float32, copy=False) / denom
    if float(out.min(initial=0.0)) < 0.0 or float(out.max(initial=0.0)) > 1.0:
        raise ValueError("normalized prediction is outside [0,1]")
    return out


def _bbox(value: Any) -> list[list[float]]:
    if (
        not isinstance(value, list)
        or len(value) != 2
        or any(not isinstance(row, list) or len(row) != 3 for row in value)
    ):
        raise ValueError("bbox_zyx_half_open must be [[z0,y0,x0],[z1,y1,x1]]")
    try:
        out = [[float(v) for v in row] for row in value]
    except (TypeError, ValueError) as exc:
        raise ValueError("bbox_zyx_half_open must be numeric") from exc
    if any(not math.isfinite(v) for row in out for v in row):
        raise ValueError("bbox_zyx_half_open must be finite")
    if any(out[0][i] >= out[1][i] for i in range(3)):
        raise ValueError("bbox_zyx_half_open must use increasing half-open bounds")
    return out


def _surface_seating_record(record: Any, base_dir: Path) -> tuple[bool, dict[str, Any] | None, list[str], list[str]]:
    """Validate and hash the artifact that admits a surface to ink triage.

    The hunt command does not decide whether a surface is physically correct; it
    requires a separate seating/orientation artifact to have done that job. This
    prevents strong ink-model output on a sheet switch or m7 orientation failure
    from becoming a review candidate.
    """
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(record, dict):
        return False, None, errors, ["surface_seating evidence is required"]

    state = record.get("state")
    if state not in {"pass", "fail", "unknown"}:
        errors.append("surface_seating.state must be pass, fail, or unknown")

    raw_path = record.get("path")
    if not isinstance(raw_path, str) or not raw_path:
        errors.append("surface_seating.path is required")
        return False, {"state": state}, errors, warnings
    path = Path(raw_path)
    if not path.is_absolute():
        path = base_dir / path
    if not path.is_file():
        errors.append(f"surface_seating artifact does not exist: {raw_path}")
        return False, {"state": state, "path": raw_path}, errors, warnings

    actual_sha = _sha256_file(path)
    declared_sha = record.get("sha256")
    if declared_sha is not None:
        if not isinstance(declared_sha, str) or not SHA256_RE.fullmatch(declared_sha):
            errors.append("surface_seating.sha256 must be lowercase hexadecimal SHA-256")
        elif declared_sha != actual_sha:
            errors.append("surface_seating.sha256 does not match the artifact")

    method = record.get("method")
    if not isinstance(method, str) or not method:
        warnings.append("surface_seating.method is not declared")

    meta = {
        "state": state,
        "path": raw_path,
        "sha256": actual_sha,
        "method": method,
    }
    return state == "pass" and not errors, meta, errors, warnings


def _array_record(record: Any, base_dir: Path) -> tuple[np.ndarray, dict[str, Any]]:
    if not isinstance(record, dict):
        raise ValueError("prediction record must be an object")
    raw_path = record.get("path")
    if not isinstance(raw_path, str) or not raw_path:
        raise ValueError("prediction record path is required")
    path = Path(raw_path)
    if not path.is_absolute():
        path = base_dir / path
    if not path.is_file():
        raise ValueError(f"prediction file does not exist: {raw_path}")
    scale = record.get("scale", "auto")
    if scale not in {"auto", "unit", "uint8", "uint16"}:
        raise ValueError(f"unsupported prediction scale {scale!r}")
    arr = _normalize(_load_2d(path), str(scale))
    meta = {
        "path": raw_path,
        "sha256": _sha256_file(path),
        "shape": list(arr.shape),
        "scale": scale,
    }
    for key in (
        "id", "checkpoint_sha256", "seed", "direction", "depth_offset_voxels",
        "kind", "name", "offset_voxels", "model_window_voxels_zyx",
    ):
        if key in record:
            meta[key] = record[key]
    return arr, meta


def _signal_metrics(arr: np.ndarray, threshold: float) -> dict[str, float]:
    mask = arr >= threshold
    return {
        "signal_fraction": float(mask.mean()),
        "mean_probability": float(arr.mean()),
        "p999_probability": float(np.quantile(arr, 0.999)),
    }


def _iou(a: np.ndarray, b: np.ndarray) -> float | None:
    union = int(np.count_nonzero(a | b))
    if union == 0:
        return None
    return float(np.count_nonzero(a & b) / union)


def _mean_pairwise_iou(arrays: list[np.ndarray], threshold: float) -> float | None:
    values: list[float] = []
    binary = [a >= threshold for a in arrays]
    for i in range(len(binary)):
        for j in range(i + 1, len(binary)):
            value = _iou(binary[i], binary[j])
            if value is not None:
                values.append(value)
    return float(sum(values) / len(values)) if values else None


def _candidate_report(
    candidate: Any,
    *,
    base_dir: Path,
    threshold: float,
    min_primary_signal_fraction: float,
    min_localization_margin: float,
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(candidate, dict):
        return {"id": None, "status": "invalid", "errors": ["candidate must be an object"], "warnings": []}

    candidate_id = candidate.get("id")
    if not isinstance(candidate_id, str) or not candidate_id:
        errors.append("candidate.id must be a non-empty string")

    try:
        bbox = _bbox(candidate.get("bbox_zyx_half_open"))
    except ValueError as exc:
        bbox = None
        errors.append(str(exc))

    support = candidate.get("surface_support_frac")
    if support is not None:
        if type(support) not in (int, float) or not math.isfinite(float(support)) or not 0 <= float(support) <= 1:
            errors.append("surface_support_frac must be in [0,1]")
            support = None
        else:
            support = float(support)

    seating_ok, seating_meta, seating_errors, seating_warnings = _surface_seating_record(
        candidate.get("surface_seating"), base_dir
    )
    errors.extend(seating_errors)
    warnings.extend(seating_warnings)

    primary_raw = candidate.get("primary_predictions")
    primary_raw = primary_raw if isinstance(primary_raw, list) else []
    if len(primary_raw) < 2:
        warnings.append("fewer than two primary predictions were declared")

    primary_arrays: list[np.ndarray] = []
    primary_rows: list[dict[str, Any]] = []
    checkpoint_shas: set[str] = set()
    common_shape: tuple[int, ...] | None = None
    for i, record in enumerate(primary_raw):
        try:
            arr, meta = _array_record(record, base_dir)
        except ValueError as exc:
            errors.append(f"primary_predictions[{i}]: {exc}")
            continue
        if common_shape is None:
            common_shape = arr.shape
        elif arr.shape != common_shape:
            errors.append(f"primary_predictions[{i}] shape {arr.shape} differs from {common_shape}")
            continue
        sha = meta.get("checkpoint_sha256")
        if not isinstance(sha, str) or not SHA256_RE.fullmatch(sha):
            warnings.append(f"primary_predictions[{i}] lacks a lowercase checkpoint SHA-256")
        else:
            checkpoint_shas.add(sha)
        primary_arrays.append(arr)
        primary_rows.append({**meta, **_signal_metrics(arr, threshold)})

    if len(checkpoint_shas) < 2:
        warnings.append("fewer than two distinct checkpoint SHA-256 values are represented")

    controls_raw = candidate.get("controls")
    controls_raw = controls_raw if isinstance(controls_raw, list) else []
    control_rows: list[dict[str, Any]] = []
    control_kinds: set[str] = set()
    normal_offsets: set[float] = set()
    for i, record in enumerate(controls_raw):
        try:
            arr, meta = _array_record(record, base_dir)
        except ValueError as exc:
            errors.append(f"controls[{i}]: {exc}")
            continue
        if common_shape is not None and arr.shape != common_shape:
            errors.append(f"controls[{i}] shape {arr.shape} differs from {common_shape}")
            continue
        kind = meta.get("kind")
        if isinstance(kind, str):
            control_kinds.add(kind)
        if kind == "normal_offset":
            offset = meta.get("offset_voxels")
            if type(offset) in (int, float) and math.isfinite(float(offset)):
                normal_offsets.add(float(offset))
        control_rows.append({**meta, **_signal_metrics(arr, threshold)})

    missing_kinds = sorted(REQUIRED_CONTROL_KINDS - control_kinds)
    missing_offsets = [
        value for value in REQUIRED_NORMAL_OFFSETS
        if not any(abs(value - actual) <= 1e-9 for actual in normal_offsets)
    ]
    if missing_kinds:
        warnings.append("missing control kinds: " + ", ".join(missing_kinds))
    if missing_offsets:
        warnings.append("missing normal-offset controls: " + ", ".join(f"{v:g}" for v in missing_offsets))
    controls_complete = not missing_kinds and not missing_offsets

    if primary_arrays:
        signal_fractions = [row["signal_fraction"] for row in primary_rows]
        primary_median_signal = float(median(signal_fractions))
        stack = np.stack([a >= threshold for a in primary_arrays], axis=0)
        needed = len(primary_arrays) // 2 + 1
        consensus_fraction = float((stack.sum(axis=0) >= needed).mean())
        agreement_iou = _mean_pairwise_iou(primary_arrays, threshold)
    else:
        primary_median_signal = None
        consensus_fraction = None
        agreement_iou = None

    max_control_signal = (
        max(row["signal_fraction"] for row in control_rows)
        if control_rows else None
    )
    localization_margin = (
        primary_median_signal - max_control_signal
        if primary_median_signal is not None and max_control_signal is not None
        else None
    )

    evidence_complete = (
        seating_ok
        and controls_complete
        and len(checkpoint_shas) >= 2
        and len(primary_arrays) >= 2
    )
    signal_ok = (
        primary_median_signal is not None
        and primary_median_signal > min_primary_signal_fraction
    )
    localization_ok = (
        localization_margin is not None
        and localization_margin > min_localization_margin
    )
    status = (
        "invalid" if errors
        else "review" if evidence_complete and signal_ok and localization_ok
        else "hold"
    )

    return {
        "id": candidate_id,
        "bbox_zyx_half_open": bbox,
        "surface_support_frac": support,
        "surface_seating": seating_meta,
        "status": status,
        "threshold": threshold,
        "primary": {
            "count": len(primary_rows),
            "distinct_checkpoint_count": len(checkpoint_shas),
            "median_signal_fraction": primary_median_signal,
            "majority_consensus_signal_fraction": consensus_fraction,
            "mean_pairwise_positive_iou": agreement_iou,
            "predictions": primary_rows,
        },
        "controls": {
            "complete": controls_complete,
            "required_normal_offsets_voxels": list(REQUIRED_NORMAL_OFFSETS),
            "missing_normal_offsets_voxels": missing_offsets,
            "missing_kinds": missing_kinds,
            "max_signal_fraction": max_control_signal,
            "predictions": control_rows,
        },
        "localization_margin": localization_margin,
        "gates": {
            "evidence_complete": evidence_complete,
            "surface_seating_pass": seating_ok,
            "primary_signal_above_minimum": signal_ok,
            "localization_margin_above_minimum": localization_ok,
            "min_primary_signal_fraction": min_primary_signal_fraction,
            "min_localization_margin": min_localization_margin,
        },
        "errors": errors,
        "warnings": warnings,
    }


def build_hunt_report(
    manifest: dict[str, Any],
    *,
    base_dir: Path,
    expected_volume_root: str | None = None,
    threshold: float | None = None,
    min_primary_signal_fraction: float = 0.0,
    min_localization_margin: float = 0.0,
) -> dict[str, Any]:
    errors: list[str] = []
    if not isinstance(manifest, dict):
        return {"schema_version": SCHEMA_VERSION, "tool": "scroliq-first-letter-hunt", "status": "fail", "errors": ["manifest must be an object"]}

    volume_root = manifest.get("volume_root")
    if not isinstance(volume_root, str) or not volume_root:
        errors.append("volume_root must be a non-empty exact CT root")
    if expected_volume_root is not None and volume_root != expected_volume_root:
        errors.append("manifest volume_root does not match --expected-volume-root")

    if threshold is None:
        threshold = manifest.get("prediction_threshold", 0.5)
    if type(threshold) not in (int, float) or not math.isfinite(float(threshold)) or not 0 <= float(threshold) <= 1:
        errors.append("prediction threshold must be in [0,1]")
        threshold = 0.5
    threshold = float(threshold)

    for value, name in (
        (min_primary_signal_fraction, "min_primary_signal_fraction"),
        (min_localization_margin, "min_localization_margin"),
    ):
        if not math.isfinite(value):
            errors.append(f"{name} must be finite")
    if min_primary_signal_fraction < 0 or min_primary_signal_fraction > 1:
        errors.append("min_primary_signal_fraction must be in [0,1]")

    candidates_raw = manifest.get("candidates")
    candidates_raw = candidates_raw if isinstance(candidates_raw, list) else []
    if not candidates_raw:
        errors.append("at least one candidate is required")

    rows = [
        _candidate_report(
            candidate,
            base_dir=base_dir,
            threshold=threshold,
            min_primary_signal_fraction=min_primary_signal_fraction,
            min_localization_margin=min_localization_margin,
        )
        for candidate in candidates_raw
    ]
    ids = [row.get("id") for row in rows if row.get("id")]
    if len(ids) != len(set(ids)):
        errors.append("candidate ids must be unique")

    def rank_key(row: dict[str, Any]) -> tuple[Any, ...]:
        review = 1 if row.get("status") == "review" else 0
        margin = row.get("localization_margin")
        iou = row.get("primary", {}).get("mean_pairwise_positive_iou")
        support = row.get("surface_support_frac")
        consensus = row.get("primary", {}).get("majority_consensus_signal_fraction")
        return (
            -review,
            -(margin if isinstance(margin, (int, float)) else -math.inf),
            -(iou if isinstance(iou, (int, float)) else -math.inf),
            -(support if isinstance(support, (int, float)) else -math.inf),
            -(consensus if isinstance(consensus, (int, float)) else -math.inf),
            str(row.get("id") or ""),
        )

    ranked = sorted(rows, key=rank_key)
    for index, row in enumerate(ranked, start=1):
        row["rank"] = index

    return {
        "schema_version": SCHEMA_VERSION,
        "tool": "scroliq-first-letter-hunt",
        "purpose": "unknown-ground-truth ink candidate triage with physical falsification controls",
        "status": "fail" if errors else "ok",
        "volume_root": volume_root,
        "prediction_threshold": threshold,
        "ranking_rule": (
            "lexicographic: review-gate pass, localization margin, cross-checkpoint positive IoU, "
            "surface support, majority-consensus signal fraction, candidate id"
        ),
        "candidate_count": len(ranked),
        "review_candidate_count": sum(row.get("status") == "review" for row in ranked),
        "review_queue": ranked,
        "errors": errors,
        "limitation": (
            "This tool ranks windows for human/technical review. It does not identify a letter, "
            "prove biological ink, independently certify surface seating, or replace held-out validation "
            "on known ground truth. Distinct checkpoint hashes prove only checkpoint distinction, not "
            "independent training data."
        ),
    }


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Rank first-letter candidate windows by cross-checkpoint repeatability and "
            "suppression on physical falsification controls."
        )
    )
    ap.add_argument("manifest", help="JSON manifest describing candidates and prediction arrays")
    ap.add_argument("--out", required=True, help="Output JSON review queue")
    ap.add_argument("--expected-volume-root")
    ap.add_argument("--threshold", type=float, default=None)
    ap.add_argument("--min-primary-signal-fraction", type=float, default=0.0)
    ap.add_argument("--min-localization-margin", type=float, default=0.0)
    args = ap.parse_args(argv)

    manifest_path = Path(args.manifest)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    report = build_hunt_report(
        manifest,
        base_dir=manifest_path.parent,
        expected_volume_root=args.expected_volume_root,
        threshold=args.threshold,
        min_primary_signal_fraction=args.min_primary_signal_fraction,
        min_localization_margin=args.min_localization_margin,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 1 if report["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
