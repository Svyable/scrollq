"""Physical-evidence passport for proposed ink components.

For every connected ink component in a rendered prediction (and every
reviewer-selected letter region), emit one machine-readable record that ties
together:

* the exact submitted TIFXYZ surface (decoded-geometry digest) and the
  prediction file (SHA-256);
* the component's UV pixels, mapped to level-0 CT coordinates through the
  surface by a declared pixels-per-vertex factor;
* the model checkpoint hash;
* training-region exclusion, tested point by point against the provenance
  gate's ``level0-voxel-index`` region boxes;
* the raw ink score (summary only, never a verdict);
* an independent relief-support statistic when one is supplied, otherwise
  ``not-measured``.

The passport records evidence; it does not decide that a component is ink or
that a letter is legible. Missing evidence stays missing: a component without a
training-region declaration is ``unknown``, not ``clear``, and a component
without a relief field is ``not-measured``, not ``unsupported``.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Sequence

import numpy as np
from scipy.ndimage import binary_dilation, label as connected_components

from .ink_validation import SHA256_RE, _load_2d, _normalize_prediction, _sha256_file
from .provenance import _boxes_overlap, _validate_box
from .tifxyz_audit import geometry_digest, load_valid_vertices

SCHEMA_VERSION = 1
TOOL = "scroliq-ink-passport"
COORDINATE_SPACE = "level0-voxel-index"  # [z, y, x], as in scroliq-provenance
DEFAULT_MIN_COMPONENT_PIXELS = 16
RING_PIXELS = 3  # matched local background for the relief statistic

LIMITATION = (
    "A passport ties a proposed ink component to the exact mesh, CT coordinates, "
    "checkpoint and training-region exclusion it depends on. It does not decide "
    "that the component is ink or that a letter is legible, and a relief "
    "statistic is corroboration only when the relief field was computed without "
    "the ink prediction."
)


def _fail(message: str) -> None:
    raise ValueError(message)


def map_uv_to_ct(
    rows: np.ndarray,
    cols: np.ndarray,
    xyz: np.ndarray,
    valid: np.ndarray,
    pixels_per_vertex: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Bilinearly map prediction pixel centres to CT ``[z, y, x]``.

    Pixel centre ``p`` sits at grid coordinate ``(p + 0.5) / ppv - 0.5``.
    Centres within half a grid step outside the grid are clamped to its edge;
    anything further out is unmapped. A pixel maps only when all four
    surrounding vertices are valid; otherwise it is reported unmapped rather
    than extrapolated across a hole.
    """
    h, w = valid.shape
    gr = (rows + 0.5) / pixels_per_vertex - 0.5
    gc = (cols + 0.5) / pixels_per_vertex - 0.5
    inside = (gr >= -0.5) & (gr <= h - 0.5) & (gc >= -0.5) & (gc <= w - 0.5)
    out = np.full((rows.size, 3), np.nan)
    ok = np.zeros(rows.size, dtype=bool)
    if h < 2 or w < 2:
        return out, ok
    gr = np.clip(gr, 0.0, h - 1.0)
    gc = np.clip(gc, 0.0, w - 1.0)
    r0 = np.minimum(np.floor(gr).astype(np.int64), h - 2)
    c0 = np.minimum(np.floor(gc).astype(np.int64), w - 2)
    idx = np.flatnonzero(inside)
    if idx.size:
        a, b = r0[idx], c0[idx]
        corners_ok = valid[a, b] & valid[a + 1, b] & valid[a, b + 1] & valid[a + 1, b + 1]
        idx, a, b = idx[corners_ok], a[corners_ok], b[corners_ok]
        fr = (gr[idx] - a)[:, None]
        fc = (gc[idx] - b)[:, None]
        p = (xyz[a, b] * (1 - fr) * (1 - fc) + xyz[a + 1, b] * fr * (1 - fc)
             + xyz[a, b + 1] * (1 - fr) * fc + xyz[a + 1, b + 1] * fr * fc)
        out[idx] = p[:, ::-1]  # xyz -> zyx
        ok[idx] = True
    return out, ok


def load_training_regions(document: Any, volume_id: str) -> dict[str, Any]:
    """Validate training region sets in the scroliq-provenance format.

    Accepts one region set or ``{"region_sets": [...]}``. Only sets on the same
    exact volume are geometric constraints; others are recorded as
    other-volume and cannot overlap.
    """
    sets = document.get("region_sets") if isinstance(document, dict) and "region_sets" in document \
        else [document]
    if not isinstance(sets, list) or not sets:
        _fail("training regions must be a region set or {'region_sets': [...]}")
    boxes: list[dict[str, Any]] = []
    other_volume: list[str] = []
    for i, region_set in enumerate(sets):
        if not isinstance(region_set, dict):
            _fail(f"region_sets[{i}] must be an object")
        set_id = str(region_set.get("id", f"region_set_{i}"))
        if region_set.get("role") != "training":
            _fail(f"region set {set_id!r} must have role='training'")
        if region_set.get("volume_id") != volume_id:
            other_volume.append(set_id)
            continue
        if region_set.get("coordinate_space") != COORDINATE_SPACE:
            _fail(f"region set {set_id!r} must use coordinate_space={COORDINATE_SPACE!r}")
        errors: list[dict[str, str]] = []
        raw = region_set.get("boxes")
        if not isinstance(raw, list) or not raw:
            _fail(f"same-volume training region set {set_id!r} has no boxes")
        for j, box in enumerate(raw):
            parsed = _validate_box(box, f"{set_id}.boxes[{j}]", errors)
            if parsed is None:
                _fail("; ".join(e["message"] for e in errors) or f"invalid box {set_id}[{j}]")
            boxes.append({"region_set_id": set_id, "box_index": j, "box": parsed})
    return {"same_volume_boxes": boxes, "other_volume_region_sets": sorted(other_volume)}


def _exclusion(points: np.ndarray, unit_box, regions: dict[str, Any] | None) -> dict[str, Any]:
    if regions is None:
        return {"status": "unknown", "reason": "no training-region declaration supplied"}
    hits = []
    for entry in regions["same_volume_boxes"]:
        if unit_box is None or not _boxes_overlap(entry["box"], unit_box):
            continue
        start, stop = np.asarray(entry["box"][0]), np.asarray(entry["box"][1])
        inside = np.all((points >= start) & (points < stop), axis=1)
        if inside.any():
            hits.append({"region_set_id": entry["region_set_id"], "box_index": entry["box_index"],
                         "points_inside": int(inside.sum())})
    return {
        "status": "overlap" if hits else "clear",
        "overlaps": hits,
        "same_volume_boxes_checked": len(regions["same_volume_boxes"]),
        "other_volume_region_sets": regions["other_volume_region_sets"],
    }


def _relief(mask: np.ndarray, relief: np.ndarray | None) -> dict[str, Any]:
    if relief is None:
        return {"status": "not-measured"}
    ring = binary_dilation(mask, iterations=RING_PIXELS) & ~mask
    inner = relief[mask]
    outer = relief[ring]
    inner = inner[np.isfinite(inner)]
    outer = outer[np.isfinite(outer)]
    if not inner.size or not outer.size:
        return {"status": "not-measured", "reason": "no finite relief inside or around the unit"}
    pooled = math.sqrt((float(inner.var()) + float(outer.var())) / 2.0)
    delta = float(inner.mean() - outer.mean())
    return {
        "status": "measured",
        "mean_inside": float(inner.mean()),
        "mean_ring": float(outer.mean()),
        "delta": delta,
        "standardized_delta": delta / pooled if pooled > 0 else None,
        "n_inside": int(inner.size),
        "n_ring": int(outer.size),
        "ring_pixels": RING_PIXELS,
        "sign_convention": "inside minus matched ring; sign is reported, never assumed",
    }


def _unit_record(unit_id: str, kind: str, mask: np.ndarray, prediction: np.ndarray, xyz, valid,
                 ppv: float, regions, relief) -> dict[str, Any]:
    rows, cols = np.nonzero(mask)
    scores = prediction[rows, cols]
    ct, ok = map_uv_to_ct(rows, cols, xyz, valid, ppv)
    mapped = ct[ok]
    record: dict[str, Any] = {
        "id": unit_id,
        "kind": kind,
        "pixels": int(rows.size),
        "uv_bbox_px": [int(cols.min()), int(rows.min()), int(cols.max()) + 1, int(rows.max()) + 1],
        "uv_centroid_px": [float(cols.mean()), float(rows.mean())],
        "ink_score": {
            "mean": float(scores.mean()),
            "median": float(np.median(scores)),
            "max": float(scores.max()),
        },
        "ct": {"mapped_pixels": int(ok.sum()), "unmapped_pixels": int((~ok).sum())},
    }
    unit_box = None
    if mapped.size:
        lo = np.floor(mapped.min(axis=0))
        hi = np.floor(mapped.max(axis=0)) + 1
        unit_box = (tuple(map(float, lo)), tuple(map(float, hi)))
        record["ct"].update(
            centroid_zyx=[float(v) for v in mapped.mean(axis=0)],
            bbox_zyx={"start": [int(v) for v in lo], "stop": [int(v) for v in hi]},
        )
    record["training_exclusion"] = _exclusion(mapped, unit_box, regions)
    record["relief_support"] = _relief(mask, relief)
    gaps = []
    if not ok.all():
        gaps.append("ct-mapping-incomplete")
    if record["training_exclusion"]["status"] != "clear":
        gaps.append(f"training-exclusion-{record['training_exclusion']['status']}")
    if record["relief_support"]["status"] != "measured":
        gaps.append("relief-not-measured")
    record["evidence_gaps"] = gaps
    record["status"] = "complete" if not gaps else (
        "training-overlap" if record["training_exclusion"]["status"] == "overlap" else "incomplete")
    return record


def _regions(document: Any, shape: tuple[int, int]) -> list[tuple[str, np.ndarray]]:
    items = document.get("regions") if isinstance(document, dict) else None
    if not isinstance(items, list):
        _fail("reviewer regions must be {'regions': [{'id', 'bbox_px': [x0, y0, x1, y1]}]}")
    out = []
    seen = set()
    for i, item in enumerate(items):
        rid = item.get("id") if isinstance(item, dict) else None
        box = item.get("bbox_px") if isinstance(item, dict) else None
        if not isinstance(rid, str) or not rid or rid in seen:
            _fail(f"regions[{i}] needs a unique string id")
        if (not isinstance(box, list) or len(box) != 4
                or not all(isinstance(v, int) and not isinstance(v, bool) for v in box)):
            _fail(f"regions[{i}].bbox_px must be four integers [x0, y0, x1, y1]")
        x0, y0, x1, y1 = box
        if not (0 <= x0 < x1 <= shape[1] and 0 <= y0 < y1 <= shape[0]):
            _fail(f"regions[{i}].bbox_px is empty or outside the prediction")
        seen.add(rid)
        mask = np.zeros(shape, dtype=bool)
        mask[y0:y1, x0:x1] = True
        out.append((rid, mask))
    return out


def build_passport(
    *,
    prediction_path: str | Path,
    surface_path: str | Path,
    pixels_per_vertex: float,
    volume_id: str,
    checkpoint_sha256: str,
    threshold: float,
    model_id: str | None = None,
    prediction_scale: str = "auto",
    training_regions_path: str | Path | None = None,
    relief_path: str | Path | None = None,
    relief_producer: str | None = None,
    regions_path: str | Path | None = None,
    min_component_pixels: int = DEFAULT_MIN_COMPONENT_PIXELS,
) -> dict[str, Any]:
    if not SHA256_RE.fullmatch(checkpoint_sha256 or ""):
        _fail("checkpoint_sha256 must be 64 lowercase hex characters")
    if not volume_id:
        _fail("volume_id is required (the exact eligible volume)")
    if not (isinstance(pixels_per_vertex, (int, float)) and math.isfinite(pixels_per_vertex)
            and pixels_per_vertex > 0):
        _fail("pixels_per_vertex must be a positive number")
    if not 0.0 < threshold < 1.0:
        _fail("threshold must be in (0, 1) on the normalized prediction")
    if relief_path is not None and not relief_producer:
        _fail("a relief field needs --relief-producer naming how it was computed")

    prediction = _normalize_prediction(_load_2d(prediction_path), prediction_scale)
    xyz, valid, info = load_valid_vertices(surface_path)
    grid_h, grid_w = info["shape_yx"]
    expect = (grid_h * pixels_per_vertex, grid_w * pixels_per_vertex)
    if any(abs(got - want) > pixels_per_vertex for got, want in zip(prediction.shape, expect)):
        _fail(
            f"prediction shape {list(prediction.shape)} does not match surface grid "
            f"{info['shape_yx']} x {pixels_per_vertex} pixels per vertex")

    regions = None
    regions_sha = None
    if training_regions_path is not None:
        regions = load_training_regions(json.loads(Path(training_regions_path).read_text()),
                                        volume_id)
        regions_sha = _sha256_file(Path(training_regions_path))

    relief = None
    if relief_path is not None:
        relief = np.asarray(_load_2d(relief_path), dtype=np.float64)
        if relief.shape != prediction.shape:
            _fail(f"relief shape {list(relief.shape)} differs from prediction "
                  f"{list(prediction.shape)}")

    units: list[dict[str, Any]] = []
    labels, count = connected_components(prediction >= threshold, structure=np.ones((3, 3)))
    sizes = np.bincount(labels.ravel(), minlength=count + 1)
    kept = [k for k in range(1, count + 1) if sizes[k] >= min_component_pixels]
    for k in kept:
        units.append(_unit_record(f"component-{len(units) + 1:05d}", "component", labels == k,
                                  prediction, xyz, valid, pixels_per_vertex, regions, relief))
    reviewer_sha = None
    if regions_path is not None:
        reviewer_sha = _sha256_file(Path(regions_path))
        for rid, mask in _regions(json.loads(Path(regions_path).read_text()), prediction.shape):
            units.append(_unit_record(rid, "reviewer-region", mask, prediction, xyz, valid,
                                      pixels_per_vertex, regions, relief))

    statuses = {s: sum(1 for u in units if u["status"] == s)
                for s in ("complete", "incomplete", "training-overlap")}
    if not units:
        status = "unverified"  # nothing was inspected
    elif statuses["training-overlap"]:
        status = "training-overlap"
    elif statuses["incomplete"]:
        status = "incomplete"
    else:
        status = "complete"

    return {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "status": status,
        "volume_id": volume_id,
        "coordinate_space": COORDINATE_SPACE,
        "inputs": {
            "prediction": {"path": str(prediction_path), "sha256": _sha256_file(Path(prediction_path)),
                           "shape_yx": list(prediction.shape), "scale": prediction_scale},
            "surface": {"path": str(surface_path), **geometry_digest(surface_path)},
            "model": {"id": model_id, "checkpoint_sha256": checkpoint_sha256},
            "training_regions": None if regions is None else {
                "path": str(training_regions_path), "sha256": regions_sha,
                "same_volume_boxes": len(regions["same_volume_boxes"]),
                "other_volume_region_sets": regions["other_volume_region_sets"]},
            "relief": None if relief is None else {
                "path": str(relief_path), "sha256": _sha256_file(Path(relief_path)),
                "producer": relief_producer},
            "reviewer_regions": None if regions_path is None else {
                "path": str(regions_path), "sha256": reviewer_sha},
        },
        "parameters": {
            "pixels_per_vertex": pixels_per_vertex,
            "threshold": threshold,
            "connectivity": 8,
            "min_component_pixels": min_component_pixels,
            "uv_to_grid": ("(pixel + 0.5) / pixels_per_vertex - 0.5, clamped within half a step, "
                           "bilinear, all 4 corners valid"),
            "relief_ring_pixels": RING_PIXELS,
        },
        "components_found": int(count),
        "components_below_min_pixels": int(count - len(kept)),
        "units": units,
        "unit_status_counts": statuses,
        "limitation": LIMITATION,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--prediction", required=True, help="2D ink prediction (.tif/.png/.npy)")
    parser.add_argument("--prediction-scale", default="auto",
                        choices=("auto", "unit", "uint8", "uint16"))
    parser.add_argument("--threshold", type=float, required=True,
                        help="declared ink threshold on the normalized [0, 1] prediction")
    parser.add_argument("--surface", required=True, help="submitted TIFXYZ directory")
    parser.add_argument("--pixels-per-vertex", type=float, required=True,
                        help="prediction pixels per TIFXYZ grid step (checked against shapes)")
    parser.add_argument("--volume-id", required=True, help="exact eligible CT volume id")
    parser.add_argument("--checkpoint-sha256", required=True)
    parser.add_argument("--model-id")
    parser.add_argument("--training-regions",
                        help="training region set(s) in the scroliq-provenance format")
    parser.add_argument("--relief", help="independent relief-support field, same UV frame")
    parser.add_argument("--relief-producer", help="how the relief field was computed")
    parser.add_argument("--regions", help="reviewer letter regions {'regions': [...]} in pixels")
    parser.add_argument("--min-component-pixels", type=int, default=DEFAULT_MIN_COMPONENT_PIXELS)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    out = Path(args.out)
    if out.exists():
        parser.error(f"output already exists: {out}")
    try:
        passport = build_passport(
            prediction_path=args.prediction, surface_path=args.surface,
            pixels_per_vertex=args.pixels_per_vertex, volume_id=args.volume_id,
            checkpoint_sha256=args.checkpoint_sha256, threshold=args.threshold,
            model_id=args.model_id, prediction_scale=args.prediction_scale,
            training_regions_path=args.training_regions, relief_path=args.relief,
            relief_producer=args.relief_producer, regions_path=args.regions,
            min_component_pixels=args.min_component_pixels)
    except ValueError as exc:
        parser.error(str(exc))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(passport, indent=2, sort_keys=True) + "\n")
    print(f"{passport['status']}: {len(passport['units'])} unit(s), "
          f"{passport['unit_status_counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
