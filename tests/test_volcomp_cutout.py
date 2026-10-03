import json
import struct
from pathlib import Path

import numpy as np
import pytest

from zpa import volcomp as vc
import scrollq.volcomp_cutout as cut


class Head:
    def __init__(self, exists=True, status=200, error=None):
        self.exists = exists
        self.status = status
        self.error = error


class FakeStore:
    def __init__(self, meta, shards):
        self.meta = meta
        self.shards = shards

    def get_json(self, path):
        assert path.endswith("/0/zarr.json")
        return self.meta

    def head(self, path):
        if path not in self.shards:
            return Head(False, 404)
        return Head(True, 200)

    def get_suffix(self, path, length):
        return self.shards[path][-length:]

    def get_range(self, path, start, length):
        return self.shards[path][start : start + length]


def _meta(*, shape=(8, 8, 8), outer=(8, 8, 8), inner=(4, 4, 4), fill=7, crc=False):
    index_codecs = [{"name": "bytes"}]
    if crc:
        index_codecs.append({"name": "crc32c"})
    return {
        "zarr_format": 3,
        "node_type": "array",
        "shape": list(shape),
        "data_type": "uint8",
        "fill_value": fill,
        "chunk_grid": {
            "name": "regular",
            "configuration": {"chunk_shape": list(outer)},
        },
        "codecs": [
            {
                "name": "sharding_indexed",
                "configuration": {
                    "chunk_shape": list(inner),
                    "codecs": [{"name": "volcomp"}],
                    "index_codecs": index_codecs,
                    "index_location": "end",
                },
            }
        ],
    }


def _shard(values, *, crc=False, missing=()):
    chunks = []
    entries = []
    offset = 0
    for i, value in enumerate(values):
        if i in set(missing):
            entries.append((vc.MISSING, vc.MISSING))
            continue
        blob = bytes([value]) * (4 * 4 * 4)
        chunks.append(blob)
        entries.append((offset, len(blob)))
        offset += len(blob)
    index = b"".join(struct.pack("<QQ", *entry) for entry in entries)
    if crc:
        index += int(vc.crc32c(index)).to_bytes(4, "little")
    return b"".join(chunks) + index


def _store(*, fill=7, crc=False, missing=()):
    meta = _meta(fill=fill, crc=crc)
    shard = _shard(range(1, 9), crc=crc, missing=missing)
    return FakeStore(meta, {"v.zarr/0/c/0/0/0": shard})


def test_reads_exact_box_across_inner_chunk_boundaries():
    store = _store(fill=7)
    box, stats = cut.read_box(
        store,
        "v.zarr",
        (3, 3, 3),
        (6, 6, 6),
        decoder=lambda blob: blob,
    )
    assert box.shape == (3, 3, 3)
    # Corners cross all eight 4^3 inner chunks.
    assert box[0, 0, 0] == 1
    assert box[-1, -1, -1] == 8
    assert stats["chunks_present"] == 8
    assert stats["chunks_missing"] == 0
    assert stats["shards_touched"] == 1


def test_missing_inner_chunk_uses_declared_fill_value():
    store = _store(fill=19, missing=(0,))
    box, stats = cut.read_box(
        store,
        "v.zarr",
        (0, 0, 0),
        (2, 2, 2),
        decoder=lambda blob: blob,
    )
    assert np.all(box == 19)
    assert stats["chunks_present"] == 0
    assert stats["chunks_missing"] == 1


def test_missing_whole_shard_uses_fill_value():
    store = FakeStore(_meta(fill=23), {})
    box, stats = cut.read_box(
        store,
        "v.zarr",
        (0, 0, 0),
        (2, 2, 2),
        decoder=lambda blob: blob,
    )
    assert np.all(box == 23)
    assert stats["chunks_missing"] == 1


def test_crc32c_index_is_verified():
    store = _store(crc=True)
    box, _ = cut.read_box(
        store,
        "v.zarr",
        (0, 0, 0),
        (2, 2, 2),
        decoder=lambda blob: blob,
    )
    assert box[0, 0, 0] == 1

    key = "v.zarr/0/c/0/0/0"
    raw = bytearray(store.shards[key])
    raw[-1] ^= 1
    store.shards[key] = bytes(raw)
    with pytest.raises(cut.CutoutError, match="CRC32C mismatch"):
        cut.read_box(
            store,
            "v.zarr",
            (0, 0, 0),
            (2, 2, 2),
            decoder=lambda blob: blob,
        )


def test_clips_requested_box_to_volume_bounds():
    store = _store(fill=7)
    box, stats = cut.read_box(
        store,
        "v.zarr",
        (-2, -1, -3),
        (2, 2, 2),
        decoder=lambda blob: blob,
    )
    assert box.shape == (2, 2, 2)
    assert stats["requested_lo_zyx"] == [-2, -1, -3]
    assert stats["clipped_lo_zyx"] == [0, 0, 0]


@pytest.mark.parametrize(
    "mutator, message",
    [
        (lambda m: m.update(data_type="float32"), "expected uint8"),
        (lambda m: m.update(fill_value=-1), "unsupported fill_value"),
        (lambda m: m.update(codecs=[]), "not a volcomp"),
        (
            lambda m: m["codecs"][0]["configuration"].update(index_location="start"),
            "index_location",
        ),
    ],
)
def test_unsupported_metadata_fails_closed(mutator, message):
    meta = _meta()
    mutator(meta)
    store = FakeStore(meta, {})
    with pytest.raises(cut.CutoutError, match=message):
        cut.read_box(
            store,
            "v.zarr",
            (0, 0, 0),
            (2, 2, 2),
            decoder=lambda blob: blob,
        )


def _attested_audit(integrity="PASS"):
    return {
        "schema_version": "1.3.0",
        "tool_version": "test",
        "integrity": integrity,
        "source_attestation": {
            "algorithm": "zpa-metadata-semantics-v1",
            "state": "PRESENT",
            "metadata_semantics_sha256": "a" * 64,
            "axes": ["z", "y", "x"],
            "base_declared_scale": [1.0, 1.0, 1.0],
            "absolute_scale_state": "unspecified",
            "spatial_axes": [],
        },
    }


def test_extract_hash_binds_output_and_refuses_overwrite(tmp_path, monkeypatch):
    monkeypatch.setattr(cut, "audit_root", lambda store, root: _attested_audit())
    expected = np.arange(27, dtype=np.uint8).reshape(3, 3, 3)
    monkeypatch.setattr(
        cut,
        "read_box",
        lambda *a, **k: (
            expected,
            {
                "requested_lo_zyx": [1, 2, 3],
                "requested_hi_zyx": [4, 5, 6],
                "clipped_lo_zyx": [1, 2, 3],
                "clipped_hi_zyx": [4, 5, 6],
                "shape_zyx": [3, 3, 3],
                "fill_value": 0,
                "shards_touched": 1,
                "chunks_present": 1,
                "chunks_missing": 0,
                "decoded_bytes": 64,
            },
        ),
    )
    out = tmp_path / "cutout.npy"
    report = cut.extract(
        base_url="https://example.invalid",
        root="v.zarr",
        lo_zyx=(1, 2, 3),
        hi_zyx=(4, 5, 6),
        out_path=out,
        store=object(),
    )
    assert report["source_attestation"]["metadata_semantics_sha256"] == "a" * 64
    assert report["output"]["sha256"] == cut._sha256_file(out)
    saved = json.loads(out.with_suffix(".json").read_text())
    assert saved["output"]["sha256"] == report["output"]["sha256"]

    with pytest.raises(ValueError, match="refusing to overwrite"):
        cut.extract(
            base_url="https://example.invalid",
            root="v.zarr",
            lo_zyx=(1, 2, 3),
            hi_zyx=(4, 5, 6),
            out_path=out,
            store=object(),
        )


def test_extract_refuses_nonpassing_or_unattested_source(tmp_path, monkeypatch):
    monkeypatch.setattr(cut, "audit_root", lambda store, root: _attested_audit("FAIL"))
    with pytest.raises(cut.CutoutError, match="integrity is FAIL"):
        cut.extract(
            base_url="x",
            root="v.zarr",
            lo_zyx=(0, 0, 0),
            hi_zyx=(2, 2, 2),
            out_path=tmp_path / "x.npy",
            store=object(),
        )

    bad = _attested_audit()
    bad["source_attestation"]["state"] = "UNKNOWN"
    monkeypatch.setattr(cut, "audit_root", lambda store, root: bad)
    with pytest.raises(cut.CutoutError, match="attestation"):
        cut.extract(
            base_url="x",
            root="v.zarr",
            lo_zyx=(0, 0, 0),
            hi_zyx=(2, 2, 2),
            out_path=tmp_path / "y.npy",
            store=object(),
        )
