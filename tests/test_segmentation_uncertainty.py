import json

import pytest

from scrollq.segmentation_uncertainty import (
    StructuralUncertaintyError,
    digest,
    evaluate,
    main,
)


PROVENANCE = {
    "checkpoint_sha256": "a" * 64,
    "inference_script_sha256": "b" * 64,
    "inference_config_sha256": "c" * 64,
}


def _spec(alpha=0.25, calibration_ids=None, test_ids=None):
    calibration_ids = calibration_ids or ["c1", "c2", "c3", "c4"]
    test_ids = test_ids or ["t1", "t2"]
    return {
        "schema_version": 1,
        "method": "split_conformal",
        "alpha": alpha,
        "boundary_metric": "symmetric_p95_voxels",
        "component_metric": "truth_component_recall_any",
        "max_nonvacuous_boundary_voxels": 4.0,
        "calibration": {
            "dataset": "calibration-v1",
            "region_ids": calibration_ids,
        },
        "test": {
            "dataset": "test-v1",
            "region_ids": test_ids,
        },
    }


def _results(dataset, ids, boundaries, component_recalls=None, provenance=None):
    if component_recalls is None:
        component_recalls = [1.0] * len(ids)
    rows = []
    for region_id, boundary, recall in zip(ids, boundaries, component_recalls):
        rows.append(
            {
                "id": region_id,
                "status": "ok",
                "metrics": {
                    "symmetric_p95_voxels": boundary,
                    "truth_component_recall_any": recall,
                },
            }
        )
    return {
        "schema_version": 1,
        "model": "surface-model-v1",
        "dataset": dataset,
        "task": "segmentation",
        "provenance": dict(PROVENANCE if provenance is None else provenance),
        "regions": rows,
    }


def test_nonvacuous_boundary_and_component_bounds_pass():
    spec = _spec()
    calibration = _results(
        "calibration-v1",
        spec["calibration"]["region_ids"],
        [1.0, 2.0, 2.5, 3.0],
    )
    test = _results(
        "test-v1",
        spec["test"]["region_ids"],
        [2.0, 3.0],
    )

    report = evaluate(spec, calibration, test)

    assert report["boundary"]["upper_voxels"] == 3.0
    assert report["component"]["upper"] == 0.0
    assert report["boundary"]["test_empirical_coverage"] == 1.0
    assert report["component"]["test_empirical_coverage"] == 1.0
    assert report["vacuous"] is False
    assert report["proof_gate_pass"] is True


def test_component_miss_in_calibration_makes_structural_bound_vacuous():
    spec = _spec()
    calibration = _results(
        "calibration-v1",
        spec["calibration"]["region_ids"],
        [1.0, 2.0, 2.5, 3.0],
        [1.0, 1.0, 1.0, 0.5],
    )
    test = _results(
        "test-v1",
        spec["test"]["region_ids"],
        [1.0, 2.0],
    )

    report = evaluate(spec, calibration, test)

    assert report["component"]["upper"] == 1.0
    assert report["component"]["vacuous"] is True
    assert report["proof_gate_pass"] is False
    assert any("completely missed" in reason for reason in report["reasons"])


def test_small_calibration_cannot_claim_finite_95_percent_bound():
    cal_ids = [f"c{i}" for i in range(10)]
    spec = _spec(alpha=0.05, calibration_ids=cal_ids)
    calibration = _results("calibration-v1", cal_ids, [1.0] * len(cal_ids))
    test = _results("test-v1", spec["test"]["region_ids"], [1.0, 1.0])

    report = evaluate(spec, calibration, test)

    assert report["boundary"]["upper_voxels"] is None
    assert report["component"]["upper"] is None
    assert report["vacuous"] is True
    assert report["proof_gate_pass"] is False
    assert any("too small" in reason for reason in report["reasons"])


def test_test_component_miss_fails_empirical_coverage():
    spec = _spec()
    calibration = _results(
        "calibration-v1",
        spec["calibration"]["region_ids"],
        [1.0, 1.5, 2.0, 2.5],
    )
    test = _results(
        "test-v1",
        spec["test"]["region_ids"],
        [1.0, 2.0],
        [1.0, 0.0],
    )

    report = evaluate(spec, calibration, test)

    assert report["component"]["upper"] == 0.0
    assert report["component"]["test_empirical_coverage"] == 0.5
    assert report["component"]["coverage_verified"] is False
    assert report["proof_gate_pass"] is False


def test_region_set_and_provenance_are_fail_closed():
    spec = _spec()
    calibration = _results(
        "calibration-v1",
        spec["calibration"]["region_ids"],
        [1.0, 2.0, 2.5, 3.0],
    )
    test = _results(
        "test-v1",
        spec["test"]["region_ids"],
        [1.0, 2.0],
    )

    test["regions"].pop()
    with pytest.raises(StructuralUncertaintyError, match="region IDs"):
        evaluate(spec, calibration, test)

    test = _results(
        "test-v1",
        spec["test"]["region_ids"],
        [1.0, 2.0],
        provenance={**PROVENANCE, "checkpoint_sha256": "d" * 64},
    )
    report = evaluate(spec, calibration, test)
    assert report["proof_gate_pass"] is False
    assert any("provenance differs" in reason for reason in report["reasons"])


def test_cli_hash_create_only_and_exit_status(tmp_path, capsys):
    spec = _spec()
    calibration = _results(
        "calibration-v1",
        spec["calibration"]["region_ids"],
        [1.0, 2.0, 2.5, 3.0],
    )
    test = _results(
        "test-v1",
        spec["test"]["region_ids"],
        [2.0, 3.0],
    )
    spec_path = tmp_path / "spec.json"
    cal_path = tmp_path / "cal.json"
    test_path = tmp_path / "test.json"
    out_path = tmp_path / "report.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    cal_path.write_text(json.dumps(calibration), encoding="utf-8")
    test_path.write_text(json.dumps(test), encoding="utf-8")

    assert main(["--spec", str(spec_path), "--print-spec-hash"]) == 0
    assert capsys.readouterr().out.strip() == digest(spec)

    args = [
        "--spec", str(spec_path),
        "--calibration", str(cal_path),
        "--test", str(test_path),
        "--out", str(out_path),
        "--format", "json",
    ]
    assert main(args) == 0
    assert out_path.is_file()
    original = out_path.read_bytes()

    with pytest.raises(SystemExit) as error:
        main(args)
    assert error.value.code == 2
    assert out_path.read_bytes() == original
