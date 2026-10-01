"""Regression tests for bin/stability.py: the resampling harness.

Guards the exact failure mode caught 2026-09-30: a resample comparison is
only honest when the two runs read (near-)disjoint shard sets. A rotation
that mostly re-reads the same shards inflates Spearman rho and masquerades
as stability evidence.
"""

import importlib.util
import math
import sys
from pathlib import Path

BIN = Path(__file__).resolve().parents[1] / "bin" / "stability.py"


def _load(bin_path=BIN, argv=("stability.py", "out.json")):
    """Import bin/stability.py with a controlled sys.argv (module reads
    SAMPLES/ROTATE_B at import time)."""
    spec = importlib.util.spec_from_file_location("stability_mod", bin_path)
    mod = importlib.util.module_from_spec(spec)
    old = sys.argv
    sys.argv = list(argv)
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.argv = old
    return mod


def _rotated(cands, rotate):
    return cands[rotate:] + cands[:rotate]


def test_spearman_perfect_and_inverse():
    mod = _load()
    assert mod.spearman([1, 2, 3, 4], [1, 2, 3, 4]) == 1.0
    assert mod.spearman([1, 2, 3, 4], [4, 3, 2, 1]) == -1.0


def test_spearman_ignores_scale():
    mod = _load()
    assert mod.spearman([1, 2, 3], [10, 20, 30]) == 1.0


def test_rotate_1_is_not_disjoint_at_4_samples():
    # The documented weak resample: 3 of 4 shards shared. If a future
    # default ever becomes rotate_b=1 again, this test forces the claim
    # to say so.
    from scrollq.score import _spread
    cands = [(x, y, z) for x in _spread(37, 3)
             for y in _spread(15, 3) for z in _spread(15, 3)]
    assert len(cands) == 27
    a = set(_rotated(cands, 0)[:4])
    b = set(_rotated(cands, 1)[:4])
    assert len(a & b) == 3  # mostly the same shards: NOT a stability check


def test_rotate_13_is_disjoint_at_4_and_12_samples():
    from scrollq.score import _spread
    cands = [(x, y, z) for x in _spread(37, 3)
             for y in _spread(15, 3) for z in _spread(15, 3)]
    for n in (4, 12):
        a = set(_rotated(cands, 0)[:n])
        b = set(_rotated(cands, 13)[:n])
        assert len(a & b) == 0, f"rotate=13 shares shards at n={n}"


def test_default_rotation_is_the_honest_one():
    mod = _load()
    assert mod.ROTATE_B == 13
    assert mod.SAMPLES == 4


def test_cli_overrides_samples_and_rotation():
    mod = _load(argv=("stability.py", "out.json", "12", "13"))
    assert mod.SAMPLES == 12
    assert mod.ROTATE_B == 13


def test_cli_overrides_spread():
    mod = _load(argv=("stability.py", "out.json", "12", "13", "5"))
    assert mod.SPREAD == 5


def test_default_spread_is_3():
    mod = _load()
    assert mod.SPREAD == 3


def test_main_records_provenance(tmp_path):
    # main() must record which samples/rotations produced the numbers,
    # so a reader can tell a weak resample from a strong one.
    mod = _load(argv=("stability.py", str(tmp_path / "o.json"), "12"))
    captured = {}

    def fake_run(roots, rotate, exclude=None):
        captured[rotate] = True
        return [{"root": f"v{i}", "ok": True, "score": float(i)}
                for i in range(12)]

    mod.run = fake_run
    out = mod.main()
    assert captured == {0: True, 13: True}
    assert out["samples"] == 12
    assert out["rotate_a"] == 0
    assert out["rotate_b"] == 13
    assert out["spearman_rho"] == 1.0
    assert out["top10_overlap"] == 10
    assert out["gate_pass"] is True


def _scored(root, score, identities, complete=True):
    return {"root": root, "ok": True, "score": score,
            "sampling": {"complete": complete},
            "sample_provenance": [{"identity": i} for i in identities]}


def test_cli_disjoint_flag():
    assert _load(argv=("stability.py", "o.json", "24", "13", "5",
                       "disjoint")).DISJOINT is True
    assert _load(argv=("stability.py", "o.json", "24", "13", "5")).DISJOINT \
        is False


def test_disjoint_main_excludes_run_a_identities(tmp_path):
    mod = _load(argv=("stability.py", str(tmp_path / "o.json"), "2", "13",
                      "5", "disjoint"))
    seen = {}

    def fake_run(roots, rotate, exclude=None):
        seen[rotate] = exclude
        return [_scored(f"v{i}", float(i), [f"v{i}-r{rotate}"])
                for i in range(3)]

    mod.run = fake_run
    mod.load_volumes = lambda: ["v0", "v1", "v2"]
    out = mod.main()
    assert seen[0] is None
    assert seen[13] == {f"v{i}": {f"v{i}-r0"} for i in range(3)}
    assert out["forced_disjoint"] is True
    assert out["provenance"]["n_truly_disjoint"] == 3


def test_disjoint_complete_drops_rereads_and_short_runs():
    mod = _load()
    r0 = [_scored("a", 10.0, ["a1"]), _scored("b", 20.0, ["b1"]),
          _scored("c", 30.0, ["c1"]), _scored("d", 40.0, ["d1"])]
    r1 = [_scored("a", 11.0, ["a2"]),               # disjoint, complete
          _scored("b", 21.0, ["b1"]),               # re-read: excluded
          _scored("c", 31.0, ["c2"], complete=False),  # short: excluded
          _scored("d", 41.0, ["d2"])]               # disjoint, complete
    out = mod.compare(r0, r1)
    assert out["n_volumes"] == 4
    honest = out["disjoint_complete"]
    assert honest["n_volumes"] == 2
    assert honest["spearman_rho"] == 1.0
    assert honest["mean_abs_diff"] == 1.0


def test_disjoint_complete_with_too_few_volumes_is_not_a_pass():
    mod = _load()
    out = mod.compare([_scored("a", 1.0, ["a1"])], [_scored("a", 1.0, ["a1"])])
    assert out["disjoint_complete"]["spearman_rho"] is None
    assert out["disjoint_complete"]["gate_pass"] is False
