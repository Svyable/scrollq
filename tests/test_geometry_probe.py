import pytest

from scrollq.geometry_probe import (
    aabb_distance_voxels,
    candidate_z_center,
    split_axial_windows,
)


def _candidate(window_z, wrap, z0, z1):
    return {
        "path": f"mesh/z{window_z}_{wrap}",
        "window_z": window_z,
        "wrap": wrap,
        "bbox": [[0.0, 0.0, float(z0)], [1.0, 1.0, float(z1)]],
    }


def test_candidate_z_center_uses_bbox_not_window_label():
    row = _candidate(1000, "w020", 1100, 1300)
    assert candidate_z_center(row) == pytest.approx(1200.0)


def test_three_band_split_is_deterministic_and_wrap_paired():
    candidates = []
    centers = [100, 200, 300, 400, 1000, 1100, 1200, 1300, 2000, 2100, 2200, 2300]
    for i, center in enumerate(centers, start=1):
        for wrap in ("w020", "w100"):
            candidates.append(_candidate(i, wrap, center - 10, center + 10))

    result = split_axial_windows(
        list(reversed(candidates)), bands=3, core_depth=20
    )

    assert result["held_out_windows"] == [2, 6, 10]
    assert result["fit_candidates"] == 18
    assert result["held_out_candidates"] == 6
    held_roles = [r for r in result["candidate_roles"] if r["role"] == "held_out"]
    assert {r["window_z"] for r in held_roles} == {2, 6, 10}
    assert len(held_roles) == 6
    assert result["uses_quality_or_ink"] is False
    separation = result["fit_holdout_spatial_separation"]
    assert separation["status"] == "measured"
    assert separation["minimum_aabb_distance_voxels"] == pytest.approx(80.0)
    assert separation["aabb_overlap_or_touch_pair_count"] == 0


def test_aabb_distance_is_conservative_and_zero_for_touching_boxes():
    first = _candidate(1, "w020", 0, 10)
    second = _candidate(2, "w020", 15, 20)
    assert aabb_distance_voxels(first, second) == pytest.approx(5.0)

    touching = _candidate(3, "w020", 10, 30)
    assert aabb_distance_voxels(first, touching) == 0.0


def test_predeclared_fit_holdout_gap_gate_passes_and_fails_without_resplitting():
    candidates = []
    centers = [100, 200, 300, 400, 1000, 1100, 1200, 1300, 2000, 2100, 2200, 2300]
    for i, center in enumerate(centers, start=1):
        for wrap in ("w020", "w100"):
            candidates.append(_candidate(i, wrap, center - 10, center + 10))

    passing = split_axial_windows(
        candidates,
        bands=3,
        core_depth=20,
        minimum_fit_holdout_gap_voxels=80.0,
    )
    failing = split_axial_windows(
        candidates,
        bands=3,
        core_depth=20,
        minimum_fit_holdout_gap_voxels=80.1,
    )

    assert passing["held_out_windows"] == failing["held_out_windows"] == [2, 6, 10]
    assert passing["fit_holdout_spatial_separation"]["status"] == "pass"
    assert failing["fit_holdout_spatial_separation"]["status"] == "fail"
    assert (
        passing["fit_holdout_spatial_separation"]["minimum_aabb_distance_voxels"]
        == pytest.approx(80.0)
    )


def test_nonfinite_candidate_bbox_is_rejected():
    row = _candidate(1, "w020", 0, 10)
    row["bbox"][0][0] = float("nan")
    with pytest.raises(ValueError, match="not finite"):
        candidate_z_center(row)


def test_split_rejects_overlapping_evaluation_cores():
    candidates = []
    for i, center in enumerate((100, 110, 300), start=1):
        candidates.append(_candidate(i, "w020", center - 2, center + 2))

    with pytest.raises(ValueError, match="overlap"):
        split_axial_windows(candidates, bands=3, core_depth=20)


def test_split_requires_equal_band_sizes():
    candidates = [
        _candidate(i, "w020", i * 100, i * 100 + 10)
        for i in range(5)
    ]
    with pytest.raises(ValueError, match="cannot be divided equally"):
        split_axial_windows(candidates, bands=3)
