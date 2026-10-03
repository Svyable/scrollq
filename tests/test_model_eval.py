import hashlib
import json

import pytest

from scrollq.model_eval import (
    bootstrap_region_ci,
    build_preflight_report,
    main,
    overlap_check,
)


def _write_inputs(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    script = root / "models" / "demo" / "infer.py"
    script.parent.mkdir(parents=True)
    script.write_text("print('demo')\n", encoding="utf-8")
    checkpoint = tmp_path / "model.ckpt"
    checkpoint.write_bytes(b"checkpoint-v1")

    card = {
        "schema_version": 1,
        "name": "demo-ink-v1",
        "author": "Example Author",
        "task": "ink_detection",
        "checkpoint_sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
        "checkpoint_url": "https://example.org/checkpoints/demo-ink-v1.ckpt",
        "training_data": ["training-set-v1"],
        "training_data_sources": {
            "training-set-v1": "https://example.org/datasets/training-set-v1"
        },
        "training_regions": ["other-set:r9"],
        "training_inventory_complete": True,
        "training_data_license": "CC-BY-NC-4.0",
        "held_out_excluded": True,
        "pseudo_labeling_used": False,
        "pseudo_label_stages": [],
        "inference_script": "models/demo/infer.py",
        "inference_sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
        "license": "MIT",
        "random_seed": 1729,
        "experiment_run_url": "https://example.org/runs/demo-ink-v1",
    }
    dataset = {
        "schema_version": 1,
        "dataset_id": "heldout-v1",
        "task": "ink_detection",
        "held_out": True,
        "source_url": "https://example.org/datasets/heldout-v1",
        "truth_commitment_sha256": "9" * 64,
        "regions": [
            {
                "id": "r1",
                "scroll_id": "PHerc0001",
                "volume_root": "PHerc0001/volumes/exact.zarr",
            },
            {
                "id": "r2",
                "scroll_id": "PHerc0002",
                "volume_root": "PHerc0002/volumes/exact.zarr",
            },
        ],
    }
    model_path = tmp_path / "model.json"
    dataset_path = tmp_path / "dataset.json"
    model_path.write_text(json.dumps(card), encoding="utf-8")
    dataset_path.write_text(json.dumps(dataset), encoding="utf-8")
    return root, script, checkpoint, card, dataset, model_path, dataset_path


def test_preflight_passes_but_never_ranks(tmp_path):
    root, _, checkpoint, card, dataset, model_path, dataset_path = _write_inputs(tmp_path)
    report = build_preflight_report(
        card=card,
        dataset=dataset,
        model_path=model_path,
        dataset_path=dataset_path,
        checkpoint_path=checkpoint,
        root_dir=root,
    )
    assert report["status"] == "pass"
    assert report["checks"]["training_overlap"]["status"] == "none"
    assert report["model"]["checkpoint"]["status"] == "pass"
    assert report["model"]["inference"]["status"] == "pass"
    assert report["rank_status"] == "not_evaluated"
    assert report["rank_eligible"] is False


def test_private_heldout_source_can_be_opaque_when_truth_is_committed(tmp_path):
    root, _, checkpoint, card, dataset, model_path, dataset_path = _write_inputs(tmp_path)
    dataset.pop("source_url")
    report = build_preflight_report(
        card=card,
        dataset=dataset,
        model_path=model_path,
        dataset_path=dataset_path,
        checkpoint_path=checkpoint,
        root_dir=root,
    )
    assert report["status"] == "pass"
    assert report["held_out_dataset"]["source_url"] is None
    assert report["held_out_dataset"]["truth_commitment_sha256"] == "9" * 64


def test_checkpoint_hash_mismatch_fails_closed(tmp_path):
    root, _, checkpoint, card, dataset, model_path, dataset_path = _write_inputs(tmp_path)
    card["checkpoint_sha256"] = "0" * 64
    report = build_preflight_report(
        card=card,
        dataset=dataset,
        model_path=model_path,
        dataset_path=dataset_path,
        checkpoint_path=checkpoint,
        root_dir=root,
    )
    assert report["status"] == "fail"
    assert report["model"]["checkpoint"]["status"] == "fail"
    assert "checkpoint SHA-256 mismatch" in report["rank_blockers"]


def test_overlap_blocks_even_when_card_claims_held_out(tmp_path):
    _, _, _, card, dataset, _, _ = _write_inputs(tmp_path)
    card["training_regions"].append("heldout-v1:r2")
    check = overlap_check(card, dataset)
    assert check["status"] == "present"
    assert check["region_overlap"] == ["heldout-v1:r2"]


def test_incomplete_training_inventory_is_unknown_and_blocked(tmp_path):
    root, _, checkpoint, card, dataset, model_path, dataset_path = _write_inputs(tmp_path)
    card["training_inventory_complete"] = False
    report = build_preflight_report(
        card=card,
        dataset=dataset,
        model_path=model_path,
        dataset_path=dataset_path,
        checkpoint_path=checkpoint,
        root_dir=root,
    )
    assert report["status"] == "fail"
    assert report["checks"]["training_overlap"]["status"] == "unknown"


def test_missing_public_training_source_blocks_preflight(tmp_path):
    root, _, checkpoint, card, dataset, model_path, dataset_path = _write_inputs(tmp_path)
    card["training_data_sources"] = {}
    report = build_preflight_report(
        card=card,
        dataset=dataset,
        model_path=model_path,
        dataset_path=dataset_path,
        checkpoint_path=checkpoint,
        root_dir=root,
    )
    assert report["status"] == "fail"
    assert any("training_data_sources" in item for item in report["rank_blockers"])


def test_pseudo_labeling_requires_every_stage_provenance(tmp_path):
    root, _, checkpoint, card, dataset, model_path, dataset_path = _write_inputs(tmp_path)
    card["pseudo_labeling_used"] = True
    card["pseudo_label_stages"] = []
    report = build_preflight_report(
        card=card,
        dataset=dataset,
        model_path=model_path,
        dataset_path=dataset_path,
        checkpoint_path=checkpoint,
        root_dir=root,
    )
    assert report["status"] == "fail"
    assert any("pseudo_label_stages" in item for item in report["rank_blockers"])


def test_inference_hash_mismatch_fails_closed(tmp_path):
    root, script, checkpoint, card, dataset, model_path, dataset_path = _write_inputs(tmp_path)
    script.write_text("print('changed')\n", encoding="utf-8")
    report = build_preflight_report(
        card=card,
        dataset=dataset,
        model_path=model_path,
        dataset_path=dataset_path,
        checkpoint_path=checkpoint,
        root_dir=root,
    )
    assert report["status"] == "fail"
    assert report["model"]["inference"]["status"] == "fail"


def test_bootstrap_ci_is_deterministic_and_region_based():
    values = [0.8, 0.9, 1.0, 0.7]
    first = bootstrap_region_ci(values, seed=7, samples=500)
    second = bootstrap_region_ci(values, seed=7, samples=500)
    assert first == second
    assert first["point_estimate"] == pytest.approx(0.85)
    assert first["n"] == 4
    assert first["bootstrap_unit"] == "region"
    assert first["ci95"][0] <= first["point_estimate"] <= first["ci95"][1]


def test_cli_writes_report_and_refuses_overwrite(tmp_path):
    root, _, checkpoint, _, _, model_path, dataset_path = _write_inputs(tmp_path)
    out = tmp_path / "report.json"
    args = [
        "--model",
        str(model_path),
        "--dataset",
        str(dataset_path),
        "--checkpoint",
        str(checkpoint),
        "--root-dir",
        str(root),
        "--out",
        str(out),
        "--format",
        "json",
    ]
    assert main(args) == 0
    report = json.loads(out.read_text())
    assert report["status"] == "pass"
    with pytest.raises(SystemExit) as exc:
        main(args)
    assert exc.value.code == 2
