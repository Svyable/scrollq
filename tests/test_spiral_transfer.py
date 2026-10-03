import json
from pathlib import Path

import numpy as np
import pytest

from scrollq.spiral_transfer import (
    TriangleSurface,
    _git_blob_sha1,
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
    data = b"hello\n"
    import hashlib
    expected = hashlib.sha1(b"blob 6\0hello\n").hexdigest()
    assert _git_blob_sha1(data) == expected
