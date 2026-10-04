"""Export ScrolIQ diagnostic review queues as native VC3D PointCollections.

Supported sources: the preregistered winding-attachment result and the
winding ray-order audit (``scroliq-winding`` ``ray_order.review_queue``).
The exporter is deterministic, carries the source SHA-256, and preserves
review context in PointCollection tags so the file can be loaded directly
through VC3D or ``vc3d_load_points_json``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

TOOL = "scroliq-vc3d-review"
SCHEMA_VERSION = 1
POINTCOLLECTIONS_VERSION = "1"
KIND = "winding-attachment"
RAY_ORDER_KIND = "winding-ray-order"
KINDS = (KIND, RAY_ORDER_KIND)

LIMITATION = (
    "These markers are review cues, not confirmed annotation or patch errors. "
    "Inspect the papyrus surface and CT evidence in VC3D before changing data."
)


class ReviewExportError(ValueError):
    """The review source cannot be exported safely."""


def _finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def build_winding_attachment_bundle(
    document: Any,
    *,
    source_name: str,
    source_sha256: str,
    scroll: str,
) -> dict[str, Any]:
    """Convert a winding-attachment result into VC3D PointCollections v1."""
    if not isinstance(document, dict):
        raise ReviewExportError("source must be a JSON object")
    if not isinstance(source_name, str) or not source_name.strip():
        raise ReviewExportError("source_name must be non-empty")
    if (
        not isinstance(source_sha256, str)
        or len(source_sha256) != 64
        or any(ch not in "0123456789abcdef" for ch in source_sha256)
    ):
        raise ReviewExportError("source_sha256 must be lowercase 64-hex")
    if not isinstance(scroll, str) or not scroll.strip():
        raise ReviewExportError("scroll must be non-empty")

    queue = document.get("review_queue")
    if not isinstance(queue, list) or not queue:
        raise ReviewExportError("source review_queue must be a non-empty list")

    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for index, row in enumerate(queue):
        if not isinstance(row, dict):
            raise ReviewExportError(f"review_queue[{index}] must be an object")
        frame = row.get("frame")
        point_id = row.get("point_id")
        xyz = row.get("xyz")
        wind_a = row.get("wind_a")
        residual = row.get("residual")
        patch_piece = row.get("patch_piece")
        distance = row.get("distance")

        if not isinstance(frame, str) or not frame:
            raise ReviewExportError(f"review_queue[{index}].frame must be non-empty")
        point_id = str(point_id) if point_id is not None else ""
        if not point_id:
            raise ReviewExportError(f"review_queue[{index}].point_id must be present")
        if (
            not isinstance(xyz, list)
            or len(xyz) != 3
            or not all(_finite_number(v) for v in xyz)
        ):
            raise ReviewExportError(
                f"review_queue[{index}].xyz must be three finite numbers"
            )
        xyzf = [float(v) for v in xyz]
        if not _finite_number(wind_a) or not float(wind_a).is_integer():
            raise ReviewExportError(
                f"review_queue[{index}].wind_a must be a finite integer"
            )
        wind_value = int(wind_a)
        if not _finite_number(residual) or not float(residual).is_integer():
            raise ReviewExportError(
                f"review_queue[{index}].residual must be a finite integer"
            )
        if not isinstance(patch_piece, str) or not patch_piece:
            raise ReviewExportError(
                f"review_queue[{index}].patch_piece must be non-empty"
            )
        if not _finite_number(distance) or float(distance) < 0:
            raise ReviewExportError(
                f"review_queue[{index}].distance must be finite and >= 0"
            )

        key = (frame, point_id)
        finding = {
            "distance_voxels": float(distance),
            "patch_piece": patch_piece,
            "residual": int(residual),
        }
        existing = grouped.get(key)
        if existing is None:
            grouped[key] = {
                "frame": frame,
                "point_id": point_id,
                "xyz": xyzf,
                "wind_a": wind_value,
                "findings": [finding],
            }
        else:
            if existing["xyz"] != xyzf or existing["wind_a"] != wind_value:
                raise ReviewExportError(
                    f"duplicate point {frame}/{point_id} has inconsistent "
                    "coordinates or winding"
                )
            existing["findings"].append(finding)

    collections: dict[str, Any] = {}
    for collection_index, key in enumerate(sorted(grouped), start=1):
        item = grouped[key]
        findings = sorted(
            item["findings"],
            key=lambda finding: (
                -abs(finding["residual"]),
                finding["distance_voxels"],
                finding["patch_piece"],
            ),
        )
        max_abs = max(abs(finding["residual"]) for finding in findings)
        tags = {
            "scroliq_kind": KIND,
            "source_sha256": source_sha256,
            "frame": item["frame"],
            "source_point_id": item["point_id"],
            "source_winding": str(item["wind_a"]),
            "finding_count": str(len(findings)),
            "max_abs_residual": str(max_abs),
            "findings_json": json.dumps(
                findings, separators=(",", ":"), sort_keys=True
            ),
        }
        collections[str(collection_index)] = {
            "name": f"ScrolIQ winding · {item['frame']}/{item['point_id']}",
            "points": {
                str(collection_index): {
                    "p": item["xyz"],
                    "creation_time": 0,
                    "wind_a": item["wind_a"],
                }
            },
            "metadata": {"winding_is_absolute": item["frame"] == "absolute"},
            "color": [1, 0.55, 0],
            "tags": tags,
        }

    decision = document.get("decision")
    verdict = decision.get("verdict") if isinstance(decision, dict) else None
    return {
        "scroliq_review_bundle": {
            "schema_version": SCHEMA_VERSION,
            "tool": TOOL,
            "kind": KIND,
            "scroll": scroll,
            "coordinate_space": "level0-voxel-xyz",
            "source": source_name,
            "source_sha256": source_sha256,
            "source_verdict": verdict,
            "review_points": len(collections),
            "source_findings": len(queue),
            "limitation": LIMITATION,
        },
        "vc_pointcollections_json_version": POINTCOLLECTIONS_VERSION,
        "collections": collections,
    }


def build_ray_order_bundle(
    document: Any,
    *,
    source_name: str,
    source_sha256: str,
    scroll: str,
) -> dict[str, Any]:
    """Convert a winding ray-order audit's review queue into PointCollections v1."""
    if not isinstance(document, dict):
        raise ReviewExportError("source must be a JSON object")
    if (
        not isinstance(source_sha256, str)
        or len(source_sha256) != 64
        or any(ch not in "0123456789abcdef" for ch in source_sha256)
    ):
        raise ReviewExportError("source_sha256 must be lowercase 64-hex")
    if not isinstance(scroll, str) or not scroll.strip():
        raise ReviewExportError("scroll must be non-empty")
    ray = document.get("ray_order")
    if not isinstance(ray, dict):
        raise ReviewExportError("source has no ray_order section")
    if ray.get("review_queue_truncated"):
        raise ReviewExportError("ray_order review_queue is truncated; rerun untruncated")
    queue = ray.get("review_queue")
    if not isinstance(queue, list) or not queue:
        raise ReviewExportError("ray_order.review_queue must be a non-empty list")

    rows: dict[tuple[str, str], dict[str, Any]] = {}
    for index, row in enumerate(queue):
        if not isinstance(row, dict):
            raise ReviewExportError(f"review_queue[{index}] must be an object")
        frame = row.get("frame")
        point_id = str(row.get("point_id") or "")
        xyz = row.get("xyz")
        wind_a = row.get("wind_a")
        if not isinstance(frame, str) or not frame or not point_id:
            raise ReviewExportError(f"review_queue[{index}] needs frame and point_id")
        if (
            not isinstance(xyz, list)
            or len(xyz) != 3
            or not all(_finite_number(v) for v in xyz)
        ):
            raise ReviewExportError(
                f"review_queue[{index}].xyz must be three finite numbers"
            )
        if not _finite_number(wind_a) or not float(wind_a).is_integer():
            raise ReviewExportError(
                f"review_queue[{index}].wind_a must be a finite integer"
            )
        key = (frame, point_id)
        if key in rows:
            raise ReviewExportError(f"duplicate review point {frame}/{point_id}")
        rows[key] = {
            "xyz": [float(v) for v in xyz],
            "wind_a": int(wind_a),
            "inversion_pairs": int(row.get("inversion_pairs") or 0),
            "comparable_pairs": int(row.get("comparable_pairs") or 0),
        }

    collections: dict[str, Any] = {}
    for collection_index, key in enumerate(sorted(rows), start=1):
        frame, point_id = key
        item = rows[key]
        collections[str(collection_index)] = {
            "name": f"ScrolIQ ray order · {frame}/{point_id}",
            "points": {
                str(collection_index): {
                    "p": item["xyz"],
                    "creation_time": 0,
                    "wind_a": item["wind_a"],
                }
            },
            "metadata": {"winding_is_absolute": frame == "absolute"},
            "color": [0.4, 0.66, 0.88],
            "tags": {
                "scroliq_kind": RAY_ORDER_KIND,
                "source_sha256": source_sha256,
                "frame": frame,
                "source_point_id": point_id,
                "source_winding": str(item["wind_a"]),
                "inversion_pairs": str(item["inversion_pairs"]),
                "comparable_pairs": str(item["comparable_pairs"]),
            },
        }

    return {
        "scroliq_review_bundle": {
            "schema_version": SCHEMA_VERSION,
            "tool": TOOL,
            "kind": RAY_ORDER_KIND,
            "scroll": scroll,
            "coordinate_space": "level0-voxel-xyz",
            "source": source_name,
            "source_sha256": source_sha256,
            "source_verdict": ray.get("status"),
            "review_points": len(collections),
            "source_findings": len(queue),
            "limitation": LIMITATION,
        },
        "vc_pointcollections_json_version": POINTCOLLECTIONS_VERSION,
        "collections": collections,
    }


def export_file(
    source: str | Path,
    output: str | Path,
    *,
    scroll: str,
    kind: str = KIND,
) -> dict[str, Any]:
    if kind not in KINDS:
        raise ReviewExportError(f"unknown kind {kind!r}; expected one of {KINDS}")
    src = Path(source)
    out = Path(output)
    if out.exists():
        raise ReviewExportError(f"refusing to overwrite existing output: {out}")
    try:
        raw = src.read_bytes()
        document = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReviewExportError(f"cannot read source: {exc}") from exc

    builder = (
        build_ray_order_bundle if kind == RAY_ORDER_KIND
        else build_winding_attachment_bundle
    )
    bundle = builder(
        document,
        source_name=src.name,
        source_sha256=_sha256(raw),
        scroll=scroll,
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(_json_bytes(bundle))
    return bundle


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog=TOOL,
        description=(
            "Export a ScrolIQ winding review queue (attachment or ray order) "
            "as a native "
            "VC3D PointCollections v1 JSON file."
        ),
    )
    parser.add_argument(
        "--input", required=True,
        help="winding-attachment result.json or winding-audit JSON",
    )
    parser.add_argument(
        "--kind", choices=KINDS, default=KIND,
        help="review queue type (default: %(default)s)",
    )
    parser.add_argument("--scroll", required=True, help="scroll id, e.g. PHercParis4")
    parser.add_argument("--out", required=True, help="new PointCollections JSON path")
    args = parser.parse_args(argv)

    try:
        bundle = export_file(
            args.input, args.out, scroll=args.scroll, kind=args.kind
        )
    except ReviewExportError as exc:
        print(f"{TOOL}: FAIL: {exc}", file=sys.stderr)
        return 2

    meta = bundle["scroliq_review_bundle"]
    print(
        f"{TOOL}: PASS: {meta['review_points']} VC3D review point(s) "
        f"from {meta['source_findings']} finding(s)"
    )
    print(f"source sha256: {meta['source_sha256']}")
    print(f"output: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
