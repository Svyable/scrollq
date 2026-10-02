"""scrollq-health must fail closed: missing integrity evidence never reads as PASS.

Regression for the fail-open path documented in the companion's
docs/INTEGRATION.md: an unreadable level (ACCESS_UNKNOWN), an absent root,
or an audit exception used to leave integrity at PASS, so a readable sampled
level could still produce TRAIN.
"""

import pytest

import scrollq.health as health

GOOD_QUALITY = {"ok": True, "score": 80.0, "components": {},
                "sampling": {"requested": 24, "decoded": 24, "complete": True}}


def _audit(integrity, findings=(), evidence=None):
    return {
        "schema_version": "1.1.0",
        "tool_version": "test",
        "integrity": integrity,
        "evidence": evidence or {"state": "PRESENT", "reason": ""},
        "coverage": {"levels_declared": 6},
        "findings": [
            {"code": code, "severity": sev, "level": "0", "detail": code,
             "evidence_state": state}
            for code, sev, state in findings
        ],
    }


def _run(monkeypatch, audit, quality=GOOD_QUALITY):
    monkeypatch.setattr(health, "audit_root", lambda store, root: audit)
    return health.health_report(
        "https://example.invalid", "v.zarr", store=object(),
        scorer=lambda *a, **k: dict(quality),
    )


def test_clean_integrity_and_good_quality_trains(monkeypatch):
    report = _run(monkeypatch, _audit("PASS", [("NOTE", "info", "PRESENT")]))
    assert report["verdict"] == "TRAIN"
    assert report["integrity"]["consumer_action"] == "DEFER_TO_QUALITY"
    # Informational findings are kept with their codes, not dropped.
    assert report["integrity"]["findings"][0]["code"] == "NOTE"


def test_unreadable_level_blocks_even_with_good_quality(monkeypatch):
    report = _run(
        monkeypatch,
        _audit("UNKNOWN", [("ACCESS_UNKNOWN", "info", "UNKNOWN")]),
    )
    assert report["verdict"] == "DO NOT TRAIN"
    assert "ACCESS_UNKNOWN" in report["verdict_reason"]
    assert report["integrity"]["unknown_evidence"][0]["code"] == "ACCESS_UNKNOWN"


def test_absent_root_blocks(monkeypatch):
    report = _run(
        monkeypatch,
        # As observed live (artifacts/2026-10-01-health-verdicts-fail-closed/
        # absent-root.json): integrity UNKNOWN, but the finding and the
        # report evidence both say ABSENT, so no finding is "UNKNOWN".
        _audit("UNKNOWN", [("ROOT_ABSENT", "low", "ABSENT")],
               evidence={"state": "ABSENT", "reason": "NOT_FOUND"}),
        quality={"ok": False, "error": "no chunks"},
    )
    assert report["verdict"] == "DO NOT TRAIN"
    assert "ROOT_ABSENT" in report["verdict_reason"]


def test_audit_exception_is_a_failure_not_a_pass(monkeypatch):
    class Broken:
        def __getattr__(self, name):
            raise RuntimeError("store exploded")

    # Use the real companion audit_root: it must convert the crash to FAIL.
    report = health.health_report(
        "https://example.invalid", "v.zarr", store=Broken(),
        scorer=lambda *a, **k: dict(GOOD_QUALITY),
    )
    assert report["integrity"]["verdict"] == "FAIL"
    assert report["verdict"] == "DO NOT TRAIN"
    assert "store exploded" in report["integrity_error"]


def test_high_finding_blocks(monkeypatch):
    report = _run(monkeypatch, _audit("FAIL", [("LEVEL_NO_CHUNKS", "high", "ABSENT")]))
    assert report["verdict"] == "DO NOT TRAIN"
    assert report["verdict_reason"] == "1 high-severity integrity finding(s)"


@pytest.mark.parametrize(
    ("quality", "reason"),
    [
        ({"ok": False, "error": "v2"}, "quality unscorable: v2"),
        ({"ok": True, "score": 12.0}, "quality score 12.0 below 40"),
    ],
)
def test_clean_integrity_defers_to_quality(monkeypatch, quality, reason):
    report = _run(monkeypatch, _audit("PASS"), quality=quality)
    assert report["verdict"] == "CAUTION"
    assert report["verdict_reason"] == reason


def test_medium_finding_cautions(monkeypatch):
    report = _run(monkeypatch, _audit("WARN", [("EMPTY_LEVEL", "medium", "PRESENT")]))
    assert report["verdict"] == "CAUTION"


@pytest.mark.parametrize("sampling", [
    None, {}, {"requested": 24, "decoded": 1, "complete": False},
    {"requested": 24, "decoded": 1, "complete": True},
    {"requested": 1, "decoded": 1, "complete": True},
    {"requested": 24, "decoded": 24, "complete": "true"},
])
def test_incomplete_or_unverified_sampling_never_trains(monkeypatch, sampling):
    quality = {**GOOD_QUALITY, "sampling": sampling}
    report = _run(monkeypatch, _audit("PASS"), quality)
    assert report["verdict"] == "CAUTION"
    assert "sampling" in report["verdict_reason"]
    assert report["quality"] == quality


@pytest.mark.parametrize("score", [None, float("nan"), float("inf"), -1, 101, "80", True])
def test_invalid_quality_score_never_trains(monkeypatch, score):
    report = _run(monkeypatch, _audit("PASS"), {**GOOD_QUALITY, "score": score})
    assert report["verdict"] == "CAUTION"
    assert "invalid" in report["verdict_reason"]


@pytest.mark.parametrize("integrity, verdict", [("PASS", "CAUTION"), ("FAIL", "DO NOT TRAIN"),
                                               ("UNKNOWN", "DO NOT TRAIN")])
def test_quality_exception_preserves_integrity_result(monkeypatch, integrity, verdict):
    monkeypatch.setattr(health, "audit_root", lambda *a: _audit(integrity))

    def broken(*a, **k):
        raise OSError("chunk transport failed")

    report = health.health_report("https://example.invalid", "v.zarr",
                                  store=object(), scorer=broken)
    assert report["verdict"] == verdict
    assert report["integrity"]["verdict"] == integrity
    assert "chunk transport failed" in report["quality"]["error"]
