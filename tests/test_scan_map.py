from types import SimpleNamespace

import pytest

import scrollq.scan_map as scan_map


class _Response:
    def __init__(self, status_code=206, content=b"index"):
        self.status_code = status_code
        self.content = content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


def _info(shape=(4, 4, 4), outer=(2, 2, 2), inner=(1, 1, 1)):
    return SimpleNamespace(
        shape=shape,
        outer_chunks=outer,
        inner_chunks=inner,
        inner_codec="volcomp",
        index_codecs=[],
    )


def _patch_common(monkeypatch, *, info=None, status_by_shard=None, entries=None):
    info = info or _info()
    status_by_shard = status_by_shard or {}
    entries = entries or [(0, 1)] * 8

    class Session:
        def get(self, url, *args, **kwargs):
            shard = url.rsplit("/", 1)[-1]
            return _Response(status_by_shard.get(shard, 206))

    class Store:
        def get_json(self, path):
            return {}

        def _session(self):
            return Session()

        def get_range(self, path, start, length):
            return b"blob"

    monkeypatch.setattr(scan_map, "open_store", lambda base: Store())
    monkeypatch.setattr(scan_map.vc, "available", lambda: (True, None))
    monkeypatch.setattr(scan_map.vc, "parse_zarr_json", lambda meta: info)
    monkeypatch.setattr(
        scan_map.vc, "shard_key",
        lambda root, level, sc: f"shard-{sc[0]}-{sc[1]}-{sc[2]}",
    )
    monkeypatch.setattr(
        scan_map.vc, "inner_chunks_per_shard",
        lambda info, sc: tuple(o // i for o, i in zip(info.outer_chunks, info.inner_chunks)),
    )
    monkeypatch.setattr(scan_map.vc, "index_encoded_size", lambda n, codecs: 4)
    monkeypatch.setattr(
        scan_map.vc, "parse_index",
        lambda raw, n, codecs: entries[:n],
    )
    monkeypatch.setattr(scan_map.vc, "decode_chunk", lambda blob: b"\x01")
    monkeypatch.setattr(
        scan_map,
        "chunk_metrics",
        lambda vox: {
            "nonzero_frac": 1.0,
            "std": 0.0,
            "dyn_range": 0.0,
            "sat_frac": 0.0,
            "grad_energy": 0.0,
            "dead_slices": 0,
        },
    )
    return info


def test_scan_map_preserves_spatial_coordinates_without_readiness_score(monkeypatch):
    _patch_common(monkeypatch)

    report = scan_map.scan_volume_map(
        "https://example.test", "root", grid=2, chunks_per_shard=1
    )

    assert report["ok"] is True
    assert report["sampling"]["candidate_shards"] == 8
    assert report["sampling"]["chunks_decoded"] == 8
    assert "score" not in report

    last = next(r for r in report["regions"] if r["shard_coord"] == [1, 1, 1])
    assert last["status"] == "decoded"
    assert last["shard_voxel_bbox"] == {
        "start": [2, 2, 2],
        "stop": [4, 4, 4],
    }
    chunk = last["chunks"][0]
    assert chunk["global_chunk_coord"] == [2, 2, 2]
    assert chunk["voxel_bbox"] == {
        "start": [2, 2, 2],
        "stop": [3, 3, 3],
    }


def test_scan_map_retains_missing_and_failed_shards(monkeypatch):
    info = _info(shape=(3, 1, 1), outer=(1, 1, 1), inner=(1, 1, 1))
    _patch_common(
        monkeypatch,
        info=info,
        status_by_shard={
            "shard-1-0-0": 404,
            "shard-2-0-0": 503,
        },
        entries=[(0, 1)],
    )

    report = scan_map.scan_volume_map(
        "https://example.test", "root", grid=3, chunks_per_shard=1
    )

    assert report["sampling"]["status_counts"] == {
        "decoded": 1,
        "missing-shard": 1,
        "read-failure": 1,
    }
    statuses = {
        tuple(region["shard_coord"]): region["status"]
        for region in report["regions"]
    }
    assert statuses[(0, 0, 0)] == "decoded"
    assert statuses[(1, 0, 0)] == "missing-shard"
    assert statuses[(2, 0, 0)] == "read-failure"


def test_scan_map_marks_sparse_mask_instead_of_silently_dropping(monkeypatch):
    info = _info(shape=(1, 1, 1), outer=(1, 1, 1), inner=(1, 1, 1))
    _patch_common(monkeypatch, info=info, entries=[(scan_map.vc.MISSING, 0)])

    report = scan_map.scan_volume_map(
        "https://example.test", "root", grid=1, chunks_per_shard=1
    )

    assert report["ok"] is False
    assert report["regions"][0]["status"] == "sparse-mask"
    assert report["regions"][0]["present_frac"] == 0.0


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"grid": 0}, "grid must be >= 1"),
        ({"chunks_per_shard": 0}, "chunks_per_shard must be >= 1"),
    ],
)
def test_scan_map_rejects_invalid_sampling(monkeypatch, kwargs, message):
    monkeypatch.setattr(scan_map, "open_store", lambda base: object())
    report = scan_map.scan_volume_map("https://example.test", "root", **kwargs)
    assert report["ok"] is False
    assert report["error"] == message
