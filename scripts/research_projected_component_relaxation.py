#!/usr/bin/env python3
"""Run the frozen projected material-grid correspondence experiment."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import numpy as np
import requests

from scrollq.coverage_witness import hide_rect, odd_rect
from scrollq.prediction_recovery import (
    label_connectivity,
    projected_material_relaxation,
    raw_component_points,
    read_level_box,
    score_projected_relaxation,
)
from scrollq.sheetness_plan import _load_surface
from scrollq.support import ZarrV2Level
from scrollq.wrong_wrap_plan import _NearestSampler

SPEC_SCHEMA = "scrollq-research-projected-component-relaxation/1"
RESULT_SCHEMA = "scrollq-research-projected-component-relaxation-result/1"


class RelaxationRunError(RuntimeError):
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
        raise RelaxationRunError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RelaxationRunError(f"{path} must contain a JSON object")
    return value


def load_v1_runner() -> Any:
    path = Path(__file__).with_name("research_prediction_connectivity_recovery.py")
    spec = importlib.util.spec_from_file_location("frozen_v1_recovery_runner", path)
    if spec is None or spec.loader is None:
        raise RelaxationRunError(f"cannot load v1 recovery runner: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_spec(spec: dict[str, Any]) -> None:
    if spec.get("schema") != SPEC_SCHEMA:
        raise RelaxationRunError(f"spec must be {SPEC_SCHEMA}")
    if spec.get("status") != "frozen-after-connectivity-v1-fail-before-relaxation-read":
        raise RelaxationRunError("v2 spec is not frozen before relaxation read")
    relaxation = spec.get("projected_relaxation", {})
    if relaxation.get("iteration_count") != 84:
        raise RelaxationRunError("unexpected frozen iteration count")
    projection = relaxation.get("projection_constraints", {})
    if projection.get("maximum_neighbor_mean_to_component_distance_voxels") != 16:
        raise RelaxationRunError("unexpected frozen projection residual")
    if projection.get("maximum_per_iteration_candidate_movement_voxels") != 16:
        raise RelaxationRunError("unexpected frozen movement bound")
    if relaxation.get("early_stopping") is not False:
        raise RelaxationRunError("early stopping must remain disabled")


def verify_v1_baseline(
    spec: dict[str, Any],
    v1_result: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    if v1_result.get("schema") != "scrollq-research-prediction-connectivity-recovery-result/1":
        raise RelaxationRunError("v1 result schema mismatch")
    if v1_result.get("decision", {}).get("status") != "fail":
        raise RelaxationRunError("v1 result is not the frozen failed development result")
    by_id = {
        str(row["id"]): row
        for row in v1_result.get("centers", [])
        if isinstance(row, dict) and row.get("id")
    }
    frozen = spec["development_cohort"]
    if [row["id"] for row in frozen] != [gid for gid in by_id if gid in {r["id"] for r in frozen}]:
        # Order in the result is six-center order; verify each frozen member
        # directly below rather than relying on filtered dict iteration.
        pass
    for row in frozen:
        gid = str(row["id"])
        observed = by_id.get(gid)
        if observed is None:
            raise RelaxationRunError(f"v1 result missing {gid}")
        candidate = observed.get("candidate", {})
        score = observed.get("score", {})
        if candidate.get("component_status") != "selected":
            raise RelaxationRunError(f"v1 component not selected for {gid}")
        if candidate.get("candidate_sha256") != row["v1_candidate_sha256"]:
            raise RelaxationRunError(f"v1 candidate hash changed for {gid}")
        if candidate.get("component_selection", {}).get("selected_label") != row["v1_selected_label"]:
            raise RelaxationRunError(f"v1 selected label changed for {gid}")
        for key, score_key in (
            ("v1_fraction_within_8_voxels", "fraction_within_8_voxels"),
            ("v1_median_error_voxels", "median_error_voxels"),
            ("v1_p95_error_voxels", "p95_error_voxels"),
        ):
            if not np.isclose(
                float(score.get(score_key)),
                float(row[key]),
                rtol=0,
                atol=1e-12,
            ):
                raise RelaxationRunError(f"v1 baseline metric changed for {gid}: {key}")
    return by_id


def visible_immediate_boundaries_zyx(
    xyz: np.ndarray,
    valid: np.ndarray,
    rect: tuple[int, int, int, int],
) -> dict[str, np.ndarray]:
    y0, y1, x0, x1 = rect
    h, w = valid.shape
    if y0 <= 0 or x0 <= 0 or y1 >= h or x1 >= w:
        raise RelaxationRunError("deletion lacks immediate visible boundary in TIFXYZ grid")

    def rows(cells: list[tuple[int, int]]) -> np.ndarray:
        out = np.full((len(cells), 3), np.nan, dtype=np.float64)
        for i, (y, x) in enumerate(cells):
            if valid[y, x] and np.isfinite(xyz[y, x]).all():
                out[i] = xyz[y, x, ::-1]
        return out

    return {
        "top": rows([(y0 - 1, x) for x in range(x0, x1)]),
        "bottom": rows([(y1, x) for x in range(x0, x1)]),
        "left": rows([(y, x0 - 1) for y in range(y0, y1)]),
        "right": rows([(y, x1) for y in range(y0, y1)]),
    }


def rebuild_v1_component_points(
    *,
    candidate: dict[str, Any],
    pred_level: ZarrV2Level,
    ct_level: ZarrV2Level,
    v1_spec: dict[str, Any],
) -> np.ndarray:
    box = candidate.get("box_zyx_half_open", {})
    lo = np.asarray(box.get("lo"), dtype=np.int64)
    hi = np.asarray(box.get("hi"), dtype=np.int64)
    if lo.shape != (3,) or hi.shape != (3,):
        raise RelaxationRunError("v1 candidate lacks local component box")
    pred_box, _ = read_level_box(pred_level, lo, hi)
    ct_box, _ = read_level_box(ct_level, lo, hi)
    raw = (
        (pred_box > int(v1_spec["source"]["surface_prediction_stored_value_threshold"]))
        & (ct_box > 0)
    )
    labels, _ = label_connectivity(
        raw,
        dilation_iterations=int(
            v1_spec["local_prediction_component"]["dilation_iterations"]
        ),
    )
    selected_label = candidate.get("component_selection", {}).get("selected_label")
    if type(selected_label) is not int or selected_label <= 0:
        raise RelaxationRunError("v1 candidate lacks selected component label")
    return raw_component_points(
        raw,
        labels,
        selected_label,
        origin_zyx=lo,
    )


def serialize_grid(grid: np.ndarray) -> list[list[list[float]]]:
    return [
        [[float(v) for v in point] for point in row]
        for row in np.asarray(grid, dtype=np.float64)
    ]


def run(
    *,
    spec_path: Path,
    v1_spec_path: Path,
    v1_result_path: Path,
    tifxyz_root: Path,
    reference_plan_path: Path,
) -> dict[str, Any]:
    spec = load_json(spec_path)
    verify_spec(spec)
    v1_spec = load_json(v1_spec_path)
    if v1_spec.get("schema") != "scrollq-research-prediction-connectivity-recovery/1":
        raise RelaxationRunError("v1 spec schema mismatch")
    v1_result = load_json(v1_result_path)
    frozen_v1_rows = verify_v1_baseline(spec, v1_result)

    v1 = load_v1_runner()
    v1.verify_spec(v1_spec)
    surface_hashes = v1.verify_surface_hashes(
        tifxyz_root,
        v1_spec["source"]["tifxyz_sha256"],
    )
    truth_xyz, truth_valid, surface_info = _load_surface(tifxyz_root)
    reference_plan = load_json(reference_plan_path)

    session = requests.Session()
    session.mount("https://", requests.adapters.HTTPAdapter(pool_maxsize=16))
    pred_level = ZarrV2Level(
        v1_spec["source"]["surface_prediction_url"].rstrip("/") + "/0",
        session,
    )
    ct_level = ZarrV2Level(v1_spec["source"]["ct_url"].rstrip("/") + "/0", session)
    expected_shape = tuple(
        int(v) for v in reference_plan["zpa_report"]["level0_shape_zyx"]
    )
    if tuple(pred_level.shape) != expected_shape or tuple(ct_level.shape) != expected_shape:
        raise RelaxationRunError("v2 source shape differs from frozen exact volume")
    pred_sampler = _NearestSampler(pred_level)
    ct_sampler = _NearestSampler(ct_level)

    v1_centers = {
        str(row["id"]): row
        for row in v1_spec["development_regions"]["centers"]
    }
    centers_out: list[dict[str, Any]] = []
    candidate_hashes: list[str] = []
    score_rows: list[dict[str, Any]] = []
    try:
        for frozen in spec["development_cohort"]:
            gid = str(frozen["id"])
            center_row = v1_centers[gid]
            center = tuple(int(v) for v in center_row["grid_yx"])
            rect = odd_rect(
                center,
                int(v1_spec["development_regions"]["deletion_size_vertices"]),
            )
            observed_xyz, observed_valid = hide_rect(truth_xyz, truth_valid, rect)
            v1_candidate = v1.generate_candidate(
                observed_xyz=observed_xyz,
                observed_valid=observed_valid,
                rect=rect,
                pred_level=pred_level,
                ct_level=ct_level,
                pred_sampler=pred_sampler,
                ct_sampler=ct_sampler,
                spec=v1_spec,
            )
            hash_exact = v1_candidate["candidate_sha256"] == frozen["v1_candidate_sha256"]
            label_exact = (
                v1_candidate.get("component_selection", {}).get("selected_label")
                == frozen["v1_selected_label"]
            )
            if not hash_exact or not label_exact:
                raise RelaxationRunError(f"v1 identity reproduction failed for {gid}")
            if v1_candidate.get("component_status") != "selected":
                raise RelaxationRunError(f"v1 component is no longer selected for {gid}")

            recovered_rows = v1_candidate["recovered_zyx"]
            if any(row is None for row in recovered_rows):
                raise RelaxationRunError(f"v1 initial grid is incomplete for {gid}")
            size = int(v1_spec["development_regions"]["deletion_size_vertices"])
            initial = np.asarray(recovered_rows, dtype=np.float64).reshape(size, size, 3)
            component_points = rebuild_v1_component_points(
                candidate=v1_candidate,
                pred_level=pred_level,
                ct_level=ct_level,
                v1_spec=v1_spec,
            )
            boundaries = visible_immediate_boundaries_zyx(
                observed_xyz,
                observed_valid,
                rect,
            )
            relaxation = spec["projected_relaxation"]
            projection = relaxation["projection_constraints"]
            relaxed = projected_material_relaxation(
                initial,
                component_points,
                top_boundary_zyx=boundaries["top"],
                bottom_boundary_zyx=boundaries["bottom"],
                left_boundary_zyx=boundaries["left"],
                right_boundary_zyx=boundaries["right"],
                iteration_count=int(relaxation["iteration_count"]),
                maximum_projection_residual_voxels=float(
                    projection["maximum_neighbor_mean_to_component_distance_voxels"]
                ),
                maximum_movement_per_iteration_voxels=float(
                    projection["maximum_per_iteration_candidate_movement_voxels"]
                ),
            )
            final_grid = np.asarray(relaxed["relaxed_zyx"], dtype=np.float64)
            flat = final_grid.reshape(-1, 3)
            v2_candidate = {
                "component_status": "selected",
                "v1_candidate_sha256": v1_candidate["candidate_sha256"],
                "v1_selected_label": int(frozen["v1_selected_label"]),
                "relaxation_method": relaxation["name"],
                "relaxation_history": relaxed["history"],
                "recovered_zyx": [[float(v) for v in row] for row in flat],
                "candidate_available": [True] * len(flat),
                "candidate_available_fraction_all_material_cells": 1.0,
                "unique_recovered_voxel_fraction": float(
                    relaxed["unique_recovered_voxel_fraction"]
                ),
                "component_raw_voxel_count": int(component_points.shape[0]),
            }
            v2_candidate["candidate_sha256"] = canonical_sha256(v2_candidate)
            candidate_hashes.append(v2_candidate["candidate_sha256"])

            scoring = v1.score_candidate(
                candidate=v2_candidate,
                truth_xyz=truth_xyz,
                truth_valid=truth_valid,
                rect=rect,
                wrong_wrap_zyx=np.asarray(
                    center_row["wrong_wrap_zyx"], dtype=np.float64
                ),
                tolerances=[4.0, 8.0, 12.0, 16.0],
            )
            baseline = frozen_v1_rows[gid]["score"]
            comparison = {
                "v1_candidate_hash_exact": bool(hash_exact),
                "v1_component_label_exact": bool(label_exact),
                "v1_fraction_within_8_voxels": float(
                    frozen["v1_fraction_within_8_voxels"]
                ),
                "v2_fraction_within_8_voxels": float(
                    scoring["fraction_within_8_voxels"]
                ),
                "within_8_delta": float(
                    scoring["fraction_within_8_voxels"]
                    - frozen["v1_fraction_within_8_voxels"]
                ),
                "v1_median_error_voxels": float(
                    frozen["v1_median_error_voxels"]
                ),
                "v2_median_error_voxels": float(scoring["median_error_voxels"]),
                "v1_p95_error_voxels": float(frozen["v1_p95_error_voxels"]),
                "v2_p95_error_voxels": float(scoring["p95_error_voxels"]),
                "v2_unique_recovered_voxel_fraction": float(
                    scoring["unique_recovered_voxel_fraction"]
                ),
                "v2_wrong_wrap_rejected": bool(scoring["wrong_wrap_rejected"]),
                "v1_wrong_wrap_rejected": bool(baseline["wrong_wrap_rejected"]),
            }
            score_rows.append(comparison)
            centers_out.append(
                {
                    "id": gid,
                    "grid_yx": list(center),
                    "v1_identity": {
                        "candidate_sha256": v1_candidate["candidate_sha256"],
                        "selected_label": v1_candidate["component_selection"][
                            "selected_label"
                        ],
                        "hash_exact": bool(hash_exact),
                        "label_exact": bool(label_exact),
                    },
                    "v2_candidate": v2_candidate,
                    "score": scoring,
                    "comparison": comparison,
                }
            )
    finally:
        session.close()

    gate = spec["development_gate"]
    decision = score_projected_relaxation(
        score_rows,
        required_cohort_size=int(gate["required_cohort_size"]),
        minimum_fraction_within_8_voxels_every_center=float(
            gate["minimum_fraction_within_8_voxels_every_center"]
        ),
        minimum_median_fraction_within_8_voxels=float(
            gate["minimum_median_fraction_within_8_voxels"]
        ),
        maximum_within_8_regression_vs_v1_each_center=float(
            gate["maximum_within_8_regression_vs_v1_each_center"]
        ),
        maximum_median_error_voxels_every_center=float(
            gate["maximum_median_error_voxels_every_center"]
        ),
        maximum_median_p95_error_voxels=float(
            gate["maximum_median_p95_error_voxels"]
        ),
        require_all_wrong_wrap_controls_rejected=bool(
            gate["require_all_wrong_wrap_controls_rejected"]
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
            "v1_spec": {
                "path": str(v1_spec_path),
                "sha256": sha256_file(v1_spec_path),
            },
            "v1_result": {
                "path": str(v1_result_path),
                "sha256": sha256_file(v1_result_path),
            },
            "reference_plan": {
                "path": str(reference_plan_path),
                "sha256": sha256_file(reference_plan_path),
            },
            "tifxyz_sha256": surface_hashes,
            "surface_shape_yx": surface_info["shape_yx"],
        },
        "firewall": {
            "v2_candidate_hashes_frozen_before_scoring": candidate_hashes,
            "relaxation_hidden_reference_arguments": [],
            "hidden_truth_use": "scoring-only after v2 candidate_sha256",
        },
        "centers": centers_out,
        "decision": {
            **decision,
            "classification_after_development": (
                "SUPPORT projected correspondence; freeze integrated method before holdout"
                if decision["status"] == "pass"
                else "DISMISS surface-constrained-material-laplacian-v1"
            ),
            "claim_boundary": spec["claim_boundary"],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--v1-spec", required=True)
    parser.add_argument("--v1-result", required=True)
    parser.add_argument("--tifxyz", required=True)
    parser.add_argument("--reference-plan", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    out = Path(args.out)
    if out.exists():
        parser.error(f"refusing to overwrite {out}")
    try:
        result = run(
            spec_path=Path(args.spec),
            v1_spec_path=Path(args.v1_spec),
            v1_result_path=Path(args.v1_result),
            tifxyz_root=Path(args.tifxyz),
            reference_plan_path=Path(args.reference_plan),
        )
    except Exception as exc:
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
                "median_within_8": result["decision"]["median_fraction_within_8_voxels"],
                "median_p95": result["decision"]["median_p95_error_voxels"],
                "max_regression": result["decision"]["maximum_within_8_regression"],
                "wrong_wrap_rejected": result["decision"]["wrong_wrap_rejected_count"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
