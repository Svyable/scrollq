import numpy as np
import pytest

from scrollq.normal_response import (
    REQUIRED_OFFSETS_VOXELS,
    build_report,
    evaluate_normal_response,
    main,
)


def _arrays():
    labels = np.array(
        [
            [1, 0, 1, 0],
            [1, 0, 1, 0],
            [0, 0, 0, 0],
            [0, 0, 0, 0],
        ],
        dtype=np.uint8,
    )
    prediction = np.array(
        [
            [0.9, 0.8, 0.85, 0.2],
            [0.8, 0.2, 0.75, 0.1],
            [0.1, 0.2, 0.3, 0.4],
            [0.2, 0.1, 0.2, 0.1],
        ],
        dtype=np.float32,
    )
    mask = np.ones_like(labels)
    offsets = {}
    for offset in REQUIRED_OFFSETS_VOXELS:
        arr = prediction.copy()
        arr[labels > 0] = np.maximum(arr[labels > 0] - 0.35, 0.0)
        arr[labels == 0] = np.minimum(arr[labels == 0] + 0.1, 1.0)
        offsets[offset] = arr
    return prediction, labels, mask, offsets


def _report_kwargs():
    return {
        "threshold": 0.5,
        "split_id": "fold-1",
        "held_out": True,
        "training_overlap": "none",
        "ground_truth_source_url": "https://example.org/public-ground-truth",
        "model_checkpoint_sha256": "a" * 64,
        "model_window_voxels": (17, 64, 64),
        "surface_geometry_sha256": "b" * 64,
        "sampling_manifest_sha256": "c" * 64,
    }


def test_protocol_localizes_true_ink_and_rejects_background_false_positive():
    prediction, labels, mask, offsets = _arrays()
    result = evaluate_normal_response(
        prediction, labels, mask, offsets, threshold=0.5
    )

    assert result["protocol_conformant"] is True
    assert result["localization"]["strict_zero_peak_fraction"]["ink"] == 1.0
    assert result["localization"]["strict_zero_peak_fraction"]["background"] == 0.0
    assert result["primary_evaluation"]["false_positive_rate"] > 0.0
    assert result["center_win_gate"]["evaluation"]["false_positive_rate"] == 0.0
    assert result["center_win_gate"]["evaluation"]["recall"] == 1.0


def test_flat_response_does_not_count_ties_as_surface_localized():
    prediction, labels, mask, _ = _arrays()
    offsets = {offset: prediction.copy() for offset in REQUIRED_OFFSETS_VOXELS}

    result = evaluate_normal_response(prediction, labels, mask, offsets)

    assert result["localization"]["strict_zero_peak_fraction"]["ink"] == 0.0
    assert result["localization"]["strict_zero_peak_fraction"]["background"] == 0.0
    assert result["center_win_gate"]["evaluation"]["recall"] == 0.0


def test_partial_grid_is_measured_but_not_protocol_conformant():
    prediction, labels, mask, offsets = _arrays()
    offsets.pop(6)

    result = evaluate_normal_response(prediction, labels, mask, offsets)

    assert result["protocol_conformant"] is False
    assert result["missing_offsets_voxels"] == [6]


def test_report_fail_closes_on_partial_grid():
    prediction, labels, mask, offsets = _arrays()
    offsets.pop(-6)

    report = build_report(
        prediction=prediction,
        labels=labels,
        validation_mask=mask,
        normal_offsets=offsets,
        **_report_kwargs(),
    )

    assert report["experimental_evidence_ready"] is False
    assert any("offset grid" in reason for reason in report["readiness_reasons"])


def test_report_ready_only_means_protocol_complete():
    prediction, labels, mask, offsets = _arrays()
    report = build_report(
        prediction=prediction,
        labels=labels,
        validation_mask=mask,
        normal_offsets=offsets,
        **_report_kwargs(),
    )

    assert report["experimental_evidence_ready"] is True
    assert "not proof of ink" in report["interpretation"]
    assert report["surface"]["geometry_sha256"] == "b" * 64


def test_invalid_zero_offset_and_noninteger_offsets_fail():
    prediction, labels, mask, offsets = _arrays()
    with pytest.raises(ValueError, match="reserved"):
        evaluate_normal_response(prediction, labels, mask, {0: offsets[-6]})
    with pytest.raises(ValueError, match="integer"):
        evaluate_normal_response(prediction, labels, mask, {-1.5: offsets[-6]})


def test_digest_changes_when_one_offset_changes():
    prediction, labels, mask, offsets = _arrays()
    first = evaluate_normal_response(prediction, labels, mask, offsets)
    changed = {k: v.copy() for k, v in offsets.items()}
    changed[6][0, 0] += 0.01
    second = evaluate_normal_response(prediction, labels, mask, changed)

    assert first["evaluated_arrays_sha256"] != second["evaluated_arrays_sha256"]


def test_cli_writes_protocol_complete_report(tmp_path):
    prediction, labels, mask, offsets = _arrays()
    prediction_path = tmp_path / "prediction.npy"
    labels_path = tmp_path / "labels.npy"
    mask_path = tmp_path / "mask.npy"
    manifest_path = tmp_path / "sampling-manifest.json"
    out_path = tmp_path / "normal-response.json"
    np.save(prediction_path, prediction)
    np.save(labels_path, labels)
    np.save(mask_path, mask)
    manifest_path.write_text(
        '{"normal_convention":"frozen-test","interpolation":"test"}\n',
        encoding="utf-8",
    )

    args = [
        "--prediction",
        str(prediction_path),
        "--labels",
        str(labels_path),
        "--validation-mask",
        str(mask_path),
        "--split-id",
        "fold-1",
        "--held-out",
        "--training-overlap",
        "none",
        "--ground-truth-source-url",
        "https://example.org/public-ground-truth",
        "--model-checkpoint-sha256",
        "d" * 64,
        "--model-window",
        "17x64x64",
        "--surface-geometry-sha256",
        "e" * 64,
        "--sampling-manifest",
        str(manifest_path),
        "--out",
        str(out_path),
        "--format",
        "json",
    ]
    for offset in REQUIRED_OFFSETS_VOXELS:
        path = tmp_path / f"offset-{offset:+d}.npy"
        np.save(path, offsets[offset])
        args.extend(["--normal-offset", f"{path}@{offset}"])

    status = main(args)

    assert status == 0
    text = out_path.read_text(encoding="utf-8")
    assert '"protocol_conformant": true' in text
    assert '"experimental_evidence_ready": true' in text



def _component_arrays():
    labels = np.zeros((10, 10), dtype=np.uint8)
    labels[1:3, 1:3] = 1
    mask = np.ones_like(labels)
    prediction = np.full((10, 10), 0.05, dtype=np.float32)
    prediction[1:3, 1:3] = 0.9
    prediction[7:9, 7:9] = 0.8

    offsets = {}
    for offset in REQUIRED_OFFSETS_VOXELS:
        arr = np.full_like(prediction, 0.05)
        arr[1:3, 1:3] = 0.2
        arr[7:9, 7:9] = 0.8
        offsets[offset] = arr

    y, x = np.mgrid[0:10, 0:10]
    xyz = np.stack([x, y, np.full_like(x, 12)], axis=-1).astype(np.float64)
    return prediction, labels, mask, offsets, xyz


def test_component_profiles_separate_surface_locked_and_persistent_components():
    prediction, labels, mask, offsets, xyz = _component_arrays()

    result = evaluate_normal_response(
        prediction,
        labels,
        mask,
        offsets,
        threshold=0.5,
        min_component_pixels=4,
        surface_xyz=xyz,
    )
    components = result["components"]

    assert components["predicted_components_total"] == 2
    assert components["analyzed_components"] == 2
    assert components["strict_nominal_peak_components"] == 1
    assert components["review_candidate_components"] == 1
    assert (
        components["ground_truth_groups"]["with_ink_overlap"][
            "strict_nominal_peak_fraction"
        ]
        == 1.0
    )
    assert (
        components["ground_truth_groups"]["without_ink_overlap"][
            "strict_nominal_peak_fraction"
        ]
        == 0.0
    )

    true_component, false_component = components["components"]
    assert true_component["has_ground_truth_ink"] is True
    assert true_component["strict_nominal_peak"] is True
    assert true_component["center_advantage_mean_probability"] == pytest.approx(0.7)

    assert false_component["has_ground_truth_ink"] is False
    assert false_component["strict_nominal_peak"] is False
    assert false_component["center_advantage_mean_probability"] == pytest.approx(0.0)
    assert false_component["peak_offsets_voxels"] == [
        -6, -4, -2, 0, 2, 4, 6
    ]
    assert components["vc3d_review_ready"] is True
    assert len(components["review_queue"]) == 1
    assert components["review_queue"][0]["component_id"] == false_component["component_id"]
    assert components["review_queue"][0]["xyz"] == [7.0, 7.0, 12.0]


def test_component_profiles_ignore_small_nominal_speckles():
    prediction, labels, mask, offsets, xyz = _component_arrays()
    prediction[5, 5] = 0.95
    for arr in offsets.values():
        arr[5, 5] = 0.95

    result = evaluate_normal_response(
        prediction,
        labels,
        mask,
        offsets,
        min_component_pixels=4,
        surface_xyz=xyz,
    )

    components = result["components"]
    assert components["predicted_components_total"] == 3
    assert components["analyzed_components"] == 2
    assert components["ignored_small_components"] == 1


def test_component_surface_xyz_must_match_prediction_shape():
    prediction, labels, mask, offsets, _ = _component_arrays()
    with pytest.raises(ValueError, match="surface_xyz shape mismatch"):
        evaluate_normal_response(
            prediction,
            labels,
            mask,
            offsets,
            surface_xyz=np.zeros((10, 10, 2), dtype=np.float64),
        )


def test_cli_hashes_surface_xyz_and_emits_component_review_queue(tmp_path):
    prediction, labels, mask, offsets, xyz = _component_arrays()
    prediction_path = tmp_path / "component-prediction.npy"
    labels_path = tmp_path / "component-labels.npy"
    mask_path = tmp_path / "component-mask.npy"
    xyz_path = tmp_path / "surface-xyz.npy"
    manifest_path = tmp_path / "component-sampling.json"
    out_path = tmp_path / "component-normal-response.json"

    np.save(prediction_path, prediction)
    np.save(labels_path, labels)
    np.save(mask_path, mask)
    np.save(xyz_path, xyz)
    manifest_path.write_text('{"normal":"synthetic"}\n', encoding="utf-8")

    args = [
        "--prediction", str(prediction_path),
        "--labels", str(labels_path),
        "--validation-mask", str(mask_path),
        "--split-id", "component-fold",
        "--held-out",
        "--training-overlap", "none",
        "--ground-truth-source-url", "https://example.org/component-truth",
        "--model-checkpoint-sha256", "7" * 64,
        "--model-window", "17x64x64",
        "--surface-geometry-sha256", "8" * 64,
        "--surface-xyz", str(xyz_path),
        "--sampling-manifest", str(manifest_path),
        "--min-component-pixels", "4",
        "--out", str(out_path),
    ]
    for offset in REQUIRED_OFFSETS_VOXELS:
        path = tmp_path / f"component-offset-{offset:+d}.npy"
        np.save(path, offsets[offset])
        args.extend(["--normal-offset", f"{path}@{offset}"])

    assert main(args) == 0
    report = __import__("json").loads(out_path.read_text(encoding="utf-8"))
    assert report["schema_version"] == 2
    assert report["inputs"]["surface_xyz"]["path"] == str(xyz_path)
    assert report["normal_response"]["components"]["review_candidate_components"] == 1
    assert len(report["normal_response"]["components"]["review_queue"]) == 1
