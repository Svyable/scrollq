"""Winding conservation: layer count, pitch and identity continuity as whole-scroll QC.

A stitched whole-scroll (or large-window) winding solution should obey global
geometric conservation laws that were not used to produce any individual
surface. Local CT seating can be excellent while a stitch silently loses,
duplicates, merges or swaps a winding. This module tests the solution against
three invariants on a (z, theta) cell grid around the umbilicus:

* **layer count** -- along a ray, every winding label between the innermost and
  outermost crossing is crossed exactly once, in label order. The label-free
  crossing count (crossings closer than ``COINCIDENCE_FRACTION`` of the ray's
  pitch are one physical crossing) must equal the label span, and consecutive
  labels must step by the solution's orientation (+1 or -1).
* **pitch** -- each label-free gap along the ray, divided by that ray's median
  gap, must lie inside ``PITCH_BAND``. Pitch is also reported in micrometres
  when the voxel size is given (median and IQR over cells).
* **identity continuity** -- across each boundary between neighbouring cells
  (theta +-1 with wrap, z +-1), every label shared by both cells is followed
  (label l to l at an ordinary boundary, l to l + orientation at the declared
  branch cut). Neighbouring sheets move together, so the radial shift of
  consecutive shared labels may not differ by more than ``MATCH_FRACTION`` of
  the pitch, the median shift may not exceed it either (a bulk relabel or a
  wrong branch cut), and an interior label may not vanish across the boundary.

A fourth, weaker check (**support**) flags a crossing whose point density
(points / radius) is below ``SUPPORT_FRACTION`` of the cell median.

Every threshold here is ScrollQ's own, frozen in this file before any real
solution was measured; none is taken from an external project. The checks use
geometry and winding labels only (never ink) and never consult a reference
solution: ``calibrate`` measures how small a planted defect can be and still
fire, and how often the same footprint fires on the unmodified solution.

Flags are review cues, not verdicts. Folding, tears and the scroll's own start
and end break these invariants legitimately; the innermost and outermost
crossing of every cell are exempt from the partner check for that reason.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from .winding_geometry import Umbilicus, load_umbilicus, parse_umbilicus

SCHEMA_VERSION = 1
TOOL = "scroliq-winding-conservation"
DIAGNOSTIC = "winding-conservation"
METHOD = "scroliq-winding-conservation-v1"

# Frozen constants (ScrollQ's own; not calibrated on any real solution).
THETA_BINS = 72  # 5 degrees per cell
Z_BIN = 16.0  # voxels per cell
MIN_CROSSING_POINTS = 3  # a label needs this many points in a cell to count
MIN_GAPS_FOR_PITCH = 3  # fewer gaps: the ray's pitch is not estimated
COINCIDENCE_FRACTION = 0.3  # gaps below this x ray pitch are one crossing
PITCH_BAND = (0.6, 1.4)  # allowed gap / ray pitch
MATCH_FRACTION = 0.5  # neighbour match tolerance x pitch
SUPPORT_FRACTION = 0.5  # density below this x cell median is a deficit
RELIABLE_RATE = 0.95  # calibrate: detection share called "reliable"

FAMILIES = ("layer_count", "pitch", "continuity", "support")
DEFECTS = ("delete", "duplicate", "merge", "switch")
DUPLICATE_OFFSET = 1.0  # voxels between a duplicated surface and its source

LIMITATION = (
    "Conservation flags are review cues, not errors: folds, tears, crushed "
    "regions and the scroll's start and end can break ray order, pitch and "
    "partner matching legitimately. A clean report says the stitched labels "
    "are self-consistent at the cell resolution; it does not establish CT "
    "support, recto coverage, or that the labels match the physical windings."
)


class Solution:
    """Labelled surface points: ``xyz`` (N, 3) base voxels, integer ``winding``."""

    def __init__(self, xyz: np.ndarray, winding: np.ndarray, *, source: str | None = None,
                 sha256: str | None = None):
        xyz = np.asarray(xyz, dtype=np.float64)
        winding = np.asarray(winding)
        if xyz.ndim != 2 or xyz.shape[1] != 3:
            raise ValueError("xyz must have shape (N, 3)")
        if winding.shape != (xyz.shape[0],):
            raise ValueError("winding must have one label per point")
        if winding.size and not np.issubdtype(winding.dtype, np.integer):
            if not np.all(np.isfinite(winding)) or not np.all(np.mod(winding, 1) == 0):
                raise ValueError("winding labels must be integers")
        keep = np.all(np.isfinite(xyz), axis=1)
        self.xyz = xyz[keep]
        self.winding = winding[keep].astype(np.int64)
        self.dropped_nonfinite = int((~keep).sum())
        self.source = source
        self.sha256 = sha256


def load_solution(path: str | Path) -> Solution:
    """Load an ``.npz`` with ``xyz`` (N, 3) and ``winding`` (N,) arrays."""
    raw = Path(path).read_bytes()
    with np.load(Path(path), allow_pickle=False) as data:
        if "xyz" not in data or "winding" not in data:
            raise ValueError("solution .npz needs 'xyz' and 'winding' arrays")
        return Solution(data["xyz"], data["winding"], source=str(path),
                        sha256=hashlib.sha256(raw).hexdigest())


def _cylindrical(xyz: np.ndarray, umbilicus: Umbilicus, cut: float):
    axis = umbilicus(xyz[:, 2])
    dy = xyz[:, 1] - axis[:, 0]
    dx = xyz[:, 0] - axis[:, 1]
    radius = np.hypot(dy, dx)
    phi = np.mod(np.arctan2(dy, dx) - cut, 2 * math.pi)
    return radius, phi, axis


def _in_window(zb: np.ndarray, tb: np.ndarray, window: tuple[int, int, int, int]) -> np.ndarray:
    z0, z1, t0, t1 = window
    inside_t = (tb >= t0) & (tb <= t1) if t0 <= t1 else (tb >= t0) | (tb <= t1)
    return (zb >= z0) & (zb <= z1) & inside_t


def _crossings(solution: Solution, umbilicus: Umbilicus, *, cut: float, z_origin: float,
               theta_bins: int, z_bin: float, window: tuple[int, int, int, int] | None = None):
    """Per (cell, label): median radius and point count, sorted by (cell, radius).
    With ``window``, only points in those cells are binned."""
    radius, phi, _ = _cylindrical(solution.xyz, umbilicus, cut)
    zb = np.floor((solution.xyz[:, 2] - z_origin) / z_bin).astype(np.int64)
    tb = np.minimum((phi / (2 * math.pi) * theta_bins).astype(np.int64), theta_bins - 1)
    ok = (radius > 0) & (zb >= 0)
    nz_all = int(zb.max()) + 1 if zb.size else 0
    if window is not None:
        ok &= _in_window(zb, tb, window)
    zb, tb, w, r = zb[ok], tb[ok], solution.winding[ok], radius[ok]
    if not r.size:
        empty = np.empty(0, dtype=np.int64)
        return empty, empty, empty, np.empty(0), empty, nz_all
    nz = nz_all
    cell = zb * theta_bins + tb
    order = np.lexsort((r, w, cell))
    cell, w, r = cell[order], w[order], r[order]
    key_change = np.ones(cell.size, dtype=bool)
    key_change[1:] = (cell[1:] != cell[:-1]) | (w[1:] != w[:-1])
    starts = np.flatnonzero(key_change)
    counts = np.diff(np.append(starts, cell.size))
    med = r[starts + (counts - 1) // 2]
    even = counts % 2 == 0
    med = np.where(even, 0.5 * (med + r[np.minimum(starts + counts // 2, r.size - 1)]), med)
    c_cell, c_w = cell[starts], w[starts]
    order = np.lexsort((med, c_cell))
    return c_cell[order], c_w[order], med[order], counts[order], tb, nz


def _modal(values: list[int]) -> int:
    counts = Counter(values)
    best = max(counts.values())
    return min((v for v, c in counts.items() if c == best), key=lambda v: (abs(v), v))


def measure(
    solution: Solution,
    umbilicus: Umbilicus,
    *,
    voxel_um: float | None = None,
    branch_cut_degrees: float = 0.0,
    z_origin: float | None = None,
    theta_bins: int = THETA_BINS,
    z_bin: float = Z_BIN,
    cell_window: tuple[int, int, int, int] | None = None,
    max_flagged_cells: int = 200,
) -> dict[str, Any]:
    """Measure the conservation invariants. ``cell_window`` = (z0, z1, t0, t1)
    restricts which cells are *reported* (inclusive bins, theta may wrap); the
    cells one bin around it are still read so every reported cell keeps its
    neighbour comparisons, and nothing further away is computed."""
    if theta_bins < 8 or not z_bin > 0:
        raise ValueError("theta_bins must be >= 8 and z_bin > 0")
    cut = math.radians(branch_cut_degrees)
    if z_origin is None:
        z_origin = float(np.floor(solution.xyz[:, 2].min())) if solution.xyz.size else 0.0
    read_window = None
    if cell_window is not None:
        z0, z1, t0, t1 = cell_window
        span = (t1 - t0) % theta_bins + 1
        read_window = ((z0 - 1, z1 + 1, 0, theta_bins - 1) if span + 2 >= theta_bins
                       else (z0 - 1, z1 + 1, (t0 - 1) % theta_bins, (t1 + 1) % theta_bins))
    c_cell, c_w, c_r, c_n, _, nz = _crossings(
        solution, umbilicus, cut=cut, z_origin=z_origin, theta_bins=theta_bins, z_bin=z_bin,
        window=read_window)
    keep = c_n >= MIN_CROSSING_POINTS
    sparse = int((~keep).sum())
    c_cell, c_w, c_r, c_n = c_cell[keep], c_w[keep], c_r[keep], c_n[keep]

    bounds = np.searchsorted(c_cell, np.arange(nz * theta_bins + 1))
    steps_all = []
    for cell in range(nz * theta_bins):
        lo, hi = bounds[cell], bounds[cell + 1]
        if hi - lo >= 2:
            steps_all.extend(np.diff(c_w[lo:hi]).tolist())
    nonzero = [s for s in steps_all if s]
    orientation = 1 if not nonzero or sum(1 for s in nonzero if s > 0) >= len(nonzero) / 2 else -1

    cells: dict[int, dict[str, Any]] = {}
    for cell in range(nz * theta_bins):
        lo, hi = bounds[cell], bounds[cell + 1]
        if hi == lo:
            continue
        r, w, n = c_r[lo:hi], c_w[lo:hi], c_n[lo:hi]
        info: dict[str, Any] = {"crossings": int(r.size), "flags": Counter(), "pitch": None}
        gaps = np.diff(r)
        if gaps.size >= MIN_GAPS_FOR_PITCH:
            pitch = float(np.median(gaps))
            info["pitch"] = pitch
            coincident = gaps < COINCIDENCE_FRACTION * pitch
            free_count = int(r.size - coincident.sum())
            span = int(abs(int(w.max()) - int(w.min())) + 1)
            residual = free_count - span
            info["layer_residual"] = residual
            bad_steps = int(np.sum(np.diff(w) != orientation))
            if residual or bad_steps:
                info["flags"]["layer_count"] += abs(residual) + bad_steps
            free_r = r[np.concatenate([[True], ~coincident])]
            ratio = np.diff(free_r) / pitch
            out = (ratio < PITCH_BAND[0]) | (ratio > PITCH_BAND[1])
            if out.any():
                info["flags"]["pitch"] += int(out.sum())
                info["pitch_ratio_extremes"] = [float(ratio.min()), float(ratio.max())]
            if r.size >= 3:
                density = n / r
                deficit = density < SUPPORT_FRACTION * float(np.median(density))
                if deficit.any():
                    info["flags"]["support"] += int(deficit.sum())
        cells[cell] = info

    def neighbours(cell: int):
        zb, tb = divmod(cell, theta_bins)
        offset = orientation if tb == theta_bins - 1 else 0  # the branch cut
        yield zb * theta_bins + (tb + 1) % theta_bins, offset
        if zb + 1 < nz:
            yield (zb + 1) * theta_bins + tb, 0

    for cell, info in cells.items():
        for other, offset in neighbours(cell):
            if other not in cells:
                continue
            pa, pb = info["pitch"], cells[other]["pitch"]
            if pa is None or pb is None:
                continue
            tol = MATCH_FRACTION * min(pa, pb)
            la, ha = bounds[cell], bounds[cell + 1]
            lb, hb = bounds[other], bounds[other + 1]
            ra = dict(zip(c_w[la:ha].tolist(), c_r[la:ha].tolist()))
            rb = dict(zip(c_w[lb:hb].tolist(), c_r[lb:hb].tolist()))
            common = sorted(l for l in ra if l + offset in rb)
            if len(common) >= 2:
                # Adjacent sheets move together across one cell boundary; a
                # label that jumps to another sheet breaks that by ~a pitch.
                # A shift of the whole ray by about a pitch is a bulk relabel
                # (or a wrong branch cut) and flags every shared label.
                shift = np.array([rb[l + offset] - ra[l] for l in common])
                if abs(float(np.median(shift))) > tol:
                    bad = len(common)
                else:
                    bad = int(np.sum(np.abs(np.diff(shift)) > tol))
                if bad:
                    info["flags"]["continuity"] += bad
                    cells[other]["flags"]["continuity"] += bad
            # An interior identity must not vanish across a cell boundary.
            for side, src, dst, step in ((info, ra, rb, offset), (cells[other], rb, ra, -offset)):
                labels = sorted(src)
                lo, hi = min(dst) - step, max(dst) - step
                lost = sum(1 for l in labels[1:-1] if lo < l < hi and l + step not in dst)
                if lost:
                    side["flags"]["continuity"] += lost

    def reported(cell: int) -> bool:
        if cell_window is None:
            return True
        zb, tb = divmod(cell, theta_bins)
        return bool(_in_window(np.array([zb]), np.array([tb]), cell_window)[0])

    flagged = []
    family_cells = Counter()
    pitches = []
    evaluated = 0
    for cell in sorted(cells):
        if not reported(cell):
            continue
        info = cells[cell]
        if info["pitch"] is None:
            continue
        evaluated += 1
        pitches.append(info["pitch"])
        if info["flags"]:
            zb, tb = divmod(cell, theta_bins)
            for family in info["flags"]:
                family_cells[family] += 1
            flagged.append({
                "z_bin": zb,
                "theta_bin": tb,
                "z_range": [z_origin + zb * z_bin, z_origin + (zb + 1) * z_bin],
                "theta_degrees": [
                    (branch_cut_degrees + tb * 360.0 / theta_bins) % 360.0,
                    (branch_cut_degrees + (tb + 1) * 360.0 / theta_bins) % 360.0,
                ],
                "flags": dict(sorted(info["flags"].items())),
                "crossings": info["crossings"],
                "pitch_voxels": info["pitch"],
                "layer_residual": info.get("layer_residual"),
            })
    flagged.sort(key=lambda row: (-sum(row["flags"].values()), row["z_bin"], row["theta_bin"]))

    pitch_summary = None
    if pitches:
        q1, q2, q3 = (float(v) for v in np.percentile(pitches, [25, 50, 75]))
        pitch_summary = {"cells": len(pitches), "median_voxels": q2, "iqr_voxels": [q1, q3]}
        if voxel_um:
            pitch_summary.update(
                median_um=q2 * voxel_um, iqr_um=[q1 * voxel_um, q3 * voxel_um])

    status = "not-evaluated" if not evaluated else ("review" if flagged else "consistent")
    return {
        "schema_version": SCHEMA_VERSION,
        "diagnostic": DIAGNOSTIC,
        "method": METHOD,
        "status": status,
        "solution": {
            "source": solution.source,
            "sha256": solution.sha256,
            "points": int(solution.xyz.shape[0]),
            "dropped_nonfinite": solution.dropped_nonfinite,
            "labels": int(np.unique(solution.winding).size),
        },
        "umbilicus": {"source": umbilicus.source, "sha256": umbilicus.sha256},
        "parameters": {
            "theta_bins": theta_bins,
            "z_bin_voxels": z_bin,
            "z_origin": z_origin,
            "branch_cut_degrees": branch_cut_degrees,
            "min_crossing_points": MIN_CROSSING_POINTS,
            "min_gaps_for_pitch": MIN_GAPS_FOR_PITCH,
            "coincidence_fraction": COINCIDENCE_FRACTION,
            "pitch_band": list(PITCH_BAND),
            "match_fraction": MATCH_FRACTION,
            "support_fraction": SUPPORT_FRACTION,
            "voxel_um": voxel_um,
        },
        "label_orientation": orientation,
        "cells_evaluated": evaluated,
        "sparse_crossings_skipped": sparse,
        "flagged_cells": len(flagged),
        "flagged_cells_by_family": {f: int(family_cells.get(f, 0)) for f in FAMILIES},
        "pitch": pitch_summary,
        "flagged": flagged[:max_flagged_cells],
        "flagged_truncated": max(len(flagged) - max_flagged_cells, 0),
        "limitation": LIMITATION,
    }


# --------------------------------------------------------------------------
# Planted defects. Each acts only inside the footprint
# theta in [theta0, theta0 + dtheta) (degrees, relative to the branch cut,
# wrapping), z in [z0, z0 + dz), on winding ``k``; nothing else changes.


def _footprint(solution: Solution, umbilicus: Umbilicus, cut: float, theta0: float,
               dtheta: float, z0: float, dz: float):
    radius, phi, axis = _cylindrical(solution.xyz, umbilicus, cut)
    rel = np.mod(np.degrees(phi) - theta0, 360.0)
    z = solution.xyz[:, 2]
    inside = (rel < dtheta) & (z >= z0) & (z < z0 + dz)
    return inside, radius, axis


def _move_radial(xyz: np.ndarray, axis: np.ndarray, radius: np.ndarray, delta: np.ndarray):
    out = xyz.copy()
    scale = (radius + delta) / radius
    out[:, 0] = axis[:, 1] + (xyz[:, 0] - axis[:, 1]) * scale
    out[:, 1] = axis[:, 0] + (xyz[:, 1] - axis[:, 0]) * scale
    return out


def _neighbour_gap(solution: Solution, radius: np.ndarray, umbilicus: Umbilicus, cut: float,
                   k: int, step: int, sel: np.ndarray) -> np.ndarray:
    """Per point of label k in ``sel``: radius of label k+step at the nearest
    (theta, z) sample minus own radius."""
    _, phi, _ = _cylindrical(solution.xyz, umbilicus, cut)
    src = sel & (solution.winding == k)
    dst = sel & (solution.winding == k + step)
    if not dst.any():
        raise ValueError(f"winding {k + step} has no points inside the footprint")
    key_d = np.stack([phi[dst], solution.xyz[dst, 2]], axis=1)
    key_s = np.stack([phi[src], solution.xyz[src, 2]], axis=1)
    rd = radius[dst]
    out = np.empty(key_s.shape[0])
    for start in range(0, key_s.shape[0], 2048):
        block = key_s[start:start + 2048]
        dphi = np.abs(block[:, None, 0] - key_d[None, :, 0])
        dphi = np.minimum(dphi, 2 * math.pi - dphi) * 100.0  # ~ voxels at r=100
        d2 = dphi ** 2 + (block[:, None, 1] - key_d[None, :, 1]) ** 2
        out[start:start + block.shape[0]] = rd[np.argmin(d2, axis=1)]
    return out - radius[src]


def plant_defect(
    solution: Solution,
    umbilicus: Umbilicus,
    *,
    kind: str,
    k: int,
    theta0: float,
    dtheta: float,
    z0: float,
    dz: float,
    branch_cut_degrees: float = 0.0,
    orientation: int = 1,
) -> Solution:
    """Return a copy of ``solution`` with one deterministic defect planted.

    * ``delete``: winding k's points inside the footprint are removed.
    * ``duplicate``: winding k is emitted twice; the copy (offset outward by
      ``DUPLICATE_OFFSET`` voxels) takes label k+1 and every outer label
      inside the footprint shifts by one, as an extra-wrap stitch would.
    * ``merge``: windings k and k+1 become one surface halfway between them,
      labelled k; outer labels inside the footprint shift back by one.
    * ``switch``: winding k's surface is replaced by winding k+1's surface
      (still a real, CT-seated sheet), keeping label k.

    Labels "outer" and "+1" follow ``orientation``.
    """
    if kind not in DEFECTS:
        raise ValueError(f"unknown defect {kind!r}")
    cut = math.radians(branch_cut_degrees)
    inside, radius, axis = _footprint(solution, umbilicus, cut, theta0, dtheta, z0, dz)
    w = solution.winding
    nxt = k + orientation
    outer = inside & ((w - k) * orientation > 0)
    xyz, labels = solution.xyz, w.copy()
    if kind == "delete":
        keep = ~(inside & (w == k))
        return Solution(xyz[keep], labels[keep], source=solution.source)
    if kind == "duplicate":
        src = inside & (w == k)
        labels[outer] += orientation
        copy = _move_radial(xyz[src], axis[src], radius[src],
                            np.full(int(src.sum()), DUPLICATE_OFFSET))
        return Solution(np.vstack([xyz, copy]),
                        np.concatenate([labels, np.full(copy.shape[0], nxt)]),
                        source=solution.source)
    if kind == "merge":
        src = inside & (w == k)
        gap = _neighbour_gap(solution, radius, umbilicus, cut, k, orientation, inside)
        moved = xyz.copy()
        moved[src] = _move_radial(xyz[src], axis[src], radius[src], gap / 2.0)
        drop = inside & (w == nxt)
        beyond = inside & ((w - nxt) * orientation > 0)
        labels[beyond] -= orientation
        return Solution(moved[~drop], labels[~drop], source=solution.source)
    # switch
    src = inside & (w == nxt)
    keep = ~(inside & (w == k))
    return Solution(np.vstack([xyz[keep], xyz[src]]),
                    np.concatenate([labels[keep], np.full(int(src.sum()), k)]),
                    source=solution.source)


# --------------------------------------------------------------------------
# Deterministic synthetic spiral (calibration substrate, not data).

SYNTHETIC = {
    "pitch_voxels": 20.0,
    "voxel_um": 8.64,
    "r0_voxels": 60.0,
    "windings": 16,
    "z_range": [0.0, 256.0],
    "theta_step_degrees": 1.0,
    "z_step_voxels": 4.0,
    "pitch_modulation": 0.15,
    "radial_jitter_voxels": 0.75,
    "compression": {"windings": [6, 10], "factor": 0.65, "theta_center_degrees": 200.0,
                    "theta_half_width_degrees": 60.0, "z_center": 128.0, "z_half_width": 96.0},
    "seed": 20261005,
}


def _synthetic_umbilicus_doc() -> dict[str, Any]:
    return {"control_points": [{"z": z, "y": 400.0 + 0.08 * z, "x": 420.0 - 0.05 * z}
                               for z in (0.0, 512.0)]}


def synthetic_solution(params: dict[str, Any] | None = None) -> tuple[Solution, Umbilicus]:
    """A deformed Archimedean spiral with smooth pitch modulation, radial
    jitter and one compressed-but-correct sector (a hard null for pitch)."""
    p = dict(SYNTHETIC if params is None else params)
    umb = parse_umbilicus(_synthetic_umbilicus_doc(), source="synthetic")
    phi = np.radians(np.arange(0.5, 360.0, p["theta_step_degrees"]))
    z = np.arange(p["z_range"][0] + p["z_step_voxels"] / 2, p["z_range"][1], p["z_step_voxels"])
    PHI, Z = np.meshgrid(phi, z, indexing="ij")
    base = p["pitch_voxels"] * (
        1 + p["pitch_modulation"] * np.sin(PHI + 0.7) * np.cos(2 * math.pi * Z / 512.0))
    comp = p["compression"]
    dphi = np.abs(np.degrees(PHI) - comp["theta_center_degrees"])
    dphi = np.minimum(dphi, 360.0 - dphi)
    taper = (np.clip(1 - dphi / comp["theta_half_width_degrees"], 0, 1)
             * np.clip(1 - np.abs(Z - comp["z_center"]) / comp["z_half_width"], 0, 1))
    taper = 0.5 - 0.5 * np.cos(math.pi * taper)  # smooth raised cosine 0..1
    windings = int(p["windings"])
    gaps = np.repeat(base[None], windings, axis=0)
    c0, c1 = comp["windings"]
    gaps[c0:c1] *= 1 - (1 - comp["factor"]) * taper[None]
    inner = np.concatenate([np.zeros((1,) + PHI.shape), np.cumsum(gaps, axis=0)[:-1]])
    radius = p["r0_voxels"] + inner + gaps * (PHI / (2 * math.pi))[None]
    rng = np.random.default_rng(p["seed"])
    radius = radius + rng.normal(0.0, p["radial_jitter_voxels"], radius.shape)
    zz = np.broadcast_to(Z, radius.shape).ravel()
    pp = np.broadcast_to(PHI, radius.shape).ravel()
    axis = umb(zz)
    r = radius.ravel()
    xyz = np.stack([axis[:, 1] + r * np.cos(pp), axis[:, 0] + r * np.sin(pp), zz], axis=1)
    labels = np.repeat(np.arange(windings), PHI.size)
    return Solution(xyz, labels, source="synthetic"), umb


# --------------------------------------------------------------------------
# Calibration ladder.

THETA_EXTENTS = (2.5, 5.0, 10.0, 20.0, 45.0, 90.0, 180.0, 360.0)
Z_EXTENTS = (4.0, 8.0, 16.0, 32.0, 64.0, 128.0)
PLACEMENTS = 16


def _placements(rng: np.random.Generator, n: int, dz: float, z_lo: float, z_hi: float,
                k_lo: int, k_hi: int):
    out = []
    for _ in range(n):
        out.append((float(rng.uniform(0.0, 360.0)),
                    float(rng.uniform(z_lo, max(z_lo, z_hi - dz))),
                    int(rng.integers(k_lo, k_hi + 1))))
    return out


def _window(theta0: float, dtheta: float, z0: float, dz: float, z_origin: float,
            theta_bins: int, z_bin: float, nz: int, margin: int = 1):
    width = 360.0 / theta_bins
    t0 = int(math.floor(theta0 / width)) - margin
    t1 = int(math.floor((theta0 + dtheta - 1e-9) / width)) + margin
    if t1 - t0 + 1 >= theta_bins:
        t0, t1 = 0, theta_bins - 1
    zb0 = max(int(math.floor((z0 - z_origin) / z_bin)) - margin, 0)
    zb1 = min(int(math.floor((z0 + dz - 1e-9 - z_origin) / z_bin)) + margin, nz - 1)
    return zb0, zb1, t0 % theta_bins, t1 % theta_bins


def _fired(report: dict[str, Any]) -> dict[str, bool]:
    by = report["flagged_cells_by_family"]
    out = {family: by[family] > 0 for family in FAMILIES}
    out["any"] = report["flagged_cells"] > 0
    return out


def calibrate(
    solution: Solution,
    umbilicus: Umbilicus,
    *,
    seed: int = 0,
    theta_extents: Sequence[float] = THETA_EXTENTS,
    z_extents: Sequence[float] = Z_EXTENTS,
    placements: int = PLACEMENTS,
    defects: Sequence[str] = DEFECTS,
    voxel_um: float | None = None,
    branch_cut_degrees: float = 0.0,
    edge_windings: int = 3,
) -> dict[str, Any]:
    """Plant every defect at every (theta, z) extent ``placements`` times and
    record which invariant families fire in the footprint (dilated by one
    cell), next to the same footprints measured on the unmodified solution."""
    z_origin = float(np.floor(solution.xyz[:, 2].min()))
    z_hi = float(solution.xyz[:, 2].max())
    labels = np.unique(solution.winding)
    k_lo, k_hi = int(labels.min()) + edge_windings, int(labels.max()) - edge_windings - 1
    if k_hi < k_lo:
        raise ValueError("solution has too few windings to place defects away from its edges")
    clean = measure(solution, umbilicus, voxel_um=voxel_um, branch_cut_degrees=branch_cut_degrees,
                    z_origin=z_origin, max_flagged_cells=10**9)
    orientation = clean["label_orientation"]
    nz = int(math.floor((z_hi - z_origin) / Z_BIN)) + 1
    clean_cells = {(row["z_bin"], row["theta_bin"]): row["flags"] for row in clean["flagged"]}

    def null_fired(window):
        z0, z1, t0, t1 = window
        fired = {family: False for family in FAMILIES}
        for (zb, tb), flags in clean_cells.items():
            inside_t = t0 <= tb <= t1 if t0 <= t1 else (tb >= t0 or tb <= t1)
            if z0 <= zb <= z1 and inside_t:
                for family in flags:
                    fired[family] = True
        fired["any"] = any(fired.values())
        return fired

    rows = []
    rng = np.random.default_rng(seed)
    for kind in defects:
        for dz in z_extents:
            for dtheta in theta_extents:
                hits = Counter()
                null_hits = Counter()
                for theta0, z0, k in _placements(rng, placements, dz, z_origin, z_hi, k_lo, k_hi):
                    planted = plant_defect(solution, umbilicus, kind=kind, k=k, theta0=theta0,
                                           dtheta=dtheta, z0=z0, dz=dz,
                                           branch_cut_degrees=branch_cut_degrees,
                                           orientation=orientation)
                    window = _window(theta0, dtheta, z0, dz, z_origin, THETA_BINS, Z_BIN, nz)
                    report = measure(planted, umbilicus, branch_cut_degrees=branch_cut_degrees,
                                     z_origin=z_origin, cell_window=window, max_flagged_cells=0)
                    for family, fired in _fired(report).items():
                        hits[family] += fired
                    for family, fired in null_fired(window).items():
                        null_hits[family] += fired
                rows.append({
                    "defect": kind,
                    "dz_voxels": dz,
                    "dtheta_degrees": dtheta,
                    "placements": placements,
                    "detection_rate": {f: hits[f] / placements for f in FAMILIES + ("any",)},
                    "null_rate": {f: null_hits[f] / placements for f in FAMILIES + ("any",)},
                })

    def smallest(kind: str, family: str):
        out = []
        for dz in z_extents:
            # Smallest theta extent from which every larger one is also reliable.
            found = None
            for dtheta in sorted(theta_extents, reverse=True):
                row = next(r for r in rows if r["defect"] == kind and r["dz_voxels"] == dz
                           and r["dtheta_degrees"] == dtheta)
                if row["detection_rate"][family] < RELIABLE_RATE:
                    break
                found = {"dtheta_degrees": dtheta,
                         "detection_rate": row["detection_rate"][family],
                         "null_rate": row["null_rate"][family]}
            out.append({"dz_voxels": dz, "smallest_reliable": found})
        return out

    frontier = {kind: {family: smallest(kind, family) for family in FAMILIES + ("any",)}
                for kind in defects}
    return {
        "schema_version": SCHEMA_VERSION,
        "diagnostic": "winding-conservation-calibration",
        "method": METHOD,
        "seed": seed,
        "reliable_rate": RELIABLE_RATE,
        "theta_extents_degrees": list(theta_extents),
        "z_extents_voxels": list(z_extents),
        "placements_per_extent": placements,
        "defect_winding_range": [k_lo, k_hi],
        "detection_rule": (
            "a family fires when any cell in the footprint dilated by one cell carries its flag; "
            "null_rate is the same footprint on the unmodified solution; smallest_reliable is "
            "the smallest theta extent from which every larger one reaches reliable_rate"),
        "clean": {key: clean[key] for key in (
            "status", "solution", "parameters", "label_orientation", "cells_evaluated",
            "flagged_cells", "flagged_cells_by_family", "pitch")},
        "rows": rows,
        "smallest_reliable_extent": frontier,
        "limitation": LIMITATION,
    }


def _write(path: str, document: dict[str, Any]) -> None:
    out = Path(path)
    if out.exists():
        raise SystemExit(f"output already exists: {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")


def positive_control(solution: Solution, umbilicus: Umbilicus, report: dict[str, Any], *,
                     branch_cut_degrees: float) -> dict[str, Any]:
    """Delete the median winding over a 45 deg x 4-cell footprint at the
    median z; the measurement must flag it, or the run is ``unverified``."""
    labels = np.unique(solution.winding)
    k = int(labels[labels.size // 2])
    z_origin = report["parameters"]["z_origin"]
    sel = solution.winding == k
    z0 = float(np.median(solution.xyz[sel, 2])) if sel.any() else z_origin
    z0 = z_origin + Z_BIN * math.floor((z0 - z_origin) / Z_BIN)
    planted = plant_defect(solution, umbilicus, kind="delete", k=k, theta0=90.0, dtheta=45.0,
                           z0=z0, dz=4 * Z_BIN, branch_cut_degrees=branch_cut_degrees)
    nz = int(math.floor((float(solution.xyz[:, 2].max()) - z_origin) / Z_BIN)) + 1
    window = _window(90.0, 45.0, z0, 4 * Z_BIN, z_origin, THETA_BINS, Z_BIN, nz)
    planted_report = measure(planted, umbilicus, branch_cut_degrees=branch_cut_degrees,
                             z_origin=z_origin, cell_window=window, max_flagged_cells=0)
    clean_in_window = measure(solution, umbilicus, branch_cut_degrees=branch_cut_degrees,
                              z_origin=z_origin, cell_window=window, max_flagged_cells=0)
    detected = planted_report["flagged_cells"] > clean_in_window["flagged_cells"]
    return {"defect": "delete", "winding": k, "theta0_degrees": 90.0, "dtheta_degrees": 45.0,
            "z0": z0, "dz_voxels": 4 * Z_BIN, "detected": bool(detected),
            "flagged_cells_planted": planted_report["flagged_cells"],
            "flagged_cells_clean": clean_in_window["flagged_cells"]}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p_measure = sub.add_parser("measure", help="measure the invariants on a labelled solution")
    p_measure.add_argument("--solution", required=True,
                           help=".npz with xyz (N,3) base-voxel XYZ and winding (N,) labels")
    p_measure.add_argument("--umbilicus", required=True, help="umbilicus.json (control_points)")
    p_measure.add_argument("--voxel-um", type=float, help="voxel size, to report pitch in um")
    p_measure.add_argument("--branch-cut-degrees", type=float, default=0.0)
    p_measure.add_argument("--out", required=True)

    p_cal = sub.add_parser("calibrate",
                           help="plant delete/duplicate/merge/switch defects over an extent ladder")
    p_cal.add_argument("--solution", help="labelled .npz; default: the built-in synthetic spiral")
    p_cal.add_argument("--umbilicus", help="required with --solution")
    p_cal.add_argument("--voxel-um", type=float)
    p_cal.add_argument("--branch-cut-degrees", type=float, default=0.0)
    p_cal.add_argument("--seed", type=int, default=0)
    p_cal.add_argument("--placements", type=int, default=PLACEMENTS)
    p_cal.add_argument("--out", required=True)

    args = parser.parse_args(argv)
    if args.command == "measure":
        solution = load_solution(args.solution)
        umbilicus = load_umbilicus(Path(args.umbilicus))
        report = measure(solution, umbilicus, voxel_um=args.voxel_um,
                         branch_cut_degrees=args.branch_cut_degrees)
        if report["status"] != "not-evaluated":
            control = positive_control(solution, umbilicus, report,
                                       branch_cut_degrees=args.branch_cut_degrees)
            report["positive_control"] = control
            if not control["detected"]:
                report["status"] = "unverified"
        _write(args.out, report)
        print(f"{report['status']}: {report['flagged_cells']} flagged of "
              f"{report['cells_evaluated']} evaluated cells")
        return 0

    if args.solution:
        if not args.umbilicus:
            parser.error("--umbilicus is required with --solution")
        solution = load_solution(args.solution)
        umbilicus = load_umbilicus(Path(args.umbilicus))
        voxel_um = args.voxel_um
        substrate = {"kind": "solution", "source": solution.source, "sha256": solution.sha256}
    else:
        solution, umbilicus = synthetic_solution()
        voxel_um = args.voxel_um or SYNTHETIC["voxel_um"]
        substrate = {"kind": "synthetic", "parameters": SYNTHETIC}
    report = calibrate(solution, umbilicus, seed=args.seed, placements=args.placements,
                       voxel_um=voxel_um, branch_cut_degrees=args.branch_cut_degrees)
    report["substrate"] = substrate
    _write(args.out, report)
    print(f"calibrated {len(report['rows'])} defect/extent rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
