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


VALIDITY_RULES = ("tifxyz", "nonnegative-xyz")
_AXES = ("x", "y", "z")


def _valid_vertex_mask(
    xyz: np.ndarray,
    keep: np.ndarray | None,
    *,
    rule: str = "tifxyz",
) -> tuple[np.ndarray, int]:
    """Return ``(valid, nonfinite_count)`` under one named validity rule.

    ``tifxyz`` is this audit's rule: VC3D marks holes with ``-1``, so a vertex
    is valid when ``z > 0`` (and inside the optional mask). ``nonnegative-xyz``
    is the upstream spiral-input convention: every coordinate is ``>= 0``.
    The two differ only for vertices with ``z == 0`` or a negative x/y, so
    callers that compare against a published count must record which one ran.
    """
    if rule == "tifxyz":
        valid = xyz[..., 2] > 0
    elif rule == "nonnegative-xyz":
        valid = (xyz >= 0).all(axis=-1)
    else:
        raise ValueError(f"unknown vertex validity rule {rule!r}; use one of {VALIDITY_RULES}")
    if keep is not None:
        valid = valid & keep
    nonfinite = valid & ~np.isfinite(xyz).all(axis=-1)
    return valid & ~nonfinite, int(nonfinite.sum())


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def load_valid_vertices(
    path: str | Path,
    *,
    validity: str = "tifxyz",
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Decode a TIFXYZ directory into ``(xyz, valid, info)`` without auditing it.

    Raises ``ValueError`` when the coordinate files are missing, undecodable or
    disagree in shape; a surface with zero valid vertices is returned, not
    raised, so callers can report it as empty rather than as unreadable.
    """
    root = Path(path)
    missing = [n for n in ("x.tif", "y.tif", "z.tif") if not (root / n).is_file()]
    if missing:
        raise ValueError("missing required TIFXYZ files: " + ", ".join(missing))
    try:
        x = np.asarray(_read_tiff(root / "x.tif"), dtype=np.float32)
        y = np.asarray(_read_tiff(root / "y.tif"), dtype=np.float32)
        z = np.asarray(_read_tiff(root / "z.tif"), dtype=np.float32)
    except Exception as exc:  # noqa: BLE001 - surface any decoder failure uniformly
        raise ValueError(f"coordinate TIFFs could not be decoded: {exc}") from exc
    if any(a.ndim != 2 for a in (x, y, z)):
        raise ValueError("x.tif, y.tif, and z.tif must be single-channel 2D images")
    if not (x.shape == y.shape == z.shape):
        raise ValueError(f"coordinate TIFF shapes differ: x={x.shape}, y={y.shape}, z={z.shape}")
    keep, mask_info = _mask(root / "mask.tif", z.shape)
    xyz = np.stack([x, y, z], axis=-1)
    valid, nonfinite = _valid_vertex_mask(xyz, keep, rule=validity)
    return xyz, valid, {
        "shape_yx": [int(z.shape[0]), int(z.shape[1])],
        "valid_vertices": int(valid.sum()),
        "nonfinite_vertices": nonfinite,
        "validity_rule": validity,
        "mask": mask_info,
    }


def recompute_bbox(path: str | Path, *, validity: str = "tifxyz") -> dict[str, Any]:
    """Recompute the XYZ bounds of a TIFXYZ surface from its valid vertices.

    Never reads ``meta.json``: the point of this function is a spatial extent
    that does not depend on what the producer declared. ``status`` is ``ok``,
    ``empty`` (decoded, but no valid vertex) or ``unreadable``.
    """
    if validity not in VALIDITY_RULES:  # a bad argument is not a bad surface
        raise ValueError(f"unknown vertex validity rule {validity!r}; use one of {VALIDITY_RULES}")
    try:
        xyz, valid, info = load_valid_vertices(path, validity=validity)
    except ValueError as exc:
        return {"status": "unreadable", "reason": str(exc), "observed_bbox_xyz": None,
                "valid_vertices": 0, "validity_rule": validity}
    if not info["valid_vertices"]:
        return {"status": "empty", "observed_bbox_xyz": None, **info}
    pts = xyz[valid]
    return {
        "status": "ok",
        "observed_bbox_xyz": [pts.min(axis=0).tolist(), pts.max(axis=0).tolist()],
        **info,
    }


def compare_bbox(
    declared: Any,
    observed: Any,
    *,
    tolerance_voxels: float = 1e-3,
) -> dict[str, Any]:
    """Compare a declared ``meta.json`` bbox with bounds recomputed from vertices.

    ``stale`` means valid vertices lie outside the declared box by more than
    ``tolerance_voxels`` on at least one axis. Such a box is not an upper bound
    on the surface, so a spatial filter built on it can silently drop geometry.
    A box that merely contains the surface loosely is ``consistent``; the slack
    is recorded but is not a defect.
    """
    if not math.isfinite(tolerance_voxels) or tolerance_voxels < 0:
        raise ValueError("tolerance_voxels must be finite and >= 0")
    out: dict[str, Any] = {"status": "undeclared", "tolerance_voxels": float(tolerance_voxels)}
    if declared is None:
        return out
    if not (
        isinstance(declared, list)
        and len(declared) == 2
        and all(isinstance(row, list) and len(row) == 3 and all(_is_number(v) for v in row)
                for row in declared)
    ):
        return {**out, "status": "unreadable",
                "reason": "bbox must be [[x0,y0,z0],[x1,y1,z1]] of finite numbers"}
    box = np.asarray(declared, dtype=np.float64)
    if not np.isfinite(box).all():
        return {**out, "status": "unreadable", "reason": "bbox contains non-finite numbers"}
    if (box[0] > box[1]).any():
        return {**out, "status": "unreadable", "reason": "bbox minima exceed maxima",
                "metadata_bbox_xyz": box.tolist()}
    obs = np.asarray(observed, dtype=np.float64)
    below = np.maximum(0.0, box[0] - obs[0])
    above = np.maximum(0.0, obs[1] - box[1])
    excess = np.maximum(below, above)
    stale_axes = [a for a, e in zip(_AXES, excess) if e > tolerance_voxels]
    slack = np.maximum(0.0, np.maximum(obs[0] - box[0], box[1] - obs[1]))
    return {
        **out,
        "status": "stale" if stale_axes else "consistent",
        "metadata_bbox_xyz": box.tolist(),
        "contains_observed_vertices": not stale_axes,
        "max_abs_error_voxels": float(np.max(np.abs(box - obs))),
        "excess_voxels_xyz": [float(e) for e in excess],
        "max_excess_voxels": float(excess.max()),
        "stale_axes": stale_axes,
        "max_slack_voxels": float(slack.max()),
    }


def geometry_digest(path: str | Path) -> dict[str, Any]:
    """Digest the decoded geometry of a TIFXYZ surface, independent of encoding.

    Hashes the validity bitmap and the float32 coordinates of valid vertices
    only, so a re-encoded TIFF, a rewritten ``meta.json`` uuid, or junk in the
    masked-out cells does not change it. Two surfaces with equal digests are
    the same geometry; a producer whose output digest equals its input digest
    changed nothing.
    """
    xyz, valid, info = load_valid_vertices(path)
    h = hashlib.sha256()
    h.update(b"scrollq-tifxyz-geometry-v1")
    h.update(np.asarray(info["shape_yx"], dtype="<i8").tobytes())
    h.update(np.packbits(valid, axis=None).tobytes())
    h.update(np.ascontiguousarray(xyz[valid], dtype="<f4").tobytes())
    return {
        "coordinate_sha256": h.hexdigest(),
        "shape_yx": info["shape_yx"],
        "valid_vertices": info["valid_vertices"],
    }


def _nonnegative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _same_declared_root(left: str, right: str) -> bool:
    return left.rstrip("/") == right.rstrip("/")


def _surface_preflight_evidence(
    report_path: str | Path | None,
    surface_root: Path,
    *,
    volume_root: str | None,
    shape: tuple[int, int],
    scale: tuple[float, float],
    meta_sha256: str,
    valid_vertex_count: int,
) -> tuple[dict[str, Any], list[str], list[str], list[dict[str, str]]]:
    """Validate a Villa vesuvius.surface_preflight schema-v2 report.

    The upstream preflight owns CT bounds/signal-support semantics. ScrolIQ
    only verifies that the supplied report is structurally complete and tied
    to the surface/volume currently being audited.
    """
    if report_path is None:
        return (
            {
                "status": "unknown",
                "tool": "vesuvius.surface_preflight",
                "reason": "no upstream vesuvius.surface_preflight report supplied",
            },
            [],
            [],
            [],
        )

    path = Path(report_path)
    errors: list[str] = []
    warnings: list[str] = []
    findings: list[dict[str, str]] = []
    evidence: dict[str, Any] = {
        "status": "fail",
        "tool": "vesuvius.surface_preflight",
        "report_path": str(path),
    }
    if not path.is_file():
        errors.append(f"surface preflight report does not exist: {path}")
        return evidence, errors, warnings, findings

    evidence["report_sha256"] = _sha256(path)
    evidence["report_bytes"] = path.stat().st_size
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"surface preflight report could not be parsed: {exc}")
        return evidence, errors, warnings, findings
    if not isinstance(report, dict):
        errors.append("surface preflight report must contain a JSON object")
        return evidence, errors, warnings, findings

    schema_version = report.get("schema_version")
    evidence["schema_version"] = schema_version
    if schema_version != 2:
        errors.append(
            f"surface preflight schema_version must be 2, got {schema_version!r}"
        )

    surface = report.get("surface")
    if not isinstance(surface, dict):
        surface = {}
        errors.append("surface preflight report surface must be an object")
    declared_surface = surface.get("path")
    path_match = False
    if isinstance(declared_surface, str) and declared_surface:
        try:
            path_match = (
                Path(declared_surface).expanduser().resolve()
                == surface_root.expanduser().resolve()
            )
        except OSError:
            path_match = False
    else:
        errors.append("surface preflight report must name its input surface")
    evidence["declared_surface"] = declared_surface
    evidence["surface_path_matches"] = path_match
    if isinstance(declared_surface, str) and declared_surface and not path_match:
        errors.append("surface preflight report names a different TIFXYZ surface path")

    report_meta_sha = surface.get("meta_sha256")
    evidence["meta_sha256"] = report_meta_sha
    if report_meta_sha != meta_sha256:
        errors.append("surface preflight meta.json SHA-256 does not match the audited surface")

    report_shape = surface.get("stored_shape_yx")
    evidence["stored_shape_yx"] = report_shape
    if report_shape != [int(shape[0]), int(shape[1])]:
        errors.append("surface preflight stored grid shape does not match the audited surface")

    report_scale = surface.get("scale_xy")
    scale_matches = False
    if isinstance(report_scale, list) and len(report_scale) >= 2:
        try:
            scale_matches = all(
                math.isclose(
                    float(report_scale[i]),
                    float(scale[i]),
                    rel_tol=1e-9,
                    abs_tol=1e-12,
                )
                for i in range(2)
            )
        except (TypeError, ValueError):
            scale_matches = False
    evidence["scale_xy"] = report_scale
    if not scale_matches:
        errors.append("surface preflight scale_xy does not match the audited surface")

    report_valid_vertices = surface.get("valid_vertex_count")
    evidence["valid_vertex_count"] = report_valid_vertices
    if report_valid_vertices != valid_vertex_count:
        errors.append(
            "surface preflight valid_vertex_count does not match the audited surface"
        )

    volume = report.get("volume")
    if volume_root is None:
        errors.append(
            "surface preflight evidence requires scroliq-mesh --volume-root "
            "to bind the exact CT input"
        )
    if not isinstance(volume, dict):
        volume = {}
        errors.append("surface preflight report must include a CT volume")
    declared_volume = volume.get("path")
    evidence["declared_volume"] = declared_volume
    volume_match = (
        isinstance(declared_volume, str)
        and isinstance(volume_root, str)
        and _same_declared_root(declared_volume, volume_root)
    )
    evidence["volume_root_matches"] = volume_match
    if isinstance(volume_root, str) and not volume_match:
        errors.append("surface preflight report names a different CT volume root")

    gates = report.get("gates")
    gate_map: dict[str, dict[str, Any]] = {}
    if not isinstance(gates, list) or not gates:
        errors.append("surface preflight gates must be a non-empty list")
        gates = []
    for gate in gates:
        if not isinstance(gate, dict) or not isinstance(gate.get("name"), str):
            errors.append("surface preflight gates must be named objects")
            continue
        name = gate["name"]
        if name in gate_map:
            errors.append(f"surface preflight gate {name!r} is duplicated")
            continue
        if gate.get("required") is not True or not isinstance(gate.get("passed"), bool):
            errors.append(
                f"surface preflight gate {name!r} must declare required=true and boolean passed"
            )
        gate_map[name] = gate

    required_names = {
        "tifxyz_required_files",
        "tifxyz_metadata",
        "tifxyz_coordinate_shapes",
        "volume_is_3d",
        "valid_surface_vertices",
        "valid_surface_quads",
        "finite_selected_coordinates",
        "coordinates_within_volume",
        "tifxyz_scale_consistency",
        "sampled_volume_signal_support",
    }
    missing_gates = sorted(required_names - set(gate_map))
    if missing_gates:
        errors.append(
            "surface preflight report is missing required gate(s): "
            + ", ".join(missing_gates)
        )

    failed_gates = sorted(
        name
        for name, gate in gate_map.items()
        if gate.get("required") is True and gate.get("passed") is not True
    )
    declared_status = report.get("status")
    computed_pass = bool(gate_map) and not failed_gates
    if declared_status not in {"PASS", "FAIL"}:
        errors.append("surface preflight status must be PASS or FAIL")
    elif (declared_status == "PASS") != computed_pass:
        errors.append("surface preflight status contradicts its required gates")

    summary = report.get("summary")
    if isinstance(summary, dict):
        required_count = sum(g.get("required") is True for g in gate_map.values())
        passed_count = sum(
            g.get("required") is True and g.get("passed") is True
            for g in gate_map.values()
        )
        if summary.get("required_gate_count") != required_count:
            errors.append("surface preflight required_gate_count contradicts its gates")
        if summary.get("passed_required_gates") != passed_count:
            errors.append("surface preflight passed_required_gates contradicts its gates")
    else:
        errors.append("surface preflight report summary must be an object")

    support = volume.get("sampled_signal_support")
    if isinstance(support, dict):
        evidence["sampled_signal_support"] = {
            key: support.get(key)
            for key in ("sample_count", "supported_count", "support_fraction")
        }
    evidence["resolved_array_key"] = volume.get("resolved_array_key")
    evidence["failed_gates"] = failed_gates
    evidence["required_gate_count"] = len(gate_map)

    if failed_gates or declared_status == "FAIL":
        errors.append(
            "vesuvius.surface_preflight failed required gate(s): "
            + (", ".join(failed_gates) if failed_gates else "unknown")
        )
        findings.append(
            {
                "kind": "surface-preflight",
                "severity": "block",
                "message": (
                    "official Villa surface preflight failed: "
                    + (", ".join(failed_gates) if failed_gates else "report status FAIL")
                ),
            }
        )

    evidence["binding"] = (
        "report path + current meta.json SHA-256 + grid shape + valid-vertex "
        "count + exact declared CT root; upstream schema v2 does not hash x/y/z.tif"
    )
    evidence["status"] = "fail" if errors else "pass"
    return evidence, errors, warnings, findings


def _selfcross_evidence(
    report_path: str | Path | None,
    surface_root: Path,
    shape: tuple[int, int],
) -> tuple[dict[str, Any], list[str], list[str], list[dict[str, str]]]:
    """Validate and summarize an upstream vc_tifxyz_selfcross report.

    ScrolIQ deliberately does not reimplement triangle/triangle intersection.
    When supplied, this evidence is accepted only when the upstream report is
    structurally self-consistent and bound to the exact local TIFXYZ path and
    grid being audited.
    """
    if report_path is None:
        return (
            {
                "status": "unknown",
                "tool": "vc_tifxyz_selfcross",
                "reason": "no upstream vc_tifxyz_selfcross report supplied",
            },
            [],
            [],
            [],
        )

    path = Path(report_path)
    errors: list[str] = []
    warnings: list[str] = []
    findings: list[dict[str, str]] = []
    evidence: dict[str, Any] = {
        "status": "fail",
        "tool": "vc_tifxyz_selfcross",
        "report_path": str(path),
    }

    if not path.is_file():
        errors.append(f"selfcross report does not exist: {path}")
        return evidence, errors, warnings, findings

    evidence["report_sha256"] = _sha256(path)
    evidence["report_bytes"] = path.stat().st_size
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"selfcross report could not be parsed: {exc}")
        return evidence, errors, warnings, findings
    if not isinstance(report, dict):
        errors.append("selfcross report must contain a JSON object")
        return evidence, errors, warnings, findings

    if report.get("tool") != "vc_tifxyz_selfcross":
        errors.append('selfcross report tool must equal "vc_tifxyz_selfcross"')
    if report.get("report_only") is not True:
        errors.append("selfcross report must declare report_only=true")

    declared_surface = report.get("surface")
    path_match = False
    if isinstance(declared_surface, str) and declared_surface:
        try:
            path_match = Path(declared_surface).expanduser().resolve() == surface_root.expanduser().resolve()
        except OSError:
            path_match = False
    else:
        errors.append("selfcross report must name its input surface")
    evidence["declared_surface"] = declared_surface
    evidence["surface_path_matches"] = path_match
    if isinstance(declared_surface, str) and declared_surface and not path_match:
        errors.append("selfcross report names a different TIFXYZ surface path")

    rows, cols = shape
    evidence["grid_shape_yx"] = [int(rows), int(cols)]
    if report.get("grid_rows") != rows or report.get("grid_cols") != cols:
        errors.append(
            "selfcross report grid shape does not match the audited TIFXYZ grid"
        )

    params = report.get("parameters")
    parameters: dict[str, Any] = {}
    if not isinstance(params, dict):
        errors.append("selfcross report parameters must be an object")
    else:
        parameters = {
            key: params.get(key)
            for key in ("exclude", "maxedge", "cell", "touch_tolerance", "diagonals")
        }
        diagonals = params.get("diagonals")
        if diagonals != [0, 1]:
            errors.append("selfcross report must census both triangulations [0, 1]")
        if not _nonnegative_int(params.get("exclude")):
            errors.append("selfcross exclude must be a non-negative integer")
        maxedge = params.get("maxedge")
        if not isinstance(maxedge, (int, float)) or isinstance(maxedge, bool) or not math.isfinite(float(maxedge)) or float(maxedge) < 0:
            errors.append("selfcross maxedge must be a finite number >= 0")
        for key in ("cell", "touch_tolerance"):
            value = params.get(key)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)) or float(value) <= 0:
                errors.append(f"selfcross {key} must be a finite positive number")
    evidence["parameters"] = parameters

    census = report.get("census")
    per_diagonal: list[dict[str, int]] = []
    seen_diagonals: set[int] = set()
    transverse_total = 0
    coplanar_total = 0
    grazing_total = 0
    dropped_total = 0
    malformed_contacts = 0

    if not isinstance(census, list) or len(census) != 2:
        errors.append("selfcross census must contain exactly two diagonal reports")
    else:
        for item in census:
            if not isinstance(item, dict):
                errors.append("selfcross census entries must be objects")
                continue
            diagonal = item.get("diagonal")
            if diagonal not in (0, 1) or diagonal in seen_diagonals:
                errors.append("selfcross census diagonal IDs must be unique 0 and 1")
                continue
            seen_diagonals.add(int(diagonal))

            counts: dict[str, int] = {}
            for key in (
                "triangles",
                "quads_dropped_for_edge_length",
                "pairs_tested",
                "transverse",
                "coplanar",
                "grazing",
            ):
                value = item.get(key)
                if not _nonnegative_int(value):
                    errors.append(f"selfcross diagonal {diagonal} {key} must be a non-negative integer")
                    value = 0
                counts[key] = int(value)

            contacts = item.get("transverse_contacts")
            if not isinstance(contacts, list):
                errors.append(f"selfcross diagonal {diagonal} transverse_contacts must be a list")
                contacts = []
            if len(contacts) != counts["transverse"]:
                errors.append(
                    f"selfcross diagonal {diagonal} transverse count does not match contact rows"
                )

            for contact in contacts:
                ok = isinstance(contact, dict)
                if ok:
                    for key in ("quad1", "quad2"):
                        q = contact.get(key)
                        ok = ok and isinstance(q, list) and len(q) == 2 and all(_nonnegative_int(v) for v in q)
                    site = contact.get("site")
                    ok = ok and isinstance(site, list) and len(site) == 3 and all(
                        isinstance(v, (int, float))
                        and not isinstance(v, bool)
                        and math.isfinite(float(v))
                        for v in site
                    )
                    for key in ("penetration_vx", "angle_deg"):
                        value = contact.get(key)
                        ok = ok and isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))
                if not ok:
                    malformed_contacts += 1

            transverse_total += counts["transverse"]
            coplanar_total += counts["coplanar"]
            grazing_total += counts["grazing"]
            dropped_total += counts["quads_dropped_for_edge_length"]
            per_diagonal.append({"diagonal": int(diagonal), **counts})

        if seen_diagonals != {0, 1}:
            errors.append("selfcross census must contain diagonal IDs 0 and 1")

    if malformed_contacts:
        errors.append(f"{malformed_contacts} selfcross transverse contact row(s) are malformed")

    declared_clean = report.get("clean_of_transverse_self_intersection")
    computed_clean = transverse_total == 0
    if not isinstance(declared_clean, bool):
        errors.append("selfcross report must declare clean_of_transverse_self_intersection")
    elif declared_clean != computed_clean:
        errors.append("selfcross clean verdict contradicts the transverse contact counts")

    evidence.update(
        {
            "clean_of_transverse_self_intersection": computed_clean,
            "transverse_contacts": transverse_total,
            "coplanar_contacts": coplanar_total,
            "grazing_contacts": grazing_total,
            "quads_dropped_for_edge_length": dropped_total,
            "census": sorted(per_diagonal, key=lambda item: item["diagonal"]),
        }
    )

    if transverse_total:
        errors.append(
            f"vc_tifxyz_selfcross found {transverse_total} non-adjacent transverse contact(s)"
        )
        findings.append(
            {
                "kind": "self-intersection",
                "severity": "block",
                "message": (
                    f"official VC3D census found {transverse_total} non-adjacent "
                    "transverse triangle contact(s)"
                ),
            }
        )
    if dropped_total:
        warnings.append(
            f"vc_tifxyz_selfcross dropped {dropped_total} quad(s) for exceeding maxedge; "
            "its clean verdict does not cover those quads"
        )

    evidence["status"] = "fail" if errors else ("partial" if warnings else "pass")
    return evidence, errors, warnings, findings


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
    *,
    reference_spacing: tuple[float, float],
    reference_source: str,
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

    # Area alone cannot establish a low-distortion isometric parameterization.
    # Normalize the two parameter directions by an explicit expected spacing
    # when the caller supplies one; otherwise use the observed directional
    # median edge spacing. TIFXYZ meta.scale is retained as metadata/spacing
    # evidence but is not assumed to be a universal physical edge-length
    # contract. That assumption false-positives on real Villa fixtures whose
    # meta.scale describes the parameter grid at a different sampling scale.
    ref_x, ref_y = reference_spacing
    if vq.any():
        j1 = np.stack(
            ((p01 - p00) / ref_x, (p10 - p00) / ref_y),
            axis=-1,
        )[vq]
        j2 = np.stack(
            ((p11 - p10) / ref_x, (p11 - p01) / ref_y),
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
            "method": "per-triangle singular values of directionally normalized local 3D edges",
            "normalization": {
                "source": reference_source,
                "reference_spacing_voxels": [float(ref_x), float(ref_y)],
                "meta_scale_xy": [float(scale[0]), float(scale[1])],
            },
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



def _review_queue(
    xyz: np.ndarray,
    valid: np.ndarray,
    *,
    jump_ratio: float,
    flip_angle: float,
    limit_per_kind: int,
) -> dict[str, Any]:
    """Return a deterministic, bounded queue of local geometry review sites."""
    edge_candidates: list[dict[str, Any]] = []

    for orientation, a, b, edge_valid in (
        (
            "column",
            xyz[:, :-1],
            xyz[:, 1:],
            valid[:, :-1] & valid[:, 1:],
        ),
        (
            "row",
            xyz[:-1, :],
            xyz[1:, :],
            valid[:-1, :] & valid[1:, :],
        ),
    ):
        distance = np.linalg.norm(b - a, axis=-1)
        values = distance[edge_valid]
        median = float(np.median(values)) if values.size else None
        if median is None or not math.isfinite(median) or median <= 0:
            continue
        candidate_mask = edge_valid & np.isfinite(distance) & (
            distance > jump_ratio * median
        )
        for row, col in np.argwhere(candidate_mask):
            d = float(distance[row, col])
            point = ((a[row, col] + b[row, col]) / 2.0).astype(float)
            if orientation == "column":
                endpoints = [[int(row), int(col)], [int(row), int(col + 1)]]
            else:
                endpoints = [[int(row), int(col)], [int(row + 1), int(col)]]
            edge_candidates.append(
                {
                    "kind": "edge-jump",
                    "orientation": orientation,
                    "grid_endpoints_yx": endpoints,
                    "xyz": point.tolist(),
                    "distance_voxels": d,
                    "axis_median_voxels": median,
                    "ratio_to_axis_median": d / median,
                }
            )

    edge_candidates.sort(
        key=lambda item: (
            -float(item["ratio_to_axis_median"]),
            str(item["orientation"]),
            item["grid_endpoints_yx"][0][0],
            item["grid_endpoints_yx"][0][1],
        )
    )

    normal_candidates: list[dict[str, Any]] = []
    vq = valid[:-1, :-1] & valid[:-1, 1:] & valid[1:, :-1] & valid[1:, 1:]
    if vq.size:
        p00 = xyz[:-1, :-1]
        p01 = xyz[:-1, 1:]
        p10 = xyz[1:, :-1]
        p11 = xyz[1:, 1:]
        c1 = np.cross(p01 - p00, p10 - p00)
        c2 = np.cross(p11 - p01, p10 - p01)
        normals = c1 + c2
        norm = np.linalg.norm(normals, axis=-1)
        ok = vq & np.isfinite(norm) & (norm > 1e-8)
        unit = np.zeros_like(normals)
        unit[ok] = normals[ok] / norm[ok, None]
        center = (p00 + p01 + p10 + p11) / 4.0
        cutoff = math.cos(math.radians(flip_angle))

        for orientation, left, right, pair_valid in (
            (
                "column",
                unit[:, :-1],
                unit[:, 1:],
                ok[:, :-1] & ok[:, 1:],
            ),
            (
                "row",
                unit[:-1, :],
                unit[1:, :],
                ok[:-1, :] & ok[1:, :],
            ),
        ):
            dot = (left * right).sum(axis=-1)
            candidate_mask = pair_valid & np.isfinite(dot) & (dot < cutoff)
            for row, col in np.argwhere(candidate_mask):
                d = float(np.clip(dot[row, col], -1.0, 1.0))
                angle = math.degrees(math.acos(d))
                if orientation == "column":
                    point = (center[row, col] + center[row, col + 1]) / 2.0
                    quads = [[int(row), int(col)], [int(row), int(col + 1)]]
                else:
                    point = (center[row, col] + center[row + 1, col]) / 2.0
                    quads = [[int(row), int(col)], [int(row + 1), int(col)]]
                normal_candidates.append(
                    {
                        "kind": "normal-reversal",
                        "orientation": orientation,
                        "grid_quads_yx": quads,
                        "xyz": point.astype(float).tolist(),
                        "normal_dot": d,
                        "angle_deg": float(angle),
                    }
                )

    normal_candidates.sort(
        key=lambda item: (
            -float(item["angle_deg"]),
            str(item["orientation"]),
            item["grid_quads_yx"][0][0],
            item["grid_quads_yx"][0][1],
        )
    )

    emitted: list[dict[str, Any]] = []
    for candidates in (edge_candidates, normal_candidates):
        for rank, item in enumerate(candidates[:limit_per_kind], start=1):
            emitted.append({**item, "rank": rank})

    return {
        "coordinate_space": "level0-voxel-xyz",
        "limit_per_kind": int(limit_per_kind),
        "total_candidates_by_kind": {
            "edge-jump": len(edge_candidates),
            "normal-reversal": len(normal_candidates),
        },
        "emitted_by_kind": {
            "edge-jump": min(len(edge_candidates), limit_per_kind),
            "normal-reversal": min(len(normal_candidates), limit_per_kind),
        },
        "candidates": emitted,
        "limitation": (
            "Review sites localize the strongest local geometry cues only. "
            "They are VC3D inspection targets, not defect verdicts or sheet-identity proof."
        ),
    }


def review_queue_pointcollections(report: dict[str, Any]) -> dict[str, Any]:
    """Convert a Mesh IQ review queue into VC3D PointCollections JSON v1."""
    queue = report.get("review_queue")
    candidates = (
        queue.get("candidates")
        if isinstance(queue, dict) and isinstance(queue.get("candidates"), list)
        else []
    )
    groups = (
        ("edge-jump", "Mesh IQ · edge jumps", [1.0, 0.55, 0.0]),
        ("normal-reversal", "Mesh IQ · normal reversals", [1.0, 0.2, 0.2]),
    )
    collections: dict[str, Any] = {}
    collection_id = 0
    for kind, name, color in groups:
        selected = [item for item in candidates if item.get("kind") == kind]
        if not selected:
            continue
        collection_id += 1
        points: dict[str, Any] = {}
        for point_id, item in enumerate(selected, start=1):
            xyz = item.get("xyz")
            if not (
                isinstance(xyz, list)
                and len(xyz) == 3
                and all(isinstance(v, (int, float)) and math.isfinite(float(v)) for v in xyz)
            ):
                continue
            points[str(point_id)] = {
                "id": point_id,
                "p": [float(v) for v in xyz],
                "wind_a": None,
                "collection_id": collection_id,
            }
        if not points:
            continue
        collections[str(collection_id)] = {
            "id": collection_id,
            "name": name,
            "color": color,
            "points": points,
            "metadata": {
                "tool": "ScrolIQ Mesh IQ",
                "finding_kind": kind,
                "source_tifxyz": report.get("tifxyz_path"),
                "volume_root": report.get("volume_root"),
                "coordinate_space": "level0-voxel-xyz",
                "ranking": (
                    "descending edge ratio" if kind == "edge-jump"
                    else "descending normal angle"
                ),
            },
        }
    return {
        "vc_pointcollections_json_version": "1",
        "collections": collections,
    }


def write_review_pointcollections(
    report: dict[str, Any],
    path: str | Path,
) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(review_queue_pointcollections(report), indent=2) + "\n",
        encoding="utf-8",
    )

def audit_tifxyz(
    path: str | Path,
    *,
    volume_root: str | None = None,
    spacing_tolerance_ratio: float = 1.5,
    jump_ratio: float = 4.0,
    distortion_p95_threshold: float = 2.0,
    isometry_p95_threshold: float = 2.0,
    expected_spacing_x: float | None = None,
    expected_spacing_y: float | None = None,
    normal_flip_angle_deg: float = 120.0,
    review_limit_per_kind: int = 20,
    selfcross_report: str | Path | None = None,
    surface_preflight_report: str | Path | None = None,
    bbox_tolerance_voxels: float = 1e-3,
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
    if (expected_spacing_x is None) != (expected_spacing_y is None):
        raise ValueError("expected_spacing_x and expected_spacing_y must be supplied together")
    if expected_spacing_x is not None and (
        not math.isfinite(expected_spacing_x)
        or not math.isfinite(expected_spacing_y)
        or expected_spacing_x <= 0
        or expected_spacing_y <= 0
    ):
        raise ValueError("expected spacings must be finite positive numbers")
    if not 90 <= normal_flip_angle_deg < 180:
        raise ValueError("normal_flip_angle_deg must be in [90, 180)")
    if review_limit_per_kind < 0:
        raise ValueError("review_limit_per_kind must be >= 0")

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

    xyz = np.stack([x, y, z], axis=-1)
    valid, nonfinite_count = _valid_vertex_mask(xyz, keep)
    if nonfinite_count:
        errors.append(f"{nonfinite_count} valid vertices contain non-finite coordinates")

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

    # Spatial metadata is always recomputed from the valid vertices; the
    # declared bbox is only ever compared against it, never trusted alone.
    bbox: dict[str, Any] = {"metadata_present": meta.get("bbox") is not None, "status": "undeclared"}
    if valid_count:
        pts = xyz[valid]
        observed = np.asarray([pts.min(axis=0), pts.max(axis=0)])
        bbox["observed_bbox_xyz"] = observed.tolist()
        bbox.update(compare_bbox(meta.get("bbox"), observed, tolerance_voxels=bbox_tolerance_voxels))
        if bbox["status"] == "stale":
            axes = ",".join(bbox["stale_axes"])
            warnings.append(
                "meta.json bbox does not contain all valid vertices "
                f"(stale on axis {axes}; worst excess {bbox['max_excess_voxels']:.6g} voxels)"
            )
            findings.append({
                "kind": "stale-bbox",
                "severity": "review",
                "message": (
                    f"declared bbox misses valid vertices on {axes} by up to "
                    f"{bbox['max_excess_voxels']:.6g} voxels; recompute it from the "
                    "vertices before any spatial filtering"
                ),
            })
        elif bbox["status"] == "unreadable":
            warnings.append(f"meta.json bbox could not be interpreted: {bbox['reason']}")

    edges = _edge_metrics(xyz, valid, scale, jump_ratio)
    observed_x = edges["columns"]["distance_voxels"]["median"]
    observed_y = edges["rows"]["distance_voxels"]["median"]
    if expected_spacing_x is not None:
        isometry_reference = (float(expected_spacing_x), float(expected_spacing_y))
        isometry_reference_source = "explicit-expected-spacing"
    elif (
        observed_x is not None and observed_x > 0
        and observed_y is not None and observed_y > 0
    ):
        isometry_reference = (float(observed_x), float(observed_y))
        isometry_reference_source = "observed-directional-median"
    else:
        # No stable local reference can be derived; keep the audit executable
        # but make the lack of isometry evidence explicit.
        isometry_reference = (1.0 / scale[0], 1.0 / scale[1])
        isometry_reference_source = "meta-scale-fallback"
        warnings.append(
            "isometry normalization fell back to meta.scale because directional "
            "median edge spacing could not be measured"
        )
    quads = _quad_metrics(
        xyz,
        valid,
        scale,
        normal_flip_angle_deg,
        reference_spacing=isometry_reference,
        reference_source=isometry_reference_source,
    )
    if quads["valid_quads"] == 0:
        errors.append("surface contains no valid quads")

    review_queue = _review_queue(
        xyz,
        valid,
        jump_ratio=jump_ratio,
        flip_angle=normal_flip_angle_deg,
        limit_per_kind=review_limit_per_kind,
    )

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

    ct_preflight, preflight_errors, preflight_warnings, preflight_findings = (
        _surface_preflight_evidence(
            surface_preflight_report,
            root,
            volume_root=volume_root,
            shape=z.shape,
            scale=scale,
            meta_sha256=provenance["meta.json"]["sha256"],
            valid_vertex_count=valid_count,
        )
    )
    errors.extend(preflight_errors)
    warnings.extend(preflight_warnings)
    findings.extend(preflight_findings)

    self_intersection, selfcross_errors, selfcross_warnings, selfcross_findings = (
        _selfcross_evidence(selfcross_report, root, z.shape)
    )
    errors.extend(selfcross_errors)
    warnings.extend(selfcross_warnings)
    findings.extend(selfcross_findings)

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
        "review_queue": review_queue,
        "ct_preflight": ct_preflight,
        "self_intersection": self_intersection,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
        "findings": findings,
        "limitation": (
            "This audit combines local TIFXYZ geometry"
            + (
                ", a validated upstream Villa surface preflight against the declared CT volume"
                if ct_preflight.get("status") == "pass"
                else ""
            )
            + (
                ", and a validated upstream VC3D transverse self-intersection census"
                if self_intersection.get("status") == "pass"
                else ""
            )
            + ". It does not establish correct winding identity or readable ink."
            + (
                " CT support remains unverified."
                if ct_preflight.get("status") != "pass"
                else ""
            )
            + (
                " Freedom from nonlocal transverse self-intersections remains unverified."
                if self_intersection.get("status") != "pass"
                else ""
            )
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
    ap.add_argument(
        "--expected-spacing-x",
        type=float,
        default=None,
        help=(
            "optional expected 3D voxel spacing for one TIFXYZ column step; "
            "requires --expected-spacing-y. Default: observed directional median"
        ),
    )
    ap.add_argument(
        "--expected-spacing-y",
        type=float,
        default=None,
        help=(
            "optional expected 3D voxel spacing for one TIFXYZ row step; "
            "requires --expected-spacing-x. Default: observed directional median"
        ),
    )
    ap.add_argument("--normal-flip-angle", type=float, default=120.0)
    ap.add_argument(
        "--review-limit",
        type=int,
        default=20,
        help="maximum emitted VC3D review sites per local finding kind",
    )
    ap.add_argument(
        "--review-points",
        default=None,
        help="optional VC3D PointCollections JSON path for ranked local review sites",
    )
    ap.add_argument(
        "--selfcross-report",
        default=None,
        help="optional report.json produced by VC3D vc_tifxyz_selfcross for this exact surface",
    )
    ap.add_argument(
        "--surface-preflight-report",
        default=None,
        help=(
            "optional JSON produced by vesuvius.surface_preflight for this exact "
            "surface and --volume-root"
        ),
    )
    ap.add_argument("--out", required=True)
    ap.add_argument(
        "--fail-on-findings", action="store_true",
        help="exit 2 when review findings are present, for CI/pipeline gating",
    )
    args = ap.parse_args()

    result = audit_tifxyz(
        args.tifxyz,
        volume_root=args.volume_root,
        spacing_tolerance_ratio=args.spacing_tolerance_ratio,
        jump_ratio=args.jump_ratio,
        distortion_p95_threshold=args.distortion_p95_threshold,
        isometry_p95_threshold=args.isometry_p95_threshold,
        expected_spacing_x=args.expected_spacing_x,
        expected_spacing_y=args.expected_spacing_y,
        normal_flip_angle_deg=args.normal_flip_angle,
        review_limit_per_kind=args.review_limit,
        selfcross_report=args.selfcross_report,
        surface_preflight_report=args.surface_preflight_report,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if args.review_points and result.get("status") != "fail":
        write_review_pointcollections(result, args.review_points)
    print(
        f"{result['status'].upper()} {args.tifxyz}: "
        f"{result.get('error_count', 0)} error(s), {result.get('warning_count', 0)} warning(s)"
    )
    if result["status"] == "fail" or (args.fail_on_findings and result.get("findings")):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
