from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import tifffile


METHOD = "itk-hessian-objectness-m2-n3-compatible"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _gaussian_kernel1d(sigma: float, truncate: float = 3.0) -> np.ndarray:
    if not math.isfinite(sigma) or sigma <= 0:
        raise ValueError("sigma must be a finite positive number")
    radius = max(1, int(math.ceil(truncate * sigma)))
    x = np.arange(-radius, radius + 1, dtype=np.float64)
    kernel = np.exp(-0.5 * (x / sigma) ** 2)
    kernel /= kernel.sum()
    return kernel


def _convolve_axis_reflect(volume: np.ndarray, kernel: np.ndarray, axis: int) -> np.ndarray:
    radius = kernel.size // 2
    pads = [(0, 0)] * volume.ndim
    pads[axis] = (radius, radius)
    padded = np.pad(volume, pads, mode="reflect")
    windows = np.lib.stride_tricks.sliding_window_view(
        padded, window_shape=kernel.size, axis=axis
    )
    return np.tensordot(windows, kernel, axes=([-1], [0]))


def gaussian_smooth(volume: np.ndarray, sigma: float) -> np.ndarray:
    """Dependency-light separable Gaussian smoothing for small 3-D cutouts."""
    kernel = _gaussian_kernel1d(sigma)
    out = np.asarray(volume, dtype=np.float64)
    for axis in range(3):
        out = _convolve_axis_reflect(out, kernel, axis)
    return out


def robust_normalize(
    volume: np.ndarray, lower_percentile: float = 1.0, upper_percentile: float = 99.0
) -> tuple[np.ndarray, dict[str, float]]:
    if not (0.0 <= lower_percentile < upper_percentile <= 100.0):
        raise ValueError("normalization percentiles must satisfy 0 <= low < high <= 100")
    arr = np.asarray(volume, dtype=np.float64)
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        raise ValueError("volume contains no finite voxels")
    lo, hi = np.percentile(finite, [lower_percentile, upper_percentile])
    if not math.isfinite(float(lo)) or not math.isfinite(float(hi)) or hi <= lo:
        raise ValueError("normalization percentiles do not span a positive range")
    normalized = np.clip((arr - lo) / (hi - lo), 0.0, 1.0)
    normalized[~np.isfinite(normalized)] = 0.0
    return normalized, {
        "lower_percentile": float(lower_percentile),
        "upper_percentile": float(upper_percentile),
        "lower_value": float(lo),
        "upper_value": float(hi),
    }


def _hessian(smoothed: np.ndarray, sigma: float) -> np.ndarray:
    if smoothed.ndim != 3:
        raise ValueError("sheetness requires a 3-D volume")
    if any(size < 5 for size in smoothed.shape):
        raise ValueError("each volume dimension must be at least 5 voxels")

    gz, gy, gx = np.gradient(smoothed, edge_order=2)
    hzz = np.gradient(gz, axis=0, edge_order=2)
    hyy = np.gradient(gy, axis=1, edge_order=2)
    hxx = np.gradient(gx, axis=2, edge_order=2)
    hzy = 0.5 * (
        np.gradient(gz, axis=1, edge_order=2)
        + np.gradient(gy, axis=0, edge_order=2)
    )
    hzx = 0.5 * (
        np.gradient(gz, axis=2, edge_order=2)
        + np.gradient(gx, axis=0, edge_order=2)
    )
    hyx = 0.5 * (
        np.gradient(gy, axis=2, edge_order=2)
        + np.gradient(gx, axis=1, edge_order=2)
    )

    hessian = np.empty(smoothed.shape + (3, 3), dtype=np.float64)
    hessian[..., 0, 0] = hzz
    hessian[..., 1, 1] = hyy
    hessian[..., 2, 2] = hxx
    hessian[..., 0, 1] = hessian[..., 1, 0] = hzy
    hessian[..., 0, 2] = hessian[..., 2, 0] = hzx
    hessian[..., 1, 2] = hessian[..., 2, 1] = hyx

    # Scale-normalized second derivatives, matching the usual multiscale
    # Hessian convention: a feature should not win merely because sigma changes.
    hessian *= sigma**2
    return hessian


def plate_objectness(
    smoothed: np.ndarray,
    *,
    sigma: float,
    beta: float = 0.5,
    gamma: float = 0.1,
    bright_object: bool = True,
    scale_objectness: bool = False,
    return_normals: bool = False,
) -> tuple[np.ndarray, np.ndarray | None]:
    """Compute the 2-D-in-3-D specialization of ITK Hessian objectness.

    Eigenvalues are sorted by absolute magnitude. For a sheet/plate, two
    tangential curvatures should be small and the normal curvature large.
    With object dimension M=2 in N=3, ITK's generalized objectness reduces to
    an exp(-rB^2 / 2 beta^2) plate term times a second-order structureness term.
    """
    if beta <= 0 or not math.isfinite(beta):
        raise ValueError("beta must be a finite positive number")
    if gamma <= 0 or not math.isfinite(gamma):
        raise ValueError("gamma must be a finite positive number")

    hessian = _hessian(smoothed, sigma)
    eigenvalues, eigenvectors = np.linalg.eigh(hessian)
    order = np.argsort(np.abs(eigenvalues), axis=-1)
    eigenvalues = np.take_along_axis(eigenvalues, order, axis=-1)
    abs_eigenvalues = np.abs(eigenvalues)

    strongest = abs_eigenvalues[..., 2]
    rb = np.divide(
        abs_eigenvalues[..., 1],
        strongest,
        out=np.full_like(strongest, np.inf),
        where=strongest > 1e-12,
    )
    frobenius = np.sqrt(np.sum(abs_eigenvalues**2, axis=-1))

    response = np.exp(-0.5 * (rb / beta) ** 2)
    response *= 1.0 - np.exp(-0.5 * (frobenius / gamma) ** 2)

    # ITK's BrightObject sign convention requires the eigenvalues orthogonal
    # to the requested object dimension to be negative for bright structures,
    # positive for dark structures.
    sign_ok = eigenvalues[..., 2] < 0 if bright_object else eigenvalues[..., 2] > 0
    response = np.where(sign_ok, response, 0.0)

    if scale_objectness:
        response *= strongest

    normals = None
    if return_normals:
        sorted_vectors = np.take_along_axis(
            eigenvectors, order[..., None, :], axis=-1
        )
        normals = sorted_vectors[..., :, 2]
        normals = np.asarray(normals, dtype=np.float32)

    return np.asarray(response, dtype=np.float32), normals


def multiscale_sheetness(
    volume: np.ndarray,
    *,
    sigmas: Iterable[float],
    beta: float = 0.5,
    gamma: float = 0.1,
    bright_object: bool = True,
    scale_objectness: bool = False,
    normalize: bool = True,
    lower_percentile: float = 1.0,
    upper_percentile: float = 99.0,
    return_normals: bool = False,
) -> tuple[np.ndarray, np.ndarray, np.ndarray | None, dict[str, Any]]:
    arr = np.asarray(volume)
    if arr.ndim != 3:
        raise ValueError("sheetness requires a 3-D volume")
    if any(size < 5 for size in arr.shape):
        raise ValueError("each volume dimension must be at least 5 voxels")

    sigma_list = [float(s) for s in sigmas]
    if not sigma_list:
        raise ValueError("at least one sigma is required")
    if any((not math.isfinite(s) or s <= 0) for s in sigma_list):
        raise ValueError("all sigmas must be finite positive numbers")

    normalization: dict[str, Any]
    if normalize:
        work, normalization = robust_normalize(
            arr, lower_percentile=lower_percentile, upper_percentile=upper_percentile
        )
        normalization["enabled"] = True
    else:
        work = np.asarray(arr, dtype=np.float64)
        if not np.isfinite(work).all():
            raise ValueError("non-finite voxels require normalization")
        normalization = {"enabled": False}

    best = np.full(arr.shape, -np.inf, dtype=np.float32)
    best_scale = np.zeros(arr.shape, dtype=np.float32)
    best_normal = (
        np.zeros(arr.shape + (3,), dtype=np.float32) if return_normals else None
    )

    scale_summaries: list[dict[str, Any]] = []
    for sigma in sigma_list:
        smoothed = gaussian_smooth(work, sigma)
        response, normals = plate_objectness(
            smoothed,
            sigma=sigma,
            beta=beta,
            gamma=gamma,
            bright_object=bright_object,
            scale_objectness=scale_objectness,
            return_normals=return_normals,
        )
        wins = response > best
        best[wins] = response[wins]
        best_scale[wins] = sigma
        if best_normal is not None and normals is not None:
            best_normal[wins] = normals[wins]

        scale_summaries.append(
            {
                "sigma": sigma,
                "response_max": float(np.max(response)),
                "response_mean": float(np.mean(response)),
                "response_p99": float(np.quantile(response, 0.99)),
            }
        )

    return best, best_scale, best_normal, {
        "method": METHOD,
        "parameters": {
            "sigmas": sigma_list,
            "beta": float(beta),
            "gamma": float(gamma),
            "bright_object": bool(bright_object),
            "scale_objectness": bool(scale_objectness),
        },
        "normalization": normalization,
        "per_scale": scale_summaries,
    }


def _summary(values: np.ndarray) -> dict[str, float]:
    return {
        "min": float(np.min(values)),
        "p50": float(np.quantile(values, 0.50)),
        "p90": float(np.quantile(values, 0.90)),
        "p99": float(np.quantile(values, 0.99)),
        "max": float(np.max(values)),
        "mean": float(np.mean(values)),
    }


def load_volume(path: Path) -> np.ndarray:
    suffix = path.suffix.lower()
    if suffix == ".npy":
        arr = np.load(path, allow_pickle=False)
    elif suffix == ".npz":
        with np.load(path, allow_pickle=False) as z:
            if "volume" in z.files:
                arr = z["volume"]
            elif len(z.files) == 1:
                arr = z[z.files[0]]
            else:
                raise ValueError("NPZ must contain 'volume' or exactly one array")
    elif suffix in {".tif", ".tiff"}:
        arr = tifffile.imread(path)
    else:
        raise ValueError("input must be .npy, .npz, .tif, or .tiff")
    arr = np.asarray(arr)
    if arr.ndim != 3:
        raise ValueError(f"input volume must be 3-D, got shape {arr.shape}")
    return arr


def run(
    input_path: str | Path,
    out_prefix: str | Path,
    *,
    sigmas: Iterable[float],
    beta: float = 0.5,
    gamma: float = 0.1,
    bright_object: bool = True,
    scale_objectness: bool = False,
    normalize: bool = True,
    lower_percentile: float = 1.0,
    upper_percentile: float = 99.0,
    write_normal: bool = False,
    max_voxels: int = 2_500_000,
) -> dict[str, Any]:
    input_path = Path(input_path)
    out_prefix = Path(out_prefix)
    volume = load_volume(input_path)
    voxels = int(np.prod(volume.shape))
    if max_voxels <= 0:
        raise ValueError("max_voxels must be positive")
    if voxels > max_voxels:
        raise ValueError(
            f"cutout has {voxels:,} voxels, above --max-voxels {max_voxels:,}; "
            "use a smaller cutout or explicitly raise the guard"
        )

    response, scale, normal, details = multiscale_sheetness(
        volume,
        sigmas=sigmas,
        beta=beta,
        gamma=gamma,
        bright_object=bright_object,
        scale_objectness=scale_objectness,
        normalize=normalize,
        lower_percentile=lower_percentile,
        upper_percentile=upper_percentile,
        return_normals=write_normal,
    )

    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    response_path = Path(str(out_prefix) + ".sheetness.npy")
    scale_path = Path(str(out_prefix) + ".scale.npy")
    report_path = Path(str(out_prefix) + ".sheetness.json")
    normal_path = Path(str(out_prefix) + ".normal-zyx.npy")

    np.save(response_path, response, allow_pickle=False)
    np.save(scale_path, scale, allow_pickle=False)
    if write_normal and normal is not None:
        np.save(normal_path, normal, allow_pickle=False)

    unique_scales, counts = np.unique(scale, return_counts=True)
    report: dict[str, Any] = {
        "schema_version": 1,
        "kind": "sheetness",
        "status": "measured",
        "scope": (
            "local 3-D cutout diagnostic; not by itself evidence of correct "
            "papyrus identity, winding identity, recto/verso, or readable ink"
        ),
        "input": {
            "path": str(input_path),
            "sha256": _sha256(input_path),
            "shape_zyx": [int(v) for v in volume.shape],
            "dtype": str(volume.dtype),
            "voxels": voxels,
        },
        **details,
        "response": {
            "summary": _summary(response),
            "nonzero_fraction": float(np.count_nonzero(response) / response.size),
            "output_path": str(response_path),
            "output_sha256": _sha256(response_path),
        },
        "winning_scale": {
            "output_path": str(scale_path),
            "output_sha256": _sha256(scale_path),
            "counts": {
                str(float(s)): int(c) for s, c in zip(unique_scales.tolist(), counts.tolist())
            },
        },
        "normal": None,
    }
    if write_normal:
        report["normal"] = {
            "basis": "ZYX voxel axes",
            "interpretation": (
                "unit eigenvector of the largest-absolute Hessian eigenvalue "
                "at the winning scale; sign is arbitrary"
            ),
            "output_path": str(normal_path),
            "output_sha256": _sha256(normal_path),
        }

    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def _parse_sigmas(value: str) -> list[float]:
    try:
        values = [float(part) for part in value.split(",") if part.strip()]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("sigmas must be comma-separated numbers") from exc
    if not values or any((not math.isfinite(v) or v <= 0) for v in values):
        raise argparse.ArgumentTypeError("sigmas must be finite positive numbers")
    return values


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Measure multiscale Hessian plate/sheet response in a local 3-D CT cutout. "
            "This is an independent geometry diagnostic, not a sheet-identity verdict."
        )
    )
    parser.add_argument("input", help="3-D .npy/.npz/.tif/.tiff cutout in ZYX order")
    parser.add_argument("--out-prefix", required=True)
    parser.add_argument("--sigmas", type=_parse_sigmas, default=[0.8, 1.2, 1.8])
    parser.add_argument("--beta", type=float, default=0.5)
    parser.add_argument("--gamma", type=float, default=0.1)
    polarity = parser.add_mutually_exclusive_group()
    polarity.add_argument("--bright-object", action="store_true", default=True)
    polarity.add_argument("--dark-object", action="store_false", dest="bright_object")
    parser.add_argument("--scale-objectness", action="store_true")
    parser.add_argument("--no-normalize", action="store_true")
    parser.add_argument("--normalize-low", type=float, default=1.0)
    parser.add_argument("--normalize-high", type=float, default=99.0)
    parser.add_argument("--write-normal", action="store_true")
    parser.add_argument(
        "--max-voxels",
        type=int,
        default=2_500_000,
        help="memory guard for this dependency-light reference implementation",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = run(
            args.input,
            args.out_prefix,
            sigmas=args.sigmas,
            beta=args.beta,
            gamma=args.gamma,
            bright_object=args.bright_object,
            scale_objectness=args.scale_objectness,
            normalize=not args.no_normalize,
            lower_percentile=args.normalize_low,
            upper_percentile=args.normalize_high,
            write_normal=args.write_normal,
            max_voxels=args.max_voxels,
        )
    except (OSError, ValueError, np.linalg.LinAlgError) as exc:
        raise SystemExit(f"scroliq-sheetness: {exc}") from exc
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
