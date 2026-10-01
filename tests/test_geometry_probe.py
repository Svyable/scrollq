import pytest

from scrollq.geometry_probe import candidate_z_center, split_axial_windows


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
