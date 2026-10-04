import numpy as np
import pytest

from scrollq import fiber_seam as fs


def _analysis(delta_by_row, missing=()):
    frames = []
    for gy in range(4):
        if ("left", gy) not in missing:
            frames.append({"grid": [gy, 1], "axes_degrees": [10.0, 100.0]})
        if ("right", gy) not in missing:
            d = float(delta_by_row[gy])
            frames.append({"grid": [gy, 2], "axes_degrees": [10.0 + d, 100.0 + d]})
    return {"status": "measured", "frames": frames}


def test_seam_metrics_scores_only_frozen_boundary_pairs():
    result = fs.seam_metrics(_analysis([0.0, 30.0, 40.0, 5.0]))

    assert result["valid_comparison_count"] == 4
    assert result["flagged_comparison_count"] == 2
    assert result["seam_positive"] is True
    assert [r["tile_a"] for r in result["comparisons"]] == [
        [0, 1], [1, 1], [2, 1], [3, 1]
    ]


def test_missing_frame_is_not_silently_clean():
    result = fs.seam_metrics(
        _analysis([35.0, 35.0, 35.0, 35.0], missing={("right", 0), ("right", 1)})
    )

    assert result["valid_comparison_count"] == 2
    assert result["flagged_comparison_count"] == 2
    assert result["status"] == "insufficient"
    assert result["seam_positive"] is False


def test_half_stitch_changes_only_declared_side():
    target = np.zeros((9, 4, 6), dtype=np.uint8)
    wrong = np.ones((9, 4, 6), dtype=np.uint8)
    variants = fs.stitch_half_slabs(target, wrong)

    assert np.array_equal(variants["intact"], target)
    assert np.all(variants["target_left_wrong_right"][:, :, :3] == 0)
    assert np.all(variants["target_left_wrong_right"][:, :, 3:] == 1)
    assert np.all(variants["wrong_left_target_right"][:, :, :3] == 1)
    assert np.all(variants["wrong_left_target_right"][:, :, 3:] == 0)


def _group(*, usable=True, intact=False, left=True, right=True, valid=4):
    def row(value):
        return {
            "seam_positive": value,
            "valid_comparison_count": valid,
        }
    return {
        "status": "usable" if usable else "unusable",
        "variants": {
            "intact": row(intact) if usable else {},
            "target_left_wrong_right": row(left) if usable else {},
            "wrong_left_target_right": row(right) if usable else {},
        },
    }


def test_development_gate_passes_frozen_all_group_denominators():
    groups = [_group() for _ in range(8)] + [
        _group(usable=False),
        _group(usable=False),
    ]
    result = fs.score_development(groups)

    assert result["status"] == "pass"
    assert result["usable_group_count"] == 8
    assert result["intact_false_positive_fraction"] == 0.0
    assert result["target_left_wrong_right_detection_fraction"] == 0.8
    assert result["wrong_left_target_right_detection_fraction"] == 0.8
    assert result["pooled_seam_comparison_coverage_fraction"]["intact"] == 0.8
    assert all(result["checks"].values())


def test_unusable_groups_count_against_detection_and_coverage():
    groups = [_group() for _ in range(7)] + [
        _group(usable=False),
        _group(usable=False),
        _group(usable=False),
    ]
    result = fs.score_development(groups)

    assert result["status"] == "fail"
    assert result["target_left_wrong_right_detection_fraction"] == 0.7
    assert result["checks"]["usable_groups"] is False
    assert result["pooled_seam_comparison_coverage_fraction"]["intact"] == 0.7
    assert result["checks"]["intact_seam_coverage"] is False


def test_intact_false_positive_gate_is_fail_closed():
    groups = [
        _group(intact=True),
        _group(intact=True),
        _group(intact=True),
        *[_group() for _ in range(7)],
    ]
    result = fs.score_development(groups)

    assert result["status"] == "fail"
    assert result["intact_false_positive_fraction"] == pytest.approx(0.3)
    assert result["checks"]["intact_false_positive_fraction"] is False
