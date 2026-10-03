import copy
import hashlib
import json

from scrollq.package_hash import sha256_path
from scrollq.provenance import validate_manifest


def _manifest():
    return {
        "schema_version": 6,
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
                "path": "zpa-report.json",
                "sha256": "c" * 64,
                "root": "PHerc0813/volumes/20250821151723.zarr",
                "integrity": "PASS",
                "source_attestation": {
                    "algorithm": "zpa-metadata-semantics-v1",
                    "state": "PRESENT",
                    "metadata_semantics_sha256": "5" * 64,
                    "axes": ["z", "y", "x"],
                },
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
                "input_contract": {
                    "axes": ["z", "y", "x"],
                    "source_voxel_size_um": 9.362,
                    "model_voxel_size_um": 9.362,
                    "resampling": "none",
                    "window_voxels_zyx": [17, 64, 64],
                    "preprocessing_profile": {
                        "public_url": "https://example.org/models/ink-v1/preprocessing.json",
                        "sha256": "6" * 64,
                    },
                },
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
                "scale_proof": {
                    "tool": "scroliq-submission-image",
                    "path": "column_01.scale.json",
                    "sha256": "7" * 64,
                    "base_voxel_size_um": 9.362,
                    "group_idx": 0,
                    "render_scale": 1.0,
                    "micrometers_per_output_pixel": 9.362,
                    "scale_bar_pixels": 1068,
                },
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
                "ink_evidence": {
                    "tool": "scroliq-ink-validate",
                    "model_checkpoint_sha256": "d" * 64,
                    "split_id": "public-held-out-1",
                    "held_out": True,
                    "training_overlap": "none",
                    "known_ground_truth": True,
                    "ground_truth_source_url": (
                        "https://example.org/validation/ground-truth"
                    ),
                    "model_window_voxels_zyx": [17, 64, 64],
                    "control_names": ["normal-plus-3"],
                    "evaluated_arrays_sha256": "4" * 64,
                    "metrics": {
                        "balanced_accuracy": 0.9,
                        "false_positive_rate": 0.05,
                        "both_classes_present": True,
                    },
                },
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
            "proof": {
                "tool": "scroliq-submission-image",
                "path": "banner.proof.json",
                "sha256": "8" * 64,
            },
        },
    }


def _codes(report):
    return {item["code"] for item in report["errors"]}


def _ink_report(manifest):
    evidence = manifest["held_out_validations"][0]["ink_evidence"]
    return {
        "schema_version": 1,
        "tool": "scroliq-ink-validate",
        "purpose": "held-out ink signal recovery / false-positive evidence",
        "split": {
            "id": evidence["split_id"],
            "held_out": True,
            "training_overlap": "none",
            "known_ground_truth": True,
            "ground_truth_source_url": evidence["ground_truth_source_url"],
        },
        "model": {
            "checkpoint_sha256": evidence["model_checkpoint_sha256"],
            "window_voxels_zyx": evidence["model_window_voxels_zyx"],
        },
        "evaluation": dict(evidence["metrics"]),
        "controls": [
            {"name": name, "metrics": {}}
            for name in evidence["control_names"]
        ],
        "evaluated_arrays_sha256": evidence["evaluated_arrays_sha256"],
        "prize_evidence_ready": True,
        "readiness_reasons": [],
    }


def _zpa_report(manifest):
    audit = manifest["ct_volume"]["zarr_audit"]
    attestation = audit["source_attestation"]
    return {
        "schema_version": "1.3.0",
        "tool": "zarr-pyramid-audit",
        "tool_version": "0.4.0",
        "root": audit["root"],
        "kind": "pyramid",
        "zarr_format": 3,
        "evidence": {"state": "PRESENT", "reason": None},
        "source_attestation": {
            "algorithm": attestation["algorithm"],
            "state": attestation["state"],
            "metadata_semantics_sha256": attestation[
                "metadata_semantics_sha256"
            ],
            "axes": list(attestation["axes"]),
            "base_declared_scale": [9.362, 9.362, 9.362],
            "absolute_scale_state": "unspecified",
            "spatial_axes": [
                {"index": 0, "name": "z", "unit": "micrometer"},
                {"index": 1, "name": "y", "unit": "micrometer"},
                {"index": 2, "name": "x", "unit": "micrometer"},
            ],
        },
        "integrity": "PASS",
        "max_severity": "none",
        "coverage": {
            "levels_declared": 1,
            "levels_present": 1,
            "levels_unknown": 0,
            "chunk_presence": {"PRESENT": 1, "ABSENT": 0, "UNKNOWN": 0},
        },
        "levels": [
            {
                "path": "0",
                "index": 0,
                "present": True,
                "evidence_state": "PRESENT",
                "evidence_reason": None,
                "shape": [10, 10, 10],
                "chunks": [5, 5, 5],
                "dtype": "uint16",
                "declared_scale": [9.362, 9.362, 9.362],
                "zarr_format": 3,
                "has_chunks": True,
                "chunk_evidence_state": "PRESENT",
                "chunk_evidence_reason": None,
            }
        ],
        "findings": [],
    }


def _write_submission_image_proofs(tmp_path, manifest):
    render = manifest["renders"][0]
    scale = render["scale_proof"]
    scale_payload = {
        "schema_version": 1,
        "tool": "scroliq-submission-image",
        "operation": "column",
        "column": render["column"],
        "input": {
            "path": "column_01.raw.tif",
            "sha256": "0" * 64,
            "size_xy": [1200, 100],
        },
        "output": {
            "path": "column_01.tif",
            "sha256": render["sha256"],
            "size_xy": [1200, 148],
        },
        "vc_render_tifxyz": {
            "base_voxel_size_um": scale["base_voxel_size_um"],
            "group_idx": scale["group_idx"],
            "render_scale": scale["render_scale"],
            "ds_scale": 1.0,
            "micrometers_per_output_pixel": scale[
                "micrometers_per_output_pixel"
            ],
            "formula": (
                "base_voxel_size_um / (2**-group_idx) / render_scale"
            ),
        },
        "scale_bar": {
            "centimeters": 1,
            "micrometers": 10000,
            "pixels": scale["scale_bar_pixels"],
            "x": 16,
            "y": 112,
            "thickness": 4,
            "footer_height": 48,
        },
    }
    scale_bytes = json.dumps(scale_payload, sort_keys=True).encode("utf-8")
    (tmp_path / scale["path"]).write_bytes(scale_bytes)
    scale["sha256"] = hashlib.sha256(scale_bytes).hexdigest()

    banner = manifest["banner"]
    banner_payload = {
        "schema_version": 1,
        "tool": "scroliq-submission-image",
        "operation": "banner",
        "columns": [
            {
                "column": render["column"],
                "path": "column_01.tif",
                "sha256": render["sha256"],
                "banner_x": 0,
                "display_size_xy": [1200, 148],
                "display_scale": 1.0,
            }
        ],
        "column_numbers_overlaid": True,
        "output": {
            "path": "banner.tif",
            "sha256": banner["sha256"],
            "size_xy": [1200, 176],
        },
        "max_column_height": 1200,
        "label_height": 28,
        "gap": 8,
    }
    banner_bytes = json.dumps(banner_payload, sort_keys=True).encode("utf-8")
    (tmp_path / banner["proof"]["path"]).write_bytes(banner_bytes)
    banner["proof"]["sha256"] = hashlib.sha256(banner_bytes).hexdigest()


def _write_zpa_report(tmp_path, manifest):
    payload = json.dumps(_zpa_report(manifest), sort_keys=True).encode("utf-8")
    (tmp_path / "zpa-report.json").write_bytes(payload)
    manifest["ct_volume"]["zarr_audit"]["sha256"] = hashlib.sha256(
        payload
    ).hexdigest()
    if (tmp_path / "column_01.tif").is_file() and (tmp_path / "banner.tif").is_file():
        _write_submission_image_proofs(tmp_path, manifest)
    return payload


def _write_local_mesh(tmp_path, manifest, *, target_volume=None, scroll_source=None):
    mesh_dir = tmp_path / "column_01.tifxyz"
    mesh_dir.mkdir(exist_ok=True)
    meta = {
        "format": "tifxyz",
        "scale": [1.0, 1.0],
        "bbox": [[0, 0, 0], [1, 1, 1]],
        "source": "vc_grow_seg_from_seed",
        "target_volume": (
            target_volume
            if target_volume is not None
            else manifest["submission"]["eligible_volume_id"] + ".zarr"
        ),
        "scroll_source": (
            scroll_source
            if scroll_source is not None
            else manifest["submission"]["scroll_id"]
        ),
    }
    (mesh_dir / "meta.json").write_text(
        json.dumps(meta, sort_keys=True), encoding="utf-8"
    )
    for channel in "xyz":
        path = mesh_dir / f"{channel}.tif"
        if not path.exists():
            path.write_bytes(channel.encode("ascii"))
    manifest["meshes"][0]["sha256"] = sha256_path(mesh_dir)
    return mesh_dir


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


def test_scale_proof_must_match_eligible_voxel_and_true_bar_length():
    manifest = _manifest()
    proof = manifest["renders"][0]["scale_proof"]
    proof["base_voxel_size_um"] = 8.64
    proof["scale_bar_pixels"] = 999

    report = validate_manifest(manifest)

    assert "GP_SCALE_PROOF_VOXEL" in _codes(report)
    assert "GP_SCALE_PROOF_PIXELS" in _codes(report)


def test_scale_proof_physical_spacing_must_match_vc3d_formula():
    manifest = _manifest()
    manifest["renders"][0]["scale_proof"][
        "micrometers_per_output_pixel"
    ] = 10.0

    report = validate_manifest(manifest)

    assert "GP_SCALE_PROOF_PIXEL_SIZE" in _codes(report)


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


def test_model_source_voxel_must_match_eligible_volume():
    manifest = _manifest()
    manifest["models"][0]["input_contract"]["source_voxel_size_um"] = 9.0

    report = validate_manifest(manifest)

    assert "GP_MODEL_SOURCE_VOXEL" in _codes(report)


def test_model_axes_must_match_audited_source():
    manifest = _manifest()
    manifest["models"][0]["input_contract"]["axes"] = ["x", "y", "z"]

    report = validate_manifest(manifest)

    assert "GP_MODEL_INPUT_AXES" in _codes(report)


def test_held_out_window_must_match_model_contract():
    manifest = _manifest()
    manifest["models"][0]["input_contract"]["window_voxels_zyx"] = [9, 32, 32]

    report = validate_manifest(manifest)

    assert "GP_INK_EVIDENCE_WINDOW" in _codes(report)


def test_local_zpa_attestation_mismatch_fails_closed(tmp_path):
    manifest = _manifest()
    report_payload = _zpa_report(manifest)
    report_payload["source_attestation"]["metadata_semantics_sha256"] = "9" * 64
    payload = json.dumps(report_payload, sort_keys=True).encode("utf-8")
    (tmp_path / "zpa-report.json").write_bytes(payload)
    manifest["ct_volume"]["zarr_audit"]["sha256"] = hashlib.sha256(
        payload
    ).hexdigest()

    result = validate_manifest(manifest, root_dir=tmp_path)

    assert "GP_CT_SOURCE_ATTESTATION_MISMATCH" in _codes(result)


def test_package_file_hashes_are_verified(tmp_path):
    manifest = _manifest()
    payloads = {
        "column_01.tif": b"render",
        "banner.tif": b"banner",
        "held_out_validation.json": (
            json.dumps(_ink_report(manifest), sort_keys=True).encode("utf-8")
        ),
    }
    for name, payload in payloads.items():
        (tmp_path / name).write_bytes(payload)
    _write_local_mesh(tmp_path, manifest)

    manifest["renders"][0]["sha256"] = hashlib.sha256(
        payloads["column_01.tif"]
    ).hexdigest()
    manifest["banner"]["sha256"] = hashlib.sha256(
        payloads["banner.tif"]
    ).hexdigest()
    manifest["held_out_validations"][0]["sha256"] = hashlib.sha256(
        payloads["held_out_validation.json"]
    ).hexdigest()
    _write_zpa_report(tmp_path, manifest)

    report = validate_manifest(manifest, root_dir=tmp_path)
    assert report["eligible"] is True

    (tmp_path / "column_01.tif").write_bytes(b"tampered")
    report = validate_manifest(manifest, root_dir=tmp_path)
    assert "GP_HASH_MISMATCH" in _codes(report)


def test_local_submission_image_proofs_bind_exact_render_and_banner(tmp_path):
    manifest = _manifest()
    payloads = {
        "column_01.tif": b"render",
        "banner.tif": b"banner",
        "held_out_validation.json": (
            json.dumps(_ink_report(manifest), sort_keys=True).encode("utf-8")
        ),
    }
    for name, payload in payloads.items():
        (tmp_path / name).write_bytes(payload)
    _write_local_mesh(tmp_path, manifest)
    manifest["renders"][0]["sha256"] = hashlib.sha256(
        payloads["column_01.tif"]
    ).hexdigest()
    manifest["banner"]["sha256"] = hashlib.sha256(
        payloads["banner.tif"]
    ).hexdigest()
    manifest["held_out_validations"][0]["sha256"] = hashlib.sha256(
        payloads["held_out_validation.json"]
    ).hexdigest()
    _write_zpa_report(tmp_path, manifest)

    report = validate_manifest(manifest, root_dir=tmp_path)

    assert report["eligible"] is True
    assert report["scale_proofs"][0]["artifact_checked"] is True
    assert report["banner_proof"]["artifact_checked"] is True


def test_local_scale_proof_rejects_render_substitution(tmp_path):
    manifest = _manifest()
    payloads = {
        "column_01.tif": b"render",
        "banner.tif": b"banner",
        "held_out_validation.json": (
            json.dumps(_ink_report(manifest), sort_keys=True).encode("utf-8")
        ),
    }
    for name, payload in payloads.items():
        (tmp_path / name).write_bytes(payload)
    _write_local_mesh(tmp_path, manifest)
    manifest["renders"][0]["sha256"] = hashlib.sha256(b"render").hexdigest()
    manifest["banner"]["sha256"] = hashlib.sha256(b"banner").hexdigest()
    manifest["held_out_validations"][0]["sha256"] = hashlib.sha256(
        payloads["held_out_validation.json"]
    ).hexdigest()
    _write_zpa_report(tmp_path, manifest)

    scale_path = tmp_path / manifest["renders"][0]["scale_proof"]["path"]
    payload = json.loads(scale_path.read_text(encoding="utf-8"))
    payload["output"]["sha256"] = "9" * 64
    tampered = json.dumps(payload, sort_keys=True).encode("utf-8")
    scale_path.write_bytes(tampered)
    manifest["renders"][0]["scale_proof"]["sha256"] = hashlib.sha256(
        tampered
    ).hexdigest()

    report = validate_manifest(manifest, root_dir=tmp_path)

    assert "GP_SCALE_PROOF_MISMATCH" in _codes(report)


def test_local_banner_proof_rejects_wrong_render_set(tmp_path):
    manifest = _manifest()
    payloads = {
        "column_01.tif": b"render",
        "banner.tif": b"banner",
        "held_out_validation.json": (
            json.dumps(_ink_report(manifest), sort_keys=True).encode("utf-8")
        ),
    }
    for name, payload in payloads.items():
        (tmp_path / name).write_bytes(payload)
    _write_local_mesh(tmp_path, manifest)
    manifest["renders"][0]["sha256"] = hashlib.sha256(b"render").hexdigest()
    manifest["banner"]["sha256"] = hashlib.sha256(b"banner").hexdigest()
    manifest["held_out_validations"][0]["sha256"] = hashlib.sha256(
        payloads["held_out_validation.json"]
    ).hexdigest()
    _write_zpa_report(tmp_path, manifest)

    proof_path = tmp_path / manifest["banner"]["proof"]["path"]
    payload = json.loads(proof_path.read_text(encoding="utf-8"))
    payload["columns"][0]["sha256"] = "9" * 64
    tampered = json.dumps(payload, sort_keys=True).encode("utf-8")
    proof_path.write_bytes(tampered)
    manifest["banner"]["proof"]["sha256"] = hashlib.sha256(
        tampered
    ).hexdigest()

    report = validate_manifest(manifest, root_dir=tmp_path)

    assert "GP_BANNER_PROOF_MISMATCH" in _codes(report)


def test_local_vc3d_target_context_is_bound_to_eligible_volume(tmp_path):
    manifest = _manifest()
    payloads = {
        "column_01.tif": b"render",
        "banner.tif": b"banner",
        "held_out_validation.json": (
            json.dumps(_ink_report(manifest), sort_keys=True).encode("utf-8")
        ),
    }
    for name, payload in payloads.items():
        (tmp_path / name).write_bytes(payload)
    mesh_dir = _write_local_mesh(tmp_path, manifest)
    manifest["renders"][0]["sha256"] = hashlib.sha256(
        payloads["column_01.tif"]
    ).hexdigest()
    manifest["banner"]["sha256"] = hashlib.sha256(
        payloads["banner.tif"]
    ).hexdigest()
    manifest["held_out_validations"][0]["sha256"] = hashlib.sha256(
        payloads["held_out_validation.json"]
    ).hexdigest()
    _write_zpa_report(tmp_path, manifest)

    report = validate_manifest(manifest, root_dir=tmp_path)

    assert report["eligible"] is True
    proof = report["mesh_context_proofs"][0]
    assert proof["checked"] is True
    assert proof["target_volume"] == "20250821151723.zarr"
    assert proof["scroll_source"] == "PHerc0813"
    assert proof["source"] == "vc_grow_seg_from_seed"
    assert proof["meta_sha256"] == hashlib.sha256(
        (mesh_dir / "meta.json").read_bytes()
    ).hexdigest()


def test_local_vc3d_wrong_target_volume_fails_closed(tmp_path):
    manifest = _manifest()
    payloads = {
        "column_01.tif": b"render",
        "banner.tif": b"banner",
        "held_out_validation.json": (
            json.dumps(_ink_report(manifest), sort_keys=True).encode("utf-8")
        ),
    }
    for name, payload in payloads.items():
        (tmp_path / name).write_bytes(payload)
    _write_local_mesh(tmp_path, manifest, target_volume="wrong-volume.zarr")
    manifest["renders"][0]["sha256"] = hashlib.sha256(
        payloads["column_01.tif"]
    ).hexdigest()
    manifest["banner"]["sha256"] = hashlib.sha256(
        payloads["banner.tif"]
    ).hexdigest()
    manifest["held_out_validations"][0]["sha256"] = hashlib.sha256(
        payloads["held_out_validation.json"]
    ).hexdigest()
    _write_zpa_report(tmp_path, manifest)

    report = validate_manifest(manifest, root_dir=tmp_path)

    assert report["eligible"] is False
    assert "GP_MESH_TARGET_VOLUME" in _codes(report)


def test_tifxyz_directory_tree_hash_is_verified(tmp_path):
    manifest = _manifest()
    mesh_dir = _write_local_mesh(tmp_path, manifest)

    ink_payload = json.dumps(_ink_report(manifest), sort_keys=True).encode("utf-8")
    payloads = {
        "column_01.tif": b"render",
        "banner.tif": b"banner",
        "held_out_validation.json": ink_payload,
    }
    for name, payload in payloads.items():
        (tmp_path / name).write_bytes(payload)

    manifest["meshes"][0]["sha256"] = sha256_path(mesh_dir)
    manifest["renders"][0]["sha256"] = hashlib.sha256(
        payloads["column_01.tif"]
    ).hexdigest()
    manifest["banner"]["sha256"] = hashlib.sha256(
        payloads["banner.tif"]
    ).hexdigest()
    manifest["held_out_validations"][0]["sha256"] = hashlib.sha256(
        ink_payload
    ).hexdigest()
    _write_zpa_report(tmp_path, manifest)

    report = validate_manifest(manifest, root_dir=tmp_path)
    assert report["eligible"] is True

    (mesh_dir / "x.tif").write_bytes(b"tampered")
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



def test_held_out_validation_requires_deterministic_ink_evidence():
    manifest = _manifest()
    del manifest["held_out_validations"][0]["ink_evidence"]

    report = validate_manifest(manifest)

    assert "GP_INK_EVIDENCE" in _codes(report)


def test_ink_evidence_checkpoint_must_match_submitted_model():
    manifest = _manifest()
    evidence = manifest["held_out_validations"][0]["ink_evidence"]
    evidence["model_checkpoint_sha256"] = "9" * 64

    report = validate_manifest(manifest)

    assert "GP_INK_EVIDENCE_CHECKPOINT" in _codes(report)


def test_ink_evidence_requires_no_overlap_controls_and_both_classes():
    manifest = _manifest()
    evidence = manifest["held_out_validations"][0]["ink_evidence"]
    evidence["training_overlap"] = "unknown"
    evidence["control_names"] = []
    evidence["metrics"]["both_classes_present"] = False

    report = validate_manifest(manifest)

    assert {
        "GP_INK_EVIDENCE_OVERLAP",
        "GP_INK_EVIDENCE_CONTROLS",
        "GP_INK_EVIDENCE_CLASSES",
    } <= _codes(report)


def test_local_ink_report_mismatch_fails_closed(tmp_path):
    manifest = _manifest()
    report_payload = _ink_report(manifest)
    report_payload["model"]["window_voxels_zyx"] = [99, 99, 99]
    payload = json.dumps(report_payload, sort_keys=True).encode("utf-8")

    for name, data in {
        "column_01.tif": b"render",
        "banner.tif": b"banner",
        "held_out_validation.json": payload,
    }.items():
        (tmp_path / name).write_bytes(data)
    _write_local_mesh(tmp_path, manifest)

    manifest["renders"][0]["sha256"] = hashlib.sha256(b"render").hexdigest()
    manifest["banner"]["sha256"] = hashlib.sha256(b"banner").hexdigest()
    manifest["held_out_validations"][0]["sha256"] = hashlib.sha256(
        payload
    ).hexdigest()
    _write_zpa_report(tmp_path, manifest)

    result = validate_manifest(manifest, root_dir=tmp_path)

    assert "GP_INK_EVIDENCE_MISMATCH" in _codes(result)


def test_published_example_manifest_validates_under_current_schema():
    """examples/grand-prize-provenance.example.json is what the docs point
    people at; it must pass the current schema, not a retired one."""
    import json
    from pathlib import Path

    from scrollq.provenance import SCHEMA_VERSION, validate_manifest

    path = (Path(__file__).resolve().parents[1] / "examples"
            / "grand-prize-provenance.example.json")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == SCHEMA_VERSION
    assert validate_manifest(manifest)["errors"] == []
