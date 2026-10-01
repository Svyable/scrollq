
def test_score_from_metrics_consistent():
    """score_from_metrics matches the inline formula on aggregate metrics."""
    from scrollq.score import score_from_metrics
    m = {"nonzero_frac": 0.8, "grad_energy": 10.0, "dyn_range": 150.0,
         "sat_frac": 0.01, "dead_slices": 2}
    s = score_from_metrics(m)
    # manual: 40*0.889 + 30*0.833 + 20*0.75 - 25*0.2 - 30 = 35.6+25+15-5-30
    assert 40.0 < s < 45.0, s


def test_score_std_nonnegative():
    """Per-chunk std is computed when chunk_results exist."""
    from scrollq.score import score_from_metrics
    chunks = [
        {"nonzero_frac": 0.9, "grad_energy": 12.0, "dyn_range": 200.0,
         "sat_frac": 0.0, "dead_slices": 0},
        {"nonzero_frac": 0.5, "grad_energy": 6.0, "dyn_range": 100.0,
         "sat_frac": 0.02, "dead_slices": 1},
    ]
    scores = [score_from_metrics(c) for c in chunks]
    assert scores[0] > scores[1]
    import numpy as np
    assert float(np.std(scores)) > 0
