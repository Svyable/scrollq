import csv
import hashlib
import json
from pathlib import Path

import pytest

from scrollq import horizon_validation


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_truth(path: Path, ys: list[float]) -> None:
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["x", "y"])
        for x, y in enumerate(ys):
            writer.writerow([x, y])


def _write_prediction_csv(path: Path, ys: dict[int, int]) -> None:
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["x", "y", "normalized_score", "source_score"])
        for x, y in sorted(ys.items()):
            writer.writerow([x, y, 1.0, 1.0])


def _documents(tmp_path: Path, *, omit_x: int | None = None):
    truth = tmp_path / "truth.csv"
    truth_y = [5.0] * 11
    _write_truth(truth, truth_y)

    score_sha = _sha_bytes(b"frozen-score-map")
    spec = {
        "schema_version": 1,
        "coordinate_system": "score_map_xy",
        "protocol_id": "synthetic-heldout-v1",
        "volume_root": "public/test-volume.zarr",
        "source_attestation": {
            "algorithm": "zpa-metadata-semantics-v1",
            "state": "PRESENT",
            "metadata_semantics_sha256": "a" * 64,
        },
        "shape_yx": [20, 11],
        "score_sha256": score_sha,
        "truth_sha256": horizon_validation._sha256(truth),
        "tracker": {
            "max_step": 2,
            "smoothness": 0.2,
            "normalization": {"enabled": False},
        },
        "anchors": [{"x": 5, "y": 5}],
        "anchor_exclusion_columns": 1,
        "tolerance_rows": 1.0,
        "minimum_within_tolerance_rate": 1.0,
    }

    points = {x: 5 for x in range(11) if x != omit_x}
    # Deliberately wrong inside the excluded anchor neighborhood.
    for x in (4, 5, 6):
        if x in points:
            points[x] = 15

    pred_csv = tmp_path / "prediction.horizon.csv"
    _write_prediction_csv(pred_csv, points)
    prediction = {
        "schema_version": 1,
        "kind": "horizon-path",
        "method": "deterministic-first-order-horizon-dp-v1",
        "input": {"sha256": score_sha, "shape_yx": [20, 11]},
        "parameters": {"max_step": 2, "smoothness": 0.2},
        "normalization": {"enabled": False},
        "path": {
            "anchors": [{"x": 5, "y": 5}],
            "points": [{"x": x, "y": y} for x, y in sorted(points.items())],
            "csv_path": str(pred_csv),
            "csv_sha256": horizon_validation._sha256(pred_csv),
        },
    }
    return spec, prediction, truth, pred_csv


def test_anchor_neighborhood_is_excluded_from_denominator(tmp_path: Path):
    spec, prediction, truth, pred_csv = _documents(tmp_path)
    result = horizon_validation.evaluate(
        spec, prediction, truth_path=truth, prediction_csv=pred_csv
    )

    assert result["verdict"] == "PASS"
    assert result["expected_heldout_points"] == 8
    assert result["within_tolerance"] == 8
    assert result["within_tolerance_rate"] == 1.0
    excluded = [
        row["x"]
        for row in result["targets"]
        if row["status"] == "excluded-anchor-neighborhood"
    ]
    assert excluded == [4, 5, 6]


def test_missing_prediction_stays_in_denominator_and_fails(tmp_path: Path):
    spec, prediction, truth, pred_csv = _documents(tmp_path, omit_x=0)
    result = horizon_validation.evaluate(
        spec, prediction, truth_path=truth, prediction_csv=pred_csv
    )

    assert result["verdict"] == "FAIL"
    assert result["expected_heldout_points"] == 8
    assert result["predicted_heldout_points"] == 7
    assert result["missing_predictions"] == 1
    assert result["within_tolerance"] == 7
    assert result["within_tolerance_rate"] == pytest.approx(7 / 8)


def test_threshold_equality_passes(tmp_path: Path):
    spec, prediction, truth, pred_csv = _documents(tmp_path, omit_x=0)
    spec["minimum_within_tolerance_rate"] = 7 / 8
    result = horizon_validation.evaluate(
        spec, prediction, truth_path=truth, prediction_csv=pred_csv
    )
    assert result["verdict"] == "PASS"


def test_prediction_parameters_must_match_frozen_spec(tmp_path: Path):
    spec, prediction, truth, pred_csv = _documents(tmp_path)
    prediction["parameters"]["smoothness"] = 0.25

    with pytest.raises(ValueError, match="smoothness"):
        horizon_validation.evaluate(
            spec, prediction, truth_path=truth, prediction_csv=pred_csv
        )


def test_truth_hash_must_match_frozen_spec(tmp_path: Path):
    spec, prediction, truth, pred_csv = _documents(tmp_path)
    truth.write_text("x,y\n0,9\n")

    with pytest.raises(ValueError, match="truth CSV SHA-256"):
        horizon_validation.evaluate(
            spec, prediction, truth_path=truth, prediction_csv=pred_csv
        )


def test_prediction_csv_must_match_report_hash(tmp_path: Path):
    spec, prediction, truth, pred_csv = _documents(tmp_path)
    pred_csv.write_text(pred_csv.read_text() + "10,10,0,0\n")

    with pytest.raises(ValueError, match="prediction CSV SHA-256"):
        horizon_validation.evaluate(
            spec, prediction, truth_path=truth, prediction_csv=pred_csv
        )


def test_prediction_csv_rows_must_match_json_points(tmp_path: Path):
    spec, prediction, truth, pred_csv = _documents(tmp_path)
    altered = {x: 5 for x in range(11)}
    altered[0] = 6
    _write_prediction_csv(pred_csv, altered)
    prediction["path"]["csv_sha256"] = horizon_validation._sha256(pred_csv)

    with pytest.raises(ValueError, match="does not match prediction JSON"):
        horizon_validation.evaluate(
            spec, prediction, truth_path=truth, prediction_csv=pred_csv
        )


def test_exclusion_cannot_remove_all_truth(tmp_path: Path):
    spec, prediction, truth, pred_csv = _documents(tmp_path)
    spec["anchor_exclusion_columns"] = 100

    with pytest.raises(ValueError, match="leaves no held-out truth points"):
        horizon_validation.evaluate(
            spec, prediction, truth_path=truth, prediction_csv=pred_csv
        )


def test_canonical_spec_hash_is_stable(tmp_path: Path):
    spec, _, _, _ = _documents(tmp_path)
    shuffled = dict(reversed(list(spec.items())))
    assert horizon_validation.digest(spec) == horizon_validation.digest(shuffled)


def test_source_attestation_must_be_present(tmp_path: Path):
    spec, prediction, truth, pred_csv = _documents(tmp_path)
    spec["source_attestation"]["state"] = "UNKNOWN"

    with pytest.raises(ValueError, match="state must be PRESENT"):
        horizon_validation.evaluate(
            spec, prediction, truth_path=truth, prediction_csv=pred_csv
        )
