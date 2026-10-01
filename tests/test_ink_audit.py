from scrollq.ink_audit import audit_ink_manifest


def _manifest():
    return {
        "volume_root": "volume-A",
        "model": {
            "checkpoint": "models/fold-0.ckpt",
            "checkpoint_sha256": "a" * 64,
        },
        "seeds": [7, 11],
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
    }


def test_complete_nonoverlapping_manifest_passes():
    result = audit_ink_manifest(_manifest(), expected_volume_root="volume-A")

    assert result["status"] == "pass"
    assert result["leakage"]["status"] == "pass"
    assert result["leakage"]["spatial_overlap_count"] == 0
    assert result["controls"]["complete"] is True
    assert result["runs"]["missing_evaluation_region_ids"] == []


def test_training_evaluation_overlap_fails_closed():
    manifest = _manifest()
    manifest["evaluation_regions"][0]["bbox_zyx_half_open"] = [[5, 5, 5], [15, 15, 15]]

    result = audit_ink_manifest(manifest)

    assert result["status"] == "fail"
    assert result["leakage"]["spatial_overlap_count"] == 1
    overlap = result["leakage"]["overlaps"][0]
    assert overlap["overlap_extent_zyx"] == [5.0, 5.0, 5.0]
    assert overlap["overlap_volume_voxels3"] == 125.0


def test_missing_falsification_controls_are_partial_not_invented():
    manifest = _manifest()
    manifest["controls"] = {"normal_offsets_voxels": [0]}

    result = audit_ink_manifest(manifest)

    assert result["status"] == "partial"
    assert result["leakage"]["status"] == "pass"
    assert -3.0 in result["controls"]["missing_normal_offsets_voxels"]
    assert result["controls"]["adjacent_winding"] is False


def test_exact_volume_binding_fails_closed():
    result = audit_ink_manifest(_manifest(), expected_volume_root="volume-B")

    assert result["status"] == "fail"
    assert any("does not match" in message for message in result["errors"])



def test_manifest_must_evaluate_the_bound_volume():
    manifest = _manifest()
    manifest["evaluation_regions"][0]["volume_root"] = "volume-B"

    result = audit_ink_manifest(manifest)

    assert result["status"] == "fail"
    assert any("no evaluation region is bound" in message for message in result["errors"])


def test_malformed_run_checkpoint_hash_stays_visible():
    manifest = _manifest()
    manifest["runs"][0]["checkpoint_sha256"] = "not-a-hash"

    result = audit_ink_manifest(manifest)

    assert result["status"] == "partial"
    assert any("valid checkpoint_sha256" in message for message in result["warnings"])
