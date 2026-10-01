import hashlib
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


def _sha256(path):
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _write_surface_preflight_report(
    tmp_path,
    surface,
    *,
    volume_root="volume-A",
    declared_surface=None,
    declared_volume=None,
    meta_sha256=None,
    fail_gate=None,
    omit_gate=None,
    schema_version=2,
):
    gate_names = [
        "tifxyz_required_files",
        "tifxyz_metadata",
        "tifxyz_coordinate_shapes",
        "volume_is_3d",
        "valid_surface_vertices",
        "valid_surface_quads",
        "finite_selected_coordinates",
        "coordinates_within_volume",
        "tifxyz_scale_consistency",
        "sampled_volume_signal_support",
    ]
    gates = []
    for name in gate_names:
        if name == omit_gate:
            continue
        gates.append(
            {
                "name": name,
                "required": True,
                "passed": name != fail_gate,
                "observed": {},
                "threshold": None,
                "message": "fixture",
            }
        )
    passed_count = sum(gate["passed"] for gate in gates)
    report = {
        "schema_version": schema_version,
        "status": "PASS" if fail_gate is None else "FAIL",
        "surface": {
            "path": (
                str(surface.resolve())
                if declared_surface is None
                else str(declared_surface)
            ),
            "scale_xy": [0.5, 0.5],
            "meta_sha256": (
                _sha256(surface / "meta.json")
                if meta_sha256 is None
                else meta_sha256
            ),
            "stored_shape_yx": [5, 5],
            "valid_vertex_count": 25,
        },
        "volume": {
            "path": volume_root if declared_volume is None else declared_volume,
            "resolved_array_key": "0",
            "shape_zyx": [32, 32, 32],
            "sampled_signal_support": {
                "sample_count": 25,
                "supported_count": 25,
                "support_fraction": 1.0,
            },
        },
        "configuration": {
            "minimum_support_fraction": 0.95,
            "support_threshold": 0.0,
        },
        "gates": gates,
        "summary": {
            "passed_required_gates": passed_count,
            "required_gate_count": len(gates),
        },
    }
    path = tmp_path / "surface-preflight.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return path


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


def test_clean_official_surface_preflight_binds_ct_support(tmp_path):
    surface = _write_tifxyz(tmp_path)
    report = _write_surface_preflight_report(tmp_path, surface)

    result = audit_tifxyz(
        surface,
        volume_root="volume-A",
        surface_preflight_report=report,
    )

    assert result["status"] == "pass"
    assert result["ct_preflight"]["status"] == "pass"
    assert result["ct_preflight"]["volume_root_matches"] is True
    assert result["ct_preflight"]["sampled_signal_support"]["support_fraction"] == 1.0
    assert len(result["ct_preflight"]["report_sha256"]) == 64
    assert "validated upstream Villa surface preflight" in result["limitation"]


def test_surface_preflight_fails_closed_on_surface_or_volume_mismatch(tmp_path):
    surface = _write_tifxyz(tmp_path)
    report = _write_surface_preflight_report(
        tmp_path,
        surface,
        declared_surface=tmp_path / "other-surface",
        declared_volume="volume-B",
        meta_sha256="0" * 64,
    )

    result = audit_tifxyz(
        surface,
        volume_root="volume-A",
        surface_preflight_report=report,
    )

    assert result["status"] == "fail"
    assert result["ct_preflight"]["status"] == "fail"
    assert result["ct_preflight"]["surface_path_matches"] is False
    assert result["ct_preflight"]["volume_root_matches"] is False
    assert any("meta.json SHA-256" in message for message in result["errors"])
    assert any("different CT volume root" in message for message in result["errors"])


def test_surface_preflight_requires_ct_gates_and_volume_binding(tmp_path):
    surface = _write_tifxyz(tmp_path)
    report = _write_surface_preflight_report(
        tmp_path,
        surface,
        omit_gate="sampled_volume_signal_support",
    )

    result = audit_tifxyz(surface, surface_preflight_report=report)

    assert result["status"] == "fail"
    assert result["ct_preflight"]["status"] == "fail"
    assert any("--volume-root" in message for message in result["errors"])
    assert any("sampled_volume_signal_support" in message for message in result["errors"])


def test_failed_official_surface_preflight_blocks_mesh(tmp_path):
    surface = _write_tifxyz(tmp_path)
    report = _write_surface_preflight_report(
        tmp_path,
        surface,
        fail_gate="sampled_volume_signal_support",
    )

    result = audit_tifxyz(
        surface,
        volume_root="volume-A",
        surface_preflight_report=report,
    )

    assert result["status"] == "fail"
    assert result["ct_preflight"]["status"] == "fail"
    assert result["ct_preflight"]["failed_gates"] == ["sampled_volume_signal_support"]
    assert any(item["kind"] == "surface-preflight" for item in result["findings"])


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
