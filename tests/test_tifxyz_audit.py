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
        # horizontally and 0.4x compression vertically. Area remains exactly
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


def _write_selfcross_report(
    tmp_path,
    surface,
    *,
    transverse=0,
    dropped=0,
    declared_surface=None,
    wrong_grid=False,
):
    contacts = [
        {
            "quad1": [0, 0],
            "quad2": [3, 3],
            "tri1": 0,
            "tri2": 1,
            "penetration_vx": 0.25,
            "angle_deg": 45.0,
            "site": [1.0, 2.0, 10.0],
        }
        for _ in range(transverse)
    ]
    report = {
        "tool": "vc_tifxyz_selfcross",
        "report_only": True,
        "surface": str(surface.resolve()) if declared_surface is None else str(declared_surface),
        "clean_of_transverse_self_intersection": transverse == 0,
        "parameters": {
            "exclude": 1,
            "maxedge": 60.0,
            "cell": 40.0,
            "touch_tolerance": 1e-5,
            "diagonals": [0, 1],
        },
        "grid_rows": 6 if wrong_grid else 5,
        "grid_cols": 5,
        "census": [
            {
                "diagonal": 0,
                "triangles": 32,
                "quads_dropped_for_edge_length": dropped,
                "pairs_tested": 100,
                "transverse": transverse,
                "coplanar": 2,
                "grazing": 1,
                "transverse_contacts": contacts,
            },
            {
                "diagonal": 1,
                "triangles": 32,
                "quads_dropped_for_edge_length": 0,
                "pairs_tested": 100,
                "transverse": 0,
                "coplanar": 0,
                "grazing": 0,
                "transverse_contacts": [],
            },
        ],
    }
    path = tmp_path / "selfcross.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return path


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


def test_clean_official_selfcross_report_closes_nonlocal_intersection_gap(tmp_path):
    surface = _write_tifxyz(tmp_path)
    report = _write_selfcross_report(tmp_path, surface)

    result = audit_tifxyz(surface, selfcross_report=report)

    assert result["status"] == "pass"
    assert result["self_intersection"]["status"] == "pass"
    assert result["self_intersection"]["clean_of_transverse_self_intersection"] is True
    assert result["self_intersection"]["transverse_contacts"] == 0
    assert result["self_intersection"]["coplanar_contacts"] == 2
    assert len(result["self_intersection"]["report_sha256"]) == 64
    assert "validated upstream VC3D" in result["limitation"]


def test_official_selfcross_transverse_contact_blocks_mesh(tmp_path):
    surface = _write_tifxyz(tmp_path)
    report = _write_selfcross_report(tmp_path, surface, transverse=1)

    result = audit_tifxyz(surface, selfcross_report=report)

    assert result["status"] == "fail"
    assert result["self_intersection"]["status"] == "fail"
    assert result["self_intersection"]["transverse_contacts"] == 1
    assert any(item["kind"] == "self-intersection" for item in result["findings"])
    assert any("non-adjacent transverse" in message for message in result["errors"])


def test_selfcross_report_must_bind_exact_surface_path_and_grid(tmp_path):
    surface = _write_tifxyz(tmp_path)
    report = _write_selfcross_report(
        tmp_path,
        surface,
        declared_surface=tmp_path / "different-surface",
        wrong_grid=True,
    )

    result = audit_tifxyz(surface, selfcross_report=report)

    assert result["status"] == "fail"
    assert result["self_intersection"]["surface_path_matches"] is False
    assert any("different TIFXYZ surface path" in message for message in result["errors"])
    assert any("grid shape" in message for message in result["errors"])


def test_selfcross_dropped_long_edge_quads_remain_partial_evidence(tmp_path):
    surface = _write_tifxyz(tmp_path)
    report = _write_selfcross_report(tmp_path, surface, dropped=2)

    result = audit_tifxyz(surface, selfcross_report=report)

    assert result["status"] == "partial"
    assert result["self_intersection"]["status"] == "partial"
    assert result["self_intersection"]["quads_dropped_for_edge_length"] == 2
    assert any("clean verdict does not cover" in message for message in result["warnings"])


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
