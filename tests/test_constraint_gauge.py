import json

import pytest

from scrollq.constraint_gauge import (
    GaugeError,
    digest,
    freeze,
    main,
    positive_control,
    score,
)


def _truth(n=60):
    pairs = [{"a": f"n{k:03d}", "b": f"n{k + 1:03d}", "truth_delta": 1}
             for k in range(n)]
    return {"schema_version": 1, "truth_source": "human-verified test",
            "pairs": pairs}


def _sub(spec, name="p", **kw):
    return {"schema_version": 1, "spec_sha256": digest(spec),
            "producer": {"name": name, "version": "1"}, **kw}


def test_positive_control_passes():
    ctl = positive_control()
    assert ctl["passed"], ctl


def test_exact_producer_is_admissible_and_sign_follows_order():
    truth = _truth()
    spec = freeze(truth, benchmark_id="b", frozen_at="2026-10-06")
    cons = [{"a": p["b"], "b": p["a"], "d": -1} for p in truth["pairs"]]
    r = score(spec, truth, [_sub(spec, constraints=cons)], run_control=False)
    row = r["producers"][0]
    assert row["exact"] == 1.0 and row["coverage"] == 1.0
    assert row["status"] == "admissible"
    assert row["confidence"]["status"] == "absent"


def test_internal_metrics_never_change_the_verdict():
    truth = _truth()
    spec = freeze(truth, benchmark_id="b", frozen_at="2026-10-06")
    cons = [{"a": p["a"], "b": p["b"], "d": 3} for p in truth["pairs"]]
    r = score(spec, truth, [_sub(spec, constraints=cons, internal_metrics={
        "cycle_consistency": 1.0, "agreement": 0.99})], run_control=False)
    row = r["producers"][0]
    assert row["status"] == "not_admissible"
    assert row["internal_metrics_not_evidence"]["agreement"] == 0.99
    assert row["internal_consistency_not_evidence"] == 1.0
    assert row["mean_abs_residual"] == 2.0


def test_no_overlap_is_unverified():
    truth = _truth()
    spec = freeze(truth, benchmark_id="b", frozen_at="2026-10-06")
    r = score(spec, truth, [_sub(spec, constraints=[
        {"a": "x", "b": "y", "d": 0}])], run_control=False)
    assert r["producers"][0]["status"] == "unverified"


def test_windings_submission_scores_pairs():
    truth = _truth(40)
    spec = freeze(truth, benchmark_id="b", frozen_at="2026-10-06")
    wind = {f"n{k:03d}": 100 - k for k in range(41)}
    wind["n010"] += 1  # breaks two pairs
    row = score(spec, truth, [_sub(spec, windings=wind)],
                run_control=False)["producers"][0]
    assert row["scored"] == 40 and row["exact"] == pytest.approx(38 / 40)


def test_partial_confidence_is_unverified_not_trusted():
    truth = _truth()
    spec = freeze(truth, benchmark_id="b", frozen_at="2026-10-06")
    cons = [{"a": p["a"], "b": p["b"], "d": 1,
             "confidence": 0.9 if k else None}
            for k, p in enumerate(truth["pairs"])]
    row = score(spec, truth, [_sub(spec, constraints=cons)],
                run_control=False)["producers"][0]
    assert row["confidence"]["status"] == "unverified"


def test_underpopulated_bins_cannot_earn_weight():
    truth = _truth()
    spec = freeze(truth, benchmark_id="b", frozen_at="2026-10-06",
                  min_per_bin=50)
    cons = [{"a": p["a"], "b": p["b"], "d": 1, "confidence": 0.95}
            for p in truth["pairs"]]
    row = score(spec, truth, [_sub(spec, constraints=cons)],
                run_control=False)["producers"][0]
    assert row["confidence"]["status"] == "unverified"


@pytest.mark.parametrize("mutate, match", [
    (lambda s, t, p: p.update(spec_sha256="0" * 64), "frozen benchmark"),
    (lambda s, t, p: t["pairs"][0].update(truth_delta=5), "truth_sha256"),
    (lambda s, t, p: p.update(windings={"n000": 1}), "exactly one"),
    (lambda s, t, p: p["producer"].pop("version"), "commit or version"),
    (lambda s, t, p: p.update(ink_overlap=0.5), "ink"),
])
def test_binding_defects_fail_closed(mutate, match):
    truth = _truth()
    spec = freeze(truth, benchmark_id="b", frozen_at="2026-10-06")
    sub = _sub(spec, constraints=[{"a": "n000", "b": "n001", "d": 1}])
    mutate(spec, truth, sub)
    with pytest.raises(GaugeError, match=match):
        score(spec, truth, [sub], run_control=False)


def test_truth_validation():
    t = _truth()
    t["pairs"].append(dict(t["pairs"][0]))
    with pytest.raises(GaugeError, match="duplicates"):
        freeze(t, benchmark_id="b", frozen_at="2026-10-06")
    with pytest.raises(GaugeError, match="truth_source"):
        freeze(dict(_truth(), truth_source=""), benchmark_id="b",
               frozen_at="2026-10-06")


def test_cli_round_trip(tmp_path):
    truth = _truth()
    (tmp_path / "t.json").write_text(json.dumps(truth))
    spec_path = tmp_path / "spec.json"
    assert main(["freeze", "--truth", str(tmp_path / "t.json"),
                 "--benchmark-id", "b", "--frozen-at", "2026-10-06",
                 "--out", str(spec_path)]) == 0
    spec = json.loads(spec_path.read_text())
    assert "pairs" not in spec  # truth stays sealed
    (tmp_path / "p.json").write_text(json.dumps(_sub(spec, constraints=[
        {"a": p["a"], "b": p["b"], "d": 1} for p in truth["pairs"]])))
    out = tmp_path / "r.json"
    assert main(["score", "--spec", str(spec_path), "--truth",
                 str(tmp_path / "t.json"), "--producer",
                 str(tmp_path / "p.json"), "--out", str(out)]) == 0
    assert json.loads(out.read_text())["status"] == "scored"
