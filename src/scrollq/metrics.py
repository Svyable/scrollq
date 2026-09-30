"""Per-chunk quality metrics from decoded voxels.

All metrics are computed on a decoded uint8 chunk (any shape). They are
*descriptive* — no claim is made that any one of them measures ink or
readability directly. Together they form a triage signal: volumes with
strong texture energy, healthy dynamic range, and no acquisition
artifacts deserve segmentation effort first.
"""

from __future__ import annotations

import numpy as np


def chunk_metrics(vox: np.ndarray) -> dict:
    """Compute quality metrics for one decoded chunk.

    ``vox``: any-shape uint8 ndarray.
    """
    a = np.ascontiguousarray(vox, dtype=np.uint8).astype(np.float32)
    n = a.size
    nz = int((a != 0).sum())
    p1, p50, p99 = (float(v) for v in np.percentile(a, (1, 50, 99)))
    # Texture / edge energy: mean absolute neighbor difference along each
    # axis. Flat regions (air, solid fill) score ~0; papyrus texture and
    # ink boundaries score higher.
    gx = float(np.abs(np.diff(a, axis=-1)).mean()) if a.shape[-1] > 1 else 0.0
    gy = float(np.abs(np.diff(a, axis=-2)).mean()) if a.shape[-2] > 1 else 0.0
    gz = float(np.abs(np.diff(a, axis=-3)).mean()) if a.shape[-3] > 1 else 0.0
    grad = (gx + gy + gz) / 3.0
    # Dead slices: isolated all-zero z-planes inside densely populated
    # chunks — the signature of an acquisition dropout. Both neighbors
    # must be densely populated, otherwise a masked gap between two
    # scroll pieces (legitimate mask geometry) would false-positive.
    dead_slices = 0
    if a.ndim == 3 and nz > 0.5 * n:
        plane_frac = (a != 0).reshape(a.shape[0], -1).mean(axis=1)
        for z in range(1, a.shape[0] - 1):
            if (plane_frac[z] == 0 and plane_frac[z - 1] > 0.5
                    and plane_frac[z + 1] > 0.5):
                dead_slices += 1
    return {
        "n": int(n),
        "nonzero_frac": nz / n,
        "mean": float(a.mean()),
        "std": float(a.std()),
        "p1": p1,
        "p50": p50,
        "p99": p99,
        "dyn_range": p99 - p1,
        "sat_frac": float((a == 255).mean()),
        "grad_energy": grad,
        "dead_slices": dead_slices,
    }
