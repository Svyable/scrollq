#!/usr/bin/env python3
"""Run the frozen PHerc0139 CT fiber-fingerprint development experiment."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import requests

from scrollq.fiber_fingerprint import (
    FiberFingerprintError,
    canonical_sha256,
    cosine_distance,
    descriptor_sha256,
    score_development,
    tangent_fiber_spectrum,
    tangent_frame,
    tangent_patch_coordinates,
)
from scrollq.sheetness_plan import _load_surface
from scrollq.support import ZarrV2Level
from scrollq.wrong_wrap_plan import _NearestSampler


SPEC_SCHEMA = "scrollq-research-fiber-fingerprint-dev/1"
RESULT_SCHEMA = "scrollq-research-fiber-fingerprint-dev-result/1"


class DevelopmentRunError(RuntimeError):
    pass


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DevelopmentRunError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise DevelopmentRunError(f"{path} must contain a JSON object")
    return value


def verify_spec(spec: dict[str, Any]) -> None:
    if spec.get("schema") != SPEC_SCHEMA:
        raise DevelopmentRunError(f"spec must be {SPEC_SCHEMA}")
    if spec.get("status") != "frozen-before-ct-texture-read":
        raise DevelopmentRunError("spec is not frozen before CT texture read")
    descriptor = spec.get("descriptor", {})
    if descriptor.get("name") != "tangent-fiber-spectrum-v1":
        raise DevelopmentRunError("unexpected descriptor name")
    sampling = spec.get("sampling", {})
    if sampling.get("interpolation") != (
        "nearest voxel using floor(coord+0.5), consistent with existing frozen geometry samplers"
    ):
        raise DevelopmentRunError("unexpected interpolation contract")
    if sampling.get("patch_shape_depth_v_u") != [5, 25, 25]:
        raise DevelopmentRunError("unexpected patch shape")
    if sampling.get("normal_offsets_voxels") != [-4, -2, 0, 2, 4]:
        raise DevelopmentRunError("unexpected normal offsets")
    if sampling.get("in_plane_offsets_voxels") != list(range(-12, 13)):
        raise DevelopmentRunError("unexpected in-plane offsets")
    if spec.get("reproducibility", {}).get("holdout_unread_until_separate_prereg") is not True:
        raise DevelopmentRunError("holdout firewall is not enabled")


def verify_surface_hashes(root: Path, expected: dict[str, Any]) -> dict[str, str]:
    required = {"meta.json", "x.tif", "y.tif", "z.tif"}
    if set(expected) != required:
        raise DevelopmentRunError("frozen TIFXYZ hash set must cover exactly four required files")
    observed = {}
    for name in sorted(required):
        path = root / name
        if not path.is_file():
            raise DevelopmentRunError(f"missing frozen TIFXYZ file {path}")
        digest = sha256_file(path)
        observed[name] = digest
        if digest != expected[name]:
            raise DevelopmentRunError(
                f"TIFXYZ hash mismatch for {name}: {digest} != {expected[name]}"
            )
    return observed


def _center_map(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = [
        *spec["split"]["development_centers"],
        *spec["split"]["holdout_centers"],
    ]
    out = {}
    for row in rows:
        gid = row["id"]
        if gid in out:
            raise DevelopmentRunError(f"duplicate frozen center id {gid}")
        out[gid] = row
    return out


def verify_reference_plan(
    spec: dict[str, Any],
    reference_plan_path: Path,
) -> tuple[dict[str, Any], str]:
    plan = load_json(reference_plan_path)
    if plan.get("schema") != "scroliq-sheetness-plan/1":
        raise DevelopmentRunError("reference plan schema mismatch")
    if plan.get("volume_root", "").strip("/") != spec["source"]["exact_ct_root"].strip("/"):
        raise DevelopmentRunError("reference plan exact CT root changed")
    groups = {
        row["id"]: row
        for row in plan.get("groups", [])
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    centers = _center_map(spec)
    for gid, frozen in centers.items():
        row = groups.get(gid)
        if row is None:
            raise DevelopmentRunError(f"reference plan missing {gid}")
        if [int(v) for v in row.get("grid_yx", [])] != [
            int(v) for v in frozen["grid_yx"]
        ]:
            raise DevelopmentRunError(f"grid_yx changed for {gid}")
    return plan, sha256_file(reference_plan_path)


def verify_wrong_wraps(
    spec: dict[str, Any],
    wrong_wrap_result_path: Path,
) -> str:
    result = load_json(wrong_wrap_result_path)
    if result.get("schema") != "scroliq-wrong-wrap-plan/1":
        raise DevelopmentRunError("wrong-wrap result schema mismatch")
    groups = {
        row["id"]: row
        for row in result.get("groups", [])
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    for gid, frozen in _center_map(spec).items():
        row = groups.get(gid)
        if row is None or row.get("status") != "found":
            raise DevelopmentRunError(f"wrong-wrap control missing for {gid}")
        actual = np.asarray(row.get("global_zyx"), dtype=np.float64)
        expected = np.asarray(frozen["wrong_wrap_zyx"], dtype=np.float64)
        if actual.shape != (3,) or not np.allclose(actual, expected, atol=1e-12, rtol=0):
            raise DevelopmentRunError(f"wrong-wrap coordinate changed for {gid}")
        if float(row.get("signed_distance_voxels")) != float(
            frozen["wrong_wrap_signed_distance_voxels"]
        ):
            raise DevelopmentRunError(f"wrong-wrap signed distance changed for {gid}")
    return sha256_file(wrong_wrap_result_path)


def _descriptor(
    sampler: _NearestSampler,
    *,
    center_xyz: np.ndarray,
    x_axis: np.ndarray,
    y_axis: np.ndarray,
    normal: np.ndarray,
    spec: dict[str, Any],
) -> tuple[np.ndarray | None, dict[str, Any]]:
    sampling = spec["sampling"]
    before_missing = set(sampler.missing_chunks)
    coords_xyz = tangent_patch_coordinates(
        center_xyz,
        x_axis,
        y_axis,
        normal,
        in_plane_offsets=sampling["in_plane_offsets_voxels"],
        normal_offsets=sampling["normal_offsets_voxels"],
    )
    flat_zyx = coords_xyz.reshape(-1, 3)[:, ::-1]
    values, in_bounds = sampler.sample(flat_zyx)
    new_missing = sorted(set(sampler.missing_chunks) - before_missing)
    shape = tuple(int(v) for v in sampling["patch_shape_depth_v_u"])
    info = {
        "sample_count": int(values.size),
        "in_bounds_count": int(in_bounds.sum()),
        "new_missing_chunks": [list(v) for v in new_missing],
    }
    if not bool(in_bounds.all()):
        return None, {**info, "status": "invalid", "reason": "out-of-bounds sample"}
    if new_missing:
        return None, {**info, "status": "invalid", "reason": "missing CT chunk"}

    nonzero_fraction = float(np.mean(values > 0))
    info["nonzero_fraction"] = nonzero_fraction
    if nonzero_fraction < float(sampling["minimum_nonzero_fraction"]):
        return None, {
            **info,
            "status": "invalid",
            "reason": "nonzero fraction below frozen minimum",
        }
    patch = values.reshape(shape)
    try:
        vector = tangent_fiber_spectrum(patch)
    except FiberFingerprintError as exc:
        return None, {**info, "status": "invalid", "reason": str(exc)}
    return vector, {
        **info,
        "status": "ok",
        "descriptor_length": int(vector.size),
        "descriptor_sha256": descriptor_sha256(vector),
    }


def measure_group(
    *,
    frozen: dict[str, Any],
    xyz: np.ndarray,
    valid: np.ndarray,
    sampler: _NearestSampler,
    spec: dict[str, Any],
) -> dict[str, Any]:
    gid = str(frozen["id"])
    y, x = (int(v) for v in frozen["grid_yx"])
    try:
        center_xyz, x_axis, y_axis, normal = tangent_frame(xyz, valid, y, x)
    except FiberFingerprintError as exc:
        return {"id": gid, "status": "unusable", "reason": str(exc)}

    center_desc, center_info = _descriptor(
        sampler,
        center_xyz=center_xyz,
        x_axis=x_axis,
        y_axis=y_axis,
        normal=normal,
        spec=spec,
    )
    if center_desc is None:
        return {
            "id": gid,
            "status": "unusable",
            "reason": "center descriptor invalid",
            "center": center_info,
        }

    neighbor_rows = []
    neighbor_vectors = []
    for dy, dx in spec["same_sheet_controls"]["material_grid_offsets_yx"]:
        ny, nx = y + int(dy), x + int(dx)
        row = {"grid_yx": [ny, nx], "offset_yx": [int(dy), int(dx)]}
        try:
            nxyz, nx_axis, ny_axis, nnormal = tangent_frame(xyz, valid, ny, nx)
            vector, info = _descriptor(
                sampler,
                center_xyz=nxyz,
                x_axis=nx_axis,
                y_axis=ny_axis,
                normal=nnormal,
                spec=spec,
            )
        except FiberFingerprintError as exc:
            vector = None
            info = {"status": "invalid", "reason": str(exc)}
        if vector is not None:
            neighbor_vectors.append(vector)
            row["distance_to_center"] = cosine_distance(center_desc, vector)
        else:
            row["distance_to_center"] = None
        row["descriptor"] = info
        neighbor_rows.append(row)

    minimum_neighbors = int(
        spec["same_sheet_controls"]["minimum_usable_neighbors_per_group"]
    )
    if len(neighbor_vectors) < minimum_neighbors:
        return {
            "id": gid,
            "status": "unusable",
            "reason": "too few usable same-sheet neighbors",
            "center": center_info,
            "neighbors": neighbor_rows,
        }

    wrong_xyz = np.asarray(frozen["wrong_wrap_zyx"], dtype=np.float64)[::-1]
    wrong_desc, wrong_info = _descriptor(
        sampler,
        center_xyz=wrong_xyz,
        x_axis=x_axis,
        y_axis=y_axis,
        normal=normal,
        spec=spec,
    )
    if wrong_desc is None:
        return {
            "id": gid,
            "status": "unusable",
            "reason": "wrong-wrap descriptor invalid",
            "center": center_info,
            "neighbors": neighbor_rows,
            "wrong_wrap": wrong_info,
        }

    references = [center_desc, *neighbor_vectors]
    wrong_distances = [cosine_distance(wrong_desc, ref) for ref in references]
    positive_distances = [
        float(row["distance_to_center"])
        for row in neighbor_rows
        if row["distance_to_center"] is not None
    ]
    return {
        "id": gid,
        "status": "usable",
        "grid_yx": [y, x],
        "wrong_wrap_zyx": [float(v) for v in frozen["wrong_wrap_zyx"]],
        "center": center_info,
        "neighbors": neighbor_rows,
        "usable_neighbor_count": len(neighbor_vectors),
        "positive_distances": positive_distances,
        "wrong_wrap": wrong_info,
        "wrong_wrap_reference_distances": wrong_distances,
        "wrong_wrap_score": float(min(wrong_distances)),
    }


def run(
    *,
    spec_path: Path,
    tifxyz_root: Path,
    reference_plan_path: Path,
    wrong_wrap_result_path: Path,
) -> dict[str, Any]:
    spec = load_json(spec_path)
    verify_spec(spec)
    surface_hashes = verify_surface_hashes(
        tifxyz_root, spec["source"]["tifxyz_sha256"]
    )
    plan, reference_plan_sha = verify_reference_plan(spec, reference_plan_path)
    wrong_wrap_sha = verify_wrong_wraps(spec, wrong_wrap_result_path)

    xyz, valid, surface_info = _load_surface(tifxyz_root)
    if surface_info["hashes"]["x.tif"] != surface_hashes["x.tif"]:
        raise DevelopmentRunError("surface loader observed unexpected TIFXYZ bytes")

    expected_dev = list(spec["split"]["development_ids"])
    expected_holdout = set(spec["split"]["holdout_ids"])
    actual_dev = [row["id"] for row in spec["split"]["development_centers"]]
    if actual_dev != expected_dev:
        raise DevelopmentRunError("development center order does not match frozen ids")
    if expected_holdout.intersection(actual_dev):
        raise DevelopmentRunError("development/holdout split overlaps")

    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(pool_maxsize=8)
    session.mount("https://", adapter)
    ct = ZarrV2Level(spec["source"]["ct_url"].rstrip("/") + "/0", session)
    expected_shape = tuple(int(v) for v in plan["zpa_report"]["level0_shape_zyx"])
    if tuple(ct.shape) != expected_shape:
        raise DevelopmentRunError(
            f"exact CT shape changed: {ct.shape} != {expected_shape}"
        )
    sampler = _NearestSampler(ct)

    groups = []
    sampled_ids = []
    for frozen in spec["split"]["development_centers"]:
        gid = str(frozen["id"])
        if gid in expected_holdout:
            raise DevelopmentRunError(f"holdout firewall violation: {gid}")
        sampled_ids.append(gid)
        groups.append(
            measure_group(
                frozen=frozen,
                xyz=xyz,
                valid=valid,
                sampler=sampler,
                spec=spec,
            )
        )

    if set(sampled_ids).intersection(expected_holdout):
        raise DevelopmentRunError("holdout CT descriptor was sampled")

    gate = spec["development_gate"]
    decision = score_development(
        groups,
        quantile=0.95,
        required_usable_groups=int(gate["required_usable_groups"]),
        required_positive_pairs=int(gate["required_pooled_positive_pairs"]),
        minimum_wrong_wrap_rejection_fraction=float(
            gate["minimum_wrong_wrap_rejection_fraction"]
        ),
        minimum_median_wrong_to_positive_distance_ratio=float(
            gate["minimum_median_wrong_to_positive_distance_ratio"]
        ),
        require_median_wrong_distance_above_threshold=bool(
            gate["require_median_wrong_distance_above_threshold"]
        ),
    )

    return {
        "schema": RESULT_SCHEMA,
        "status": "measured",
        "spec": {
            "path": str(spec_path),
            "sha256": sha256_file(spec_path),
            "canonical_sha256": canonical_sha256(spec),
        },
        "inputs": {
            "reference_plan_path": str(reference_plan_path),
            "reference_plan_sha256": reference_plan_sha,
            "wrong_wrap_result_path": str(wrong_wrap_result_path),
            "wrong_wrap_result_sha256": wrong_wrap_sha,
            "tifxyz_sha256": surface_hashes,
            "exact_ct_root": spec["source"]["exact_ct_root"],
            "ct_url": spec["source"]["ct_url"],
            "ct_level0_shape_zyx": list(ct.shape),
            "missing_ct_chunks": [list(v) for v in sorted(sampler.missing_chunks)],
        },
        "firewall": {
            "sampled_development_ids": sampled_ids,
            "holdout_ids": list(spec["split"]["holdout_ids"]),
            "holdout_descriptor_reads": 0,
        },
        "groups": groups,
        "decision": {
            **decision,
            "classification_after_development": (
                "FREEZE THRESHOLD FOR HOLDOUT"
                if decision["status"] == "pass"
                else "DISMISS tangent-fiber-spectrum-v1"
            ),
            "claim_boundary": spec["claim_boundary"],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--tifxyz", required=True)
    parser.add_argument("--reference-plan", required=True)
    parser.add_argument("--wrong-wrap-result", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    out = Path(args.out)
    if out.exists():
        raise SystemExit(f"refusing to overwrite {out}")
    result = run(
        spec_path=Path(args.spec),
        tifxyz_root=Path(args.tifxyz),
        reference_plan_path=Path(args.reference_plan),
        wrong_wrap_result_path=Path(args.wrong_wrap_result),
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps({
        "status": result["status"],
        "scientific_decision": result["decision"]["status"],
        "threshold": result["decision"]["threshold"],
        "usable_groups": result["decision"]["usable_group_count"],
        "positive_pairs": result["decision"]["pooled_positive_pair_count"],
        "wrong_wrap_rejection_fraction": result["decision"]["wrong_wrap_rejection_fraction"],
        "median_wrong_to_positive_ratio": result["decision"]["median_wrong_to_positive_distance_ratio"],
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
