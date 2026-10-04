"""Census of declared-vs-recomputed spatial metadata over TIFXYZ patch packs.

A published pack reported that many verified patches carry ``meta.json`` bounds
that no longer contain their own valid vertices (stale in Z by hundreds of
slices in the worst case). A bbox that misses its surface is not an upper
bound, so a spatial prefilter built on it silently discards real geometry.

This tool recomputes every patch's bounds from its decoded valid vertices,
compares them with the declared bbox, and counts how many vertices a filter on
the declared box would lose. It reproduces that kind of claim; it does not
assert any particular count. Run it where the data is reachable and commit the
result create-only.

Two lessons of this repository are built in:

* a census that inspected nothing is ``unverified``, never clean;
* every run first passes a synthetic positive control (a stale patch must be
  detected, an exact one must not), and a failed control fails the run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Sequence

import numpy as np
from PIL import Image

from .tifxyz_audit import (
    VALIDITY_RULES,
    compare_bbox,
    load_valid_vertices,
)

SCHEMA_VERSION = 1
TOOL = "scroliq-bbox-census"
DEFAULT_TOLERANCE_VOXELS = 1.0
_REQUIRED = ("meta.json", "x.tif", "y.tif", "z.tif")
_AXES = ("x", "y", "z")


class BBoxCensusError(ValueError):
    """Raised when the census is configured inconsistently."""


def find_patches(root: str | Path) -> list[Path]:
    """TIFXYZ patch directories at or below ``root``, sorted, symlinks not followed."""
    base = Path(root)
    if not base.is_dir():
        raise BBoxCensusError(f"census root is not a directory: {base}")
    found: list[Path] = []
    for current, dirs, files in os.walk(base, followlinks=False):
        dirs.sort()
        if all(name in files for name in _REQUIRED):
            found.append(Path(current))
    return sorted(found)


def census_patch(
    patch: str | Path,
    *,
    validity: str = "tifxyz",
    tolerance_voxels: float = DEFAULT_TOLERANCE_VOXELS,
) -> dict[str, Any]:
    """Classify one patch; never raises on bad data, only on bad arguments."""
    path = Path(patch)
    row: dict[str, Any] = {"patch": path.name, "path": str(path)}
    try:
        raw = (path / "meta.json").read_bytes()
        row["meta_sha256"] = hashlib.sha256(raw).hexdigest()
        meta = json.loads(raw)
    except (OSError, ValueError) as exc:
        return {**row, "status": "unreadable", "reason": f"meta.json: {exc}"}
    if not isinstance(meta, dict):
        return {**row, "status": "unreadable", "reason": "meta.json must contain an object"}
    try:
        xyz, valid, info = load_valid_vertices(path, validity=validity)
    except ValueError as exc:
        if str(exc).startswith("unknown vertex validity rule"):
            raise
        return {**row, "status": "unreadable", "reason": str(exc)}
    row["valid_vertices"] = info["valid_vertices"]
    if not info["valid_vertices"]:
        return {**row, "status": "empty", "reason": "no valid vertices under the validity rule"}

    pts = xyz[valid]
    observed = [pts.min(axis=0).tolist(), pts.max(axis=0).tolist()]
    comparison = compare_bbox(meta.get("bbox"), observed, tolerance_voxels=tolerance_voxels)
    row.update(
        {
            "status": comparison["status"],
            "observed_bbox_xyz": observed,
            "declared_bbox_xyz": comparison.get("metadata_bbox_xyz"),
            "stale_axes": comparison.get("stale_axes", []),
            "excess_voxels_xyz": comparison.get("excess_voxels_xyz"),
            "max_excess_voxels": comparison.get("max_excess_voxels"),
        }
    )
    if "reason" in comparison:
        row["reason"] = comparison["reason"]
    if comparison["status"] in ("stale", "consistent"):
        lo, hi = np.asarray(comparison["metadata_bbox_xyz"], dtype=np.float64)
        inside = ((pts >= lo - tolerance_voxels) & (pts <= hi + tolerance_voxels)).all(axis=1)
        lost = int((~inside).sum())
        row["vertices_outside_declared_bbox"] = lost
        row["fraction_outside_declared_bbox"] = float(lost / len(pts))
    return row


def _write_patch(
    root: Path,
    name: str,
    *,
    z0: float,
    bbox: list[list[float]] | None,
) -> None:
    patch = root / name
    patch.mkdir(parents=True)
    yy, xx = np.mgrid[0:4, 0:4]
    for fname, arr in (
        ("x.tif", (xx * 2).astype(np.float32)),
        ("y.tif", (yy * 2).astype(np.float32)),
        ("z.tif", np.full((4, 4), z0, dtype=np.float32)),
    ):
        Image.fromarray(arr).save(patch / fname)
    meta: dict[str, Any] = {"format": "tifxyz", "scale": [0.5, 0.5]}
    if bbox is not None:
        meta["bbox"] = bbox
    (patch / "meta.json").write_text(json.dumps(meta), encoding="utf-8")


def run_positive_control(
    *,
    validity: str = "tifxyz",
    tolerance_voxels: float = DEFAULT_TOLERANCE_VOXELS,
) -> dict[str, Any]:
    """Plant known stale/exact patches and require the census to separate them."""
    with tempfile.TemporaryDirectory(prefix="scroliq-bbox-control-") as tmp:
        root = Path(tmp)
        _write_patch(root, "exact", z0=100.0, bbox=[[0, 0, 100], [6, 6, 100]])
        _write_patch(root, "stale-z", z0=754.0, bbox=[[0, 0, 100], [6, 6, 100]])
        _write_patch(root, "stale-x", z0=100.0, bbox=[[50, 0, 100], [60, 6, 100]])
        _write_patch(root, "undeclared", z0=100.0, bbox=None)
        rows = {
            p.name: census_patch(p, validity=validity, tolerance_voxels=tolerance_voxels)
            for p in find_patches(root)
        }
    expected = {
        "exact": ("consistent", []),
        "stale-z": ("stale", ["z"]),
        "stale-x": ("stale", ["x"]),
        "undeclared": ("undeclared", []),
    }
    mismatches = {
        name: {"expected": want, "observed": (rows[name]["status"], rows[name].get("stale_axes"))}
        for name, want in expected.items()
        if name not in rows or (rows[name]["status"], rows[name].get("stale_axes", [])) != want
    }
    worst = rows.get("stale-z", {}).get("max_excess_voxels")
    return {
        "passed": not mismatches and worst == 654.0,
        "planted": len(expected),
        "mismatches": mismatches,
        "planted_worst_excess_voxels": 654.0,
        "detected_worst_excess_voxels": worst,
    }


def census(
    root: str | Path,
    *,
    validity: str = "tifxyz",
    tolerance_voxels: float = DEFAULT_TOLERANCE_VOXELS,
    workers: int = 4,
    include_all_rows: bool = False,
) -> dict[str, Any]:
    if validity not in VALIDITY_RULES:
        raise BBoxCensusError(f"validity must be one of {VALIDITY_RULES}")
    if not math.isfinite(tolerance_voxels) or tolerance_voxels < 0:
        raise BBoxCensusError("tolerance_voxels must be finite and >= 0")
    if type(workers) is not int or workers < 1:
        raise BBoxCensusError("workers must be an integer >= 1")

    control = run_positive_control(validity=validity, tolerance_voxels=tolerance_voxels)
    patches = find_patches(root)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        rows = list(
            pool.map(
                lambda p: census_patch(p, validity=validity, tolerance_voxels=tolerance_voxels),
                patches,
            )
        )

    by_status: dict[str, int] = {}
    for row in rows:
        by_status[row["status"]] = by_status.get(row["status"], 0) + 1
    stale = [r for r in rows if r["status"] == "stale"]
    axis_counts = {a: sum(1 for r in stale if a in r["stale_axes"]) for a in _AXES}
    worst = min(stale, key=lambda r: (-r["max_excess_voxels"], r["patch"]), default=None)
    lost = sum(r.get("vertices_outside_declared_bbox", 0) for r in stale)

    if not control["passed"]:
        verdict = "control-failed"
    elif not rows:
        verdict = "unverified"
    elif stale or by_status.get("unreadable") or by_status.get("empty"):
        verdict = "metadata-defects-present"
    else:
        verdict = "clean"

    summary = {
        "patches_inspected": len(rows),
        "by_status": dict(sorted(by_status.items())),
        "stale_patches": len(stale),
        "stale_axis_counts": axis_counts,
        "worst_excess_voxels": worst["max_excess_voxels"] if worst else None,
        "worst_patch": worst["patch"] if worst else None,
        "valid_vertices_outside_declared_bbox": lost,
    }
    reported = (
        rows
        if include_all_rows
        else [r for r in rows if r["status"] not in ("consistent", "undeclared")]
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "root": str(root),
        "validity_rule": validity,
        "tolerance_voxels": float(tolerance_voxels),
        "verdict": verdict,
        "summary": summary,
        "positive_control": control,
        "rows": reported,
        "rows_included": "all" if include_all_rows else "non-consistent only",
        "limitation": (
            "Counts depend on the vertex-validity rule and tolerance recorded here; "
            "compare them with a published count only under the same rule. A "
            "'clean' verdict covers bbox containment only, not surface correctness."
        ),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", required=True, help="directory holding TIFXYZ patch directories")
    parser.add_argument("--out", required=True, help="create-only JSON result")
    parser.add_argument(
        "--validity",
        choices=VALIDITY_RULES,
        default="tifxyz",
        help="vertex validity rule: 'tifxyz' (z > 0, the audit's rule) or "
        "'nonnegative-xyz' (every coordinate >= 0, the upstream spiral convention)",
    )
    parser.add_argument(
        "--tolerance-voxels",
        type=float,
        default=DEFAULT_TOLERANCE_VOXELS,
        help="voxels a declared bbox may miss vertices by before it is stale (default 1)",
    )
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--all-rows", action="store_true", help="also list consistent patches")
    parser.add_argument(
        "--fail-on-defects",
        action="store_true",
        help="exit 2 when any patch is stale, empty or unreadable",
    )
    args = parser.parse_args(argv)

    out = Path(args.out)
    if out.exists():
        parser.error(f"result already exists: {out}")
    try:
        result = census(
            args.root,
            validity=args.validity,
            tolerance_voxels=args.tolerance_voxels,
            workers=args.workers,
            include_all_rows=args.all_rows,
        )
    except BBoxCensusError as exc:
        parser.error(str(exc))
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, sort_keys=True, allow_nan=False)
        fh.write("\n")

    s = result["summary"]
    print(
        f"{result['verdict'].upper()} {args.root}: {s['patches_inspected']} patches, "
        f"{s['stale_patches']} stale (x={s['stale_axis_counts']['x']} "
        f"y={s['stale_axis_counts']['y']} z={s['stale_axis_counts']['z']}), "
        f"worst excess {s['worst_excess_voxels']} voxels"
    )
    if result["verdict"] in ("unverified", "control-failed"):
        return 2
    if args.fail_on_defects and result["verdict"] != "clean":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
