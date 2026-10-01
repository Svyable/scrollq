import json
import math
from pathlib import Path

import pytest

from scrollq.passport import build_passport
from scrollq.winding_audit import audit_dataset
from scrollq.winding_geometry import check_ray_order, parse_umbilicus

SPACING = 20.0  # voxels between windings along a ray
R0 = 40.0


def _axis(z):
    # A tilted umbilicus: the centre drifts with z.
    return 500.0 + 0.1 * z, 600.0 - 0.05 * z  # (y, x)


def _umbilicus_doc():
    return {
        "control_points": [
            {"z": z, "y": _axis(z)[0], "x": _axis(z)[1]} for z in (0.0, 1000.0)
        ]
    }


def _spiral_point(winding, theta, z):
    """XYZ on an ideal Archimedean spiral whose winding increments at theta=0."""
    radius = R0 + SPACING * (winding + theta / (2 * math.pi))
    cy, cx = _axis(z)
    return [cx + radius * math.cos(theta), cy + radius * math.sin(theta), z]


def _absolute_doc(windings=range(3, 12), thetas=(0.2, 1.7, 3.1, 4.6, 6.0), zs=(100.0, 130.0)):
    points = {}
    for w in windings:
        for theta in thetas:
            for z in zs:
                points[str(len(points))] = {"p": _spiral_point(w, theta, z), "wind_a": w}
    return {
        "vc_pointcollections_json_version": "1",
        "collections": {"1": {"name": "abs", "points": points}},
    }


def _umbilicus():
    return parse_umbilicus(_umbilicus_doc(), source="umbilicus.json")


def test_ideal_spiral_is_consistent_and_has_comparable_pairs():
    report = check_ray_order({"absolute": _absolute_doc()}, _umbilicus())

    assert report["status"] == "consistent"
    assert report["comparable_pairs"] > 100
    assert report["inversion_candidates"] == 0
    assert report["review_queue"] == []


def test_branch_cut_neighbours_are_not_compared_at_gap_one():
    # At theta=0 the winding number steps by one although the sheet is
    # continuous: winding 6 just below the cut sits at almost the same radius
    # as winding 7 just above it. Whether a one-winding pair is "in order"
    # therefore depends on the cut convention, so it must not be compared.
    doc = {
        "vc_pointcollections_json_version": "1",
        "collections": {
            "1": {
                "name": "cut",
                "points": {
                    "0": {"p": _spiral_point(6, 2 * math.pi - 0.05, 100.0), "wind_a": 6},
                    "1": {"p": _spiral_point(7, 0.05, 100.0), "wind_a": 7},
                    "2": {"p": _spiral_point(5, 2 * math.pi - 0.05, 100.0), "wind_a": 5},
                },
            }
        },
    }
    report = check_ray_order({"absolute": doc}, _umbilicus())

    # Only the (5, 7) pair is comparable, and it is correctly ordered.
    assert report["comparable_pairs"] == 1
    assert report["status"] == "consistent"


def test_single_misnumbered_point_tops_the_review_queue():
    doc = _absolute_doc()
    points = doc["collections"]["1"]["points"]
    # Point on winding 4 annotated as winding 10.
    bad = next(
        key for key, point in points.items() if point["wind_a"] == 4
    )
    points[bad]["wind_a"] = 10

    report = check_ray_order({"absolute": doc}, _umbilicus())

    assert report["status"] == "review"
    assert report["inversion_candidates"] > 0
    head = report["review_queue"][0]
    assert head["point_id"] == bad
    assert head["wind_a"] == 10
    assert head["inversion_pairs"] == max(
        item["inversion_pairs"] for item in report["review_queue"]
    )
    # Every candidate involves the corrupted point.
    for candidate in report["candidates"]:
        assert bad in {candidate["inner"]["point_id"], candidate["outer"]["point_id"]}
        assert candidate["winding_gap"] >= 2
        assert candidate["radial_inversion_voxels"] > 0


def test_relative_collections_are_independent_frames():
    def rel(offset, windings):
        return {
            "name": f"rel{offset}",
            "points": {
                str(i): {"p": _spiral_point(w, 1.0, 100.0 + i), "wind_a": w - offset}
                for i, w in enumerate(windings)
            },
        }

    doc = {
        "vc_pointcollections_json_version": "1",
        # Different arbitrary zero points: comparing across collections would
        # manufacture inversions.
        "collections": {"1": rel(0, [3, 6, 9]), "2": rel(20, [4, 7, 10])},
    }
    report = check_ray_order({"relative": doc}, _umbilicus())

    assert report["status"] == "consistent"
    assert [row["frame"] for row in report["frames"]] == ["relative:1", "relative:2"]
    assert all(row["comparable_pairs"] == 3 for row in report["frames"])


def test_points_in_distant_z_bands_are_not_comparable():
    # Same angle and a six-winding gap, but 800 voxels apart in z.
    doc = {
        "vc_pointcollections_json_version": "1",
        "collections": {
            "1": {
                "name": "far",
                "points": {
                    "0": {"p": _spiral_point(9, 0.2, 100.0), "wind_a": 3},
                    "1": {"p": _spiral_point(3, 0.2, 900.0), "wind_a": 9},
                },
            }
        },
    }
    report = check_ray_order({"absolute": doc}, _umbilicus())
    assert report["status"] == "no-comparable-pairs"
    assert report["comparable_pairs"] == 0

    wide = check_ray_order({"absolute": doc}, _umbilicus(), z_tolerance=1000.0)
    assert wide["status"] == "review"
    assert wide["inversion_candidates"] == 1


@pytest.mark.parametrize(
    "document",
    [
        {},
        {"control_points": [{"x": 1, "y": 2, "z": 3}]},
        {"control_points": [{"x": 1, "y": 2, "z": 3}, {"x": 1, "y": 2, "z": 3}]},
        {"control_points": [{"x": 1, "y": 2, "z": 3}, {"x": "a", "y": 2, "z": 4}]},
    ],
)
def test_invalid_umbilicus_is_rejected(document):
    with pytest.raises(ValueError):
        parse_umbilicus(document)


def test_min_winding_gap_below_two_is_rejected():
    with pytest.raises(ValueError):
        check_ray_order({}, _umbilicus(), min_winding_gap=1)


def _write_dataset(root: Path, *, umbilicus=True, corrupt=False):
    doc = _absolute_doc()
    if corrupt:
        doc["collections"]["1"]["points"]["0"]["wind_a"] = 11
    (root / "abs_winding.json").write_text(json.dumps(doc))
    if umbilicus:
        (root / "umbilicus.json").write_text(json.dumps(_umbilicus_doc()))


def test_dataset_audit_auto_detects_umbilicus_and_records_input_hashes(tmp_path):
    _write_dataset(tmp_path)

    report = audit_dataset(tmp_path)

    ray = report["ray_order"]
    assert ray["status"] == "consistent"
    assert ray["umbilicus"]["sha256"]
    assert ray["inputs_sha256"]["absolute"] == report["documents"]["absolute"]["sha256"]
    assert ray["inputs_sha256"]["relative"] is None
    assert not any(f["code"].startswith("WINDING_RAY") for f in report["findings"])


def test_dataset_audit_without_umbilicus_is_not_evaluated(tmp_path):
    _write_dataset(tmp_path, umbilicus=False)

    report = audit_dataset(tmp_path)

    assert report["ray_order"]["status"] == "not-evaluated"
    assert report["status"] != "fail"


def test_explicit_missing_umbilicus_fails_closed(tmp_path):
    _write_dataset(tmp_path, umbilicus=False)

    report = audit_dataset(tmp_path, umbilicus=tmp_path / "nope.json")

    assert report["status"] == "fail"
    assert any(f["code"] == "WINDING_UMBILICUS_INVALID" for f in report["findings"])


def test_inversions_warn_and_reach_passport_as_review_action(tmp_path):
    _write_dataset(tmp_path, corrupt=True)
    root = "community-uploads/x/volumes/v.zarr"

    report = audit_dataset(tmp_path, volume_root=root)

    assert report["status"] == "partial"
    assert any(f["code"] == "WINDING_RAY_ORDER_CANDIDATES" for f in report["findings"])
    assert report["ray_order"]["review_queue"][0]["point_id"] == "0"

    passport = build_passport(
        {"root": root, "score": 50.0, "health": {}},
        winding_audit=report,
    )
    winding = passport["stages"]["winding"]
    assert winding["status"] == "partial"
    assert winding["ray_order"]["inversion_candidates"] > 0
    assert winding["ray_order"]["review_queue_head"][0]["point_id"] == "0"
    assert any(
        "ray-order inversion candidates" in action["action"]
        and action["priority"] == "high"
        for action in passport["next_actions"]
    )
