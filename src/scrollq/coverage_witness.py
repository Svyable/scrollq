"""Research helpers for identity-aware coverage-witness experiments.

These functions are intentionally not exposed as a console script. They support
the preregistered Stage-B experiment for issue #151 and remain small enough to
remove if the real-papyrus gate fails.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable
import warnings

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.linalg import MatrixRankWarning, spsolve


class CoverageWitnessError(RuntimeError):
    pass


@dataclass(frozen=True)
class RayRun:
    start_offset: int
    end_offset: int
    midpoint: float
    length: int

    def as_dict(self) -> dict[str, float | int]:
        return {
            "start_offset": self.start_offset,
            "end_offset": self.end_offset,
            "midpoint": self.midpoint,
            "length": self.length,
        }


def odd_rect(
    center_yx: tuple[int, int], size: int
) -> tuple[int, int, int, int]:
    """Return a half-open odd square [y0,y1,x0,x1]."""
    if type(size) is not int or size <= 0 or size % 2 != 1:
        raise CoverageWitnessError("size must be a positive odd integer")
    y, x = (int(center_yx[0]), int(center_yx[1]))
    half = size // 2
    return y - half, y + half + 1, x - half, x + half + 1


def hide_rect(
    xyz: np.ndarray,
    valid: np.ndarray,
    rect_yx: tuple[int, int, int, int],
) -> tuple[np.ndarray, np.ndarray]:
    """Remove a rectangle from geometry input, including invalid source cells."""
    xyz = np.asarray(xyz, dtype=np.float64)
    valid = np.asarray(valid, dtype=bool)
    if xyz.ndim != 3 or xyz.shape[-1] != 3:
        raise CoverageWitnessError("xyz must have shape [H,W,3]")
    if valid.shape != xyz.shape[:2]:
        raise CoverageWitnessError("valid must match xyz spatial shape")
    y0, y1, x0, x1 = rect_yx
    h, w = valid.shape
    if not (0 <= y0 < y1 <= h and 0 <= x0 < x1 <= w):
        raise CoverageWitnessError("hidden rectangle is out of bounds")
    out_xyz = xyz.copy()
    out_valid = valid.copy()
    out_xyz[y0:y1, x0:x1, :] = np.nan
    out_valid[y0:y1, x0:x1] = False
    return out_xyz, out_valid


def _unknown_index(
    rect_yx: tuple[int, int, int, int]
) -> tuple[dict[tuple[int, int], int], list[tuple[int, int]]]:
    y0, y1, x0, x1 = rect_yx
    cells = [(y, x) for y in range(y0, y1) for x in range(x0, x1)]
    return {cell: i for i, cell in enumerate(cells)}, cells


def harmonic_continue_rect(
    observed_xyz: np.ndarray,
    observed_valid: np.ndarray,
    rect_yx: tuple[int, int, int, int],
) -> tuple[np.ndarray, np.ndarray, dict]:
    """Fill one hidden rectangle by a 4-neighbor discrete harmonic solve.

    Only visible valid neighbors outside rect_yx contribute Dirichlet values.
    Invalid visible neighbors are omitted, which acts as a local Neumann
    boundary. Hidden values in observed_xyz are never consulted.
    """
    xyz = np.asarray(observed_xyz, dtype=np.float64)
    valid = np.asarray(observed_valid, dtype=bool)
    if xyz.ndim != 3 or xyz.shape[-1] != 3:
        raise CoverageWitnessError("observed_xyz must have shape [H,W,3]")
    if valid.shape != xyz.shape[:2]:
        raise CoverageWitnessError("observed_valid must match xyz spatial shape")
    y0, y1, x0, x1 = rect_yx
    h, w = valid.shape
    if not (0 <= y0 < y1 <= h and 0 <= x0 < x1 <= w):
        raise CoverageWitnessError("continuation rectangle is out of bounds")
    if np.isfinite(xyz[y0:y1, x0:x1]).any():
        raise CoverageWitnessError(
            "hidden rectangle must contain no finite geometry before continuation"
        )
    if valid[y0:y1, x0:x1].any():
        raise CoverageWitnessError(
            "hidden rectangle must contain no valid cells before continuation"
        )

    index, cells = _unknown_index(rect_yx)
    n = len(cells)
    rows: list[int] = []
    cols: list[int] = []
    data: list[float] = []
    rhs = np.zeros((n, 3), dtype=np.float64)
    dirichlet_edges = 0
    omitted_invalid_edges = 0

    for i, (y, x) in enumerate(cells):
        degree = 0
        for yy, xx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
            if not (0 <= yy < h and 0 <= xx < w):
                omitted_invalid_edges += 1
                continue
            j = index.get((yy, xx))
            if j is not None:
                rows.append(i)
                cols.append(j)
                data.append(-1.0)
                degree += 1
                continue
            if valid[yy, xx] and np.isfinite(xyz[yy, xx]).all():
                rhs[i] += xyz[yy, xx]
                degree += 1
                dirichlet_edges += 1
            else:
                omitted_invalid_edges += 1
        if degree <= 0:
            raise CoverageWitnessError(
                f"hidden cell {(y, x)} has no graph or Dirichlet neighbors"
            )
        rows.append(i)
        cols.append(i)
        data.append(float(degree))

    if dirichlet_edges <= 0:
        raise CoverageWitnessError("hidden rectangle has no visible valid boundary")

    matrix = csr_matrix((data, (rows, cols)), shape=(n, n))
    solution = np.empty((n, 3), dtype=np.float64)
    with warnings.catch_warnings():
        warnings.simplefilter("error", MatrixRankWarning)
        try:
            for channel in range(3):
                solution[:, channel] = spsolve(matrix, rhs[:, channel])
        except MatrixRankWarning as exc:
            raise CoverageWitnessError("harmonic continuation matrix is singular") from exc

    if not np.isfinite(solution).all():
        raise CoverageWitnessError("harmonic continuation produced non-finite values")

    filled = xyz.copy()
    filled_valid = valid.copy()
    for i, (y, x) in enumerate(cells):
        filled[y, x] = solution[i]
        filled_valid[y, x] = True

    return filled, filled_valid, {
        "method": "discrete-harmonic-material-grid-v1",
        "hidden_cell_count": n,
        "dirichlet_edges": int(dirichlet_edges),
        "omitted_invalid_or_oob_edges": int(omitted_invalid_edges),
        "matrix_nnz": int(matrix.nnz),
    }


def centered_normal_xyz(
    xyz: np.ndarray,
    valid: np.ndarray,
    y: int,
    x: int,
) -> np.ndarray | None:
    """Use the centered tangent cross-product convention from sheetness planning."""
    xyz = np.asarray(xyz, dtype=np.float64)
    valid = np.asarray(valid, dtype=bool)
    h, w = valid.shape
    if y <= 0 or y >= h - 1 or x <= 0 or x >= w - 1:
        return None
    neighbors = ((y, x), (y, x - 1), (y, x + 1), (y - 1, x), (y + 1, x))
    if not all(valid[yy, xx] for yy, xx in neighbors):
        return None
    vals = [xyz[yy, xx] for yy, xx in neighbors]
    if not all(np.isfinite(v).all() for v in vals):
        return None
    col = xyz[y, x + 1] - xyz[y, x - 1]
    row = xyz[y + 1, x] - xyz[y - 1, x]
    normal = np.cross(col, row)
    norm = float(np.linalg.norm(normal))
    if not np.isfinite(norm) or norm <= 1e-8:
        return None
    return normal / norm


def supported_runs(
    offsets: Iterable[int],
    supported: Iterable[bool],
    *,
    min_run_voxels: int,
) -> list[RayRun]:
    """Return maximal contiguous supported integer-offset runs."""
    offsets_arr = np.asarray(list(offsets), dtype=np.int64)
    supported_arr = np.asarray(list(supported), dtype=bool)
    if offsets_arr.ndim != 1 or supported_arr.ndim != 1:
        raise CoverageWitnessError("offsets and supported must be one-dimensional")
    if offsets_arr.size != supported_arr.size or offsets_arr.size == 0:
        raise CoverageWitnessError("offsets and supported must be non-empty and aligned")
    if not np.all(np.diff(offsets_arr) == 1):
        raise CoverageWitnessError("offsets must be contiguous integer steps")
    if type(min_run_voxels) is not int or min_run_voxels < 1:
        raise CoverageWitnessError("min_run_voxels must be >= 1")

    runs: list[RayRun] = []
    i = 0
    n = len(offsets_arr)
    while i < n:
        if not supported_arr[i]:
            i += 1
            continue
        j = i + 1
        while j < n and supported_arr[j]:
            j += 1
        length = j - i
        if length >= min_run_voxels:
            start = int(offsets_arr[i])
            end = int(offsets_arr[j - 1])
            runs.append(
                RayRun(
                    start_offset=start,
                    end_offset=end,
                    midpoint=(start + end) / 2.0,
                    length=length,
                )
            )
        i = j
    return runs


def classify_runs(
    runs: Iterable[RayRun],
    *,
    target_abs_max: float,
    competitor_abs_min: float,
    competitor_abs_max: float,
) -> dict:
    """Select one target run and separate competing and guard-band runs."""
    if not (0 <= target_abs_max < competitor_abs_min <= competitor_abs_max):
        raise CoverageWitnessError("run-classification bands are inconsistent")
    rows = list(runs)
    targets = [r for r in rows if abs(r.midpoint) <= target_abs_max]
    guards = [
        r for r in rows
        if target_abs_max < abs(r.midpoint) < competitor_abs_min
    ]
    competitors = [
        r for r in rows
        if competitor_abs_min <= abs(r.midpoint) <= competitor_abs_max
    ]
    targets.sort(
        key=lambda r: (
            abs(r.midpoint),
            0 if r.midpoint < 0 else 1,
            r.start_offset,
        )
    )
    return {
        "target": None if not targets else targets[0],
        "target_candidates": targets,
        "guard": guards,
        "competitors": competitors,
    }
