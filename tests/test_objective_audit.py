import json
import math

import pytest

from scrollq.objective_audit import (
    ObjectiveAuditError,
    ObjectiveTracker,
    audit_objective,
    main,
)

DENSE = ("dense_normal", "dense_spacing")


def _configured(dense_expect=None):
    def term(name, weight, **extra):
        row = {"name": name, "weight": weight, **extra}
        return row

    return {
        "terms": [
            term("sheet_fit", 1.0),
            term("dense_normal", 2.0, claim="inter-sheet-ordering",
                 **({"expect": dense_expect} if dense_expect else {})),
            term("dense_spacing", 0.5, claim="inter-sheet-spacing",
                 **({"expect": dense_expect} if dense_expect else {})),
        ]
    }


def _loop(*, dense_active, steps=10, dense_weighted_value=0.25, tracker=None):
    """A stand-in training loop. With no outer-shell mesh the dense terms
    return exactly zero (masked) while their configured weights stay nonzero."""
    tracker = tracker or ObjectiveTracker(["sheet_fit", *DENSE])
    for step in range(steps):
        tracker.record("sheet_fit", 0.5 + step * 0.01, grad_norm=0.3)
        for name in DENSE:
            if dense_active:
                tracker.record(name, dense_weighted_value, grad_norm=0.2)
            else:
                tracker.record(name, 0.0, grad_norm=0.0)
        tracker.end_step()
    return tracker


def _passport(tracker, configured=None, **extra):
    return {
        "schema_version": 1,
        "run_id": "synthetic",
        "configured_objective": configured or _configured(),
        "effective_objective": tracker.effective_objective(),
        **extra,
    }


def _codes(report, name):
    row = next(r for r in report["terms"] if r["name"] == name)
    return {f["code"] for f in row["failures"]}


def test_all_terms_active_with_gradient_evidence_is_verified():
    report = audit_objective(_passport(_loop(dense_active=True)))

    assert report["verdict"] == "OBJECTIVE_VERIFIED"
    assert report["summary"]["configured_active"] == 3
    assert report["summary"]["effectively_active"] == 3
    assert report["summary"]["claims_with_gradient_evidence"] == [
        "inter-sheet-ordering",
        "inter-sheet-spacing",
    ]
    assert report["steps"] == 10
    assert len(report["passport_sha256"]) == 64


def test_nonzero_configured_weight_with_silently_zero_term_fails():
    # Reported failure shape: weights are nonzero, nothing errors, the dense
    # terms just evaluate to exactly zero every step.
    passport = _passport(_loop(dense_active=False))
    assert all(t["weight"] != 0 for t in passport["configured_objective"]["terms"])

    report = audit_objective(passport)

    assert report["verdict"] == "OBJECTIVE_INTEGRITY_FAILURE"
    assert report["summary"]["failed_terms"] == list(DENSE)
    for name in DENSE:
        assert _codes(report, name) == {"ALWAYS_ZERO", "ZERO_GRADIENT"}
    assert _codes(report, "sheet_fit") == set()
    assert report["summary"]["effectively_active"] == 1
    assert report["summary"]["claims_with_gradient_evidence"] == []


def test_a_term_the_loop_never_evaluated_is_explicit_in_the_record():
    tracker = ObjectiveTracker(["sheet_fit", *DENSE])
    for _ in range(5):
        tracker.record("sheet_fit", 0.4, grad_norm=0.1)
        tracker.end_step()

    effective = {t["name"]: t for t in tracker.effective_objective()["terms"]}
    assert effective["dense_normal"]["evaluations"] == 0

    report = audit_objective(_passport(tracker))
    assert _codes(report, "dense_normal") == {"NEVER_EVALUATED"}


def test_configured_term_absent_from_the_effective_block_fails():
    passport = _passport(_loop(dense_active=True))
    passport["effective_objective"]["terms"] = [
        t for t in passport["effective_objective"]["terms"] if t["name"] != "dense_spacing"
    ]
    report = audit_objective(passport)
    assert _codes(report, "dense_spacing") == {"MISSING_FROM_EFFECTIVE"}


def test_nonfinite_evaluations_and_gradients_fail():
    tracker = ObjectiveTracker(["sheet_fit", *DENSE])
    for step in range(4):
        tracker.record("sheet_fit", 0.5, grad_norm=0.3)
        tracker.record("dense_normal", float("nan") if step == 1 else 0.2, grad_norm=0.2)
        tracker.record("dense_spacing", 0.1, grad_norm=float("inf") if step == 2 else 0.1)
        tracker.end_step()

    report = audit_objective(_passport(tracker))

    assert _codes(report, "dense_normal") == {"NONFINITE"}
    assert _codes(report, "dense_spacing") == {"NONFINITE_GRADIENT"}
    nan_row = next(t for t in tracker.effective_objective()["terms"] if t["name"] == "dense_normal")
    assert nan_row["evaluations"] == 4 and nan_row["finite_evaluations"] == 3


def test_claimed_term_needs_gradient_evidence_but_unclaimed_does_not():
    tracker = ObjectiveTracker(["sheet_fit", *DENSE])
    for _ in range(3):
        tracker.record("sheet_fit", 0.5)  # unclaimed, no gradient reported: fine
        tracker.record("dense_normal", 0.2)  # claimed, no gradient: not enough
        tracker.record("dense_spacing", 0.1, grad_norm=0.1)
        tracker.end_step()
    passport = _passport(tracker)

    strict = audit_objective(passport)
    assert _codes(strict, "dense_normal") == {"NO_GRADIENT_EVIDENCE"}
    assert _codes(strict, "sheet_fit") == set()

    lenient = audit_objective(passport, require_gradient_for_claims=False)
    assert lenient["verdict"] == "OBJECTIVE_VERIFIED"
    assert lenient["summary"]["claims_with_gradient_evidence"] == ["inter-sheet-spacing"]


def test_min_nonzero_fraction_catches_a_mostly_dead_term():
    tracker = ObjectiveTracker(["sheet_fit", *DENSE])
    for step in range(10):
        tracker.record("sheet_fit", 0.5, grad_norm=0.3)
        for name in DENSE:
            tracker.record(name, 0.2 if step == 0 else 0.0, grad_norm=0.1)
        tracker.end_step()
    passport = _passport(tracker)

    assert audit_objective(passport)["verdict"] == "OBJECTIVE_VERIFIED"
    strict = audit_objective(passport, min_nonzero_fraction=0.5)
    assert _codes(strict, "dense_normal") == {"LOW_ACTIVATION"}
    assert strict["terms"][1]["nonzero_fraction"] == pytest.approx(0.1)


def test_ablation_arm_must_actually_be_inactive():
    configured = _configured()
    for term in configured["terms"]:
        if term["name"] in DENSE:
            term["expect"] = "inactive"
            del term["claim"]

    ablated = audit_objective(_passport(_loop(dense_active=False), configured))
    assert ablated["verdict"] == "OBJECTIVE_VERIFIED"
    assert ablated["summary"]["configured_inactive"] == 2

    leaky = audit_objective(_passport(_loop(dense_active=True), configured))
    assert leaky["verdict"] == "OBJECTIVE_INTEGRITY_FAILURE"
    assert _codes(leaky, "dense_normal") == {
        "INACTIVE_TERM_IS_ACTIVE",
        "INACTIVE_TERM_HAS_GRADIENT",
    }


def test_inactive_by_zero_weight_is_inferred_and_checked():
    configured = {
        "terms": [
            {"name": "sheet_fit", "weight": 1.0},
            {"name": "dense_normal", "weight": 0.0},
        ]
    }
    tracker = ObjectiveTracker(["sheet_fit", "dense_normal"])
    for _ in range(3):
        tracker.record("sheet_fit", 0.5, grad_norm=0.3)
        tracker.record("dense_normal", 0.0)
        tracker.end_step()
    report = audit_objective(_passport(tracker, configured))
    assert report["verdict"] == "OBJECTIVE_VERIFIED"
    assert report["terms"][1]["expect"] == "inactive"


def test_active_term_the_config_never_declared_fails_but_a_dead_one_does_not():
    tracker = _loop(dense_active=True)
    for _ in range(3):
        tracker.record("hidden_regulariser", 0.3)
        tracker.record("unused_probe", 0.0)
    report = audit_objective(_passport(tracker))

    assert report["verdict"] == "OBJECTIVE_INTEGRITY_FAILURE"
    assert [u["name"] for u in report["undeclared_terms"]] == ["hidden_regulariser"]
    assert report["summary"]["failed_terms"] == ["hidden_regulariser"]
    assert report["undeclared_terms"][0]["failures"][0]["code"] == "UNDECLARED_ACTIVE_TERM"


def test_the_three_arm_design_separates_active_ablated_and_silently_dead():
    # A: independent-sheet refinement (no dense terms configured at all)
    arm_a_configured = {"terms": [{"name": "sheet_fit", "weight": 1.0}]}
    a = ObjectiveTracker(["sheet_fit"])
    for _ in range(5):
        a.record("sheet_fit", 0.5, grad_norm=0.3)
        a.end_step()
    # B: dense losses configured and verified active
    b = _loop(dense_active=True)
    # C: dense losses deliberately disabled and verified inactive
    arm_c_configured = _configured()
    for term in arm_c_configured["terms"]:
        if term["name"] in DENSE:
            term["expect"] = "inactive"
            del term["claim"]
    c = _loop(dense_active=False)
    # B-but-dead: the reported failure, which must not be mistaken for B
    b_dead = _loop(dense_active=False)

    verdicts = {
        "A": audit_objective(_passport(a, arm_a_configured))["verdict"],
        "B": audit_objective(_passport(b))["verdict"],
        "C": audit_objective(_passport(c, arm_c_configured))["verdict"],
        "B-dead": audit_objective(_passport(b_dead))["verdict"],
    }
    assert verdicts == {
        "A": "OBJECTIVE_VERIFIED",
        "B": "OBJECTIVE_VERIFIED",
        "C": "OBJECTIVE_VERIFIED",
        "B-dead": "OBJECTIVE_INTEGRITY_FAILURE",
    }


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda p: p.update(schema_version=2), "schema_version"),
        (lambda p: p["configured_objective"].update(terms=[]), "must not be empty"),
        (lambda p: p["configured_objective"]["terms"].append({"name": "sheet_fit", "weight": 1}),
         "duplicate configured"),
        (lambda p: p["configured_objective"]["terms"][1].update(weight=0.0, expect="active"),
         "cannot have weight 0"),
        (lambda p: p["configured_objective"]["terms"][1].update(weight=True), "must be a number"),
        (lambda p: p["configured_objective"]["terms"][1].update(expect="maybe"), "expect must be"),
        (lambda p: p["configured_objective"]["terms"][1].update(expect="inactive"),
         "inactive term cannot carry a claim"),
        (lambda p: p["effective_objective"].update(steps=0), "steps must be"),
        (lambda p: p["effective_objective"]["terms"][0].update(finite_evaluations=999),
         "finite_evaluations exceeds"),
        (lambda p: p["effective_objective"]["terms"][0].update(nonzero_evaluations=999),
         "nonzero_evaluations exceeds"),
        (lambda p: p["effective_objective"]["terms"][0].update(evaluations=True),
         "integer >= 0"),
        (lambda p: p["effective_objective"]["terms"][0].update(
            accumulated_contribution=float("nan")), "must be finite"),
        (lambda p: p["effective_objective"]["terms"][0]["gradient_norm"].update(count=999),
         "count exceeds"),
        (lambda p: p["effective_objective"]["terms"][0]["gradient_norm"].update(max=-1),
         ">= 0"),
        (lambda p: p["effective_objective"]["terms"].append(
            dict(p["effective_objective"]["terms"][0])), "duplicate effective"),
    ],
)
def test_malformed_passports_raise_rather_than_pass(mutate, message):
    passport = json.loads(json.dumps(_passport(_loop(dense_active=True))))
    mutate(passport)
    with pytest.raises(ObjectiveAuditError, match=message):
        audit_objective(passport)


def test_threshold_arguments_are_validated():
    passport = _passport(_loop(dense_active=True))
    with pytest.raises(ObjectiveAuditError, match="min_nonzero_fraction"):
        audit_objective(passport, min_nonzero_fraction=1.5)


def test_passport_hash_tracks_content_not_key_order():
    passport = _passport(_loop(dense_active=True))
    reordered = dict(reversed(list(passport.items())))
    assert audit_objective(passport)["passport_sha256"] == audit_objective(reordered)["passport_sha256"]
    changed = json.loads(json.dumps(passport))
    changed["effective_objective"]["steps"] += 1
    assert audit_objective(changed)["passport_sha256"] != audit_objective(passport)["passport_sha256"]


def test_tracker_counts_and_roundtrips_through_json():
    tracker = ObjectiveTracker(["a"])
    tracker.record("a", 0.5, grad_norm=2.0)
    tracker.record("a", 0.0, grad_norm=4.0)
    tracker.record("a", float("nan"))
    tracker.end_step()

    (term,) = tracker.effective_objective()["terms"]
    assert term["evaluations"] == 3
    assert term["finite_evaluations"] == 2
    assert term["nonzero_evaluations"] == 1
    assert term["accumulated_contribution"] == 0.5
    assert term["gradient_norm"] == {"count": 2, "sum": 6.0, "max": 4.0, "nonfinite": 0}
    json.dumps(tracker.effective_objective(), allow_nan=False)
    with pytest.raises(ObjectiveAuditError):
        ObjectiveTracker(["bad name!"])


def test_gradient_block_is_null_unless_the_loop_reported_one():
    tracker = ObjectiveTracker(["a", "b"])
    tracker.record("a", 1.0)
    tracker.record("b", 1.0, grad_norm=math.nan)
    by_name = {t["name"]: t for t in tracker.effective_objective()["terms"]}
    assert by_name["a"]["gradient_norm"] is None
    assert by_name["b"]["gradient_norm"]["nonfinite"] == 1


def test_cli_verdict_exit_codes_and_create_only(tmp_path, capsys):
    good = tmp_path / "good.json"
    bad = tmp_path / "bad.json"
    good.write_text(json.dumps(_passport(_loop(dense_active=True))))
    bad.write_text(json.dumps(_passport(_loop(dense_active=False))))

    assert main(["--passport", str(good), "--out", str(tmp_path / "good.out.json")]) == 0
    assert "OBJECTIVE_VERIFIED" in capsys.readouterr().out
    assert main(["--passport", str(bad), "--out", str(tmp_path / "bad.out.json")]) == 2
    assert "dense_normal" in capsys.readouterr().out
    result = json.loads((tmp_path / "bad.out.json").read_text())
    assert result["verdict"] == "OBJECTIVE_INTEGRITY_FAILURE"

    with pytest.raises(SystemExit) as error:
        main(["--passport", str(good), "--out", str(tmp_path / "good.out.json")])
    assert error.value.code == 2

    broken = tmp_path / "broken.json"
    broken.write_text("{not json")
    with pytest.raises(SystemExit) as error:
        main(["--passport", str(broken), "--out", str(tmp_path / "x.json")])
    assert error.value.code == 2
    assert not (tmp_path / "x.json").exists()
