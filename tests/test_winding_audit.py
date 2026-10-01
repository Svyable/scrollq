import json
from pathlib import Path

from scrollq.winding_audit import audit_dataset, audit_document, audit_file


def _doc(points, *, metadata=None, name="c"):
    collection = {"name": name, "points": points}
    if metadata is not None:
        collection["metadata"] = metadata
    return {
        "vc_pointcollections_json_version": "1",
        "collections": {"0": collection},
    }


def test_valid_relative_document_reports_constraint_span():
    report = audit_document(
        _doc(
            {
                "0": {"p": [1, 2, 3], "wind_a": 0},
                "1": {"p": [4, 5, 6], "wind_a": 2},
            }
        ),
        role="relative",
    )

    assert report["status"] == "pass"
    assert report["point_count"] == 2
    stats = report["collections"][0]["role_stats"]
    assert stats["winding_span"] == 2
    assert stats["ordered_edges"] == 1
    assert stats["nonzero_ordered_winding_steps"] == 1


def test_same_winding_rejects_wind_a():
    report = audit_document(
        _doc({"0": {"p": [1, 2, 3], "wind_a": 0}}),
        role="same_winding",
    )

    assert report["status"] == "fail"
    assert any(
        item["code"] == "WINDING_SAME_HAS_WIND_A"
        for item in report["findings"]
    )


def test_relative_requires_integer_wind_a():
    report = audit_document(
        _doc(
            {
                "0": {"p": [1, 2, 3], "wind_a": 0.5},
                "1": {"p": [4, 5, 6], "wind_a": 1},
            }
        ),
        role="relative",
    )

    assert report["status"] == "fail"
    assert any(
        item["code"] == "WINDING_INVALID_WIND_A"
        for item in report["findings"]
    )


def test_absolute_metadata_mismatch_warns_but_keeps_explicit_role():
    report = audit_document(
        _doc(
            {"0": {"p": [1, 2, 3], "wind_a": 7}},
            metadata={"winding_is_absolute": False},
        ),
        role="absolute",
    )

    assert report["status"] == "warn"
    assert report["annotated_point_count"] == 1
    assert any(
        item["code"] == "WINDING_ROLE_METADATA_MISMATCH"
        for item in report["findings"]
    )


def test_audit_file_hashes_exact_bytes(tmp_path: Path):
    path = tmp_path / "same_windings.json"
    path.write_text(
        json.dumps(_doc({"0": {"p": [1, 2, 3]}})),
        encoding="utf-8",
    )

    first = audit_file(path, role="same_winding")
    second = audit_file(path, role="same_winding")

    assert first["status"] == "pass"
    assert first["sha256"] == second["sha256"]
    assert len(first["sha256"]) == 64


def test_dataset_is_partial_when_optional_roles_are_missing(tmp_path: Path):
    (tmp_path / "same_windings.json").write_text(
        json.dumps(_doc({"0": {"p": [1, 2, 3]}})),
        encoding="utf-8",
    )

    report = audit_dataset(tmp_path)

    assert report["status"] == "partial"
    assert report["present_roles"] == ["same_winding"]
    assert set(report["missing_roles"]) == {"absolute", "relative"}
    assert report["error_count"] == 0


def test_required_missing_role_fails(tmp_path: Path):
    report = audit_dataset(tmp_path, required_roles=["relative"])

    assert report["status"] == "fail"
    assert any(
        item["code"] == "WINDING_REQUIRED_ROLE_MISSING"
        for item in report["findings"]
    )


def test_same_winding_accepts_vc3d_null_wind_a():
    report = audit_document(
        _doc({"0": {"p": [1, 2, 3], "wind_a": None}}),
        role="same_winding",
    )

    assert report["status"] == "pass"


def test_pointcollections_p_is_reported_as_xyz_with_z_from_third_coordinate():
    report = audit_document(
        _doc(
            {
                "0": {"p": [100, 200, 30]},
                "1": {"p": [110, 210, 50]},
            }
        ),
        role="same_winding",
    )

    bounds = report["raw_coordinate_bounds"]
    geometry = report["collections"][0]["geometry"]
    assert bounds["coordinate_order"] == "xyz (VC3D PointCollections p)"
    assert geometry["z_range"] == [30.0, 50.0]
    assert geometry["median_z"] == 40.0


def test_axial_coverage_marks_empty_fit_window_bands(tmp_path: Path):
    document = {
        "vc_pointcollections_json_version": "1",
        "collections": {
            "0": {
                "name": "low",
                "points": {
                    "0": {"p": [1, 2, 0]},
                    "1": {"p": [1, 2, 20]},
                },
            },
            "1": {
                "name": "high",
                "points": {
                    "0": {"p": [1, 2, 80]},
                    "1": {"p": [1, 2, 100]},
                },
            },
        },
    }
    (tmp_path / "same_windings.json").write_text(
        json.dumps(document),
        encoding="utf-8",
    )

    report = audit_dataset(tmp_path, z_range=(0, 100), z_bins=5)
    coverage = report["axial_coverage"]
    window = coverage["fit_window"]

    assert coverage["observed_z_range"] == [10.0, 90.0]
    assert coverage["largest_collection_center_gap"] == {
        "gap_slices": 80.0,
        "between_median_z": [10.0, 90.0],
    }
    assert window["nonempty_bins"] == 2
    assert window["empty_bins"] == [1, 2, 3]
    assert window["nonempty_bin_fraction"] == 0.4
    assert [row["collection_centers"] for row in window["bin_counts"]] == [
        1,
        0,
        0,
        0,
        1,
    ]


def test_point_count_keeps_malformed_entries_in_denominator():
    report = audit_document(
        _doc(
            {
                "0": "not-an-object",
                "1": {"p": [1, 2, 3]},
            }
        ),
        role="same_winding",
    )

    assert report["status"] == "fail"
    assert report["point_count"] == 2
    assert report["collections"][0]["geometry"]["valid_coordinate_points"] == 1


def test_invalid_axial_window_is_rejected(tmp_path: Path):
    try:
        audit_dataset(tmp_path, z_range=(10, 10))
    except ValueError as exc:
        assert "start < stop" in str(exc)
    else:
        raise AssertionError("invalid z_range should fail")


def test_dataset_can_bind_audit_to_exact_volume_root(tmp_path: Path):
    root = "community-uploads/forrest/volcomp/PHercTEST/volumes/v1.zarr"
    report = audit_dataset(tmp_path, volume_root=root)

    assert report["volume_root"] == root


# -- shape of real VC3D output ---------------------------------------------
# Anchored to ScrollPrize/villa volume-cartographer/core/src/PointCollections.cpp
# (to_json): every point has "p" and "creation_time", an explicit "wind_a"
# (null when unannotated), optional "links", optional "fiber_dir"; collections
# may carry "windings_linked". SpiralPclRole.hpp: same-winding points carry no
# wind_a (the editor writes null), relative points an integer wind_a counting
# 0, 1, 2, ... in placement order. Genuine editor output must not false-positive.
def _vc3d_point(xyz, wind_a, **extra):
    point = {"p": xyz, "creation_time": 1760000000, "wind_a": wind_a}
    point.update(extra)
    return point


def test_genuine_vc3d_same_winding_output_has_no_findings():
    doc = _doc(
        {
            "0": _vc3d_point([10.5, 20.25, 30.0], None, fiber_dir="h"),
            "1": _vc3d_point([11.5, 21.25, 31.0], None, links=[0]),
        },
        name="same-winding collection 3",
    )
    doc["collections"]["0"]["windings_linked"] = []
    report = audit_document(doc, role="same_winding")
    assert report["status"] == "pass", report["findings"]
    assert report["findings"] == []


def test_genuine_vc3d_relative_output_counts_from_zero_with_extras():
    doc = _doc(
        {
            "0": _vc3d_point([1.0, 2.0, 3.0], 0.0),
            "1": _vc3d_point([4.0, 5.0, 6.0], 1.0, links=[0]),
            "2": _vc3d_point([7.0, 8.0, 9.0], 2.0, fiber_dir="v"),
        },
        metadata={"winding_is_absolute": False},
    )
    report = audit_document(doc, role="relative")
    assert report["status"] == "pass", report["findings"]
    assert report["collections"][0]["role_stats"]["winding_span"] == 2


def test_integer_valued_floats_are_accepted_but_fractions_are_not():
    # VC3D serializes wind_a as a double, so 2.0 is the normal on-disk form
    ok = audit_document(
        _doc({"0": _vc3d_point([1, 2, 3], 0.0),
              "1": _vc3d_point([4, 5, 6], 2.0)}),
        role="relative")
    assert ok["status"] == "pass"
    bad = audit_document(
        _doc({"0": _vc3d_point([1, 2, 3], 0.0),
              "1": _vc3d_point([4, 5, 6], 1.5)}),
        role="relative")
    assert any(f["code"] == "WINDING_INVALID_WIND_A" for f in bad["findings"])
