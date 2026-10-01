"""Chunk-level failures must be counted in sampling provenance, not skipped."""

from types import SimpleNamespace

import pytest

import scrollq.score as score_mod

GOOD_METRICS = {
    "nonzero_frac": 1.0, "std": 1.0, "dyn_range": 1.0,
    "sat_frac": 0.0, "grad_energy": 1.0, "dead_slices": 0,
}
CHUNK_BYTES = 128 ** 3


def _install(monkeypatch, *, inner=(128, 128, 128), get_range=None,
             decode=None, parse_index=None):
    """One 1-shard, 1-chunk volume; each stage is overridable."""

    class Store:
        def get_json(self, path):
            return {}

        def get_suffix(self, path, length):
            return b"index"

        def head(self, path):
            return SimpleNamespace(exists=True, status=200)

        def get_range(self, path, start, length):
            return b"blob"

    if get_range is not None:
        Store.get_range = lambda self, path, start, length: get_range()

    info = SimpleNamespace(shape=inner, outer_chunks=inner, inner_chunks=inner,
                           inner_codec="volcomp", index_codecs=[])
    monkeypatch.setattr(score_mod, "open_store", lambda base: Store())
    vc = score_mod.vc
    monkeypatch.setattr(vc, "available", lambda: (True, None))
    monkeypatch.setattr(vc, "parse_zarr_json", lambda meta: info)
    monkeypatch.setattr(vc, "shard_key", lambda root, level, sc: "shard")
    monkeypatch.setattr(vc, "inner_chunks_per_shard", lambda i, sc: (1, 1, 1))
    monkeypatch.setattr(vc, "index_encoded_size", lambda n, codecs: 16)
    monkeypatch.setattr(vc, "parse_index",
                        parse_index or (lambda raw, n, codecs: [(0, 1)] * n))
    monkeypatch.setattr(vc, "decode_chunk",
                        decode or (lambda blob: b"\x01" * CHUNK_BYTES))
    monkeypatch.setattr(score_mod, "chunk_metrics",
                        lambda vox: GOOD_METRICS.copy())


def _run():
    return score_mod.score_volume("https://example.test", "root", samples=1)


def test_clean_run_reports_zero_failure_counters(monkeypatch):
    _install(monkeypatch)
    r = _run()
    assert r["ok"] is True
    s = r["sampling"]
    assert (s["shard_index_invalid"], s["chunk_read_failures"],
            s["chunk_decode_failures"]) == (0, 0, 0)


def test_invalid_shard_index_is_counted_not_dropped(monkeypatch):
    # zpa.parse_index returns None on structural problems (no exception).
    _install(monkeypatch, parse_index=lambda raw, n, codecs: None)
    r = _run()
    assert r["ok"] is False
    assert r["sampling"]["shard_index_invalid"] == 1
    assert "1 shard index" in r["error"]


def test_chunk_read_failure_is_counted(monkeypatch):
    def boom():
        raise RuntimeError("range read failed")

    _install(monkeypatch, get_range=boom)
    r = _run()
    assert r["ok"] is False
    assert r["sampling"]["chunk_read_failures"] == 1
    assert "1 chunk read" in r["error"]


def test_decoder_returning_none_is_counted(monkeypatch):
    _install(monkeypatch, decode=lambda blob: None)
    r = _run()
    assert r["ok"] is False
    assert r["sampling"]["chunk_decode_failures"] == 1
    assert "1 chunk decode" in r["error"]


def test_unsupported_inner_chunk_shape_is_a_decode_failure_not_a_crash(
        monkeypatch):
    # libvolcomp always yields 128^3 bytes; a 64^3 inner shape cannot be
    # reshaped. This used to raise ValueError out of score_volume.
    _install(monkeypatch, inner=(64, 64, 64))
    r = _run()
    assert r["ok"] is False
    assert r["sampling"]["chunk_decode_failures"] == 1


def test_failures_do_not_hide_behind_a_complete_budget(monkeypatch):
    """complete=True with failures: the counters are the only evidence."""
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient")
        return b"blob"

    # Two inner chunks in one shard; first read fails, second succeeds.
    _install(monkeypatch, inner=(128, 128, 128), get_range=flaky)
    monkeypatch.setattr(score_mod.vc, "inner_chunks_per_shard",
                        lambda i, sc: (2, 1, 1))
    r = _run()
    assert r["ok"] is True
    assert r["sampling"]["complete"] is True
    assert r["sampling"]["chunk_read_failures"] == 1


@pytest.mark.parametrize("key", ["shard_index_invalid",
                                 "chunk_read_failures",
                                 "chunk_decode_failures"])
def test_counters_are_integers(monkeypatch, key):
    _install(monkeypatch)
    assert isinstance(_run()["sampling"][key], int)


def _two_chunk_shard(monkeypatch):
    _install(monkeypatch)
    monkeypatch.setattr(score_mod.vc, "inner_chunks_per_shard",
                        lambda i, sc: (2, 1, 1))


def test_default_sampling_has_no_exclusion_key(monkeypatch):
    # exclude=None must leave the published sampling record unchanged.
    _two_chunk_shard(monkeypatch)
    r = score_mod.score_volume("https://example.test", "root", samples=2)
    assert "excluded_chunks" not in r["sampling"]


def test_exclude_forces_chunk_disjoint_resample(monkeypatch):
    _two_chunk_shard(monkeypatch)
    first = score_mod.score_volume("https://example.test", "root", samples=1)
    seen = {p["identity"] for p in first["sample_provenance"]}
    second = score_mod.score_volume("https://example.test", "root",
                                    samples=1, exclude=seen)
    assert second["ok"] is True
    assert seen.isdisjoint(p["identity"] for p in second["sample_provenance"])
    assert second["sampling"]["excluded_chunks"] == 1


def test_exclude_everything_reports_shortfall_not_reuse(monkeypatch):
    _install(monkeypatch)
    first = score_mod.score_volume("https://example.test", "root", samples=1)
    seen = {p["identity"] for p in first["sample_provenance"]}
    r = score_mod.score_volume("https://example.test", "root", samples=1,
                               exclude=seen)
    assert r["ok"] is False
    assert r["sampling"]["decoded"] == 0
    assert r["sampling"]["excluded_chunks"] == 1
