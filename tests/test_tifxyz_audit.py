import json

import numpy as np
from PIL import Image

from scrollq.tifxyz_audit import audit_tifxyz


def _write_tifxyz(
    tmp_path,
    *,
    hole=False,
    stale_bbox=False,
    empty=False,
    high_res_mask=False,
    area_preserving_anisotropy=False,
):
    root = tmp_path / "surface"
    root.mkdir()
    yy, xx = np.mgrid[0:5, 0:5]
    if area_preserving_anisotropy:
        # Relative to the declared 2-voxel flat step, this is 2.5x stretch
        # horizontally and 0.4x compression vertically.  Area remains exactly
        # preserved (2.5 * 0.4 == 1), so an area-only metric cannot catch it.
        x = (xx * 5).astype(np.float32)
        y = (yy * 0.8).astype(np.float32)
    else:
        x = (xx * 2).astype(np.float32)
        y = (yy * 2).astype(np.float32)
    z = np.full((5, 5), 10.0, dtype=np.float32)
    if empty:
        x[:] = y[:] = z[:] = -1
    elif hole:
        x[2, 2] = y[2, 2] = z[2, 2] = -1

    for name, arr in (("x.tif", x), ("y.tif", y), ("z.tif", z)):
        Image.fromarray(arr).save(root / name)

    bbox = (
        [[0, 0, 10], [20, 3.2, 10]]
        if area_preserving_anisotropy
        else [[0, 0, 10], [8, 8, 10]]
    )
    if stale_bbox:
        bbox = [[100, 100, 100], [101, 101, 101]]
    (root / "meta.json").write_text(
        json.dumps({"format": "tifxyz", "scale": [0.5, 0.5], "bbox": bbox}),
        encoding="utf-8",
    )

    if high_res_mask:
        mask = np.full((10, 10), 255, dtype=np.uint8)
        mask[4:6, 4:6] = 0
        Image.fromarray(mask).save(root / "mask.tif")
    return root


def test_planar_tifxyz_passes_structure_spacing_and_distortion_checks(tmp_path):
    result = audit_tifxyz(_write_tifxyz(tmp_path), volume_root="volume-A")

    assert result["status"] == "pass"
    assert result["volume_root"] == "volume-A"
    assert result["grid"]["valid_vertex_components"]["components"] == 1
    assert result["grid"]["enclosed_invalid_components"] == 0
    assert result["spacing"]["columns"]["measured_to_nominal_ratio"] == 1.0
    assert result["spacing"]["rows"]["measured_to_nominal_ratio"] == 1.0
    assert result["quads"]["symmetric_area_distortion"]["median"] == 1.0
    assert result["quads"]["isometry"]["symmetric_stretch_distortion"]["median"] == 1.0
    assert result["quads"]["isometry"]["anisotropy"]["median"] == 1.0
    assert result["quads"]["normal_reversal_pairs"] == 0


def test_area_preserving_anisotropy_is_detected_as_non_isometric(tmp_path):
    result = audit_tifxyz(
        _write_tifxyz(tmp_path, area_preserving_anisotropy=True),
        spacing_tolerance_ratio=3.0,
    )

    assert np.isclose(result["quads"]["symmetric_area_distortion"]["median"], 1.0)
    assert np.isclose(
        result["quads"]["isometry"]["symmetric_stretch_distortion"]["p95"],
        2.5,
    )
    assert np.isclose(result["quads"]["isometry"]["anisotropy"]["median"], 6.25)
    assert result["status"] == "partial"
    assert any(item["kind"] == "isometry-distortion" for item in result["findings"])


def test_enclosed_hole_and_stale_bbox_are_review_findings(tmp_path):
    result = audit_tifxyz(
        _write_tifxyz(tmp_path, hole=True, stale_bbox=True),
        volume_root="volume-A",
    )

    assert result["status"] == "partial"
    assert result["grid"]["enclosed_invalid_components"] == 1
    assert result["bbox"]["contains_observed_vertices"] is False
    assert result["warning_count"] >= 2
    assert any(item["kind"] == "hole" for item in result["findings"])


def test_integer_multiple_mask_uses_tifxyz_validity_semantics(tmp_path):
    result = audit_tifxyz(_write_tifxyz(tmp_path, high_res_mask=True))

    assert result["grid"]["mask"]["applied"] is True
    assert result["grid"]["mask"]["integer_scale_xy"] == [2, 2]
    assert result["grid"]["valid_vertices"] == 24
    assert result["grid"]["enclosed_invalid_components"] == 1


def test_empty_surface_fails_closed(tmp_path):
    result = audit_tifxyz(_write_tifxyz(tmp_path, empty=True))

    assert result["status"] == "fail"
    assert result["grid"]["valid_vertices"] == 0
    assert any("no valid vertices" in message for message in result["errors"])
