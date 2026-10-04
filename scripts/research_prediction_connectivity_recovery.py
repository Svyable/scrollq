#!/usr/bin/env python3
"""Run the frozen PHerc0139 prediction-connectivity gap-recovery experiment."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import requests

from scrollq.coverage_witness import (
    CoverageWitnessError,
    centered_normal_xyz,
    harmonic_continue_rect,
    hide_rect,
    odd_rect,
)
from scrollq.prediction_recovery import (
    PredictionRecoveryError,
    boundary_anchor_cells,
    label_connectivity,
    raw_component_points,
    read_level_box,
    score_development,
    select_seeded_component,
    snap_to_component,
)
from scrollq.sheetness_plan import _load_surface
from scrollq.support import ZarrV2Level
from scrollq.wrong_wrap_plan import _NearestSampler

SPEC_SCHEMA = "scrollq-research-prediction-connectivity-recovery/1"
RESULT_SCHEMA = "scrollq-research-prediction-connectivity-recovery-result/1"


class RecoveryRunError(RuntimeError):
    pass


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_json(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RecoveryRunError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RecoveryRunError(f"{path} must contain a JSON object")
    return value


def verify_spec(spec: dict[str, Any]) -> None:
    if spec.get("schema") != SPEC_SCHEMA:
        raise RecoveryRunError(f"spec must be {SPEC_SCHEMA}")
    if spec.get("status") != "frozen-before-connectivity-read":
        raise RecoveryRunError("spec is not frozen before connectivity read")
    if spec.get("candidate_generation_firewall", {}).get(
        "hidden_reference_xyz_forbidden"
    ) is not True:
        raise RecoveryRunError("hidden-reference XYZ firewall is not enabled")
    if spec.get("candidate_generation_firewall", {}).get(
        "hidden_reference_validity_forbidden"
    ) is not True:
        raise RecoveryRunError("hidden-reference validity firewall is not enabled")
    if spec.get("development_regions", {}).get("deletion_size_vertices") != 21:
        raise RecoveryRunError("unexpected deletion size")
    if spec.get("coarse_material_prior", {}).get("search_padding_voxels") != 64:
        raise RecoveryRunError("unexpected search padding")
    component = spec.get("local_prediction_component", {})
    if (
        component.get("connectivity") != 26
        or component.get("dilation_iterations") != 1
    ):
        raise RecoveryRunError("unexpected connectivity contract")
    if spec.get("recovered_geometry", {}).get("maximum_snap_distance_voxels") != 64:
        raise RecoveryRunError("unexpected maximum snap distance")


def verify_surface_hashes(root: Path, expected: dict[str, Any]) -> dict[str, str]:
    required = {"meta.json", "x.tif", "y.tif", "z.tif"}
    if set(expected) != required:
        raise RecoveryRunError("frozen TIFXYZ hash set must cover exactly meta/x/y/z")
    observed: dict[str, str] = {}
    for name in sorted(required):
        path = root / name
        if not path.is_file():
            raise RecoveryRunError(f"missing TIFXYZ file: {path}")
        digest = sha256_file(path)
        observed[name] = digest
        if digest != expected[name]:
            raise RecoveryRunError(
                f"TIFXYZ hash mismatch for {name}: {digest} != {expected[name]}"
            )
    return observed


def verify_upstream_evidence(
    spec: dict[str, Any],
    stage_a_spec_path: Path,
    wrong_wrap_result_path: Path,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, Any]]:
    stage_a = load_json(stage_a_spec_path)
    if stage_a.get("schema") != "scrollq-research-coverage-witness-pherc0139/2":
        raise RecoveryRunError("Stage-A v2 spec schema mismatch")
    if stage_a.get("status") != "frozen-before-v2-witness-read":
        raise RecoveryRunError("Stage-A v2 spec status mismatch")
    if stage_a.get("reference_surface", {}).get("exact_ct_root") != spec["source"]["exact_ct_root"]:
        raise RecoveryRunError("Stage-A exact CT root differs from recovery spec")
    source = stage_a.get("independent_witness_source", {})
    if source.get("prediction_url") != spec["source"]["surface_prediction_url"]:
        raise RecoveryRunError("surface prediction URL differs from frozen Stage-A source")
    if source.get("ct_support_url") != spec["source"]["ct_url"]:
        raise RecoveryRunError("CT support URL differs from frozen Stage-A source")
    if source.get("stored_value_threshold") != spec["source"]["surface_prediction_stored_value_threshold"]:
        raise RecoveryRunError("surface-prediction threshold changed")

    stage_centers = {
        str(row["id"]): [int(v) for v in row["grid_yx"]]
        for row in stage_a.get("deletion_protocol", {}).get("centers", [])
    }
    recovery_centers = spec["development_regions"]["centers"]
    if list(stage_centers) != [str(row["id"]) for row in recovery_centers]:
        raise RecoveryRunError("recovery center IDs/order differ from Stage-A v2")
    for row in recovery_centers:
        if stage_centers[str(row["id"])] != [int(v) for v in row["grid_yx"]]:
            raise RecoveryRunError(f"grid_yx changed for {row['id']}")

    wrong = load_json(wrong_wrap_result_path)
    if wrong.get("schema") != "scroliq-wrong-wrap-plan/1":
        raise RecoveryRunError("wrong-wrap result schema mismatch")
    wrong_map = {
        str(row["id"]): row
        for row in wrong.get("groups", [])
        if isinstance(row, dict) and row.get("id")
    }
    for frozen in recovery_centers:
        gid = str(frozen["id"])
        row = wrong_map.get(gid)
        if row is None or row.get("status") != "found":
            raise RecoveryRunError(f"wrong-wrap control missing for {gid}")
        actual = np.asarray(row.get("global_zyx"), dtype=np.float64)
        expected = np.asarray(frozen["wrong_wrap_zyx"], dtype=np.float64)
        if actual.shape != (3,) or not np.allclose(actual, expected, atol=1e-12, rtol=0):
            raise RecoveryRunError(f"wrong-wrap coordinate changed for {gid}")
        if float(row.get("signed_distance_voxels")) != float(
            frozen["wrong_wrap_signed_distance_voxels"]
        ):
            raise RecoveryRunError(f"wrong-wrap distance changed for {gid}")

    ref_path = Path(stage_a["reference_surface"]["reference_plan_path"])
    return stage_a, wrong_map, {
        "stage_a_spec_sha256": sha256_file(stage_a_spec_path),
        "wrong_wrap_result_sha256": sha256_file(wrong_wrap_result_path),
        "reference_plan_path": ref_path.as_posix(),
        "reference_plan_sha256": stage_a["reference_surface"]["reference_plan_sha256"],
    }


def _seed_order(offsets: list[int]) -> list[int]:
    return sorted(
        range(len(offsets)),
        key=lambda i: (
            abs(int(offsets[i])),
            0 if int(offsets[i]) == 0 else 1,
            0 if int(offsets[i]) < 0 else 1,
        ),
    )


def visible_boundary_seeds(
    *,
    observed_xyz: np.ndarray,
    observed_valid: np.ndarray,
    rect: tuple[int, int, int, int],
    pred_sampler: _NearestSampler,
    ct_sampler: _NearestSampler,
    spec: dict[str, Any],
) -> dict[str, Any]:
    contract = spec["visible_boundary_anchors"]
    offsets = [int(v) for v in contract["normal_search_offsets_voxels"]]
    order = _seed_order(offsets)
    threshold = int(spec["source"]["surface_prediction_stored_value_threshold"])
    anchors = boundary_anchor_cells(
        rect,
        ring_offset=int(contract["ring_offset_material_cells"]),
    )
    h, w = observed_valid.shape
    by_side: dict[str, list[dict[str, Any]]] = {side: [] for side in anchors}
    attempted: dict[str, int] = {side: 0 for side in anchors}

    for side, cells in anchors.items():
        for y, x in cells:
            if not (1 <= y < h - 1 and 1 <= x < w - 1):
                continue
            attempted[side] += 1
            if not observed_valid[y, x] or not np.isfinite(observed_xyz[y, x]).all():
                continue
            normal_xyz = centered_normal_xyz(observed_xyz, observed_valid, y, x)
            if normal_xyz is None:
                continue
            surface_xyz = np.asarray(observed_xyz[y, x], dtype=np.float64)
            surface_zyx = surface_xyz[::-1]
            normal_zyx = np.asarray(normal_xyz[::-1], dtype=np.float64)
            coords = np.stack(
                [
                    surface_zyx + float(offset) * normal_zyx
                    for offset in offsets
                ],
                axis=0,
            )
            pred_values, pred_valid = pred_sampler.sample(coords)
            ct_values, ct_valid = ct_sampler.sample(coords)
            supported = (
                pred_valid
                & ct_valid
                & (pred_values > threshold)
                & (ct_values > 0)
            )
            chosen = next((i for i in order if bool(supported[i])), None)
            if chosen is None:
                continue
            coord = coords[chosen]
            voxel = np.floor(coord + 0.5).astype(np.int64)
            by_side[side].append(
                {
                    "grid_yx": [int(y), int(x)],
                    "offset_voxels": int(offsets[chosen]),
                    "coordinate_zyx": [float(v) for v in coord],
                    "voxel_zyx": [int(v) for v in voxel],
                    "prediction_value": int(pred_values[chosen]),
                    "ct_value": int(ct_values[chosen]),
                }
            )

    return {
        "attempted_by_side": attempted,
        "seeds_by_side": by_side,
        "seed_count_by_side": {side: len(rows) for side, rows in by_side.items()},
        "seed_count": sum(len(rows) for rows in by_side.values()),
    }


def _candidate_json_recovered(
    recovered: np.ndarray,
    available: np.ndarray,
) -> list[list[float] | None]:
    rows: list[list[float] | None] = []
    for point, ok in zip(recovered, available):
        rows.append([float(v) for v in point] if bool(ok) else None)
    return rows


def generate_candidate(
    *,
    observed_xyz: np.ndarray,
    observed_valid: np.ndarray,
    rect: tuple[int, int, int, int],
    pred_level: ZarrV2Level,
    ct_level: ZarrV2Level,
    pred_sampler: _NearestSampler,
    ct_sampler: _NearestSampler,
    spec: dict[str, Any],
) -> dict[str, Any]:
    """Generate one recovery candidate without any hidden reference input."""
    filled_xyz, filled_valid, continuation = harmonic_continue_rect(
        observed_xyz,
        observed_valid,
        rect,
    )
    y0, y1, x0, x1 = rect
    coarse_zyx = np.asarray(
        filled_xyz[y0:y1, x0:x1, ::-1],
        dtype=np.float64,
    ).reshape(-1, 3)

    seed_report = visible_boundary_seeds(
        observed_xyz=observed_xyz,
        observed_valid=observed_valid,
        rect=rect,
        pred_sampler=pred_sampler,
        ct_sampler=ct_sampler,
        spec=spec,
    )
    anchor_contract = spec["visible_boundary_anchors"]
    minimum_total = int(anchor_contract["minimum_total_valid_seeds"])
    minimum_side = int(anchor_contract["minimum_valid_seeds_per_side"])
    side_counts = seed_report["seed_count_by_side"]
    if (
        int(seed_report["seed_count"]) < minimum_total
        or any(int(side_counts[side]) < minimum_side for side in ("top", "bottom", "left", "right"))
    ):
        candidate = {
            "component_status": "abstain",
            "abstention_reason": "insufficient visible boundary seeds",
            "continuation": continuation,
            "seed_report": seed_report,
            "recovered_zyx": [None] * int(coarse_zyx.shape[0]),
            "candidate_available": [False] * int(coarse_zyx.shape[0]),
            "candidate_available_fraction_all_material_cells": 0.0,
            "unique_recovered_voxel_fraction": 0.0,
        }
        candidate["candidate_sha256"] = canonical_sha256(candidate)
        return candidate

    seed_points = np.asarray(
        [
            row["voxel_zyx"]
            for side in ("top", "bottom", "left", "right")
            for row in seed_report["seeds_by_side"][side]
        ],
        dtype=np.float64,
    )
    box_points = np.concatenate([coarse_zyx, seed_points], axis=0)
    padding = int(spec["coarse_material_prior"]["search_padding_voxels"])
    shape = np.asarray(pred_level.shape, dtype=np.int64)
    lo = np.maximum(
        0,
        np.floor(np.min(box_points, axis=0)).astype(np.int64) - padding,
    )
    hi = np.minimum(
        shape,
        np.ceil(np.max(box_points, axis=0)).astype(np.int64) + padding + 1,
    )
    if np.any(lo >= hi):
        raise RecoveryRunError("local recovery box is empty")

    pred_box, missing_pred = read_level_box(pred_level, lo, hi)
    ct_box, missing_ct = read_level_box(ct_level, lo, hi)
    raw = (
        (pred_box > int(spec["source"]["surface_prediction_stored_value_threshold"]))
        & (ct_box > 0)
    )
    labels, component_count = label_connectivity(
        raw,
        dilation_iterations=int(
            spec["local_prediction_component"]["dilation_iterations"]
        ),
    )

    local_seeds: dict[str, list[list[int]]] = {}
    for side in ("top", "bottom", "left", "right"):
        local_seeds[side] = [
            [int(v) for v in (np.asarray(row["voxel_zyx"], dtype=np.int64) - lo)]
            for row in seed_report["seeds_by_side"][side]
        ]
    selection = select_seeded_component(
        labels,
        local_seeds,
        minimum_seeds_per_side=minimum_side,
        minimum_total_seed_share=0.5,
    )
    if (
        selection["valid_seed_count"] < minimum_total
        or any(
            int(selection["valid_seed_count_by_side"][side]) < minimum_side
            for side in ("top", "bottom", "left", "right")
        )
    ):
        selection = {
            **selection,
            "status": "abstain",
            "selected_label": None,
            "eligible_component_count": 0,
        }

    base = {
        "component_status": selection["status"],
        "abstention_reason": (
            None
            if selection["status"] == "selected"
            else "no unique four-sided majority prediction component"
        ),
        "continuation": continuation,
        "seed_report": seed_report,
        "box_zyx_half_open": {
            "lo": [int(v) for v in lo],
            "hi": [int(v) for v in hi],
            "shape": [int(v) for v in (hi - lo)],
        },
        "box_missing_prediction_chunks": [list(v) for v in missing_pred],
        "box_missing_ct_chunks": [list(v) for v in missing_ct],
        "raw_candidate_voxel_count": int(np.sum(raw)),
        "connectivity_component_count": int(component_count),
        "component_selection": selection,
    }
    if selection["status"] != "selected":
        candidate = {
            **base,
            "recovered_zyx": [None] * int(coarse_zyx.shape[0]),
            "candidate_available": [False] * int(coarse_zyx.shape[0]),
            "candidate_available_fraction_all_material_cells": 0.0,
            "unique_recovered_voxel_fraction": 0.0,
        }
        candidate["candidate_sha256"] = canonical_sha256(candidate)
        return candidate

    selected_label = int(selection["selected_label"])
    component_points = raw_component_points(
        raw,
        labels,
        selected_label,
        origin_zyx=lo,
    )
    snap = snap_to_component(
        coarse_zyx,
        component_points,
        maximum_distance_voxels=float(
            spec["recovered_geometry"]["maximum_snap_distance_voxels"]
        ),
    )
    recovered = np.asarray(snap["recovered_zyx"], dtype=np.float64)
    available = np.asarray(snap["available"], dtype=bool)
    candidate = {
        **base,
        "selected_component_raw_voxel_count": int(component_points.shape[0]),
        "coarse_zyx": [[float(v) for v in row] for row in coarse_zyx],
        "recovered_zyx": _candidate_json_recovered(recovered, available),
        "candidate_available": [bool(v) for v in available],
        "candidate_available_fraction_all_material_cells": float(
            snap["candidate_available_fraction"]
        ),
        "unique_recovered_voxel_fraction": float(
            snap["unique_recovered_voxel_fraction"]
        ),
        "snap_distance_voxels": [
            float(v) for v in np.asarray(snap["snap_distance_voxels"])
        ],
    }
    candidate["candidate_sha256"] = canonical_sha256(candidate)
    return candidate


def score_candidate(
    *,
    candidate: dict[str, Any],
    truth_xyz: np.ndarray,
    truth_valid: np.ndarray,
    rect: tuple[int, int, int, int],
    wrong_wrap_zyx: np.ndarray,
    tolerances: list[float],
) -> dict[str, Any]:
    """Open scoring truth only after candidate generation is complete."""
    y0, y1, x0, x1 = rect
    valid_flat = np.asarray(truth_valid[y0:y1, x0:x1], dtype=bool).reshape(-1)
    truth_zyx = np.asarray(
        truth_xyz[y0:y1, x0:x1, ::-1],
        dtype=np.float64,
    ).reshape(-1, 3)
    recovered_raw = candidate["recovered_zyx"]
    if len(recovered_raw) != len(valid_flat):
        raise RecoveryRunError("candidate material-grid shape does not match frozen deletion")
    available = np.asarray(candidate["candidate_available"], dtype=bool)
    recovered = np.full((len(recovered_raw), 3), np.nan, dtype=np.float64)
    for i, row in enumerate(recovered_raw):
        if row is not None:
            recovered[i] = np.asarray(row, dtype=np.float64)

    denom = int(np.sum(valid_flat))
    scored = valid_flat & available
    errors = (
        np.linalg.norm(recovered[scored] - truth_zyx[scored], axis=1)
        if np.any(scored)
        else np.empty(0, dtype=np.float64)
    )
    fractions: dict[str, float] = {}
    for tolerance in tolerances:
        fractions[str(float(tolerance))] = (
            float(np.sum(errors <= float(tolerance)) / denom) if denom else 0.0
        )
    all_recovered = recovered[available]
    wrong = np.asarray(wrong_wrap_zyx, dtype=np.float64)
    wrong_min = (
        float(np.linalg.norm(all_recovered - wrong[None, :], axis=1).min())
        if len(all_recovered)
        else None
    )
    invalid_flat = ~valid_flat
    invalid_fill = (
        float(np.mean(available[invalid_flat])) if np.any(invalid_flat) else 0.0
    )

    return {
        "component_status": candidate["component_status"],
        "candidate_sha256": candidate["candidate_sha256"],
        "valid_hidden_vertex_count": denom,
        "candidate_available_valid_hidden_count": int(np.sum(scored)),
        "candidate_available_fraction": (
            float(np.sum(scored) / denom) if denom else 0.0
        ),
        "fraction_within_tolerance": fractions,
        "fraction_within_8_voxels": fractions.get("8.0", 0.0),
        "median_error_voxels": float(np.median(errors)) if len(errors) else None,
        "p95_error_voxels": (
            float(np.quantile(errors, 0.95)) if len(errors) else None
        ),
        "max_error_voxels": float(np.max(errors)) if len(errors) else None,
        "unique_recovered_voxel_fraction": float(
            candidate["unique_recovered_voxel_fraction"]
        ),
        "invalid_hidden_cell_fill_fraction": invalid_fill,
        "wrong_wrap_min_recovered_distance_voxels": wrong_min,
        "wrong_wrap_rejected": bool(wrong_min is None or wrong_min > 8.0),
    }


def run(
    *,
    spec_path: Path,
    tifxyz_root: Path,
    stage_a_spec_path: Path,
    wrong_wrap_result_path: Path,
    reference_plan_path: Path,
) -> dict[str, Any]:
    spec = load_json(spec_path)
    verify_spec(spec)
    stage_a, _, upstream = verify_upstream_evidence(
        spec,
        stage_a_spec_path,
        wrong_wrap_result_path,
    )
    if reference_plan_path.as_posix() != upstream["reference_plan_path"]:
        raise RecoveryRunError("reference-plan path differs from frozen Stage-A source")
    if sha256_file(reference_plan_path) != upstream["reference_plan_sha256"]:
        raise RecoveryRunError("reference-plan hash differs from frozen Stage-A source")
    reference_plan = load_json(reference_plan_path)

    surface_hashes = verify_surface_hashes(
        tifxyz_root,
        spec["source"]["tifxyz_sha256"],
    )
    truth_xyz, truth_valid, surface_info = _load_surface(tifxyz_root)
    if surface_info["hashes"]["x.tif"] != surface_hashes["x.tif"]:
        raise RecoveryRunError("surface loader observed unexpected TIFXYZ bytes")

    session = requests.Session()
    session.mount("https://", requests.adapters.HTTPAdapter(pool_maxsize=16))
    pred_level = ZarrV2Level(
        spec["source"]["surface_prediction_url"].rstrip("/") + "/0",
        session,
    )
    ct_level = ZarrV2Level(spec["source"]["ct_url"].rstrip("/") + "/0", session)
    expected_shape = tuple(
        int(v) for v in reference_plan["zpa_report"]["level0_shape_zyx"]
    )
    if tuple(pred_level.shape) != expected_shape or tuple(ct_level.shape) != expected_shape:
        raise RecoveryRunError(
            f"exact source shape mismatch: pred={pred_level.shape} ct={ct_level.shape} expected={expected_shape}"
        )
    pred_sampler = _NearestSampler(pred_level)
    ct_sampler = _NearestSampler(ct_level)

    centers_out: list[dict[str, Any]] = []
    candidate_hashes_before_scoring: list[str] = []
    try:
        for frozen in spec["development_regions"]["centers"]:
            center = tuple(int(v) for v in frozen["grid_yx"])
            rect = odd_rect(center, int(spec["development_regions"]["deletion_size_vertices"]))

            # Firewall boundary: after this call, candidate generation sees only
            # the explicitly hidden arrays, never truth_xyz or truth_valid.
            observed_xyz, observed_valid = hide_rect(truth_xyz, truth_valid, rect)
            candidate = generate_candidate(
                observed_xyz=observed_xyz,
                observed_valid=observed_valid,
                rect=rect,
                pred_level=pred_level,
                ct_level=ct_level,
                pred_sampler=pred_sampler,
                ct_sampler=ct_sampler,
                spec=spec,
            )
            candidate_hashes_before_scoring.append(candidate["candidate_sha256"])

            scoring = score_candidate(
                candidate=candidate,
                truth_xyz=truth_xyz,
                truth_valid=truth_valid,
                rect=rect,
                wrong_wrap_zyx=np.asarray(frozen["wrong_wrap_zyx"], dtype=np.float64),
                tolerances=[
                    float(v)
                    for v in spec["scoring"]["secondary_accuracy_tolerances_voxels"]
                ],
            )
            if scoring["candidate_sha256"] != candidate_hashes_before_scoring[-1]:
                raise RecoveryRunError("candidate identity changed during scoring")
            centers_out.append(
                {
                    "id": frozen["id"],
                    "grid_yx": list(center),
                    "rect_yx_half_open": list(rect),
                    "candidate": candidate,
                    "score": scoring,
                }
            )
    finally:
        session.close()

    score_rows = [
        {
            **row["score"],
            "component_status": row["candidate"]["component_status"],
        }
        for row in centers_out
    ]
    gate = spec["development_gate"]
    decision = score_development(
        score_rows,
        frozen_center_count=len(spec["development_regions"]["centers"]),
        required_selected_component_centers=int(
            gate["required_selected_component_centers"]
        ),
        minimum_candidate_available_fraction_every_selected_center=float(
            gate["minimum_candidate_available_fraction_every_selected_center"]
        ),
        minimum_fraction_within_8_voxels_every_selected_center=float(
            gate["minimum_fraction_within_8_voxels_every_selected_center"]
        ),
        minimum_median_fraction_within_8_voxels_across_all_centers=float(
            gate["minimum_median_fraction_within_8_voxels_across_all_six_centers"]
        ),
        maximum_median_error_voxels_every_selected_center=float(
            gate["maximum_median_error_voxels_every_selected_center"]
        ),
        maximum_median_p95_error_voxels_across_selected_centers=float(
            gate["maximum_median_p95_error_voxels_across_selected_centers"]
        ),
        require_all_wrong_wrap_controls_rejected=bool(
            gate["require_all_six_wrong_wrap_controls_rejected"]
        ),
        minimum_median_unique_recovered_voxel_fraction=float(
            gate["minimum_median_unique_recovered_voxel_fraction"]
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
            "stage_a_v2_spec": {
                "path": str(stage_a_spec_path),
                "sha256": upstream["stage_a_spec_sha256"],
            },
            "wrong_wrap_result": {
                "path": str(wrong_wrap_result_path),
                "sha256": upstream["wrong_wrap_result_sha256"],
            },
            "reference_plan": {
                "path": str(reference_plan_path),
                "sha256": upstream["reference_plan_sha256"],
            },
            "tifxyz_sha256": surface_hashes,
            "exact_ct_root": spec["source"]["exact_ct_root"],
            "ct_level0_shape_zyx": list(ct_level.shape),
            "prediction_level0_shape_zyx": list(pred_level.shape),
            "boundary_sampler_missing_prediction_chunks": [
                list(v) for v in sorted(pred_sampler.missing_chunks)
            ],
            "boundary_sampler_missing_ct_chunks": [
                list(v) for v in sorted(ct_sampler.missing_chunks)
            ],
        },
        "firewall": {
            "candidate_hashes_frozen_before_scoring": candidate_hashes_before_scoring,
            "candidate_generator_hidden_reference_arguments": [],
            "hidden_truth_use": "scoring-only after candidate_sha256",
        },
        "centers": centers_out,
        "decision": {
            **decision,
            "classification_after_development": (
                "FREEZE IDENTICAL CONNECTIVITY RECOVERY FOR HOLDOUT"
                if decision["status"] == "pass"
                else "DISMISS prediction-connectivity-recovery-v1"
            ),
            "claim_boundary": spec["claim_boundary"],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--tifxyz", required=True)
    parser.add_argument("--stage-a-spec", required=True)
    parser.add_argument("--wrong-wrap-result", required=True)
    parser.add_argument("--reference-plan", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    out = Path(args.out)
    if out.exists():
        parser.error(f"refusing to overwrite {out}")
    try:
        result = run(
            spec_path=Path(args.spec),
            tifxyz_root=Path(args.tifxyz),
            stage_a_spec_path=Path(args.stage_a_spec),
            wrong_wrap_result_path=Path(args.wrong_wrap_result),
            reference_plan_path=Path(args.reference_plan),
        )
    except (
        RecoveryRunError,
        PredictionRecoveryError,
        CoverageWitnessError,
        OSError,
        requests.RequestException,
    ) as exc:
        print(
            json.dumps(
                {"schema": RESULT_SCHEMA, "status": "invalid", "error": str(exc)},
                sort_keys=True,
            )
        )
        return 2

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")

    print(
        json.dumps(
            {
                "schema": result["schema"],
                "status": result["status"],
                "decision": result["decision"]["status"],
                "selected_centers": result["decision"]["selected_component_center_count"],
                "median_fraction_within_8": result["decision"][
                    "median_fraction_within_8_voxels_across_all_centers"
                ],
                "median_p95_error": result["decision"][
                    "median_p95_error_voxels_across_selected_centers"
                ],
                "wrong_wrap_rejected": result["decision"]["wrong_wrap_rejected_count"],
                "median_unique_fraction": result["decision"][
                    "median_unique_recovered_voxel_fraction"
                ],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
