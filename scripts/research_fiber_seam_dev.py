#!/usr/bin/env python3
"""Run the frozen PHerc0139 cross-ply seam substitution development experiment."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import requests

from scrollq.fiber_fingerprint import tangent_frame, tangent_patch_coordinates
from scrollq.fiber_frame import analyze_slab
from scrollq.fiber_seam import score_development, seam_metrics, stitch_half_slabs
from scrollq.sheetness_plan import _load_surface
from scrollq.support import ZarrV2Level
from scrollq.wrong_wrap_plan import _NearestSampler


SPEC_SCHEMA = "scrollq-research-fiber-seam-dev/1"
RESULT_SCHEMA = "scrollq-research-fiber-seam-dev-result/1"


class SeamRunError(RuntimeError):
    pass


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


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
    if spec.get("status") != (
        "frozen-after-spectrum-v1-fail-before-cross-ply-frame-read"
    ):
        raise SeamRunError("seam spec is not in the frozen pre-observation state")
    split = spec.get("split", {})
    dev = split.get("development_ids")
    hold = split.get("holdout_ids")
    if not isinstance(dev, list) or len(dev) != 10 or len(set(dev)) != 10:
        raise SeamRunError("development split must contain ten unique ids")
    if not isinstance(hold, list) or len(hold) != 10 or len(set(hold)) != 10:
        raise SeamRunError("holdout split must contain ten unique ids")
    if set(dev) & set(hold):
        raise SeamRunError("development and holdout splits overlap")
    sampling = spec.get("sampling", {})
    if sampling.get("slab_shape_depth_y_x") != [9, 64, 64]:
        raise SeamRunError("unexpected frozen slab shape")
    if sampling.get("normal_offsets_voxels") != list(range(-4, 5)):
        raise SeamRunError("unexpected frozen normal offsets")
    if sampling.get("in_plane_offsets_voxels") != list(range(-32, 32)):
        raise SeamRunError("unexpected frozen in-plane offsets")
    params = spec.get("analyzer", {}).get("parameters")
    expected = {
        "tile_size": 16,
        "sigma": 1.0,
        "min_coherence": 0.35,
        "min_separation_degrees": 25.0,
        "min_mode_share": 0.15,
        "switch_degrees": 25.0,
    }
    if params != expected:
        raise SeamRunError("frozen fiber-frame parameters changed")


def verify_surface_hashes(root: Path, expected: dict[str, Any]) -> dict[str, str]:
    names = {"meta.json", "x.tif", "y.tif", "z.tif"}
    if set(expected) != names:
        raise SeamRunError("TIFXYZ hash set must cover exactly meta/x/y/z")
    observed: dict[str, str] = {}
    for name in sorted(names):
        path = root / name
        if not path.is_file():
            raise SeamRunError(f"missing TIFXYZ file {path}")
        digest = sha256_file(path)
        observed[name] = digest
        if digest != expected[name]:
            raise SeamRunError(
                f"TIFXYZ hash mismatch for {name}: {digest} != {expected[name]}"
            )
    return observed


def load_center_source(
    spec: dict[str, Any],
    source_spec_path: Path,
    fingerprint_result_path: Path,
    wrong_wrap_result_path: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, str]]:
    expected_sha = spec["split"]["center_source_spec_sha256"]
    source_sha = sha256_file(source_spec_path)
    if source_sha != expected_sha:
        raise SeamRunError(
            f"center source spec changed: {source_sha} != {expected_sha}"
        )
    source = load_json(source_spec_path)
    if source.get("schema") != "scrollq-research-fiber-fingerprint-dev/1":
        raise SeamRunError("center source spec schema mismatch")
    if source.get("source", {}).get("exact_ct_root") != spec["source"]["exact_ct_root"]:
        raise SeamRunError("center source exact CT root differs from seam spec")
    if source.get("split", {}).get("development_ids") != spec["split"]["development_ids"]:
        raise SeamRunError("development ids differ from frozen source spec")
    if source.get("split", {}).get("holdout_ids") != spec["split"]["holdout_ids"]:
        raise SeamRunError("holdout ids differ from frozen source spec")

    result = load_json(fingerprint_result_path)
    if result.get("schema") != "scrollq-research-fiber-fingerprint-dev-result/1":
        raise SeamRunError("fingerprint development result schema mismatch")
    if result.get("decision", {}).get("status") != "fail":
        raise SeamRunError("seam experiment requires the recorded spectrum-v1 FAIL")
    if result.get("spec", {}).get("sha256") != expected_sha:
        raise SeamRunError("fingerprint result is not bound to the frozen source spec")
    if result.get("firewall", {}).get("holdout_descriptor_reads") != 0:
        raise SeamRunError("fingerprint result does not preserve the holdout firewall")

    wrong = load_json(wrong_wrap_result_path)
    if wrong.get("schema") != "scroliq-wrong-wrap-plan/1":
        raise SeamRunError("wrong-wrap result schema mismatch")
    wrong_by_id = {
        row.get("id"): row
        for row in wrong.get("groups", [])
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }

    centers = source["split"]["development_centers"]
    if [row["id"] for row in centers] != spec["split"]["development_ids"]:
        raise SeamRunError("development-center order differs from seam preregistration")
    for frozen in centers:
        gid = frozen["id"]
        row = wrong_by_id.get(gid)
        if row is None or row.get("status") != "found":
            raise SeamRunError(f"missing wrong-wrap control for {gid}")
        actual = np.asarray(row.get("global_zyx"), dtype=np.float64)
        expected = np.asarray(frozen["wrong_wrap_zyx"], dtype=np.float64)
        if actual.shape != (3,) or not np.allclose(actual, expected, atol=1e-12, rtol=0):
            raise SeamRunError(f"wrong-wrap coordinate changed for {gid}")
        if float(row.get("signed_distance_voxels")) != float(
            frozen["wrong_wrap_signed_distance_voxels"]
        ):
            raise SeamRunError(f"wrong-wrap signed distance changed for {gid}")

    return centers, result, {
        "center_source_spec_sha256": source_sha,
        "fingerprint_result_sha256": sha256_file(fingerprint_result_path),
        "wrong_wrap_result_sha256": sha256_file(wrong_wrap_result_path),
    }


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
    values, in_bounds = sampler.sample(coords_xyz.reshape(-1, 3)[:, ::-1])
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
    nonzero = float(np.mean(values > 0))
    info["nonzero_fraction"] = nonzero
    if nonzero < float(sampling["minimum_nonzero_fraction"]):
        return None, {
            **info,
            "status": "invalid",
            "reason": "nonzero fraction below frozen minimum",
        }
    shape = tuple(int(v) for v in sampling["slab_shape_depth_y_x"])
    return values.reshape(shape), {**info, "status": "ok"}


def analyze_variant(slab: np.ndarray, spec: dict[str, Any]) -> dict[str, Any]:
    params = spec["analyzer"]["parameters"]
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
        seam_rows=range(4),
        left_tile_x=1,
        right_tile_x=2,
        switch_degrees=float(params["switch_degrees"]),
        minimum_valid_comparisons=3,
        minimum_flagged_comparisons=2,
    )
    return {
        "analysis": analysis,
        **seam,
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
    except Exception as exc:
        return {"id": gid, "status": "unusable", "reason": f"frame: {exc}", "variants": {}}

    target, target_info = sample_slab(
        sampler,
        center_xyz=center_xyz,
        x_axis=x_axis,
        y_axis=y_axis,
        normal=normal,
        spec=spec,
    )
    wrong_xyz = np.asarray(frozen["wrong_wrap_zyx"], dtype=np.float64)[::-1]
    wrong, wrong_info = sample_slab(
        sampler,
        center_xyz=wrong_xyz,
        x_axis=x_axis,
        y_axis=y_axis,
        normal=normal,
        spec=spec,
    )
    if target is None or wrong is None:
        return {
            "id": gid,
            "status": "unusable",
            "reason": "target or wrong-wrap source slab invalid",
            "target_source": target_info,
            "wrong_wrap_source": wrong_info,
            "variants": {},
        }

    variants = stitch_half_slabs(target, wrong)
    reports = {name: analyze_variant(slab, spec) for name, slab in variants.items()}
    usable = all(row["status"] == "measured" for row in reports.values())
    return {
        "id": gid,
        "grid_yx": [y, x],
        "wrong_wrap_zyx": [float(v) for v in frozen["wrong_wrap_zyx"]],
        "status": "usable" if usable else "unusable",
        "reason": None if usable else "one or more seam variants lacked three recoverable comparisons",
        "target_source": target_info,
        "wrong_wrap_source": wrong_info,
        "variants": reports,
    }


def run(
    *,
    spec_path: Path,
    source_spec_path: Path,
    fingerprint_result_path: Path,
    wrong_wrap_result_path: Path,
    tifxyz_root: Path,
) -> dict[str, Any]:
    spec = load_json(spec_path)
    verify_spec(spec)
    centers, fingerprint_result, upstream_hashes = load_center_source(
        spec, source_spec_path, fingerprint_result_path, wrong_wrap_result_path
    )
    surface_hashes = verify_surface_hashes(tifxyz_root, spec["source"]["tifxyz_sha256"])
    xyz, valid, surface_info = _load_surface(tifxyz_root)
    if surface_info["hashes"]["x.tif"] != surface_hashes["x.tif"]:
        raise SeamRunError("surface loader observed unexpected TIFXYZ bytes")

    session = requests.Session()
    session.mount("https://", requests.adapters.HTTPAdapter(pool_maxsize=8))
    ct = ZarrV2Level(spec["source"]["ct_url"].rstrip("/") + "/0", session)
    prior_shape = tuple(
        int(v) for v in fingerprint_result["inputs"]["ct_level0_shape_zyx"]
    )
    if tuple(ct.shape) != prior_shape:
        raise SeamRunError(
            f"exact CT grid changed relative to the prior bound run: {ct.shape} != {prior_shape}"
        )
    sampler = _NearestSampler(ct)

    holdout = set(spec["split"]["holdout_ids"])
    groups = []
    sampled_ids = []
    for frozen in centers:
        gid = str(frozen["id"])
        if gid in holdout:
            raise SeamRunError(f"holdout firewall violation: {gid}")
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

    gate = spec["development_gate"]
    decision = score_development(
        groups,
        frozen_group_count=10,
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
        "spec": {"path": str(spec_path), "sha256": sha256_file(spec_path)},
        "inputs": {
            **upstream_hashes,
            "tifxyz_sha256": surface_hashes,
            "ct_url": spec["source"]["ct_url"],
            "ct_level0_shape_zyx": list(ct.shape),
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
                "FREEZE cross-ply-seam-v1 FOR HOLDOUT"
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
    parser.add_argument("--fingerprint-result", required=True)
    parser.add_argument("--wrong-wrap-result", required=True)
    parser.add_argument("--tifxyz", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    out = Path(args.out)
    if out.exists():
        raise SystemExit(f"refusing to overwrite {out}")

    result = run(
        spec_path=Path(args.spec),
        source_spec_path=Path(args.source_spec),
        fingerprint_result_path=Path(args.fingerprint_result),
        wrong_wrap_result_path=Path(args.wrong_wrap_result),
        tifxyz_root=Path(args.tifxyz),
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
        "coverage": result["decision"]["pooled_seam_comparison_coverage_fraction"],
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
