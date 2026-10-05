import copy
import json

import pytest

from scrollq.harvest_qc_benchmark import (
    BenchmarkError,
    _control_inputs,
    digest,
    evaluate,
    main,
    positive_control,
    validate_spec,
)


def test_positive_control_passes():
    ctl = positive_control()
    assert ctl["passed"], ctl


def test_control_report_is_evaluated_and_bound_to_spec_hash():
    spec, sq, cands = _control_inputs()
    r = evaluate(spec, sq, cands)
    assert r["status"] == "evaluated"
    assert r["spec_sha256"] == digest(validate_spec(spec))
    closes = next(m for m in r["candidate_metrics"] if m["metric"] == "closes")
    assert closes["blind_spots_closed"] == ["cross"]
    assert closes["agreement_with_scrollq_gates"]["topology"][
        "metric_only_reject"] == 2


def test_seed_region_overlap_is_refused():
    spec, _, _ = _control_inputs()
    spec["surfaces"][2]["bbox_zyx"] = [[590, 610], [0, 10], [0, 10]]
    with pytest.raises(BenchmarkError, match="spatially separated"):
        validate_spec(spec)


def test_seed_region_on_other_volume_does_not_conflict():
    spec, _, _ = _control_inputs()
    spec["seed_regions"][0]["volume_id"] = "Vother"
    spec["surfaces"][0]["bbox_zyx"] = [[550, 560], [0, 10], [0, 10]]
    validate_spec(spec)


@pytest.mark.parametrize("mutate, match", [
    (lambda s: s["surfaces"][0].update(failure_class="cross_roll"),
     "no failure_class"),
    (lambda s: s["surfaces"][2].update(failure_class="looks_odd"),
     "failure_class"),
    (lambda s: s["surfaces"][1].update(truth_source=""), "truth_source"),
    (lambda s: s["surfaces"][1].update(sha256=s["surfaces"][0]["sha256"]),
     "duplicate"),
    (lambda s: s.update(min_invalid=3), "minimums"),
    (lambda s: s["candidate_metrics"][0].pop("calibration_scrolls"),
     "calibration_scrolls"),
])
def test_spec_defects_fail_closed(mutate, match):
    spec, _, _ = _control_inputs()
    mutate(spec)
    with pytest.raises(BenchmarkError, match=match):
        validate_spec(spec)


def test_decisions_against_another_spec_are_refused():
    spec, sq, cands = _control_inputs()
    sq = dict(sq, spec_sha256="0" * 64)
    with pytest.raises(BenchmarkError, match="frozen spec"):
        evaluate(spec, sq, cands)


def test_unregistered_evaluator_and_surfaces_are_refused():
    spec, sq, cands = _control_inputs()
    with pytest.raises(BenchmarkError, match="not registered"):
        evaluate(spec, sq, [dict(cands[0], evaluator="other")])
    bad = copy.deepcopy(cands[0])
    bad["decisions"]["ghost"] = {}
    with pytest.raises(BenchmarkError, match="outside the frozen spec"):
        evaluate(spec, sq, [bad])


def test_missing_candidate_file_is_incomplete():
    spec, sq, _ = _control_inputs()
    r = evaluate(spec, sq, [])
    assert {m["verdict"] for m in r["candidate_metrics"]} == {"INCOMPLETE"}


def test_missing_decision_counts_as_unknown():
    spec, sq, cands = _control_inputs()
    c = copy.deepcopy(cands[0])
    del c["decisions"]["good1"]["closes"]
    r = evaluate(spec, sq, [c])
    closes = next(m for m in r["candidate_metrics"] if m["metric"] == "closes")
    assert closes["verdict"] == "INCOMPLETE"
    assert closes["missing_decisions"] == ["good1:closes"]


def test_unknown_scrollq_gate_does_not_hide_a_blind_spot():
    spec, sq, cands = _control_inputs()
    sq = copy.deepcopy(sq)
    sq["decisions"]["cross"]["topology"] = "unknown"
    r = evaluate(spec, sq, cands)
    assert r["scrollq"]["blind_spots"] == ["cross"]
    row = next(x for x in r["scrollq"]["surfaces"] if x["surface_id"] == "cross")
    assert row["combined"] == "unknown"


def test_in_domain_decisions_are_not_promotion_evidence():
    # Calibrating on scroll B removes the only blind spot from LOSO evidence.
    spec, sq, cands = _control_inputs()
    spec["candidate_metrics"][0]["calibration_scrolls"] = ["B"]
    sq = dict(sq, spec_sha256=digest(validate_spec(spec)))
    cands = [dict(cands[0], spec_sha256=sq["spec_sha256"])]
    r = evaluate(spec, sq, cands)
    closes = next(m for m in r["candidate_metrics"] if m["metric"] == "closes")
    assert closes["verdict"] == "NO_NEW_COVERAGE"
    assert closes["in_calibration_domain_surfaces"] == ["good2", "cross"]


def test_cli_freeze_and_evaluate_are_create_only(tmp_path):
    spec, sq, cands = _control_inputs()
    (tmp_path / "spec.json").write_text(json.dumps(spec))
    (tmp_path / "sq.json").write_text(json.dumps(sq))
    (tmp_path / "ext.json").write_text(json.dumps(cands[0]))
    frozen = tmp_path / "frozen.json"
    assert main(["freeze", "--spec", str(tmp_path / "spec.json"),
                 "--out", str(frozen)]) == 0
    assert main(["freeze", "--spec", str(tmp_path / "spec.json"),
                 "--out", str(frozen)]) == 2
    out = tmp_path / "report.json"
    assert main(["evaluate", "--spec", str(frozen), "--scrollq",
                 str(tmp_path / "sq.json"), "--candidate",
                 str(tmp_path / "ext.json"), "--out", str(out)]) == 0
    report = json.loads(out.read_text())
    assert report["status"] == "evaluated"
    assert main(["self-test"]) == 0
