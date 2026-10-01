import copy
import hashlib

from scrollq.provenance import validate_manifest


def _manifest():
    return {
        "schema_version": 3,
        "rules": {
            "url": "https://scrollprize.org/prizes",
            "as_of": "2026-09-30",
        },
        "submission": {
            "scroll_id": "PHerc0813",
            "eligible_volume_id": "20250821151723",
            "human_input_hours": 2.5,
        },
        "code": {
            "repository": "https://github.com/example/grand-prize-pipeline",
            "commit": "a" * 40,
            "license": "MIT",
            "docker_image": (
                "ghcr.io/example/grand-prize-pipeline@sha256:" + "b" * 64
            ),
        },
        "ct_volume": {
            "id": "ct:eligible",
            "scroll_id": "PHerc0813",
            "volume_id": "20250821151723",
            "uri": "s3://vesuvius/PHerc0813/volumes/20250821151723.zarr",
            "zarr_audit": {
                "tool": "zarr-pyramid-audit",
                "manifest_sha256": "c" * 64,
                "root": (
                    "s3://vesuvius/PHerc0813/volumes/"
                    "20250821151723.zarr"
                ),
            },
        },
        "region_sets": [
            {
                "id": "regions:train",
                "role": "training",
                "volume_id": "other-volume",
                "coordinate_space": "level0-voxel-index",
                "boxes": [
                    {"start": [0, 0, 0], "stop": [10, 10, 10]}
                ],
            },
            {
                "id": "regions:column-01",
                "role": "prediction",
                "volume_id": "20250821151723",
                "coordinate_space": "level0-voxel-index",
                "boxes": [
                    {
                        "start": [100, 100, 100],
                        "stop": [110, 110, 110],
                    }
                ],
            },
            {
                "id": "regions:held-out",
                "role": "validation",
                "volume_id": "public-validation-volume",
                "coordinate_space": "level0-voxel-index",
                "boxes": [
                    {
                        "start": [200, 200, 200],
                        "stop": [210, 210, 210],
                    }
                ],
            },
        ],
        "datasets": [
            {
                "id": "dataset:ink-v1",
                "public_url": "https://example.org/datasets/ink-v1",
                "license": "CC-BY-NC-4.0",
                "training_region_set_id": "regions:train",
                "sources": [
                    {
                        "scroll_id": "PHerc1667",
                        "volume_id": "public-training-volume",
                        "voxel_size_um": 7.91,
                    }
                ],
            }
        ],
        "models": [
            {
                "id": "model:ink-v1",
                "checkpoint_url": (
                    "https://example.org/checkpoints/ink-v1.ckpt"
                ),
                "sha256": "d" * 64,
                "checkpoint_license": "MIT",
                "training_dataset_ids": ["dataset:ink-v1"],
                "stochastic": {
                    "training": True,
                    "inference": True,
                },
                "training_seed": 1234,
                "inference_seed": 5678,
                "training_run": {
                    "url": "https://wandb.ai/example/project/runs/train",
                    "public": True,
                },
                "inference_run": {
                    "url": "https://wandb.ai/example/project/runs/infer",
                    "public": True,
                },
            }
        ],
        "surfaces": [
            {
                "id": "surface:column-01",
                "ct_volume_id": "ct:eligible",
                "uri": "s3://example/surfaces/column-01.zarr",
            }
        ],
        "meshes": [
            {
                "id": "mesh:column-01",
                "path": "column_01.tifxyz",
                "sha256": "e" * 64,
                "surface_id": "surface:column-01",
                "ct_volume_id": "ct:eligible",
                "flattening": "low-distortion-isometric",
                "column": 1,
            }
        ],
        "renders": [
            {
                "id": "render:column-01",
                "path": "column_01.tif",
                "sha256": "f" * 64,
                "mesh_id": "mesh:column-01",
                "ct_volume_id": "ct:eligible",
                "model_id": "model:ink-v1",
                "prediction_region_set_id": "regions:column-01",
                "column": 1,
                "scale_bar_cm": 1,
                "generated_by": {
                    "command": (
                        "python -m pipeline.render --column 1"
                    ),
                    "code_commit": "a" * 40,
                },
            }
        ],
        "held_out_validations": [
            {
                "id": "validation:ink-v1",
                "model_id": "model:ink-v1",
                "protocol": "held-out",
                "region_set_id": "regions:held-out",
                "public_input_url": (
                    "https://example.org/validation/input-volume"
                ),
                "ground_truth_url": (
                    "https://example.org/validation/ground-truth"
                ),
                "public_url": (
                    "https://example.org/validation/results/ink-v1"
                ),
                "path": "held_out_validation.json",
                "sha256": "2" * 64,
                "metrics": {
                    "precision": 0.91,
                    "recall": 0.87,
                },
                "experiment_run": {
                    "url": (
                        "https://wandb.ai/example/project/runs/held-out"
                    ),
                    "public": True,
                },
                "code_commit": "a" * 40,
            }
        ],
        "recto_coverage": {
            "schema_version": 1,
            "volume_root": (
                "s3://vesuvius/PHerc0813/volumes/"
                "20250821151723.zarr"
            ),
            "generated_by": {
                "command": "python -m pipeline.measure_recto",
                "code_commit": "a" * 40,
            },
            "reference": {
                "surface_area": 100.0,
                "area_unit": "mm^2",
                "method": "Frozen reference recto inventory",
                "artifact_url": "https://example.org/recto/reference.json",
                "sha256": "3" * 64,
            },
            "components": [
                {
                    "id": "main-sheet",
                    "kind": "main-sheet",
                    "area": 100.0,
                    "unrolled": True,
                    "excluded": False,
                    "mesh_ids": ["mesh:column-01"],
                }
            ],
        },
        "banner": {
            "path": "banner.tif",
            "sha256": "1" * 64,
            "render_ids": ["render:column-01"],
            "column_numbers_overlaid": True,
        },
    }


def _codes(report):
    return {item["code"] for item in report["errors"]}


def test_valid_manifest_builds_a_complete_render_chain():
    report = validate_manifest(_manifest())

    assert report["eligible"] is True
    assert report["error_count"] == 0
    chain = report["render_chains"][0]
    assert chain["ct_volume_id"] == "ct:eligible"
    assert chain["surface_id"] == "surface:column-01"
    assert chain["mesh_id"] == "mesh:column-01"
    assert chain["model_id"] == "model:ink-v1"
    assert chain["training_seed"] == 1234
    assert chain["inference_seed"] == 5678
    assert chain["region_exclusion"]["overlaps"] == []
    assert report["held_out_validation_proofs"][0]["overlaps"] == []
    assert report["recto_coverage_proof"]["status"] == "pass"
    assert report["recto_coverage_proof"]["mesh_ids"] == ["mesh:column-01"]


def test_wrong_same_scroll_volume_fails_closed():
    manifest = _manifest()
    manifest["submission"]["eligible_volume_id"] = "20260319130212"
    manifest["ct_volume"]["volume_id"] = "20260319130212"
    manifest["ct_volume"]["uri"] = (
        "s3://vesuvius/PHerc0813/volumes/20260319130212.zarr"
    )

    report = validate_manifest(manifest)

    assert report["eligible"] is False
    assert "GP_VOLUME_NOT_ELIGIBLE" in _codes(report)


def test_training_prediction_overlap_is_detected():
    manifest = _manifest()
    train = manifest["region_sets"][0]
    train["volume_id"] = "20250821151723"
    train["boxes"] = [
        {
            "start": [105, 105, 105],
            "stop": [120, 120, 120],
        }
    ]

    report = validate_manifest(manifest)

    assert "GP_TRAIN_PREDICT_OVERLAP" in _codes(report)
    assert (
        report["render_chains"][0]["region_exclusion"]["checked_pairs"]
        == 1
    )


def test_touching_half_open_regions_are_disjoint():
    manifest = _manifest()
    train = manifest["region_sets"][0]
    train["volume_id"] = "20250821151723"
    train["boxes"] = [
        {
            "start": [90, 100, 100],
            "stop": [100, 110, 110],
        }
    ]

    report = validate_manifest(manifest)

    assert "GP_TRAIN_PREDICT_OVERLAP" not in _codes(report)
    assert report["eligible"] is True


def test_stochastic_inference_requires_seed_and_public_run():
    manifest = _manifest()
    model = manifest["models"][0]
    del model["inference_seed"]
    model["inference_run"]["public"] = False

    report = validate_manifest(manifest)

    assert "GP_MISSING_SEED" in _codes(report)
    assert "GP_RUN_NOT_PUBLIC" in _codes(report)


def test_training_dataset_must_be_public_cc_by_nc():
    manifest = _manifest()
    dataset = manifest["datasets"][0]
    dataset["public_url"] = "private://dataset"
    dataset["license"] = "MIT"

    report = validate_manifest(manifest)

    assert {
        "GP_DATASET_PUBLIC",
        "GP_DATASET_LICENSE",
    } <= _codes(report)


def test_higher_resolution_same_scroll_training_source_is_rejected():
    manifest = _manifest()
    manifest["datasets"][0]["sources"] = [
        {
            "scroll_id": "PHerc0813",
            "volume_id": "some-other-scan",
            "voxel_size_um": 2.4,
        }
    ]

    report = validate_manifest(manifest)

    assert "GP_HIGHER_RES_SAME_SCROLL_SOURCE" in _codes(report)


def test_package_file_hashes_are_verified(tmp_path):
    manifest = _manifest()
    payloads = {
        "column_01.tifxyz": b"mesh",
        "column_01.tif": b"render",
        "banner.tif": b"banner",
        "held_out_validation.json": b"held-out",
    }
    for name, payload in payloads.items():
        (tmp_path / name).write_bytes(payload)

    manifest["meshes"][0]["sha256"] = hashlib.sha256(
        payloads["column_01.tifxyz"]
    ).hexdigest()
    manifest["renders"][0]["sha256"] = hashlib.sha256(
        payloads["column_01.tif"]
    ).hexdigest()
    manifest["banner"]["sha256"] = hashlib.sha256(
        payloads["banner.tif"]
    ).hexdigest()
    manifest["held_out_validations"][0]["sha256"] = hashlib.sha256(
        payloads["held_out_validation.json"]
    ).hexdigest()

    report = validate_manifest(manifest, root_dir=tmp_path)
    assert report["eligible"] is True

    (tmp_path / "column_01.tif").write_bytes(b"tampered")
    report = validate_manifest(manifest, root_dir=tmp_path)
    assert "GP_HASH_MISMATCH" in _codes(report)


def test_pseudo_label_producer_checkpoint_must_use_cc_by_nc():
    manifest = _manifest()
    dataset = manifest["datasets"][0]
    dataset["pseudo_labeled"] = True
    dataset["producer_model_id"] = "model:ink-v1"

    report = validate_manifest(manifest)

    assert "GP_CHECKPOINT_LICENSE" in _codes(report)



def test_each_model_requires_held_out_validation():
    manifest = _manifest()
    manifest["held_out_validations"] = []

    report = validate_manifest(manifest)

    assert "GP_HELD_OUT_VALIDATION" in _codes(report)


def test_training_holdout_overlap_is_detected():
    manifest = _manifest()
    train = manifest["region_sets"][0]
    train["volume_id"] = "public-validation-volume"
    train["boxes"] = [
        {
            "start": [205, 205, 205],
            "stop": [220, 220, 220],
        }
    ]

    report = validate_manifest(manifest)

    assert "GP_TRAIN_HOLDOUT_OVERLAP" in _codes(report)
    proof = report["held_out_validation_proofs"][0]
    assert proof["checked_pairs"] == 1
    assert len(proof["overlaps"]) == 1


def test_held_out_validation_requires_public_ground_truth_metrics_and_run():
    manifest = _manifest()
    validation = manifest["held_out_validations"][0]
    validation["ground_truth_url"] = "private://ground-truth"
    validation["metrics"] = {}
    validation["experiment_run"]["public"] = False

    report = validate_manifest(manifest)

    assert {
        "GP_HELD_OUT_GROUND_TRUTH_PUBLIC",
        "GP_HELD_OUT_METRICS",
        "GP_HELD_OUT_RUN",
    } <= _codes(report)


def test_k_fold_validation_requires_fold_count():
    manifest = _manifest()
    validation = manifest["held_out_validations"][0]
    validation["protocol"] = "k-fold"

    report = validate_manifest(manifest)

    assert "GP_HELD_OUT_PROTOCOL" in _codes(report)



def test_recto_coverage_is_required():
    manifest = _manifest()
    del manifest["recto_coverage"]

    report = validate_manifest(manifest)

    assert "GP_RECTO_COVERAGE" in _codes(report)


def test_recto_coverage_must_bind_exact_package_mesh_set():
    manifest = _manifest()
    manifest["recto_coverage"]["components"][0]["mesh_ids"] = [
        "mesh:not-in-package"
    ]

    report = validate_manifest(manifest)

    assert "GP_RECTO_MESH_SET" in _codes(report)


def test_recto_coverage_must_pin_submission_commit():
    manifest = _manifest()
    manifest["recto_coverage"]["generated_by"]["code_commit"] = "b" * 40

    report = validate_manifest(manifest)

    assert "GP_RECTO_COMMIT" in _codes(report)


def test_recto_coverage_failure_propagates_into_provenance_gate():
    manifest = _manifest()
    manifest["recto_coverage"]["components"] = [
        {
            "id": "outer-only",
            "kind": "disconnected-outer-patch",
            "area": 100.0,
            "unrolled": False,
            "excluded": True,
            "mesh_ids": [],
            "exclusion_reason": "invalid full exclusion",
        }
    ]

    report = validate_manifest(manifest)

    assert "GP_RECTO_COVERAGE" in _codes(report)
    assert "GP_RECTO_MESH_SET" in _codes(report)
