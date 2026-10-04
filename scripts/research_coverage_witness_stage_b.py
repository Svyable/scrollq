#!/usr/bin/env python3
"""Run the preregistered identity-aware coverage-witness Stage-B experiment."""
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
    centered_normal_xyz,
    classify_runs,
    harmonic_continue_rect,
    hide_rect,
    odd_rect,
    supported_runs,
)
from scrollq.sheetness_plan import _load_surface
from scrollq.support import ZarrV2Level
from scrollq.wrong_wrap_plan import _NearestSampler


SPEC_SCHEMA = "scrollq-research-coverage-witness-stage-b/1"
RESULT_SCHEMA = "scrollq-research-coverage-witness-stage-b-result/1"


class StageBError(RuntimeError):
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
        raise StageBError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise StageBError(f"{path} must contain a JSON object")
    return value


def _load_spec(path: str | Path) -> tuple[dict[str, Any], str]:
    spec = _load_json(path)
    if spec.get("schema") != SPEC_SCHEMA:
        raise StageBError(f"spec must be {SPEC_SCHEMA}")
    if spec.get("status") != "frozen-before-stage-b-witness-read":
        raise StageBError("spec is not frozen-before-stage-b-witness-read")
    return spec, sha256_file(path)


def _verify_tifxyz_hashes(root: Path, expected: dict[str, Any]) -> dict[str, str]:
    observed: dict[str, str] = {}
    for name, expected_digest in expected.items():
        path = root / name
        if not path.is_file():
            raise StageBError(f"missing TIFXYZ file: {path}")
        digest = sha256_file(path)
        observed[name] = digest
        if digest != expected_digest:
            raise StageBError(
                f"TIFXYZ hash mismatch for {name}: {digest} != {expected_digest}"
            )
    return observed


def _verify_wrong_wrap_controls(
    spec: dict[str, Any],
    wrong_wrap_result_path: Path,
) -> str:
    result = _load_json(wrong_wrap_result_path)
    if result.get("schema") != "scroliq-wrong-wrap-plan/1":
        raise StageBError("wrong-wrap result schema mismatch")
    by_id = {
        row.get("id"): row
        for row in result.get("groups", [])
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    for center in spec["frozen_regions"]["centers"]:
        row = by_id.get(center["id"])
        if not isinstance(row, dict) or row.get("status") != "found":
            raise StageBError(f"wrong-wrap control missing for {center['id']}")
        expected = np.asarray(center["wrong_wrap_zyx"], dtype=np.float64)
        actual = np.asarray(row.get("global_zyx"), dtype=np.float64)
        if actual.shape != (3,) or not np.allclose(actual, expected, atol=1e-12, rtol=0):
            raise StageBError(f"wrong-wrap coordinate changed for {center['id']}")
        if float(row.get("signed_distance_voxels")) != float(
            center["wrong_wrap_signed_distance_voxels"]
        ):
            raise StageBError(f"wrong-wrap signed distance changed for {center['id']}")
    return sha256_file(wrong_wrap_result_path)


def _window_contains_boundary(
    center: tuple[int, int],
    deletion_size: int,
    evaluation_size: int,
) -> bool:
    dy0, dy1, dx0, dx1 = odd_rect(center, deletion_size)
    wy0, wy1, wx0, wx1 = odd_rect(center, evaluation_size)
    return (
        wy0 <= dy0 - 1
        and dy1 + 1 <= wy1
        and wx0 <= dx0 - 1
        and dx1 + 1 <= wx1
    )


def _ray_candidate(
    *,
    y: int,
    x: int,
    filled_xyz: np.ndarray,
    filled_valid: np.ndarray,
    offsets: np.ndarray,
    pred_sampler: _NearestSampler,
    ct_sampler: _NearestSampler,
    threshold: int,
    min_run: int,
    target_abs_max: float,
    competitor_abs_min: float,
    competitor_abs_max: float,
) -> dict[str, Any] | None:
    normal_xyz = centered_normal_xyz(filled_xyz, filled_valid, y, x)
    if normal_xyz is None:
        return None
    continued_xyz = np.asarray(filled_xyz[y, x], dtype=np.float64)
    if not np.isfinite(continued_xyz).all():
        return None

    continued_zyx = continued_xyz[::-1]
    normal_zyx = normal_xyz[::-1]
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
        min_run_voxels=min_run,
    )
    classified = classify_runs(
        runs,
        target_abs_max=target_abs_max,
        competitor_abs_min=competitor_abs_min,
        competitor_abs_max=competitor_abs_max,
    )

    target = classified["target"]
    target_midpoint = None if target is None else float(target.midpoint)
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
        "target_midpoint": target_midpoint,
        "target_coordinate_zyx": target_coord,
        "target_run": None if target is None else target.as_dict(),
        "target_candidate_count": len(classified["target_candidates"]),
        "guard_run_count": len(classified["guard"]),
        "competitors": competitors,
        "all_run_count": len(runs),
    }


def _generate_variant_candidates(
    *,
    xyz: np.ndarray,
    valid: np.ndarray,
    center: tuple[int, int],
    deletion_size: int,
    evaluation_size: int,
    ray_spec: dict[str, Any],
    pred_sampler: _NearestSampler,
    ct_sampler: _NearestSampler,
    threshold: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not _window_contains_boundary(center, deletion_size, evaluation_size):
        raise StageBError(
            f"{deletion_size} deletion does not leave one-cell boundary "
            f"inside {evaluation_size} evaluation window"
        )

    rect = odd_rect(center, deletion_size)
    observed_xyz, observed_valid = hide_rect(xyz, valid, rect)
    filled_xyz, filled_valid, continuation_report = harmonic_continue_rect(
        observed_xyz, observed_valid, rect
    )

    offsets = np.asarray(ray_spec["signed_offsets_voxels"], dtype=np.float64)
    if not np.all(np.diff(offsets) == 1):
        raise StageBError("frozen ray offsets are not contiguous unit steps")

    rows: list[dict[str, Any]] = []
    y0, y1, x0, x1 = rect
    for y in range(y0, y1):
        for x in range(x0, x1):
            row = _ray_candidate(
                y=y,
                x=x,
                filled_xyz=filled_xyz,
                filled_valid=filled_valid,
                offsets=offsets,
                pred_sampler=pred_sampler,
                ct_sampler=ct_sampler,
                threshold=threshold,
                min_run=int(ray_spec["min_run_voxels"]),
                target_abs_max=float(
                    ray_spec["target_band_abs_midpoint_voxels_max"]
                ),
                competitor_abs_min=float(
                    ray_spec["competing_band_abs_midpoint_voxels_min"]
                ),
                competitor_abs_max=float(
                    ray_spec["competing_band_abs_midpoint_voxels_max"]
                ),
            )
            if row is not None:
                rows.append(row)

    return rows, {
        "rect_yx_half_open": list(rect),
        "evaluation_window_yx_half_open": list(
            odd_rect(center, evaluation_size)
        ),
        "continuation": continuation_report,
        "candidate_grid_count": len(rows),
        "candidate_sha256": canonical_sha256(rows),
    }


def _quantiles(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    array = np.asarray(values, dtype=np.float64)
    return {
        "min": float(np.min(array)),
        "median": float(np.median(array)),
        "p95": float(np.quantile(array, 0.95)),
        "max": float(np.max(array)),
    }


def _score_variant(
    *,
    candidates: list[dict[str, Any]],
    generation: dict[str, Any],
    xyz: np.ndarray,
    valid: np.ndarray,
    center_row: dict[str, Any],
    deletion_size: int,
    correct_tolerance: float,
    omission_tolerance: float,
) -> dict[str, Any]:
    rect = tuple(int(v) for v in generation["rect_yx_half_open"])
    y0, y1, x0, x1 = rect

    delete = np.zeros_like(valid, dtype=bool)
    delete[y0:y1, x0:x1] = True
    outside_points_xyz = np.asarray(xyz[valid & ~delete], dtype=np.float64)
    if outside_points_xyz.size == 0:
        raise StageBError("counterfactual submitted surface is empty")
    outside_tree = cKDTree(np.ascontiguousarray(outside_points_xyz[:, ::-1]))

    by_yx = {
        (int(row["grid_yx"][0]), int(row["grid_yx"][1])): row
        for row in candidates
    }

    eligible = []
    continuation_errors: list[float] = []
    target_rows = []
    correct_rows = []
    omission_hits = 0
    guard_runs = 0
    competitor_runs = 0

    for y in range(y0, y1):
        for x in range(x0, x1):
            row = by_yx.get((y, x))
            if row is None:
                continue
            if not valid[y, x] or not np.isfinite(xyz[y, x]).all():
                continue
            eligible.append(row)
            true_zyx = np.asarray(xyz[y, x, ::-1], dtype=np.float64)
            continued_zyx = np.asarray(row["continued_zyx"], dtype=np.float64)
            continuation_errors.append(
                float(np.linalg.norm(continued_zyx - true_zyx))
            )
            guard_runs += int(row["guard_run_count"])
            competitor_runs += len(row["competitors"])

            target_coord = row["target_coordinate_zyx"]
            if target_coord is None:
                continue
            target_rows.append(row)
            target_zyx = np.asarray(target_coord, dtype=np.float64)
            target_error = float(np.linalg.norm(target_zyx - true_zyx))
            if target_error > correct_tolerance:
                continue
            correct_rows.append(row)
            distance, _ = outside_tree.query(target_zyx, k=1, workers=1)
            if float(distance) > omission_tolerance:
                omission_hits += 1

    wrong = np.asarray(center_row["wrong_wrap_zyx"], dtype=np.float64)
    all_target_coords = [
        np.asarray(row["target_coordinate_zyx"], dtype=np.float64)
        for row in candidates
        if row["target_coordinate_zyx"] is not None
    ]
    if all_target_coords:
        target_stack = np.stack(all_target_coords, axis=0)
        wrong_wrap_min_target_distance = float(
            np.linalg.norm(target_stack - wrong[None, :], axis=1).min()
        )
    else:
        wrong_wrap_min_target_distance = None

    center_key = tuple(int(v) for v in center_row["grid_yx"])
    center_candidate = by_yx.get(center_key)
    center_competitor_distances: list[float] = []
    if center_candidate is not None:
        for comp in center_candidate["competitors"]:
            coord = np.asarray(comp["coordinate_zyx"], dtype=np.float64)
            center_competitor_distances.append(float(np.linalg.norm(coord - wrong)))
    center_competitor_min_distance = (
        min(center_competitor_distances)
        if center_competitor_distances
        else None
    )
    center_competitor_recovered = (
        center_competitor_min_distance is not None
        and center_competitor_min_distance <= correct_tolerance
    )

    eligible_count = len(eligible)
    target_count = len(target_rows)
    correct_count = len(correct_rows)
    target_fraction = (
        float(target_count / eligible_count) if eligible_count else None
    )
    correct_recall = (
        float(correct_count / eligible_count) if eligible_count else None
    )
    target_precision = (
        float(correct_count / target_count) if target_count else None
    )
    omission_recall = (
        float(omission_hits / correct_count) if correct_count else None
    )

    return {
        "center_id": center_row["id"],
        "center_grid_yx": list(center_key),
        "deletion_size_vertices": int(deletion_size),
        "rect_yx_half_open": list(rect),
        "generation": generation,
        "eligible_hidden_count": eligible_count,
        "target_witness_count": target_count,
        "correct_target_count": correct_count,
        "target_witness_fraction": target_fraction,
        "correct_target_recall": correct_recall,
        "target_precision": target_precision,
        "omission_recall_among_correct_targets": omission_recall,
        "wrong_wrap_min_target_distance_voxels": wrong_wrap_min_target_distance,
        "wrong_wrap_rejected": (
            wrong_wrap_min_target_distance is None
            or wrong_wrap_min_target_distance > correct_tolerance
        ),
        "competitor_run_count": int(competitor_runs),
        "guard_band_run_count": int(guard_runs),
        "center_competitor_min_wrong_wrap_distance_voxels": (
            center_competitor_min_distance
        ),
        "center_competitor_recovered": bool(center_competitor_recovered),
        "continuation_error_quantiles_scoring_only": _quantiles(
            continuation_errors
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


def _decision(
    spec: dict[str, Any], variants: list[dict[str, Any]]
) -> dict[str, Any]:
    rule = spec["decision_rule"]
    sizes = [int(v) for v in spec["frozen_regions"]["deletion_sizes_vertices"]]
    expected = len(spec["frozen_regions"]["centers"]) * len(sizes)
    complete = len(variants) == expected

    min_targets = int(rule["minimum_target_witnesses_each_variant"])
    min_recall = float(rule["every_variant_min_correct_target_recall"])
    median_recall_required = float(
        rule["median_correct_target_recall_each_size"]
    )
    min_precision = float(rule["every_variant_min_target_precision"])
    median_precision_required = float(
        rule["median_target_precision_each_size"]
    )
    min_omission = float(
        rule["every_variant_min_omission_recall_among_correct_targets"]
    )
    median_omission_required = float(
        rule["median_omission_recall_among_correct_targets_each_size"]
    )

    by_size: dict[str, Any] = {}
    all_numeric_ok = complete

    for size in sizes:
        rows = [v for v in variants if int(v["deletion_size_vertices"]) == size]
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

        size_ok = (
            len(rows) == len(spec["frozen_regions"]["centers"])
            and all(int(v["target_witness_count"]) >= min_targets for v in rows)
            and all(
                v["correct_target_recall"] is not None
                and float(v["correct_target_recall"]) >= min_recall
                for v in rows
            )
            and (_median(recalls) or 0.0) >= median_recall_required
            and all(
                v["target_precision"] is not None
                and float(v["target_precision"]) >= min_precision
                for v in rows
            )
            and (_median(precisions) or 0.0) >= median_precision_required
            and all(
                v["omission_recall_among_correct_targets"] is not None
                and float(v["omission_recall_among_correct_targets"]) >= min_omission
                for v in rows
            )
            and (_median(omissions) or 0.0) >= median_omission_required
        )
        all_numeric_ok = all_numeric_ok and size_ok
        by_size[str(size)] = {
            "variant_count": len(rows),
            "min_target_witness_count": (
                min(int(v["target_witness_count"]) for v in rows) if rows else None
            ),
            "min_correct_target_recall": min(recalls) if recalls else None,
            "median_correct_target_recall": _median(recalls),
            "min_target_precision": min(precisions) if precisions else None,
            "median_target_precision": _median(precisions),
            "min_omission_recall": min(omissions) if omissions else None,
            "median_omission_recall": _median(omissions),
            "pass": bool(size_ok),
        }

    wrong_wrap_ok = all(bool(v["wrong_wrap_rejected"]) for v in variants)
    size41 = [v for v in variants if int(v["deletion_size_vertices"]) == 41]
    recovered = sum(bool(v["center_competitor_recovered"]) for v in size41)
    competitor_ok = recovered >= int(
        rule["size_41_min_centers_with_wrong_wrap_competitor_recovered"]
    )

    passed = bool(
        complete
        and all_numeric_ok
        and wrong_wrap_ok
        and competitor_ok
    )
    return {
        "status": "pass" if passed else "fail",
        "variant_completeness": {
            "expected": expected,
            "observed": len(variants),
            "pass": bool(complete),
        },
        "by_size": by_size,
        "wrong_wrap_target_rejection": {
            "required_all": bool(
                rule["require_all_wrong_wraps_rejected_as_targets"]
            ),
            "rejected_count": sum(bool(v["wrong_wrap_rejected"]) for v in variants),
            "variant_count": len(variants),
            "pass": bool(wrong_wrap_ok),
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
    wrong_wrap_result_path: Path,
) -> dict[str, Any]:
    spec, spec_sha = _load_spec(spec_path)
    observed_hashes = _verify_tifxyz_hashes(
        tifxyz, spec["reference_surface"]["tifxyz_sha256"]
    )
    wrong_wrap_sha = _verify_wrong_wrap_controls(
        spec, wrong_wrap_result_path
    )

    xyz, valid, surface_info = _load_surface(tifxyz)
    regions = spec["frozen_regions"]
    sizes = [int(v) for v in regions["deletion_sizes_vertices"]]
    evaluation_size = int(regions["evaluation_window_size_vertices"])
    ray_spec = spec["normal_ray_decomposition"]
    scoring = spec["scoring"]
    source = spec["independent_witness_source"]

    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(pool_maxsize=16)
    session.mount("https://", adapter)
    variants: list[dict[str, Any]] = []
    try:
        pred_level = ZarrV2Level(source["prediction_url"].rstrip("/") + "/0", session)
        ct_level = ZarrV2Level(source["ct_support_url"].rstrip("/") + "/0", session)
        if tuple(pred_level.shape) != tuple(ct_level.shape):
            raise StageBError(
                f"prediction shape {pred_level.shape} != CT shape {ct_level.shape}"
            )
        pred_sampler = _NearestSampler(pred_level)
        ct_sampler = _NearestSampler(ct_level)

        for center_row in regions["centers"]:
            center = tuple(int(v) for v in center_row["grid_yx"])
            for size in sizes:
                candidates, generation = _generate_variant_candidates(
                    xyz=xyz,
                    valid=valid,
                    center=center,
                    deletion_size=size,
                    evaluation_size=evaluation_size,
                    ray_spec=ray_spec,
                    pred_sampler=pred_sampler,
                    ct_sampler=ct_sampler,
                    threshold=int(source["stored_value_threshold"]),
                )
                variants.append(
                    _score_variant(
                        candidates=candidates,
                        generation=generation,
                        xyz=xyz,
                        valid=valid,
                        center_row=center_row,
                        deletion_size=size,
                        correct_tolerance=float(
                            scoring["correct_target_tolerance_voxels"]
                        ),
                        omission_tolerance=float(
                            scoring["omission_tolerance_voxels"]
                        ),
                    )
                )

        missing_pred = sorted([list(v) for v in pred_sampler.missing_chunks])
        missing_ct = sorted([list(v) for v in ct_sampler.missing_chunks])
        if missing_pred or missing_ct:
            raise StageBError(
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
        "wrong_wrap_controls": {
            "path": str(wrong_wrap_result_path),
            "sha256": wrong_wrap_sha,
            "count": len(regions["centers"]),
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
            wrong_wrap_result_path=Path(args.wrong_wrap_result),
        )
    except (
        StageBError,
        CoverageWitnessError,
        OSError,
        requests.RequestException,
    ) as exc:
        print(json.dumps({"schema": RESULT_SCHEMA, "status": "invalid", "error": str(exc)}))
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
