"""Read-only TIFXYZ mesh diagnostics for Vesuvius Challenge surfaces."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

DIAGNOSTIC = "tifxyz-mesh-audit"
SCHEMA_VERSION = 1


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _summary(values: np.ndarray) -> dict[str, float | int | None]:
    a = np.asarray(values, dtype=np.float64).reshape(-1)
    a = a[np.isfinite(a)]
    if not a.size:
        return {"count": 0, "min": None, "p05": None, "median": None, "p95": None, "max": None}
    q = np.quantile(a, [0, 0.05, 0.5, 0.95, 1])
    return {
        "count": int(a.size),
        "min": float(q[0]),
        "p05": float(q[1]),
        "median": float(q[2]),
        "p95": float(q[3]),
        "max": float(q[4]),
    }


def _runs(row: np.ndarray) -> list[tuple[int, int]]:
    padded = np.pad(np.asarray(row, dtype=np.int8), (1, 1), constant_values=0)
    delta = np.diff(padded)
    return [
        (int(a), int(b))
        for a, b in zip(np.flatnonzero(delta == 1), np.flatnonzero(delta == -1))
    ]


class _UnionFind:
    def __init__(self) -> None:
        self.parent: list[int] = []
        self.size: list[int] = []
        self.border: list[bool] = []

    def make(self, size: int, border: bool) -> int:
        i = len(self.parent)
        self.parent.append(i)
        self.size.append(size)
        self.border.append(border)
        return i

    def find(self, i: int) -> int:
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def union(self, a: int, b: int) -> int:
        a, b = self.find(a), self.find(b)
        if a == b:
            return a
        if self.size[a] < self.size[b]:
            a, b = b, a
        self.parent[b] = a
        self.size[a] += self.size[b]
        self.border[a] = self.border[a] or self.border[b]
        return a


def _components(mask: np.ndarray) -> dict[str, Any]:
    mask = np.asarray(mask, dtype=bool)
    h, w = mask.shape
    total = int(mask.sum())
    if total == 0:
        return {
            "components": 0,
            "cells": 0,
            "largest_component_cells": 0,
            "largest_component_fraction": 0.0,
            "border_touching_components": 0,
            "enclosed_components": 0,
        }

    uf = _UnionFind()
    previous: list[tuple[int, int, int]] = []
    for y in range(h):
        current: list[tuple[int, int, int]] = []
        j0 = 0
        for start, end in _runs(mask[y]):
            label = uf.make(end - start, y in (0, h - 1) or start == 0 or end == w)
            while j0 < len(previous) and previous[j0][1] <= start:
                j0 += 1
            j = j0
            while j < len(previous) and previous[j][0] < end:
                p_start, p_end, p_label = previous[j]
                if p_end > start and p_start < end:
                    label = uf.union(label, p_label)
                j += 1
            current.append((start, end, label))
        previous = current

    roots = [i for i in range(len(uf.parent)) if uf.find(i) == i]
    sizes = [uf.size[i] for i in roots]
    borders = [uf.border[i] for i in roots]
    largest = max(sizes, default=0)
    return {
        "components": len(roots),
        "cells": total,
        "largest_component_cells": int(largest),
        "largest_component_fraction": float(largest / total),
        "border_touching_components": int(sum(borders)),
        "enclosed_components": int(sum(not b for b in borders)),
    }


def _read_tiff(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        return np.asarray(image)


def _mask(path: Path, shape: tuple[int, int]) -> tuple[np.ndarray | None, dict[str, Any]]:
    if not path.exists():
        return None, {"present": False, "applied": False}
    raw = _read_tiff(path)
    if raw.ndim == 3:
        raw = raw[..., 0]
    if raw.ndim != 2:
        return None, {"present": True, "applied": False, "reason": "mask is not 2D"}
    h, w = shape
    mh, mw = raw.shape
    if mh % h or mw % w or mh < h or mw < w:
        return None, {
            "present": True,
            "applied": False,
            "shape_yx": [int(mh), int(mw)],
            "reason": "mask dimensions are not positive integer multiples of the coordinate grid",
        }
    sy, sx = mh // h, mw // w
    keep = (raw >= 255).reshape(h, sy, w, sx).all(axis=(1, 3))
    return keep, {
        "present": True,
        "applied": True,
        "shape_yx": [int(mh), int(mw)],
        "integer_scale_xy": [int(sx), int(sy)],
        "keep_fraction": float(keep.mean()),
    }


def _edge_metrics(
    xyz: np.ndarray,
    valid: np.ndarray,
    scale: tuple[float, float],
    jump_ratio: float,
) -> dict[str, Any]:
    cv = valid[:, :-1] & valid[:, 1:]
    rv = valid[:-1, :] & valid[1:, :]
    cd = np.linalg.norm(xyz[:, 1:] - xyz[:, :-1], axis=-1)[cv]
    rd = np.linalg.norm(xyz[1:] - xyz[:-1], axis=-1)[rv]
    out: dict[str, Any] = {}
    for name, values, nominal in (
        ("columns", cd, 1.0 / scale[0]),
        ("rows", rd, 1.0 / scale[1]),
    ):
        median = float(np.median(values)) if values.size else None
        threshold = jump_ratio * median if median and median > 0 else None
        stretch = values / nominal if values.size else np.asarray([])
        out[name] = {
            "distance_voxels": _summary(values),
            "nominal_distance_voxels": nominal,
            "stretch_ratio": _summary(stretch),
            "jump_ratio_threshold": jump_ratio,
            "jump_distance_threshold_voxels": threshold,
            "jump_edges": int((values > threshold).sum()) if threshold else 0,
        }
    return out


def _quad_metrics(
    xyz: np.ndarray,
    valid: np.ndarray,
    scale: tuple[float, float],
    flip_angle: float,
) -> dict[str, Any]:
    vq = valid[:-1, :-1] & valid[:-1, 1:] & valid[1:, :-1] & valid[1:, 1:]
    p00 = xyz[:-1, :-1]
    p01 = xyz[:-1, 1:]
    p10 = xyz[1:, :-1]
    p11 = xyz[1:, 1:]

    c1 = np.cross(p01 - p00, p10 - p00)
    c2 = np.cross(p11 - p01, p10 - p01)
    area = 0.5 * (np.linalg.norm(c1, axis=-1) + np.linalg.norm(c2, axis=-1))
    nominal = 1.0 / (scale[0] * scale[1])
    ratios = area[vq] / nominal if vq.any() else np.asarray([])
    distortion = (
        np.maximum(ratios, np.divide(1.0, ratios, out=np.full_like(ratios, np.inf), where=ratios > 0))
        if ratios.size else np.asarray([])
    )

    # Area alone cannot establish a low-distortion isometric parameterization:
    # e.g. 2x stretch in one flat axis and 0.5x compression in the other
    # preserves area exactly.  Treat each valid quad as two triangles and
    # measure the singular values of the local flat->3D Jacobian.  TIFXYZ
    # meta.scale is grid cells per voxel, so multiplying grid-edge vectors by
    # scale converts derivatives to one-voxel flat-coordinate units.
    if vq.any():
        j1 = np.stack(
            ((p01 - p00) * scale[0], (p10 - p00) * scale[1]),
            axis=-1,
        )[vq]
        j2 = np.stack(
            ((p11 - p10) * scale[0], (p11 - p01) * scale[1]),
            axis=-1,
        )[vq]
        jacobians = np.concatenate([j1, j2], axis=0)
        gram = np.einsum("...ki,...kj->...ij", jacobians, jacobians)
        singular = np.sqrt(np.clip(np.linalg.eigvalsh(gram), 0.0, None))
        usable = np.isfinite(singular).all(axis=1) & (singular[:, 0] > 1e-8)
        sigma_min = singular[usable, 0]
        sigma_max = singular[usable, 1]
        symmetric_stretch = np.maximum(sigma_max, 1.0 / sigma_min)
        anisotropy = sigma_max / sigma_min
        symmetric_dirichlet = (
            sigma_min**2 + sigma_max**2
            + 1.0 / sigma_min**2 + 1.0 / sigma_max**2
        )
        degenerate_triangles = int((~usable).sum())
    else:
        sigma_min = sigma_max = symmetric_stretch = anisotropy = symmetric_dirichlet = np.asarray([])
        degenerate_triangles = 0

    normals = c1 + c2
    norm = np.linalg.norm(normals, axis=-1)
    ok = vq & np.isfinite(norm) & (norm > 1e-8)
    unit = np.zeros_like(normals)
    unit[ok] = normals[ok] / norm[ok, None]
    horizontal = ok[:, :-1] & ok[:, 1:]
    vertical = ok[:-1] & ok[1:]
    hd = (unit[:, :-1] * unit[:, 1:]).sum(axis=-1)[horizontal]
    vd = (unit[:-1] * unit[1:]).sum(axis=-1)[vertical]
    dots = np.concatenate([hd, vd]) if hd.size or vd.size else np.asarray([])
    cutoff = math.cos(math.radians(flip_angle))

    return {
        "valid_quads": int(vq.sum()),
        "valid_quad_fraction": float(vq.mean()) if vq.size else 0.0,
        "degenerate_quads": int((vq & (~np.isfinite(area) | (area <= 1e-8))).sum()),
        "surface_area_voxels2": float(area[vq].sum()) if vq.any() else 0.0,
        "nominal_flat_area_voxels2": float(vq.sum() * nominal),
        "area_ratio_3d_to_flat": _summary(ratios),
        "symmetric_area_distortion": _summary(distortion),
        "isometry": {
            "method": "per-triangle singular values of the flat-to-3D Jacobian",
            "triangles": int(2 * vq.sum()),
            "degenerate_triangles": degenerate_triangles,
            "sigma_min": _summary(sigma_min),
            "sigma_max": _summary(sigma_max),
            "symmetric_stretch_distortion": _summary(symmetric_stretch),
            "anisotropy": _summary(anisotropy),
            "symmetric_dirichlet_energy": _summary(symmetric_dirichlet),
        },
        "normal_neighbor_dot": _summary(dots),
        "normal_flip_angle_deg": flip_angle,
        "normal_reversal_pairs": int((dots < cutoff).sum()) if dots.size else 0,
    }


def audit_tifxyz(
    path: str | Path,
    *,
    volume_root: str | None = None,
    spacing_tolerance_ratio: float = 1.5,
    jump_ratio: float = 4.0,
    distortion_p95_threshold: float = 2.0,
    isometry_p95_threshold: float = 2.0,
    normal_flip_angle_deg: float = 120.0,
) -> dict[str, Any]:
    root = Path(path)
    errors: list[str] = []
    warnings: list[str] = []
    findings: list[dict[str, str]] = []

    if (
        spacing_tolerance_ratio <= 1
        or jump_ratio <= 1
        or distortion_p95_threshold <= 1
        or isometry_p95_threshold <= 1
    ):
        raise ValueError("ratio thresholds must be > 1")
    if not 90 <= normal_flip_angle_deg < 180:
        raise ValueError("normal_flip_angle_deg must be in [90, 180)")

    required = [root / name for name in ("meta.json", "x.tif", "y.tif", "z.tif")]
    missing = [p.name for p in required if not p.exists()]
    if missing:
        errors.append("missing required TIFXYZ files: " + ", ".join(missing))
        return {
            "schema_version": SCHEMA_VERSION,
            "diagnostic": DIAGNOSTIC,
            "volume_root": volume_root,
            "tifxyz_path": str(root),
            "status": "fail",
            "error_count": len(errors),
            "warning_count": 0,
            "errors": errors,
            "warnings": [],
            "findings": [],
        }

    provenance = {
        p.name: {"sha256": _sha256(p), "bytes": p.stat().st_size}
        for p in required
    }
    mask_path = root / "mask.tif"
    if mask_path.exists():
        provenance["mask.tif"] = {"sha256": _sha256(mask_path), "bytes": mask_path.stat().st_size}

    try:
        meta = json.loads((root / "meta.json").read_text(encoding="utf-8"))
    except Exception as exc:
        meta = {}
        errors.append(f"meta.json could not be parsed: {exc}")
    if not isinstance(meta, dict):
        meta = {}
        errors.append("meta.json must contain an object")
    if meta.get("format") != "tifxyz":
        errors.append('meta.json format must equal "tifxyz"')

    scale = None
    values = meta.get("scale")
    if (
        isinstance(values, list)
        and len(values) == 2
        and all(type(v) in (int, float) and math.isfinite(float(v)) and float(v) > 0 for v in values)
    ):
        scale = (float(values[0]), float(values[1]))
    else:
        errors.append("meta.json scale must contain two finite positive numbers")

    try:
        x = np.asarray(_read_tiff(root / "x.tif"), dtype=np.float32)
        y = np.asarray(_read_tiff(root / "y.tif"), dtype=np.float32)
        z = np.asarray(_read_tiff(root / "z.tif"), dtype=np.float32)
    except Exception as exc:
        x = y = z = np.empty((0, 0))
        errors.append(f"coordinate TIFFs could not be decoded: {exc}")

    if any(a.ndim != 2 for a in (x, y, z)):
        errors.append("x.tif, y.tif, and z.tif must be single-channel 2D images")
    elif not (x.shape == y.shape == z.shape):
        errors.append(f"coordinate TIFF shapes differ: x={x.shape}, y={y.shape}, z={z.shape}")

    if errors or scale is None or x.ndim != 2 or not (x.shape == y.shape == z.shape):
        return {
            "schema_version": SCHEMA_VERSION,
            "diagnostic": DIAGNOSTIC,
            "volume_root": volume_root,
            "tifxyz_path": str(root),
            "status": "fail",
            "metadata": meta,
            "provenance": provenance,
            "error_count": len(errors),
            "warning_count": 0,
            "errors": errors,
            "warnings": [],
            "findings": [],
        }

    keep, mask_info = _mask(mask_path, z.shape)
    if mask_info.get("present") and not mask_info.get("applied"):
        warnings.append(str(mask_info.get("reason")))

    valid = z > 0
    if keep is not None:
        valid &= keep
    xyz = np.stack([x, y, z], axis=-1)
    nonfinite = valid & ~np.isfinite(xyz).all(axis=-1)
    if nonfinite.any():
        errors.append(f"{int(nonfinite.sum())} valid vertices contain non-finite coordinates")
        valid &= ~nonfinite

    valid_count = int(valid.sum())
    if not valid_count:
        errors.append("surface contains no valid vertices after TIFXYZ validity rules")

    connected = _components(valid)
    invalid = _components(~valid)
    holes = int(invalid["enclosed_components"])
    if connected["components"] > 1:
        warnings.append(f"valid-vertex grid has {connected['components']} disconnected components")
        findings.append({
            "kind": "connectivity",
            "severity": "review",
            "message": f"{connected['components']} disconnected valid-vertex components",
        })
    if holes:
        warnings.append(f"valid-vertex grid contains {holes} enclosed invalid component(s)")
        findings.append({
            "kind": "hole",
            "severity": "review",
            "message": f"{holes} enclosed invalid grid component(s)",
        })

    bbox: dict[str, Any] = {"metadata_present": False}
    if valid_count:
        pts = xyz[valid]
        observed = np.asarray([pts.min(axis=0), pts.max(axis=0)])
        bbox["observed_bbox_xyz"] = observed.tolist()
        raw_bbox = meta.get("bbox")
        if (
            isinstance(raw_bbox, list)
            and len(raw_bbox) == 2
            and all(isinstance(row, list) and len(row) == 3 for row in raw_bbox)
        ):
            bbox["metadata_present"] = True
            try:
                declared = np.asarray(raw_bbox, dtype=np.float64)
                contains = bool(
                    np.all(declared[0] <= observed[0] + 1e-3)
                    and np.all(declared[1] >= observed[1] - 1e-3)
                )
                bbox.update({
                    "metadata_bbox_xyz": declared.tolist(),
                    "contains_observed_vertices": contains,
                    "max_abs_error_voxels": float(np.max(np.abs(declared - observed))),
                })
                if not contains:
                    warnings.append("meta.json bbox does not contain all valid vertices")
            except Exception:
                warnings.append("meta.json bbox could not be interpreted as finite XYZ bounds")

    edges = _edge_metrics(xyz, valid, scale, jump_ratio)
    quads = _quad_metrics(xyz, valid, scale, normal_flip_angle_deg)
    if quads["valid_quads"] == 0:
        errors.append("surface contains no valid quads")

    spacing: dict[str, Any] = {}
    for axis in ("columns", "rows"):
        measured = edges[axis]["distance_voxels"]["median"]
        nominal = edges[axis]["nominal_distance_voxels"]
        ratio = float(measured / nominal) if measured is not None else None
        within = ratio is not None and 1 / spacing_tolerance_ratio <= ratio <= spacing_tolerance_ratio
        spacing[axis] = {
            "measured_median_voxels": measured,
            "nominal_voxels_from_scale": nominal,
            "measured_to_nominal_ratio": ratio,
            "tolerance_ratio": spacing_tolerance_ratio,
            "within_tolerance": bool(within),
        }
        if ratio is not None and not within:
            warnings.append(f"{axis} median 3D step disagrees with 1/scale by {ratio:.3g}x")

    jumps = int(edges["columns"]["jump_edges"] + edges["rows"]["jump_edges"])
    if jumps:
        warnings.append(f"{jumps} local mesh edge(s) exceed {jump_ratio:g}x axis-median spacing")
        findings.append({
            "kind": "edge-jump",
            "severity": "review",
            "message": f"{jumps} edges exceed {jump_ratio:g}x axis-median spacing",
        })
    if quads["normal_reversal_pairs"]:
        warnings.append(
            f"{quads['normal_reversal_pairs']} neighboring quad pair(s) reverse by more than "
            f"{normal_flip_angle_deg:g} degrees"
        )
        findings.append({
            "kind": "normal-reversal",
            "severity": "review",
            "message": f"{quads['normal_reversal_pairs']} severe neighboring-normal reversals",
        })
    p95 = quads["symmetric_area_distortion"]["p95"]
    if p95 is not None and p95 > distortion_p95_threshold:
        warnings.append(
            f"p95 symmetric quad-area distortion {p95:.3g} exceeds "
            f"{distortion_p95_threshold:g}"
        )

    isometry_p95 = quads["isometry"]["symmetric_stretch_distortion"]["p95"]
    if isometry_p95 is not None and isometry_p95 > isometry_p95_threshold:
        warnings.append(
            f"p95 local isometry distortion {isometry_p95:.3g} exceeds "
            f"{isometry_p95_threshold:g}"
        )
        findings.append({
            "kind": "isometry-distortion",
            "severity": "review",
            "message": (
                f"p95 local symmetric stretch {isometry_p95:.3g} exceeds "
                f"{isometry_p95_threshold:g}"
            ),
        })

    status = "fail" if errors else ("partial" if warnings else "pass")
    return {
        "schema_version": SCHEMA_VERSION,
        "diagnostic": DIAGNOSTIC,
        "volume_root": volume_root,
        "tifxyz_path": str(root),
        "status": status,
        "metadata": {
            "format": meta.get("format"),
            "scale": list(scale),
            "uuid": meta.get("uuid"),
            "type": meta.get("type"),
        },
        "provenance": provenance,
        "grid": {
            "shape_yx": [int(z.shape[0]), int(z.shape[1])],
            "vertices": int(z.size),
            "valid_vertices": valid_count,
            "valid_vertex_fraction": float(valid.mean()) if valid.size else 0.0,
            "mask": mask_info,
            "valid_vertex_components": connected,
            "enclosed_invalid_components": holes,
        },
        "bbox": bbox,
        "spacing": spacing,
        "edges": edges,
        "quads": quads,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
        "findings": findings,
        "limitation": (
            "This is a mesh-format and mesh-geometry audit. It does not establish CT support, "
            "correct winding identity, absence of nonlocal self-intersections, or readable ink."
        ),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Audit one Vesuvius TIFXYZ surface without modifying it")
    ap.add_argument("--tifxyz", required=True)
    ap.add_argument("--volume-root", default=None)
    ap.add_argument("--spacing-tolerance-ratio", type=float, default=1.5)
    ap.add_argument("--jump-ratio", type=float, default=4.0)
    ap.add_argument("--distortion-p95-threshold", type=float, default=2.0)
    ap.add_argument("--isometry-p95-threshold", type=float, default=2.0)
    ap.add_argument("--normal-flip-angle", type=float, default=120.0)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    result = audit_tifxyz(
        args.tifxyz,
        volume_root=args.volume_root,
        spacing_tolerance_ratio=args.spacing_tolerance_ratio,
        jump_ratio=args.jump_ratio,
        distortion_p95_threshold=args.distortion_p95_threshold,
        isometry_p95_threshold=args.isometry_p95_threshold,
        normal_flip_angle_deg=args.normal_flip_angle,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        f"{result['status'].upper()} {args.tifxyz}: "
        f"{result.get('error_count', 0)} error(s), {result.get('warning_count', 0)} warning(s)"
    )
    if result["status"] == "fail":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
