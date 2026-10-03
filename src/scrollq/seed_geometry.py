"""Choose deterministic growth seeds from CT sheetness evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

SCHEMA_VERSION = 1
METHOD = "scrollq-sheetness-seed-point-v1"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _load(path: Path) -> np.ndarray:
    if path.suffix.lower() != ".npy":
        raise ValueError("seed-geometry inputs must be .npy arrays")
    return np.load(path, allow_pickle=False)


def _summary(values: np.ndarray) -> dict[str, float]:
    if values.size == 0:
        raise ValueError("cannot summarize an empty set")
    return {
        "mean": float(np.mean(values)),
        "p50": float(np.quantile(values, 0.50)),
        "p90": float(np.quantile(values, 0.90)),
        "p99": float(np.quantile(values, 0.99)),
        "max": float(np.max(values)),
    }


def _normalize_vector(value: np.ndarray) -> list[float] | None:
    vec = np.asarray(value, dtype=np.float64)
    if vec.shape != (3,) or not np.isfinite(vec).all():
        return None
    norm = float(np.linalg.norm(vec))
    if norm <= 0:
        return None
    return [float(v) for v in vec / norm]


def analyze(
    surface_mask: np.ndarray,
    response: np.ndarray,
    normals: np.ndarray,
    *,
    bbox_origin_zyx: tuple[int, int, int],
    candidate_quantile: float = 0.99,
) -> dict[str, Any]:
    mask = np.asarray(surface_mask) > 0
    score = np.asarray(response, dtype=np.float64)
    normal = np.asarray(normals)

    if mask.ndim != 3 or score.ndim != 3:
        raise ValueError("surface mask and sheetness response must be 3-D")
    if mask.shape != score.shape:
        raise ValueError("surface mask and sheetness response shapes differ")
    if normal.shape != score.shape + (3,):
        raise ValueError("normal array must have response.shape + (3,)")
    if not (0.0 <= candidate_quantile <= 1.0):
        raise ValueError("candidate_quantile must be in [0,1]")
    if any(type(v) is not int for v in bbox_origin_zyx):
        raise ValueError("bbox origin must be integer ZYX")

    finite = np.isfinite(score)
    valid = mask & finite
    if not np.any(valid):
        raise ValueError("surface mask has no finite sheetness samples")

    on = score[valid]
    off = score[(~mask) & finite]
    q = float(np.quantile(on, candidate_quantile))
    candidates = np.argwhere(valid & (score >= q))
    if candidates.size == 0:
        raise ValueError("no candidate survives the sheetness quantile")

    center = (np.asarray(score.shape, dtype=np.float64) - 1.0) / 2.0
    distances = np.sum(
        (candidates.astype(np.float64) - center) ** 2, axis=1
    )
    candidate_scores = score[tuple(candidates.T)]
    order = sorted(
        range(candidates.shape[0]),
        key=lambda i: (
            float(distances[i]),
            -float(candidate_scores[i]),
            int(candidates[i, 0]),
            int(candidates[i, 1]),
            int(candidates[i, 2]),
        ),
    )
    local = tuple(int(v) for v in candidates[order[0]])
    global_coord = [
        int(bbox_origin_zyx[d] + local[d]) for d in range(3)
    ]

    on_summary = _summary(on)
    off_summary = _summary(off) if off.size else None
    selected_normal = _normalize_vector(normal[local])

    return {
        "schema_version": SCHEMA_VERSION,
        "method": METHOD,
        "status": "measured",
        "candidate_quantile": float(candidate_quantile),
        "surface_mask_voxels": int(np.count_nonzero(mask)),
        "finite_surface_mask_voxels": int(np.count_nonzero(valid)),
        "surface_mask_fraction": float(np.mean(mask)),
        "sheetness_on_surface_mask": on_summary,
        "sheetness_off_surface_mask": off_summary,
        "mean_sheetness_enrichment": (
            float(on_summary["mean"] - off_summary["mean"])
            if off_summary is not None
            else None
        ),
        "selected_seed": {
            "local_zyx": list(local),
            "global_zyx": global_coord,
            "sheetness": float(score[local]),
            "normal_zyx": selected_normal,
            "squared_distance_to_cutout_center": float(
                np.sum((np.asarray(local, dtype=float) - center) ** 2)
            ),
        },
        "claim_boundary": (
            "The selected point is a deterministic surface-growth/review seed "
            "where the released surface mask overlaps high CT sheetness. It does "
            "not establish correct winding, recto/verso, surface continuity, ink, "
            "or readability."
        ),
    }


def run(
    mask_path: str | Path,
    response_path: str | Path,
    normal_path: str | Path,
    *,
    bbox_origin_zyx: tuple[int, int, int],
    candidate_quantile: float = 0.99,
) -> dict[str, Any]:
    mask_path = Path(mask_path)
    response_path = Path(response_path)
    normal_path = Path(normal_path)
    result = analyze(
        _load(mask_path),
        _load(response_path),
        _load(normal_path),
        bbox_origin_zyx=bbox_origin_zyx,
        candidate_quantile=candidate_quantile,
    )
    result["inputs"] = {
        "surface_mask": {
            "path": str(mask_path),
            "sha256": _sha256(mask_path),
        },
        "sheetness": {
            "path": str(response_path),
            "sha256": _sha256(response_path),
        },
        "normal": {
            "path": str(normal_path),
            "sha256": _sha256(normal_path),
        },
        "bbox_origin_zyx": list(bbox_origin_zyx),
    }
    return result


def _parse_origin(value: str) -> tuple[int, int, int]:
    try:
        parts = tuple(int(v.strip()) for v in value.split(","))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "bbox origin must be z,y,x integers"
        ) from exc
    if len(parts) != 3:
        raise argparse.ArgumentTypeError(
            "bbox origin must be z,y,x integers"
        )
    return parts


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=(
            "Choose one deterministic local growth seed from a released surface "
            "mask and an independent CT sheetness field."
        )
    )
    ap.add_argument("--surface-mask", required=True)
    ap.add_argument("--sheetness", required=True)
    ap.add_argument("--normal", required=True)
    ap.add_argument(
        "--bbox-origin",
        type=_parse_origin,
        required=True,
        help="global z,y,x",
    )
    ap.add_argument("--candidate-quantile", type=float, default=0.99)
    ap.add_argument("--out", required=True)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run(
            args.surface_mask,
            args.sheetness,
            args.normal,
            bbox_origin_zyx=args.bbox_origin,
            candidate_quantile=args.candidate_quantile,
        )
    except (OSError, ValueError) as exc:
        raise SystemExit(f"scroliq-seed-geometry: {exc}") from exc
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
