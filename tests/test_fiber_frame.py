from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from scrollq.fiber_frame import (
    FiberFrameError,
    analyze_slab,
    frame_distance_degrees,
    main,
)


def _wave(angle_degrees: float, height: int, width: int, period: float = 8.0):
    y, x = np.mgrid[0:height, 0:width]
    angle = np.deg2rad(angle_degrees)
    phase = x * np.cos(angle) + y * np.sin(angle)
    return np.sin(2.0 * np.pi * phase / period)


def _cross_ply_slab(*, switch: bool = False) -> np.ndarray:
    depth, height, width = 8, 64, 64
    slab = np.empty((depth, height, width), dtype=np.float64)
    for z in range(depth):
        base_angle = 0.0 if z < depth // 2 else 90.0
        image = _wave(base_angle, height, width)
        if switch:
            changed = _wave(base_angle + 35.0, height, width)
            image[:, width // 2 :] = changed[:, width // 2 :]
        slab[z] = image
    return slab


def _xyz(height: int = 64, width: int = 64) -> np.ndarray:
    y, x = np.mgrid[0:height, 0:width]
    return np.stack([x, y, np.full_like(x, 12)], axis=-1).astype(np.float64)


def test_unordered_frame_distance_is_swap_invariant():
    assert frame_distance_degrees((10.0, 100.0), (100.0, 10.0)) == pytest.approx(0.0)
    assert frame_distance_degrees((0.0, 90.0), (35.0, 125.0)) == pytest.approx(35.0)


def test_uniform_cross_ply_field_has_no_switch_findings():
    report = analyze_slab(_cross_ply_slab(), tile_size=16, switch_degrees=25.0)

    assert report["status"] == "measured"
    assert report["coverage"]["valid_tiles"] == 16
    assert report["coverage"]["flagged_comparisons"] == 0
    assert report["findings"] == []


def test_injected_sheet_switch_is_localized_to_the_splice_boundary():
    report = analyze_slab(
        _cross_ply_slab(switch=True),
        xyz=_xyz(),
        tile_size=16,
        switch_degrees=25.0,
    )

    assert report["status"] == "measured"
    assert report["coverage"]["flagged_comparisons"] == 4
    assert len(report["review_queue"]) == 4
    assert {row["tile_a"][1] for row in report["findings"]} == {1}
    assert {row["tile_b"][1] for row in report["findings"]} == {2}
    assert all(row["frame_delta_degrees"] > 30.0 for row in report["findings"])
    assert all(len(row["xyz"]) == 3 for row in report["review_queue"])


def test_constant_slab_fails_closed_as_insufficient():
    report = analyze_slab(np.zeros((8, 64, 64)), tile_size=16)

    assert report["status"] == "insufficient"
    assert report["coverage"]["valid_tiles"] == 0
    assert report["findings"] == []


def test_invalid_xyz_shape_and_thresholds_fail():
    slab = _cross_ply_slab()
    with pytest.raises(FiberFrameError, match="xyz"):
        analyze_slab(slab, xyz=np.zeros((64, 64, 2)), tile_size=16)
    with pytest.raises(FiberFrameError, match="switch_degrees"):
        analyze_slab(slab, tile_size=16, switch_degrees=0)


def test_cli_hashes_inputs_and_emits_vc3d_ready_review_queue(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    source = tmp_path / "slab.npz"
    np.savez(source, slab=_cross_ply_slab(switch=True), xyz=_xyz())
    manifest = tmp_path / "sampling.json"
    manifest.write_text(
        json.dumps(
            {
                "normal_convention": "synthetic-test",
                "tangent_frame": "yx",
                "interpolation": "none",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "report.json"

    status = main(
        [
            "--input",
            str(source),
            "--volume-root",
            "synthetic-volume",
            "--surface-geometry-sha256",
            "a" * 64,
            "--sampling-manifest",
            str(manifest),
            "--tile-size",
            "16",
            "--out",
            str(output),
        ]
    )

    assert status == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["classification"] == "EXPERIMENT FURTHER"
    assert report["experimental_evidence_ready"] is True
    assert report["analysis"]["vc3d_review_ready"] is True
    assert report["input"]["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert report["surface"]["sampling_manifest"]["sha256"] == hashlib.sha256(
        manifest.read_bytes()
    ).hexdigest()
    assert "flagged neighbor comparisons" in capsys.readouterr().out

    assert main(
        [
            "--input",
            str(source),
            "--volume-root",
            "synthetic-volume",
            "--surface-geometry-sha256",
            "a" * 64,
            "--sampling-manifest",
            str(manifest),
            "--tile-size",
            "16",
            "--out",
            str(output),
        ]
    ) == 2
