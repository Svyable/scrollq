from __future__ import annotations

import json
from pathlib import Path

import pytest

from scrollq.vc3d_review_export import (
    ReviewExportError,
    build_ray_order_bundle,
    build_winding_attachment_bundle,
    export_file,
    main,
)


def _source() -> dict:
    return {
        "decision": {"verdict": "INCONSISTENT"},
        "review_queue": [
            {
                "residual": -2,
                "frame": "relative:2",
                "point_id": "8",
                "xyz": [1, 2, 3],
                "wind_a": 4,
                "patch_piece": "b/#2",
                "distance": 7.0,
            },
            {
                "residual": -5,
                "frame": "relative:1",
                "point_id": "7",
                "xyz": [4.5, 5.5, 6.5],
                "wind_a": 3,
                "patch_piece": "a/#1",
                "distance": 0.5,
            },
            {
                "residual": 2,
                "frame": "relative:2",
                "point_id": "8",
                "xyz": [1, 2, 3],
                "wind_a": 4,
                "patch_piece": "c/#3",
                "distance": 1.0,
            },
        ],
    }


def test_build_groups_duplicate_point_and_preserves_context() -> None:
    bundle = build_winding_attachment_bundle(
        _source(),
        source_name="result.json",
        source_sha256="a" * 64,
        scroll="PHercParis4",
    )
    assert bundle["vc_pointcollections_json_version"] == "1"
    meta = bundle["scroliq_review_bundle"]
    assert meta["review_points"] == 2
    assert meta["source_findings"] == 3
    assert meta["source_verdict"] == "INCONSISTENT"

    collections = bundle["collections"]
    first = collections["1"]
    assert first["name"] == "ScrolIQ winding · relative:1/7"
    assert first["points"]["1"]["p"] == [4.5, 5.5, 6.5]
    assert first["points"]["1"]["creation_time"] == 0
    assert first["metadata"] == {"winding_is_absolute": False}

    second = collections["2"]
    assert second["tags"]["finding_count"] == "2"
    findings = json.loads(second["tags"]["findings_json"])
    assert [row["patch_piece"] for row in findings] == ["c/#3", "b/#2"]


def test_duplicate_point_must_have_identical_geometry() -> None:
    source = _source()
    source["review_queue"][2]["xyz"] = [9, 9, 9]
    with pytest.raises(ReviewExportError, match="inconsistent"):
        build_winding_attachment_bundle(
            source,
            source_name="result.json",
            source_sha256="b" * 64,
            scroll="PHercParis4",
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("xyz", [1, 2, float("nan")]),
        ("wind_a", 1.5),
        ("residual", 1.5),
        ("distance", -1),
        ("patch_piece", ""),
    ],
)
def test_invalid_rows_fail_closed(field: str, value: object) -> None:
    source = _source()
    source["review_queue"][0][field] = value
    with pytest.raises(ReviewExportError):
        build_winding_attachment_bundle(
            source,
            source_name="result.json",
            source_sha256="c" * 64,
            scroll="PHercParis4",
        )


def test_empty_queue_fails() -> None:
    with pytest.raises(ReviewExportError, match="non-empty"):
        build_winding_attachment_bundle(
            {"review_queue": []},
            source_name="result.json",
            source_sha256="d" * 64,
            scroll="PHercParis4",
        )


def test_export_is_deterministic_and_create_only(tmp_path: Path) -> None:
    src = tmp_path / "result.json"
    src.write_text(json.dumps(_source(), sort_keys=True) + "\n")
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"

    export_file(src, a, scroll="PHercParis4")
    export_file(src, b, scroll="PHercParis4")
    assert a.read_bytes() == b.read_bytes()

    with pytest.raises(ReviewExportError, match="refusing to overwrite"):
        export_file(src, a, scroll="PHercParis4")


def test_cli_help_and_success(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0

    src = tmp_path / "result.json"
    src.write_text(json.dumps(_source()) + "\n")
    out = tmp_path / "points.json"
    assert (
        main(
            [
                "--input",
                str(src),
                "--scroll",
                "PHercParis4",
                "--out",
                str(out),
            ]
        )
        == 0
    )
    stdout = capsys.readouterr().out
    assert "2 VC3D review point(s) from 3 finding(s)" in stdout
    assert out.is_file()


RAY_AUDIT = (
    Path(__file__).resolve().parents[1]
    / "artifacts/2026-10-01-paris4-winding-ray-order/PHercParis4.winding-audit.json"
)


def test_ray_order_queue_exports_every_frozen_review_point(tmp_path):
    out = tmp_path / "ray.points.json"
    bundle = export_file(RAY_AUDIT, out, scroll="PHercParis4", kind="winding-ray-order")
    meta = bundle["scroliq_review_bundle"]
    queue = json.loads(RAY_AUDIT.read_text())["ray_order"]["review_queue"]
    assert meta["kind"] == "winding-ray-order"
    assert meta["review_points"] == meta["source_findings"] == len(queue) == 4
    first = bundle["collections"]["1"]
    assert first["tags"]["scroliq_kind"] == "winding-ray-order"
    assert first["points"]["1"]["p"] == queue[0]["xyz"]
    assert json.loads(out.read_text()) == bundle


def test_ray_order_export_fails_closed_on_truncated_or_bad_queue():
    good = json.loads(RAY_AUDIT.read_text())
    truncated = json.loads(json.dumps(good))
    truncated["ray_order"]["review_queue_truncated"] = True
    with pytest.raises(ReviewExportError, match="truncated"):
        build_ray_order_bundle(truncated, source_name="x", source_sha256="0" * 64, scroll="P")
    bad = json.loads(json.dumps(good))
    bad["ray_order"]["review_queue"][0]["xyz"] = [1.0, float("nan"), 2.0]
    with pytest.raises(ReviewExportError, match="finite"):
        build_ray_order_bundle(bad, source_name="x", source_sha256="0" * 64, scroll="P")
    with pytest.raises(ReviewExportError, match="unknown kind"):
        export_file(RAY_AUDIT, "/nonexistent/out.json", scroll="P", kind="mesh")


def test_committed_ray_order_bundle_matches_fresh_export(tmp_path):
    committed = (
        Path(__file__).resolve().parents[1]
        / "artifacts/2026-10-04-review-queues/PHercParis4.ray-order.points.json"
    )
    out = tmp_path / "ray.points.json"
    export_file(RAY_AUDIT, out, scroll="PHercParis4", kind="winding-ray-order")
    assert out.read_bytes() == committed.read_bytes()
