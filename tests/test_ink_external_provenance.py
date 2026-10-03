from scrollq.ink_audit import audit_ink_manifest


def _manifest():
    return {
        "volume_root": "volume-A",
        "model": {
            "checkpoint": "models/fold-0.ckpt",
            "checkpoint_sha256": "a" * 64,
        },
        "seeds": [7],
        "training_regions": [
            {
                "id": "train-1",
                "volume_root": "volume-A",
                "bbox_zyx_half_open": [[0, 0, 0], [10, 10, 10]],
                "split": "train",
            }
        ],
        "evaluation_regions": [
            {
                "id": "eval-1",
                "volume_root": "volume-A",
                "bbox_zyx_half_open": [[20, 20, 20], [30, 30, 30]],
                "split": "held_out",
            }
        ],
        "controls": {
            "normal_offsets_voxels": [-3, 0, 3],
            "adjacent_winding": True,
            "geometry_perturbation": True,
            "independent_checkpoint": True,
        },
        "runs": [
            {
                "evaluation_region_id": "eval-1",
                "seed": 7,
                "checkpoint_sha256": "a" * 64,
            }
        ],
        "external_method": {
            "repository": "public/example",
            "revision": "1" * 40,
            "code_license": "MIT",
            "checkpoint_license": "MIT",
            "license_evidence": [
                "https://example.org/code-license",
                "https://example.org/checkpoint-license",
            ],
            "data_license": "CC-BY-NC 4.0",
            "data_license_evidence": "https://example.org/data-license",
            "intended_use_permitted": True,
            "grand_prize_role": "control_only",
            "inference_only": True,
            "uses_pseudolabel_training": False,
            "experiment_tracking_public": True,
        },
        "selection_contract": {
            "evaluation_regions_frozen_before_candidate_inference": True,
            "ocr_or_legibility_used_for_selection": False,
            "candidate_output_used_to_choose_evaluation_regions": False,
        },
    }


def test_external_method_provenance_and_selection_contract_can_pass():
    result = audit_ink_manifest(_manifest())
    assert result["status"] == "pass"
    assert result["external_method"]["revision"] == "1" * 40
    assert result["external_method"]["grand_prize_role"] == "control_only"


def test_external_method_cannot_choose_its_own_evaluation_regions():
    manifest = _manifest()
    manifest["selection_contract"][
        "candidate_output_used_to_choose_evaluation_regions"
    ] = True
    result = audit_ink_manifest(manifest)
    assert result["status"] == "fail"
    assert any(
        "candidate_output_used_to_choose_evaluation_regions must be false"
        in message
        for message in result["errors"]
    )


def test_pseudolabel_method_fails_without_public_stage_provenance():
    manifest = _manifest()
    manifest["external_method"]["uses_pseudolabel_training"] = True
    manifest["external_method"]["experiment_tracking_public"] = False
    result = audit_ink_manifest(manifest)
    assert result["status"] == "fail"
    joined = " | ".join(result["errors"])
    assert "all_training_data_public=true" in joined
    assert "training_data_license=CC-BY-NC 4.0" in joined
    assert "all_intermediate_checkpoints_public=true" in joined
    assert "intermediate_checkpoint_license=CC-BY-NC 4.0" in joined
    assert "experiment_tracking_public=true" in joined


def test_missing_public_training_tracking_remains_visible_for_non_pseudolabel_model():
    manifest = _manifest()
    manifest["external_method"].pop("experiment_tracking_public")
    result = audit_ink_manifest(manifest)
    assert result["status"] == "partial"
    assert any(
        "public experiment tracking" in message for message in result["warnings"]
    )
