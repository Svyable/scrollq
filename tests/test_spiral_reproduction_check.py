import hashlib
import json

from scrollq.spiral_reproduction_check import evaluate_run


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    recipe = run / "spiral-run.recipe.json"
    recipe.write_text(json.dumps({
        "scroll": "PHerc0826",
        "prize_volume_id": "20250821151701",
        "bounded_reproduction": {
            "z_range_half_open": [11000, 12000],
            "expected_reference_context": {
                "documented_gpu": "RTX 3090",
                "documented_tracks_loaded_with_input_use_tracks_true": 480117,
                "comparison_only_not_correctness_metrics": {
                    "dr_per_winding_voxels": 14.8851,
                    "satisfied_tracks_percent": 12.6,
                    "satisfied_track_points_percent": 41.6
                }
            }
        }
    }))
    stdout = run / "spiral-run.stdout.log"
    stdout.write_text(
        "setup\n"
        "loaded 480,117 tracks within z-roi [11000, 12000)\n"
        "done\n"
    )
    metrics = run / "satisfaction_metrics_fitted.json"
    metrics.write_text(json.dumps({
        "summary": {
            "total_tracks": 480117,
            "satisfied_tracks_fraction": 0.12604,
            "satisfied_track_points_fraction": 0.41596
        }
    }))
    receipt = {
        "schema_version": 1,
        "tool": "scroliq-spiral-run",
        "success": True,
        "scroll": "PHerc0826",
        "prize_volume_id": "20250821151701",
        "recipe": {"copy_path": recipe.name, "copy_sha256": _sha(recipe)},
        "logs": {"stdout": {"path": stdout.name, "sha256": _sha(stdout)}},
        "outputs": [{
            "path": metrics.name,
            "size": metrics.stat().st_size,
            "sha256": _sha(metrics)
        }]
    }
    (run / "spiral-run.receipt.json").write_text(json.dumps(receipt))
    return run


def test_exact_published_sanity_context_passes(tmp_path):
    report = evaluate_run(_fixture(tmp_path))
    assert report["status"] == "sanity-match"
    assert report["baseline_reproduction_ready_for_export"] is True
    assert report["mechanically_unverified_reference_fields"] == ["dr_per_winding_voxels"]


def test_wrong_track_count_fails(tmp_path):
    run = _fixture(tmp_path)
    stdout = run / "spiral-run.stdout.log"
    stdout.write_text("loaded 480,116 tracks within z-roi [11000, 12000)\n")
    receipt_path = run / "spiral-run.receipt.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["logs"]["stdout"]["sha256"] = _sha(stdout)
    receipt_path.write_text(json.dumps(receipt))
    report = evaluate_run(run)
    assert report["baseline_reproduction_ready_for_export"] is False
    assert any(row["name"] == "track_count" and not row["ok"] for row in report["checks"])


def test_wrong_z_range_fails(tmp_path):
    run = _fixture(tmp_path)
    stdout = run / "spiral-run.stdout.log"
    stdout.write_text("loaded 480,117 tracks within z-roi [10999, 12000)\n")
    receipt_path = run / "spiral-run.receipt.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["logs"]["stdout"]["sha256"] = _sha(stdout)
    receipt_path.write_text(json.dumps(receipt))
    report = evaluate_run(run)
    assert report["baseline_reproduction_ready_for_export"] is False
    assert any(row["name"] == "track_z_range" and not row["ok"] for row in report["checks"])


def test_one_decimal_published_percent_is_the_contract(tmp_path):
    run = _fixture(tmp_path)
    metrics = run / "satisfaction_metrics_fitted.json"
    metrics.write_text(json.dumps({
        "summary": {
            "total_tracks": 480117,
            "satisfied_tracks_fraction": 0.12549,
            "satisfied_track_points_fraction": 0.41596
        }
    }))
    receipt_path = run / "spiral-run.receipt.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["outputs"][0]["sha256"] = _sha(metrics)
    receipt["outputs"][0]["size"] = metrics.stat().st_size
    receipt_path.write_text(json.dumps(receipt))
    report = evaluate_run(run)
    assert report["baseline_reproduction_ready_for_export"] is False
    assert any(
        row["name"] == "satisfied_tracks_percent" and not row["ok"]
        for row in report["checks"]
    )


def test_metrics_hash_tamper_fails(tmp_path):
    run = _fixture(tmp_path)
    metrics = run / "satisfaction_metrics_fitted.json"
    metrics.write_text(json.dumps({"summary": {}}))
    report = evaluate_run(run)
    assert report["baseline_reproduction_ready_for_export"] is False
    assert any(
        row["name"] == "satisfaction_metrics_hash" and not row["ok"]
        for row in report["checks"]
    )
