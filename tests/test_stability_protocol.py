"""O5 pre-registered stability test: constants are frozen and decide()
returns the verdict the protocol document states."""

import pytest

from scrollq import stability_protocol as sp
from scrollq.score import score_from_metrics


def test_constants_match_the_protocol_document():
    text = open(sp.PROTOCOL, encoding="utf-8").read()
    c = sp.preregistered_constants()
    assert c == {
        "protocol": "docs/stability-v2-protocol.md", "spread": 7, "order": "balanced",
        "parts": [[2, 0], [2, 1]], "n_primary": 48, "n_secondary": 24,
        "gate_rho": 0.85, "min_eligible": 48,
    }
    for literal in ("spread 7", "48 chunks", "24 chunks", "0.85", "48 of the 64"):
        assert literal in text, literal


def test_spearman_handles_ties_and_degenerate_input():
    assert sp.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert sp.spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
    assert sp.spearman([1, 2, 2, 3], [1, 2, 3, 4]) == pytest.approx(0.9487, abs=1e-4)
    assert sp.spearman([1, 1, 1], [1, 2, 3]) is None
    assert sp.spearman([1, 2], [1, 2]) is None


def _run(score, n=48, decoded=None, ok=True, metrics=None):
    return {"ok": ok, "score": score,
            "sampling": {"requested": n, "decoded": n if decoded is None else decoded},
            "metrics": metrics or {}}


def test_eligibility_requires_the_full_requested_sample():
    assert sp.eligible(_run(50), 48)
    assert not sp.eligible(_run(50, decoded=47), 48)
    assert not sp.eligible(_run(50, ok=False), 48)
    assert not sp.eligible(None, 48)
    assert not sp.eligible(_run(50, n=24), 48)


def test_pooled_score_is_the_union_of_two_equal_samples():
    ma = {"nonzero_frac": 0.8, "std": 30.0, "dyn_range": 150.0, "sat_frac": 0.001, "grad_energy": 9.0, "dead_slices": 0}
    mb = {"nonzero_frac": 0.6, "std": 20.0, "dyn_range": 120.0, "sat_frac": 0.003, "grad_energy": 7.0, "dead_slices": 1}
    union = {k: (ma[k] + mb[k]) / 2 for k in sp.METRIC_KEYS} | {"dead_slices": 1}
    assert sp.pooled_score({"metrics": ma}, {"metrics": mb}) == round(score_from_metrics(union), 1)


def test_rank_bands_span_all_three_orderings():
    rows = {"x": {"a": 90, "b": 50, "pooled": 70}, "y": {"a": 60, "b": 80, "pooled": 75}, "z": {"a": 10, "b": 10, "pooled": 10}}
    bands = sp.rank_bands(rows)
    assert bands["x"] == {"best": 1, "worst": 2}
    assert bands["y"] == {"best": 1, "worst": 2}
    assert bands["z"] == {"best": 3, "worst": 3}


def _arm(n_volumes, rho_pattern, n=48, short=0):
    a, b = {}, {}
    for i in range(n_volumes):
        a[f"v{i:02d}"] = _run(float(i), n=n)
        b[f"v{i:02d}"] = _run(float(rho_pattern(i)), n=n, decoded=n - 1 if i < short else None)
    return sp.arm_summary(a, b, n)


def test_decide_pass_fail_insufficient():
    perfect = _arm(64, lambda i: i)
    assert perfect["eligible"] == 64 and perfect["spearman_rho"] == pytest.approx(1.0)
    assert sp.decide(perfect)["verdict"] == "PASS"

    scrambled = _arm(64, lambda i: (i * 37) % 64)
    assert sp.decide(scrambled)["verdict"] == "FAIL"
    assert "rank bands" in sp.decide(scrambled)["consequence"]

    sparse = _arm(64, lambda i: i, short=17)            # 47 eligible < 48
    assert sparse["eligible"] == 47 and len(sparse["excluded"]) == 17
    assert sp.decide(sparse)["verdict"] == "INSUFFICIENT"

    with pytest.raises(ValueError):
        sp.decide(_arm(64, lambda i: i, n=24))


def test_arm_summary_reports_systematic_shift():
    summary = _arm(20, lambda i: i + 5)
    assert summary["mean_shift_b_minus_a"] == pytest.approx(5.0)
    assert summary["sd_shift"] == pytest.approx(0.0)
    assert summary["mean_abs_diff"] == pytest.approx(5.0)
    assert summary["top10_overlap"] == 10


def _load_runner():
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / "bin" / "stability_v2.py"
    spec = importlib.util.spec_from_file_location("stability_v2", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


METRICS = {"nonzero_frac": 0.9, "std": 30.0, "dyn_range": 150.0, "sat_frac": 0.0, "grad_energy": 8.0, "dead_slices": 0}


def _fake_scorer(shared=False, short_root=None):
    def scorer(root, n, part):
        i = int(root[1:])
        decoded = n - 1 if root == short_root else n
        tag = "x" if shared else f"p{part[1]}"
        return {"root": root, "ok": True, "score": float(i if part[1] == 0 else i + 0.5),
                "sampling": {"requested": n, "decoded": decoded},
                "metrics": METRICS | {"grad_energy": 1.0 + i / 10},
                "sample_provenance": [{"identity": f"{root}/{tag}#{j}"} for j in range(decoded)]}
    return scorer


def test_runner_runs_both_arms_and_decides():
    runner = _load_runner()
    roots = [f"v{i:02d}" for i in range(60)]
    result = runner.run_campaign(roots, workers=4, scorer=_fake_scorer(short_root="v03"))
    assert result["decision"]["verdict"] == "PASS"
    assert result["arms"]["48"]["eligible"] == 59
    assert "v03" in result["arms"]["48"]["excluded"]
    assert set(result["runs"]) == {"48", "24"}
    assert result["rank_bands"]["v59"] == {"best": 1, "worst": 1}


def test_runner_fails_closed_when_runs_share_a_chunk():
    runner = _load_runner()
    result = runner.run_campaign([f"v{i:02d}" for i in range(50)], workers=4, scorer=_fake_scorer(shared=True))
    assert result["decision"]["verdict"] == "PROTOCOL_VIOLATION"
