"""Research helpers for CT-local papyrus fiber/texture fingerprints.

This module is intentionally not exposed as a console script. It implements
the preregistered tangent-fiber-spectrum-v1 descriptor for issue #151.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np


class FiberFingerprintError(RuntimeError):
    pass


@dataclass(frozen=True)
class TangentFrame:
    origin_xyz: np.ndarray
    x_axis_xyz: np.ndarray
    y_axis_xyz: np.ndarray
    normal_xyz: np.ndarray

    def as_dict(self) -> dict:
        return {
            "origin_xyz": [float(v) for v in self.origin_xyz],
            "x_axis_xyz": [float(v) for v in self.x_axis_xyz],
            "y_axis_xyz": [float(v) for v in self.y_axis_xyz],
            "normal_xyz": [float(v) for v in self.normal_xyz],
        }


def _unit(value: np.ndarray, label: str) -> np.ndarray:
    arr = np.asarray(value, dtype=np.float64)
    if arr.shape != (3,) or not np.isfinite(arr).all():
        raise FiberFingerprintError(f"{label} must be a finite 3-vector")
    norm = float(np.linalg.norm(arr))
    if norm <= 1e-8:
        raise FiberFingerprintError(f"{label} is degenerate")
    return arr / norm


def tangent_frame_xyz(
    xyz: np.ndarray,
    valid: np.ndarray,
    y: int,
    x: int,
) -> TangentFrame | None:
    """Build a right-handed material frame from centered TIFXYZ tangents."""
    xyz = np.asarray(xyz, dtype=np.float64)
    valid = np.asarray(valid, dtype=bool)
    if xyz.ndim != 3 or xyz.shape[-1] != 3 or valid.shape != xyz.shape[:2]:
        raise FiberFingerprintError("xyz/valid shapes are inconsistent")
    h, w = valid.shape
    if y <= 0 or y >= h - 1 or x <= 0 or x >= w - 1:
        return None
    neighbors = ((y, x), (y, x - 1), (y, x + 1), (y - 1, x), (y + 1, x))
    if not all(valid[yy, xx] for yy, xx in neighbors):
        return None
    if not all(np.isfinite(xyz[yy, xx]).all() for yy, xx in neighbors):
        return None

    origin = np.asarray(xyz[y, x], dtype=np.float64)
    x_axis = _unit(xyz[y, x + 1] - xyz[y, x - 1], "column tangent")
    provisional_y = np.asarray(xyz[y + 1, x] - xyz[y - 1, x], dtype=np.float64)
    normal = _unit(np.cross(x_axis, provisional_y), "surface normal")
    y_axis = _unit(np.cross(normal, x_axis), "orthogonalized row tangent")
    return TangentFrame(
        origin_xyz=origin,
        x_axis_xyz=x_axis,
        y_axis_xyz=y_axis,
        normal_xyz=normal,
    )


def translated_frame(frame: TangentFrame, origin_xyz: Iterable[float]) -> TangentFrame:
    """Move a frozen frame to another origin without re-estimating orientation."""
    origin = np.asarray(list(origin_xyz), dtype=np.float64)
    if origin.shape != (3,) or not np.isfinite(origin).all():
        raise FiberFingerprintError("translated frame origin must be finite XYZ")
    return TangentFrame(
        origin_xyz=origin,
        x_axis_xyz=np.asarray(frame.x_axis_xyz, dtype=np.float64).copy(),
        y_axis_xyz=np.asarray(frame.y_axis_xyz, dtype=np.float64).copy(),
        normal_xyz=np.asarray(frame.normal_xyz, dtype=np.float64).copy(),
    )


def tangent_sample_coordinates_zyx(
    frame: TangentFrame,
    *,
    in_plane_offsets: Iterable[float],
    normal_offsets: Iterable[float],
) -> tuple[np.ndarray, tuple[int, int, int]]:
    """Return flattened global ZYX coordinates for a depth-v-u tangent slab."""
    uv = np.asarray(list(in_plane_offsets), dtype=np.float64)
    depths = np.asarray(list(normal_offsets), dtype=np.float64)
    if uv.ndim != 1 or uv.size == 0 or not np.isfinite(uv).all():
        raise FiberFingerprintError("in-plane offsets must be finite and non-empty")
    if depths.ndim != 1 or depths.size == 0 or not np.isfinite(depths).all():
        raise FiberFingerprintError("normal offsets must be finite and non-empty")

    coords_xyz = (
        frame.origin_xyz[None, None, None, :]
        + depths[:, None, None, None] * frame.normal_xyz[None, None, None, :]
        + uv[None, :, None, None] * frame.y_axis_xyz[None, None, None, :]
        + uv[None, None, :, None] * frame.x_axis_xyz[None, None, None, :]
    )
    shape = (int(depths.size), int(uv.size), int(uv.size))
    coords_zyx = coords_xyz[..., ::-1].reshape(-1, 3)
    return np.asarray(coords_zyx, dtype=np.float64), shape


def _orientation_histogram(
    grad_v: np.ndarray,
    grad_u: np.ndarray,
    *,
    bins: int,
) -> np.ndarray:
    magnitude = np.hypot(grad_u, grad_v)
    angle = np.mod(np.arctan2(grad_v, grad_u), np.pi)
    index = np.floor(angle * bins / np.pi).astype(np.int64)
    index = np.clip(index, 0, bins - 1)
    hist = np.bincount(index.ravel(), weights=magnitude.ravel(), minlength=bins)
    total = float(hist.sum())
    if not np.isfinite(total) or total <= 0:
        raise FiberFingerprintError("gradient orientation histogram has zero power")
    return np.asarray(hist / total, dtype=np.float64)


def _spectral_angular_features(
    normalized: np.ndarray,
    *,
    angular_bins: int,
    radial_bands: tuple[tuple[float, float], ...],
) -> np.ndarray:
    n0, n1 = normalized.shape
    if n0 != n1 or n0 < 3:
        raise FiberFingerprintError("spectral slice must be square and at least 3x3")
    window = np.outer(np.hanning(n0), np.hanning(n1))
    fft = np.fft.fftshift(np.fft.fft2(normalized * window))
    power = np.abs(fft) ** 2

    freq = np.arange(n0, dtype=np.float64) - (n0 // 2)
    kv, ku = np.meshgrid(freq, freq, indexing="ij")
    radius = np.hypot(ku, kv)
    angle = np.mod(np.arctan2(kv, ku), np.pi)
    angular_index = np.floor(angle * angular_bins / np.pi).astype(np.int64)
    angular_index = np.clip(angular_index, 0, angular_bins - 1)

    features = []
    for low, high in radial_bands:
        mask = (radius >= float(low)) & (radius < float(high))
        if not np.any(mask):
            raise FiberFingerprintError(
                f"spectral radial band [{low},{high}) is empty"
            )
        hist = np.bincount(
            angular_index[mask].ravel(),
            weights=power[mask].ravel(),
            minlength=angular_bins,
        ).astype(np.float64)
        total = float(hist.sum())
        if not np.isfinite(total) or total <= 0:
            raise FiberFingerprintError(
                f"spectral radial band [{low},{high}) has zero power"
            )
        features.extend((hist / total).tolist())
    return np.asarray(features, dtype=np.float64)


def tangent_fiber_spectrum_descriptor(
    slab: np.ndarray,
    *,
    minimum_nonzero_fraction: float = 0.95,
    gradient_orientation_bins: int = 12,
    gradient_magnitude_quantiles: tuple[float, ...] = (0.5, 0.75, 0.9, 0.95),
    spectral_angular_bins: int = 12,
    spectral_radial_bands: tuple[tuple[float, float], ...] = (
        (1.5, 4.0),
        (4.0, 8.0),
        (8.0, 12.5),
    ),
) -> tuple[np.ndarray, dict]:
    """Compute the preregistered tangent-fiber-spectrum-v1 descriptor."""
    raw = np.asarray(slab)
    if raw.ndim != 3 or raw.shape[1:] != (25, 25):
        raise FiberFingerprintError(
            f"slab must have shape [D,25,25], got {raw.shape}"
        )
    if not np.isfinite(raw).all():
        raise FiberFingerprintError("slab contains non-finite values")
    if not 0 <= minimum_nonzero_fraction <= 1:
        raise FiberFingerprintError("minimum_nonzero_fraction must be in [0,1]")
    nonzero_fraction = float(np.count_nonzero(raw) / raw.size)
    if nonzero_fraction < minimum_nonzero_fraction:
        raise FiberFingerprintError(
            f"slab nonzero fraction {nonzero_fraction:.6f} "
            f"< {minimum_nonzero_fraction:.6f}"
        )

    features: list[float] = []
    slice_reports = []
    for depth_index, slice_raw in enumerate(raw.astype(np.float64, copy=False)):
        median = float(np.median(slice_raw))
        q25 = float(np.quantile(slice_raw, 0.25))
        q75 = float(np.quantile(slice_raw, 0.75))
        iqr = q75 - q25
        if not np.isfinite(iqr) or iqr < 1.0:
            raise FiberFingerprintError(
                f"depth {depth_index} IQR {iqr!r} is < 1"
            )
        normalized = np.clip((slice_raw - median) / iqr, -5.0, 5.0)
        grad_v, grad_u = np.gradient(normalized)

        orient = _orientation_histogram(
            grad_v, grad_u, bins=gradient_orientation_bins
        )
        magnitude = np.hypot(grad_u, grad_v)
        magnitude_q = np.quantile(
            magnitude,
            np.asarray(gradient_magnitude_quantiles, dtype=np.float64),
        )
        spectral = _spectral_angular_features(
            normalized,
            angular_bins=spectral_angular_bins,
            radial_bands=spectral_radial_bands,
        )

        per_depth = np.concatenate(
            [orient, np.asarray(magnitude_q, dtype=np.float64), spectral]
        )
        if per_depth.shape != (52,):
            raise FiberFingerprintError(
                f"unexpected per-depth feature count {per_depth.shape}"
            )
        if not np.isfinite(per_depth).all():
            raise FiberFingerprintError("descriptor slice contains non-finite values")
        features.extend(per_depth.tolist())
        slice_reports.append(
            {
                "depth_index": int(depth_index),
                "median": median,
                "iqr": float(iqr),
                "gradient_magnitude_quantiles": [
                    float(v) for v in np.asarray(magnitude_q).tolist()
                ],
            }
        )

    vector = np.asarray(features, dtype=np.float64)
    expected = raw.shape[0] * 52
    if vector.shape != (expected,):
        raise FiberFingerprintError(
            f"unexpected descriptor length {len(vector)} != {expected}"
        )
    norm = float(np.linalg.norm(vector))
    if not np.isfinite(norm) or norm <= 0:
        raise FiberFingerprintError("descriptor has zero/non-finite L2 norm")
    vector = vector / norm
    return vector, {
        "name": "tangent-fiber-spectrum-v1",
        "shape": [int(v) for v in raw.shape],
        "dimension": int(vector.size),
        "nonzero_fraction": nonzero_fraction,
        "slice_reports": slice_reports,
        "l2_norm": float(np.linalg.norm(vector)),
    }


def cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine distance for finite non-zero descriptor vectors."""
    aa = np.asarray(a, dtype=np.float64).reshape(-1)
    bb = np.asarray(b, dtype=np.float64).reshape(-1)
    if aa.shape != bb.shape or aa.size == 0:
        raise FiberFingerprintError("descriptor vectors must have equal nonzero shape")
    if not np.isfinite(aa).all() or not np.isfinite(bb).all():
        raise FiberFingerprintError("descriptor vectors must be finite")
    na = float(np.linalg.norm(aa))
    nb = float(np.linalg.norm(bb))
    if na <= 0 or nb <= 0:
        raise FiberFingerprintError("descriptor vectors must be non-zero")
    similarity = float(np.dot(aa, bb) / (na * nb))
    return float(1.0 - np.clip(similarity, -1.0, 1.0))
