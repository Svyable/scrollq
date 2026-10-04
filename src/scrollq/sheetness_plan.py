"""Plan frozen, geometry-only sheetness probes before looking at sheetness scores."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Callable

import numpy as np
from PIL import Image

from zpa.report import validate_report as validate_zpa_report


SCHEMA = "scroliq-sheetness-plan/1"


class PlanError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _git_blob_sha1(path: Path) -> str:
    data = path.read_bytes()
    h = hashlib.sha1()
    h.update(b"blob " + str(len(data)).encode("ascii") + b"\\0")
    h.update(data)
    return h.hexdigest()


def _external_surface_binding(
    path: str | Path,
    *,
    surface_root: Path,
    volume_root: str,
) -> dict[str, Any]:
    binding_path = Path(path)
    try:
        doc = json.loads(binding_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PlanError(f"cannot read surface binding: {exc}") from exc
    if not isinstance(doc, dict) or doc.get("schema") != "scroliq-tifxyz-volume-binding/1":
        raise PlanError("surface binding schema must be scroliq-tifxyz-volume-binding/1")
    if doc.get("volume_root", "").strip("/") != volume_root.strip("/"):
        raise PlanError("surface binding volume_root does not exactly match requested volume_root")
    source = doc.get("source")
    if not isinstance(source, dict):
        raise PlanError("surface binding source is required")
    repository = source.get("repository")
    commit = source.get("commit")
    source_path = source.get("path")
    evidence_url = doc.get("evidence_url")
    if not all(isinstance(v, str) and v for v in (repository, commit, source_path)):
        raise PlanError("surface binding source repository/commit/path are required")
    if not isinstance(evidence_url, str) or not evidence_url.startswith(("https://", "http://")):
        raise PlanError("surface binding evidence_url must be public http(s)")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise PlanError("surface binding source commit must be lowercase 40-hex")

    files = doc.get("files")
    required = {"meta.json", "x.tif", "y.tif", "z.tif"}
    if not isinstance(files, dict) or set(files) != required:
        raise PlanError("surface binding files must exactly cover meta.json/x.tif/y.tif/z.tif")
    verified: dict[str, str] = {}
    for name in sorted(required):
        row = files.get(name)
        expected = row.get("git_blob_sha1") if isinstance(row, dict) else None
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{40}", expected):
            raise PlanError(f"surface binding {name} git_blob_sha1 must be lowercase 40-hex")
        actual = _git_blob_sha1(surface_root / name)
        if actual != expected:
            raise PlanError(
                f"surface binding {name} blob mismatch: actual {actual}, expected {expected}"
            )
        verified[name] = actual

    return {
        "path": str(binding_path),
        "sha256": _sha256(binding_path),
        "schema": doc["schema"],
        "volume_root": volume_root.strip("/"),
        "source": {
            "repository": repository,
            "commit": commit,
            "path": source_path,
        },
        "evidence_url": evidence_url,
        "verified_git_blob_sha1": verified,
    }


def _read_tiff(path: Path) -> np.ndarray:
    try:
        with Image.open(path) as image:
            return np.asarray(image)
    except Exception as exc:
        raise PlanError(f"cannot read TIFF {path}: {exc}") from exc


def _triplet_int(value: Any, name: str) -> tuple[int, int, int]:
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 3
        or any(type(v) is not int for v in value)
    ):
        raise PlanError(f"{name} must contain exactly three integer ZYX values")
    return int(value[0]), int(value[1]), int(value[2])


def _parse_offsets(text: str) -> tuple[float, ...]:
    try:
        values = tuple(float(part.strip()) for part in text.split(",") if part.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError("offsets must be comma-separated finite numbers") from exc
    if not values:
        raise argparse.ArgumentTypeError("offsets must contain at least one value")
    if any(not math.isfinite(v) or v == 0 for v in values):
        raise argparse.ArgumentTypeError("offsets must be finite and non-zero")
    if len(set(values)) != len(values):
        raise argparse.ArgumentTypeError("offsets must not contain duplicates")
    if not any(v < 0 for v in values) or not any(v > 0 for v in values):
        raise argparse.ArgumentTypeError("offsets must include both negative and positive distances")
    return values


def _mask_keep(path: Path, shape: tuple[int, int]) -> tuple[np.ndarray | None, dict[str, Any]]:
    if not path.exists():
        return None, {"present": False, "applied": False}
    raw = _read_tiff(path)
    if raw.ndim == 3:
        raw = raw[..., 0]
    if raw.ndim != 2:
        raise PlanError("mask.tif must be 2-D")
    h, w = shape
    mh, mw = raw.shape
    if mh < h or mw < w or mh % h or mw % w:
        raise PlanError("mask.tif dimensions must be positive integer multiples of coordinate grid")
    sy, sx = mh // h, mw // w
    keep = (raw >= 255).reshape(h, sy, w, sx).all(axis=(1, 3))
    return keep, {
        "present": True,
        "applied": True,
        "shape_yx": [int(mh), int(mw)],
        "integer_scale_xy": [int(sx), int(sy)],
        "keep_fraction": float(keep.mean()),
    }


def _load_surface(root: Path) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    required = [root / "x.tif", root / "y.tif", root / "z.tif", root / "meta.json"]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise PlanError("missing TIFXYZ file(s): " + ", ".join(missing))

    arrays = [_read_tiff(root / name).astype(np.float64, copy=False) for name in ("x.tif", "y.tif", "z.tif")]
    if any(array.ndim != 2 for array in arrays):
        raise PlanError("x.tif, y.tif and z.tif must be 2-D")
    if len({array.shape for array in arrays}) != 1:
        raise PlanError("x.tif, y.tif and z.tif must have identical shapes")
    xyz = np.stack(arrays, axis=-1)
    h, w = xyz.shape[:2]

    try:
        meta = json.loads((root / "meta.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PlanError(f"cannot parse meta.json: {exc}") from exc
    if not isinstance(meta, dict):
        raise PlanError("meta.json must contain a JSON object")

    # VC3D/TIFXYZ validity convention used elsewhere in ScrolIQ: Z <= 0 invalid.
    valid = np.isfinite(xyz).all(axis=-1) & (xyz[..., 2] > 0)
    mask, mask_info = _mask_keep(root / "mask.tif", (h, w))
    if mask is not None:
        valid &= mask

    hashes = {
        name: _sha256(root / name)
        for name in ("x.tif", "y.tif", "z.tif", "meta.json")
    }
    if (root / "mask.tif").is_file():
        hashes["mask.tif"] = _sha256(root / "mask.tif")

    return xyz, valid, {
        "shape_yx": [int(h), int(w)],
        "valid_vertex_count": int(valid.sum()),
        "mask": mask_info,
        "hashes": hashes,
        "meta": meta,
    }


def _verify_zpa(
    report: dict[str, Any],
    *,
    volume_root: str,
    validate_report_fn: Callable[[dict[str, Any]], list[str]],
) -> tuple[dict[str, Any], tuple[int, int, int]]:
    errors = validate_report_fn(report)
    if errors:
        raise PlanError("ZPA report fails schema validation: " + "; ".join(errors[:3]))
    if report.get("tool") != "zarr-pyramid-audit":
        raise PlanError("ZPA report tool must be zarr-pyramid-audit")
    if report.get("root") != volume_root:
        raise PlanError("ZPA report root does not exactly match volume_root")
    if report.get("integrity") != "PASS":
        raise PlanError("ZPA report integrity must be PASS")

    att = report.get("source_attestation")
    if not isinstance(att, dict):
        raise PlanError("ZPA source_attestation is required")
    if att.get("algorithm") != "zpa-metadata-semantics-v1":
        raise PlanError("ZPA source attestation algorithm mismatch")
    if att.get("state") != "PRESENT":
        raise PlanError("ZPA source attestation state must be PRESENT")
    if att.get("axes") != ["z", "y", "x"]:
        raise PlanError("ZPA source axes must be exactly ['z', 'y', 'x']")
    digest = att.get("metadata_semantics_sha256")
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(ch not in "0123456789abcdef" for ch in digest)
    ):
        raise PlanError("ZPA metadata_semantics_sha256 must be lowercase 64-hex")

    levels = report.get("levels")
    if not isinstance(levels, list):
        raise PlanError("ZPA report levels must be a list")
    base = [row for row in levels if isinstance(row, dict) and row.get("index") == 0]
    if len(base) != 1:
        raise PlanError("ZPA report must contain exactly one level-0 record")
    shape = _triplet_int(base[0].get("shape"), "ZPA level-0 shape")
    return dict(att), shape


def _normal_at_grid(
    xyz: np.ndarray,
    valid: np.ndarray,
    y: int,
    x: int,
) -> np.ndarray | None:
    h, w = valid.shape
    if y <= 0 or y >= h - 1 or x <= 0 or x >= w - 1:
        return None
    neighbors = ((y, x), (y, x - 1), (y, x + 1), (y - 1, x), (y + 1, x))
    if not all(valid[yy, xx] for yy, xx in neighbors):
        return None
    col = xyz[y, x + 1] - xyz[y, x - 1]
    row = xyz[y + 1, x] - xyz[y - 1, x]
    normal = np.cross(col, row)
    norm = float(np.linalg.norm(normal))
    if not np.isfinite(normal).all() or norm <= 1e-8:
        return None
    return normal / norm


def _xyz_to_zyx(value: np.ndarray) -> np.ndarray:
    return np.asarray([value[2], value[1], value[0]], dtype=np.float64)


def _bbox_for_points(
    points_zyx: list[np.ndarray],
    *,
    halo: int,
    source_shape: tuple[int, int, int],
) -> tuple[list[int], list[int]] | None:
    stack = np.stack(points_zyx, axis=0)
    start = np.floor(stack.min(axis=0)).astype(np.int64) - halo
    # +1 makes the upper interpolation neighbor available; halo supplies
    # convolution context around every frozen continuous probe.
    stop = np.ceil(stack.max(axis=0)).astype(np.int64) + halo + 1
    if np.any(start < 0) or np.any(stop > np.asarray(source_shape, dtype=np.int64)):
        return None
    return [int(v) for v in start], [int(v) for v in stop]


def _selection_indices(count: int, requested: int) -> list[int]:
    if requested < 1:
        raise PlanError("samples must be >= 1")
    if count < requested:
        raise PlanError(f"only {count} eligible surface vertices for {requested} requested samples")
    # Geometry-only, deterministic coverage of the lexicographically ordered
    # eligible set. No random state and no CT/sheetness values are consulted.
    return [min(count - 1, int((i + 0.5) * count / requested)) for i in range(requested)]


def _eligible_row_candidates(
    xyz: np.ndarray,
    valid: np.ndarray,
    y: int,
    *,
    offsets: tuple[float, ...],
    halo: int,
    source_shape: tuple[int, int, int],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return eligible x indices, surface XYZ and unit normals for one grid row.

    Eligibility is exactly the scalar planner contract, evaluated with NumPy
    across the row: center + four neighbours valid, finite non-degenerate
    centered normal, and every frozen offset plus halo inside the audited CT.
    The returned x indices are ascending, preserving lexicographic (y, x)
    candidate order.
    """
    h, w = valid.shape
    if y <= 0 or y >= h - 1 or w < 3:
        return (
            np.empty(0, dtype=np.int64),
            np.empty((0, 3), dtype=np.float64),
            np.empty((0, 3), dtype=np.float64),
        )

    neighbor_ok = (
        valid[y, 1:-1]
        & valid[y, :-2]
        & valid[y, 2:]
        & valid[y - 1, 1:-1]
        & valid[y + 1, 1:-1]
    )
    xs = np.flatnonzero(neighbor_ok).astype(np.int64, copy=False) + 1
    if xs.size == 0:
        return (
            xs,
            np.empty((0, 3), dtype=np.float64),
            np.empty((0, 3), dtype=np.float64),
        )

    surface_xyz = np.asarray(xyz[y, xs], dtype=np.float64)
    col = np.asarray(xyz[y, xs + 1], dtype=np.float64) - np.asarray(
        xyz[y, xs - 1], dtype=np.float64
    )
    row = np.asarray(xyz[y + 1, xs], dtype=np.float64) - np.asarray(
        xyz[y - 1, xs], dtype=np.float64
    )
    normal_xyz = np.cross(col, row)
    norms = np.linalg.norm(normal_xyz, axis=1)
    normal_ok = (
        np.isfinite(normal_xyz).all(axis=1)
        & np.isfinite(norms)
        & (norms > 1e-8)
    )
    xs = xs[normal_ok]
    surface_xyz = surface_xyz[normal_ok]
    normal_xyz = normal_xyz[normal_ok]
    norms = norms[normal_ok]
    if xs.size == 0:
        return xs, surface_xyz, normal_xyz

    normal_xyz = normal_xyz / norms[:, None]

    distances = np.asarray((0.0, *offsets), dtype=np.float64)
    points_xyz = (
        surface_xyz[:, None, :]
        + distances[None, :, None] * normal_xyz[:, None, :]
    )
    points_zyx = points_xyz[..., ::-1]
    starts = np.floor(points_zyx.min(axis=1)).astype(np.int64) - halo
    stops = np.ceil(points_zyx.max(axis=1)).astype(np.int64) + halo + 1
    shape = np.asarray(source_shape, dtype=np.int64)
    in_bounds = (starts >= 0).all(axis=1) & (stops <= shape).all(axis=1)

    return xs[in_bounds], surface_xyz[in_bounds], normal_xyz[in_bounds]


def build_plan(
    *,
    tifxyz: str | Path,
    zpa_report_path: str | Path,
    volume_root: str,
    surface_volume_token: str,
    binding_url: str,
    surface_binding_path: str | Path | None = None,
    samples: int,
    offsets: tuple[float, ...],
    halo: int,
    validate_report_fn: Callable[[dict[str, Any]], list[str]] = validate_zpa_report,
) -> dict[str, Any]:
    root = Path(tifxyz)
    if not root.is_dir():
        raise PlanError(f"TIFXYZ directory does not exist: {root}")
    volume_root = volume_root.strip("/")
    if not volume_root:
        raise PlanError("volume_root must be non-empty")
    if not surface_volume_token or surface_volume_token not in volume_root:
        raise PlanError("surface_volume_token must occur in the exact volume_root")
    if not isinstance(binding_url, str) or not binding_url.startswith(("https://", "http://")):
        raise PlanError("binding_url must be public http(s)")
    if halo < 1:
        raise PlanError("halo must be >= 1")
    if not offsets or not any(v < 0 for v in offsets) or not any(v > 0 for v in offsets):
        raise PlanError("offsets must include negative and positive distances")
    if any(not math.isfinite(v) or v == 0 for v in offsets):
        raise PlanError("offsets must be finite and non-zero")

    surface_name_match = surface_volume_token in root.name
    xyz, valid, surface_info = _load_surface(root)
    meta_text = json.dumps(surface_info["meta"], sort_keys=True)
    meta_match = surface_volume_token in meta_text
    external_binding = (
        _external_surface_binding(
            surface_binding_path,
            surface_root=root,
            volume_root=volume_root,
        )
        if surface_binding_path is not None
        else None
    )
    if not (surface_name_match or meta_match or external_binding is not None):
        raise PlanError(
            "surface volume token is not present in TIFXYZ directory name or meta.json "
            "and no verified external surface binding was supplied"
        )

    zpa_path = Path(zpa_report_path)
    try:
        zpa = json.loads(zpa_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PlanError(f"cannot read ZPA report: {exc}") from exc
    if not isinstance(zpa, dict):
        raise PlanError("ZPA report must contain a JSON object")
    attestation, source_shape = _verify_zpa(
        zpa,
        volume_root=volume_root,
        validate_report_fn=validate_report_fn,
    )

    # First pass: count eligible candidates per row without materializing one
    # Python dict per surface vertex. This keeps the frozen lexicographic
    # selection rule practical on full-resolution multi-million-vertex TIFXYZ.
    h, _w = valid.shape
    row_counts = np.zeros(max(h - 2, 0), dtype=np.int64)
    for y in range(1, h - 1):
        xs, _surface_xyz, _normal_xyz = _eligible_row_candidates(
            xyz,
            valid,
            y,
            offsets=offsets,
            halo=halo,
            source_shape=source_shape,
        )
        row_counts[y - 1] = xs.size

    eligible_count = int(row_counts.sum())
    selected_ranks = _selection_indices(eligible_count, samples)

    # Map global lexicographic ranks to row-local ranks, then recompute only
    # the rows containing selected probes. Semantics are identical to building
    # the full candidate list and indexing it, but memory scales with image
    # width instead of total eligible vertices.
    cumulative = np.cumsum(row_counts)
    selected_by_row: dict[int, list[tuple[int, int, int]]] = {}
    for sample_index, rank in enumerate(selected_ranks, start=1):
        row_index = int(np.searchsorted(cumulative, rank, side="right"))
        before = int(cumulative[row_index - 1]) if row_index else 0
        y = row_index + 1
        local_rank = int(rank - before)
        selected_by_row.setdefault(y, []).append(
            (sample_index, int(rank), local_rank)
        )

    groups_by_index: dict[int, dict[str, Any]] = {}
    for y in sorted(selected_by_row):
        xs, surface_rows, normal_rows = _eligible_row_candidates(
            xyz,
            valid,
            y,
            offsets=offsets,
            halo=halo,
            source_shape=source_shape,
        )
        for sample_index, rank, local_rank in selected_by_row[y]:
            if local_rank < 0 or local_rank >= xs.size:
                raise PlanError("internal selected-rank mapping is inconsistent")
            x = int(xs[local_rank])
            surface_xyz = np.asarray(surface_rows[local_rank], dtype=np.float64)
            normal_xyz = np.asarray(normal_rows[local_rank], dtype=np.float64)
            surface_zyx = _xyz_to_zyx(surface_xyz)
            offset_rows: list[dict[str, Any]] = []
            points = [surface_zyx]
            for distance in offsets:
                point_xyz = surface_xyz + distance * normal_xyz
                point_zyx = _xyz_to_zyx(point_xyz)
                points.append(point_zyx)
                offset_rows.append(
                    {
                        "distance_voxels": float(distance),
                        "global_xyz": [float(v) for v in point_xyz],
                        "global_zyx": [float(v) for v in point_zyx],
                    }
                )
            bbox = _bbox_for_points(points, halo=halo, source_shape=source_shape)
            if bbox is None:
                raise PlanError("internal eligible candidate became out of bounds")
            groups_by_index[sample_index] = {
                "grid_yx": [int(y), x],
                "surface_global_xyz": [float(v) for v in surface_xyz],
                "surface_global_zyx": [float(v) for v in surface_zyx],
                "reference_normal_xyz": [float(v) for v in normal_xyz],
                "reference_normal_zyx": [
                    float(normal_xyz[2]),
                    float(normal_xyz[1]),
                    float(normal_xyz[0]),
                ],
                "normal_offsets": offset_rows,
                "cutout_bbox_zyx_half_open": {
                    "start": bbox[0],
                    "stop": bbox[1],
                },
                "id": f"surface-{sample_index:04d}",
                "eligible_rank": rank,
                "wrong_wrap": {
                    "status": "pending-independent-geometry",
                    "global_zyx": None,
                    "requirement": (
                        "supply a competing-sheet coordinate from evidence independent "
                        "of the sheetness response before freezing the benchmark spec"
                    ),
                },
            }

    groups = [groups_by_index[i] for i in range(1, samples + 1)]

    binding_methods = []
    if surface_name_match:
        binding_methods.append("tifxyz-directory-name")
    if meta_match:
        binding_methods.append("meta-json-token")
    if external_binding is not None:
        binding_methods.append("hash-bound-external-binding")

    return {
        "schema": SCHEMA,
        "status": "planned",
        "volume_root": volume_root,
        "source_attestation": attestation,
        "zpa_report": {
            "path": str(zpa_path),
            "sha256": _sha256(zpa_path),
            "integrity": zpa.get("integrity"),
            "level0_shape_zyx": list(source_shape),
        },
        "surface": {
            "path": str(root),
            "volume_token": surface_volume_token,
            "binding_url": binding_url,
            "binding_methods": binding_methods,
            "external_binding": external_binding,
            "shape_yx": surface_info["shape_yx"],
            "valid_vertex_count": surface_info["valid_vertex_count"],
            "mask": surface_info["mask"],
            "hashes": surface_info["hashes"],
        },
        "protocol": {
            "coordinate_convention": {
                "tifxyz": "global base-volume XYZ voxels",
                "benchmark": "global/local ZYX voxels",
                "conversion": "global_zyx = [tifxyz_z, tifxyz_y, tifxyz_x]",
            },
            "normal_method": (
                "unit cross product of centered TIFXYZ column and row tangents; "
                "sign is arbitrary and benchmark comparison uses absolute cosine"
            ),
            "offsets_voxels": [float(v) for v in offsets],
            "halo_voxels": int(halo),
            "sample_selection": {
                "algorithm": "lexicographic-even-quantiles-v1",
                "eligible_vertex_count": eligible_count,
                "implementation": "row-vectorized-two-pass-v1",
                "requested_samples": int(samples),
                "selected_eligible_ranks": selected_ranks,
                "uses_ct_intensity": False,
                "uses_sheetness_response": False,
                "random_state": None,
            },
        },
        "groups": groups,
        "freeze_requirements": {
            "wrong_wraps_complete": False,
            "next_step": (
                "bind independent wrong-wrap coordinates, extract each planned CT box "
                "with scroliq-ct-cutout, then freeze sheetness specs before inference"
            ),
        },
        "claim_boundary": (
            "This plan deterministically selects geometry-only surface probes and "
            "normal offsets. It does not use CT intensity or sheetness scores and does "
            "not establish that the surface is the globally correct winding. Wrong-wrap "
            "coordinates are intentionally left for independent geometry evidence."
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tifxyz", required=True)
    parser.add_argument("--zpa-report", required=True)
    parser.add_argument("--volume-root", required=True)
    parser.add_argument("--surface-volume-token", required=True)
    parser.add_argument("--binding-url", required=True)
    parser.add_argument(
        "--surface-binding",
        default=None,
        help=(
            "optional hash-bound external TIFXYZ-to-volume binding for sources whose "
            "directory/meta do not embed the exact volume id"
        ),
    )
    parser.add_argument("--samples", type=int, required=True)
    parser.add_argument(
        "--offsets",
        type=_parse_offsets,
        required=True,
        help="explicit signed voxel offsets, e.g. --offsets=-8,-4,4,8",
    )
    parser.add_argument("--halo", type=int, required=True)
    parser.add_argument("--out", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    out = Path(args.out)
    if out.exists():
        print(json.dumps({"schema": SCHEMA, "status": "invalid", "error": f"refusing to overwrite {out}"}))
        return 2
    try:
        result = build_plan(
            tifxyz=args.tifxyz,
            zpa_report_path=args.zpa_report,
            volume_root=args.volume_root,
            surface_volume_token=args.surface_volume_token,
            binding_url=args.binding_url,
            surface_binding_path=args.surface_binding,
            samples=args.samples,
            offsets=args.offsets,
            halo=args.halo,
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("x", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2, sort_keys=True)
            handle.write("\n")
    except (PlanError, OSError) as exc:
        print(json.dumps({"schema": SCHEMA, "status": "invalid", "error": str(exc)}))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
