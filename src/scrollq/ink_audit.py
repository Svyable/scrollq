"""Fail-closed validation/provenance audit for ink-recovery evidence."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

DIAGNOSTIC = "ink-evidence-audit"
SCHEMA_VERSION = 1


def _bbox(value: Any, label: str, errors: list[str]) -> list[list[float]] | None:
    if (
        not isinstance(value, list)
        or len(value) != 2
        or any(not isinstance(row, list) or len(row) != 3 for row in value)
    ):
        errors.append(f"{label} bbox must be [[z0,y0,x0],[z1,y1,x1]]")
        return None
    try:
        out = [[float(v) for v in row] for row in value]
    except (TypeError, ValueError):
        errors.append(f"{label} bbox must be numeric")
        return None
    if any(not math.isfinite(v) for row in out for v in row):
        errors.append(f"{label} bbox must be finite")
        return None
    if any(out[0][i] >= out[1][i] for i in range(3)):
        errors.append(f"{label} bbox must use increasing half-open bounds")
        return None
    return out


def _regions(manifest: dict[str, Any], key: str, errors: list[str]) -> list[dict[str, Any]]:
    raw = manifest.get(key)
    if raw is None:
        return []
    if not isinstance(raw, list):
        errors.append(f"{key} must be a list")
        return []
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i, row in enumerate(raw):
        label = f"{key}[{i}]"
        if not isinstance(row, dict):
            errors.append(f"{label} must be an object")
            continue
        region_id = row.get("id")
        volume_root = row.get("volume_root")
        if not isinstance(region_id, str) or not region_id:
            errors.append(f"{label}.id must be a non-empty string")
            continue
        if region_id in seen:
            errors.append(f"duplicate region id: {region_id}")
            continue
        seen.add(region_id)
        if not isinstance(volume_root, str) or not volume_root:
            errors.append(f"{label}.volume_root must be a non-empty string")
            continue
        parsed = _bbox(row.get("bbox_zyx_half_open"), label, errors)
        if parsed is None:
            continue
        result.append({
            "id": region_id,
            "volume_root": volume_root,
            "bbox_zyx_half_open": parsed,
            "split": row.get("split"),
        })
    return result


def _overlap(a: list[list[float]], b: list[list[float]]) -> list[float] | None:
    extent = [
        min(a[1][i], b[1][i]) - max(a[0][i], b[0][i])
        for i in range(3)
    ]
    return extent if all(v > 0 for v in extent) else None



def _is_hex(value: Any, length: int) -> bool:
    return (
        isinstance(value, str)
        and len(value) == length
        and all(ch in "0123456789abcdefABCDEF" for ch in value)
    )


def _is_cc_by_nc_4(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    normalized = (
        value.lower()
        .replace("\u2011", "-")
        .replace("\u2013", "-")
        .replace("_", "-")
        .replace(" ", "")
    )
    return any(token in normalized for token in ("cc-by-nc-4.0", "cc-by-nc4.0", "ccby-nc4.0"))


def _external_method_provenance(
    manifest: dict[str, Any],
    errors: list[str],
    warnings: list[str],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    raw = manifest.get("external_method")
    if raw is None:
        return None, None
    if not isinstance(raw, dict):
        errors.append("external_method must be an object")
        return None, None

    repository = raw.get("repository")
    revision = raw.get("revision")
    code_license = raw.get("code_license")
    checkpoint_license = raw.get("checkpoint_license")
    license_evidence_raw = raw.get("license_evidence")
    if isinstance(license_evidence_raw, str):
        license_evidence = [license_evidence_raw]
    elif isinstance(license_evidence_raw, list):
        license_evidence = license_evidence_raw
    else:
        license_evidence = []
    data_license = raw.get("data_license")
    data_license_evidence = raw.get("data_license_evidence")
    role = raw.get("grand_prize_role")
    inference_only = raw.get("inference_only")
    uses_pseudolabel_training = raw.get("uses_pseudolabel_training")

    if not isinstance(repository, str) or not repository.strip():
        errors.append("external_method.repository must be a non-empty string")
    if not _is_hex(revision, 40):
        errors.append("external_method.revision must be an exact 40-character Git SHA")
    if not isinstance(code_license, str) or not code_license.strip():
        errors.append("external_method.code_license must be declared")
    if not isinstance(checkpoint_license, str) or not checkpoint_license.strip():
        errors.append("external_method.checkpoint_license must be declared")
    if (
        not license_evidence
        or any(
            not isinstance(url, str)
            or not url.startswith(("https://", "http://"))
            for url in license_evidence
        )
    ):
        errors.append(
            "external_method.license_evidence must contain public http(s) URL(s)"
        )
    if not isinstance(data_license, str) or not data_license.strip():
        errors.append("external_method.data_license must be declared")
    if (
        not isinstance(data_license_evidence, str)
        or not data_license_evidence.startswith(("https://", "http://"))
    ):
        errors.append(
            "external_method.data_license_evidence must be a public http(s) URL"
        )
    if raw.get("intended_use_permitted") is not True:
        errors.append("external_method.intended_use_permitted must be true")
    if role not in {"control_only", "candidate_submission_model"}:
        errors.append(
            "external_method.grand_prize_role must be control_only or candidate_submission_model"
        )
    if type(inference_only) is not bool:
        errors.append("external_method.inference_only must be boolean")
    if type(uses_pseudolabel_training) is not bool:
        errors.append("external_method.uses_pseudolabel_training must be boolean")

    if uses_pseudolabel_training is True:
        if raw.get("all_training_data_public") is not True:
            errors.append(
                "pseudo-label provenance requires all_training_data_public=true"
            )
        if not _is_cc_by_nc_4(raw.get("training_data_license")):
            errors.append(
                "pseudo-label provenance requires training_data_license=CC-BY-NC 4.0"
            )
        if raw.get("all_intermediate_checkpoints_public") is not True:
            errors.append(
                "pseudo-label provenance requires all_intermediate_checkpoints_public=true"
            )
        if not _is_cc_by_nc_4(raw.get("intermediate_checkpoint_license")):
            errors.append(
                "pseudo-label provenance requires intermediate_checkpoint_license=CC-BY-NC 4.0"
            )
        if raw.get("experiment_tracking_public") is not True:
            errors.append(
                "pseudo-label provenance requires experiment_tracking_public=true"
            )
    elif raw.get("experiment_tracking_public") is not True:
        warnings.append(
            "external_method does not establish public experiment tracking for the trained source model"
        )

    selection = manifest.get("selection_contract")
    if not isinstance(selection, dict):
        errors.append(
            "selection_contract is required when external_method is declared"
        )
        selection_out = None
    else:
        required_true = ("evaluation_regions_frozen_before_candidate_inference",)
        required_false = (
            "ocr_or_legibility_used_for_selection",
            "candidate_output_used_to_choose_evaluation_regions",
        )
        for key in required_true:
            if selection.get(key) is not True:
                errors.append(f"selection_contract.{key} must be true")
        for key in required_false:
            if selection.get(key) is not False:
                errors.append(f"selection_contract.{key} must be false")
        selection_out = {
            key: selection.get(key)
            for key in (*required_true, *required_false)
        }

    return {
        "repository": repository,
        "revision": revision,
        "code_license": code_license,
        "checkpoint_license": checkpoint_license,
        "license_evidence": license_evidence,
        "data_license": data_license,
        "data_license_evidence": data_license_evidence,
        "intended_use_permitted": raw.get("intended_use_permitted") is True,
        "grand_prize_role": role,
        "inference_only": inference_only,
        "uses_pseudolabel_training": uses_pseudolabel_training,
        "all_training_data_public": raw.get("all_training_data_public"),
        "training_data_license": raw.get("training_data_license"),
        "all_intermediate_checkpoints_public": raw.get(
            "all_intermediate_checkpoints_public"
        ),
        "intermediate_checkpoint_license": raw.get(
            "intermediate_checkpoint_license"
        ),
        "experiment_tracking_public": raw.get("experiment_tracking_public"),
    }, selection_out

def audit_ink_manifest(
    manifest: dict[str, Any],
    *,
    expected_volume_root: str | None = None,
    required_normal_offsets: tuple[float, ...] = (-3.0, 0.0, 3.0),
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(manifest, dict):
        return {
            "schema_version": SCHEMA_VERSION,
            "diagnostic": DIAGNOSTIC,
            "status": "fail",
            "error_count": 1,
            "warning_count": 0,
            "errors": ["manifest must contain a JSON object"],
            "warnings": [],
        }

    volume_root = manifest.get("volume_root")
    if not isinstance(volume_root, str) or not volume_root:
        errors.append("volume_root must be a non-empty exact CT root")
        volume_root = None
    if expected_volume_root is not None and volume_root != expected_volume_root:
        errors.append("manifest volume_root does not match the requested exact CT root")

    model = manifest.get("model")
    if not isinstance(model, dict):
        model = {}
        errors.append("model must be an object")
    checkpoint = model.get("checkpoint")
    checkpoint_sha = model.get("checkpoint_sha256")
    if not isinstance(checkpoint, str) or not checkpoint:
        errors.append("model.checkpoint must identify the exact checkpoint")
    if (
        not isinstance(checkpoint_sha, str)
        or len(checkpoint_sha) != 64
        or any(c not in "0123456789abcdefABCDEF" for c in checkpoint_sha)
    ):
        errors.append("model.checkpoint_sha256 must be a 64-character hexadecimal SHA-256")

    external_method, selection_contract = _external_method_provenance(
        manifest, errors, warnings
    )

    seeds = manifest.get("seeds")
    if not isinstance(seeds, list) or not seeds or any(type(v) is not int for v in seeds):
        warnings.append("declare at least one integer random seed")

    training = _regions(manifest, "training_regions", errors)
    evaluation = _regions(manifest, "evaluation_regions", errors)
    if not training:
        warnings.append("no training regions were declared; spatial leakage cannot be excluded against undeclared data")
    if not evaluation:
        errors.append("at least one evaluation region is required")
    if volume_root and evaluation and not any(
        row["volume_root"] == volume_root for row in evaluation
    ):
        errors.append("no evaluation region is bound to manifest volume_root")

    non_held = [
        row["id"] for row in evaluation
        if row.get("split") not in {"held_out", "held-out", "test"}
    ]
    if non_held:
        warnings.append("evaluation regions are not all explicitly held out/test: " + ", ".join(non_held))

    overlaps: list[dict[str, Any]] = []
    for train in training:
        for test in evaluation:
            if train["volume_root"] != test["volume_root"]:
                continue
            extent = _overlap(train["bbox_zyx_half_open"], test["bbox_zyx_half_open"])
            if extent is not None:
                overlaps.append({
                    "training_region": train["id"],
                    "evaluation_region": test["id"],
                    "volume_root": train["volume_root"],
                    "overlap_extent_zyx": extent,
                    "overlap_volume_voxels3": float(extent[0] * extent[1] * extent[2]),
                })
    if overlaps:
        errors.append(f"{len(overlaps)} training/evaluation spatial overlap(s) detected")

    controls = manifest.get("controls")
    if not isinstance(controls, dict):
        controls = {}
        warnings.append("controls must be declared to support ink falsification")

    normal_offsets = controls.get("normal_offsets_voxels")
    declared_offsets = (
        [float(v) for v in normal_offsets]
        if isinstance(normal_offsets, list)
        and all(type(v) in (int, float) and math.isfinite(float(v)) for v in normal_offsets)
        else []
    )
    missing_offsets = [
        required for required in required_normal_offsets
        if not any(abs(required - actual) <= 1e-9 for actual in declared_offsets)
    ]
    if missing_offsets:
        warnings.append("missing required normal-offset controls: " + ", ".join(f"{v:g}" for v in missing_offsets))

    boolean_controls = (
        "adjacent_winding",
        "geometry_perturbation",
        "independent_checkpoint",
    )
    missing_controls = [key for key in boolean_controls if controls.get(key) is not True]
    if missing_controls:
        warnings.append("missing falsification controls: " + ", ".join(missing_controls))

    runs_raw = manifest.get("runs")
    runs = runs_raw if isinstance(runs_raw, list) else []
    if runs_raw is not None and not isinstance(runs_raw, list):
        errors.append("runs must be a list")
    eval_ids = {row["id"] for row in evaluation}
    run_eval_ids: set[str] = set()
    for i, run in enumerate(runs):
        if not isinstance(run, dict):
            errors.append(f"runs[{i}] must be an object")
            continue
        region_id = run.get("evaluation_region_id")
        if region_id not in eval_ids:
            errors.append(f"runs[{i}] references unknown evaluation region {region_id!r}")
            continue
        run_eval_ids.add(region_id)
        if type(run.get("seed")) is not int:
            warnings.append(f"runs[{i}] does not declare an integer seed")
        run_sha = run.get("checkpoint_sha256")
        if (
            not isinstance(run_sha, str)
            or len(run_sha) != 64
            or any(c not in "0123456789abcdefABCDEF" for c in run_sha)
        ):
            warnings.append(f"runs[{i}] does not declare a valid checkpoint_sha256")
    missing_run_regions = sorted(eval_ids - run_eval_ids)
    if evaluation and missing_run_regions:
        warnings.append("no run provenance for evaluation regions: " + ", ".join(missing_run_regions))

    control_complete = not missing_offsets and not missing_controls
    status = "fail" if errors else ("partial" if warnings else "pass")
    return {
        "schema_version": SCHEMA_VERSION,
        "diagnostic": DIAGNOSTIC,
        "volume_root": volume_root,
        "status": status,
        "model": {
            "checkpoint": checkpoint,
            "checkpoint_sha256": checkpoint_sha,
        },
        "seeds": seeds if isinstance(seeds, list) else [],
        "external_method": external_method,
        "selection_contract": selection_contract,
        "training_regions": training,
        "evaluation_regions": evaluation,
        "leakage": {
            "status": "fail" if overlaps else ("unknown" if not training else "pass"),
            "spatial_overlap_count": len(overlaps),
            "overlaps": overlaps,
        },
        "controls": {
            "normal_offsets_voxels": declared_offsets,
            "required_normal_offsets_voxels": list(required_normal_offsets),
            "missing_normal_offsets_voxels": missing_offsets,
            **{key: controls.get(key) is True for key in boolean_controls},
            "complete": control_complete,
        },
        "runs": {
            "declared": len(runs),
            "evaluation_regions_with_runs": len(run_eval_ids),
            "missing_evaluation_region_ids": missing_run_regions,
        },
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
        "limitation": (
            "This audit verifies declared spatial separation and validation provenance. "
            "External license, publication, and tracking fields are declarations that still require "
            "their cited public evidence to be checked independently. It does not establish that "
            "model output is ink, that the scan contains an ink signal, or that the manifest is "
            "complete without independently reproducible upstream data generation."
        ),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Audit held-out ink evidence, leakage, and falsification controls")
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--volume-root", default=None)
    ap.add_argument("--normal-offsets", default="-3,0,3")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    try:
        required_offsets = tuple(float(v) for v in args.normal_offsets.split(","))
    except ValueError as exc:
        raise SystemExit("--normal-offsets must be comma-separated numbers") from exc

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    result = audit_ink_manifest(
        manifest,
        expected_volume_root=args.volume_root,
        required_normal_offsets=required_offsets,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        f"{result['status'].upper()} {args.manifest}: "
        f"{result.get('error_count', 0)} error(s), {result.get('warning_count', 0)} warning(s)"
    )
    if result["status"] == "fail":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
