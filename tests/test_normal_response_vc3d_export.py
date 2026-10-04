from __future__ import annotations

import json
from pathlib import Path

import pytest

from scrollq.vc3d_review_export import (
    ReviewExportError,
    build_normal_response_bundle,
    export_file,
)


def _report() -> dict:
    return {
        "schema_version": 2,
        "tool": "scroliq-normal-response",
        "experimental_evidence_ready": True,
        "normal_response": {
            "components": {
                "review_queue": [
                    {
                        "component_id": 7,
                        "pixels": 23,
                        "xyz": [10.0, 20.0, 30.0],
                        "center_advantage_mean_probability": -0.12,
                        "nominal_mean_probability": 0.72,
                        "strongest_off_surface_mean_probability": 0.84,
                        "strongest_off_surface_offsets_voxels": [2],
                        "peak_offsets_voxels": [2],
                        "has_ground_truth_ink": False,
                    }
                ]
            }
        },
    }


def test_normal_response_component_exports_as_review_only_point():
    bundle = build_normal_response_bundle(
        _report(),
        source_name="normal-response.json",
        source_sha256="a" * 64,
        scroll="PHercParis4",
    )

    meta = bundle["scroliq_review_bundle"]
    assert meta["kind"] == "normal-response-component"
    assert meta["review_points"] == 1
    assert meta["source_verdict"] is True

    point = bundle["collections"]["1"]
    assert point["points"]["1"]["p"] == [10.0, 20.0, 30.0]
    assert "wind_a" not in point["points"]["1"]
    assert point["metadata"]["review_only"] is True
    assert point["tags"]["component_id"] == "7"
    assert point["tags"]["peak_offsets_voxels"] == "[2]"
    assert point["tags"]["has_ground_truth_ink"] == "false"


def test_normal_response_export_is_deterministic_and_create_only(tmp_path: Path):
    source = tmp_path / "normal-response.json"
    source.write_text(json.dumps(_report(), sort_keys=True) + "\n", encoding="utf-8")
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"

    export_file(source, a, scroll="PHercParis4", kind="normal-response-component")
    export_file(source, b, scroll="PHercParis4", kind="normal-response-component")

    assert a.read_bytes() == b.read_bytes()
    with pytest.raises(ReviewExportError, match="refusing to overwrite"):
        export_file(
            source,
            a,
            scroll="PHercParis4",
            kind="normal-response-component",
        )


def test_normal_response_export_fails_closed_without_xyz():
    report = _report()
    del report["normal_response"]["components"]["review_queue"][0]["xyz"]
    with pytest.raises(ReviewExportError, match="finite xyz"):
        build_normal_response_bundle(
            report,
            source_name="normal-response.json",
            source_sha256="b" * 64,
            scroll="PHercParis4",
        )


def test_normal_response_export_rejects_wrong_source_type():
    report = _report()
    report["tool"] = "other"
    with pytest.raises(ReviewExportError, match="not a scroliq-normal-response"):
        build_normal_response_bundle(
            report,
            source_name="normal-response.json",
            source_sha256="c" * 64,
            scroll="PHercParis4",
        )
