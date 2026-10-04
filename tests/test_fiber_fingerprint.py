import numpy as np
import pytest

from scrollq import fiber_fingerprint as ff


def _plane(size: int = 9):
    yy, xx = np.meshgrid(np.arange(size), np.arange(size), indexing="ij")
    xyz = np.stack(
        [20.0 * xx, 20.0 * yy, np.full_like(xx, 100.0, dtype=float)],
        axis=-1,
    )
    return xyz.astype(float), np.ones((size, size), dtype=bool)


def _texture(transpose: bool = False) -> np.ndarray:
    y, x = np.meshgrid(np.arange(25), np.arange(25), indexing="ij")
    base = (
        100.0
        + 35.0 * np.sin(2.0 * np.pi * x / 6.0)
        + 12.0 * np.cos(2.0 * np.pi * y / 11.0)
        + 0.8 * x
    )
    if transpose:
        base = base.T
    return np.stack([base + d * 3.0 for d in (-4, -2, 0, 2, 4)], axis=0)


def test_tangent_frame_is_right_handed_and_geometry_only():
    xyz, valid = _plane()
    center, x_axis, y_axis, normal = ff.tangent_frame(xyz, valid, 4, 4)

    assert np.allclose(center, [80.0, 80.0, 100.0])
    assert np.allclose(x_axis, [1.0, 0.0, 0.0])
    assert np.allclose(y_axis, [0.0, 1.0, 0.0])
    assert np.allclose(normal, [0.0, 0.0, 1.0])
    assert np.allclose(np.cross(x_axis, y_axis), normal)


def test_tangent_patch_coordinates_match_frozen_shape_and_offsets():
    coords = ff.tangent_patch_coordinates(
        np.array([10.0, 20.0, 30.0]),
        np.array([1.0, 0.0, 0.0]),
        np.array([0.0, 1.0, 0.0]),
        np.array([0.0, 0.0, 1.0]),
        in_plane_offsets=list(range(-12, 13)),
        normal_offsets=[-4, -2, 0, 2, 4],
    )

    assert coords.shape == (5, 25, 25, 3)
    assert np.allclose(coords[2, 12, 12], [10.0, 20.0, 30.0])
    assert np.allclose(coords[0, 0, 0], [-2.0, 8.0, 26.0])
    assert np.allclose(coords[-1, -1, -1], [22.0, 32.0, 34.0])


def test_descriptor_is_260_values_unit_norm_and_deterministic():
    patch = _texture()
    first = ff.tangent_fiber_spectrum(patch)
    second = ff.tangent_fiber_spectrum(patch.copy())

    assert first.shape == (260,)
    assert np.isclose(np.linalg.norm(first), 1.0)
    assert np.array_equal(first, second)
    assert ff.descriptor_sha256(first) == ff.descriptor_sha256(second)


def test_descriptor_responds_to_in_plane_texture_orientation():
    horizontal = ff.tangent_fiber_spectrum(_texture(False))
    rotated = ff.tangent_fiber_spectrum(_texture(True))

    assert ff.cosine_distance(horizontal, horizontal) == pytest.approx(0.0, abs=1e-12)
    assert ff.cosine_distance(horizontal, rotated) > 1e-3


def test_descriptor_rejects_degenerate_low_iqr_patch():
    with pytest.raises(ff.FiberFingerprintError, match="IQR"):
        ff.tangent_fiber_spectrum(np.full((5, 25, 25), 17.0))


def test_development_gate_passes_only_frozen_threshold_logic():
    groups = []
    for i in range(8):
        groups.append(
            {
                "id": f"g{i}",
                "status": "usable",
                "positive_distances": [0.08, 0.09, 0.10, 0.11],
                "wrong_wrap_score": 0.30 + 0.01 * i,
            }
        )

    result = ff.score_development(groups)

    assert result["status"] == "pass"
    assert result["usable_group_count"] == 8
    assert result["pooled_positive_pair_count"] == 32
    assert result["wrong_wrap_rejection_fraction"] == 1.0
    assert result["threshold"] == pytest.approx(
        np.quantile([0.08, 0.09, 0.10, 0.11] * 8, 0.95, method="linear")
    )
    assert all(result["checks"].values())


def test_development_gate_fails_without_adjacent_winding_separation():
    groups = []
    for i in range(8):
        groups.append(
            {
                "id": f"g{i}",
                "status": "usable",
                "positive_distances": [0.08, 0.09, 0.10, 0.11],
                "wrong_wrap_score": 0.07,
            }
        )

    result = ff.score_development(groups)

    assert result["status"] == "fail"
    assert result["checks"]["wrong_wrap_rejection_fraction"] is False
    assert result["checks"]["median_wrong_to_positive_distance_ratio"] is False
    assert result["checks"]["median_wrong_distance_above_threshold"] is False
