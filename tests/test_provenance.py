import copy
import hashlib

from scrollq.provenance import validate_manifest


def _manifest():
    return {
        "schema_version": 1,
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
