"""Ingest human VC3D review decisions into a deterministic provenance ledger."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from .vc3d_review_export import build_winding_attachment_bundle

TOOL = "scroliq-vc3d-review-ingest"
SCHEMA_VERSION = 1
POINTCOLLECTIONS_VERSION = "1"
REVIEW_TAG_STATUS = "scroliq_review_status"
REVIEW_TAG_NOTE = "scroliq_review_note"
REVIEW_STATUSES = {
    "annotation_corrected",
    "patch_issue",
    "no_issue",
    "uncertain",
}
LIMITATION = (
    "The ledger records reviewer decisions and verified file provenance. "
    "A human classification is not by itself proof of CT support or downstream improvement."
)


class ReviewIngestError(ValueError):
    """The reviewed VC3D bundle cannot be trusted or ingested safely."""


def _json_bytes(value: Any) -> bytes:
    try:
        text = json.dumps(
            value,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ReviewIngestError(f"cannot serialize ledger: {exc}") from exc
    return (text + "\n").encode("utf-8")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _integer(value: Any, *, label: str) -> int:
    if not _finite_number(value) or not float(value).is_integer():
        raise ReviewIngestError(f"{label} must be a finite integer")
    return int(value)


def _integer_text(value: Any, *, label: str) -> int:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ReviewIngestError(f"{label} must be an integer string")
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ReviewIngestError(f"{label} must be an integer string") from exc
    if str(parsed) != value:
        raise ReviewIngestError(f"{label} must use canonical integer text")
    return parsed


def _f32(value: Any, *, label: str) -> float:
    if not _finite_number(value):
        raise ReviewIngestError(f"{label} must be finite")
    return struct.unpack("!f", struct.pack("!f", float(value)))[0]


def _validate_reviewed_at(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReviewIngestError("reviewed_at must be non-empty")
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ReviewIngestError("reviewed_at must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ReviewIngestError("reviewed_at must include a timezone")
    return parsed.isoformat()


def _one_point(collection: Any, *, label: str) -> tuple[str, dict[str, Any]]:
    if not isinstance(collection, dict):
        raise ReviewIngestError(f"{label} must be an object")
    points = collection.get("points")
    if not isinstance(points, dict) or len(points) != 1:
        raise ReviewIngestError(f"{label}.points must contain exactly one point")
    point_id, point = next(iter(points.items()))
    if not isinstance(point, dict):
        raise ReviewIngestError(f"{label}.points[{point_id!r}] must be an object")
    return str(point_id), point


def _position(point: dict[str, Any], *, label: str) -> list[float]:
    raw = point.get("p")
    if (
        not isinstance(raw, list)
        or len(raw) != 3
        or not all(_finite_number(v) for v in raw)
    ):
        raise ReviewIngestError(f"{label}.p must contain three finite numbers")
    return [float(v) for v in raw]


def _validate_vc3d_roundtrip_position(
    original: list[float], reviewed: list[float], *, label: str
) -> None:
    for axis, (before, after) in enumerate(zip(original, reviewed)):
        if _f32(before, label=label) != _f32(after, label=label):
            raise ReviewIngestError(
                f"{label}.p[{axis}] moved during review; review markers are immutable"
            )


def _validate_digest(value: Any, *, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise ReviewIngestError(f"{label} must be lowercase 64-hex")
    return value


def _validated_meta(bundle: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(bundle, dict):
        raise ReviewIngestError(f"{label} must be a JSON object")
    if bundle.get("vc_pointcollections_json_version") != POINTCOLLECTIONS_VERSION:
        raise ReviewIngestError(
            f"{label}.vc_pointcollections_json_version must be "
            f"{POINTCOLLECTIONS_VERSION!r}"
        )
    meta = bundle.get("scroliq_review_bundle")
    if not isinstance(meta, dict):
        raise ReviewIngestError(f"{label}.scroliq_review_bundle must be an object")
    if meta.get("schema_version") != 1:
        raise ReviewIngestError(f"{label} has unsupported review bundle schema")
    if meta.get("kind") != "winding-attachment":
        raise ReviewIngestError(f"{label} has unsupported review kind")
    _validate_digest(meta.get("source_sha256"), label=f"{label}.source_sha256")
    scroll = meta.get("scroll")
    source = meta.get("source")
    if not isinstance(scroll, str) or not scroll:
        raise ReviewIngestError(f"{label}.scroll must be non-empty")
    if not isinstance(source, str) or not source:
        raise ReviewIngestError(f"{label}.source must be non-empty")
    return meta


def build_review_ledger(
    original_bundle: Any,
    reviewed_bundle: Any,
    diagnostic_result: Any,
    *,
    diagnostic_sha256: str,
    original_bundle_sha256: str,
    reviewed_bundle_sha256: str,
    reviewer: str,
    reviewed_at: str,
    review_minutes: int,
) -> dict[str, Any]:
    """Validate a VC3D-reviewed bundle and produce a deterministic review ledger."""
    diagnostic_sha256 = _validate_digest(
        diagnostic_sha256, label="diagnostic_sha256"
    )
    original_bundle_sha256 = _validate_digest(
        original_bundle_sha256, label="original_bundle_sha256"
    )
    reviewed_bundle_sha256 = _validate_digest(
        reviewed_bundle_sha256, label="reviewed_bundle_sha256"
    )
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise ReviewIngestError("reviewer must be non-empty")
    reviewer = reviewer.strip()
    if (
        not isinstance(review_minutes, int)
        or isinstance(review_minutes, bool)
        or not 1 <= review_minutes <= 480
    ):
        raise ReviewIngestError("review_minutes must be an integer from 1 to 480")
    reviewed_at = _validate_reviewed_at(reviewed_at)

    original_meta = _validated_meta(original_bundle, label="original bundle")
    reviewed_meta = _validated_meta(reviewed_bundle, label="reviewed bundle")
    if reviewed_meta != original_meta:
        raise ReviewIngestError("reviewed bundle metadata changed from the original")
    if original_meta["source_sha256"] != diagnostic_sha256:
        raise ReviewIngestError(
            "diagnostic result SHA-256 does not match the review bundle"
        )
    if not isinstance(diagnostic_result, dict):
        raise ReviewIngestError("diagnostic result must be a JSON object")

    expected_original = build_winding_attachment_bundle(
        diagnostic_result,
        source_name=original_meta["source"],
        source_sha256=diagnostic_sha256,
        scroll=original_meta["scroll"],
    )
    if original_bundle != expected_original:
        raise ReviewIngestError(
            "original review bundle is not the deterministic export of the "
            "supplied diagnostic result"
        )

    inputs = diagnostic_result.get("inputs")
    hashes = inputs.get("sha256") if isinstance(inputs, dict) else None
    if not isinstance(hashes, dict):
        raise ReviewIngestError("diagnostic result is missing inputs.sha256")
    upstream_hashes: dict[str, str] = {}
    for name, digest in hashes.items():
        if not isinstance(name, str) or not name:
            raise ReviewIngestError("diagnostic input hash names must be non-empty")
        upstream_hashes[name] = _validate_digest(
            digest, label=f"inputs.sha256[{name!r}]"
        )

    original_collections = original_bundle.get("collections")
    reviewed_collections = reviewed_bundle.get("collections")
    if not isinstance(original_collections, dict) or not original_collections:
        raise ReviewIngestError("original bundle collections must be non-empty")
    if not isinstance(reviewed_collections, dict):
        raise ReviewIngestError("reviewed bundle collections must be an object")
    if set(reviewed_collections) != set(original_collections):
        raise ReviewIngestError("reviewed bundle changed the collection set")

    decisions: list[dict[str, Any]] = []
    counts = {status: 0 for status in sorted(REVIEW_STATUSES)}

    def collection_sort_key(value: str) -> tuple[int, str]:
        try:
            return (int(value), "")
        except (TypeError, ValueError):
            return (2**63 - 1, str(value))

    for collection_id in sorted(original_collections, key=collection_sort_key):
        before = original_collections[collection_id]
        after = reviewed_collections[collection_id]
        label = f"collections[{collection_id!r}]"
        if not isinstance(before, dict) or not isinstance(after, dict):
            raise ReviewIngestError(f"{label} must remain an object")

        before_tags = before.get("tags")
        after_tags = after.get("tags")
        if not isinstance(before_tags, dict) or not isinstance(after_tags, dict):
            raise ReviewIngestError(f"{label}.tags must remain an object")
        for key, value in before_tags.items():
            if after_tags.get(key) != value:
                raise ReviewIngestError(
                    f"{label}.tags[{key!r}] changed during review"
                )
        extra_tags = set(after_tags) - set(before_tags)
        allowed_extra = {REVIEW_TAG_STATUS, REVIEW_TAG_NOTE}
        unexpected = extra_tags - allowed_extra
        if unexpected:
            raise ReviewIngestError(
                f"{label} has unexpected added tags: {sorted(unexpected)}"
            )

        status = after_tags.get(REVIEW_TAG_STATUS)
        note = after_tags.get(REVIEW_TAG_NOTE)
        if status not in REVIEW_STATUSES:
            raise ReviewIngestError(
                f"{label}.{REVIEW_TAG_STATUS} must be one of "
                f"{sorted(REVIEW_STATUSES)}"
            )
        if not isinstance(note, str) or not note.strip():
            raise ReviewIngestError(
                f"{label}.{REVIEW_TAG_NOTE} must be a non-empty review note"
            )
        note = note.strip()

        for field in ("metadata", "name"):
            if after.get(field) != before.get(field):
                raise ReviewIngestError(f"{label}.{field} changed during review")

        before_point_id, before_point = _one_point(before, label=f"original {label}")
        after_point_id, after_point = _one_point(after, label=f"reviewed {label}")
        if after_point_id != before_point_id:
            raise ReviewIngestError(f"{label} changed its point id")
        before_position = _position(before_point, label=f"original {label}")
        after_position = _position(after_point, label=f"reviewed {label}")
        _validate_vc3d_roundtrip_position(
            before_position, after_position, label=label
        )

        before_winding = _integer(
            before_point.get("wind_a"), label=f"original {label}.wind_a"
        )
        after_winding = _integer(
            after_point.get("wind_a"), label=f"reviewed {label}.wind_a"
        )
        source_winding = _integer_text(
            before_tags.get("source_winding"),
            label=f"{label}.tags.source_winding",
        )
        if before_winding != source_winding:
            raise ReviewIngestError(
                f"{label} original winding disagrees with source_winding tag"
            )

        if status == "annotation_corrected":
            if after_winding == before_winding:
                raise ReviewIngestError(
                    f"{label} is annotation_corrected but wind_a did not change"
                )
        elif after_winding != before_winding:
            raise ReviewIngestError(
                f"{label} changed wind_a without annotation_corrected status"
            )

        findings_raw = before_tags.get("findings_json")
        try:
            findings = json.loads(findings_raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ReviewIngestError(f"{label}.findings_json is invalid") from exc
        if not isinstance(findings, list) or not findings:
            raise ReviewIngestError(f"{label}.findings_json must be a non-empty list")

        frame = before_tags.get("frame")
        source_point_id = before_tags.get("source_point_id")
        if not isinstance(frame, str) or not frame:
            raise ReviewIngestError(f"{label}.tags.frame must be non-empty")
        if not isinstance(source_point_id, str) or not source_point_id:
            raise ReviewIngestError(
                f"{label}.tags.source_point_id must be non-empty"
            )

        decisions.append(
            {
                "collection_id": str(collection_id),
                "vc3d_point_id": before_point_id,
                "frame": frame,
                "source_point_id": source_point_id,
                "xyz": before_position,
                "original_winding": before_winding,
                "reviewed_winding": after_winding,
                "status": status,
                "note": note,
                "findings": findings,
            }
        )
        counts[status] += 1

    return {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "kind": "winding-attachment-review-ledger",
        "scroll": original_meta["scroll"],
        "diagnostic_source": original_meta["source"],
        "diagnostic_source_sha256": diagnostic_sha256,
        "source_verdict": original_meta.get("source_verdict"),
        "original_bundle_sha256": original_bundle_sha256,
        "reviewed_bundle_sha256": reviewed_bundle_sha256,
        "upstream_inputs_sha256": dict(sorted(upstream_hashes.items())),
        "human_review": {
            "reviewer": reviewer,
            "reviewed_at": reviewed_at,
            "minutes": review_minutes,
        },
        "summary": {
            "review_points": len(decisions),
            "annotation_corrections": counts["annotation_corrected"],
            "patch_issues": counts["patch_issue"],
            "no_issue": counts["no_issue"],
            "uncertain": counts["uncertain"],
        },
        "decisions": decisions,
        "limitation": LIMITATION,
    }


def _read_json(path: Path, *, label: str) -> tuple[bytes, Any]:
    try:
        raw = path.read_bytes()
        return raw, json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReviewIngestError(f"cannot read {label}: {exc}") from exc


def ingest_files(
    original_bundle: str | Path,
    reviewed_bundle: str | Path,
    diagnostic_result: str | Path,
    output: str | Path,
    *,
    reviewer: str,
    reviewed_at: str,
    review_minutes: int,
) -> dict[str, Any]:
    original_path = Path(original_bundle)
    reviewed_path = Path(reviewed_bundle)
    diagnostic_path = Path(diagnostic_result)
    out = Path(output)
    if out.exists():
        raise ReviewIngestError(f"refusing to overwrite existing output: {out}")

    original_raw, original_doc = _read_json(
        original_path, label="original review bundle"
    )
    reviewed_raw, reviewed_doc = _read_json(
        reviewed_path, label="reviewed VC3D bundle"
    )
    diagnostic_raw, diagnostic_doc = _read_json(
        diagnostic_path, label="diagnostic result"
    )

    ledger = build_review_ledger(
        original_doc,
        reviewed_doc,
        diagnostic_doc,
        diagnostic_sha256=_sha256(diagnostic_raw),
        original_bundle_sha256=_sha256(original_raw),
        reviewed_bundle_sha256=_sha256(reviewed_raw),
        reviewer=reviewer,
        reviewed_at=reviewed_at,
        review_minutes=review_minutes,
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(_json_bytes(ledger))
    return ledger


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog=TOOL,
        description=(
            "Verify a human-reviewed VC3D PointCollections file and emit a "
            "hash-bound review/correction ledger."
        ),
    )
    parser.add_argument("--original", required=True, help="original ScrolIQ VC3D review bundle")
    parser.add_argument("--reviewed", required=True, help="VC3D-saved reviewed bundle")
    parser.add_argument(
        "--diagnostic-result",
        required=True,
        help="exact source diagnostic result.json used to create the original bundle",
    )
    parser.add_argument("--reviewer", required=True, help="reviewer name or stable identifier")
    parser.add_argument(
        "--reviewed-at",
        required=True,
        help="timezone-aware ISO-8601 review completion time",
    )
    parser.add_argument(
        "--review-minutes",
        required=True,
        type=int,
        help="documented human review minutes for this session (1..480)",
    )
    parser.add_argument("--out", required=True, help="new deterministic review ledger path")
    args = parser.parse_args(argv)

    try:
        ledger = ingest_files(
            args.original,
            args.reviewed,
            args.diagnostic_result,
            args.out,
            reviewer=args.reviewer,
            reviewed_at=args.reviewed_at,
            review_minutes=args.review_minutes,
        )
    except ReviewIngestError as exc:
        print(f"{TOOL}: FAIL: {exc}", file=sys.stderr)
        return 2

    summary = ledger["summary"]
    print(
        f"{TOOL}: PASS: {summary['review_points']} reviewed point(s); "
        f"{summary['annotation_corrections']} annotation correction(s), "
        f"{summary['patch_issues']} patch issue(s), "
        f"{summary['no_issue']} no-issue, {summary['uncertain']} uncertain"
    )
    print(f"reviewed bundle sha256: {ledger['reviewed_bundle_sha256']}")
    print(f"output: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
