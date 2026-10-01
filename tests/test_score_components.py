"""The published component breakdown and the score share one set of weights."""

import itertools

import pytest

from scrollq.score import SCORE_POLICY_VERSION, score_components, score_from_metrics


def _reference_score(m: dict) -> float:
    """The original inline formula, kept verbatim as an independent oracle."""
    s_signal = 40.0 * min(1.0, m["nonzero_frac"] / 0.9)
    s_texture = 30.0 * min(1.0, m["grad_energy"] / 12.0)
    s_dynamic = 20.0 * min(1.0, m["dyn_range"] / 200.0)
    p_sat = 25.0 * min(1.0, m["sat_frac"] / 0.05)
    p_dead = min(30.0, 15.0 * m["dead_slices"])
    return max(0.0, min(100.0, s_signal + s_texture + s_dynamic
                        - p_sat - p_dead))


GRID = [
    {"nonzero_frac": nz, "grad_energy": g, "dyn_range": d,
     "sat_frac": s, "dead_slices": dead}
    for nz, g, d, s, dead in itertools.product(
        (0.0, 0.3, 0.9, 1.0),
        (0.0, 4.0, 12.0, 40.0),
        (0.0, 100.0, 200.0, 255.0),
        (0.0, 0.01, 0.05, 0.5),
        (0, 1, 2, 5),
    )
]


@pytest.mark.parametrize("m", GRID)
def test_score_matches_original_formula_exactly(m):
    assert score_from_metrics(m) == _reference_score(m)


def test_score_pinned_value():
    # 35.5556 + 25 + 15 - 5 - 30: documents the weights on a fixed input.
    m = {"nonzero_frac": 0.8, "grad_energy": 10.0, "dyn_range": 150.0,
         "sat_frac": 0.01, "dead_slices": 2}
    assert score_from_metrics(m) == pytest.approx(40.5556, abs=1e-4)


def test_components_use_the_published_keys_and_weight_caps():
    best = {"nonzero_frac": 1.0, "grad_energy": 99.0, "dyn_range": 255.0,
            "sat_frac": 0.0, "dead_slices": 0}
    c = score_components(best)
    assert set(c) == {"signal_40", "texture_30", "dynamic_20",
                      "pen_sat", "pen_dead"}
    assert (c["signal_40"], c["texture_30"], c["dynamic_20"]) == (40, 30, 20)

    worst_penalties = {**best, "sat_frac": 1.0, "dead_slices": 99}
    c = score_components(worst_penalties)
    assert (c["pen_sat"], c["pen_dead"]) == (25, 30)


def test_score_policy_has_a_stable_explicit_version():
    assert SCORE_POLICY_VERSION == "scan-health-v1"
