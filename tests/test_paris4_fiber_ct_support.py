import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "artifacts/2026-10-04-paris4-fiber-ct-support-prereg/spec.json"


def _m():
    s = importlib.util.spec_from_file_location("ct", ROOT / "scripts/paris4_fiber_ct_support.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def test_spec_hash_pinned_and_census_matches():
    m = _m()
    assert hashlib.sha256(SPEC.read_bytes()).hexdigest() == m.SPEC_SHA256
    spec = json.loads(SPEC.read_text())
    census = json.loads((ROOT / "artifacts/2026-10-04-fiber-corpus-census/summary.json").read_text())
    assert spec["inputs"]["census_manifest_sha256"] == census["manifest_sha256"]
    binding = json.loads((ROOT / "artifacts/2026-10-04-paris4-fiber-binding/result.json").read_text())
    assert binding["compatible"] == [spec["volume"]["root"]]


def test_auc_matches_brute_force_with_ties():
    m = _m()
    rng = np.random.default_rng(0)
    a, b = rng.integers(0, 5, 40), rng.integers(0, 5, 30)
    brute = np.mean([(x > y) + 0.5 * (x == y) for x in a for y in b])
    assert abs(m.auc(a, b) - brute) < 1e-12


def test_coordinate_conversion_reverses_axes_and_scales():
    m = _m()
    assert m.to_level(np.array([[10.0, 21.0, 33.0]]), 2).tolist() == [[16, 10, 5]]


def _groups(fiber_level, shift_level, swap_level, n=60, k=16, seed=1):
    rng = np.random.default_rng(seed)

    def draw(mu):
        return [rng.normal(mu, 20, k).clip(0, 255) for _ in range(n)]

    return {"F": draw(fiber_level), "S": [np.concatenate([x, y]) for x, y in zip(draw(shift_level), draw(shift_level))],
            "R": draw(100), "X": draw(swap_level)}


def _spec():
    s = json.loads(SPEC.read_text())
    s["decision"]["bootstrap_reps"] = 300
    return s


def test_decision_supported_only_when_fibers_beat_background_and_shift():
    m = _m()
    assert m.decide(_groups(140, 100, 100), _spec())["verdict"] == "SUPPORTED"
    assert m.decide(_groups(100, 100, 100), _spec())["verdict"] == "NOT SUPPORTED"
    # Bright everywhere near the fiber (no specificity) is not support.
    assert m.decide(_groups(140, 140, 100), _spec())["verdict"] == "NOT SUPPORTED"


def test_wrong_frame_control_blocks_a_claim():
    m = _m()
    assert m.decide(_groups(140, 100, 140), _spec())["verdict"] == "CONTROL FAILURE"


def test_per_fiber_flags():
    m = _m()
    g = _groups(140, 100, 100)
    flags = m.per_fiber_flags(g)
    assert flags["flag_rate_fibers"] < 0.1 < flags["flag_rate_shifted"]


def test_fiber_points_are_evenly_spaced_and_unique():
    m = _m()
    line = np.arange(30, dtype=float).reshape(10, 3)
    assert len(m.fiber_points(line, 16)) == 10
    assert m.fiber_points(np.arange(300, dtype=float).reshape(100, 3), 16).shape == (16, 3)


def test_frozen_ct_support_result_matches_run_one_log():
    run = ROOT / "artifacts/2026-10-04-paris4-fiber-ct-support-run/result.json"
    r = json.loads(run.read_text())
    m = _m()
    assert r["spec_sha256"] == m.SPEC_SHA256
    assert r["verdict"] == "SUPPORTED" and r["control_wrong_frame_supported"] is False
    # Values logged by run 1 (37169930475); run 2 must reproduce them exactly.
    assert r["auc_F_vs_R"] == 0.7752110042374026
    assert r["auc_S_vs_R"] == 0.5545193365288441
    assert r["auc_X_vs_R"] == 0.42915697988754326
    assert r["auc_F_vs_R_ci95"] == [0.7601893124695881, 0.7894949573134056]
    assert r["specificity_F_minus_S_ci95"] == [0.20675294473509476, 0.23329532187702753]
    assert r["reads"] == {"voxels": 10880, "missing_chunk_reads": 470, "out_of_bounds": 0}
    assert r["per_fiber"]["flag_rate_fibers"] == 0.0
    assert round(r["per_fiber"]["flag_rate_shifted"] * 136) == 38
    census = json.loads((ROOT / "artifacts/2026-10-04-fiber-corpus-census/summary.json").read_text())
    assert r["fibers"] == [row["file"] for row in census["rows"]]
    assert len(r["per_fiber_auc_F_vs_R"]) == 136
