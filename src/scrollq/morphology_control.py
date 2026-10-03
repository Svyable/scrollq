"""Audit preregistered morphology-based ink controls.

This module deliberately does not claim that optical profilometry transfers to
sealed-scroll CT. It binds the public source, licensing, split policy, and
anti-leakage rules for a staged falsification experiment.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

TOOL = "scroliq-morphology-control"
SCHEMA_VERSION = 1


def _is_hex(value: Any, length: int = 64) -> bool:
    return (
        isinstance(value, str)
        and len(value) == length
        and all(ch in "0123456789abcdefABCDEF" for ch in value)
    )


def _public_url(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(("https://", "http://"))


def _license_token(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return (
        value.lower()
        .replace("\u2011", "-")
        .replace("\u2013", "-")
        .replace("_", "-")
        .replace(" ", "")
    )


def _is_cc_by_nc_4(value: Any) -> bool:
    token = _license_token(value)
    return any(
        candidate in token
        for candidate in ("cc-by-nc-4.0", "cc-by-nc4.0", "ccby-nc4.0")
    )


def _is_cc_by_nc_nd_4(value: Any) -> bool:
    token = _license_token(value)
    return any(
        candidate in token
        for candidate in (
            "cc-by-nc-nd-4.0",
            "cc-by-nc-nd4.0",
            "ccby-nc-nd4.0",
        )
    )


def _pair_positive(value: Any, label: str, errors: list[str]) -> list[float] | None:
    if (
        not isinstance(value, list)
        or len(value) != 2
        or any(type(v) not in (int, float) for v in value)
    ):
        errors.append(f"{label} must be two finite positive numbers")
        return None
    out = [float(v) for v in value]
    if any(not math.isfinite(v) or v <= 0 for v in out):
        errors.append(f"{label} must be two finite positive numbers")
        return None
    return out


def audit_morphology_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(manifest, dict):
        return {
            "schema_version": SCHEMA_VERSION,
            "tool": TOOL,
            "status": "fail",
            "errors": ["manifest must be a JSON object"],
            "warnings": [],
        }

    if manifest.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must equal {SCHEMA_VERSION}")

    mode = manifest.get("mode")
    if mode not in {"source_benchmark", "target_control"}:
        errors.append("mode must be source_benchmark or target_control")

    source = manifest.get("source")
    if not isinstance(source, dict):
        errors.append("source must be an object")
        source = {}

    dataset_id = source.get("dataset_id")
    revision = source.get("revision")
    dataset_license = source.get("dataset_license")
    dataset_license_evidence = source.get("dataset_license_evidence")
    paper_url = source.get("paper_url")
    paper_license = source.get("paper_license")
    paper_license_evidence = source.get("paper_license_evidence")
    source_papyri = source.get("source_papyri")

    if not isinstance(dataset_id, str) or not dataset_id.strip():
        errors.append("source.dataset_id must be non-empty")
    if not _is_hex(revision, 40):
        errors.append("source.revision must be an exact 40-character source revision")
    if not _is_cc_by_nc_4(dataset_license):
        errors.append("source.dataset_license must be CC-BY-NC 4.0")
    if not _public_url(dataset_license_evidence):
        errors.append("source.dataset_license_evidence must be a public http(s) URL")
    if not _public_url(paper_url):
        errors.append("source.paper_url must be a public http(s) URL")
    if not _is_cc_by_nc_nd_4(paper_license):
        errors.append("source.paper_license must be CC-BY-NC-ND 4.0")
    if not _public_url(paper_license_evidence):
        errors.append("source.paper_license_evidence must be a public http(s) URL")
    if (
        not isinstance(source_papyri, list)
        or not source_papyri
        or any(not isinstance(v, str) or not v.strip() for v in source_papyri)
    ):
        errors.append("source.source_papyri must be a non-empty string list")

    sampling = manifest.get("sampling")
    if not isinstance(sampling, dict):
        errors.append("sampling must be an object")
        sampling = {}
    dataset_sampling = _pair_positive(
        sampling.get("dataset_native_um_xy"),
        "sampling.dataset_native_um_xy",
        errors,
    )
    manuscript_sampling = _pair_positive(
        sampling.get("manuscript_native_um_xy"),
        "sampling.manuscript_native_um_xy",
        errors,
    )
    discrepancy = sampling.get("discrepancy_status")
    if discrepancy not in {"unresolved", "resolved"}:
        errors.append("sampling.discrepancy_status must be unresolved or resolved")
    if discrepancy == "unresolved":
        warnings.append(
            "source physical sampling discrepancy is unresolved; absolute-scale transfer is not trustworthy"
        )

    design = manifest.get("design")
    if not isinstance(design, dict):
        errors.append("design must be an object")
        design = {}

    descriptors = design.get("descriptors")
    if (
        not isinstance(descriptors, list)
        or not descriptors
        or any(not isinstance(v, str) or not v.strip() for v in descriptors)
    ):
        errors.append("design.descriptors must be a non-empty string list")

    if design.get("source_split") != "leave-one-papyrus-out":
        errors.append(
            "design.source_split must be leave-one-papyrus-out to test cross-papyrus transfer"
        )
    if design.get("learned_classifier") is not False:
        errors.append(
            "design.learned_classifier must be false for the first morphology-control stage"
        )
    if design.get("source_labels_used_for_target_training") is not False:
        errors.append("design.source_labels_used_for_target_training must be false")
    if design.get("paper_adapted_material_in_repo") is not False:
        errors.append(
            "design.paper_adapted_material_in_repo must be false under the paper's no-derivatives license"
        )
    if design.get("missingness_mask_control") is not True:
        errors.append("design.missingness_mask_control must be true")
    if design.get("label_permutation_control") is not True:
        errors.append("design.label_permutation_control must be true")

    absolute_scale = design.get("uses_absolute_micron_thresholds")
    if type(absolute_scale) is not bool:
        errors.append("design.uses_absolute_micron_thresholds must be boolean")
    if discrepancy == "unresolved" and absolute_scale is True:
        errors.append(
            "absolute micron thresholds are forbidden while the public source sampling discrepancy is unresolved"
        )

    target = manifest.get("target")
    selection = manifest.get("selection_contract")
    source_benchmark_sha = None
    if mode == "target_control":
        if discrepancy != "resolved":
            errors.append(
                "target_control is blocked until the source sampling discrepancy is resolved"
            )
        if not isinstance(target, dict):
            errors.append("target must be an object in target_control mode")
            target = {}
        volume_root = target.get("volume_root")
        ink_manifest_sha = target.get("ink_manifest_sha256")
        source_benchmark_sha = target.get("source_benchmark_artifact_sha256")
        eval_ids = target.get("evaluation_region_ids")
        if not isinstance(volume_root, str) or not volume_root.strip():
            errors.append("target.volume_root must be non-empty")
        if not _is_hex(ink_manifest_sha):
            errors.append("target.ink_manifest_sha256 must be a 64-character SHA-256")
        if not _is_hex(source_benchmark_sha):
            errors.append(
                "target.source_benchmark_artifact_sha256 must bind a completed source benchmark"
            )
        if (
            not isinstance(eval_ids, list)
            or not eval_ids
            or any(not isinstance(v, str) or not v.strip() for v in eval_ids)
        ):
            errors.append("target.evaluation_region_ids must be a non-empty string list")

        if not isinstance(selection, dict):
            errors.append("selection_contract is required in target_control mode")
            selection = {}
        if selection.get("target_regions_frozen_before_descriptor_evaluation") is not True:
            errors.append(
                "selection_contract.target_regions_frozen_before_descriptor_evaluation must be true"
            )
        if selection.get("ink_model_or_ocr_used_to_select_target_regions") is not False:
            errors.append(
                "selection_contract.ink_model_or_ocr_used_to_select_target_regions must be false"
            )
        if selection.get("candidate_render_used_to_tune_descriptors") is not False:
            errors.append(
                "selection_contract.candidate_render_used_to_tune_descriptors must be false"
            )

    transfer_authorized = (
        mode == "target_control"
        and discrepancy == "resolved"
        and _is_hex(source_benchmark_sha)
        and not errors
    )
    status = "fail" if errors else ("partial" if warnings else "pass")

    return {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "mode": mode,
        "status": status,
        "source": {
            "dataset_id": dataset_id,
            "revision": revision,
            "dataset_license": dataset_license,
            "dataset_license_evidence": dataset_license_evidence,
            "paper_url": paper_url,
            "paper_license": paper_license,
            "paper_license_evidence": paper_license_evidence,
            "source_papyri": source_papyri if isinstance(source_papyri, list) else [],
        },
        "sampling": {
            "dataset_native_um_xy": dataset_sampling,
            "manuscript_native_um_xy": manuscript_sampling,
            "discrepancy_status": discrepancy,
        },
        "design": {
            "descriptors": descriptors if isinstance(descriptors, list) else [],
            "source_split": design.get("source_split"),
            "learned_classifier": design.get("learned_classifier"),
            "uses_absolute_micron_thresholds": absolute_scale,
            "missingness_mask_control": design.get("missingness_mask_control") is True,
            "label_permutation_control": design.get("label_permutation_control") is True,
        },
        "transfer_authorized": transfer_authorized,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
        "limitation": (
            "This audit binds declared provenance and experiment design. It does not show "
            "that morphology measured by optical profilometry is recoverable in X-ray CT, "
            "that a descriptor is ink-specific, or that any apparent text is genuine."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog=TOOL,
        description="Audit a staged morphology-based ink falsification manifest.",
    )
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    try:
        manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(f"{TOOL}: cannot read manifest: {exc}")
        return 2

    result = audit_morphology_manifest(manifest)
    out = Path(args.out)
    if out.exists():
        print(f"{TOOL}: refusing to overwrite existing output: {out}")
        return 2
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"{result['status'].upper()} {args.manifest}: "
        f"{result['error_count']} error(s), {result['warning_count']} warning(s)"
    )
    return 2 if result["status"] == "fail" else (1 if result["status"] == "partial" else 0)


if __name__ == "__main__":
    raise SystemExit(main())
