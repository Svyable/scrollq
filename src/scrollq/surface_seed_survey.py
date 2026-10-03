"""Deterministic remote seed-box survey for local papyrus surface growth.

This is campaign triage, not a surface or ink verdict. It samples bounded
prediction chunks inside a frozen z-range, measures how much predicted surface
is supported by non-zero masked CT, spatially thins the strongest boxes, and
optionally writes the selected CT cutouts for independent geometry diagnostics.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

SCHEMA_VERSION = 1
METHOD = "scrollq-surface-seed-survey-v1"


class SeedSurveyError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _spread_indices(size: int, count: int) -> list[int]:
    if size < 1:
        return []
    if count < 1:
        raise ValueError("sample count must be >= 1")
    if count >= size:
        return list(range(size))
    raw = np.linspace(0, size - 1, count)
    return sorted({int(round(v)) for v in raw})


def _grid_shape(shape: tuple[int, ...], chunks: tuple[int, ...]) -> tuple[int, ...]:
    return tuple((s + c - 1) // c for s, c in zip(shape, chunks))


def _chunk_bbox(level: Any, idx: tuple[int, int, int]) -> tuple[list[int], list[int]]:
    lo = [idx[d] * level.chunks[d] for d in range(3)]
    hi = [min(lo[d] + level.chunks[d], level.shape[d]) for d in range(3)]
    return lo, hi


def _candidate_bbox(
    pred: Any, idx: tuple[int, int, int], z0: int, z1: int
) -> tuple[list[int], list[int]] | None:
    lo, hi = _chunk_bbox(pred, idx)
    lo[0] = max(lo[0], z0)
    hi[0] = min(hi[0], z1)
    return (lo, hi) if all(lo[d] < hi[d] for d in range(3)) else None


def _crop_chunk(
    level: Any,
    idx: tuple[int, int, int],
    chunk: np.ndarray,
    lo: list[int],
    hi: list[int],
) -> np.ndarray:
    base = [idx[d] * level.chunks[d] for d in range(3)]
    sl = tuple(slice(lo[d] - base[d], hi[d] - base[d]) for d in range(3))
    return np.asarray(chunk)[sl]


def _read_bbox(
    level: Any,
    lo: list[int],
    hi: list[int],
    *,
    cache: dict[tuple[int, int, int], np.ndarray | None] | None = None,
) -> np.ndarray:
    if any(lo[d] < 0 or hi[d] > level.shape[d] or lo[d] >= hi[d] for d in range(3)):
        raise ValueError("bbox lies outside level shape or is empty")
    out = np.zeros(tuple(hi[d] - lo[d] for d in range(3)), dtype=np.uint8)
    starts = [lo[d] // level.chunks[d] for d in range(3)]
    stops = [(hi[d] - 1) // level.chunks[d] for d in range(3)]
    for cz in range(starts[0], stops[0] + 1):
        for cy in range(starts[1], stops[1] + 1):
            for cx in range(starts[2], stops[2] + 1):
                idx = (cz, cy, cx)
                if cache is not None and idx in cache:
                    chunk = cache[idx]
                else:
                    chunk = level.chunk(idx)
                    if cache is not None:
                        cache[idx] = chunk
                if chunk is None:
                    continue
                c_lo, c_hi = _chunk_bbox(level, idx)
                i_lo = [max(lo[d], c_lo[d]) for d in range(3)]
                i_hi = [min(hi[d], c_hi[d]) for d in range(3)]
                if any(i_lo[d] >= i_hi[d] for d in range(3)):
                    continue
                src = tuple(
                    slice(i_lo[d] - c_lo[d], i_hi[d] - c_lo[d])
                    for d in range(3)
                )
                dst = tuple(
                    slice(i_lo[d] - lo[d], i_hi[d] - lo[d])
                    for d in range(3)
                )
                out[dst] = np.asarray(chunk)[src]
    return out


def _prediction_box(
    pred: Any,
    idx: tuple[int, int, int],
    lo: list[int],
    hi: list[int],
) -> np.ndarray | None:
    chunk = pred.chunk(idx)
    if chunk is None:
        return None
    return _crop_chunk(pred, idx, chunk, lo, hi)


def _thin_spatially(
    rows: list[dict[str, Any]], *, top_k: int, min_chunk_distance: int
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for row in rows:
        pz, py, px = row["prediction_chunk_zyx"]
        too_close = False
        for kept in selected:
            kz, ky, kx = kept["prediction_chunk_zyx"]
            if pz == kz and max(abs(py - ky), abs(px - kx)) <= min_chunk_distance:
                too_close = True
                break
        if too_close:
            continue
        selected.append(row)
        if len(selected) >= top_k:
            break
    return selected


def survey_seed_boxes(
    pred: Any,
    ct: Any,
    *,
    z0: int,
    z1: int,
    per_dim: int = 12,
    prefilter: int = 0,
    top_k: int = 12,
    min_chunk_distance: int = 1,
    threshold: int = 127,
) -> dict[str, Any]:
    """Survey a deterministic coarse grid and return evidence-ranked seed boxes."""
    if tuple(pred.shape) != tuple(ct.shape):
        raise SeedSurveyError(f"prediction shape {pred.shape} != CT shape {ct.shape}")
    if len(pred.shape) != 3 or len(pred.chunks) != 3 or len(ct.chunks) != 3:
        raise SeedSurveyError("prediction and CT must be 3-D")
    if not (0 <= z0 < z1 <= pred.shape[0]):
        raise SeedSurveyError(
            "z range must be a non-empty half-open interval inside the volume"
        )
    if per_dim < 1 or prefilter < 0 or top_k < 1:
        raise SeedSurveyError(
            "per_dim and top_k must be >= 1; prefilter must be >= 0"
        )
    if min_chunk_distance < 0:
        raise SeedSurveyError("min_chunk_distance must be >= 0")
    if not (0 <= threshold <= 255):
        raise SeedSurveyError("threshold must be in [0,255]")

    grid = _grid_shape(tuple(pred.shape), tuple(pred.chunks))
    pz0 = z0 // pred.chunks[0]
    pz1 = (z1 - 1) // pred.chunks[0]
    ys = _spread_indices(grid[1], per_dim)
    xs = _spread_indices(grid[2], per_dim)

    phase1: list[dict[str, Any]] = []
    positive_masks: dict[tuple[int, int, int], np.ndarray] = {}
    prediction_reads = 0
    for pz in range(pz0, pz1 + 1):
        for py in ys:
            for px in xs:
                idx = (pz, py, px)
                bbox = _candidate_bbox(pred, idx, z0, z1)
                if bbox is None:
                    continue
                lo, hi = bbox
                pbox = _prediction_box(pred, idx, lo, hi)
                prediction_reads += 1
                if pbox is None:
                    continue
                pos = pbox > threshold
                positives = int(pos.sum())
                if positives == 0:
                    continue
                positive_masks[idx] = pos
                phase1.append(
                    {
                        "prediction_chunk_zyx": list(idx),
                        "bbox_zyx_half_open": [lo, hi],
                        "prediction_positive_voxels": positives,
                        "prediction_positive_fraction": float(
                            positives / pos.size
                        ),
                    }
                )

    phase1.sort(
        key=lambda row: (
            -row["prediction_positive_voxels"],
            tuple(row["prediction_chunk_zyx"]),
        )
    )
    measured = (
        phase1 if prefilter == 0
        else phase1[: min(prefilter, len(phase1))]
    )
    ct_chunk_reads = 0

    for row in measured:
        idx = tuple(row["prediction_chunk_zyx"])
        lo, hi = row["bbox_zyx_half_open"]
        pos = positive_masks[idx]
        row_cache: dict[tuple[int, int, int], np.ndarray | None] = {}
        ctbox = _read_bbox(ct, lo, hi, cache=row_cache)
        ct_chunk_reads += len(row_cache)
        positives = int(pos.sum())
        phantom = int((pos & (ctbox == 0)).sum())
        row.update(
            {
                "measurement_status": "measured",
                "phantom_voxels": phantom,
                "surface_support_frac": float(1.0 - phantom / positives),
                "ct_nonzero_fraction": float(
                    np.count_nonzero(ctbox) / ctbox.size
                ),
                "cutout_voxels": int(ctbox.size),
            }
        )

    ranked = [
        row for row in measured
        if row.get("measurement_status") == "measured"
    ]
    ranked.sort(
        key=lambda row: (
            -row["surface_support_frac"],
            -row["prediction_positive_voxels"],
            tuple(row["prediction_chunk_zyx"]),
        )
    )
    selected = _thin_spatially(
        ranked, top_k=top_k, min_chunk_distance=min_chunk_distance
    )
    for rank, row in enumerate(selected, start=1):
        row["rank"] = rank
        row["requires_surface_seating"] = True
        row["requires_sheetness_or_equivalent_geometry_check"] = True

    return {
        "schema_version": SCHEMA_VERSION,
        "method": METHOD,
        "status": "ok" if selected else "no-seeds",
        "volume_shape_zyx": list(pred.shape),
        "prediction_chunk_shape_zyx": list(pred.chunks),
        "ct_chunk_shape_zyx": list(ct.chunks),
        "z_half_open": [z0, z1],
        "threshold": threshold,
        "sampling": {
            "per_dim": per_dim,
            "prediction_chunks_considered": (
                (pz1 - pz0 + 1) * len(ys) * len(xs)
            ),
            "prediction_chunks_with_surface": len(phase1),
            "prefilter_requested": prefilter,
            "prefilter_mode": (
                "all-nonempty" if prefilter == 0 else "top-positive-count"
            ),
            "ct_supported_boxes_measured": len(ranked),
            "top_k": top_k,
            "min_chunk_distance": min_chunk_distance,
            "prediction_chunk_reads": prediction_reads,
            "ct_chunk_reads": ct_chunk_reads,
            "peak_ct_chunk_cache_scope": "one measured box",
        },
        "ranking_rule": (
            "phase 1 prefilter by prediction-positive voxels; phase 2 rank by local "
            "CT support, then positive voxels, then prediction chunk coordinate; "
            "greedy Chebyshev spatial thinning in y/x"
        ),
        "selected": selected,
        "measured": ranked,
        "claim_boundary": (
            "A selected box is only a deterministic place to attempt local surface "
            "growth. CT support does not establish sheet identity, winding identity, "
            "recto/verso, ink, or readability."
        ),
    }


def write_selected_cutouts(
    report: dict[str, Any],
    pred: Any,
    ct: Any,
    out_dir: Path,
    *,
    threshold: int = 127,
) -> None:
    """Write exact selected CT cutouts and binary prediction masks with hashes."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for row in report.get("selected", []):
        rank = int(row["rank"])
        idx = tuple(row["prediction_chunk_zyx"])
        lo, hi = row["bbox_zyx_half_open"]
        ctbox = _read_bbox(ct, lo, hi, cache={})
        pbox = _prediction_box(pred, idx, lo, hi)
        if pbox is None:
            raise SeedSurveyError(
                f"selected prediction chunk disappeared: {idx}"
            )
        mask = np.asarray(pbox > threshold, dtype=np.uint8)
        stem = (
            f"seed-{rank:02d}-z{lo[0]}-{hi[0]}"
            f"-y{lo[1]}-{hi[1]}-x{lo[2]}-{hi[2]}"
        )
        ct_path = out_dir / f"{stem}.ct.npy"
        mask_path = out_dir / f"{stem}.surface-mask.npy"
        np.save(ct_path, ctbox, allow_pickle=False)
        np.save(mask_path, mask, allow_pickle=False)
        row["cutouts"] = {
            "ct": {
                "path": str(ct_path),
                "sha256": _sha256_file(ct_path),
            },
            "surface_mask": {
                "path": str(mask_path),
                "sha256": _sha256_file(mask_path),
            },
        }


def _parse_z_range(value: str) -> tuple[int, int]:
    try:
        parts = [int(v.strip()) for v in value.split(",")]
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "z range must be z0,z1 integers"
        ) from exc
    if len(parts) != 2 or parts[0] < 0 or parts[0] >= parts[1]:
        raise argparse.ArgumentTypeError(
            "z range must be increasing half-open z0,z1"
        )
    return parts[0], parts[1]


def _volume_guard(
    pred_url: str, ct_url: str, volume_id: str | None
) -> None:
    if not volume_id:
        return
    if f"/{volume_id}-" not in ct_url:
        raise SeedSurveyError(
            f"CT URL does not name expected volume {volume_id}"
        )
    if f"/{volume_id}-surface-" not in pred_url:
        raise SeedSurveyError(
            f"prediction URL does not name expected volume {volume_id}"
        )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Rank deterministic local surface-growth seed boxes inside a frozen "
            "z-range. Selected CT cutouts are suitable for scroliq-sheetness; "
            "this command makes no ink claim."
        )
    )
    ap.add_argument(
        "--pred-url",
        required=True,
        help="surface-prediction Zarr root (without /0)",
    )
    ap.add_argument(
        "--ct-url",
        required=True,
        help="exact masked-CT Zarr root (without /0)",
    )
    ap.add_argument("--expected-volume-id")
    ap.add_argument(
        "--z-range",
        type=_parse_z_range,
        required=True,
        help="half-open z0,z1",
    )
    ap.add_argument("--per-dim", type=int, default=12)
    ap.add_argument(
        "--prefilter",
        type=int,
        default=0,
        help="0 = measure CT support for every nonempty sampled box",
    )
    ap.add_argument("--top-k", type=int, default=12)
    ap.add_argument("--min-chunk-distance", type=int, default=1)
    ap.add_argument("--threshold", type=int, default=127)
    ap.add_argument(
        "--cutout-dir",
        help="write selected CT + surface-mask .npy cutouts",
    )
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    _volume_guard(args.pred_url, args.ct_url, args.expected_volume_id)
    from .support import ZarrV2Level
    import requests

    session = requests.Session()
    pred = ZarrV2Level(f"{args.pred_url.rstrip('/')}/0", session)
    ct = ZarrV2Level(f"{args.ct_url.rstrip('/')}/0", session)
    z0, z1 = args.z_range
    report = survey_seed_boxes(
        pred,
        ct,
        z0=z0,
        z1=z1,
        per_dim=args.per_dim,
        prefilter=args.prefilter,
        top_k=args.top_k,
        min_chunk_distance=args.min_chunk_distance,
        threshold=args.threshold,
    )
    report["source"] = {
        "prediction_url": args.pred_url,
        "ct_url": args.ct_url,
        "expected_volume_id": args.expected_volume_id,
    }
    if args.cutout_dir:
        write_selected_cutouts(
            report,
            pred,
            ct,
            Path(args.cutout_dir),
            threshold=args.threshold,
        )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
