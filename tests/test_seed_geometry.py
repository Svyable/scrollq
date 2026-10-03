from pathlib import Path

import numpy as np
import pytest

from scrollq.seed_geometry import analyze, main


def test_seed_is_high_sheetness_mask_voxel_near_center():
    mask = np.zeros((5, 7, 7), dtype=np.uint8)
    mask[2, 1:6, 1:6] = 1
    score = np.zeros(mask.shape, dtype=np.float32)
    score[2, 1:6, 1:6] = 0.5
    score[2, 3, 3] = 0.9
    score[2, 1, 1] = 1.0
    normal = np.zeros(mask.shape + (3,), dtype=np.float32)
    normal[..., 0] = 2.0

    result = analyze(
        mask,
        score,
        normal,
        bbox_origin_zyx=(100, 200, 300),
        candidate_quantile=0.90,
    )

    assert result["selected_seed"]["local_zyx"] == [2, 3, 3]
    assert result["selected_seed"]["global_zyx"] == [102, 203, 303]
    assert result["selected_seed"]["normal_zyx"] == [1.0, 0.0, 0.0]


def test_seed_tie_break_is_deterministic():
    mask = np.ones((3, 3, 3), dtype=np.uint8)
    score = np.ones((3, 3, 3), dtype=np.float32)
    normal = np.zeros((3, 3, 3, 3), dtype=np.float32)
    normal[..., 2] = 1
    a = analyze(
        mask,
        score,
        normal,
        bbox_origin_zyx=(0, 0, 0),
        candidate_quantile=1.0,
    )
    b = analyze(
        mask,
        score,
        normal,
        bbox_origin_zyx=(0, 0, 0),
        candidate_quantile=1.0,
    )
    assert a["selected_seed"] == b["selected_seed"]
    assert a["selected_seed"]["local_zyx"] == [1, 1, 1]


def test_shape_mismatch_fails_closed():
    with pytest.raises(ValueError, match="shapes differ"):
        analyze(
            np.ones((3, 3, 3)),
            np.ones((3, 3, 4)),
            np.ones((3, 3, 4, 3)),
            bbox_origin_zyx=(0, 0, 0),
        )


def test_cli_hash_pins_inputs(tmp_path: Path):
    mask = np.zeros((5, 5, 5), dtype=np.uint8)
    mask[2, 2, 2] = 1
    score = np.zeros((5, 5, 5), dtype=np.float32)
    score[2, 2, 2] = 1.0
    normal = np.zeros((5, 5, 5, 3), dtype=np.float32)
    normal[2, 2, 2] = [0, 1, 0]
    mp = tmp_path / "mask.npy"
    sp = tmp_path / "sheetness.npy"
    npth = tmp_path / "normal.npy"
    out = tmp_path / "out.json"
    np.save(mp, mask, allow_pickle=False)
    np.save(sp, score, allow_pickle=False)
    np.save(npth, normal, allow_pickle=False)

    assert main([
        "--surface-mask", str(mp),
        "--sheetness", str(sp),
        "--normal", str(npth),
        "--bbox-origin", "10,20,30",
        "--out", str(out),
    ]) == 0
    import json
    report = json.loads(out.read_text())
    assert report["selected_seed"]["global_zyx"] == [12, 22, 32]
    assert len(report["inputs"]["surface_mask"]["sha256"]) == 64
