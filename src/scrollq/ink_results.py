"""Adapt held-out ink-validation reports to the common ScrolIQ evaluator.

Each expected evaluation region becomes exactly one results row. Missing,
malformed, non-held-out, non-prize-ready, or provenance-mismatched ink reports
become explicit failed rows so they stay in the denominator in scroliq-eval.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from .model_eval import (
    ValidationError,
    build_preflight,
    validate_dataset_manifest,
    validate_model_card,
)

SCHEMA_VERSION = 1
TOOL = "scroliq-ink-results"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
METRIC_FIELDS = (
    "roc_auc",
    "balanced_accuracy",
    "false_positive_rate",
    "f1",
    "iou",
    "brier",
    "ink_background_margin",
    "precision",
    "recall",
    "specificity",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"cannot read {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be a JSON object")
    return value


def _parse_region_arg(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("region must be ID=PATH")
    region_id, raw_path = value.split("=", 1)
    if not region_id.strip() or not raw_path.strip():
        raise argparse.ArgumentTypeError("region must be ID=PATH")
    return region_id.strip(), Path(raw_path.strip())


def _metric_values(report: Mapping[str, Any]) -> dict[str, float]:
    evaluation = report.get("evaluation")
    if not isinstance(evaluation, Mapping):
        return {}
    metrics: dict[str, float] = {}
    for name in METRIC_FIELDS:
        value = evaluation.get(name)
        if type(value) in (int, float) and math.isfinite(float(value)):
            metrics[name] = float(value)
    return metrics


def _region_from_report(
    *,
    region_id: str,
    path: Path,
    primary_metric: str,
    checkpoint_sha256: str,
) -> dict[str, Any]:
    evidence: dict[str, str] = {}
    try:
        evidence["ink_validation"] = _sha256(path)
        report = _load_object(path, f"ink report for {region_id}")
    except (OSError, ValidationError) as exc:
        return {
            "id": region_id,
            "status": "failed",
            "reason": str(exc),
            **({"evidence_sha256": evidence} if evidence else {}),
        }

    reasons: list[str] = []
    if report.get("schema_version") != 1:
        reasons.append("ink report schema_version is not 1")
    if report.get("tool") != "scroliq-ink-validate":
        reasons.append("report was not produced by scroliq-ink-validate")

    split = report.get("split")
    if not isinstance(split, Mapping):
        reasons.append("ink report split is missing")
    else:
        if split.get("id") != region_id:
            reasons.append(
                f"split id {split.get('id')!r} does not match region {region_id!r}"
            )
        if split.get("held_out") is not True:
            reasons.append("split is not held out")
        if split.get("training_overlap") != "none":
            reasons.append("training overlap is not explicitly none")
        if split.get("known_ground_truth") is not True:
            reasons.append("ground truth is not declared known")

    model = report.get("model")
    if not isinstance(model, Mapping):
        reasons.append("ink report model identity is missing")
    elif model.get("checkpoint_sha256") != checkpoint_sha256:
        reasons.append("ink report checkpoint SHA-256 does not match verified model")

    if report.get("prize_evidence_ready") is not True:
        report_reasons = report.get("readiness_reasons")
        if isinstance(report_reasons, list) and report_reasons:
            reasons.append(
                "ink report is not prize-evidence-ready: "
                + "; ".join(str(value) for value in report_reasons)
            )
        else:
            reasons.append("ink report is not prize-evidence-ready")

    evaluated_sha = report.get("evaluated_arrays_sha256")
    if isinstance(evaluated_sha, str) and SHA256_RE.fullmatch(evaluated_sha):
        evidence["evaluated_arrays"] = evaluated_sha
    else:
        reasons.append("evaluated array digest is missing or malformed")

    inputs = report.get("inputs")
    if isinstance(inputs, Mapping):
        for source_name in ("prediction", "labels", "validation_mask"):
            row = inputs.get(source_name)
            if isinstance(row, Mapping):
                digest = row.get("sha256")
                if isinstance(digest, str) and SHA256_RE.fullmatch(digest):
                    evidence[source_name] = digest

    metrics = _metric_values(report)
    if primary_metric not in metrics:
        reasons.append(f"primary metric {primary_metric!r} is missing or non-finite")

    if reasons:
        row: dict[str, Any] = {
            "id": region_id,
            "status": "failed",
            "reason": "; ".join(reasons),
        }
        if metrics:
            row["metrics"] = metrics
        if evidence:
            row["evidence_sha256"] = evidence
        return row

    return {
        "id": region_id,
        "status": "ok",
        "metrics": metrics,
        "evidence_sha256": evidence,
    }


def build_results(
    *,
    model_document: Mapping[str, Any],
    dataset_document: Mapping[str, Any],
    root: Path,
    checkpoint: Path,
    region_reports: Mapping[str, Path],
) -> dict[str, Any]:
    """Build common region results from deterministic ink validation reports."""
    model = validate_model_card(model_document)
    dataset = validate_dataset_manifest(dataset_document)
    if dataset["task"] != "ink":
        raise ValidationError("dataset.task must be 'ink'")
    if "ink" not in model["tasks"]:
        raise ValidationError("model does not declare the ink task")

    preflight = build_preflight(
        model,
        dataset,
        root=root,
        checkpoint_override=checkpoint,
    )
    if not preflight["rank_eligible"]:
        blocked = [
            row["name"] for row in preflight["checks"] if not row["ok"]
        ]
        raise ValidationError(
            "model preflight is blocked: " + ", ".join(blocked)
        )

    expected = [row["id"] for row in dataset["regions"]]
    unknown = sorted(set(region_reports) - set(expected))
    if unknown:
        raise ValidationError(f"region report mapping contains unknown ids: {unknown}")

    regions: list[dict[str, Any]] = []
    primary_metric = dataset["primary_metric"]["name"]
    for region_id in expected:
        path = region_reports.get(region_id)
        if path is None:
            regions.append(
                {
                    "id": region_id,
                    "status": "failed",
                    "reason": "no ink-validation report supplied",
                }
            )
            continue
        regions.append(
            _region_from_report(
                region_id=region_id,
                path=path,
                primary_metric=primary_metric,
                checkpoint_sha256=model["checkpoint_sha256"],
            )
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "model": model["name"],
        "dataset": dataset["id"],
        "task": "ink",
        "provenance": {
            "checkpoint_sha256": preflight["checkpoint_sha256_observed"],
            "inference_script_sha256": preflight["inference_script_sha256"],
            "inference_config_sha256": preflight["inference_config_sha256"],
        },
        "regions": regions,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Convert per-region scroliq-ink-validate reports into the common "
            "scroliq-eval region-results contract."
        )
    )
    parser.add_argument("--model", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--root", default=".")
    parser.add_argument(
        "--region",
        action="append",
        default=[],
        type=_parse_region_arg,
        metavar="ID=PATH",
        help="held-out region report; repeatable",
    )
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    mappings: dict[str, Path] = {}
    for region_id, path in args.region:
        if region_id in mappings:
            parser.error(f"duplicate region mapping: {region_id}")
        mappings[region_id] = path

    try:
        model_document = _load_object(Path(args.model), "model card")
        dataset_document = _load_object(Path(args.dataset), "dataset manifest")
        results = build_results(
            model_document=model_document,
            dataset_document=dataset_document,
            root=Path(args.root),
            checkpoint=Path(args.checkpoint),
            region_reports=mappings,
        )
    except ValidationError as exc:
        parser.error(str(exc))

    out = Path(args.out)
    if out.exists():
        parser.error(f"refusing to overwrite existing output: {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(results, indent=2, sort_keys=True, allow_nan=False) + "\n"
    out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")

    return 0 if all(row["status"] == "ok" for row in results["regions"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
