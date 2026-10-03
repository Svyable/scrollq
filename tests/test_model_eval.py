import hashlib
import json

import pytest

from scrollq.model_eval import (
    ValidationError,
    bootstrap_mean_ci,
    build_report,
    main,
    validate_dataset_manifest,
    validate_model_card,
)


def _fixture(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    script = root / "models" / "demo" / "infer.py"
    script.parent.mkdir(parents=True)
    script.write_text("print('demo')\n")
    checkpoint = script.parent / "model.bin"
    checkpoint.write_bytes(b"checkpoint-v1")
    checkpoint_sha = hashlib.sha256(checkpoint.read_bytes()).hexdigest()

    model = {
        "schema_version": 1,
        "name": "demo-ink-v1",
        "author": "Demo Author",
        "checkpoint_sha256": checkpoint_sha,
        "checkpoint_path": "models/demo/model.bin",
        "training_data": ["train-a"],
        "held_out_excluded": True,
        "inference_script": "models/demo/infer.py",
        "inference_config": {
            "overlap": 0.5,
            "blend_mode": "hann",
            "layer_start": 0,
            "layer_end": 64
        },
        "license": "MIT",
        "tasks": ["ink"],
        "stochastic": True,
        "random_seed": 7,
        "training_run_url": "https://example.org/train-run",
    }
    dataset = {
        "schema_version": 1,
        "id": "blind-ink-v1",
        "task": "ink",
        "held_out": True,
        "evaluation_data": ["holdout-a"],
        "regions": [{"id": "r1"}, {"id": "r2"}, {"id": "r3"}],
        "primary_metric": {
            "name": "balanced_accuracy",
            "higher_is_better": True,
            "failure_value": 0.0,
        },
        "visibility": "private_blind",
        "bootstrap_seed": 123,
    }
    model_path = tmp_path / "model.json"
    dataset_path = tmp_path / "dataset.json"
    model_path.write_text(json.dumps(model))
    dataset_path.write_text(json.dumps(dataset))
    return root, model, dataset, model_path, dataset_path


def test_model_and_dataset_contracts(tmp_path):
    _, model, dataset, *_ = _fixture(tmp_path)
    assert validate_model_card(model)["random_seed"] == 7
    assert validate_dataset_manifest(dataset)["primary_metric"]["failure_value"] == 0.0


def test_undeclared_tasks_fail_closed(tmp_path):
    root, model, dataset, model_path, dataset_path = _fixture(tmp_path)
    model.pop("tasks")
    model_path.write_text(json.dumps(model))
    report = build_report(
        model_document=model,
        dataset_document=dataset,
        model_path=model_path,
        dataset_path=dataset_path,
        root=root,
    )
    check = next(c for c in report["preflight"]["checks"] if c["name"] == "task_supported")
    assert check["ok"] is False
    assert report["preflight"]["rank_eligible"] is False


def test_stochastic_model_requires_seed(tmp_path):
    _, model, *_ = _fixture(tmp_path)
    model.pop("random_seed")
    with pytest.raises(ValidationError, match="random_seed"):
        validate_model_card(model)


def test_missing_inference_configuration_blocks_ranking(tmp_path):
    root, model, dataset, model_path, dataset_path = _fixture(tmp_path)
    model.pop("inference_config")
    model_path.write_text(json.dumps(model))
    report = build_report(
        model_document=model,
        dataset_document=dataset,
        model_path=model_path,
        dataset_path=dataset_path,
        root=root,
    )
    check = next(
        c for c in report["preflight"]["checks"]
        if c["name"] == "inference_configuration"
    )
    assert check["ok"] is False
    assert report["preflight"]["rank_eligible"] is False


def test_inference_configuration_is_canonical_hash_bound(tmp_path):
    _, model, *_ = _fixture(tmp_path)
    first = validate_model_card(model)
    reordered = dict(model)
    reordered["inference_config"] = {
        "layer_end": 64,
        "layer_start": 0,
        "blend_mode": "hann",
        "overlap": 0.5,
    }
    second = validate_model_card(reordered)
    assert first["inference_config_sha256"] == second["inference_config_sha256"]

    changed = dict(model)
    changed["inference_config"] = dict(model["inference_config"])
    changed["inference_config"]["overlap"] = 0.25
    third = validate_model_card(changed)
    assert first["inference_config_sha256"] != third["inference_config_sha256"]


def test_inference_configuration_rejects_empty_or_nonfinite(tmp_path):
    _, model, *_ = _fixture(tmp_path)
    model["inference_config"] = {}
    with pytest.raises(ValidationError, match="non-empty JSON object"):
        validate_model_card(model)
    model["inference_config"] = {"overlap": float("nan")}
    with pytest.raises(ValidationError, match="finite JSON values"):
        validate_model_card(model)


def test_overlap_blocks_ranking(tmp_path):
    root, model, dataset, model_path, dataset_path = _fixture(tmp_path)
    model["training_data"] = ["holdout-a"]
    model_path.write_text(json.dumps(model))
    report = build_report(
        model_document=model,
        dataset_document=dataset,
        model_path=model_path,
        dataset_path=dataset_path,
        root=root,
    )
    assert report["preflight"]["rank_eligible"] is False
    overlap = next(c for c in report["preflight"]["checks"] if c["name"] == "training_overlap")
    assert overlap["overlap"] == ["holdout-a"]


def test_checkpoint_mismatch_blocks_ranking(tmp_path):
    root, model, dataset, model_path, dataset_path = _fixture(tmp_path)
    model["checkpoint_sha256"] = "a" * 64
    model_path.write_text(json.dumps(model))
    report = build_report(
        model_document=model,
        dataset_document=dataset,
        model_path=model_path,
        dataset_path=dataset_path,
        root=root,
    )
    check = next(c for c in report["preflight"]["checks"] if c["name"] == "checkpoint_hash")
    assert check["ok"] is False
    assert "mismatch" in check["detail"]


def test_bootstrap_is_deterministic():
    a = bootstrap_mean_ci([0.8, 0.9, 1.0], seed=4, samples=1000)
    b = bootstrap_mean_ci([0.8, 0.9, 1.0], seed=4, samples=1000)
    assert a == b


def test_complete_results_get_ci_and_rank(tmp_path):
    root, model, dataset, model_path, dataset_path = _fixture(tmp_path)
    results = {
        "schema_version": 1,
        "model": model["name"],
        "dataset": dataset["id"],
        "task": "ink",
        "regions": [
            {"id": "r1", "status": "ok", "metrics": {"balanced_accuracy": 0.8}},
            {"id": "r2", "status": "ok", "metrics": {"balanced_accuracy": 0.9}},
            {"id": "r3", "status": "ok", "metrics": {"balanced_accuracy": 1.0}},
        ],
    }
    result_path = tmp_path / "results.json"
    result_path.write_text(json.dumps(results))
    report = build_report(
        model_document=model,
        dataset_document=dataset,
        model_path=model_path,
        dataset_path=dataset_path,
        root=root,
        results_document=results,
        results_path=result_path,
        bootstrap_samples=1000,
    )
    assert report["rank_eligible"] is True
    assert report["evaluation"]["n"] == 3
    assert report["evaluation"]["point_estimate"] == pytest.approx(0.9)
    assert report["evaluation"]["ci95"][0] <= 0.9 <= report["evaluation"]["ci95"][1]
    assert report["evaluation"]["failures"] == []


def test_failed_or_missing_region_is_scored_fail_closed_and_not_ranked(tmp_path):
    root, model, dataset, model_path, dataset_path = _fixture(tmp_path)
    results = {
        "schema_version": 1,
        "model": model["name"],
        "dataset": dataset["id"],
        "task": "ink",
        "regions": [
            {"id": "r1", "status": "ok", "metrics": {"balanced_accuracy": 0.9}},
            {"id": "r2", "status": "failed", "reason": "inference crashed"},
        ],
    }
    report = build_report(
        model_document=model,
        dataset_document=dataset,
        model_path=model_path,
        dataset_path=dataset_path,
        root=root,
        results_document=results,
        bootstrap_samples=1000,
    )
    assert report["rank_eligible"] is False
    assert report["evaluation"]["status"] == "incomplete"
    assert report["evaluation"]["n"] == 3
    assert report["evaluation"]["point_estimate"] == pytest.approx(0.3)
    assert {f["kind"] for f in report["evaluation"]["failures"]} == {"failed", "missing"}


def test_unknown_region_rejected(tmp_path):
    root, model, dataset, model_path, dataset_path = _fixture(tmp_path)
    results = {
        "schema_version": 1,
        "model": model["name"],
        "dataset": dataset["id"],
        "task": "ink",
        "regions": [{"id": "other", "status": "ok", "metrics": {"balanced_accuracy": 1.0}}],
    }
    with pytest.raises(ValidationError, match="unknown region"):
        build_report(
            model_document=model,
            dataset_document=dataset,
            model_path=model_path,
            dataset_path=dataset_path,
            root=root,
            results_document=results,
        )


def test_cli_check_only_and_no_overwrite(tmp_path):
    root, _, _, model_path, dataset_path = _fixture(tmp_path)
    out = tmp_path / "report.json"
    args = [
        "--model", str(model_path),
        "--dataset", str(dataset_path),
        "--root", str(root),
        "--check-only",
        "--out", str(out),
        "--format", "json",
    ]
    assert main(args) == 0
    assert json.loads(out.read_text())["preflight"]["status"] == "ready"
    with pytest.raises(SystemExit) as error:
        main(args)
    assert error.value.code == 2
