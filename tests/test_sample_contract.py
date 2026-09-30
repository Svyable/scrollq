from scrollq.score import _spread


def test_spread_never_exceeds_requested_count():
    for n in range(1, 20):
        for k in range(1, 10):
            assert len(_spread(n, k)) <= k


def test_score_volume_honors_sample_budget(monkeypatch):
    from types import SimpleNamespace
    import scrollq.score as score_mod

    class Response:
        status_code = 206
        content = b"index"

        def raise_for_status(self):
            return None

    class Session:
        def get(self, *args, **kwargs):
            return Response()

    class Store:
        def get_json(self, path):
            return {}

        def _session(self):
            return Session()

        def get_range(self, path, start, length):
            return b"blob"

    info = SimpleNamespace(
        shape=(4, 2, 2),
        outer_chunks=(2, 1, 1),
        inner_chunks=(1, 1, 1),
        inner_codec="volcomp",
        index_codecs=[],
    )
    metrics = {
        "nonzero_frac": 1.0,
        "std": 1.0,
        "dyn_range": 1.0,
        "sat_frac": 0.0,
        "grad_energy": 1.0,
        "dead_slices": 0,
    }

    monkeypatch.setattr(score_mod, "open_store", lambda base: Store())
    monkeypatch.setattr(score_mod.vc, "available", lambda: (True, None))
    monkeypatch.setattr(score_mod.vc, "parse_zarr_json", lambda meta: info)
    monkeypatch.setattr(score_mod.vc, "shard_key", lambda root, level, sc: "shard")
    monkeypatch.setattr(score_mod.vc, "inner_chunks_per_shard", lambda info, sc: (2, 1, 1))
    monkeypatch.setattr(score_mod.vc, "index_encoded_size", lambda n, codecs: 4)
    monkeypatch.setattr(score_mod.vc, "parse_index", lambda raw, n, codecs: [(0, 1)] * n)
    monkeypatch.setattr(score_mod.vc, "decode_chunk", lambda blob: b"\x01")
    monkeypatch.setattr(score_mod, "chunk_metrics", lambda vox: metrics.copy())

    assert score_mod.score_volume("https://example.test", "root", samples=1)["metrics"]["chunks_decoded"] == 1
    assert score_mod.score_volume("https://example.test", "root", samples=3)["metrics"]["chunks_decoded"] == 3


def test_score_volume_rejects_nonpositive_sample_budget():
    import scrollq.score as score_mod

    result = score_mod.score_volume("https://example.test", "root", samples=0)
    assert result["ok"] is False
    assert result["error"] == "samples must be >= 1"
