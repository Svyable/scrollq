import json
from pathlib import Path

import numpy as np

from scrollq import sheetness


def _grid(n=21):
    z, y, x = np.mgrid[-10:11, -10:11, -10:11]
    return z.astype(float), y.astype(float), x.astype(float)


def test_plate_response_exceeds_tube_and_blob():
    z, y, x = _grid()
    plate = np.exp(-0.5 * (z / 1.0) ** 2)
    tube = np.exp(-0.5 * ((z / 1.0) ** 2 + (y / 1.0) ** 2))
    blob = np.exp(
        -0.5 * ((z / 1.0) ** 2 + (y / 1.0) ** 2 + (x / 1.0) ** 2)
    )

    def peak(arr):
        smoothed = sheetness.gaussian_smooth(arr, 1.0)
        response, _ = sheetness.plate_objectness(
            smoothed, sigma=1.0, beta=0.5, gamma=0.1
        )
        return float(response.max())

    assert peak(plate) > 0.8
    assert peak(plate) > peak(tube)
    assert peak(tube) > peak(blob)


def test_plate_normal_points_along_thin_axis():
    z, _, _ = _grid()
    plate = np.exp(-0.5 * (z / 1.0) ** 2)
    smoothed = sheetness.gaussian_smooth(plate, 1.0)
    response, normals = sheetness.plate_objectness(
        smoothed,
        sigma=1.0,
        beta=0.5,
        gamma=0.1,
        return_normals=True,
    )

    assert normals is not None
    center = normals[10, 10, 10]
    assert response[10, 10, 10] > 0.8
    assert abs(float(center[0])) > 0.99
    assert abs(float(center[1])) < 0.02
    assert abs(float(center[2])) < 0.02


def test_polarity_is_explicit():
    z, _, _ = _grid()
    bright_plate = np.exp(-0.5 * (z / 1.0) ** 2)
    dark_plate = 1.0 - bright_plate

    bright_response, _ = sheetness.plate_objectness(
        sheetness.gaussian_smooth(bright_plate, 1.0),
        sigma=1.0,
        gamma=0.1,
        bright_object=True,
    )
    wrong_polarity, _ = sheetness.plate_objectness(
        sheetness.gaussian_smooth(bright_plate, 1.0),
        sigma=1.0,
        gamma=0.1,
        bright_object=False,
    )
    dark_response, _ = sheetness.plate_objectness(
        sheetness.gaussian_smooth(dark_plate, 1.0),
        sigma=1.0,
        gamma=0.1,
        bright_object=False,
    )

    assert bright_response[10, 10, 10] > 0.8
    assert wrong_polarity[10, 10, 10] == 0.0
    assert dark_response[10, 10, 10] > 0.8


def test_multiscale_is_deterministic_and_records_winning_scale():
    z, _, _ = _grid()
    plate = np.exp(-0.5 * (z / 1.4) ** 2)

    a = sheetness.multiscale_sheetness(
        plate, sigmas=[0.8, 1.2, 1.8], gamma=0.1, normalize=False
    )
    b = sheetness.multiscale_sheetness(
        plate, sigmas=[0.8, 1.2, 1.8], gamma=0.1, normalize=False
    )

    np.testing.assert_array_equal(a[0], b[0])
    np.testing.assert_array_equal(a[1], b[1])
    assert set(np.unique(a[1])).issubset({0.8, 1.2, 1.8})
    assert a[3]["method"] == sheetness.METHOD


def test_cli_outputs_hash_pinned_arrays_and_caveat(tmp_path: Path):
    z, _, _ = _grid()
    volume = np.exp(-0.5 * (z / 1.0) ** 2).astype(np.float32)
    source = tmp_path / "cutout.npy"
    np.save(source, volume, allow_pickle=False)
    prefix = tmp_path / "out" / "plate"

    rc = sheetness.main(
        [
            str(source),
            "--out-prefix",
            str(prefix),
            "--sigmas",
            "1.0",
            "--gamma",
            "0.1",
            "--no-normalize",
            "--write-normal",
        ]
    )
    assert rc == 0

    report_path = Path(str(prefix) + ".sheetness.json")
    report = json.loads(report_path.read_text())
    assert report["kind"] == "sheetness"
    assert report["input"]["sha256"] == sheetness._sha256(source)
    assert "not by itself evidence of correct papyrus identity" in report["scope"]
    assert Path(report["response"]["output_path"]).exists()
    assert Path(report["winning_scale"]["output_path"]).exists()
    assert Path(report["normal"]["output_path"]).exists()


def test_memory_guard_fails_before_expensive_hessian(tmp_path: Path):
    source = tmp_path / "cutout.npy"
    np.save(source, np.zeros((8, 8, 8), dtype=np.uint8), allow_pickle=False)

    try:
        sheetness.run(
            source,
            tmp_path / "out",
            sigmas=[1.0],
            max_voxels=100,
        )
    except ValueError as exc:
        assert "above --max-voxels" in str(exc)
    else:
        raise AssertionError("expected max-voxel guard to reject the cutout")
