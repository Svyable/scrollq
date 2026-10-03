"""Fail-closed model registry and held-out evaluation preflight for ScrolIQ.

This first slice deliberately stops before executing community inference code.
It binds a model card, checkpoint, inference script, and held-out dataset
manifest; verifies hashes; and refuses rank eligibility when training overlap is
present or cannot be established from a complete declared training inventory.

Task-specific adapters will consume this preflight record and add per-region
measurements plus deterministic bootstrap confidence intervals.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Sequence

import numpy as np

SCHEMA_VERSION = 1
MODEL_SCHEMA_VERSION = 1
DATASET_SCHEMA_VERSION = 1
TASKS = {"ink_detection", "geometry", "segmentation"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REGION_KEY_RE = re.compile(r"^[^:\s]+:[^:\s]+$")


def canonical_digest(document: dict[str, Any]) -> str:
    """Return a stable SHA-256 for a JSON object."""
    encoded = json.dumps(
        document, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _public_url(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(("https://", "http://"))


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _unique_strings(value: Any, field: str, errors: list[str]) -> list[str]:
    if not isinstance(value, list) or any(not _nonempty_string(v) for v in value):
        errors.append(f"{field} must be a list of non-empty strings")
        return []
    rows = [str(v) for v in value]
    if len(rows) != len(set(rows)):
        errors.append(f"{field} contains duplicates")
    return rows


def validate_model_card(card: dict[str, Any]) -> list[str]:
    """Validate the dependency-light subset enforced by scroliq-eval."""
    errors: list[str] = []
    if not isinstance(card, dict):
        return ["model card must be a JSON object"]
    if type(card.get("schema_version")) is not int or card.get("schema_version") != MODEL_SCHEMA_VERSION:
        errors.append(f"schema_version must be {MODEL_SCHEMA_VERSION}")
    for field in ("name", "author", "inference_script", "license"):
        if not _nonempty_string(card.get(field)):
            errors.append(f"{field} must be a non-empty string")
    if card.get("task") not in TASKS:
        errors.append(f"task must be one of {sorted(TASKS)}")
    if not SHA256_RE.fullmatch(str(card.get("checkpoint_sha256", ""))):
        errors.append("checkpoint_sha256 must be lowercase 64-hex")
    if not SHA256_RE.fullmatch(str(card.get("inference_sha256", ""))):
        errors.append("inference_sha256 must be lowercase 64-hex")
    _unique_strings(card.get("training_data"), "training_data", errors)
    training_regions = _unique_strings(
        card.get("training_regions", []), "training_regions", errors
    )
    for key in training_regions:
        if not REGION_KEY_RE.fullmatch(key):
            errors.append(
                "training_regions entries must be DATASET_ID:REGION_ID with no whitespace"
            )
            break
    if type(card.get("training_inventory_complete")) is not bool:
        errors.append("training_inventory_complete must be boolean")
    if type(card.get("held_out_excluded")) is not bool:
        errors.append("held_out_excluded must be boolean")
    if card.get("training_data_license") != "CC-BY-NC-4.0":
        errors.append("training_data_license must be CC-BY-NC-4.0")
    if type(card.get("random_seed")) is not int or card.get("random_seed", -1) < 0:
        errors.append("random_seed must be a non-negative integer")
    if not _public_url(card.get("experiment_run_url")):
        errors.append("experiment_run_url must be public http(s)")
    return errors


def validate_dataset_manifest(dataset: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(dataset, dict):
        return ["dataset manifest must be a JSON object"]
    if (
        type(dataset.get("schema_version")) is not int
        or dataset.get("schema_version") != DATASET_SCHEMA_VERSION
    ):
        errors.append(f"schema_version must be {DATASET_SCHEMA_VERSION}")
    if not _nonempty_string(dataset.get("dataset_id")):
        errors.append("dataset_id must be a non-empty string")
    if dataset.get("task") not in TASKS:
        errors.append(f"task must be one of {sorted(TASKS)}")
    if dataset.get("held_out") is not True:
        errors.append("held_out must be true")
    if dataset.get("source_url") is not None and not _public_url(dataset.get("source_url")):
        errors.append("source_url must be public http(s) when provided")
    if not SHA256_RE.fullmatch(str(dataset.get("truth_commitment_sha256", ""))):
        errors.append("truth_commitment_sha256 must be lowercase 64-hex")
    regions = dataset.get("regions")
    if not isinstance(regions, list) or not regions:
        errors.append("regions must be a non-empty list")
        return errors
    seen: set[str] = set()
    for index, row in enumerate(regions):
        if not isinstance(row, dict):
            errors.append(f"regions[{index}] must be an object")
            continue
        identifier = row.get("id")
        if not _nonempty_string(identifier):
            errors.append(f"regions[{index}].id must be a non-empty string")
        elif identifier in seen:
            errors.append(f"duplicate region id: {identifier}")
        else:
            seen.add(identifier)
        for field in ("scroll_id", "volume_root"):
            if not _nonempty_string(row.get(field)):
                errors.append(f"regions[{index}].{field} must be a non-empty string")
    return errors


def overlap_check(
    card: dict[str, Any], dataset: dict[str, Any]
) -> dict[str, Any]:
    """Check exact declared dataset and region identifiers, failing closed."""
    dataset_id = str(dataset.get("dataset_id", ""))
    held_out_regions = {
        f"{dataset_id}:{row['id']}"
        for row in dataset.get("regions", [])
        if isinstance(row, dict) and _nonempty_string(row.get("id"))
    }
    training_data = set(card.get("training_data", []))
    training_regions = set(card.get("training_regions", []))
    region_overlap = sorted(held_out_regions & training_regions)
    dataset_overlap = dataset_id in training_data

    if dataset_overlap or region_overlap:
        status = "present"
        reasons = []
        if dataset_overlap:
            reasons.append(f"held-out dataset_id {dataset_id!r} is declared training data")
        if region_overlap:
            reasons.append(
                "held-out region IDs overlap declared training regions: "
                + ", ".join(region_overlap)
            )
    elif card.get("training_inventory_complete") is not True:
        status = "unknown"
        reasons = ["training inventory is not declared complete"]
    elif card.get("held_out_excluded") is not True:
        status = "unknown"
        reasons = ["model card does not declare held-out exclusion"]
    else:
        status = "none"
        reasons = []

    return {
        "status": status,
        "dataset_overlap": dataset_overlap,
        "region_overlap": region_overlap,
        "held_out_regions_checked": len(held_out_regions),
        "basis": "exact declared dataset/region identifiers",
        "limitations": (
            "This proves consistency against the published training inventory; "
            "it cannot detect omitted or aliased training sources."
        ),
        "reasons": reasons,
    }


def _resolve_repo_path(root: Path, relative: str, field: str) -> Path:
    raw = Path(relative)
    if raw.is_absolute():
        raise ValueError(f"{field} must be repository-relative")
    root = root.resolve()
    candidate = (root / raw).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{field} escapes root directory") from exc
    return candidate


def bootstrap_region_ci(
    values: Sequence[float], *, seed: int, samples: int = 2000
) -> dict[str, Any]:
    """Deterministic percentile 95% CI over regions."""
    if type(seed) is not int or seed < 0:
        raise ValueError("seed must be a non-negative integer")
    if type(samples) is not int or samples < 100:
        raise ValueError("samples must be an integer >= 100")
    arr = np.asarray(values, dtype=np.float64)
    if arr.ndim != 1 or arr.size == 0 or not np.all(np.isfinite(arr)):
        raise ValueError("values must be a non-empty finite 1D sequence")
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, arr.size, size=(samples, arr.size))
    means = arr[draws].mean(axis=1)
    low, high = np.quantile(means, [0.025, 0.975])
    return {
        "point_estimate": float(arr.mean()),
        "ci95": [float(low), float(high)],
        "n": int(arr.size),
        "bootstrap_samples": samples,
        "seed": seed,
        "bootstrap_unit": "region",
    }


def build_preflight_report(
    *,
    card: dict[str, Any],
    dataset: dict[str, Any],
    model_path: Path,
    dataset_path: Path,
    checkpoint_path: Path,
    root_dir: Path,
) -> dict[str, Any]:
    model_errors = validate_model_card(card)
    dataset_errors = validate_dataset_manifest(dataset)
    blockers: list[str] = []

    if model_errors:
        blockers.extend(f"model card: {error}" for error in model_errors)
    if dataset_errors:
        blockers.extend(f"dataset manifest: {error}" for error in dataset_errors)

    task_match = card.get("task") == dataset.get("task")
    if not task_match:
        blockers.append("model task does not match held-out dataset task")

    overlap = overlap_check(card, dataset)
    if overlap["status"] != "none":
        blockers.extend(f"training overlap: {r}" for r in overlap["reasons"])

    checkpoint_check: dict[str, Any] = {
        "path": str(checkpoint_path),
        "expected_sha256": card.get("checkpoint_sha256"),
        "actual_sha256": None,
        "status": "fail",
    }
    try:
        actual = sha256_file(checkpoint_path)
        checkpoint_check["actual_sha256"] = actual
        checkpoint_check["status"] = (
            "pass" if actual == card.get("checkpoint_sha256") else "fail"
        )
        if checkpoint_check["status"] != "pass":
            blockers.append("checkpoint SHA-256 mismatch")
    except OSError as exc:
        blockers.append(f"checkpoint unavailable: {exc}")

    inference_check: dict[str, Any] = {
        "path": card.get("inference_script"),
        "expected_sha256": card.get("inference_sha256"),
        "actual_sha256": None,
        "status": "fail",
    }
    try:
        inference_path = _resolve_repo_path(
            root_dir, str(card.get("inference_script", "")), "inference_script"
        )
        actual = sha256_file(inference_path)
        inference_check["resolved_path"] = str(inference_path)
        inference_check["actual_sha256"] = actual
        inference_check["status"] = (
            "pass" if actual == card.get("inference_sha256") else "fail"
        )
        if inference_check["status"] != "pass":
            blockers.append("inference script SHA-256 mismatch")
    except (OSError, ValueError) as exc:
        blockers.append(f"inference script unavailable: {exc}")

    preflight_status = "pass" if not blockers else "fail"
    rank_blockers = list(blockers)
    rank_blockers.append(
        "task adapter has not produced held-out per-region metrics in preflight mode"
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "tool": "scroliq-eval",
        "mode": "preflight",
        "status": preflight_status,
        "model": {
            "name": card.get("name"),
            "author": card.get("author"),
            "task": card.get("task"),
            "model_card_path": str(model_path),
            "model_card_sha256": canonical_digest(card) if isinstance(card, dict) else None,
            "checkpoint": checkpoint_check,
            "inference": inference_check,
            "random_seed": card.get("random_seed"),
            "experiment_run_url": card.get("experiment_run_url"),
        },
        "held_out_dataset": {
            "dataset_id": dataset.get("dataset_id"),
            "task": dataset.get("task"),
            "manifest_path": str(dataset_path),
            "manifest_sha256": canonical_digest(dataset)
            if isinstance(dataset, dict)
            else None,
            "regions": len(dataset.get("regions", []))
            if isinstance(dataset.get("regions"), list)
            else 0,
            "source_url": dataset.get("source_url"),
            "truth_commitment_sha256": dataset.get("truth_commitment_sha256"),
        },
        "checks": {
            "model_card_errors": model_errors,
            "dataset_manifest_errors": dataset_errors,
            "task_match": task_match,
            "training_overlap": overlap,
        },
        "uncertainty_contract": {
            "confidence": 0.95,
            "method": "percentile bootstrap",
            "bootstrap_unit": "region",
            "default_samples": 2000,
            "seed_source": "model.random_seed",
        },
        "rank_status": "not_evaluated",
        "rank_eligible": False,
        "rank_blockers": rank_blockers,
        "next_stage": (
            "A task adapter must run the hash-pinned inference code in an isolated "
            "environment, score every held-out region, and attach point estimates, "
            "95% region-bootstrap CIs, failures, and provenance."
        ),
    }


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fail-closed ScrolIQ model-evaluation preflight. Binds a registry "
            "entry, checkpoint, inference code, and held-out dataset before any "
            "model can be evaluated or ranked."
        )
    )
    parser.add_argument("--model", required=True, help="model-card JSON")
    parser.add_argument("--dataset", required=True, help="held-out dataset manifest JSON")
    parser.add_argument("--checkpoint", required=True, help="local checkpoint file")
    parser.add_argument(
        "--root-dir",
        default=".",
        help="repository root used to resolve the model card's inference_script",
    )
    parser.add_argument("--out", required=True, help="new report path; refuses overwrite")
    parser.add_argument(
        "--format", choices=("text", "json", "github"), default="text"
    )
    args = parser.parse_args(argv)

    try:
        model_path = Path(args.model)
        dataset_path = Path(args.dataset)
        checkpoint_path = Path(args.checkpoint)
        report = build_preflight_report(
            card=_load_json(model_path),
            dataset=_load_json(dataset_path),
            model_path=model_path,
            dataset_path=dataset_path,
            checkpoint_path=checkpoint_path,
            root_dir=Path(args.root_dir),
        )
        text = json.dumps(report, indent=2, allow_nan=False) + "\n"
        with Path(args.out).open("x", encoding="utf-8") as fh:
            fh.write(text)

        if args.format == "json":
            print(text, end="")
        elif args.format == "github":
            if report["status"] == "pass":
                print(
                    "::notice title=SCROLIQ_EVAL_PREFLIGHT_PASS::"
                    f"model={report['model']['name']} "
                    f"regions={report['held_out_dataset']['regions']}"
                )
            else:
                for blocker in report["rank_blockers"]:
                    if "task adapter has not produced" not in blocker:
                        print(
                            "::error title=SCROLIQ_EVAL_PREFLIGHT_BLOCKED::"
                            + blocker
                        )
        else:
            print(f"ScrolIQ eval preflight: {report['status'].upper()}")
            print(
                f"model={report['model']['name']} "
                f"task={report['model']['task']} "
                f"regions={report['held_out_dataset']['regions']}"
            )
            print(
                "rank_status=not_evaluated "
                "(preflight never produces a leaderboard score)"
            )
            for blocker in report["rank_blockers"]:
                if report["status"] == "fail" or "task adapter has not produced" in blocker:
                    print(f"- {blocker}")
        return 0 if report["status"] == "pass" else 1
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
