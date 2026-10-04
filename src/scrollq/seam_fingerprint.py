"""Papyrus microtexture fingerprint authentication of claimed patch overlaps.

Given two shallow CT slabs that two independently built surface patches claim
to share (already rectified into local tangent coordinates ``(depth, y, x)`` on
a common pixel grid), this module asks one narrow question: do the band-passed
slabs contain the same microscopic arrangement of texture, at a displacement
compatible with the claimed registration?

The statistic is a band-limited, phase-preserving cross-correlation. Unlike the
magnitude-only ``fiber_fingerprint`` descriptor it is *not* shift invariant: it
keeps exactly the spatial identity that a descriptor of orientation histograms
discards. Ink is never read.

The verdict is three-valued and fail-closed: ``AUTHENTICATED`` needs a sharp,
unique, geometrically compatible peak that also beats phase-randomized
surrogates of the same slab; ``CONTRADICTED`` needs informative texture on both
sides and no compatible correspondence; everything else, including every
low-information patch, is ``UNKNOWN``.

What a peak can and cannot mean is limited by where the two slabs' noise comes
from. Slabs sampled from the *same* CT volume share voxel noise, so a peak there
certifies that both patches read the same voxel neighborhood (within the
recovered transform) - not that an independent physical fingerprint exists.
Independent registered rescans are the arm that tests physical microstructure.
The report records which arm it was.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Sequence

import numpy as np
from scipy.ndimage import binary_dilation, gaussian_filter
from scipy.ndimage import rotate as nd_rotate
from scipy.ndimage import shift as nd_shift

TOOL = "scroliq-seam-fingerprint"
SCHEMA_VERSION = 1
METHOD = "tangent-microtexture-phasecorr-v1"

AUTHENTICATED = "AUTHENTICATED"
CONTRADICTED = "CONTRADICTED"
UNKNOWN = "UNKNOWN"
VERDICTS = (AUTHENTICATED, CONTRADICTED, UNKNOWN)

_TINY = 1e-12
_RATIO_CAP = 1e3


class SeamFingerprintError(ValueError):
    """Invalid slab, mask, configuration, or report input."""


@dataclasses.dataclass(frozen=True)
class SeamConfig:
    """Every constant of ``tangent-microtexture-phasecorr-v1``.

    The decision constants are PROVISIONAL: they were set from synthetic data
    only and must be re-derived on a real-CT development split and then frozen,
    unchanged, before any held-out evaluation. ``config_sha256`` binds them to
    each report so a silent change cannot masquerade as the frozen rule.
    """

    sigma_low_px: float = 1.0
    sigma_high_px: float = 4.0
    window_alpha: float = 0.5
    search_radius_px: float = 12.0
    depth_search: int = 2
    geometry_tolerance_px: float = 3.0
    exclusion_radius_px: float = 3.0
    z_authenticate: float = 9.0
    z_contradict: float = 6.0
    min_unique_ratio: float = 1.5
    min_valid_fraction: float = 0.7
    min_band_snr: float = 1.5
    feature_clip_sigma: float = 4.0
    feature_dilate_px: int = 2
    max_masked_fraction: float = 0.35
    surrogates: int = 16
    surrogate_margin: float = 1.25
    flip_margin: float = 1.5
    z_refine: float = 25.0

    def validate(self) -> None:
        if not 0 < self.sigma_low_px < self.sigma_high_px:
            raise SeamFingerprintError("need 0 < sigma_low_px < sigma_high_px")
        if not 0 <= self.window_alpha <= 1:
            raise SeamFingerprintError("window_alpha must be in [0, 1]")
        if self.search_radius_px <= 0 or self.exclusion_radius_px <= 0:
            raise SeamFingerprintError("search/exclusion radii must be positive")
        if self.geometry_tolerance_px < 0 or self.geometry_tolerance_px > self.search_radius_px:
            raise SeamFingerprintError("geometry tolerance must lie within the search radius")
        if self.depth_search < 0:
            raise SeamFingerprintError("depth_search must be >= 0")
        if self.z_contradict <= 0 or self.z_contradict > self.z_authenticate:
            raise SeamFingerprintError("need 0 < z_contradict <= z_authenticate")
        if self.min_band_snr < 0:
            raise SeamFingerprintError("min_band_snr must be >= 0")
        if self.min_unique_ratio < 1 or self.surrogate_margin < 1 or self.flip_margin < 1:
            raise SeamFingerprintError("unique ratio, surrogate margin and flip margin must be >= 1")
        if self.z_refine < self.z_authenticate:
            raise SeamFingerprintError("z_refine must not be below z_authenticate")
        if not 0 < self.min_valid_fraction <= 1:
            raise SeamFingerprintError("min_valid_fraction must be in (0, 1]")
        if self.feature_clip_sigma < 0 or self.feature_dilate_px < 0:
            raise SeamFingerprintError("feature clip sigma and dilation must be >= 0")
        if not 0 < self.max_masked_fraction <= 1:
            raise SeamFingerprintError("max_masked_fraction must be in (0, 1]")
        if self.surrogates < 1:
            raise SeamFingerprintError("at least one phase-randomized surrogate is required")

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    def sha256(self) -> str:
        return _canonical_sha256(self.as_dict())


DEFAULT_CONFIG = SeamConfig()


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _lower_hex_sha(value: str, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise SeamFingerprintError(f"{name} must be lowercase 64-hex sha256")
    return value


def source_sha256() -> str:
    """Digest of this implementation, bound into every report."""
    return _sha256_file(Path(__file__).resolve())


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------


def _check_slab(slab: Any, name: str) -> np.ndarray:
    arr = np.asarray(slab)
    if arr.ndim != 3:
        raise SeamFingerprintError(f"{name} must have shape (depth, y, x)")
    if not np.issubdtype(arr.dtype, np.number) or np.issubdtype(arr.dtype, np.complexfloating):
        raise SeamFingerprintError(f"{name} must be a real numeric array")
    arr = arr.astype(np.float64)
    if not np.isfinite(arr).all():
        raise SeamFingerprintError(f"{name} must be finite; pass a valid mask instead of NaN")
    if min(arr.shape) < 1:
        raise SeamFingerprintError(f"{name} must be non-empty")
    return arr


def _check_mask(mask: Any, shape: tuple[int, int], name: str) -> np.ndarray:
    if mask is None:
        return np.ones(shape, dtype=bool)
    arr = np.asarray(mask)
    if arr.shape != shape:
        raise SeamFingerprintError(f"{name} must have shape {shape}")
    return arr.astype(bool)


# --------------------------------------------------------------------------
# spectral pipeline
# --------------------------------------------------------------------------


def _radius(h: int, w: int) -> np.ndarray:
    fy = np.fft.fftfreq(h)[:, None]
    fx = np.fft.fftfreq(w)[None, :]
    return np.hypot(fy, fx)


def band_transfer(h: int, w: int, cfg: SeamConfig) -> np.ndarray:
    """Normalized difference-of-Gaussians transfer function on the FFT grid."""
    r2 = _radius(h, w) ** 2
    lo = np.exp(-2.0 * math.pi**2 * cfg.sigma_low_px**2 * r2)
    hi = np.exp(-2.0 * math.pi**2 * cfg.sigma_high_px**2 * r2)
    transfer = lo - hi
    peak = float(transfer.max())
    if peak <= 0:
        raise SeamFingerprintError("band-pass transfer is degenerate for this patch size")
    return transfer / peak


def _window(h: int, w: int, alpha: float) -> np.ndarray:
    def tukey(n: int) -> np.ndarray:
        if alpha <= 0 or n < 2:
            return np.ones(n)
        x = np.linspace(0.0, 1.0, n)
        win = np.ones(n)
        edge = alpha / 2.0
        left = x < edge
        right = x > 1.0 - edge
        win[left] = 0.5 * (1 + np.cos(2 * math.pi / alpha * (x[left] - edge)))
        win[right] = 0.5 * (1 + np.cos(2 * math.pi / alpha * (x[right] - 1.0 + edge)))
        return win

    return np.outer(tukey(h), tukey(w))


def _dilate(mask: np.ndarray, radius: int) -> np.ndarray:
    if radius <= 0 or not mask.any():
        return mask
    yy, xx = np.mgrid[-radius : radius + 1, -radius : radius + 1]
    return binary_dilation(mask, structure=(np.hypot(yy, xx) <= radius))


def _inpaint(image: np.ndarray, keep: np.ndarray, sigma: float) -> np.ndarray:
    """Fill rejected pixels by normalized convolution of the kept neighbors."""
    weight = gaussian_filter(keep.astype(np.float64), sigma, mode="reflect")
    total = gaussian_filter(np.where(keep, image, 0.0), sigma, mode="reflect")
    fill = np.where(weight > 1e-3, total / np.maximum(weight, 1e-3), 0.0)
    return np.where(keep, image, fill)


def _prepare_slab(
    slab: np.ndarray, valid: np.ndarray, cfg: SeamConfig
) -> tuple[np.ndarray, np.ndarray, float]:
    """Return (windowed raw, windowed band-passed, masked-feature fraction).

    The raw copy only feeds the information gate. For the correlation, pixels
    that are invalid or amplitude outliers of the locally high-passed raw image
    are replaced by a smooth fill *before* band-passing, then excluded after it.
    A crack or fold shared by an adjacent winding is exactly such an outlier;
    removing it in the raw domain, where it is a sharp line, avoids the wide
    negative halo that the band-pass would otherwise spread around it. The
    evidence must therefore come from the background microtexture.
    """
    depth, h, w = slab.shape
    win = _window(h, w, cfg.window_alpha)
    transfer = band_transfer(h, w, cfg)
    raw = np.zeros_like(slab)
    band = np.zeros_like(slab)
    masked = 0
    total = 0
    n_valid = int(valid.sum())
    for z in range(depth):
        centered = slab[z] - (np.median(slab[z][valid]) if n_valid else 0.0)
        raw[z] = np.where(valid, centered, 0.0) * win
        keep = valid.copy()
        if cfg.feature_clip_sigma > 0 and n_valid:
            filled = _inpaint(centered, valid, cfg.sigma_high_px)
            high = filled - gaussian_filter(filled, cfg.sigma_high_px, mode="reflect")
            sigma = 1.4826 * float(np.median(np.abs(high[valid])))
            if sigma > _TINY:
                keep &= ~_dilate(np.abs(high) > cfg.feature_clip_sigma * sigma, cfg.feature_dilate_px)
        keep &= ~_dilate(~valid, cfg.feature_dilate_px)
        masked += int((valid & ~keep).sum())
        total += n_valid
        bp = np.fft.ifft2(np.fft.fft2(_inpaint(centered, keep, cfg.sigma_high_px)) * transfer).real
        band[z] = np.where(keep, bp, 0.0) * win
    return raw, band, (masked / total if total else 1.0)


def _spectra(windowed: np.ndarray) -> np.ndarray:
    return np.fft.fft2(windowed, axes=(-2, -1))


def band_snr(spectra: np.ndarray, cfg: SeamConfig) -> float:
    """Median over slices of in-band PSD over the top-frequency noise floor.

    White noise (including a featureless slab whose only content is voxel
    noise) scores about 1; texture living in the frozen band scores far higher.
    """
    depth, h, w = spectra.shape
    radius = _radius(h, w)
    transfer = band_transfer(h, w, cfg)
    in_band = transfer >= 0.5
    floor = radius >= 0.35
    if not in_band.any() or not floor.any():
        raise SeamFingerprintError("patch too small for the frozen band/noise annuli")
    power = np.abs(spectra) ** 2
    values = []
    for z in range(depth):
        noise = float(power[z][floor].mean())
        signal = float(power[z][in_band].mean())
        values.append(0.0 if noise <= _TINY else signal / noise)
    return float(np.median(values))


def _phat_planes(
    spec_a: np.ndarray,
    spec_b: np.ndarray,
    weight: np.ndarray,
    lags: Sequence[int],
) -> np.ndarray:
    """Band-weighted phase-correlation planes, one per depth lag.

    Convention: content at ``r`` in A appears at ``r + d`` in B; the peak sits
    at ``+d`` (and ``dz`` is the depth-index lag, ``b[z + dz] ~ a[z]``).
    """
    depth, h, w = spec_a.shape
    planes = []
    for dz in lags:
        acc = np.zeros((h, w), dtype=np.complex128)
        count = 0
        for z in range(depth):
            zb = z + dz
            if not 0 <= zb < depth:
                continue
            cross = np.conj(spec_a[z]) * spec_b[zb]
            mag = np.abs(spec_a[z]) * np.abs(spec_b[zb])
            acc += cross / (mag + _TINY * (float(mag.max()) + 1.0)) * weight
            count += 1
        if count == 0:
            raise SeamFingerprintError("depth lag has no overlapping slices")
        planes.append(np.fft.fftshift(np.fft.ifft2(acc / count).real))
    return np.stack(planes)


def _robust_z(planes: np.ndarray) -> np.ndarray:
    z = np.empty_like(planes)
    for i, plane in enumerate(planes):
        med = float(np.median(plane))
        sigma = 1.4826 * float(np.median(np.abs(plane - med)))
        z[i] = (plane - med) / max(sigma, _TINY)
    return z


def _search_mask(h: int, w: int, expected: np.ndarray, radius: float) -> np.ndarray:
    yy, xx = np.mgrid[0:h, 0:w]
    cy, cx = h // 2 + expected[0], w // 2 + expected[1]
    return np.hypot(yy - cy, xx - cx) <= radius


def _parabolic(minus: float, center: float, plus: float) -> float:
    denom = minus - 2.0 * center + plus
    if abs(denom) <= _TINY:
        return 0.0
    return float(np.clip(0.5 * (minus - plus) / denom, -0.5, 0.5))


def _find_peak(
    planes: np.ndarray,
    expected: np.ndarray,
    lags: Sequence[int],
    cfg: SeamConfig,
) -> dict[str, Any]:
    _, h, w = planes.shape
    zmap = _robust_z(planes)
    search = _search_mask(h, w, expected, cfg.search_radius_px)
    masked = np.where(search[None], zmap, -np.inf)
    li, yi, xi = np.unravel_index(int(np.argmax(masked)), masked.shape)
    z1 = float(masked[li, yi, xi])

    yy, xx = np.mgrid[0:h, 0:w]
    near = np.hypot(yy - yi, xx - xi) <= cfg.exclusion_radius_px
    rest = np.where((search & ~near)[None], zmap, -np.inf)
    z2 = float(rest.max())
    ratio = _RATIO_CAP if z2 <= 0 else min(z1 / z2, _RATIO_CAP)

    plane = planes[li]
    dy_sub = _parabolic(plane[yi - 1, xi], plane[yi, xi], plane[yi + 1, xi])
    dx_sub = _parabolic(plane[yi, xi - 1], plane[yi, xi], plane[yi, xi + 1])
    shift = np.array([yi - h // 2 + dy_sub, xi - w // 2 + dx_sub])
    med_abs = float(np.median(np.abs(plane)))
    return {
        "z": z1,
        "second_peak_z": max(z2, 0.0),
        "unique_ratio": float(ratio),
        "shift_yx_px": [float(shift[0]), float(shift[1])],
        "depth_lag": int(lags[li]),
        "peak_value": float(plane[yi, xi]),
        "peak_to_median_abs": float(plane[yi, xi] / med_abs) if med_abs > _TINY else _RATIO_CAP,
    }


def _depth_agreement(
    spec_a: np.ndarray,
    spec_b: np.ndarray,
    weight: np.ndarray,
    peak: dict[str, Any],
) -> float | None:
    """Fraction of slice pairs whose own best cell agrees with the pooled peak."""
    depth, h, w = spec_a.shape
    dz = peak["depth_lag"]
    pairs = [(z, z + dz) for z in range(depth) if 0 <= z + dz < depth]
    if len(pairs) < 2:
        return None
    target = np.array(peak["shift_yx_px"])
    agree = 0
    for za, zb in pairs:
        plane = _phat_planes(spec_a[za : za + 1], spec_b[zb : zb + 1], weight, [0])[0]
        yi, xi = np.unravel_index(int(np.argmax(plane)), plane.shape)
        own = np.array([yi - h // 2, xi - w // 2], dtype=float)
        agree += int(np.hypot(*(own - target)) <= 1.5)
    return agree / len(pairs)


def _phase_randomized(windowed: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """3-D phase-randomized surrogate: same power spectrum, destroyed identity."""
    axes = (0, 1, 2)
    spec = np.fft.rfftn(windowed, axes=axes)
    phase = rng.uniform(0.0, 2.0 * math.pi, size=spec.shape)
    return np.fft.irfftn(np.abs(spec) * np.exp(1j * phase), s=windowed.shape, axes=axes)


def _seed_from(arrays: Sequence[np.ndarray], cfg: SeamConfig) -> int:
    h = hashlib.sha256(cfg.sha256().encode("ascii"))
    for arr in arrays:
        h.update(np.ascontiguousarray(arr, dtype="<f8").tobytes())
    return int.from_bytes(h.digest()[:8], "big")


# --------------------------------------------------------------------------
# authentication of one tile pair
# --------------------------------------------------------------------------


def authenticate_pair(
    slab_a: np.ndarray,
    slab_b: np.ndarray,
    *,
    valid_a: np.ndarray | None = None,
    valid_b: np.ndarray | None = None,
    expected_shift_yx: Sequence[float] = (0.0, 0.0),
    config: SeamConfig = DEFAULT_CONFIG,
) -> dict[str, Any]:
    """Authenticate one claimed-overlap tile pair. Never raises on weak data."""
    config.validate()
    a = _check_slab(slab_a, "slab_a")
    b = _check_slab(slab_b, "slab_b")
    if a.shape != b.shape:
        raise SeamFingerprintError("slab_a and slab_b must share one (depth, y, x) shape")
    depth, h, w = a.shape
    expected = np.asarray(expected_shift_yx, dtype=np.float64)
    if expected.shape != (2,) or not np.isfinite(expected).all():
        raise SeamFingerprintError("expected_shift_yx must be two finite numbers")
    if min(h, w) < 4.0 * config.search_radius_px:
        raise SeamFingerprintError(
            "tile must be at least 4x the search radius so that a maximal shift "
            "still leaves >= 75% overlap"
        )
    reach = math.ceil(config.search_radius_px) + 1
    for size, offset, axis in ((h, expected[0], "y"), (w, expected[1], "x")):
        lo = size // 2 + math.floor(offset) - reach
        hi = size // 2 + math.ceil(offset) + reach
        if lo < 0 or hi > size - 1:
            raise SeamFingerprintError(
                f"tile too small along {axis}: the search disk around the expected "
                "shift must fit inside the tile"
            )
    va = _check_mask(valid_a, (h, w), "valid_a")
    vb = _check_mask(valid_b, (h, w), "valid_b")

    reasons: list[str] = []
    valid_fraction = [float(va.mean()), float(vb.mean())]
    if min(valid_fraction) < config.min_valid_fraction:
        reasons.append("insufficient-valid-fraction")

    both = va & vb
    if both.any() and np.array_equal(a[:, both], b[:, both]):
        reasons.append("identical-pixel-arrays")

    raw_a, band_a, masked_a = _prepare_slab(a, va, config)
    raw_b, band_b, masked_b = _prepare_slab(b, vb, config)
    snr = [band_snr(_spectra(raw_a), config), band_snr(_spectra(raw_b), config)]
    if min(snr) < config.min_band_snr:
        reasons.append("insufficient-band-information")
    masked_fraction = [float(masked_a), float(masked_b)]
    if max(masked_fraction) > config.max_masked_fraction:
        reasons.append("insufficient-unmasked-microtexture")
    spec_a = _spectra(band_a)
    spec_b = _spectra(band_b)

    transfer = band_transfer(h, w, config)
    lag_limit = min(config.depth_search, depth - 1)
    lags = [dz for dz in range(-lag_limit, lag_limit + 1) if depth - abs(dz) >= max(1, depth // 2)]
    if not lags:
        raise SeamFingerprintError("no depth lag keeps at least half of the slab overlapping")

    peak = _find_peak(_phat_planes(spec_a, spec_b, transfer, lags), expected, lags, config)
    shift = np.array(peak["shift_yx_px"])
    residual = shift - expected
    residual_norm = float(np.hypot(*residual))
    agreement = _depth_agreement(spec_a, spec_b, transfer, peak)

    rng = np.random.default_rng(_seed_from([a, b, va, vb, expected], config))
    sur_z = []
    for _ in range(config.surrogates):
        sur_spec = _spectra(_phase_randomized(band_b, rng))
        sur_peak = _find_peak(_phat_planes(spec_a, sur_spec, transfer, lags), expected, lags, config)
        sur_z.append(sur_peak["z"])
    sur_max = float(max(sur_z))

    flipped_z: float | None = None
    if depth >= 3 and not reasons:
        spec_flip = _spectra(band_b[::-1].copy())
        flipped = _find_peak(_phat_planes(spec_a, spec_flip, transfer, lags), expected, lags, config)
        flipped_z = flipped["z"]

    verdict, why = _decide(
        peak, residual_norm, sur_max, flipped_z, reasons, config, max(lags)
    )
    return {
        "verdict": verdict,
        "reasons": why,
        "peak": {
            **peak,
            "residual_yx_px": [float(residual[0]), float(residual[1])],
            "residual_px": residual_norm,
            "depth_agreement": agreement,
        },
        "information": {
            "valid_fraction": valid_fraction,
            "band_snr": [float(v) for v in snr],
            "masked_feature_fraction": masked_fraction,
        },
        "surrogates": {
            "count": int(config.surrogates),
            "z_max": sur_max,
            "z_median": float(np.median(sur_z)),
        },
        "flipped_normal_z": flipped_z,
        "refinement": {
            "usable": bool(verdict == AUTHENTICATED and peak["z"] >= config.z_refine),
            "residual_yx_px": [float(residual[0]), float(residual[1])],
            "depth_lag": int(peak["depth_lag"]),
            "basis": f"AUTHENTICATED and peak z >= {config.z_refine:g}",
        },
        "expected_shift_yx_px": [float(expected[0]), float(expected[1])],
        "shape": [int(depth), int(h), int(w)],
    }


def _decide(
    peak: dict[str, Any],
    residual_norm: float,
    surrogate_max_z: float,
    flipped_z: float | None,
    info_reasons: list[str],
    cfg: SeamConfig,
    lag_limit: int,
) -> tuple[str, list[str]]:
    if info_reasons:
        return UNKNOWN, list(info_reasons)
    z = peak["z"]
    if (
        flipped_z is not None
        and flipped_z >= cfg.z_authenticate
        and flipped_z >= cfg.flip_margin * z
    ):
        return CONTRADICTED, ["normal-orientation-flipped"]
    if z < cfg.z_contradict:
        return CONTRADICTED, ["no-correspondence-within-search"]
    if z < cfg.z_authenticate:
        return UNKNOWN, ["peak-below-authentication-floor"]
    if peak["unique_ratio"] < cfg.min_unique_ratio:
        return UNKNOWN, ["ambiguous-peak"]
    if z < cfg.surrogate_margin * surrogate_max_z:
        return UNKNOWN, ["not-separated-from-phase-randomized-surrogates"]
    if lag_limit > 0 and abs(peak["depth_lag"]) >= lag_limit:
        return UNKNOWN, ["depth-lag-at-search-boundary"]
    if residual_norm > cfg.geometry_tolerance_px:
        return CONTRADICTED, ["registration-offset-exceeds-tolerance"]
    return AUTHENTICATED, []


# --------------------------------------------------------------------------
# deterministic synthetic controls
# --------------------------------------------------------------------------
#
# These are software controls, not scientific evidence about carbonized
# papyrus. Real-CT claims need the adjacent-winding benchmark in
# docs/papyrus-seam-fingerprint.md.

FIELD_SHAPE = (9, 160, 160)
TILE = 64
SLAB_DEPTH = 5
_Z0 = 2
_Y0 = _X0 = 48
DEV_SEED_BASE = 100_000  # consumed during development; never a held-out number
DEFAULT_SEED_BASE = 700_000  # held-out: first used after the constants were frozen


def synthetic_sheet(seed: int, shape: tuple[int, int, int] = FIELD_SHAPE) -> np.ndarray:
    """Periodic synthetic physical sheet: two crossed fiber plies plus voids."""
    rng = np.random.default_rng(int(seed))
    depth, h, w = shape
    ply1 = gaussian_filter(rng.standard_normal(shape), (1.2, 0.8, 5.0), mode="wrap")
    ply2 = gaussian_filter(rng.standard_normal(shape), (1.2, 5.0, 0.8), mode="wrap")
    # cross-ply depth structure: the horizontal ply dominates one face, the
    # vertical ply the other, so reversing the normal changes the content
    ramp = np.linspace(1.0, 0.0, depth)[:, None, None]
    ply1 = ply1 * (0.25 + 0.75 * ramp)
    ply2 = ply2 * (0.25 + 0.75 * (1.0 - ramp))
    voids = np.zeros(shape)
    for _ in range(40):
        voids[rng.integers(0, depth), rng.integers(0, h), rng.integers(0, w)] = 1.0
    voids = gaussian_filter(voids, (1.0, 1.6, 1.6), mode="wrap")
    return ply1 / ply1.std() + 0.6 * ply2 / ply2.std() - 2.5 * voids / voids.max()


def _fine_only(field: np.ndarray, coarse_sigma: float = 6.0) -> np.ndarray:
    return field - gaussian_filter(field, (0, coarse_sigma, coarse_sigma), mode="wrap")


def _translate(field: np.ndarray, dy: float, dx: float, order: int = 0) -> np.ndarray:
    """Translate every slice of a periodic field; order 0 is an exact Fourier shift."""
    out = np.empty_like(field)
    for z in range(field.shape[0]):
        if order == 0:
            out[z] = np.fft.ifft2(
                np.fft.fft2(field[z]) * np.exp(
                    -2j * math.pi * (
                        np.fft.fftfreq(field.shape[1])[:, None] * dy
                        + np.fft.fftfreq(field.shape[2])[None, :] * dx
                    )
                )
            ).real
        else:
            out[z] = nd_shift(field[z], (dy, dx), order=order, mode="grid-wrap")
    return out


def _slab(field: np.ndarray, z0: int = _Z0) -> np.ndarray:
    return field[z0 : z0 + SLAB_DEPTH, _Y0 : _Y0 + TILE, _X0 : _X0 + TILE].copy()


def _crack_field(amplitude: float = 8.0, angle_deg: float = 20.0, width: float = 1.0) -> np.ndarray:
    """A through-going straight crack across the middle of the sampled tile."""
    depth, h, w = FIELD_SHAPE
    yy, xx = np.mgrid[0:h, 0:w]
    cy, cx = _Y0 + TILE / 2, _X0 + TILE / 2
    th = math.radians(angle_deg)
    dist = (xx - cx) * math.sin(th) - (yy - cy) * math.cos(th)
    return np.broadcast_to(amplitude * np.exp(-0.5 * (dist / width) ** 2), FIELD_SHAPE).copy()


def _block_shuffle(slab: np.ndarray, rng: np.random.Generator, block: int = 8) -> np.ndarray:
    cells = [(i, j) for i in range(0, TILE, block) for j in range(0, TILE, block)]
    order = rng.permutation(len(cells))
    out = slab.copy()
    for target, source in zip(cells, (cells[k] for k in order)):
        out[:, target[0] : target[0] + block, target[1] : target[1] + block] = slab[
            :, source[0] : source[0] + block, source[1] : source[1] + block
        ]
    return out


def _rotated(field: np.ndarray, degrees: float) -> np.ndarray:
    out = np.empty_like(field)
    for z in range(field.shape[0]):
        out[z] = nd_rotate(field[z], degrees, reshape=False, order=1, mode="grid-wrap")
    return out


@dataclasses.dataclass(frozen=True)
class ControlCase:
    name: str
    # genuine: same sheet, sound claim; misregistered: same sheet, wrong claimed
    # geometry; impostor: a different sheet; falsification: identity destroyed;
    # unknown-required: too little information to say anything
    kind: str
    description: str
    allowed: tuple[str, ...]
    build: Any  # (seed, rng) -> (slab_a, slab_b, extra), extra may hold truth


def _case_genuine(noise: float = 0.0, order: int = 0, dz: int = 0, offset: float = 2.0):
    def build(seed: int, rng: np.random.Generator):
        field = synthetic_sheet(seed)
        dy, dx = rng.uniform(-offset, offset, 2)
        a = _slab(field)
        b = _slab(_translate(field, dy, dx, order), _Z0 - dz)
        if noise:
            a = a + noise * rng.standard_normal(a.shape)
            b = b + noise * rng.standard_normal(b.shape)
        return a, b, {"truth_shift": (float(dy), float(dx)), "truth_lag": dz}

    return build


def _case_fused(seed: int, rng: np.random.Generator):
    s1, s2a, s2b = synthetic_sheet(seed), synthetic_sheet(seed + 1), synthetic_sheet(seed + 2)
    dy, dx = rng.uniform(-2, 2, 2)
    a = _slab(s1 + 0.7 * s2a)
    b = _slab(_translate(s1, dy, dx) + 0.7 * s2b)
    return a, b, {"truth_shift": (float(dy), float(dx)), "truth_lag": 0}


def _case_shared_crack(genuine: bool):
    def build(seed: int, rng: np.random.Generator):
        crack = _crack_field()
        dy, dx = rng.uniform(-2, 2, 2)
        if genuine:
            # the crack belongs to the sheet, so it translates with it
            field = synthetic_sheet(seed) - crack
            return (
                _slab(field),
                _slab(_translate(field, dy, dx)),
                {"truth_shift": (float(dy), float(dx)), "truth_lag": 0},
            )
        # impostor: a different sheet cut by the crack at the same place (worst case)
        return (
            _slab(synthetic_sheet(seed) - crack),
            _slab(synthetic_sheet(seed + 1) - crack),
            {},
        )

    return build


def _case_wrong_sheet(seed: int, rng: np.random.Generator):
    return _slab(synthetic_sheet(seed)), _slab(synthetic_sheet(seed + 1)), {}


def _case_adjacent_shared_coarse(seed: int, rng: np.random.Generator):
    f1 = synthetic_sheet(seed)
    coarse = f1 - _fine_only(f1)
    f2 = coarse + _fine_only(synthetic_sheet(seed + 1))
    return _slab(f1), _slab(f2), {}


def _case_shared_fold(seed: int, rng: np.random.Generator):
    yy, xx = np.mgrid[0:TILE, 0:TILE]
    fold = np.broadcast_to(6.0 * np.tanh((xx - TILE / 2) / 6.0), (SLAB_DEPTH, TILE, TILE))
    return _slab(synthetic_sheet(seed)) + fold, _slab(synthetic_sheet(seed + 1)) + fold, {}


def _case_destroyed(kind: str):
    def build(seed: int, rng: np.random.Generator):
        field = synthetic_sheet(seed)
        dy, dx = rng.uniform(-2, 2, 2)
        a = _slab(field)
        b = _slab(_translate(field, dy, dx))
        if kind == "phase":
            b = _phase_randomized(b, rng)
        else:
            b = _block_shuffle(b, rng)
        return a, b, {}

    return build


def _case_flipped(seed: int, rng: np.random.Generator):
    field = synthetic_sheet(seed)
    return _slab(field), _slab(field)[::-1].copy(), {}


def _case_far_offset(shift: float):
    def build(seed: int, rng: np.random.Generator):
        field = synthetic_sheet(seed)
        return _slab(field), _slab(_translate(field, shift, 0.6 * shift)), {}

    return build


def _case_depth_misregistered(seed: int, rng: np.random.Generator):
    field = synthetic_sheet(seed)
    return _slab(field, 1), _slab(field, 4), {}


def _case_blank(seed: int, rng: np.random.Generator):
    smooth = gaussian_filter(rng.standard_normal(FIELD_SHAPE), (2, 12, 12), mode="wrap") * 5
    a, b = _slab(smooth), _slab(smooth)
    return a + 0.3 * rng.standard_normal(a.shape), b + 0.3 * rng.standard_normal(b.shape), {}


def _case_blank_shared_noise(seed: int, rng: np.random.Generator):
    # one noise realization read twice: the same-volume arm, where featureless
    # papyrus still correlates perfectly through shared voxel noise
    smooth = gaussian_filter(rng.standard_normal(FIELD_SHAPE), (2, 12, 12), mode="wrap") * 5
    noisy = smooth + 0.3 * rng.standard_normal(FIELD_SHAPE)
    dy, dx = rng.uniform(-2, 2, 2)
    return _slab(noisy), _slab(_translate(noisy, dy, dx)), {}


def _case_pure_noise(seed: int, rng: np.random.Generator):
    return rng.standard_normal((SLAB_DEPTH, TILE, TILE)), rng.standard_normal((SLAB_DEPTH, TILE, TILE)), {}


def _case_identical(seed: int, rng: np.random.Generator):
    a = _slab(synthetic_sheet(seed))
    return a, a.copy(), {}


def _case_degraded(seed: int, rng: np.random.Generator):
    field = synthetic_sheet(seed)
    blurred = gaussian_filter(field, (0, 3.0, 3.0), mode="wrap")
    dy, dx = rng.uniform(-2, 2, 2)
    a = _slab(blurred) + 0.5 * rng.standard_normal((SLAB_DEPTH, TILE, TILE))
    b = _slab(_translate(blurred, dy, dx)) + 0.5 * rng.standard_normal((SLAB_DEPTH, TILE, TILE))
    return a, b, {"truth_shift": (float(dy), float(dx)), "truth_lag": 0}


_NOT_CONTRADICTED = (AUTHENTICATED, UNKNOWN)
_NOT_AUTHENTICATED = (CONTRADICTED, UNKNOWN)

CONTROL_CASES: tuple[ControlCase, ...] = (
    ControlCase("genuine_small_offset", "genuine",
                "same sheet, independent exact sub-pixel offset up to 2 px, no noise",
                (AUTHENTICATED,), _case_genuine()),
    ControlCase("genuine_independent_noise", "genuine",
                "same sheet, independent additive noise per patch (rescan analogue)",
                (AUTHENTICATED,), _case_genuine(noise=1.0)),
    ControlCase("genuine_rerendered", "genuine",
                "patch B independently resampled with bilinear interpolation",
                (AUTHENTICATED,), _case_genuine(noise=0.5, order=1)),
    ControlCase("genuine_depth_offset", "genuine",
                "patch B sampled one slice deeper along the normal",
                (AUTHENTICATED,), _case_genuine(dz=1)),
    ControlCase("genuine_fused_sheet", "genuine",
                "same sheet plus a different adjacent sheet leaking into each slab",
                _NOT_CONTRADICTED, _case_fused),
    ControlCase("genuine_shared_crack", "genuine",
                "same sheet carrying a through-going crack",
                _NOT_CONTRADICTED, _case_shared_crack(True)),
    ControlCase("genuine_degraded", "genuine",
                "same sheet with severe in-plane blur and heavy noise (compressed/low-resolution)",
                _NOT_CONTRADICTED, _case_degraded),
    ControlCase("genuine_depth_misregistered", "genuine",
                "same sheet sampled three slices deeper: the lag is beyond the search and must not be asserted",
                (UNKNOWN,), _case_depth_misregistered),
    ControlCase("genuine_registration_offset", "misregistered",
                "same sheet but claimed registration is 8 px off (outside tolerance, inside search)",
                (CONTRADICTED,), _case_far_offset(8.0)),
    ControlCase("wrong_sheet_independent", "impostor",
                "distant papyrus: independent sheet with identical statistics",
                _NOT_AUTHENTICATED, _case_wrong_sheet),
    ControlCase("adjacent_shared_coarse", "impostor",
                "adjacent winding: same coarse structure/orientation, independent microtexture",
                _NOT_AUTHENTICATED, _case_adjacent_shared_coarse),
    ControlCase("shared_crack_impostor", "impostor",
                "adjacent winding cut by the same through-going crack, independent microtexture",
                _NOT_AUTHENTICATED, _case_shared_crack(False)),
    ControlCase("shared_fold_impostor", "impostor",
                "adjacent winding sharing the same fold step, independent microtexture",
                _NOT_AUTHENTICATED, _case_shared_fold),
    ControlCase("offset_beyond_search", "misregistered",
                "same sheet displaced 20 px, beyond the 12 px search radius",
                _NOT_AUTHENTICATED, _case_far_offset(20.0)),
    ControlCase("flipped_normal", "misregistered",
                "same sheet with the normal (depth) axis reversed",
                (CONTRADICTED,), _case_flipped),
    ControlCase("phase_randomized", "falsification",
                "genuine pair with patch B phase-randomized: statistics kept, identity destroyed",
                _NOT_AUTHENTICATED, _case_destroyed("phase")),
    ControlCase("block_shuffled", "falsification",
                "genuine pair with patch B block-shuffled (8 px): local texture kept, layout destroyed",
                _NOT_AUTHENTICATED, _case_destroyed("block")),
    ControlCase("blank_smooth", "unknown-required",
                "smooth papyrus plus shared voxel noise",
                (UNKNOWN,), _case_blank),
    ControlCase("blank_shared_voxel_noise", "unknown-required",
                "smooth papyrus whose two patches read the same voxel-noise realization",
                (UNKNOWN,), _case_blank_shared_noise),
    ControlCase("pure_noise", "unknown-required",
                "independent noise only",
                (UNKNOWN,), _case_pure_noise),
    ControlCase("identical_pixels", "unknown-required",
                "the same pixel array supplied twice (shared preprocessing hazard)",
                (UNKNOWN,), _case_identical),
)


def _summary(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    arr = np.asarray(values, dtype=np.float64)
    return {
        "min": float(arr.min()),
        "median": float(np.median(arr)),
        "max": float(arr.max()),
    }


def _run_case(
    case: ControlCase, seeds: Sequence[int], config: SeamConfig
) -> dict[str, Any]:
    counts = {v: 0 for v in VERDICTS}
    reasons: dict[str, int] = {}
    zs: list[float] = []
    errors: list[float] = []
    lag_ok: list[bool] = []
    outside = 0
    for seed in seeds:
        rng = np.random.default_rng(seed + 7_919)
        a, b, extra = case.build(seed, rng)
        result = authenticate_pair(a, b, config=config)
        counts[result["verdict"]] += 1
        outside += result["verdict"] not in case.allowed
        for reason in result["reasons"]:
            reasons[reason] = reasons.get(reason, 0) + 1
        zs.append(result["peak"]["z"])
        if "truth_shift" in extra and result["verdict"] == AUTHENTICATED:
            truth = np.asarray(extra["truth_shift"])
            got = np.asarray(result["peak"]["shift_yx_px"])
            errors.append(float(np.hypot(*(got - truth))))
            lag_ok.append(result["peak"]["depth_lag"] == extra["truth_lag"])
    return {
        "name": case.name,
        "kind": case.kind,
        "description": case.description,
        "allowed_verdicts": list(case.allowed),
        "n": len(list(seeds)),
        "verdict_counts": counts,
        "reason_counts": dict(sorted(reasons.items())),
        "peak_z": _summary(zs),
        "shift_error_px_authenticated_runs": _summary(errors),
        "depth_lag_recovered_fraction": (float(np.mean(lag_ok)) if lag_ok else None),
        "runs_outside_allowed": int(outside),
        "pass": outside == 0,
    }


def _sweep(
    label: str,
    levels: Sequence[float],
    seeds: Sequence[int],
    config: SeamConfig,
    make: Any,
) -> list[dict[str, Any]]:
    rows = []
    for level in levels:
        counts = {v: 0 for v in VERDICTS}
        zs = []
        for seed in seeds:
            rng = np.random.default_rng(seed + 104_729)
            a, b = make(level, seed, rng)
            result = authenticate_pair(a, b, config=config)
            counts[result["verdict"]] += 1
            zs.append(result["peak"]["z"])
        rows.append({label: float(level), "n": len(list(seeds)),
                     "verdict_counts": counts, "peak_z": _summary(zs)})
    return rows


def _noise_pair(level: float, seed: int, rng: np.random.Generator):
    field = synthetic_sheet(seed)
    a, b = _slab(field), _slab(_translate(field, 1.0, -1.5))
    return a + level * rng.standard_normal(a.shape), b + level * rng.standard_normal(b.shape)


def _rotation_pair(level: float, seed: int, rng: np.random.Generator):
    field = synthetic_sheet(seed)
    a = _slab(field) + 0.5 * rng.standard_normal((SLAB_DEPTH, TILE, TILE))
    b = _slab(_rotated(_translate(field, 1.0, -1.5), level)) + 0.5 * rng.standard_normal(a.shape)
    return a, b


def run_controls(
    *,
    config: SeamConfig = DEFAULT_CONFIG,
    seed_base: int = DEFAULT_SEED_BASE,
    n: int = 20,
    sweep_n: int = 12,
) -> dict[str, Any]:
    """Run the full synthetic control suite and the pre-stated gate."""
    config.validate()
    if n < 1 or sweep_n < 1:
        raise SeamFingerprintError("n and sweep_n must be positive")
    seeds = [seed_base + 3 * i for i in range(n)]
    sweep_seeds = [seed_base + 50_000 + 3 * i for i in range(sweep_n)]
    cases = [_run_case(case, seeds, config) for case in CONTROL_CASES]
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for row in cases:
        by_kind.setdefault(row["kind"], []).append(row)
    by_name = {row["name"]: row for row in cases}

    def median_z(name: str) -> float:
        return by_name[name]["peak_z"]["median"]

    genuine_ref = median_z("genuine_small_offset")
    collapse = {
        name: float(median_z(name) / genuine_ref) if genuine_ref > 0 else None
        for name in ("phase_randomized", "block_shuffled")
    }
    shift_errors = [
        by_name[name]["shift_error_px_authenticated_runs"]["max"]
        for name in ("genuine_small_offset", "genuine_independent_noise",
                     "genuine_rerendered", "genuine_depth_offset")
        if by_name[name]["shift_error_px_authenticated_runs"]
    ]
    impostor_z = [
        r["peak_z"]["max"] for r in by_kind["impostor"] + by_kind["falsification"]
    ]
    gate = {
        "max_impostor_or_destroyed_peak_z": float(max(impostor_z)),
        "z_authenticate": float(config.z_authenticate),
        "genuine_controls_behave": all(r["pass"] for r in by_kind["genuine"]),
        "impostors_never_authenticated": all(
            r["verdict_counts"][AUTHENTICATED] == 0 for r in by_kind["impostor"]
        ),
        "misregistered_never_authenticated": all(
            r["verdict_counts"][AUTHENTICATED] == 0 for r in by_kind["misregistered"]
        ),
        "falsification_collapses": all(
            r["verdict_counts"][AUTHENTICATED] == 0 for r in by_kind["falsification"]
        ) and all(v is not None and v < 0.5 for v in collapse.values()),
        "low_information_is_unknown": all(r["pass"] for r in by_kind["unknown-required"]),
        "depth_lag_recovered": all(
            by_name[name]["depth_lag_recovered_fraction"] == 1.0
            for name in ("genuine_small_offset", "genuine_depth_offset")
        ),
        "max_shift_error_px": float(max(shift_errors)) if shift_errors else None,
        "shift_error_within_half_pixel": bool(shift_errors and max(shift_errors) <= 0.5),
    }
    gate["status"] = "pass" if all(
        v for k, v in gate.items() if isinstance(v, bool)
    ) else "fail"
    return {
        "cases": cases,
        "falsification_z_collapse_ratio": collapse,
        "sweeps": {
            "noise_sigma_independent_per_patch": _sweep(
                "noise_sigma", (0.5, 1.0, 2.0, 3.0, 4.0, 6.0, 8.0), sweep_seeds, config, _noise_pair
            ),
            "inplane_rotation_degrees": _sweep(
                "rotation_degrees", (0.0, 0.5, 1.0, 2.0, 4.0), sweep_seeds, config, _rotation_pair
            ),
        },
        "gate": gate,
        "seed_base": int(seed_base),
        "n_per_case": int(n),
        "sweep_n": int(sweep_n),
    }


# --------------------------------------------------------------------------
# reports and CLI
# --------------------------------------------------------------------------

CLASSIFICATION = "EXPERIMENT FURTHER"

_PAIR_INTERPRETATION = {
    "shared-voxels": (
        "Both slabs were declared to come from one CT volume, so they share "
        "voxel noise. AUTHENTICATED therefore certifies that the two patches "
        "read the same voxel neighborhood at the recovered transform; it is not "
        "evidence of an independent physical fingerprint. That needs the "
        "independent-scan arm."
    ),
    "independent-scans": (
        "The slabs were declared to come from different CT volumes. Noise "
        "independence between those volumes is declared, not verified here. "
        "Only this arm can support a physical-identity reading, and only after "
        "real-CT adjacent-winding controls pass."
    ),
}


def build_pair_report(
    *,
    result: dict[str, Any],
    config: SeamConfig,
    input_path: str | Path,
    input_sha256: str,
    volume_root_a: str,
    volume_root_b: str,
    surface_a_sha256: str,
    surface_b_sha256: str,
    sampling_manifest_path: str | Path,
    sampling_manifest_sha256: str,
    has_xyz: bool,
) -> dict[str, Any]:
    for name, value in (("volume_root_a", volume_root_a), ("volume_root_b", volume_root_b)):
        if not isinstance(value, str) or not value.strip():
            raise SeamFingerprintError(f"{name} must be non-empty")
    _lower_hex_sha(input_sha256, "input_sha256")
    _lower_hex_sha(surface_a_sha256, "surface_a_sha256")
    _lower_hex_sha(surface_b_sha256, "surface_b_sha256")
    _lower_hex_sha(sampling_manifest_sha256, "sampling_manifest_sha256")
    arm = "shared-voxels" if volume_root_a == volume_root_b else "independent-scans"
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "method": METHOD,
        "classification": CLASSIFICATION,
        "purpose": (
            "ink-blind authentication of a claimed patch overlap from CT "
            "microtexture; never a readability claim"
        ),
        "verdict": result["verdict"],
        "noise_arm": arm,
        "interpretation": _PAIR_INTERPRETATION[arm],
        "config": config.as_dict(),
        "config_sha256": config.sha256(),
        "config_status": "PROVISIONAL: set on synthetic data only",
        "source_sha256": source_sha256(),
        "volume_root_a": volume_root_a,
        "volume_root_b": volume_root_b,
        "surface_a_geometry_sha256": surface_a_sha256,
        "surface_b_geometry_sha256": surface_b_sha256,
        "sampling_manifest": {
            "path": str(sampling_manifest_path),
            "sha256": sampling_manifest_sha256,
        },
        "input": {
            "path": str(input_path),
            "sha256": input_sha256,
            "format": "npz",
            "required_arrays": ["slab_a(depth,y,x)", "slab_b(depth,y,x)"],
            "optional_arrays": [
                "valid_a(y,x)", "valid_b(y,x)", "expected_shift_yx(2)",
                "xyz_a(y,x,3)", "xyz_b(y,x,3)",
            ],
            "has_xyz": bool(has_xyz),
        },
        "result": result,
        "numpy_version": np.__version__,
    }


def build_controls_report(
    *, suite: dict[str, Any], config: SeamConfig, ablation: str | None
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "method": METHOD,
        "classification": CLASSIFICATION,
        "synthetic": True,
        "ablation": ablation,
        "purpose": (
            "software controls for the seam fingerprint authenticator; "
            "synthetic data only"
        ),
        "interpretation": (
            "A pass shows the implementation honors its stated verdict rules on "
            "synthetic sheets, including the falsification and low-information "
            "controls. It says nothing about whether carbonized papyrus at "
            "scan resolution carries a recoverable fingerprint; that requires "
            "the real-CT adjacent-winding benchmark."
        ),
        "config": config.as_dict(),
        "config_sha256": config.sha256(),
        "source_sha256": source_sha256(),
        "numpy_version": np.__version__,
        **suite,
    }


def _load_pair_npz(path: Path) -> dict[str, np.ndarray | None]:
    try:
        with np.load(path, allow_pickle=False) as data:
            files = set(data.files)
            for key in ("slab_a", "slab_b"):
                if key not in files:
                    raise SeamFingerprintError(f"input NPZ must contain array '{key}'")
            return {
                key: (np.asarray(data[key]) if key in files else None)
                for key in (
                    "slab_a", "slab_b", "valid_a", "valid_b",
                    "expected_shift_yx", "xyz_a", "xyz_b",
                )
            }
    except (OSError, ValueError) as exc:
        if isinstance(exc, SeamFingerprintError):
            raise
        raise SeamFingerprintError(f"cannot read input NPZ: {exc}") from exc


def _write_new(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(report, indent=2, sort_keys=True) + "\n")


ABLATIONS: dict[str, dict[str, float]] = {
    "feature-gate": {"feature_clip_sigma": 0.0},
    "information-gate": {"min_band_snr": 0.0},
}

EXIT_AUTHENTICATED = 0
EXIT_UNKNOWN = 1
EXIT_ERROR = 2
EXIT_CONTRADICTED = 3


def _cmd_pair(args: argparse.Namespace) -> int:
    source = Path(args.input)
    manifest = Path(args.sampling_manifest)
    output = Path(args.out)
    if output.exists():
        print(f"{TOOL}: refusing to overwrite existing output: {output}", file=sys.stderr)
        return EXIT_ERROR
    try:
        arrays = _load_pair_npz(source)
        expected = arrays["expected_shift_yx"]
        result = authenticate_pair(
            arrays["slab_a"],
            arrays["slab_b"],
            valid_a=arrays["valid_a"],
            valid_b=arrays["valid_b"],
            expected_shift_yx=(0.0, 0.0) if expected is None else expected,
        )
        report = build_pair_report(
            result=result,
            config=DEFAULT_CONFIG,
            input_path=source,
            input_sha256=_sha256_file(source),
            volume_root_a=args.volume_root,
            volume_root_b=args.volume_root_b or args.volume_root,
            surface_a_sha256=args.surface_a_sha256,
            surface_b_sha256=args.surface_b_sha256,
            sampling_manifest_path=manifest,
            sampling_manifest_sha256=_sha256_file(manifest),
            has_xyz=arrays["xyz_a"] is not None and arrays["xyz_b"] is not None,
        )
        _write_new(output, report)
    except (OSError, SeamFingerprintError) as exc:
        print(f"{TOOL}: FAIL: {exc}", file=sys.stderr)
        return EXIT_ERROR
    peak = result["peak"]
    print(
        f"{TOOL}: {result['verdict']}: z={peak['z']:.1f} "
        f"shift=({peak['shift_yx_px'][0]:+.2f},{peak['shift_yx_px'][1]:+.2f}) px "
        f"depth_lag={peak['depth_lag']:+d} reasons={result['reasons'] or '-'} "
        f"arm={report['noise_arm']}"
    )
    return {
        AUTHENTICATED: EXIT_AUTHENTICATED,
        UNKNOWN: EXIT_UNKNOWN,
        CONTRADICTED: EXIT_CONTRADICTED,
    }[result["verdict"]]


def _cmd_controls(args: argparse.Namespace) -> int:
    output = Path(args.out)
    if output.exists():
        print(f"{TOOL}: refusing to overwrite existing output: {output}", file=sys.stderr)
        return EXIT_ERROR
    config = DEFAULT_CONFIG
    ablation = None
    if args.ablate:
        config = dataclasses.replace(DEFAULT_CONFIG, **ABLATIONS[args.ablate])
        ablation = f"{args.ablate}-disabled"
    try:
        suite = run_controls(config=config, seed_base=args.seed_base, n=args.n, sweep_n=args.sweep_n)
        report = build_controls_report(suite=suite, config=config, ablation=ablation)
        _write_new(output, report)
    except (OSError, SeamFingerprintError) as exc:
        print(f"{TOOL}: FAIL: {exc}", file=sys.stderr)
        return EXIT_ERROR
    gate = suite["gate"]
    for row in suite["cases"]:
        counts = row["verdict_counts"]
        print(
            f"  {row['name']:30s} {row['kind']:16s} "
            f"A={counts[AUTHENTICATED]:3d} C={counts[CONTRADICTED]:3d} U={counts[UNKNOWN]:3d} "
            f"{'ok' if row['pass'] else 'OUTSIDE ALLOWED'}"
        )
    print(f"{TOOL}: controls gate: {gate['status'].upper()}"
          f"{' (ablation: ' + ablation + ')' if ablation else ''}")
    return 0 if gate["status"] == "pass" else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog=TOOL,
        description=(
            "Authenticate a claimed patch overlap from CT microtexture "
            "(AUTHENTICATED / CONTRADICTED / UNKNOWN), or run the synthetic "
            "control suite. Experimental; ink is never read."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    pair = sub.add_parser("pair", help="authenticate one rectified slab pair from an NPZ")
    pair.add_argument("--input", required=True,
                      help="NPZ with slab_a, slab_b (+ optional valid_a/b, expected_shift_yx, xyz_a/b)")
    pair.add_argument("--volume-root", required=True, help="exact CT volume root/id for slab A")
    pair.add_argument("--volume-root-b", default=None,
                      help="exact CT volume root/id for slab B when it differs (independent-scan arm)")
    pair.add_argument("--surface-a-sha256", required=True)
    pair.add_argument("--surface-b-sha256", required=True)
    pair.add_argument("--sampling-manifest", required=True,
                      help="frozen manifest describing CT source, tangent frame, normal "
                           "convention, depth offsets, interpolation, and code revision")
    pair.add_argument("--out", required=True, help="new JSON report path")
    pair.set_defaults(func=_cmd_pair)

    controls = sub.add_parser("controls", help="run the deterministic synthetic control suite")
    controls.add_argument("--out", required=True, help="new JSON report path")
    controls.add_argument("--seed-base", type=int, default=DEFAULT_SEED_BASE)
    controls.add_argument("--n", type=int, default=20, help="seeds per control case")
    controls.add_argument("--sweep-n", type=int, default=12, help="seeds per sweep level")
    controls.add_argument("--ablate", choices=sorted(ABLATIONS), default=None,
                          help="disable one gate to record the naive variant (gate is expected to FAIL)")
    controls.set_defaults(func=_cmd_controls)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
