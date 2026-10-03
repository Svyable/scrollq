import copy
import json

import pytest

from scrollq.geometry_validation import digest, evaluate, main


def inputs():
    spec = {"schema_version": 1, "volume_root": "exact-scan.zarr",
            "coordinate_system": "base_voxel_xyz", "tolerance_voxels": 5,
            "fit_ids": ["fit-a"], "targets": [
                {"id": "hold-a", "xyz": [0, 0, 0]},
                {"id": "hold-b", "xyz": [0, 0, 10]}]}
    pred = {"schema_version": 1, "volume_root": "exact-scan.zarr",
            "coordinate_system": "base_voxel_xyz", "checkpoint_sha256": "a" * 64,
            "used_fit_ids": ["fit-a"], "spec_sha256": digest(spec),
            "predictions": [{"id": "hold-a", "status": "ok", "xyz": [3, 4, 0]},
                            {"id": "hold-b", "status": "ok", "xyz": [0, 0, 10]}]}
    return spec, pred


def test_exact_threshold_and_injected_displacement():
    spec, pred = inputs()
    report = evaluate(spec, pred)
    assert report["within_tolerance_rate"] == 1
    assert report["predicted_only_median_error_voxels"] == 2.5
    pred["predictions"][0]["xyz"] = [3, 4, 1]
    assert evaluate(spec, pred)["within_tolerance_rate"] == 0.5


def test_missing_and_failed_remain_in_denominator():
    spec, pred = inputs()
    pred["predictions"] = [{"id": "hold-a", "status": "failed", "reason": "fit unavailable"}]
    report = evaluate(spec, pred)
    assert (report["expected"], report["missing"], report["failed"]) == (2, 1, 1)
    assert report["within_tolerance_rate"] == 0
    assert report["predicted_only_median_error_voxels"] is None
    assert report["status"] == "incomplete"


@pytest.mark.parametrize("field,value", [
    ("volume_root", "other-scan.zarr"), ("coordinate_system", "micron_zyx"),
    ("spec_sha256", "b" * 64), ("used_fit_ids", ["hold-a"]),
    ("used_fit_ids", ["unknown"]), ("used_fit_ids", []),
    ("used_fit_ids", ["fit-a", "fit-a"]), ("checkpoint_sha256", "latest"),
    ("schema_version", True),
])
def test_invalid_binding_rejected(field, value):
    spec, pred = inputs()
    pred[field] = value
    with pytest.raises(ValueError):
        evaluate(spec, pred)


@pytest.mark.parametrize("xyz", [[True, 0, 0], [0, 0], [0, float("nan"), 0],
                                [0, float("inf"), 0], [10**1000, 0, 0]])
def test_bad_coordinates_rejected(xyz):
    spec, pred = inputs()
    pred["predictions"][0]["xyz"] = xyz
    with pytest.raises(ValueError):
        evaluate(spec, pred)


@pytest.mark.parametrize("tolerance", [0, -1, True, float("inf"), float("nan")])
def test_bad_tolerance_rejected(tolerance):
    spec, pred = inputs()
    spec["tolerance_voxels"] = tolerance
    with pytest.raises(ValueError):
        evaluate(spec, pred)


def test_changed_spec_duplicate_targets_and_outputs_rejected():
    spec, pred = inputs()
    spec["tolerance_voxels"] = 50
    with pytest.raises(ValueError, match="spec_sha256"):
        evaluate(spec, pred)
    spec, pred = inputs()
    spec["targets"].append(copy.deepcopy(spec["targets"][0]))
    with pytest.raises(ValueError, match="duplicate target"):
        evaluate(spec, pred)
    spec, pred = inputs()
    pred["predictions"].append(copy.deepcopy(pred["predictions"][0]))
    with pytest.raises(ValueError, match="duplicate prediction"):
        evaluate(spec, pred)


def test_empty_targets_cannot_pass():
    spec, pred = inputs()
    spec["targets"] = []
    with pytest.raises(ValueError):
        evaluate(spec, pred)


def test_input_order_does_not_change_per_target_metrics():
    spec, pred = inputs()
    before = evaluate(spec, pred)
    pred["predictions"].reverse()
    assert evaluate(spec, pred)["targets"] == before["targets"]


def test_cli_hash_report_failure_and_no_overwrite(tmp_path, capsys):
    spec, pred = inputs()
    s, p, out = (tmp_path / name for name in ("spec.json", "pred.json", "report.json"))
    s.write_text(json.dumps(spec))
    p.write_text(json.dumps(pred))
    assert main(["--spec", str(s), "--print-spec-hash"]) == 0
    assert capsys.readouterr().out.strip() == digest(spec)
    args = ["--spec", str(s), "--predictions", str(p)]
    assert main(args + ["--out", str(out)]) == 0
    original = out.read_bytes()
    with pytest.raises(SystemExit) as error:
        main(args + ["--out", str(out)])
    assert error.value.code == 2
    assert out.read_bytes() == original
    pred["predictions"] = []
    p.write_text(json.dumps(pred))
    assert main(args) == 1
