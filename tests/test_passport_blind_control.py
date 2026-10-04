"""Passport stage for sealed-truth timing (blind controls)."""

import copy

import pytest

from scrollq import blind_control
from scrollq.passport import _BLIND_VERDICTS, build_passport

from test_blind_control import T_ANCHOR, T_COMMIT, T_REVEAL, Chain
from test_passport import _volume

ROOT = "nist-synthetic-carbonized-scroll"


def _passport(report, root=ROOT):
    return build_passport(_volume(root=root), blind_control=report)


def _stage(report, root=ROOT):
    return _passport(report, root)["stages"]["blind_control"]


@pytest.fixture
def anchored(tmp_path):
    chain = Chain(tmp_path)
    return chain.report(chain.reveal(), chain.anchor_external())


def test_verdict_vocabulary_matches_the_producer():
    assert _BLIND_VERDICTS == blind_control.VERDICTS


def test_no_report_leaves_blind_control_unknown_and_adds_no_action():
    passport = build_passport(_volume())
    stage = passport["stages"]["blind_control"]
    assert stage["status"] == "unknown"
    assert "not recorded" in stage["reason"]
    assert not [a for a in passport["next_actions"] if "blind-control" in a["action"]
                or "sealed-truth" in a["action"]]
    assert "blind-control" in passport["interpretation"]


def test_anchored_report_is_measured_and_carries_timing_and_limits(anchored):
    stage = _stage(anchored)
    assert stage["status"] == "measured"
    assert stage["verdict"] == "sealed-order-anchored"
    assert stage["timing"]["prediction_committed_at"] == T_COMMIT
    assert stage["timing"]["truth_first_visible_at"] == T_REVEAL
    assert stage["timing"]["anchored_at"] == T_ANCHOR
    assert stage["acquisition"]["pin_status"] == "pinned"
    assert stage["benchmark"]["evaluation_only"] is True
    assert any("carbon-ink detection on ancient papyrus" in s for s in stage["claim_limits"])
    assert "no detection or surface score" in stage["limitation"]
    assert stage["volume"]["claimed"]["slice_count"] == 620


def test_self_asserted_and_awaiting_reveal_are_partial_with_an_action(tmp_path):
    chain = Chain(tmp_path)
    self_asserted = chain.report(chain.reveal())
    awaiting = chain.report(None, chain.anchor_external())
    for report in (self_asserted, awaiting):
        passport = _passport(report)
        assert passport["stages"]["blind_control"]["status"] == "partial"
        assert any("sealed-truth chain" in a["action"] for a in passport["next_actions"])
    assert _stage(self_asserted)["weaknesses"]


def test_not_blind_report_blocks_with_its_violations(tmp_path):
    chain = Chain(tmp_path)
    forged = dict(chain.commitment, committed_at="2026-10-04T00:00:00+00:00")
    report = chain.report(chain.reveal(), commitment=forged)
    passport = _passport(report)
    stage = passport["stages"]["blind_control"]
    assert stage["status"] == "blocked"
    assert stage["violations"]
    assert any(a["priority"] == "high" and "blind-control" in a["action"]
               for a in passport["next_actions"])


@pytest.mark.parametrize(
    "mutate, fragment",
    [
        (lambda r: r["timing"].update(truth_first_visible_at=T_COMMIT),
         "do not show the prediction committed before truth"),
        (lambda r: r["timing"].update(order="truth-not-after-prediction"),
         "do not show the prediction committed before truth"),
        (lambda r: r["timing"].update(truth_first_visible_at=None),
         "truth_first_visible_at is missing"),
        (lambda r: r["timing"].update(prediction_committed_at="2026-10-05T10:00:00"),
         "prediction_committed_at is missing or has no UTC offset"),
        (lambda r: r["timing"].update(ordering_evidence="self-asserted-clock"),
         "anchor or custody attestation is not recorded"),
        (lambda r: r["timing"].update(custody_attested=False),
         "anchor or custody attestation is not recorded"),
    ],
)
def test_passport_rederives_order_instead_of_trusting_the_verdict(anchored, mutate, fragment):
    report = copy.deepcopy(anchored)
    assert report["verdict"] == "sealed-order-anchored"
    mutate(report)
    stage = _stage(report)
    assert stage["status"] == "blocked"
    assert "internally inconsistent" in stage["reason"] and fragment in stage["reason"]


def test_awaiting_reveal_that_records_visibility_is_inconsistent(tmp_path):
    chain = Chain(tmp_path)
    report = chain.report(None)
    report["timing"]["truth_first_visible_at"] = T_REVEAL
    assert _stage(report)["status"] == "blocked"


def test_exact_binding_is_required(anchored):
    assert _stage(anchored, root="community-uploads/other.zarr")["status"] == "excluded"
    assert "different volume" in _stage(anchored, root="community-uploads/other.zarr")["reason"]

    no_id = copy.deepcopy(anchored)
    no_id["volume"].pop("id")
    assert "no exact volume.id binding" in _stage(no_id)["reason"]

    wrong_kind = copy.deepcopy(anchored)
    wrong_kind["diagnostic"] = "ink-evidence-audit"
    assert "not a ScrolIQ blind-control-report" in _stage(wrong_kind)["reason"]

    bad_verdict = copy.deepcopy(anchored)
    bad_verdict["verdict"] = "trust-me"
    stage = _stage(bad_verdict)
    assert stage["status"] == "excluded" and "unsupported" in stage["reason"]
    assert _passport(bad_verdict)["next_actions"]


def test_blind_control_does_not_touch_the_scan_score(anchored):
    plain = build_passport(_volume(root=ROOT))
    with_report = _passport(anchored)
    assert with_report["stages"]["scan"] == plain["stages"]["scan"]
    assert with_report["stages"]["ink"]["status"] == "unknown"
    assert with_report["stages"]["mesh"]["status"] == "unknown"
