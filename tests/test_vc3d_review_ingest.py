from __future__ import annotations

import copy
import hashlib
import json
import struct
from pathlib import Path

import pytest

from scrollq.vc3d_review_export import build_winding_attachment_bundle
from scrollq.vc3d_review_ingest import (
    ReviewIngestError,
    build_review_ledger,
    ingest_files,
)


def _diagnostic() -> dict:
    return {
        "decision": {"verdict": "INCONSISTENT"},
        "review_queue": [
            {
                "residual": -2,
                "frame": "relative:2",
                "point_id": "20",
                "xyz": [100.1234567, 200.25, 300.75],
                "wind_a": 3,
                "patch_piece": "patch-b/#7",
                "distance": 1.5,
            },
            {
                "residual": 2,
                "frame": "relative:1",
                "point_id": "10",
                "xyz": [400.5, 500.125, 600.875],
                "wind_a": 5,
                "patch_piece": "patch-a/#2",
                "distance": 0.75,
            },
        ],
        "inputs": {
            "sha256": {
                "relative_windings.json": "a" * 64,
                "abs_winding.json": "b" * 64,
                "umbilicus.json": "c" * 64,
            }
        },
    }


def _bundle(diag: dict | None = None, digest: str = "d" * 64) -> dict:
    diag = _diagnostic() if diag is None else diag
    return build_winding_attachment_bundle(
        diag,
        source_name="result.json",
        source_sha256=digest,
        scroll="PHercParis4",
    )


def _reviewed(original: dict) -> dict:
    reviewed = copy.deepcopy(original)
    first = reviewed["collections"]["1"]
    first["tags"]["scroliq_review_status"] = "annotation_corrected"
    first["tags"]["scroliq_review_note"] = "CT inspection supports the adjacent winding."
    point = next(iter(first["points"].values()))
    point["wind_a"] = int(point["wind_a"]) + 1

    second = reviewed["collections"]["2"]
    second["tags"]["scroliq_review_status"] = "patch_issue"
    second["tags"]["scroliq_review_note"] = "Annotation agrees with the closer patch."
    return reviewed


def _ledger(original: dict, reviewed: dict, diag: dict | None = None) -> dict:
    return build_review_ledger(
        original,
        reviewed,
        _diagnostic() if diag is None else diag,
        diagnostic_sha256="d" * 64,
        original_bundle_sha256="e" * 64,
        reviewed_bundle_sha256="f" * 64,
        reviewer="reviewer-1",
        reviewed_at="2026-10-03T12:00:00Z",
        review_minutes=17,
    )


def test_build_review_ledger_binds_decisions_and_human_time() -> None:
    original = _bundle()
    ledger = _ledger(original, _reviewed(original))

    assert ledger["scroll"] == "PHercParis4"
    assert ledger["diagnostic_source"] == "result.json"
    assert ledger["source_verdict"] == "INCONSISTENT"
    assert ledger["summary"] == {
        "review_points": 2,
        "annotation_corrections": 1,
        "patch_issues": 1,
        "no_issue": 0,
        "uncertain": 0,
    }
    assert ledger["human_review"] == {
        "reviewer": "reviewer-1",
        "reviewed_at": "2026-10-03T12:00:00+00:00",
        "minutes": 17,
    }
    assert ledger["upstream_inputs_sha256"]["relative_windings.json"] == "a" * 64
    correction = ledger["decisions"][0]
    assert correction["frame"] == "relative:1"
    assert correction["source_point_id"] == "10"
    assert correction["original_winding"] == 5
    assert correction["reviewed_winding"] == 6
    assert correction["status"] == "annotation_corrected"


def test_vc3d_float32_coordinate_roundtrip_is_accepted() -> None:
    original = _bundle()
    reviewed = _reviewed(original)
    for collection in reviewed["collections"].values():
        point = next(iter(collection["points"].values()))
        point["p"] = [
            struct.unpack("!f", struct.pack("!f", float(value)))[0]
            for value in point["p"]
        ]
    ledger = _ledger(original, reviewed)
    assert ledger["summary"]["review_points"] == 2


@pytest.mark.parametrize("field", ["scroliq_review_status", "scroliq_review_note"])
def test_review_decision_tags_are_required(field: str) -> None:
    original = _bundle()
    reviewed = _reviewed(original)
    reviewed["collections"]["1"]["tags"].pop(field)
    with pytest.raises(ReviewIngestError):
        _ledger(original, reviewed)


def test_original_provenance_tags_cannot_change() -> None:
    original = _bundle()
    reviewed = _reviewed(original)
    reviewed["collections"]["1"]["tags"]["source_sha256"] = "0" * 64
    with pytest.raises(ReviewIngestError, match="changed during review"):
        _ledger(original, reviewed)


def test_review_marker_position_cannot_move() -> None:
    original = _bundle()
    reviewed = _reviewed(original)
    point = next(iter(reviewed["collections"]["1"]["points"].values()))
    point["p"][0] += 1.0
    with pytest.raises(ReviewIngestError, match="moved during review"):
        _ledger(original, reviewed)


def test_annotation_correction_requires_winding_change() -> None:
    original = _bundle()
    reviewed = _reviewed(original)
    before = next(iter(original["collections"]["1"]["points"].values()))
    after = next(iter(reviewed["collections"]["1"]["points"].values()))
    after["wind_a"] = before["wind_a"]
    with pytest.raises(ReviewIngestError, match="wind_a did not change"):
        _ledger(original, reviewed)


def test_other_status_cannot_change_winding() -> None:
    original = _bundle()
    reviewed = _reviewed(original)
    reviewed["collections"]["1"]["tags"]["scroliq_review_status"] = "no_issue"
    with pytest.raises(ReviewIngestError, match="without annotation_corrected"):
        _ledger(original, reviewed)


def test_original_bundle_must_reproduce_from_diagnostic() -> None:
    original = _bundle()
    reviewed = _reviewed(original)
    original["collections"]["1"]["name"] = "tampered"
    with pytest.raises(ReviewIngestError, match="not the deterministic export"):
        _ledger(original, reviewed)


def test_review_timestamp_requires_timezone() -> None:
    original = _bundle()
    reviewed = _reviewed(original)
    with pytest.raises(ReviewIngestError, match="timezone"):
        build_review_ledger(
            original,
            reviewed,
            _diagnostic(),
            diagnostic_sha256="d" * 64,
            original_bundle_sha256="e" * 64,
            reviewed_bundle_sha256="f" * 64,
            reviewer="reviewer-1",
            reviewed_at="2026-10-03T12:00:00",
            review_minutes=17,
        )


def test_ingest_files_hashes_inputs_and_refuses_overwrite(tmp_path: Path) -> None:
    diagnostic = _diagnostic()
    diagnostic_raw = (
        json.dumps(diagnostic, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    diagnostic_sha = hashlib.sha256(diagnostic_raw).hexdigest()
    original = _bundle(diagnostic, diagnostic_sha)
    reviewed = _reviewed(original)

    diagnostic_path = tmp_path / "result.json"
    original_path = tmp_path / "original.points.json"
    reviewed_path = tmp_path / "reviewed.points.json"
    output_path = tmp_path / "ledger.json"
    diagnostic_path.write_bytes(diagnostic_raw)
    original_path.write_text(
        json.dumps(original, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    reviewed_path.write_text(
        json.dumps(reviewed, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    ledger = ingest_files(
        original_path,
        reviewed_path,
        diagnostic_path,
        output_path,
        reviewer="reviewer-1",
        reviewed_at="2026-10-03T12:00:00+00:00",
        review_minutes=17,
    )
    assert ledger["diagnostic_source_sha256"] == diagnostic_sha
    assert output_path.is_file()

    with pytest.raises(ReviewIngestError, match="refusing to overwrite"):
        ingest_files(
            original_path,
            reviewed_path,
            diagnostic_path,
            output_path,
            reviewer="reviewer-1",
            reviewed_at="2026-10-03T12:00:00+00:00",
            review_minutes=17,
        )


def test_frozen_paris4_bundle_is_exact_export_of_frozen_result() -> None:
    root = Path(__file__).resolve().parents[1]
    artifact = root / "artifacts/2026-10-03-paris4-winding-attachment"
    result_path = artifact / "result.json"
    bundle_path = artifact / "vc3d-review-points.json"

    raw = result_path.read_bytes()
    expected = build_winding_attachment_bundle(
        json.loads(raw),
        source_name=result_path.name,
        source_sha256=hashlib.sha256(raw).hexdigest(),
        scroll="PHercParis4",
    )
    committed = json.loads(bundle_path.read_bytes())
    assert committed == expected
