"""Published outputs must not depend on the order of input rows.

A greedy or first-wins step can change a published number when the same rows
arrive in a different order (an external SwitchBench audit found a 70 -> 56
false-alarm swing from that alone). These tests feed the published campaign
rows in original, reversed and seeded-shuffled order, plus an exact-duplicate
control, and require byte-identical outputs.
"""

import json
import random
import sys
from collections import Counter
from pathlib import Path

import pytest

from scrollq import leaderboard
from scrollq.coverage import build_coverage
from scrollq.grand_prize import FIRST_LETTERS_MANIFEST, qualify

ROOT = Path(__file__).resolve().parents[1]
VOLUMES = ROOT / "artifacts/2026-09-30-scrollq-n24-dense/volumes.json"
COVERAGE = ROOT / "artifacts/2026-09-30-scrollq-n24-dense/coverage.json"
SUPPORT = ROOT / "artifacts/2026-09-30-grand-prize-qualifier/surface_support_external.json"


def _rows():
    return json.loads(VOLUMES.read_text(encoding="utf-8"))


def _orders(rows):
    yield "original", list(rows)
    yield "reverse", list(reversed(rows))
    for seed in range(20):
        shuffled = list(rows)
        random.Random(seed).shuffle(shuffled)
        yield f"permutation_{seed:02d}", shuffled


def _canon(obj):
    return json.dumps(obj, sort_keys=True)


def test_published_campaign_has_tied_scores():
    # Positive control: ties are what make a stable sort order-dependent, so
    # the leaderboard test below is only meaningful if the data has them.
    scores = Counter(v["score"] for v in _rows() if v.get("ok"))
    assert sum(1 for n in scores.values() if n > 1) >= 1


@pytest.mark.parametrize("manifest", [None, FIRST_LETTERS_MANIFEST],
                         ids=["grand-prize", "first-letters"])
def test_qualify_is_input_order_invariant(manifest):
    support = json.loads(SUPPORT.read_text(encoding="utf-8"))
    rows = _rows()
    expected = _canon(qualify(rows, manifest, support))
    for name, ordered in _orders(rows):
        assert _canon(qualify(ordered, manifest, support)) == expected, name
    assert _canon(qualify(rows + rows, manifest, support)) == expected


def test_build_coverage_is_input_order_invariant():
    rows = _rows()
    scrolls = sorted({p for v in rows for p in v["root"].split("/")
                      if p.startswith("PHerc")})
    ink = Counter({s: i % 3 for i, s in enumerate(scrolls)})
    surf = Counter({s: i for i, s in enumerate(scrolls)})
    expected = _canon(build_coverage(rows, ink, surf))
    for name, ordered in _orders(rows):
        assert _canon(build_coverage(ordered, ink, surf)) == expected, name


def _render(tmp_path, rows, name):
    inp = tmp_path / f"{name}.json"
    out = tmp_path / f"{name}.html"
    inp.write_text(json.dumps(rows), encoding="utf-8")
    argv = ["scrollq-leaderboard", "--in", str(inp), "--out", str(out),
            "--coverage", str(COVERAGE)]
    old = sys.argv
    sys.argv = argv
    try:
        leaderboard.main()
    finally:
        sys.argv = old
    return out.read_text(encoding="utf-8")


def test_leaderboard_is_input_order_invariant(tmp_path):
    rows = _rows()
    expected = _render(tmp_path, rows, "original")
    for name, ordered in _orders(rows):
        assert _render(tmp_path, ordered, name) == expected, name
