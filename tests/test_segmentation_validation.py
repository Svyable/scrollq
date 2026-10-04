import hashlib
import json

import numpy as np
import pytest
from PIL import Image

from scrollq.model_eval import build_report, validate_model_card
from scrollq.segmentation_validation import (
    SegmentationValidationError,
    compute_truth_commitment,
    digest,
    evaluate,
    main,
)


def _write_surface(root, *, shape=(5, 5), z_value=10.0, valid=None, z_shift=None):
    root.mkdir(parents=True)
    yy, xx = np.mgrid[0:shape[0], 0:shape[1]]
    x = xx.astype(np.float32)
    y = yy.astype(np.float32)
    z = np.full(shape, z_value, dtype=np.float32)
    if z_shift is not None:
        z = z + np.asarray(z_shift, dtype=np.float32)
    if valid is not None:
        valid = np.asarray(valid, dtype=bool)
        x = x.copy()
        y = y.copy()
        z = z.copy()
        x[~valid] = -1
        y[~valid] = -1
        z[~valid] = -1
    for name, array in (("x.tif", x), ("y.tif", y), ("z.tif", z)):
        Image.fromarray(array).save(root / name)
    (root / "meta.json").write_text(
        json.dumps(
            {
                "format": "tifxyz",
                "scale": [1.0, 1.0],
                "bbox": [
                    [float(x[x >= 0].min()), float(y[y >= 0].min()), float(z[z > 0].min())],
                    [float(x.max()), float(y.max()), float(z.max())],
                ],
            }
        ),
        encoding="utf-8",
    )
    return root


def _fixture(tmp_path, *, tolerance=0.1, region_gate=None):
    dataset = {
        "schema_version": 1,
        "id": "blind-surface-v1",
        "task": "segmentation",
        "held_out": True,
        "evaluation_data": ["PHerc-test-heldout-v1"],
        "regions": [{"id": "r1"}],
        "primary_metric": {
            "name": "bidirectional_coverage",
            "higher_is_better": True,
            "failure_value": 0.0,
        },
        "visibility": "private_blind",
        "bootstrap_seed": 9,
    }

    truth_root = tmp_path / "truth"
    pred_root = tmp_path / "pred"
    _write_surface(truth_root / "r1.tifxyz")
    _write_surface(pred_root / "r1.tifxyz")

    truth = {
        "schema_version": 1,
        "dataset": dataset["id"],
        "volume_root": "PHerc-test/volumes/exact.zarr",
        "coordinate_system": "base_voxel_xyz",
        "commitment_salt": "11" * 32,
        "regions": [{"id": "r1", "tifxyz": "r1.tifxyz"}],
    }
    commitment = compute_truth_commitment(
        dataset_document=dataset,
        truth_document=truth,
        truth_root=truth_root,
    )["truth_commitment_sha256"]

    region = {"id": "r1"}
    if region_gate:
        region.update(region_gate)
    spec = {
        "schema_version": 1,
        "dataset": dataset["id"],
        "dataset_manifest_sha256": digest(dataset),
        "truth_commitment_sha256": commitment,
        "volume_root": truth["volume_root"],
        "coordinate_system": "base_voxel_xyz",
        "tolerance_voxels": tolerance,
        "max_vertices_per_surface": 100,
        "regions": [region],
    }
    provenance = {
        "checkpoint_sha256": "a" * 64,
        "inference_script_sha256": "b" * 64,
        "inference_config_sha256": "c" * 64,
    }
    predictions = {
        "schema_version": 1,
        "model": "surface-model-v1",
        "dataset": dataset["id"],
        "spec_sha256": digest(spec),
        "volume_root": truth["volume_root"],
        "coordinate_system": "base_voxel_xyz",
        "provenance": provenance,
        "regions": [{"id": "r1", "status": "ok", "tifxyz": "r1.tifxyz"}],
    }
    return dataset, spec, truth, predictions, truth_root, pred_root


def _evaluate(fixture):
    dataset, spec, truth, predictions, truth_root, pred_root = fixture
    return evaluate(
        dataset_document=dataset,
        spec_document=spec,
        truth_document=truth,
        predictions_document=predictions,
        truth_root=truth_root,
        prediction_root=pred_root,
    )


def test_exact_surface_scores_one_and_preserves_commitment(tmp_path):
    fixture = _fixture(tmp_path)
    result = _evaluate(fixture)
    row = result["regions"][0]
    assert row["status"] == "ok"
    assert row["metrics"]["bidirectional_coverage"] == 1.0
    assert row["metrics"]["symmetric_p95_voxels"] == 0.0
    assert row["evidence_sha256"]["truth_commitment"] == fixture[1]["truth_commitment_sha256"]
    assert "truth_surface" not in row["evidence_sha256"]


def test_exact_tolerance_boundary_counts_as_covered(tmp_path):
    fixture = _fixture(tmp_path, tolerance=0.5)
    pred_root = fixture[-1]
    for name in ("z.tif",):
        z = np.full((5, 5), 10.5, dtype=np.float32)
        Image.fromarray(z).save(pred_root / "r1.tifxyz" / name)
    result = _evaluate(fixture)
    assert result["regions"][0]["metrics"]["bidirectional_coverage"] == 1.0


def test_missing_surface_area_reduces_bidirectional_coverage(tmp_path):
    fixture = _fixture(tmp_path, tolerance=0.1)
    pred_root = fixture[-1]
    valid = np.zeros((5, 5), dtype=bool)
    valid[:, :2] = True
    # Recreate the prediction so only 40% of truth vertices remain.
    for path in (pred_root / "r1.tifxyz").iterdir():
        path.unlink()
    (pred_root / "r1.tifxyz").rmdir()
    _write_surface(pred_root / "r1.tifxyz", valid=valid)

    row = _evaluate(fixture)["regions"][0]
    assert row["status"] == "ok"
    assert row["metrics"]["prediction_to_truth_coverage"] == 1.0
    assert row["metrics"]["truth_to_prediction_coverage"] == pytest.approx(0.4)
    assert row["metrics"]["bidirectional_coverage"] == pytest.approx(0.4)


def test_extra_wrong_sheet_surface_reduces_prediction_to_truth_coverage(tmp_path):
    fixture = _fixture(tmp_path, tolerance=0.1)
    pred_root = fixture[-1]
    shift = np.zeros((5, 5), dtype=np.float32)
    shift[:, 2:] = 10.0
    for path in (pred_root / "r1.tifxyz").iterdir():
        path.unlink()
    (pred_root / "r1.tifxyz").rmdir()
    _write_surface(pred_root / "r1.tifxyz", z_shift=shift)

    row = _evaluate(fixture)["regions"][0]
    assert row["status"] == "ok"
    assert row["metrics"]["prediction_to_truth_coverage"] == pytest.approx(0.4)
    assert row["metrics"]["bidirectional_coverage"] == pytest.approx(0.4)
    assert row["metrics"]["symmetric_p95_voxels"] > 5


def test_completely_missed_truth_component_is_measured(tmp_path):
    fixture = list(_fixture(tmp_path, tolerance=0.1))
    dataset, spec, truth, predictions, truth_root, pred_root = fixture

    truth_valid = np.ones((5, 5), dtype=bool)
    truth_valid[:, 2] = False
    pred_valid = np.zeros((5, 5), dtype=bool)
    pred_valid[:, :2] = True

    for root, valid in (
        (truth_root / "r1.tifxyz", truth_valid),
        (pred_root / "r1.tifxyz", pred_valid),
    ):
        for path in root.iterdir():
            path.unlink()
        root.rmdir()
        _write_surface(root, valid=valid)

    spec["truth_commitment_sha256"] = compute_truth_commitment(
        dataset_document=dataset,
        truth_document=truth,
        truth_root=truth_root,
    )["truth_commitment_sha256"]
    predictions["spec_sha256"] = digest(spec)

    row = _evaluate(tuple(fixture))["regions"][0]
    assert row["metrics"]["truth_components"] == 2
    assert row["metrics"]["truth_components_with_prediction_support"] == 1
    assert row["metrics"]["truth_component_recall_any"] == pytest.approx(0.5)
    assert row["metrics"]["truth_component_min_coverage"] == 0.0


def test_hidden_truth_tampering_is_rejected_by_public_commitment(tmp_path):
    fixture = _fixture(tmp_path)
    truth_root = fixture[-2]
    z = np.full((5, 5), 11.0, dtype=np.float32)
    Image.fromarray(z).save(truth_root / "r1.tifxyz" / "z.tif")
    with pytest.raises(SegmentationValidationError, match="truth_commitment"):
        _evaluate(fixture)


def test_fragmentation_gate_fails_but_retains_metrics(tmp_path):
    fixture = _fixture(
        tmp_path,
        region_gate={
            "max_prediction_components": 1,
            "min_largest_component_fraction": 0.75,
        },
    )
    pred_root = fixture[-1]
    valid = np.ones((5, 5), dtype=bool)
    valid[:, 2] = False
    for path in (pred_root / "r1.tifxyz").iterdir():
        path.unlink()
    (pred_root / "r1.tifxyz").rmdir()
    _write_surface(pred_root / "r1.tifxyz", valid=valid)

    row = _evaluate(fixture)["regions"][0]
    assert row["status"] == "failed"
    assert row["metrics"]["prediction_components"] == 2
    assert row["metrics"]["bidirectional_coverage"] < 1
    assert "components" in row["reason"]


def test_missing_prediction_is_explicit_failure(tmp_path):
    fixture = list(_fixture(tmp_path))
    fixture[3]["regions"] = []
    row = _evaluate(tuple(fixture))["regions"][0]
    assert row["status"] == "failed"
    assert "no result" in row["reason"]


def test_prediction_surface_over_vertex_cap_fails_region(tmp_path):
    fixture = list(_fixture(tmp_path))
    fixture[1]["max_vertices_per_surface"] = 30
    fixture[3]["spec_sha256"] = digest(fixture[1])
    pred_root = fixture[-1]
    for path in (pred_root / "r1.tifxyz").iterdir():
        path.unlink()
    (pred_root / "r1.tifxyz").rmdir()
    _write_surface(pred_root / "r1.tifxyz", shape=(6, 6))
    row = _evaluate(tuple(fixture))["regions"][0]
    assert row["status"] == "failed"
    assert "exceeds preregistered cap" in row["reason"]


def test_changed_spec_is_rejected_before_truth_scoring(tmp_path):
    fixture = list(_fixture(tmp_path))
    fixture[1]["tolerance_voxels"] = 5.0
    with pytest.raises(SegmentationValidationError, match="spec_sha256"):
        _evaluate(tuple(fixture))


def test_segmentation_output_flows_into_common_model_eval(tmp_path):
    fixture = _fixture(tmp_path)
    dataset, _, _, predictions, _, _ = fixture
    results = _evaluate(fixture)

    repo = tmp_path / "repo"
    script = repo / "models" / "surface" / "infer.py"
    script.parent.mkdir(parents=True)
    script.write_text("print('surface')\n", encoding="utf-8")
    checkpoint = script.parent / "model.bin"
    checkpoint.write_bytes(b"surface-checkpoint")

    model = {
        "schema_version": 1,
        "name": predictions["model"],
        "author": "Fixture",
        "checkpoint_sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
        "checkpoint_path": "models/surface/model.bin",
        "training_data": ["train-surface-a"],
        "held_out_excluded": True,
        "inference_script": "models/surface/infer.py",
        "inference_config": {"threshold": 0.5},
        "license": "MIT",
        "tasks": ["segmentation"],
        "stochastic": False,
    }
    normalized = validate_model_card(model)
    results["provenance"] = {
        "checkpoint_sha256": model["checkpoint_sha256"],
        "inference_script_sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
        "inference_config_sha256": normalized["inference_config_sha256"],
    }
    model_path = tmp_path / "model.json"
    dataset_path = tmp_path / "dataset.json"
    results_path = tmp_path / "results.json"
    model_path.write_text(json.dumps(model), encoding="utf-8")
    dataset_path.write_text(json.dumps(dataset), encoding="utf-8")
    results_path.write_text(json.dumps(results), encoding="utf-8")

    report = build_report(
        model_document=model,
        dataset_document=dataset,
        model_path=model_path,
        dataset_path=dataset_path,
        root=repo,
        results_document=results,
        results_path=results_path,
        bootstrap_samples=100,
    )
    assert report["rank_eligible"] is True
    assert report["evaluation"]["point_estimate"] == 1.0
    region = report["evaluation"]["regions"][0]
    assert region["metrics"]["symmetric_p95_voxels"] == 0.0
    assert region["evidence_sha256"]["truth_commitment"] == fixture[1]["truth_commitment_sha256"]


def test_cli_commit_spec_hash_and_create_only_output(tmp_path, capsys):
    dataset, spec, truth, predictions, truth_root, pred_root = _fixture(tmp_path)
    dataset_path = tmp_path / "dataset.json"
    spec_path = tmp_path / "spec.json"
    truth_path = tmp_path / "truth.json"
    pred_path = tmp_path / "predictions.json"
    out = tmp_path / "results.json"
    dataset_path.write_text(json.dumps(dataset), encoding="utf-8")
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    truth_path.write_text(json.dumps(truth), encoding="utf-8")
    pred_path.write_text(json.dumps(predictions), encoding="utf-8")

    assert main([
        "--dataset", str(dataset_path),
        "--truth", str(truth_path),
        "--truth-root", str(truth_root),
        "--print-truth-commitment",
    ]) == 0
    assert capsys.readouterr().out.strip() == spec["truth_commitment_sha256"]

    assert main([
        "--dataset", str(dataset_path),
        "--spec", str(spec_path),
        "--print-spec-hash",
    ]) == 0
    assert capsys.readouterr().out.strip() == digest(spec)

    args = [
        "--dataset", str(dataset_path),
        "--spec", str(spec_path),
        "--truth", str(truth_path),
        "--predictions", str(pred_path),
        "--truth-root", str(truth_root),
        "--prediction-root", str(pred_root),
        "--out", str(out),
    ]
    assert main(args) == 0
    original = out.read_bytes()
    with pytest.raises(SystemExit) as error:
        main(args)
    assert error.value.code == 2
    assert out.read_bytes() == original
