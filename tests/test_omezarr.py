import json

import numpy as np
import pytest

from omezarr_fixture import build_store
from scrollq.omezarr import HttpStore, OmeZarrVolume, UnsupportedZarr


def _vol(shape=(20, 17, 23), seed=1):
    rng = np.random.default_rng(seed)
    return rng.integers(1, 255, shape, dtype=np.uint8)


def test_open_parses_levels_scales_and_fill():
    v = OmeZarrVolume.open(build_store(_vol(), chunks=(8, 8, 8), levels=3),
                           "vol.zarr")
    assert [lv.shape for lv in v.levels] == [(20, 17, 23), (10, 9, 12),
                                             (5, 5, 6)]
    assert v.levels[2].scale == (4.0, 4.0, 4.0)
    assert v.levels[0].chunk_grid == (3, 3, 3)
    assert v.fill_value == 0


def test_read_box_matches_source_across_chunk_and_edge_boundaries():
    vol = _vol()
    v = OmeZarrVolume.open(build_store(vol), "vol.zarr")
    box, stats = v.read_box(0, (5, 3, 6), (20, 17, 23))
    assert np.array_equal(box, vol[5:20, 3:17, 6:23])
    assert stats.chunks_missing == 0 and stats.chunks_present > 0
    # clipped request outside the array
    box2, _ = v.read_box(0, (-4, -4, -4), (100, 100, 100))
    assert np.array_equal(box2, vol)


def test_absent_chunks_read_as_fill_and_are_counted_not_errors():
    vol = _vol()
    vol[:8, :, :] = 0  # first z-slab of chunks is all zero -> absent
    store = build_store(vol)
    v = OmeZarrVolume.open(store, "vol.zarr")
    box, stats = v.read_box(0, (0, 0, 0), (16, 17, 23))
    assert np.array_equal(box, vol[:16])
    assert stats.chunks_missing == 9  # 3x3 chunks in the dropped slab
    assert stats.chunks_present == 9


def test_trilinear_is_exact_at_nodes_and_averages_midpoints():
    vol = _vol().astype(np.uint8)
    v = OmeZarrVolume.open(build_store(vol), "vol.zarr")
    pts = np.array([[3.0, 4.0, 5.0], [3.5, 4.0, 5.0], [3.5, 4.5, 5.5]])
    vals, valid, _ = v.sample_trilinear(0, pts)
    assert valid.all()
    f = vol.astype(np.float64)
    assert vals[0] == pytest.approx(f[3, 4, 5])
    assert vals[1] == pytest.approx((f[3, 4, 5] + f[4, 4, 5]) / 2)
    cube = f[3:5, 4:6, 5:7]
    assert vals[2] == pytest.approx(cube.mean(), abs=1e-4)


def test_trilinear_marks_out_of_range_invalid_nan():
    v = OmeZarrVolume.open(build_store(_vol()), "vol.zarr")
    pts = np.array([[-0.5, 3.0, 3.0], [19.0, 3.0, 3.0], [10.0, 3.0, 3.0]])
    vals, valid, _ = v.sample_trilinear(0, pts)
    assert valid.tolist() == [False, False, True]
    assert np.isnan(vals[0]) and np.isnan(vals[1]) and not np.isnan(vals[2])


def test_trilinear_pyramid_level_uses_that_levels_index_space():
    vol = _vol((32, 32, 32))
    v = OmeZarrVolume.open(build_store(vol, levels=2), "vol.zarr")
    vals, valid, _ = v.sample_trilinear(1, np.array([[4.0, 5.0, 6.0]]))
    assert valid[0] and vals[0] == pytest.approx(vol[8, 10, 12])


def test_nearest_level_picks_closest_voxel_size():
    v = OmeZarrVolume.open(build_store(_vol((32, 32, 32)), levels=3),
                           "vol.zarr")
    assert v.nearest_level(2.4, 2.4) == 0
    assert v.nearest_level(9.0, 2.4) == 2  # 9.6 um beats 4.8 um
    assert v.nearest_level(5.0, 2.4) == 1


@pytest.mark.parametrize("mutate,msg", [
    (lambda za: za.update(compressor={"id": "blosc"}), "compressed"),
    (lambda za: za.update(dtype="<u2"), "uint8"),
    (lambda za: za.update(order="F"), "C order"),
    (lambda za: za.update(zarr_format=3), "zarr_format 2"),
])
def test_unsupported_layouts_fail_loudly(mutate, msg):
    store = build_store(_vol())
    za = json.loads(store.data["vol.zarr/0/.zarray"])
    mutate(za)
    store.data["vol.zarr/0/.zarray"] = json.dumps(za).encode()
    with pytest.raises(UnsupportedZarr, match=msg):
        OmeZarrVolume.open(store, "vol.zarr")


def test_wrong_chunk_byte_length_is_not_silently_decoded():
    store = build_store(_vol())
    key = next(k for k in store.data if k.startswith("vol.zarr/0/0/"))
    store.data[key] = store.data[key][:-1]
    v = OmeZarrVolume.open(store, "vol.zarr")
    with pytest.raises(UnsupportedZarr, match="expected"):
        v.read_box(0, (0, 0, 0), (8, 8, 8))


def test_non_zyx_axes_rejected():
    store = build_store(_vol())
    za = json.loads(store.data["vol.zarr/.zattrs"])
    za["multiscales"][0]["axes"][0]["name"] = "t"
    store.data["vol.zarr/.zattrs"] = json.dumps(za).encode()
    with pytest.raises(UnsupportedZarr, match="z,y,x"):
        OmeZarrVolume.open(store, "vol.zarr")


def test_http_store_maps_404_to_none_and_retries_5xx():
    class R:
        def __init__(self, code, content=b""):
            self.status_code, self.content = code, content

    calls = []

    class S:
        def get(self, url, timeout):
            calls.append(url)
            if "ok" not in url:
                return R(404)
            # first attempt at /ok is a transient 503, the retry succeeds
            return R(503) if calls.count(url) == 1 else R(200, b"abc")

    st = HttpStore("https://x.test/b/", session=S(), retries=2)
    assert st.get("missing") is None
    assert st.get("ok") == b"abc"
    assert calls == ["https://x.test/b/missing", "https://x.test/b/ok",
                     "https://x.test/b/ok"]
