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
from statistics import median
from typing import Any, Iterable

from . import winding_geometry

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

        total_points += len(raw_points)
        winding_values: list[int] = []
        point_rows: list[tuple[int, int | None]] = []
        collection_coords: list[list[float]] = []
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
                xyz = [float(value) for value in coords]
                all_coords.append(xyz)
                collection_coords.append(xyz)

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

        geometry: dict[str, Any] = {
            "valid_coordinate_points": len(collection_coords),
            "xyz_bounds": None,
            "z_range": None,
            "median_z": None,
        }
        if collection_coords:
            geometry.update(
                {
                    "xyz_bounds": {
                        "min": [
                            min(point[i] for point in collection_coords)
                            for i in range(3)
                        ],
                        "max": [
                            max(point[i] for point in collection_coords)
                            for i in range(3)
                        ],
                    },
                    "z_range": [
                        min(point[2] for point in collection_coords),
                        max(point[2] for point in collection_coords),
                    ],
                    "median_z": float(
                        median(point[2] for point in collection_coords)
                    ),
                }
            )

        collections_report.append(
            {
                "id": collection_id,
                "source_id": str(collection_key),
                "name": name if isinstance(name, str) else None,
                "points": len(raw_points),
                "annotated_points": len(winding_values),
                "geometry": geometry,
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
            "coordinate_order": "xyz (VC3D PointCollections p)",
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



def summarize_axial_coverage(
    documents: dict[str, dict[str, Any]],
    *,
    z_range: tuple[float, float] | None = None,
    bins: int = 12,
) -> dict[str, Any]:
    """Summarize annotation-center coverage along the scroll axis.

    Each collection contributes one value: the median z of its valid XYZ points.
    Counting collections instead of raw points prevents a densely sampled path from
    masquerading as broader annotation coverage.
    """
    if bins < 1:
        raise ValueError("z bins must be >= 1")
    if z_range is not None:
        start, stop = (float(z_range[0]), float(z_range[1]))
        if not math.isfinite(start) or not math.isfinite(stop) or stop <= start:
            raise ValueError("z_range requires finite start < stop")
        z_range = (start, stop)

    by_role: dict[str, list[float]] = {role: [] for role in ROLE_FILES}
    centers: list[dict[str, Any]] = []
    for role in ROLE_FILES:
        document = documents.get(role) or {}
        for collection in document.get("collections") or []:
            geometry = collection.get("geometry") or {}
            value = geometry.get("median_z")
            if not _is_finite_number(value):
                continue
            z = float(value)
            by_role[role].append(z)
            centers.append(
                {
                    "role": role,
                    "collection_id": collection.get("id"),
                    "source_id": collection.get("source_id"),
                    "name": collection.get("name"),
                    "median_z": z,
                }
            )

    ordered_z = sorted(item["median_z"] for item in centers)
    largest_gap = None
    if len(ordered_z) >= 2:
        left, right = max(
            zip(ordered_z, ordered_z[1:]),
            key=lambda pair: (pair[1] - pair[0], -pair[0]),
        )
        largest_gap = {
            "gap_slices": right - left,
            "between_median_z": [left, right],
        }

    report: dict[str, Any] = {
        "measure": "collection-median-z coverage proxy",
        "coordinate_order": "xyz (VC3D PointCollections p)",
        "collection_centers": len(centers),
        "observed_z_range": [min(ordered_z), max(ordered_z)] if ordered_z else None,
        "largest_collection_center_gap": largest_gap,
        "by_role": {
            role: {
                "collection_centers": len(values),
                "observed_z_range": [min(values), max(values)] if values else None,
            }
            for role, values in by_role.items()
        },
        "fit_window": None,
        "limitation": (
            "Coverage counts one median-z center per collection. It is an axial "
            "annotation-density proxy, not proof that a winding or surface is "
            "geometrically constrained throughout a bin."
        ),
    }

    if z_range is None:
        return report

    start, stop = z_range
    width = (stop - start) / bins
    counts = [0 for _ in range(bins)]
    outside = 0
    for item in centers:
        z = item["median_z"]
        if z < start or z > stop:
            outside += 1
            continue
        index = bins - 1 if z == stop else int((z - start) / width)
        index = max(0, min(index, bins - 1))
        counts[index] += 1

    bin_rows = []
    empty_bins = []
    for index, count in enumerate(counts):
        lo = start + index * width
        hi = start + (index + 1) * width
        if count == 0:
            empty_bins.append(index)
        bin_rows.append(
            {
                "index": index,
                "z_interval": [lo, hi],
                "right_closed": index == bins - 1,
                "collection_centers": count,
            }
        )

    nonempty = bins - len(empty_bins)
    report["fit_window"] = {
        "z_range": [start, stop],
        "bins": bins,
        "bin_width_slices": width,
        "collection_centers_inside": sum(counts),
        "collection_centers_outside": outside,
        "nonempty_bins": nonempty,
        "empty_bins": empty_bins,
        "nonempty_bin_fraction": nonempty / bins,
        "bin_counts": bin_rows,
    }
    return report

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
    z_range: tuple[float, float] | None = None,
    z_bins: int = 12,
    volume_root: str | None = None,
    umbilicus: Path | None = None,
    ray_order_options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Audit conventional spiral winding inputs under one dataset root.

    ``umbilicus`` defaults to ``<dataset>/umbilicus.json`` when that file
    exists; when available, the report gains an umbilicus ray-order section.
    """
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

    ray_order = _ray_order_section(
        dataset, documents, umbilicus, ray_order_options or {}
    )
    if ray_order.get("status") == "invalid-umbilicus":
        _finding(
            findings,
            "error",
            "WINDING_UMBILICUS_INVALID",
            "umbilicus",
            ray_order["reason"],
        )
    elif ray_order.get("inversion_candidates"):
        _finding(
            findings,
            "warning",
            "WINDING_RAY_ORDER_CANDIDATES",
            "ray_order",
            f"{ray_order['inversion_candidates']} of {ray_order['comparable_pairs']} "
            "comparable annotation pairs are out of radial order around the "
            "umbilicus; review the ranked queue",
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
        "volume_root": volume_root,
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
        "axial_coverage": summarize_axial_coverage(
            documents, z_range=z_range, bins=z_bins
        ),
        "ray_order": ray_order,
        "findings": findings,
        "limitation": (
            "This audit checks PointCollections structure, role semantics, numeric sanity, "
            "file provenance, and (with an umbilicus) radial-order review candidates. It "
            "does not establish CT support, patch attachment, graph consistency, or "
            "held-out spiral-fit accuracy."
        ),
    }


def _ray_order_section(
    dataset: Path,
    documents: dict[str, dict[str, Any]],
    umbilicus: Path | None,
    options: dict[str, Any],
) -> dict[str, Any]:
    explicit = umbilicus is not None
    path = Path(umbilicus) if explicit else dataset / "umbilicus.json"
    if not path.is_file():
        if explicit:
            return {
                "diagnostic": winding_geometry.DIAGNOSTIC,
                "status": "invalid-umbilicus",
                "reason": f"umbilicus file not found: {path}",
            }
        return {
            "diagnostic": winding_geometry.DIAGNOSTIC,
            "status": "not-evaluated",
            "reason": "no umbilicus.json in the dataset and none supplied",
        }
    try:
        axis = winding_geometry.load_umbilicus(path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        return {
            "diagnostic": winding_geometry.DIAGNOSTIC,
            "status": "invalid-umbilicus",
            "reason": f"could not use umbilicus {path}: {exc}",
        }

    parsed: dict[str, Any] = {}
    inputs: dict[str, str | None] = {}
    for role in ("absolute", "relative"):
        report = documents[role]
        if report.get("status") in {"missing", "fail"}:
            # Failed documents are already blocking; do not reason about them.
            inputs[role] = None
            continue
        raw = (dataset / ROLE_FILES[role]).read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != report.get("sha256"):
            raise RuntimeError(f"{ROLE_FILES[role]} changed during the audit")
        parsed[role] = json.loads(raw)
        inputs[role] = digest
    section = winding_geometry.check_ray_order(parsed, axis, **options)
    section["inputs_sha256"] = inputs
    return section


def _parse_z_range(value: str) -> tuple[float, float]:
    try:
        fields = [float(part.strip()) for part in value.split(",")]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("z range must be BEGIN,END") from exc
    if (
        len(fields) != 2
        or not all(math.isfinite(field) for field in fields)
        or fields[1] <= fields[0]
    ):
        raise argparse.ArgumentTypeError("z range requires finite BEGIN < END")
    return fields[0], fields[1]


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
    ap.add_argument(
        "--volume-root",
        help=(
            "optional exact ScrolIQ/CT volume root binding; required when this "
            "artifact will be attached to a ScrolIQ passport"
        ),
    )
    ap.add_argument(
        "--z-range",
        type=_parse_z_range,
        help="optional fit/evaluation axial window as BEGIN,END in L0 voxel z",
    )
    ap.add_argument(
        "--z-bins",
        type=int,
        default=12,
        help="number of equal-width axial coverage bins inside --z-range (default: 12)",
    )
    ap.add_argument(
        "--umbilicus",
        help=(
            "umbilicus.json (control_points x/y/z) for the ray-order check; "
            "defaults to <dataset>/umbilicus.json when present"
        ),
    )
    ap.add_argument(
        "--ray-sector-degrees",
        type=float,
        default=winding_geometry.DEFAULT_SECTOR_DEGREES,
        help="max angular separation around the umbilicus for a comparable pair",
    )
    ap.add_argument(
        "--ray-z-tolerance",
        type=float,
        default=winding_geometry.DEFAULT_Z_TOLERANCE,
        help="max |dz| in L0 voxels for a comparable pair",
    )
    ap.add_argument(
        "--ray-min-winding-gap",
        type=int,
        default=winding_geometry.DEFAULT_MIN_WINDING_GAP,
        help="min winding difference for a comparable pair (>= 2)",
    )
    ap.add_argument(
        "--ray-radial-margin",
        type=float,
        default=winding_geometry.DEFAULT_RADIAL_MARGIN,
        help="inversions smaller than this many voxels are ignored",
    )
    ap.add_argument("--out", help="optional JSON report path")
    ap.add_argument(
        "--format",
        choices=("text", "json", "github"),
        default="text",
    )
    args = ap.parse_args()

    if args.z_bins < 1:
        ap.error("--z-bins must be >= 1")
    if not 0 < args.ray_sector_degrees < 180:
        ap.error("--ray-sector-degrees must be in (0, 180)")
    if args.ray_min_winding_gap < 2:
        ap.error("--ray-min-winding-gap must be >= 2")
    if not args.ray_z_tolerance >= 0 or not args.ray_radial_margin >= 0:
        ap.error("--ray-z-tolerance and --ray-radial-margin must be >= 0")
    report = audit_dataset(
        Path(args.dataset),
        required_roles=args.require_role,
        z_range=args.z_range,
        z_bins=args.z_bins,
        volume_root=args.volume_root,
        umbilicus=Path(args.umbilicus) if args.umbilicus else None,
        ray_order_options={
            "sector_degrees": args.ray_sector_degrees,
            "z_tolerance": args.ray_z_tolerance,
            "min_winding_gap": args.ray_min_winding_gap,
            "radial_margin": args.ray_radial_margin,
        },
    )
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
        coverage = report["axial_coverage"]
        gap = coverage.get("largest_collection_center_gap")
        if gap:
            print(
                "axial collection-center gap="
                f"{gap['gap_slices']:.1f} slices between "
                f"{gap['between_median_z'][0]:.1f} and "
                f"{gap['between_median_z'][1]:.1f}"
            )
        fit_window = coverage.get("fit_window")
        if fit_window:
            print(
                "axial fit-window bins="
                f"{fit_window['nonempty_bins']}/{fit_window['bins']} nonempty; "
                f"empty={fit_window['empty_bins']}"
            )
        ray = report["ray_order"]
        if ray.get("comparable_pairs") is not None:
            print(
                f"umbilicus ray order: {ray['status']} "
                f"inversions={ray['inversion_candidates']}/{ray['comparable_pairs']} "
                "comparable pairs"
            )
            for item in ray["review_queue"][:5]:
                print(
                    f"  review {item['role']} collection={item['collection_id']} "
                    f"point={item['point_id']} wind_a={item['wind_a']} "
                    f"xyz={[round(v, 1) for v in item['xyz']]} "
                    f"inversions={item['inversion_pairs']}/{item['comparable_pairs']}"
                )
        else:
            print(f"umbilicus ray order: {ray['status']} ({ray.get('reason', '')})")
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
