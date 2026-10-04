import numpy as np
import pytest

from scrollq.fiber_fingerprint import (
    FiberFingerprintError,
    cosine_distance,
    tangent_fiber_spectrum_descriptor,
    tangent_frame_xyz,
    tangent_sample_coordinates_zyx,
    translated_frame,
)


def _plane(h=11, w=13):
    yy, xx = np.meshgrid(
        np.arange(h, dtype=float),
        np.arange(w, dtype=float),
        indexing="ij",
    )
    xyz = np.stack(
        [
            100.0 + 2.0 * xx,
            200.0 + 3.0 * yy,
            300.0 + 0.25 * xx + 0.5 * yy,
        ],
        axis=-1,
    )
    return xyz, np.ones((h, w), dtype=bool)


def _striped_slab(axis="u", phase=0.0):
    y, x = np.meshgrid(np.arange(25), np.arange(25), indexing="ij")
    slabs = []
    for depth in range(5):
        if axis == "u":
            wave = np.sin(2.0 * np.pi * (x + phase + 0.25 * depth) / 6.0)
        elif axis == "v":
            wave = np.sin(2.0 * np.pi * (y + phase + 0.25 * depth) / 6.0)
        else:
            raise ValueError(axis)
        cross = 0.2 * np.cos(2.0 * np.pi * (x + y + depth) / 11.0)
        slabs.append(128.0 + 38.0 * wave + 9.0 * cross)
    return np.stack(slabs, axis=0)


def test_tangent_frame_is_orthonormal_and_right_handed():
    xyz, valid = _plane()
    frame = tangent_frame_xyz(xyz, valid, 5, 6)
    assert frame is not None
    axes = [frame.x_axis_xyz, frame.y_axis_xyz, frame.normal_xyz]
    for axis in axes:
        assert np.linalg.norm(axis) == pytest.approx(1.0)
    assert np.dot(axes[0], axes[1]) == pytest.approx(0.0, abs=1e-12)
    assert np.dot(axes[0], axes[2]) == pytest.approx(0.0, abs=1e-12)
    assert np.dot(axes[1], axes[2]) == pytest.approx(0.0, abs=1e-12)
    np.testing.assert_allclose(
        np.cross(frame.x_axis_xyz, frame.y_axis_xyz),
        frame.normal_xyz,
        atol=1e-12,
        rtol=0,
    )


def test_translated_frame_preserves_orientation():
    xyz, valid = _plane()
    frame = tangent_frame_xyz(xyz, valid, 5, 6)
    assert frame is not None
    moved = translated_frame(frame, [1.0, 2.0, 3.0])
    np.testing.assert_allclose(moved.origin_xyz, [1.0, 2.0, 3.0])
    np.testing.assert_allclose(moved.x_axis_xyz, frame.x_axis_xyz)
    np.testing.assert_allclose(moved.y_axis_xyz, frame.y_axis_xyz)
    np.testing.assert_allclose(moved.normal_xyz, frame.normal_xyz)


def test_tangent_sample_coordinate_shape_and_center():
    xyz, valid = _plane()
    frame = tangent_frame_xyz(xyz, valid, 5, 6)
    assert frame is not None
    coords, shape = tangent_sample_coordinates_zyx(
        frame,
        in_plane_offsets=range(-1, 2),
        normal_offsets=[-2, 0, 2],
    )
    assert shape == (3, 3, 3)
    assert coords.shape == (27, 3)
    center = coords.reshape(shape + (3,))[1, 1, 1]
    np.testing.assert_allclose(center, frame.origin_xyz[::-1], atol=1e-12)


def test_descriptor_dimension_unit_norm_and_phase_tolerance():
    a, report_a = tangent_fiber_spectrum_descriptor(_striped_slab("u", 0.0))
    b, report_b = tangent_fiber_spectrum_descriptor(_striped_slab("u", 1.25))
    c, _ = tangent_fiber_spectrum_descriptor(_striped_slab("v", 0.0))
    assert a.shape == (260,)
    assert report_a["dimension"] == 260
    assert report_b["dimension"] == 260
    assert np.linalg.norm(a) == pytest.approx(1.0)
    assert np.linalg.norm(b) == pytest.approx(1.0)
    same_orientation = cosine_distance(a, b)
    orthogonal_orientation = cosine_distance(a, c)
    assert same_orientation < orthogonal_orientation
    assert orthogonal_orientation - same_orientation > 0.05


def test_descriptor_rejects_sparse_or_degenerate_slab():
    sparse = np.zeros((5, 25, 25), dtype=float)
    sparse[:, 10:15, 10:15] = 100.0
    with pytest.raises(FiberFingerprintError, match="nonzero fraction"):
        tangent_fiber_spectrum_descriptor(sparse)

    constant = np.full((5, 25, 25), 128.0)
    with pytest.raises(FiberFingerprintError, match="IQR"):
        tangent_fiber_spectrum_descriptor(
            constant,
            minimum_nonzero_fraction=0.0,
        )


def test_cosine_distance_identity_and_symmetry():
    a, _ = tangent_fiber_spectrum_descriptor(_striped_slab("u", 0.0))
    b, _ = tangent_fiber_spectrum_descriptor(_striped_slab("v", 0.0))
    assert cosine_distance(a, a) == pytest.approx(0.0, abs=1e-12)
    assert cosine_distance(a, b) == pytest.approx(cosine_distance(b, a))
