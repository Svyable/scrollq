"""Audit VC3D/spiral-fitting winding point-collection inputs.

This is a deliberately shallow, dependency-free diagnostic. It checks the
PointCollections v1 document shape, role semantics, coordinates, winding values,
and file provenance. It does not claim that annotations are geometrically
correct; geometry-aware consistency and held-out fit evaluation are separate
future diagnostics.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = 1
POINTCOLLECTIONS_VERSION = "1"
OPEN_PROBLEM_URL = "https://scrollprize.org/open_problems/winding_annotations"

ROLE_FILES = {
    "absolute": "abs_winding.json",
    "relative": "relative_windings.json",
    "same_winding": "same_windings.json",
}


def _finding(
    findings: list[dict[str, str]],
    severity: str,
    code: str,
    path: str,
    message: str,
) -> None:
    findings.append(
        {"severity": severity, "code": code, "path": path, "message": message}
    )


def _is_finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _is_integer_number(value: Any) -> bool:
    return _is_finite_number(value) and float(value).is_integer()


def _id_as_int(value: Any) -> int | None:
    try:
        if isinstance(value, bool):
            return None
        return int(str(value))
    except (TypeError, ValueError):
        return None


def audit_document(
    document: Any,
    *,
    role: str,
    source: str | None = None,
    sha256: str | None = None,
) -> dict[str, Any]:
    """Validate one PointCollections v1 document for a conventional spiral role."""
    if role not in ROLE_FILES:
        raise ValueError(f"unsupported winding role: {role!r}")

    findings: list[dict[str, str]] = []
    collections_report: list[dict[str, Any]] = []
    all_coords: list[list[float]] = []
    total_points = 0
    annotated_points = 0

    if not isinstance(document, dict):
        _finding(
            findings,
            "error",
            "WINDING_DOCUMENT_TYPE",
            "$",
            "PointCollections document must be a JSON object",
        )
        collections: dict[str, Any] = {}
    else:
        if document.get("vc_pointcollections_json_version") != POINTCOLLECTIONS_VERSION:
            _finding(
                findings,
                "error",
                "WINDING_JSON_VERSION",
                "vc_pointcollections_json_version",
                f"expected PointCollections version {POINTCOLLECTIONS_VERSION!r}",
            )
        raw_collections = document.get("collections")
        if not isinstance(raw_collections, dict):
            _finding(
                findings,
                "error",
                "WINDING_COLLECTIONS_TYPE",
                "collections",
                "collections must be an object keyed by collection id",
            )
            collections = {}
        else:
            collections = raw_collections

    seen_collection_ids: dict[int, str] = {}
    for collection_key, collection in collections.items():
        cpath = f"collections[{collection_key!r}]"
        collection_id = _id_as_int(collection_key)
        if collection_id is None:
            _finding(
                findings,
                "error",
                "WINDING_COLLECTION_ID",
                cpath,
                "collection id must be integer-like",
            )
        elif collection_id in seen_collection_ids:
            _finding(
                findings,
                "error",
                "WINDING_COLLECTION_ID_COLLISION",
                cpath,
                f"normalizes to the same integer id as {seen_collection_ids[collection_id]!r}",
            )
        else:
            seen_collection_ids[collection_id] = str(collection_key)

        if not isinstance(collection, dict):
            _finding(
                findings,
                "error",
                "WINDING_COLLECTION_TYPE",
                cpath,
                "collection must be an object",
            )
            continue

        name = collection.get("name")
        if not isinstance(name, str) or not name.strip():
            _finding(
                findings,
                "error",
                "WINDING_COLLECTION_NAME",
                f"{cpath}.name",
                "collection name must be a non-empty string",
            )

        metadata = collection.get("metadata", {})
        if not isinstance(metadata, dict):
            _finding(
                findings,
                "error",
                "WINDING_METADATA_TYPE",
                f"{cpath}.metadata",
                "metadata must be an object when present",
            )
            metadata = {}
        absolute_flag = metadata.get("winding_is_absolute")
        if absolute_flag is not None and not isinstance(absolute_flag, bool):
            _finding(
                findings,
                "warning",
                "WINDING_ABSOLUTE_FLAG_TYPE",
                f"{cpath}.metadata.winding_is_absolute",
                "winding_is_absolute should be boolean when present",
            )
        elif role == "absolute" and absolute_flag is False:
            _finding(
                findings,
                "warning",
                "WINDING_ROLE_METADATA_MISMATCH",
                f"{cpath}.metadata.winding_is_absolute",
                "file role is absolute but metadata declares false; explicit fitter role overrides this",
            )
        elif role != "absolute" and absolute_flag is True:
            _finding(
                findings,
                "warning",
                "WINDING_ROLE_METADATA_MISMATCH",
                f"{cpath}.metadata.winding_is_absolute",
                f"file role is {role} but metadata declares an absolute-winding collection",
            )

        raw_points = collection.get("points")
        if not isinstance(raw_points, dict):
            _finding(
                findings,
                "error",
                "WINDING_POINTS_TYPE",
                f"{cpath}.points",
                "points must be an object keyed by point id",
            )
            raw_points = {}

        if not raw_points:
            _finding(
                findings,
                "warning",
                "WINDING_EMPTY_COLLECTION",
                f"{cpath}.points",
                "collection contains no points",
            )

        winding_values: list[int] = []
        point_rows: list[tuple[int, int | None]] = []
        seen_point_ids: dict[int, str] = {}

        for point_key, point in raw_points.items():
            ppath = f"{cpath}.points[{point_key!r}]"
            point_id = _id_as_int(point_key)
            if point_id is None:
                _finding(
                    findings,
                    "error",
                    "WINDING_POINT_ID",
                    ppath,
                    "point id must be integer-like",
                )
            elif point_id in seen_point_ids:
                _finding(
                    findings,
                    "error",
                    "WINDING_POINT_ID_COLLISION",
                    ppath,
                    f"normalizes to the same integer id as {seen_point_ids[point_id]!r}",
                )
            else:
                seen_point_ids[point_id] = str(point_key)

            if not isinstance(point, dict):
                _finding(
                    findings,
                    "error",
                    "WINDING_POINT_TYPE",
                    ppath,
                    "point must be an object",
                )
                continue

            coords = point.get("p")
            if (
                not isinstance(coords, list)
                or len(coords) != 3
                or not all(_is_finite_number(value) for value in coords)
            ):
                _finding(
                    findings,
                    "error",
                    "WINDING_POINT_COORDINATES",
                    f"{ppath}.p",
                    "p must contain exactly three finite numeric coordinates",
                )
            else:
                all_coords.append([float(value) for value in coords])

            has_wind = "wind_a" in point and point.get("wind_a") is not None
            wind_value: int | None = None
            if role == "same_winding":
                if has_wind:
                    _finding(
                        findings,
                        "error",
                        "WINDING_SAME_HAS_WIND_A",
                        f"{ppath}.wind_a",
                        "same-winding points must not carry wind_a",
                    )
            else:
                if not has_wind:
                    _finding(
                        findings,
                        "error",
                        "WINDING_MISSING_WIND_A",
                        f"{ppath}.wind_a",
                        f"{role}-winding points require an integer wind_a",
                    )
                elif not _is_integer_number(point.get("wind_a")):
                    _finding(
                        findings,
                        "error",
                        "WINDING_INVALID_WIND_A",
                        f"{ppath}.wind_a",
                        "wind_a must be a finite integer",
                    )
                else:
                    wind_value = int(point["wind_a"])
                    winding_values.append(wind_value)
                    annotated_points += 1

            if point_id is not None:
                point_rows.append((point_id, wind_value))
            total_points += 1

        role_stats: dict[str, Any] = {}
        if role in {"absolute", "relative"} and winding_values:
            unique = sorted(set(winding_values))
            role_stats.update(
                {
                    "winding_min": min(unique),
                    "winding_max": max(unique),
                    "winding_span": max(unique) - min(unique),
                    "unique_winding_values": len(unique),
                }
            )
        if role == "relative":
            if len(raw_points) < 2:
                _finding(
                    findings,
                    "warning",
                    "WINDING_RELATIVE_TOO_SHORT",
                    cpath,
                    "relative-winding collection needs at least two points to encode a relation",
                )
            ordered = [
                value
                for _, value in sorted(point_rows, key=lambda item: item[0])
                if value is not None
            ]
            deltas = [b - a for a, b in zip(ordered, ordered[1:])]
            role_stats["ordered_edges"] = max(len(ordered) - 1, 0)
            role_stats["nonzero_ordered_winding_steps"] = sum(
                delta != 0 for delta in deltas
            )
            if len(raw_points) >= 2 and winding_values and len(set(winding_values)) == 1:
                _finding(
                    findings,
                    "warning",
                    "WINDING_RELATIVE_ZERO_SPAN",
                    cpath,
                    "all relative wind_a values are equal, so this collection encodes no winding separation",
                )

        collections_report.append(
            {
                "id": collection_id,
                "source_id": str(collection_key),
                "name": name if isinstance(name, str) else None,
                "points": len(raw_points),
                "annotated_points": len(winding_values),
                "role_stats": role_stats,
            }
        )

    errors = [item for item in findings if item["severity"] == "error"]
    warnings = [item for item in findings if item["severity"] == "warning"]
    status = "fail" if errors else "warn" if warnings else "pass"

    raw_bounds = None
    if all_coords:
        raw_bounds = {
            "min": [min(point[i] for point in all_coords) for i in range(3)],
            "max": [max(point[i] for point in all_coords) for i in range(3)],
            "coordinate_order": "raw PointCollections p order",
        }

    return {
        "role": role,
        "source": source,
        "sha256": sha256,
        "status": status,
        "collection_count": len(collections_report),
        "point_count": total_points,
        "annotated_point_count": annotated_points,
        "raw_coordinate_bounds": raw_bounds,
        "collections": collections_report,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "findings": findings,
    }


def audit_file(path: Path, *, role: str) -> dict[str, Any]:
    """Audit one winding document and retain exact file provenance."""
    if not path.is_file():
        return {
            "role": role,
            "source": str(path),
            "present": False,
            "status": "missing",
            "collection_count": 0,
            "point_count": 0,
            "annotated_point_count": 0,
            "error_count": 0,
            "warning_count": 0,
            "findings": [],
        }

    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    try:
        document = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {
            "role": role,
            "source": str(path),
            "present": True,
            "sha256": digest,
            "status": "fail",
            "collection_count": 0,
            "point_count": 0,
            "annotated_point_count": 0,
            "error_count": 1,
            "warning_count": 0,
            "findings": [
                {
                    "severity": "error",
                    "code": "WINDING_JSON_PARSE",
                    "path": "$",
                    "message": f"could not parse JSON: {exc}",
                }
            ],
        }

    report = audit_document(document, role=role, source=str(path), sha256=digest)
    report["present"] = True
    return report


def audit_dataset(
    dataset: Path,
    *,
    required_roles: Iterable[str] = (),
) -> dict[str, Any]:
    """Audit conventional spiral winding inputs under one dataset root."""
    dataset = Path(dataset)
    required = set(required_roles)
    unknown_required = required - set(ROLE_FILES)
    if unknown_required:
        raise ValueError(f"unsupported required roles: {sorted(unknown_required)}")

    documents = {
        role: audit_file(dataset / filename, role=role)
        for role, filename in ROLE_FILES.items()
    }
    missing_roles = [role for role, report in documents.items() if not report["present"]]
    present_roles = [role for role, report in documents.items() if report["present"]]

    findings: list[dict[str, str]] = []
    for role, report in documents.items():
        for item in report["findings"]:
            findings.append({**item, "path": f"{role}:{item['path']}"})
        if role in required and not report["present"]:
            _finding(
                findings,
                "error",
                "WINDING_REQUIRED_ROLE_MISSING",
                role,
                f"required winding input is missing: {ROLE_FILES[role]}",
            )

    errors = [item for item in findings if item["severity"] == "error"]
    warnings = [item for item in findings if item["severity"] == "warning"]
    if errors:
        status = "fail"
    elif missing_roles or warnings:
        status = "partial"
    else:
        status = "pass"

    return {
        "schema_version": SCHEMA_VERSION,
        "diagnostic": "winding-annotation-audit",
        "open_problem": OPEN_PROBLEM_URL,
        "dataset": str(dataset),
        "status": status,
        "present_roles": present_roles,
        "missing_roles": missing_roles,
        "required_roles": sorted(required),
        "totals": {
            "collections": sum(r["collection_count"] for r in documents.values()),
            "points": sum(r["point_count"] for r in documents.values()),
            "annotated_points": sum(
                r["annotated_point_count"] for r in documents.values()
            ),
        },
        "error_count": len(errors),
        "warning_count": len(warnings),
        "documents": documents,
        "findings": findings,
        "limitation": (
            "This audit checks PointCollections structure, role semantics, numeric sanity, "
            "and file provenance only. It does not establish CT support, patch attachment, "
            "graph consistency, or held-out spiral-fit accuracy."
        ),
    }


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Audit VC3D/spiral-fitting winding annotation inputs"
    )
    ap.add_argument("--dataset", required=True, help="spiral dataset root")
    ap.add_argument(
        "--require-role",
        action="append",
        choices=tuple(ROLE_FILES),
        default=[],
        help="fail when this conventional winding role is absent; repeatable",
    )
    ap.add_argument("--out", help="optional JSON report path")
    ap.add_argument(
        "--format",
        choices=("text", "json", "github"),
        default="text",
    )
    args = ap.parse_args()

    report = audit_dataset(Path(args.dataset), required_roles=args.require_role)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if args.format == "json":
        print(json.dumps(report, indent=2))
    elif args.format == "github":
        for item in report["findings"]:
            command = "error" if item["severity"] == "error" else "warning"
            print(f"::{command} title={item['code']}::{item['path']}: {item['message']}")
        print(
            f"Winding annotation audit: {report['status'].upper()} "
            f"({report['totals']['collections']} collections, {report['totals']['points']} points)"
        )
    else:
        print(f"Winding annotation audit: {report['status'].upper()}")
        print(
            f"collections={report['totals']['collections']} "
            f"points={report['totals']['points']} "
            f"annotated={report['totals']['annotated_points']}"
        )
        for role in ROLE_FILES:
            doc = report["documents"][role]
            digest = doc.get("sha256", "")
            digest_suffix = f" sha256={digest[:12]}..." if digest else ""
            print(
                f"- {role}: {doc['status']} "
                f"collections={doc['collection_count']} points={doc['point_count']}"
                f"{digest_suffix}"
            )
        for item in report["findings"]:
            print(
                f"- {item['severity'].upper()} {item['code']} "
                f"{item['path']}: {item['message']}"
            )

    raise SystemExit(1 if report["status"] == "fail" else 0)


if __name__ == "__main__":
    main()
