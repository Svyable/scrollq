from scrollq.passport import OPEN_PROBLEMS, alignment_manifest, build_passport


def _volume(**overrides):
    base = {
        "root": "community-uploads/forrest/volcomp/PHercTEST/volumes/v1.zarr",
        "ok": True,
        "score": 71.2,
        "metrics": {
            "nonzero_frac": 0.8,
            "grad_energy": 12.0,
            "dyn_range": 55.0,
            "sat_frac": 0.01,
            "dead_slices": 0,
            "chunks_decoded": 4,
        },
        "components": {
            "signal_40": 32.0,
            "texture_30": 22.0,
            "dynamic_20": 18.0,
            "pen_sat": 0.8,
            "pen_dead": 0.0,
        },
        "sampling": {"requested": 4, "decoded": 4, "complete": True},
    }
    base.update(overrides)
    return base


def test_alignment_manifest_names_pipeline_bottlenecks_without_ranking_them():
    manifest = alignment_manifest()
    ids = {item["id"] for item in OPEN_PROBLEMS}

    assert manifest["source"]["url"].endswith("/2026_open_problems")
    assert {
        "scan-diagnostics",
        "surface-topology",
        "mesh-connectivity",
        "fiber-connectivity",
        "spiral-fitting",
        "label-quality",
        "ink-reliability",
        "data-scale",
    } <= ids
    assert "score" not in manifest
    assert "rank" not in manifest


def test_passport_keeps_unmeasured_downstream_stages_unknown():
    passport = build_passport(_volume())

    assert passport["stages"]["scan"]["status"] == "measured"
    assert passport["stages"]["scan"]["quality_score"] == 71.2
    assert passport["stages"]["scan"]["spatial_map"]["status"] == "unknown"
    assert any(
        action["open_problem"] == "scan-diagnostics"
        for action in passport["next_actions"]
    )
    for stage in ("surface", "mesh", "fibers", "spiral", "ink"):
        assert passport["stages"][stage]["status"] == "unknown"


def test_passport_uses_label_coverage_without_claiming_label_accuracy():
    passport = build_passport(
        _volume(),
        {"ink_labels": 0, "segments": 2, "label_next": True},
    )

    labels = passport["stages"]["labels"]
    assert labels["status"] == "partial"
    assert labels["label_next"] is True
    assert "does not yet measure" in labels["limitation"]
    assert any(
        action["open_problem"] == "label-quality"
        for action in passport["next_actions"]
    )


def test_incomplete_sampling_is_a_high_priority_data_scale_action():
    passport = build_passport(
        _volume(sampling={"requested": 4, "decoded": 2, "complete": False})
    )

    assert passport["stages"]["data"]["status"] == "partial"
    assert passport["next_actions"][0]["priority"] == "high"
    assert passport["next_actions"][0]["open_problem"] == "data-scale"



def test_passport_accepts_matching_spatial_scan_evidence():
    volume = _volume()
    scan_map = {
        "diagnostic": "spatial-scan-map",
        "root": volume["root"],
        "ok": True,
        "coordinate_space": "level0-voxel-index",
        "sampling": {
            "candidate_shards": 27,
            "chunks_decoded": 24,
            "status_counts": {"decoded": 24, "sparse-mask": 3},
        },
        "metric_distribution": {
            "grad_energy": {"min": 2.0, "median": 8.0, "max": 14.0}
        },
    }

    passport = build_passport(volume, scan_map=scan_map)
    spatial = passport["stages"]["scan"]["spatial_map"]

    assert spatial["status"] == "measured"
    assert spatial["coordinate_space"] == "level0-voxel-index"
    assert spatial["sampling"]["chunks_decoded"] == 24
    assert not any(
        action["open_problem"] == "scan-diagnostics"
        for action in passport["next_actions"]
    )


def test_passport_fails_closed_on_spatial_map_for_different_volume():
    volume = _volume()
    scan_map = {
        "diagnostic": "spatial-scan-map",
        "root": "different-volume",
        "ok": True,
    }

    passport = build_passport(volume, scan_map=scan_map)

    assert passport["stages"]["scan"]["spatial_map"]["status"] == "excluded"
    assert "different volume root" in (
        passport["stages"]["scan"]["spatial_map"]["reason"]
    )
