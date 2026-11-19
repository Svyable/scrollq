"""Row-block evaluation of the TIFXYZ audit must not change any reported value.

The audit evaluates edge, quad and review-queue metrics in row blocks so the
largest published meshes fit in memory. Every block size has to give the
same report, byte for byte, as evaluating the grid in one block.
"""

import json

import numpy as np
import pytest
from PIL import Image

from scrollq.tifxyz_audit import _block_rows, audit_tifxyz


def _write(tmp_path, xyz, name="s"):
    root = tmp_path / f"{name}.tifxyz"
    root.mkdir()
    for i, axis in enumerate("xyz"):
        Image.fromarray(np.ascontiguousarray(xyz[..., i], dtype=np.float32)).save(root / f"{axis}.tif")
    valid = xyz[..., 2] > 0
    pts = xyz[valid]
    bbox = [pts.min(axis=0).tolist(), pts.max(axis=0).tolist()]
    (root / "meta.json").write_text(json.dumps({"format": "tifxyz", "scale": [0.5, 0.5], "bbox": bbox}))
    return root


def _surface(seed, h=23, w=17):
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    xyz = np.stack([xx * 2, yy * 2, 10 + rng.normal(0, 0.3, (h, w))], axis=-1).astype(np.float32)
    # holes, a detached island, a fold, and a few spikes, spread across rows
    xyz[5:8, 4:7] = -1
    xyz[:, 11] = -1
    xyz[15, 2:5] = -1
    xyz[18:21, 3:9, 2] = 30 - xyz[18:21, 3:9, 2]   # flip a patch: folds
    xyz[12:14, 13:15, 0] *= -1                      # reversed normals
    for r, c in rng.integers(1, [h - 1, w - 1], size=(6, 2)):
        if xyz[r, c, 2] > 0:
            xyz[r, c, 2] += 80                      # edge jumps
    return xyz


def _report(root, **kw):
    r = audit_tifxyz(root, review_limit_per_kind=50, **kw)
    r.pop("tifxyz_path", None)
    return json.dumps(r, sort_keys=True)


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_every_block_size_gives_the_same_report(tmp_path, seed):
    root = _write(tmp_path, _surface(seed), name=f"s{seed}")
    whole = _report(root, block_rows=10**6)
    data = json.loads(whole)
    # the fixture must exercise every metric the blocks split
    kinds = {f["kind"] for f in data["findings"]}
    assert {"connectivity", "hole", "edge-jump", "normal-reversal"} <= kinds
    assert data["review_queue"]["total_candidates_by_kind"]["normal-reversal"] > 0
    assert data["review_queue"]["total_candidates_by_kind"]["edge-jump"] > 0
    for rows in (1, 2, 3, 5, 7, 22, 23, 24):
        assert _report(root, block_rows=rows) == whole, rows
    assert _report(root) == whole


def test_review_queue_ranking_survives_truncation(tmp_path):
    root = _write(tmp_path, _surface(4))
    full = json.loads(_report(root, block_rows=10**6))["review_queue"]["candidates"]
    r = audit_tifxyz(root, review_limit_per_kind=3, block_rows=2)
    top = r["review_queue"]["candidates"]
    for kind in ("edge-jump", "normal-reversal"):
        want = [c for c in full if c["kind"] == kind][:3]
        assert [c for c in top if c["kind"] == kind] == want


def test_single_row_and_single_column_grids(tmp_path):
    row = np.stack(np.broadcast_arrays(np.arange(9, dtype=np.float32)[None] * 2,
                                       np.zeros((1, 9), np.float32), np.full((1, 9), 5, np.float32)), -1)
    root = _write(tmp_path, row, name="row")
    assert _report(root, block_rows=1) == _report(root, block_rows=10**6)
    col = np.ascontiguousarray(row.transpose(1, 0, 2)[..., [1, 0, 2]])
    root = _write(tmp_path, col, name="col")
    assert _report(root, block_rows=1) == _report(root, block_rows=10**6)


def test_block_rows_default_and_validation():
    assert _block_rows((10, 1000), None) == 2000
    assert _block_rows((10, 10**8), None) == 1
    assert _block_rows((10, 1000), 4) == 4
    with pytest.raises(ValueError):
        _block_rows((10, 10), 0)
