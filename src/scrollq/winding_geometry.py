"""Umbilicus ray-order consistency for winding annotations.

A rolled scroll is one sheet spiralling outward from its central axis (the
umbilicus). Along a ray leaving the axis, a sheet two or more windings further
out should be crossed *after* the inner one. This module checks that ordering
for annotated winding numbers before any spiral fit is run:

* absolute-winding points share one global frame;
* each relative-winding collection is its own frame (only differences of its
  ``wind_a`` values are meaningful).

A pair of points in the same frame is *comparable* when they sit in the same
narrow angular sector around the umbilicus and a nearby z band, and their
winding numbers differ by at least ``min_winding_gap`` (default 2). The gap of
two makes the test independent of where the winding number increments (the
upstream spiral fitter's theta=0 branch cut), which can shift a comparison by
at most one winding. A comparable pair is a *ray-order inversion candidate*
when the higher-numbered point lies closer to the umbilicus by more than
``radial_margin`` voxels.

Candidates are review cues, never verdicts. The eruption deformed the spiral,
and a strongly folded region can legitimately make a ray from the umbilicus
cross windings out of order. The useful output is the ranked queue of points
that participate in many inversions: an isolated mis-numbered annotation shows
up as one point disagreeing with many neighbours.

Conventions follow the upstream spiral-fitting code: PointCollections ``p`` is
XYZ in full-resolution voxels; ``umbilicus.json`` holds ``control_points`` with
``x``/``y``/``z`` and is interpolated linearly in z, extrapolating beyond its
ends.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

DIAGNOSTIC = "umbilicus-ray-order"
DEFAULT_SECTOR_DEGREES = 10.0
DEFAULT_Z_TOLERANCE = 64.0
DEFAULT_MIN_WINDING_GAP = 2
DEFAULT_RADIAL_MARGIN = 0.0
DEFAULT_MIN_RADIUS = 1.0
DEFAULT_MAX_CANDIDATES = 200
DEFAULT_MAX_REVIEW_POINTS = 50

LIMITATION = (
    "Ray-order inversions are review candidates, not errors. They assume a "
    "ray from the umbilicus crosses windings in increasing order, which a "
    "strongly folded region can violate. They do not establish patch "
    "attachment, CT support, or held-out spiral-fit accuracy."
)


def _finite(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


class Umbilicus:
    """Piecewise-linear z -> (y, x) axis with linear extrapolation."""

    def __init__(self, z: np.ndarray, yx: np.ndarray, *, source: str | None, sha256: str | None):
        self.z = z
        self.yx = yx
        self.source = source
        self.sha256 = sha256

    @property
    def z_range(self) -> tuple[float, float]:
        return float(self.z[0]), float(self.z[-1])

    def __call__(self, z: np.ndarray) -> np.ndarray:
        z = np.asarray(z, dtype=np.float64)
        out = np.empty((z.size, 2), dtype=np.float64)
        for axis in range(2):
            values = self.yx[:, axis]
            out[:, axis] = np.interp(z, self.z, values)
            lo = z < self.z[0]
            hi = z > self.z[-1]
            if lo.any():
                slope = (values[1] - values[0]) / (self.z[1] - self.z[0])
                out[lo, axis] = values[0] + slope * (z[lo] - self.z[0])
            if hi.any():
                slope = (values[-1] - values[-2]) / (self.z[-1] - self.z[-2])
                out[hi, axis] = values[-1] + slope * (z[hi] - self.z[-1])
        return out


def parse_umbilicus(
    document: Any, *, source: str | None = None, sha256: str | None = None
) -> Umbilicus:
    """Parse the upstream ``umbilicus.json`` control-point document."""
    if not isinstance(document, dict) or not isinstance(document.get("control_points"), list):
        raise ValueError("umbilicus must be an object with a control_points list")
    rows = []
    for index, point in enumerate(document["control_points"]):
        if not isinstance(point, dict) or not all(
            _finite(point.get(key)) for key in ("x", "y", "z")
        ):
            raise ValueError(f"umbilicus control_points[{index}] needs finite x, y, z")
        rows.append((float(point["z"]), float(point["y"]), float(point["x"])))
    rows.sort()
    zs = [row[0] for row in rows]
    if len(rows) < 2:
        raise ValueError("umbilicus needs at least two control points")
    if len(set(zs)) != len(zs):
        raise ValueError("umbilicus control points must have distinct z values")
    array = np.asarray(rows, dtype=np.float64)
    return Umbilicus(array[:, 0], array[:, 1:], source=source, sha256=sha256)


def load_umbilicus(path: Path) -> Umbilicus:
    raw = Path(path).read_bytes()
    return parse_umbilicus(
        json.loads(raw), source=str(path), sha256=hashlib.sha256(raw).hexdigest()
    )


def _annotated_points(document: Any, role: str) -> list[dict[str, Any]]:
    """Valid points with finite XYZ and integer wind_a; anything else is the
    structural audit's business and is skipped here."""
    rows: list[dict[str, Any]] = []
    if not isinstance(document, dict) or not isinstance(document.get("collections"), dict):
        return rows
    for collection_key, collection in document["collections"].items():
        if not isinstance(collection, dict) or not isinstance(collection.get("points"), dict):
            continue
        frame = "absolute" if role == "absolute" else f"relative:{collection_key}"
        for point_key, point in collection["points"].items():
            if not isinstance(point, dict):
                continue
            p = point.get("p")
            wind = point.get("wind_a")
            if (
                not isinstance(p, list)
                or len(p) != 3
                or not all(_finite(value) for value in p)
                or not _finite(wind)
                or not float(wind).is_integer()
            ):
                continue
            rows.append(
                {
                    "frame": frame,
                    "role": role,
                    "collection_id": str(collection_key),
                    "point_id": str(point_key),
                    "xyz": [float(value) for value in p],
                    "wind_a": int(wind),
                }
            )
    return rows


def _angular_distance(a: np.ndarray, b: float) -> np.ndarray:
    delta = np.abs(a - b) % (2 * math.pi)
    return np.minimum(delta, 2 * math.pi - delta)


def check_ray_order(
    documents: dict[str, Any],
    umbilicus: Umbilicus,
    *,
    sector_degrees: float = DEFAULT_SECTOR_DEGREES,
    z_tolerance: float = DEFAULT_Z_TOLERANCE,
    min_winding_gap: int = DEFAULT_MIN_WINDING_GAP,
    radial_margin: float = DEFAULT_RADIAL_MARGIN,
    min_radius: float = DEFAULT_MIN_RADIUS,
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
    max_review_points: int = DEFAULT_MAX_REVIEW_POINTS,
    include_point_comparisons: bool = False,
) -> dict[str, Any]:
    """Check umbilicus ray order for parsed ``absolute``/``relative`` documents.

    ``include_point_comparisons`` adds ``point_comparisons``: for every
    evaluated point with at least one comparable pair, its comparable-pair
    count keyed ``frame|collection_id|point_id``. A point with no comparable
    pair cannot be flagged at all, so this is the check's per-point reach.
    """
    if not 0 < sector_degrees < 180:
        raise ValueError("sector_degrees must be in (0, 180)")
    if not z_tolerance >= 0:
        raise ValueError("z_tolerance must be >= 0")
    if min_winding_gap < 2:
        raise ValueError("min_winding_gap must be >= 2 (one-winding comparisons depend on the branch cut)")
    if not radial_margin >= 0 or not min_radius >= 0:
        raise ValueError("radial_margin and min_radius must be >= 0")

    points: list[dict[str, Any]] = []
    for role in ("absolute", "relative"):
        points.extend(_annotated_points(documents.get(role), role))

    sector = math.radians(sector_degrees)
    z_lo, z_hi = umbilicus.z_range
    near_axis = 0
    extrapolated = 0
    usable: list[dict[str, Any]] = []
    if points:
        xyz = np.asarray([row["xyz"] for row in points], dtype=np.float64)
        axis = umbilicus(xyz[:, 2])
        dy = xyz[:, 1] - axis[:, 0]
        dx = xyz[:, 0] - axis[:, 1]
        radius = np.hypot(dy, dx)
        theta = np.arctan2(dy, dx)
        for index, row in enumerate(points):
            z = row["xyz"][2]
            row["extrapolated_umbilicus"] = bool(z < z_lo or z > z_hi)
            extrapolated += row["extrapolated_umbilicus"]
            if radius[index] < min_radius:
                near_axis += 1
                continue
            row["radius"] = float(radius[index])
            row["theta_degrees"] = float(math.degrees(theta[index]))
            row["_theta"] = float(theta[index])
            usable.append(row)

    frames: dict[str, list[dict[str, Any]]] = {}
    for row in usable:
        frames.setdefault(row["frame"], []).append(row)

    candidates: list[dict[str, Any]] = []
    involvement: dict[tuple[str, str, str], int] = {}
    comparisons: dict[tuple[str, str, str], int] = {}
    reach: dict[tuple[str, str, str], int] = {}
    frame_rows = []
    total_pairs = 0
    total_inversions = 0
    for frame in sorted(frames):
        rows = sorted(frames[frame], key=lambda row: row["xyz"][2])
        z = np.asarray([row["xyz"][2] for row in rows])
        theta = np.asarray([row["_theta"] for row in rows])
        radius = np.asarray([row["radius"] for row in rows])
        wind = np.asarray([row["wind_a"] for row in rows])
        pair_i: list[np.ndarray] = []
        pair_j: list[np.ndarray] = []
        for i in range(len(rows)):
            stop = int(np.searchsorted(z, z[i] + z_tolerance, side="right"))
            if stop <= i + 1:
                continue
            j = np.arange(i + 1, stop)
            j = j[
                (np.abs(wind[j] - wind[i]) >= min_winding_gap)
                & (_angular_distance(theta[j], theta[i]) <= sector)
            ]
            if j.size:
                pair_i.append(np.full(j.size, i))
                pair_j.append(j)
        if pair_i:
            a = np.concatenate(pair_i)
            b = np.concatenate(pair_j)
        else:
            a = b = np.empty(0, dtype=np.int64)
        # Orient each pair as (inner winding, outer winding).
        a_is_outer = wind[a] > wind[b]
        inner = np.where(a_is_outer, b, a)
        outer = np.where(a_is_outer, a, b)
        inverted = radius[inner] - radius[outer] > radial_margin
        pairs = int(a.size)
        inversions = int(inverted.sum())
        compared_counts = np.bincount(a, minlength=len(rows)) + np.bincount(
            b, minlength=len(rows)
        )
        inverted_counts = np.bincount(
            inner[inverted], minlength=len(rows)
        ) + np.bincount(outer[inverted], minlength=len(rows))
        for idx in np.nonzero(compared_counts)[0]:
            reach[_point_key(rows[idx])] = int(compared_counts[idx])
        for idx in np.nonzero(inverted_counts)[0]:
            key = _point_key(rows[idx])
            involvement[key] = int(inverted_counts[idx])
            comparisons[key] = int(compared_counts[idx])
        for lo, hi in zip(inner[inverted], outer[inverted]):
            candidates.append(
                {
                    "frame": frame,
                    "radial_inversion_voxels": float(radius[lo] - radius[hi]),
                    "winding_gap": int(wind[hi] - wind[lo]),
                    "inner": _public_point(rows[lo]),
                    "outer": _public_point(rows[hi]),
                }
            )
        total_pairs += pairs
        total_inversions += inversions
        frame_rows.append(
            {
                "frame": frame,
                "points": len(rows),
                "comparable_pairs": pairs,
                "inversion_candidates": inversions,
                "inversion_fraction": inversions / pairs if pairs else None,
            }
        )

    candidates.sort(
        key=lambda item: (
            -item["radial_inversion_voxels"],
            item["frame"],
            item["inner"]["collection_id"],
            item["inner"]["point_id"],
        )
    )
    by_key = {_point_key(row): row for row in usable}
    review = []
    for key, count in sorted(involvement.items(), key=lambda kv: (-kv[1], kv[0])):
        compared = comparisons[key]
        review.append(
            {
                **_public_point(by_key[key]),
                "frame": key[0],
                "inversion_pairs": count,
                "comparable_pairs": compared,
                "inversion_share": count / compared,
            }
        )

    if not usable:
        status = "not-evaluated"
    elif total_pairs == 0:
        status = "no-comparable-pairs"
    elif total_inversions:
        status = "review"
    else:
        status = "consistent"

    report = {
        "diagnostic": DIAGNOSTIC,
        "status": status,
        "umbilicus": {
            "source": umbilicus.source,
            "sha256": umbilicus.sha256,
            "control_points": int(umbilicus.z.size),
            "z_range": list(umbilicus.z_range),
            "interpolation": "linear in z, linear extrapolation beyond the ends",
        },
        "parameters": {
            "sector_degrees": sector_degrees,
            "z_tolerance_voxels": z_tolerance,
            "min_winding_gap": min_winding_gap,
            "radial_margin_voxels": radial_margin,
            "min_radius_voxels": min_radius,
        },
        "points": {
            "annotated": len(points),
            "evaluated": len(usable),
            "skipped_near_axis": near_axis,
            "extrapolated_umbilicus": extrapolated,
            "with_comparable_pairs": len(reach),
        },
        "frames": frame_rows,
        "comparable_pairs": total_pairs,
        "inversion_candidates": total_inversions,
        "inversion_fraction": total_inversions / total_pairs if total_pairs else None,
        "candidates": candidates[:max_candidates],
        "candidates_truncated": max(len(candidates) - max_candidates, 0),
        "review_queue": review[:max_review_points],
        "review_queue_truncated": max(len(review) - max_review_points, 0),
        "coordinate_order": "xyz (VC3D PointCollections p)",
        "limitation": LIMITATION,
    }
    if include_point_comparisons:
        report["point_comparisons"] = {
            "|".join(key): count for key, count in sorted(reach.items())
        }
    return report


def _point_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (row["frame"], row["collection_id"], row["point_id"])


def _public_point(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "role": row["role"],
        "collection_id": row["collection_id"],
        "point_id": row["point_id"],
        "xyz": row["xyz"],
        "wind_a": row["wind_a"],
        "radius_voxels": row["radius"],
        "theta_degrees": row["theta_degrees"],
        "extrapolated_umbilicus": row["extrapolated_umbilicus"],
    }
