import numpy as np
from PIL import Image
import pytest

from scrollq.ink_validation import (
    _binarize_labels,
    _load_2d,
    _normalize_prediction,
    build_report,
    evaluate_prediction,
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
            [0.9, 0.1, 0.8, 0.2],
            [0.8, 0.2, 0.7, 0.1],
            [0.1, 0.2, 0.3, 0.4],
            [0.2, 0.1, 0.2, 0.1],
        ],
        dtype=np.float32,
    )
    mask = np.ones_like(labels)
    return prediction, labels, mask


def test_perfect_held_out_metrics():
    prediction, labels, mask = _arrays()
    metrics = evaluate_prediction(prediction, labels, mask, threshold=0.5)

    assert metrics["confusion"] == {"tp": 4, "tn": 12, "fp": 0, "fn": 0}
    assert metrics["balanced_accuracy"] == 1.0
    assert metrics["roc_auc"] == 1.0
    assert metrics["false_positive_rate"] == 0.0
    assert metrics["both_classes_present"] is True


def test_roc_auc_is_tie_correct_and_threshold_independent():
    labels = np.array([[0, 1, 0, 1]], dtype=np.uint8)
    prediction = np.array([[0.5, 0.5, 0.1, 0.9]], dtype=np.float32)

    metrics = evaluate_prediction(prediction, labels, threshold=0.95)

    assert metrics["balanced_accuracy"] == pytest.approx(0.5)
    assert metrics["roc_auc"] == pytest.approx(0.875)


def test_report_requires_falsification_control_for_prize_readiness():
    prediction, labels, mask = _arrays()
    report = build_report(
        prediction=prediction,
        labels=labels,
        validation_mask=mask,
        threshold=0.5,
        split_id="fold-1",
        held_out=True,
        training_overlap="none",
        ground_truth_source_url="https://example.org/public-ground-truth",
        model_checkpoint_sha256="a" * 64,
        model_window_voxels=(17, 64, 64),
        controls={},
    )

    assert report["prize_evidence_ready"] is False
    assert "no falsification-control prediction" in " ".join(
        report["readiness_reasons"]
    )


def test_control_delta_records_correct_surface_advantage():
    prediction, labels, mask = _arrays()
    control = np.full_like(prediction, 0.5)
    report = build_report(
        prediction=prediction,
        labels=labels,
        validation_mask=mask,
        threshold=0.5,
        split_id="fold-1",
        held_out=True,
        training_overlap="none",
        ground_truth_source_url="https://example.org/public-ground-truth",
        model_checkpoint_sha256="b" * 64,
        model_window_voxels=(17, 64, 64),
        label_ancestry="independent",
        controls={"normal+3": control},
    )

    assert report["prize_evidence_ready"] is True
    row = report["controls"][0]
    assert row["name"] == "normal+3"
    assert row["primary_minus_control_balanced_accuracy"] == pytest.approx(0.5)
    assert row["primary_minus_control_roc_auc"] == pytest.approx(0.5)


def test_related_label_ancestry_prevents_prize_readiness():
    prediction, labels, mask = _arrays()
    report = build_report(
        prediction=prediction,
        labels=labels,
        validation_mask=mask,
        threshold=0.5,
        split_id="fold-1",
        held_out=True,
        training_overlap="none",
        ground_truth_source_url="https://example.org/public-ground-truth",
        model_checkpoint_sha256="9" * 64,
        model_window_voxels=(17, 64, 64),
        label_ancestry="related",
        label_source_sha256="8" * 64,
        controls={"normal+3": np.full_like(prediction, 0.5)},
    )

    assert report["prize_evidence_ready"] is False
    assert report["split"]["label_ancestry"] == "related"
    assert report["split"]["label_source_sha256"] == "8" * 64
    assert any("label ancestry" in reason for reason in report["readiness_reasons"])


def test_training_overlap_prevents_prize_readiness():
    prediction, labels, mask = _arrays()
    report = build_report(
        prediction=prediction,
        labels=labels,
        validation_mask=mask,
        threshold=0.5,
        split_id="fold-1",
        held_out=True,
        training_overlap="present",
        ground_truth_source_url="https://example.org/public-ground-truth",
        model_checkpoint_sha256="c" * 64,
        model_window_voxels=(17, 64, 64),
        controls={"normal+3": np.full_like(prediction, 0.5)},
    )

    assert report["prize_evidence_ready"] is False
    assert any("overlap" in reason for reason in report["readiness_reasons"])


def test_loads_grayscale_png_without_conversion(tmp_path):
    uint8_path = tmp_path / "prediction.png"
    uint16_path = tmp_path / "prediction16.png"
    uint8 = np.array([[0, 255], [128, 64]], dtype=np.uint8)
    uint16 = np.array([[0, 65535], [32768, 1024]], dtype=np.uint16)
    Image.fromarray(uint8).save(uint8_path)
    Image.fromarray(uint16).save(uint16_path)

    loaded8 = _load_2d(uint8_path)
    loaded16 = _load_2d(uint16_path)

    assert np.array_equal(loaded8, uint8)
    assert loaded8.dtype == np.uint8
    assert np.array_equal(loaded16, uint16)
    assert loaded16.dtype == np.uint16


def test_replicated_rgb_png_collapses_without_color_conversion(tmp_path):
    path = tmp_path / "rgb.png"
    gray = np.array([[0, 255], [128, 64]], dtype=np.uint8)
    rgb = np.repeat(gray[..., None], 3, axis=2)
    Image.fromarray(rgb).save(path)

    loaded = _load_2d(path)

    assert np.array_equal(loaded, gray)
    assert loaded.dtype == np.uint8


def test_true_color_png_is_rejected(tmp_path):
    path = tmp_path / "rgb.png"
    rgb = np.zeros((2, 2, 3), dtype=np.uint8)
    rgb[0, 0, 1] = 1
    Image.fromarray(rgb).save(path)

    with pytest.raises(ValueError, match="color channels differ"):
        _load_2d(path)


def test_uint8_soft_labels_use_explicit_strict_threshold():
    labels = np.array([[0, 127, 128, 255]], dtype=np.uint8)

    binary = _binarize_labels(labels, scale="uint8", threshold=0.5)

    assert binary.tolist() == [[0, 0, 1, 1]]


def test_binary_label_mode_stays_strict():
    with pytest.raises(ValueError, match="use --label-scale"):
        _binarize_labels(
            np.array([[0, 127, 255]], dtype=np.uint8),
            scale="binary",
        )


def test_uint8_prediction_normalization():
    arr = np.array([[0, 255], [128, 64]], dtype=np.uint8)
    out = _normalize_prediction(arr, "auto")
    assert out.dtype == np.float32
    assert out[0, 0] == 0.0
    assert out[0, 1] == 1.0


def test_float_outside_unit_range_requires_explicit_encoding():
    arr = np.array([[0.0, 2.0]], dtype=np.float32)
    with pytest.raises(ValueError, match="outside"):
        _normalize_prediction(arr, "auto")


def test_empty_mask_and_nonbinary_inputs_fail_explicitly():
    prediction, labels, mask = _arrays()
    with pytest.raises(ValueError, match="zero pixels"):
        evaluate_prediction(prediction, labels, np.zeros_like(mask))
    labels[0, 0] = 2
    with pytest.raises(ValueError, match="labels must be binary"):
        evaluate_prediction(prediction, labels, mask)
    labels[0, 0] = 1
    mask[0, 0] = 2
    with pytest.raises(ValueError, match="mask must be binary"):
        evaluate_prediction(prediction, labels, mask)


def test_shape_mismatch_and_nonfinite_prediction_fail():
    prediction, labels, mask = _arrays()
    with pytest.raises(ValueError, match="shape mismatch"):
        evaluate_prediction(prediction[:-1], labels, mask)
    prediction[0, 0] = np.nan
    with pytest.raises(ValueError, match="finite probabilities"):
        evaluate_prediction(prediction, labels, mask)


def test_single_class_mask_is_measured_but_not_ready():
    prediction, labels, mask = _arrays()
    mask[labels == 0] = 0
    report = build_report(
        prediction=prediction,
        labels=labels,
        validation_mask=mask,
        threshold=0.5,
        split_id="fold-1",
        held_out=True,
        training_overlap="none",
        ground_truth_source_url="https://example.org/public-ground-truth",
        model_checkpoint_sha256="d" * 64,
        model_window_voxels=(17, 64, 64),
        controls={"normal+3": prediction},
    )

    assert report["evaluation"]["both_classes_present"] is False
    assert report["evaluation"]["roc_auc"] is None
    assert report["prize_evidence_ready"] is False


def test_digest_changes_when_a_control_changes():
    prediction, labels, mask = _arrays()
    kwargs = dict(
        prediction=prediction,
        labels=labels,
        validation_mask=mask,
        threshold=0.5,
        split_id="fold-1",
        held_out=True,
        training_overlap="none",
        ground_truth_source_url="https://example.org/public-ground-truth",
        model_checkpoint_sha256="e" * 64,
        model_window_voxels=(17, 64, 64),
    )
    first = build_report(**kwargs, controls={"offset": np.zeros_like(prediction)})
    second = build_report(**kwargs, controls={"offset": np.ones_like(prediction)})

    assert first["evaluated_arrays_sha256"] != second["evaluated_arrays_sha256"]


def test_cli_writes_report_and_returns_fail_closed_status(tmp_path):
    prediction, labels, mask = _arrays()
    prediction_path = tmp_path / "prediction.npy"
    labels_path = tmp_path / "labels.npy"
    mask_path = tmp_path / "mask.npy"
    out_path = tmp_path / "report.json"
    np.save(prediction_path, prediction)
    np.save(labels_path, labels)
    np.save(mask_path, mask)

    status = main(
        [
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
            "f" * 64,
            "--model-window",
            "17x64x64",
            "--out",
            str(out_path),
            "--format",
            "json",
        ]
    )

    assert status == 1
    assert out_path.is_file()
    assert '"prize_evidence_ready": false' in out_path.read_text()
