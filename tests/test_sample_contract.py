from scrollq.score import _spread


def test_spread_never_exceeds_requested_count():
    for n in range(1, 20):
        for k in range(1, 10):
            assert len(_spread(n, k)) <= k
