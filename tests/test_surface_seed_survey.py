from pathlib import Path

import numpy as np
import pytest

from scrollq.surface_seed_survey import (
    SeedSurveyError,
    _read_bbox,
    _volume_guard,
    survey_seed_boxes,
    write_selected_cutouts,
)


class FakeLevel:
    def __init__(self, arr, chunks):
        self.arr = np.asarray(arr, dtype=np.uint8)
        self.shape = self.arr.shape
        self.chunks = tuple(chunks)
        self.reads = 0

    def chunk(self, idx):
        self.reads += 1
        lo = [idx[d] * self.chunks[d] for d in range(3)]
        if any(lo[d] >= self.shape[d] for d in range(3)):
            return None
        hi = [
            min(lo[d] + self.chunks[d], self.shape[d])
            for d in range(3)
        ]
        sl = tuple(slice(lo[d], hi[d]) for d in range(3))
        chunk = self.arr[sl]
        return None if not np.any(chunk) else chunk.copy()


def test_read_bbox_crosses_chunk_boundaries_and_treats_missing_as_zero():
    arr = np.zeros((6, 6, 6), dtype=np.uint8)
    arr[1:5, 1:5, 1:5] = 7
    level = FakeLevel(arr, (2, 2, 2))
    got = _read_bbox(level, [1, 1, 1], [5, 5, 5])
    np.testing.assert_array_equal(got, arr[1:5, 1:5, 1:5])


def test_survey_ranks_local_ct_support_and_spatially_thins():
    shape = (4, 12, 12)
    pred = np.zeros(shape, dtype=np.uint8)
    ct = np.zeros(shape, dtype=np.uint8)

    for y, x in ((0, 0), (0, 4), (4, 0), (8, 8)):
        pred[:, y:y + 4, x:x + 4] = 255

    ct[:, 0:4, 0:4] = 100
    ct[:, 0:4, 4:8] = 100
    ct[:, 4:8, 0:2] = 100

    report = survey_seed_boxes(
        FakeLevel(pred, (4, 4, 4)),
        FakeLevel(ct, (2, 2, 2)),
        z0=0,
        z1=4,
        per_dim=3,
        prefilter=9,
        top_k=2,
        min_chunk_distance=1,
    )

    assert report["status"] == "ok"
    assert report["selected"][0]["surface_support_frac"] == 1.0
    assert report["selected"][0]["prediction_chunk_zyx"] == [0, 0, 0]
    assert report["selected"][1]["prediction_chunk_zyx"] == [0, 2, 2]
    assert all(
        row["requires_surface_seating"]
        for row in report["selected"]
    )


def test_shape_mismatch_fails_closed():
    pred = FakeLevel(
        np.zeros((4, 8, 8), dtype=np.uint8), (4, 4, 4)
    )
    ct = FakeLevel(
        np.zeros((5, 8, 8), dtype=np.uint8), (2, 2, 2)
    )
    with pytest.raises(SeedSurveyError, match="prediction shape"):
        survey_seed_boxes(pred, ct, z0=0, z1=4)


def test_exact_volume_guard_checks_both_urls():
    vid = "20250521151210"
    _volume_guard(
        f"https://x/PHerc0490A/representations/{vid}-surface-m7.zarr",
        f"https://x/PHerc0490A/volumes/{vid}-8.640um.zarr",
        vid,
    )
    with pytest.raises(SeedSurveyError, match="prediction URL"):
        _volume_guard(
            "https://x/PHerc0490A/representations/OTHER-surface-m7.zarr",
            f"https://x/PHerc0490A/volumes/{vid}-8.640um.zarr",
            vid,
        )


def test_selected_cutouts_are_hash_pinned(tmp_path: Path):
    pred_arr = np.ones((4, 4, 4), dtype=np.uint8) * 255
    ct_arr = np.ones((4, 4, 4), dtype=np.uint8) * 100
    pred = FakeLevel(pred_arr, (4, 4, 4))
    ct = FakeLevel(ct_arr, (2, 2, 2))
    report = survey_seed_boxes(
        pred,
        ct,
        z0=0,
        z1=4,
        per_dim=1,
        prefilter=1,
        top_k=1,
        min_chunk_distance=0,
    )
    write_selected_cutouts(report, pred, ct, tmp_path)

    cutouts = report["selected"][0]["cutouts"]
    for rec in cutouts.values():
        assert Path(rec["path"]).is_file()
        assert len(rec["sha256"]) == 64
    loaded = np.load(cutouts["ct"]["path"], allow_pickle=False)
    np.testing.assert_array_equal(loaded, ct_arr)
