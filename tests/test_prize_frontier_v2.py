import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts/2026-10-04-prize-frontier-v2"


def _m():
    spec = importlib.util.spec_from_file_location("prize_frontier_v2", ROOT / "bin/prize_frontier_v2.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_committed_frontiers_match_a_fresh_recompute():
    m = _m()
    stability = json.loads(m.STABILITY.read_text())
    for prize in ("grand-prize", "first-letters"):
        fresh = json.loads(json.dumps(m.frontier_v2(stability, prize)))
        committed = json.loads((OUT / f"{prize}.json").read_text())
        assert fresh == committed


def test_published_v2_frontier_claims():
    s = json.loads((OUT / "summary.json").read_text())["prizes"]
    gp, fl = s["grand-prize"], s["first-letters"]
    assert gp["robust_members"] == ["PHerc1447"]
    assert fl["robust_members"] == ["PHerc0800"]
    assert gp["september_members_dropped"] == ["PHerc0813"]
    assert fl["september_members_dropped"] == ["PHerc0813"]
    for view in ("frontier_pooled", "frontier_run_a", "frontier_run_b"):
        assert "PHerc0813" not in gp[view] and "PHerc0813" not in fl[view]


def test_incomplete_v2_sample_is_never_scored_or_on_a_frontier():
    gp = json.loads((OUT / "grand-prize.json").read_text())
    row = next(t for t in gp["targets"] if t["scroll"] == "PHerc1545")
    assert row["score_pooled"] is row["score_run_a"] is row["score_run_b"] is None
    assert row["qualification_pooled"] == "needs-quality-score"
    assert not any(row["on_frontier"].values())
