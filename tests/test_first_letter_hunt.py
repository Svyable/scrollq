import json

import numpy as np

from scrollq.first_letter_hunt import build_hunt_report, main


def _write(tmp_path, name, arr):
    path = tmp_path / name
    np.save(path, np.asarray(arr, dtype=np.float32))
    return path.name


def _candidate(tmp_path, candidate_id, control_signal=False, same_checkpoint=False):
    primary1 = np.zeros((8, 8), dtype=np.float32)
    primary2 = np.zeros((8, 8), dtype=np.float32)
    primary1[2:5, 2:5] = 0.9
    primary2[2:5, 2:5] = 0.8
    control = np.zeros((8, 8), dtype=np.float32)
    if control_signal:
        control[2:5, 2:5] = 0.95
    sha1 = "a" * 64
    sha2 = sha1 if same_checkpoint else "b" * 64
    return {
        "id": candidate_id,
        "bbox_zyx_half_open": [[9274, 100, 100], [9338, 200, 200]],
        "surface_support_frac": 0.8,
        "primary_predictions": [
            {"path": _write(tmp_path, f"{candidate_id}-p1.npy", primary1), "checkpoint_sha256": sha1},
            {"path": _write(tmp_path, f"{candidate_id}-p2.npy", primary2), "checkpoint_sha256": sha2},
        ],
        "controls": [
            {"path": _write(tmp_path, f"{candidate_id}-m3.npy", control), "kind": "normal_offset", "offset_voxels": -3},
            {"path": _write(tmp_path, f"{candidate_id}-p3.npy", control), "kind": "normal_offset", "offset_voxels": 3},
            {"path": _write(tmp_path, f"{candidate_id}-adj.npy", control), "kind": "adjacent_winding"},
            {"path": _write(tmp_path, f"{candidate_id}-geom.npy", control), "kind": "geometry_perturbation"},
        ],
    }


def test_localized_candidate_is_reviewable_and_ranks_first(tmp_path):
    manifest = {
        "volume_root": "PHerc0490A/exact-volume.zarr",
        "candidates": [
            _candidate(tmp_path, "localized"),
            _candidate(tmp_path, "control-like", control_signal=True),
        ],
    }
    report = build_hunt_report(manifest, base_dir=tmp_path)

    assert report["status"] == "ok"
    assert report["review_candidate_count"] == 1
    assert report["review_queue"][0]["id"] == "localized"
    assert report["review_queue"][0]["status"] == "review"
    assert report["review_queue"][0]["localization_margin"] > 0
    assert report["review_queue"][1]["status"] == "hold"


def test_missing_physical_controls_holds_candidate(tmp_path):
    candidate = _candidate(tmp_path, "missing")
    candidate["controls"] = candidate["controls"][:1]
    report = build_hunt_report(
        {"volume_root": "volume-A", "candidates": [candidate]}, base_dir=tmp_path
    )

    row = report["review_queue"][0]
    assert row["status"] == "hold"
    assert row["controls"]["complete"] is False
    assert "adjacent_winding" in row["controls"]["missing_kinds"]
    assert 3.0 in row["controls"]["missing_normal_offsets_voxels"]


def test_distinct_checkpoint_gate_is_not_faked_by_repeated_run(tmp_path):
    candidate = _candidate(tmp_path, "same", same_checkpoint=True)
    report = build_hunt_report(
        {"volume_root": "volume-A", "candidates": [candidate]}, base_dir=tmp_path
    )
    row = report["review_queue"][0]

    assert row["status"] == "hold"
    assert row["primary"]["distinct_checkpoint_count"] == 1
    assert any("distinct checkpoint" in warning for warning in row["warnings"])


def test_exact_volume_binding_fails_closed(tmp_path):
    candidate = _candidate(tmp_path, "x")
    report = build_hunt_report(
        {"volume_root": "volume-A", "candidates": [candidate]},
        base_dir=tmp_path,
        expected_volume_root="volume-B",
    )
    assert report["status"] == "fail"
    assert any("expected-volume-root" in error for error in report["errors"])


def test_cli_writes_queue(tmp_path):
    manifest = {"volume_root": "volume-A", "candidates": [_candidate(tmp_path, "x")]}
    manifest_path = tmp_path / "manifest.json"
    out_path = tmp_path / "queue.json"
    manifest_path.write_text(json.dumps(manifest))

    assert main([str(manifest_path), "--out", str(out_path)]) == 0
    report = json.loads(out_path.read_text())
    assert report["review_candidate_count"] == 1
