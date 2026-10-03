from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from scrollq.winding_review_compare import (
    ReviewCompareError,
    compare_files,
    compare_review_rerun,
)


SOURCE_SHA = "1" * 64
CORRECTED_SHA = "2" * 64
ABS_SHA = "3" * 64
UMB_SHA = "4" * 64


def _result(
    relative_sha: str,
    *,
    residual_ge_2: int,
    queue: list[dict],
    detection_rate: float,
    localization_rate: float,
) -> dict:
    return {
        "primary": {
            "sense": 1,
            "cut_degrees": 20,
            "attach_distance_voxels": 8.0,
        },
        "decision": {
            "verdict": "INCONSISTENT" if residual_ge_2 else "CONSISTENT",
            "control_detection_rate": detection_rate,
            "control_min_detection": 0.9,
            "inconsistent_constraints": residual_ge_2,
        },
        "summary": {
            "constraints": 100,
            "nodes": 20,
            "patch_pieces": 10,
            "frames": 5,
            "relative_frames": 4,
            "relative_frames_tied_to_absolute": 4,
            "components": 1,
            "independent_cycles": 81,
            "redundant_constraints": 81,
            "residual_0": 90 if residual_ge_2 == 6 else 96,
            "residual_abs_1": 4 if residual_ge_2 == 6 else 2,
            "residual_abs_ge_2": residual_ge_2,
            "edges_with_disagreeing_points": 3 if residual_ge_2 == 6 else 1,
        },
        "control": {
            "eligible": 80,
            "trials": 20,
            "shift": 2,
            "seed": 20261003,
            "detected": round(detection_rate * 20),
            "localized": round(localization_rate * 20),
            "detection_rate": detection_rate,
            "localization_rate": localization_rate,
        },
        "review_queue": queue,
        "inputs": {
            "points": {"absolute": 10, "relative": 30},
            "patch_entries": 50,
            "patches_with_bbox": 50,
            "patches_touching": 12,
            "patches_read": 12,
            "patch_read_errors": 0,
            "patch_read_error_examples": {},
            "usable_pieces_in_touched_patches": 14,
            "excluded_pieces": {},
            "attachments_within_max_distance": 120,
            "points_attached_primary": 35,
            "sha256": {
                "relative_windings.json": relative_sha,
                "abs_winding.json": ABS_SHA,
                "umbilicus.json": UMB_SHA,
            },
        },
        "constants": {
            "protocol": "docs/winding-attachment-protocol.md",
            "attach_distance_voxels": 8.0,
            "control_shift": 2,
            "control_trials": 200,
            "control_seed": 20261003,
            "control_min_detection": 0.9,
        },
        "generated_at": "2026-10-03T00:00:00+00:00",
        "source_commit": "deadbeef",
    }


def _before() -> dict:
    return _result(
        SOURCE_SHA,
        residual_ge_2=6,
        queue=[
            {
                "frame": "relative:1",
                "point_id": "10",
                "residual": -3,
                "xyz": [1.0, 2.0, 3.0],
                "wind_a": 5,
                "patch_piece": "patch-a/#1",
                "distance": 1.0,
            },
            {
                "frame": "relative:1",
                "point_id": "10",
                "residual": -2,
                "xyz": [1.0, 2.0, 3.0],
                "wind_a": 5,
                "patch_piece": "patch-b/#2",
                "distance": 2.0,
            },
            {
                "frame": "relative:2",
                "point_id": "20",
                "residual": 2,
                "xyz": [4.0, 5.0, 6.0],
                "wind_a": 3,
                "patch_piece": "patch-c/#3",
                "distance": 1.5,
            },
        ],
        detection_rate=0.95,
        localization_rate=0.80,
    )


def _after() -> dict:
    return _result(
        CORRECTED_SHA,
        residual_ge_2=2,
        queue=[
            {
                "frame": "relative:2",
                "point_id": "20",
                "residual": 2,
                "xyz": [4.0, 5.0, 6.0],
                "wind_a": 3,
                "patch_piece": "patch-c/#3",
                "distance": 1.5,
            },
            {
                "frame": "relative:3",
                "point_id": "30",
                "residual": -2,
                "xyz": [7.0, 8.0, 9.0],
                "wind_a": 8,
                "patch_piece": "patch-d/#4",
                "distance": 0.5,
            },
        ],
        detection_rate=0.90,
        localization_rate=0.85,
    )


def _attachments() -> list[dict]:
    return [
        {
            "point": "relative:1/10",
            "node": "patch-a/#1",
            "distance": 1.0,
            "phi": 2.5,
        },
        {
            "point": "relative:2/20",
            "node": "patch-c/#3",
            "distance": 1.5,
            "phi": 4.5,
        },
    ]


def _application(before_result_sha: str) -> dict:
    return {
        "schema_version": 1,
        "tool": "scroliq-winding-apply-review",
        "kind": "winding-review-application",
        "scroll": "PHercParis4",
        "source": "relative_windings.json",
        "source_sha256": SOURCE_SHA,
        "ledger": "review-ledger.json",
        "ledger_sha256": "5" * 64,
        "diagnostic_source_sha256": before_result_sha,
        "reviewed_bundle_sha256": "6" * 64,
        "human_review": {
            "reviewer": "reviewer-1",
            "reviewed_at": "2026-10-03T18:00:00-05:00",
            "minutes": 20,
        },
        "review_points": 2,
        "corrections_applied": 1,
        "changes": [
            {
                "frame": "relative:1",
                "collection_id": "1",
                "point_id": "10",
                "xyz": [1.0, 2.0, 3.0],
                "before_winding": 5,
                "after_winding": 6,
                "review_note": "confirmed",
            }
        ],
        "corrected_output": "relative_windings.corrected.json",
        "corrected_sha256": CORRECTED_SHA,
        "limitation": "reviewed hypothesis",
    }


def _compare(
    before: dict | None = None,
    after: dict | None = None,
    attachments_before: list[dict] | None = None,
    attachments_after: list[dict] | None = None,
    application: dict | None = None,
) -> dict:
    before = _before() if before is None else before
    after = _after() if after is None else after
    attachments_before = _attachments() if attachments_before is None else attachments_before
    attachments_after = copy.deepcopy(attachments_before) if attachments_after is None else attachments_after
    application = _application("a" * 64) if application is None else application
    return compare_review_rerun(
        before,
        attachments_before,
        after,
        attachments_after,
        application,
        before_result_sha256="a" * 64,
        before_attachments_sha256="b" * 64,
        after_result_sha256="c" * 64,
        after_attachments_sha256="d" * 64,
        application_sha256="e" * 64,
    )


def test_controlled_comparison_reports_deltas_and_point_disposition() -> None:
    comparison = _compare()

    assert comparison["controls"] == {
        "same_non_correction_input_hashes": True,
        "same_input_accounting": True,
        "same_preregistered_constants": True,
        "same_attachment_geometry": True,
        "attachment_rows": 2,
    }
    assert comparison["before"]["summary"]["residual_abs_ge_2"] == 6
    assert comparison["after"]["summary"]["residual_abs_ge_2"] == 2
    assert comparison["delta_after_minus_before"]["summary"]["residual_abs_ge_2"] == -4
    assert comparison["before"]["flagged_physical_points"] == 2
    assert comparison["after"]["flagged_physical_points"] == 2
    assert comparison["review_queue_change"]["resolved_points"] == [
        {"frame": "relative:1", "point_id": "10"}
    ]
    assert comparison["review_queue_change"]["introduced_points"] == [
        {"frame": "relative:3", "point_id": "30"}
    ]
    assert comparison["corrected_points"] == [
        {
            "frame": "relative:1",
            "point_id": "10",
            "before_flagged": True,
            "after_flagged": False,
            "disposition": "not_flagged_after",
        }
    ]
    assert comparison["control_gate"]["before_passes"] is True
    assert comparison["control_gate"]["after_passes"] is True


def test_before_result_must_match_application_diagnostic_hash() -> None:
    application = _application("0" * 64)
    with pytest.raises(ReviewCompareError, match="before result SHA-256"):
        _compare(application=application)


def test_after_relative_hash_must_match_corrected_output() -> None:
    after = _after()
    after["inputs"]["sha256"]["relative_windings.json"] = "9" * 64
    with pytest.raises(ReviewCompareError, match="corrected output"):
        _compare(after=after)


def test_non_correction_input_hash_change_rejected() -> None:
    after = _after()
    after["inputs"]["sha256"]["abs_winding.json"] = "9" * 64
    with pytest.raises(ReviewCompareError, match="non-correction input"):
        _compare(after=after)


def test_input_accounting_change_rejected() -> None:
    after = _after()
    after["inputs"]["patches_read"] = 11
    with pytest.raises(ReviewCompareError, match="accounting changed"):
        _compare(after=after)


def test_preregistered_constant_change_rejected() -> None:
    after = _after()
    after["constants"]["attach_distance_voxels"] = 12.0
    with pytest.raises(ReviewCompareError, match="constants changed"):
        _compare(after=after)


def test_attachment_geometry_change_rejected() -> None:
    changed = _attachments()
    changed[0]["distance"] = 1.1
    with pytest.raises(ReviewCompareError, match="attachment geometry changed"):
        _compare(attachments_after=changed)


def test_duplicate_application_target_rejected() -> None:
    application = _application("a" * 64)
    application["changes"].append(copy.deepcopy(application["changes"][0]))
    application["corrections_applied"] = 2
    with pytest.raises(ReviewCompareError, match="duplicate correction target"):
        _compare(application=application)


def test_compare_files_binds_actual_file_hashes_and_is_deterministic(tmp_path: Path) -> None:
    outputs = []
    for run in ("a", "b"):
        root = tmp_path / run
        root.mkdir()
        before = _before()
        before_raw = (json.dumps(before, indent=2, sort_keys=True) + "\n").encode()
        before_sha = hashlib.sha256(before_raw).hexdigest()
        application = _application(before_sha)

        paths = {
            "before_result": root / "before-result.json",
            "before_attachments": root / "before-attachments.json",
            "after_result": root / "after-result.json",
            "after_attachments": root / "after-attachments.json",
            "application": root / "application.json",
            "out": root / "comparison.json",
        }
        paths["before_result"].write_bytes(before_raw)
        paths["before_attachments"].write_text(
            json.dumps(_attachments()) + "\n", encoding="utf-8"
        )
        paths["after_result"].write_text(
            json.dumps(_after(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        paths["after_attachments"].write_text(
            json.dumps(_attachments()) + "\n", encoding="utf-8"
        )
        paths["application"].write_text(
            json.dumps(application, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

        comparison = compare_files(
            paths["before_result"],
            paths["before_attachments"],
            paths["after_result"],
            paths["after_attachments"],
            paths["application"],
            paths["out"],
        )
        assert comparison["provenance"]["before_result_sha256"] == before_sha
        outputs.append(paths["out"].read_bytes())

    assert outputs[0] == outputs[1]


def test_compare_files_refuses_overwrite(tmp_path: Path) -> None:
    out = tmp_path / "comparison.json"
    out.write_text("occupied", encoding="utf-8")
    with pytest.raises(ReviewCompareError, match="refusing to overwrite"):
        compare_files(
            tmp_path / "missing-before.json",
            tmp_path / "missing-before-attachments.json",
            tmp_path / "missing-after.json",
            tmp_path / "missing-after-attachments.json",
            tmp_path / "missing-application.json",
            out,
        )
