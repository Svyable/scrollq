import hashlib
import json

import pytest

from scrollq.ink_results import build_results, main
from scrollq.model_eval import ValidationError


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _setup(tmp_path, *, regions=("w058", "w060")):
    inference = tmp_path / "models" / "v8in" / "infer.py"
    inference.parent.mkdir(parents=True)
    inference.write_text("print('infer')\n", encoding="utf-8")
    checkpoint = tmp_path / "model.pt"
    checkpoint.write_bytes(b"checkpoint")

    model = {
        "schema_version": 1,
        "name": "v8in",
        "author": "Youssef Nader",
        "checkpoint_sha256": _sha(checkpoint),
        "training_data": ["v8-patchpack/train"],
        "held_out_excluded": True,
        "inference_script": "models/v8in/infer.py",
        "inference_config": {
            "layer_order": "frozen",
            "overlap": 0.5,
        },
        "license": "MIT",
        "tasks": ["ink"],
        "stochastic": False,
    }
    dataset = {
        "schema_version": 1,
        "id": "pherc1447-zero-shot",
        "task": "ink",
        "held_out": True,
        "evaluation_data": ["pherc1447/refined-labels"],
        "regions": [{"id": region} for region in regions],
        "primary_metric": {
            "name": "roc_auc",
            "higher_is_better": True,
            "failure_value": 0.0,
        },
        "visibility": "public",
        "bootstrap_seed": 1447,
    }
    return model, dataset, checkpoint


def _report(region, checkpoint_sha, *, ready=True):
    return {
        "schema_version": 1,
        "tool": "scroliq-ink-validate",
        "purpose": "held-out ink signal recovery / false-positive evidence",
        "split": {
            "id": region,
            "held_out": True,
            "training_overlap": "none",
            "known_ground_truth": True,
            "ground_truth_source_url": "https://example.org/ground-truth",
        },
        "model": {
            "checkpoint_sha256": checkpoint_sha,
            "window_voxels_zyx": [17, 64, 64],
        },
        "evaluation": {
            "roc_auc": 0.86,
            "balanced_accuracy": 0.78,
            "false_positive_rate": 0.09,
            "f1": 0.71,
            "iou": 0.55,
            "brier": 0.12,
            "ink_background_margin": 0.31,
            "precision": 0.75,
            "recall": 0.68,
            "specificity": 0.91,
        },
        "controls": [{"name": "normal+3"}] if ready else [],
        "evaluated_arrays_sha256": "a" * 64,
        "inputs": {
            "prediction": {"path": "prediction.tif", "sha256": "b" * 64},
            "labels": {"path": "labels.tif", "sha256": "c" * 64},
            "validation_mask": {"path": "mask.tif", "sha256": "d" * 64},
        },
        "prize_evidence_ready": ready,
        "readiness_reasons": [] if ready else ["no falsification-control prediction was evaluated"],
    }


def _write_report(tmp_path, region, report):
    path = tmp_path / f"{region}.ink.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return path


def test_builds_common_results_with_verified_run_identity(tmp_path):
    model, dataset, checkpoint = _setup(tmp_path)
    reports = {
        region: _write_report(
            tmp_path,
            region,
            _report(region, model["checkpoint_sha256"]),
        )
        for region in ("w058", "w060")
    }

    result = build_results(
        model_document=model,
        dataset_document=dataset,
        root=tmp_path,
        checkpoint=checkpoint,
        region_reports=reports,
    )

    assert result["model"] == "v8in"
    assert result["dataset"] == "pherc1447-zero-shot"
    assert result["task"] == "ink"
    assert result["provenance"]["checkpoint_sha256"] == model["checkpoint_sha256"]
    assert len(result["provenance"]["inference_script_sha256"]) == 64
    assert len(result["provenance"]["inference_config_sha256"]) == 64
    assert [row["status"] for row in result["regions"]] == ["ok", "ok"]
    assert result["regions"][0]["metrics"]["roc_auc"] == 0.86
    assert result["regions"][0]["evidence_sha256"]["prediction"] == "b" * 64


def test_missing_expected_region_becomes_explicit_failure(tmp_path):
    model, dataset, checkpoint = _setup(tmp_path)
    report = _write_report(
        tmp_path, "w058", _report("w058", model["checkpoint_sha256"])
    )

    result = build_results(
        model_document=model,
        dataset_document=dataset,
        root=tmp_path,
        checkpoint=checkpoint,
        region_reports={"w058": report},
    )

    assert result["regions"][1] == {
        "id": "w060",
        "status": "failed",
        "reason": "no ink-validation report supplied",
    }


def test_wrong_split_and_checkpoint_fail_region_not_whole_adapter(tmp_path):
    model, dataset, checkpoint = _setup(tmp_path, regions=("w058",))
    report = _report("other", "e" * 64)
    path = _write_report(tmp_path, "w058", report)

    result = build_results(
        model_document=model,
        dataset_document=dataset,
        root=tmp_path,
        checkpoint=checkpoint,
        region_reports={"w058": path},
    )

    row = result["regions"][0]
    assert row["status"] == "failed"
    assert "does not match region" in row["reason"]
    assert "checkpoint SHA-256" in row["reason"]


def test_non_ready_ink_report_fails_region(tmp_path):
    model, dataset, checkpoint = _setup(tmp_path, regions=("w058",))
    path = _write_report(
        tmp_path,
        "w058",
        _report("w058", model["checkpoint_sha256"], ready=False),
    )

    result = build_results(
        model_document=model,
        dataset_document=dataset,
        root=tmp_path,
        checkpoint=checkpoint,
        region_reports={"w058": path},
    )

    assert result["regions"][0]["status"] == "failed"
    assert "not prize-evidence-ready" in result["regions"][0]["reason"]


def test_unknown_region_mapping_and_blocked_preflight_fail_closed(tmp_path):
    model, dataset, checkpoint = _setup(tmp_path)
    with pytest.raises(ValidationError, match="unknown ids"):
        build_results(
            model_document=model,
            dataset_document=dataset,
            root=tmp_path,
            checkpoint=checkpoint,
            region_reports={"w999": tmp_path / "none.json"},
        )

    model["training_data"].append("pherc1447/refined-labels")
    with pytest.raises(ValidationError, match="preflight is blocked"):
        build_results(
            model_document=model,
            dataset_document=dataset,
            root=tmp_path,
            checkpoint=checkpoint,
            region_reports={},
        )


def test_cli_writes_results_and_returns_nonzero_for_incomplete_set(tmp_path):
    model, dataset, checkpoint = _setup(tmp_path)
    model_path = tmp_path / "model.json"
    dataset_path = tmp_path / "dataset.json"
    model_path.write_text(json.dumps(model), encoding="utf-8")
    dataset_path.write_text(json.dumps(dataset), encoding="utf-8")
    report_path = _write_report(
        tmp_path, "w058", _report("w058", model["checkpoint_sha256"])
    )
    out = tmp_path / "results.json"

    rc = main(
        [
            "--model",
            str(model_path),
            "--dataset",
            str(dataset_path),
            "--checkpoint",
            str(checkpoint),
            "--root",
            str(tmp_path),
            "--region",
            f"w058={report_path}",
            "--out",
            str(out),
        ]
    )

    assert rc == 1
    result = json.loads(out.read_text(encoding="utf-8"))
    assert result["regions"][0]["status"] == "ok"
    assert result["regions"][1]["status"] == "failed"

    with pytest.raises(SystemExit) as error:
        main(
            [
                "--model",
                str(model_path),
                "--dataset",
                str(dataset_path),
                "--checkpoint",
                str(checkpoint),
                "--root",
                str(tmp_path),
                "--out",
                str(out),
            ]
        )
    assert error.value.code == 2
