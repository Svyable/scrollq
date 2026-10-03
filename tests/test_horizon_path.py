import json
from pathlib import Path

import numpy as np
import pytest

from scrollq import horizon_path


def _synthetic_horizon(rows=61, cols=120):
    x = np.arange(cols)
    truth = np.rint(30.0 + 6.0 * np.sin(x / 14.0)).astype(int)
    yy = np.arange(rows)[:, None]
    ridge = np.exp(-0.5 * ((yy - truth[None, :]) / 1.0) ** 2)
    clutter = 0.04 * (1.0 + np.sin(0.37 * yy + 0.19 * x[None, :]))
    score = ridge + clutter
    score[:, 48:61] = clutter[:, 48:61]
    return score.astype(np.float64), truth


def test_tracker_recovers_curved_horizon_across_gap():
    score, truth = _synthetic_horizon()
    result = horizon_path.track_horizon(
        score,
        max_step=2,
        smoothness=0.20,
        anchors=[(0, int(truth[0])), (42, int(truth[42])), (68, int(truth[68])), (119, int(truth[119]))],
    )

    path = result["path_y"]
    mae = float(np.mean(np.abs(path - truth)))
    assert mae < 1.25
    assert result["max_observed_step"] <= 2


def test_hard_anchors_are_respected_exactly():
    score, truth = _synthetic_horizon(cols=80)
    anchors = [(5, int(truth[5])), (35, int(truth[35])), (70, int(truth[70]))]
    result = horizon_path.track_horizon(
        score, max_step=2, smoothness=0.15, anchors=anchors
    )

    for x, y in anchors:
        assert int(result["path_y"][x]) == y
    assert result["anchors"] == [{"x": x, "y": y} for x, y in anchors]


def test_unreachable_anchor_pair_fails_closed():
    score = np.ones((20, 10), dtype=float)
    with pytest.raises(ValueError, match="unreachable"):
        horizon_path.track_horizon(
            score,
            max_step=1,
            anchors=[(1, 1), (3, 10)],
        )


def test_step_constraint_cannot_be_bought_by_high_score():
    score = np.zeros((12, 8), dtype=float)
    score[1, 0] = 10.0
    score[10, 1:] = 1000.0

    result = horizon_path.track_horizon(
        score,
        max_step=1,
        smoothness=0.0,
        anchors=[(0, 1)],
    )

    assert result["max_observed_step"] <= 1
    assert int(result["path_y"][1]) <= 2


def test_tracker_is_bitwise_deterministic():
    score, truth = _synthetic_horizon(cols=70)
    kwargs = {
        "max_step": 2,
        "smoothness": 0.2,
        "anchors": [(0, int(truth[0])), (69, int(truth[69]))],
    }
    a = horizon_path.track_horizon(score, **kwargs)
    b = horizon_path.track_horizon(score, **kwargs)
    np.testing.assert_array_equal(a["path_y"], b["path_y"])
    np.testing.assert_array_equal(a["path_scores"], b["path_scores"])
    assert a["objective"] == b["objective"]


def test_cli_outputs_hash_pinned_path_and_caveat(tmp_path: Path):
    score, truth = _synthetic_horizon(cols=50)
    source = tmp_path / "score.npy"
    np.save(source, score.astype(np.float32), allow_pickle=False)
    prefix = tmp_path / "out" / "trace"

    rc = horizon_path.main(
        [
            str(source),
            "--out-prefix",
            str(prefix),
            "--max-step",
            "2",
            "--smoothness",
            "0.2",
            "--anchor",
            f"0:{int(truth[0])}",
            "--anchor",
            f"49:{int(truth[49])}",
        ]
    )
    assert rc == 0

    report_path = Path(str(prefix) + ".horizon.json")
    report = json.loads(report_path.read_text())
    csv_path = Path(report["path"]["csv_path"])
    assert report["kind"] == "horizon-path"
    assert report["input"]["sha256"] == horizon_path._sha256(source)
    assert report["path"]["csv_sha256"] == horizon_path._sha256(csv_path)
    assert len(report["path"]["points"]) == score.shape[1]
    assert "not by itself evidence of correct papyrus identity" in report["scope"]


def test_anchor_json_requires_integer_coordinates(tmp_path: Path):
    path = tmp_path / "anchors.json"
    path.write_text('[{"x": "1", "y": 2}]')
    with pytest.raises(ValueError, match="must be integers"):
        horizon_path._load_anchor_file(path)


def test_pixel_guard_rejects_before_dynamic_program(tmp_path: Path):
    source = tmp_path / "score.npy"
    np.save(source, np.zeros((20, 20), dtype=np.float32), allow_pickle=False)

    with pytest.raises(ValueError, match="above --max-pixels"):
        horizon_path.run(
            source,
            tmp_path / "out",
            max_pixels=100,
        )
