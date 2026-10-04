import copy
import json

import pytest

from scrollq.winding_validation import digest, evaluate, main


def _spec():
    return {
        "schema_version": 1,
        "diagnostic": "winding-validation-spec",
        "status": "frozen-before-prediction",
        "volume_root": "PHerc0139/volumes/exact-eligible.zarr",
        "coordinate_system": "base_voxel_xyz",
        "turn_semantics": "signed_pairwise_delta_turns",
        "reference_evidence": {
            "source_kind": "manual-independent",
            "method": "two-reviewer sparse CT turn relations",
            "source_sha256": "a" * 64,
            "established_without_candidate_output": True,
            "candidate_output_observed_before_freeze": False,
        },
        "fit_relation_ids": ["fit-001"],
        "targets": [
            {
                "id": "hold-001",
                "region_id": "r1",
                "a": {"id": "a1", "xyz": [10, 20, 30]},
                "b": {"id": "b1", "xyz": [11, 21, 31]},
                "reference_delta_turns": 0,
            },
            {
                "id": "hold-002",
                "region_id": "r2",
                "a": {"id": "a2", "xyz": [40, 50, 60]},
                "b": {"id": "b2", "xyz": [41, 51, 61]},
                "reference_delta_turns": 2,
            },
            {
                "id": "hold-003",
                "region_id": "r3",
                "a": {"id": "a3", "xyz": [70, 80, 90]},
                "b": {"id": "b3", "xyz": [71, 81, 91]},
                "reference_delta_turns": -1,
            },
        ],
    }


def _prediction(spec=None):
    spec = spec or _spec()
    return {
        "schema_version": 1,
        "diagnostic": "winding-validation-predictions",
        "volume_root": spec["volume_root"],
        "coordinate_system": "base_voxel_xyz",
        "turn_semantics": "signed_pairwise_delta_turns",
        "spec_sha256": digest(spec),
        "candidate_method": "example-winding-solver",
        "candidate_artifact_sha256": "b" * 64,
        "used_reference_ids": ["fit-001"],
        "predictions": [
            {
                "id": "hold-001",
                "status": "ok",
                "predicted_delta_turns": 0,
            },
            {
                "id": "hold-002",
                "status": "ok",
                "predicted_delta_turns": 1,
            },
            {
                "id": "hold-003",
                "status": "ok",
                "predicted_delta_turns": 2,
            },
        ],
    }


def test_scores_exact_one_wrap_and_multi_wrap_separately():
    spec = _spec()
    report = evaluate(spec, _prediction(spec))

    assert report["status"] == "measured"
    assert report["verdict"] == "fail"
    assert report["expected"] == 3
    assert report["scored"] == 3
    assert report["exact"] == 1
    assert report["catastrophic_one_wrap_hops"] == 1
    assert report["multi_wrap_errors"] == 1
    assert report["signed_error_histogram_turns"] == {
        "-1": 1,
        "0": 1,
        "3": 1,
    }

    rows = {row["id"]: row for row in report["targets"]}
    assert (
        rows["hold-002"]["error_class"]
        == "catastrophic-one-wrap-hop"
    )
    assert rows["hold-002"]["signed_error_turns"] == -1
    assert rows["hold-003"]["error_class"] == "multi-wrap-error"
    assert rows["hold-003"]["signed_error_turns"] == 3


def test_suspended_unscorable_failed_and_missing_remain_in_denominator():
    spec = _spec()
    prediction = _prediction(spec)
    prediction["predictions"] = [
        {
            "id": "hold-001",
            "status": "suspended",
            "reason": "low confidence",
        },
        {
            "id": "hold-002",
            "status": "unscorable",
            "reason": "no correspondence",
        },
    ]

    report = evaluate(spec, prediction)

    assert report["status"] == "incomplete"
    assert report["verdict"] == "fail"
    assert report["expected"] == 3
    assert report["scored"] == 0
    assert report["scorable_rate"] == 0
    assert report["status_counts"] == {
        "ok": 0,
        "suspended": 1,
        "unscorable": 1,
        "failed": 0,
        "missing": 1,
    }
    assert report["exact_rate_all_targets"] == 0
    assert report["exact_rate_scored_only"] is None


def test_all_exact_passes():
    spec = _spec()
    prediction = _prediction(spec)
    for row, target in zip(
        prediction["predictions"], spec["targets"]
    ):
        row["predicted_delta_turns"] = target[
            "reference_delta_turns"
        ]

    report = evaluate(spec, prediction)

    assert report["status"] == "measured"
    assert report["verdict"] == "pass"
    assert report["exact"] == 3
    assert report["catastrophic_one_wrap_hops"] == 0
    assert report["multi_wrap_errors"] == 0


def test_global_gauge_shift_is_not_part_of_pairwise_metric():
    spec = _spec()
    prediction = _prediction(spec)
    for row, target in zip(
        prediction["predictions"], spec["targets"]
    ):
        row["predicted_delta_turns"] = target[
            "reference_delta_turns"
        ]

    report = evaluate(spec, prediction)

    assert report["turn_semantics"] == "signed_pairwise_delta_turns"
    assert any(
        "global integer gauge shift" in limitation
        for limitation in report["limitations"]
    )


@pytest.mark.parametrize(
    "field,value,match",
    [
        ("status", "draft", "frozen-before-prediction"),
        ("coordinate_system", "zyx", "base_voxel_xyz"),
        (
            "turn_semantics",
            "absolute-label",
            "signed_pairwise_delta_turns",
        ),
    ],
)
def test_bad_spec_contract_rejected(field, value, match):
    spec = _spec()
    spec[field] = value
    prediction = _prediction(_spec())
    with pytest.raises(ValueError, match=match):
        evaluate(spec, prediction)


def test_reference_must_be_independent_and_hash_bound():
    spec = _spec()
    spec["reference_evidence"][
        "established_without_candidate_output"
    ] = False
    with pytest.raises(
        ValueError, match="established_without_candidate_output"
    ):
        evaluate(spec, _prediction(_spec()))

    spec = _spec()
    spec["reference_evidence"][
        "candidate_output_observed_before_freeze"
    ] = True
    with pytest.raises(
        ValueError, match="candidate_output_observed_before_freeze"
    ):
        evaluate(spec, _prediction(_spec()))

    spec = _spec()
    spec["reference_evidence"]["source_sha256"] = "latest"
    with pytest.raises(ValueError, match="64-hex"):
        evaluate(spec, _prediction(_spec()))


def test_heldout_relation_cannot_be_used_for_fit():
    spec = _spec()
    prediction = _prediction(spec)
    prediction["used_reference_ids"] = ["hold-001"]

    with pytest.raises(
        ValueError, match="held-out target relation"
    ):
        evaluate(spec, prediction)


def test_undeclared_fit_relation_rejected():
    spec = _spec()
    prediction = _prediction(spec)
    prediction["used_reference_ids"] = ["fit-999"]

    with pytest.raises(
        ValueError, match="undeclared fit relation"
    ):
        evaluate(spec, prediction)


def test_spec_target_cannot_overlap_fit_ids():
    spec = _spec()
    spec["fit_relation_ids"] = ["hold-001"]

    with pytest.raises(
        ValueError, match="overlaps fit_relation_ids"
    ):
        evaluate(spec, _prediction(_spec()))


def test_prediction_must_bind_exact_frozen_spec():
    spec = _spec()
    prediction = _prediction(spec)
    changed = copy.deepcopy(spec)
    changed["targets"][0]["reference_delta_turns"] = 1

    with pytest.raises(ValueError, match="spec_sha256"):
        evaluate(changed, prediction)


@pytest.mark.parametrize("delta", [True, 1.5, "1"])
def test_predicted_delta_must_be_integer(delta):
    spec = _spec()
    prediction = _prediction(spec)
    prediction["predictions"][0][
        "predicted_delta_turns"
    ] = delta

    with pytest.raises(
        ValueError, match="integer number of turns"
    ):
        evaluate(spec, prediction)


def test_non_ok_status_cannot_hide_a_delta():
    spec = _spec()
    prediction = _prediction(spec)
    prediction["predictions"][0] = {
        "id": "hold-001",
        "status": "suspended",
        "reason": "ambiguous",
        "predicted_delta_turns": 0,
    }

    with pytest.raises(ValueError, match="cannot also supply"):
        evaluate(spec, prediction)


def test_unknown_duplicate_and_bad_volume_rejected():
    spec = _spec()
    prediction = _prediction(spec)
    prediction["predictions"][0]["id"] = "unknown"
    with pytest.raises(
        ValueError, match="unknown or duplicate"
    ):
        evaluate(spec, prediction)

    prediction = _prediction(spec)
    prediction["predictions"].append(
        copy.deepcopy(prediction["predictions"][0])
    )
    with pytest.raises(
        ValueError, match="unknown or duplicate"
    ):
        evaluate(spec, prediction)

    prediction = _prediction(spec)
    prediction["volume_root"] = "other.zarr"
    with pytest.raises(ValueError, match="volume_root"):
        evaluate(spec, prediction)


def test_cli_hash_report_and_no_overwrite(tmp_path, capsys):
    spec = _spec()
    prediction = _prediction(spec)
    spec_path = tmp_path / "spec.json"
    prediction_path = tmp_path / "predictions.json"
    out = tmp_path / "report.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    prediction_path.write_text(
        json.dumps(prediction), encoding="utf-8"
    )

    assert (
        main(
            [
                "--spec",
                str(spec_path),
                "--print-spec-hash",
            ]
        )
        == 0
    )
    assert capsys.readouterr().out.strip() == digest(spec)

    rc = main(
        [
            "--spec",
            str(spec_path),
            "--predictions",
            str(prediction_path),
            "--out",
            str(out),
        ]
    )
    assert rc == 1
    assert (
        json.loads(out.read_text())[
            "catastrophic_one_wrap_hops"
        ]
        == 1
    )

    with pytest.raises(SystemExit) as error:
        main(
            [
                "--spec",
                str(spec_path),
                "--predictions",
                str(prediction_path),
                "--out",
                str(out),
            ]
        )
    assert error.value.code == 2
