"""Standardized, fail-closed model-evaluation reports for ScrolIQ.

The initial harness deliberately separates running untrusted community inference
from scoring and ranking. scroliq-eval validates a model card, a held-out
dataset manifest, and (optionally) task-adapter region results. It refuses to
rank when provenance is incomplete, checkpoint bytes do not match, declared
training data overlaps held-out data, or any held-out region is missing/failed.

Task-specific adapters (ink, geometry, segmentation) can emit the small region
results contract consumed here. Keeping the aggregator task-neutral lets the
existing ScrolIQ validators remain the source of metric definitions while this
module standardizes uncertainty, failure accounting, and provenance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

SCHEMA_VERSION = 1
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
TASKS = {"ink", "geometry", "segmentation"}


class ValidationError(ValueError):
    """Raised when an evaluation contract is malformed."""


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(document: Mapping[str, Any]) -> str:
    payload = json.dumps(
        document, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"cannot read {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be a JSON object")
    return value


def _schema_v1(document: Mapping[str, Any], label: str) -> None:
    value = document.get("schema_version")
    if type(value) is not int or value != SCHEMA_VERSION:
        raise ValidationError(f"{label}.schema_version must be {SCHEMA_VERSION}")


def _nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field} must be a non-empty string")
    return value.strip()


def _identifier(value: Any, field: str) -> str:
    text = _nonempty_string(value, field)
    if not NAME_RE.fullmatch(text):
        raise ValidationError(
            f"{field} must match {NAME_RE.pattern!r}; got {text!r}"
        )
    return text


def _unique_strings(value: Any, field: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list):
        raise ValidationError(f"{field} must be a list")
    rows = [_nonempty_string(item, field) for item in value]
    if not allow_empty and not rows:
        raise ValidationError(f"{field} must not be empty")
    if len(rows) != len(set(rows)):
        raise ValidationError(f"{field} must not contain duplicates")
    return rows


def _relative_path(value: Any, field: str) -> str:
    text = _nonempty_string(value, field)
    path = Path(text)
    if path.is_absolute() or ".." in path.parts:
        raise ValidationError(f"{field} must be a repository-relative path")
    return path.as_posix()


def _public_url(value: Any, field: str) -> str:
    text = _nonempty_string(value, field)
    if not text.startswith(("https://", "http://")):
        raise ValidationError(f"{field} must be an http(s) URL")
    return text


def validate_model_card(document: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize one model registry entry."""
    _schema_v1(document, "model")
    name = _identifier(document.get("name"), "model.name")
    author = _nonempty_string(document.get("author"), "model.author")
    checkpoint_sha256 = _nonempty_string(
        document.get("checkpoint_sha256"), "model.checkpoint_sha256"
    )
    if not SHA256_RE.fullmatch(checkpoint_sha256):
        raise ValidationError("model.checkpoint_sha256 must be lowercase 64-hex")
    training_data = _unique_strings(document.get("training_data"), "model.training_data")
    if type(document.get("held_out_excluded")) is not bool:
        raise ValidationError("model.held_out_excluded must be boolean")
    inference_script = _relative_path(
        document.get("inference_script"), "model.inference_script"
    )

    inference_config_value = document.get("inference_config")
    if inference_config_value is None:
        inference_config = None
        inference_config_sha256 = None
    else:
        if not isinstance(inference_config_value, dict) or not inference_config_value:
            raise ValidationError("model.inference_config must be a non-empty JSON object")
        try:
            encoded_config = json.dumps(
                inference_config_value,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                "model.inference_config must contain only finite JSON values"
            ) from exc
        inference_config = json.loads(encoded_config)
        inference_config_sha256 = hashlib.sha256(
            encoded_config.encode("utf-8")
        ).hexdigest()

    license_name = _nonempty_string(document.get("license"), "model.license")

    checkpoint_path = document.get("checkpoint_path")
    if checkpoint_path is not None:
        checkpoint_path = _relative_path(checkpoint_path, "model.checkpoint_path")

    tasks = document.get("tasks")
    if tasks is None:
        normalized_tasks = []
    else:
        normalized_tasks = _unique_strings(tasks, "model.tasks")
        unknown = sorted(set(normalized_tasks) - TASKS)
        if unknown:
            raise ValidationError(f"model.tasks contains unknown task(s): {unknown}")

    stochastic = document.get("stochastic", False)
    if type(stochastic) is not bool:
        raise ValidationError("model.stochastic must be boolean")
    random_seed = document.get("random_seed")
    if stochastic:
        if type(random_seed) is not int:
            raise ValidationError(
                "model.random_seed must be an integer when stochastic=true"
            )
    elif random_seed is not None and type(random_seed) is not int:
        raise ValidationError("model.random_seed must be an integer when supplied")

    training_run_url = document.get("training_run_url")
    if training_run_url is not None:
        training_run_url = _public_url(training_run_url, "model.training_run_url")
    inference_run_url = document.get("inference_run_url")
    if inference_run_url is not None:
        inference_run_url = _public_url(inference_run_url, "model.inference_run_url")

    return {
        "schema_version": SCHEMA_VERSION,
        "name": name,
        "author": author,
        "checkpoint_sha256": checkpoint_sha256,
        "checkpoint_path": checkpoint_path,
        "training_data": training_data,
        "held_out_excluded": document["held_out_excluded"],
        "inference_script": inference_script,
        "inference_config": inference_config,
        "inference_config_sha256": inference_config_sha256,
        "license": license_name,
        "tasks": normalized_tasks,
        "stochastic": stochastic,
        "random_seed": random_seed,
        "training_run_url": training_run_url,
        "inference_run_url": inference_run_url,
    }


def validate_dataset_manifest(document: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the public/blind metadata for one held-out evaluation set."""
    _schema_v1(document, "dataset")
    dataset_id = _identifier(document.get("id"), "dataset.id")
    task = _nonempty_string(document.get("task"), "dataset.task")
    if task not in TASKS:
        raise ValidationError(f"dataset.task must be one of {sorted(TASKS)}")
    if document.get("held_out") is not True:
        raise ValidationError("dataset.held_out must be true")
    evaluation_data = _unique_strings(
        document.get("evaluation_data"), "dataset.evaluation_data"
    )

    regions_value = document.get("regions")
    if not isinstance(regions_value, list) or not regions_value:
        raise ValidationError("dataset.regions must be a non-empty list")
    regions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in regions_value:
        if not isinstance(row, dict):
            raise ValidationError("each dataset.regions entry must be an object")
        region_id = _identifier(row.get("id"), "dataset.regions[].id")
        if region_id in seen:
            raise ValidationError(f"duplicate dataset region id: {region_id}")
        seen.add(region_id)
        regions.append({"id": region_id})

    metric = document.get("primary_metric")
    if not isinstance(metric, dict):
        raise ValidationError("dataset.primary_metric must be an object")
    metric_name = _identifier(metric.get("name"), "dataset.primary_metric.name")
    if type(metric.get("higher_is_better")) is not bool:
        raise ValidationError("dataset.primary_metric.higher_is_better must be boolean")
    failure_value = metric.get("failure_value")
    if type(failure_value) not in (int, float) or not math.isfinite(float(failure_value)):
        raise ValidationError("dataset.primary_metric.failure_value must be finite")

    visibility = document.get("visibility", "private_blind")
    if visibility not in {"public", "private_blind"}:
        raise ValidationError("dataset.visibility must be public or private_blind")
    source_url = document.get("source_url")
    if source_url is not None:
        source_url = _public_url(source_url, "dataset.source_url")

    bootstrap_seed = document.get("bootstrap_seed", 0)
    if type(bootstrap_seed) is not int:
        raise ValidationError("dataset.bootstrap_seed must be an integer")

    return {
        "schema_version": SCHEMA_VERSION,
        "id": dataset_id,
        "task": task,
        "held_out": True,
        "evaluation_data": evaluation_data,
        "regions": regions,
        "primary_metric": {
            "name": metric_name,
            "higher_is_better": metric["higher_is_better"],
            "failure_value": float(failure_value),
        },
        "visibility": visibility,
        "source_url": source_url,
        "bootstrap_seed": bootstrap_seed,
    }


def validate_region_results(
    document: Mapping[str, Any],
    *,
    model: Mapping[str, Any],
    dataset: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate a task adapter's per-region output without redefining its metric."""
    _schema_v1(document, "results")
    if document.get("model") != model["name"]:
        raise ValidationError("results.model does not match model card")
    if document.get("dataset") != dataset["id"]:
        raise ValidationError("results.dataset does not match dataset manifest")
    if document.get("task") != dataset["task"]:
        raise ValidationError("results.task does not match dataset task")

    rows = document.get("regions")
    if not isinstance(rows, list):
        raise ValidationError("results.regions must be a list")
    expected = {row["id"] for row in dataset["regions"]}
    metric_name = dataset["primary_metric"]["name"]
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValidationError("each results.regions entry must be an object")
        region_id = _identifier(row.get("id"), "results.regions[].id")
        if region_id not in expected:
            raise ValidationError(f"results contains unknown region id: {region_id}")
        if region_id in seen:
            raise ValidationError(f"duplicate results region id: {region_id}")
        seen.add(region_id)
        status = row.get("status")
        if status == "ok":
            metrics = row.get("metrics")
            if not isinstance(metrics, dict):
                raise ValidationError(f"region {region_id}: metrics must be an object")
            value = metrics.get(metric_name)
            if type(value) not in (int, float) or not math.isfinite(float(value)):
                raise ValidationError(
                    f"region {region_id}: primary metric {metric_name!r} must be finite"
                )
            normalized.append(
                {"id": region_id, "status": "ok", "metric": float(value)}
            )
        elif status == "failed":
            reason = _nonempty_string(row.get("reason"), f"region {region_id}.reason")
            normalized.append({"id": region_id, "status": "failed", "reason": reason})
        else:
            raise ValidationError(f"region {region_id}: status must be ok or failed")

    return {
        "schema_version": SCHEMA_VERSION,
        "model": model["name"],
        "dataset": dataset["id"],
        "task": dataset["task"],
        "regions": normalized,
    }


def _resolve_under(root: Path, relative: str) -> Path:
    root = root.resolve()
    candidate = (root / relative).resolve()
    if root != candidate and root not in candidate.parents:
        raise ValidationError(f"path escapes repository root: {relative}")
    return candidate


def build_preflight(
    model: Mapping[str, Any],
    dataset: Mapping[str, Any],
    *,
    root: Path,
    checkpoint_override: Path | None = None,
) -> dict[str, Any]:
    """Check model/dataset binding and file provenance without running inference."""
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: str, **extra: Any) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail, **extra})

    check(
        "held_out_excluded",
        model["held_out_excluded"] is True,
        "model explicitly attests held-out exclusion"
        if model["held_out_excluded"] is True
        else "model does not attest held-out exclusion",
    )

    overlap = sorted(set(model["training_data"]) & set(dataset["evaluation_data"]))
    check(
        "training_overlap",
        not overlap,
        "no declared training/evaluation identifiers overlap"
        if not overlap
        else f"declared overlap: {', '.join(overlap)}",
        overlap=overlap,
    )

    check(
        "task_supported",
        dataset["task"] in model["tasks"],
        f"model declares task {dataset['task']}"
        if dataset["task"] in model["tasks"]
        else f"model does not declare task {dataset['task']}",
    )

    inference = _resolve_under(root, model["inference_script"])
    if inference.is_file():
        inference_sha = _file_sha256(inference)
        check("inference_script", True, "inference script exists", sha256=inference_sha)
    else:
        inference_sha = None
        check("inference_script", False, f"missing inference script: {inference}")

    inference_config_sha = model.get("inference_config_sha256")
    if inference_config_sha is None:
        check(
            "inference_configuration",
            False,
            "model does not bind output-affecting inference configuration",
        )
    else:
        check(
            "inference_configuration",
            True,
            "model binds output-affecting inference configuration",
            sha256=inference_config_sha,
        )

    checkpoint_path: Path | None = None
    if checkpoint_override is not None:
        checkpoint_path = checkpoint_override.resolve()
    elif model.get("checkpoint_path"):
        checkpoint_path = _resolve_under(root, model["checkpoint_path"])

    observed_checkpoint_sha: str | None = None
    if checkpoint_path is None:
        check(
            "checkpoint_hash",
            False,
            "checkpoint bytes not supplied; hash cannot be verified",
            expected_sha256=model["checkpoint_sha256"],
        )
    elif not checkpoint_path.is_file():
        check(
            "checkpoint_hash",
            False,
            f"checkpoint file missing: {checkpoint_path}",
            expected_sha256=model["checkpoint_sha256"],
        )
    else:
        observed_checkpoint_sha = _file_sha256(checkpoint_path)
        matches = observed_checkpoint_sha == model["checkpoint_sha256"]
        check(
            "checkpoint_hash",
            matches,
            "checkpoint SHA-256 matches model card"
            if matches
            else "checkpoint SHA-256 mismatch",
            expected_sha256=model["checkpoint_sha256"],
            observed_sha256=observed_checkpoint_sha,
        )

    if model["stochastic"]:
        seeded = type(model.get("random_seed")) is int
        check(
            "fixed_random_seed",
            seeded,
            f"stochastic inference seed={model.get('random_seed')}"
            if seeded
            else "stochastic model has no fixed seed",
        )
    else:
        check("fixed_random_seed", True, "model declares deterministic inference")

    eligible = all(row["ok"] for row in checks)
    return {
        "status": "ready" if eligible else "blocked",
        "rank_eligible": eligible,
        "checks": checks,
        "inference_script_sha256": inference_sha,
        "inference_config_sha256": inference_config_sha,
        "checkpoint_sha256_observed": observed_checkpoint_sha,
    }


def bootstrap_mean_ci(
    values: Sequence[float], *, seed: int, samples: int = 10_000
) -> tuple[float, float]:
    """Deterministic percentile bootstrap CI over evaluation regions."""
    if samples < 100:
        raise ValidationError("bootstrap_samples must be at least 100")
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 1 or array.size == 0 or not np.all(np.isfinite(array)):
        raise ValidationError("bootstrap values must be a non-empty finite vector")
    if array.size == 1:
        value = float(array[0])
        return value, value
    rng = np.random.default_rng(seed)
    means: list[np.ndarray] = []
    remaining = samples
    batch = min(2048, samples)
    while remaining:
        count = min(batch, remaining)
        indices = rng.integers(0, array.size, size=(count, array.size))
        means.append(array[indices].mean(axis=1))
        remaining -= count
    draws = np.concatenate(means)
    low, high = np.quantile(draws, [0.025, 0.975])
    return float(low), float(high)


def build_report(
    *,
    model_document: Mapping[str, Any],
    dataset_document: Mapping[str, Any],
    model_path: Path,
    dataset_path: Path,
    root: Path,
    checkpoint_override: Path | None = None,
    results_document: Mapping[str, Any] | None = None,
    results_path: Path | None = None,
    bootstrap_samples: int = 10_000,
) -> dict[str, Any]:
    """Create a standardized preflight or measured evaluation report."""
    model = validate_model_card(model_document)
    dataset = validate_dataset_manifest(dataset_document)
    preflight = build_preflight(
        model, dataset, root=root, checkpoint_override=checkpoint_override
    )

    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "tool": "scroliq-eval",
        "model": {
            "name": model["name"],
            "author": model["author"],
            "license": model["license"],
            "checkpoint_sha256": model["checkpoint_sha256"],
            "inference_config_sha256": model["inference_config_sha256"],
        },
        "dataset": {
            "id": dataset["id"],
            "task": dataset["task"],
            "held_out": True,
            "visibility": dataset["visibility"],
        },
        "preflight": preflight,
        "evaluation": {"status": "not_run"},
        "rank_eligible": False,
        "provenance": {
            "model_card_sha256": _canonical_sha256(model_document),
            "dataset_manifest_sha256": _canonical_sha256(dataset_document),
            "model_card_file_sha256": _file_sha256(model_path),
            "dataset_manifest_file_sha256": _file_sha256(dataset_path),
            "evaluator_sha256": _file_sha256(Path(__file__)),
            "inference_script_sha256": preflight["inference_script_sha256"],
            "inference_config_sha256": preflight["inference_config_sha256"],
            "checkpoint_sha256": preflight["checkpoint_sha256_observed"],
        },
    }

    if results_document is None:
        return report

    results = validate_region_results(results_document, model=model, dataset=dataset)
    by_id = {row["id"]: row for row in results["regions"]}
    failure_value = dataset["primary_metric"]["failure_value"]
    metric_name = dataset["primary_metric"]["name"]

    values: list[float] = []
    region_rows: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for expected in dataset["regions"]:
        region_id = expected["id"]
        row = by_id.get(region_id)
        if row is None:
            values.append(failure_value)
            failure = {"id": region_id, "kind": "missing", "reason": "no result emitted"}
            failures.append(failure)
            region_rows.append({**failure, "score_used": failure_value})
        elif row["status"] == "failed":
            values.append(failure_value)
            failure = {"id": region_id, "kind": "failed", "reason": row["reason"]}
            failures.append(failure)
            region_rows.append({**failure, "score_used": failure_value})
        else:
            values.append(row["metric"])
            region_rows.append(
                {"id": region_id, "kind": "ok", "score_used": row["metric"]}
            )

    point = float(np.mean(np.asarray(values, dtype=np.float64)))
    ci_low, ci_high = bootstrap_mean_ci(
        values, seed=dataset["bootstrap_seed"], samples=bootstrap_samples
    )
    rank_eligible = preflight["rank_eligible"] and not failures

    report["evaluation"] = {
        "status": "measured" if not failures else "incomplete",
        "primary_metric": metric_name,
        "higher_is_better": dataset["primary_metric"]["higher_is_better"],
        "point_estimate": point,
        "ci95": [ci_low, ci_high],
        "n": len(values),
        "bootstrap": {
            "method": "percentile bootstrap over held-out regions",
            "samples": bootstrap_samples,
            "seed": dataset["bootstrap_seed"],
        },
        "failure_value": failure_value,
        "failures": failures,
        "regions": region_rows,
    }
    report["rank_eligible"] = rank_eligible
    if results_path is not None:
        report["provenance"]["region_results_file_sha256"] = _file_sha256(results_path)
        report["provenance"]["region_results_sha256"] = _canonical_sha256(results_document)
    return report


def _render_text(report: Mapping[str, Any]) -> str:
    model = report["model"]["name"]
    dataset = report["dataset"]["id"]
    preflight = report["preflight"]["status"].upper()
    evaluation = report["evaluation"]
    lines = [f"ScrolIQ model evaluation: {model} × {dataset}", f"preflight={preflight}"]
    if evaluation["status"] == "not_run":
        lines.append("evaluation=NOT RUN")
    else:
        low, high = evaluation["ci95"]
        lines.append(
            f"{evaluation['primary_metric']}={evaluation['point_estimate']:.6g} "
            f"95% CI [{low:.6g}, {high:.6g}] n={evaluation['n']}"
        )
        lines.append(f"failed_or_missing_regions={len(evaluation['failures'])}")
    lines.append(f"rank_eligible={'yes' if report['rank_eligible'] else 'no'}")
    for check in report["preflight"]["checks"]:
        if not check["ok"]:
            lines.append(f"- BLOCKED {check['name']}: {check['detail']}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate a ScrolIQ model card against a held-out dataset and build "
            "a standardized fail-closed evaluation report."
        )
    )
    parser.add_argument("--model", required=True, help="model registry JSON")
    parser.add_argument("--dataset", required=True, help="held-out dataset manifest JSON")
    parser.add_argument(
        "--results",
        help="task-adapter per-region result JSON; omit only with --check-only",
    )
    parser.add_argument(
        "--checkpoint",
        help="checkpoint file; overrides model.checkpoint_path for hash verification",
    )
    parser.add_argument(
        "--root",
        default=".",
        help="repository root used to resolve inference_script/checkpoint_path",
    )
    parser.add_argument("--check-only", action="store_true", help="run provenance preflight only")
    parser.add_argument("--bootstrap-samples", type=int, default=10_000)
    parser.add_argument("--out", help="new report path; refuses overwrite")
    parser.add_argument("--format", choices=("text", "json", "github"), default="text")
    args = parser.parse_args(argv)

    if args.check_only and args.results:
        parser.error("--check-only cannot be combined with --results")
    if not args.check_only and not args.results:
        parser.error("--results is required unless --check-only is used")

    try:
        model_path = Path(args.model)
        dataset_path = Path(args.dataset)
        results_path = Path(args.results) if args.results else None
        model_document = _load_object(model_path, "model card")
        dataset_document = _load_object(dataset_path, "dataset manifest")
        results_document = (
            _load_object(results_path, "region results") if results_path is not None else None
        )
        report = build_report(
            model_document=model_document,
            dataset_document=dataset_document,
            model_path=model_path,
            dataset_path=dataset_path,
            root=Path(args.root),
            checkpoint_override=Path(args.checkpoint) if args.checkpoint else None,
            results_document=results_document,
            results_path=results_path,
            bootstrap_samples=args.bootstrap_samples,
        )
    except (ValidationError, OSError) as exc:
        parser.error(str(exc))

    encoded = json.dumps(report, indent=2, allow_nan=False) + "\n"
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            with out.open("x", encoding="utf-8") as fh:
                fh.write(encoded)
        except OSError as exc:
            parser.error(str(exc))

    if args.format == "json":
        print(encoded, end="")
    elif args.format == "github":
        for check in report["preflight"]["checks"]:
            if not check["ok"]:
                print(f"::error title=SCROLIQ_EVAL_BLOCKED::{check['name']}: {check['detail']}")
        if report["evaluation"]["status"] != "not_run":
            metric = report["evaluation"]["primary_metric"]
            point = report["evaluation"]["point_estimate"]
            low, high = report["evaluation"]["ci95"]
            print(
                f"::notice title=SCROLIQ_EVAL::{metric}={point:.6g} "
                f"ci95=[{low:.6g},{high:.6g}] n={report['evaluation']['n']}"
            )
    else:
        print(_render_text(report))

    if args.check_only:
        return 0 if report["preflight"]["rank_eligible"] else 1
    return 0 if report["rank_eligible"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
