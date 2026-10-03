import json

import pytest

from scrollq.geometry_tournament import GeometryTournamentError, evaluate_tournament, main


def _sha(ch):
    return ch * 64


def report(*, prediction="a", checkpoint="1", errors=(1.0, 2.0), statuses=None):
    if statuses is None:
        statuses = ["ok"] * len(errors)
    targets = []
    within = 0
    ok_errors = []
    for i, (status, error) in enumerate(zip(statuses, errors)):
        row = {
            "id": f"h{i}",
            "reference_xyz": [0, 0, i * 10],
            "status": status,
            "within_tolerance": False,
        }
        if status == "ok":
            row["error_voxels"] = float(error)
            row["xyz"] = [0, 0, i * 10 + error]
            row["within_tolerance"] = error <= 5
            within += int(error <= 5)
            ok_errors.append(float(error))
        elif status == "failed":
            row["reason"] = "no fit"
        targets.append(row)
    expected = len(targets)
    predicted = len(ok_errors)
    missing = sum(s == "missing" for s in statuses)
    failed = sum(s == "failed" for s in statuses)
    ordered = sorted(ok_errors)
    if not ordered:
        median = None
    elif len(ordered) % 2:
        median = ordered[len(ordered) // 2]
    else:
        middle = len(ordered) // 2
        median = (ordered[middle - 1] + ordered[middle]) / 2
    return {
        "schema_version": 1,
        "tool": "scroliq-geometry-validate",
        "status": "measured" if predicted == expected else "incomplete",
        "volume_root": "PHerc0826/volumes/exact.zarr",
        "coordinate_system": "base_voxel_xyz",
        "spec_sha256": _sha("f"),
        "prediction_sha256": _sha(prediction),
        "checkpoint_sha256": _sha(checkpoint),
        "tolerance_voxels": 5,
        "expected": expected,
        "predicted": predicted,
        "missing": missing,
        "failed": failed,
        "within_tolerance": within,
        "within_tolerance_rate": within / expected,
        "predicted_only_median_error_voxels": median,
        "predicted_only_max_error_voxels": max(ok_errors) if ok_errors else None,
        "targets": targets,
    }


def entry(name, doc, ch):
    return name, doc, _sha(ch)


def test_complete_unique_pareto_winner():
    baseline = report(prediction="a", checkpoint="1", errors=(2.0, 4.0))
    better = report(prediction="b", checkpoint="2", errors=(1.0, 2.0))
    result = evaluate_tournament(
        [entry("baseline", baseline, "c"), entry("candidate", better, "d")]
    )
    assert result["decision"] == "winner"
    assert result["winner"] == "candidate"
    assert result["frontier"] == ["candidate"]
    assert {tuple(x.values()) for x in result["pairwise_dominance"]} == {
        ("candidate", "baseline")
    }


def test_tradeoff_stays_indeterminate_without_weighting():
    low_error = report(prediction="a", checkpoint="1", errors=(1.0, 6.0))
    more_hits = report(prediction="b", checkpoint="2", errors=(4.0, 4.0))
    result = evaluate_tournament(
        [entry("low-error", low_error, "c"), entry("more-hits", more_hits, "d")]
    )
    assert result["decision"] == "indeterminate"
    assert result["winner"] is None
    assert set(result["frontier"]) == {"low-error", "more-hits"}


def test_incomplete_candidate_prevents_winner_even_if_dominated():
    complete = report(prediction="a", checkpoint="1", errors=(1.0, 1.0))
    incomplete = report(
        prediction="b",
        checkpoint="2",
        errors=(9.0, 9.0),
        statuses=["ok", "missing"],
    )
    result = evaluate_tournament(
        [entry("complete", complete, "c"), entry("incomplete", incomplete, "d")]
    )
    assert result["status"] == "incomplete"
    assert result["decision"] == "indeterminate"
    assert result["winner"] is None


def test_mismatched_frozen_evidence_and_duplicate_predictions_rejected():
    a = report(prediction="a")
    b = report(prediction="b", checkpoint="2")
    b["spec_sha256"] = _sha("e")
    with pytest.raises(GeometryTournamentError, match="spec_sha256"):
        evaluate_tournament([entry("a", a, "c"), entry("b", b, "d")])
    b = report(prediction="a", checkpoint="2")
    with pytest.raises(GeometryTournamentError, match="prediction_sha256"):
        evaluate_tournament([entry("a", a, "c"), entry("b", b, "d")])


def test_tampered_summary_is_rejected():
    a = report(prediction="a")
    b = report(prediction="b", checkpoint="2")
    b["within_tolerance_rate"] = 0.5
    with pytest.raises(GeometryTournamentError, match="within_tolerance_rate"):
        evaluate_tournament([entry("a", a, "c"), entry("b", b, "d")])


def test_requires_two_unique_candidates():
    a = report(prediction="a")
    with pytest.raises(GeometryTournamentError, match="at least two"):
        evaluate_tournament([entry("a", a, "c")])
    with pytest.raises(GeometryTournamentError, match="candidate ids"):
        evaluate_tournament(
            [entry("a", a, "c"), entry("a", report(prediction="b"), "d")]
        )


def test_cli_writes_once_and_returns_one_for_tie(tmp_path):
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    out = tmp_path / "tournament.json"
    a.write_text(json.dumps(report(prediction="a", errors=(1.0, 6.0))))
    b.write_text(
        json.dumps(report(prediction="b", checkpoint="2", errors=(4.0, 4.0)))
    )
    args = [
        "--candidate",
        f"a={a}",
        "--candidate",
        f"b={b}",
        "--out",
        str(out),
    ]
    assert main(args) == 1
    saved = out.read_bytes()
    with pytest.raises(SystemExit) as exc:
        main(args)
    assert exc.value.code == 2
    assert out.read_bytes() == saved
