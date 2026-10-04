"""Frozen CT-local fiber/texture fingerprint primitives for sheet-identity R&D.

This module implements only the preregistered tangent-fiber-spectrum-v1
descriptor and deterministic development scoring. It makes no sheet-identity,
coverage, ink, or readability claim by itself.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

import numpy as np


class FiberFingerprintError(ValueError):
    """Invalid geometry, sampled CT patch, or frozen scoring input."""


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def descriptor_sha256(vector: np.ndarray) -> str:
    arr = np.asarray(vector, dtype="<f8").reshape(-1)
    return hashlib.sha256(arr.tobytes(order="C")).hexdigest()


def _unit(vector: np.ndarray, name: str) -> np.ndarray:
    value = np.asarray(vector, dtype=np.float64)
    if value.shape != (3,) or not np.isfinite(value).all():
        raise FiberFingerprintError(f"{name} must be one finite 3-vector")
    norm = float(np.linalg.norm(value))
    if norm <= 0:
        raise FiberFingerprintError(f"{name} must be non-zero")
    return value / norm


def tangent_frame(
    xyz: np.ndarray,
    valid: np.ndarray,
    y: int,
    x: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return center_xyz, x_axis, y_axis, normal using the frozen convention."""
    xyz = np.asarray(xyz, dtype=np.float64)
    valid = np.asarray(valid, dtype=bool)
    if xyz.ndim != 3 or xyz.shape[-1] != 3 or valid.shape != xyz.shape[:2]:
        raise FiberFingerprintError("xyz/valid shapes are incompatible")
    h, w = valid.shape
    if not (1 <= y < h - 1 and 1 <= x < w - 1):
        raise FiberFingerprintError("center lacks a centered tangent stencil")
    required = [(y, x), (y, x - 1), (y, x + 1), (y - 1, x), (y + 1, x)]
    if not all(valid[yy, xx] and np.isfinite(xyz[yy, xx]).all() for yy, xx in required):
        raise FiberFingerprintError("centered tangent stencil contains invalid material")

    center = np.asarray(xyz[y, x], dtype=np.float64)
    x_axis = _unit(xyz[y, x + 1] - xyz[y, x - 1], "column tangent")
    provisional_y = _unit(xyz[y + 1, x] - xyz[y - 1, x], "row tangent")
    normal = _unit(np.cross(x_axis, provisional_y), "surface normal")
    y_axis = _unit(np.cross(normal, x_axis), "orthogonal row tangent")
    return center, x_axis, y_axis, normal


def tangent_patch_coordinates(
    center_xyz: np.ndarray,
    x_axis: np.ndarray,
    y_axis: np.ndarray,
    normal: np.ndarray,
    *,
    in_plane_offsets: list[int] | tuple[int, ...] | np.ndarray,
    normal_offsets: list[int] | tuple[int, ...] | np.ndarray,
) -> np.ndarray:
    """Build [depth,v,u,xyz] coordinates for the frozen tangent-frame sampler."""
    center = np.asarray(center_xyz, dtype=np.float64)
    x_axis = _unit(x_axis, "x_axis")
    y_axis = _unit(y_axis, "y_axis")
    normal = _unit(normal, "normal")
    u = np.asarray(in_plane_offsets, dtype=np.float64)
    v = np.asarray(in_plane_offsets, dtype=np.float64)
    d = np.asarray(normal_offsets, dtype=np.float64)
    if u.ndim != 1 or d.ndim != 1 or not len(u) or not len(d):
        raise FiberFingerprintError("offset arrays must be non-empty 1-D arrays")
    if not np.isfinite(u).all() or not np.isfinite(d).all():
        raise FiberFingerprintError("offset arrays must be finite")

    dd, vv, uu = np.meshgrid(d, v, u, indexing="ij")
    coords = (
        center[None, None, None, :]
        + uu[..., None] * x_axis
        + vv[..., None] * y_axis
        + dd[..., None] * normal
    )
    return coords


def _angular_histogram(
    angles: np.ndarray,
    weights: np.ndarray,
    bins: int,
) -> np.ndarray:
    hist, _ = np.histogram(
        np.mod(angles, np.pi),
        bins=np.linspace(0.0, np.pi, bins + 1),
        weights=weights,
    )
    total = float(hist.sum())
    if not np.isfinite(total) or total <= 0:
        raise FiberFingerprintError("angular histogram has zero/invalid weight")
    return np.asarray(hist, dtype=np.float64) / total


def tangent_fiber_spectrum(
    patch: np.ndarray,
    *,
    orientation_bins: int = 12,
    magnitude_quantiles: tuple[float, ...] = (0.5, 0.75, 0.9, 0.95),
    radial_bands: tuple[tuple[float, float], ...] = (
        (1.5, 4.0),
        (4.0, 8.0),
        (8.0, 12.5),
    ),
) -> np.ndarray:
    """Compute the exact tangent-fiber-spectrum-v1 descriptor."""
    patch = np.asarray(patch, dtype=np.float64)
    if patch.ndim != 3:
        raise FiberFingerprintError("patch must have shape [depth,v,u]")
    depth, h, w = patch.shape
    if h != w or h < 5:
        raise FiberFingerprintError("in-plane patch must be square and at least 5x5")
    if orientation_bins <= 0:
        raise FiberFingerprintError("orientation_bins must be positive")
    if not np.isfinite(patch).all():
        raise FiberFingerprintError("patch contains non-finite values")

    yy = np.arange(h, dtype=np.float64) - (h // 2)
    xx = np.arange(w, dtype=np.float64) - (w // 2)
    fy, fx = np.meshgrid(yy, xx, indexing="ij")
    radius = np.sqrt(fx * fx + fy * fy)
    frequency_angle = np.mod(np.arctan2(fy, fx), np.pi)
    window = np.outer(np.hanning(h), np.hanning(w))

    features: list[np.ndarray] = []
    for z in range(depth):
        image = patch[z]
        median = float(np.median(image))
        q25, q75 = (float(v) for v in np.quantile(image, [0.25, 0.75]))
        iqr = q75 - q25
        if not np.isfinite(iqr) or iqr < 1.0:
            raise FiberFingerprintError("slice IQR is below frozen 1-unit minimum")
        normalized = np.clip((image - median) / iqr, -5.0, 5.0)

        grad_v, grad_u = np.gradient(normalized)
        magnitude = np.hypot(grad_u, grad_v)
        orientation = np.mod(np.arctan2(grad_v, grad_u), np.pi)
        grad_hist = _angular_histogram(orientation, magnitude, orientation_bins)
        mag_q = np.asarray(np.quantile(magnitude, magnitude_quantiles), dtype=np.float64)

        power = np.abs(np.fft.fftshift(np.fft.fft2(normalized * window))) ** 2
        spectral_parts = []
        for lower, upper in radial_bands:
            mask = (radius >= lower) & (radius < upper)
            if not mask.any():
                raise FiberFingerprintError("frozen radial band has no frequency cells")
            band = _angular_histogram(
                frequency_angle[mask],
                power[mask],
                orientation_bins,
            )
            spectral_parts.append(band)

        features.extend([grad_hist, mag_q, *spectral_parts])

    vector = np.concatenate(features).astype(np.float64, copy=False)
    norm = float(np.linalg.norm(vector))
    if not np.isfinite(norm) or norm <= 0:
        raise FiberFingerprintError("descriptor L2 norm is zero/invalid")
    return vector / norm


def cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    a = np.asarray(a, dtype=np.float64).reshape(-1)
    b = np.asarray(b, dtype=np.float64).reshape(-1)
    if a.shape != b.shape or not a.size:
        raise FiberFingerprintError("descriptor shapes must match and be non-empty")
    if not np.isfinite(a).all() or not np.isfinite(b).all():
        raise FiberFingerprintError("descriptors must be finite")
    an = float(np.linalg.norm(a))
    bn = float(np.linalg.norm(b))
    if an <= 0 or bn <= 0:
        raise FiberFingerprintError("descriptor norm must be positive")
    dot = float(np.dot(a / an, b / bn))
    return float(1.0 - np.clip(dot, -1.0, 1.0))


def score_development(
    groups: list[dict[str, Any]],
    *,
    quantile: float = 0.95,
    required_usable_groups: int = 8,
    required_positive_pairs: int = 24,
    minimum_wrong_wrap_rejection_fraction: float = 0.7,
    minimum_median_wrong_to_positive_distance_ratio: float = 1.25,
    require_median_wrong_distance_above_threshold: bool = True,
) -> dict[str, Any]:
    """Apply only the frozen development threshold and pass/fail rule."""
    usable = [row for row in groups if row.get("status") == "usable"]
    positive = [
        float(value)
        for row in usable
        for value in row.get("positive_distances", [])
        if np.isfinite(float(value))
    ]
    wrong = [
        float(row["wrong_wrap_score"])
        for row in usable
        if row.get("wrong_wrap_score") is not None
        and np.isfinite(float(row["wrong_wrap_score"]))
    ]

    threshold = (
        float(np.quantile(np.asarray(positive), quantile, method="linear"))
        if positive
        else None
    )
    rejection_fraction = (
        float(np.mean(np.asarray(wrong) > threshold))
        if threshold is not None and wrong
        else None
    )
    positive_median = float(np.median(positive)) if positive else None
    wrong_median = float(np.median(wrong)) if wrong else None
    ratio = (
        float(wrong_median / positive_median)
        if positive_median is not None
        and positive_median > 0
        and wrong_median is not None
        else None
    )

    checks = {
        "usable_groups": len(usable) >= required_usable_groups,
        "pooled_positive_pairs": len(positive) >= required_positive_pairs,
        "wrong_wrap_rejection_fraction": (
            rejection_fraction is not None
            and rejection_fraction >= minimum_wrong_wrap_rejection_fraction
        ),
        "median_wrong_to_positive_distance_ratio": (
            ratio is not None
            and ratio >= minimum_median_wrong_to_positive_distance_ratio
        ),
        "median_wrong_distance_above_threshold": (
            True
            if not require_median_wrong_distance_above_threshold
            else (
                threshold is not None
                and wrong_median is not None
                and wrong_median > threshold
            )
        ),
    }
    return {
        "status": "pass" if all(checks.values()) else "fail",
        "threshold": threshold,
        "quantile": float(quantile),
        "usable_group_count": len(usable),
        "pooled_positive_pair_count": len(positive),
        "wrong_wrap_group_count": len(wrong),
        "positive_distance_median": positive_median,
        "positive_distance_p95": (
            float(np.quantile(positive, 0.95, method="linear")) if positive else None
        ),
        "wrong_wrap_distance_median": wrong_median,
        "wrong_wrap_rejection_fraction": rejection_fraction,
        "median_wrong_to_positive_distance_ratio": ratio,
        "checks": checks,
    }
