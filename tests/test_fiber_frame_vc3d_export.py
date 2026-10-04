from __future__ import annotations

import json
from pathlib import Path

import pytest

from scrollq.vc3d_review_export import (
    ReviewExportError,
    build_fiber_frame_bundle,
    export_file,
)


def _report() -> dict:
    return {
        "schema_version": 1,
        "tool": "scroliq-fiber-frame",
        "analysis": {
            "status": "measured",
            "review_queue": [
                {
                    "finding_id": "0:1->0:2",
                    "kind": "cross_ply_frame_discontinuity",
                    "tile_a": [0, 1],
                    "tile_b": [0, 2],
                    "frame_delta_degrees": 36.5,
                    "xyz": [10.0, 20.0, 30.0],
                },
                {
                    "finding_id": "1:1->1:2",
                    "kind": "cross_ply_frame_discontinuity",
                    "tile_a": [1, 1],
                    "tile_b": [1, 2],
                    "frame_delta_degrees": 34.0,
                    "xyz": [11.0, 21.0, 31.0],
                },
            ],
        },
    }


def test_fiber_frame_bundle_is_native_review_points():
    bundle = build_fiber_frame_bundle(
        _report(),
        source_name="fiber-frame.json",
        source_sha256="a" * 64,
        scroll="PHercParis4",
    )

    meta = bundle["scroliq_review_bundle"]
    assert meta["kind"] == "fiber-frame-discontinuity"
    assert meta["review_points"] == 2
    assert meta["source_verdict"] == "measured"

    first = bundle["collections"]["1"]
    assert first["points"]["1"]["p"] == [10.0, 20.0, 30.0]
    assert "wind_a" not in first["points"]["1"]
    assert first["metadata"]["review_only"] is True
    assert first["tags"]["finding_id"] == "0:1->0:2"


def test_fiber_frame_export_is_deterministic_and_create_only(tmp_path: Path):
    source = tmp_path / "fiber-frame.json"
    source.write_text(json.dumps(_report(), sort_keys=True) + "\n", encoding="utf-8")
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"

    export_file(
        source,
        a,
        scroll="PHercParis4",
        kind="fiber-frame-discontinuity",
    )
    export_file(
        source,
        b,
        scroll="PHercParis4",
        kind="fiber-frame-discontinuity",
    )

    assert a.read_bytes() == b.read_bytes()
    with pytest.raises(ReviewExportError, match="refusing to overwrite"):
        export_file(
            source,
            a,
            scroll="PHercParis4",
            kind="fiber-frame-discontinuity",
        )


def test_fiber_frame_export_fails_closed_without_xyz():
    report = _report()
    del report["analysis"]["review_queue"][0]["xyz"]
    with pytest.raises(ReviewExportError, match="finite xyz"):
        build_fiber_frame_bundle(
            report,
            source_name="fiber-frame.json",
            source_sha256="b" * 64,
            scroll="PHercParis4",
        )


def test_fiber_frame_export_rejects_wrong_source_type():
    report = _report()
    report["tool"] = "other"
    with pytest.raises(ReviewExportError, match="not a scroliq-fiber-frame"):
        build_fiber_frame_bundle(
            report,
            source_name="fiber-frame.json",
            source_sha256="c" * 64,
            scroll="PHercParis4",
        )
