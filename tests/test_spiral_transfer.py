import json
from pathlib import Path

import numpy as np
import pytest

from scrollq.spiral_transfer import (
    TriangleSurface,
    _git_blob_sha1,
    _midpoint_ranks,
    _choose_offset,
    _held_metrics,
    _load_predictions,
    _point_triangle_distance,
    _triangles,
)


def test_exact_triangle_hit_and_known_normal_displacement():
    tri = np.array([[[0., 0., 0.], [2., 0., 0.], [0., 2., 0.]]])
    assert _point_triangle_distance(np.array([0.5, 0.5, 0.]), tri)[0] == pytest.approx(0.0)
    assert _point_triangle_distance(np.array([0.5, 0.5, 3.]), tri)[0] == pytest.approx(3.0)


def test_point_to_triangle_not_nearest_vertex_regression():
    tri = np.array([[[0., 0., 0.], [10., 0., 0.], [0., 10., 0.]]])
    p = np.array([4., 4., 2.])
    d = _point_triangle_distance(p, tri)[0]
    nearest_vertex = min(np.linalg.norm(p - v) for v in tri[0])
    assert d == pytest.approx(2.0)
    assert d < nearest_vertex


def test_triangle_surface_exact_search_handles_far_centroid_large_triangle():
    # The huge triangle has a far centroid but contains the query projection.
    tri = np.array([
        [[0., 0., 0.], [100., 0., 0.], [0., 100., 0.]],
        [[2., 2., 10.], [3., 2., 10.], [2., 3., 10.]],
    ])
    d = TriangleSurface(tri).distances(np.array([[1., 1., 1.]]))
    assert d[0] == pytest.approx(1.0)


def test_invalid_quad_excluded_and_frozen_diagonal_used():
    grid = np.array([
        [[1., 2.], [1., 2.]],
        [[1., 1.], [2., 2.]],
        [[10., 10.], [10., 10.]],
    ])
    tri = _triangles(grid, (0., 20.))
    assert tri.shape == (2, 3, 3)
    # Frozen diagonal is 00 -> 11, present in both triangles.
    p00 = grid[:, 0, 0]
    p11 = grid[:, 1, 1]
    assert all(any(np.allclose(v, p00) for v in t) and any(np.allclose(v, p11) for v in t) for t in tri)

    bad = grid.copy()
    bad[:, 1, 1] = -1
    assert _triangles(bad, (0., 20.)).shape[0] == 0


def test_core_z_clipping_includes_margin_and_excludes_beyond_it():
    grid = np.array([
        [[1., 2.], [1., 2.]],
        [[1., 1.], [2., 2.]],
        [[35., 35.], [35., 35.]],
    ])
    assert len(_triangles(grid, (100., 200.))) == 0  # 35 < 100-64
    grid[2] = 36.
    assert len(_triangles(grid, (100., 200.))) == 2  # boundary intersects margin


def test_malformed_npz_rejected(tmp_path):
    path = tmp_path / "bad.npz"
    np.savez(path, w020=np.zeros((2, 3, 4)))
    with pytest.raises(ValueError, match=r"shape \(3,H,W\)"):
        _load_predictions(path)


def test_npz_key_must_be_winding(tmp_path):
    path = tmp_path / "bad-key.npz"
    np.savez(path, prediction=np.ones((3, 2, 2)))
    with pytest.raises(ValueError, match="not wNNN"):
        _load_predictions(path)


def test_git_blob_hash_matches_git_object_definition():
    data = b"hello
"
    import hashlib
    expected = hashlib.sha1(b"blob 6\0hello
").hexdigest()
    assert _git_blob_sha1(data) == expected


def test_exact_1024_midpoint_rank_sampling():
    ranks = _midpoint_ranks(10000)
    assert len(ranks) == 1024
    expected = np.floor((np.arange(1024) + 0.5) * 10000 / 1024).astype(np.int64)
    assert np.array_equal(ranks, expected)
    assert np.all(np.diff(ranks) > 0)


def test_offset_tie_break_prefers_abs_then_signed():
    rows = [
        {"offset": 2, "eligible": True, "fit_mesh_median_of_medians": 1.0},
        {"offset": -1, "eligible": True, "fit_mesh_median_of_medians": 1.0},
        {"offset": 1, "eligible": True, "fit_mesh_median_of_medians": 1.0},
        {"offset": 0, "eligible": False, "fit_mesh_median_of_medians": None},
    ]
    assert _choose_offset(rows)["offset"] == -1


def test_offset_choice_has_no_held_out_input_surface():
    # The chooser accepts only already-computed fit rows. There is deliberately
    # no held-out argument that could alter the selected convention.
    fit_rows = [
        {"offset": 0, "eligible": True, "fit_mesh_median_of_medians": 4.0},
        {"offset": 1, "eligible": True, "fit_mesh_median_of_medians": 2.0},
    ]
    assert _choose_offset(fit_rows)["offset"] == 1
    held_out_catastrophe = {"offset": 1, "held_out_median": 999999.0}
    assert _choose_offset(fit_rows)["offset"] == 1
    assert "held_out_median" not in _choose_offset(fit_rows)


def test_repeat_report_serialization_can_be_byte_identical():
    report = {"b": [2, 1], "a": {"value": 3.5}}
    one = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "
"
    two = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "
"
    assert one.encode() == two.encode()
    assert "timestamp" not in one


def test_neighbor_classification_and_missing_expected_stay_in_denominator():
    per = {
        -2: np.array([9., 1., np.nan, 4.]),
        -1: np.array([8., 2., np.nan, 3.]),
         0: np.array([1., np.nan, np.nan, 3.]),
         1: np.array([2., 4., np.nan, 3.]),
         2: np.array([3., 5., np.nan, 3.]),
    }
    m = _held_metrics(per)
    assert m["sample_count"] == 4
    assert m["missing_or_unscorable_samples"] == 2
    # Missing expected predictions do not shrink either fixed denominator.
    assert m["fraction_distance_le_5_voxels"] == pytest.approx(2 / 4)
    assert m["expected_winding_nearest_fraction_among_plus_minus_2"] == pytest.approx(2 / 4)
    assert m["nearest_winding_delta_counts"]["0"] == 2
    assert m["nearest_winding_delta_counts"]["-2"] == 1
    assert m["neighbor_classifiable_samples"] == 3
