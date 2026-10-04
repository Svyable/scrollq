"""Surface-normal response falsification for held-out ink predictions.

The experiment keeps a frozen primary prediction at the submitted surface and
compares it with predictions generated at fixed signed offsets along the local
surface normal. It is deliberately a falsification/control artifact: protocol
completeness never implies that a mark is ink or that text is legible.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from scipy.ndimage import label as connected_components

from .ink_validation import (
    SHA256_RE,
    _load_2d,
    _normalize_prediction,
    _sha256_file,
    evaluate_prediction,
)

SCHEMA_VERSION = 2
PROTOCOL = "surface-normal-response-v1"
REQUIRED_OFFSETS_VOXELS = (-6, -4, -2, 2, 4, 6)


def _canonical_digest(
    prediction: np.ndarray,
    labels: np.ndarray,
    validation_mask: np.ndarray,
    normal_offsets: Mapping[int, np.ndarray],
) -> str:
    h = hashlib.sha256()

    def add(name: str, array: np.ndarray, dtype: str) -> None:
        encoded = name.encode("utf-8")
        canonical = np.asarray(array, dtype=dtype)
        h.update(len(encoded).to_bytes(8, "big"))
        h.update(encoded)
        h.update(len(canonical.shape).to_bytes(8, "big"))
        for size in canonical.shape:
            h.update(int(size).to_bytes(8, "big"))
        h.update(canonical.tobytes(order="C"))

    add("prediction@0", prediction, "<f4")
    add("labels", np.asarray(labels) > 0, "u1")
    add("validation_mask", np.asarray(validation_mask) > 0, "u1")
    for offset, array in sorted(normal_offsets.items()):
        add(f"prediction@{offset:+d}", array, "<f4")
    return h.hexdigest()


def _class_mean(values: np.ndarray, selected: np.ndarray) -> float | None:
    subset = np.asarray(values, dtype=np.float32)[selected]
    return float(subset.mean()) if subset.size else None


def _class_median(values: np.ndarray, selected: np.ndarray) -> float | None:
    subset = np.asarray(values, dtype=np.float32)[selected]
    return float(np.median(subset)) if subset.size else None


def _fraction(mask: np.ndarray, selected: np.ndarray) -> float | None:
    denom = int(np.count_nonzero(selected))
    if denom == 0:
        return None
    return float(np.count_nonzero(mask & selected) / denom)


def _delta(after: float | None, before: float | None) -> float | None:
    if after is None or before is None:
        return None
    return float(after - before)


def _peak_histogram(
    peak_offsets: np.ndarray,
    unique_peak: np.ndarray,
    selected: np.ndarray,
    offsets: Sequence[int],
) -> dict[str, int]:
    keep = unique_peak & selected
    return {
        f"{offset:+d}": int(np.count_nonzero(keep & (peak_offsets == offset)))
        for offset in offsets
    }


def _component_profiles(
    primary: np.ndarray,
    labels: np.ndarray,
    validation_mask: np.ndarray,
    offsets: Mapping[int, np.ndarray],
    *,
    threshold: float,
    min_component_pixels: int,
    surface_xyz: np.ndarray | None,
) -> dict[str, Any]:
    """Summarize fixed-support depth profiles for nominal predicted components.

    Components are defined once on the nominal thresholded prediction. Every
    offset is then measured on exactly that same pixel support; offset maps are
    never re-thresholded or re-segmented. This prevents a drifting component
    from manufacturing apparent depth consistency.
    """
    if (
        isinstance(min_component_pixels, bool)
        or not isinstance(min_component_pixels, int)
        or min_component_pixels < 1
    ):
        raise ValueError("min_component_pixels must be an integer >= 1")

    primary = np.asarray(primary, dtype=np.float32)
    labels = np.asarray(labels)
    mask = np.asarray(validation_mask)
    if surface_xyz is not None:
        surface_xyz = np.asarray(surface_xyz, dtype=np.float64)
        expected = primary.shape + (3,)
        if surface_xyz.shape != expected:
            raise ValueError(
                f"surface_xyz shape mismatch: expected {expected}, got "
                f"{surface_xyz.shape}"
            )
        if not np.all(np.isfinite(surface_xyz)):
            raise ValueError("surface_xyz must contain finite coordinates")

    binary = (primary >= threshold) & (mask > 0)
    component_map, component_count = connected_components(
        binary, structure=np.ones((3, 3), dtype=np.uint8)
    )
    all_offsets = tuple(sorted((0, *offsets)))
    arrays = {
        offset: primary if offset == 0 else np.asarray(offsets[offset], dtype=np.float32)
        for offset in all_offsets
    }

    rows: list[dict[str, Any]] = []
    review_queue: list[dict[str, Any]] = []
    ignored_small = 0
    for component_id in range(1, int(component_count) + 1):
        support = component_map == component_id
        pixels = int(np.count_nonzero(support))
        if pixels < min_component_pixels:
            ignored_small += 1
            continue

        means = {
            offset: float(np.asarray(arrays[offset], dtype=np.float32)[support].mean())
            for offset in all_offsets
        }
        nominal_mean = means[0]
        off_max = max(means[offset] for offset in offsets)
        strongest_off_offsets = [
            int(offset) for offset in sorted(offsets)
            if means[offset] == off_max
        ]
        global_max = max(means.values())
        peak_offsets = [
            int(offset) for offset in all_offsets if means[offset] == global_max
        ]
        strict_nominal_peak = nominal_mean > off_max
        half_level = 0.5 * nominal_mean
        half_support_offsets = [
            int(offset) for offset in all_offsets if means[offset] >= half_level
        ]
        half_span = (
            int(max(half_support_offsets) - min(half_support_offsets))
            if half_support_offsets
            else None
        )

        coords = np.argwhere(support)
        centroid_yx = coords.mean(axis=0)
        distance2 = np.sum((coords - centroid_yx[None, :]) ** 2, axis=1)
        review_pixel = coords[int(np.argmin(distance2))]
        ink_pixels = int(np.count_nonzero((labels > 0) & support))
        row: dict[str, Any] = {
            "component_id": int(component_id),
            "pixels": pixels,
            "centroid_yx": [float(centroid_yx[0]), float(centroid_yx[1])],
            "review_pixel_yx": [int(review_pixel[0]), int(review_pixel[1])],
            "ground_truth_ink_pixels": ink_pixels,
            "ground_truth_ink_fraction": float(ink_pixels / pixels),
            "has_ground_truth_ink": ink_pixels > 0,
            "profile": [
                {"offset_voxels": int(offset), "mean_probability": means[offset]}
                for offset in all_offsets
            ],
            "nominal_mean_probability": nominal_mean,
            "strongest_off_surface_mean_probability": float(off_max),
            "strongest_off_surface_offsets_voxels": strongest_off_offsets,
            "center_advantage_mean_probability": float(nominal_mean - off_max),
            "off_surface_persistence_ratio": (
                float(off_max / nominal_mean) if nominal_mean > 0 else None
            ),
            "peak_offsets_voxels": peak_offsets,
            "strict_nominal_peak": bool(strict_nominal_peak),
            "half_nominal_support_offsets_voxels": half_support_offsets,
            "half_nominal_support_span_voxels": half_span,
        }
        if surface_xyz is not None:
            xyz = surface_xyz[int(review_pixel[0]), int(review_pixel[1])]
            row["xyz"] = [float(value) for value in xyz]
        rows.append(row)

        if not strict_nominal_peak and "xyz" in row:
            review_queue.append(
                {
                    "component_id": row["component_id"],
                    "pixels": row["pixels"],
                    "xyz": row["xyz"],
                    "center_advantage_mean_probability": row[
                        "center_advantage_mean_probability"
                    ],
                    "nominal_mean_probability": row["nominal_mean_probability"],
                    "strongest_off_surface_mean_probability": row[
                        "strongest_off_surface_mean_probability"
                    ],
                    "strongest_off_surface_offsets_voxels": row[
                        "strongest_off_surface_offsets_voxels"
                    ],
                    "peak_offsets_voxels": row["peak_offsets_voxels"],
                    "has_ground_truth_ink": row["has_ground_truth_ink"],
                }
            )

    def group_summary(has_ink: bool) -> dict[str, Any]:
        group = [row for row in rows if row["has_ground_truth_ink"] is has_ink]
        strict = sum(bool(row["strict_nominal_peak"]) for row in group)
        return {
            "components": len(group),
            "strict_nominal_peak_components": strict,
            "strict_nominal_peak_fraction": (
                float(strict / len(group)) if group else None
            ),
        }

    strict_total = sum(bool(row["strict_nominal_peak"]) for row in rows)
    return {
        "definition": (
            "8-connected components of the nominal prediction at the declared "
            "threshold, restricted to the validation mask; every depth profile "
            "uses the fixed nominal component support"
        ),
        "min_component_pixels": min_component_pixels,
        "predicted_components_total": int(component_count),
        "analyzed_components": len(rows),
        "ignored_small_components": ignored_small,
        "strict_nominal_peak_components": strict_total,
        "review_candidate_components": len(rows) - strict_total,
        "review_candidate_rule": (
            "nominal component mean probability is not strictly greater than "
            "the mean probability on every non-zero surface offset"
        ),
        "ground_truth_groups": {
            "with_ink_overlap": group_summary(True),
            "without_ink_overlap": group_summary(False),
        },
        "components": rows,
        "review_queue": review_queue,
        "vc3d_review_ready": bool(review_queue),
        "claim_boundary": (
            "Component depth profiles are held-out falsification evidence, not "
            "a glyph recognizer. A non-nominal peak is a review cue; a nominal "
            "peak is not proof of ink."
        ),
    }


def evaluate_normal_response(
    prediction: np.ndarray,
    labels: np.ndarray,
    validation_mask: np.ndarray,
    normal_offsets: Mapping[int, np.ndarray],
    *,
    threshold: float = 0.5,
    min_component_pixels: int = 4,
    surface_xyz: np.ndarray | None = None,
) -> dict[str, Any]:
    """Measure whether held-out ink evidence is localized to the true surface."""
    primary = np.asarray(prediction, dtype=np.float32)
    primary_metrics = evaluate_prediction(
        primary, labels, validation_mask, threshold=threshold
    )
    raw_labels = np.asarray(labels)
    raw_mask = np.asarray(validation_mask)
    positive = (raw_labels > 0) & (raw_mask > 0)
    negative = (raw_labels == 0) & (raw_mask > 0)

    if not normal_offsets:
        raise ValueError("at least one non-zero normal offset is required")

    offsets: dict[int, np.ndarray] = {}
    offset_evaluations: list[dict[str, Any]] = []
    curve_rows: list[dict[str, Any]] = []

    for raw_offset, raw_array in normal_offsets.items():
        if isinstance(raw_offset, bool) or not isinstance(raw_offset, int):
            raise ValueError("normal offsets must be integer voxel displacements")
        if raw_offset == 0:
            raise ValueError("normal offset 0 is reserved for the primary prediction")
        if raw_offset in offsets:
            raise ValueError(f"duplicate normal offset {raw_offset}")

        arr = np.asarray(raw_array, dtype=np.float32)
        metrics = evaluate_prediction(
            arr, labels, validation_mask, threshold=threshold
        )
        offsets[raw_offset] = arr
        offset_evaluations.append(
            {"offset_voxels": int(raw_offset), "evaluation": metrics}
        )
        curve_rows.append(
            {
                "offset_voxels": int(raw_offset),
                "ink_probability_mean": _class_mean(arr, positive),
                "background_probability_mean": _class_mean(arr, negative),
            }
        )

    supplied = tuple(sorted(offsets))
    required = tuple(REQUIRED_OFFSETS_VOXELS)
    missing = [v for v in required if v not in offsets]
    extra = [v for v in supplied if v not in required]
    protocol_conformant = supplied == required

    off_stack = np.stack([offsets[v] for v in supplied], axis=0)
    strongest_off_surface = off_stack.max(axis=0)
    center_advantage = primary - strongest_off_surface
    strict_center_win = center_advantage > 0.0

    gated_prediction = (
        (primary >= threshold) & strict_center_win
    ).astype(np.float32)
    gated_metrics = evaluate_prediction(
        gated_prediction, labels, validation_mask, threshold=0.5
    )

    all_offsets = tuple(sorted((0, *supplied)))
    all_stack = np.stack(
        [primary if offset == 0 else offsets[offset] for offset in all_offsets],
        axis=0,
    )
    max_response = all_stack.max(axis=0)
    maxima = all_stack == max_response
    unique_peak = maxima.sum(axis=0) == 1
    argmax = np.argmax(all_stack, axis=0)
    peak_offsets = np.asarray(all_offsets, dtype=np.int32)[argmax]

    curve_rows.append(
        {
            "offset_voxels": 0,
            "ink_probability_mean": _class_mean(primary, positive),
            "background_probability_mean": _class_mean(primary, negative),
        }
    )
    curve_rows.sort(key=lambda row: row["offset_voxels"])
    offset_evaluations.sort(key=lambda row: row["offset_voxels"])

    localization = {
        "center_advantage_vs_strongest_offset": {
            "ink_mean": _class_mean(center_advantage, positive),
            "ink_median": _class_median(center_advantage, positive),
            "background_mean": _class_mean(center_advantage, negative),
            "background_median": _class_median(center_advantage, negative),
        },
        "strict_zero_peak_fraction": {
            "ink": _fraction(strict_center_win, positive),
            "background": _fraction(strict_center_win, negative),
        },
        "unique_peak_fraction": {
            "ink": _fraction(unique_peak, positive),
            "background": _fraction(unique_peak, negative),
        },
        "unique_peak_offset_histogram": {
            "ink": _peak_histogram(
                peak_offsets, unique_peak, positive, all_offsets
            ),
            "background": _peak_histogram(
                peak_offsets, unique_peak, negative, all_offsets
            ),
        },
    }

    components = _component_profiles(
        primary,
        labels,
        validation_mask,
        offsets,
        threshold=threshold,
        min_component_pixels=min_component_pixels,
        surface_xyz=surface_xyz,
    )

    return {
        "protocol": PROTOCOL,
        "required_offsets_voxels": list(required),
        "supplied_offsets_voxels": list(supplied),
        "protocol_conformant": protocol_conformant,
        "missing_offsets_voxels": missing,
        "extra_offsets_voxels": extra,
        "tie_policy": (
            "zero-surface localization requires a strict response maximum; "
            "ties do not count as center-localized"
        ),
        "curve": curve_rows,
        "primary_evaluation": primary_metrics,
        "offset_evaluations": offset_evaluations,
        "localization": localization,
        "components": components,
        "center_win_gate": {
            "rule": (
                "primary_probability >= threshold AND "
                "primary_probability > max(nonzero_offset_probabilities)"
            ),
            "evaluation": gated_metrics,
            "delta_vs_primary": {
                "precision": _delta(
                    gated_metrics["precision"], primary_metrics["precision"]
                ),
                "recall": _delta(gated_metrics["recall"], primary_metrics["recall"]),
                "false_positive_rate": _delta(
                    gated_metrics["false_positive_rate"],
                    primary_metrics["false_positive_rate"],
                ),
                "balanced_accuracy": _delta(
                    gated_metrics["balanced_accuracy"],
                    primary_metrics["balanced_accuracy"],
                ),
            },
        },
        "evaluated_arrays_sha256": _canonical_digest(
            primary, labels, validation_mask, offsets
        ),
    }


def build_report(
    *,
    prediction: np.ndarray,
    labels: np.ndarray,
    validation_mask: np.ndarray,
    normal_offsets: Mapping[int, np.ndarray],
    threshold: float,
    split_id: str,
    held_out: bool,
    training_overlap: str,
    ground_truth_source_url: str,
    model_checkpoint_sha256: str,
    model_window_voxels: Sequence[int],
    surface_geometry_sha256: str,
    sampling_manifest_sha256: str,
    input_records: dict[str, Any] | None = None,
    min_component_pixels: int = 4,
    surface_xyz: np.ndarray | None = None,
) -> dict[str, Any]:
    if training_overlap not in {"none", "present", "unknown"}:
        raise ValueError("training_overlap must be one of none/present/unknown")
    if not isinstance(split_id, str) or not split_id.strip():
        raise ValueError("split_id is required")
    if (
        not isinstance(ground_truth_source_url, str)
        or not ground_truth_source_url.startswith(("https://", "http://"))
    ):
        raise ValueError("ground_truth_source_url must be public http(s)")
    for value, name in (
        (model_checkpoint_sha256, "model_checkpoint_sha256"),
        (surface_geometry_sha256, "surface_geometry_sha256"),
        (sampling_manifest_sha256, "sampling_manifest_sha256"),
    ):
        if not SHA256_RE.fullmatch(value):
            raise ValueError(f"{name} must be lowercase 64-hex")
    if len(model_window_voxels) != 3 or any(
        not isinstance(v, int) or v <= 0 for v in model_window_voxels
    ):
        raise ValueError("model_window_voxels must be positive [z,y,x] integers")

    result = evaluate_normal_response(
        prediction,
        labels,
        validation_mask,
        normal_offsets,
        threshold=threshold,
        min_component_pixels=min_component_pixels,
        surface_xyz=surface_xyz,
    )

    reasons: list[str] = []
    if not held_out:
        reasons.append("validation split is not declared held-out")
    if training_overlap != "none":
        reasons.append("training/prediction overlap is not explicitly none")
    if not result["primary_evaluation"]["both_classes_present"]:
        reasons.append("validation mask does not contain both ink and background")
    if not result["protocol_conformant"]:
        reasons.append(
            "normal-offset grid does not exactly match surface-normal-response-v1"
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "tool": "scroliq-normal-response",
        "purpose": "held-out physical localization / false-positive falsification",
        "split": {
            "id": split_id,
            "held_out": bool(held_out),
            "training_overlap": training_overlap,
            "known_ground_truth": True,
            "ground_truth_source_url": ground_truth_source_url,
        },
        "model": {
            "checkpoint_sha256": model_checkpoint_sha256,
            "window_voxels_zyx": list(model_window_voxels),
        },
        "surface": {
            "geometry_sha256": surface_geometry_sha256,
            "sampling_manifest_sha256": sampling_manifest_sha256,
            "offset_units": "voxels along the frozen local surface normal",
        },
        "threshold": float(threshold),
        "normal_response": result,
        "inputs": input_records or {},
        "experimental_evidence_ready": not reasons,
        "readiness_reasons": reasons,
        "interpretation": (
            "experimental_evidence_ready means the frozen held-out protocol is "
            "complete enough to inspect; it is not proof of ink, legibility, "
            "or Grand Prize readiness"
        ),
    }


def _parse_window(text: str) -> tuple[int, int, int]:
    parts = re.split(r"[xX,]", text)
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("window must be ZxYxX, e.g. 17x256x256")
    try:
        values = tuple(int(v) for v in parts)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("window dimensions must be integers") from exc
    if any(v <= 0 for v in values):
        raise argparse.ArgumentTypeError("window dimensions must be positive")
    return values  # type: ignore[return-value]


def _parse_normal_offset(text: str) -> tuple[str, int]:
    if "@" not in text:
        raise argparse.ArgumentTypeError(
            "normal offset must be PATH@SIGNED_VOXELS, e.g. map.npy@-6"
        )
    path, raw_offset = text.rsplit("@", 1)
    if not path.strip():
        raise argparse.ArgumentTypeError("normal-offset path must not be empty")
    try:
        offset = int(raw_offset)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("normal offset must be an integer") from exc
    if offset == 0:
        raise argparse.ArgumentTypeError(
            "offset 0 is the primary prediction; provide only non-zero offsets"
        )
    return path, offset


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Measure whether a frozen held-out ink prediction is physically "
            "localized to the submitted surface across signed normal offsets."
        )
    )
    ap.add_argument("--prediction", required=True)
    ap.add_argument("--labels", required=True)
    ap.add_argument("--validation-mask", required=True)
    ap.add_argument(
        "--normal-offset",
        action="append",
        required=True,
        type=_parse_normal_offset,
        metavar="PATH@SIGNED_VOXELS",
        help=(
            "prediction generated at one signed surface-normal offset; repeat. "
            "Protocol v1 requires exactly -6,-4,-2,+2,+4,+6 voxels."
        ),
    )
    ap.add_argument(
        "--prediction-scale",
        choices=("auto", "unit", "uint8", "uint16"),
        default="auto",
    )
    ap.add_argument("--threshold", type=float, default=0.5)
    ap.add_argument("--split-id", required=True)
    ap.add_argument("--held-out", action="store_true")
    ap.add_argument(
        "--training-overlap",
        choices=("none", "present", "unknown"),
        default="unknown",
    )
    ap.add_argument("--ground-truth-source-url", required=True)
    ap.add_argument("--model-checkpoint-sha256", required=True)
    ap.add_argument("--model-window", type=_parse_window, required=True)
    ap.add_argument("--surface-geometry-sha256", required=True)
    ap.add_argument(
        "--surface-xyz",
        help=(
            "optional .npy array shaped (H,W,3) mapping prediction pixels to "
            "level-0 voxel XYZ for component review export"
        ),
    )
    ap.add_argument(
        "--min-component-pixels",
        type=int,
        default=4,
        help="ignore nominal predicted components smaller than this size (default: 4)",
    )
    ap.add_argument(
        "--sampling-manifest",
        required=True,
        help=(
            "frozen manifest describing geometry/normal convention, CT source, "
            "interpolation/sampling settings, and inference command"
        ),
    )
    ap.add_argument("--out", required=True)
    ap.add_argument("--format", choices=("text", "json", "github"), default="text")
    args = ap.parse_args(argv)

    prediction_path = Path(args.prediction)
    labels_path = Path(args.labels)
    mask_path = Path(args.validation_mask)
    sampling_manifest_path = Path(args.sampling_manifest)

    prediction = _normalize_prediction(
        _load_2d(prediction_path), args.prediction_scale
    )
    labels = _load_2d(labels_path)
    mask = _load_2d(mask_path)

    surface_xyz = None
    surface_xyz_path = None
    if args.surface_xyz:
        surface_xyz_path = Path(args.surface_xyz)
        try:
            surface_xyz = np.load(surface_xyz_path, allow_pickle=False)
        except (OSError, ValueError) as exc:
            raise SystemExit(f"cannot read --surface-xyz: {exc}") from exc

    normal_offsets: dict[int, np.ndarray] = {}
    normal_inputs: list[dict[str, Any]] = []
    for raw_path, offset in args.normal_offset:
        if offset in normal_offsets:
            raise SystemExit(f"duplicate normal offset: {offset}")
        path = Path(raw_path)
        normal_offsets[offset] = _normalize_prediction(
            _load_2d(path), args.prediction_scale
        )
        normal_inputs.append(
            {
                "offset_voxels": offset,
                "path": str(path),
                "sha256": _sha256_file(path),
            }
        )

    sampling_manifest_sha256 = _sha256_file(sampling_manifest_path)
    report = build_report(
        prediction=prediction,
        labels=labels,
        validation_mask=mask,
        normal_offsets=normal_offsets,
        threshold=args.threshold,
        split_id=args.split_id,
        held_out=args.held_out,
        training_overlap=args.training_overlap,
        ground_truth_source_url=args.ground_truth_source_url,
        model_checkpoint_sha256=args.model_checkpoint_sha256,
        model_window_voxels=args.model_window,
        surface_geometry_sha256=args.surface_geometry_sha256,
        sampling_manifest_sha256=sampling_manifest_sha256,
        min_component_pixels=args.min_component_pixels,
        surface_xyz=surface_xyz,
        input_records={
            "prediction": {
                "path": str(prediction_path),
                "sha256": _sha256_file(prediction_path),
            },
            "labels": {
                "path": str(labels_path),
                "sha256": _sha256_file(labels_path),
            },
            "validation_mask": {
                "path": str(mask_path),
                "sha256": _sha256_file(mask_path),
            },
            "sampling_manifest": {
                "path": str(sampling_manifest_path),
                "sha256": sampling_manifest_sha256,
            },
            "normal_offsets": sorted(
                normal_inputs, key=lambda row: row["offset_voxels"]
            ),
            **(
                {
                    "surface_xyz": {
                        "path": str(surface_xyz_path),
                        "sha256": _sha256_file(surface_xyz_path),
                    }
                }
                if surface_xyz_path is not None
                else {}
            ),
        },
    )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if args.format == "json":
        print(json.dumps(report, indent=2))
    elif args.format == "github":
        if not report["experimental_evidence_ready"]:
            for reason in report["readiness_reasons"]:
                print(f"::error title=NORMAL_RESPONSE_NOT_READY::{reason}")
        else:
            loc = report["normal_response"]["localization"]
            gate = report["normal_response"]["center_win_gate"]["delta_vs_primary"]
            print(
                "::notice title=NORMAL_RESPONSE_READY::"
                f"ink_zero_peak={loc['strict_zero_peak_fraction']['ink']} "
                f"background_zero_peak={loc['strict_zero_peak_fraction']['background']} "
                f"fpr_delta={gate['false_positive_rate']}"
            )
    else:
        verdict = (
            "READY TO INSPECT"
            if report["experimental_evidence_ready"]
            else "NOT READY"
        )
        loc = report["normal_response"]["localization"]
        gate = report["normal_response"]["center_win_gate"]["delta_vs_primary"]
        print(f"Surface-normal response: {verdict}")
        print(
            "ink_zero_peak="
            f"{loc['strict_zero_peak_fraction']['ink']} "
            "background_zero_peak="
            f"{loc['strict_zero_peak_fraction']['background']} "
            f"fpr_delta={gate['false_positive_rate']}"
        )
        components = report["normal_response"]["components"]
        print(
            "components="
            f"{components['analyzed_components']} "
            "review_candidates="
            f"{components['review_candidate_components']}"
        )
        for reason in report["readiness_reasons"]:
            print(f"- {reason}")

    return 0 if report["experimental_evidence_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
