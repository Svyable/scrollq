"""Interpret Vesuvius ``transform.json`` registrations between two scans.

A rescan's ``transform.json`` stores a 3x4 affine matrix plus matching
``fixed_landmarks`` / ``moving_landmarks``. The file does not say which way
the matrix maps or in which axis order, so this module *measures* it: all four
(direction, axis-order) hypotheses are scored by mean landmark residual and
the best one is accepted only if it clearly beats the others. Coordinates are
level-0 voxel indices of the respective volume.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


class RegistrationError(ValueError):
    """The transform is malformed or its interpretation is ambiguous."""


@dataclass(frozen=True)
class Registration:
    matrix: np.ndarray            # 3x4 as stored
    direction: str                # "moving_to_fixed" | "fixed_to_moving"
    axis_order: str               # "xyz" | "zyx" (order the matrix expects)
    fixed_name: str
    residual_mean: float          # destination-frame level-0 voxels
    residual_max: float
    n_landmarks: int
    runner_up_residual: float     # best residual among rejected hypotheses

    @property
    def linear(self) -> np.ndarray:
        return self.matrix[:, :3]

    @property
    def scale(self) -> float:
        """Isotropic scale ``det(A)^(1/3)`` of the stored matrix."""
        return float(abs(np.linalg.det(self.linear)) ** (1.0 / 3.0))

    def _apply(self, pts: np.ndarray, inverse: bool) -> np.ndarray:
        a, b = self.linear, self.matrix[:, 3]
        if self.axis_order == "zyx":
            pts = pts[:, ::-1]
        out = ((pts - b) @ np.linalg.inv(a).T) if inverse else pts @ a.T + b
        return out[:, ::-1] if self.axis_order == "zyx" else out

    def fixed_to_moving(self, pts_xyz: np.ndarray) -> np.ndarray:
        """Map ``(N,3)`` fixed-frame ``x,y,z`` to moving-frame ``x,y,z``."""
        pts = np.asarray(pts_xyz, dtype=np.float64).reshape(-1, 3)
        inverse = self.direction == "moving_to_fixed"
        return self._apply(pts, inverse=inverse)

    def lattice_rotation(self) -> np.ndarray:
        """Rotation taking the moving scan's voxel axes into the fixed frame.

        Columns are the images of the moving ``x, y, z`` unit steps in fixed
        voxel units, reduced to their orthogonal (polar) factor. A grid
        aligned with the fixed frame is rotated by the inverse of this
        relative to the moving scan's own voxel lattice.
        """
        origin = self.moving_to_fixed(np.zeros((1, 3)))[0]
        axes = (self.moving_to_fixed(np.eye(3)) - origin).T  # columns
        u, _, vt = np.linalg.svd(axes)
        q = u @ vt
        if np.linalg.det(q) < 0:  # a reflection cannot be a lattice rotation
            u[:, -1] *= -1
            q = u @ vt
        return q

    def moving_to_fixed(self, pts_xyz: np.ndarray) -> np.ndarray:
        pts = np.asarray(pts_xyz, dtype=np.float64).reshape(-1, 3)
        inverse = self.direction == "fixed_to_moving"
        return self._apply(pts, inverse=inverse)


def _hypothesis_residuals(m: np.ndarray, fixed: np.ndarray,
                          moving: np.ndarray) -> dict:
    a, b = m[:, :3], m[:, 3]
    out = {}
    for direction, src, dst in (("moving_to_fixed", moving, fixed),
                                ("fixed_to_moving", fixed, moving)):
        for order in ("xyz", "zyx"):
            s = src if order == "xyz" else src[:, ::-1]
            d = dst if order == "xyz" else dst[:, ::-1]
            err = np.linalg.norm(s @ a.T + b - d, axis=1)
            out[(direction, order)] = (float(err.mean()), float(err.max()))
    return out


def infer_registration(doc: dict, *, min_landmarks: int = 4,
                       ambiguity_ratio: float = 0.2) -> Registration:
    """Build a :class:`Registration` from a parsed ``transform.json``.

    The winning hypothesis must have a mean residual below
    ``ambiguity_ratio`` times the runner-up's, otherwise the registration is
    rejected as ambiguous rather than guessed.
    """
    try:
        m = np.array(doc["transformation_matrix"], dtype=np.float64)
        fixed = np.array(doc["fixed_landmarks"], dtype=np.float64)
        moving = np.array(doc["moving_landmarks"], dtype=np.float64)
    except (KeyError, TypeError, ValueError) as exc:
        raise RegistrationError(f"malformed transform: {exc}") from exc
    if m.shape != (3, 4):
        raise RegistrationError(f"matrix shape {m.shape} != (3, 4)")
    if fixed.shape != moving.shape or fixed.ndim != 2 or fixed.shape[1] != 3:
        raise RegistrationError("landmark arrays must both be (N, 3)")
    if len(fixed) < min_landmarks:
        raise RegistrationError(
            f"{len(fixed)} landmarks < required {min_landmarks}")
    if not (np.isfinite(m).all() and np.isfinite(fixed).all()
            and np.isfinite(moving).all()):
        raise RegistrationError("non-finite values in transform")
    if abs(np.linalg.det(m[:, :3])) < 1e-12:
        raise RegistrationError("singular linear part")

    res = _hypothesis_residuals(m, fixed, moving)
    ranked = sorted(res.items(), key=lambda kv: kv[1][0])
    (direction, order), (mean, mx) = ranked[0]
    runner = ranked[1][1][0]
    if not mean < ambiguity_ratio * runner:
        raise RegistrationError(
            f"ambiguous registration: best residual {mean:.2f} vs "
            f"runner-up {runner:.2f}")
    return Registration(
        matrix=m, direction=direction, axis_order=order,
        fixed_name=str(doc.get("fixed_volume", "")), residual_mean=mean,
        residual_max=mx, n_landmarks=len(fixed), runner_up_residual=runner)
