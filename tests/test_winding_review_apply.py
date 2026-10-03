from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from scrollq.winding_review_apply import (
    ReviewApplyError,
    apply_files,
    apply_review_ledger,
)


def _source() -> dict:
    return {
        "vc_pointcollections_json_version": "1",
        "coordinate_space": "level0-voxel-xyz",
        "collections": {
            "1": {
                "name": "relative one",
                "metadata": {"winding_is_absolute": False},
                "color": [0.2, 0.8, 1.0],
                "points": {
                    "10": {
                        "p": [10.5, 20.25, 30.125],
                        "creation_time": 100,
                        "wind_a": 5,
                    },
                    "11": {
                        "p": [11.5, 21.25, 31.125],
                        "creation_time": 101,
                        "wind_a": 5,
                    },
                },
            },
            "2": {
                "name": "relative two",
                "metadata": {"winding_is_absolute": False},
                "points": {
                    "20": {
                        "p": [40.5, 50.25, 60.125],
                        "creation_time": 200,
                        "wind_a": 3,
                    }
                },
            },
        },
    }


def _raw(value: dict) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _ledger(source_sha: str) -> dict:
    return {
        "schema_version": 1,
        "tool": "scroliq-vc3d-review-ingest",
        "kind": "winding-attachment-review-ledger",
        "scroll": "PHercParis4",
        "diagnostic_source": "result.json",
        "diagnostic_source_sha256": "a" * 64,
        "source_verdict": "INCONSISTENT",
        "original_bundle_sha256": "b" * 64,
        "reviewed_bundle_sha256": "c" * 64,
        "upstream_inputs_sha256": {
            "relative_windings.json": source_sha,
            "abs_winding.json": "d" * 64,
            "umbilicus.json": "e" * 64,
        },
        "human_review": {
            "reviewer": "reviewer-1",
            "reviewed_at": "2026-10-03T18:00:00-05:00",
            "minutes": 21,
        },
        "summary": {
            "review_points": 2,
            "annotation_corrections": 1,
            "patch_issues": 1,
            "no_issue": 0,
            "uncertain": 0,
        },
        "decisions": [
            {
                "collection_id": "1",
                "vc3d_point_id": "1",
                "frame": "relative:1",
                "source_point_id": "10",
                "xyz": [10.5, 20.25, 30.125],
                "original_winding": 5,
                "reviewed_winding": 6,
                "status": "annotation_corrected",
                "note": "CT inspection supports the next winding.",
                "findings": [{"residual": -2}],
            },
            {
                "collection_id": "2",
                "vc3d_point_id": "2",
                "frame": "relative:2",
                "source_point_id": "20",
                "xyz": [40.5, 50.25, 60.125],
                "original_winding": 3,
                "reviewed_winding": 3,
                "status": "patch_issue",
                "note": "The annotation follows the local sheet.",
                "findings": [{"residual": 2}],
            },
        ],
        "limitation": "review evidence",
    }


def _inputs() -> tuple[dict, bytes, str, dict]:
    source = _source()
    raw = _raw(source)
    source_sha = hashlib.sha256(raw).hexdigest()
    return source, raw, source_sha, _ledger(source_sha)


def test_apply_changes_only_confirmed_winding() -> None:
    source, _, source_sha, ledger = _inputs()
    before = copy.deepcopy(source)

    corrected, manifest = apply_review_ledger(
        source,
        ledger,
        source_sha256=source_sha,
        ledger_sha256="f" * 64,
        source_name="relative_windings.json",
        ledger_name="review-ledger.json",
    )

    expected = copy.deepcopy(before)
    expected["collections"]["1"]["points"]["10"]["wind_a"] = 6
    assert corrected == expected
    assert source == before
    assert manifest["corrections_applied"] == 1
    assert manifest["review_points"] == 2
    assert manifest["source_sha256"] == source_sha
    assert manifest["ledger_sha256"] == "f" * 64
    assert manifest["reviewed_bundle_sha256"] == "c" * 64
    assert manifest["human_review"]["minutes"] == 21
    assert manifest["changes"] == [
        {
            "frame": "relative:1",
            "collection_id": "1",
            "point_id": "10",
            "xyz": [10.5, 20.25, 30.125],
            "before_winding": 5,
            "after_winding": 6,
            "review_note": "CT inspection supports the next winding.",
        }
    ]


def test_source_hash_must_match_reviewed_input() -> None:
    source, _, source_sha, ledger = _inputs()
    ledger["upstream_inputs_sha256"]["relative_windings.json"] = "0" * 64
    with pytest.raises(ReviewApplyError, match="source SHA-256"):
        apply_review_ledger(
            source,
            ledger,
            source_sha256=source_sha,
            ledger_sha256="f" * 64,
            source_name="relative_windings.json",
            ledger_name="review-ledger.json",
        )


def test_source_winding_must_match_review_ledger() -> None:
    source, _, source_sha, ledger = _inputs()
    source["collections"]["1"]["points"]["10"]["wind_a"] = 4
    with pytest.raises(ReviewApplyError, match="ledger expects 5"):
        apply_review_ledger(
            source,
            ledger,
            source_sha256=source_sha,
            ledger_sha256="f" * 64,
            source_name="relative_windings.json",
            ledger_name="review-ledger.json",
        )


def test_source_coordinates_must_match_reviewed_point() -> None:
    source, _, source_sha, ledger = _inputs()
    ledger["decisions"][0]["xyz"][0] += 1
    with pytest.raises(ReviewApplyError, match="coordinates do not match"):
        apply_review_ledger(
            source,
            ledger,
            source_sha256=source_sha,
            ledger_sha256="f" * 64,
            source_name="relative_windings.json",
            ledger_name="review-ledger.json",
        )


def test_missing_target_fails_closed() -> None:
    source, _, source_sha, ledger = _inputs()
    ledger["decisions"][0]["source_point_id"] = "999"
    with pytest.raises(ReviewApplyError, match="source point"):
        apply_review_ledger(
            source,
            ledger,
            source_sha256=source_sha,
            ledger_sha256="f" * 64,
            source_name="relative_windings.json",
            ledger_name="review-ledger.json",
        )


def test_duplicate_correction_target_rejected() -> None:
    source, _, source_sha, ledger = _inputs()
    duplicate = copy.deepcopy(ledger["decisions"][0])
    ledger["decisions"].append(duplicate)
    ledger["summary"]["review_points"] = 3
    ledger["summary"]["annotation_corrections"] = 2
    with pytest.raises(ReviewApplyError, match="multiple correction decisions"):
        apply_review_ledger(
            source,
            ledger,
            source_sha256=source_sha,
            ledger_sha256="f" * 64,
            source_name="relative_windings.json",
            ledger_name="review-ledger.json",
        )


def test_absolute_correction_is_not_silently_applied_to_relative_file() -> None:
    source, _, source_sha, ledger = _inputs()
    ledger["decisions"][0]["frame"] = "absolute"
    with pytest.raises(ReviewApplyError, match="outside a relative winding frame"):
        apply_review_ledger(
            source,
            ledger,
            source_sha256=source_sha,
            ledger_sha256="f" * 64,
            source_name="relative_windings.json",
            ledger_name="review-ledger.json",
        )


def test_vacuous_no_correction_ledger_rejected() -> None:
    source, _, source_sha, ledger = _inputs()
    ledger["decisions"][0]["status"] = "no_issue"
    ledger["decisions"][0]["reviewed_winding"] = 5
    ledger["summary"] = {
        "review_points": 2,
        "annotation_corrections": 0,
        "patch_issues": 1,
        "no_issue": 1,
        "uncertain": 0,
    }
    with pytest.raises(ReviewApplyError, match="no annotation corrections"):
        apply_review_ledger(
            source,
            ledger,
            source_sha256=source_sha,
            ledger_sha256="f" * 64,
            source_name="relative_windings.json",
            ledger_name="review-ledger.json",
        )


def test_ledger_summary_must_match_decisions() -> None:
    source, _, source_sha, ledger = _inputs()
    ledger["summary"]["annotation_corrections"] = 2
    with pytest.raises(ReviewApplyError, match="summary does not match"):
        apply_review_ledger(
            source,
            ledger,
            source_sha256=source_sha,
            ledger_sha256="f" * 64,
            source_name="relative_windings.json",
            ledger_name="review-ledger.json",
        )


def test_apply_files_is_deterministic_and_hashes_corrected_bytes(tmp_path: Path) -> None:
    source, source_raw, _, ledger = _inputs()
    ledger_raw = _raw(ledger)

    outputs = []
    manifests = []
    for run in ("a", "b"):
        root = tmp_path / run
        root.mkdir()
        source_path = root / "relative_windings.json"
        ledger_path = root / "review-ledger.json"
        out_path = root / "relative_windings.corrected.json"
        manifest_path = root / "application.json"
        source_path.write_bytes(source_raw)
        ledger_path.write_bytes(ledger_raw)

        manifest = apply_files(
            source_path,
            ledger_path,
            out_path,
            manifest_path,
        )
        outputs.append(out_path.read_bytes())
        manifests.append(manifest_path.read_bytes())
        assert manifest["corrected_sha256"] == hashlib.sha256(outputs[-1]).hexdigest()
        corrected = json.loads(outputs[-1])
        assert corrected["collections"]["1"]["points"]["10"]["wind_a"] == 6
        assert corrected["collections"]["1"]["points"]["11"]["wind_a"] == 5
        assert corrected["collections"]["2"]["points"]["20"]["wind_a"] == 3

    assert outputs[0] == outputs[1]
    assert manifests[0] == manifests[1]


def test_apply_files_refuses_source_overwrite(tmp_path: Path) -> None:
    _, source_raw, _, ledger = _inputs()
    source_path = tmp_path / "relative_windings.json"
    ledger_path = tmp_path / "review-ledger.json"
    source_path.write_bytes(source_raw)
    ledger_path.write_bytes(_raw(ledger))

    with pytest.raises(ReviewApplyError, match="overwrite the source"):
        apply_files(
            source_path,
            ledger_path,
            source_path,
            tmp_path / "application.json",
        )


def test_apply_files_refuses_existing_outputs(tmp_path: Path) -> None:
    _, source_raw, _, ledger = _inputs()
    source_path = tmp_path / "relative_windings.json"
    ledger_path = tmp_path / "review-ledger.json"
    out_path = tmp_path / "corrected.json"
    manifest_path = tmp_path / "application.json"
    source_path.write_bytes(source_raw)
    ledger_path.write_bytes(_raw(ledger))
    out_path.write_text("occupied", encoding="utf-8")

    with pytest.raises(ReviewApplyError, match="refusing to overwrite"):
        apply_files(source_path, ledger_path, out_path, manifest_path)
