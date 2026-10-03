import copy
import json

import pytest

from scrollq.sheetness_validation import digest, evaluate, main


def inputs():
    spec = {
        "schema_version": 1,
        "volume_root": "exact-scan.zarr",
        "coordinate_system": "base_voxel_xyz",
        "criteria": {
            "min_surface_control_margin": 0.1,
            "min_surface_normal_abs_cosine": 0.9,
        },
        "probes": [
            {
                "id": "g1-surface",
                "group_id": "g1",
                "role": "surface",
                "xyz": [10, 20, 30],
                "reference_normal_xyz": [0, 0, 1],
            },
            {
                "id": "g1-offset-plus",
                "group_id": "g1",
                "role": "normal_offset",
                "xyz": [10, 20, 33],
                "reference_surface_id": "g1-surface",
                "offset_voxels": 3,
            },
            {
                "id": "g1-wrong-wrap",
                "group_id": "g1",
                "role": "wrong_wrap",
                "xyz": [14, 25, 40],
                "reference_surface_id": "g1-surface",
            },
        ],
    }
    observations = {
        "schema_version": 1,
        "volume_root": "exact-scan.zarr",
        "coordinate_system": "base_voxel_xyz",
        "spec_sha256": digest(spec),
        "engine": {
            "name": "test-sheetness",
            "version": "1.0",
            "config_sha256": "a" * 64,
            "deterministic": True,
        },
        "observations": [
            {
                "id": "g1-surface",
                "status": "ok",
                "sheetness": 0.8,
                "normal_xyz": [0, 0, -2],
                "scale_voxels": 2,
            },
            {"id": "g1-offset-plus", "status": "ok", "sheetness": 0.5},
            {"id": "g1-wrong-wrap", "status": "ok", "sheetness": 0.4},
        ],
    }
    return spec, observations


def test_surface_beats_controls_and_normal_sign_is_ignored():
    spec, observations = inputs()
    report = evaluate(spec, observations)

    assert report["status"] == "measured"
    assert report["meets_frozen_criteria"] is True
    assert report["groups_meeting_frozen_criteria_rate"] == 1
    assert report["groups"][0]["surface_control_margin"] == pytest.approx(0.3)
    assert report["groups"][0]["surface_normal_abs_cosine"] == pytest.approx(1)


def test_deliberate_wrong_control_score_fails_frozen_criteria():
    spec, observations = inputs()
    observations["observations"][2]["sheetness"] = 0.75

    report = evaluate(spec, observations)

    assert report["status"] == "measured"
    assert report["meets_frozen_criteria"] is False
    assert report["groups"][0]["surface_beats_controls"] is False


def test_bad_normal_fails_even_when_score_margin_passes():
    spec, observations = inputs()
    observations["observations"][0]["normal_xyz"] = [1, 0, 0]

    report = evaluate(spec, observations)

    assert report["groups"][0]["surface_beats_controls"] is True
    assert report["groups"][0]["surface_normal_aligned"] is False
    assert report["meets_frozen_criteria"] is False


def test_missing_and_failed_probes_remain_visible_and_cannot_pass():
    spec, observations = inputs()
    observations["observations"] = [
        observations["observations"][0],
        {
            "id": "g1-offset-plus",
            "status": "failed",
            "reason": "out of bounds",
        },
    ]

    report = evaluate(spec, observations)

    assert report["status"] == "incomplete"
    assert (report["observed_ok"], report["failed"], report["missing"]) == (1, 1, 1)
    assert report["meets_frozen_criteria"] is False
    assert report["groups"][0]["complete"] is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("volume_root", "other-scan.zarr"),
        ("coordinate_system", "micron_zyx"),
        ("spec_sha256", "b" * 64),
        ("schema_version", True),
    ],
)
def test_binding_mismatches_are_rejected(field, value):
    spec, observations = inputs()
    observations[field] = value
    with pytest.raises(ValueError):
        evaluate(spec, observations)


def test_stochastic_engine_requires_seed():
    spec, observations = inputs()
    observations["engine"]["deterministic"] = False

    with pytest.raises(ValueError, match="seed"):
        evaluate(spec, observations)

    observations["engine"]["seed"] = 17
    assert evaluate(spec, observations)["engine"]["seed"] == 17


@pytest.mark.parametrize(
    "mutator,match",
    [
        (lambda spec: spec["probes"].append(copy.deepcopy(spec["probes"][0])), "duplicate probe"),
        (
            lambda spec: spec["probes"][1].update(reference_surface_id="not-the-surface"),
            "must reference surface",
        ),
        (
            lambda spec: spec["probes"][1].update(offset_voxels=0),
            "must be non-zero",
        ),
        (
            lambda spec: spec["criteria"].update(min_surface_normal_abs_cosine=1.1),
            r"\[0, 1\]",
        ),
    ],
)
def test_invalid_frozen_spec_is_rejected(mutator, match):
    spec, observations = inputs()
    mutator(spec)
    observations["spec_sha256"] = digest(spec)
    with pytest.raises(ValueError, match=match):
        evaluate(spec, observations)


def test_unknown_duplicate_and_bad_observations_are_rejected():
    spec, observations = inputs()

    bad = copy.deepcopy(observations)
    bad["observations"][0]["id"] = "unknown"
    with pytest.raises(ValueError, match="unknown or duplicate"):
        evaluate(spec, bad)

    bad = copy.deepcopy(observations)
    bad["observations"].append(copy.deepcopy(bad["observations"][0]))
    with pytest.raises(ValueError, match="unknown or duplicate"):
        evaluate(spec, bad)

    bad = copy.deepcopy(observations)
    bad["observations"][0]["normal_xyz"] = [0, 0, 0]
    with pytest.raises(ValueError, match="non-zero"):
        evaluate(spec, bad)


def test_changed_spec_is_rejected():
    spec, observations = inputs()
    spec["criteria"]["min_surface_control_margin"] = 0.2

    with pytest.raises(ValueError, match="spec_sha256"):
        evaluate(spec, observations)


def test_cli_hash_pass_fail_and_no_overwrite(tmp_path, capsys):
    spec, observations = inputs()
    spec_path = tmp_path / "spec.json"
    obs_path = tmp_path / "observations.json"
    out = tmp_path / "report.json"
    spec_path.write_text(json.dumps(spec))
    obs_path.write_text(json.dumps(observations))

    assert main(["--spec", str(spec_path), "--print-spec-hash"]) == 0
    assert capsys.readouterr().out.strip() == digest(spec)

    args = ["--spec", str(spec_path), "--observations", str(obs_path)]
    assert main(args + ["--out", str(out)]) == 0
    original = out.read_bytes()

    with pytest.raises(SystemExit) as error:
        main(args + ["--out", str(out)])
    assert error.value.code == 2
    assert out.read_bytes() == original

    observations["observations"][2]["sheetness"] = 0.75
    obs_path.write_text(json.dumps(observations))
    assert main(args) == 1
