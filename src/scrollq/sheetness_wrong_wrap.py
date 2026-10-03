"""Bind frozen sheetness probes to independent competing-sheet geometry."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from .sheetness_plan import SCHEMA as PLAN_SCHEMA
from .sheetness_plan import PlanError, _load_surface


SCHEMA = "scroliq-sheetness-wrong-wrap-binding/1"


class BindingError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _parse_mapping(text: str, label: str) -> tuple[str, str]:
    if "=" not in text:
        raise argparse.ArgumentTypeError(f"{label} must use ID=VALUE")
    key, value = text.split("=", 1)
    key, value = key.strip(), value.strip()
    if not key or not value:
        raise argparse.ArgumentTypeError(f"{label} must use non-empty ID=VALUE")
    return key, value


def _parse_candidate(text: str) -> tuple[str, str]:
    return _parse_mapping(text, "candidate")


def _parse_binding_url(text: str) -> tuple[str, str]:
    key, value = _parse_mapping(text, "binding-url")
    if not value.startswith(("https://", "http://")):
        raise argparse.ArgumentTypeError("binding URL must be public http(s)")
    return key, value.rstrip("/")


def _read_plan(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BindingError(f"cannot read sheetness plan: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema") != PLAN_SCHEMA:
        raise BindingError(f"plan must be {PLAN_SCHEMA}")
    if value.get("status") != "planned":
        raise BindingError("plan status must be planned")
    protocol = value.get("protocol")
    if not isinstance(protocol, dict):
        raise BindingError("plan protocol is required")
    selection = protocol.get("sample_selection")
    if (
        not isinstance(selection, dict)
        or selection.get("uses_ct_intensity") is not False
        or selection.get("uses_sheetness_response") is not False
    ):
        raise BindingError("plan must prove geometry-only sample selection")
    freeze = value.get("freeze_requirements")
    if not isinstance(freeze, dict) or freeze.get("wrong_wraps_complete") is not False:
        raise BindingError("plan must still have pending independent wrong-wrap geometry")
    groups = value.get("groups")
    if not isinstance(groups, list) or not groups:
        raise BindingError("plan groups must be non-empty")
    return value


def _candidate_arrays(
    root: Path,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    try:
        xyz, valid, info = _load_surface(root)
    except PlanError as exc:
        raise BindingError(str(exc)) from exc

    h, w = valid.shape
    if h < 3 or w < 3:
        raise BindingError(f"candidate TIFXYZ is too small for centered normals: {root}")

    core = (
        valid[1:-1, 1:-1]
        & valid[1:-1, :-2]
        & valid[1:-1, 2:]
        & valid[:-2, 1:-1]
        & valid[2:, 1:-1]
    )
    col = xyz[1:-1, 2:] - xyz[1:-1, :-2]
    row = xyz[2:, 1:-1] - xyz[:-2, 1:-1]
    normals_xyz = np.cross(col, row)
    norm = np.linalg.norm(normals_xyz, axis=-1)
    core &= np.isfinite(normals_xyz).all(axis=-1) & np.isfinite(norm) & (norm > 1e-8)

    yy, xx = np.nonzero(core)
    if yy.size == 0:
        raise BindingError(f"candidate has no valid centered-normal vertices: {root}")
    yy = yy + 1
    xx = xx + 1

    points_xyz = xyz[yy, xx]
    normals_xyz = normals_xyz[yy - 1, xx - 1]
    normals_xyz = normals_xyz / np.linalg.norm(normals_xyz, axis=1, keepdims=True)
    points_zyx = points_xyz[:, ::-1].astype(np.float64, copy=False)
    normals_zyx = normals_xyz[:, ::-1].astype(np.float64, copy=False)
    grid_yx = np.stack([yy, xx], axis=1).astype(np.int64, copy=False)
    return points_zyx, normals_zyx, grid_yx, info


def _volume_token_bound(root: Path, info: dict[str, Any], token: str) -> bool:
    if token in root.name:
        return True
    try:
        return token in json.dumps(info.get("meta"), sort_keys=True)
    except (TypeError, ValueError):
        return False


def _expanded_bbox(
    planned: dict[str, Any],
    point_zyx: np.ndarray,
    *,
    halo: int,
    source_shape: tuple[int, int, int],
) -> dict[str, list[int]] | None:
    bbox = planned.get("cutout_bbox_zyx_half_open")
    if not isinstance(bbox, dict):
        raise BindingError("planned group cutout_bbox_zyx_half_open is required")
    start = np.asarray(bbox.get("start"), dtype=np.int64)
    stop = np.asarray(bbox.get("stop"), dtype=np.int64)
    if start.shape != (3,) or stop.shape != (3,):
        raise BindingError("planned group bbox must contain 3-D start/stop")

    wrong_start = np.floor(point_zyx).astype(np.int64) - halo
    wrong_stop = np.ceil(point_zyx).astype(np.int64) + halo + 1
    combined_start = np.minimum(start, wrong_start)
    combined_stop = np.maximum(stop, wrong_stop)
    shape = np.asarray(source_shape, dtype=np.int64)
    if np.any(combined_start < 0) or np.any(combined_stop > shape):
        return None
    return {
        "start": [int(v) for v in combined_start],
        "stop": [int(v) for v in combined_stop],
    }


def bind_wrong_wraps(
    *,
    plan: dict[str, Any],
    plan_file_sha256: str,
    candidates: dict[str, Path],
    binding_urls: dict[str, str],
    min_normal_separation: float,
    max_normal_separation: float,
    max_tangential_distance: float,
    min_normal_abs_cosine: float,
) -> dict[str, Any]:
    for name, value in (
        ("min_normal_separation", min_normal_separation),
        ("max_normal_separation", max_normal_separation),
        ("max_tangential_distance", max_tangential_distance),
        ("min_normal_abs_cosine", min_normal_abs_cosine),
    ):
        if not math.isfinite(value):
            raise BindingError(f"{name} must be finite")
    if min_normal_separation <= 0 or max_normal_separation <= min_normal_separation:
        raise BindingError("normal separation requires 0 < min < max")
    if max_tangential_distance <= 0:
        raise BindingError("max_tangential_distance must be positive")
    if not 0 <= min_normal_abs_cosine <= 1:
        raise BindingError("min_normal_abs_cosine must be between 0 and 1")

    if not candidates:
        raise BindingError("at least one competing candidate surface is required")
    if set(candidates) != set(binding_urls):
        raise BindingError("candidate IDs and binding-url IDs must match exactly")

    volume_root = plan.get("volume_root")
    if not isinstance(volume_root, str) or not volume_root:
        raise BindingError("plan volume_root is required")
    surface = plan.get("surface")
    if not isinstance(surface, dict):
        raise BindingError("plan surface record is required")
    token = surface.get("volume_token")
    if not isinstance(token, str) or not token or token not in volume_root:
        raise BindingError("plan surface volume token is not bound to volume_root")
    reference_hashes = surface.get("hashes")
    if not isinstance(reference_hashes, dict):
        raise BindingError("plan surface hashes are required")

    zpa = plan.get("zpa_report")
    source_shape_raw = zpa.get("level0_shape_zyx") if isinstance(zpa, dict) else None
    if (
        not isinstance(source_shape_raw, list)
        or len(source_shape_raw) != 3
        or any(type(v) is not int or v <= 0 for v in source_shape_raw)
    ):
        raise BindingError("plan must retain positive ZPA level0_shape_zyx")
    source_shape = tuple(int(v) for v in source_shape_raw)

    protocol = plan.get("protocol")
    halo = protocol.get("halo_voxels") if isinstance(protocol, dict) else None
    if type(halo) is not int or halo < 1:
        raise BindingError("plan must retain a positive integer halo_voxels")

    prepared: dict[str, dict[str, Any]] = {}
    for cid in sorted(candidates):
        root = candidates[cid]
        if not root.is_dir():
            raise BindingError(f"candidate directory does not exist: {root}")
        points, normals, grid, info = _candidate_arrays(root)
        if not _volume_token_bound(root, info, token):
            raise BindingError(
                f"candidate {cid!r} does not bind to source-volume token {token!r}"
            )
        hashes = info.get("hashes")
        if not isinstance(hashes, dict):
            raise BindingError(f"candidate {cid!r} lacks coordinate hashes")
        if all(hashes.get(name) == reference_hashes.get(name) for name in ("x.tif", "y.tif", "z.tif")):
            raise BindingError(
                f"candidate {cid!r} is coordinate-identical to the reference surface"
            )
        prepared[cid] = {
            "root": root,
            "points_zyx": points,
            "normals_zyx": normals,
            "grid_yx": grid,
            "info": info,
        }

    bindings: list[dict[str, Any]] = []
    for group in plan["groups"]:
        gid = group.get("id")
        surface_zyx = np.asarray(group.get("surface_global_zyx"), dtype=np.float64)
        reference_normal = np.asarray(group.get("reference_normal_zyx"), dtype=np.float64)
        if surface_zyx.shape != (3,) or not np.isfinite(surface_zyx).all():
            raise BindingError(f"group {gid!r} has invalid surface_global_zyx")
        if reference_normal.shape != (3,) or not np.isfinite(reference_normal).all():
            raise BindingError(f"group {gid!r} has invalid reference_normal_zyx")
        n_norm = float(np.linalg.norm(reference_normal))
        if n_norm <= 0:
            raise BindingError(f"group {gid!r} has zero reference normal")
        reference_normal = reference_normal / n_norm

        best: tuple[tuple[float, float, str, int, int], dict[str, Any]] | None = None
        for cid in sorted(prepared):
            candidate = prepared[cid]
            points = candidate["points_zyx"]
            normals = candidate["normals_zyx"]
            grid = candidate["grid_yx"]

            delta = points - surface_zyx[None, :]
            signed_normal = delta @ reference_normal
            normal_sep = np.abs(signed_normal)
            total_sq = np.einsum("ij,ij->i", delta, delta)
            tangential_sq = np.maximum(0.0, total_sq - signed_normal**2)
            tangential = np.sqrt(tangential_sq)
            normal_cosine = np.abs(normals @ reference_normal)

            eligible = (
                (normal_sep >= min_normal_separation)
                & (normal_sep <= max_normal_separation)
                & (tangential <= max_tangential_distance)
                & (normal_cosine >= min_normal_abs_cosine)
            )
            for idx in np.flatnonzero(eligible):
                point = points[idx]
                expanded = _expanded_bbox(
                    group,
                    point,
                    halo=halo,
                    source_shape=source_shape,
                )
                if expanded is None:
                    continue
                y, x = (int(v) for v in grid[idx])
                key = (
                    float(normal_sep[idx]),
                    float(tangential[idx]),
                    cid,
                    y,
                    x,
                )
                record = {
                    "candidate_surface_id": cid,
                    "global_zyx": [float(v) for v in point],
                    "candidate_grid_yx": [y, x],
                    "normal_separation_voxels": float(normal_sep[idx]),
                    "signed_normal_separation_voxels": float(signed_normal[idx]),
                    "tangential_distance_voxels": float(tangential[idx]),
                    "candidate_reference_normal_abs_cosine": float(normal_cosine[idx]),
                    "cutout_bbox_zyx_half_open": expanded,
                }
                if best is None or key < best[0]:
                    best = (key, record)

        if best is None:
            raise BindingError(
                f"group {gid!r} has no independent competing-sheet candidate "
                "inside the frozen geometry criteria"
            )
        chosen = best[1]
        cid = chosen["candidate_surface_id"]
        candidate = prepared[cid]
        info = candidate["info"]
        chosen["source"] = {
            "surface_id": cid,
            "path": str(candidate["root"]),
            "binding_url": binding_urls[cid],
            "volume_token": token,
            "shape_yx": info.get("shape_yx"),
            "hashes": info.get("hashes"),
        }
        bindings.append({"group_id": gid, "wrong_wrap": chosen})

    candidate_records: list[dict[str, Any]] = []
    for cid in sorted(prepared):
        candidate = prepared[cid]
        info = candidate["info"]
        candidate_records.append(
            {
                "surface_id": cid,
                "path": str(candidate["root"]),
                "binding_url": binding_urls[cid],
                "volume_token": token,
                "shape_yx": info.get("shape_yx"),
                "valid_vertex_count": info.get("valid_vertex_count"),
                "hashes": info.get("hashes"),
            }
        )

    return {
        "schema": SCHEMA,
        "status": "bound",
        "plan": {
            "schema": PLAN_SCHEMA,
            "sha256": plan_file_sha256,
            "volume_root": volume_root,
            "reference_surface_hashes": reference_hashes,
        },
        "criteria": {
            "selection_algorithm": (
                "minimum-normal-separation-then-tangential-distance-v1; "
                "ties by candidate surface ID then grid Y,X"
            ),
            "min_normal_separation_voxels": float(min_normal_separation),
            "max_normal_separation_voxels": float(max_normal_separation),
            "max_tangential_distance_voxels": float(max_tangential_distance),
            "min_candidate_reference_normal_abs_cosine": float(min_normal_abs_cosine),
            "uses_ct_intensity": False,
            "uses_sheetness_response": False,
            "random_state": None,
        },
        "candidate_surfaces": candidate_records,
        "bindings": bindings,
        "complete": True,
        "claim_boundary": (
            "This artifact binds each frozen surface probe to nearby, roughly parallel "
            "geometry from a different hash-pinned TIFXYZ surface without consulting "
            "CT intensity or sheetness response. It provides competing-sheet ambiguity "
            "probes, not proof that either surface has the correct global winding."
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True)
    parser.add_argument(
        "--candidate",
        action="append",
        type=_parse_candidate,
        required=True,
        metavar="ID=PATH",
    )
    parser.add_argument(
        "--binding-url",
        action="append",
        type=_parse_binding_url,
        required=True,
        metavar="ID=URL",
    )
    parser.add_argument("--min-normal-separation", type=float, required=True)
    parser.add_argument("--max-normal-separation", type=float, required=True)
    parser.add_argument("--max-tangential-distance", type=float, required=True)
    parser.add_argument("--min-normal-cosine", type=float, required=True)
    parser.add_argument("--out", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    out = Path(args.out)
    if out.exists():
        print(
            json.dumps(
                {
                    "schema": SCHEMA,
                    "status": "invalid",
                    "error": f"refusing to overwrite {out}",
                }
            )
        )
        return 2

    try:
        plan_path = Path(args.plan)
        plan = _read_plan(plan_path)

        candidates: dict[str, Path] = {}
        for cid, raw_path in args.candidate:
            if cid in candidates:
                raise BindingError(f"duplicate candidate ID {cid!r}")
            candidates[cid] = Path(raw_path)

        urls: dict[str, str] = {}
        for cid, url in args.binding_url:
            if cid in urls:
                raise BindingError(f"duplicate binding-url ID {cid!r}")
            urls[cid] = url

        result = bind_wrong_wraps(
            plan=plan,
            plan_file_sha256=_sha256(plan_path),
            candidates=candidates,
            binding_urls=urls,
            min_normal_separation=args.min_normal_separation,
            max_normal_separation=args.max_normal_separation,
            max_tangential_distance=args.max_tangential_distance,
            min_normal_abs_cosine=args.min_normal_cosine,
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("x", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2, sort_keys=True)
            handle.write("\n")
    except (BindingError, OSError) as exc:
        print(json.dumps({"schema": SCHEMA, "status": "invalid", "error": str(exc)}))
        return 2

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
