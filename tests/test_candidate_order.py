"""Shard-candidate order: the default reproduces published campaigns; the
balanced order spreads every prefix through the volume; parts are disjoint."""

from types import SimpleNamespace

import pytest

import scrollq.score as score_mod
from scrollq.score import _candidates, _spread


def _legacy(grid, spread, rotate=0):
    cands = [(x, y, z)
             for x in _spread(grid[0], spread)
             for y in _spread(grid[1], spread)
             for z in _spread(grid[2], spread)]
    if rotate:
        rotate %= max(1, len(cands))
        cands = cands[rotate:] + cands[:rotate]
    return cands


@pytest.mark.parametrize("grid", [(40, 40, 40), (9, 30, 17), (3, 3, 3), (1, 50, 2)])
@pytest.mark.parametrize("spread", [3, 5, 7])
@pytest.mark.parametrize("rotate", [0, 13])
def test_default_order_is_the_published_one(grid, spread, rotate):
    assert _candidates(grid, spread, rotate) == _legacy(grid, spread, rotate)


def test_grid_prefix_is_one_slab_balanced_prefix_spans_the_volume():
    grid = (40, 40, 40)
    # 12 shards x 2 chunks = a 24-chunk sample when every candidate is usable.
    grid_prefix = _candidates(grid, 5)[:12]
    assert len({c[0] for c in grid_prefix}) == 1          # a single x plane
    balanced_prefix = _candidates(grid, 5, order="balanced")[:12]
    for axis in range(3):
        assert len({c[axis] for c in balanced_prefix}) >= 3
    first12 = _candidates(grid, 7, order="balanced")[:12]
    assert all(len({c[a] for c in first12}) >= 6 for a in range(3))
    # The default order's first 12 of the same 7-lattice share one x plane.
    assert len({c[0] for c in _candidates(grid, 7)[:12]}) == 1


def test_balanced_is_a_permutation_of_the_same_lattice():
    for grid, spread in [((40, 40, 40), 7), ((9, 30, 17), 5), ((2, 2, 50), 7)]:
        assert sorted(_candidates(grid, spread, order="balanced")) == sorted(_candidates(grid, spread))


def test_parts_are_disjoint_cover_everything_and_stay_spread():
    grid = (40, 40, 40)
    a = _candidates(grid, 7, order="balanced", part=(2, 0))
    b = _candidates(grid, 7, order="balanced", part=(2, 1))
    assert not set(a) & set(b)
    assert sorted(a + b) == sorted(_candidates(grid, 7))
    for part in (a, b):
        for axis in range(3):
            assert len({c[axis] for c in part[:12]}) >= 3


def test_invalid_order_or_part_is_rejected():
    with pytest.raises(ValueError):
        _candidates((4, 4, 4), 3, order="random")
    for bad in [(0, 0), (2, 2), (2, -1)]:
        with pytest.raises(ValueError):
            _candidates((4, 4, 4), 3, part=bad)


def _fake_volume(monkeypatch):
    info = SimpleNamespace(shape=(1280, 1280, 1280), outer_chunks=(128, 128, 128),
                           inner_chunks=(128, 128, 128), inner_codec="volcomp", index_codecs=[])

    class Store:
        def get_json(self, path):
            return {}

        def get_range(self, path, start, length):
            return b"blob"

    vc = score_mod.vc
    monkeypatch.setattr(score_mod, "open_store", lambda base: Store())
    monkeypatch.setattr(score_mod, "_read_shard_index", lambda store, key, size: (b"i", "ok", None))
    monkeypatch.setattr(vc, "available", lambda: (True, None))
    monkeypatch.setattr(vc, "parse_zarr_json", lambda meta: info)
    monkeypatch.setattr(vc, "shard_key", lambda root, level, sc: "s/%d.%d.%d" % sc)
    monkeypatch.setattr(vc, "inner_chunks_per_shard", lambda i, sc: (1, 1, 1))
    monkeypatch.setattr(vc, "index_encoded_size", lambda n, codecs: 16)
    monkeypatch.setattr(vc, "parse_index", lambda raw, n, codecs: [(0, 1)] * n)
    monkeypatch.setattr(vc, "decode_chunk", lambda blob: b"\x01" * 128 ** 3)
    monkeypatch.setattr(score_mod, "chunk_metrics", lambda vox: {
        "nonzero_frac": 1.0, "std": 1.0, "dyn_range": 1.0,
        "sat_frac": 0.0, "grad_energy": 1.0, "dead_slices": 0})


def test_score_volume_records_order_and_part_and_reads_disjoint_chunks(monkeypatch):
    _fake_volume(monkeypatch)
    default = score_mod.score_volume("u", "r", samples=6, spread=5)
    assert "order" not in default["sampling"] and "part" not in default["sampling"]
    assert len({p["shard_coord"][0] for p in default["sample_provenance"]}) == 1

    runs = [score_mod.score_volume("u", "r", samples=6, spread=5, order="balanced", part=(2, i))
            for i in (0, 1)]
    ids = [{p["identity"] for p in r["sample_provenance"]} for r in runs]
    assert all(r["sampling"]["order"] == "balanced" for r in runs)
    assert [r["sampling"]["part"] for r in runs] == [[2, 0], [2, 1]]
    assert all(len(i) == 6 for i in ids) and not ids[0] & ids[1]
    assert all(len({p["shard_coord"][0] for p in r["sample_provenance"]}) >= 3 for r in runs)

    bad = score_mod.score_volume("u", "r", samples=6, order="nope")
    assert bad["ok"] is False and "order" in bad["error"]


def test_parts_are_spatially_neutral():
    # Regression: an every-other split of a Halton order puts each part in one
    # half of x. Both parts' early candidates must sit around the centre.
    grid = (40, 40, 40)
    for i in (0, 1):
        part = _candidates(grid, 7, order="balanced", part=(2, i))[:24]
        for axis in range(3):
            mean = sum(c[axis] for c in part) / len(part) / (grid[axis] - 1)
            assert 0.35 <= mean <= 0.65, (i, axis, mean)
