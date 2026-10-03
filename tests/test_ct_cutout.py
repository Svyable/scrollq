import json
from pathlib import Path

import numpy as np
import pytest

from scrollq import ct_cutout


class FakeLevel:
    def __init__(self, array, chunks=(4, 4, 4), missing=()):
        self.array = np.asarray(array, dtype=np.uint8)
        self.shape = self.array.shape
        self.chunks = chunks
        self.missing = {tuple(v) for v in missing}

    def chunk(self, idx):
        idx = tuple(idx)
        if idx in self.missing:
            return None
        sl = tuple(
            slice(
                idx[d] * self.chunks[d],
                min((idx[d] + 1) * self.chunks[d], self.shape[d]),
            )
            for d in range(3)
        )
        return self.array[sl]


def _zpa(root, shape=(6, 7, 8), chunks=(4, 4, 4)):
    return {
        "schema_version": "1.3.0",
        "tool": "zarr-pyramid-audit",
        "root": root,
        "integrity": "PASS",
        "source_attestation": {
            "algorithm": "zpa-metadata-semantics-v1",
            "state": "PRESENT",
            "metadata_semantics_sha256": "b" * 64,
            "axes": ["z", "y", "x"],
        },
        "levels": [
            {
                "index": 0,
                "path": "0",
                "shape": list(shape),
                "chunks": list(chunks),
                "dtype": "|u1",
            }
        ],
    }


def test_cross_chunk_extraction_preserves_global_box():
    arr = np.arange(6 * 7 * 8, dtype=np.uint8).reshape(6, 7, 8)
    level = FakeLevel(arr)

    cutout, touched = ct_cutout.extract_from_level(
        level, start_zyx=(1, 2, 3), stop_zyx=(6, 6, 8)
    )

    np.testing.assert_array_equal(cutout, arr[1:6, 2:6, 3:8])
    assert touched == [
        [0, 0, 0], [0, 0, 1],
        [0, 1, 0], [0, 1, 1],
        [1, 0, 0], [1, 0, 1],
        [1, 1, 0], [1, 1, 1],
    ]


def test_missing_source_chunk_fails_closed():
    arr = np.ones((6, 7, 8), dtype=np.uint8)
    level = FakeLevel(arr, missing=[(0, 0, 1)])

    with pytest.raises(ct_cutout.CutoutError, match="missing"):
        ct_cutout.extract_from_level(
            level, start_zyx=(1, 2, 3), stop_zyx=(6, 6, 8)
        )


@pytest.mark.parametrize(
    "start,stop,message",
    [
        ((-1, 0, 0), (1, 1, 1), "non-negative"),
        ((1, 1, 1), (1, 2, 2), "start < stop"),
        ((0, 0, 0), (7, 1, 1), "exceeds source shape"),
    ],
)
def test_invalid_bbox_is_rejected(start, stop, message):
    level = FakeLevel(np.zeros((6, 7, 8), dtype=np.uint8))
    with pytest.raises(ct_cutout.CutoutError, match=message):
        ct_cutout.extract_from_level(level, start_zyx=start, stop_zyx=stop)


def test_zpa_binding_requires_exact_root_pass_and_zyx_axes():
    root = "PHerc0800/volumes/exact.zarr"
    report = _zpa(root)
    validate = lambda _report: []

    att, base = ct_cutout._verify_zpa_report(
        report, volume_root=root, validate_report_fn=validate
    )
    assert att["metadata_semantics_sha256"] == "b" * 64
    assert base["shape_zyx"] == [6, 7, 8]

    bad = dict(report)
    bad["root"] = "other.zarr"
    with pytest.raises(ct_cutout.CutoutError, match="exactly match"):
        ct_cutout._verify_zpa_report(
            bad, volume_root=root, validate_report_fn=validate
        )

    bad = json.loads(json.dumps(report))
    bad["source_attestation"]["axes"] = ["x", "y", "z"]
    with pytest.raises(ct_cutout.CutoutError, match="axes exactly"):
        ct_cutout._verify_zpa_report(
            bad, volume_root=root, validate_report_fn=validate
        )


def test_run_writes_hash_pinned_coordinate_manifest(tmp_path: Path):
    root = "PHerc0800/volumes/exact.zarr"
    source = np.arange(6 * 7 * 8, dtype=np.uint8).reshape(6, 7, 8)
    report_path = tmp_path / "zpa.json"
    report_path.write_text(json.dumps(_zpa(root)))
    out = tmp_path / "cutout.npy"
    manifest_path = tmp_path / "cutout.json"

    def factory(url, _session):
        assert url == f"https://example.test/{root}/0"
        return FakeLevel(source)

    result = ct_cutout.run(
        ct_url=f"https://example.test/{root}",
        volume_root=root,
        zpa_report_path=report_path,
        start_zyx=(1, 2, 3),
        stop_zyx=(6, 6, 8),
        out_path=out,
        manifest_path=manifest_path,
        session=object(),
        level_factory=factory,
        validate_report_fn=lambda _report: [],
    )

    np.testing.assert_array_equal(np.load(out), source[1:6, 2:6, 3:8])
    assert result["bbox_zyx_half_open"] == {
        "start": [1, 2, 3],
        "stop": [6, 6, 8],
    }
    assert result["local_to_global"]["start_zyx"] == [1, 2, 3]
    assert result["cutout"]["sha256"] == ct_cutout.sha256_file(out)
    assert result["zpa_report"]["sha256"] == ct_cutout.sha256_file(report_path)
    assert result["source_chunks"]["missing_count"] == 0
    assert (
        json.loads(manifest_path.read_text())["cutout"]["sha256"]
        == result["cutout"]["sha256"]
    )


def test_run_refuses_url_alias_and_overwrite(tmp_path: Path):
    root = "PHerc0800/volumes/exact.zarr"
    report_path = tmp_path / "zpa.json"
    report_path.write_text(json.dumps(_zpa(root)))
    out = tmp_path / "cutout.npy"
    out.write_bytes(b"keep")
    manifest = tmp_path / "manifest.json"

    with pytest.raises(ct_cutout.CutoutError, match="exact volume_root"):
        ct_cutout.run(
            ct_url="https://example.test/PHerc0800/volumes/other.zarr",
            volume_root=root,
            zpa_report_path=report_path,
            start_zyx=(0, 0, 0),
            stop_zyx=(1, 1, 1),
            out_path=tmp_path / "new.npy",
            manifest_path=manifest,
            session=object(),
            validate_report_fn=lambda _report: [],
        )

    with pytest.raises(ct_cutout.CutoutError, match="overwrite"):
        ct_cutout.run(
            ct_url=f"https://example.test/{root}",
            volume_root=root,
            zpa_report_path=report_path,
            start_zyx=(0, 0, 0),
            stop_zyx=(1, 1, 1),
            out_path=out,
            manifest_path=manifest,
            session=object(),
            level_factory=lambda *_: FakeLevel(
                np.zeros((6, 7, 8), dtype=np.uint8)
            ),
            validate_report_fn=lambda _report: [],
        )
