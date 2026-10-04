"""Research helpers for multi-sided surface-prediction gap recovery.

These primitives are intentionally not a production CLI. They support the
preregistered prediction-connectivity recovery experiment and keep component
selection independent of hidden reference geometry.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping, Sequence

import numpy as np
from scipy.ndimage import binary_dilation, label
from scipy.spatial import cKDTree


class PredictionRecoveryError(ValueError):
    pass


def boundary_anchor_cells(
    rect_yx: tuple[int, int, int, int],
    *,
    ring_offset: int = 2,
) -> dict[str, list[tuple[int, int]]]:
    """Return deterministic four-sided visible anchor cells around a rectangle.

    Corners belong to top/bottom. Left/right omit endpoints so every anchor has
    exactly one side label.
    """
    if type(ring_offset) is not int or ring_offset < 1:
        raise PredictionRecoveryError("ring_offset must be an integer >= 1")
    y0, y1, x0, x1 = (int(v) for v in rect_yx)
    if not (y0 < y1 and x0 < x1):
        raise PredictionRecoveryError("rect_yx must be a non-empty half-open rectangle")

    top_y = y0 - ring_offset
    bottom_y = y1 - 1 + ring_offset
    left_x = x0 - ring_offset
    right_x = x1 - 1 + ring_offset
    return {
        "top": [(top_y, x) for x in range(x0, x1)],
        "bottom": [(bottom_y, x) for x in range(x0, x1)],
        "left": [(y, left_x) for y in range(y0 + 1, y1 - 1)],
        "right": [(y, right_x) for y in range(y0 + 1, y1 - 1)],
    }


def label_connectivity(
    raw_mask: np.ndarray,
    *,
    dilation_iterations: int = 1,
) -> tuple[np.ndarray, int]:
    """Label 26-connected components after connectivity-only dilation."""
    raw = np.asarray(raw_mask, dtype=bool)
    if raw.ndim != 3:
        raise PredictionRecoveryError("raw_mask must have shape [z,y,x]")
    if type(dilation_iterations) is not int or dilation_iterations < 0:
        raise PredictionRecoveryError("dilation_iterations must be an integer >= 0")
    structure = np.ones((3, 3, 3), dtype=bool)
    connected = (
        binary_dilation(raw, structure=structure, iterations=dilation_iterations)
        if dilation_iterations
        else raw
    )
    labels, count = label(connected, structure=structure)
    return labels.astype(np.int32, copy=False), int(count)


def select_seeded_component(
    labels: np.ndarray,
    seed_local_zyx_by_side: Mapping[str, Sequence[Sequence[int]]],
    *,
    required_sides: Sequence[str] = ("top", "bottom", "left", "right"),
    minimum_seeds_per_side: int = 3,
    minimum_total_seed_share: float = 0.5,
) -> dict[str, Any]:
    """Select exactly one component supported by the frozen multi-side rule."""
    lab = np.asarray(labels)
    if lab.ndim != 3 or not np.issubdtype(lab.dtype, np.integer):
        raise PredictionRecoveryError("labels must be an integer [z,y,x] array")
    if type(minimum_seeds_per_side) is not int or minimum_seeds_per_side < 1:
        raise PredictionRecoveryError("minimum_seeds_per_side must be >= 1")
    if not 0 < float(minimum_total_seed_share) <= 1:
        raise PredictionRecoveryError("minimum_total_seed_share must be in (0,1]")

    side_counts: dict[int, dict[str, int]] = defaultdict(
        lambda: {str(side): 0 for side in required_sides}
    )
    total_counts: dict[int, int] = defaultdict(int)
    valid_seed_count = 0

    shape = np.asarray(lab.shape, dtype=np.int64)
    normalized: dict[str, list[list[int]]] = {}
    for side in required_sides:
        rows = seed_local_zyx_by_side.get(str(side), ())
        normalized[str(side)] = []
        for raw_coord in rows:
            coord = np.asarray(raw_coord, dtype=np.int64)
            if coord.shape != (3,):
                raise PredictionRecoveryError("seed coordinates must be integer ZYX triplets")
            if np.any(coord < 0) or np.any(coord >= shape):
                continue
            label_id = int(lab[tuple(coord)])
            if label_id <= 0:
                continue
            normalized[str(side)].append([int(v) for v in coord])
            valid_seed_count += 1
            total_counts[label_id] += 1
            side_counts[label_id][str(side)] += 1

    candidates = []
    for label_id in sorted(total_counts):
        total = int(total_counts[label_id])
        share = float(total / valid_seed_count) if valid_seed_count else 0.0
        per_side = side_counts[label_id]
        eligible = (
            all(per_side[str(side)] >= minimum_seeds_per_side for side in required_sides)
            and share >= float(minimum_total_seed_share)
        )
        candidates.append(
            {
                "label": int(label_id),
                "seed_count": total,
                "seed_share": share,
                "seed_count_by_side": dict(per_side),
                "eligible": bool(eligible),
            }
        )

    eligible = [row for row in candidates if row["eligible"]]
    selected = eligible[0]["label"] if len(eligible) == 1 else None
    return {
        "status": "selected" if selected is not None else "abstain",
        "selected_label": selected,
        "valid_seed_count": int(valid_seed_count),
        "valid_seed_count_by_side": {
            side: len(normalized[str(side)]) for side in required_sides
        },
        "components_with_seed_votes": candidates,
        "eligible_component_count": len(eligible),
    }


def raw_component_points(
    raw_mask: np.ndarray,
    labels: np.ndarray,
    selected_label: int,
    *,
    origin_zyx: Sequence[int] = (0, 0, 0),
) -> np.ndarray:
    """Return global ZYX coordinates for raw voxels in one connectivity label."""
    raw = np.asarray(raw_mask, dtype=bool)
    lab = np.asarray(labels)
    if raw.shape != lab.shape or raw.ndim != 3:
        raise PredictionRecoveryError("raw_mask and labels must share [z,y,x] shape")
    if type(selected_label) is not int or selected_label <= 0:
        raise PredictionRecoveryError("selected_label must be a positive integer")
    origin = np.asarray(origin_zyx, dtype=np.int64)
    if origin.shape != (3,):
        raise PredictionRecoveryError("origin_zyx must contain three integers")
    points = np.argwhere(raw & (lab == selected_label))
    if not len(points):
        raise PredictionRecoveryError("selected component has no raw candidate voxels")
    return points.astype(np.float64) + origin[None, :]


def snap_to_component(
    coarse_zyx: np.ndarray,
    component_points_zyx: np.ndarray,
    *,
    maximum_distance_voxels: float,
) -> dict[str, Any]:
    """Snap coarse coordinates to nearest raw selected-component voxels."""
    coarse = np.asarray(coarse_zyx, dtype=np.float64)
    points = np.asarray(component_points_zyx, dtype=np.float64)
    if coarse.ndim != 2 or coarse.shape[1] != 3:
        raise PredictionRecoveryError("coarse_zyx must have shape [N,3]")
    if points.ndim != 2 or points.shape[1] != 3 or len(points) == 0:
        raise PredictionRecoveryError("component_points_zyx must have non-empty shape [M,3]")
    if not np.isfinite(coarse).all() or not np.isfinite(points).all():
        raise PredictionRecoveryError("coordinates must be finite")
    maximum = float(maximum_distance_voxels)
    if not np.isfinite(maximum) or maximum <= 0:
        raise PredictionRecoveryError("maximum_distance_voxels must be finite and > 0")

    tree = cKDTree(points)
    distances, indices = tree.query(coarse, k=1, workers=1)
    distances = np.asarray(distances, dtype=np.float64)
    indices = np.asarray(indices, dtype=np.int64)
    available = distances <= maximum
    recovered = np.full_like(coarse, np.nan, dtype=np.float64)
    recovered[available] = points[indices[available]]

    if np.any(available):
        unique = np.unique(recovered[available].astype(np.int64), axis=0)
        unique_fraction = float(len(unique) / int(np.sum(available)))
    else:
        unique_fraction = 0.0
    return {
        "recovered_zyx": recovered,
        "available": available,
        "snap_distance_voxels": distances,
        "candidate_available_fraction": float(np.mean(available)) if len(available) else 0.0,
        "unique_recovered_voxel_fraction": unique_fraction,
    }


def score_development(
    centers: list[dict[str, Any]],
    *,
    frozen_center_count: int = 6,
    required_selected_component_centers: int = 5,
    minimum_candidate_available_fraction_every_selected_center: float = 0.80,
    minimum_fraction_within_8_voxels_every_selected_center: float = 0.50,
    minimum_median_fraction_within_8_voxels_across_all_centers: float = 0.80,
    maximum_median_error_voxels_every_selected_center: float = 8.0,
    maximum_median_p95_error_voxels_across_selected_centers: float = 16.0,
    require_all_wrong_wrap_controls_rejected: bool = True,
    minimum_median_unique_recovered_voxel_fraction: float = 0.50,
) -> dict[str, Any]:
    """Apply the frozen all-center recovery gate."""
    if len(centers) != frozen_center_count:
        raise PredictionRecoveryError(
            f"expected {frozen_center_count} frozen centers, got {len(centers)}"
        )
    selected = [row for row in centers if row.get("component_status") == "selected"]

    fractions_all = [
        float(row.get("fraction_within_8_voxels", 0.0) or 0.0)
        if row.get("component_status") == "selected"
        else 0.0
        for row in centers
    ]
    selected_availability = [
        float(row.get("candidate_available_fraction", 0.0) or 0.0)
        for row in selected
    ]
    selected_fraction8 = [
        float(row.get("fraction_within_8_voxels", 0.0) or 0.0)
        for row in selected
    ]
    selected_median_error = [
        row.get("median_error_voxels") for row in selected
    ]
    selected_p95 = [row.get("p95_error_voxels") for row in selected]
    selected_unique = [
        float(row.get("unique_recovered_voxel_fraction", 0.0) or 0.0)
        for row in selected
    ]
    wrong_wrap_rows = [
        bool(row.get("wrong_wrap_rejected", True))
        for row in centers
    ]

    finite_median_error = [
        float(v) for v in selected_median_error
        if isinstance(v, (int, float)) and np.isfinite(float(v))
    ]
    finite_p95 = [
        float(v) for v in selected_p95
        if isinstance(v, (int, float)) and np.isfinite(float(v))
    ]

    checks = {
        "selected_component_centers": (
            len(selected) >= required_selected_component_centers
        ),
        "candidate_available_fraction_every_selected_center": (
            bool(selected)
            and all(
                value >= minimum_candidate_available_fraction_every_selected_center
                for value in selected_availability
            )
        ),
        "fraction_within_8_voxels_every_selected_center": (
            bool(selected)
            and all(
                value >= minimum_fraction_within_8_voxels_every_selected_center
                for value in selected_fraction8
            )
        ),
        "median_fraction_within_8_voxels_across_all_centers": (
            float(np.median(fractions_all))
            >= minimum_median_fraction_within_8_voxels_across_all_centers
        ),
        "median_error_voxels_every_selected_center": (
            len(finite_median_error) == len(selected)
            and bool(selected)
            and all(
                value <= maximum_median_error_voxels_every_selected_center
                for value in finite_median_error
            )
        ),
        "median_p95_error_voxels_across_selected_centers": (
            len(finite_p95) == len(selected)
            and bool(selected)
            and float(np.median(finite_p95))
            <= maximum_median_p95_error_voxels_across_selected_centers
        ),
        "wrong_wrap_controls_rejected": (
            (not require_all_wrong_wrap_controls_rejected)
            or all(wrong_wrap_rows)
        ),
        "median_unique_recovered_voxel_fraction": (
            bool(selected_unique)
            and float(np.median(selected_unique))
            >= minimum_median_unique_recovered_voxel_fraction
        ),
    }

    return {
        "status": "pass" if all(checks.values()) else "fail",
        "selected_component_center_count": len(selected),
        "frozen_center_count": frozen_center_count,
        "median_fraction_within_8_voxels_across_all_centers": float(
            np.median(fractions_all)
        ),
        "median_p95_error_voxels_across_selected_centers": (
            float(np.median(finite_p95)) if finite_p95 else None
        ),
        "median_unique_recovered_voxel_fraction": (
            float(np.median(selected_unique)) if selected_unique else None
        ),
        "wrong_wrap_rejected_count": sum(wrong_wrap_rows),
        "checks": checks,
    }


def read_level_box(
    level: Any,
    lo_zyx: Sequence[int],
    hi_zyx: Sequence[int],
) -> tuple[np.ndarray, list[tuple[int, int, int]]]:
    """Read one half-open uint8 Zarr-v2 box, treating absent fill chunks as zero."""
    shape = np.asarray(level.shape, dtype=np.int64)
    chunks = np.asarray(level.chunks, dtype=np.int64)
    lo = np.asarray(lo_zyx, dtype=np.int64)
    hi = np.asarray(hi_zyx, dtype=np.int64)
    if lo.shape != (3,) or hi.shape != (3,):
        raise PredictionRecoveryError("box bounds must be ZYX triplets")
    if np.any(lo < 0) or np.any(hi > shape) or np.any(lo >= hi):
        raise PredictionRecoveryError("box is empty or outside level bounds")

    out_shape = tuple(int(v) for v in (hi - lo))
    out = np.zeros(out_shape, dtype=np.uint8)
    first = lo // chunks
    last = (hi - 1) // chunks
    missing: list[tuple[int, int, int]] = []

    for cz in range(int(first[0]), int(last[0]) + 1):
        for cy in range(int(first[1]), int(last[1]) + 1):
            for cx in range(int(first[2]), int(last[2]) + 1):
                cidx = (cz, cy, cx)
                chunk = level.chunk(cidx)
                if chunk is None:
                    missing.append(cidx)
                    continue
                array = np.asarray(chunk, dtype=np.uint8)
                global_lo = np.asarray(cidx, dtype=np.int64) * chunks
                global_hi = global_lo + np.asarray(array.shape, dtype=np.int64)
                ov_lo = np.maximum(lo, global_lo)
                ov_hi = np.minimum(hi, global_hi)
                if np.any(ov_lo >= ov_hi):
                    continue
                out_slices = tuple(
                    slice(int(ov_lo[d] - lo[d]), int(ov_hi[d] - lo[d]))
                    for d in range(3)
                )
                chunk_slices = tuple(
                    slice(
                        int(ov_lo[d] - global_lo[d]),
                        int(ov_hi[d] - global_lo[d]),
                    )
                    for d in range(3)
                )
                out[out_slices] = array[chunk_slices]
    return out, missing
