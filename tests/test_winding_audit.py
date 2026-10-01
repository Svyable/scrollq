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
