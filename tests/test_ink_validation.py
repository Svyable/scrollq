import numpy as np
import pytest

from scrollq.ink_validation import (
    _normalize_prediction,
    build_report,
    evaluate_prediction,
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
    assert metrics["false_positive_rate"] == 0.0
    assert metrics["both_classes_present"] is True


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
        controls={"normal+3": control},
    )

    assert report["prize_evidence_ready"] is True
    row = report["controls"][0]
    assert row["name"] == "normal+3"
    assert row["primary_minus_control_balanced_accuracy"] == pytest.approx(0.5)


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
