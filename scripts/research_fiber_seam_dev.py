#!/usr/bin/env python3
"""Run the frozen PHerc0139 cross-ply seam development experiment."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import requests

from scrollq.fiber_fingerprint import FiberFingerprintError, tangent_frame, tangent_patch_coordinates
from scrollq.fiber_frame import analyze_slab
from scrollq.fiber_seam import FiberSeamError, score_development, seam_metrics, stitch_half_slabs
from scrollq.sheetness_plan import _load_surface
from scrollq.support import ZarrV2Level
from scrollq.wrong_wrap_plan import _NearestSampler

SPEC_SCHEMA = "scrollq-research-fiber-seam-dev/1"
SOURCE_SPEC_SCHEMA = "scrollq-research-fiber-fingerprint-dev/1"
RESULT_SCHEMA = "scrollq-research-fiber-seam-dev-result/1"


class SeamRunError(RuntimeError):
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
        raise SeamRunError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SeamRunError(f"{path} must contain a JSON object")
    return value


def verify_spec(spec: dict[str, Any]) -> None:
    if spec.get("schema") != SPEC_SCHEMA:
        raise SeamRunError(f"spec must be {SPEC_SCHEMA}")
    if spec.get("status") != "frozen-after-spectrum-v1-fail-before-cross-ply-frame-read":
        raise SeamRunError("spec is not frozen before cross-ply frame read")
    if spec.get("reproducibility", {}).get("holdout_unread_until_separate_prereg") is not True:
        raise SeamRunError("holdout firewall is not enabled")
    sampling = spec.get("sampling", {})
    if sampling.get("slab_shape_depth_y_x") != [9, 64, 64]:
        raise SeamRunError("unexpected frozen slab shape")
    if sampling.get("normal_offsets_voxels") != list(range(-4, 5)):
        raise SeamRunError("unexpected frozen normal offsets")
    if sampling.get("in_plane_offsets_voxels") != list(range(-32, 32)):
        raise SeamRunError("unexpected frozen in-plane offsets")
    params = spec.get("analyzer", {}).get("parameters", {})
    expected = {
        "tile_size": 16,
        "sigma": 1,
        "min_coherence": 0.35,
        "min_separation_degrees": 25,
        "min_mode_share": 0.15,
        "switch_degrees": 25,
    }
    if params != expected:
        raise SeamRunError(f"frozen analyzer parameters changed: {params!r}")


def verify_surface_hashes(root: Path, expected: dict[str, Any]) -> dict[str, str]:
    required = {"meta.json", "x.tif", "y.tif", "z.tif"}
    if set(expected) != required:
        raise SeamRunError("frozen TIFXYZ hash set must cover exactly meta/x/y/z")
    observed: dict[str, str] = {}
    for name in sorted(required):
        path = root / name
        if not path.is_file():
            raise SeamRunError(f"missing frozen TIFXYZ file {path}")
        digest = sha256_file(path)
        observed[name] = digest
        if digest != expected[name]:
            raise SeamRunError(f"TIFXYZ hash mismatch for {name}: {digest} != {expected[name]}")
    return observed


def verify_source_spec(
    seam_spec: dict[str, Any],
    source_spec_path: Path,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], str]:
    source_spec = load_json(source_spec_path)
    if source_spec.get("schema") != SOURCE_SPEC_SCHEMA:
        raise SeamRunError("center source spec schema mismatch")
    digest = sha256_file(source_spec_path)
    frozen = seam_spec.get("split", {}).get("center_source_spec_sha256")
    if digest != frozen:
        raise SeamRunError(f"center source spec hash changed: {digest} != {frozen}")
    if source_spec.get("source", {}).get("exact_ct_root") != seam_spec.get("source", {}).get("exact_ct_root"):
        raise SeamRunError("center source exact CT root changed")
    if source_spec.get("source", {}).get("tifxyz") != seam_spec.get("source", {}).get("tifxyz"):
        raise SeamRunError("center source TIFXYZ identity changed")

    split = seam_spec["split"]
    if source_spec.get("split", {}).get("development_ids") != split.get("development_ids"):
        raise SeamRunError("development IDs changed from frozen center source")
    if source_spec.get("split", {}).get("holdout_ids") != split.get("holdout_ids"):
        raise SeamRunError("holdout IDs changed from frozen center source")

    rows = source_spec["split"].get("development_centers")
    if not isinstance(rows, list):
        raise SeamRunError("center source development_centers missing")
    centers = {str(row["id"]): row for row in rows if isinstance(row, dict) and row.get("id")}
    if list(centers) != list(split["development_ids"]):
        raise SeamRunError("center source development-center order changed")
    return source_spec, centers, digest


def verify_reference_plan(
    seam_spec: dict[str, Any],
    source_spec: dict[str, Any],
    reference_plan_path: Path,
) -> tuple[dict[str, Any], str]:
    plan = load_json(reference_plan_path)
    if plan.get("schema") != "scroliq-sheetness-plan/1":
        raise SeamRunError("reference plan schema mismatch")
    if plan.get("volume_root", "").strip("/") != seam_spec["source"]["exact_ct_root"].strip("/"):
        raise SeamRunError("reference plan exact CT root changed")
    expected_path = source_spec.get("provenance", {}).get("reference_plan_path")
    if expected_path and Path(expected_path).as_posix() != reference_plan_path.as_posix():
        raise SeamRunError("reference plan path changed from frozen source spec")
    groups = {
        str(row["id"]): row
        for row in plan.get("groups", [])
        if isinstance(row, dict) and row.get("id")
    }
    source_centers = source_spec["split"]["development_centers"]
    for center in source_centers:
        gid = str(center["id"])
        row = groups.get(gid)
        if row is None:
            raise SeamRunError(f"reference plan missing {gid}")
        if [int(v) for v in row.get("grid_yx", [])] != [int(v) for v in center["grid_yx"]]:
            raise SeamRunError(f"reference plan grid changed for {gid}")
    return plan, sha256_file(reference_plan_path)


def sample_slab(
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
    info: dict[str, Any] = {
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
    shape = tuple(int(v) for v in sampling["slab_shape_depth_y_x"])
    if values.size != int(np.prod(shape)):
        raise SeamRunError("sample count does not match frozen slab shape")
    return values.reshape(shape), {**info, "status": "ok"}


def measure_group(
    *,
    center: dict[str, Any],
    xyz: np.ndarray,
    valid: np.ndarray,
    sampler: _NearestSampler,
    spec: dict[str, Any],
) -> dict[str, Any]:
    gid = str(center["id"])
    y, x = (int(v) for v in center["grid_yx"])
    try:
        target_xyz, x_axis, y_axis, normal = tangent_frame(xyz, valid, y, x)
    except FiberFingerprintError as exc:
        return {"id": gid, "status": "unusable", "reason": str(exc), "variants": {}}

    target, target_info = sample_slab(
        sampler,
        center_xyz=target_xyz,
        x_axis=x_axis,
        y_axis=y_axis,
        normal=normal,
        spec=spec,
    )
    if target is None:
        return {
            "id": gid,
            "status": "unusable",
            "reason": "target source slab invalid",
            "target_slab": target_info,
            "variants": {},
        }

    wrong_xyz = np.asarray(center["wrong_wrap_zyx"], dtype=np.float64)[::-1]
    wrong, wrong_info = sample_slab(
        sampler,
        center_xyz=wrong_xyz,
        x_axis=x_axis,
        y_axis=y_axis,
        normal=normal,
        spec=spec,
    )
    if wrong is None:
        return {
            "id": gid,
            "status": "unusable",
            "reason": "wrong-wrap source slab invalid",
            "target_slab": target_info,
            "wrong_wrap_slab": wrong_info,
            "variants": {},
        }

    params = spec["analyzer"]["parameters"]
    variants_out: dict[str, Any] = {}
    for name, slab in stitch_half_slabs(target, wrong).items():
        analysis = analyze_slab(
            slab,
            tile_size=int(params["tile_size"]),
            sigma=float(params["sigma"]),
            min_coherence=float(params["min_coherence"]),
            min_separation_degrees=float(params["min_separation_degrees"]),
            min_mode_share=float(params["min_mode_share"]),
            switch_degrees=float(params["switch_degrees"]),
        )
        seam = seam_metrics(
            analysis,
            switch_degrees=float(params["switch_degrees"]),
            minimum_valid_comparisons=3,
            minimum_flagged_comparisons=2,
        )
        variants_out[name] = {
            **seam,
            "analysis_status": analysis["status"],
            "analysis_coverage": analysis["coverage"],
            "frames": analysis["frames"],
        }

    usable = all(row.get("status") == "measured" for row in variants_out.values())
    return {
        "id": gid,
        "status": "usable" if usable else "unusable",
        "reason": None if usable else "one or more variants lacks three recoverable frozen seam comparisons",
        "grid_yx": [y, x],
        "wrong_wrap_zyx": [float(v) for v in center["wrong_wrap_zyx"]],
        "target_slab": target_info,
        "wrong_wrap_slab": wrong_info,
        "variants": variants_out,
    }


def run(
    *,
    spec_path: Path,
    source_spec_path: Path,
    tifxyz_root: Path,
    reference_plan_path: Path,
) -> dict[str, Any]:
    spec = load_json(spec_path)
    verify_spec(spec)
    source_spec, centers, source_spec_sha = verify_source_spec(spec, source_spec_path)
    plan, reference_plan_sha = verify_reference_plan(spec, source_spec, reference_plan_path)
    surface_hashes = verify_surface_hashes(tifxyz_root, spec["source"]["tifxyz_sha256"])

    xyz, valid, surface_info = _load_surface(tifxyz_root)
    if surface_info["hashes"]["x.tif"] != surface_hashes["x.tif"]:
        raise SeamRunError("surface loader observed unexpected TIFXYZ bytes")

    development_ids = list(spec["split"]["development_ids"])
    holdout_ids = set(spec["split"]["holdout_ids"])
    if holdout_ids.intersection(development_ids):
        raise SeamRunError("development/holdout split overlaps")
    if list(centers) != development_ids:
        raise SeamRunError("development-center order differs from frozen split")

    session = requests.Session()
    session.mount("https://", requests.adapters.HTTPAdapter(pool_maxsize=8))
    ct = ZarrV2Level(spec["source"]["ct_url"].rstrip("/") + "/0", session)
    expected_shape = tuple(int(v) for v in plan["zpa_report"]["level0_shape_zyx"])
    if tuple(ct.shape) != expected_shape:
        raise SeamRunError(f"exact CT shape changed: {ct.shape} != {expected_shape}")
    sampler = _NearestSampler(ct)

    groups = []
    sampled_ids = []
    for gid in development_ids:
        if gid in holdout_ids:
            raise SeamRunError(f"holdout firewall violation: {gid}")
        sampled_ids.append(gid)
        groups.append(
            measure_group(
                center=centers[gid],
                xyz=xyz,
                valid=valid,
                sampler=sampler,
                spec=spec,
            )
        )

    if holdout_ids.intersection(sampled_ids):
        raise SeamRunError("holdout CT slab was sampled")

    gate = spec["development_gate"]
    decision = score_development(
        groups,
        frozen_group_count=len(development_ids),
        required_usable_groups=int(gate["required_usable_groups"]),
        maximum_intact_false_positive_fraction=float(
            gate["maximum_intact_false_positive_fraction"]
        ),
        minimum_target_left_wrong_right_detection_fraction=float(
            gate["minimum_target_left_wrong_right_detection_fraction"]
        ),
        minimum_wrong_left_target_right_detection_fraction=float(
            gate["minimum_wrong_left_target_right_detection_fraction"]
        ),
        minimum_pooled_seam_comparison_coverage_fraction_each_variant=float(
            gate["minimum_pooled_seam_comparison_coverage_fraction_each_variant"]
        ),
    )

    return {
        "schema": RESULT_SCHEMA,
        "status": "measured",
        "spec": {
            "path": str(spec_path),
            "sha256": sha256_file(spec_path),
        },
        "inputs": {
            "center_source_spec": {
                "path": str(source_spec_path),
                "sha256": source_spec_sha,
            },
            "reference_plan": {
                "path": str(reference_plan_path),
                "sha256": reference_plan_sha,
            },
            "tifxyz_sha256": surface_hashes,
            "exact_ct_root": spec["source"]["exact_ct_root"],
            "ct_url": spec["source"]["ct_url"],
            "ct_level0_shape_zyx": list(ct.shape),
            "ct_level0_chunks_zyx": list(ct.chunks),
            "missing_ct_chunks": [list(v) for v in sorted(sampler.missing_chunks)],
        },
        "firewall": {
            "sampled_development_ids": sampled_ids,
            "holdout_ids": list(spec["split"]["holdout_ids"]),
            "holdout_ct_reads": 0,
        },
        "groups": groups,
        "decision": {
            **decision,
            "classification_after_development": (
                "FREEZE UNCHANGED CROSS-PLY SEAM CONTRACT FOR HOLDOUT"
                if decision["status"] == "pass"
                else "DISMISS cross-ply-seam-v1"
            ),
            "claim_boundary": spec["claim_boundary"],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--source-spec", required=True)
    parser.add_argument("--tifxyz", required=True)
    parser.add_argument("--reference-plan", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    out = Path(args.out)
    if out.exists():
        raise SystemExit(f"refusing to overwrite {out}")
    result = run(
        spec_path=Path(args.spec),
        source_spec_path=Path(args.source_spec),
        tifxyz_root=Path(args.tifxyz),
        reference_plan_path=Path(args.reference_plan),
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps({
        "status": result["status"],
        "scientific_decision": result["decision"]["status"],
        "usable_groups": result["decision"]["usable_group_count"],
        "intact_false_positive_fraction": result["decision"]["intact_false_positive_fraction"],
        "target_left_wrong_right_detection_fraction": result["decision"]["target_left_wrong_right_detection_fraction"],
        "wrong_left_target_right_detection_fraction": result["decision"]["wrong_left_target_right_detection_fraction"],
        "pooled_seam_comparison_coverage_fraction": result["decision"]["pooled_seam_comparison_coverage_fraction"],
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
