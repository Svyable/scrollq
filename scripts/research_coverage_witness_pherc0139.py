#!/usr/bin/env python3
"""Run the preregistered PHerc0139 coverage-witness deletion control.

Research-only runner for issue #151. It deliberately reuses the exact w035
TIFXYZ plus the independently published surface-m7 prediction frozen in
a previously merged coverage-witness preregistration.

This is not a production ScrollQ diagnostic and is not installed as a CLI.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import requests
from scipy.spatial import cKDTree

from scrollq.sheetness_plan import _load_surface, _normal_at_grid
from scrollq.support import ZarrV2Level
from scrollq.wrong_wrap_plan import _NearestSampler


SPEC_SCHEMAS = {
    "scrollq-research-coverage-witness-pherc0139/1": {
        "status": "frozen-before-witness-read",
        "result_schema": "scrollq-research-coverage-witness-pherc0139-result/1",
    },
    "scrollq-research-coverage-witness-pherc0139/2": {
        "status": "frozen-before-v2-witness-read",
        "result_schema": "scrollq-research-coverage-witness-pherc0139-result/2",
    },
}


class ExperimentError(RuntimeError):
    pass


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_spec(path: str | Path) -> tuple[dict[str, Any], str]:
    path = Path(path)
    try:
        spec = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExperimentError(f"cannot read spec: {exc}") from exc
    if not isinstance(spec, dict) or spec.get("schema") not in SPEC_SCHEMAS:
        raise ExperimentError(
            "unsupported coverage-witness spec schema: "
            f"{None if not isinstance(spec, dict) else spec.get('schema')!r}"
        )
    contract = SPEC_SCHEMAS[spec["schema"]]
    if spec.get("status") != contract["status"]:
        raise ExperimentError(
            f"spec status must be {contract['status']!r} for {spec['schema']}"
        )
    return spec, sha256_file(path)


def _verify_tifxyz_hashes(root: Path, expected: dict[str, Any]) -> dict[str, str]:
    observed: dict[str, str] = {}
    for name, digest in expected.items():
        path = root / name
        if not path.is_file():
            raise ExperimentError(f"missing TIFXYZ file: {path}")
        actual = sha256_file(path)
        observed[name] = actual
        if actual != digest:
            raise ExperimentError(
                f"TIFXYZ hash mismatch for {name}: {actual} != {digest}"
            )
    return observed


def _rect(center: tuple[int, int], size: int) -> tuple[int, int, int, int]:
    if size <= 0 or size % 2 != 1:
        raise ExperimentError("deletion sizes must be positive odd integers")
    y, x = center
    half = size // 2
    return y - half, y + half + 1, x - half, x + half + 1


def _inside(y: int, x: int, rect: tuple[int, int, int, int]) -> bool:
    y0, y1, x0, x1 = rect
    return y0 <= y < y1 and x0 <= x < x1


def _surface_points_zyx(xyz: np.ndarray, keep: np.ndarray) -> np.ndarray:
    pts = np.asarray(xyz[keep], dtype=np.float64)
    if pts.size == 0:
        raise ExperimentError("counterfactual surface has no valid points")
    return np.ascontiguousarray(pts[:, ::-1])


def _normal_shifted_patch_zyx(
    xyz: np.ndarray,
    valid: np.ndarray,
    rect: tuple[int, int, int, int],
    *,
    shift_voxels: float,
) -> np.ndarray:
    y0, y1, x0, x1 = rect
    rows: list[np.ndarray] = []
    for y in range(y0, y1):
        for x in range(x0, x1):
            if not valid[y, x]:
                continue
            normal_xyz = _normal_at_grid(xyz, valid, y, x)
            if normal_xyz is None:
                continue
            point_xyz = np.asarray(xyz[y, x], dtype=np.float64)
            shifted_xyz = point_xyz + float(shift_voxels) * normal_xyz
            rows.append(shifted_xyz[::-1])
    if not rows:
        return np.empty((0, 3), dtype=np.float64)
    return np.ascontiguousarray(np.stack(rows, axis=0), dtype=np.float64)


def _candidate_order(offsets: list[float]) -> list[int]:
    # Exact zero first; otherwise smaller absolute distance, negative before
    # positive on an exact tie.
    return sorted(
        range(len(offsets)),
        key=lambda i: (
            abs(float(offsets[i])),
            0 if float(offsets[i]) == 0 else 1,
            0 if float(offsets[i]) < 0 else 1,
        ),
    )


def _witnesses_for_window(
    *,
    xyz: np.ndarray,
    valid: np.ndarray,
    center: tuple[int, int],
    max_size: int,
    offsets: list[float],
    threshold: int,
    pred_sampler: _NearestSampler,
    ct_sampler: _NearestSampler,
) -> dict[str, Any]:
    y0, y1, x0, x1 = _rect(center, max_size)
    h, w = valid.shape
    if y0 < 1 or x0 < 1 or y1 > h - 1 or x1 > w - 1:
        raise ExperimentError(
            f"max deletion window around {center} exceeds centered-normal bounds"
        )

    order = _candidate_order(offsets)
    rows: list[dict[str, Any]] = []
    valid_count = 0
    normal_count = 0

    for y in range(y0, y1):
        for x in range(x0, x1):
            if not valid[y, x]:
                continue
            valid_count += 1
            normal_xyz = _normal_at_grid(xyz, valid, y, x)
            if normal_xyz is None:
                continue
            normal_count += 1
            surface_xyz = np.asarray(xyz[y, x], dtype=np.float64)
            surface_zyx = surface_xyz[::-1]
            normal_zyx = np.asarray(normal_xyz[::-1], dtype=np.float64)
            coords = np.stack(
                [surface_zyx + float(offset) * normal_zyx for offset in offsets],
                axis=0,
            )
            pred_values, pred_valid = pred_sampler.sample(coords)
            ct_values, ct_valid = ct_sampler.sample(coords)
            supported = (
                pred_valid
                & ct_valid
                & (pred_values > int(threshold))
                & (ct_values > 0)
            )
            chosen = next((i for i in order if bool(supported[i])), None)
            if chosen is None:
                continue
            rows.append(
                {
                    "grid_yx": [int(y), int(x)],
                    "offset_voxels": float(offsets[chosen]),
                    "witness_zyx": [float(v) for v in coords[chosen]],
                    "prediction_value": int(pred_values[chosen]),
                    "ct_value": int(ct_values[chosen]),
                }
            )

    return {
        "window_rect_yx_half_open": [y0, y1, x0, x1],
        "valid_vertex_count": int(valid_count),
        "valid_centered_normal_count": int(normal_count),
        "witness_count": len(rows),
        "witness_fraction_of_valid_normals": (
            float(len(rows) / normal_count) if normal_count else 0.0
        ),
        "witnesses": rows,
    }


def _query(points: np.ndarray, witnesses: list[dict[str, Any]]) -> np.ndarray:
    if not witnesses:
        return np.empty(0, dtype=np.float64)
    tree = cKDTree(points)
    query = np.asarray([row["witness_zyx"] for row in witnesses], dtype=np.float64)
    distances, _ = tree.query(query, k=1, workers=1)
    return np.asarray(distances, dtype=np.float64)


def _score_distances(
    *,
    witnesses: list[dict[str, Any]],
    distances: np.ndarray,
    rect: tuple[int, int, int, int],
    tolerances: list[float],
) -> dict[str, Any]:
    inside_mask = np.asarray(
        [
            _inside(int(row["grid_yx"][0]), int(row["grid_yx"][1]), rect)
            for row in witnesses
        ],
        dtype=bool,
    )
    outside_mask = ~inside_mask

    rows: dict[str, Any] = {}
    for tol in tolerances:
        inside = distances[inside_mask]
        outside = distances[outside_mask]
        rows[str(float(tol))] = {
            "deleted_witness_count": int(inside.size),
            "outside_witness_count": int(outside.size),
            "deletion_recall": (
                float(np.mean(inside > float(tol))) if inside.size else None
            ),
            "outside_stability": (
                float(np.mean(outside <= float(tol))) if outside.size else None
            ),
            "deleted_distance_quantiles": (
                {
                    "min": float(np.min(inside)),
                    "median": float(np.median(inside)),
                    "p95": float(np.quantile(inside, 0.95)),
                    "max": float(np.max(inside)),
                }
                if inside.size
                else None
            ),
        }
    return rows


def _median(values: list[float]) -> float | None:
    return float(np.median(np.asarray(values, dtype=np.float64))) if values else None


def _min(values: list[float]) -> float | None:
    return float(np.min(np.asarray(values, dtype=np.float64))) if values else None


def _decision(
    spec: dict[str, Any],
    variants: list[dict[str, Any]],
) -> dict[str, Any]:
    rule = spec["decision_rule"]
    primary_tol = str(float(spec["metric"]["primary_unexplained_tolerance_voxels"]))
    min_support = int(rule["minimum_supported_witnesses_per_patch"])

    support_ok = all(
        int(v["omission"][primary_tol]["deleted_witness_count"]) >= min_support
        for v in variants
    )

    by_size: dict[int, list[dict[str, Any]]] = {}
    for row in variants:
        by_size.setdefault(int(row["size_vertices"]), []).append(row)

    omission_summary: dict[str, Any] = {}
    omission_ok = support_ok
    omission_req = rule["omission_primary_requirements"]
    for size, rows in sorted(by_size.items()):
        recalls = [
            float(r["omission"][primary_tol]["deletion_recall"])
            for r in rows
            if r["omission"][primary_tol]["deletion_recall"] is not None
        ]
        stability = [
            float(r["omission"][primary_tol]["outside_stability"])
            for r in rows
            if r["omission"][primary_tol]["outside_stability"] is not None
        ]
        median_recall = _median(recalls)
        min_recall = _min(recalls)
        min_stability = _min(stability)
        threshold = float(
            omission_req[
                "size_21_min_median_recall"
                if size == 21
                else (
                    "size_31_min_median_recall"
                    if size == 31
                    else "size_41_min_median_recall"
                )
            ]
        )
        size_ok = (
            median_recall is not None
            and median_recall >= threshold
            and min_recall is not None
            and min_recall >= float(omission_req["every_size_min_patch_recall"])
            and min_stability is not None
            and min_stability >= float(omission_req["min_outside_stability"])
        )
        omission_ok = omission_ok and size_ok
        omission_summary[str(size)] = {
            "median_recall": median_recall,
            "min_patch_recall": min_recall,
            "min_outside_stability": min_stability,
            "required_median_recall": threshold,
            "pass": bool(size_ok),
        }

    substitution_req = rule["parallel_substitution_primary_requirements"]
    substitution_ok = support_ok
    substitution_summary: dict[str, Any] = {}
    for size in (31, 41):
        rows = by_size.get(size, [])
        recalls = [
            float(r["parallel_substitution"][primary_tol]["deletion_recall"])
            for r in rows
            if r["parallel_substitution"][primary_tol]["deletion_recall"] is not None
        ]
        stability = [
            float(r["parallel_substitution"][primary_tol]["outside_stability"])
            for r in rows
            if r["parallel_substitution"][primary_tol]["outside_stability"] is not None
        ]
        median_recall = _median(recalls)
        min_stability = _min(stability)
        threshold = float(
            substitution_req[
                "size_31_min_median_recall"
                if size == 31
                else "size_41_min_median_recall"
            ]
        )
        size_ok = (
            median_recall is not None
            and median_recall >= threshold
            and min_stability is not None
            and min_stability >= float(substitution_req["min_outside_stability"])
        )
        substitution_ok = substitution_ok and size_ok
        substitution_summary[str(size)] = {
            "median_recall": median_recall,
            "min_outside_stability": min_stability,
            "required_median_recall": threshold,
            "pass": bool(size_ok),
        }

    passed = bool(support_ok and omission_ok and substitution_ok)
    return {
        "status": "pass" if passed else "fail",
        "support_count_gate": {
            "minimum_supported_witnesses_per_patch": min_support,
            "pass": bool(support_ok),
        },
        "omission": {
            "pass": bool(omission_ok),
            "by_size": omission_summary,
        },
        "parallel_substitution": {
            "pass": bool(substitution_ok),
            "by_size": substitution_summary,
        },
        "interpretation": spec["decision_rule"]["interpretation"],
    }


def run(spec_path: Path, tifxyz: Path) -> dict[str, Any]:
    spec, spec_sha = _load_spec(spec_path)
    reference = spec["reference_surface"]
    observed_hashes = _verify_tifxyz_hashes(
        tifxyz, reference["tifxyz_sha256"]
    )

    xyz, valid, surface_info = _load_surface(tifxyz)
    centers = spec["deletion_protocol"]["centers"]
    sizes = [int(v) for v in spec["deletion_protocol"]["square_sizes_vertices"]]
    max_deletion_size = max(sizes)
    evaluation_size = int(
        spec["deletion_protocol"].get(
            "evaluation_window_size_vertices", max_deletion_size
        )
    )
    if evaluation_size < max_deletion_size or evaluation_size % 2 != 1:
        raise ExperimentError(
            "evaluation window must be odd and at least the largest deletion"
        )

    witness_spec = spec["witness_association"]
    offsets = [float(v) for v in witness_spec["signed_search_offsets_voxels"]]
    threshold = int(spec["independent_witness_source"]["stored_value_threshold"])
    tolerances = [float(v) for v in spec["metric"]["sensitivity_tolerances_voxels"]]
    primary_tol = float(spec["metric"]["primary_unexplained_tolerance_voxels"])
    if primary_tol not in tolerances:
        raise ExperimentError("primary tolerance must be in sensitivity tolerances")

    witness_source = spec["independent_witness_source"]
    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(pool_maxsize=16)
    session.mount("https://", adapter)
    try:
        pred_level = ZarrV2Level(
            witness_source["prediction_url"].rstrip("/") + "/0", session
        )
        ct_level = ZarrV2Level(
            witness_source["ct_support_url"].rstrip("/") + "/0", session
        )
        if tuple(pred_level.shape) != tuple(ct_level.shape):
            raise ExperimentError(
                f"prediction shape {pred_level.shape} != CT shape {ct_level.shape}"
            )
        pred_sampler = _NearestSampler(pred_level)
        ct_sampler = _NearestSampler(ct_level)

        full_points = _surface_points_zyx(xyz, valid)
        full_tree = cKDTree(full_points)
        center_results: list[dict[str, Any]] = []
        variants: list[dict[str, Any]] = []

        for center_row in centers:
            center = tuple(int(v) for v in center_row["grid_yx"])
            witness_window = _witnesses_for_window(
                xyz=xyz,
                valid=valid,
                center=center,
                max_size=evaluation_size,
                offsets=offsets,
                threshold=threshold,
                pred_sampler=pred_sampler,
                ct_sampler=ct_sampler,
            )
            witnesses = witness_window.pop("witnesses")
            witness_array = np.asarray(
                [row["witness_zyx"] for row in witnesses], dtype=np.float64
            )
            if witnesses:
                baseline_distances, _ = full_tree.query(
                    witness_array, k=1, workers=1
                )
                baseline_summary = {
                    "max_distance_voxels": float(np.max(baseline_distances)),
                    "median_distance_voxels": float(np.median(baseline_distances)),
                    "p95_distance_voxels": float(
                        np.quantile(baseline_distances, 0.95)
                    ),
                }
            else:
                baseline_summary = {
                    "max_distance_voxels": None,
                    "median_distance_voxels": None,
                    "p95_distance_voxels": None,
                }

            center_entry = {
                "id": center_row["id"],
                "grid_yx": list(center),
                "window": witness_window,
                "baseline": baseline_summary,
            }
            center_results.append(center_entry)

            for size in sizes:
                rect = _rect(center, size)
                delete = np.zeros_like(valid, dtype=bool)
                y0, y1, x0, x1 = rect
                delete[y0:y1, x0:x1] = True
                omitted_keep = valid & ~delete
                omitted_points = _surface_points_zyx(xyz, omitted_keep)
                omission_distances = _query(omitted_points, witnesses)

                shifted = _normal_shifted_patch_zyx(
                    xyz,
                    valid,
                    rect,
                    shift_voxels=float(
                        spec["counterfactuals"]["parallel_substitution"][
                            "signed_normal_shift_voxels"
                        ]
                    ),
                )
                substitution_points = (
                    np.concatenate([omitted_points, shifted], axis=0)
                    if shifted.size
                    else omitted_points
                )
                substitution_distances = _query(substitution_points, witnesses)

                variants.append(
                    {
                        "center_id": center_row["id"],
                        "center_grid_yx": list(center),
                        "size_vertices": int(size),
                        "rect_yx_half_open": list(rect),
                        "valid_vertices_deleted": int((valid & delete).sum()),
                        "omission": _score_distances(
                            witnesses=witnesses,
                            distances=omission_distances,
                            rect=rect,
                            tolerances=tolerances,
                        ),
                        "parallel_substitution": _score_distances(
                            witnesses=witnesses,
                            distances=substitution_distances,
                            rect=rect,
                            tolerances=tolerances,
                        ),
                        "parallel_substitution_vertex_count": int(shifted.shape[0]),
                    }
                )

        missing_pred = sorted([list(v) for v in pred_sampler.missing_chunks])
        missing_ct = sorted([list(v) for v in ct_sampler.missing_chunks])
        if missing_pred or missing_ct:
            raise ExperimentError(
                "source sampling encountered missing stored chunks; "
                f"prediction={len(missing_pred)} CT={len(missing_ct)}"
            )
    finally:
        session.close()

    decision = _decision(spec, variants)

    support_fractions = [
        float(row["window"]["witness_fraction_of_valid_normals"])
        for row in center_results
    ]
    support_counts = [int(row["window"]["witness_count"]) for row in center_results]

    return {
        "schema": SPEC_SCHEMAS[spec["schema"]]["result_schema"],
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
        "independent_witness_source": {
            "prediction_url": witness_source["prediction_url"],
            "ct_support_url": witness_source["ct_support_url"],
            "stored_value_threshold": threshold,
            "model_id": witness_source["model_id"],
            "missing_prediction_chunks": 0,
            "missing_ct_chunks": 0,
        },
        "descriptive_witness_support": {
            "center_count": len(center_results),
            "evaluation_window_size_vertices": evaluation_size,
            "witness_counts": support_counts,
            "min_count": min(support_counts) if support_counts else 0,
            "median_count": float(np.median(support_counts)) if support_counts else 0.0,
            "witness_fraction_of_valid_normals": support_fractions,
            "min_fraction": min(support_fractions) if support_fractions else 0.0,
            "median_fraction": (
                float(np.median(support_fractions)) if support_fractions else 0.0
            ),
        },
        "centers": center_results,
        "variants": variants,
        "decision": decision,
        "claim_boundary": spec["claim_boundary"],
    }


def _self_test() -> None:
    # Pure geometry sanity check for the counterfactual-distance machinery.
    yy, xx = np.meshgrid(np.arange(9), np.arange(9), indexing="ij")
    xyz = np.stack(
        [xx.astype(float) * 20.0, yy.astype(float) * 20.0, np.ones_like(xx) * 50.0],
        axis=-1,
    )
    valid = np.ones((9, 9), dtype=bool)
    rect = _rect((4, 4), 3)
    delete = np.zeros_like(valid)
    y0, y1, x0, x1 = rect
    delete[y0:y1, x0:x1] = True
    witnesses = [
        {"grid_yx": [4, 4], "witness_zyx": [50.0, 80.0, 80.0]},
        {"grid_yx": [1, 1], "witness_zyx": [50.0, 20.0, 20.0]},
    ]
    distances = _query(_surface_points_zyx(xyz, valid & ~delete), witnesses)
    score = _score_distances(
        witnesses=witnesses,
        distances=distances,
        rect=rect,
        tolerances=[8.0],
    )["8.0"]
    assert score["deletion_recall"] == 1.0
    assert score["outside_stability"] == 1.0
    print("self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec")
    parser.add_argument("--tifxyz")
    parser.add_argument("--out")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        _self_test()
        return 0
    if not args.spec or not args.tifxyz or not args.out:
        parser.error("--spec, --tifxyz and --out are required unless --self-test")

    out = Path(args.out)
    if out.exists():
        parser.error(f"refusing to overwrite {out}")
    try:
        result = run(Path(args.spec), Path(args.tifxyz))
    except (ExperimentError, OSError, requests.RequestException) as exc:
        print(json.dumps({"status": "invalid", "error": str(exc)}))
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
                "min_witness_count": result["descriptive_witness_support"]["min_count"],
                "median_witness_fraction": result[
                    "descriptive_witness_support"
                ]["median_fraction"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
