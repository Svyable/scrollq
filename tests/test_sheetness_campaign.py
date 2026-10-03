import json
from pathlib import Path

import pytest

from scrollq import sheetness_campaign as campaign


ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "artifacts/2026-10-03-pherc0139-sheetness-prereg/reference-plan.json"
WRONG_SPEC = ROOT / "artifacts/2026-10-03-pherc0139-wrong-wrap-prereg/wrong-wrap-spec.json"
WRONG_RESULT = ROOT / "artifacts/2026-10-03-pherc0139-wrong-wrap-run/wrong-wrap-result.json"


def _freeze(**overrides):
    kwargs = {
        "reference_plan_path": REFERENCE,
        "wrong_wrap_spec_path": WRONG_SPEC,
        "wrong_wrap_result_path": WRONG_RESULT,
        "code_revision": "a" * 40,
        "sigmas": [0.8, 1.2, 1.8],
        "beta": 0.5,
        "gamma": 0.1,
        "bright_object": True,
        "scale_objectness": False,
        "normalize": True,
        "normalize_low": 1.0,
        "normalize_high": 99.0,
        "max_voxels": 2_500_000,
        "min_score_completeness": 1.0,
        "min_normal_offset_win_fraction": 0.75,
        "min_median_normal_offset_margin": 0.0,
        "min_normal_completeness": 1.0,
        "min_median_abs_cosine": 0.7,
    }
    kwargs.update(overrides)
    return campaign.freeze_plan(**kwargs)


def test_freeze_real_pherc0139_bundle_before_sheetness():
    plan = _freeze()

    assert plan["schema"] == campaign.SCHEMA
    assert plan["status"] == "frozen-before-sheetness"
    assert plan["summary"]["group_count"] == 32
    assert plan["summary"]["ready_group_count"] == 32
    assert plan["summary"]["blocked_group_count"] == 0
    assert plan["summary"]["max_cutout_voxels"] < 2_500_000
    assert plan["engine"]["parameters"]["sigmas"] == [0.8, 1.2, 1.8]
    assert plan["engine"]["normalization"] == {
        "enabled": True,
        "lower_percentile": 1.0,
        "upper_percentile": 99.0,
    }
    assert plan["engine"]["write_normal"] is True
    assert plan["campaign_decision_rule"]["min_normal_offset_win_fraction"] == 0.75
    assert plan["campaign_decision_rule"]["min_median_abs_cosine"] == 0.7

    for group in plan["groups"]:
        assert group["status"] == "ready"
        roles = [row["role"] for row in group["controls"]]
        assert roles.count("normal-offset") == 4
        assert roles.count("wrong-wrap") == 1
        start = group["bbox_zyx_half_open"]["start"]
        stop = group["bbox_zyx_half_open"]["stop"]
        assert group["shape_zyx"] == [stop[d] - start[d] for d in range(3)]
        points = [group["surface"]["global_zyx"]] + [
            row["global_zyx"] for row in group["controls"]
        ]
        for point in points:
            for d in range(3):
                assert start[d] <= point[d] < stop[d]


def test_freeze_requires_enough_halo_for_frozen_sigma_set():
    with pytest.raises(campaign.CampaignError, match="halo"):
        _freeze(sigmas=[3.0])


def test_freeze_rejects_changed_wrong_wrap_result_binding(tmp_path):
    payload = json.loads(WRONG_RESULT.read_text())
    payload["spec"]["file_sha256"] = "0" * 64
    changed = tmp_path / "wrong-result.json"
    changed.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(campaign.CampaignError, match="bind supplied spec"):
        _freeze(wrong_wrap_result_path=changed)


def test_freeze_rejects_hidden_sheetness_consultation(tmp_path):
    payload = json.loads(WRONG_RESULT.read_text())
    payload["sheetness_response_consulted"] = True
    changed = tmp_path / "wrong-result.json"
    changed.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(campaign.CampaignError, match="consulted sheetness"):
        _freeze(wrong_wrap_result_path=changed)


def test_freeze_rejects_cutout_memory_contract_too_small():
    with pytest.raises(campaign.CampaignError, match="above frozen max_voxels"):
        _freeze(max_voxels=1)


def _write_plan(tmp_path):
    plan = _freeze()
    path = tmp_path / "campaign-plan.json"
    path.write_text(json.dumps(plan, sort_keys=True), encoding="utf-8")
    return plan, path


def _cutout_manifest(plan, group):
    start = group["bbox_zyx_half_open"]["start"]
    return {
        "schema": "scroliq-ct-cutout/1",
        "status": "measured",
        "volume_root": plan["volume_root"],
        "level": 0,
        "coordinate_space": "level0-voxel-index",
        "source_attestation": {
            **plan["source_attestation"],
        },
        "zpa_report": {
            "sha256": plan["zpa_report_sha256"],
            "integrity": "PASS",
        },
        "bbox_zyx_half_open": group["bbox_zyx_half_open"],
        "local_to_global": {
            "kind": "integer-translation",
            "start_zyx": start,
        },
        "source_chunks": {"missing_count": 0},
        "cutout": {
            "sha256": "c" * 64,
            "shape_zyx": group["shape_zyx"],
            "dtype": "uint8",
        },
    }


def _sheetness_report(plan, group):
    return {
        "schema_version": 1,
        "kind": "sheetness",
        "status": "measured",
        "input": {
            "sha256": "c" * 64,
            "shape_zyx": group["shape_zyx"],
        },
        "method": plan["engine"]["method"],
        "parameters": plan["engine"]["parameters"],
        "normalization": {
            "enabled": True,
            "lower_percentile": 1.0,
            "upper_percentile": 99.0,
            "lower_value": 10.0,
            "upper_value": 200.0,
        },
        "response": {"output_sha256": "d" * 64},
        "normal": {"output_sha256": "e" * 64},
    }


def test_seal_group_materializes_measurement_only_v3_spec(tmp_path):
    plan, plan_path = _write_plan(tmp_path)
    group = plan["groups"][0]
    manifest_path = tmp_path / "cutout.json"
    report_path = tmp_path / "sheetness.json"
    manifest_path.write_text(
        json.dumps(_cutout_manifest(plan, group), sort_keys=True),
        encoding="utf-8",
    )
    report_path.write_text(
        json.dumps(_sheetness_report(plan, group), sort_keys=True),
        encoding="utf-8",
    )

    spec = campaign.seal_group(
        plan_path=plan_path,
        group_id=group["id"],
        cutout_manifest_path=manifest_path,
        sheetness_report_path=report_path,
    )
    assert spec["schema_version"] == 3
    assert spec["campaign_group_id"] == group["id"]
    assert spec["decision_rule"] == campaign.MEASUREMENT_ONLY_RULE
    assert spec["campaign_decision_rule"] == plan["campaign_decision_rule"]
    row = spec["groups"][0]
    assert len([c for c in row["controls"] if c["role"] == "normal-offset"]) == 4
    assert len([c for c in row["controls"] if c["role"] == "wrong-wrap"]) == 1


def test_seal_group_rejects_engine_parameter_drift(tmp_path):
    plan, plan_path = _write_plan(tmp_path)
    group = plan["groups"][0]
    manifest_path = tmp_path / "cutout.json"
    report_path = tmp_path / "sheetness.json"
    manifest_path.write_text(
        json.dumps(_cutout_manifest(plan, group), sort_keys=True),
        encoding="utf-8",
    )
    report = _sheetness_report(plan, group)
    report["parameters"]["sigmas"] = [1.0]
    report_path.write_text(json.dumps(report, sort_keys=True), encoding="utf-8")
    with pytest.raises(campaign.CampaignError, match="sigmas"):
        campaign.seal_group(
            plan_path=plan_path,
            group_id=group["id"],
            cutout_manifest_path=manifest_path,
            sheetness_report_path=report_path,
        )


def test_seal_group_rejects_bbox_drift(tmp_path):
    plan, plan_path = _write_plan(tmp_path)
    group = plan["groups"][0]
    manifest = _cutout_manifest(plan, group)
    manifest["bbox_zyx_half_open"]["start"][0] -= 1
    manifest_path = tmp_path / "cutout.json"
    report_path = tmp_path / "sheetness.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    report_path.write_text(
        json.dumps(_sheetness_report(plan, group)), encoding="utf-8"
    )
    with pytest.raises(campaign.CampaignError, match="bbox"):
        campaign.seal_group(
            plan_path=plan_path,
            group_id=group["id"],
            cutout_manifest_path=manifest_path,
            sheetness_report_path=report_path,
        )


def _write_aggregate_bundle(tmp_path, *, wins=24, cosine=0.8):
    plan, plan_path = _write_plan(tmp_path)
    specs = tmp_path / "specs"
    results = tmp_path / "results"
    specs.mkdir()
    results.mkdir()
    plan_sha = campaign.sha256_file(plan_path)

    for i, group in enumerate(plan["groups"]):
        gid = group["id"]
        spec = {
            "schema_version": 3,
            "campaign_plan_sha256": plan_sha,
            "campaign_group_id": gid,
        }
        spec_path = specs / f"{gid}.json"
        spec_path.write_text(json.dumps(spec, sort_keys=True), encoding="utf-8")
        win = i < wins
        result = {
            "schema": "scroliq-sheetness-benchmark/3",
            "status": "pass",
            "volume_root": plan["volume_root"],
            "spec": {
                "file_sha256": campaign.sha256_file(spec_path),
            },
            "metrics": {"group_count": 1},
            "groups": [
                {
                    "id": gid,
                    "score_complete": True,
                    "surface_beats_all_normal_offsets": win,
                    "surface_minus_best_normal_offset": 0.1 if win else -0.1,
                    "surface_beats_all_wrong_wraps": False,
                    "surface_minus_best_wrong_wrap": -0.05,
                    "surface": {
                        "predicted_normal_abs_cosine": cosine,
                    },
                }
            ],
        }
        (results / f"{gid}.json").write_text(
            json.dumps(result, sort_keys=True), encoding="utf-8"
        )
    return plan, plan_path, specs, results


def test_aggregate_applies_rule_once_across_all_groups(tmp_path):
    plan, plan_path, specs, results = _write_aggregate_bundle(
        tmp_path, wins=24, cosine=0.8
    )
    result = campaign.aggregate(
        plan_path=plan_path, specs_dir=specs, results_dir=results
    )
    assert result["status"] == "pass"
    assert result["metrics"]["group_count"] == 32
    assert result["metrics"]["normal_offset_win_count"] == 24
    assert result["metrics"]["normal_offset_win_fraction"] == 0.75
    assert result["metrics"]["score_completeness"] == 1.0
    assert result["metrics"]["normal_completeness"] == 1.0
    assert result["decision_checks"]["no_invalid_or_missing_groups"] is True


def test_aggregate_missing_group_stays_in_denominator_and_fails(tmp_path):
    _, plan_path, specs, results = _write_aggregate_bundle(
        tmp_path, wins=32, cosine=0.9
    )
    (results / "surface-0001.json").unlink()
    result = campaign.aggregate(
        plan_path=plan_path, specs_dir=specs, results_dir=results
    )
    assert result["status"] == "fail"
    assert result["metrics"]["group_count"] == 32
    assert result["metrics"]["score_completeness"] == pytest.approx(31 / 32)
    assert result["metrics"]["failed_group_count"] == 1
    assert result["decision_checks"]["no_invalid_or_missing_groups"] is False


def test_aggregate_wrong_wrap_is_descriptive_only(tmp_path):
    _, plan_path, specs, results = _write_aggregate_bundle(
        tmp_path, wins=32, cosine=0.9
    )
    result = campaign.aggregate(
        plan_path=plan_path, specs_dir=specs, results_dir=results
    )
    assert result["status"] == "pass"
    assert result["metrics"]["wrong_wrap_win_fraction_descriptive"] == 0.0


def test_cli_freeze_is_create_only(tmp_path):
    out = tmp_path / "plan.json"
    args = [
        "freeze",
        "--reference-plan", str(REFERENCE),
        "--wrong-wrap-spec", str(WRONG_SPEC),
        "--wrong-wrap-result", str(WRONG_RESULT),
        "--code-revision", "a" * 40,
        "--sigmas", "0.8,1.2,1.8",
        "--beta", "0.5",
        "--gamma", "0.1",
        "--bright-object",
        "--no-scale-objectness",
        "--normalize",
        "--normalize-low", "1",
        "--normalize-high", "99",
        "--max-voxels", "2500000",
        "--min-score-completeness", "1",
        "--min-normal-offset-win-fraction", "0.75",
        "--min-median-normal-offset-margin", "0",
        "--min-normal-completeness", "1",
        "--min-median-abs-cosine", "0.7",
        "--out", str(out),
    ]
    assert campaign.main(args) == 0
    original = out.read_bytes()
    assert campaign.main(args) == 2
    assert out.read_bytes() == original
