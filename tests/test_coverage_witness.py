import numpy as np
import pytest

from scrollq.coverage_witness import (
    CoverageWitnessError,
    RayRun,
    centered_normal_xyz,
    classify_runs,
    harmonic_continue_rect,
    hide_rect,
    odd_rect,
    supported_runs,
)


def _plane(h=15, w=17):
    yy, xx = np.meshgrid(
        np.arange(h, dtype=np.float64),
        np.arange(w, dtype=np.float64),
        indexing="ij",
    )
    xyz = np.stack(
        [
            10.0 + 2.0 * xx + 0.5 * yy,
            -4.0 + 3.0 * yy - 0.25 * xx,
            50.0 + 0.75 * xx + 1.25 * yy,
        ],
        axis=-1,
    )
    return xyz, np.ones((h, w), dtype=bool)


def test_odd_rect():
    assert odd_rect((7, 8), 5) == (5, 10, 6, 11)
    with pytest.raises(CoverageWitnessError):
        odd_rect((1, 1), 4)


def test_harmonic_continuation_recovers_affine_plane():
    xyz, valid = _plane()
    rect = odd_rect((7, 8), 7)
    observed_xyz, observed_valid = hide_rect(xyz, valid, rect)
    filled, filled_valid, report = harmonic_continue_rect(
        observed_xyz, observed_valid, rect
    )
    y0, y1, x0, x1 = rect
    np.testing.assert_allclose(
        filled[y0:y1, x0:x1],
        xyz[y0:y1, x0:x1],
        atol=1e-10,
        rtol=0,
    )
    assert filled_valid[y0:y1, x0:x1].all()
    assert report["hidden_cell_count"] == 49
    assert report["dirichlet_edges"] > 0


def test_hidden_interior_is_a_true_firewall():
    xyz_a, valid = _plane()
    xyz_b = xyz_a.copy()
    rect = odd_rect((7, 8), 7)
    y0, y1, x0, x1 = rect
    # Make the hidden reference absurdly different. hide_rect must erase it.
    xyz_b[y0:y1, x0:x1, 0] += 100000.0
    xyz_b[y0:y1, x0:x1, 1] -= 70000.0
    xyz_b[y0:y1, x0:x1, 2] *= -3.0

    obs_a, val_a = hide_rect(xyz_a, valid, rect)
    obs_b, val_b = hide_rect(xyz_b, valid, rect)
    np.testing.assert_array_equal(val_a, val_b)
    assert np.array_equal(np.isnan(obs_a), np.isnan(obs_b))
    np.testing.assert_allclose(
        np.nan_to_num(obs_a, nan=0.0),
        np.nan_to_num(obs_b, nan=0.0),
        atol=0,
        rtol=0,
    )

    fill_a, valid_a, _ = harmonic_continue_rect(obs_a, val_a, rect)
    fill_b, valid_b, _ = harmonic_continue_rect(obs_b, val_b, rect)
    np.testing.assert_array_equal(valid_a, valid_b)
    np.testing.assert_allclose(fill_a, fill_b, atol=0, rtol=0)


def test_harmonic_continuation_requires_hidden_values_erased():
    xyz, valid = _plane()
    rect = odd_rect((7, 8), 5)
    with pytest.raises(CoverageWitnessError, match="no finite geometry"):
        harmonic_continue_rect(xyz, valid & False, rect)


def test_centered_normal_is_finite_on_continued_plane():
    xyz, valid = _plane()
    normal = centered_normal_xyz(xyz, valid, 7, 8)
    assert normal is not None
    assert np.isfinite(normal).all()
    assert np.linalg.norm(normal) == pytest.approx(1.0)


def test_supported_runs_are_maximal_and_min_length_filtered():
    offsets = list(range(-6, 7))
    mask = [
        False, True, True, False, True, False, True,
        True, True, False, True, True, False,
    ]
    runs = supported_runs(offsets, mask, min_run_voxels=2)
    assert [r.as_dict() for r in runs] == [
        {"start_offset": -5, "end_offset": -4, "midpoint": -4.5, "length": 2},
        {"start_offset": 0, "end_offset": 2, "midpoint": 1.0, "length": 3},
        {"start_offset": 4, "end_offset": 5, "midpoint": 4.5, "length": 2},
    ]


def test_classify_runs_separates_target_guard_and_competitors():
    rows = [
        RayRun(-25, -23, -24.0, 3),
        RayRun(-10, -9, -9.5, 2),
        RayRun(-2, 1, -0.5, 4),
        RayRun(12, 14, 13.0, 3),
        RayRun(29, 31, 30.0, 3),
    ]
    out = classify_runs(
        rows,
        target_abs_max=8,
        competitor_abs_min=12,
        competitor_abs_max=32,
    )
    assert out["target"].midpoint == -0.5
    assert [r.midpoint for r in out["guard"]] == [-9.5]
    assert [r.midpoint for r in out["competitors"]] == [-24.0, 13.0, 30.0]


def test_classify_target_tie_prefers_negative_midpoint():
    rows = [
        RayRun(-3, -1, -2.0, 3),
        RayRun(1, 3, 2.0, 3),
    ]
    out = classify_runs(
        rows,
        target_abs_max=8,
        competitor_abs_min=12,
        competitor_abs_max=32,
    )
    assert out["target"].midpoint == -2.0
