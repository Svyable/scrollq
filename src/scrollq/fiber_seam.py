"""Fail-closed scoring helpers for frozen cross-ply seam experiments."""
from __future__ import annotations

from typing import Any, Iterable

import numpy as np

from .fiber_frame import frame_distance_degrees


class FiberSeamError(ValueError):
    pass


def seam_metrics(
    analysis: dict[str, Any],
    *,
    seam_rows: Iterable[int] = range(4),
    left_tile_x: int = 1,
    right_tile_x: int = 2,
    switch_degrees: float = 25.0,
    minimum_valid_comparisons: int = 3,
    minimum_flagged_comparisons: int = 2,
) -> dict[str, Any]:
    """Score only the frozen tile-neighbor pairs crossing one vertical seam."""
    if analysis.get("status") != "measured":
        return {
            "status": "insufficient",
            "valid_comparison_count": 0,
            "flagged_comparison_count": 0,
            "seam_positive": False,
            "comparisons": [],
        }
    frames_raw = analysis.get("frames")
    if not isinstance(frames_raw, list):
        raise FiberSeamError("analysis.frames must be a list")

    frames: dict[tuple[int, int], dict[str, Any]] = {}
    for row in frames_raw:
        if not isinstance(row, dict):
            continue
        grid = row.get("grid")
        axes = row.get("axes_degrees")
        if (
            not isinstance(grid, list)
            or len(grid) != 2
            or not all(type(v) is int for v in grid)
            or not isinstance(axes, list)
            or len(axes) != 2
        ):
            continue
        key = (int(grid[0]), int(grid[1]))
        if key in frames:
            raise FiberSeamError(f"duplicate frame grid {key}")
        frames[key] = row

    comparisons = []
    for gy in seam_rows:
        a = frames.get((int(gy), int(left_tile_x)))
        b = frames.get((int(gy), int(right_tile_x)))
        if a is None or b is None:
            continue
        delta = frame_distance_degrees(a["axes_degrees"], b["axes_degrees"])
        comparisons.append(
            {
                "tile_a": [int(gy), int(left_tile_x)],
                "tile_b": [int(gy), int(right_tile_x)],
                "frame_delta_degrees": float(delta),
                "flagged": bool(delta > float(switch_degrees)),
            }
        )

    valid = len(comparisons)
    flagged = sum(bool(row["flagged"]) for row in comparisons)
    sufficient = valid >= int(minimum_valid_comparisons)
    return {
        "status": "measured" if sufficient else "insufficient",
        "valid_comparison_count": valid,
        "flagged_comparison_count": flagged,
        "seam_positive": bool(
            sufficient and flagged >= int(minimum_flagged_comparisons)
        ),
        "comparisons": comparisons,
    }


def score_development(
    groups: list[dict[str, Any]],
    *,
    frozen_group_count: int = 10,
    required_usable_groups: int = 8,
    maximum_intact_false_positive_fraction: float = 0.2,
    minimum_target_left_wrong_right_detection_fraction: float = 0.7,
    minimum_wrong_left_target_right_detection_fraction: float = 0.7,
    minimum_pooled_seam_comparison_coverage_fraction_each_variant: float = 0.75,
) -> dict[str, Any]:
    """Apply the preregistered all-groups/all-comparisons development gate."""
    if len(groups) != frozen_group_count:
        raise FiberSeamError(
            f"expected {frozen_group_count} frozen groups, got {len(groups)}"
        )

    variants = (
        "intact",
        "target_left_wrong_right",
        "wrong_left_target_right",
    )
    usable_count = sum(row.get("status") == "usable" for row in groups)

    positives: dict[str, int] = {}
    coverage: dict[str, float] = {}
    for variant in variants:
        positives[variant] = sum(
            bool(row.get("variants", {}).get(variant, {}).get("seam_positive"))
            for row in groups
        )
        valid = sum(
            int(
                row.get("variants", {})
                .get(variant, {})
                .get("valid_comparison_count", 0)
            )
            for row in groups
        )
        coverage[variant] = float(valid / (frozen_group_count * 4))

    intact_fp = positives["intact"] / frozen_group_count
    left_detection = positives["target_left_wrong_right"] / frozen_group_count
    right_detection = positives["wrong_left_target_right"] / frozen_group_count

    checks = {
        "usable_groups": usable_count >= required_usable_groups,
        "intact_false_positive_fraction": (
            intact_fp <= maximum_intact_false_positive_fraction
        ),
        "target_left_wrong_right_detection_fraction": (
            left_detection >= minimum_target_left_wrong_right_detection_fraction
        ),
        "wrong_left_target_right_detection_fraction": (
            right_detection >= minimum_wrong_left_target_right_detection_fraction
        ),
        "intact_seam_coverage": (
            coverage["intact"]
            >= minimum_pooled_seam_comparison_coverage_fraction_each_variant
        ),
        "target_left_wrong_right_seam_coverage": (
            coverage["target_left_wrong_right"]
            >= minimum_pooled_seam_comparison_coverage_fraction_each_variant
        ),
        "wrong_left_target_right_seam_coverage": (
            coverage["wrong_left_target_right"]
            >= minimum_pooled_seam_comparison_coverage_fraction_each_variant
        ),
    }

    return {
        "status": "pass" if all(checks.values()) else "fail",
        "usable_group_count": usable_count,
        "frozen_group_count": frozen_group_count,
        "intact_false_positive_fraction": float(intact_fp),
        "target_left_wrong_right_detection_fraction": float(left_detection),
        "wrong_left_target_right_detection_fraction": float(right_detection),
        "pooled_seam_comparison_coverage_fraction": coverage,
        "seam_positive_group_counts": positives,
        "checks": checks,
    }


def stitch_half_slabs(
    target: np.ndarray,
    wrong: np.ndarray,
) -> dict[str, np.ndarray]:
    """Build the frozen intact and two half-slab substitution variants."""
    target = np.asarray(target)
    wrong = np.asarray(wrong)
    if target.shape != wrong.shape or target.ndim != 3:
        raise FiberSeamError("target/wrong slabs must share [depth,y,x] shape")
    if target.shape[2] % 2:
        raise FiberSeamError("slab x dimension must be even")
    split = target.shape[2] // 2
    return {
        "intact": np.array(target, copy=True),
        "target_left_wrong_right": np.concatenate(
            [target[:, :, :split], wrong[:, :, split:]], axis=2
        ),
        "wrong_left_target_right": np.concatenate(
            [wrong[:, :, :split], target[:, :, split:]], axis=2
        ),
    }
