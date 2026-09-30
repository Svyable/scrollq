from scrollq.grand_prize import DEFAULT_MANIFEST, qualify


def _volume(scroll, volume_id, score, ok=True):
    return {
        "root": (
            f"community-uploads/forrest/volcomp/{scroll}/volumes/"
            f"{volume_id}-masked.zarr"
        ),
        "ok": ok,
        "score": score,
    }


def test_current_campaign_frontier_is_weight_free():
    scores = {
        "PHerc0125": 58.5,
        "PHerc0191": 43.5,
        "PHerc0211": 48.1,
        "PHerc0257": 63.9,
        "PHerc0268": 38.3,
        "PHerc0358": 53.4,
        "PHerc0800": 42.6,
        "PHerc0813": 77.4,
        "PHerc0826": 28.2,
        "PHerc1203": 53.2,
        "PHerc1218": 45.1,
        "PHerc1447": 70.7,
        "PHerc1545": 30.8,
    }
    volumes = [
        _volume(t["scroll"], t["volume_id"], scores[t["scroll"]])
        for t in DEFAULT_MANIFEST["targets"]
    ]
    result = qualify(volumes)

    assert len(result["targets"]) == 13
    assert result["frontier"] == ["PHerc0813", "PHerc1447"]
    assert "score" not in result["method"]

    rows = {r["scroll"]: r for r in result["targets"]}
    assert rows["PHerc0800"]["qualification"] == "dominated-on-current-evidence"
    assert "PHerc1447" in rows["PHerc0800"]["dominated_by"]
    assert rows["PHerc1447"]["segments"] == 15


def test_exact_prize_volume_match_excludes_other_same_scroll_scan():
    target = next(
        t for t in DEFAULT_MANIFEST["targets"] if t["scroll"] == "PHerc1203"
    )
    volumes = [
        _volume("PHerc1203", "20260319130212", 99.9),
        _volume("PHerc1203", target["volume_id"], 53.2),
    ]
    result = qualify(volumes)
    row = next(r for r in result["targets"] if r["scroll"] == "PHerc1203")

    assert row["quality_score"] == 53.2
    assert row["volume_id"] == "20250820131727"
    assert row["excluded_same_scroll_higher_res"][0]["volume_id"] == "20260319130212"


def test_missing_quality_is_not_put_on_frontier():
    manifest = {
        "as_of": "2026-09-30",
        "targets": [
            {
                "scroll": "PHercTEST",
                "volume_id": "v1",
                "voxel_size_um": 9.0,
                "energy_kev": 100,
                "segments": 99,
                "surface_prediction": "surface",
                "lasagna_prediction": "lasagna",
                "source_url": "https://example.test",
            }
        ],
    }
    result = qualify([], manifest)

    assert result["frontier"] == []
    assert result["targets"][0]["qualification"] == "needs-quality-score"



def test_surface_support_is_separate_and_fails_closed_on_wrong_volume():
    scores = {
        "PHerc0125": 58.5,
        "PHerc0191": 43.5,
        "PHerc0211": 48.1,
        "PHerc0257": 63.9,
        "PHerc0268": 38.3,
        "PHerc0358": 53.4,
        "PHerc0800": 42.6,
        "PHerc0813": 77.4,
        "PHerc0826": 28.2,
        "PHerc1203": 53.2,
        "PHerc1218": 45.1,
        "PHerc1447": 70.7,
        "PHerc1545": 30.8,
    }
    volumes = [
        _volume(t["scroll"], t["volume_id"], scores[t["scroll"]])
        for t in DEFAULT_MANIFEST["targets"]
    ]
    support = {
        "source": {"repository": "example/evidence"},
        "rows": [
            {
                "scroll": "PHerc0800",
                "eligible_volume_id": "20250521135224",
                "survey_ct": (
                    "https://example/PHerc0800/volumes/"
                    "20250521135224-8.640um-masked.zarr"
                ),
                "volume_match": "exact",
                "usable_for_qualification": True,
                "sampled_support_frac": 0.583,
                "survey_path": "survey_PHerc0800.json",
                "survey_sha": "a",
            },
            {
                "scroll": "PHerc0813",
                "eligible_volume_id": "20250821151723",
                "survey_ct": (
                    "https://example/PHerc0813/volumes/"
                    "20250821151723-9.362um-masked.zarr"
                ),
                "volume_match": "exact",
                "usable_for_qualification": True,
                "sampled_support_frac": 0.566,
                "survey_path": "survey_PHerc0813.json",
                "survey_sha": "b",
            },
            {
                "scroll": "PHerc1447",
                "eligible_volume_id": "20250521151220",
                "survey_ct": (
                    "https://example/PHerc1447/volumes/"
                    "20250521151220-8.640um-masked.zarr"
                ),
                "volume_match": "exact",
                "usable_for_qualification": True,
                "sampled_support_frac": 0.562,
                "survey_path": "survey_PHerc1447.json",
                "survey_sha": "c",
            },
            {
                "scroll": "PHerc1203",
                "eligible_volume_id": "20250820131727",
                "survey_ct": (
                    "https://example/PHerc1203/volumes/"
                    "20260319130212-2.403um-masked.zarr"
                ),
                "volume_match": "exact",
                "usable_for_qualification": True,
                "sampled_support_frac": 0.999,
                "survey_path": "survey_PHerc1203.json",
                "survey_sha": "d",
            },
        ],
    }

    result = qualify(volumes, surface_support=support)

    # Imported evidence never changes the primary two-axis result.
    assert result["frontier"] == ["PHerc0813", "PHerc1447"]
    sensitivity = result["surface_support_analysis"]
    assert sensitivity["frontier"] == ["PHerc0800", "PHerc0813", "PHerc1447"]

    rows = {r["scroll"]: r for r in result["targets"]}
    assert rows["PHerc1203"]["surface_support_frac"] is None
    assert "does not contain prize volume ID" in (
        rows["PHerc1203"]["surface_support_exclusion_reason"]
    )
    assert "PHerc1203" in sensitivity["excluded_targets"]
