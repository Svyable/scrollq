import pytest

from scrollq.score import _spread


def test_spread_never_exceeds_requested_count():
    for n in range(1, 20):
        for k in range(1, 10):
            assert len(_spread(n, k)) <= k


@pytest.mark.parametrize("budget", [1, 3, 7, 9, 20])
def test_score_volume_honors_sample_budget(monkeypatch, budget):
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

    result = score_mod.score_volume("https://example.test", "root", samples=budget)
    assert result["metrics"]["chunks_decoded"] == min(budget, 16)
    assert result["sampling"]["complete"] == (budget <= 16)


@pytest.mark.parametrize("budget", [0, -1, -10])
def test_score_volume_rejects_nonpositive_sample_budget(budget):
    import scrollq.score as score_mod

    result = score_mod.score_volume("https://example.test", "root", samples=budget)
    assert result["ok"] is False
    assert result["error"] == "samples must be >= 1"


@pytest.mark.parametrize("status", [206, 404, 503])
def test_score_volume_reports_sampling_completeness(monkeypatch, status):
    from types import SimpleNamespace
    import scrollq.score as score_mod

    class Response:
        status_code = status
        content = b"index"

        def raise_for_status(self):
            if status >= 400:
                raise RuntimeError("request failed")

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
        shape=(2, 1, 1),
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

    result = score_mod.score_volume("https://example.test", "root", samples=4, rotate=3)

    assert result["ok"] is (status == 206)
    assert result["sampling"] == {
        "requested": 4,
        "decoded": 2 if status == 206 else 0,
        "complete": False,
        "rotate": 0,
        "shard_candidates": 1,
        "missing_shards": int(status == 404),
        "shard_read_failures": int(status == 503),
    }
