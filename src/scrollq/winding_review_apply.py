"""Apply confirmed VC3D winding-review corrections to a hash-matched source file."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

TOOL = "scroliq-winding-apply-review"
SCHEMA_VERSION = 1
POINTCOLLECTIONS_VERSION = "1"
LEDGER_TOOL = "scroliq-vc3d-review-ingest"
LEDGER_KIND = "winding-attachment-review-ledger"
SOURCE_HASH_KEY = "relative_windings.json"
CORRECTION_STATUS = "annotation_corrected"

LIMITATION = (
    "This tool applies reviewer-confirmed winding-number edits only. "
    "The corrected file is a hypothesis to re-evaluate, not proof that the "
    "annotation or downstream geometry is correct."
)


class ReviewApplyError(ValueError):
    """A review ledger cannot be safely applied to its claimed source."""


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


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
        raise ReviewApplyError(f"cannot serialize output: {exc}") from exc
    return (text + "\n").encode("utf-8")


def _digest(value: Any, *, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise ReviewApplyError(f"{label} must be lowercase 64-hex")
    return value


def _finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _integer(value: Any, *, label: str) -> int:
    if not _finite_number(value) or not float(value).is_integer():
        raise ReviewApplyError(f"{label} must be a finite integer")
    return int(value)


def _xyz(value: Any, *, label: str) -> list[float]:
    if (
        not isinstance(value, list)
        or len(value) != 3
        or not all(_finite_number(item) for item in value)
    ):
        raise ReviewApplyError(f"{label} must contain exactly three finite numbers")
    return [float(item) for item in value]


def _validate_source(document: Any) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise ReviewApplyError("source PointCollections must be a JSON object")
    if document.get("vc_pointcollections_json_version") != POINTCOLLECTIONS_VERSION:
        raise ReviewApplyError(
            "source must be VC3D PointCollections JSON version "
            f"{POINTCOLLECTIONS_VERSION!r}"
        )
    collections = document.get("collections")
    if not isinstance(collections, dict):
        raise ReviewApplyError("source collections must be an object")
    return collections


def _validate_ledger(
    ledger: Any,
    *,
    source_sha256: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not isinstance(ledger, dict):
        raise ReviewApplyError("review ledger must be a JSON object")
    if ledger.get("schema_version") != 1:
        raise ReviewApplyError("unsupported review ledger schema_version")
    if ledger.get("tool") != LEDGER_TOOL or ledger.get("kind") != LEDGER_KIND:
        raise ReviewApplyError("input is not a ScrolIQ winding review ledger")

    scroll = ledger.get("scroll")
    if not isinstance(scroll, str) or not scroll:
        raise ReviewApplyError("review ledger scroll must be non-empty")
    _digest(
        ledger.get("diagnostic_source_sha256"),
        label="ledger.diagnostic_source_sha256",
    )
    _digest(
        ledger.get("original_bundle_sha256"),
        label="ledger.original_bundle_sha256",
    )
    _digest(
        ledger.get("reviewed_bundle_sha256"),
        label="ledger.reviewed_bundle_sha256",
    )

    upstream = ledger.get("upstream_inputs_sha256")
    if not isinstance(upstream, dict):
        raise ReviewApplyError("review ledger is missing upstream_inputs_sha256")
    expected_source_sha = _digest(
        upstream.get(SOURCE_HASH_KEY),
        label=f"ledger.upstream_inputs_sha256[{SOURCE_HASH_KEY!r}]",
    )
    if expected_source_sha != source_sha256:
        raise ReviewApplyError(
            "source SHA-256 does not match the relative_windings.json reviewed "
            "by the diagnostic"
        )

    human_review = ledger.get("human_review")
    if not isinstance(human_review, dict):
        raise ReviewApplyError("review ledger is missing human_review")
    if not isinstance(human_review.get("reviewer"), str) or not human_review["reviewer"]:
        raise ReviewApplyError("review ledger reviewer must be non-empty")
    if not isinstance(human_review.get("reviewed_at"), str) or not human_review["reviewed_at"]:
        raise ReviewApplyError("review ledger reviewed_at must be non-empty")
    if (
        not isinstance(human_review.get("minutes"), int)
        or isinstance(human_review.get("minutes"), bool)
        or human_review["minutes"] <= 0
    ):
        raise ReviewApplyError("review ledger human-review minutes must be positive")

    decisions = ledger.get("decisions")
    if not isinstance(decisions, list) or not decisions:
        raise ReviewApplyError("review ledger decisions must be a non-empty list")

    status_counts = {
        "annotation_corrected": 0,
        "patch_issue": 0,
        "no_issue": 0,
        "uncertain": 0,
    }
    for index, decision in enumerate(decisions):
        if not isinstance(decision, dict):
            raise ReviewApplyError(f"decisions[{index}] must be an object")
        status = decision.get("status")
        if status not in status_counts:
            raise ReviewApplyError(
                f"decisions[{index}].status is unsupported: {status!r}"
            )
        status_counts[status] += 1

    summary = ledger.get("summary")
    expected_summary = {
        "review_points": len(decisions),
        "annotation_corrections": status_counts["annotation_corrected"],
        "patch_issues": status_counts["patch_issue"],
        "no_issue": status_counts["no_issue"],
        "uncertain": status_counts["uncertain"],
    }
    if summary != expected_summary:
        raise ReviewApplyError("review ledger summary does not match its decisions")
    if status_counts[CORRECTION_STATUS] == 0:
        raise ReviewApplyError("review ledger contains no annotation corrections")

    return decisions, human_review


def apply_review_ledger(
    source_document: Any,
    ledger: Any,
    *,
    source_sha256: str,
    ledger_sha256: str,
    source_name: str,
    ledger_name: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Apply relative-winding corrections and return corrected JSON + manifest."""
    source_sha256 = _digest(source_sha256, label="source_sha256")
    ledger_sha256 = _digest(ledger_sha256, label="ledger_sha256")
    if not isinstance(source_name, str) or not source_name:
        raise ReviewApplyError("source_name must be non-empty")
    if not isinstance(ledger_name, str) or not ledger_name:
        raise ReviewApplyError("ledger_name must be non-empty")

    collections = _validate_source(source_document)
    decisions, human_review = _validate_ledger(
        ledger,
        source_sha256=source_sha256,
    )

    corrected = copy.deepcopy(source_document)
    corrected_collections = corrected["collections"]
    changes: list[dict[str, Any]] = []
    seen_targets: set[tuple[str, str]] = set()

    corrections = [
        (index, decision)
        for index, decision in enumerate(decisions)
        if decision.get("status") == CORRECTION_STATUS
    ]
    corrections.sort(
        key=lambda item: (
            str(item[1].get("frame")),
            str(item[1].get("source_point_id")),
            item[0],
        )
    )

    for index, decision in corrections:
        frame = decision.get("frame")
        if not isinstance(frame, str) or not frame.startswith("relative:"):
            raise ReviewApplyError(
                f"decisions[{index}] is an annotation correction outside a "
                "relative winding frame"
            )
        collection_id = frame[len("relative:") :]
        if not collection_id:
            raise ReviewApplyError(f"decisions[{index}].frame has no collection id")

        point_id = decision.get("source_point_id")
        if not isinstance(point_id, str) or not point_id:
            raise ReviewApplyError(
                f"decisions[{index}].source_point_id must be non-empty"
            )

        target = (collection_id, point_id)
        if target in seen_targets:
            raise ReviewApplyError(
                f"multiple correction decisions target {frame}/{point_id}"
            )
        seen_targets.add(target)

        collection = corrected_collections.get(collection_id)
        if not isinstance(collection, dict):
            raise ReviewApplyError(
                f"source collection {collection_id!r} from {frame!r} is missing"
            )
        points = collection.get("points")
        if not isinstance(points, dict):
            raise ReviewApplyError(
                f"source collection {collection_id!r}.points must be an object"
            )
        point = points.get(point_id)
        if not isinstance(point, dict):
            raise ReviewApplyError(
                f"source point {frame}/{point_id} is missing"
            )

        before = _integer(
            point.get("wind_a"),
            label=f"source {frame}/{point_id}.wind_a",
        )
        expected_before = _integer(
            decision.get("original_winding"),
            label=f"decisions[{index}].original_winding",
        )
        after = _integer(
            decision.get("reviewed_winding"),
            label=f"decisions[{index}].reviewed_winding",
        )
        if before != expected_before:
            raise ReviewApplyError(
                f"source {frame}/{point_id} winding is {before}, but the review "
                f"ledger expects {expected_before}"
            )
        if after == before:
            raise ReviewApplyError(
                f"decisions[{index}] correction does not change the winding"
            )

        source_xyz = _xyz(
            point.get("p"),
            label=f"source {frame}/{point_id}.p",
        )
        reviewed_xyz = _xyz(
            decision.get("xyz"),
            label=f"decisions[{index}].xyz",
        )
        if source_xyz != reviewed_xyz:
            raise ReviewApplyError(
                f"source {frame}/{point_id} coordinates do not match the reviewed point"
            )

        note = decision.get("note")
        if not isinstance(note, str) or not note.strip():
            raise ReviewApplyError(
                f"decisions[{index}].note must be non-empty"
            )

        point["wind_a"] = after
        changes.append(
            {
                "frame": frame,
                "collection_id": collection_id,
                "point_id": point_id,
                "xyz": source_xyz,
                "before_winding": before,
                "after_winding": after,
                "review_note": note.strip(),
            }
        )

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "kind": "winding-review-application",
        "scroll": ledger["scroll"],
        "source": source_name,
        "source_sha256": source_sha256,
        "ledger": ledger_name,
        "ledger_sha256": ledger_sha256,
        "diagnostic_source_sha256": ledger["diagnostic_source_sha256"],
        "reviewed_bundle_sha256": ledger["reviewed_bundle_sha256"],
        "human_review": copy.deepcopy(human_review),
        "review_points": len(decisions),
        "corrections_applied": len(changes),
        "changes": changes,
        "limitation": LIMITATION,
    }
    return corrected, manifest


def _read_json(path: Path, *, label: str) -> tuple[bytes, Any]:
    try:
        raw = path.read_bytes()
        return raw, json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReviewApplyError(f"cannot read {label}: {exc}") from exc


def apply_files(
    source: str | Path,
    ledger: str | Path,
    output: str | Path,
    manifest_output: str | Path,
) -> dict[str, Any]:
    source_path = Path(source)
    ledger_path = Path(ledger)
    out = Path(output)
    manifest_path = Path(manifest_output)

    if out == source_path:
        raise ReviewApplyError("refusing to overwrite the source winding file")
    if out == manifest_path:
        raise ReviewApplyError("corrected output and manifest must be different paths")
    for path in (out, manifest_path):
        if path.exists():
            raise ReviewApplyError(f"refusing to overwrite existing output: {path}")

    source_raw, source_document = _read_json(source_path, label="source winding file")
    ledger_raw, ledger_document = _read_json(ledger_path, label="review ledger")

    corrected, manifest = apply_review_ledger(
        source_document,
        ledger_document,
        source_sha256=_sha256(source_raw),
        ledger_sha256=_sha256(ledger_raw),
        source_name=source_path.name,
        ledger_name=ledger_path.name,
    )
    corrected_raw = _json_bytes(corrected)
    manifest["corrected_output"] = out.name
    manifest["corrected_sha256"] = _sha256(corrected_raw)
    manifest_raw = _json_bytes(manifest)

    out.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(corrected_raw)
    manifest_path.write_bytes(manifest_raw)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog=TOOL,
        description=(
            "Apply annotation_corrected decisions from a ScrolIQ VC3D review "
            "ledger to the exact hash-matched relative_windings.json source."
        ),
    )
    parser.add_argument(
        "--source",
        required=True,
        help="exact relative_windings.json reviewed by the diagnostic",
    )
    parser.add_argument(
        "--ledger",
        required=True,
        help="review ledger from scroliq-vc3d-review-ingest",
    )
    parser.add_argument(
        "--out",
        required=True,
        help="new corrected PointCollections JSON path; source is never overwritten",
    )
    parser.add_argument(
        "--manifest-out",
        required=True,
        help="new correction-application manifest path",
    )
    args = parser.parse_args(argv)

    try:
        manifest = apply_files(
            args.source,
            args.ledger,
            args.out,
            args.manifest_out,
        )
    except ReviewApplyError as exc:
        print(f"{TOOL}: FAIL: {exc}", file=sys.stderr)
        return 2

    print(
        f"{TOOL}: PASS: applied {manifest['corrections_applied']} "
        f"confirmed correction(s) from {manifest['review_points']} reviewed point(s)"
    )
    print(f"source sha256: {manifest['source_sha256']}")
    print(f"corrected sha256: {manifest['corrected_sha256']}")
    print(f"corrected output: {args.out}")
    print(f"manifest: {args.manifest_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
