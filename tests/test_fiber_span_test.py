import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/fiber_span_test.py"
SPEC = ROOT / "artifacts/2026-10-04-fiber-span-test-prereg/spec.json"


def _m():
    spec = importlib.util.spec_from_file_location("fiber_span_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _spec():
    return json.loads(SPEC.read_text())


def test_spec_hash_is_pinned_in_the_runner():
    assert hashlib.sha256(SPEC.read_bytes()).hexdigest() == _m().SPEC_SHA256


def test_spec_pins_the_frozen_census():
    census = json.loads((ROOT / "artifacts/2026-10-04-fiber-corpus-census/summary.json").read_text())
    assert _spec()["inputs"]["census_manifest_sha256"] == census["manifest_sha256"]


def _line(n, big_steps=()):
    xs, x = [], 0.0
    for i in range(n):
        xs.append([x, 0.0, 0.0])
        x += 10.0 if i in big_steps else 1.0
    return xs


def test_gap_steps_are_assigned_to_their_span():
    m = _m()
    line = _line(30, big_steps={4, 22})
    controls = [line[0], line[10], line[20], line[29]]
    out = m.span_table(line, controls, ["trace", "cspline", "lasagna"], gap_factor=4.0)
    spans = out["spans"]
    assert [s["gap_steps"] for s in spans] == [[4], [], [22]]
    assert [s["fallback"] for s in spans] == [False, True, True]
    assert out["gap_steps_outside_spans"] == 0
    assert m.fiber_counts(spans) == (2, 1, 1, 1)


def test_gap_after_last_control_is_counted_outside():
    m = _m()
    line = _line(30, big_steps={27})
    out = m.span_table(line, [line[0], line[10], line[20]], ["trace", "trace"], gap_factor=4.0)
    assert out["gap_steps_outside_spans"] == 1


def test_non_monotone_controls_are_excluded_not_guessed():
    m = _m()
    line = _line(30)
    out = m.span_table(line, [line[0], line[20], line[10]], ["trace", "trace"], gap_factor=4.0)
    assert out["status"] == "non-monotone"


def test_mode_count_must_match_spans():
    m = _m()
    line = _line(10)
    with pytest.raises(ValueError):
        m.span_table(line, [line[0], line[9]], ["trace", "trace"], gap_factor=4.0)


def _structure(n=60, seed=1):
    rng = np.random.default_rng(seed)
    nf = rng.integers(1, 8, size=n)
    nn = rng.integers(10, 60, size=n)
    return nf, nn


def test_decision_supports_a_planted_effect_and_rejects_no_effect():
    m = _m()
    spec = _spec()
    nf, nn = _structure()
    strong = np.stack([nf, nf, nn, np.zeros_like(nn)], axis=1)
    assert m.decide(strong, spec, seed=1, reps=2000)["verdict"] == "SUPPORTED"
    reverse = np.stack([nf, np.zeros_like(nf), nn, nn], axis=1)
    assert m.decide(reverse, spec, seed=1, reps=2000)["verdict"] == "NOT SUPPORTED"


def test_insufficient_when_too_few_fallback_spans():
    m = _m()
    c = np.array([[1, 1, 20, 0]] * 5)
    assert m.decide(c, _spec(), seed=1, reps=100)["verdict"] == "INSUFFICIENT"


def test_controls_pass_on_a_realistic_structure():
    m = _m()
    nf, nn = _structure(n=136, seed=7)
    rng = np.random.default_rng(3)
    c = np.stack([nf, rng.binomial(nf, 0.1), nn, rng.binomial(nn, 0.05)], axis=1)
    spec = _spec()
    spec["controls"]["null_replicates"] = 40
    spec["controls"]["null_bootstrap_reps"] = 300
    out = m.controls(c, spec)
    assert out["positive"]["verdict"] == "SUPPORTED"
    assert out["null_false_positive_rate"] <= 0.1
    assert out["passed"] is True


def test_mantel_haenszel_skips_single_type_strata():
    m = _m()
    c = np.array([[4, 2, 10, 1], [0, 0, 10, 5], [3, 3, 0, 0]])
    # Only the first stratum is informative: (2*9/14)/(1*2/14) = 9
    assert m.mantel_haenszel_or(c) == pytest.approx(9.0)


def test_vc3d_bundle_shape():
    m = _m()
    gaps = [{"file": "a.json", "sha256": "0" * 64, "step": 3, "span": 1, "mode": "cspline",
             "xyz": [1.0, 2.0, 3.0], "ratio": 6.5}]
    b = m.vc3d_bundle(gaps, "1" * 64)
    assert b["vc_pointcollections_json_version"] == "1"
    assert b["collections"]["1"]["points"]["1"]["p"] == [1.0, 2.0, 3.0]
    assert b["collections"]["1"]["tags"]["span_mode"] == "cspline"
