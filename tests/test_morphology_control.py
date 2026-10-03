import json

from scrollq.morphology_control import audit_morphology_manifest, main


def _manifest(mode="source_benchmark"):
    out = {
        "schema_version": 1,
        "mode": mode,
        "source": {
            "dataset_id": "scrollprize/profilometer",
            "revision": "a806bead2f3b9100c20e19de37814fb285cfeefd",
            "dataset_license": "CC BY-NC 4.0",
            "dataset_license_evidence": (
                "https://huggingface.co/datasets/scrollprize/profilometer/blob/"
                "a806bead2f3b9100c20e19de37814fb285cfeefd/LICENSE"
            ),
            "paper_url": "https://doi.org/10.1038/s41598-026-58467-1",
            "paper_license": "CC BY-NC-ND 4.0",
            "paper_license_evidence": (
                "https://www.nature.com/articles/s41598-026-58467-1_reference.pdf"
            ),
            "source_papyri": ["PHerc. 248", "PHerc. 250", "PHerc. 500P2"],
        },
        "sampling": {
            "dataset_native_um_xy": [0.68793625, 0.68793625],
            "manuscript_native_um_xy": [0.34, 0.34],
            "discrepancy_status": "unresolved",
        },
        "design": {
            "descriptors": [
                "local-gradient-rank",
                "curvature-rank",
                "fiber-relative-roughness",
            ],
            "source_split": "leave-one-papyrus-out",
            "learned_classifier": False,
            "source_labels_used_for_target_training": False,
            "paper_adapted_material_in_repo": False,
            "missingness_mask_control": True,
            "label_permutation_control": True,
            "uses_absolute_micron_thresholds": False,
        },
    }
    if mode == "target_control":
        out["target"] = {
            "volume_root": "PHerc0813/volumes/exact.zarr",
            "ink_manifest_sha256": "b" * 64,
            "source_benchmark_artifact_sha256": "c" * 64,
            "evaluation_region_ids": ["held-1"],
        }
        out["selection_contract"] = {
            "target_regions_frozen_before_descriptor_evaluation": True,
            "ink_model_or_ocr_used_to_select_target_regions": False,
            "candidate_render_used_to_tune_descriptors": False,
        }
    return out


def test_source_benchmark_is_partial_while_sampling_discrepancy_is_unresolved():
    result = audit_morphology_manifest(_manifest())
    assert result["status"] == "partial"
    assert result["transfer_authorized"] is False
    assert any("sampling discrepancy" in msg for msg in result["warnings"])


def test_absolute_scale_is_forbidden_while_sampling_discrepancy_is_unresolved():
    manifest = _manifest()
    manifest["design"]["uses_absolute_micron_thresholds"] = True
    result = audit_morphology_manifest(manifest)
    assert result["status"] == "fail"
    assert any("absolute micron thresholds" in msg for msg in result["errors"])


def test_leave_one_papyrus_out_is_required():
    manifest = _manifest()
    manifest["design"]["source_split"] = "random-pixels"
    result = audit_morphology_manifest(manifest)
    assert result["status"] == "fail"
    assert any("leave-one-papyrus-out" in msg for msg in result["errors"])


def test_no_derivatives_paper_material_cannot_be_adapted_into_repo():
    manifest = _manifest()
    manifest["design"]["paper_adapted_material_in_repo"] = True
    result = audit_morphology_manifest(manifest)
    assert result["status"] == "fail"
    assert any("no-derivatives" in msg for msg in result["errors"])


def test_target_transfer_is_blocked_until_sampling_discrepancy_is_resolved():
    result = audit_morphology_manifest(_manifest("target_control"))
    assert result["status"] == "fail"
    assert result["transfer_authorized"] is False
    assert any("target_control is blocked" in msg for msg in result["errors"])


def test_target_transfer_requires_completed_source_benchmark_and_frozen_regions():
    manifest = _manifest("target_control")
    manifest["sampling"]["discrepancy_status"] = "resolved"
    manifest["target"]["source_benchmark_artifact_sha256"] = "nope"
    manifest["selection_contract"]["ink_model_or_ocr_used_to_select_target_regions"] = True
    result = audit_morphology_manifest(manifest)
    assert result["status"] == "fail"
    joined = " | ".join(result["errors"])
    assert "completed source benchmark" in joined
    assert "ink_model_or_ocr_used_to_select_target_regions must be false" in joined


def test_resolved_target_control_can_pass_with_all_bindings():
    manifest = _manifest("target_control")
    manifest["sampling"]["discrepancy_status"] = "resolved"
    result = audit_morphology_manifest(manifest)
    assert result["status"] == "pass"
    assert result["transfer_authorized"] is True


def test_cli_refuses_overwrite_and_partial_returns_one(tmp_path, capsys):
    manifest = tmp_path / "manifest.json"
    out = tmp_path / "audit.json"
    manifest.write_text(json.dumps(_manifest()), encoding="utf-8")
    assert main(["--manifest", str(manifest), "--out", str(out)]) == 1
    result = json.loads(out.read_text(encoding="utf-8"))
    assert result["status"] == "partial"
    before = out.read_bytes()
    assert main(["--manifest", str(manifest), "--out", str(out)]) == 2
    assert out.read_bytes() == before
    assert "refusing to overwrite" in capsys.readouterr().out
