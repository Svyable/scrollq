#!/usr/bin/env python3
"""Run the preregistered precision-first coverage-witness Stage-C experiment."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import requests
from scipy.spatial import cKDTree

from scrollq.coverage_witness import (
    CoverageWitnessError,
    classify_runs,
    evaluate_tensor_polynomial_surface,
    fit_tensor_polynomial_surface,
    hide_rect,
    inner_collar_mask,
    odd_rect,
    polynomial_consensus,
    supported_runs,
)
from scrollq.sheetness_plan import _load_surface
from scrollq.support import ZarrV2Level
from scrollq.wrong_wrap_plan import _NearestSampler


SPEC_SCHEMA = "scrollq-research-coverage-witness-stage-c/1"
RESULT_SCHEMA = "scrollq-research-coverage-witness-stage-c-result/1"


class StageCError(RuntimeError):
    pass


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _load_json(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StageCError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise StageCError(f"{path} must contain a JSON object")
    return value


def _load_spec(path: str | Path) -> tuple[dict[str, Any], str]:
    spec = _load_json(path)
    if spec.get("schema") != SPEC_SCHEMA:
        raise StageCError(f"spec must be {SPEC_SCHEMA}")
    if spec.get("status") != "frozen-before-stage-c-witness-read":
        raise StageCError("spec is not frozen-before-stage-c-witness-read")
    return spec, sha256_file(path)


def _verify_tifxyz_hashes(root: Path, expected: dict[str, Any]) -> dict[str, str]:
    observed: dict[str, str] = {}
    for name, expected_digest in expected.items():
        path = root / name
        if not path.is_file():
            raise StageCError(f"missing TIFXYZ file: {path}")
        digest = sha256_file(path)
        observed[name] = digest
        if digest != expected_digest:
            raise StageCError(
                f"TIFXYZ hash mismatch for {name}: {digest} != {expected_digest}"
            )
    return observed


def _verify_holdout_selection(
    spec: dict[str, Any],
    reference_plan_path: Path,
) -> str:
    plan = _load_json(reference_plan_path)
    if plan.get("schema") != "scroliq-sheetness-plan/1":
        raise StageCError("reference plan schema mismatch")
    selection = spec["fresh_holdout_selection"]
    excluded = set(selection["excluded_stage_b_ids"])
    shape = tuple(int(v) for v in spec["reference_surface"]["grid_shape_yx"])
    evaluation = int(spec["deletion_protocol"]["evaluation_window_size_vertices"])
    half = evaluation // 2
    groups = plan.get("groups")
    if not isinstance(groups, list):
        raise StageCError("reference plan groups missing")

    eligible = []
    for row in groups:
        if not isinstance(row, dict) or row.get("id") in excluded:
            continue
        y, x = (int(v) for v in row["grid_yx"])
        if (
            y - half >= 0
            and y + half < shape[0]
            and x - half >= 0
            and x + half < shape[1]
        ):
            eligible.append({"id": row["id"], "grid_yx": [y, x]})

    if len(eligible) != int(selection["eligible_count"]):
        raise StageCError(
            f"fresh holdout eligible count {len(eligible)} != "
            f"{selection['eligible_count']}"
        )
    n = len(eligible)
    ranks = [min(n - 1, int((i + 0.5) * n / 6)) for i in range(6)]
    if ranks != [int(v) for v in selection["selected_zero_based_ranks"]]:
        raise StageCError("fresh holdout selection ranks do not reproduce")

    selected = [eligible[i] for i in ranks]
    frozen = [
        {"id": row["id"], "grid_yx": [int(v) for v in row["grid_yx"]]}
        for row in selection["selected_centers"]
    ]
    if selected != frozen:
        raise StageCError(
            f"fresh holdout centers do not reproduce: {selected} != {frozen}"
        )
    return sha256_file(reference_plan_path)


def _verify_wrong_wrap_controls(
    spec: dict[str, Any],
    wrong_wrap_result_path: Path,
) -> str:
    result = _load_json(wrong_wrap_result_path)
    if result.get("schema") != "scroliq-wrong-wrap-plan/1":
        raise StageCError("wrong-wrap result schema mismatch")
    by_id = {
        row.get("id"): row
        for row in result.get("groups", [])
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    for center in spec["fresh_holdout_selection"]["selected_centers"]:
        row = by_id.get(center["id"])
        if not isinstance(row, dict) or row.get("status") != "found":
            raise StageCError(f"wrong-wrap control missing for {center['id']}")
        expected = np.asarray(center["wrong_wrap_zyx"], dtype=np.float64)
        actual = np.asarray(row.get("global_zyx"), dtype=np.float64)
        if actual.shape != (3,) or not np.allclose(actual, expected, atol=1e-12, rtol=0):
            raise StageCError(f"wrong-wrap coordinate changed for {center['id']}")
        if float(row.get("signed_distance_voxels")) != float(
            center["wrong_wrap_signed_distance_voxels"]
        ):
            raise StageCError(f"wrong-wrap signed distance changed for {center['id']}")
    return sha256_file(wrong_wrap_result_path)


def _window_points(
    center: tuple[int, int],
    size: int,
) -> np.ndarray:
    y0, y1, x0, x1 = odd_rect(center, size)
    yy, xx = np.meshgrid(
        np.arange(y0, y1, dtype=np.int64),
        np.arange(x0, x1, dtype=np.int64),
        indexing="ij",
    )
    return np.stack([yy.ravel(), xx.ravel()], axis=1)


def _visible_training(
    *,
    observed_xyz: np.ndarray,
    observed_valid: np.ndarray,
    window_yx: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    rows = []
    values = []
    for y, x in window_yx:
        y = int(y)
        x = int(x)
        if observed_valid[y, x] and np.isfinite(observed_xyz[y, x]).all():
            rows.append([y, x])
            values.append(observed_xyz[y, x])
    if not rows:
        raise CoverageWitnessError("no visible training points in evaluation window")
    return np.asarray(rows, dtype=np.float64), np.asarray(values, dtype=np.float64)


def _fit_pair(
    yx: np.ndarray,
    xyz: np.ndarray,
    *,
    center: tuple[int, int],
    scale: float,
) -> tuple[Any, Any]:
    model2 = fit_tensor_polynomial_surface(
        yx,
        xyz,
        degree=2,
        center_yx=(float(center[0]), float(center[1])),
        scale=scale,
        min_points_per_term=4,
    )
    model3 = fit_tensor_polynomial_surface(
        yx,
        xyz,
        degree=3,
        center_yx=(float(center[0]), float(center[1])),
        scale=scale,
        min_points_per_term=4,
    )
    return model2, model3


def _quantiles(values: np.ndarray | list[float]) -> dict[str, float] | None:
    array = np.asarray(values, dtype=np.float64)
    if array.size == 0:
        return None
    return {
        "min": float(np.min(array)),
        "median": float(np.median(array)),
        "p95": float(np.quantile(array, 0.95)),
        "max": float(np.max(array)),
    }


def _visible_validation(
    *,
    visible_yx: np.ndarray,
    visible_xyz: np.ndarray,
    hidden_rect: tuple[int, int, int, int],
    center: tuple[int, int],
    scale: float,
    width: int,
) -> dict[str, Any]:
    collar = inner_collar_mask(
        visible_yx.astype(np.int64),
        hidden_rect,
        width=width,
    )
    validation_yx = visible_yx[collar]
    validation_xyz = visible_xyz[collar]
    train_yx = visible_yx[~collar]
    train_xyz = visible_xyz[~collar]
    if validation_yx.shape[0] == 0:
        raise CoverageWitnessError("visible validation collar is empty")

    model2, model3 = _fit_pair(
        train_yx,
        train_xyz,
        center=center,
        scale=scale,
    )
    pred3, _ = evaluate_tensor_polynomial_surface(model3, validation_yx)
    errors = np.linalg.norm(pred3 - validation_xyz, axis=1)
    return {
        "holdout_count": int(validation_yx.shape[0]),
        "training_count": int(train_yx.shape[0]),
        "degree2_condition_number": float(model2.condition_number),
        "degree3_condition_number": float(model3.condition_number),
        "degree3_error_quantiles": _quantiles(errors),
        "degree3_p95_error_voxels": float(np.quantile(errors, 0.95)),
    }


def _ray_candidate_from_prediction(
    *,
    y: int,
    x: int,
    continued_xyz: np.ndarray,
    normal_xyz: np.ndarray,
    position_disagreement: float,
    normal_cosine: float,
    offsets: np.ndarray,
    pred_sampler: _NearestSampler,
    ct_sampler: _NearestSampler,
    threshold: int,
    ray_spec: dict[str, Any],
) -> dict[str, Any]:
    continued_zyx = np.asarray(continued_xyz, dtype=np.float64)[::-1]
    normal_zyx = np.asarray(normal_xyz, dtype=np.float64)[::-1]
    coords = continued_zyx[None, :] + offsets[:, None] * normal_zyx[None, :]
    pred_values, pred_valid = pred_sampler.sample(coords)
    ct_values, ct_valid = ct_sampler.sample(coords)
    support = (
        pred_valid
        & ct_valid
        & (pred_values > threshold)
        & (ct_values > 0)
    )
    runs = supported_runs(
        [int(v) for v in offsets],
        [bool(v) for v in support],
        min_run_voxels=int(ray_spec["min_run_voxels"]),
    )
    classified = classify_runs(
        runs,
        target_abs_max=float(ray_spec["target_band_abs_midpoint_voxels_max"]),
        competitor_abs_min=float(ray_spec["competing_band_abs_midpoint_voxels_min"]),
        competitor_abs_max=float(ray_spec["competing_band_abs_midpoint_voxels_max"]),
    )
    target = classified["target"]
    target_coord = (
        None
        if target is None
        else [
            float(v)
            for v in (continued_zyx + target.midpoint * normal_zyx)
        ]
    )
    competitors = [
        {
            "midpoint": float(run.midpoint),
            "coordinate_zyx": [
                float(v)
                for v in (continued_zyx + run.midpoint * normal_zyx)
            ],
            "run": run.as_dict(),
        }
        for run in classified["competitors"]
    ]
    return {
        "grid_yx": [int(y), int(x)],
        "continued_zyx": [float(v) for v in continued_zyx],
        "normal_zyx": [float(v) for v in normal_zyx],
        "position_disagreement_voxels": float(position_disagreement),
        "abs_normal_cosine": float(normal_cosine),
        "target_midpoint": None if target is None else float(target.midpoint),
        "target_coordinate_zyx": target_coord,
        "target_run": None if target is None else target.as_dict(),
        "guard_run_count": len(classified["guard"]),
        "competitors": competitors,
        "all_run_count": len(runs),
    }


def _generate_variant(
    *,
    xyz: np.ndarray,
    valid: np.ndarray,
    center: tuple[int, int],
    deletion_size: int,
    spec: dict[str, Any],
    pred_sampler: _NearestSampler,
    ct_sampler: _NearestSampler,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    deletion = spec["deletion_protocol"]
    ensemble = spec["continuation_ensemble"]
    ray_spec = spec["normal_ray_decomposition"]
    source = spec["independent_witness_source"]

    evaluation_size = int(deletion["evaluation_window_size_vertices"])
    hidden_rect = odd_rect(center, deletion_size)
    window_rect = odd_rect(center, evaluation_size)
    wy0, wy1, wx0, wx1 = window_rect
    dy0, dy1, dx0, dx1 = hidden_rect
    if not (
        wy0 <= dy0 - 1
        and dy1 + 1 <= wy1
        and wx0 <= dx0 - 1
        and dx1 + 1 <= wx1
    ):
        raise CoverageWitnessError("hidden rectangle lacks visible boundary in window")

    observed_xyz, observed_valid = hide_rect(xyz, valid, hidden_rect)
    window_yx = _window_points(center, evaluation_size)
    visible_yx, visible_xyz = _visible_training(
        observed_xyz=observed_xyz,
        observed_valid=observed_valid,
        window_yx=window_yx,
    )

    scale = float(evaluation_size // 2)
    validation = _visible_validation(
        visible_yx=visible_yx,
        visible_xyz=visible_xyz,
        hidden_rect=hidden_rect,
        center=center,
        scale=scale,
        width=int(ensemble["visible_only_validation"]["holdout_band_width_vertices"]),
    )

    model2, model3 = _fit_pair(
        visible_yx,
        visible_xyz,
        center=center,
        scale=scale,
    )

    hidden_yx = _window_points(center, deletion_size).astype(np.float64)
    xyz2, normals2 = evaluate_tensor_polynomial_surface(model2, hidden_yx)
    xyz3, normals3 = evaluate_tensor_polynomial_surface(model3, hidden_yx)
    consensus, disagreement, cosine = polynomial_consensus(
        xyz2,
        normals2,
        xyz3,
        normals3,
        max_position_disagreement=float(
            ensemble["consensus"]["max_position_disagreement_voxels"]
        ),
        min_abs_normal_cosine=float(
            ensemble["consensus"]["min_abs_normal_cosine"]
        ),
    )

    offsets = np.asarray(ray_spec["signed_offsets_voxels"], dtype=np.float64)
    if not np.all(np.diff(offsets) == 1):
        raise CoverageWitnessError("frozen ray offsets are not contiguous unit steps")

    rows: list[dict[str, Any]] = []
    for index in np.flatnonzero(consensus):
        y, x = (int(v) for v in hidden_yx[index])
        rows.append(
            _ray_candidate_from_prediction(
                y=y,
                x=x,
                continued_xyz=xyz3[index],
                normal_xyz=normals3[index],
                position_disagreement=float(disagreement[index]),
                normal_cosine=float(cosine[index]),
                offsets=offsets,
                pred_sampler=pred_sampler,
                ct_sampler=ct_sampler,
                threshold=int(source["stored_value_threshold"]),
                ray_spec=ray_spec,
            )
        )

    generation = {
        "hidden_rect_yx_half_open": list(hidden_rect),
        "evaluation_window_yx_half_open": list(window_rect),
        "visible_training_count": int(visible_yx.shape[0]),
        "degree2_condition_number": float(model2.condition_number),
        "degree3_condition_number": float(model3.condition_number),
        "hidden_grid_count": int(hidden_yx.shape[0]),
        "consensus_grid_count": int(consensus.sum()),
        "consensus_fraction_all_hidden": float(consensus.mean()),
        "candidate_sha256": canonical_sha256(rows),
    }
    scoring_only = {
        "hidden_yx": hidden_yx,
        "degree2_xyz": xyz2,
        "degree3_xyz": xyz3,
        "position_disagreement": disagreement,
        "normal_cosine": cosine,
        "consensus": consensus,
    }
    return rows, generation, {**validation, **scoring_only}


def _score_variant(
    *,
    candidates: list[dict[str, Any]],
    generation: dict[str, Any],
    auxiliary: dict[str, Any],
    xyz: np.ndarray,
    valid: np.ndarray,
    center_row: dict[str, Any],
    deletion_size: int,
    spec: dict[str, Any],
) -> dict[str, Any]:
    scoring = spec["scoring"]
    correct_tol = float(scoring["correct_target_tolerance_voxels"])
    omission_tol = float(scoring["omission_tolerance_voxels"])
    rect = tuple(int(v) for v in generation["hidden_rect_yx_half_open"])
    y0, y1, x0, x1 = rect

    delete = np.zeros_like(valid, dtype=bool)
    delete[y0:y1, x0:x1] = True
    outside_xyz = np.asarray(xyz[valid & ~delete], dtype=np.float64)
    if outside_xyz.size == 0:
        raise StageCError("counterfactual submitted surface is empty")
    outside_tree = cKDTree(np.ascontiguousarray(outside_xyz[:, ::-1]))

    hidden_yx = np.asarray(auxiliary["hidden_yx"], dtype=np.int64)
    consensus = np.asarray(auxiliary["consensus"], dtype=bool)
    disagreement = np.asarray(auxiliary["position_disagreement"], dtype=np.float64)
    degree3_xyz = np.asarray(auxiliary["degree3_xyz"], dtype=np.float64)
    by_yx = {
        (int(row["grid_yx"][0]), int(row["grid_yx"][1])): row
        for row in candidates
    }

    eligible_indices = []
    consensus_eligible_indices = []
    degree3_errors = []
    disagreement_eligible = []
    target_rows = []
    correct_rows = []
    omission_hits = 0

    for i, (y, x) in enumerate(hidden_yx):
        y = int(y)
        x = int(x)
        if not valid[y, x] or not np.isfinite(xyz[y, x]).all():
            continue
        eligible_indices.append(i)
        true_xyz = np.asarray(xyz[y, x], dtype=np.float64)
        degree3_errors.append(float(np.linalg.norm(degree3_xyz[i] - true_xyz)))
        disagreement_eligible.append(float(disagreement[i]))
        if not consensus[i]:
            continue
        consensus_eligible_indices.append(i)
        row = by_yx.get((y, x))
        if row is None:
            raise StageCError("consensus point missing generated candidate row")
        if row["target_coordinate_zyx"] is None:
            continue
        target_rows.append(row)
        target_zyx = np.asarray(row["target_coordinate_zyx"], dtype=np.float64)
        true_zyx = true_xyz[::-1]
        if float(np.linalg.norm(target_zyx - true_zyx)) > correct_tol:
            continue
        correct_rows.append(row)
        distance, _ = outside_tree.query(target_zyx, k=1, workers=1)
        if float(distance) > omission_tol:
            omission_hits += 1

    all_target_coords = [
        np.asarray(row["target_coordinate_zyx"], dtype=np.float64)
        for row in candidates
        if row["target_coordinate_zyx"] is not None
    ]
    wrong = np.asarray(center_row["wrong_wrap_zyx"], dtype=np.float64)
    if all_target_coords:
        stack = np.stack(all_target_coords, axis=0)
        wrong_min = float(np.linalg.norm(stack - wrong[None, :], axis=1).min())
    else:
        wrong_min = None

    center_key = tuple(int(v) for v in center_row["grid_yx"])
    center_candidate = by_yx.get(center_key)
    competitor_distances = []
    if center_candidate is not None:
        for comp in center_candidate["competitors"]:
            coord = np.asarray(comp["coordinate_zyx"], dtype=np.float64)
            competitor_distances.append(float(np.linalg.norm(coord - wrong)))
    competitor_min = min(competitor_distances) if competitor_distances else None
    competitor_recovered = (
        competitor_min is not None and competitor_min <= correct_tol
    )

    eligible_count = len(eligible_indices)
    consensus_count = len(consensus_eligible_indices)
    target_count = len(target_rows)
    correct_count = len(correct_rows)

    return {
        "status": "measured",
        "center_id": center_row["id"],
        "center_grid_yx": list(center_key),
        "deletion_size_vertices": int(deletion_size),
        "generation": generation,
        "visible_collar_validation_count": int(auxiliary["holdout_count"]),
        "visible_collar_validation_training_count": int(auxiliary["training_count"]),
        "visible_collar_validation_p95_error_voxels": float(
            auxiliary["degree3_p95_error_voxels"]
        ),
        "visible_collar_validation_error_quantiles": auxiliary[
            "degree3_error_quantiles"
        ],
        "visible_validation_degree2_condition_number": float(
            auxiliary["degree2_condition_number"]
        ),
        "visible_validation_degree3_condition_number": float(
            auxiliary["degree3_condition_number"]
        ),
        "eligible_hidden_count": eligible_count,
        "consensus_hidden_count": consensus_count,
        "consensus_fraction": (
            float(consensus_count / eligible_count) if eligible_count else None
        ),
        "target_witness_count": target_count,
        "correct_target_count": correct_count,
        "correct_target_recall": (
            float(correct_count / eligible_count) if eligible_count else None
        ),
        "target_precision": (
            float(correct_count / target_count) if target_count else None
        ),
        "omission_recall_among_correct_targets": (
            float(omission_hits / correct_count) if correct_count else None
        ),
        "wrong_wrap_min_target_distance_voxels": wrong_min,
        "wrong_wrap_rejected": (
            wrong_min is None or wrong_min > correct_tol
        ),
        "center_competitor_min_wrong_wrap_distance_voxels": competitor_min,
        "center_competitor_recovered": bool(competitor_recovered),
        "hidden_position_disagreement_quantiles_scoring_only": _quantiles(
            disagreement_eligible
        ),
        "degree3_hidden_error_quantiles_scoring_only": _quantiles(
            degree3_errors
        ),
        "candidate_preview": {
            "center": center_candidate,
            "first_target": next(
                (
                    row
                    for row in candidates
                    if row["target_coordinate_zyx"] is not None
                ),
                None,
            ),
        },
    }


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    return float(np.median(np.asarray(values, dtype=np.float64)))


def _decision(spec: dict[str, Any], variants: list[dict[str, Any]]) -> dict[str, Any]:
    rule = spec["decision_rule"]
    sizes = [int(v) for v in spec["deletion_protocol"]["deletion_sizes_vertices"]]
    centers = spec["fresh_holdout_selection"]["selected_centers"]
    expected = len(sizes) * len(centers)
    measured = [v for v in variants if v.get("status") == "measured"]
    complete = len(variants) == expected and len(measured) == expected

    by_size: dict[str, Any] = {}
    all_size_ok = complete
    for size in sizes:
        rows = [
            v for v in measured if int(v["deletion_size_vertices"]) == size
        ]
        recalls = [
            float(v["correct_target_recall"])
            for v in rows
            if v["correct_target_recall"] is not None
        ]
        precisions = [
            float(v["target_precision"])
            for v in rows
            if v["target_precision"] is not None
        ]
        omissions = [
            float(v["omission_recall_among_correct_targets"])
            for v in rows
            if v["omission_recall_among_correct_targets"] is not None
        ]
        visible_p95 = [
            float(v["visible_collar_validation_p95_error_voxels"])
            for v in rows
        ]

        size_ok = (
            len(rows) == len(centers)
            and all(
                int(v["target_witness_count"])
                >= int(rule["minimum_target_witnesses_each_variant"])
                for v in rows
            )
            and all(
                v["correct_target_recall"] is not None
                and float(v["correct_target_recall"])
                >= float(rule["every_variant_min_correct_target_recall"])
                for v in rows
            )
            and (_median(recalls) or 0.0)
            >= float(rule["median_correct_target_recall_each_size"])
            and all(
                v["target_precision"] is not None
                and float(v["target_precision"])
                >= float(rule["every_variant_min_target_precision"])
                for v in rows
            )
            and (_median(precisions) or 0.0)
            >= float(rule["median_target_precision_each_size"])
            and all(
                v["omission_recall_among_correct_targets"] is not None
                and float(v["omission_recall_among_correct_targets"])
                >= float(
                    rule[
                        "every_variant_min_omission_recall_among_correct_targets"
                    ]
                )
                for v in rows
            )
            and (_median(omissions) or 0.0)
            >= float(
                rule[
                    "median_omission_recall_among_correct_targets_each_size"
                ]
            )
            and all(
                value
                <= float(rule["visible_validation_every_variant_p95_max_voxels"])
                for value in visible_p95
            )
            and (_median(visible_p95) or float("inf"))
            <= float(rule["visible_validation_median_p95_each_size_max_voxels"])
        )
        all_size_ok = all_size_ok and size_ok
        by_size[str(size)] = {
            "variant_count": len(rows),
            "min_target_witness_count": (
                min(int(v["target_witness_count"]) for v in rows)
                if rows
                else None
            ),
            "min_correct_target_recall": min(recalls) if recalls else None,
            "median_correct_target_recall": _median(recalls),
            "min_target_precision": min(precisions) if precisions else None,
            "median_target_precision": _median(precisions),
            "min_omission_recall": min(omissions) if omissions else None,
            "median_omission_recall": _median(omissions),
            "max_visible_validation_p95": max(visible_p95) if visible_p95 else None,
            "median_visible_validation_p95": _median(visible_p95),
            "pass": bool(size_ok),
        }

    wrong_ok = (
        len(measured) == expected
        and all(bool(v["wrong_wrap_rejected"]) for v in measured)
    )
    size41 = [
        v for v in measured if int(v["deletion_size_vertices"]) == 41
    ]
    recovered = sum(bool(v["center_competitor_recovered"]) for v in size41)
    competitor_ok = recovered >= int(
        rule["size_41_min_centers_with_wrong_wrap_competitor_recovered"]
    )
    passed = bool(complete and all_size_ok and wrong_ok and competitor_ok)
    return {
        "status": "pass" if passed else "fail",
        "variant_completeness": {
            "expected": expected,
            "observed": len(variants),
            "measured": len(measured),
            "pass": bool(complete),
        },
        "by_size": by_size,
        "wrong_wrap_target_rejection": {
            "rejected_count": sum(
                bool(v.get("wrong_wrap_rejected")) for v in measured
            ),
            "variant_count": len(measured),
            "required_all": bool(
                rule["require_all_wrong_wraps_rejected_as_targets"]
            ),
            "pass": bool(wrong_ok),
        },
        "size_41_competitor_recovery": {
            "recovered_centers": int(recovered),
            "required_centers": int(
                rule["size_41_min_centers_with_wrong_wrap_competitor_recovered"]
            ),
            "center_count": len(size41),
            "pass": bool(competitor_ok),
        },
        "interpretation": rule["pass_interpretation"],
    }


def run(
    *,
    spec_path: Path,
    tifxyz: Path,
    reference_plan_path: Path,
    wrong_wrap_result_path: Path,
) -> dict[str, Any]:
    spec, spec_sha = _load_spec(spec_path)
    observed_hashes = _verify_tifxyz_hashes(
        tifxyz, spec["reference_surface"]["tifxyz_sha256"]
    )
    reference_plan_sha = _verify_holdout_selection(spec, reference_plan_path)
    wrong_wrap_sha = _verify_wrong_wrap_controls(spec, wrong_wrap_result_path)

    xyz, valid, surface_info = _load_surface(tifxyz)
    centers = spec["fresh_holdout_selection"]["selected_centers"]
    sizes = [int(v) for v in spec["deletion_protocol"]["deletion_sizes_vertices"]]
    source = spec["independent_witness_source"]

    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(pool_maxsize=16)
    session.mount("https://", adapter)
    variants: list[dict[str, Any]] = []
    try:
        pred_level = ZarrV2Level(source["prediction_url"].rstrip("/") + "/0", session)
        ct_level = ZarrV2Level(source["ct_support_url"].rstrip("/") + "/0", session)
        if tuple(pred_level.shape) != tuple(ct_level.shape):
            raise StageCError(
                f"prediction shape {pred_level.shape} != CT shape {ct_level.shape}"
            )
        pred_sampler = _NearestSampler(pred_level)
        ct_sampler = _NearestSampler(ct_level)

        for center_row in centers:
            center = tuple(int(v) for v in center_row["grid_yx"])
            for size in sizes:
                try:
                    candidates, generation, auxiliary = _generate_variant(
                        xyz=xyz,
                        valid=valid,
                        center=center,
                        deletion_size=size,
                        spec=spec,
                        pred_sampler=pred_sampler,
                        ct_sampler=ct_sampler,
                    )
                    variants.append(
                        _score_variant(
                            candidates=candidates,
                            generation=generation,
                            auxiliary=auxiliary,
                            xyz=xyz,
                            valid=valid,
                            center_row=center_row,
                            deletion_size=size,
                            spec=spec,
                        )
                    )
                except CoverageWitnessError as exc:
                    variants.append(
                        {
                            "status": "invalid",
                            "center_id": center_row["id"],
                            "center_grid_yx": list(center),
                            "deletion_size_vertices": int(size),
                            "error": str(exc),
                        }
                    )

        missing_pred = sorted([list(v) for v in pred_sampler.missing_chunks])
        missing_ct = sorted([list(v) for v in ct_sampler.missing_chunks])
        if missing_pred or missing_ct:
            raise StageCError(
                "source sampling encountered missing stored chunks; "
                f"prediction={len(missing_pred)} CT={len(missing_ct)}"
            )
    finally:
        session.close()

    decision = _decision(spec, variants)
    return {
        "schema": RESULT_SCHEMA,
        "status": "measured",
        "spec": {
            "path": str(spec_path),
            "sha256": spec_sha,
            "schema": spec["schema"],
        },
        "reference_surface": {
            "path": str(tifxyz),
            "observed_sha256": observed_hashes,
            "shape_yx": surface_info["shape_yx"],
            "valid_vertex_count": surface_info["valid_vertex_count"],
        },
        "holdout_source": {
            "reference_plan_path": str(reference_plan_path),
            "reference_plan_sha256": reference_plan_sha,
            "selected_center_count": len(centers),
        },
        "wrong_wrap_controls": {
            "path": str(wrong_wrap_result_path),
            "sha256": wrong_wrap_sha,
            "count": len(centers),
        },
        "independent_witness_source": {
            "prediction_url": source["prediction_url"],
            "ct_support_url": source["ct_support_url"],
            "model_id": source["model_id"],
            "stored_value_threshold": source["stored_value_threshold"],
            "missing_prediction_chunks": 0,
            "missing_ct_chunks": 0,
        },
        "variants": variants,
        "decision": decision,
        "claim_boundary": spec["claim_boundary"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--tifxyz", required=True)
    parser.add_argument("--reference-plan", required=True)
    parser.add_argument("--wrong-wrap-result", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    out = Path(args.out)
    if out.exists():
        parser.error(f"refusing to overwrite {out}")
    try:
        result = run(
            spec_path=Path(args.spec),
            tifxyz=Path(args.tifxyz),
            reference_plan_path=Path(args.reference_plan),
            wrong_wrap_result_path=Path(args.wrong_wrap_result),
        )
    except (
        StageCError,
        CoverageWitnessError,
        OSError,
        requests.RequestException,
    ) as exc:
        print(
            json.dumps(
                {"schema": RESULT_SCHEMA, "status": "invalid", "error": str(exc)}
            )
        )
        return 2

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
        handle.write("\n")

    print(
        json.dumps(
            {
                "schema": result["schema"],
                "status": result["status"],
                "decision": result["decision"]["status"],
                "measured_variants": result["decision"][
                    "variant_completeness"
                ]["measured"],
                "wrong_wrap_rejected": result["decision"][
                    "wrong_wrap_target_rejection"
                ]["rejected_count"],
                "size_41_competitors_recovered": result["decision"][
                    "size_41_competitor_recovery"
                ]["recovered_centers"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
