import numpy as np
import pytest

from scrollq.registration import RegistrationError, infer_registration


def _rot(deg_z=30.0, deg_x=10.0):
    a, b = np.deg2rad(deg_z), np.deg2rad(deg_x)
    rz = np.array([[np.cos(a), -np.sin(a), 0], [np.sin(a), np.cos(a), 0],
                   [0, 0, 1]])
    rx = np.array([[1, 0, 0], [0, np.cos(b), -np.sin(b)],
                   [0, np.sin(b), np.cos(b)]])
    return rz @ rx


def _doc(direction="moving_to_fixed", order="xyz", scale=0.47, n=8, seed=3,
         noise=0.0):
    rng = np.random.default_rng(seed)
    a = scale * _rot()
    b = np.array([120.0, -40.0, 300.0])
    moving = rng.uniform(0, 4000, (n, 3))
    fixed = moving @ a.T + b
    fixed = fixed + rng.normal(0, noise, fixed.shape)
    mat = np.hstack([a, b[:, None]])
    if direction == "fixed_to_moving":
        # same pair of landmark clouds, but the stored matrix maps fixed->moving
        a2 = np.linalg.inv(a)
        b2 = -a2 @ b
        mat = np.hstack([a2, b2[:, None]])
    if order == "zyx":
        # matrix expects reversed axes: P' = R P R with R the axis reversal
        r = np.eye(3)[::-1]
        mat = np.hstack([r @ mat[:, :3] @ r, (r @ mat[:, 3])[:, None]])
    return {"schema_version": "1.0.0", "fixed_volume": "fixed_masked",
            "transformation_matrix": mat.tolist(),
            "fixed_landmarks": fixed.tolist(),
            "moving_landmarks": moving.tolist()}, moving, fixed


@pytest.mark.parametrize("direction", ["moving_to_fixed", "fixed_to_moving"])
@pytest.mark.parametrize("order", ["xyz", "zyx"])
def test_direction_and_axis_order_are_inferred(direction, order):
    doc, moving, fixed = _doc(direction, order)
    reg = infer_registration(doc)
    assert (reg.direction, reg.axis_order) == (direction, order)
    assert reg.residual_mean < 1e-6
    # round trip through the public mapping helpers, whatever the convention
    assert np.allclose(reg.moving_to_fixed(moving), fixed, atol=1e-6)
    assert np.allclose(reg.fixed_to_moving(fixed), moving, atol=1e-6)
    assert reg.fixed_name == "fixed_masked"


def test_residual_reports_landmark_noise_in_voxels():
    doc, *_ = _doc(noise=2.0, n=40, seed=7)
    reg = infer_registration(doc)
    assert 1.0 < reg.residual_mean < 6.0
    assert reg.residual_max >= reg.residual_mean
    assert reg.n_landmarks == 40


def test_scale_is_det_cuberoot():
    doc, *_ = _doc(scale=0.47)
    assert infer_registration(doc).scale == pytest.approx(0.47, rel=1e-6)


def test_ambiguous_registration_is_rejected_not_guessed():
    # identity transform on identical landmark clouds: every hypothesis fits
    pts = np.random.default_rng(0).uniform(0, 100, (6, 3))
    doc = {"transformation_matrix": np.hstack([np.eye(3), np.zeros((3, 1))])
           .tolist(), "fixed_landmarks": pts.tolist(),
           "moving_landmarks": pts.tolist()}
    with pytest.raises(RegistrationError, match="ambiguous"):
        infer_registration(doc)


@pytest.mark.parametrize("mutate,msg", [
    (lambda d: d.pop("transformation_matrix"), "malformed"),
    (lambda d: d.update(fixed_landmarks=d["fixed_landmarks"][:3],
                        moving_landmarks=d["moving_landmarks"][:3]),
     "landmarks"),
    (lambda d: d.update(moving_landmarks=d["moving_landmarks"][:-1]),
     "both be"),
    (lambda d: d.update(transformation_matrix=[[0, 0, 0, 1]] * 3), "singular"),
    (lambda d: d["fixed_landmarks"][0].__setitem__(0, float("nan")),
     "non-finite"),
])
def test_malformed_transforms_fail_closed(mutate, msg):
    doc, *_ = _doc()
    mutate(doc)
    with pytest.raises(RegistrationError, match=msg):
        infer_registration(doc)
