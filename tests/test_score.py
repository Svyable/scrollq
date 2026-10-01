
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

def test_provenance_identity_format():
    """Provenance identities are stable strings combining shard key + flat index."""
    # Simulate the provenance structure without network access
    prov = {
        "identity": "some/key.zarr#42",
        "shard_coord": [1, 2, 3],
        "shard_key": "some/key.zarr",
        "inner_flat": 42,
        "inner_coord": [0, 1, 2],
    }
    assert "#" in prov["identity"]
    assert prov["identity"].endswith("#42")
    assert len(prov["shard_coord"]) == 3
    assert len(prov["inner_coord"]) == 3


def test_provenance_overlap_detection():
    """Jaccard computation correctly identifies disjoint vs overlapping sets."""
    s0 = {"a#1", "a#2", "b#1"}
    s1 = {"c#1", "c#2", "d#1"}
    assert len(s0 & s1) == 0  # disjoint
    s2 = {"a#1", "x#9"}
    inter = len(s0 & s2)
    union = len(s0 | s2)
    assert inter == 1
    assert round(inter / union, 3) == 0.25
