"""Ink-blind cross-ply fiber-frame continuity diagnostics.

This module consumes a shallow CT slab already rectified into surface-normal
(depth, y, x) coordinates. It estimates two dominant axial fiber orientations
per spatial tile from depth-resolved 2-D structure tensors, treats the pair as
unordered, and flags abrupt frame changes between neighboring tiles.

The output is a review/falsification artifact. It does not prove recto polarity,
sheet identity, or geometric correctness.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Sequence

import numpy as np
from scipy.ndimage import gaussian_filter

TOOL = "scroliq-fiber-frame"
SCHEMA_VERSION = 1
METHOD = "depth-resolved-cross-ply-structure-tensor-v1"


class FiberFrameError(ValueError):
    pass


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
        raise FiberFrameError(f"{name} must be lowercase 64-hex sha256")
    return value


def axial_distance_degrees(a: float, b: float) -> float:
    """Smallest difference between two unoriented axes in degrees."""
    delta = abs(float(a) - float(b)) % 180.0
    return min(delta, 180.0 - delta)


def frame_distance_degrees(a: Sequence[float], b: Sequence[float]) -> float:
    """Worst matched axial-angle difference for two unordered 2-axis frames."""
    if len(a) != 2 or len(b) != 2:
        raise FiberFrameError("fiber frames must each contain exactly two axes")
    direct = max(
        axial_distance_degrees(a[0], b[0]),
        axial_distance_degrees(a[1], b[1]),
    )
    swapped = max(
        axial_distance_degrees(a[0], b[1]),
        axial_distance_degrees(a[1], b[0]),
    )
    return float(min(direct, swapped))


def _weighted_axial_mean(angles: np.ndarray, weights: np.ndarray) -> float | None:
    z = np.sum(weights * np.exp(1j * np.deg2rad(2.0 * angles)))
    if abs(z) <= 1e-15:
        return None
    return float((np.rad2deg(np.angle(z)) / 2.0) % 180.0)


def _cluster_two_axial(
    angles_degrees: np.ndarray,
    weights: np.ndarray,
) -> tuple[np.ndarray, np.ndarray] | None:
    """Deterministic weighted two-means on axial angles."""
    angles = np.asarray(angles_degrees, dtype=np.float64)
    weights = np.asarray(weights, dtype=np.float64)
    if (
        angles.ndim != 1
        or weights.shape != angles.shape
        or angles.size < 2
        or not np.all(np.isfinite(angles))
        or not np.all(np.isfinite(weights))
        or np.any(weights <= 0)
    ):
        return None

    first = int(np.argmax(weights))
    separation = np.asarray(
        [axial_distance_degrees(angles[first], value) for value in angles],
        dtype=np.float64,
    )
    second = int(np.argmax(separation * weights))
    if second == first or separation[second] <= 0:
        return None

    centers = np.asarray([angles[first], angles[second]], dtype=np.float64)
    for _ in range(24):
        distances = np.asarray(
            [
                [axial_distance_degrees(angle, center) for center in centers]
                for angle in angles
            ],
            dtype=np.float64,
        )
        labels = np.argmin(distances, axis=1)
        updated: list[float] = []
        for cluster in range(2):
            selected = labels == cluster
            if not np.any(selected):
                return None
            mean = _weighted_axial_mean(angles[selected], weights[selected])
            if mean is None:
                return None
            updated.append(mean)
        new_centers = np.asarray(updated, dtype=np.float64)
        if max(
            axial_distance_degrees(centers[i], new_centers[i])
            for i in range(2)
        ) < 1e-7:
            centers = new_centers
            break
        centers = new_centers

    distances = np.asarray(
        [
            [axial_distance_degrees(angle, center) for center in centers]
            for angle in angles
        ],
        dtype=np.float64,
    )
    labels = np.argmin(distances, axis=1)
    cluster_weights = np.asarray(
        [float(weights[labels == i].sum()) for i in range(2)],
        dtype=np.float64,
    )
    order = np.argsort(centers)
    return centers[order], cluster_weights[order]


def _depth_orientation(
    gx: np.ndarray,
    gy: np.ndarray,
) -> tuple[float, float, float] | None:
    jxx = float(np.mean(gx * gx))
    jyy = float(np.mean(gy * gy))
    jxy = float(np.mean(gx * gy))
    trace = jxx + jyy
    if not math.isfinite(trace) or trace <= 1e-15:
        return None
    anisotropy = math.sqrt((jxx - jyy) ** 2 + 4.0 * jxy * jxy)
    coherence = anisotropy / (trace + 1e-15)
    gradient_angle = (
        0.5 * math.degrees(math.atan2(2.0 * jxy, jxx - jyy))
    ) % 180.0
    fiber_angle = (gradient_angle + 90.0) % 180.0
    return fiber_angle, coherence, trace


def _tile_frame(
    gx: np.ndarray,
    gy: np.ndarray,
    *,
    min_coherence: float,
    min_separation_degrees: float,
    min_mode_share: float,
) -> dict[str, Any] | None:
    angles: list[float] = []
    weights: list[float] = []
    coherences: list[float] = []

    for depth in range(gx.shape[0]):
        estimate = _depth_orientation(gx[depth], gy[depth])
        if estimate is None:
            continue
        angle, coherence, energy = estimate
        if coherence < min_coherence:
            continue
        angles.append(angle)
        coherences.append(coherence)
        weights.append(coherence * energy)

    if len(angles) < 4:
        return None

    clustered = _cluster_two_axial(
        np.asarray(angles, dtype=np.float64),
        np.asarray(weights, dtype=np.float64),
    )
    if clustered is None:
        return None
    centers, cluster_weights = clustered
    total_weight = float(cluster_weights.sum())
    if total_weight <= 0:
        return None

    separation = axial_distance_degrees(centers[0], centers[1])
    mode_share = float(cluster_weights.min() / total_weight)
    if separation < min_separation_degrees or mode_share < min_mode_share:
        return None

    return {
        "axes_degrees": [float(centers[0]), float(centers[1])],
        "axis_separation_degrees": float(separation),
        "mode_weight_share_min": mode_share,
        "valid_depth_slices": len(angles),
        "mean_depth_coherence": float(np.mean(coherences)),
    }


def _validate_inputs(
    slab: np.ndarray,
    xyz: np.ndarray | None,
    *,
    tile_size: int,
    sigma: float,
    min_coherence: float,
    min_separation_degrees: float,
    min_mode_share: float,
    switch_degrees: float,
) -> tuple[np.ndarray, np.ndarray | None]:
    slab = np.asarray(slab)
    if slab.ndim != 3:
        raise FiberFrameError(
            f"slab must have shape (depth,y,x), got {slab.shape}"
        )
    if min(slab.shape) < 2:
        raise FiberFrameError("slab dimensions must all be >= 2")
    if not np.issubdtype(slab.dtype, np.number) or not np.all(np.isfinite(slab)):
        raise FiberFrameError("slab must contain finite numeric CT values")
    if isinstance(tile_size, bool) or tile_size < 8:
        raise FiberFrameError("tile_size must be an integer >= 8")
    if slab.shape[1] < tile_size or slab.shape[2] < tile_size:
        raise FiberFrameError("tile_size exceeds the slab surface dimensions")
    if not math.isfinite(sigma) or sigma < 0:
        raise FiberFrameError("sigma must be finite and >= 0")
    if not 0 <= min_coherence <= 1:
        raise FiberFrameError("min_coherence must be in [0,1]")
    if not 0 < min_separation_degrees <= 90:
        raise FiberFrameError("min_separation_degrees must be in (0,90]")
    if not 0 < min_mode_share <= 0.5:
        raise FiberFrameError("min_mode_share must be in (0,0.5]")
    if not 0 < switch_degrees <= 90:
        raise FiberFrameError("switch_degrees must be in (0,90]")

    xyz_out: np.ndarray | None = None
    if xyz is not None:
        xyz_out = np.asarray(xyz, dtype=np.float64)
        expected = (slab.shape[1], slab.shape[2], 3)
        if xyz_out.shape != expected:
            raise FiberFrameError(
                f"xyz must have shape {expected}, got {xyz_out.shape}"
            )
        if not np.all(np.isfinite(xyz_out)):
            raise FiberFrameError("xyz must contain finite coordinates")

    return slab.astype(np.float64, copy=False), xyz_out


def analyze_slab(
    slab: np.ndarray,
    *,
    xyz: np.ndarray | None = None,
    tile_size: int = 32,
    sigma: float = 1.0,
    min_coherence: float = 0.35,
    min_separation_degrees: float = 25.0,
    min_mode_share: float = 0.15,
    switch_degrees: float = 25.0,
) -> dict[str, Any]:
    """Estimate local cross-ply frames and flag abrupt neighboring changes."""
    slab, xyz = _validate_inputs(
        slab,
        xyz,
        tile_size=tile_size,
        sigma=sigma,
        min_coherence=min_coherence,
        min_separation_degrees=min_separation_degrees,
        min_mode_share=min_mode_share,
        switch_degrees=switch_degrees,
    )
    smoothed = (
        gaussian_filter(slab, sigma=(0.0, sigma, sigma), mode="reflect")
        if sigma > 0
        else slab
    )
    gy = np.gradient(smoothed, axis=1)
    gx = np.gradient(smoothed, axis=2)

    depth, height, width = slab.shape
    y_starts = list(range(0, height - tile_size + 1, tile_size))
    x_starts = list(range(0, width - tile_size + 1, tile_size))
    frames: dict[tuple[int, int], dict[str, Any]] = {}
    frame_rows: list[dict[str, Any]] = []

    for grid_y, y0 in enumerate(y_starts):
        for grid_x, x0 in enumerate(x_starts):
            frame = _tile_frame(
                gx[:, y0 : y0 + tile_size, x0 : x0 + tile_size],
                gy[:, y0 : y0 + tile_size, x0 : x0 + tile_size],
                min_coherence=min_coherence,
                min_separation_degrees=min_separation_degrees,
                min_mode_share=min_mode_share,
            )
            if frame is None:
                continue
            cy = min(y0 + tile_size // 2, height - 1)
            cx = min(x0 + tile_size // 2, width - 1)
            row = {
                "grid": [grid_y, grid_x],
                "bounds_yx": [y0, y0 + tile_size, x0, x0 + tile_size],
                "center_yx": [cy, cx],
                **frame,
            }
            if xyz is not None:
                row["xyz"] = [float(v) for v in xyz[cy, cx]]
            frames[(grid_y, grid_x)] = row
            frame_rows.append(row)

    findings: list[dict[str, Any]] = []
    review_queue: list[dict[str, Any]] = []
    comparisons = 0
    for key in sorted(frames):
        grid_y, grid_x = key
        left = frames[key]
        for neighbor in ((grid_y, grid_x + 1), (grid_y + 1, grid_x)):
            right = frames.get(neighbor)
            if right is None:
                continue
            comparisons += 1
            delta = frame_distance_degrees(
                left["axes_degrees"], right["axes_degrees"]
            )
            if delta <= switch_degrees:
                continue
            finding_id = f"{grid_y}:{grid_x}->{neighbor[0]}:{neighbor[1]}"
            finding = {
                "finding_id": finding_id,
                "kind": "cross_ply_frame_discontinuity",
                "tile_a": list(key),
                "tile_b": list(neighbor),
                "frame_delta_degrees": float(delta),
                "switch_threshold_degrees": float(switch_degrees),
                "axes_a_degrees": left["axes_degrees"],
                "axes_b_degrees": right["axes_degrees"],
            }
            if xyz is not None:
                midpoint = (
                    np.asarray(left["xyz"], dtype=np.float64)
                    + np.asarray(right["xyz"], dtype=np.float64)
                ) / 2.0
                finding["xyz"] = [float(v) for v in midpoint]
                review_queue.append(dict(finding))
            findings.append(finding)

    total_tiles = len(y_starts) * len(x_starts)
    valid_tiles = len(frame_rows)
    status = "measured" if valid_tiles >= 2 and comparisons > 0 else "insufficient"

    return {
        "method": METHOD,
        "status": status,
        "shape_depth_y_x": [depth, height, width],
        "parameters": {
            "tile_size": tile_size,
            "sigma": float(sigma),
            "min_coherence": float(min_coherence),
            "min_separation_degrees": float(min_separation_degrees),
            "min_mode_share": float(min_mode_share),
            "switch_degrees": float(switch_degrees),
        },
        "coverage": {
            "total_tiles": total_tiles,
            "valid_tiles": valid_tiles,
            "valid_tile_fraction": (
                float(valid_tiles / total_tiles) if total_tiles else 0.0
            ),
            "neighbor_comparisons": comparisons,
            "flagged_comparisons": len(findings),
        },
        "frames": frame_rows,
        "findings": findings,
        "review_queue": review_queue,
        "vc3d_review_ready": bool(review_queue),
        "claim_boundary": (
            "A cross-ply frame discontinuity is a review cue only. It does not "
            "prove a sheet switch, recto polarity, or geometry error; folds, "
            "tears, cracks, joins, weak texture, and sampling defects can alter "
            "the local orientation field."
        ),
    }


def build_report(
    *,
    analysis: dict[str, Any],
    input_path: str | Path,
    input_sha256: str,
    volume_root: str,
    surface_geometry_sha256: str,
    sampling_manifest_path: str | Path,
    sampling_manifest_sha256: str,
    has_xyz: bool,
) -> dict[str, Any]:
    if not isinstance(volume_root, str) or not volume_root.strip():
        raise FiberFrameError("volume_root must be non-empty")
    _lower_hex_sha(input_sha256, "input_sha256")
    _lower_hex_sha(surface_geometry_sha256, "surface_geometry_sha256")
    _lower_hex_sha(sampling_manifest_sha256, "sampling_manifest_sha256")
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "classification": "EXPERIMENT FURTHER",
        "purpose": (
            "ink-blind CT-conditioned cross-ply continuity review for candidate "
            "surface sheet switches"
        ),
        "volume_root": volume_root,
        "input": {
            "path": str(input_path),
            "sha256": input_sha256,
            "format": "npz",
            "required_array": "slab(depth,y,x)",
            "optional_array": "xyz(y,x,3)",
            "has_xyz": bool(has_xyz),
        },
        "surface": {
            "geometry_sha256": surface_geometry_sha256,
            "sampling_manifest": {
                "path": str(sampling_manifest_path),
                "sha256": sampling_manifest_sha256,
            },
        },
        "analysis": analysis,
        "experimental_evidence_ready": analysis.get("status") == "measured",
        "interpretation": (
            "experimental_evidence_ready means the diagnostic had enough "
            "recoverable local frames to measure continuity. Promotion to an "
            "unrolling gate requires real-CT adjacent-winding and legitimate-"
            "discontinuity controls; no such promotion is implied here."
        ),
    }


def _load_npz(path: Path) -> tuple[np.ndarray, np.ndarray | None]:
    try:
        with np.load(path, allow_pickle=False) as data:
            if "slab" not in data.files:
                raise FiberFrameError("input NPZ must contain array 'slab'")
            slab = np.asarray(data["slab"])
            xyz = np.asarray(data["xyz"]) if "xyz" in data.files else None
    except (OSError, ValueError) as exc:
        if isinstance(exc, FiberFrameError):
            raise
        raise FiberFrameError(f"cannot read input NPZ: {exc}") from exc
    return slab, xyz


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog=TOOL,
        description=(
            "Estimate two depth-resolved papyrus fiber axes per rectified CT "
            "tile and flag abrupt neighboring frame changes."
        ),
    )
    parser.add_argument("--input", required=True, help="NPZ with slab and optional xyz")
    parser.add_argument("--volume-root", required=True, help="exact CT volume root/id")
    parser.add_argument("--surface-geometry-sha256", required=True)
    parser.add_argument(
        "--sampling-manifest",
        required=True,
        help=(
            "frozen manifest describing CT source, surface sampling, tangent "
            "frame, normal convention, interpolation, and code revision"
        ),
    )
    parser.add_argument("--tile-size", type=int, default=32)
    parser.add_argument("--sigma", type=float, default=1.0)
    parser.add_argument("--min-coherence", type=float, default=0.35)
    parser.add_argument("--min-separation-degrees", type=float, default=25.0)
    parser.add_argument("--min-mode-share", type=float, default=0.15)
    parser.add_argument("--switch-degrees", type=float, default=25.0)
    parser.add_argument("--out", required=True, help="new JSON report path")
    args = parser.parse_args(argv)

    source = Path(args.input)
    manifest = Path(args.sampling_manifest)
    output = Path(args.out)
    if output.exists():
        print(f"{TOOL}: refusing to overwrite existing output: {output}", file=sys.stderr)
        return 2

    try:
        slab, xyz = _load_npz(source)
        analysis = analyze_slab(
            slab,
            xyz=xyz,
            tile_size=args.tile_size,
            sigma=args.sigma,
            min_coherence=args.min_coherence,
            min_separation_degrees=args.min_separation_degrees,
            min_mode_share=args.min_mode_share,
            switch_degrees=args.switch_degrees,
        )
        report = build_report(
            analysis=analysis,
            input_path=source,
            input_sha256=_sha256_file(source),
            volume_root=args.volume_root,
            surface_geometry_sha256=args.surface_geometry_sha256,
            sampling_manifest_path=manifest,
            sampling_manifest_sha256=_sha256_file(manifest),
            has_xyz=xyz is not None,
        )
    except (OSError, FiberFrameError) as exc:
        print(f"{TOOL}: FAIL: {exc}", file=sys.stderr)
        return 2

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    coverage = analysis["coverage"]
    print(
        f"{TOOL}: {analysis['status']}: "
        f"{coverage['valid_tiles']}/{coverage['total_tiles']} valid tiles; "
        f"{coverage['flagged_comparisons']} flagged neighbor comparisons"
    )
    if analysis["review_queue"]:
        print(
            f"{len(analysis['review_queue'])} finding(s) include XYZ for VC3D review"
        )
    return 0 if report["experimental_evidence_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
