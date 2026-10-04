import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "artifacts/2026-10-04-fiber-gap-rule-prereg/spec.json"


def _m():
    sys.path.insert(0, str(ROOT / "scripts"))
    s = importlib.util.spec_from_file_location("gre", ROOT / "scripts/fiber_gap_rule_eval.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def _p():
    return json.loads(SPEC.read_text())["parameters"]


def test_spec_pinned():
    assert hashlib.sha256(SPEC.read_bytes()).hexdigest() == _m().SPEC_SHA256


def _fiber():
    # native span: 20 unit steps; fallback span: 10 steps of 3.5 (sparse rendering).
    xs = [float(i) for i in range(21)] + [20 + 3.5 * i for i in range(1, 11)]
    line = [[x, 0.0, 0.0] for x in xs]
    controls = [line[0], line[20], line[30]]
    return line, controls, ["trace", "lasagna"]


def test_old_rule_flags_nothing_in_a_uniform_sparse_span_and_span_rule_agrees():
    m = _m()
    line, controls, modes = _fiber()
    table = m.span_table(line, controls, modes, gap_factor=4.0)
    steps = m.steps_of(np.asarray(line))
    assert m.flagged(steps, table["spans"], "old", _p()) == set()
    assert m.flagged(steps, table["spans"], "span", _p()) == set()


def test_span_rule_suppresses_sparse_rendering_but_keeps_a_local_break():
    m = _m()
    # fallback span rendered at 4.5x: old rule flags every step, span rule none.
    xs = [float(i) for i in range(21)] + [20 + 4.5 * i for i in range(1, 11)]
    line = [[x, 0.0, 0.0] for x in xs]
    table = m.span_table(line, [line[0], line[20], line[30]], ["trace", "lasagna"], gap_factor=4.0)
    steps = m.steps_of(np.asarray(line))
    assert len(m.flagged(steps, table["spans"], "old", _p())) == 10
    assert m.flagged(steps, table["spans"], "span", _p()) == set()
    # a planted 6x-span-median step inside the fallback span is still found
    rng = np.random.default_rng(0)
    fb = [s for s in table["spans"] if s["fallback"]][0]
    planted, j = m.plant(np.asarray(line), steps, fb, rng, 6.0, 4.5)
    assert j in m.flagged(m.steps_of(planted), table["spans"], "span", _p())


def test_short_spans_fall_back_to_fiber_median():
    m = _m()
    xs = [float(i) for i in range(21)] + [20 + 4.5 * i for i in range(1, 4)]
    line = [[x, 0.0, 0.0] for x in xs]
    table = m.span_table(line, [line[0], line[20], line[23]], ["trace", "lasagna"], gap_factor=4.0)
    steps = m.steps_of(np.asarray(line))
    assert m.flagged(steps, table["spans"], "span", _p()) == m.flagged(steps, table["spans"], "old", _p())


def test_evaluate_and_summarize_decide():
    m = _m()
    spec = json.loads(SPEC.read_text())
    rng = np.random.default_rng(1)
    line, controls, modes = _fiber()
    per = [m.evaluate_fiber(line, controls, modes, spec["parameters"], rng) for _ in range(40)]
    out = m.summarize(per, spec)
    rec = out["planted_recall"]["span_relative"]
    assert rec["native"]["n"] == rec["fallback"]["n"] == 40
    assert rec["native"]["span"] == 1.0 and rec["fallback"]["span"] == 1.0
    # no real fallback candidates under the old rule -> reduction check cannot pass
    assert out["checks"]["fallback_reduction"] is False and out["verdict"] == "KEEP"
    few = m.summarize(per[:5], spec)
    assert few["verdict"] == "INSUFFICIENT"
